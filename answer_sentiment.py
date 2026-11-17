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

import ai_visibility_messages as av_messages
import brand_match

logger = logging.getLogger(__name__)

SENTIMENT_TABLE = "answer_sentiment"

VALID_POLARITIES = ("positive", "neutral", "negative")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def is_enabled(sentiment_config: dict | None) -> bool:
    """Sentiment is OFF unless explicitly enabled (Spec Y.9.1)."""
    return bool((sentiment_config or {}).get("enabled", False))


def answer_mentions_brand(answer_text: str, brand_patterns: list[str],
                          negative_terms: list[str] | None = None) -> bool:
    """True if any brand pattern names the brand in the answer.

    P5 / D3.12 (cold-review finding 2): this was a bare substring test with
    no negative terms, and it is the gate deciding which answers buy a paid
    sentiment classification. "living systems theory" therefore still bought
    a call and stored a sentiment row attributed to the practice, after the
    same bug had been fixed on the ``mentioned`` axis. It now calls the one
    shared matcher — word boundary, and the editorial *negative_terms*
    (``config.yml ai_visibility.negative_terms``) vetoed per match.
    """
    return brand_match.matches_patterns(answer_text, brand_patterns, negative_terms)


#: Whether a classification produced a verdict. D-M-25: a call that raised,
#: or whose response could not be parsed, used to return polarity "neutral" —
#: three rate-limited calls became three measured neutral verdicts and a
#: Sentiment axis of 0.0. A failed classification carries no polarity.
STATUS_CLASSIFIED = "classified"
STATUS_FAILED = "failed"
#: The call was never made because ``max_total_calls`` was already spent.
#: Cold-review finding 4: budget exhaustion returned early and recorded
#: nothing, so the report printed "not measured — no answer this run
#: portrayed this brand" over answers that did portray it. A budget that ran
#: out is a retryable state (P1), not an absence of mentions.
STATUS_SKIPPED_BUDGET = "skipped_budget"

#: The statuses that record an attempted classification (a verdict or a
#: failure), as against one that was never attempted at all.
ATTEMPTED_STATUSES = (STATUS_CLASSIFIED, STATUS_FAILED)


