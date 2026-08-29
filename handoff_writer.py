"""handoff_writer.py — Competitor handoff JSON generation and schema validation.

Spec: serp_tool1_improvements_spec.md#I.6, moz_api_upgrade_spec_v1.md#T.4

Cross-tool contract
-------------------
serp-compete validates this file against its own copy of
``handoff_schema.json`` and calls ``sys.exit(1)`` on any validation error
(``Serp-compete/src/main.py``). Both the root object and each target set
``additionalProperties: false``, so a new field is **not** silently ignored
downstream — it is fatal until Tool 2's schema copy allows it.

The T.4 ``moz`` block is therefore optional, top-level (never inside a
target), and absent entirely unless ``moz.competitor.enabled`` is true;
``schema_version`` moves to "1.1" only when it is present, so a run without it
still emits exactly the v1.0 document Tool 2 already accepts.
"""

import json
import logging
import os
from urllib.parse import urlparse

import jsonschema

_HANDOFF_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "handoff_schema.json")
_HANDOFF_SCHEMA = None
if os.path.exists(_HANDOFF_SCHEMA_PATH):
    with open(_HANDOFF_SCHEMA_PATH) as _f:
        _HANDOFF_SCHEMA = json.load(_f)


SCHEMA_VERSION_BASE = "1.0"
#: Bumped only when the optional `moz` block is actually present, so a run
#: without it stays byte-compatible with what Tool 2 already accepts.
SCHEMA_VERSION_WITH_MOZ = "1.1"


def build_competitor_handoff(
    all_organic,
    run_id,
    run_timestamp,
    client_domain,
    client_brand_names,
    n=10,
    omit_from_audit=None,
    moz_competitor=None,
):
    """Build the validated handoff dict for Tool 2 from organic results.

    Selects the top *n* organic URLs per keyword, excluding the client's own
    domain and any domain in *omit_from_audit*.  Returns the handoff dict; the
    caller is responsible for writing it.

    Returns None if:
    - all_organic is empty or None (no SERP data was collected — nothing to hand off)
    - schema validation fails (schema violation logged)
    """
    if not all_organic:
        logging.info("No organic results — competitor handoff not produced.")
        return None
    omit_set = {d.lower() for d in (omit_from_audit or [])}
    client_domain_lower = (client_domain or "").lower()

    # Build per-keyword top-N lists; simultaneously track primary keyword per URL.
    # primary_keyword_for_url = keyword where this URL appears at its lowest rank.
    url_best_rank: dict[str, tuple[int, str]] = {}  # url -> (rank, keyword)

    # First pass: find best (lowest) rank per URL across all keywords
    for item in all_organic:
        # Situational "S"-label probe rows feed only the AIO trigger-rate
        # analysis — never the handoff (Spec: seo_geo_deferred_spec_v1.md
        # #T.5, criterion T.5.3). The probe pass produces no organic rows;
        # this filter is a defensive guarantee.
        if item.get("Query_Label") == "S":
            continue
        url = item.get("Link") or item.get("url", "")
        if not url or url == "N/A":
            continue
        try:
            rank = int(item.get("Rank", 9999))
        except (TypeError, ValueError):
            rank = 9999
        keyword = item.get("Root_Keyword") or item.get("Keyword", "")
        prev = url_best_rank.get(url)
        if prev is None or rank < prev[0]:
            url_best_rank[url] = (rank, keyword)

    # Second pass: build per-keyword top-N candidate sets, applying exclusions
    seen_urls: set[str] = set()
    targets: list[dict] = []
    client_excluded = 0
    omit_excluded = 0
    omit_domains_hit: set[str] = set()

    # Group by keyword, preserving rank order
    from collections import defaultdict
    by_keyword: dict[str, list] = defaultdict(list)
    for item in all_organic:
        if item.get("Query_Label") == "S":  # see T.5.3 note above
            continue
        url = item.get("Link") or item.get("url", "")
        if not url or url == "N/A":
            continue
        kw = item.get("Root_Keyword") or item.get("Keyword", "")
        by_keyword[kw].append(item)

    for kw, items in by_keyword.items():
        # Sort by rank ascending
        def _rank(i):
            try:
                return int(i.get("Rank", 9999))
            except (TypeError, ValueError):
                return 9999

        sorted_items = sorted(items, key=_rank)
        added = 0
        for item in sorted_items:
            if added >= n:
                break
            url = item.get("Link") or item.get("url", "")
            if not url or url == "N/A":
                continue
            domain = urlparse(url).netloc.lower()

            if domain == client_domain_lower or client_domain_lower in domain:
                client_excluded += 1
                continue
            if domain in omit_set:
                omit_excluded += 1
                omit_domains_hit.add(domain)
                continue

            if url in seen_urls:
                added += 1
                continue
            seen_urls.add(url)

            try:
                rank_int = int(item.get("Rank", 0))
            except (TypeError, ValueError):
                rank_int = 0

            primary_kw = url_best_rank.get(url, (0, kw))[1]

            targets.append({
                "url": url,
                "domain": domain,
                "rank": rank_int,
                "entity_type": item.get("Entity_Type") or "N/A",
                "content_type": item.get("Content_Type") or "N/A",
                "title": item.get("Title") or "",
                "source_keyword": kw,
                "primary_keyword_for_url": primary_kw,
            })
            added += 1

    handoff = {
        "schema_version": (
            SCHEMA_VERSION_WITH_MOZ if moz_competitor else SCHEMA_VERSION_BASE
        ),
        "source_run_id": run_id,
        "source_run_timestamp": run_timestamp,
        "client_domain": client_domain or "",
        "client_brand_names": client_brand_names or [],
        "targets": targets,
        "exclusions": {
            "client_urls_excluded": client_excluded,
            "omit_list_excluded": omit_excluded,
            "omit_list_used": sorted(omit_domains_hit),
        },
    }

    if moz_competitor:
        handoff["moz"] = moz_competitor

    if _HANDOFF_SCHEMA:
        try:
            jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)
        except jsonschema.ValidationError as exc:
            logging.error(f"Handoff schema validation FAILED: {exc.message}")
            return None

    return handoff
