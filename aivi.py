#!/usr/bin/env python3
"""aivi.py — AI Visibility Index (AIVI): composite 0–100 score.

Spec: yoast_geo_upgrade_spec_v1.md#Y.6 (decision gate Y-D6).

The tool reports raw mention/citation rates but no single, trendable headline
number. Yoast's report leads with an AIVI 0–100 on a four-axis radar — Mentions,
Ranking, Citations, Sentiment — that makes "are we getting more visible?"
answerable at a glance and comparable across engines and months.

Axes (each already normalised 0–100 by its source module):

  * **Mentions**  — share of probed questions where the client was mentioned.
  * **Ranking**   — client's position on the Y.7 leaderboard, normalised
                    (rank 1 → 100, unranked → 0); ``brand_mentions.client_ranking_axis``.
  * **Citations** — client-owned citations as a share of total citations for the
                    client's questions (Y.8); ``citation_table.citations_axis``.
  * **Sentiment** — client % positive (Y.9). When sentiment is OFF this axis is
                    ``None`` (n/a) and is EXCLUDED from the weighted mean —
                    weights renormalise over the present axes; it is NEVER
                    counted as 0 (principle 3).

Design principle 1: PYTHON computes the score; the number is never LLM-derived.
Weights come from ``config.yml`` ``aivi.weights`` (default equal 25% each,
per Y-D6); malformed/missing weights fall back to equal with a warning.

Persistence: an ``ai_visibility_index`` SQLite table (``run_ts, engine, aivi,
mentions_axis, ranking_axis, citations_axis, sentiment_axis, weights_json``) so
the score is trendable (principle 5). All timestamps UTC.
"""
from __future__ import annotations

import json
import logging
import sqlite3

logger = logging.getLogger(__name__)

AIVI_TABLE = "ai_visibility_index"

AXES = ("mentions", "ranking", "citations", "sentiment")

#: Y-D6 recommended default: equal 25% each. Never hardcoded into the score —
#: this is only the fallback when config supplies no (valid) weights.
DEFAULT_WEIGHTS = {"mentions": 0.25, "ranking": 0.25,
                   "citations": 0.25, "sentiment": 0.25}


def resolve_weights(aivi_config: dict | None) -> dict:
    """Resolve the four axis weights from config, falling back to equal.

    A missing block, a non-numeric weight, or weights summing to zero all fall
    back to equal 25% each with a logged warning (Spec Y.6.3). Weights are
    normalised to sum to 1 across the four axes; unknown keys are ignored.
    """
    raw = (aivi_config or {}).get("weights")
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("aivi.weights is not a mapping — using equal weights.")
        return dict(DEFAULT_WEIGHTS)
    weights: dict[str, float] = {}
    for axis in AXES:
        value = raw.get(axis)
        try:
            weights[axis] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "aivi.weights.%s is missing or non-numeric — using equal weights.",
                axis)
            return dict(DEFAULT_WEIGHTS)
        if weights[axis] < 0:
            logger.warning("aivi.weights.%s is negative — using equal weights.", axis)
            return dict(DEFAULT_WEIGHTS)
    total = sum(weights.values())
    if total <= 0:
        logger.warning("aivi.weights sum to zero — using equal weights.")
        return dict(DEFAULT_WEIGHTS)
    return {axis: weights[axis] / total for axis in AXES}


