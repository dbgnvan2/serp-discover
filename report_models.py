"""Report-model dropdown options for serp-me.

Purpose: Supply the Anthropic model IDs offered in the GUI report-model
         dropdowns from the live model list when reachable, so retired
         snapshots don't linger as 404 landmines, with a static fallback.
Spec:    follow-up to the advisory-model 404 fix (2026-08-06)
Tests:   tests/test_report_models.py

Retired hardcoded IDs (e.g. claude-sonnet-4-20250514) previously sat in the
dropdown and 404'd when selected. Sourcing the list from the shared
global-api-config live model call removes that class of failure; the static
list below is the fallback when the shared config or network is unavailable.
"""

from __future__ import annotations

import os
import sys

# Static fallback, and the preferred ordering applied to the live list.
# Verified against the live Anthropic model list on 2026-08-06.
DEFAULT_REPORT_MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]


def _global_config_dir() -> str:
    """Locate global-api-config (sibling of this repo under ProjectsLocal).

    Override with the GLOBAL_API_CONFIG_DIR env var.
    """
    return os.environ.get("GLOBAL_API_CONFIG_DIR") or os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "global-api-config")
    )


# Short timeout so a degraded-but-connected network can't block GUI startup for
# long. list_models does a single GET with no internal retry, so this is a true
# ceiling. Offline fails fast (connection refused) well under this.
_LIVE_FETCH_TIMEOUT = 3


def _default_loader(timeout: int = _LIVE_FETCH_TIMEOUT) -> list[str]:
    """Fetch live Anthropic model IDs via the shared global-api-config module.

    Raises on any failure (missing module/keys file, network error); the caller
    falls back to DEFAULT_REPORT_MODELS.
    """
    cfg_dir = _global_config_dir()
    if cfg_dir not in sys.path:
        # append, not insert(0): global-api-config must not shadow a repo module
        # of the same name.
        sys.path.append(cfg_dir)
    import llm_providers  # noqa: WPS433 - optional shared dependency

    try:
        provider = llm_providers.resolve_provider(app="serp-discover")
    except Exception:
        provider = llm_providers.resolve_provider()
    return list(llm_providers.list_models(provider, timeout=timeout))


def get_report_model_options(fallback=None, loader=None, on_error=None):
    """Return report-model dropdown options.

    Tries the live Anthropic model list (Claude models only), ordered with
    DEFAULT_REPORT_MODELS first, then any other live Claude models sorted.
    Returns `fallback` (DEFAULT_REPORT_MODELS) on any error or empty result.

    `loader` is injectable for tests. `on_error(exc)` is called with the caught
    exception when the live fetch fails and the static fallback is used, so the
    caller can surface a misconfiguration (bad keys file, auth error) rather
    than have it look identical to a benign offline run.
    """
    fb = list(fallback) if fallback else list(DEFAULT_REPORT_MODELS)
    load = loader or _default_loader
    try:
        models = load()
    except Exception as exc:
        if on_error is not None:
            on_error(exc)
        return fb
    claude = [m for m in models if isinstance(m, str) and m.startswith("claude")]
    if not claude:
        return fb
    preferred = [m for m in DEFAULT_REPORT_MODELS if m in claude]
    rest = sorted(m for m in claude if m not in DEFAULT_REPORT_MODELS)
    return preferred + rest


def resolve_default(preferred, options):
    """Return a valid default selection given a preferred model and the options.

    Keeps `preferred` when it is actually offered; otherwise falls back to the
    first (preferred-first, guaranteed-live) option so the GUI never defaults to
    a model that was dropped from the dropdown because it was retired. Returns
    `preferred` unchanged when `options` is empty.
    """
    if preferred in options:
        return preferred
    return options[0] if options else preferred
