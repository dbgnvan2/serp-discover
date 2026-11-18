"""config_tab_models.py — the data side of the Configuration Manager tabs.

No tkinter here. Each tab keeps the data it loaded as its model and saves the
model plus what the user edited, instead of rebuilding the file from widget
contents. Rebuilding dropped every key that had no widget (the review's M1).

Spec: docs/plan_config_save_exit_codes_2026-11-14.md (A1-A8)
Tests: tests/test_config_manager_save.py
"""

import copy
import json
import os
import subprocess
import tempfile

import yaml

import db_connect
import http_retry
import report_llm
import timeouts
from yaml_io import save_yaml_preserving_comments


def positive_only_fields() -> set:
    """`(section, field)` pairs the loader refuses at zero or less.

    Read off the tables the loaders themselves drive — `http_retry`'s retry
    budgets and timeout paths, the keys `timeouts` governs, the SQLite lock
    wait `db_connect` names and the brief's wait and token limits
    `report_llm` names — so this is not a second list that can
    disagree with them (P32). The GUI is where
    these are edited, and until review chunk Y8 it offered a floor of 0 for
    all of them: the value saved, the loader reported it and used the
    documented default, and the report went to a log the GUI operator never
    reads (P2).
    """
    pairs = set()
    for section_name, keys in http_retry.BUDGET_SOURCES:
        for _, cfg_key, _ in keys:
            pairs.add((section_name, cfg_key))
    for section_name, cfg_key in http_retry.TIMEOUT_SOURCES.values():
        pairs.add((section_name, cfg_key))
    pairs.update(timeouts.GOVERNED_FIELDS)
    # Each loader that refuses a value at zero names its own keys, and this
    # reads them off the loader: `timeouts` cannot name the lock wait, because
    # `db_connect` imports `timeouts` for its validator, and `report_llm`'s
    # three were in no table at all — so the GUI saved a typed 0 for the
    # brief's wait and token limits after chunk Y8 had fixed the other nine
    # (review chunk Y11 and its cold review). A new refused key belongs in its
    # loader's own tuple, not appended here.
    pairs.add(db_connect.LOCK_TIMEOUT_SOURCE)
    pairs.update(report_llm.GOVERNED_FIELDS)
    return pairs


#: The directory the repo's editorial files live in. `BaseConfigTab` resolved
#: `file_name` against `os.getcwd()`, so the Configuration Manager edited
#: whatever directory it happened to be started from while every reader of
#: those files resolves against the module's own directory. Started anywhere
#: but the repo root — a Finder launch gives `/` — the tab for an existing
#: file showed empty, and saving created a brand-new file there and reported
#: success, while the run went on reading the real one. This is the class
#: review chunk Y12 fixed for the database and the config
#: (`db_connect.database_path`, `process_config.config_path`); chunk Y15 made
#: it worse by routing ten more files through it, and for a source tab a wrong
#: cwd is indistinguishable from a legitimately empty file (the cold review of
#: chunk Y15, finding 2).
EDITORIAL_DIR = os.path.dirname(os.path.abspath(__file__))


def editorial_file_path(file_name: str, directory: str = None) -> str:
    """Where this editorial file is. *directory* is for tests only."""
    return os.path.join(EDITORIAL_DIR if directory is None else directory,
                        file_name)


