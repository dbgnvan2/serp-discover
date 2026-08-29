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

import brief_data_extraction
from play_rendering import format_play_cell

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
    from moz_client import MozClient, credentials_present
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

# Service-intent gate for pivots — reuse the shared predicate + editorial
# token list (serp_vocab.yml), never hardcode a parallel list (B.1.c).
try:
    from query_variants import is_service_like as _is_service_like
    from pattern_matching import SERP_VOCAB as _SERP_VOCAB
    SERVICE_LIKE_TOKENS = _SERP_VOCAB.get("service_like_tokens", [])
    SERVICE_GATE_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - defensive import guard
    SERVICE_LIKE_TOKENS = []
    SERVICE_GATE_AVAILABLE = False
    logger.warning("Service-intent gate unavailable (%s) — pivots ungated.", _exc)

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
    """Return the bare domain for *url*, with or without a scheme.

    ``urlparse`` puts everything in ``path`` when there is no ``//``, so a
    scheme-less key such as ``"example.com/page"`` (the format the Moz cache
    writes) would otherwise yield an empty domain.
    """
    try:
        parsed = urlparse(url if "//" in url else "//" + url)
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return ""


# Every credential whose literal value must be scrubbed from a log line.
# Hardening one provider's redaction and not its siblings is the P5 failure
# mode: MOZ_TOKEN was absent here while Moz exceptions were being logged.
_SECRET_ENV_VARS = (
    "SERPAPI_KEY",
    "MOZ_TOKEN",
    "ANTHROPIC_API_KEY",
    "DATAFORSEO_PASSWORD",
    "GEMINI_API_KEY",
)

# Credential query-param names that must never reach a log line.
_CREDENTIAL_PARAM_RE = re.compile(
    r"(?i)\b(api_key|apikey|key|token|secret|password|passwd|login)=([^&\s]+)"
)


def _scrub_secrets(text: object) -> str:
    """Redact secrets from a string before logging it.

    ``requests`` exceptions carry the full request URL — including
    ``api_key=<SERPAPI_KEY>`` — so logging ``str(exc)`` naively leaks the key
    (security standard + learnings P5). Redact both the concrete SERPAPI_KEY
    value (wherever it appears) and any credential query param by name.

    Spec: seo_geo_review_20260704.md (chip B, B.3).
    """
    s = str(text)
    for var in _SECRET_ENV_VARS:
        value = os.environ.get(var, "")
        if value:
            s = s.replace(value, "REDACTED")
    s = _CREDENTIAL_PARAM_RE.sub(r"\1=REDACTED", s)
    return s


def _fetch_pivot_local_pack(keyword: str, config: dict) -> tuple[list[dict], bool]:
    """Fetch Maps/local pack results for a pivot keyword via SerpAPI.

    Returns ``(local_results, ok)`` where ``ok`` is ``False`` when the fetch
    could not be performed (missing deps/key) or failed. A failed fetch must
    NOT be conflated with a genuine empty pack: the caller records
    "could not measure", never a false "not in local pack" (B.2, P1/P2/P14).
    """
    if not REQUESTS_AVAILABLE:
        return [], False
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        return [], False
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
        return data.get("local_results", []), True
    except Exception as exc:
        logger.warning("Pivot Maps fetch failed for '%s': %s", keyword, _scrub_secrets(exc))
        return [], False


