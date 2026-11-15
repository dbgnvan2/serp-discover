"""Provider and model selection for the report writer.

Spec: docs/plan_google_report_model_2026-11-14.md (G1-G6)
No network: the registry, requests.post and the Anthropic SDK are faked.
"""

import os
import re
from types import SimpleNamespace

import pytest

import brief_llm
import brief_rendering
import http_retry
import report_llm
from report_llm import Provider, ReportLLMError, Settings

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOGLE = Provider("gemini-serp", "openai", "SECRET-KEY", "https://example.test/v1beta/openai/")
CLAUDE = Provider("anthropic", "anthropic", "SECRET-KEY", "")


class FakeRegistry:
    """Stands in for llm_providers: local choice, then the apps map, then the default."""

    def __init__(self, providers, apps=None, default=None):
        self.providers, self.apps, self.default = providers, apps or {}, default

    def resolve_provider(self, app=None, local_choice=None):
        name = local_choice or self.apps.get(app) or self.default
        if name not in self.providers:
            raise KeyError(f"no provider named {name}")
        return SimpleNamespace(name=name, **self.providers[name])


REGISTRY = FakeRegistry(
    {"gemini-serp": {"dialect": "openai", "api_key": "g-key", "base_url": "https://g.test/openai"},
     "anthropic": {"dialect": "anthropic", "api_key": "a-key", "base_url": ""},
     "empty": {"dialect": "openai", "api_key": "", "base_url": "https://e.test"}},
    default="anthropic")


class FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text
        self.ok, self.headers = status < 400, {}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def chat(content="REPORT", finish="stop", **message):
    return FakeResponse(body={"choices": [
        {"finish_reason": finish, "message": {"content": content, **message}}]})


@pytest.fixture
def posts(monkeypatch):
    """Record requests.post calls; replies are taken in order from ``calls.replies``."""
    calls = SimpleNamespace(sent=[], replies=[chat()])

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.sent.append(SimpleNamespace(url=url, headers=headers, json=json, timeout=timeout))
        reply = calls.replies.pop(0) if len(calls.replies) > 1 else calls.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(brief_llm.requests, "post", fake_post)
    monkeypatch.setattr(http_retry.time, "sleep", lambda seconds: None)
    return calls


@pytest.fixture
def sdk(monkeypatch):
    """A fake Anthropic SDK that records the client options and the request."""
    seen = SimpleNamespace(options=None, request=None, stop_reason="end_turn", text="REPORT")

    def create(**request):
        seen.request = request
        return SimpleNamespace(content=[SimpleNamespace(text=seen.text)],
                               stop_reason=seen.stop_reason)

    def client(**options):
        seen.options = options
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    monkeypatch.setattr(brief_llm, "anthropic", SimpleNamespace(Anthropic=client))
    monkeypatch.setattr(brief_llm, "ANTHROPIC_AVAILABLE", True)
    return seen


def test_g1_models_and_provider_come_from_config():
    settings = report_llm.settings_from_config({"report_llm": {
        "provider": "gemini-serp", "main_model": "m-main", "advisory_model": "m-adv",
        "timeout_seconds": 90, "model_include": ["gemini-"], "model_exclude": "tts"}})
    assert settings == Settings("gemini-serp", "m-main", "m-adv", 90.0, ("gemini-",), ("tts",))
    assert report_llm.settings_from_config({}) == Settings()
    assert report_llm.resolve_provider(settings, registry=REGISTRY).name == "gemini-serp"
    # empty provider: the registry's apps map, then its default
    mapped = FakeRegistry(REGISTRY.providers, apps={"serp-discover": "gemini-serp"}, default="anthropic")
    assert report_llm.resolve_provider(Settings(), registry=mapped).name == "gemini-serp"
    assert report_llm.resolve_provider(Settings(), registry=REGISTRY).name == "anthropic"


def test_g1_no_model_id_literal_in_python_source():
    for name in ("brief_llm.py", "serp-me.py", "report_models.py", "report_llm.py",
                 "generate_content_brief.py"):
        with open(os.path.join(REPO, name), encoding="utf-8") as f:
            found = re.findall(r"""["'](?:claude|gemini|gpt)-[\w.\-]+["']""", f.read())
        assert not found, f"{name} hardcodes model IDs: {found}"


