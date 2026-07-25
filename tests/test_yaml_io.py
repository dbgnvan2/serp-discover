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


def test_dump_failure_is_atomic_and_does_not_poison_later_saves(tmp_path):
    """A mid-dump failure (un-representable value) must (a) leave the original config
    intact with no temp file behind (atomic, P2), AND (b) not break the next save —
    fresh-YAML-per-call means no poisoned shared emitter (P1/P15)."""
    bad = tmp_path / "bad.yml"
    bad.write_text("a: 1  # keep\n")
    good = tmp_path / "good.yml"
    good.write_text("g: 1  # doc\n")

    with pytest.raises(Exception):
        yaml_io.save_yaml_preserving_comments(str(bad), {"a": object()})   # RepresenterError mid-emit
    assert bad.read_text() == "a: 1  # keep\n"                             # original untouched (atomic)
    assert not any(p.name.startswith(".yamlio_") for p in tmp_path.iterdir())  # no temp leak

    # The old shared-singleton bug would make THIS raise "I/O operation on closed file":
    yaml_io.save_yaml_preserving_comments(str(good), {"g": 2})
    assert "g: 2" in good.read_text() and "# doc" in good.read_text()


def test_symlinked_config_updates_target_not_detaches_link(tmp_path):
    """P3/P6 — a symlinked config (the multi-client workflow) is written through to
    its target, keeping the link; not replaced by a standalone file."""
    import os
    real = tmp_path / "real.yml"
    real.write_text("a: 1  # doc\n")
    link = tmp_path / "config.yml"
    os.symlink(real, link)
    yaml_io.save_yaml_preserving_comments(str(link), {"a": 2})
    assert os.path.islink(str(link))                       # link intact, not a plain file
    assert "a: 2" in real.read_text() and "# doc" in real.read_text()   # target updated + comment kept


def test_no_repo_config_has_yaml11_boollike_top_level_key():
    """Latent-divergence guard (Finding 3): the PyYAML-src vs ruamel-dst parser
    mismatch only bites on YAML-1.1 bool-like keys; assert no repo config uses one."""
    import glob
    import os
    import yaml as pyyaml
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    boollike = {"on", "off", "yes", "no", "true", "false"}
    for path in glob.glob(os.path.join(root, "*.yml")):
        try:
            data = pyyaml.safe_load(open(path, encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict):
            keys = {str(k).lower() for k in data.keys()}
            assert not (keys & boollike), \
                f"{os.path.basename(path)} has a bool-like top-level key — align parsers in yaml_io"


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