def _fetch_pivot_organic_urls(
    keyword: str, config: dict, max_urls: int = 10
) -> tuple[list[str], bool]:
    """Fetch organic results for a pivot keyword and return ``(urls, ok)``.

    ``ok`` is ``False`` when the fetch could not be performed or failed, so the
    caller can distinguish a measurement failure from a genuinely empty SERP
    (B.2). URLs in any raised exception are scrubbed of the API key (B.3).
    """
    if not REQUESTS_AVAILABLE:
        return [], False
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        return [], False
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
        return [r.get("link", "") for r in data.get("organic_results", [])[:max_urls] if r.get("link")], True
    except Exception as exc:
        logger.warning("Pivot organic fetch failed for '%s': %s", keyword, _scrub_secrets(exc))
        return [], False


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

    if da_client is None and MOZ_AVAILABLE and credentials_present():
        try:
            da_client = MozClient.from_config(config)
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

    # Build a domain-to-DA map for lookup. Both DA providers key their results
    # by URL, so the domain has to be parsed out — `split('/')[0]` yielded
    # "https:" for every DataForSEO key (it keys by the caller's input URL,
    # scheme included), collapsing the whole map onto one bogus entry and
    # leaving `avg_serp_da` None on every keyword. `lstrip('www.')` was a
    # second defect: it strips *characters*, so "worldbank.org" became
    # "orldbank.org". `_extract_domain` handles both key formats correctly.
    domain_to_da: dict[str, dict] = {}
    for cached_url, metrics in da_metrics.items():
        domain_part = _extract_domain(cached_url)
        if domain_part and domain_part not in domain_to_da:
            domain_to_da[domain_part] = metrics

    keywords = sorted(urls_by_kw.keys())
    logger.info("Scoring feasibility for %d keywords...", len(keywords))

    for kw in keywords:
        urls = urls_by_kw[kw]
        competitor_das = [
            domain_to_da[_extract_domain(url)]["da"]
            for url in urls
            if _extract_domain(url) in domain_to_da and _extract_domain(url) != client_domain
        ]

        # Gate: only service-intent keywords get a neighbourhood pivot/variants.
        # Informational keywords ("how does birth order affect personality West
        # Vancouver") get none — a geo variant is nonsense (B.1.c). Computed once
        # so BOTH the scored and No-DA branches honour it.
        kw_service_like = _is_service_like(kw, SERVICE_LIKE_TOKENS, location) \
            if SERVICE_GATE_AVAILABLE else True

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
                     "all_variants": [f"{kw} {nb}" for nb in neighborhoods] if kw_service_like else []}
        else:
            feas = compute_feasibility(client_da, competitor_das)
            pivot_input = {
                "status": feas["feasibility_status"],
                "avg_competitor_da": feas["avg_serp_da"],
            }
            pivot = generate_hyper_local_pivot(
                kw, location, pivot_input, neighborhoods,
                is_service_like=kw_service_like,
            )

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

                local_rows, local_ok = _fetch_pivot_local_pack(pivot_kw, config)
                if local_ok:
                    in_pack = any(
                        client_domain and client_domain in str(r.get("website") or "").lower()
                        for r in local_rows
                    )
                    # A real measurement: 1 = in pack, 0 = measured-absent.
                    client_in_local_pack = int(in_pack)
                else:
                    # Fetch failed — record "could not measure", never a false 0
                    # that renders as "✗ not in local pack" (B.2, P1/P2/P14).
                    client_in_local_pack = None

                pivot_das = []
                organic_ok = True
                if da_client:
                    pivot_urls, organic_ok = _fetch_pivot_organic_urls(pivot_kw, config)
                    if pivot_urls:
                        pivot_da_data = _get_metrics(pivot_urls)
                        pivot_das = [v["da"] for v in pivot_da_data.values()]

                # If the validation SERP fetch failed we cannot score the pivot;
                # do not present the failure as a real "Low Feasibility" verdict.
                if not organic_ok:
                    pivot_feas = {
                        "avg_serp_da": None, "client_da": client_da, "gap": None,
                        "feasibility_score": None, "feasibility_status": "Not Measured",
                    }
                else:
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
                    "Client_In_Local_Pack": client_in_local_pack,
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
    "Not Measured":         "⚠️ Not measured",
}


