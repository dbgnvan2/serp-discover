#!/usr/bin/env python3
"""
run_gsc_analysis.py
~~~~~~~~~~~~~~~~~~~
Standalone Google Search Console analysis for an existing market analysis
JSON: joins first-party click/impression/CTR/position data onto the run's
queries and measures the zero-click / AI Overview "sponge" effect on the
client's own traffic.

Spec: seo_geo_deferred_spec_v1.md#G.4 (decision gate D-3: headless
service-account auth via GSC_CREDENTIALS_PATH; the service-account email
must be granted on the Search Console property).

Pattern: run_feasibility.py — reads config + the latest
market_analysis_*.json, runs any time, no pipeline coupling. The main
pipeline never imports this module or gsc_client (G.4.4).

Usage
-----
::

    python run_gsc_analysis.py
    python run_gsc_analysis.py --json market_analysis_x.json --out gsc_report.md

Outputs (both gitignored):
- ``gsc_analysis_<topic>_<ts>.md`` — human report with the sponge table.
- ``gsc_analysis_<topic>_<ts>.json`` — sidecar consumed (optionally, when
  config ``gsc.feed_strategic_flags`` is true) by the content brief as
  ``gsc_summary``.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from statistics import median

import gsc_client
import gsc_demand

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# GSC positions are grouped into bands so CTRs are compared at comparable
# rank ("median CTR at comparable position", spec G.4 required change 2).
DEFAULT_POSITION_BANDS: list[tuple[float, float]] = [(1, 3), (4, 10), (11, 20)]

#: Minimum queries per bucket before the sponge comparison is trusted.
MIN_BUCKET_SIZE = 3

#: How many top PAA phrasings join the query set.
MAX_PAA_QUERIES = 20

#: Ranking is "good" (reformat candidate territory) up to this position.
REFORMAT_MAX_POSITION = 10.0

#: Minimum impressions before a query's CTR is treated as a measurement.
#: A query with two impressions and no click has a CTR of 0.0, which is not a
#: CTR — it is an absence of data. Editorial: config `gsc.min_impressions`.
DEFAULT_MIN_IMPRESSIONS = 50

#: How far below the band's no-AIO median a CTR must sit before the query is a
#: reformat candidate. Without a margin "below the median" is half the rows by
#: construction (D-M-15). Editorial: config `gsc.reformat_ctr_margin`.
DEFAULT_REFORMAT_CTR_MARGIN = 0.25


def resolve_sponge_thresholds(cfg: dict | None) -> dict:
    """``{min_impressions, reformat_ctr_margin}`` from config `gsc`.

    Spec: review_2026-11-04 D5.1 / D5.2 (D-M-15)

    Both are judgements about this property's traffic, so they are editorial.
    A missing or non-numeric value warns and falls back to the documented
    default rather than aborting.
    """
    gsc_cfg = (cfg or {}).get("gsc", {}) or {}
    out = {"min_impressions": DEFAULT_MIN_IMPRESSIONS,
           "reformat_ctr_margin": DEFAULT_REFORMAT_CTR_MARGIN}
    for key, cast in (("min_impressions", int), ("reformat_ctr_margin", float)):
        if key not in gsc_cfg:
            continue
        try:
            value = cast(gsc_cfg[key])
        except (TypeError, ValueError):
            logger.warning("gsc.%s is not a number (%r) — using %s.",
                           key, gsc_cfg[key], out[key])
            continue
        if value < 0:
            logger.warning("gsc.%s is negative (%r) — using %s.",
                           key, value, out[key])
            continue
        out[key] = value
    return out


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
    configured = (config.get("files", {}) or {}).get("output_json")
    if configured and os.path.exists(configured):
        return configured
    candidates = glob.glob("market_analysis_*.json") + glob.glob("output/market_analysis_*.json")
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _derive_output_base(json_path: str) -> str:
    base = os.path.basename(json_path or "report.json")
    slug = re.sub(r"^market_analysis_", "", base)
    slug = re.sub(r"(?:_\d{8}_\d{4})?\.json$", "", slug) or "report"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"gsc_analysis_{slug}_{timestamp}"


# ---------------------------------------------------------------------------
# Query collection (root keywords + A.1/A.2/S variants + top PAA phrasings)
# ---------------------------------------------------------------------------

def collect_queries(data: dict, max_paa: int = MAX_PAA_QUERIES) -> list[dict]:
    """Build the query set with ``has_ai_overview`` joined from the run.

    - overview rows labeled A / A.1 / A.2: Executed_Query with the
      main-response AIO flag;
    - situational probes (label "S"): Executed_Query with Has_AI_Overview;
    - top PAA phrasings (AIO state unknown → None, never guessed).
    """
    rows: list[dict] = []
    seen: set[str] = set()

    def _add(query: str, label: str, source_keyword: str, has_aio) -> None:
        query = (query or "").strip()
        key = query.lower()
        if not query or key in seen:
            return
        seen.add(key)
        rows.append({
            "query": query,
            "query_label": label,
            "source_keyword": source_keyword,
            "has_ai_overview": has_aio,
        })

    for row in data.get("overview") or []:
        label = str(row.get("Query_Label") or "")
        if label not in ("A", "A.1", "A.2"):
            continue
        _add(str(row.get("Executed_Query") or row.get("Source_Keyword") or ""),
             label, str(row.get("Source_Keyword") or ""),
             bool(row.get("Has_Main_AI_Overview")))

    for row in data.get("situational_probes") or []:
        _add(str(row.get("Executed_Query") or ""), "S",
             str(row.get("Source_Keyword") or ""),
             bool(row.get("Has_AI_Overview")))

    paa_added = 0
    for row in data.get("paa_questions") or []:
        if paa_added >= max_paa:
            break
        before = len(rows)
        _add(str(row.get("Question") or ""), "PAA",
             str(row.get("Source_Keyword") or ""), None)
        if len(rows) > before:
            paa_added += 1

    return rows


# ---------------------------------------------------------------------------
# Sponge computation (G.4.2)
# ---------------------------------------------------------------------------

def compute_sponge_effect(rows: list[dict],
                          bands: list[tuple[float, float]] = None,
                          min_bucket_size: int = MIN_BUCKET_SIZE,
                          not_reached: int = 0,
                          min_impressions: int = DEFAULT_MIN_IMPRESSIONS) -> dict:
    """Median CTR at comparable position: AIO-present vs AIO-absent queries.

    Only queries with GSC data, a known AIO state, a position AND at least
    *min_impressions* impressions participate. Per position band, the
    comparison is reported only when BOTH buckets hold at least
    *min_bucket_size* queries — otherwise the band states insufficient data
    (G.4.2); the no-AIO median alone is still computed when its own bucket is
    large enough (it anchors reformat_candidates).

    The impression floor was added for D5.1 (D-M-15): a query with two
    impressions and no click contributes a CTR of 0.0 to the median, which is
    not a low CTR but an absence of one. The floor and how many queries it
    excluded travel with the figures (P2).

    What this measures is an ASSOCIATION at comparable position, not an
    effect. Queries that trigger an AI Overview differ from those that do not
    in exactly the way that also drives CTR — they are more often
    informational — so intent confounds the comparison. The report says so.

    Spec: seo_geo_deferred_spec_v1.md#G.4; review_2026-11-04 D5.1 (D-M-15).
    """
    bands = bands or DEFAULT_POSITION_BANDS
    with_state = [
        r for r in rows
        if r.get("found") and r.get("has_ai_overview") is not None
        and r.get("position") is not None
    ]
    floor = int(min_impressions or 0)
    usable = [r for r in with_state
              if _to_number(r.get("impressions")) >= floor]
    below_floor = len(with_state) - len(usable)
    out_bands: list[dict] = []
    for low, high in bands:
        in_band = [r for r in usable if low <= r["position"] <= high]
        aio_ctrs = [r["ctr"] for r in in_band if r["has_ai_overview"]]
        no_aio_ctrs = [r["ctr"] for r in in_band if not r["has_ai_overview"]]
        sufficient = len(aio_ctrs) >= min_bucket_size and len(no_aio_ctrs) >= min_bucket_size
        aio_median = round(median(aio_ctrs), 4) if sufficient else None
        no_aio_median = (round(median(no_aio_ctrs), 4)
                         if len(no_aio_ctrs) >= min_bucket_size else None)
        out_bands.append({
            "band": f"{low:g}-{high:g}",
            "band_range": [low, high],
            "aio_query_count": len(aio_ctrs),
            "no_aio_query_count": len(no_aio_ctrs),
            "sufficient": sufficient,
            "aio_median_ctr": aio_median,
            "no_aio_median_ctr": no_aio_median,
            "ctr_delta": (round(aio_median - no_aio_median, 4)
                          if sufficient and no_aio_median is not None else None),
        })
    return {
        "data_available": any(b["sufficient"] for b in out_bands),
        "min_bucket_size": min_bucket_size,
        # D2b.8 — the denominator travels with the figures (P2).
        "queries_considered": len(rows),
        "queries_usable": len(usable),
        # D5.1 — and what the impression floor cost (P2/P9).
        "min_impressions": floor,
        "queries_below_impression_floor": below_floor,
        "not_reached": int(not_reached or 0),
        "bands": out_bands,
    }


def _to_number(value) -> float:
    """``value`` as a float, or 0.0 when it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Reformat candidates (G.4.3)
