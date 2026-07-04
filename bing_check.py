"""bing_check.py — secondary index check: Bing.

Spec: seo_geo_deferred_spec_v1.md#G.5. ChatGPT search grounds
substantially on Bing, so a Google-only view can miss an entire AI
referral surface. When enabled (config.yml bing_check.enabled — default
OFF, decision gate D-4), the pipeline makes ONE SerpAPI ``engine=bing``
call per root keyword (same query text as the label-"A" Google query, no
pagination, no enrichment, no classification) and records whether the
client is visible and at what rank. This is a visibility check, not a
second market analysis.

serp_audit.py binds ``run_bing_checks`` to its config globals and the
standard retry wrapper (``_fetch_serp_api``); results land in the
analysis JSON's ``bing_visibility`` list and are summarised per keyword
by ``brief_data_extraction._build_bing_visibility``.
"""
import json
import os
import re
import time
from datetime import datetime

from brief_data_extraction import _domain_from_link, _is_client_domain


def parse_bing_visibility(results, client_domain):
    """Parse a SerpAPI Bing response into a visibility record (G.5.2).

    Reads ``organic_results`` (position/link/title shape, verified
    against tests/fixtures/bing_serp_sample.json). Returns::

        {"checked": True, "client_rank": int|None, "client_url": str|None,
         "top3_domains": [str, ...]}

    ``client_rank`` is None when the client's domain does not appear —
    with ``checked`` still True: an absence that was actually measured.
    """
    client_lower = (client_domain or "").lower()
    organic = (results or {}).get("organic_results") or []

    positioned = []
    client_rank = None
    client_url = None
    for item in organic:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        domain = _domain_from_link(link)
        try:
            position = int(item.get("position"))
        except (TypeError, ValueError):
            position = None
        if position is not None and domain:
            positioned.append((position, domain))
        if client_rank is None and _is_client_domain(domain, client_lower):
            client_rank = position
            client_url = link

    top3_domains = []
    for _position, domain in sorted(positioned):
        if domain not in top3_domains:
            top3_domains.append(domain)
        if len(top3_domains) == 3:
            break

    return {
        "checked": True,
        "client_rank": client_rank,
        "client_url": client_url,
        "top3_domains": top3_domains,
    }


def _save_raw_bing(run_id, keyword, results):
    """Store the raw Bing response under raw/{run_id}/bing_{kw}.json."""
    slug = re.sub(r"[^a-z0-9]+", "_", (keyword or "").lower()).strip("_") or "keyword"
    output_dir = f"raw/{run_id}"
    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/bing_{slug}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def run_bing_checks(root_keywords, run_id, *, enabled, num, location,
                    force_local, fetch_fn, apply_no_cache, api_key,
                    client_domain, request_delay=0.0):
    """Run the Bing visibility pass; returns per-keyword rows.

    Zero SerpAPI calls when ``enabled`` is false (G.5.1). When enabled:
    exactly one ``engine=bing`` call per root keyword (G.5.3), routed
    through ``fetch_fn`` — serp_audit's standard retry wrapper. The query
    text mirrors the label-"A" Google query (forced-local suffix
    included) so Google and Bing ranks are comparable.

    Row shape (analysis JSON ``bing_visibility`` list): Run_ID,
    Created_At, Source_Keyword, Query_Label ("A" — the root query text),
    Executed_Query, Checked, Client_Rank, Client_URL, Top3_Domains,
    Num_Requested. A failed fetch yields Checked=False, never a guess.
    Spec: seo_geo_deferred_spec_v1.md#G.5.
    """
    if not enabled:
        print("Bing check: disabled (0 SerpAPI calls)")
        return []

    city_lower = (location or "").split(",")[0].strip().lower()
    rows = []
    calls_made = 0
    for keyword in root_keywords:
        if force_local and city_lower and city_lower not in keyword.lower():
            query_term = f"{keyword} {location}"
        else:
            query_term = keyword

        params = apply_no_cache({
            "engine": "bing",
            "q": query_term,
            "location": location,
            "count": num,
            "api_key": api_key,
        })
        print(f"  [Bing check] '{query_term}'")
        results = fetch_fn(params)
        calls_made += 1

        if results:
            _save_raw_bing(run_id, keyword, results)
            parsed = parse_bing_visibility(results, client_domain)
        else:
            parsed = {"checked": False, "client_rank": None,
                      "client_url": None, "top3_domains": []}

        rows.append({
            "Run_ID": run_id,
            "Created_At": datetime.now().isoformat(),
            "Source_Keyword": keyword,
            "Query_Label": "A",
            "Executed_Query": query_term,
            "Checked": parsed["checked"],
            "Client_Rank": parsed["client_rank"],
            "Client_URL": parsed["client_url"],
            "Top3_Domains": parsed["top3_domains"],
            "Num_Requested": num,
        })
        time.sleep(request_delay)

    print(f"Bing check: {calls_made} SerpAPI calls ({len(root_keywords)} root keywords)")
    return rows
