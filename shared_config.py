"""
shared_config.py
~~~~~~~~~~~~~~~~
Single owner of the out-of-repo shared config contract.

The SERP tools share one optional JSON file with Tool 2 (the competitor
audit tool). It lives OUTSIDE this repo — by default one directory above
it — and, when present, overrides selected in-repo settings so both tools
agree on client identity and scoring thresholds.

Spec: seo_geo_deferred_spec_v1.md#C.9 — exactly one module constructs the
path, handles the ``SERP_SHARED_CONFIG`` env override, and turns a
malformed file into one loud warning plus safe defaults. Consumers
(``serp_audit.py``, ``feasibility.py``) import from here; they must not
duplicate the path logic.

Schema and precedence are documented in ``docs/config_reference.md``
("Shared config"). Precedence: shared config > ``config.yml`` >
``serp_vocab.yml`` defaults (stop words) / code defaults (thresholds).

Do NOT remove this file's authority: Tool 2 also consumes it (decision
gate D-5 in seo_geo_deferred_spec_v1.md).
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_FILENAME = "shared_config.json"
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", _FILENAME
)

# Env var that redirects loading (useful for tests and non-standard
# deploy layouts where the shared file is not one directory up).
ENV_VAR = "SERP_SHARED_CONFIG"


def shared_config_path() -> str:
    """Return the shared config path: $SERP_SHARED_CONFIG or ../shared_config.json."""
    return os.environ.get(ENV_VAR) or _DEFAULT_PATH


def load_shared_config(path: str | None = None) -> dict:
    """Load the shared cross-tool config.

    Returns ``{}`` when the file is absent or malformed. A malformed file
    logs ONE warning naming the file (a silently-ignored shared config
    changing every feasibility verdict is worse than a loud fallback).
    One INFO line states whether the file was found and which top-level
    keys were consumed.
    """
    fpath = path or shared_config_path()
    if not os.path.exists(fpath):
        logger.info(
            "Shared config not found at %s — using in-repo defaults.", fpath
        )
        return {}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(
                f"top-level value must be a JSON object, got {type(data).__name__}"
            )
    except Exception as exc:
        logger.warning(
            "Malformed shared config at %s (%s) — falling back to in-repo defaults.",
            fpath, exc,
        )
        return {}
    logger.info(
        "Loaded shared config from %s (keys consumed: %s).",
        fpath, ", ".join(sorted(data)) if data else "none",
    )
    return data
