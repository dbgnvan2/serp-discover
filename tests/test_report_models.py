"""Tests for report_models — the launcher's report-model dropdown options.

Spec: docs/plan_google_report_model_2026-11-14.md (G7)
No network: the loader is injected.
"""

from types import SimpleNamespace

import report_llm
import report_models
from report_llm import Settings
from report_models import get_report_model_options, resolve_default

SETTINGS = Settings(
    provider="gemini-serp", main_model="gemini-4-hydrogen", advisory_model="gemini-3.8-flash",
    model_include=("gemini-", "claude-"), model_exclude=("tts", "embedding", "image"))
GOOGLE_LIVE = ["models/gemini-4-hydrogen", "models/gemini-4-argon", "models/gemini-3.8-flash",
               "models/gemini-3.8-flash-tts", "models/gemini-embedding-2",
               "models/gemini-3-pro-image", "models/lyria-3.5", "models/gemma-4-31b-it"]


def test_g7_google_models_are_listed_and_filtered():
    options = get_report_model_options(SETTINGS, loader=lambda: GOOGLE_LIVE)
    # configured models first, then the rest sorted; prefix removed; filters applied
    assert options == ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-4-argon"]
    # the same settings work for an Anthropic provider
    claude = ["claude-sonnet-5", "claude-opus-5"]
    assert get_report_model_options(SETTINGS, loader=lambda: claude) == [
        "claude-opus-5", "claude-sonnet-5"]
    # an empty include list offers every live model that is not excluded
    everything = Settings(main_model="x", model_exclude=("tts",))
    assert get_report_model_options(everything, loader=lambda: ["b", "a-tts", "a"]) == ["a", "b"]


def test_g7_defaults_come_from_config():
    options = get_report_model_options(SETTINGS, loader=lambda: GOOGLE_LIVE)
    assert resolve_default(SETTINGS.main_model, options) == "gemini-4-hydrogen"
    assert resolve_default(SETTINGS.advisory_model, options) == "gemini-3.8-flash"
    # a configured model that is no longer live is not offered and not the default
    retired = Settings(main_model="gemini-1-gone", model_include=("gemini-",))
    options = get_report_model_options(retired, loader=lambda: GOOGLE_LIVE)
    assert "gemini-1-gone" not in options
    assert resolve_default(retired.main_model, options) == options[0]
    assert resolve_default("anything", []) == "anything"


def test_g7_offline_fallback_is_the_configured_models():
    seen = []

    def boom():
        raise RuntimeError("offline")

    options = get_report_model_options(SETTINGS, loader=boom, on_error=seen.append)
    assert options == ["gemini-4-hydrogen", "gemini-3.8-flash"]
    assert isinstance(seen[0], RuntimeError)
    # nothing passes the filter: same fallback, and on_error is not called
    seen.clear()
    assert get_report_model_options(
        SETTINGS, loader=lambda: ["models/lyria-3.5"], on_error=seen.append
    ) == ["gemini-4-hydrogen", "gemini-3.8-flash"]
    assert seen == []


def test_g7_default_loader_lists_the_resolved_provider(monkeypatch):
    asked = {}
    provider = SimpleNamespace(name="gemini-serp", dialect="openai", api_key="k",
                               base_url="https://g.test")

    def list_models(given, timeout):
        asked.update(name=given.name, timeout=timeout)
        return ["models/gemini-4-hydrogen"]

    registry = SimpleNamespace(
        resolve_provider=lambda app=None, local_choice=None: provider, list_models=list_models)
    monkeypatch.setattr(report_llm, "load_registry", lambda: registry)
    assert report_models._default_loader(SETTINGS, timeout=7) == ["models/gemini-4-hydrogen"]
    assert asked == {"name": "gemini-serp", "timeout": 7}
