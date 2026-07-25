#!/usr/bin/env python3
"""gsc_demand.py — Branded vs Non-Branded Demand (D2 / AV.2).

Purpose: Classify the client's Search Console queries as branded (name-seeking)
         vs non-branded and trend the branded click share — the demand signal
         that predicts survival when generic clicks fall to AI answers.
Spec:    discover-spec.md#D2 (AV.2)
Plan:    d2_d5_implementation_plan.md (AV.2)
Tests:   tests/test_gsc_demand.py

Isolation: imported ONLY by ``run_gsc_analysis`` (the standalone GSC path) — never
by a pipeline module (``tests/test_gsc.py`` enforces the GSC modules stay out of
the pipeline import graph). No LLM, no new fetch — it classifies the rows
``run_analysis`` already pulled.

Grain (decision D-D2a): the current GSC client fetches per-query only (no ``date``
dimension), so there is no true per-day series. The demand series is therefore
keyed by **run** (``run_ts``, parsed from the market_analysis filename) and trends
across successive runs — the repo's raw-sqlite second-run model. Denominator
(decision D-D2b): the branded share is computed over the run's **tracked** queries
(what GSC was asked for), labelled as such — not the full property.

Branded classification reuses the ``client_name_patterns`` substring match (the
``detect_visibility`` form — single-word brands included), plus an optional
negative-term override for generic words that contain the brand. Bands are
industry REFERENCE points from config, labelled as reference — not targets.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

DEMAND_RUN_TABLE = "gsc_demand_run"
DEMAND_SCORE_TABLE = "gsc_demand_score"

#: D2 default benchmark bands (branded click-share thresholds). Industry REFERENCE
#: points, config-overridable, labelled in the report as reference — not targets.
DEFAULT_BANDS = {"below_avg": 0.024, "top": 0.10}
_RUN_TS_RE = re.compile(r"(\d{8}_\d{4})")


def run_ts_from_filename(path) -> str | None:
    """Extract the ``YYYYMMDD_HHMM`` run stamp from a market_analysis_* filename;
    ``None`` when unparseable (caller renders without persisting — no fabricated
    stamp)."""
    if not path:
        return None
    match = _RUN_TS_RE.search(os.path.basename(str(path)))   # basename only, so an
    return match.group(1) if match else None                 # ancestor dir stamp can't mis-key


def _to_int(value) -> int:
    """Coerce to int, tolerating None/empty/non-numeric (a malformed cached row
    must not raise mid-rollup — P2)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def is_branded(query, patterns, negatives=None) -> bool:
    """Name-seeking? Any ``client_name_pattern`` matches on a **word boundary**
    (case-insensitive) and no negative-override term appears (substring, broad).

    Word-boundary (not bare substring) so a brand token can't match inside a larger
    word (``Bowen`` in ``Bowenville``). NOTE: it cannot disambiguate a brand that is
    itself a generic phrase — ``"Living Systems"`` still matches ``"living systems
    theory"`` — which inflates the branded share; use ``gsc_demand.negative_terms``
    to exclude known generic collocations, and audit per-query ``is_branded`` in the
    sidecar. Mirrors ``detect_visibility`` (single-word brands included), NOT the
    ≥2-word ``_client_match_patterns``."""
    q = str(query or "").lower()
    if not q:
        return False
    if any(str(neg).lower() in q for neg in (negatives or []) if str(neg).strip()):
        return False
    for pat in (patterns or []):
        pat = str(pat).strip().lower()
        if pat and re.search(r"\b" + re.escape(pat) + r"\b", q):
            return True
    return False


def classify_rows(rows, patterns, negatives=None):
    """Annotate each GSC row (that has data) with ``is_branded``. Recomputed every
    run so a ``client_name_patterns`` edit reclassifies (acceptance D2.1)."""
    for row in rows:
        row["is_branded"] = bool(row.get("found")) and is_branded(
            row.get("query"), patterns, negatives)
    return rows


