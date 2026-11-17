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
import gsc_filters

logger = logging.getLogger(__name__)

GSC_CACHE_TABLE = "gsc_cache"

_DEFER_NOTE = (
    "*Snapshot only.* The demand-vs-clicks **trend** (visibility falling while brand "
    "demand holds) is deferred: it needs per-keyword search volume (not provided by the "
    "current SERP sources) and a daily GSC series (Search Console returns per-query "
    "totals). This shows the point-in-time position; the branded-demand trend lives in "
    "the GSC analysis report (D2)."
)


def _resolve_filters(config):
    """``(cache filter key, resolved filters)`` for the configured country/device.

    The dashboard reads the same ``gsc_cache`` the standalone GSC fetch writes,
    so it must read the rows pulled under the configuration in force: a
    pre-D5.7 unfiltered row and a CAN/desktop row are two populations, and
    summing them into one click total is the fault D5.7 exists to prevent (cold
    review 2). ``gsc_filters`` holds the resolution so this module never
    imports ``gsc_client`` (pipeline isolation, G.4.4).
    """
    try:
        resolved = gsc_filters.resolve_query_filters(config)
    except Exception as exc:          # a config problem must not drop the section
        logger.warning("GSC filter resolution failed (%s) — reading unfiltered "
                       "cache rows only.", exc)
        return "", {"country": None, "device": None}
    return gsc_filters.cache_filter_key(resolved), resolved


def _latest_gsc(db_path, filter_key=""):
    """``({normalized_query: {...}}, gsc_ran)`` from the most recent ``gsc_cache``
    row per query. Each value carries ``clicks``, ``impressions``, GSC's own
    ``ctr`` and ``position``, and the ``start_date``/``end_date`` of the window
    those figures cover. ``gsc_ran`` is True when the table exists (GSC has been
    run) even if no query matched. Returns ``({}, False)`` — never raises (P2) —
    when there is no db, the table is absent, the db is locked, or it is corrupt.

    The ctr, position and window were added for D5.3 (D-M-17): the dashboard
    modelled a CTR loss against a curve while GSC's own measured CTR sat in the
    same row unread, and the report named no window for the figures it printed.
    """
    if not db_path:
        return {}, False
    try:
        with sqlite3.connect(db_path) as conn:
            # SQLite single-min/max bare-column rule: with exactly ONE MAX()/MIN()
            # and GROUP BY, the bare columns come from the row holding that
            # MAX(fetched_at) — i.e. the latest fetch per query. Adding a
            # second aggregate would break this; keep it a single MAX().
            # A cache written before D5.7 has no `filters` column at all; all
            # of its rows are unfiltered, so they are served to an unfiltered
            # read and to nothing else.
            columns = {r[1] for r in conn.execute(
                f"PRAGMA table_info({GSC_CACHE_TABLE})")}
            if not columns:
                return {}, False                      # table absent
            if "filters" not in columns:
                if filter_key:
                    logger.warning(
                        "gsc_cache holds no filtered rows (written before the "
                        "country/device filter existed) — no GSC overlay for "
                        "the configured population. Re-run the GSC fetch.")
                    return {}, True
                rows = conn.execute(
                    f"""SELECT query, clicks, impressions, ctr, position,
                               start_date, end_date, MAX(fetched_at)
                        FROM {GSC_CACHE_TABLE} WHERE found = 1
                        GROUP BY query""").fetchall()
            else:
                # COALESCE: a row written before the column was populated
                # carries NULL and means "unfiltered".
                rows = conn.execute(
                    f"""SELECT query, clicks, impressions, ctr, position,
                               start_date, end_date, MAX(fetched_at)
                        FROM {GSC_CACHE_TABLE}
                        WHERE found = 1 AND COALESCE(filters, '') = ?
                        GROUP BY query""", (filter_key,)).fetchall()
    except sqlite3.OperationalError:
        return {}, False   # table absent (GSC never run) or db locked — degrade silently
    except Exception as exc:   # corrupt / not-a-database → degrade, never drop the report
        logger.warning("gsc_cache read failed (%s) — showing AIO coverage only.", exc)
        return {}, False
    return ({
        str(q).strip().lower(): {
            "clicks": c or 0, "impressions": i or 0,
            "ctr": ctr, "position": pos,
            "start_date": start, "end_date": end,
        }
        for q, c, i, ctr, pos, start, end, _ in rows
    }, True)


