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

import brand_match
from domain_utils import normalize_domain

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
    domain = normalize_domain(url_or_domain)
    label = domain.split(".")[0] if domain else ""
    return label


#: Host labels that are never a brand name. Technical, not editorial: these
#: are public-suffix and hosting labels, so "com" or "ca" matching its own
#: host must not let a one-word harvested source through.
_NON_BRAND_LABELS = {
    "www", "www2", "com", "org", "net", "ca", "co", "uk", "us", "io", "info",
    "biz", "gov", "edu", "int", "au", "nz", "eu", "blog", "news", "shop",
    "app", "web", "site", "online", "store",
}


def _domain_labels(url_or_domain: str) -> set[str]:
    """Every label of a host that could plausibly be the brand name.

    ``_domain_stub`` takes ``host.split(".")[0]``, so any subdomained host
    loses its brand: ``ca.indeed.com`` -> ``ca``, ``www2.pathways.ca`` ->
    ``www2``. The single-token keep rule in ``build_gazetteer`` compared the
    harvested name against that stub, so a legitimate one-word brand on a
    ``ca.*`` / ``blog.*`` host was dropped from the gazetteer — and in a
    ``.ca`` directory market that is the common case, not the edge. Dropping
    a real rival shrinks the leaderboard and moves the client's rank and
    authority sub-score in the client's favour, which is the wrong direction
    to be wrong in.
    """
    raw = str(url_or_domain or "").strip()
    parsed = urlparse(raw if "//" in raw else "//" + raw)
    domain = (parsed.netloc or raw).lower()
    return {label for label in domain.split(".")
            if label and label not in _NON_BRAND_LABELS}


def build_gazetteer(known_brands: list[str], analysis_data: dict | None,
                    limit: int = 40,
                    generic_source_stoplist: list[str] | None = None) -> list[str]:
    """Build the deterministic brand gazetteer.

    Combines the editorial ``known_brands`` list with the most frequent
    competitor *sources/titles* harvested from the market_analysis JSON's
    organic results. Returns a de-duplicated, insertion-ordered list of brand
    strings (original casing preserved from the first occurrence).

    An old analysis JSON without ``organic_results`` (principle 3) simply
    contributes nothing — no crash, no fabricated brands.

    D-M-14: a *harvested* source is only a brand if it looks like one. A
    single generic token ("Indeed", "Pathways") matched ordinary answer text
    and took a leaderboard rank beside a real competitor, so a harvested
    source is kept only when it has two or more tokens, or is a single token
    that matches a *label of its own row's host* (``pathways.ca`` →
    "Pathways" is a brand; a bare "Indeed" beside ``ca.indeed.com`` still is,
    because "indeed" is a label of that host; a bare "Pathways" beside
    ``vch.ca`` is not). Public-suffix and hosting labels ("ca", "com",
    "www2") never count as the brand. *generic_source_stoplist* is the
    editorial override (``config.yml ai_visibility.generic_source_stoplist``)
    and drops a harvested name outright. ``known_brands`` is editorial and is
    never filtered — if the user put it there, it is a brand. Spec: D3.10.
    """
    stoplist = {_norm(w) for w in (generic_source_stoplist or []) if str(w).strip()}
    harvested = 0
    dropped_stoplist = 0
    dropped_generic = 0
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
        harvested += 1
        if key in stoplist:
            dropped_stoplist += 1
            continue
        if len(key.split()) < 2 \
                and key not in _domain_labels(row.get("Link") or ""):
            # One generic word that is not even a label of this row's host.
            dropped_generic += 1
            continue
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, source)
    for key, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        _add(display[key])

    # P2: say what was excluded rather than silently shrinking the field.
    if dropped_stoplist or dropped_generic:
        logger.info(
            "build_gazetteer: kept %d of %d harvested sources "
            "(%d on the editorial stoplist, %d a single generic token).",
            len(counts), harvested, dropped_stoplist, dropped_generic)

    return ordered[:limit]


# ---------------------------------------------------------------------------
# Extraction passes
# ---------------------------------------------------------------------------