class TabFileState:
    """Load/save guard for one config file. Mixed into BaseConfigTab.

    Subclasses provide ``file_name``, ``file_path``, ``file_type``,
    ``get_edited_data()`` and ``validate()``.
    """

    load_error = None
    _disk_mtime = None

    def _read_file(self):
        """Parse the file. Raises on a file that exists but cannot be parsed."""
        with open(self.file_path, "r", encoding="utf-8") as f:
            if self.file_type == "yaml":
                return yaml.safe_load(f) or {}
            return json.load(f)

    def _file_mtime(self):
        try:
            return os.path.getmtime(self.file_path)
        except OSError:
            return None

    def load_current_data(self):
        """Load the file. A parse failure is kept in ``load_error`` so the tab
        can refuse to save over a file it never read (A1)."""
        self.load_error = None
        self._disk_mtime = self._file_mtime()
        if self._disk_mtime is None:
            self.current_data = {}
            return
        try:
            self.current_data = self._read_file()
        except Exception as e:  # any parse/read failure blocks saving, by design
            self.current_data = {}
            self.load_error = f"{type(e).__name__}: {e}"

    def changed_on_disk(self):
        """True when the file was written by something else since we loaded it (A8)."""
        return self._file_mtime() != self._disk_mtime

    def needs_reload(self):
        """True when what the tab shows is not what is on disk and saving is blocked."""
        return bool(self.load_error) or self.changed_on_disk()

    def has_unsaved_changes(self):
        if self.load_error:
            return False
        return self.get_edited_data() != self.current_data

    def save_blocker(self):
        """Why this tab must not be written right now, or None."""
        if self.load_error:
            return (f"{self.file_name} could not be read when the window opened "
                    f"({self.load_error}). Fix the file, then use Discard Changes to reload.")
        if self.changed_on_disk():
            return (f"{self.file_name} changed on disk after it was loaded. "
                    f"Use Discard Changes to reload it, then redo the edit.")
        return None

    def save_to_disk(self):
        """Validate, then write. Returns (success, message)."""
        blocker = self.save_blocker()
        if blocker:
            return (False, blocker)
        is_valid, errors, _warnings = self.validate()
        if not is_valid:
            return (False, f"Validation failed for {self.file_name}:\n" + "\n".join(errors))
        try:
            data = self.get_edited_data()
            if self.file_type == "yaml":
                save_yaml_preserving_comments(self.file_path, data)
            else:
                tmp = self.file_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.file_path)
        except Exception as e:
            return (False, f"Failed to save {self.file_name}: {e}")
        self.current_data = copy.deepcopy(data)
        self._disk_mtime = self._file_mtime()
        return (True, f"Saved {self.file_name}")


def save_changed_tabs(tabs):
    """Save only the tabs that changed, and only if all of them may be written.

    Returns ``(ok, saved_names, problems)``. Every blocker and validation error
    is collected before the first write, so a bad tab cannot leave a partial
    multi-file save (A2, A7).
    """
    problems = [f"{t.file_name}: not loaded ({t.load_error})" for t in tabs if t.load_error]
    dirty = [t for t in tabs if t.has_unsaved_changes()]
    blocked = []
    for tab in dirty:
        blocker = tab.save_blocker()
        if blocker:
            blocked.append(blocker)
            continue
        is_valid, errors, _warnings = tab.validate()
        if not is_valid:
            blocked.extend(f"{tab.file_name}: {e}" for e in errors)
    if blocked:
        return (False, [], problems + blocked)
    saved = []
    for tab in dirty:
        ok, message = tab.save_to_disk()
        if not ok:
            return (False, saved, problems + [message])
        saved.append(tab.file_name)
    return (True, saved, problems)


# --- config.yml: overlay edits on the loaded data (A3, A4) -------------------

def _parse_field(raw, field_type):
    if field_type == "bool":
        return bool(raw)
    if field_type == "str":
        return raw
    if field_type == "int":
        return int(str(raw).strip())
    if field_type == "float":
        return float(str(raw).strip())
    parsed = yaml.safe_load(raw) if isinstance(raw, str) else raw
    expected = list if field_type == "list" else dict
    if parsed is None:
        return expected()
    if not isinstance(parsed, expected):
        raise ValueError(f"expected a {field_type}")
    return parsed