def compute_dashboard(keyword_profiles, config, db_path=None):
    """Assemble the snapshot read-model (no new storage). Joins D1 AIO exposure to
    GSC clicks by normalized keyword (``gsc_cache.query`` is lower-cased; the
    profile keys are raw, so both sides are lower/stripped before matching)."""
    aio_rows, rollup = aio_exposure.compute_aio_exposure(keyword_profiles, config)
    filter_key, filters = _resolve_filters(config)
    gsc, gsc_ran = _latest_gsc(db_path, filter_key)

    exposure_cfg = aio_exposure.resolve_exposure_config(config)
    total_clicks = total_impr = matched = 0
    est_at_risk = 0.0
    at_risk = []
    zero_click_at_risk: list[str] = []
    for row in aio_rows:
        stats = gsc.get(str(row["keyword"]).strip().lower())
        if not stats:
            continue
        matched += 1
        total_clicks += stats["clicks"]
        total_impr += stats["impressions"]
        # D5.3 (D-M-17): the figure is a share of the clicks the client
        # actually receives, so it is the modelled interception share applied
        # to the measured clicks — never a CTR-point loss applied to
        # impressions, which produced more clicks at risk than the query had.
        # The share is position-free (the multiplier, halved where cited), so
        # it is bounded by the measured clicks by construction.
        share = aio_exposure.interception_share(
            row["aio_present"], row["client_cited"], exposure_cfg)
        intercepted = float(stats["clicks"]) * share
        # est_traffic_at_risk is scoped to AIO keywords where the client is NOT cited
        # — matching the label + docs. A cited keyword already owns the citation, so
        # its (halved) loss must not inflate the "at risk" total.
        if row["aio_present"] and not row["client_cited"]:
            # A keyword with impressions and no clicks has nothing to
            # intercept, but it is the most exposed case, not an absence.
            # Counted and stated rather than dropped (P2, cold review 5).
            if not stats["clicks"]:
                zero_click_at_risk.append(row["keyword"])
                continue
            est_at_risk += intercepted
            at_risk.append({
                "keyword": row["keyword"], "clicks": stats["clicks"],
                "impressions": stats["impressions"],
                "est_intercepted": round(intercepted, 1),
            })
    at_risk.sort(key=lambda d: -d["est_intercepted"])
    # The window the GSC figures cover. All rows of one fetch share it; a mixed
    # cache (two windows) is reported as the span, never as one of them.
    _starts = sorted({s["start_date"] for s in gsc.values() if s.get("start_date")})
    _ends = sorted({s["end_date"] for s in gsc.values() if s.get("end_date")})
    return {
        "gsc_window": ({"start": _starts[0], "end": _ends[-1],
                        "mixed": len(_starts) > 1 or len(_ends) > 1}
                       if _starts and _ends else None),
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
        # AIO, not cited, impressions but zero clicks: nothing to intercept,
        # and the most exposed case there is (P2, cold review 5).
        "zero_click_at_risk": sorted(zero_click_at_risk),
        # Which searchers these GSC figures are about (D5.7, cold review 2).
        "gsc_population": gsc_filters.filters_text(filters),
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

    # D5.3 (D-M-17): the figures are for a window, and the window belongs
    # beside them — a click count with no period is not a measurement.
    _window = dash.get("gsc_window")
    if _window:
        out.append(
            f"- **Search Console window:** {_window['start']} to {_window['end']}"
            + (f", {dash['gsc_population']}" if dash.get("gsc_population") else "")
            + (" (the cache holds more than one window; this is the span of "
               "them, so the figures below are not all from one period)"
               if _window.get("mixed") else "")
            + "."
        )
    out.append(
        f"- **Client clicks (GSC):** {dash['total_clicks']} clicks / "
        f"{dash['total_impressions']} impressions across {dash['matched_query_count']} "
        "matched tracked queries."
    )
    out.append(
        f"- **Estimated traffic at risk to AI Overviews:** ~{dash['est_traffic_at_risk']:.0f} "
        "clicks/period (indicative — for AIO keywords where the client is not "
        "cited, the modeled AI-Overview interception share applied to the "
        "clicks Search Console measured for each keyword. It is a share of the "
        "clicks the client has, so it cannot exceed them.)"
    )
    if dash.get("zero_click_at_risk"):
        names = dash["zero_click_at_risk"]
        out.append(
            f"- **{len(names)} AIO keyword(s) had impressions but no clicks** and "
            "so contribute nothing to the figure above — there is no click to "
            "intercept. These are the most exposed keywords, not the least: "
            + ", ".join(names[:5])
            + (f" and {len(names) - 5} more." if len(names) > 5 else "."))
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
