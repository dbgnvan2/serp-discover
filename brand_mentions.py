#!/usr/bin/env python3
"""brand_mentions.py — competitor mention leaderboard via brand-entity extraction.

Spec: yoast_geo_upgrade_spec_v1.md#Y.7 (decision gate Y-D7).

The AI-visibility probe (``probe_ai_visibility.py``) only detects competitors
when their *domain is cited*. Yoast's report ranked 24 brands by how often they
were *named* in the answer text — many without any link. Answer-text brand
naming is the dominant signal in AI answers, so this module extracts named
brand/organization entities from each probed answer and aggregates a
mention-count leaderboard with the client's own rank.

Y-D7 reconciliation with design principle 1 ("deterministic Python computes;
the LLM writes"):

  * A **gazetteer pass** (deterministic) runs FIRST: it matches the editorial
    ``known_brands`` list plus the top competitor names/domains harvested from
    the latest market_analysis JSON, case-insensitively.
  * An **LLM pass** (gated, OFF by default via ``brand_mentions.llm_extraction:
    false``) only fills unknowns — it lists organisation names present in the
    text. Its output is treated as a MEASURED INPUT, stored verbatim; PYTHON
    computes every mention count, rank, and percentage from those stored labels.
  * New brands the LLM surfaces that are not already known are written to a
    review file ``brand_mentions_candidates_<topic>_<ts>.md`` (pattern:
    ``domain_override_candidates.md``) so the user can promote them into
    ``known_brands`` — no silent taxonomy growth.

Persistence: a ``brand_mentions`` SQLite table (``run_ts, engine, brand,
mention_count, questions_total, is_client, source``) so the leaderboard is
trendable per engine (design principle 5). All timestamps UTC.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

try:
    from datetime import UTC as _UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _tz
    _UTC = _tz.utc

logger = logging.getLogger(__name__)

BRAND_MENTIONS_TABLE = "brand_mentions"

#: Sources recorded per leaderboard row.
SOURCE_GAZETTEER = "gazetteer"
SOURCE_LLM = "llm"


# ---------------------------------------------------------------------------
# Gazetteer construction (deterministic — no network, no LLM)
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Case/whitespace-normalised key for de-duplication."""
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _domain_stub(url_or_domain: str) -> str:
    """Human-ish brand label from a domain: ``livingsystems.ca`` -> ``livingsystems``."""
    raw = str(url_or_domain or "").strip()
    parsed = urlparse(raw if "//" in raw else "//" + raw)
    domain = (parsed.netloc or raw).lower().removeprefix("www.")
    label = domain.split(".")[0] if domain else ""
    return label


