"""brief_llm.py — the LLM call that writes the report and the advisory briefing.

Purpose: One call, two dialects. An ``anthropic`` provider uses the Anthropic
         SDK; an ``openai`` provider (OpenAI, Google's compatible endpoint,
         DeepSeek, local) gets a /chat/completions request. Provider and
         models come from report_llm.py, never from this file.
Spec:    serp_tool1_improvements_spec.md#I.5;
         docs/plan_google_report_model_2026-11-14.md#G2, #G3, #G4, #G5
Tests:   tests/test_brief_llm_providers.py
"""

import requests

import report_llm
from http_retry import post_with_transient_retry
from report_llm import ReportLLMError

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

# What each dialect reports for a finished answer, one that hit the token limit,
# and a refusal. Any reason not listed as complete is a failure: an unknown
# reason must not let a partial report through.
COMPLETE_REASONS = {"anthropic": {"end_turn", "stop_sequence"}, "openai": {"stop"}}
TRUNCATED_REASONS = {"anthropic": {"max_tokens"}, "openai": {"length"}}
REFUSED_REASONS = {"anthropic": {"refusal"}, "openai": {"content_filter"}}
ERROR_DETAIL_CHARS = 300


def progress(message):
    print(message, flush=True)


def _scrub(text, provider):
    return str(text).replace(provider.api_key, "***") if provider.api_key else str(text)


def _call_anthropic(provider, system_prompt, messages, model, max_tokens, timeout):
    if not ANTHROPIC_AVAILABLE:
        raise ReportLLMError("anthropic package not installed.")
    options = {"api_key": provider.api_key, "timeout": timeout}
    if provider.base_url:
        options["base_url"] = provider.base_url
    client = anthropic.Anthropic(**options)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    chunks = [getattr(block, "text", None) for block in response.content]
    return "\n".join(c for c in chunks if c).strip(), getattr(response, "stop_reason", None)


def _call_openai(provider, system_prompt, messages, model, max_tokens, timeout):
    response = post_with_transient_retry(
        provider.name,
        provider.base_url.rstrip("/") + "/chat/completions",
        {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
        {"model": model, "max_tokens": max_tokens,
         "messages": [{"role": "system", "content": system_prompt}] + messages},
        batch_desc=f"report ({model})",
        timeout=timeout,
        post=requests.post,
    )
    if response is None:
        raise ReportLLMError(f"{provider.name}: no response from the provider (network failure).")
    if not response.ok:
        raise ReportLLMError(
            f"{provider.name}: HTTP {response.status_code} for model {model}: "
            f"{_scrub(response.text[:ERROR_DETAIL_CHARS], provider)}")
    try:
        choice = (response.json().get("choices") or [{}])[0]
    except ValueError as exc:
        raise ReportLLMError(f"{provider.name}: the response was not JSON.") from exc
    message = choice.get("message") or {}
    reason = "content_filter" if message.get("refusal") else choice.get("finish_reason")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ReportLLMError(
            f"{provider.name}: the answer was {type(content).__name__}, not text.")
    return content.strip(), reason


_CALLERS = {"anthropic": _call_anthropic, "openai": _call_openai}


def run_llm_report(system_prompt, user_prompt, model, max_tokens, prior_response=None,
                   correction_message=None, provider=None, timeout=None):
    """Return the model's answer, or raise ReportLLMError.

    ``provider`` is a report_llm.Provider; when omitted it is resolved from
    config.yml. An empty, refused or cut-off answer raises (G4): a short report
    must never be written as if it were complete.
    """
    if prior_response is not None and not correction_message:
        raise RuntimeError("correction_message is required when prior_response is provided.")
    if not model:
        raise ReportLLMError("No model was given and none is set under report_llm in config.yml.")
    if provider is None:
        settings = report_llm.load_settings()
        provider = report_llm.resolve_provider(settings)
        timeout = timeout or settings.timeout_seconds
    timeout = timeout or report_llm.DEFAULT_TIMEOUT_SECONDS

    messages = [{"role": "user", "content": user_prompt}]
    if prior_response is not None:
        messages += [
            {"role": "assistant", "content": prior_response},
            {"role": "user", "content": correction_message},
        ]
    progress(f"[7/7] Calling {provider.name} model {model}...")
    text, reason = _CALLERS[provider.dialect](
        provider, system_prompt, messages, model, max_tokens, timeout)
    label = f"{provider.name} model {model}"
    if reason in TRUNCATED_REASONS[provider.dialect]:
        raise ReportLLMError(
            f"{label}: the answer was cut off at the {max_tokens}-token limit; nothing was written.")
    if reason in REFUSED_REASONS[provider.dialect]:
        raise ReportLLMError(f"{label}: the model refused or the answer was filtered.")
    if not text:
        raise ReportLLMError(f"{label}: the answer was empty (finish reason: {reason}).")
    if reason not in COMPLETE_REASONS[provider.dialect]:
        raise ReportLLMError(
            f"{label}: unexpected finish reason {reason!r}; the answer may be incomplete, "
            "so nothing was written.")
    return text
