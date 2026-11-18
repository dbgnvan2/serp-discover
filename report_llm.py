"""report_llm.py — which provider and models write the report and advisory briefing.

Purpose: Read the ``report_llm`` block of config.yml and resolve its provider
         from the shared key registry (~/.config/llm/keys.json). No model ID and
         no provider name is hardcoded here.
Spec:    docs/plan_google_report_model_2026-11-14.md#G1, #G5, #G7
Tests:   tests/test_brief_llm_providers.py
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

import yaml

import process_config

from timeouts import seconds_from_config

APP_NAME = "serp-discover"
# The Anthropic SDK's own default. A 16,000-token report can take minutes.
DEFAULT_TIMEOUT_SECONDS = 600.0
# Output-token limits used when config.yml sets none (the values in use before
# they became configurable). Models that spend output tokens on hidden
# reasoning need more: see report_llm.main_max_tokens in config.yml.
DEFAULT_MAIN_MAX_TOKENS = 16000
DEFAULT_ADVISORY_MAX_TOKENS = 4000
SUPPORTED_DIALECTS = ("anthropic", "openai")
ENV_PROVIDER_NAME = "anthropic (ANTHROPIC_API_KEY)"


class ReportLLMError(RuntimeError):
    """The report LLM is misconfigured, unreachable, or gave an unusable answer."""


@dataclass(frozen=True)
class Settings:
    provider: str = ""
    main_model: str = ""
    advisory_model: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    main_max_tokens: int = DEFAULT_MAIN_MAX_TOKENS
    advisory_max_tokens: int = DEFAULT_ADVISORY_MAX_TOKENS
    model_include: tuple = ()
    model_exclude: tuple = ()


@dataclass(frozen=True)
class Provider:
    name: str
    dialect: str
    api_key: str = field(repr=False)
    base_url: str = ""


def _strings(value):
    if isinstance(value, str):
        value = [value]
    return tuple(str(v).strip() for v in (value or []) if str(v).strip())


def _token_limit(value, default, name):
    """A positive whole number of tokens, else ``default`` with a warning."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        logging.warning(f"config {name}={value!r} is not a positive whole number; using {default}.")
        return default
    return value


#: The keys in this block that are refused at zero or less: the wait, read by
#: `timeouts.seconds_from_config`, and the two token limits, read by
#: `_token_limit`. Named here so `config_tab_models.positive_only_fields`
#: reads the fact off this loader rather than keeping a list of its own (P32).
#: They were in no table at all, so the GUI saved a typed 0 for a fourth
#: timeout class after chunk Y8 had fixed the other nine — the same fault,
#: surviving because the set was extended by hand (cold review of chunk Y11).
GOVERNED_FIELDS = (
    ("report_llm", "timeout_seconds"),
    ("report_llm", "main_max_tokens"),
    ("report_llm", "advisory_max_tokens"),
)


def settings_from_config(config):
    """The ``report_llm`` block of a loaded config.yml dict. Missing keys are empty."""
    block = config.get("report_llm") if isinstance(config, dict) else None
    block = block if isinstance(block, dict) else {}
    return Settings(
        provider=str(block.get("provider") or "").strip(),
        main_model=str(block.get("main_model") or "").strip(),
        advisory_model=str(block.get("advisory_model") or "").strip(),
        timeout_seconds=seconds_from_config(
            block.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS, "report_llm.timeout_seconds"),
        main_max_tokens=_token_limit(
            block.get("main_max_tokens"), DEFAULT_MAIN_MAX_TOKENS, "report_llm.main_max_tokens"),
        advisory_max_tokens=_token_limit(
            block.get("advisory_max_tokens"), DEFAULT_ADVISORY_MAX_TOKENS,
            "report_llm.advisory_max_tokens"),
        model_include=_strings(block.get("model_include")),
        model_exclude=_strings(block.get("model_exclude")),
    )


def load_settings(config_path=None):
    """The report-LLM settings, with the outbound retry policy applied.

    `brief_llm` calls every provider through `http_retry`, so this config read
    is the brief's only chance to pick up `config.yml http_retry` — without it
    the setting changed the audit's behaviour and silently did nothing here
    (P5, cold review of chunk Y4).
    """
    # No path named means the repo's own config.yml, not the cwd's (the
    # cold review of chunk Y12).
    config_path = process_config.config_path(config_path)
    if not os.path.exists(config_path):
        process_config.apply(None)
        return Settings()
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    process_config.apply(raw)
    return settings_from_config(raw)


def global_config_dir():
    """The shared global-api-config folder (sibling of this repo).

    Override with the GLOBAL_API_CONFIG_DIR env var.
    """
    return os.environ.get("GLOBAL_API_CONFIG_DIR") or os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "global-api-config")
    )


def load_registry():
    """The shared ``llm_providers`` module, or None when it is not on this machine."""
    cfg_dir = global_config_dir()
    if cfg_dir not in sys.path:
        # append, not insert(0): the shared folder must not shadow a repo module.
        sys.path.append(cfg_dir)
    try:
        import llm_providers  # noqa: WPS433 - optional shared dependency
    except ImportError:
        return None
    return llm_providers


_LOAD = object()


def resolve_provider(settings, registry=_LOAD, env=None):
    """The provider that writes the reports.

    Order (llm-integration.md L6): ``report_llm.provider`` in config.yml, then the
    registry's ``apps`` map, then the registry default. A configured provider
    that cannot be resolved is an error: there is no fallback to another
    provider. With nothing configured and no usable registry, the Anthropic
    key in the environment is used, as before this module existed.
    """
    env = os.environ if env is None else env
    registry = load_registry() if registry is _LOAD else registry
    found, failure = None, "the shared key registry (global-api-config) was not found"
    if registry is not None:
        try:
            found = registry.resolve_provider(
                app=APP_NAME, local_choice=settings.provider or None)
        except Exception as exc:  # noqa: BLE001 - any registry failure is reported below
            failure = f"{type(exc).__name__}: {exc}"
    if found is None:
        if settings.provider:
            raise ReportLLMError(
                f"report_llm.provider '{settings.provider}' could not be loaded: {failure}")
        api_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise ReportLLMError(
                f"No report LLM provider: {failure}, and ANTHROPIC_API_KEY is not set.")
        return Provider(ENV_PROVIDER_NAME, "anthropic", api_key)
    provider = Provider(
        name=str(found.name), dialect=str(found.dialect or "").strip().lower(),
        api_key=str(found.api_key or "").strip(), base_url=str(found.base_url or "").strip())
    if provider.dialect not in SUPPORTED_DIALECTS:
        raise ReportLLMError(
            f"Provider '{provider.name}' has dialect '{provider.dialect}'; "
            f"supported: {', '.join(SUPPORTED_DIALECTS)}.")
    if not provider.api_key:
        raise ReportLLMError(f"Provider '{provider.name}' has no api_key in the key registry.")
    if provider.dialect == "openai" and not provider.base_url:
        raise ReportLLMError(f"Provider '{provider.name}' has no base_url in the key registry.")
    return provider