def classify_answer(answer_text: str, brand: str, model: str,
                    llm_runner=None) -> dict:
    """One gated LLM sentiment classification for a (answer, brand) pair.

    Returns ``{polarity, positive_aspects, negative_aspects}`` — the LLM output
    stored VERBATIM (Y-D7). ``llm_runner`` defaults to
    ``brief_llm.run_llm_report`` and is injectable for tests (all calls mocked).
    A malformed or failed response returns ``polarity: None`` with
    ``status: "failed"`` and the reason — never a neutral verdict, which is a
    measurement (D-M-25, D3.14). Never raises.
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
        return _failed_classification(str(exc))
    return _parse_classification(raw)


def _failed_classification(reason: str) -> dict:
    """No verdict, and why. Excluded from every percentage and from the axis."""
    return {"polarity": None, "positive_aspects": [], "negative_aspects": [],
            "status": STATUS_FAILED, "failure_reason": reason}


def _parse_classification(raw: str) -> dict:
    if not raw:
        return _failed_classification("the model returned nothing")
    text = str(raw).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("answer_sentiment: could not parse classification: %r", raw[:120])
        return _failed_classification("the response was not JSON")
    if not isinstance(parsed, dict):
        return _failed_classification("the response was not a JSON object")
    polarity = str(parsed.get("polarity") or "").strip().lower()
    if polarity not in VALID_POLARITIES:
        # A missing or unrecognised label is an unread answer, not a neutral
        # one. "neutral" is only ever stored when the model said neutral.
        return _failed_classification(
            f"polarity {parsed.get('polarity')!r} is not one of "
            f"{sorted(VALID_POLARITIES)}")

    def _phrases(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()]

    return {
        "polarity": polarity,
        "positive_aspects": _phrases(parsed.get("positive_aspects")),
        "negative_aspects": _phrases(parsed.get("negative_aspects")),
        "status": STATUS_CLASSIFIED,
        "failure_reason": None,
    }


def collect_sentiment(answers: list[dict], brand_targets: dict[str, list[str]],
                      model: str, llm_runner=None,
                      call_budget: int | None = None,
                      negative_terms: list[str] | None = None
                      ) -> tuple[list[dict], int]:
    """Classify each answer that mentions a target brand.

    ``answers`` is a list of ``{engine, answer_text}`` dicts. ``brand_targets``
    maps a brand display name → its match patterns (e.g. the client and the top
    competitor). *negative_terms* is the editorial veto list (``config.yml
    ai_visibility.negative_terms``), applied through the one shared matcher so
    a phrase that is not a mention does not buy a paid call (P5).
    Returns ``(rows, calls_made)`` where each row is
    ``{engine, brand, polarity, positive_aspects, negative_aspects,
    answer_excerpt, status, failure_reason}``. ``call_budget`` caps the number
    of LLM calls (counts against ``max_total_calls``, Spec Y.9.4); when
    exhausted, each remaining (answer, brand) pair is still recorded, with
    ``status: "skipped_budget"`` and ``polarity: None``, so the report says
    the budget ran out rather than that nothing portrayed the brand.

    A row whose ``status`` is ``failed`` carries ``polarity: None`` and is
    excluded from ``percent_positive`` and from the Sentiment axis (D3.14) —
    it says a call was attempted, not what the answer said.
    """
    rows: list[dict] = []
    calls = 0
    skipped = 0
    for ans in answers or []:
        text = ans.get("answer_text", "")
        engine = ans.get("engine", "")
        for brand, patterns in brand_targets.items():
            if not answer_mentions_brand(text, patterns, negative_terms):
                continue
            if call_budget is not None and calls >= call_budget:
                # P1/P2: record the skip so the report can say the budget ran
                # out instead of claiming no answer portrayed the brand.
                skipped += 1
                rows.append({
                    "engine": engine,
                    "brand": brand,
                    "polarity": None,
                    "positive_aspects": [],
                    "negative_aspects": [],
                    "answer_excerpt": (text or "")[:400],
                    "status": STATUS_SKIPPED_BUDGET,
                    "failure_reason": (
                        f"sentiment call budget of {call_budget} was already "
                        f"spent — this answer was never classified"),
                })
                continue
            result = classify_answer(text, brand, model, llm_runner=llm_runner)
            calls += 1
            rows.append({
                "engine": engine,
                "brand": brand,
                "polarity": result["polarity"],
                "positive_aspects": result["positive_aspects"],
                "negative_aspects": result["negative_aspects"],
                "answer_excerpt": (text or "")[:400],
                "status": result.get("status", STATUS_CLASSIFIED),
                "failure_reason": result.get("failure_reason"),
            })
    if skipped:
        logger.warning(
            "answer_sentiment: call budget %s reached — %d (answer, brand) "
            "pair(s) recorded as %s, not as unmentioned.",
            call_budget, skipped, STATUS_SKIPPED_BUDGET)
    return rows, calls


def classified_rows(rows: list[dict] | None, brand: str | None = None) -> list[dict]:
    """The rows that carry a real verdict (D3.14).

    A row with ``status: "failed"`` records an attempt, never an opinion, so
    every percentage and the Sentiment axis are computed over these only.
    Rows written before D3b carry no status and were only ever stored on a
    parsed response, so an absent status reads as classified.
    """
    out = [r for r in (rows or [])
           if (r.get("status") or STATUS_CLASSIFIED) == STATUS_CLASSIFIED]
    if brand is not None:
        out = [r for r in out if _norm(r["brand"]) == _norm(brand)]
    return out


def percent_positive(rows: list[dict], brand: str) -> float | None:
    """Python-computed % positive for one brand (Spec Y.9.2).

    ``None`` when the brand has no *classified* answers (not measured, not 0)
    — a brand whose every classification failed is unmeasured, and used to
    read 0% positive (D-M-25).
    """
    brand_rows = classified_rows(rows, brand)
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
    for r in classified_rows(rows, brand):
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
            answer_excerpt         TEXT,
            status                 TEXT,
            failure_reason         TEXT
        )''')
        # D3.14: pre-D3b databases predate the two columns. Same idempotent
        # ALTER TABLE convention as storage.py / the probe table; an old row
        # carries no status and reads as classified, which is what it was.
        for column, ddl_type in (("status", "TEXT"), ("failure_reason", "TEXT")):
            try:
                conn.execute(
                    f"ALTER TABLE {SENTIMENT_TABLE} ADD COLUMN {column} {ddl_type}")
            except sqlite3.OperationalError:
                pass  # already present
        conn.commit()


def save_sentiment(db_path: str, run_ts: str, rows: list[dict]) -> None:
    init_sentiment_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {SENTIMENT_TABLE} WHERE run_ts = ?",
                     (run_ts,))   # idempotent per run_ts (all engines saved together) — P8
        conn.executemany(
            f"""INSERT INTO {SENTIMENT_TABLE}
                (run_ts, engine, brand, polarity, positive_aspects_json,
                 negative_aspects_json, answer_excerpt, status, failure_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, r["engine"], r["brand"], r["polarity"],
                 json.dumps(r["positive_aspects"]),
                 json.dumps(r["negative_aspects"]),
                 (r.get("answer_excerpt") or "")[:400],
                 r.get("status") or STATUS_CLASSIFIED,
                 r.get("failure_reason"))
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
                             run_count: int = 0,
                             tied_top_competitors: list[str] | None = None
                             ) -> list[str]:
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
        for_brand = [r for r in rows if _norm(r["brand"]) == _norm(brand)]
        # Three populations, three facts: a row that was classified, one whose
        # call was attempted and failed, and one that was never asked because
        # the budget was spent (cold-review finding 4).
        attempted = [r for r in for_brand
                     if (r.get("status") or STATUS_CLASSIFIED) in ATTEMPTED_STATUSES]
        skipped = [r for r in for_brand
                   if r.get("status") == STATUS_SKIPPED_BUDGET]
        brand_rows = classified_rows(rows, brand)
        failed = len(attempted) - len(brand_rows)
        # D3.14 (P2): the coverage travels with the figure — a percentage over
        # 2 of 5 attempted classifications is not a percentage over 5.
        coverage = (f"{len(brand_rows)} classified of {len(attempted)} attempted"
                    if failed else f"{len(brand_rows)} answer(s)")
        if skipped:
            coverage += av_messages.line(
                "sentiment_skipped_note",
                "; {skipped} further answer(s) were never classified "
                "(call budget spent)", skipped=len(skipped))
        if pct is None:
            if not attempted and skipped:
                out.append(f"- **{label} ({brand}):** " + av_messages.line(
                    "sentiment_budget_exhausted",
                    "not measured — the sentiment call budget ran out before "
                    "any of the {skipped} answer(s) naming this brand could be "
                    "classified. Re-run with a larger `max_total_calls`.",
                    skipped=len(skipped)))
            elif failed:
                out.append(f"- **{label} ({brand}):** " + av_messages.line(
                    "sentiment_all_failed",
                    "not measured — all {attempted} classification(s) failed, "
                    "so this brand has no sentiment this run. Not a neutral "
                    "portrayal: re-run.", attempted=len(attempted)))
            else:
                out.append(f"- **{label} ({brand}):** " + av_messages.line(
                    "sentiment_not_portrayed",
                    "not measured — no answer this run portrayed this brand."))
            continue
        pos = ", ".join(chips["positive"]) or "—"
        neg = ", ".join(chips["negative"]) or "—"
        out.append(
            f"- **{label} ({brand}):** {pct:.0f}% positive across "
            f"{coverage}. Positive: {pos}. Negative: {neg}."
        )
    tied = [b for b in (tied_top_competitors or []) if str(b).strip()]
    if len(tied) > 1:
        # Cold-review finding 8: the benchmark is one of several brands on the
        # same mention count, not the leader. Say so rather than letting the
        # alphabet imply a winner.
        out.append(
            f"- *Top competitor is a tie: {', '.join(tied)} are level on "
            f"mentions. {top_competitor} was benchmarked; the others were not "
            f"classified.*")
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
    # D3.14: only a classified row carries an opinion to alert on.
    client_rows = classified_rows(rows, client_brand)
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
