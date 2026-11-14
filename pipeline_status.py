"""pipeline_status.py — how a pipeline run reports that it failed.

Pure helpers shared by serp_audit.py, run_pipeline.py and the launcher, so the
exit-code rules are tested without a SERP fetch or a GUI.

Spec: docs/plan_config_save_exit_codes_2026-11-14.md (B1-B5)
Tests: tests/test_pipeline_exit_codes.py
"""

import logging
import os

import yaml

from yaml_io import save_yaml_preserving_comments

EXIT_OK = 0
EXIT_FAILED = 1

# The one script whose exit code 1 means "ran, and found a difference".
MISMATCH_SCRIPT = "validate_xlsx_vs_json.py"


def fetch_summary(planned, failed):
    """Counts for one audit run. ``failed`` is a list of
    ``{"query", "source_keyword", "reason"}``."""
    return {"planned": planned, "fetched": planned - len(failed), "failed": list(failed),
            "pivot_failed": []}


def fetch_summary_line(summary):
    line = f"Fetched {summary['fetched']} of {summary['planned']} queries"
    if summary["failed"]:
        names = "; ".join(f"{f['query']} ({f['reason']})" for f in summary["failed"])
        line += f" — {len(summary['failed'])} failed: {names}"
    return line


def missing_outputs(written):
    """Names of the outputs that were not written. ``written`` is {name: bool}."""
    return [name for name, ok in written.items() if not ok]


# Which config.yml ``files`` key each output is recorded under. The handoff
# file has none: Tool 2 finds it by name.
CONFIG_PATH_KEYS = {"json": "output_json", "xlsx": "output_xlsx", "md": "output_md"}


def finish_run(written, paths, config_path="config.yml"):
    """End-of-run status for the audit. Returns the process exit code.

    All outputs written: record their paths in config.yml. Any output missing:
    the run failed, config.yml is left alone, and the outputs that were written
    are renamed ``<name>.failed`` so steps that pick the newest
    ``market_analysis_*.json`` do not use a partial run.
    """
    missing = missing_outputs(written)
    if missing:
        set_aside = []
        for name, ok in written.items():
            path = paths.get(name)
            if ok and path and os.path.exists(path):
                os.replace(path, path + ".failed")
                set_aside.append(path + ".failed")
        logging.error(
            f"Run failed: output not written: {', '.join(missing)}. config.yml output paths "
            f"were left unchanged. Partial outputs kept as: {', '.join(set_aside) or 'none'}")
        return EXIT_FAILED
    try:
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        cfg.setdefault("files", {})
        for name, key in CONFIG_PATH_KEYS.items():
            cfg["files"][key] = paths[name]
        save_yaml_preserving_comments(config_path, cfg)
        print(f"Updated {config_path}: output paths set to {paths['json']}")
    except Exception as e:
        logging.error(f"Run failed: could not update {config_path} output paths ({e}). "
                      "Later steps would read the previous run's files.")
        return EXIT_FAILED
    return EXIT_OK


def absent_files(paths):
    """The paths that do not exist on disk (or are empty strings)."""
    return [p for p in paths if not p or not os.path.exists(p)]


def exit_label(script, code):
    """The launcher's status word for a finished process."""
    if code == 0:
        return "SUCCESS"
    if code == 1 and os.path.basename(script or "") == MISMATCH_SCRIPT:
        return "MISMATCH"
    return f"FAILED (exit {code})"