def resolve_bands(cfg) -> dict:
    raw = ((cfg or {}).get("gsc_demand") or {}).get("bands") or {}
    try:
        below = float(raw.get("below_avg", DEFAULT_BANDS["below_avg"]))
        top = float(raw.get("top", DEFAULT_BANDS["top"]))
    except (TypeError, ValueError):
        logger.warning("gsc_demand.bands non-numeric — using default bands.")
        return dict(DEFAULT_BANDS)
    if not 0 <= below <= top <= 1:
        logger.warning("gsc_demand.bands out of order/range — using default bands.")
        return dict(DEFAULT_BANDS)
    return {"below_avg": below, "top": top}


def _band(share: float, bands: dict) -> str:
    if share < bands["below_avg"]:
        return "below_avg"
    if share < bands["top"]:
        return "avg"
    return "top"


def compute_demand(rows, cfg):
    """Branded-vs-non-branded rollup over the run's tracked queries.

    Returns ``(rows, score)`` — ``rows`` are annotated with ``is_branded``; ``score``
    carries branded/non-branded clicks & impressions, ``branded_click_share`` (no
    divide-by-zero), ``benchmark_band``, the matched patterns, counts, and the bands
    used (``weights_json``)."""
    patterns = ((cfg or {}).get("analysis_report") or {}).get("client_name_patterns", []) or []
    negatives = ((cfg or {}).get("gsc_demand") or {}).get("negative_terms", []) or []
    bands = resolve_bands(cfg)
    classify_rows(rows, patterns, negatives)

    branded = [r for r in rows if r.get("is_branded")]
    nonbranded = [r for r in rows if r.get("found") and not r.get("is_branded")]

    def _sum(items, key):
        return sum(_to_int(r.get(key)) for r in items)

    b_clicks, nb_clicks = _sum(branded, "clicks"), _sum(nonbranded, "clicks")
    total_clicks = b_clicks + nb_clicks
    tracked = sum(1 for r in rows if r.get("found"))
    # No clicks (fresh/empty property, or a transient fetch miss) → the branded
    # share is undefined; it must NOT be reported or persisted as a real
    # "0% / below average" verdict (P2 — failures hiding as findings).
    data_available = tracked > 0 and total_clicks > 0
    share = b_clicks / total_clicks if total_clicks else 0.0
    matched = sorted({
        str(p) for p in patterns
        if any(str(p).lower() in str(r.get("query", "")).lower() for r in branded)
    })
    score = {
        "branded_clicks": b_clicks, "nonbranded_clicks": nb_clicks,
        "branded_impressions": _sum(branded, "impressions"),
        "nonbranded_impressions": _sum(nonbranded, "impressions"),
        "branded_click_share": round(share, 4),
        "benchmark_band": _band(share, bands) if data_available else None,
        "data_available": data_available,
        "matched_patterns": matched,
        "branded_query_count": len(branded),
        "tracked_query_count": tracked,
        "weights_json": json.dumps({"bands": bands}, sort_keys=True),
    }
    return rows, score


# ---------------------------------------------------------------------------
# Persistence (idempotent per (property, run_ts))
# ---------------------------------------------------------------------------

def init_demand_tables(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {DEMAND_RUN_TABLE} (
            property TEXT, run_ts TEXT, query TEXT, clicks INTEGER,
            impressions INTEGER, position REAL, is_branded INTEGER,
            source TEXT, fetched_at TEXT
        )''')
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {DEMAND_SCORE_TABLE} (
            property TEXT, run_ts TEXT, branded_clicks INTEGER,
            nonbranded_clicks INTEGER, branded_impressions INTEGER,
            nonbranded_impressions INTEGER, branded_click_share REAL,
            benchmark_band TEXT, weights_json TEXT
        )''')
        conn.commit()


