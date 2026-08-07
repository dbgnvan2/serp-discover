"""Tests for report_models — live-sourced report-model dropdown with fallback.

Purpose: Verify the dropdown options come from the live model list when
         available, fall back to the static list on any failure, and never
         surface retired/non-Claude IDs.
Spec:    follow-up to the advisory-model 404 fix (2026-08-06)
Tests:   tests/test_report_models.py

No tkinter and no network: the live loader is injected.
"""

import sys
import types

import report_models
from report_models import (
    DEFAULT_REPORT_MODELS,
    get_report_model_options,
    resolve_default,
)


def test_fallback_when_loader_raises():
    """Any loader error returns the static fallback."""
    def boom():
        raise RuntimeError("no shared config")

    assert get_report_model_options(loader=boom) == DEFAULT_REPORT_MODELS


def test_fallback_when_live_list_empty():
    """An empty live list returns the static fallback, not an empty dropdown."""
    assert get_report_model_options(loader=lambda: []) == DEFAULT_REPORT_MODELS


def test_fallback_when_no_claude_models():
    """A live list with no Claude models returns the fallback."""
    assert get_report_model_options(loader=lambda: ["gpt-4o", "gemini-2.5-pro"]) == (
        DEFAULT_REPORT_MODELS
    )


def test_retired_id_never_appears():
    """A retired id present in the fallback but absent from the live list is dropped."""
    live = ["claude-opus-4-6", "claude-sonnet-4-6"]
    options = get_report_model_options(loader=lambda: live)
    assert "claude-sonnet-4-20250514" not in options
    assert set(options) == set(live)


def test_preferred_ordering_then_sorted_rest():
    """Preferred (DEFAULT order) models come first; other live Claude models sorted after."""
    live = [
        "claude-sonnet-4-6",          # preferred (index 4)
        "claude-opus-4-6",            # preferred (index 2)
        "claude-sonnet-4-5-20250929",  # not preferred
        "claude-opus-5",              # not preferred
        "gpt-4o",                     # non-Claude, filtered out
    ]
    options = get_report_model_options(loader=lambda: live)
    assert options == [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-5",
        "claude-sonnet-4-5-20250929",
    ]


def test_default_model_present_in_live_result():
    """The GUI default (claude-opus-4-6) survives when the live list contains it."""
    live = ["claude-opus-4-8", "claude-opus-4-6", "claude-sonnet-5"]
    options = get_report_model_options(loader=lambda: live)
    assert "claude-opus-4-6" in options


def test_custom_fallback_respected():
    """An explicit fallback is used when the loader fails."""
    fb = ["claude-opus-4-6"]
    assert get_report_model_options(fallback=fb, loader=lambda: (_ for _ in ()).throw(OSError)) == fb


def test_on_error_called_with_exception_on_fallback():
    """A live-fetch failure invokes on_error so the caller can surface it (P2)."""
    seen = []

    def boom():
        raise RuntimeError("bad keys file")

    opts = get_report_model_options(loader=boom, on_error=seen.append)
    assert opts == DEFAULT_REPORT_MODELS
    assert len(seen) == 1 and isinstance(seen[0], RuntimeError)
    assert str(seen[0]) == "bad keys file"


def test_on_error_not_called_on_success():
    """on_error stays silent when the live fetch succeeds."""
    seen = []
    get_report_model_options(loader=lambda: ["claude-opus-4-6"], on_error=seen.append)
    assert seen == []


def test_resolve_default_keeps_preferred_when_offered():
    assert resolve_default("claude-opus-4-6", ["claude-opus-4-8", "claude-opus-4-6"]) == (
        "claude-opus-4-6"
    )


def test_resolve_default_falls_back_when_preferred_retired():
    """When the preferred default was retired (absent), fall back to the first live option."""
    assert resolve_default("claude-opus-4-6", ["claude-opus-4-8", "claude-sonnet-5"]) == (
        "claude-opus-4-8"
    )


def test_resolve_default_returns_preferred_when_options_empty():
    assert resolve_default("claude-opus-4-6", []) == "claude-opus-4-6"


def test_default_loader_wiring(monkeypatch):
    """_default_loader resolves the provider, falls through app->no-arg, and passes timeout."""
    calls = {"apps": []}

    def resolve_provider(app=None):
        calls["apps"].append(app)
        if app is not None:
            raise RuntimeError("no app mapping")  # force the no-arg fallback
        return "PROVIDER"

    def list_models(provider, timeout=None):
        calls["provider"] = provider
        calls["timeout"] = timeout
        return ["claude-opus-4-6"]

    fake = types.ModuleType("llm_providers")
    fake.resolve_provider = resolve_provider
    fake.list_models = list_models
    monkeypatch.setitem(sys.modules, "llm_providers", fake)

    result = report_models._default_loader(timeout=7)
    assert result == ["claude-opus-4-6"]
    assert calls["apps"] == ["serp-discover", None]  # app-keyed first, then no-arg fallback
    assert calls["provider"] == "PROVIDER"
    assert calls["timeout"] == 7
