"""Comment-preserving YAML save (yaml_io) — the shared fix for the config strippers.

Every repo YAML config carries load-bearing doc/gating comments. PyYAML's
`yaml.safe_dump` strips them all, so THREE writers were silently wiping them on a
load→modify→save cycle: `config_manager.BaseConfigTab.save_to_disk` (GUI editor),
`serp_audit` (config.yml output-path write-back, every run), and
`apply_domain_override_candidates.write_overrides` (domain_overrides.yml). All now
route through `yaml_io.save_yaml_preserving_comments` (ruamel round-trip). Pure —
no tkinter.
"""
import os

import pytest

import yaml_io


def test_dict_preserves_comments_and_updates_value(tmp_path):
    """The reported incident: a config.yml save keeps its doc-block comments while
    the edited value is written (the caller hands over a comment-less dict)."""
    f = tmp_path / "config.yml"
    f.write_text(
        "# top-of-file note\n"
        "gsc:\n"
        "  # off by default until the service-account grant is in place\n"
        "  enabled: false\n"
        "  property: sc-domain:livingsystems.ca\n"
    )
    yaml_io.save_yaml_preserving_comments(
        str(f), {"gsc": {"enabled": True, "property": "sc-domain:livingsystems.ca"}})
    out = f.read_text()
    assert "# top-of-file note" in out
    assert "service-account grant" in out
    assert "enabled: true" in out


def test_deleted_key_matches_old_safe_dump_data(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("a: 1  # keep\nb: 2  # drop\n")
    yaml_io.save_yaml_preserving_comments(str(f), {"a": 9})
    out = f.read_text()
    assert "a: 9" in out and "# keep" in out
    assert "b:" not in out and "drop" not in out


def test_new_key_added_alongside_kept_comment(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("a: 1  # note\n")
    yaml_io.save_yaml_preserving_comments(str(f), {"a": 1, "c": 3})
    out = f.read_text()
    assert "# note" in out and "c: 3" in out


def test_list_topped_preserves_document_comment(tmp_path):
    """strategic_patterns.yml is a top-level LIST — the doc-level (header) comment
    must survive (the dict-only gate previously stripped it)."""
    f = tmp_path / "strategic_patterns.yml"
    f.write_text(
        "# EDITORIAL: Bowen patterns — edit here, no Python needed\n"
        "- name: triangle\n"
        "  trigger: conflict\n"
    )
    yaml_io.save_yaml_preserving_comments(str(f), [
        {"name": "triangle", "trigger": "conflict"},
        {"name": "distance", "trigger": "cutoff"},
    ])
    out = f.read_text()
    assert "# EDITORIAL" in out          # document-level comment kept
    assert "distance" in out             # new item written


def test_no_existing_file_writes_fresh(tmp_path):
    f = tmp_path / "new.yml"
    yaml_io.save_yaml_preserving_comments(str(f), {"x": 1})
    assert "x: 1" in f.read_text()


def test_unparseable_on_disk_writes_fresh_and_warns(tmp_path, caplog):
    import logging
    f = tmp_path / "bad.yml"
    f.write_text("::: not : valid : yaml :::\n")
    with caplog.at_level(logging.WARNING):
        yaml_io.save_yaml_preserving_comments(str(f), {"x": 1})
    assert "x: 1" in f.read_text()
    assert "comments" in caplog.text.lower()   # not silent — surfaced (P2)


def test_atomic_write_preserves_original_on_dump_failure(tmp_path, monkeypatch):
    """A dump failure must leave the original config intact (temp + os.replace), not
    truncate it, and leave no temp file behind (P2)."""
    f = tmp_path / "c.yml"
    f.write_text("a: 1  # keep\n")

    def _boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(yaml_io._yaml_rt(), "dump", _boom)

    with pytest.raises(RuntimeError):
        yaml_io.save_yaml_preserving_comments(str(f), {"a": 2})
    assert f.read_text() == "a: 1  # keep\n"                     # untouched
    assert not any(p.name.startswith(".yamlio_") for p in tmp_path.iterdir())


def test_merge_nested_update_keeps_sibling_comment():
    from ruamel.yaml import YAML
    import io
    y = YAML()
    doc = y.load("a:\n  b: 1  # keep\n  c: 2\n")
    yaml_io._merge_into_commented(doc, {"a": {"b": 9}})
    buf = io.StringIO()
    y.dump(doc, buf)
    out = buf.getvalue()
    assert "b: 9" in out and "# keep" in out and "c:" not in out


def test_all_config_writers_route_through_yaml_io():
    """P5 regression guard: the whole class of config-file writers must use the
    comment-preserving save, not yaml.safe_dump."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for module in ("serp_audit.py", "apply_domain_override_candidates.py",
                   "config_manager.py"):
        src = open(os.path.join(root, module), encoding="utf-8").read()
        assert "save_yaml_preserving_comments" in src, \
            f"{module} must use the comment-preserving save"
    serp = open(os.path.join(root, "serp_audit.py"), encoding="utf-8").read()
    assert "yaml.safe_dump(_cfg" not in serp                     # config.yml write-back
    apply_src = open(os.path.join(root, "apply_domain_override_candidates.py"),
                     encoding="utf-8").read()
    assert "yaml.safe_dump(dict(sorted" not in apply_src         # domain_overrides.yml
