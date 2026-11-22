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

import process_config
import yaml

import brief_data_extraction
from domain_utils import normalize_domain
import feasibility as feasibility_module
import link_recovery
import timeouts
from play_rendering import format_play_cell

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Used only when config.yml names no serpapi.location. One definition, and the
# client's own city: the old fallback said Vancouver, which is a different
# market from North Vancouver and would be measured without a word of warning.
DEFAULT_LOCATION = "North Vancouver,British Columbia,Canada"
#: Fallback only; the editorial home is `config.yml serpapi.maps_zoom`.
DEFAULT_MAPS_ZOOM = 14

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
    _LOCAL_INTENT_VOCAB = _SERP_VOCAB
    SERVICE_GATE_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - defensive import guard
    SERVICE_LIKE_TOKENS = []
    _LOCAL_INTENT_VOCAB = None
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

def _load_config(config_path: str | None = None) -> dict:
    """The config, with the outbound retry policy applied to this process.

    Every entry point that makes outbound calls applies it, not just
    `serp_audit.py`: a `config.yml http_retry` block that changed one script's
    behaviour and silently did nothing in the other three is worse than no
    setting at all (P5 — a class of calls is configured together, review
    chunk Y4's cold review).
    """
    # No path named means the repo's own config.yml, not the cwd's: the
    # default was the bare `"config.yml"`, so starting the tool from
    # another directory found no config and reset every policy, the
    # configured database among them (the cold review of chunk Y12).
    config_path = process_config.config_path(config_path)
    if not os.path.exists(config_path):
        process_config.apply(None)
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    process_config.apply(config)
    return config


def _extract_domain(url: str) -> str:
    """Return the bare domain for *url*, with or without a scheme.

    One definition, in ``domain_utils`` (review chunk Y1).
    """
    try:
        return normalize_domain(url)
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
        "location": serpapi_cfg.get("location", DEFAULT_LOCATION),
        "type": "search",
        # REQUIRED by SerpAPI whenever `location` is set: without it every
        # Maps call answers 400 "Missing `z` or `m` parameter". The audit
        # passed it and this pass did not, so the pivot local-pack check had
        # never once succeeded — invisible until the gate fix of 2026-11-21
        # produced a pivot to check (one home: serpapi.maps_zoom).
        "z": str(serpapi_cfg.get("maps_zoom", DEFAULT_MAPS_ZOOM)),
    }
    try:
        resp = _requests.get("https://serpapi.com/search", params=params,
                             timeout=timeouts.serpapi_timeout(config))
        resp.raise_for_status()
        data = resp.json()
        return data.get("local_results", []), True
    except Exception as exc:
        logger.warning("Pivot Maps fetch failed for '%s': %s", keyword, _scrub_secrets(exc))
        return [], False


