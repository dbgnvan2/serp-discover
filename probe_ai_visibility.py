#!/usr/bin/env python3
"""
probe_ai_visibility.py
~~~~~~~~~~~~~~~~~~~~~~
Standalone AI-engine mention probing: asks Claude and/or Gemini realistic
therapy-seeker questions (with web search / grounding enabled) and measures
whether Living Systems is mentioned in the answer text or cited in the
returned sources — tracked as a per-engine TREND in SQLite, because AI
assistant behaviour swings between model versions (single runs are
snapshots, never conclusions).

Spec: seo_geo_deferred_spec_v1.md#G.1 (decision gate D-2: engines = Claude
AND Gemini, selectable via config `ai_visibility.engines` or the
``--engines`` CLI flag; a missing GEMINI_API_KEY skips that engine with a
warning, never an abort).

Pattern: run_feasibility.py — reads config + the latest market_analysis
JSON, runs any time, no pipeline coupling. The main pipeline never imports
this module.

Usage
-----
::

    python probe_ai_visibility.py                     # cost guard only (no calls)
    python probe_ai_visibility.py --yes               # run all configured engines
    python probe_ai_visibility.py --engines claude --yes
    python probe_ai_visibility.py --json market_analysis_x.json --yes

Cost guard: the script prints the planned call count (questions x engines)
and exits WITHOUT calling any API unless ``--yes`` is passed or
``ai_visibility.assume_yes: true`` is set in config.yml (G.1.5 of the spec's
inherited design principles: paid calls are gated).
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from urllib.parse import urlparse

import requests
import yaml

import aivi as aivi_mod
import answer_sentiment as sentiment_mod
import brand_mentions as brand_mentions_mod
import citation_table as citation_mod
import engine_recommendations as engine_recs_mod
import engine_transfer as engine_transfer_mod
import foundational_score as foundational_mod
from http_retry import post_with_transient_retry
from pattern_matching import load_serp_vocab
from profile_questions import generate as generate_profile_questions
from profile_questions import load_client_profiles
from query_variants import (
    flatten_situational_templates,
    situational_template_probes,
)

try:
    from datetime import UTC as _UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _tz
    _UTC = _tz.utc

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ENGINES = ("claude", "gemini", "openai", "perplexity")

#: Engine defaults for this client (gate Y-D9, user-approved): Gemini + ChatGPT
#: ON (highest audience reach + Google-organic carryover); Perplexity ON (strong
#: referral-click value); Claude available-but-not-default (lowest reach for a
#: small local nonprofit). Every engine still runs only if its API key is
#: present; a missing key skips it with a logged warning, never an abort.
#: Spec: yoast_geo_upgrade_spec_v1.md#Y.2 / #Y.3 (gate Y-D9).
DEFAULT_ENGINES = ["gemini", "openai", "perplexity"]
DEFAULT_MAX_QUESTIONS = 20          # per engine (gate D-2 budget default)
#: Hard ceiling on total paid calls across questions × engines (gate Y-D4).
#: Enforced by the cost guard; over budget aborts with zero calls unless --yes.
DEFAULT_MAX_TOTAL_CALLS = 60
DEFAULT_HISTORY_RUNS = 5
#: Default client slug in client_profiles.yml (Y.5 — one client per deployment).
DEFAULT_CLIENT_SLUG = "living_systems"

# Model ids come from config (ai_visibility.claude_model / gemini_model);
# these are only the fallbacks when the config block is absent.
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_CLAUDE_WEB_SEARCH_TOOL = "web_search_20260209"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
#: OpenAI web-search-enabled model + Responses endpoint (Y.2). Model id is
#: read from config (ai_visibility.openai_model); this is only the fallback.
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_WEB_SEARCH_TOOL = "web_search"
#: Perplexity Sonar search-grounded model + OpenAI-compatible chat endpoint
#: (Y.3). Sonar models return citations; model id read from config
#: (ai_visibility.perplexity_model); this is only the fallback.
DEFAULT_PERPLEXITY_MODEL = "sonar"
DEFAULT_PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"

GEMINI_ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 60

PROBE_TABLE = "ai_visibility_probes"

#: Mandatory report caveat (G.1.5): single-run values are snapshots.
SNAPSHOT_CAVEAT = (
    "**Caveat — single-run values are snapshots.** AI assistant answers swing "
    "between model versions and even between identical runs of the same "
    "model. A mention (or absence) in one run is not a stable fact about the "
    "engine; only the per-engine trend across runs is actionable. Do not "
    "change strategy based on a single run."
)


# ---------------------------------------------------------------------------
# Config / input helpers (run_feasibility.py pattern)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def _load_config(config_path: str = "config.yml") -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _latest_analysis_json(config: dict) -> str | None:
    """Latest market_analysis_*.json: config files.output_json, else newest on disk."""
    configured = (config.get("files", {}) or {}).get("output_json")
    if configured and os.path.exists(configured):
        return configured
    candidates = glob.glob("market_analysis_*.json") + glob.glob("output/market_analysis_*.json")
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _derive_output_path(json_path: str) -> str:
    base = os.path.basename(json_path or "report.json")
    slug = re.sub(r"^market_analysis_", "", base)
    slug = re.sub(r"(?:_\d{8}_\d{4})?\.json$", "", slug) or "report"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"ai_visibility_{slug}_{timestamp}.md"


# ---------------------------------------------------------------------------
# Engine selection (G.1.4)
# ---------------------------------------------------------------------------

def resolve_engines(cli_engines: str | None, av_config: dict) -> list[str]:
    """Resolve the engine list: --engines CLI flag overrides config.

    Unknown engine names raise SystemExit with a message listing the valid
    options (G.1.4). Spec: seo_geo_deferred_spec_v1.md#G.1, gate D-2.
    """
    if cli_engines:
        engines = [e.strip().lower() for e in cli_engines.split(",") if e.strip()]
    else:
        engines = [str(e).strip().lower() for e in (av_config.get("engines") or DEFAULT_ENGINES)]
    deduped: list[str] = []
    for engine in engines:
        if engine not in deduped:
            deduped.append(engine)
    unknown = [e for e in deduped if e not in VALID_ENGINES]
    if unknown:
        raise SystemExit(
            f"Unknown engine(s): {', '.join(unknown)}. "
            f"Valid options: {', '.join(VALID_ENGINES)}."
        )
    if not deduped:
        raise SystemExit(
            f"No engines selected. Valid options: {', '.join(VALID_ENGINES)}."
        )
    return deduped


# ---------------------------------------------------------------------------
# Engine probes (AiEngineProbe protocol: ask(question) ->
#   {"answer_text", "source_urls", "model_id"})
# ---------------------------------------------------------------------------

class ClaudeProbe:
    """Anthropic probe with the web search server tool enabled.

    Client-construction conventions follow brief_llm.py (env API key,
    model id from config — never hardcoded).
    Spec: seo_geo_deferred_spec_v1.md#G.1.
    """

    def __init__(self, model: str, web_search_tool: str = DEFAULT_CLAUDE_WEB_SEARCH_TOOL,
                 max_tokens: int = 2048, max_searches: int = 3) -> None:
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError("anthropic package not installed.")
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self.model = model
        self.web_search_tool = web_search_tool
        self.max_tokens = max_tokens
        self.max_searches = max_searches
        self._client = anthropic.Anthropic(api_key=api_key)

    def ask(self, question: str) -> dict:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            tools=[{
                "type": self.web_search_tool,
                "name": "web_search",
                "max_uses": self.max_searches,
            }],
            messages=[{"role": "user", "content": question}],
        )
        texts: list[str] = []
        urls: list[str] = []
        for block in response.content:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text = getattr(block, "text", None)
                if text:
                    texts.append(text)
                for citation in (getattr(block, "citations", None) or []):
                    url = getattr(citation, "url", None)
                    if url:
                        urls.append(str(url))
            elif block_type == "web_search_tool_result":
                content = getattr(block, "content", None)
                # On tool errors `content` is a single error object, not a
                # list of web_search_result items — skip it.
                if isinstance(content, list):
                    for item in content:
                        url = getattr(item, "url", None)
                        if url:
                            urls.append(str(url))
        return {
            "answer_text": "\n".join(texts).strip(),
            "source_urls": list(dict.fromkeys(urls)),
            "model_id": str(getattr(response, "model", self.model)),
        }


class GeminiProbe:
    """Gemini probe via plain REST (requests + http_retry) with Google
    Search grounding enabled — no google SDK dependency.

    API key from the optional GEMINI_API_KEY env var; a missing key raises
    RuntimeError, which build_probes() converts into a logged
    skip-with-warning (gate D-2: never an abort).
    Spec: seo_geo_deferred_spec_v1.md#G.1.
    """

    def __init__(self, model: str) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        self.model = model
        self._api_key = api_key

    def ask(self, question: str) -> dict:
        url = f"{GEMINI_ENDPOINT_BASE}/{self.model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "tools": [{"google_search": {}}],
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        response = post_with_transient_retry(
            "Gemini", url, headers, payload,
            batch_desc=f"probe question ({self.model})",
            timeout=REQUEST_TIMEOUT,
            post=requests.post,
        )
        if response is None:
            raise RuntimeError("Gemini request failed at the network layer.")
        if not response.ok:
            raise RuntimeError(f"Gemini returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        candidates = data.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        parts = ((candidate.get("content") or {}).get("parts")) or []
        answer = "\n".join(p.get("text", "") for p in parts if p.get("text"))
        urls: list[str] = []
        grounding = candidate.get("groundingMetadata") or {}
        for chunk in (grounding.get("groundingChunks") or []):
            uri = ((chunk.get("web") or {}).get("uri")) if isinstance(chunk, dict) else None
            if uri:
                urls.append(str(uri))
        return {
            "answer_text": answer.strip(),
            "source_urls": list(dict.fromkeys(urls)),
            "model_id": str(data.get("modelVersion") or self.model),
        }


class ChatGPTProbe:
    """OpenAI / ChatGPT probe via the Responses API with the web_search server
    tool enabled — plain REST (requests + http_retry), no openai SDK.

    Answers reflect live retrieval; source URLs are taken from the
    ``url_citation`` annotations on the assistant message and, when present,
    the ``web_search_call`` item's ``action.sources`` list. Client-construction
    conventions follow ClaudeProbe (env API key, model id from config — never
    hardcoded). A missing OPENAI_API_KEY raises RuntimeError, which
    build_probes() converts into a logged skip-with-warning (gate Y-D2/Y-D9:
    never an abort).

    API surface confirmed 2026-07 against OpenAI's live docs: the Responses
    endpoint (``POST /v1/responses``) exposes web search via the ``web_search``
    tool and returns inline citations as ``url_citation`` annotations (each
    carrying ``url`` and ``title``). The endpoint and tool name are
    parameterised in config so the parser tracks the current surface without a
    code change.
    Spec: yoast_geo_upgrade_spec_v1.md#Y.2.
    """

    def __init__(self, model: str, endpoint: str = DEFAULT_OPENAI_ENDPOINT,
                 web_search_tool: str = DEFAULT_OPENAI_WEB_SEARCH_TOOL,
                 max_output_tokens: int = 2048) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self.model = model
        self.endpoint = endpoint
        self.web_search_tool = web_search_tool
        self.max_output_tokens = max_output_tokens
        self._api_key = api_key

    def ask(self, question: str) -> dict:
        payload = {
            "model": self.model,
            "input": question,
            "tools": [{"type": self.web_search_tool}],
            "max_output_tokens": self.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = post_with_transient_retry(
            "OpenAI", self.endpoint, headers, payload,
            batch_desc=f"probe question ({self.model})",
            timeout=REQUEST_TIMEOUT,
            post=requests.post,
        )
        if response is None:
            raise RuntimeError("OpenAI request failed at the network layer.")
        if not response.ok:
            raise RuntimeError(
                f"OpenAI returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        texts: list[str] = []
        urls: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "message":
                for block in item.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if text:
                        texts.append(text)
                    for ann in block.get("annotations") or []:
                        if not isinstance(ann, dict):
                            continue
                        if ann.get("type") == "url_citation":
                            url = ann.get("url")
                            if url:
                                urls.append(str(url))
            elif item_type == "web_search_call":
                # The complete list of consulted sources (superset of the
                # inline citations) when the account exposes it.
                action = item.get("action") or {}
                for src in action.get("sources") or []:
                    url = src.get("url") if isinstance(src, dict) else None
                    if url:
                        urls.append(str(url))
        # Fallback for the flat convenience field some responses include.
        if not texts and data.get("output_text"):
            texts.append(str(data["output_text"]))
        return {
            "answer_text": "\n".join(texts).strip(),
            "source_urls": list(dict.fromkeys(urls)),
            "model_id": str(data.get("model") or self.model),
        }


class PerplexityProbe:
    """Perplexity probe via the OpenAI-compatible chat/completions endpoint
    with a Sonar (search-grounded) model — plain REST (requests + http_retry).

    Sonar models return explicit citations, making Perplexity a high-signal
    target for the ``cited`` metric. Citations are mapped into ``source_urls``:
    the response's top-level ``search_results`` (objects with ``url``) are
    preferred, with the flat ``citations`` list (URL strings) merged in.
    Model id from config (ai_visibility.perplexity_model); API key from
    PERPLEXITY_API_KEY; a missing key raises RuntimeError → logged
    skip-with-warning (gate Y-D3/Y-D9).

    API surface confirmed 2026-07 against Perplexity's live docs: the
    OpenAI-compatible ``POST /chat/completions`` endpoint returns the answer in
    ``choices[0].message.content`` plus a top-level ``search_results`` array and
    a ``citations`` array of URLs. Endpoint parameterised in config.
    Spec: yoast_geo_upgrade_spec_v1.md#Y.3.
    """

    def __init__(self, model: str, endpoint: str = DEFAULT_PERPLEXITY_ENDPOINT,
                 max_tokens: int = 2048) -> None:
        api_key = os.getenv("PERPLEXITY_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("PERPLEXITY_API_KEY is not set.")
        self.model = model
        self.endpoint = endpoint
        self.max_tokens = max_tokens
        self._api_key = api_key

    def ask(self, question: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = post_with_transient_retry(
            "Perplexity", self.endpoint, headers, payload,
            batch_desc=f"probe question ({self.model})",
            timeout=REQUEST_TIMEOUT,
            post=requests.post,
        )
        if response is None:
            raise RuntimeError("Perplexity request failed at the network layer.")
        if not response.ok:
            raise RuntimeError(
                f"Perplexity returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        choices = data.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        answer = str(message.get("content") or "")
        urls: list[str] = []
        # Structured search_results (preferred — carries title + url).
        for result in data.get("search_results") or []:
            url = result.get("url") if isinstance(result, dict) else None
            if url:
                urls.append(str(url))
        # Flat citations list (URL strings) — merge in, de-duplicated below.
        for citation in data.get("citations") or []:
            if isinstance(citation, str) and citation:
                urls.append(citation)
            elif isinstance(citation, dict) and citation.get("url"):
                urls.append(str(citation["url"]))
        return {
            "answer_text": answer.strip(),
            "source_urls": list(dict.fromkeys(urls)),
            "model_id": str(data.get("model") or self.model),
        }


def build_probes(engines: list[str], av_config: dict) -> tuple[dict, list[dict]]:
    """Construct one probe per selected engine.

    Returns (probes, skipped). A missing API key (or missing anthropic
    package) skips that engine with a logged warning — never an abort
    (G.1.4, gate D-2).
    """
    probes: dict[str, object] = {}
    skipped: list[dict] = []
    for engine in engines:
        try:
            if engine == "claude":
                probes[engine] = ClaudeProbe(
                    model=av_config.get("claude_model", DEFAULT_CLAUDE_MODEL),
                    web_search_tool=av_config.get(
                        "claude_web_search_tool", DEFAULT_CLAUDE_WEB_SEARCH_TOOL),
                )
            elif engine == "gemini":
                probes[engine] = GeminiProbe(
                    model=av_config.get("gemini_model", DEFAULT_GEMINI_MODEL),
                )
            elif engine == "openai":
                probes[engine] = ChatGPTProbe(
                    model=av_config.get("openai_model", DEFAULT_OPENAI_MODEL),
                    endpoint=av_config.get(
                        "openai_endpoint", DEFAULT_OPENAI_ENDPOINT),
                    web_search_tool=av_config.get(
                        "openai_web_search_tool", DEFAULT_OPENAI_WEB_SEARCH_TOOL),
                )
            elif engine == "perplexity":
                probes[engine] = PerplexityProbe(
                    model=av_config.get(
                        "perplexity_model", DEFAULT_PERPLEXITY_MODEL),
                    endpoint=av_config.get(
                        "perplexity_endpoint", DEFAULT_PERPLEXITY_ENDPOINT),
                )
        except RuntimeError as exc:
            logger.warning("Skipping engine '%s': %s", engine, exc)
            skipped.append({"engine": engine, "reason": str(exc)})
    return probes, skipped


# ---------------------------------------------------------------------------
# Question set (T.5 output preferred; see spec G.1 required change 2)
# ---------------------------------------------------------------------------

def _root_keywords(data: dict) -> list[str]:
    ordered: list[str] = []
    for row in data.get("overview") or []:
        if row.get("Query_Label") != "A":
            continue
        kw = str(row.get("Source_Keyword") or "").strip()
        if kw and kw not in ordered:
            ordered.append(kw)
    if not ordered:
        for row in data.get("organic_results") or []:
            if row.get("Query_Label") != "A":
                continue
            kw = str(row.get("Source_Keyword") or "").strip()
            if kw and kw not in ordered:
                ordered.append(kw)
    return ordered


def build_question_set(data: dict, templates: list[str], city: str,
                       max_questions: int, min_words: int = 6,
                       profile_questions: list[dict] | None = None) -> list[dict]:
    """Build the probe question list, capped at *max_questions* (per engine).

    Priority order (Y.5 precedence, extending G.1 / T.5):
    **profile questions (Y.1) → T.5 situational probes → 6+-word PAA →
    serp_vocab.yml situational_templates** filled per root keyword. Profile
    questions are the highest-priority source and are AUGMENTATIVE (gate
    Y-D1): when a client profile is present its persona-shaped questions are
    probed first; when absent (``profile_questions`` empty or ``None``) the
    precedence collapses to the original G.1 behaviour exactly.

    Each returned dict carries ``query``, ``source``
    (``profile|situational|paa|template``), and ``persona`` (the profile
    persona label for profile-sourced rows, else ``None``). The ``source``
    label is stored per row so the report can show where each probe came from.

    Spec: yoast_geo_upgrade_spec_v1.md#Y.5 (Y.5.1 profile-first precedence +
    row tagging; regression: no profile ⇒ current G.1 precedence).
    """
    questions: list[dict] = []
    seen: set[str] = set()

    def _add(query: str, source: str, persona: str | None = None) -> None:
        query = (query or "").strip()
        key = query.lower()
        if query and key not in seen and len(questions) < max_questions:
            seen.add(key)
            questions.append({"query": query, "source": source,
                              "persona": persona})

    # Highest priority: profile-seeded persona questions (Y.1). Each carries
    # its persona label; source tag is the short "profile".
    for item in profile_questions or []:
        _add(str(item.get("question") or ""), "profile",
             persona=item.get("persona"))
    if not questions:
        for row in data.get("situational_probes") or []:
            _add(str(row.get("Executed_Query") or ""), "situational")
    if not questions:
        for row in data.get("paa_questions") or []:
            question = str(row.get("Question") or "").strip()
            if len(question.split()) >= min_words:
                _add(question, "paa")
    if not questions:
        for kw in _root_keywords(data):
            for query in situational_template_probes(kw, templates, city):
                _add(query, "template")
    return questions


# ---------------------------------------------------------------------------
# Detection (G.1.1)
# ---------------------------------------------------------------------------

def _domain_from_url(url: str) -> str:
    try:
        return urlparse(str(url)).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _matches_domain(domain: str, target: str) -> bool:
    return bool(domain) and (domain == target or domain.endswith("." + target))


def detect_visibility(answer_text: str, source_urls: list[str],
                      client_name_patterns: list[str], client_domain: str,
                      competitor_domains: list[str]) -> dict:
    """Engine-agnostic detection applied to each answer (G.1.1).

    - mentioned: any client name pattern appears in the answer text
      (case-insensitive).
    - cited: the client domain appears in any returned source URL.
    - competitors_cited: competitor domains (known_brands + top competitor
      domains from the latest analysis JSON) found in the source URLs.
    Spec: seo_geo_deferred_spec_v1.md#G.1.
    """
    text_lower = (answer_text or "").lower()
    mentioned = any(
        pattern and str(pattern).lower() in text_lower
        for pattern in (client_name_patterns or [])
    )

    client_lower = (client_domain or "").lower().removeprefix("www.")
    cited = False
    competitor_hits: set[str] = set()
    competitors = [str(c).lower().strip() for c in (competitor_domains or []) if str(c).strip()]
    for url in source_urls or []:
        domain = _domain_from_url(url)
        if not domain:
            continue
        if client_lower and _matches_domain(domain, client_lower):
            cited = True
        for competitor in competitors:
            if "." in competitor:
                if _matches_domain(domain, competitor):
                    competitor_hits.add(competitor)
            elif competitor in domain:
                competitor_hits.add(competitor)
    return {
        "mentioned": bool(mentioned),
        "cited": cited,
        "competitors_cited": sorted(competitor_hits),
    }


def top_competitor_domains(data: dict, client_domain: str, limit: int = 15) -> list[str]:
    """Most frequent top-10 organic domains across root keywords, minus the client."""
    client_lower = (client_domain or "").lower().removeprefix("www.")
    counts: dict[str, int] = {}
    for row in data.get("organic_results") or []:
        if row.get("Query_Label") != "A":
            continue
        try:
            rank = int(row.get("Rank") or 999)
        except (TypeError, ValueError):
            rank = 999
        if rank > 10:
            continue
        domain = _domain_from_url(row.get("Link") or row.get("URL") or "")
        if not domain or (client_lower and _matches_domain(domain, client_lower)):
            continue
        counts[domain] = counts.get(domain, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [domain for domain, _count in ranked[:limit]]


# ---------------------------------------------------------------------------
# Persistence (G.1.2) — storage.py conventions: parameterized SQL, UTC
# timestamps, CREATE TABLE IF NOT EXISTS (idempotent).
# ---------------------------------------------------------------------------

#: Columns added by Y.5 / D5 via idempotent ALTER TABLE (storage.py convention).
#: A pre-existing DB is upgraded once; old rows read back as NULL (principle 3).
#: ``raw_answer`` (D5/AV.5.1) is added here too so pre-D5 DBs migrate on first use.
_PROBE_MIGRATION_COLUMNS = (("persona", "TEXT"), ("source", "TEXT"),
                            ("raw_answer", "TEXT"))

#: D5/AV.5.1 — cap on the stored full answer text when store_raw_answer is on.
#: The full LLM answer is unbounded and may carry PII, so retention is opt-in
#: (config.yml ai_visibility.store_raw_answer, default off) and length-capped.
DEFAULT_RAW_ANSWER_MAX_CHARS = 10000
#: Appended when a stored raw answer is clipped, so an auditor can tell a
#: genuinely-short answer from a silently-truncated one (P9). Kept inside the cap.
_TRUNC_MARKER = " …[truncated]"


def _coerce_raw_cap(value) -> int:
    """Coerce ai_visibility.raw_answer_max_chars to a non-negative int with a
    fallback + warning — never a bare int() that could crash persistence AFTER the
    paid probes ran (the config-fallback convention, cf. aivi.resolve_weights)."""
    try:
        cap = int(value)
    except (TypeError, ValueError):
        logger.warning("ai_visibility.raw_answer_max_chars non-numeric — using %d.",
                       DEFAULT_RAW_ANSWER_MAX_CHARS)
        return DEFAULT_RAW_ANSWER_MAX_CHARS
    return cap if cap >= 0 else DEFAULT_RAW_ANSWER_MAX_CHARS


def init_probe_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {PROBE_TABLE} (
            run_ts                  TEXT,
            engine                  TEXT,
            model                   TEXT,
            question                TEXT,
            mentioned               INTEGER,
            cited                   INTEGER,
            competitor_domains_json TEXT,
            answer_excerpt          TEXT,
            persona                 TEXT,
            source                  TEXT,
            raw_answer              TEXT
        )''')
        # Migration for DBs created before Y.5: add persona/source columns.
        # ALTER TABLE … ADD COLUMN wrapped in try/except OperationalError so
        # the DB migrates automatically on first use — storage.py convention.
        for col, col_type in _PROBE_MIGRATION_COLUMNS:
            try:
                conn.execute(
                    f"ALTER TABLE {PROBE_TABLE} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore (idempotent).
        conn.commit()


def save_probe_rows(db_path: str, rows: list[dict], *,
                    store_raw_answer: bool = False,
                    raw_answer_max_chars: int = DEFAULT_RAW_ANSWER_MAX_CHARS) -> None:
    """Persist probe rows. D5/AV.5.1: when ``store_raw_answer`` is on (config-gated,
    default off) the FULL answer text is additionally persisted in ``raw_answer``,
    capped at ``raw_answer_max_chars`` for size/PII safety; off → ``raw_answer``
    stays NULL and only the 400-char ``answer_excerpt`` is kept."""
    init_probe_table(db_path)
    cap = _coerce_raw_cap(raw_answer_max_chars)

    def _raw(row: dict):
        if not store_raw_answer:
            return None
        text = row.get("answer_text") or ""
        if len(text) > cap:                          # P9: signal the clip, keep a
            room = max(0, cap - len(_TRUNC_MARKER))  # hard cap incl. the marker
            return text[:room] + _TRUNC_MARKER
        return text

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"""INSERT INTO {PROBE_TABLE}
                (run_ts, engine, model, question, mentioned, cited,
                 competitor_domains_json, answer_excerpt, persona, source,
                 raw_answer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["run_ts"], row["engine"], row["model"], row["question"],
                    int(bool(row["mentioned"])), int(bool(row["cited"])),
                    json.dumps(row.get("competitors_cited", [])),
                    (row.get("answer_excerpt") or "")[:400],
                    row.get("persona"), row.get("source"), _raw(row),
                )
                for row in rows
            ],
        )
        conn.commit()


