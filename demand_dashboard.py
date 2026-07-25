#!/usr/bin/env python3
"""demand_dashboard.py — Demand vs Clicks snapshot (D3 / AV.3).

Purpose: One view that operationalizes "clicks != demand" — AI-Overview coverage
         soaking up clicks alongside the client's own Search Console clicks and
         the estimated traffic at risk.
Spec:    discover-spec.md#D3 (AV.3)
Plan:    d2_d5_implementation_plan.md (AV.3)
Tests:   tests/test_demand_dashboard.py

SCOPE (decision D-D3): the point-in-time SNAPSHOT only. The spec's divergence_flag
(trailing-window slopes of visibility-down vs demand-up) is DEFERRED — it needs a
per-keyword search_volume source (which exists nowhere in the repo) and a daily
GSC time-series (the client fetches per-query totals, no `date` dimension).
Building the flag on absent data would be a fabricated signal, so this ships the
honest snapshot and documents the deferral instead.

Assembled at report time from:
- D1's ``aio_exposure.compute_aio_exposure`` → ``aio_coverage_pct`` + per-keyword
  ``est_ctr_loss``.
- The client's GSC clicks/impressions from the ``gsc_cache`` table (via ``db_path``)
  WHEN present — read defensively (the table may not exist / GSC may be off),
  degrading to an honest "connect GSC" note. No ``search_volume`` exists, so no
  normalized visibility line is invented; ``est_traffic_at_risk`` is
  ``impressions × modeled AIO CTR interception`` and is labelled indicative.

This reads the ``gsc_cache`` TABLE read-only (not the ``gsc_client`` module), so it
adds no import coupling to the standalone GSC path.
"""
from __future__ import annotations

import logging
import sqlite3

import aio_exposure

logger = logging.getLogger(__name__)

GSC_CACHE_TABLE = "gsc_cache"

_DEFER_NOTE = (
    "*Snapshot only.* The demand-vs-clicks **trend** (visibility falling while brand "
    "demand holds) is deferred: it needs per-keyword search volume (not provided by the "
    "current SERP sources) and a daily GSC series (Search Console returns per-query "
    "totals). This shows the point-in-time position; the branded-demand trend lives in "
    "the GSC analysis report (D2)."
)


def _latest_gsc(db_path):
    """``({normalized_query: {clicks, impressions}}, gsc_ran)`` from the most recent
    ``gsc_cache`` row per query. ``gsc_ran`` is True when the table exists (GSC has
    been run) even if no query matched. Returns ``({}, False)`` — never raises (P2) —
    when there is no db, the table is absent, the db is locked, or it is corrupt."""
    if not db_path:
        return {}, False
    try:
        with sqlite3.connect(db_path) as conn:
            # SQLite single-min/max bare-column rule: with exactly ONE MAX()/MIN()
            # and GROUP BY, the bare clicks/impressions come from the row holding
            # that MAX(fetched_at) — i.e. the latest fetch per query. Adding a
            # second aggregate would break this; keep it a single MAX().
            rows = conn.execute(
                f"""SELECT query, clicks, impressions, MAX(fetched_at)
                    FROM {GSC_CACHE_TABLE} WHERE found = 1
                    GROUP BY query"""
            ).fetchall()
    except sqlite3.OperationalError:
        return {}, False   # table absent (GSC never run) or db locked — degrade silently
    except Exception as exc:   # corrupt / not-a-database → degrade, never drop the report
        logger.warning("gsc_cache read failed (%s) — showing AIO coverage only.", exc)
        return {}, False
    return ({
        str(q).strip().lower(): {"clicks": c or 0, "impressions": i or 0}
        for q, c, i, _ in rows
    }, True)


