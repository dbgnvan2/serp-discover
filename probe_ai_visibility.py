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

from http_retry import post_with_transient_retry
from pattern_matching import load_serp_vocab
from query_variants import situational_template_probes

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

VALID_ENGINES = ("claude", "gemini")

DEFAULT_ENGINES = ["claude", "gemini"]
DEFAULT_MAX_QUESTIONS = 20          # per engine (gate D-2 budget default)
DEFAULT_HISTORY_RUNS = 5

# Model ids come from config (ai_visibility.claude_model / gemini_model);
# these are only the fallbacks when the config block is absent.
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_CLAUDE_WEB_SEARCH_TOOL = "web_search_20260209"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

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
                       max_questions: int, min_words: int = 6) -> list[dict]:
    """Build the probe question list, capped at *max_questions* (per engine).

    Priority order (G.1 / T.5 output): the run's situational_probes when
    present, else 6+-word PAA questions, else serp_vocab.yml
    situational_templates filled per root keyword.
    """
    questions: list[dict] = []
    seen: set[str] = set()

    def _add(query: str, source: str) -> None:
        query = (query or "").strip()
        key = query.lower()
        if query and key not in seen and len(questions) < max_questions:
            seen.add(key)
            questions.append({"query": query, "source": source})

    for row in data.get("situational_probes") or []:
        _add(str(row.get("Executed_Query") or ""), "situational_probe")
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
            answer_excerpt          TEXT
        )''')
        conn.commit()


def save_probe_rows(db_path: str, rows: list[dict]) -> None:
    init_probe_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"""INSERT INTO {PROBE_TABLE}
                (run_ts, engine, model, question, mentioned, cited,
                 competitor_domains_json, answer_excerpt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["run_ts"], row["engine"], row["model"], row["question"],
                    int(bool(row["mentioned"])), int(bool(row["cited"])),
                    json.dumps(row.get("competitors_cited", [])),
                    (row.get("answer_excerpt") or "")[:400],
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
            })
    return rows


def _rate(count: int, total: int) -> str:
    if not total:
        return "—"
    return f"{count}/{total} ({count / total:.0%})"


def generate_report(source_json: str, run_ts: str, engines: list[str],
                    rows: list[dict], trends: dict, skipped: list[dict],
                    geo_context: str, client_name: str) -> str:
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

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Probe AI engines (Claude/Gemini) for client mentions and citations."
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
    questions = build_question_set(
        data, vocab.get("situational_templates", []), city, max_questions)
    if not questions:
        logger.error("No probe questions could be built from %s.", json_path)
        return 1

    total_calls = len(questions) * len(engines)
    print(
        f"AI visibility probe plan: {len(questions)} questions x {len(engines)} engines "
        f"({', '.join(engines)}) = {total_calls} paid API calls "
        f"(cap {max_questions} questions per engine)."
    )
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
        save_probe_rows(args.db, rows)
    history_runs = int(av_config.get("history_runs", DEFAULT_HISTORY_RUNS))
    trends = {
        engine: get_engine_trend(args.db, engine, limit=history_runs)
        for engine in engines
    }

    report = generate_report(
        json_path, run_ts, engines, rows, trends, skipped, geo_context,
        analysis_cfg.get("client_name", "Client"))
    out_path = args.out or _derive_output_path(json_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    executed = len(rows)
    print(f"AI visibility probes: {executed} answers recorded across {len(probes)} engine(s).")
    logger.info("Report written: %s", out_path)
    print(f"AI_VISIBILITY_OUT={out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