def _local_pack_phrase(pack: object) -> str:
    """Render the local-pack signal honestly (B.2).

    ``None`` = the validation fetch failed (could not measure) — never shown as
    a real "not in local pack". ``0`` = measured and genuinely absent. Truthy =
    measured and present.
    """
    if pack is None:
        return " — local pack not measured (validation fetch failed)"
    if pack:
        return " ✓ in local pack"
    return " ✗ not in local pack"


def generate_feasibility_report(
    feasibility_rows: list[dict],
    config: dict,
    source_json: str,
    keyword_profiles: dict | None = None,
) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # RP-C.1 — the Recommended Play column joins on keyword_profiles[kw].recommended_play.
    # When not passed in (standalone/test), read it from the source JSON so the
    # function stays self-sufficient. Spec: seo_geo_review_20260704.md (T.4).
    if keyword_profiles is None:
        try:
            with open(source_json, "r", encoding="utf-8") as _f:
                keyword_profiles = (json.load(_f) or {}).get("keyword_profiles", {}) or {}
        except Exception:
            keyword_profiles = {}
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
        "Domain Authority gap analysis. The **Recommended Play** column carries the "
        "pre-computed verdict under the two-score, rank-vs-citation model (a rank_play "
        "keyword is a ranking target; an extraction_play keyword is an AI-Overview "
        "citation target). Service keywords whose ranking is out of reach still show a "
        "hyper-local **Recommended Pivot**; a `—` play cell means no verdict was computed.\n"
    )
    lines.append("| Keyword | Client DA | Avg Comp DA | Gap | Status | Recommended Play | Recommended Pivot |")
    lines.append("|---------|-----------|-------------|-----|--------|------------------|-------------------|")

    for row in primary:
        kw = row.get("Keyword", "—")
        avg_da = row.get("avg_serp_da")
        gap = row.get("gap")
        status = STATUS_ICONS.get(row.get("feasibility_status", ""), row.get("feasibility_status", "—"))
        avg_da_str = f"{avg_da:.0f}" if avg_da is not None else "—"
        gap_str    = f"{gap:+.0f}" if gap is not None else "—"

        # RP-C.1 — Recommended Play from the pre-computed verdict. This is the new
        # home for non-service guidance (chip B stops emitting pivots for those,
        # leaving the Pivot cell blank). Honest "—" / "inputs missing" when absent.
        play_obj = (keyword_profiles.get(kw) or {}).get("recommended_play")
        play_cell = format_play_cell(play_obj)

        pivot_cell = "*(stay the course)*"
        if row.get("pivot_status") == "No pivot — informational":
            # SEAM (chip C): the extraction-play recommendation renders here.
            pivot_cell = "*(informational — extraction play)*"
        elif row.get("pivot_status") == "Pivoting to Hyper-Local":
            suggested = row.get("suggested_keyword", "")
            pivot_result = pivot_map.get(kw)
            if pivot_result:
                pack_str = _local_pack_phrase(pivot_result.get("Client_In_Local_Pack"))
                p_icon = STATUS_ICONS.get(pivot_result.get("feasibility_status", ""),
                                          pivot_result.get("feasibility_status", ""))
                pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
            else:
                pivot_cell = f"**{suggested}**"

        lines.append(f"| {kw} | {client_da} | {avg_da_str} | {gap_str} | {status} | {play_cell} | {pivot_cell} |")

    lines.append("")

    # A geographic pivot only applies to service-intent keywords. Informational
    # Low-Feasibility keywords are handled separately (B.1.c) — no geo pivot.
    pivoting = [r for r in low if r.get("pivot_status") == "Pivoting to Hyper-Local"]
    informational = [r for r in low if r.get("pivot_status") == "No pivot — informational"]

    # Pivot strategy detail
    if pivoting:
        lines.append("## Pivot Strategy\n")
        lines.append(
            "> **Why this works:** Geographic relevance is the equalizer for non-profits. "
            "A practitioner physically located in a neighbourhood can outrank a national "
            "directory for a user searching in that specific area, regardless of domain authority.\n"
        )
        for row in pivoting:
            strategy = row.get("strategy", "")
            if strategy and strategy != "Current keyword is feasible. No pivot required.":
                kw = row.get("Keyword", "")
                lines.append(f"**{kw}:** {strategy}\n")

        # All neighbourhood variants
        lines.append("## All Neighbourhood Variants\n")
        for row in pivoting:
            kw = row.get("Keyword", "")
            variants = row.get("all_variants", [])
            if variants:
                lines.append(f"**{kw}:**")
                for v in variants:
                    pivot_result = pivot_map.get(kw)
                    if pivot_result and pivot_result.get("Keyword") == v:
                        pack_str = _local_pack_phrase(pivot_result.get("Client_In_Local_Pack"))
                        feas = STATUS_ICONS.get(pivot_result.get("feasibility_status", ""), "")
                        lines.append(f"- {v} — {feas}{pack_str}")
                    else:
                        lines.append(f"- {v}")
                lines.append("")

    # Informational Low-Feasibility keywords — no geographic pivot applies.
    if informational:
        lines.append("## Informational Keywords (no geo pivot)\n")
        lines.append(
            "> These keywords are informational, not service queries — a "
            "neighbourhood variant is nonsense (nobody searches an informational "
            "question with a neighbourhood). The play here is content "
            "**extractability**, not geography.\n"
        )
        for row in informational:
            kw = row.get("Keyword", "")
            # SEAM (chip C): the extraction-play recommendation attaches here.
            lines.append(f"- **{kw}** — extraction play (see brief)")
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

    # Write feasibility data back onto the in-memory data BEFORE anything reads
    # it, and re-route the plays BEFORE the report is rendered. Ordering is the
    # whole point of this fix: the feasibility report prints "Recommended Play"
    # and DA-derived "Status" in the same table row, so rendering it with
    # pre-DA plays reproduces the exact contradiction CD.8 exists to remove, on
    # the one page that shows both side by side.
    data["keyword_feasibility"] = feasibility_rows

    # CD.8 — re-route the plays now that Domain Authority actually exists.
    # serp_audit.py builds keyword_profiles (recommended_play included) while
    # writing the audit JSON. When feasibility is computed here instead — a
    # separate pass, after that write — every play was routed against empty
    # feasibility and never revisited, so the JSON ended up holding real DA data
    # alongside verdicts that had never seen it. That is not a confidence
    # nuance: on the 2026-08-26 run it flipped both keywords from
    # extraction_play ("ranking is unlikely, high DA gap") to rank_play, while
    # the feasibility table on the same page read High Feasibility, gap -14.
    try:
        profiles = data.get("keyword_profiles") or {}
        if profiles:
            changed = brief_data_extraction.attach_recommended_plays(
                profiles, feasibility_rows)
            data["keyword_profiles"] = profiles
            if changed:
                logger.info(
                    "Re-routed recommended_play for %d of %d keyword(s) now that "
                    "Domain Authority data is available.", changed, len(profiles))
            else:
                logger.info(
                    "Recommended plays unchanged after adding Domain Authority "
                    "data (%d keyword(s) checked).", len(profiles))
        else:
            logger.warning(
                "No keyword_profiles in %s — recommended plays not re-routed. "
                "The report's play verdicts will not reflect this DA data.",
                args.json)
    except Exception as exc:
        # Never lose the feasibility write over a routing failure: the DA data is
        # the point of this run. Say so loudly rather than leaving stale plays
        # looking freshly computed.
        logger.error(
            "Could not re-route recommended plays after computing feasibility "
            "(%s). The feasibility data below IS written; the play verdicts in "
            "the report remain those computed without it.", exc)

    out_path = args.out or _derive_output_path(args.json)
    report = generate_feasibility_report(
        feasibility_rows, config, args.json,
        keyword_profiles=data.get("keyword_profiles", {}),
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

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
