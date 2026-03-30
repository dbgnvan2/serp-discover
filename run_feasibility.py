#!/usr/bin/env python3
"""
run_feasibility.py
~~~~~~~~~~~~~~~~~~
Standalone Moz DA feasibility analysis for an existing market analysis JSON.

Runs independently of the main SERP audit — useful when you want to:
  - Check feasibility without burning SerpAPI quota
  - Re-run with an updated client_da
  - Inspect pivot suggestions for a past run

Usage
-----
::

    python run_feasibility.py --json market_analysis_estrangement_20260313.json
    python run_feasibility.py --json market_analysis_v2.json --out feasibility_report.md
    python run_feasibility.py --json market_analysis_v2.json --no-pivot-serp

Arguments
---------
--json          Path to market_analysis_*.json (required)
--out           Output markdown path (default: feasibility_{slug}_{timestamp}.md)
--client-da     Override client DA from config (optional)
--no-pivot-serp Skip secondary SERP fetch for pivot keywords (saves API quota)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependencies — degrade gracefully if missing
# ---------------------------------------------------------------------------

try:
    from dataforseo_client import DataForSEOClient
    DATAFORSEO_AVAILABLE = True
except ImportError:
    DATAFORSEO_AVAILABLE = False

try:
    from moz_client import MozClient
    MOZ_AVAILABLE = True
except ImportError:
    MOZ_AVAILABLE = False

try:
    from feasibility import compute_feasibility, generate_hyper_local_pivot
    FEASIBILITY_AVAILABLE = True
except ImportError:
    FEASIBILITY_AVAILABLE = False
    logger.error("feasibility.py not found — cannot proceed.")
    sys.exit(1)

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config(config_path: str = "config.yml") -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _fetch_pivot_local_pack(keyword: str, config: dict) -> list[dict]:
    """Fetch Maps/local pack results for a pivot keyword via SerpAPI.

    Returns a list of local result dicts, or empty list on failure.
    """
    if not REQUESTS_AVAILABLE:
        return []
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        return []
    serpapi_cfg = config.get("serpapi", {})
    params = {
        "api_key": serpapi_key,
        "engine": "google_maps",
        "q": keyword,
        "gl": serpapi_cfg.get("gl", "ca"),
        "hl": serpapi_cfg.get("hl", "en"),
        "location": serpapi_cfg.get("location", "Vancouver, British Columbia, Canada"),
        "type": "search",
    }
    try:
        resp = _requests.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("local_results", [])
    except Exception as exc:
        logger.warning("Pivot Maps fetch failed for '%s': %s", keyword, exc)
        return []


def _fetch_pivot_organic_urls(keyword: str, config: dict, max_urls: int = 10) -> list[str]:
    """Fetch organic results for a pivot keyword and return URLs."""
    if not REQUESTS_AVAILABLE:
        return []
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        return []
    serpapi_cfg = config.get("serpapi", {})
    params = {
        "api_key": serpapi_key,
        "engine": "google",
        "q": keyword,
        "gl": serpapi_cfg.get("gl", "ca"),
        "hl": serpapi_cfg.get("hl", "en"),
        "location": serpapi_cfg.get("location", "Vancouver, British Columbia, Canada"),
        "num": 10,
    }
    try:
        resp = _requests.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [r.get("link", "") for r in data.get("organic_results", [])[:max_urls] if r.get("link")]
    except Exception as exc:
        logger.warning("Pivot organic fetch failed for '%s': %s", keyword, exc)
        return []


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _get_organic_urls_by_keyword(data: dict, max_per_keyword: int = 10) -> dict[str, list[str]]:
    """Return top organic URLs keyed by keyword (primary queries only)."""
    by_kw: dict[str, list[str]] = {}
    for row in data.get("organic_results", []):
        if row.get("Query_Label") != "A":
            continue
        kw = row.get("Source_Keyword")
        url = row.get("Link") or row.get("URL") or ""
        rank = int(row.get("Rank") or 999)
        if not kw or not url:
            continue
        by_kw.setdefault(kw, [])
        by_kw[kw].append((rank, url))
    result = {}
    for kw, pairs in by_kw.items():
        pairs.sort(key=lambda x: x[0])
        result[kw] = [url for _, url in pairs[:max_per_keyword]]
    return result


def run_feasibility_analysis(
    data: dict,
    config: dict,
    client_da_override: int | None = None,
    do_pivot_serp: bool = True,
) -> list[dict]:
    """Run Moz DA lookup + feasibility scoring for all primary keywords.

    Returns a list of feasibility row dicts compatible with the format used by
    generate_insight_report.py Section 5b.
    """
    feasibility_cfg = config.get("feasibility", {})
    client_da = client_da_override or feasibility_cfg.get("client_da", 35)
    neighborhoods = feasibility_cfg.get("neighborhoods", ["Lonsdale"])
    location = feasibility_cfg.get("non_profit_location", "North Vancouver")
    client_domain = (config.get("analysis_report", {}).get("client_domain") or "").lower()

    cache_ttl = config.get("moz", {}).get("cache_ttl_days", 30)

    # DA client: prefer DataForSEO, fall back to Moz
    da_client = None
    da_source = "none"

    if DATAFORSEO_AVAILABLE and os.environ.get("DATAFORSEO_LOGIN") and os.environ.get("DATAFORSEO_PASSWORD"):
        try:
            da_client = DataForSEOClient(cache_ttl_days=cache_ttl)
            da_source = "dataforseo"
            logger.info("DA client: DataForSEO (cache TTL: %d days)", cache_ttl)
        except RuntimeError as exc:
            logger.warning("DataForSEO unavailable: %s", exc)

    if da_client is None and MOZ_AVAILABLE and os.environ.get("MOZ_TOKEN"):
        try:
            da_client = MozClient(cache_ttl_days=cache_ttl)
            da_source = "moz"
            logger.info("DA client: Moz (cache TTL: %d days)", cache_ttl)
        except RuntimeError as exc:
            logger.warning("Moz unavailable: %s", exc)

    if da_client is None:
        logger.warning(
            "No DA client available — set DATAFORSEO_LOGIN/PASSWORD or MOZ_TOKEN in .env. "
            "Keywords will be marked 'No DA Data'."
        )

    # Unified fetch method regardless of which client is active
    def _get_metrics(urls: list[str]) -> dict[str, dict]:
        if da_client is None:
            return {}
        if da_source == "dataforseo":
            return da_client.get_domain_metrics(urls)
        return da_client.get_moz_metrics(urls)  # Moz interface

    urls_by_kw = _get_organic_urls_by_keyword(data)
    all_urls = list({url for urls in urls_by_kw.values() for url in urls})

    da_metrics: dict[str, dict] = {}
    da_data_available = False
    if da_client and all_urls:
        logger.info("Fetching DA for %d unique URLs via %s...", len(all_urls), da_source)
        da_metrics = _get_metrics(all_urls)
        da_data_available = bool(da_metrics)
        logger.info("%s returned DA for %d URLs", da_source, len(da_metrics))
        if not da_data_available:
            logger.warning(
                "%s returned no data — keywords will be marked 'No DA Data'. "
                "Check credentials and account limits.", da_source
            )

    results: list[dict] = []
    pivot_jobs: list[dict] = []

    keywords = sorted(urls_by_kw.keys())
    logger.info("Scoring feasibility for %d keywords...", len(keywords))

    for kw in keywords:
        urls = urls_by_kw[kw]
        competitor_das = [
            da_metrics[url]["da"]
            for url in urls
            if url in da_metrics and _extract_domain(url) != client_domain
        ]

        if not da_data_available:
            # No Moz data — report without scores rather than falsely showing all as Low
            feas = {
                "avg_serp_da": None,
                "client_da": client_da,
                "gap": None,
                "feasibility_score": None,
                "feasibility_status": "No DA Data",
            }
            pivot = {"pivot_status": "Stay the course", "suggested_keyword": None,
                     "strategy": "Moz DA data unavailable — run again once MOZ_TOKEN is set.",
                     "all_variants": [f"{kw} {nb}" for nb in neighborhoods]}
        else:
            feas = compute_feasibility(client_da, competitor_das)
            pivot_input = {
                "status": feas["feasibility_status"],
                "avg_competitor_da": feas["avg_serp_da"],
            }
            pivot = generate_hyper_local_pivot(kw, location, pivot_input, neighborhoods)

        row: dict = {
            "Keyword": kw,
            "Query_Label": "A",
            "client_da": client_da,
            "avg_serp_da": feas["avg_serp_da"],
            "gap": feas["gap"],
            "feasibility_score": feas["feasibility_score"],
            "feasibility_status": feas["feasibility_status"],
            "pivot_status": pivot["pivot_status"],
            "suggested_keyword": pivot["suggested_keyword"],
            "strategy": pivot["strategy"],
            "all_variants": pivot["all_variants"],
            "Client_In_Local_Pack": None,
        }
        results.append(row)

        if pivot["pivot_status"] == "Pivoting to Hyper-Local" and pivot["suggested_keyword"]:
            pivot_jobs.append({
                "source_keyword": kw,
                "pivot_keyword": pivot["suggested_keyword"],
            })

    # Pivot SERP validation — direct SerpAPI Maps call (no serp_audit import needed)
    if do_pivot_serp and pivot_jobs and REQUESTS_AVAILABLE:
        serpapi_key = os.environ.get("SERPAPI_KEY", "")
        if serpapi_key:
            logger.info("Fetching pivot Maps SERPs for %d Low Feasibility keywords...", len(pivot_jobs))
            for job in pivot_jobs:
                pivot_kw = job["pivot_keyword"]
                source_kw = job["source_keyword"]
                logger.info("  Pivot Maps: '%s'", pivot_kw)

                local_rows = _fetch_pivot_local_pack(pivot_kw, config)
                in_pack = any(
                    client_domain and client_domain in str(r.get("website") or "").lower()
                    for r in local_rows
                )

                pivot_das = []
                if da_client:
                    pivot_urls = _fetch_pivot_organic_urls(pivot_kw, config)
                    if pivot_urls:
                        pivot_da_data = _get_metrics(pivot_urls)
                        pivot_das = [v["da"] for v in pivot_da_data.values()]

                pivot_feas = compute_feasibility(client_da, pivot_das)

                pivot_row: dict = {
                    "Keyword": pivot_kw,
                    "Query_Label": "P",
                    "Source_Keyword": source_kw,
                    "client_da": client_da,
                    "avg_serp_da": pivot_feas["avg_serp_da"],
                    "gap": pivot_feas["gap"],
                    "feasibility_score": pivot_feas["feasibility_score"],
                    "feasibility_status": pivot_feas["feasibility_status"],
                    "Client_In_Local_Pack": int(in_pack),
                    "pivot_status": None,
                    "suggested_keyword": None,
                    "strategy": None,
                    "all_variants": [],
                }
                results.append(pivot_row)
        else:
            logger.warning("SERPAPI_KEY not set — skipping pivot SERP validation.")

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

STATUS_ICONS = {
    "High Feasibility":     "✅ High",
    "Moderate Feasibility": "⚠️ Moderate",
    "Low Feasibility":      "🔴 Low",
    "No DA Data":           "❓ No DA Data",
}


def generate_feasibility_report(feasibility_rows: list[dict], config: dict, source_json: str) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    client_name = config.get("analysis_report", {}).get("client_name", "Client")
    client_da = (feasibility_rows[0].get("client_da") if feasibility_rows else
                 config.get("feasibility", {}).get("client_da", 35))

    lines.append("# Feasibility & Pivot Analysis")
    lines.append(f"**Client:** {client_name} | **Client DA:** {client_da} | **Generated:** {now}")
    lines.append(f"**Source:** `{os.path.basename(source_json)}`\n")

    primary = [r for r in feasibility_rows if r.get("Query_Label") != "P"]
    pivot_map = {
        r.get("Source_Keyword"): r
        for r in feasibility_rows if r.get("Query_Label") == "P"
    }

    moz_available = any(r.get("avg_serp_da") is not None for r in primary)
    if not moz_available:
        lines.append(
            "> **Note:** No Moz DA data was available. Set `MOZ_TOKEN` in your `.env` file "
            "to enable DA-based feasibility scoring.\n"
        )

    # Summary counts
    high = [r for r in primary if r.get("feasibility_status") == "High Feasibility"]
    mod  = [r for r in primary if r.get("feasibility_status") == "Moderate Feasibility"]
    low  = [r for r in primary if r.get("feasibility_status") == "Low Feasibility"]
    lines.append("## Summary")
    lines.append(f"- **Total keywords:** {len(primary)}")
    lines.append(f"- ✅ High Feasibility: {len(high)}")
    lines.append(f"- ⚠️ Moderate Feasibility: {len(mod)}")
    lines.append(f"- 🔴 Low Feasibility: {len(low)}")
    lines.append(f"- Pivot SERPs fetched: {len(pivot_map)}\n")

    # Main table
    lines.append("## Keyword Feasibility Table")
    lines.append(
        "Domain Authority gap analysis. "
        "Low Feasibility keywords include a hyper-local pivot suggestion "
        "where geographic relevance can substitute for domain strength.\n"
    )
    lines.append("| Keyword | Client DA | Avg Comp DA | Gap | Status | Recommended Pivot |")
    lines.append("|---------|-----------|-------------|-----|--------|-------------------|")

    for row in primary:
        kw = row.get("Keyword", "—")
        avg_da = row.get("avg_serp_da")
        gap = row.get("gap")
        status = STATUS_ICONS.get(row.get("feasibility_status", ""), row.get("feasibility_status", "—"))
        avg_da_str = f"{avg_da:.0f}" if avg_da is not None else "—"
        gap_str    = f"{gap:+.0f}" if gap is not None else "—"

        pivot_cell = "*(stay the course)*"
        if row.get("pivot_status") == "Pivoting to Hyper-Local":
            suggested = row.get("suggested_keyword", "")
            pivot_result = pivot_map.get(kw)
            if pivot_result:
                pack = pivot_result.get("Client_In_Local_Pack")
                pack_str = " ✓ in local pack" if pack else " ✗ not in local pack"
                p_icon = STATUS_ICONS.get(pivot_result.get("feasibility_status", ""),
                                          pivot_result.get("feasibility_status", ""))
                pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
            else:
                pivot_cell = f"**{suggested}**"

        lines.append(f"| {kw} | {client_da} | {avg_da_str} | {gap_str} | {status} | {pivot_cell} |")

    lines.append("")

    # Pivot strategy detail
    if low:
        lines.append("## Pivot Strategy\n")
        lines.append(
            "> **Why this works:** Geographic relevance is the equalizer for non-profits. "
            "A practitioner physically located in a neighbourhood can outrank a national "
            "directory for a user searching in that specific area, regardless of domain authority.\n"
        )
        for row in low:
            strategy = row.get("strategy", "")
            if strategy and strategy != "Current keyword is feasible. No pivot required.":
                kw = row.get("Keyword", "")
                lines.append(f"**{kw}:** {strategy}\n")

        # All neighbourhood variants
        lines.append("## All Neighbourhood Variants\n")
        for row in low:
            kw = row.get("Keyword", "")
            variants = row.get("all_variants", [])
            if variants:
                lines.append(f"**{kw}:**")
                for v in variants:
                    pivot_result = pivot_map.get(kw)
                    if pivot_result and pivot_result.get("Keyword") == v:
                        pack = pivot_result.get("Client_In_Local_Pack")
                        pack_str = " ✓ local pack" if pack else " ✗ local pack"
                        feas = STATUS_ICONS.get(pivot_result.get("feasibility_status", ""), "")
                        lines.append(f"- {v} — {feas}{pack_str}")
                    else:
                        lines.append(f"- {v}")
                lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output path helper
# ---------------------------------------------------------------------------

def _derive_output_path(json_path: str) -> str:
    """Derive a timestamped output path from the source JSON filename."""
    base = os.path.basename(json_path)
    slug = re.sub(r"^market_analysis_", "", base)
    slug = re.sub(r"(?:_\d{8}_\d{4})?\.json$", "", slug)
    slug = slug or "report"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"feasibility_{slug}_{timestamp}.md"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Load .env if present
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(
        description="Run Moz DA feasibility analysis on an existing market analysis JSON."
    )
    parser.add_argument("--json", required=True, help="Path to market_analysis_*.json")
    parser.add_argument("--out", default=None, help="Output markdown path (auto-generated if omitted)")
    parser.add_argument("--client-da", type=int, default=None, help="Override client DA from config")
    parser.add_argument(
        "--no-pivot-serp", action="store_true",
        help="Skip secondary SERP fetch for pivot keywords (saves SerpAPI quota)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.json):
        logger.error("JSON file not found: %s", args.json)
        sys.exit(1)

    config = _load_config()
    feasibility_cfg = config.get("feasibility", {})
    if not feasibility_cfg.get("enabled", True):
        logger.warning(
            "feasibility.enabled is false in config.yml — running anyway (standalone mode ignores this flag)."
        )

    logger.info("Loading market analysis: %s", args.json)
    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)

    do_pivot_serp = not args.no_pivot_serp and feasibility_cfg.get("pivot_serp_fetch", True)
    feasibility_rows = run_feasibility_analysis(
        data=data,
        config=config,
        client_da_override=args.client_da,
        do_pivot_serp=do_pivot_serp,
    )

    if not feasibility_rows:
        logger.warning("No feasibility data generated — check that organic_results are present in the JSON.")
        sys.exit(1)

    out_path = args.out or _derive_output_path(args.json)
    report = generate_feasibility_report(feasibility_rows, config, args.json)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    primary = [r for r in feasibility_rows if r.get("Query_Label") != "P"]
    low_count = sum(1 for r in primary if r.get("feasibility_status") == "Low Feasibility")
    mod_count = sum(1 for r in primary if r.get("feasibility_status") == "Moderate Feasibility")
    high_count = sum(1 for r in primary if r.get("feasibility_status") == "High Feasibility")
    logger.info(
        "Done. %d keywords scored — ✅ %d High / ⚠️ %d Moderate / 🔴 %d Low",
        len(primary), high_count, mod_count, low_count,
    )
    logger.info("Report written: %s", out_path)
    print(f"FEASIBILITY_OUT={out_path}")


if __name__ == "__main__":
    main()
