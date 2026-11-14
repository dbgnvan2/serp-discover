"""A failed audit or pipeline run must exit non-zero and say why.

Spec: docs/plan_config_save_exit_codes_2026-11-14.md (B1-B5)
"""

import json

import pytest

import pipeline_status as ps
import run_pipeline
import serp_audit
import validate_xlsx_vs_json


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """serp_audit.main() with no network, no enrichment, running in tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(serp_audit, "setup_logging", lambda run_id: None)
    monkeypatch.setattr(serp_audit, "SERPAPI_AVAILABLE", True)
    monkeypatch.setattr(serp_audit, "API_KEY", "test-key")
    monkeypatch.setattr(serp_audit, "ENRICHMENT_ENABLED", False)
    monkeypatch.setattr(serp_audit, "FEASIBILITY_ENABLED", False)
    monkeypatch.setattr(serp_audit, "load_keywords", lambda path: ["alpha", "beta"])
    monkeypatch.setattr(serp_audit, "expand_keywords_for_ai",
                        lambda kws: [(k, k, "base") for k in kws])
    monkeypatch.setattr(serp_audit, "fetch_autocomplete", lambda kw: None)
    monkeypatch.setattr(serp_audit.time, "sleep", lambda s: None)
    monkeypatch.setattr(serp_audit, "IntentClassifier", lambda: object())
    for name in ("OUTPUT_JSON", "OUTPUT_FILE", "OUTPUT_MD"):
        monkeypatch.setattr(serp_audit, name, str(tmp_path / f"out.{name.lower()}"))
    return serp_audit


def test_missing_key_exits_nonzero(audit, monkeypatch):
    monkeypatch.setattr(audit, "API_KEY", "")
    assert audit.main() == ps.EXIT_FAILED


def test_missing_csv_exits_nonzero(audit, monkeypatch):
    monkeypatch.setattr(audit, "load_keywords", lambda path: None)
    assert audit.main() == ps.EXIT_FAILED


def test_zero_fetched_exits_nonzero(audit, tmp_path, monkeypatch, capsys):
    calls = []

    def no_data(keyword, run_id):
        calls.append(keyword)
        return {}, {}, {"run_id": run_id}

    monkeypatch.setattr(audit, "fetch_serp_data", no_data)

    assert audit.main() == ps.EXIT_FAILED
    assert calls == ["alpha", "beta"]
    assert "Fetched 0 of 2 queries" in capsys.readouterr().out
    # no outputs, no config.yml: only the run's own state under raw/
    assert [p.name for p in tmp_path.iterdir()] == ["raw"]
    state = json.loads(next(tmp_path.glob("raw/*/run_state.json")).read_text())
    assert state["status"] == "failed"


def test_failed_queries_are_counted_and_listed():
    failed = [{"query": "beta", "source_keyword": "beta", "reason": "no SERP data returned"}]
    summary = ps.fetch_summary(3, failed)
    assert summary == {"planned": 3, "fetched": 2, "failed": failed, "pivot_failed": []}
    line = ps.fetch_summary_line(summary)
    assert line.startswith("Fetched 2 of 3 queries") and "beta" in line
    assert ps.fetch_summary_line(ps.fetch_summary(3, [])) == "Fetched 3 of 3 queries"


def test_validator_ignores_fetch_summary():
    keys = {spec.json_key for spec in validate_xlsx_vs_json.SPECS}
    assert keys and "fetch_summary" not in keys


def _outputs(tmp_path, written):
    paths = {name: str(tmp_path / f"run.{name}") for name in written}
    for name, ok in written.items():
        if ok:
            open(paths[name], "w").write(name)
    return paths


def test_write_failure_exits_nonzero_and_leaves_config_paths(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("# keep\nfiles:\n  output_json: previous.json\n")
    written = {"json": True, "xlsx": False, "md": True, "handoff": True}
    paths = _outputs(tmp_path, written)

    assert ps.finish_run(written, paths, str(config)) == ps.EXIT_FAILED

    assert config.read_text() == "# keep\nfiles:\n  output_json: previous.json\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "config.yml", "run.handoff.failed", "run.json.failed", "run.md.failed"]


def test_complete_run_exits_zero_and_records_paths(tmp_path):
    import yaml
    config = tmp_path / "config.yml"
    config.write_text("files:\n  output_json: previous.json\n  input_csv: k.csv\n")
    written = {"json": True, "xlsx": True, "md": True, "handoff": True}
    paths = _outputs(tmp_path, written)

    assert ps.finish_run(written, paths, str(config)) == ps.EXIT_OK

    assert yaml.safe_load(config.read_text())["files"] == {
        "output_json": paths["json"], "output_xlsx": paths["xlsx"],
        "output_md": paths["md"], "input_csv": "k.csv"}
    assert all((tmp_path / f"run.{n}").exists() for n in written)


def test_config_update_failure_exits_nonzero(tmp_path):
    written = {"json": True, "xlsx": True, "md": True}
    paths = _outputs(tmp_path, written)
    assert ps.finish_run(written, paths, str(tmp_path / "no_such_dir" / "config.yml")) == ps.EXIT_FAILED


def test_run_pipeline_fails_when_outputs_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yml").write_text(
        "files:\n  output_xlsx: gone.xlsx\n  output_json: gone.json\n")
    steps = []
    monkeypatch.setattr(run_pipeline, "run_command", lambda cmd, description: steps.append(description))

    with pytest.raises(SystemExit) as stop:
        run_pipeline.main()

    out = capsys.readouterr().out
    assert stop.value.code == ps.EXIT_FAILED
    assert len(steps) == 1                           # only the audit ran
    assert "gone.xlsx" in out and "Finished Successfully" not in out


def test_run_pipeline_runs_every_step_when_outputs_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.xlsx").write_text("x")
    (tmp_path / "a.json").write_text(json.dumps({}))
    (tmp_path / "config.yml").write_text("files:\n  output_xlsx: a.xlsx\n  output_json: a.json\n")
    steps = []
    monkeypatch.setattr(run_pipeline, "run_command", lambda cmd, description: steps.append(cmd[1]))

    run_pipeline.main()

    assert steps == ["serp_audit.py", "validate_xlsx_vs_json.py", "verify_enrichment.py",
                     "generate_domain_override_candidates.py"]
    assert "Finished Successfully" in capsys.readouterr().out


@pytest.mark.parametrize("script,code,label", [
    ("serp_audit.py", 0, "SUCCESS"),
    ("serp_audit.py", 1, "FAILED (exit 1)"),
    ("run_pipeline.py", 1, "FAILED (exit 1)"),
    ("validate_xlsx_vs_json.py", 1, "MISMATCH"),
    ("/abs/path/validate_xlsx_vs_json.py", 1, "MISMATCH"),
    ("validate_xlsx_vs_json.py", 2, "FAILED (exit 2)"),
    ("", -9, "FAILED (exit -9)"),
])
def test_exit_label(script, code, label):
    assert ps.exit_label(script, code) == label