def _fetch_pivot_organic_urls(
    keyword: str, config: dict,
    max_urls: int = feasibility_module.TOP_N_FOR_FEASIBILITY,
) -> tuple[feasibility_module.URLWindow, bool]:
    """Fetch a pivot keyword's organic window and return ``(window, ok)``.

    ``ok`` is ``False`` when the fetch could not be performed or failed, so the
    caller can distinguish a measurement failure from a genuinely empty SERP
    (B.2). URLs in any raised exception are scrubbed of the API key (B.3).

    The window is sliced before the linkless positions are dropped, and the
    holes are counted, for the reason `feasibility.url_window` gives.
    """
    empty = feasibility_module.URLWindow([], 0, 0)
    if not REQUESTS_AVAILABLE:
        return empty, False
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        return empty, False
    serpapi_cfg = config.get("serpapi", {})
    params = {
        "api_key": serpapi_key,
        "engine": "google",
        "q": keyword,
        "gl": serpapi_cfg.get("gl", "ca"),
        "hl": serpapi_cfg.get("hl", "en"),
        "location": serpapi_cfg.get("location", DEFAULT_LOCATION),
        "num": 10,
    }
    try:
        resp = _requests.get("https://serpapi.com/search", params=params,
                             timeout=timeouts.serpapi_timeout(config))
        resp.raise_for_status()
        data = resp.json()
        # This fetch does not go through serp_audit's wrapper, so it has to
        # unwrap Google's redirect links itself (P5: the same fix on every
        # sibling call site).
        link_recovery.recover_response(data)
        window = data.get("organic_results", [])[:max_urls]
        urls = [r.get("link", "") for r in window if r.get("link")]
        return feasibility_module.URLWindow(
            urls=urls, unresolved=len(window) - len(urls),
            window=len(window)), True
    except Exception as exc:
        logger.warning("Pivot organic fetch failed for '%s': %s", keyword, _scrub_secrets(exc))
        return empty, False


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _get_organic_urls_by_keyword(
    data: dict,
    max_per_keyword: int = feasibility_module.TOP_N_FOR_FEASIBILITY,
) -> dict[str, feasibility_module.URLWindow]:
    """Return each keyword's top-N window (primary queries only).

    Slice first, then drop what cannot be scored, and count the holes — the
    same order as `feasibility.url_window`, for the reason its docstring
    gives. Filtering before slicing slid ranks 11, 12 ... into a set every
    output calls "the top 10", and published it as complete coverage
    (P9/P31).
    """
    by_kw: dict[str, list] = {}
    for row in data.get("organic_results", []):
        if row.get("Query_Label") != "A":
            continue
        kw = row.get("Source_Keyword")
        if not kw:
            continue
        by_kw.setdefault(kw, [])
        by_kw[kw].append((int(row.get("Rank") or 999),
                          row.get("Link") or row.get("URL") or ""))

    wrapped = 0
    result: dict[str, feasibility_module.URLWindow] = {}
    for kw, pairs in by_kw.items():
        pairs.sort(key=lambda x: x[0])
        window = pairs[:max_per_keyword]
        urls = []
        for _, url in window:
            # A run written before link recovery stored Google's redirect
            # wrapper. Its domain reads google.com, so it would be scored as
            # a competitor with Google's authority. It is a position that
            # cannot be measured, not a position with no authority (P2).
            if url and link_recovery.is_google_redirect(url):
                wrapped += 1
                continue
            # feasibility.usable_url, not a local emptiness test: an "N/A"
            # link passed the local test and was sent to the provider as a
            # target (one definition, review chunk D2).
            if feasibility_module.usable_url(url):
                urls.append(url)
        result[kw] = feasibility_module.URLWindow(
            urls=urls, unresolved=len(window) - len(urls),
            window=len(window))
    if wrapped:
        logger.warning(
            "%d organic row(s) in this run's output still hold a Google "
            "redirect wrapper instead of a destination URL and could not be "
            "scored; they are reported as unscored coverage. Re-run the audit "
            "to measure them.", wrapped)
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
    config_client_da = feasibility_cfg.get("client_da", 35)
    neighborhoods = feasibility_cfg.get("neighborhoods", ["Lonsdale"])
    location = feasibility_cfg.get("non_profit_location", "North Vancouver")
    pivotable_intents = feasibility_module.resolve_pivotable_intents(config)
    # The keyword's own words. Resolved once per run, beside the intents.
    local_intent_markers = feasibility_module.resolve_local_intent_markers(
        _LOCAL_INTENT_VOCAB)
    client_domain = (config.get("analysis_report", {}).get("client_domain") or "").lower()
    # D-M-19 / D4.10: the pivot gate reads the MEASURED SERP intent, and the
    # pivot explanation reads the SERP's own entity distribution. serp_audit
    # has written keyword_profiles by the time this pass runs.
    kw_profiles_for_pivot = data.get("keyword_profiles") or {}

    cache_ttl = config.get("moz", {}).get("cache_ttl_days", 30)
    # An absence is re-asked sooner than a measurement is refreshed (F6).
    negative_ttl = config.get("moz", {}).get("negative_cache_ttl_days", 7)

    # DA client: prefer DataForSEO, fall back to Moz
    da_client = None
    da_source = "none"

    if DATAFORSEO_AVAILABLE and os.environ.get("DATAFORSEO_LOGIN") and os.environ.get("DATAFORSEO_PASSWORD"):
        try:
            da_client = DataForSEOClient(
                cache_ttl_days=cache_ttl,
                negative_cache_ttl_days=negative_ttl)
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
            "Keywords will be marked 'Not Measured'."
        )

    # Unified fetch method regardless of which client is active
    def _get_metrics(urls: list[str]) -> dict[str, dict]:
        if da_client is None:
            return {}
        if da_source == "dataforseo":
            return da_client.get_domain_metrics(urls)
        return da_client.get_moz_metrics(urls)  # Moz interface

    urls_by_kw = _get_organic_urls_by_keyword(data)
    all_urls = list({url for w in urls_by_kw.values() for url in w.urls})

    # Entity type per ranking URL, read off the rows the audit already
    # classified (serp_audit classifies every domain, HTML-enriched or not).
    # It feeds the non-directory minimum (D6.1): a directory holding a slot is
    # not evidence a DA-35 clinic can hold one. A row with no Entity_Type, or
    # the classifier's own "N/A", stays unknown rather than being counted as a
    # competitor the client's size can displace.
    entity_by_url: dict[str, str] = {}
    for row in data.get("organic_results", []):
        url = row.get("Link") or row.get("URL") or ""
        etype = (row.get("Entity_Type") or "").strip()
        if url and etype and etype.upper() != "N/A":
            entity_by_url.setdefault(url, etype)

    # The client goes into the same batch as the competitors, so both sides of
    # the gap come off one provider's scale (D-M-05). One definition, shared
    # with serp_audit's in-pipeline pass.
    all_urls = feasibility_module.with_client_url(
        all_urls, f"https://{client_domain}" if client_domain else "")

    da_metrics: dict[str, dict] = {}
    if da_client and all_urls:
        logger.info("Fetching DA for %d unique URLs via %s...", len(all_urls), da_source)
        da_metrics = _get_metrics(all_urls)
        # len(da_metrics) is not the number of DA figures: since D2 a URL the
        # provider answered about but holds no rank for is present with
        # da: None. Logging the record count read as "DA for 3 URLs" when
        # none carried one, and `if not da_metrics` never fired on a batch
        # that measured nothing (P2/P6).
        cov = feasibility_module.batch_coverage(da_metrics, asked=all_urls)
        logger.info(
            "%s answered for %d of %d URLs; %d carry a DA figure, %d have no "
            "DA record", da_source, cov.records, cov.asked, cov.measured,
            cov.unmeasured,
        )
        if not cov.measured:
            logger.warning(
                "%s measured no DA at all — every keyword will read "
                "'Not Measured'. Check credentials and account limits.",
                da_source
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

    client_da, client_da_source = feasibility_module.resolve_client_da(
        client_domain,
        lambda d: (domain_to_da.get(d) or {}),
        da_source, config_client_da, client_da_override, logger.info,
        logger.warning)

    keywords = sorted(urls_by_kw.keys())
    _directory_types = feasibility_module.resolve_directory_entity_types(config)
    logger.info("Scoring feasibility for %d keywords...", len(keywords))

    for kw in keywords:
        kw_window = urls_by_kw[kw]
        # One definition of the input set, shared with the in-pipeline pass in
        # serp_audit (feasibility.competitor_da_window — finding D-C-19).
        # `urls` is already the top N by absolute Rank; the helper drops the
        # client's own domain from that window and omits URLs with no DA
        # record (None is not a DA of 0).
        da_window = feasibility_module.competitor_da_window(
            kw_window,
            lambda u: (domain_to_da.get(feasibility_module.domain_of(u)) or {}).get("da"),
            client_domain=client_domain,
            entity_for_url=entity_by_url.get,
        )

        # Gate: only service-intent keywords get a neighbourhood pivot/variants.
        # Informational keywords ("how does birth order affect personality West
        # Vancouver") get none — a geo variant is nonsense (B.1.c). Computed once
        # so BOTH the scored and unmeasured branches honour it.
        kw_service_like = _is_service_like(kw, SERVICE_LIKE_TOKENS, location) \
            if SERVICE_GATE_AVAILABLE else True
        # D4.10: both branches ask the same question, and it is the measured
        # verdict's to answer. The unmeasured branch below built neighbourhood
        # variants from the keyword-string guess alone while the scored branch
        # went through the gate, so one keyword could be "informational, no
        # variants" with a verdict and carry variants without one.
        _pivot_profile = kw_profiles_for_pivot.get(kw) or {}
        kw_pivotable, kw_gate_source = feasibility_module._pivot_gate(
            _pivot_profile.get("serp_intent"), kw_service_like,
            pivotable_intents, keyword=kw,
            local_intent_markers=local_intent_markers)
        _pivot_base, _stripped_marker = feasibility_module.pivot_base_keyword(
            kw, local_intent_markers)

        # Availability is decided per keyword, not per run. `bool(da_metrics)`
        # made one measured keyword score every unmeasured one, and one
        # unmeasured provider response blank the keywords that did have
        # records (D-C-03). compute_feasibility reports the coverage either
        # way, so there is no second "no data" shape to keep in step.
        feas = compute_feasibility(client_da, da_window,
                                   directory_types=_directory_types)
        if feas["feasibility_status"] == feasibility_module.NOT_MEASURED:
            # No verdict for this keyword: no pivot recommendation and no paid
            # Maps fetch to support one. Gating on `gap is None` instead let a
            # thin window through — it has a real gap — and
            # generate_hyper_local_pivot then answered a "Not Measured" status
            # with "Current keyword is feasible. No pivot required.", a verdict
            # in the opposite direction from the data (P14/P6).
            pivot = {
                "pivot_status": "Stay the course",
                "suggested_keyword": None,
                # Its own field, not `strategy`: `strategy` means "what to do
                # about a Low-Feasibility keyword" and is rendered only in
                # that block, which is how the reason came to be written and
                # never shown (finding F3). This field is rendered by both
                # report writers and passed to the brief (F8).
                "no_measurement_reason":
                    feasibility_module.no_measurement_text(da_source, da_window),
                "strategy": "",
                # Built on the keyword without its trailing local marker,
                # the same base the scored branch uses — the neighbourhood
                # replaces "near me" rather than sitting beside it.
                "all_variants": [f"{_pivot_base} {nb}" for nb in neighborhoods]
                                if kw_pivotable else [],
                "pivot_base_keyword": _pivot_base,
                "stripped_local_marker": _stripped_marker,
                # The unmeasured branch builds its own dict, so it has to
                # carry the provenance too — the key was present on some
                # pivot dicts and absent on others (D4b cold review, finding 5).
                "gate_source": kw_gate_source,
            }
        else:
            pivot_input = {
                "status": feas["feasibility_status"],
                "avg_competitor_da": feas["avg_serp_da"],
            }
            pivot = generate_hyper_local_pivot(
                kw, location, pivot_input, neighborhoods,
                is_service_like=kw_service_like,
                serp_intent=_pivot_profile.get("serp_intent"),
                entity_distribution=_pivot_profile.get("entity_distribution"),
                pivotable_intents=pivotable_intents,
                local_intent_markers=local_intent_markers,
            )

        row: dict = {
            "Keyword": kw,
            "Query_Label": "A",
            "client_da": client_da,
            "avg_serp_da": feas["avg_serp_da"],
            "gap": feas["gap"],
            "feasibility_score": feas["feasibility_score"],
            "feasibility_status": feas["feasibility_status"],
            "da_count": feas["da_count"],
            "da_missing": feas["da_missing"],
            # The minima travel with the mean. Re-listing the assessment's
            # fields here is what dropped them in the first place: the mean
            # over a top-10 does not say whether anything this client's size
            # holds a slot, and a measured minimum rendered as "—" reads as
            # "no competitor was scored" (D6 cold review, finding 2).
            **{k: feas.get(k) for k in feasibility_module.MINIMA_FIELDS},
            "da_provider": da_source,
            "client_da_source": client_da_source,
            "pivot_status": pivot["pivot_status"],
            "suggested_keyword": pivot["suggested_keyword"],
            "strategy": pivot["strategy"],
            # Empty for every measured keyword; the sentence for the rest.
            "no_measurement_reason": pivot.get("no_measurement_reason", ""),
            "all_variants": pivot["all_variants"],
            # Which basis decided the pivot: the measured SERP verdict, its
            # mixed components, or the keyword-string guess. Computed and then
            # discarded (D4b cold review, finding 5).
            "pivot_gate_source": pivot.get("gate_source", ""),
            "Client_In_Local_Pack": None,
        }
        results.append(row)

        # `gap is not None` is the gate: a pivot job is a paid Maps fetch and
        # a published recommendation, and both rest on a measured gap.
        if (feas["gap"] is not None
                and pivot["pivot_status"] == "Pivoting to Hyper-Local"
                and pivot["suggested_keyword"]):
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

                pivot_das = feasibility_module.DAWindow([], 0, 0, 0)
                organic_ok = True
                if da_client:
                    pivot_urls, organic_ok = _fetch_pivot_organic_urls(pivot_kw, config)
                    if pivot_urls.urls:
                        pivot_da_data = _get_metrics(pivot_urls.urls)
                        # The same definition as the primary pass: rank-ordered
                        # top N, client's own domain dropped, URLs with no DA
                        # omitted rather than carried as None. Taking every
                        # value averaged the client in as its own competitor
                        # and could put a None into the mean (D-C-19, P5).
                        pivot_das = feasibility_module.competitor_da_window(
                            pivot_urls,
                            lambda u: (pivot_da_data.get(u)
                                       or pivot_da_data.get(
                                           feasibility_module.domain_of(u))
                                       or {}).get("da"),
                            client_domain=client_domain,
                        )

                # If the validation SERP fetch failed we cannot score the pivot;
                # do not present the failure as a real "Low Feasibility" verdict.
                if not organic_ok:
                    pivot_feas = {
                        "avg_serp_da": None, "client_da": client_da, "gap": None,
                        "feasibility_score": None,
                        "feasibility_status": feasibility_module.NOT_MEASURED,
                        "da_count": 0, "da_missing": 0,
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
                    "da_count": pivot_feas["da_count"],
                    "da_missing": pivot_feas["da_missing"],
                    **{k: pivot_feas.get(k)
                       for k in feasibility_module.MINIMA_FIELDS},
                    "da_provider": da_source,
                    "client_da_source": client_da_source,
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

# Status labels and icons are editorial and live in
# feasibility_messages.yml (feasibility.status_label). Four Python copies of
# this map are how one unmeasured state came to carry two different labels in
# different outputs; there is now one label per status (review chunk D2a).


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

    # Summary counts. "Not Measured" is counted with the rest: leaving it out
    # made the four totals disagree with the keyword count, so a run that
    # scored 3 of 10 keywords read as a run with 3 keywords (D2a.5/D2a.6, P2).
    high = [r for r in primary if r.get("feasibility_status") == "High Feasibility"]
    mod  = [r for r in primary if r.get("feasibility_status") == "Moderate Feasibility"]
    low  = [r for r in primary if r.get("feasibility_status") == "Low Feasibility"]
    unmeasured = [r for r in primary
                  if r.get("feasibility_status") == feasibility_module.NOT_MEASURED]

    if unmeasured:
        # Per keyword, not per run: one scored keyword used to silence this
        # note for the other nine.
        lines.append(
            f"> **Note:** {len(unmeasured)} of {len(primary)} keyword(s) have "
            f"no feasibility verdict — not enough ranking domains carried a "
            f"Domain Authority record. Set `DATAFORSEO_LOGIN`/"
            f"`DATAFORSEO_PASSWORD` (primary) or `MOZ_TOKEN` (fallback) in "
            f"`.env`, or read the per-keyword reason under "
            f"**Not measured — why** below.\n"
        )

    lines.append("## Summary")
    lines.append(f"- **Total keywords:** {len(primary)}")
    # Both the glyph and the words come from `feasibility_messages.yml`, not
    # from literals here: this summary printed ⚠️ for "Not measured" while
    # the configured icon is ❓, so the same state wore two glyphs in two
    # outputs of one run — the drift the config file exists to stop. The words
    # were a literal with a special case for one status until the cold review
    # of chunk Y1; the file is the only home for them.
    for status, count in (("High Feasibility", len(high)),
                          ("Moderate Feasibility", len(mod)),
                          ("Low Feasibility", len(low)),
                          ("Not Measured", len(unmeasured))):
        lines.append(
            f"- {feasibility_module.status_label(status)}: {count}".strip())
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
    lines.append("| Keyword | Client DA | Avg Comp DA | DA Coverage | Gap | Status | Recommended Play | Recommended Pivot |")
    lines.append("|---------|-----------|-------------|-------------|-----|--------|------------------|-------------------|")

    for row in primary:
        kw = row.get("Keyword", "—")
        avg_da = row.get("avg_serp_da")
        gap = row.get("gap")
        status = feasibility_module.status_label(row.get("feasibility_status", "")) or "—"
        avg_da_str = f"{avg_da:.0f}" if avg_da is not None else "—"
        gap_str    = f"{gap:+.0f}" if gap is not None else "—"
        # The denominator travels with the mean (D2a.9, P2): 85 over 3 of 10
        # domains and 85 over all 10 are not the same finding.
        coverage_str = feasibility_module.coverage_phrase(
            row.get("da_count"), row.get("da_missing"), short=True)
        client_da_str = feasibility_module.client_da_cell(
            row.get("client_da", client_da), row.get("client_da_source", ""))

        # RP-C.1 — Recommended Play from the pre-computed verdict. This is the new
        # home for non-service guidance (chip B stops emitting pivots for those,
        # leaving the Pivot cell blank). Honest "—" / "inputs missing" when absent.
        play_obj = (keyword_profiles.get(kw) or {}).get("recommended_play")
        play_cell = format_play_cell(play_obj)

        pivot_cell = "*(stay the course)*"
        if feasibility_module.is_no_pivot(row.get("pivot_status")):
            # SEAM (chip C): the extraction-play recommendation renders here.
            refused = str(row["pivot_status"]).split("— ", 1)[-1]
            pivot_cell = f"*({refused} — extraction play)*"
        elif row.get("pivot_status") == "Pivoting to Hyper-Local":
            suggested = row.get("suggested_keyword", "")
            pivot_result = pivot_map.get(kw)
            if pivot_result:
                pack_str = _local_pack_phrase(pivot_result.get("Client_In_Local_Pack"))
                p_icon = feasibility_module.status_label(
                    pivot_result.get("feasibility_status", ""))
                pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
            else:
                pivot_cell = f"**{suggested}**"

        lines.append(f"| {kw} | {client_da_str} | {avg_da_str} | {coverage_str} "
                     f"| {gap_str} | {status} | {play_cell} | {pivot_cell} |")

    lines.append("")

    # Why each unmeasured keyword has no verdict. `no_measurement_text` wrote
    # this onto the row and nothing rendered it: the only consumer of
    # `strategy` was the Low Feasibility block, which a "Not Measured" row
    # never enters (P21/P25, finding F3).
    if unmeasured:
        lines.append("## Not measured — why\n")
        for row in unmeasured:
            reason = (row.get("no_measurement_reason") or "").strip()
            coverage = feasibility_module.coverage_phrase(
                row.get("da_count"), row.get("da_missing"))
            lines.append(f"- **{row.get('Keyword', '')}** — "
                         f"{reason or coverage}"
                         + (f" ({coverage})" if reason else ""))
        lines.append("")

    # A geographic pivot only applies to service-intent keywords. Informational
    # Low-Feasibility keywords are handled separately (B.1.c) — no geo pivot.
    pivoting = [r for r in low if r.get("pivot_status") == "Pivoting to Hyper-Local"]
    informational = [r for r in low
                     if feasibility_module.is_no_pivot(r.get("pivot_status"))]

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
                        feas = feasibility_module.status_label(pivot_result.get("feasibility_status", ""))
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
    def _icon(status):
        return feasibility_module.status_label(status, bare_icon=True)

    logger.info(
        "Done. %d keywords scored — %s %d High / %s %d Moderate / %s %d Low",
        len(primary),
        _icon("High Feasibility"), high_count,
        _icon("Moderate Feasibility"), mod_count,
        _icon("Low Feasibility"), low_count,
    )
    logger.info("Report written: %s", out_path)
    print(f"FEASIBILITY_OUT={out_path}")


if __name__ == "__main__":
    main()
