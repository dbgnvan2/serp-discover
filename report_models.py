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


def _default_loader(timeout: int = 5) -> list[str]:
    """Fetch live Anthropic model IDs via the shared global-api-config module.

    Raises on any failure (missing module/keys file, network error); the caller
    falls back to DEFAULT_REPORT_MODELS.
    """
    cfg_dir = _global_config_dir()
    if cfg_dir not in sys.path:
        sys.path.insert(0, cfg_dir)
    import llm_providers  # noqa: WPS433 - optional shared dependency

    try:
        provider = llm_providers.resolve_provider(app="serp-discover")
    except Exception:
        provider = llm_providers.resolve_provider()
    return list(llm_providers.list_models(provider, timeout=timeout))


def get_report_model_options(fallback=None, loader=None):
    """Return report-model dropdown options.

    Tries the live Anthropic model list (Claude models only), ordered with
    DEFAULT_REPORT_MODELS first, then any other live Claude models sorted.
    Returns `fallback` (DEFAULT_REPORT_MODELS) on any error or empty result.
    `loader` is injectable for tests.
    """
    fb = list(fallback) if fallback else list(DEFAULT_REPORT_MODELS)
    load = loader or _default_loader
    try:
        models = load()
    except Exception:
        return fb
    claude = [m for m in models if isinstance(m, str) and m.startswith("claude")]
    if not claude:
        return fb
    preferred = [m for m in DEFAULT_REPORT_MODELS if m in claude]
    rest = sorted(m for m in claude if m not in DEFAULT_REPORT_MODELS)
    return preferred + rest
