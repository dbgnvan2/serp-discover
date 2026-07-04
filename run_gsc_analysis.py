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
                          min_bucket_size: int = MIN_BUCKET_SIZE) -> dict:
    """Median CTR at comparable position: AIO-present vs AIO-absent queries.

    Only queries with GSC data AND a known AIO state participate. Per
    position band, the comparison is reported only when BOTH buckets hold
    at least *min_bucket_size* queries — otherwise the band states
    insufficient data (G.4.2); the no-AIO median alone is still computed
    when its own bucket is large enough (it anchors reformat_candidates).
    Spec: seo_geo_deferred_spec_v1.md#G.4.
    """
    bands = bands or DEFAULT_POSITION_BANDS
    usable = [
        r for r in rows
        if r.get("found") and r.get("has_ai_overview") is not None
        and r.get("position") is not None
    ]
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
        "bands": out_bands,
    }


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
                             max_position: float = REFORMAT_MAX_POSITION) -> list[dict]:
    """Queries with a stable/good position but CTR below the no-AIO median.

    Cross-referenced against strategic_flags.geo_alerts: a candidate whose
    source keyword also carries a GEO alert (client ranks top-10 but the
    AI Overview cites other sources) is the highest-priority
    reformat-for-extraction page (G.4.3).
    Spec: seo_geo_deferred_spec_v1.md#G.4.
    """
    candidates: list[dict] = []
    for row in rows:
        if not row.get("found") or row.get("position") is None:
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
        if row["ctr"] < band["no_aio_median_ctr"]:
            candidates.append({
                "query": row["query"],
                "query_label": row.get("query_label"),
                "source_keyword": row.get("source_keyword"),
                "position": position,
                "ctr": row["ctr"],
                "no_aio_median_ctr": band["no_aio_median_ctr"],
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
                    config: dict, source_json: str, date_range: tuple[str, str]) -> str:
    lines: list[str] = []
    client_name = (config.get("analysis_report", {}) or {}).get("client_name", "Client")
    gsc_cfg = config.get("gsc", {}) or {}
    lines.append("# Google Search Console Analysis — Zero-Click / Sponge Effect")
    lines.append(
        f"**Client:** {client_name} | **Property:** `{gsc_cfg.get('property', '—')}` "
        f"| **Window:** {date_range[0]} → {date_range[1]}")
    lines.append(f"**Source analysis:** `{os.path.basename(source_json)}`\n")
    lines.append(
        "> **Private data.** These are first-party numbers for the client's own "
        "property. They describe the client's position only — never quote them "
        "as market-level claims.\n")

    with_data = [r for r in rows if r.get("found")]
    lines.append("## Coverage")
    lines.append(f"- Queries checked: {len(rows)}")
    lines.append(f"- Queries with GSC data (impressions in window): {len(with_data)}")
    lines.append(
        f"- Queries with no GSC data: {len(rows) - len(with_data)} "
        "(no impressions recorded — reported as absent, not as zero)\n")

    lines.append("## The sponge table — does an AI Overview soak up clicks?")
    lines.append(
        "Median CTR at comparable position for queries where Google shows an AI "
        "Overview vs queries where it doesn't. A lower AIO-median at the same "
        "position band is the sponge effect: the ranking is intact but the "
        "answer above it absorbs the click.\n")
    lines.append("| Position band | AIO queries | No-AIO queries | Median CTR (AIO) | Median CTR (no AIO) | Delta |")
    lines.append("|---------------|-------------|----------------|------------------|---------------------|-------|")
    for band in sponge["bands"]:
        if band["sufficient"]:
            lines.append(
                f"| {band['band']} | {band['aio_query_count']} | {band['no_aio_query_count']} "
                f"| {_pct(band['aio_median_ctr'])} | {_pct(band['no_aio_median_ctr'])} "
                f"| {band['ctr_delta']:+.1%} |")
        else:
            lines.append(
                f"| {band['band']} | {band['aio_query_count']} | {band['no_aio_query_count']} "
                f"| — | {_pct(band['no_aio_median_ctr'])} | insufficient data "
                f"(needs ≥{sponge['min_bucket_size']} queries per bucket) |")
    if not sponge["data_available"]:
        lines.append(
            "\n*No band had enough queries in both buckets — the sponge comparison "
            "is not measurable on this run. More keywords or a longer lookback "
            "window will fill the buckets.*")
    lines.append("")

    lines.append("## Reformat candidates — good position, starving CTR")
    lines.append(
        "Queries ranking in the top 10 whose CTR sits below the no-AIO median "
        "for their position band. ⚑ marks queries whose keyword also carries a "
        "GEO alert (client ranks but the AI Overview cites other sources) — "
        "reformat those pages for answer extraction first.\n")
    if candidates:
        lines.append("| Query | Label | Position | CTR | No-AIO median | AIO on SERP | GEO alert |")
        lines.append("|-------|-------|----------|-----|---------------|-------------|-----------|")
        for c in candidates:
            aio = ("yes" if c["has_ai_overview"]
                   else "no" if c["has_ai_overview"] is not None else "unknown")
            lines.append(
                f"| {c['query']} | {c['query_label']} | {c['position']:.1f} "
                f"| {_pct(c['ctr'])} | {_pct(c['no_aio_median_ctr'])} | {aio} "
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
            lines.append(
                f"| {row['query']} | {row['query_label']} | — | — | — | — | no GSC data |")
    lines.append("")
    return "\n".join(lines)


def build_sidecar(rows: list[dict], sponge: dict, candidates: list[dict],
                  config: dict, source_json: str, date_range: tuple[str, str]) -> dict:
    gsc_cfg = config.get("gsc", {}) or {}
    return {
        "generated_at": datetime.now().isoformat(),
        "source_analysis": os.path.basename(source_json),
        "property": gsc_cfg.get("property"),
        "lookback_days": gsc_cfg.get("lookback_days"),
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "queries_checked": len(rows),
        "queries_with_data": sum(1 for r in rows if r.get("found")),
        "per_query": rows,
        "sponge": sponge,
        "reformat_candidates": candidates,
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
                 today: date | None = None) -> tuple[str, dict]:
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
        query_stats = stats.get(row["query"].lower())
        if query_stats:
            row.update(query_stats)
            row["found"] = True
        else:
            row["found"] = False
    logger.info("GSC returned data for %d of %d queries.",
                sum(1 for r in rows if r["found"]), len(rows))

    sponge = compute_sponge_effect(rows)
    candidates = find_reformat_candidates(rows, sponge, geo_alert_keywords(data))
    report = generate_report(rows, sponge, candidates, config, source_json, date_range)
    sidecar = build_sidecar(rows, sponge, candidates, config, source_json, date_range)
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
    # Imported here, not at module top of any pipeline module (G.4.4) —
    # but fine here: this script IS the only gsc_client consumer.
    from gsc_client import GscClient
    try:
        client = GscClient(
            property_url=gsc_cfg.get("property", ""),
            db_path=args.db,
            cache_ttl_days=int(gsc_cfg.get("cache_ttl_days", 7)),
        )
    except RuntimeError as exc:
        print(f"{exc} — 0 API calls made.")
        return 1

    try:
        report, sidecar = run_analysis(data, config, client, json_path)
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
