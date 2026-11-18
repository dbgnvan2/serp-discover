"""process_config.py — apply every process-wide policy from one loaded config.

`config.yml` carries settings that are not passed down as arguments but set
once per process: the outbound retry and timeout policy (`http_retry`) and the
SQLite lock wait (`db_connect`). Nine loaders in this repo read `config.yml`,
and each of them has to set that state or the process runs on the import
defaults while the file says otherwise.

Five of the six called `http_retry.apply_retry_policy` directly — a list the
cold review of chunk Y4 had to extend once already, and
`generate_insight_report._load_config` was never on it although it opens the
database. Asking six call sites to remember two policies is how the next one
gets one of them, so there is one function and the loaders call it (P5/P25 —
one config→process mapping, not one per call site).

Spec: docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md
Tests: tests/test_y11_a_rollback_is_not_the_diagnosis.py
"""

import os

import db_connect
import http_retry

#: `config.yml` beside this module — the repo root. Every loader's *default*
#: config path, so the file a run reads does not depend on the directory the
#: command was started in. Eight loaders defaulted to the bare `"config.yml"`,
#: cwd-relative, and the GUI launched `serp_audit.py` with `cwd=os.getcwd()`:
#: start the tool from anywhere else and the config was never found, every
#: policy silently reset to its default, and a configured `database.path` was
#: abandoned for the built-in one — which on an installation that had ever run
#: before exists and reads as a real, stale history (P16/P2, the cold review of
#: chunk Y12). A path a caller passes is still resolved against the cwd, which
#: is what a person typing `--config` means.
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.yml")


def config_path(given=None) -> str:
    """*given*, or the repo's own `config.yml` when no path was named."""
    return DEFAULT_CONFIG_PATH if given is None else given


def apply(cfg: dict | None) -> dict:
    """Set this process's policies from *cfg*; return the outbound policy.

    `None` — the config file is absent — resets every policy to its
    documented default rather than leaving whatever a previous loader set.
    The GUI calls these loaders in-process, one after another, so inheriting
    is a real outcome and not a theoretical one.
    """
    policy = http_retry.apply_retry_policy(cfg)
    db_connect.apply_lock_timeout(cfg)
    db_connect.apply_database_path(cfg)
    return policy
