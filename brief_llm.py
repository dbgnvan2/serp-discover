"""brief_llm.py — Anthropic LLM call wrapper for content brief pipeline.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import os
import re

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False


def progress(message):
    print(message, flush=True)


MAIN_REPORT_DEFAULT_MODEL = "claude-opus-4-6"

ADVISORY_DEFAULT_MODEL = "claude-sonnet-4-20250514"

SUPPORTED_REPORT_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-opus-4-20250514",
    "claude-3-7-sonnet-20250219",
]


def run_llm_report(system_prompt, user_prompt, model, max_tokens, prior_response=None, correction_message=None):
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package not installed.")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    progress(f"[7/7] Calling Anthropic model {model}...")
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": user_prompt}]
    if prior_response is not None:
        if not correction_message:
            raise RuntimeError("correction_message is required when prior_response is provided.")
        messages = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": prior_response},
            {"role": "user", "content": correction_message},
        ]
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
    chunks = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()

