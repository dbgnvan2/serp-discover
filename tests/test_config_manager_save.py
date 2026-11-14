"""Configuration Manager must not lose or blank config files on save.

Spec: docs/plan_config_save_exit_codes_2026-11-14.md (A1-A8)
"""

import copy
import os
import shutil

import pytest
import yaml

import config_manager
import config_tab_models as ctm
from tk_probe import tkinter_usable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILES = [
    "domain_overrides.yml", "classification_rules.json", "intent_mapping.yml",
    "strategic_patterns.yml", "brief_pattern_routing.yml",
    "intent_classifier_triggers.yml", "config.yml", "url_pattern_rules.yml",
    "client_profiles.yml",
]


def _snapshot(directory):
    return {n: open(os.path.join(directory, n), "rb").read() for n in CONFIG_FILES}


# --- no tkinter ---------------------------------------------------------------

class _Tab(ctm.TabFileState):
    """A tab with no widgets: edits are whatever the test puts in ``edited``."""

    def __init__(self, path, valid=True):
        self.file_path, self.file_name, self.file_type = str(path), os.path.basename(path), "yaml"
        self.valid = valid
        self.load_current_data()
        self.edited = copy.deepcopy(self.current_data)

    def get_edited_data(self):
        return self.edited

    def validate(self):
        return (self.valid, [] if self.valid else ["bad value"], [])


def test_unparseable_file_is_never_overwritten(tmp_path):
    path = tmp_path / "broken.yml"
    path.write_text("a: [1, 2\nb: {unclosed\n")
    before = path.read_bytes()
    tab = _Tab(path)
    tab.edited = {"a": 1}

    assert tab.load_error
    assert not tab.has_unsaved_changes()
    ok, message = tab.save_to_disk()
    assert not ok and "broken.yml" in message
    ok, saved, problems = ctm.save_changed_tabs([tab])
    assert saved == [] and any("broken.yml" in p for p in problems)
    assert path.read_bytes() == before


def test_save_all_aborts_before_any_write_on_invalid_tab(tmp_path):
    good, bad = tmp_path / "good.yml", tmp_path / "bad.yml"
    good.write_text("k: 1\n")
    bad.write_text("k: 1\n")
    tabs = [_Tab(good), _Tab(bad, valid=False)]
    for tab in tabs:
        tab.edited = {"k": 2}

    ok, saved, problems = ctm.save_changed_tabs(tabs)

    assert not ok and saved == [] and problems
    assert good.read_text() == "k: 1\n"      # the valid tab came first and was not written


def test_only_changed_tabs_are_written(tmp_path):
    a, b = tmp_path / "a.yml", tmp_path / "b.yml"
    a.write_text("# keep me\nk: 1\n")
    b.write_text("k: 1\n")
    tabs = [_Tab(a), _Tab(b)]
    tabs[1].edited = {"k": 2}

    ok, saved, _ = ctm.save_changed_tabs(tabs)

    assert ok and saved == ["b.yml"]
    assert a.read_text() == "# keep me\nk: 1\n"
    assert yaml.safe_load(b.read_text()) == {"k": 2}


def test_save_refuses_when_file_changed_on_disk(tmp_path):
    path = tmp_path / "c.yml"
    path.write_text("k: 1\n")
    tab = _Tab(path)
    tab.edited = {"k": 2}
    path.write_text("k: 99\n")                       # the launcher wrote meanwhile
    os.utime(path, (tab._disk_mtime + 5, tab._disk_mtime + 5))

    ok, saved, problems = ctm.save_changed_tabs([tab])

    assert not ok and "changed on disk" in problems[0]
    assert path.read_text() == "k: 99\n"


def test_unreadable_or_stale_file_needs_reload(tmp_path):
    path = tmp_path / "d.yml"
    path.write_text("a: [1, 2\n")
    tab = _Tab(path)
    assert tab.needs_reload()
    path.write_text("a: 1\n")                      # fixed in a text editor
    tab.load_current_data()                        # what Discard Changes does
    assert not tab.needs_reload() and tab.current_data == {"a": 1}
    os.utime(path, (tab._disk_mtime + 5, tab._disk_mtime + 5))
    assert tab.needs_reload()


def test_settings_merge_preserves_unwidgeted_keys():
    current = {"known_brands": ["a.com", "b.com"], "app": {"n": 3, "note": None, "empty": {}}}
    data, errors = ctm.merge_settings_edits(current, {"known_brands": {}, "app": {"n": ("7", "int")}})
    assert errors == []
    assert data == {"known_brands": ["a.com", "b.com"], "app": {"n": 7, "note": None, "empty": {}}}