def get_engine_trend(db_path: str, engine: str, limit: int = DEFAULT_HISTORY_RUNS) -> list[dict]:
    """Per-run aggregates for one engine, oldest→newest (G.1.2)."""
    init_probe_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, MAX(model), COUNT(*), SUM(mentioned), SUM(cited)
                FROM {PROBE_TABLE}
                WHERE engine = ?
                GROUP BY run_ts
                ORDER BY run_ts DESC
                LIMIT ?""",
            (engine, limit),
        ).fetchall()
    trend = [
        {
            "run_ts": run_ts,
            "model": model,
            "questions": questions,
            "mentioned": mentioned or 0,
            "cited": cited or 0,
            "mention_rate": round((mentioned or 0) / questions, 2) if questions else None,
            "citation_rate": round((cited or 0) / questions, 2) if questions else None,
        }
        for run_ts, model, questions, mentioned, cited in rows
    ]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Run + report (G.1.5)
# ---------------------------------------------------------------------------

def run_engine_probes(probes: dict, questions: list[dict], geo_context: str,
                      client_name_patterns: list[str], client_domain: str,
                      competitor_domains: list[str], run_ts: str) -> list[dict]:
    """Ask every question on every engine; returns flat result rows."""
    rows: list[dict] = []
    for engine, probe in probes.items():
        for index, item in enumerate(questions, start=1):
            question = item["query"]
            full_question = f"{geo_context} {question}".strip() if geo_context else question
            print(f"  [{engine} {index}/{len(questions)}] {question}")
            try:
                answer = probe.ask(full_question)
            except Exception as exc:
                logger.warning("%s probe failed for %r: %s", engine, question, exc)
                continue
            detection = detect_visibility(
                answer.get("answer_text", ""), answer.get("source_urls", []),
                client_name_patterns, client_domain, competitor_domains,
            )
            rows.append({
                "run_ts": run_ts,
                "engine": engine,
                "model": answer.get("model_id", ""),
                "question": question,
                "mentioned": detection["mentioned"],
                "cited": detection["cited"],
                "competitors_cited": detection["competitors_cited"],
                "answer_excerpt": (answer.get("answer_text") or "")[:400],
                # Y.5: carry the probe's provenance onto the stored row.
                "persona": item.get("persona"),
                "source": item.get("source"),
                # Y.6–Y.9: retain the full answer text + source URLs in memory
                # (NOT persisted to the probe table) so the read-side enrichment
                # modules can extract brands, citations, and sentiment.
                "answer_text": answer.get("answer_text") or "",
                "source_urls": answer.get("source_urls") or [],
            })
    return rows


def _rate(count: int, total: int) -> str:
    if not total:
        return "—"
    return f"{count}/{total} ({count / total:.0%})"


# ---------------------------------------------------------------------------
# Phase D read-side enrichment (Y.6–Y.9): leaderboard, citations, sentiment,
# AIVI — computed from the answers already fetched, persisted per engine.
# ---------------------------------------------------------------------------

def _brand_domain_map(known_brands: list[str], client_domain: str,
                      client_name: str) -> dict[str, str]:
    """Map lower-cased domains (and the client's) to display brand names for
    Y.8 citation brand attribution. Domains in known_brands map to themselves."""
    mapping: dict[str, str] = {}
    for brand in known_brands or []:
        b = str(brand).strip()
        if "." in b:  # looks like a domain
            mapping[b.lower()] = b
    if client_domain:
        mapping[client_domain.lower().removeprefix("www.")] = client_name or client_domain
    return mapping


def run_report_enrichment(rows: list[dict], engines: list[str], config: dict,
                          analysis_data: dict, run_ts: str, topic: str,
                          db_path: str, source_json: str | None,
                          out_dir: str = ".",
                          brand_llm_runner=None,
                          sentiment_llm_runner=None,
                          sentiment_call_budget: int | None = None) -> dict:
    """Compute + persist the Y.6–Y.9 metrics from the fetched answers.

    Returns a dict the report renderer consumes::

        {"leaderboards": {engine: leaderboard},
         "citations": {engine: table},
         "sentiment": {"enabled": bool, "rows": [...], "calls": int,
                       "client_brand": str, "top_competitor": str|None},
         "aivi": {"per_engine": {engine: result}, "all_engine_avg": float|None,
                  "trends": {engine: [...]}},
         "candidates_file": str|None}

    All LLM runners are injectable and default OFF (brand LLM off unless
    ``brand_mentions.llm_extraction``; sentiment off unless ``sentiment.enabled``)
    so a plain run makes zero extra calls (principle 4). Old analysis JSONs
    without new fields flow through without crashing or fabricating zeros
    (principle 3).
    """
    analysis_cfg = config.get("analysis_report", {}) or {}
    known_brands = list(config.get("known_brands", []) or [])
    client_domain = analysis_cfg.get("client_domain", "") or ""
    client_name = analysis_cfg.get("client_name", "Client")
    client_patterns = analysis_cfg.get("client_name_patterns", []) or []

    bm_cfg = config.get("brand_mentions", {}) or {}
    llm_extraction = bool(bm_cfg.get("llm_extraction", False))
    bm_model = bm_cfg.get("llm_model", "")

    # Seed the gazetteer with the client's own name patterns so the client can
    # appear on the leaderboard and receive a rank (Y.7 — "client's own rank
    # computed"); without this the client is only ever "not mentioned".
    gazetteer = brand_mentions_mod.build_gazetteer(
        list(client_patterns) + list(known_brands), analysis_data)
    brand_domains = _brand_domain_map(known_brands, client_domain, client_name)

    leaderboards: dict[str, dict] = {}
    citations: dict[str, list] = {}
    all_unknown: list[str] = []
    unknown_seen: set[str] = set()

    for engine in engines:
        engine_rows = [r for r in rows if r["engine"] == engine]
        answers = [
            {"engine": engine, "answer_text": r.get("answer_text", ""),
             "source_urls": r.get("source_urls", [])}
            for r in engine_rows
        ]
        # Y.7 leaderboard (gazetteer always; LLM only if enabled).
        leaderboard = brand_mentions_mod.build_leaderboard(
            answers, gazetteer, client_patterns, llm_extraction, bm_model,
            llm_runner=brand_llm_runner)
        leaderboards[engine] = leaderboard
        if leaderboard.get("rows"):
            brand_mentions_mod.save_brand_mentions(db_path, run_ts, engine, leaderboard)
        for name in leaderboard.get("unknown_candidates", []):
            key = name.strip().lower()
            if key and key not in unknown_seen:
                unknown_seen.add(key)
                all_unknown.append(name)

        # Y.8 citation table.
        brand_names = [r["brand"] for r in leaderboard.get("rows", [])]
        table = citation_mod.build_citation_table(
            answers, client_domain, brand_domains, brand_names)
        citations[engine] = table
        if table:
            citation_mod.save_citations(db_path, run_ts, engine, table)

    candidates_file = brand_mentions_mod.write_candidates_file(
        all_unknown, topic, run_ts, source_json, out_dir=out_dir)

    # Y.9 sentiment (gated; zero calls when disabled).
    sent_cfg = config.get("sentiment", {}) or {}
    sent_enabled = sentiment_mod.is_enabled(sent_cfg)
    sent_model = sent_cfg.get("llm_model", "")
    sent_rows: list[dict] = []
    sent_calls = 0
    top_competitor = None
    # Top competitor = highest-ranked non-client brand across all engines.
    combined: dict[str, int] = {}
    for lb in leaderboards.values():
        for r in lb.get("rows", []):
            if not r["is_client"]:
                combined[r["brand"]] = combined.get(r["brand"], 0) + r["mention_count"]
    if combined:
        top_competitor = max(sorted(combined), key=lambda b: combined[b])
    if sent_enabled:
        targets = {client_name: client_patterns}
        if top_competitor:
            targets[top_competitor] = [top_competitor]
        answers_all = [
            {"engine": r["engine"], "answer_text": r.get("answer_text", "")}
            for r in rows
        ]
        sent_rows, sent_calls = sentiment_mod.collect_sentiment(
            answers_all, targets, sent_model, llm_runner=sentiment_llm_runner,
            call_budget=sentiment_call_budget)
        if sent_rows:
            sentiment_mod.save_sentiment(db_path, run_ts, sent_rows)

    # Y.6 AIVI per engine + all-engine average.
    aivi_weights = aivi_mod.resolve_weights(config.get("aivi", {}) or {})
    sentiment_axis = None
    if sent_enabled:
        sentiment_axis = sentiment_mod.sentiment_axis(sent_rows, client_name)
    per_engine: dict[str, dict] = {}
    for engine in engines:
        engine_rows = [r for r in rows if r["engine"] == engine]
        total = len(engine_rows)
        mentions_axis = (100.0 * sum(1 for r in engine_rows if r["mentioned"]) / total) if total else 0.0
        lb = leaderboards.get(engine, {})
        ranking_axis = brand_mentions_mod.client_ranking_axis(
            lb.get("client_rank"), len(lb.get("rows", [])))
        citations_axis = citation_mod.citations_axis(citations.get(engine, []))
        per_engine[engine] = aivi_mod.compute_aivi(
            {"mentions": mentions_axis, "ranking": ranking_axis,
             "citations": citations_axis, "sentiment": sentiment_axis},
            aivi_weights)
        aivi_mod.save_aivi(db_path, run_ts, engine, per_engine[engine])
    aivi_trends = {
        engine: aivi_mod.get_aivi_trend(db_path, engine)
        for engine in engines
    }

    # -----------------------------------------------------------------------
    # Phase E — engine strategy (Y.10–Y.12). Pure aggregation of the signals
    # already computed above; no new engine calls.
    # -----------------------------------------------------------------------
    # Y.12 foundational (transferable) readiness score — engine-agnostic, from
    # existing keyword_profiles / schema recs / Y.7 leaderboard.
    try:
        from brief_prompts import load_schema_recommendations
        schema_recs = load_schema_recommendations()
    except Exception as exc:  # never abort the report on an editorial-file issue
        logger.warning("Could not load schema_recommendations.yml: %s", exc)
        schema_recs = []
    foundational_weights = foundational_mod.resolve_weights(
        config.get("foundational", {}) or {})
    foundational_result = foundational_mod.compute_foundational_score(
        analysis_data, schema_recs, leaderboards, foundational_weights,
        client_name_patterns=client_patterns)
    foundational_mod.save_foundational_score(db_path, run_ts, foundational_result)
    foundational_trend = foundational_mod.get_foundational_trend(db_path)

    # Y.10 engine profiles + per-engine recommendations + prioritisation.
    engine_profiles = engine_recs_mod.load_engine_profiles()
    per_engine_results = {}
    per_engine_aivi_scores = {}
    for engine in engines:
        aivi_res = per_engine.get(engine, {})
        lb = leaderboards.get(engine, {})
        cats = sorted({r["category"] for r in citations.get(engine, []) if r.get("category")})
        per_engine_results[engine] = {
            "aivi": aivi_res.get("aivi"),
            "client_rank": lb.get("client_rank"),
            "citation_categories": cats,
        }
        per_engine_aivi_scores[engine] = aivi_res.get("aivi")
    priority_weights = engine_recs_mod.resolve_priority_weights(
        config.get("engine_prioritization", {}) or {})
    engine_recommendations = engine_recs_mod.engine_recommendations(
        engines, engine_profiles, per_engine_results)
    engine_prioritization = engine_recs_mod.prioritize_engines(
        engines, engine_profiles, per_engine_aivi_scores, priority_weights)

    # Y.11 cross-engine transfer (needs ≥2 engines; single engine → not measurable).
    mention_by_engine = {}
    cited_by_engine = {}
    for engine in engines:
        engine_rows = [r for r in rows if r["engine"] == engine]
        mention_by_engine[engine] = any(r["mentioned"] for r in engine_rows)
        cited_by_engine[engine] = any(r["cited"] for r in engine_rows)
    client_rank_by_engine = {
        engine: leaderboards.get(engine, {}).get("client_rank") for engine in engines
    }
    transfer_result = engine_transfer_mod.compute_transfer(
        engines, mention_by_engine, cited_by_engine, citations, client_rank_by_engine)
    engine_transfer_mod.save_transfer(db_path, run_ts, transfer_result)

    return {
        "leaderboards": leaderboards,
        "citations": citations,
        "sentiment": {
            "enabled": sent_enabled, "rows": sent_rows, "calls": sent_calls,
            "client_brand": client_name, "top_competitor": top_competitor,
        },
        "aivi": {
            "per_engine": per_engine,
            "all_engine_avg": aivi_mod.all_engine_average(per_engine),
            "trends": aivi_trends,
        },
        "foundational": {
            "result": foundational_result,
            "trend": foundational_trend,
        },
        "engine_strategy": {
            "recommendations": engine_recommendations,
            "prioritization": engine_prioritization,
        },
        "transfer": transfer_result,
        "candidates_file": candidates_file,
    }


def generate_report(source_json: str, run_ts: str, engines: list[str],
                    rows: list[dict], trends: dict, skipped: list[dict],
                    geo_context: str, client_name: str,
                    enrichment: dict | None = None) -> str:
    """Render the ai_visibility markdown report (G.1.5).

    Includes per-engine mention/citation rates for this run, the per-engine
    trend table over previous runs, the model ids used, and the mandatory
    snapshot caveat — always present, with or without history.
    """
    lines: list[str] = []
    lines.append("# AI Engine Visibility Probe")
    lines.append(f"**Client:** {client_name} | **Run:** {run_ts}")
    lines.append(f"**Source analysis:** `{os.path.basename(source_json or '—')}`")
    lines.append(f"**Geo context prefix:** \"{geo_context}\"\n")
    lines.append(SNAPSHOT_CAVEAT)
    lines.append("")

    lines.append("## This run — per engine")
    lines.append("| Engine | Model | Questions | Mentioned | Cited |")
    lines.append("|--------|-------|-----------|-----------|-------|")
    for engine in engines:
        engine_rows = [r for r in rows if r["engine"] == engine]
        if not engine_rows:
            skip_reason = next((s["reason"] for s in skipped if s["engine"] == engine), None)
            note = f"skipped — {skip_reason}" if skip_reason else "no answers"
            lines.append(f"| {engine} | — | 0 | — | — |  ")
            lines.append(f"*{engine}: {note}*")
            continue
        model = engine_rows[0]["model"]
        total = len(engine_rows)
        mentioned = sum(1 for r in engine_rows if r["mentioned"])
        cited = sum(1 for r in engine_rows if r["cited"])
        lines.append(
            f"| {engine} | {model} | {total} | {_rate(mentioned, total)} | {_rate(cited, total)} |"
        )
    lines.append("")

    lines.append("## Trend — previous runs per engine")
    for engine in engines:
        lines.append(f"\n### {engine}")
        trend = trends.get(engine) or []
        if not trend:
            lines.append("*No history yet — this is the first recorded run for this engine.*")
            continue
        lines.append("| Run | Model | Questions | Mention rate | Citation rate |")
        lines.append("|-----|-------|-----------|--------------|---------------|")
        for entry in trend:
            mention = f"{entry['mention_rate']:.0%}" if entry["mention_rate"] is not None else "—"
            citation = f"{entry['citation_rate']:.0%}" if entry["citation_rate"] is not None else "—"
            lines.append(
                f"| {entry['run_ts']} | {entry['model']} | {entry['questions']} "
                f"| {mention} | {citation} |"
            )
    lines.append("")

    hits = [r for r in rows if r["mentioned"] or r["cited"]]
    lines.append("## Questions where the client appeared")
    if hits:
        for row in hits:
            flags = []
            if row["mentioned"]:
                flags.append("mentioned")
            if row["cited"]:
                flags.append("cited")
            lines.append(f"- **{row['question']}** ({row['engine']}: {', '.join(flags)})")
    else:
        lines.append("*The client was not mentioned or cited in any answer this run.*")
    lines.append("")

    competitor_counts: dict[str, int] = {}
    for row in rows:
        for competitor in row.get("competitors_cited", []):
            competitor_counts[competitor] = competitor_counts.get(competitor, 0) + 1
    lines.append("## Competitors cited in answers")
    if competitor_counts:
        for competitor, count in sorted(competitor_counts.items(), key=lambda item: -item[1]):
            lines.append(f"- {competitor}: {count} answer(s)")
    else:
        lines.append("*No tracked competitor domains appeared in the returned sources.*")
    lines.append("")

    lines.extend(_share_of_voice_section(engines, rows))

    if enrichment:
        lines.extend(_enrichment_sections(engines, enrichment))

    return "\n".join(lines)


def _enrichment_sections(engines: list[str], enrichment: dict) -> list[str]:
    """Render the Y.6–Y.12 report sections.

    Order: the FOUNDATIONAL readiness score (Y.12) leads as the cross-platform
    priority, ahead of per-engine AIVI (Y.6); then leaderboard, citations,
    sentiment (Y.7–Y.9); then per-engine recommendations + prioritisation (Y.10)
    and the cross-engine transfer section (Y.11)."""
    out: list[str] = []

    # Y.12 — foundational (transferable) readiness FIRST (Spec Y.12.2).
    foundational_block = enrichment.get("foundational", {}) or {}
    if foundational_block.get("result"):
        out.extend(foundational_mod.render_foundational_section(
            foundational_block.get("result", {}) or {},
            foundational_block.get("trend", []) or []))

    aivi_block = enrichment.get("aivi", {}) or {}
    out.extend(aivi_mod.render_aivi_section(
        aivi_block.get("per_engine", {}) or {},
        aivi_block.get("all_engine_avg"),
        aivi_block.get("trends", {}) or {}))

    out.append("## Competitor mention leaderboard")
    out.append(
        "Brands the AI *named* in its answers (not only cited domains), ranked "
        "by how many answers named them. This is the dominant AI-answer "
        "signal — which rivals the AI recommends in the client's place."
    )
    out.append("")
    leaderboards = enrichment.get("leaderboards", {}) or {}
    for engine in engines:
        out.extend(brand_mentions_mod.render_leaderboard_section(
            engine, leaderboards.get(engine, {}) or {}))
    candidates_file = enrichment.get("candidates_file")
    if candidates_file:
        out.append(
            f"*LLM-surfaced brand candidates not yet in `known_brands` were "
            f"written to `{os.path.basename(candidates_file)}` for review.*")
        out.append("")

    out.append("## Citations")
    out.append(
        "Every source URL the engines returned, categorised via the existing "
        "content/entity classifier and attributed to a brand — an outreach "
        "target list of the sources the AI trusts for this topic. Tracking "
        "params are retained (they identify the surfacing engine)."
    )
    out.append("")
    citations = enrichment.get("citations", {}) or {}
    for engine in engines:
        out.extend(citation_mod.render_citation_section(
            engine, citations.get(engine, []) or []))

    sent = enrichment.get("sentiment", {}) or {}
    out.extend(sentiment_mod.render_sentiment_section(
        sent.get("rows"), sent.get("enabled", False),
        sent.get("client_brand", "Client"), sent.get("top_competitor")))
    # D5/AV.5.2 — own-brand negative-sentiment alert (gated on sentiment.enabled).
    out.extend(sentiment_mod.render_negative_sentiment_alert(
        sent.get("rows"), sent.get("enabled", False),
        sent.get("client_brand", "Client")))

    # Y.10 — per-engine recommendations + platform prioritisation.
    strategy = enrichment.get("engine_strategy", {}) or {}
    out.extend(engine_recs_mod.render_engine_recommendations_section(
        strategy.get("recommendations", []) or [],
        strategy.get("prioritization", []) or []))

    # Y.11 — cross-engine transfer.
    transfer = enrichment.get("transfer", {}) or {}
    if transfer:
        out.extend(engine_transfer_mod.render_transfer_section(transfer))
    return out


def _share_of_voice_section(engines: list[str], rows: list[dict]) -> list[str]:
    """Render the cross-engine share-of-voice section (Y.5.3).

    Per engine: the client mention rate and citation rate (over that engine's
    answers this run) alongside the top competitor domains cited (reusing the
    existing ``competitors_cited`` detection). Then a per-persona breakdown of
    the client mention rate. Every value carries its run count and the section
    reiterates the snapshot caveat — visibility is comparative, and knowing
    which competitors the AI cites instead of the client is the actionable
    signal. Spec: yoast_geo_upgrade_spec_v1.md#Y.5.
    """
    out: list[str] = []
    out.append("## Cross-engine share of voice")
    out.append(
        "Visibility is comparative: the point is not only *whether* the "
        "client appears but *relative to whom*. Below, per engine, is the "
        "client's mention and citation rate this run alongside the competitor "
        "domains the engine cited instead — knowing which rivals the AI cites "
        "in the client's place is the actionable signal. All rates carry the "
        "run count; single-run values are snapshots (see the caveat above), "
        "so read the per-engine trend, not one number."
    )
    out.append("")
    out.append("| Engine | Answers | Client mention rate | Client citation rate "
               "| Top competitor domains cited |")
    out.append("|--------|---------|---------------------|----------------------"
               "|------------------------------|")
    for engine in engines:
        engine_rows = [r for r in rows if r["engine"] == engine]
        total = len(engine_rows)
        if not total:
            out.append(f"| {engine} | 0 | — | — | — |")
            continue
        mentioned = sum(1 for r in engine_rows if r["mentioned"])
        cited = sum(1 for r in engine_rows if r["cited"])
        comp_counts: dict[str, int] = {}
        for r in engine_rows:
            for competitor in r.get("competitors_cited", []):
                comp_counts[competitor] = comp_counts.get(competitor, 0) + 1
        if comp_counts:
            top = sorted(comp_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
            comp_cell = ", ".join(f"{dom} ({n})" for dom, n in top)
        else:
            comp_cell = "none"
        out.append(
            f"| {engine} | {total} | {_rate(mentioned, total)} "
            f"| {_rate(cited, total)} | {comp_cell} |"
        )
    out.append("")

    # Per-persona breakdown of the client mention rate. Only profile-sourced
    # rows carry a persona; if none do, state that plainly (principle 3).
    out.append("### Client mention rate by persona")
    persona_rows: dict[str, list[dict]] = {}
    for r in rows:
        persona = r.get("persona")
        if persona:
            persona_rows.setdefault(persona, []).append(r)
    if persona_rows:
        out.append("| Persona | Answers | Client mention rate |")
        out.append("|---------|---------|---------------------|")
        for persona in sorted(persona_rows):
            prows = persona_rows[persona]
            total = len(prows)
            mentioned = sum(1 for r in prows if r["mentioned"])
            out.append(f"| {persona} | {total} | {_rate(mentioned, total)} |")
    else:
        out.append(
            "*No persona-tagged questions this run — no client profile was "
            "wired in, so profile-seeded persona probing was skipped. The "
            "per-persona breakdown appears once a client profile is present.*"
        )
    out.append("")
    return out


# ---------------------------------------------------------------------------
# serp-compete AV export (post-run hook)
# ---------------------------------------------------------------------------

def _safe_write_av_export(db_path: str, out_dir: str, client_slug: str,
                          client_name: str | None, run_ts: str | None) -> str | None:
    """Write the serp-compete AV export from stored rows — never raises (P15).

    A paid probe run must not abort because the downstream serp-compete export
    hit a problem, so every failure (including ImportError) is caught and logged.
    Returns the export path, or None on failure.

    Spec:  discover AV-EXPORT (serp-compete C1 dependency).
    Tests: tests/test_ai_visibility_export.py::test_hook_guard_never_aborts_run
    """
    try:
        from ai_visibility_export import export_latest
        return export_latest(db_path, out_dir=out_dir, client_slug=client_slug,
                             client_name=client_name, run_ts=run_ts)
    except Exception as exc:  # never abort a paid run on an export problem (P15)
        logger.warning("AV export skipped: %s", exc)
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Probe AI engines (Claude/Gemini/OpenAI/Perplexity) for client mentions and citations."
    )
    parser.add_argument("--json", default=None,
                        help="Path to market_analysis_*.json (default: latest)")
    parser.add_argument("--engines", default=None,
                        help="Comma-separated engine list (overrides config), e.g. --engines claude")
    parser.add_argument("--yes", action="store_true",
                        help="Confirm the paid API spend (cost guard)")
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Override ai_visibility.max_questions (per-engine cap)")
    parser.add_argument("--db", default="serp_data.db", help="SQLite database path")
    parser.add_argument("--out", default=None, help="Output markdown path")
    parser.add_argument("--config", default="config.yml", help="Config path")
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    av_config = config.get("ai_visibility", {}) or {}
    engines = resolve_engines(args.engines, av_config)

    json_path = args.json or _latest_analysis_json(config)
    if not json_path or not os.path.exists(json_path):
        logger.error("No market_analysis_*.json found — run the pipeline first or pass --json.")
        return 1
    logger.info("Loading market analysis: %s", json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    vocab = load_serp_vocab()
    serpapi_location = (config.get("serpapi", {}) or {}).get(
        "location", "Vancouver, British Columbia, Canada")
    city = serpapi_location.split(",")[0].strip()
    max_questions = args.max_questions or int(av_config.get("max_questions", DEFAULT_MAX_QUESTIONS))
    # situational_templates is a persona-keyed map (Y.4). No client profile is
    # wired into the probe until Phase B (Y.5), so expand ALL persona blocks
    # here (backward-compatible superset). Spec: yoast_geo_upgrade_spec_v1.md#Y.4.
    situational_templates = flatten_situational_templates(
        vocab.get("situational_templates", []))

    # Y.5: profile-seeded persona questions become the highest-priority probe
    # source (gate Y-D1: augment, never replace). Absent/malformed profile ⇒
    # empty list ⇒ the precedence collapses to the original G.1 behaviour.
    client_slug = str(av_config.get("client_slug", DEFAULT_CLIENT_SLUG))
    profiles = load_client_profiles()
    profile = profiles.get(client_slug)
    if profile:
        profile_qs = generate_profile_questions(profile)
        logger.info(
            "Client profile '%s' loaded: %d persona-seeded questions.",
            client_slug, len(profile_qs))
    else:
        profile_qs = []
        logger.info(
            "No client profile for slug '%s' — profile questions skipped; "
            "falling back to keyword-derived probes.", client_slug)

    questions = build_question_set(
        data, situational_templates, city, max_questions,
        profile_questions=profile_qs)
    if not questions:
        logger.error("No probe questions could be built from %s.", json_path)
        return 1

    # Y-D4 hard ceiling on total paid calls across questions × engines. When
    # the plan exceeds max_total_calls the question set is truncated so the
    # ceiling is never breached, and the plan line states both figures.
    max_total_calls = int(av_config.get("max_total_calls", DEFAULT_MAX_TOTAL_CALLS))
    ceiling_applied = False
    if max_total_calls > 0 and len(questions) * len(engines) > max_total_calls:
        allowed = max_total_calls // max(len(engines), 1)
        questions = questions[:allowed]
        ceiling_applied = True

    total_calls = len(questions) * len(engines)
    plan = (
        f"AI visibility probe plan: {len(questions)} questions x {len(engines)} engines "
        f"({', '.join(engines)}) = {total_calls} paid API calls "
        f"(cap {max_questions} questions per engine; "
        f"max_total_calls ceiling {max_total_calls})."
    )
    if ceiling_applied:
        plan += (
            f" Question set truncated to {len(questions)} to stay within the "
            f"{max_total_calls}-call ceiling."
        )
    print(plan)
    if not (args.yes or av_config.get("assume_yes", False)):
        print(
            "Cost guard: no API calls were made. Re-run with --yes "
            "(or set ai_visibility.assume_yes: true in config.yml) to confirm the spend."
        )
        return 0

    probes, skipped = build_probes(engines, av_config)
    if not probes:
        logger.error("No engines available (all skipped) — nothing to run.")
        return 1

    analysis_cfg = config.get("analysis_report", {}) or {}
    client_name_patterns = analysis_cfg.get("client_name_patterns", []) or []
    client_domain = analysis_cfg.get("client_domain", "") or ""
    competitor_domains = list(config.get("known_brands", []) or []) + top_competitor_domains(
        data, client_domain)
    geo_context = av_config.get(
        "geo_context", f"I'm in {analysis_cfg.get('location', 'North Vancouver, BC')}.")

    run_ts = datetime.now(_UTC).isoformat()
    rows = run_engine_probes(
        probes, questions, geo_context,
        client_name_patterns, client_domain, competitor_domains, run_ts)

    if rows:
        save_probe_rows(
            args.db, rows,
            store_raw_answer=bool(av_config.get("store_raw_answer", False)),
            raw_answer_max_chars=av_config.get(
                "raw_answer_max_chars", DEFAULT_RAW_ANSWER_MAX_CHARS),
        )
    history_runs = int(av_config.get("history_runs", DEFAULT_HISTORY_RUNS))
    trends = {
        engine: get_engine_trend(args.db, engine, limit=history_runs)
        for engine in engines
    }

    # Phase D read-side enrichment (Y.6–Y.9): leaderboard, citations, sentiment,
    # AIVI — from the answers already fetched. Sentiment counts against the same
    # max_total_calls ceiling; brand-LLM + sentiment default OFF (zero calls).
    topic = re.sub(r"^ai_visibility_|\.md$", "",
                   os.path.basename(_derive_output_path(json_path)))
    topic = re.sub(r"_\d{8}_\d{4}$", "", topic) or "report"
    sentiment_budget = None
    if sentiment_mod.is_enabled(config.get("sentiment", {}) or {}):
        sentiment_budget = max(0, max_total_calls - total_calls)
    enrichment = run_report_enrichment(
        rows, engines, config, data, run_ts, topic, args.db, json_path,
        out_dir=os.path.dirname(os.path.abspath(args.out)) if args.out else ".",
        sentiment_call_budget=sentiment_budget)

    report = generate_report(
        json_path, run_ts, engines, rows, trends, skipped, geo_context,
        analysis_cfg.get("client_name", "Client"), enrichment=enrichment)
    out_path = args.out or _derive_output_path(json_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    # AV-EXPORT: refresh the serp-compete consumption file from this run's stored
    # brand_mentions/ai_citations (pure read, no re-probe). The export is a
    # Compete-bound artifact like competitor_handoff_*.json, so it always lands in
    # output/ regardless of where the human --out report goes. Guarded so an
    # export failure can never abort a paid probe run. Spec: discover AV-EXPORT.
    av_path = _safe_write_av_export(
        args.db, "output", client_slug, analysis_cfg.get("client_name"), run_ts)
    if av_path:
        print(f"AI_VISIBILITY_EXPORT_OUT={av_path}")

    executed = len(rows)
    print(f"AI visibility probes: {executed} answers recorded across {len(probes)} engine(s).")
    logger.info("Report written: %s", out_path)
    print(f"AI_VISIBILITY_OUT={out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