# ---------------------------------------------------------------------------

def geo_alert_keywords(data: dict) -> set[str]:
    """Keywords flagged by strategic_flags.geo_alerts (T.4).

    Uses the analysis JSON's own strategic_flags when present; otherwise
    derives the same set from the embedded keyword_profiles
    ``aio_divergence.client_ranks_but_not_cited`` booleans (the geo_alerts
    source of truth).
    """
    alerts = ((data.get("strategic_flags") or {}).get("geo_alerts")) or []
    keywords = {str(a.get("keyword") or "").strip() for a in alerts if isinstance(a, dict)}
    keywords.discard("")
    if keywords:
        return keywords
    derived: set[str] = set()
    for keyword, profile in (data.get("keyword_profiles") or {}).items():
        divergence = (profile or {}).get("aio_divergence") or {}
        if divergence.get("client_ranks_but_not_cited"):
            derived.add(keyword)
    return derived


def find_reformat_candidates(rows: list[dict], sponge: dict,
                             geo_alert_kws: set[str],
                             max_position: float = REFORMAT_MAX_POSITION,
                             min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
                             ctr_margin: float = DEFAULT_REFORMAT_CTR_MARGIN) -> list[dict]:
    """Queries ranking well whose CTR sits a stated margin below the no-AIO
    median for their band, where an AI Overview is actually present.

    Cross-referenced against strategic_flags.geo_alerts: a candidate whose
    source keyword also carries a GEO alert (client ranks top-10 but the
    AI Overview cites other sources) is the highest-priority
    reformat-for-extraction page (G.4.3).

    Three conditions were added for D5.2 (D-M-15). "CTR below the median" is
    half the rows by construction, so a *margin* is required. A reformat for
    extraction is advice about an AI Overview, so one must be PRESENT — the
    rule used to name queries Google answers with no AI Overview at all. And
    the CTR must rest on at least *min_impressions* impressions, or it is not
    a CTR.

    Spec: seo_geo_deferred_spec_v1.md#G.4; review_2026-11-04 D5.2 (D-M-15).
    """
    candidates: list[dict] = []
    floor = int(min_impressions or 0)
    margin = float(ctr_margin or 0.0)
    for row in rows:
        if not row.get("found") or row.get("position") is None:
            continue
        # An AI Overview must be present: this is advice about extraction from
        # one. `None` is an unknown AIO state, not a present one.
        if row.get("has_ai_overview") is not True:
            continue
        if _to_number(row.get("impressions")) < floor:
            continue
        position = row["position"]
        if position > max_position:
            continue
        band = next(
            (b for b in sponge.get("bands", [])
             if b["band_range"][0] <= position <= b["band_range"][1]),
            None,
        )
        if not band or band.get("no_aio_median_ctr") is None:
            continue
        threshold = band["no_aio_median_ctr"] * (1.0 - margin)
        if _to_number(row.get("ctr")) < threshold:
            candidates.append({
                "query": row["query"],
                "query_label": row.get("query_label"),
                "source_keyword": row.get("source_keyword"),
                "position": position,
                "ctr": row["ctr"],
                "impressions": row.get("impressions"),
                "no_aio_median_ctr": band["no_aio_median_ctr"],
                "ctr_threshold": round(threshold, 4),
                "ctr_margin": margin,
                "has_ai_overview": row.get("has_ai_overview"),
                "geo_alert": (row.get("source_keyword") or "") in geo_alert_kws,
            })
    candidates.sort(key=lambda c: (not c["geo_alert"], c["position"]))
    return candidates


