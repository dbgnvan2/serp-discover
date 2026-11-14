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

import yaml

from yaml_io import save_yaml_preserving_comments


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
    value and is reported, never coerced to 0 / [] / {}.
    Returns ``(data, errors)``.
    """
    data = copy.deepcopy(current) if isinstance(current, dict) else {}
    errors = []
    for section, fields in raw_values.items():
        if not fields:
            continue
        target = data.setdefault(section, {})
        for field, (raw, field_type) in fields.items():
            try:
                target[field] = _parse_field(raw, field_type)
            except (ValueError, TypeError, yaml.YAMLError) as e:
                errors.append(f"{section}.{field}: not a valid {field_type} ({e})")
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
