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
import db_connect

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


#: What the default bands are, stated rather than implied. ``gsc_demand.bands``
#: carries no citation in this repo and none was found: the figures are the
#: owner's working assumption, and the report says so unless config names a
#: source (D5.4 / finding D-M-16).
DEFAULT_BAND_SOURCE = ("the owner's working assumption — no published source is "
                       "recorded for these figures")


def band_source(cfg) -> str:
    """The provenance sentence printed with the bands.

    ``gsc_demand.bands.source`` when set; otherwise the statement that the
    numbers are an assumption. A number with no stated origin reads in the
    report as an industry fact (finding D-M-16).
    """
    raw = ((cfg or {}).get("gsc_demand") or {}).get("bands") or {}
    source = str(raw.get("source") or "").strip() if isinstance(raw, dict) else ""
    return source or DEFAULT_BAND_SOURCE


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


def _property_split(property_rows, patterns, negatives):
    """Branded/non-branded clicks over every query row for the property.

    Returns ``(branded_clicks, nonbranded_clicks, query_count)`` or ``None``
    when there is no property-wide view to split (D5.4).
    """
    if not isinstance(property_rows, dict) or not property_rows:
        return None
    b_clicks = nb_clicks = clicking = 0
    for query, values in property_rows.items():
        clicks = _to_int((values or {}).get("clicks"))
        if clicks:
            clicking += 1
        if is_branded(query, patterns, negatives):
            b_clicks += clicks
        else:
            nb_clicks += clicks
    # The count is of the queries that contributed clicks, because that is
    # what the share is over — the pull also returns zero-click rows (cold
    # review 6).
    return b_clicks, nb_clicks, clicking


def compute_demand(rows, cfg, fetch_complete: bool = True, property_rows=None,
                   filters=None):
    """Branded-vs-non-branded rollup, over the property and over the tracked set.

    Returns ``(rows, score)`` — ``rows`` are annotated with ``is_branded``; ``score``
    carries branded/non-branded clicks & impressions, ``branded_click_share`` (the
    tracked-query share, no divide-by-zero), ``benchmark_band``, the matched
    patterns, counts, and the bands used (``weights_json``).

    *property_rows* is :attr:`gsc_client.GscStats.property_rows` — every query
    row for the property when the fetch pulled them and covered the whole
    property. Branded share is a claim about the client's demand, so the
    headline share and the band are computed over the property when it is
    available, with the tracked-query share reported beside it and both
    labelled. ``band_basis`` says which one the band was taken from. Over the
    tracked set alone the share is a share of the keywords this run happened
    to look at, which rises and falls with the keyword file (finding D-M-16).

    *fetch_complete* is False when the GSC fetch did not resolve every query
    it asked for — the case the no-clicks guard does not catch: the share is
    computable but over a truncated denominator, and would enter the trend
    beside complete runs as if comparable (D2b.7).
    """
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
    data_available = tracked > 0 and total_clicks > 0 and bool(fetch_complete)
    share = b_clicks / total_clicks if total_clicks else 0.0

    prop = _property_split(property_rows, patterns, negatives)
    p_b_clicks, p_nb_clicks, p_queries = prop if prop else (0, 0, 0)
    p_total = p_b_clicks + p_nb_clicks
    # The property figure stands on its own rows. It must NOT be gated on the
    # tracked set: a keyword file that happens to match no clicking query is
    # exactly the case the property share was added for, and gating it on
    # `data_available` discarded a complete real measurement and printed
    # "insufficient GSC data" (cold review 4).
    property_available = bool(prop) and p_total > 0 and bool(fetch_complete)
    p_share = p_b_clicks / p_total if p_total else 0.0
    # The band describes the client's demand, so it reads the property share
    # whenever there is one; the tracked share stays beside it, labelled.
    headline = p_share if property_available else share
    band_basis = "property" if property_available else "tracked"
    # Something real to report: either figure will do.
    reportable = property_available or data_available
    matched = sorted({
        str(p) for p in patterns
        if any(str(p).lower() in str(r.get("query", "")).lower() for r in branded)
    })
    score = {
        "branded_clicks": b_clicks, "nonbranded_clicks": nb_clicks,
        "branded_impressions": _sum(branded, "impressions"),
        "nonbranded_impressions": _sum(nonbranded, "impressions"),
        "branded_click_share": round(share, 4),
        "property_branded_clicks": p_b_clicks,
        "property_nonbranded_clicks": p_nb_clicks,
        "property_branded_click_share": round(p_share, 4) if property_available else None,
        "property_query_count": p_queries,
        "property_available": property_available,
        "headline_branded_click_share": round(headline, 4),
        "band_basis": band_basis,
        "band_source": band_source(cfg),
        # Which searchers the figures are about: since D5.7 the pull is
        # restricted to one country and one device, so "the whole property"
        # means the whole property for those searchers (cold review 6).
        "population": (filters or {}).get("text") or "",
        "benchmark_band": _band(headline, bands) if reportable else None,
        "reportable": reportable,
        "data_available": data_available,
        # Why it is unavailable, when it is — so the report can say "the fetch
        # failed" rather than "the client has no demand" (D2b.7).
        "fetch_complete": bool(fetch_complete),
        "matched_patterns": matched,
        "branded_query_count": len(branded),
        "tracked_query_count": tracked,
        "weights_json": json.dumps({"bands": bands, "band_basis": band_basis},
                                   sort_keys=True),
    }
    return rows, score