def merge_settings_edits(current, raw_values):
    """Overlay edited fields on a copy of ``current``.

    ``raw_values`` is ``{section: {field: (raw, field_type)}}``. Keys with no
    widget are kept as loaded. A field that does not parse keeps its loaded
    value and is reported, never coerced to 0 / [] / {}. A field the loader
    refuses at zero or less (``positive_only_fields``) is reported the same
    way and keeps its loaded value: the Spinbox floor only constrains its
    spin arrows, so a typed 0 for a retry budget or a timeout used to save
    (review chunk Y8).
    Returns ``(data, errors)``.
    """
    data = copy.deepcopy(current) if isinstance(current, dict) else {}
    errors = []
    positive_only = positive_only_fields()
    for section, fields in raw_values.items():
        if not fields:
            continue
        target = data.setdefault(section, {})
        for field, (raw, field_type) in fields.items():
            try:
                parsed = _parse_field(raw, field_type)
            except (ValueError, TypeError, yaml.YAMLError) as e:
                errors.append(f"{section}.{field}: not a valid {field_type} ({e})")
                continue
            if ((section, field) in positive_only
                    and isinstance(parsed, (int, float))
                    and not isinstance(parsed, bool)
                    and parsed <= 0):
                errors.append(f"{section}.{field}: must be greater than zero "
                              f"({parsed} would be refused by the loader and "
                              f"the built-in default used instead)")
                continue
            target[field] = parsed
    return data, errors


# --- row-backed tabs: each tree row stands for a full record (A5, A6) --------

class RowModel:
    """Full record behind each treeview row, keyed by the row's item id."""

    def __init__(self):
        self._by_item = {}

    def clear(self):
        self._by_item = {}

    def bind(self, item_id, record):
        self._by_item[item_id] = copy.deepcopy(record)

    def get(self, item_id):
        return copy.deepcopy(self._by_item.get(item_id))

    def move(self, old_item_id, new_item_id):
        if old_item_id in self._by_item:
            self._by_item[new_item_id] = self._by_item.pop(old_item_id)

    def drop(self, item_id):
        self._by_item.pop(item_id, None)

    def records(self, item_ids):
        return [copy.deepcopy(self._by_item[i]) for i in item_ids if i in self._by_item]


def update_record(original, fields):
    """A copy of ``original`` with ``fields`` applied; other keys are kept."""
    record = copy.deepcopy(original) if isinstance(original, dict) else {}
    record.update(fields)
    return record


MATCH_FIELDS = ("content_type", "entity_type", "local_pack", "domain_role")


def apply_rule_row(original, row_values):
    """Apply one Intent Mapping tree row to its rule.

    ``row_values`` is (content_type, entity_type, local_pack, domain_role,
    intent). A cell is written only when its text differs from the loaded
    value, so a value Tk returned as a different type is not rewritten, and
    keys the tree does not show (``rationale``) are kept.
    """
    rule = copy.deepcopy(original) if isinstance(original, dict) else {}
    match = rule.get("match")
    if not isinstance(match, dict):
        match = {}
    for name, value in zip(MATCH_FIELDS, row_values[:4]):
        if str(match.get(name, "")) != str(value):
            match[name] = value
    rule["match"] = match
    if str(rule.get("intent", "")) != str(row_values[4]):
        rule["intent"] = row_values[4]
    return rule


def restore_hidden(shown, hidden):
    """Put rules the tree never displayed back at their original positions.

    ``hidden`` is a list of ``(original_index, rule)``.
    """
    out = list(shown)
    for index, rule in sorted(hidden, key=lambda pair: pair[0]):
        out.insert(min(index, len(out)), copy.deepcopy(rule))
    return out


# ---------------------------------------------------------------------------
# Review chunk Y15 — every editorial file has an editor
# ---------------------------------------------------------------------------
#
# `CLAUDE.md` says editorial content — anything a non-developer might
# reasonably want to change — belongs in a YAML or JSON file rather than in
# Python, and the review chunks moved a great deal of it out. The
# Configuration Manager is how a non-developer reaches those files, and it was
# never extended: it registered nine tabs while the repo holds nineteen
# editable editorial files. So the rule was followed and the consequence it
# exists for was not delivered for ten of them.
#
# Each of the ten is a source tab rather than a widget form. The nine existing
# tabs are hand-written forms for one file's particular shape; these ten nest
# arbitrarily — `report_writing_directives.yml` and `engine_profiles.yml` are
# three and four levels deep with prose leaves — and a widget tree over
# arbitrary nesting is more GUI surface than the editorial benefit justifies.
# What a source tab adds over opening the file in a text editor is what
# matters: it is discoverable in the window, its YAML is parsed before the
# write so a syntax error is caught with its line instead of breaking the next
# run, the file's own validator runs if it has one, it joins Save All /
# Discard / the unsaved-changes prompt, and it carries the help text saying
# what the file is for. A form for a specific file stays available as a later
# per-file upgrade — that is what the nine bespoke tabs are.