def compute_aivi(axes: dict, weights: dict | None = None) -> dict:
    """Compute the composite AIVI 0–100 from the four axis values.

    ``axes`` maps axis name → value 0–100, or ``None`` for an axis that was not
    measured (e.g. sentiment OFF). ``None`` axes are EXCLUDED and the weights of
    the present axes are renormalised so the score stays 0–100 (Spec Y.6.2) —
    an absent axis is never silently counted as 0.

    Returns ``{aivi, axes, weights_used, excluded}`` where ``aivi`` is rounded
    to one decimal, ``axes`` echoes the (clamped) inputs including ``None``s,
    and ``excluded`` lists the n/a axes. Deterministic (Spec Y.6.1).
    """
    weights = weights or dict(DEFAULT_WEIGHTS)
    present: dict[str, float] = {}
    excluded: list[str] = []
    echoed: dict[str, float | None] = {}
    for axis in AXES:
        value = axes.get(axis)
        if value is None:
            echoed[axis] = None
            excluded.append(axis)
            continue
        clamped = max(0.0, min(100.0, float(value)))
        echoed[axis] = clamped
        present[axis] = clamped

    weight_sum = sum(weights.get(axis, 0.0) for axis in present)
    if not present or weight_sum <= 0:
        aivi = 0.0
    else:
        aivi = sum(
            present[axis] * (weights.get(axis, 0.0) / weight_sum)
            for axis in present
        )
    return {
        "aivi": round(aivi, 1),
        "axes": echoed,
        "weights_used": {a: weights.get(a, 0.0) for a in AXES},
        "excluded": excluded,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def init_aivi_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {AIVI_TABLE} (
            run_ts          TEXT,
            engine          TEXT,
            aivi            REAL,
            mentions_axis   REAL,
            ranking_axis    REAL,
            citations_axis  REAL,
            sentiment_axis  REAL,
            weights_json    TEXT
        )''')
        conn.commit()


def save_aivi(db_path: str, run_ts: str, engine: str, result: dict) -> None:
    init_aivi_table(db_path)
    axes = result.get("axes", {})
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {AIVI_TABLE} WHERE run_ts = ? AND engine = ?",
                     (run_ts, engine))   # idempotent per (run_ts, engine) — P8
        conn.execute(
            f"""INSERT INTO {AIVI_TABLE}
                (run_ts, engine, aivi, mentions_axis, ranking_axis,
                 citations_axis, sentiment_axis, weights_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_ts, engine, result.get("aivi"),
             axes.get("mentions"), axes.get("ranking"),
             axes.get("citations"), axes.get("sentiment"),
             json.dumps(result.get("weights_used", {}))),
        )
        conn.commit()


def get_aivi_trend(db_path: str, engine: str, limit: int = 5) -> list[dict]:
    """Per-run AIVI for one engine, oldest→newest (trendable, Spec Y.6.4)."""
    init_aivi_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, aivi, mentions_axis, ranking_axis,
                       citations_axis, sentiment_axis
                FROM {AIVI_TABLE}
                WHERE engine = ?
                ORDER BY run_ts DESC LIMIT ?""",
            (engine, limit),
        ).fetchall()
    trend = [
        {"run_ts": rt, "aivi": aivi, "mentions": m, "ranking": r,
         "citations": c, "sentiment": s}
        for rt, aivi, m, r, c, s in rows
    ]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

_CAVEAT = (
    "*AIVI is a single-run snapshot composed of per-engine axes; AI answers "
    "swing between runs, so read the trend, not one number. Optimisation does "
    "not transfer across engines — a high AIVI on one engine is not a high AIVI "
    "on all.*"
)


def _axis_cell(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def render_aivi_section(per_engine: dict, all_engine_avg: float | None,
                        trends: dict | None = None) -> list[str]:
    """Render the AIVI headline section.

    ``per_engine`` maps engine → the ``compute_aivi`` result. Shows the headline
    AIVI per engine, the four axis values (n/a where excluded), the prior-run
    delta (from ``trends``), and the snapshot caveat. A text/4-value
    radar-equivalent — no chart dependency (Spec Y.6.4).
    """
    out: list[str] = []
    out.append("## AI Visibility Index (AIVI)")
    out.append(
        "A single 0–100 headline per engine, computed by Python from four "
        "normalised axes (Mentions, Ranking, Citations, Sentiment). Weights are "
        "configurable (`aivi.weights`, default equal 25% each); an unmeasured "
        "axis (e.g. sentiment when disabled) is shown `n/a` and excluded from "
        "the weighted mean, never counted as zero."
    )
    out.append("")
    if all_engine_avg is not None:
        out.append(f"**All-engine average AIVI: {all_engine_avg:.1f}/100**")
        out.append("")
    out.append("| Engine | AIVI | Δ prior | Mentions | Ranking | Citations | Sentiment |")
    out.append("|--------|------|---------|----------|---------|-----------|-----------|")
    trends = trends or {}
    for engine, result in per_engine.items():
        axes = result.get("axes", {})
        delta = "—"
        trend = trends.get(engine) or []
        if len(trend) >= 2 and trend[-1].get("aivi") is not None \
                and trend[-2].get("aivi") is not None:
            diff = trend[-1]["aivi"] - trend[-2]["aivi"]
            delta = f"{diff:+.1f}"
        out.append(
            f"| {engine} | {result.get('aivi', 0):.1f} | {delta} "
            f"| {_axis_cell(axes.get('mentions'))} "
            f"| {_axis_cell(axes.get('ranking'))} "
            f"| {_axis_cell(axes.get('citations'))} "
            f"| {_axis_cell(axes.get('sentiment'))} |"
        )
    out.append("")
    out.append(_CAVEAT)
    out.append("")
    return out


def all_engine_average(per_engine: dict) -> float | None:
    """Simple mean of per-engine AIVI scores; ``None`` when there are none."""
    scores = [r.get("aivi") for r in per_engine.values() if r.get("aivi") is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)