def test_g2_openai_dialect_request_shape(posts):
    text = brief_llm.run_llm_report("SYS", "USER", "m1", 123, provider=GOOGLE, timeout=45)
    sent = posts.sent[0]
    assert text == "REPORT"
    assert sent.url == "https://example.test/v1beta/openai/chat/completions"
    assert sent.headers["Authorization"] == "Bearer SECRET-KEY"
    assert sent.timeout == 45
    assert sent.json == {"model": "m1", "max_tokens": 123, "messages": [
        {"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]}


def test_g2_correction_retry_messages(posts):
    brief_llm.run_llm_report("SYS", "USER", "m1", 10, prior_response="DRAFT",
                             correction_message="FIX", provider=GOOGLE)
    assert [m["role"] for m in posts.sent[0].json["messages"]] == [
        "system", "user", "assistant", "user"]
    assert posts.sent[0].json["messages"][2:] == [
        {"role": "assistant", "content": "DRAFT"}, {"role": "user", "content": "FIX"}]


def test_g2_timeout_and_retry(posts):
    posts.replies = [brief_llm.requests.Timeout("slow"), FakeResponse(503, text="busy"), chat()]
    with pytest.raises(ReportLLMError, match="HTTP 503"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    assert len(posts.sent) == http_retry.RETRY_ATTEMPTS

    posts.sent.clear()
    posts.replies = [FakeResponse(503, text="busy"), chat("SECOND TRY")]
    assert brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE) == "SECOND TRY"
    assert len(posts.sent) == 2

    posts.replies = [brief_llm.requests.Timeout("slow")]
    with pytest.raises(ReportLLMError, match="network failure"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)


def test_g2_key_is_not_logged(posts, capsys, caplog):
    posts.replies = [FakeResponse(401, text="bad key SECRET-KEY supplied")]
    with pytest.raises(ReportLLMError) as raised:
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    shown = str(raised.value) + capsys.readouterr().out + caplog.text + repr(GOOGLE)
    assert "SECRET-KEY" not in shown
    assert "gemini-serp" in str(raised.value) and "m1" in str(raised.value)


def test_g3_anthropic_request_unchanged(sdk):
    text = brief_llm.run_llm_report("SYS", "USER", "c1", 500, provider=CLAUDE, timeout=77)
    assert text == "REPORT"
    assert sdk.options == {"api_key": "SECRET-KEY", "timeout": 77}
    assert sdk.request == {
        "model": "c1", "max_tokens": 500,
        "system": [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "USER"}]}


def test_g3_env_key_fallback_without_registry():
    provider = report_llm.resolve_provider(
        Settings(), registry=None, env={"ANTHROPIC_API_KEY": "env-key"})
    assert (provider.dialect, provider.api_key) == ("anthropic", "env-key")
    with pytest.raises(ReportLLMError, match="ANTHROPIC_API_KEY is not set"):
        report_llm.resolve_provider(Settings(), registry=None, env={})


def test_g4_truncated_answer_is_a_failure(posts, sdk):
    posts.replies = [chat("HALF A REPORT", finish="length")]
    with pytest.raises(ReportLLMError, match="cut off at the 10-token limit"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    sdk.stop_reason = "max_tokens"
    with pytest.raises(ReportLLMError, match="cut off"):
        brief_llm.run_llm_report("S", "U", "c1", 10, provider=CLAUDE)
    # a reason that is not known to mean "finished" is also a failure
    for finish in (None, "tool_calls"):
        posts.replies = [chat("SOME TEXT", finish=finish)]
        with pytest.raises(ReportLLMError, match="unexpected finish reason"):
            brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    sdk.stop_reason = "pause_turn"
    with pytest.raises(ReportLLMError, match="unexpected finish reason"):
        brief_llm.run_llm_report("S", "U", "c1", 10, provider=CLAUDE)
    posts.replies = [chat([{"type": "text", "text": "parts"}])]
    with pytest.raises(ReportLLMError, match="not text"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)


def test_g4_empty_answer_is_a_failure(posts, sdk):
    posts.replies = [chat("")]
    with pytest.raises(ReportLLMError, match="empty"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    posts.replies = [chat("partial", refusal="I cannot")]
    with pytest.raises(ReportLLMError, match="refused"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    posts.replies = [FakeResponse(200, body=None, text="<html>")]
    with pytest.raises(ReportLLMError, match="not JSON"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    sdk.text = ""
    with pytest.raises(ReportLLMError, match="empty"):
        brief_llm.run_llm_report("S", "U", "c1", 10, provider=CLAUDE)


def test_g5_unknown_provider_fails():
    with pytest.raises(ReportLLMError, match="'nope' could not be loaded"):
        report_llm.resolve_provider(Settings(provider="nope"), registry=REGISTRY)
    with pytest.raises(ReportLLMError, match="'empty' has no api_key"):
        report_llm.resolve_provider(Settings(provider="empty"), registry=REGISTRY)


def test_g5_no_silent_fallback(posts, sdk):
    # A configured provider is never swapped for the environment's Anthropic key.
    env = {"ANTHROPIC_API_KEY": "env-key"}
    for registry in (None, REGISTRY):
        with pytest.raises(ReportLLMError, match="nope"):
            report_llm.resolve_provider(Settings(provider="nope"), registry=registry, env=env)
    # A failing Google call does not reach the Anthropic SDK.
    posts.replies = [FakeResponse(404, text="model not found")]
    with pytest.raises(ReportLLMError, match="HTTP 404"):
        brief_llm.run_llm_report("S", "U", "m1", 10, provider=GOOGLE)
    assert sdk.request is None


def test_g6_precheck_uses_resolved_provider(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(report_llm, "load_registry", lambda: REGISTRY)
    config = {"report_llm": {"provider": "gemini-serp", "main_model": "m-main"}}
    args = SimpleNamespace(llm_model=None, advisory_model=None)
    llm = brief_rendering.resolve_report_llm(config, args)
    assert llm["provider"].name == "gemini-serp"
    assert (llm["main_model"], llm["advisory_model"]) == ("m-main", "m-main")
    assert "gemini-serp" in capsys.readouterr().out
    # the command line wins over config.yml
    args = SimpleNamespace(llm_model="cli-main", advisory_model="cli-adv")
    llm = brief_rendering.resolve_report_llm(config, args)
    assert (llm["main_model"], llm["advisory_model"]) == ("cli-main", "cli-adv")

    for bad in ({"report_llm": {"provider": "nope", "main_model": "m"}},
                {"report_llm": {"provider": "gemini-serp"}}):
        with pytest.raises(SystemExit) as stopped:
            brief_rendering.resolve_report_llm(bad, SimpleNamespace(llm_model=None, advisory_model=None))
        assert stopped.value.code == 2
    assert "report_llm.main_model" in capsys.readouterr().out


def test_g6_model_is_recorded():
    footer = brief_rendering.model_footer(GOOGLE, "m-main")
    assert "`m-main`" in footer and "`gemini-serp`" in footer
    assert "SECRET-KEY" not in footer