#: `(file_name, file_type, title, structural_check)` for each editorial file
#: with no bespoke form. Adding the eleventh file is a row here, not a class.
#:
#: `structural_check` is the name of a `module:function` taking the file's
#: path and raising on a file whose *shape* is wrong — valid YAML is not a
#: valid rule table. The source tab's own check is syntax, and a tab that
#: checks only syntax while claiming to stop a broken edit reaching the next
#: run is making a claim it cannot keep: deleting the `rules:` list from
#: `play_routing.yml` saved cleanly and the next run died inside
#: `brief_data_extraction`, and deleting `numeric_claims:` from
#: `brief_validation_rules.yml` left every numeric check off while the
#: sidecar reported nothing skipped (the cold review of chunk Y15, finding 3).
#: `None` means the file's readers already degrade loudly and name what they
#: dropped; the test beside this table records that decision per file.
EDITORIAL_SOURCE_FILES = (
    ("feasibility_messages.yml", "yaml", "Feasibility Wording", None),
    ("gsc_messages.yml", "yaml", "Search Console Wording", None),
    ("ai_visibility_messages.yml", "yaml", "AI Visibility Wording", None),
    ("serp_vocab.yml", "yaml", "SERP Vocabulary", None),
    ("glossary.yml", "yaml", "Glossary", None),
    ("play_routing.yml", "yaml", "Recommended Plays",
     "play_routing:load_play_routing"),
    ("engine_profiles.yml", "yaml", "Engine Profiles", None),
    ("report_writing_directives.yml", "yaml", "Report Directives", None),
    ("brief_validation_rules.yml", "yaml", "Brief Validation",
     "brief_validation:load_validation_rules"),
    ("schema_recommendations.yml", "yaml", "Schema Recommendations", None),
)


def structural_check(name: str):
    """Resolve a `module:function` structural check, or None.

    Imported here rather than at module import: `config_tab_models` is
    imported by the GUI launcher, and pulling in the report's own modules to
    get a validator would make the launcher depend on the pipeline.
    """
    if not name:
        return None
    module_name, _, function_name = name.partition(":")
    module = __import__(module_name)
    return getattr(module, function_name)