def build_gazetteer(known_brands: list[str], analysis_data: dict | None,
                    limit: int = 40) -> list[str]:
    """Build the deterministic brand gazetteer.

    Combines the editorial ``known_brands`` list with the most frequent
    competitor *sources/titles* harvested from the market_analysis JSON's
    organic results. Returns a de-duplicated, insertion-ordered list of brand
    strings (original casing preserved from the first occurrence).

    An old analysis JSON without ``organic_results`` (principle 3) simply
    contributes nothing — no crash, no fabricated brands.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = str(name or "").strip()
        key = _norm(name)
        if name and key and key not in seen:
            seen.add(key)
            ordered.append(name)

    for brand in known_brands or []:
        _add(brand)

    # Harvest recurring competitor "Source" labels from organic results. These
    # are the human brand names Google shows (e.g. "Psychology Today"), which is
    # exactly the answer-text naming Y.7 targets. Fall back to a domain stub.
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for row in (analysis_data or {}).get("organic_results") or []:
        source = str(row.get("Source") or "").strip()
        # "Reddit · r/askvan" -> "Reddit"; keep the leading brand token group.
        if source:
            source = source.split("·")[0].strip()
        if not source:
            source = _domain_stub(row.get("Link") or "")
        if not source:
            continue
        key = _norm(source)
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, source)
    for key, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        _add(display[key])

    return ordered[:limit]


# ---------------------------------------------------------------------------
# Extraction passes
# ---------------------------------------------------------------------------

def gazetteer_pass(answer_text: str, gazetteer: list[str]) -> list[str]:
    """Deterministic, case-insensitive gazetteer match against one answer.

    Returns the gazetteer brands (original casing) found as whole-word phrases
    in the answer text, in gazetteer order. Deterministic given inputs.
    Spec: Y.7.1.
    """
    text = str(answer_text or "")
    found: list[str] = []
    for brand in gazetteer:
        pattern = r"\b" + re.escape(str(brand)) + r"\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(brand)
    return found


def llm_extract_brands(answer_text: str, model: str,
                       llm_runner=None) -> list[str]:
    """Gated LLM extraction of organisation names from one answer.

    The LLM lists organisation/brand names literally present in the text. The
    result is a MEASURED INPUT stored verbatim (Y-D7): Python does all counting
    downstream. ``llm_runner`` defaults to ``brief_llm.run_llm_report`` and is
    injectable for tests (all calls mocked; zero live calls).

    Returns a list of raw name strings (may include unknowns). Never raises on
    a malformed model response — a bad payload yields ``[]`` and a warning.
    """
    if llm_runner is None:
        from brief_llm import run_llm_report as llm_runner  # lazy: keeps import light
    system_prompt = (
        "You extract named organisations from text. Return ONLY a JSON array of "
        "the distinct organisation, company, clinic, or brand names that appear "
        "verbatim in the passage. Do not invent names, do not include people, "
        "cities, or generic terms. If none appear, return []."
    )
    user_prompt = f"Passage:\n{answer_text or ''}\n\nJSON array of organisation names:"
    try:
        raw = llm_runner(system_prompt, user_prompt, model, 512)
    except Exception as exc:  # network/model failure must never abort the run
        logger.warning("brand_mentions LLM extraction failed: %s", exc)
        return []
    return _parse_llm_names(raw)


def _parse_llm_names(raw: str) -> list[str]:
    """Parse a JSON array of names from a (possibly noisy) LLM response."""
    if not raw:
        return []
    text = str(raw).strip()
    # Tolerate code fences / prose around the array.
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("brand_mentions: could not parse LLM name array: %r", raw[:120])
        return []
    if not isinstance(parsed, list):
        return []
    names: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


# ---------------------------------------------------------------------------
# Per-answer extraction + aggregation
# ---------------------------------------------------------------------------

def extract_answer_brands(answer_text: str, gazetteer: list[str],
                          llm_extraction: bool, model: str,
                          llm_runner=None) -> tuple[list[dict], list[str]]:
    """Extract brands from one answer, two-pass (Y-D7).

    Returns ``(brands, unknowns)`` where ``brands`` is a list of
    ``{brand, source}`` dicts (de-duplicated, gazetteer wins over LLM for the
    same normalised name) and ``unknowns`` are LLM-surfaced names not present in
    the gazetteer (candidates for ``known_brands`` promotion).

    When ``llm_extraction`` is false the LLM pass is skipped entirely — the
    gazetteer alone still produces a leaderboard (Spec: Y.7.2).
    """
    brands: list[dict] = []
    seen: set[str] = set()
    gaz_keys = {_norm(b) for b in gazetteer}

    for brand in gazetteer_pass(answer_text, gazetteer):
        key = _norm(brand)
        if key not in seen:
            seen.add(key)
            brands.append({"brand": brand, "source": SOURCE_GAZETTEER})

    unknowns: list[str] = []
    if llm_extraction:
        for name in llm_extract_brands(answer_text, model, llm_runner=llm_runner):
            key = _norm(name)
            if not key or key in seen:
                continue  # already found by gazetteer (gazetteer wins)
            seen.add(key)
            brands.append({"brand": name, "source": SOURCE_LLM})
            if key not in gaz_keys:
                unknowns.append(name)
    return brands, unknowns


def build_leaderboard(answers: list[dict], gazetteer: list[str],
                      client_patterns: list[str], llm_extraction: bool,
                      model: str, llm_runner=None) -> dict:
    """Aggregate a mention-count leaderboard across all probed answers.

    ``answers`` is a list of ``{engine, answer_text}`` dicts. Returns::

        {
          "questions_total": int,
          "rows": [ {brand, mention_count, is_client, source}, ... ],
          "client_rank": int | None,       # 1-based; None if not mentioned
          "unknown_candidates": [str, ...] # LLM-surfaced, not in gazetteer
        }

    ``rows`` are ranked by mention_count desc, ties broken alphabetically
    (deterministic — Spec Y.7.3). PYTHON computes every count and rank; the LLM
    (if enabled) only contributed labels.
    """
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    source_of: dict[str, str] = {}
    unknown_candidates: list[str] = []
    unknown_seen: set[str] = set()

    client_keys = {_norm(p) for p in (client_patterns or []) if str(p).strip()}

    for ans in answers or []:
        brands, unknowns = extract_answer_brands(
            ans.get("answer_text", ""), gazetteer, llm_extraction, model,
            llm_runner=llm_runner)
        for entry in brands:
            key = _norm(entry["brand"])
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, entry["brand"])
            # Gazetteer source is authoritative over LLM for the same brand.
            if source_of.get(key) != SOURCE_GAZETTEER:
                source_of[key] = entry["source"]
        for name in unknowns:
            key = _norm(name)
            if key not in unknown_seen:
                unknown_seen.add(key)
                unknown_candidates.append(name)

    def _is_client(key: str) -> bool:
        return any(ck and ck in key for ck in client_keys)

    rows = [
        {
            "brand": display[key],
            "mention_count": counts[key],
            "is_client": _is_client(key),
            "source": source_of.get(key, SOURCE_GAZETTEER),
        }
        for key in counts
    ]
    rows.sort(key=lambda r: (-r["mention_count"], _norm(r["brand"])))

    client_rank = None
    for index, row in enumerate(rows, start=1):
        if row["is_client"]:
            client_rank = index
            break

    return {
        "questions_total": len(answers or []),
        "rows": rows,
        "client_rank": client_rank,
        "unknown_candidates": unknown_candidates,
    }


def client_ranking_axis(client_rank: int | None, leaderboard_size: int) -> float:
    """Normalise the client's leaderboard rank to a 0–100 Ranking axis (Y.6).

    Rank 1 → 100; unranked (``None``) → 0. Lower ranks scale down linearly over
    the leaderboard size so a longer competitor field is not unduly punishing.
    Spec: yoast_geo_upgrade_spec_v1.md#Y.6 (Ranking axis).
    """
    if client_rank is None or leaderboard_size <= 0:
        return 0.0
    if leaderboard_size == 1:
        return 100.0
    # rank 1 -> 100, rank N -> a small positive floor rather than 0.
    return round(100.0 * (leaderboard_size - client_rank) / (leaderboard_size - 1), 2)


# ---------------------------------------------------------------------------
# Candidates review file (pattern: domain_override_candidates.md)
# ---------------------------------------------------------------------------

def render_candidates_markdown(candidates: list[str], topic: str,
                               source_json: str | None) -> str:
    """Render the ``brand_mentions_candidates`` review file body.

    Lists LLM-surfaced brand names not already in ``known_brands`` so the user
    can promote them — no silent taxonomy growth (Spec: Y.7.2 / Y.7.5).
    """
    lines: list[str] = []
    lines.append("# Brand Mention Review Candidates")
    lines.append("")
    lines.append(f"Topic: `{topic}`")
    lines.append(f"Source analysis JSON: `{source_json or '—'}`")
    lines.append(
        "These organisation names were surfaced by the gated LLM extraction "
        "pass but are NOT in `known_brands`. Review and promote the real "
        "competitor brands into `known_brands` in `config.yml` so future runs "
        "count them deterministically (no silent taxonomy growth)."
    )
    lines.append("")
    if not candidates:
        lines.append("No new brand candidates surfaced this run.")
        return "\n".join(lines) + "\n"
    lines.append("| Candidate brand | Suggested action |")
    lines.append("| --- | --- |")
    for name in candidates:
        lines.append(f"| {name} | add to `known_brands` if a real competitor |")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_candidates_file(candidates: list[str], topic: str, run_ts: str,
                          source_json: str | None, out_dir: str = ".") -> str | None:
    """Write ``brand_mentions_candidates_<topic>_<ts>.md``; return its path.

    Returns ``None`` when there are no candidates (nothing to review).
    """
    if not candidates:
        return None
    ts = re.sub(r"[^0-9]", "", run_ts)[:12] or datetime.now(_UTC).strftime("%Y%m%d%H%M")
    fname = f"brand_mentions_candidates_{topic}_{ts}.md"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_candidates_markdown(candidates, topic, source_json))
    return path


# ---------------------------------------------------------------------------
# Persistence (probe_ai_visibility.py conventions: parameterised SQL, UTC ts,
# CREATE TABLE IF NOT EXISTS — idempotent, per-engine, trendable).
# ---------------------------------------------------------------------------

def init_brand_mentions_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {BRAND_MENTIONS_TABLE} (
            run_ts          TEXT,
            engine          TEXT,
            brand           TEXT,
            mention_count   INTEGER,
            questions_total INTEGER,
            is_client       INTEGER,
            source          TEXT
        )''')
        conn.commit()


def save_brand_mentions(db_path: str, run_ts: str, engine: str,
                        leaderboard: dict) -> None:
    """Persist one engine's leaderboard rows for a run."""
    init_brand_mentions_table(db_path)
    questions_total = leaderboard.get("questions_total", 0)
    rows = leaderboard.get("rows", [])
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"""INSERT INTO {BRAND_MENTIONS_TABLE}
                (run_ts, engine, brand, mention_count, questions_total,
                 is_client, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, engine, r["brand"], int(r["mention_count"]),
                 int(questions_total), int(bool(r["is_client"])), r["source"])
                for r in rows
            ],
        )
        conn.commit()


def get_brand_mentions_trend(db_path: str, engine: str,
                             limit: int = 5) -> list[dict]:
    """Per-run leaderboards for one engine, oldest→newest (trendable)."""
    init_brand_mentions_table(db_path)
    with sqlite3.connect(db_path) as conn:
        run_ids = [
            r[0] for r in conn.execute(
                f"""SELECT DISTINCT run_ts FROM {BRAND_MENTIONS_TABLE}
                    WHERE engine = ? ORDER BY run_ts DESC LIMIT ?""",
                (engine, limit),
            ).fetchall()
        ]
        out: list[dict] = []
        for run_ts in run_ids:
            rows = conn.execute(
                f"""SELECT brand, mention_count, is_client, source, questions_total
                    FROM {BRAND_MENTIONS_TABLE}
                    WHERE engine = ? AND run_ts = ?
                    ORDER BY mention_count DESC, brand ASC""",
                (engine, run_ts),
            ).fetchall()
            out.append({
                "run_ts": run_ts,
                "questions_total": rows[0][4] if rows else 0,
                "rows": [
                    {"brand": b, "mention_count": mc, "is_client": bool(ic),
                     "source": src}
                    for b, mc, ic, src, _qt in rows
                ],
            })
    out.reverse()
    return out


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

def render_leaderboard_section(engine: str, leaderboard: dict,
                               top_n: int = 25) -> list[str]:
    """Render the ranked leaderboard for one engine, with the client's rank
    called out explicitly (or "not mentioned"). Spec: Y.7.4 report."""
    out: list[str] = []
    total = leaderboard.get("questions_total", 0)
    rows = leaderboard.get("rows", [])
    out.append(f"### {engine} — competitor mention leaderboard")
    if not rows:
        out.append("*No brands were named in this engine's answers this run.*")
        out.append("")
        return out
    out.append("| # | Brand | Mentions | Source |")
    out.append("|---|-------|----------|--------|")
    for index, row in enumerate(rows[:top_n], start=1):
        flag = " (client)" if row["is_client"] else ""
        out.append(
            f"| {index} | {row['brand']}{flag} | {row['mention_count']}/{total} "
            f"| {row['source']} |"
        )
    client_rank = leaderboard.get("client_rank")
    if client_rank is not None:
        out.append("")
        out.append(f"**Client rank:** #{client_rank} of {len(rows)} named brands.")
    else:
        out.append("")
        out.append(
            "**Client rank:** not mentioned — the client was not named in any "
            "of this engine's answers this run."
        )
    out.append("")
    return out
