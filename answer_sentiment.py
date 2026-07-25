#!/usr/bin/env python3
"""answer_sentiment.py — per-brand sentiment + aspect-keyword extraction (gated).

Spec: yoast_geo_upgrade_spec_v1.md#Y.9 (decision gate Y-D8).

Yoast reports % positive sentiment for the client and the top competitor, with
extracted positive/negative keyword chips that tell the client WHAT the AI
praises or flags. For a nonprofit whose reputation is the product, "what does
the AI say ABOUT us, not just whether it names us" is high-value.

Design (Y-D7 + Y-D8):

  * **OFF by default** (``sentiment.enabled: false``). A disabled run makes ZERO
    sentiment calls; the report reads "sentiment not measured"; Y.6 excludes the
    axis (principle 3 — absent data stated, not faked).
  * When enabled, ONE LLM classification per answer that mentions the client or
    the top competitor returns, as a MEASURED INPUT stored verbatim: a polarity
    label (positive/neutral/negative) plus short positive/negative aspect
    phrases. Reuses ``brief_llm`` conventions; model id from config.
  * **Python computes** % positive per brand from the stored labels (principle 1
    preserved via Y-D7). Aspect phrases are surfaced verbatim, never numeric.
  * Subject to the ``max_total_calls`` ceiling — each classification counts.

Persistence: an ``answer_sentiment`` SQLite table (``run_ts, engine, brand,
polarity, positive_aspects_json, negative_aspects_json, answer_excerpt``).
Feeds Y.6's Sentiment axis.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

SENTIMENT_TABLE = "answer_sentiment"

VALID_POLARITIES = ("positive", "neutral", "negative")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def is_enabled(sentiment_config: dict | None) -> bool:
    """Sentiment is OFF unless explicitly enabled (Spec Y.9.1)."""
    return bool((sentiment_config or {}).get("enabled", False))


def answer_mentions_brand(answer_text: str, brand_patterns: list[str]) -> bool:
    """True if any brand pattern appears in the answer (case-insensitive)."""
    text = _norm(answer_text)
    return any(_norm(p) and _norm(p) in text for p in (brand_patterns or []))


def classify_answer(answer_text: str, brand: str, model: str,
                    llm_runner=None) -> dict:
    """One gated LLM sentiment classification for a (answer, brand) pair.

    Returns ``{polarity, positive_aspects, negative_aspects}`` — the LLM output
    stored VERBATIM (Y-D7). ``llm_runner`` defaults to
    ``brief_llm.run_llm_report`` and is injectable for tests (all calls mocked).
    A malformed/failed response degrades to a neutral label with empty aspects,
    never raises.
    """
    if llm_runner is None:
        from brief_llm import run_llm_report as llm_runner
    system_prompt = (
        "You classify how a passage portrays a specific organisation. Return "
        "ONLY a JSON object with keys: \"polarity\" (one of positive, neutral, "
        "negative), \"positive_aspects\" (array of short verbatim phrases the "
        "passage praises about the organisation), and \"negative_aspects\" "
        "(array of short verbatim phrases the passage flags). Use [] when none. "
        "Judge only sentiment toward the named organisation."
    )
    user_prompt = (
        f"Organisation: {brand}\n\nPassage:\n{answer_text or ''}\n\n"
        "JSON object:"
    )
    try:
        raw = llm_runner(system_prompt, user_prompt, model, 512)
    except Exception as exc:
        logger.warning("answer_sentiment LLM classification failed: %s", exc)
        return {"polarity": "neutral", "positive_aspects": [], "negative_aspects": []}
    return _parse_classification(raw)


def _parse_classification(raw: str) -> dict:
    fallback = {"polarity": "neutral", "positive_aspects": [], "negative_aspects": []}
    if not raw:
        return fallback
    text = str(raw).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("answer_sentiment: could not parse classification: %r", raw[:120])
        return fallback
    if not isinstance(parsed, dict):
        return fallback
    polarity = str(parsed.get("polarity") or "neutral").strip().lower()
    if polarity not in VALID_POLARITIES:
        polarity = "neutral"

    def _phrases(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()]

    return {
        "polarity": polarity,
        "positive_aspects": _phrases(parsed.get("positive_aspects")),
        "negative_aspects": _phrases(parsed.get("negative_aspects")),
    }


def collect_sentiment(answers: list[dict], brand_targets: dict[str, list[str]],
                      model: str, llm_runner=None,
                      call_budget: int | None = None) -> tuple[list[dict], int]:
    """Classify each answer that mentions a target brand.

    ``answers`` is a list of ``{engine, answer_text}`` dicts. ``brand_targets``
    maps a brand display name → its match patterns (e.g. the client and the top
    competitor). Returns ``(rows, calls_made)`` where each row is
    ``{engine, brand, polarity, positive_aspects, negative_aspects,
    answer_excerpt}``. ``call_budget`` caps the number of LLM calls (counts
    against ``max_total_calls``, Spec Y.9.4); when exhausted, remaining answers
    are skipped.
    """
    rows: list[dict] = []
    calls = 0
    for ans in answers or []:
        text = ans.get("answer_text", "")
        engine = ans.get("engine", "")
        for brand, patterns in brand_targets.items():
            if not answer_mentions_brand(text, patterns):
                continue
            if call_budget is not None and calls >= call_budget:
                logger.warning(
                    "answer_sentiment: call budget %d reached — remaining "
                    "answers skipped.", call_budget)
                return rows, calls
            result = classify_answer(text, brand, model, llm_runner=llm_runner)
            calls += 1
            rows.append({
                "engine": engine,
                "brand": brand,
                "polarity": result["polarity"],
                "positive_aspects": result["positive_aspects"],
                "negative_aspects": result["negative_aspects"],
                "answer_excerpt": (text or "")[:400],
            })
    return rows, calls


def percent_positive(rows: list[dict], brand: str) -> float | None:
    """Python-computed % positive for one brand (Spec Y.9.2).

    ``None`` when the brand has no classified answers (not measured, not 0).
    """
    brand_rows = [r for r in rows if _norm(r["brand"]) == _norm(brand)]
    if not brand_rows:
        return None
    positive = sum(1 for r in brand_rows if r["polarity"] == "positive")
    return round(100.0 * positive / len(brand_rows), 2)


def aspect_chips(rows: list[dict], brand: str) -> dict:
    """Collect the verbatim positive/negative aspect phrases for one brand."""
    pos: list[str] = []
    neg: list[str] = []
    seen_pos: set[str] = set()
    seen_neg: set[str] = set()
    for r in rows:
        if _norm(r["brand"]) != _norm(brand):
            continue
        for phrase in r["positive_aspects"]:
            if _norm(phrase) not in seen_pos:
                seen_pos.add(_norm(phrase))
                pos.append(phrase)
        for phrase in r["negative_aspects"]:
            if _norm(phrase) not in seen_neg:
                seen_neg.add(_norm(phrase))
                neg.append(phrase)
    return {"positive": pos, "negative": neg}


def sentiment_axis(rows: list[dict], client_brand: str) -> float | None:
    """Client % positive as the 0–100 Sentiment axis, or ``None`` when the
    client has no classified answers (Y.6 then excludes the axis)."""
    return percent_positive(rows, client_brand)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def init_sentiment_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {SENTIMENT_TABLE} (
            run_ts                 TEXT,
            engine                 TEXT,
            brand                  TEXT,
            polarity               TEXT,
            positive_aspects_json  TEXT,
            negative_aspects_json  TEXT,
            answer_excerpt         TEXT
        )''')
        conn.commit()


def save_sentiment(db_path: str, run_ts: str, rows: list[dict]) -> None:
    init_sentiment_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {SENTIMENT_TABLE} WHERE run_ts = ?",
                     (run_ts,))   # idempotent per run_ts (all engines saved together) — P8
        conn.executemany(
            f"""INSERT INTO {SENTIMENT_TABLE}
                (run_ts, engine, brand, polarity, positive_aspects_json,
                 negative_aspects_json, answer_excerpt)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, r["engine"], r["brand"], r["polarity"],
                 json.dumps(r["positive_aspects"]),
                 json.dumps(r["negative_aspects"]),
                 (r.get("answer_excerpt") or "")[:400])
                for r in rows
            ],
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