# ---------------------------------------------------------------------------
# Persistence (idempotent per (property, run_ts))
# ---------------------------------------------------------------------------

def init_demand_tables(db_path: str) -> None:
    with db_connect.connection(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {DEMAND_RUN_TABLE} (
            property TEXT, run_ts TEXT, query TEXT, clicks INTEGER,
            impressions INTEGER, position REAL, is_branded INTEGER,
            source TEXT, fetched_at TEXT
        )''')
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {DEMAND_SCORE_TABLE} (
            property TEXT, run_ts TEXT, branded_clicks INTEGER,
            nonbranded_clicks INTEGER, branded_impressions INTEGER,
            nonbranded_impressions INTEGER, branded_click_share REAL,
            benchmark_band TEXT, weights_json TEXT,
            property_branded_click_share REAL, property_query_count INTEGER,
            band_basis TEXT
        )''')
        # Databases written before D5.4 have the first nine columns only. Add
        # the rest in place rather than leaving the reads to fail on an older
        # file (the trend is the whole point of the table).
        existing = {row[1] for row in conn.execute(
            f"PRAGMA table_info({DEMAND_SCORE_TABLE})")}
        for column, decl in (("property_branded_click_share", "REAL"),
                             ("property_query_count", "INTEGER"),
                             ("band_basis", "TEXT")):
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE {DEMAND_SCORE_TABLE} ADD COLUMN {column} {decl}")
        conn.commit()


def save_demand(db_path, property_, run_ts, rows, score, fetched_at=None) -> None:
    """Idempotent per ``(property, run_ts)`` (DELETE then insert) so a re-run
    re-classifies in place — a ``client_name_patterns`` edit must reclassify, and
    the 7-day GSC cache must never gate classification (acceptance D2.1, P8)."""
    init_demand_tables(db_path)
    with db_connect.connection(db_path) as conn:
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
        if score.get("reportable", score.get("data_available")):
            conn.execute(
                f"""INSERT INTO {DEMAND_SCORE_TABLE}
                    (property, run_ts, branded_clicks, nonbranded_clicks,
                     branded_impressions, nonbranded_impressions, branded_click_share,
                     benchmark_band, weights_json, property_branded_click_share,
                     property_query_count, band_basis)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (property_, run_ts, score["branded_clicks"], score["nonbranded_clicks"],
                 score["branded_impressions"], score["nonbranded_impressions"],
                 score["branded_click_share"], score["benchmark_band"],
                 score["weights_json"],
                 score.get("property_branded_click_share"),
                 score.get("property_query_count"),
                 score.get("band_basis", "tracked")),
            )
        conn.commit()


def get_demand_trend(db_path, property_, limit=5) -> list[dict]:
    """Per-run branded-share series (oldest→newest) for one property.

    Each point carries its ``band_basis`` and its property share, because a
    property-wide share and a tracked-query share are two different
    measurements and a Δ between them means nothing (D5.4).
    """
    init_demand_tables(db_path)
    with db_connect.connection(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, branded_click_share, benchmark_band,
                       property_branded_click_share, band_basis
                FROM {DEMAND_SCORE_TABLE} WHERE property=?
                ORDER BY run_ts DESC LIMIT ?""",
            (property_, limit),
        ).fetchall()
    trend = [{"run_ts": rt, "branded_click_share": s, "benchmark_band": b,
              "property_branded_click_share": ps,
              # Rows written before D5.4 recorded only the tracked share.
              "band_basis": basis or "tracked"}
             for rt, s, b, ps, basis in rows]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Report section (appended to the gsc_analysis_*.md by run_gsc_analysis)
# ---------------------------------------------------------------------------

_BAND_LABEL = {"below_avg": "below average", "avg": "average", "top": "top"}


def _trend_messages() -> dict:
    """The `demand_trend` block of `gsc_messages.yml`, or `{}`.

    The words for every "there is no Δ, and here is why" case. Editorial, so
    they live in the messages file like every other GSC fetch-outcome word.
    """
    try:
        from gsc_client import load_messages
    except ImportError:                     # pragma: no cover
        return {}
    try:
        return (load_messages() or {}).get("demand_trend") or {}
    except Exception as exc:                # noqa: BLE001
        logger.warning("gsc_messages.yml demand_trend not loaded: %s", exc)
        return {}


