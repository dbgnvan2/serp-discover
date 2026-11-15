"""Report-model dropdown options for serp-me.

Purpose: Offer the configured provider's live models in the launcher's two
         report-model dropdowns, so a retired model ID cannot sit there and
         fail when picked. Which IDs are offered is set in config.yml
         (report_llm.model_include / model_exclude). Offline, the dropdown
         holds the models named in config.yml.
Spec:    docs/plan_google_report_model_2026-11-14.md#G7
Tests:   tests/test_report_models.py
"""

from __future__ import annotations

import report_llm

# Short timeout so a slow network cannot hold up launcher start-up for long.
# list_models is a single GET with no retry, so this is a true ceiling.
_LIVE_FETCH_TIMEOUT = 3
MODEL_ID_PREFIX = "models/"  # Google's list returns "models/<id>"


def configured_models(settings):
    """The models named in config.yml, main first, without duplicates."""
    return list(dict.fromkeys(m for m in (settings.main_model, settings.advisory_model) if m))


def _default_loader(settings, timeout: int = _LIVE_FETCH_TIMEOUT) -> list[str]:
    """The resolved provider's live model IDs. Raises on any failure."""
    registry = report_llm.load_registry()
    if registry is None:
        raise RuntimeError("the shared key registry (global-api-config) was not found")
    provider = report_llm.resolve_provider(settings, registry=registry)
    return list(registry.list_models(provider, timeout=timeout))


def get_report_model_options(settings, loader=None, on_error=None):
    """Dropdown options: the configured models first, then the other live models.

    A live ID is offered when it starts with one of ``settings.model_include``
    (an empty list offers everything) and contains none of
    ``settings.model_exclude``. On any error, or when nothing passes the
    filter, the configured models are returned and ``on_error(exc)`` is called
    so a bad keys file does not look the same as being offline.
    """
    fallback = configured_models(settings)
    try:
        models = loader() if loader else _default_loader(settings)
    except Exception as exc:  # noqa: BLE001 - reported through on_error
        if on_error is not None:
            on_error(exc)
        return fallback
    live = {m.removeprefix(MODEL_ID_PREFIX) for m in models if isinstance(m, str) and m}
    offered = {
        m for m in live
        if (not settings.model_include or m.startswith(settings.model_include))
        and not any(part in m for part in settings.model_exclude)
    }
    if not offered:
        return fallback
    first = [m for m in fallback if m in offered]
    return first + sorted(offered - set(first))


def resolve_default(preferred, options):
    """Return a valid default selection given a preferred model and the options.

    Keeps `preferred` when it is offered; otherwise the first option, so the
    launcher never defaults to a model that is not in the dropdown. Returns
    `preferred` unchanged when `options` is empty.
    """
    if preferred in options:
        return preferred
    return options[0] if options else preferred