def save_demand(db_path, property_, run_ts, rows, score, fetched_at=None) -> None:
    """Idempotent per ``(property, run_ts)`` (DELETE then insert) so a re-run
    re-classifies in place — a ``client_name_patterns`` edit must reclassify, and
    the 7-day GSC cache must never gate classification (acceptance D2.1, P8)."""
    init_demand_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {DEMAND_RUN_TABLE} WHERE property=? AND run_ts=?",
                     (property_, run_ts))
        conn.execute(f"DELETE FROM {DEMAND_SCORE_TABLE} WHERE property=? AND run_ts=?",
                     (property_, run_ts))
        conn.executemany(
            f"""INSERT INTO {DEMAND_RUN_TABLE}
                (property, run_ts, query, clicks, impressions, position,
                 is_branded, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(property_, run_ts, r.get("query"), _to_int(r.get("clicks")),
              _to_int(r.get("impressions")), float(r.get("position") or 0.0),
              int(bool(r.get("is_branded"))), "gsc", fetched_at)
             for r in rows if r.get("found")],
        )
        # Only persist a score point when there was measurable data — a 0/0 share
        # must never enter the trend as a real below-average measurement (P2).
        if score.get("data_available"):
            conn.execute(
                f"""INSERT INTO {DEMAND_SCORE_TABLE}
                    (property, run_ts, branded_clicks, nonbranded_clicks,
                     branded_impressions, nonbranded_impressions, branded_click_share,
                     benchmark_band, weights_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (property_, run_ts, score["branded_clicks"], score["nonbranded_clicks"],
                 score["branded_impressions"], score["nonbranded_impressions"],
                 score["branded_click_share"], score["benchmark_band"],
                 score["weights_json"]),
            )
        conn.commit()


def get_demand_trend(db_path, property_, limit=5) -> list[dict]:
    """Per-run branded-share series (oldest→newest) for one property."""
    init_demand_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, branded_click_share, benchmark_band
                FROM {DEMAND_SCORE_TABLE} WHERE property=?
                ORDER BY run_ts DESC LIMIT ?""",
            (property_, limit),
        ).fetchall()
    trend = [{"run_ts": rt, "branded_click_share": s, "benchmark_band": b}
             for rt, s, b in rows]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Report section (appended to the gsc_analysis_*.md by run_gsc_analysis)
# ---------------------------------------------------------------------------

_BAND_LABEL = {"below_avg": "below average", "avg": "average", "top": "top"}


def render_demand_section(score, trend=None) -> list[str]:
    out: list[str] = []
    out.append("## Branded vs Non-Branded Demand")
    out.append(
        "How much of the client's search demand is **name-seeking** (branded) vs "
        "generic (non-branded), across the run's tracked queries. Branded demand "
        "predicts survival when generic clicks fall to AI answers."
    )
    out.append("")
    if not score.get("data_available"):
        out.append(
            f"*Insufficient GSC data this run — {score['tracked_query_count']} tracked "
            f"query(ies) with data, {score['branded_clicks'] + score['nonbranded_clicks']} "
            "clicks. Branded share is only computed once there are clicks to split; "
            "connect GSC or widen the lookback window.*"
        )
        out.append("")
        return out
    share = score["branded_click_share"]
    total = score["branded_clicks"] + score["nonbranded_clicks"]
    out.append(
        f"- **Branded click share:** {share:.1%} ({score['branded_clicks']} of "
        f"{total} clicks across tracked queries) — "
        f"**{_BAND_LABEL.get(score['benchmark_band'], score['benchmark_band'])}** "
        "vs the industry reference band."
    )
    out.append(
        f"- **Branded queries:** {score['branded_query_count']} of "
        f"{score['tracked_query_count']} tracked queries with GSC data."
    )
    if score["matched_patterns"]:
        out.append(f"- **Matched brand patterns:** {', '.join(score['matched_patterns'])}.")
    if trend and len(trend) >= 2:
        delta = trend[-1]["branded_click_share"] - trend[-2]["branded_click_share"]
        out.append(f"- *Δ prior run: branded share {delta:+.1%}.*")
    out.append("")
    out.append(
        "> Bands (`config.yml gsc_demand.bands`) are **industry reference points** "
        "(below-avg < 2.4%, top ≥ 10%), not targets for this client. The share is over "
        "the run's tracked queries, not the full property; GSC's 2–3 day lag means the "
        "latest run is provisional."
    )
    out.append("")
    return out