_CAVEAT = (
    "*Sentiment is an LLM estimate of how the answer portrays each brand, not a "
    "measured fact; read it as a trend across runs, not a single-run verdict.*"
)


def render_sentiment_section(rows: list[dict] | None, enabled: bool,
                             client_brand: str,
                             top_competitor: str | None,
                             run_count: int = 0) -> list[str]:
    """Render the sentiment section.

    Disabled → a single "not measured" line (principle 3). Enabled → client and
    top-competitor % positive with verbatim keyword chips, the run count, and
    the accuracy caveat. Spec: Y.9.1 / Y.9.4 report.
    """
    out: list[str] = []
    out.append("## Sentiment")
    if not enabled:
        out.append(
            "*Sentiment not measured.* Per-brand sentiment is OFF by default "
            "(`sentiment.enabled: false`); enable it in `config.yml` to have the "
            "tool classify how AI answers portray the client and top competitor."
        )
        out.append("")
        return out

    rows = rows or []
    for label, brand in (("Client", client_brand),
                         ("Top competitor", top_competitor)):
        if not brand:
            continue
        pct = percent_positive(rows, brand)
        chips = aspect_chips(rows, brand)
        brand_rows = [r for r in rows if _norm(r["brand"]) == _norm(brand)]
        if pct is None:
            out.append(
                f"- **{label} ({brand}):** not measured — no answer this run "
                f"portrayed this brand."
            )
            continue
        pos = ", ".join(chips["positive"]) or "—"
        neg = ", ".join(chips["negative"]) or "—"
        out.append(
            f"- **{label} ({brand}):** {pct:.0f}% positive across "
            f"{len(brand_rows)} answer(s). Positive: {pos}. Negative: {neg}."
        )
    out.append("")
    out.append(_CAVEAT)
    out.append("")
    return out