def structural_errors_for_text(file_name: str, text: str,
                               file_type: str = "yaml") -> list:
    """`structural_errors` for text that is not on disk yet.

    The file's own loader takes a path, so the edit is checked where it can
    do no harm rather than after it has replaced the real file.
    """
    row = next((r for r in EDITORIAL_SOURCE_FILES if r[0] == file_name), None)
    if row is None or not row[3]:
        return []
    suffix = ".json" if file_type == "json" else ".yml"
    handle, tmp = tempfile.mkstemp(prefix="check.", suffix=suffix)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        return structural_errors(file_name, tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def structural_errors(file_name: str, path: str) -> list:
    """What is wrong with the *shape* of this file, by its own reader.

    The file's own loader is the check, never a second copy of its rules
    (P32): `play_routing.load_play_routing` already raises on a missing
    `plays` or `rules`, an unknown play id or a non-string `strategy_text`,
    and `brief_validation.load_validation_rules` already records every rule
    it had to skip.
    """
    row = next((r for r in EDITORIAL_SOURCE_FILES if r[0] == file_name), None)
    if row is None or not row[3]:
        return []
    try:
        check = structural_check(row[3])
    except Exception as e:
        # A check that cannot be imported must not block the save; say so.
        return [f"could not run the structural check for {file_name} "
                f"({type(e).__name__}: {e}); only the syntax was checked"]
    try:
        result = check(path)
    except Exception as e:
        return [f"{file_name} parses but is not a usable "
                f"{row[2].lower()} table: {type(e).__name__}: {e}"]
    # A loader that degrades rather than raising reports what it dropped.
    if isinstance(result, dict):
        problems = []
        if result.get("load_error"):
            problems.append(f"{file_name}: {result['load_error']}")
        for field in result.get("fields_skipped") or []:
            problems.append(f"{file_name}: the rule for {field} would be "
                            f"skipped — it is not in a usable shape")
        return problems
    return []

#: Files that are deliberately NOT editable in the Configuration Manager, each
#: with the reason. An explicit list, so every exclusion is a decision on the
#: record rather than something a filename pattern swept up.
NOT_EDITORIAL = {
    "handoff_schema.json":
        "a contract between the two tools — hand-editing one side is how they "
        "drift",
    "ai_visibility_export_schema.json":
        "a contract between the producer and its consumer, as above",
    "diff_report.json": ("a generated artefact, rewritten by every run, and "
                         "untracked, so the tracked-file inventory does not "
                         "reach it either"),
}


def _tracked_names(root: str):
    """Top-level file names git tracks in *root*, or None if it cannot say.

    The inventory is the *tracked* files, because the untracked ones at this
    root are a run's own output and a reader's scratch files. Listing the
    directory instead made `touch zz_scratch.yml` fail the standing guard and
    counted the gitignored `diff_report.json` as an editorial file somebody
    had forgotten to wire up (the cold review of chunk Y15, finding 4).
    """
    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--", "*.yml", "*.yaml",
             "*.json"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return {entry for entry in result.stdout.split("\0")
            if entry and "/" not in entry}


def editorial_files(root: str) -> list:
    """Every editorial YAML/JSON file git tracks at *root*, sorted.

    Excludes nothing by pattern: the exclusions are named in
    :data:`NOT_EDITORIAL` with their reasons. A *root* that is not a git work
    tree falls back to listing the directory, which is what the tests of this
    function use; the repo itself always has git to ask.
    """
    tracked = _tracked_names(root)
    names = []
    for name in sorted(os.listdir(root)):
        if not name.endswith((".yml", ".yaml", ".json")):
            continue
        if not os.path.isfile(os.path.join(root, name)):
            continue
        if tracked is not None and name not in tracked:
            continue
        names.append(name)
    return names


def files_without_an_editor(root: str, covered) -> list:
    """Editorial files in *root* that no tab edits and no exclusion names.

    This is the part of chunk Y15 that stops the fault recurring. Ten files
    reached the repo with no editor and nothing said so, because the only
    record of what was covered was the list of tab classes.
    """
    covered = set(covered)
    return [name for name in editorial_files(root)
            if name not in covered and name not in NOT_EDITORIAL]


def parse_source(text: str, file_type: str):
    """``(data, error)`` for edited source text. Exactly one is None.

    A parse failure is returned rather than raised so the tab can show it and
    refuse to save, which is how every other tab treats an unreadable edit.
    """
    try:
        if file_type == "yaml":
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as e:
        return (None, f"{type(e).__name__}: {e}")
    if data is None:
        data = {}
    if not isinstance(data, (dict, list)):
        return (None, f"the file must hold a mapping or a list, not "
                      f"{type(data).__name__}")
    return (data, None)


def write_source(path: str, text: str) -> None:
    """Write edited source text verbatim, atomically.

    Verbatim, not re-dumped from the parsed structure: a source tab shows the
    file's comments, and a comment the user adds or changes has to survive the
    save. `save_yaml_preserving_comments` merges a structure into the comments
    already on disk, which would silently discard a new one.
    """
    if text and not text.endswith("\n"):
        text += "\n"
    # A unique name in the target directory, removed on any failure: a fixed
    # `<file>.tmp` left partial content beside the file when the write failed,
    # with nothing to clean it up or mention it, and two writers of one file
    # collided on the name. `flush` + `fsync` before the rename, because a
    # crash between them leaves a zero-length file where the good one was
    # (the cold review of chunk Y15, finding 7).
    directory = os.path.dirname(os.path.abspath(path))
    handle, tmp = tempfile.mkstemp(dir=directory,
                                   prefix=os.path.basename(path) + ".",
                                   suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