def compute_dashboard(keyword_profiles, config, db_path=None):
    """Assemble the snapshot read-model (no new storage). Joins D1 AIO exposure to
    GSC clicks by normalized keyword (``gsc_cache.query`` is lower-cased; the
    profile keys are raw, so both sides are lower/stripped before matching)."""
    aio_rows, rollup = aio_exposure.compute_aio_exposure(keyword_profiles, config)
    gsc, gsc_ran = _latest_gsc(db_path)

    total_clicks = total_impr = matched = 0
    est_at_risk = 0.0
    at_risk = []
    for row in aio_rows:
        stats = gsc.get(str(row["keyword"]).strip().lower())
        if not stats:
            continue
        matched += 1
        total_clicks += stats["clicks"]
        total_impr += stats["impressions"]
        intercepted = stats["impressions"] * float(row.get("est_ctr_loss") or 0.0)
        # est_traffic_at_risk is scoped to AIO keywords where the client is NOT cited
        # — matching the label + docs. A cited keyword already owns the citation, so
        # its (halved) loss must not inflate the "at risk" total.
        if row["aio_present"] and not row["client_cited"] and intercepted > 0:
            est_at_risk += intercepted
            at_risk.append({
                "keyword": row["keyword"], "clicks": stats["clicks"],
                "impressions": stats["impressions"],
                "est_intercepted": round(intercepted, 1),
            })
    at_risk.sort(key=lambda d: -d["est_intercepted"])
    return {
        "aio_coverage_pct": rollup["aio_coverage_pct"],
        "cited_share": rollup["cited_share"],
        # connected = at least one TRACKED keyword had GSC data (so there's an overlay
        # to show); gsc_ran = the table exists at all (GSC was run for some queries).
        "gsc_connected": matched > 0,
        "gsc_ran": gsc_ran,
        "matched_query_count": matched,
        "total_clicks": total_clicks,
        "total_impressions": total_impr,
        "est_traffic_at_risk": round(est_at_risk, 1),
        "keywords_at_risk": at_risk[:10],
    }


def render_dashboard_section(dash) -> list[str]:
    out: list[str] = []
    out.append("## 5f. Demand vs Clicks (snapshot)")
    out.append(
        "One view of *clicks ≠ demand*: how much the AI Overview is soaking up "
        "alongside the client's own Search Console clicks."
    )
    out.append("")
    out.append(
        f"- **AI Overview coverage:** {dash['aio_coverage_pct']:.1f}% of tracked "
        f"keywords show an AIO; the client is cited in {dash['cited_share']:.1f}% of those."
    )
    if not dash["gsc_connected"]:
        if dash.get("gsc_ran"):
            out.append(
                "- **Client clicks:** GSC ran, but none of the tracked queries returned "
                "click data in this window — widen the lookback or verify the property."
            )
        else:
            out.append(
                "- **Client clicks:** *not connected.* Run the GSC analysis "
                "(`run_gsc_analysis.py` with `gsc.enabled: true` + credentials) to overlay "
                "first-party clicks/impressions and the estimated traffic at risk."
            )
        out.append("")
        out.append(_DEFER_NOTE)
        out.append("")
        return out

    out.append(
        f"- **Client clicks (GSC):** {dash['total_clicks']} clicks / "
        f"{dash['total_impressions']} impressions across {dash['matched_query_count']} "
        "matched tracked queries."
    )
    out.append(
        f"- **Estimated traffic at risk to AI Overviews:** ~{dash['est_traffic_at_risk']:.0f} "
        "clicks/period (indicative — impressions × modeled AIO CTR interception, "
        "for AIO keywords where the client is not cited)."
    )
    if dash["keywords_at_risk"]:
        out.append("")
        out.append("| Keyword | Clicks | Impressions | Est. intercepted |")
        out.append("|---------|--------|-------------|------------------|")
        for d in dash["keywords_at_risk"]:
            out.append(
                f"| {d['keyword']} | {d['clicks']} | {d['impressions']} "
                f"| {d['est_intercepted']:.0f} |"
            )
    out.append("")
    out.append(_DEFER_NOTE)
    out.append("")
    return out


def build_dashboard(keyword_profiles, config, db_path=None) -> list[str]:
    """Compute + render the snapshot. Pure read-model — no persistence."""
    return render_dashboard_section(
        compute_dashboard(keyword_profiles, config, db_path))