# ---------------------------------------------------------------------------
# Report + sidecar
# ---------------------------------------------------------------------------

def _pct(value) -> str:
    return f"{value:.1%}" if value is not None else "—"


def generate_report(rows: list[dict], sponge: dict, candidates: list[dict],
                    config: dict, source_json: str, date_range: tuple[str, str],
                    demand_score: dict | None = None,
                    demand_trend: list | None = None,
                    fetch_complete: bool = True,
                    filters: dict | None = None,
                    thresholds: dict | None = None) -> str:
    lines: list[str] = []
    client_name = (config.get("analysis_report", {}) or {}).get("client_name", "Client")
    gsc_cfg = config.get("gsc", {}) or {}
    lines.append("# Google Search Console Analysis — Zero-Click / Sponge Effect")
    lines.append(
        f"**Client:** {client_name} | **Property:** `{gsc_cfg.get('property', '—')}` "
        f"| **Window:** {date_range[0]} → {date_range[1]} "
        f"| **Pulled for:** {gsc_client.filters_text(filters or {})}")
    lines.append(f"**Source analysis:** `{os.path.basename(source_json)}`\n")
    if not (filters or {}).get("country") or not (filters or {}).get("device"):
        lines.append(
            "> **Mixed populations.** The SERP side of this analysis is fetched "
            f"for one country and one device (`serpapi.gl` = "
            f"`{(config.get('serpapi') or {}).get('gl', '—')}`, "
            f"`serpapi.device` = "
            f"`{(config.get('serpapi') or {}).get('device', '—')}`). This GSC "
            "pull is not restricted the same way, so a CTR here and a rank "
            "there are measured over different populations. Set `gsc.country` "
            "and `gsc.device` to match.\n")
    lines.append(
        "> **Private data.** These are first-party numbers for the client's own "
        "property. They describe the client's position only — never quote them "
        "as market-level claims.\n")

    with_data = [r for r in rows if r.get("found")]
    unreached = [r for r in rows
                 if r.get("gsc_status") == gsc_client.STATUS_NOT_REACHED]
    # Not measured and not unreached is measured absence (D2b.5).
    absent = [r for r in rows
              if r.get("gsc_status") != gsc_client.STATUS_NOT_REACHED
              and not r.get("found")]
    lines.append("## Coverage")
    if unreached:
        lines.append(gsc_client.line(
            "partial_warning",
            "**Incomplete fetch.** {not_reached} of {asked} queries were never "
            "reached, so every count below is over {reached} queries.",
            asked=len(rows), not_reached=len(unreached),
            reached=len(rows) - len(unreached)))
        lines.append("")
    lines.append(f"- Queries checked: {len(rows)}")
    lines.append(f"- Queries with GSC data (impressions in window): {len(with_data)}")
    if absent:
        lines.append("- " + gsc_client.line(
            "coverage_measured_absent",
            "Queries GSC holds no data for: {count} (no impressions recorded "
            "in the window for {population} — reported as absent, not as zero)",
            population=gsc_client.filters_text(filters or {}),
            count=len(absent)))
    if unreached:
        lines.append("- " + gsc_client.line(
            "coverage_not_reached",
            "Queries the fetch could not reach: {count} (the GSC request "
            "failed or was truncated — these are NOT recorded as having no "
            "impressions; re-run)",
            count=len(unreached)))
    lines.append("")

    if demand_score is not None:
        lines.extend(gsc_demand.render_demand_section(demand_score, demand_trend))

    lines.append("## The sponge table — does an AI Overview soak up clicks?")
    lines.append(
        "Median CTR at comparable position for queries where Google shows an AI "
        "Overview vs queries where it doesn't. A lower AIO-median at the same "
        "position band is consistent with the answer above the result absorbing "
        "the click while the ranking stays intact.\n")
    # D5.1 (D-M-15): this is an association, and the thing that decides which
    # queries get an AI Overview — their intent — also decides CTR.
    lines.append(
        "**Read this as an association, not an effect.** The two buckets are "
        "not alike apart from the AI Overview: Google shows one mostly on "
        "informational queries, and informational queries have lower CTR at "
        "every position anyway. The table cannot separate the AI Overview from "
        "the intent. A same-query comparison before and after an AI Overview "
        "appeared would; this is not that.\n")
    _floor = sponge.get("min_impressions")
    if _floor:
        _dropped = sponge.get("queries_below_impression_floor") or 0
        lines.append(
            f"Queries need at least **{_floor} impressions** in the window to "
            f"contribute a median: a CTR computed from a handful of impressions "
            f"is not a measurement. "
            + (f"{_dropped} of {sponge.get('queries_usable', 0) + _dropped} "
               f"otherwise-usable queries fell below that floor.\n"
               if _dropped else "No query fell below that floor.\n"))
    lines.append("| Position band | AIO queries | No-AIO queries | Median CTR (AIO) | Median CTR (no AIO) | Delta |")
    lines.append("|---------------|-------------|----------------|------------------|---------------------|-------|")
    for band in sponge["bands"]:
        if band["sufficient"]:
            lines.append(
                f"| {band['band']} | {band['aio_query_count']} | {band['no_aio_query_count']} "
                f"| {_pct(band['aio_median_ctr'])} | {_pct(band['no_aio_median_ctr'])} "
                f"| {band['ctr_delta']:+.1%} |")
        else:
            # D2b.8 — "insufficient data" must not read as the client's
            # property when the rows are missing because the fetch failed.
            if sponge.get("not_reached"):
                reason = gsc_client.line(
                    "band_short_of_rows",
                    "insufficient data (needs ≥{needed} queries per bucket; "
                    "{not_reached} queries were never reached)",
                    needed=sponge["min_bucket_size"],
                    not_reached=sponge["not_reached"])
            else:
                reason = (f"insufficient data (needs ≥{sponge['min_bucket_size']} "
                          "queries per bucket)")
            lines.append(
                f"| {band['band']} | {band['aio_query_count']} | {band['no_aio_query_count']} "
                f"| — | {_pct(band['no_aio_median_ctr'])} | {reason} |")
    if not sponge["data_available"]:
        if sponge.get("not_reached"):
            lines.append(
                f"\n*No band had enough queries in both buckets, and "
                f"{sponge['not_reached']} of {sponge.get('queries_considered', 0)} "
                "queries were never reached — so this is a gap in the fetch, "
                "not a measurement of the client. Re-run before reading "
                "anything into it.*")
        else:
            lines.append(
                "\n*No band had enough queries in both buckets — the sponge comparison "
                "is not measurable on this run. More keywords or a longer lookback "
                "window will fill the buckets.*")
    lines.append("")

    lines.append("## Reformat candidates — good position, starving CTR")
    # The margin the run actually used, not one re-derived from the output
    # rows: with no candidates there is no row to read it off, and printing
    # the default while config says otherwise is a false claim (cold review 7).
    _margin = (thresholds or {}).get("reformat_ctr_margin")
    if _margin is None:
        _margin = next((c.get("ctr_margin") for c in candidates
                        if c.get("ctr_margin") is not None),
                       resolve_sponge_thresholds(config)["reformat_ctr_margin"])
    lines.append(
        f"Queries ranking in the top 10, **with an AI Overview on the SERP**, "
        f"whose CTR sits at least {_margin:.0%} below the no-AIO median for "
        f"their position band. ⚑ marks queries whose keyword also carries a "
        f"GEO alert (client ranks but the AI Overview cites other sources) — "
        f"reformat those pages for answer extraction first.\n")
    # D5.2 (D-M-15): say what the three conditions are, because "below the
    # median" on its own names half the queries whatever the data says.
    lines.append(
        f"*A margin, not just \"below the median\": half of any set sits below "
        f"its own median. The query must also carry at least "
        f"{sponge.get('min_impressions', DEFAULT_MIN_IMPRESSIONS)} impressions, "
        f"so the CTR is a measurement.*\n")
    # D2b.8 — "no candidates" over 4 of 40 queries is not the same
    # statement as "no candidates" over 40 of 40.
    lines.append(
        f"*Searched {sponge.get('queries_usable', 0)} of "
        f"{sponge.get('queries_considered', len(rows))} queries — those with "
        "a GSC position and a known AI Overview state.*")
    if sponge.get("not_reached"):
        lines.append(
            f"*{sponge['not_reached']} query/queries were never reached, so "
            "they could not be considered. A page missing from this list may "
            "simply be one of them.*")
    lines.append("")
    if candidates:
        lines.append("| Query | Label | Position | Impressions | CTR | No-AIO median | Threshold | GEO alert |")
        lines.append("|-------|-------|----------|-------------|-----|---------------|-----------|-----------|")
        for c in candidates:
            lines.append(
                f"| {c['query']} | {c['query_label']} | {c['position']:.1f} "
                f"| {c.get('impressions', '—')} "
                f"| {_pct(c['ctr'])} | {_pct(c['no_aio_median_ctr'])} "
                f"| {_pct(c.get('ctr_threshold'))} "
                f"| {'⚑ yes' if c['geo_alert'] else 'no'} |")
    else:
        lines.append("*No reformat candidates identified on this run.*")
    lines.append("")

    lines.append("## Per-query detail")
    lines.append("| Query | Label | Clicks | Impressions | CTR | Avg position | AIO on SERP |")
    lines.append("|-------|-------|--------|-------------|-----|--------------|-------------|")
    for row in sorted(rows, key=lambda r: -(r.get("impressions") or 0)):
        if row.get("found"):
            aio = ("yes" if row["has_ai_overview"]
                   else "no" if row["has_ai_overview"] is not None else "unknown")
            lines.append(
                f"| {row['query']} | {row['query_label']} | {row['clicks']} "
                f"| {row['impressions']} | {_pct(row['ctr'])} "
                f"| {row['position']:.1f} | {aio} |")
        else:
            # D2b.5 — the cell says which of the two it was.
            status = row.get("gsc_status") or gsc_client.STATUS_MEASURED_ABSENT
            cell = gsc_client.status_text(status, "cell")
            if status == gsc_client.STATUS_MEASURED_ABSENT:
                # The absence is an absence for the pulled population only
                # (D5.7, cold review 1). status_text falls back to the status
                # word when the key is missing, so the suffix is only appended
                # when the configured value is really a suffix.
                suffix = gsc_client.status_text(status, "population_suffix")
                if "{population}" in suffix:
                    cell += suffix.format(
                        population=gsc_client.filters_text(filters or {}))
            lines.append(
                f"| {row['query']} | {row['query_label']} | — | — | — | — | {cell} |")
    lines.append("")
    return "\n".join(lines)