def test_settings_parse_failure_is_reported_not_coerced():
    current = {"app": {"n": 3, "ratio": 0.5, "words": ["x"]}}
    data, errors = ctm.merge_settings_edits(current, {"app": {
        "n": ("3x", "int"), "ratio": ("", "float"), "words": ("just text", "list")}})
    assert data == current
    assert sorted(e.split(":")[0] for e in errors) == ["app.n", "app.ratio", "app.words"]


def test_intent_rules_keep_rationale():
    with open(os.path.join(REPO, "intent_mapping.yml")) as f:
        rules = yaml.safe_load(f)["rules"]
    assert sum("rationale" in r for r in rules) >= 10      # the fixture has something to lose

    rebuilt = []
    for rule in rules:
        m = rule["match"]
        row = [m.get(k, "") for k in ctm.MATCH_FIELDS] + [rule.get("intent", "")]
        rebuilt.append(ctm.apply_rule_row(rule, [str(v) for v in row]))   # Tk hands back text
    assert rebuilt == rules

    edited = ctm.apply_rule_row(rules[0], ["guide", "media", "any", "any", "informational"])
    assert edited["rationale"] == rules[0]["rationale"]
    assert edited["match"]["content_type"] == "guide"


def test_hidden_rules_return_to_their_position():
    shown = [{"id": 0}, {"id": 2}]
    assert ctm.restore_hidden(shown, [(1, {"id": 1}), (9, {"id": 9})]) == [
        {"id": 0}, {"id": 1}, {"id": 2}, {"id": 9}]


def test_pattern_edit_keeps_other_fields_and_what_was_typed():
    rows = ctm.RowModel()
    rows.bind("I1", {"Pattern_Name": "Old", "Triggers": ["aaaa"], "Content_Angle_Example": "keep"})
    rows.bind("I1", ctm.update_record(rows.get("I1"), {"Pattern_Name": "New", "Triggers": ["bbbb", "cccc"]}))
    rows.bind("I2", ctm.update_record(None, {"Pattern_Name": "Added", "Triggers": ["dddd"]}))
    assert rows.records(["I2", "I1"]) == [
        {"Pattern_Name": "Added", "Triggers": ["dddd"]},
        {"Pattern_Name": "New", "Triggers": ["bbbb", "cccc"], "Content_Angle_Example": "keep"},
    ]


def test_window_close_button_uses_the_unsaved_changes_prompt():
    """Source check (the repo's convention for Tk wiring that needs no display)."""
    src = open(os.path.join(REPO, "config_manager.py")).read()
    assert 'protocol("WM_DELETE_WINDOW", self.close_window)' in src
    assert "elif confirm and not self.save_all():" in src


# --- with tkinter: the real tabs over copies of the real files -----------------

pytestmark_tk = pytest.mark.skipif(not tkinter_usable(), reason="no usable Tk display")


@pytest.fixture
def tabs(tmp_path, monkeypatch):
    import tkinter as tk
    for name in CONFIG_FILES:
        shutil.copy(os.path.join(REPO, name), tmp_path / name)
    monkeypatch.chdir(tmp_path)
    for fn in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(config_manager.messagebox, fn, lambda *a, **k: None)
    root = tk.Tk()
    root.withdraw()
    classes = [
        config_manager.DomainOverridesTab, config_manager.ClassificationRulesTab,
        config_manager.IntentMappingTab, config_manager.StrategicPatternsTab,
        config_manager.BriefPatternRoutingTab, config_manager.IntentClassifierTriggersTab,
        config_manager.ConfigSettingsTab, config_manager.UrlPatternRulesTab,
        config_manager.ClientProfileTab,
    ]
    try:
        yield {cls.__name__: cls(root) for cls in classes}
    finally:
        root.destroy()


def _widgets(parent, kind):
    found = []
    for child in parent.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_widgets(child, kind))
    return found


def _press(dialog, label):
    from tkinter import ttk
    [button] = [b for b in _widgets(dialog, ttk.Button) if b.cget("text") == label]
    button.invoke()