def render_negative_sentiment_alert(rows: list[dict] | None, enabled: bool,
                                    client_brand: str) -> list[str]:
    """D5/AV.5.2 — a prominent own-brand alert when the CLIENT is portrayed
    negatively in one or more AI answers this run.

    Gated on ``enabled``: sentiment OFF → ``[]`` (no fabricated verdict, principle
    3). Also ``[]`` when there is no client brand or no measured negative client
    answer — so the alert adds nothing unless there is a real, measured negative.
    """
    if not enabled or not client_brand:
        return []
    rows = rows or []
    client_rows = [r for r in rows if _norm(r.get("brand")) == _norm(client_brand)]
    neg_rows = [r for r in client_rows if r.get("polarity") == "negative"]
    if not neg_rows:
        return []
    engines = sorted({r.get("engine") for r in neg_rows if r.get("engine")})
    # Chips scoped to the negative-polarity rows only, so "recurring negatives"
    # matches the "N of M" count (P3 — no phrases from positive/neutral answers).
    neg_chips = aspect_chips(neg_rows, client_brand)["negative"]
    out: list[str] = []
    out.append(
        f"> ⚠️ **Negative sentiment alert:** {client_brand} was portrayed "
        f"negatively in {len(neg_rows)} of {len(client_rows)} answer(s) this run"
        + (f" ({', '.join(engines)})" if engines else "") + "."
    )
    if neg_chips:
        out.append(">")
        out.append(f"> Recurring negatives: {', '.join(neg_chips)}.")
    out.append("")
    return out
