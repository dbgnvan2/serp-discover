"""timeouts.py — read a timeout from config without ever getting "no timeout".

Spec: docs/plan_stop_button_serpapi_timeout_2026-11-14.md (T1-T4, S3, S7)
Tests: tests/test_serpapi_timeout.py
"""

import logging

# Fallbacks used when config.yml has no value. 60s is twice the slowest of 296
# real SerpAPI calls in raw/*/serp_api.log (max 30.3s, measured 2026-11-14).
DEFAULT_SERPAPI_TIMEOUT_SECONDS = 60.0


def seconds_from_config(value, default, name):
    """``value`` as a positive number of seconds, else ``default`` with a warning.

    None (key absent) is the default without a warning. Zero, negative,
    non-numeric and boolean values are rejected: none of them may switch a
    timeout off.
    """
    if value is None:
        return float(default)
    try:
        if isinstance(value, bool):
            raise ValueError("boolean")
        seconds = float(value)
        if not 0 < seconds < float("inf"):
            raise ValueError("not a positive number")
    except (TypeError, ValueError):
        logging.warning(f"config {name}={value!r} is not a positive number of seconds; "
                        f"using {default}.")
        return float(default)
    return seconds


def serpapi_timeout(config):
    """The per-call SerpAPI timeout from a loaded config.yml dict."""
    section = config.get("serpapi") if isinstance(config, dict) else None
    value = section.get("timeout_seconds") if isinstance(section, dict) else None
    return seconds_from_config(value, DEFAULT_SERPAPI_TIMEOUT_SECONDS, "serpapi.timeout_seconds")
