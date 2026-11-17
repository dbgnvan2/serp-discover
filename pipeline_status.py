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
# A run whose outputs are all on disk but which covers fewer keywords than it
# was asked for: one keyword's SERP fetch returned nothing. The outputs are
# real and usable for the keywords that did return, so they are kept and
# config.yml points at them — but the exit code is not 0, so the run does not
# become the baseline a later run's rank deltas are measured against, and the
# pipeline says so instead of printing a clean success (finding D-C-13).
EXIT_PARTIAL = 2

# The one script whose exit code 1 means "ran, and found a difference".
MISMATCH_SCRIPT = "validate_xlsx_vs_json.py"

# The scripts whose exit code 2 means "ran, outputs written, fewer keywords
# than asked for": the audit, and run_pipeline.py, which propagates the audit's
# code. Elsewhere 2 is an ordinary failure: validate_xlsx_vs_json.py returns it
# when the comparison itself raised.
PARTIAL_SCRIPTS = ("serp_audit.py", "run_pipeline.py")


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


def finish_run(written, paths, config_path="config.yml", input_csv=None,
               incomplete_keywords=None):
    """End-of-run status for the audit. Returns the process exit code.

    All outputs written: record their paths, and the keyword file they came
    from (``input_csv``), in config.yml. Any output missing:
    the run failed, config.yml is left alone, and the outputs that were written
    are renamed ``<name>.failed`` so steps that pick the newest
    ``market_analysis_*.json`` do not use a partial run.

    "Written" is checked against the files, not only against the caller's
    flags. The flags are set in-process straight after each write, so a
    truncated, deleted or renamed output used to return ``EXIT_OK`` — and
    since review chunk D1 that exit code is what stamps ``runs.completed_at``,
    which ``metrics.py`` then trusts as "this run's history is sound"
    (P6: verify status against the artifact).

    ``incomplete_keywords`` is the keywords the run was asked for that
    produced no SERP data. Every output written and some keywords missing is a
    partial run: the outputs are kept and recorded, and the return is
    ``EXIT_PARTIAL`` rather than ``EXIT_OK``.
    """
    missing = missing_outputs(written)
    if not missing:
        # Every path the caller named, not just the three config keys: the
        # handoff file is the one Tool 2 reads.
        gone = absent_files([paths.get(name) for name in written])
        if gone:
            missing = [name for name in written
                       if not paths.get(name) or paths.get(name) in gone]
            logging.error(
                f"Run failed: {len(gone)} output(s) the run reported as "
                f"written are not on disk: {', '.join(str(g) for g in gone)}")
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
        if input_csv:
            cfg["files"]["input_csv"] = input_csv
        save_yaml_preserving_comments(config_path, cfg)
        print(f"Updated {config_path}: output paths set to {paths['json']}")
    except Exception as e:
        logging.error(f"Run failed: could not update {config_path} output paths ({e}). "
                      "Later steps would read the previous run's files.")
        return EXIT_FAILED
    if incomplete_keywords:
        logging.warning(
            f"Run is partial: {len(incomplete_keywords)} keyword(s) produced no "
            f"SERP data and are absent from every output: "
            f"{', '.join(str(k) for k in incomplete_keywords)}. The outputs were "
            f"kept and recorded; this run will not be used as a rank-delta "
            f"baseline.")
        return EXIT_PARTIAL
    return EXIT_OK


def absent_files(paths):
    """The paths that do not exist on disk (or are empty strings)."""
    return [p for p in paths if not p or not os.path.exists(p)]


def exit_label(script, code, stop_reason=None):
    """The launcher's status word for a finished process.

    ``stop_reason`` is set when the launcher itself ended the run ("stopped",
    "timed out"); a run that still exited 0 finished before the signal landed.
    """
    if code == 0:
        return "SUCCESS"
    if stop_reason:
        return stop_reason.upper()
    if code == EXIT_PARTIAL and os.path.basename(script or "") in PARTIAL_SCRIPTS:
        return "PARTIAL"
    if code == 1 and os.path.basename(script or "") == MISMATCH_SCRIPT:
        return "MISMATCH"
    return f"FAILED (exit {code})"