def render_demand_section(score, trend=None, trend_error=None) -> list[str]:
    """The branded-demand section.

    `trend_error` is the reason there is no trend when the history could not
    be read or written, as opposed to there being no history yet. The two
    looked identical in the report until review chunk Y2: a persistence
    failure was caught, logged and the section rendered with no trend line at
    all, so a reader saw the same thing as a first run (P2/P6).
    """
    out: list[str] = []
    out.append("## Branded vs Non-Branded Demand")
    out.append(
        "How much of the client's search demand is **name-seeking** (branded) vs "
        "generic (non-branded). Branded demand predicts survival when generic "
        "clicks fall to AI answers. The share is measured over **every query the "
        "property received clicks on** where this run pulled them, with the "
        "share over the run's tracked queries shown beside it."
    )
    out.append("")
    if not score.get("reportable", score.get("data_available")):
        if not score.get("fetch_complete", True):
            out.append(
                "*No branded share this run — the GSC fetch did not reach every "
                "query, so any share would be computed over a truncated set and "
                "is not comparable with other runs. Nothing was recorded for the "
                "trend. Re-run to measure it.*"
            )
        else:
            out.append(
                f"*No branded share this run — {score['tracked_query_count']} tracked "
                f"query(ies) with data, {score['branded_clicks'] + score['nonbranded_clicks']} "
                "clicks. Branded share is only computed once there are clicks to split; "
                "connect GSC or widen the lookback window.*"
            )
        out.append("")
        return out
    share = score["branded_click_share"]
    total = score["branded_clicks"] + score["nonbranded_clicks"]
    band_word = _BAND_LABEL.get(score["benchmark_band"], score["benchmark_band"])
    population = score.get("population") or ""
    _for = f" for {population}" if population else ""
    if score.get("property_available"):
        p_total = score["property_branded_clicks"] + score["property_nonbranded_clicks"]
        out.append(
            f"- **Branded click share (every query the property got clicks on"
            f"{_for}):** "
            f"{score['property_branded_click_share']:.1%} "
            f"({score['property_branded_clicks']} of {p_total} clicks across "
            f"{score['property_query_count']} clicking queries) — "
            f"**{band_word}** vs the reference band. This is the figure the "
            "band was taken from."
        )
        out.append(
            "- Search Console withholds rare queries to protect searchers' "
            "privacy, and those are mostly long-tail and generic, so this "
            "share leans branded by an amount nobody can measure. It is the "
            "best figure available, not the property's true share."
        )
    if score.get("data_available"):
        out.append(
            f"- **Branded click share (this run's tracked queries only):** "
            f"{share:.1%} ({score['branded_clicks']} of {total} clicks)"
            + (". A different measurement: it moves with the keyword file, so "
               "it is not comparable with the property figure."
               if score.get("property_available") else "")
        )
    if not score.get("property_available"):
        out.append(
            "- **No property-wide figure this run** (the rows came from the "
            "cache, or the pull did not cover the whole property)"
            + (f", so the band above was taken from the tracked share, which "
               "moves with the keyword file." if score.get("data_available")
               else " and this run's tracked queries carried no clicks either.")
        )
    out.append(
        f"- **Branded queries:** {score['branded_query_count']} of "
        f"{score['tracked_query_count']} tracked queries with GSC data."
    )
    if score["matched_patterns"]:
        out.append(f"- **Matched brand patterns:** {', '.join(score['matched_patterns'])}.")
    if trend_error or not trend or len(trend) < 2:
        # Every reason there is no Δ is stated. Printing no Δ line at all was
        # indistinguishable from a first run, and three of the four reasons are
        # a configuration gap or a failed write (cold review of chunk Y2).
        messages = _trend_messages()
        reason = trend_error or messages.get("first_run") or "no history yet"
        line = messages.get("line")
        out.append(line.format(reason=str(reason).rstrip(". ")).strip()
                   if line else f"- *No run-over-run Δ: {reason}.*")
    elif trend and len(trend) >= 2:
        latest, prior = trend[-1], trend[-2]
        basis = latest.get("band_basis", "tracked")
        if prior.get("band_basis", "tracked") != basis:
            out.append(
                f"- *No Δ against the prior run: it measured the "
                f"{prior.get('band_basis', 'tracked')} share and this one the "
                f"{basis} share. The two are not the same measurement.*")
        else:
            key = ("property_branded_click_share" if basis == "property"
                   else "branded_click_share")
            if latest.get(key) is None or prior.get(key) is None:
                out.append("- *No Δ against the prior run: it recorded no "
                           f"{basis} share.*")
            else:
                delta = latest[key] - prior[key]
                out.append(f"- *Δ prior run ({basis} share): {delta:+.1%}.*")
    out.append("")
    out.append(
        "> Bands (`config.yml gsc_demand.bands`) are reference points, not targets "
        f"for this client. Where they come from: {score.get('band_source', '')}. "
        f"The band above was taken from the **{score.get('band_basis', 'tracked')}** "
        "share. GSC's 2–3 day lag means the latest run is provisional."
    )
    out.append("")
    return out