@pytestmark_tk
def test_save_all_without_edits_writes_nothing(tabs, tmp_path):
    before = _snapshot(tmp_path)
    dirty = [name for name, tab in tabs.items() if tab.has_unsaved_changes()]
    ok, saved, problems = ctm.save_changed_tabs(list(tabs.values()))
    assert (dirty, ok, saved, problems) == ([], True, [], [])
    assert _snapshot(tmp_path) == before


@pytestmark_tk
@pytest.mark.parametrize("tab_name,file_name,list_key,name_key,text_index", [
    ("StrategicPatternsTab", "strategic_patterns.yml", None, "Pattern_Name", 0),
    ("BriefPatternRoutingTab", "brief_pattern_routing.yml", "patterns", "pattern_name", 0),
])
def test_pattern_dialog_edit_reaches_saved_data(tabs, tmp_path, tab_name, file_name,
                                                list_key, name_key, text_index):
    import tkinter as tk
    tab = tabs[tab_name]
    first = tab.tree.get_children()[0]
    tab.tree.selection_set(first)
    tab._edit_pattern()
    dialog = _widgets(tab, tk.Toplevel)[-1]
    box = _widgets(dialog, tk.Text)[text_index]       # triggers / PAA themes
    box.delete("1.0", "end")
    box.insert("1.0", "typed-in-dialog-one\ntyped-in-dialog-two")
    _press(dialog, "Save")

    ok, saved, problems = ctm.save_changed_tabs(list(tabs.values()))
    assert (ok, saved, problems) == (True, [file_name], [])

    on_disk = yaml.safe_load((tmp_path / file_name).read_text())
    original = yaml.safe_load(open(os.path.join(REPO, file_name)).read())
    patterns, before = (on_disk, original) if list_key is None else (on_disk[list_key], original[list_key])
    assert ["typed-in-dialog-one", "typed-in-dialog-two"] in patterns[0].values()
    assert patterns[0][name_key] == before[0][name_key]
    assert patterns[1:] == before[1:]


@pytestmark_tk
def test_settings_edit_changes_one_key_and_keeps_the_rest(tabs, tmp_path):
    tab = tabs["ConfigSettingsTab"]
    original = copy.deepcopy(tab.current_data)
    section, field = next(
        (s, f) for s, fields in tab.section_widgets.items()
        for f, (_w, kind) in fields.items() if kind == "int")
    var = tab.section_widgets[section][field][0]

    var._tk.globalsetvar(var._name, "not-a-number")     # a typo is reported, never dropped
    before = (tmp_path / "config.yml").read_bytes()
    assert tab.has_unsaved_changes()
    ok, saved, problems = ctm.save_changed_tabs(list(tabs.values()))
    assert not ok and saved == [] and f"{section}.{field}" in problems[-1]
    assert (tmp_path / "config.yml").read_bytes() == before

    var.set(original[section][field] + 1)
    ok, saved, _ = ctm.save_changed_tabs(list(tabs.values()))
    assert ok and saved == ["config.yml"]
    expected = copy.deepcopy(original)
    expected[section][field] += 1
    assert yaml.safe_load((tmp_path / "config.yml").read_text()) == expected


@pytestmark_tk
def test_tabs_keep_keys_they_have_no_widget_for(tabs):
    triggers, urls = tabs["IntentClassifierTriggersTab"], tabs["UrlPatternRulesTab"]
    triggers.current_data["future_key"] = {"a": 1}
    triggers.current_data["medical_triggers"]["regex"] = ["x+"]
    urls.current_data["future_key"] = [1]
    urls.current_data["url_pattern_rules"][0]["note"] = "kept"
    assert triggers.get_edited_data() == triggers.current_data
    assert urls.get_edited_data() == urls.current_data


@pytestmark_tk
def test_revert_does_not_duplicate_widgets(tabs):
    from tkinter import ttk
    for name, tab in tabs.items():
        before = len(_widgets(tab, ttk.Treeview))
        tab.revert_to_disk()
        assert len(_widgets(tab, ttk.Treeview)) == before, name
        assert not tab.has_unsaved_changes(), name


@pytestmark_tk
def test_load_error_shows_on_the_tab(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    (tmp_path / "domain_overrides.yml").write_text("a: [1, 2\n")
    monkeypatch.chdir(tmp_path)
    root = tk.Tk()
    root.withdraw()
    try:
        tab = config_manager.DomainOverridesTab(root)
        assert tab.load_error
        assert any("could not be read" in str(l.cget("text")) for l in _widgets(tab, ttk.Label))
    finally:
        root.destroy()