def build_sidecar(rows: list[dict], sponge: dict, candidates: list[dict],
                  config: dict, source_json: str, date_range: tuple[str, str],
                  demand_score: dict | None = None,
                  fetch_complete: bool = True,
                  filters: dict | None = None) -> dict:
    gsc_cfg = config.get("gsc", {}) or {}
    unreached = [r["query"] for r in rows
                 if r.get("gsc_status") == gsc_client.STATUS_NOT_REACHED]
    return {
        "generated_at": datetime.now().isoformat(),
        "source_analysis": os.path.basename(source_json),
        "property": gsc_cfg.get("property"),
        "lookback_days": gsc_cfg.get("lookback_days"),
        "date_range": {"start": date_range[0], "end": date_range[1]},
        # D5.7 — which country/device the clicks were pulled for. A consumer
        # comparing them with a SERP figure needs to know they match.
        "query_filters": {"country": (filters or {}).get("country"),
                          "device": (filters or {}).get("device")},
        "queries_checked": len(rows),
        "queries_with_data": sum(1 for r in rows if r.get("found")),
        # D2b.6 — a consumer, the brief's LLM payload included, must tell
        # "no search traffic" from "the fetch failed".
        "fetch_complete": bool(fetch_complete) and not unreached,
        "queries_not_reached": unreached,
        "queries_no_impressions": [
            r["query"] for r in rows
            if r.get("gsc_status") == gsc_client.STATUS_MEASURED_ABSENT],
        "per_query": rows,
        "sponge": sponge,
        "reformat_candidates": candidates,
        "demand": demand_score,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def check_preconditions(config: dict) -> tuple[bool, str]:
    """Return (ok, message). Never touches the network (G.4.4)."""
    gsc_cfg = config.get("gsc", {}) or {}
    if not gsc_cfg.get("enabled", False):
        return False, ("GSC analysis is disabled (config.yml gsc.enabled: false) — "
                       "0 API calls made. Enable it and set GSC_CREDENTIALS_PATH to run.")
    credentials_path = os.getenv("GSC_CREDENTIALS_PATH", "").strip()
    if not credentials_path:
        return False, ("GSC_CREDENTIALS_PATH is not set — 0 API calls made. "
                       "Point it at the service-account JSON key "
                       "(the service-account email must be granted on the "
                       "Search Console property; see docs/USER_MANUAL.md).")
    if not os.path.exists(credentials_path):
        return False, (f"GSC credentials file not found: {credentials_path} — "
                       "0 API calls made.")
    return True, ""


def run_analysis(data: dict, config: dict, client, source_json: str,
                 today: date | None = None,
                 db_path: str | None = None) -> tuple[str, dict]:
    """Pull GSC stats for the run's queries and build (report_md, sidecar)."""
    gsc_cfg = config.get("gsc", {}) or {}
    lookback_days = int(gsc_cfg.get("lookback_days", 90))
    end = today or date.today()
    start = end - timedelta(days=lookback_days)
    date_range = (start.isoformat(), end.isoformat())

    rows = collect_queries(data)
    if not rows:
        raise RuntimeError("No queries could be collected from the analysis JSON.")
    logger.info("Fetching GSC stats for %d queries (%s → %s)...",
                len(rows), *date_range)
    stats = client.get_query_stats([r["query"] for r in rows], *date_range)

    for row in rows:
        query_stats = stats.stats.get(row["query"].lower())
        if query_stats:
            row.update(query_stats)
            row["found"] = True
        else:
            row["found"] = False
        # D2b.4 — `found` alone cannot say why there are no figures: GSC
        # answering "nothing" is a finding about the client, an unreached
        # query is one about the fetch.
        row["gsc_status"] = stats.status_for(row["query"])

    measured = sum(1 for r in rows if r["gsc_status"] == gsc_client.STATUS_MEASURED)
    absent = sum(1 for r in rows
                 if r["gsc_status"] == gsc_client.STATUS_MEASURED_ABSENT)
    unreached = sum(1 for r in rows
                    if r["gsc_status"] == gsc_client.STATUS_NOT_REACHED)
    if stats.complete and not unreached:
        logger.info("%s", gsc_client.line(
            "fetch_complete",
            "GSC answered for all {asked} query/queries: {measured} with data, "
            "{measured_absent} with no impressions in the window for "
            "{population}.",
            asked=len(rows), measured=measured, measured_absent=absent,
            population=gsc_client.filters_text(
                getattr(client, "filters", None) or {})))
    else:
        logger.warning("%s", gsc_client.line(
            "fetch_incomplete",
            "GSC fetch INCOMPLETE — {measured} of {asked} query/queries "
            "returned data, {not_reached} were never reached.",
            asked=len(rows), measured=measured, not_reached=unreached))

    _thresholds = resolve_sponge_thresholds(config)
    sponge = compute_sponge_effect(
        rows, not_reached=unreached,
        min_impressions=_thresholds["min_impressions"])
    candidates = find_reformat_candidates(
        rows, sponge, geo_alert_keywords(data),
        min_impressions=_thresholds["min_impressions"],
        ctr_margin=_thresholds["reformat_ctr_margin"])

    # D2/AV.2 — branded vs non-branded demand. Classify the rows just pulled and
    # persist per-run (grain = run_ts, parsed from the source filename) so the
    # branded share trends across runs (D-D2a). Classification is recomputed every
    # run so a client_name_patterns edit reclassifies (never gated by the cache).
    _filters = getattr(client, "filters", None) or {}
    rows, demand_score = gsc_demand.compute_demand(
        rows, config, fetch_complete=stats.complete and not unreached,
        property_rows=getattr(stats, "property_rows", None),
        filters={**_filters, "text": gsc_client.filters_text(_filters)})
    demand_trend = None
    run_ts = gsc_demand.run_ts_from_filename(source_json)
    property_ = (config.get("gsc", {}) or {}).get("property")
    if db_path and run_ts and property_:
        try:
            gsc_demand.save_demand(db_path, property_, run_ts, rows, demand_score,
                                   fetched_at=run_ts)
            demand_trend = gsc_demand.get_demand_trend(db_path, property_)
        except Exception as exc:   # persistence must never break the report
            logger.warning("gsc_demand persistence failed: %s", exc)
    elif db_path and run_ts and not property_:
        # Without a property the (property, run_ts) idempotency key matches on NULL
        # and every re-run would append duplicates — skip + warn, render still fires.
        logger.warning("gsc.property is not set — skipping gsc_demand persistence "
                       "(the demand section still renders).")

    filters = _filters
    report = generate_report(rows, sponge, candidates, config, source_json,
                             date_range, demand_score=demand_score,
                             demand_trend=demand_trend,
                             fetch_complete=stats.complete and not unreached,
                             filters=filters, thresholds=_thresholds)
    sidecar = build_sidecar(rows, sponge, candidates, config, source_json,
                            date_range, demand_score=demand_score,
                            fetch_complete=stats.complete and not unreached,
                            filters=filters)
    return report, sidecar


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Join Google Search Console click data onto the latest market analysis."
    )
    parser.add_argument("--json", default=None,
                        help="Path to market_analysis_*.json (default: latest)")
    parser.add_argument("--out", default=None,
                        help="Output markdown path (sidecar JSON uses the same base name)")
    parser.add_argument("--db", default="serp_data.db", help="SQLite database path (cache)")
    parser.add_argument("--config", default="config.yml", help="Config path")
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    ok, message = check_preconditions(config)
    if not ok:
        print(message)
        return 0

    json_path = args.json or _latest_analysis_json(config)
    if not json_path or not os.path.exists(json_path):
        logger.error("No market_analysis_*.json found — run the pipeline first or pass --json.")
        return 1
    logger.info("Loading market analysis: %s", json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    gsc_cfg = config.get("gsc", {}) or {}
    GscClient = gsc_client.GscClient
    try:
        query_filters = gsc_client.resolve_query_filters(config)
        for warning in query_filters["warnings"]:
            logger.warning("%s", warning)
        client = GscClient(
            property_url=gsc_cfg.get("property", ""),
            db_path=args.db,
            cache_ttl_days=int(gsc_cfg.get("cache_ttl_days", 7)),
            filters=query_filters,
        )
        logger.info("GSC pull restricted to: %s",
                    gsc_client.filters_text(query_filters))
    except RuntimeError as exc:
        print(f"{exc} — 0 API calls made.")
        return 1

    try:
        report, sidecar = run_analysis(data, config, client, json_path,
                                       db_path=args.db)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    base = args.out[:-3] if (args.out or "").endswith(".md") else args.out
    base = base or _derive_output_base(json_path)
    md_path = f"{base}.md"
    sidecar_path = f"{base}.json"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, ensure_ascii=False)

    logger.info("Report written: %s", md_path)
    logger.info("Sidecar written: %s", sidecar_path)
    print(f"GSC_ANALYSIS_OUT={md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
