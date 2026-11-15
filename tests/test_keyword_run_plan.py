"""Preparing a run writes nothing until the run is about to start.

Spec: docs/plan_checkpoint_resume_and_m3_2026-11-14.md (M1-M5)
"""

import os

import pytest

import keyword_run_plan as krp
import pipeline_status as ps


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_plan_writes_nothing(tmp_path):
    existing = tmp_path / "keywords_topic.csv"
    existing.write_text("keyword\nalpha\nbeta\n")
    before = _snapshot(tmp_path)

    krp.plan_keyword_run(str(existing), [], str(tmp_path))
    krp.plan_keyword_run(str(existing), ["gamma"], str(tmp_path))
    krp.plan_keyword_run(None, ["brand new", "other"], str(tmp_path))
    krp.plan_keyword_run(None, ["topic", "gamma"], str(tmp_path))

    assert _snapshot(tmp_path) == before
    with pytest.raises(ValueError):
        krp.plan_keyword_run(None, [], str(tmp_path))


def test_new_keywords_make_a_new_file_at_apply(tmp_path):
    plan = krp.plan_keyword_run(None, ["Brand New!", "other"], str(tmp_path))
    assert os.path.basename(plan["keyword_file"]) == "keywords_brand_new.csv"
    assert plan["write"] and plan["existing_count"] is None
    assert krp.apply_keyword_plan(plan) is True
    assert (tmp_path / "keywords_brand_new.csv").read_text() == "Brand New!\nother\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_keyword_file_is_not_overwritten(tmp_path):
    existing = tmp_path / "keywords_topic.csv"
    existing.write_text("alpha\nbeta\n")

    plan = krp.plan_keyword_run(None, ["topic", "Alpha"], str(tmp_path))
    assert plan["existing_count"] == 2              # the caller must ask (M4)
    assert plan["keywords"] == ["alpha", "beta", "topic"]
    assert plan["added_keywords"] == ["topic"]
    assert existing.read_text() == "alpha\nbeta\n"   # untouched until applied

    krp.apply_keyword_plan(plan)                     # the user said yes
    assert existing.read_text() == "alpha\nbeta\ntopic\n"

    # Same keywords again: nothing to ask, nothing to write.
    same = krp.plan_keyword_run(None, ["topic", "ALPHA", "beta"], str(tmp_path))
    assert same["existing_count"] is None and same["write"] is False

    # A subset still asks: the run would use more keywords than were typed.
    subset = krp.plan_keyword_run(None, ["topic"], str(tmp_path))
    assert subset["existing_count"] == 3 and subset["write"] is False


def test_added_keywords_are_written_at_apply(tmp_path):
    selected = tmp_path / "keywords_topic.csv"
    selected.write_text("keyword\nalpha\n")
    plan = krp.plan_keyword_run(str(selected), ["ALPHA", "gamma"], str(tmp_path))
    assert plan["added_keywords"] == ["gamma"] and plan["write"]
    assert selected.read_text() == "keyword\nalpha\n"
    krp.apply_keyword_plan(plan)
    assert selected.read_text() == "alpha\ngamma\n"

    nothing_new = krp.plan_keyword_run(str(selected), ["alpha"], str(tmp_path))
    assert nothing_new["write"] is False and krp.apply_keyword_plan(nothing_new) is False


def test_input_csv_env_overrides_config():
    """M3: the launcher names the keyword file in the environment, not in config.yml."""
    import subprocess
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = "import serp_audit; print('INPUT=' + serp_audit.INPUT_FILE)"

    def input_file(value):
        env = {**os.environ, krp.INPUT_CSV_ENV: value}
        out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env,
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-500:]
        return [l for l in out.stdout.splitlines() if l.startswith("INPUT=")][0][6:]

    assert input_file("keywords_from_env.csv") == "keywords_from_env.csv"
    assert input_file("") != ""                    # empty: falls back to config.yml


# --- the launcher: nothing is written until the run starts ---------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from tk_probe import tkinter_usable
    if not tkinter_usable():
        pytest.skip("no usable Tk display")
    import tkinter as tk
    import run_control as rc
    monkeypatch.syspath_prepend(REPO)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rc, "running_pipeline_processes", lambda *a, **k: [])
    spec = importlib.util.spec_from_file_location("serp_me", os.path.join(REPO, "serp-me.py"))
    serp_me = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serp_me)
    monkeypatch.setattr(serp_me, "get_report_model_options",
                        lambda settings, **k: [])
    monkeypatch.setattr(serp_me, "running_pipeline_processes", lambda *a, **k: [])

    (tmp_path / "config.yml").write_text("# keep\nfiles:\n  input_csv: old.csv\n"
                                         "  output_json: output/old.json\n")
    (tmp_path / "keywords_topic.csv").write_text("alpha\n")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "market_analysis_topic_20261114_0900.json").write_text("{}")

    root = tk.Tk()
    root.withdraw()
    app = serp_me.SerpLauncherApp(root)
    app.refresh_keyword_file_options()
    app.started = []
    monkeypatch.setattr(serp_me.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: app.started.append(args)})())

    def select(script_file):
        idx = next(i for i, s in app.listbox_to_script_index.items()
                   if app.scripts[s].get("file") == script_file)
        app.script_listbox.selection_clear(0, "end")
        app.script_listbox.selection_set(idx)
        display = next(d for d, p in app.keyword_file_options.items()
                       if p and os.path.basename(p) == "keywords_topic.csv")
        app.keyword_file_var.set(display)
        app.new_keywords_var.set("gamma")

    app.select = select
    app.serp_me = serp_me
    yield app
    app.run_control.finish()
    root.destroy()


def _files(folder):
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()}


def test_cancelled_run_changes_no_file(launcher, tmp_path, monkeypatch):
    before = _files(tmp_path)
    asked = []
    monkeypatch.setattr(launcher.serp_me.messagebox, "askyesno",
                        lambda title, *a, **k: asked.append(title) or False)
    launcher.feasibility_completed = False
    launcher.select("generate_content_brief.py")

    launcher.run_script()                       # cancelled at the feasibility prompt

    assert asked == ["Prerequisite: Feasibility Analysis"]
    assert launcher.started == [] and not launcher.run_control.running
    assert _files(tmp_path) == before           # keyword file and config.yml untouched


def test_pipeline_start_writes_the_keyword_file_and_not_config(launcher, tmp_path):
    config_before = (tmp_path / "config.yml").read_bytes()
    launcher.select("run_pipeline.py")

    launcher.run_script()

    assert len(launcher.started) == 1
    cmd, env, cwd = launcher.started[0]
    assert env[krp.INPUT_CSV_ENV] == "keywords_topic.csv"
    assert (tmp_path / "keywords_topic.csv").read_text() == "alpha\ngamma\n"     # M5
    assert (tmp_path / "config.yml").read_bytes() == config_before              # M2, M3


def test_existing_keyword_file_question_can_cancel_the_run(launcher, tmp_path, monkeypatch):
    """M4 in the launcher: new keywords, no file selected, the named file exists."""
    before = _files(tmp_path)
    asked = []
    monkeypatch.setattr(launcher.serp_me.messagebox, "askyesno",
                        lambda title, *a, **k: asked.append(title) or False)
    launcher.select("run_pipeline.py")
    launcher.keyword_file_var.set(next(d for d, p in launcher.keyword_file_options.items()
                                       if not p))
    launcher.new_keywords_var.set("topic, zeta")

    launcher.run_script()

    assert asked == ["Keyword File Exists"]
    assert launcher.started == [] and not launcher.run_control.running
    assert _files(tmp_path) == before
