"""process_config.py — apply every process-wide policy from one loaded config.

`config.yml` carries settings that are not passed down as arguments but set
once per process: the outbound retry and timeout policy (`http_retry`) and the
SQLite lock wait (`db_connect`). Six loaders in this repo read `config.yml`,
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

import db_connect
import http_retry


def apply(cfg: dict | None) -> dict:
    """Set this process's policies from *cfg*; return the outbound policy.

    `None` — the config file is absent — resets every policy to its
    documented default rather than leaving whatever a previous loader set.
    The GUI calls these loaders in-process, one after another, so inheriting
    is a real outcome and not a theoretical one.
    """
    policy = http_retry.apply_retry_policy(cfg)
    db_connect.apply_lock_timeout(cfg)
    return policy