def gazetteer_pass(answer_text: str, gazetteer: list[str],
                   negative_terms: list[str] | None = None) -> list[str]:
    """Deterministic, case-insensitive gazetteer match against one answer.

    Returns the gazetteer brands (original casing) found as whole-word phrases
    in the answer text, in gazetteer order. Deterministic given inputs.
    Spec: Y.7.1.

    P5 / D3.12: the gazetteer is seeded with the client's own name patterns,
    so this matcher decides the client's mention count, its leaderboard rank,
    the AIVI Ranking axis and the authority sub-score. It therefore honours
    the same editorial *negative_terms* as ``detect_visibility`` — a match
    inside "living systems theory" is the subject, not a brand — through the
    one shared matcher (``brand_match.matches_patterns``).
    """
    return [brand for brand in gazetteer
            if brand_match.matches_patterns(answer_text, [brand], negative_terms)]


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
                          llm_runner=None,
                          negative_terms: list[str] | None = None
                          ) -> tuple[list[dict], list[str]]:
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

    for brand in gazetteer_pass(answer_text, gazetteer, negative_terms):
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
                      model: str, llm_runner=None,
                      negative_terms: list[str] | None = None) -> dict:
    """Aggregate a mention-count leaderboard across all probed answers.

    ``answers`` is a list of ``{engine, answer_text}`` dicts. Returns::

        {
          "questions_total": int,
          "rows": [ {brand, mention_count, is_client, source}, ... ],
          "client_rank": int | None,       # 1-based; None if not mentioned
          "unknown_candidates": [str, ...] # LLM-surfaced, not in gazetteer
        }

    ``rows`` are listed by mention_count desc, then alphabetically so the
    ORDER is deterministic (Spec Y.7.3) — but the ``rank`` is competition
    ranking: equal mention counts share a rank, and each row carries
    ``tied_with`` (how many others hold that rank). Alphabetical order used
    to decide which of two brands on the same count was "rank 1", and the
    client's own rank was read off that position, so a tie read as a loss to
    whoever sorted first (D-M-14). ``client_rank`` is now the shared rank, and
    ``client_tied_with`` says how many brands hold it. PYTHON computes every
    count and rank; the LLM (if enabled) only contributed labels. Spec: D3.11.

    *negative_terms* (editorial, ``config.yml ai_visibility.negative_terms``)
    reaches the gazetteer matcher so the client's own mention count carries
    the same veto as its ``mentioned`` flag — P5, cold-review finding 2.
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
            llm_runner=llm_runner, negative_terms=negative_terms)
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

    # Competition ranking: 1, 2, 2, 4 — equal counts share a rank.
    per_count: dict[int, int] = {}
    for row in rows:
        per_count[row["mention_count"]] = per_count.get(row["mention_count"], 0) + 1
    rank_of: dict[int, int] = {}
    position = 1
    for count in sorted(per_count, reverse=True):
        rank_of[count] = position
        position += per_count[count]
    for row in rows:
        row["rank"] = rank_of[row["mention_count"]]
        row["tied_with"] = per_count[row["mention_count"]] - 1

    client_row = next((r for r in rows if r["is_client"]), None)

    return {
        "questions_total": len(answers or []),
        "rows": rows,
        "client_rank": client_row["rank"] if client_row else None,
        "client_tied_with": client_row["tied_with"] if client_row else None,
        "unknown_candidates": unknown_candidates,
    }


def client_ranking_axis(client_rank: int | None, leaderboard_size: int,
                        client_tied_with: int | None = 0) -> float:
    """Normalise the client's leaderboard rank to a 0–100 Ranking axis (Y.6).

    Rank 1 outright → 100; unranked (``None``) → 0. Lower ranks scale down
    linearly over the leaderboard size so a longer competitor field is not
    unduly punishing. Spec: yoast_geo_upgrade_spec_v1.md#Y.6 (Ranking axis).

    A *shared* rank does not score as an outright one (cold-review finding 7).
    Competition ranking (D3.11) gives every brand on the same mention count
    the same number, so a client tied at rank 1 with five others would have
    scored a perfect 100 while the prose beside it said "tied with 5 other
    brand(s) — not ahead of them". The tie is split: the effective rank is
    ``rank + tied_with / 2``, the mid-point of the positions the tied brands
    occupy, which is what a tie is worth.
    """
    if client_rank is None or leaderboard_size <= 0:
        return 0.0
    tied = max(0, int(client_tied_with or 0))
    effective = client_rank + tied / 2.0
    if leaderboard_size == 1:
        return 100.0
    # rank 1 -> 100, rank N -> a small positive floor rather than 0.
    axis = 100.0 * (leaderboard_size - effective) / (leaderboard_size - 1)
    return round(max(0.0, min(100.0, axis)), 2)


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
        conn.execute(f"DELETE FROM {BRAND_MENTIONS_TABLE} WHERE run_ts = ? AND engine = ?",
                     (run_ts, engine))   # idempotent per (run_ts, engine) — P8
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
    for position, row in enumerate(rows[:top_n], start=1):
        flag = " (client)" if row["is_client"] else ""
        # D-M-14: the printed rank is the competition rank, so two brands on
        # the same count show the same number instead of the alphabetical
        # order deciding a winner.
        rank = row.get("rank", position)
        tied = row.get("tied_with") or 0
        tie_note = f" (tied with {tied})" if tied else ""
        out.append(
            f"| {rank}{tie_note} | {row['brand']}{flag} | {row['mention_count']}/{total} "
            f"| {row['source']} |"
        )
    client_rank = leaderboard.get("client_rank")
    if client_rank is not None:
        out.append("")
        tied = leaderboard.get("client_tied_with") or 0
        if tied:
            out.append(
                f"**Client rank:** #{client_rank} of {len(rows)} named brands, "
                f"tied with {tied} other brand(s) on the same mention count — "
                f"not ahead of them.")
        else:
            out.append(f"**Client rank:** #{client_rank} of {len(rows)} named brands.")
    else:
        out.append("")
        out.append(
            "**Client rank:** not mentioned — the client was not named in any "
            "of this engine's answers this run."
        )
    out.append("")
    return out
