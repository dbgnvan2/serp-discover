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
``schema_version`` takes the ``_WITH_MOZ`` value only when it is present, so a
run without it emits the smaller document Tool 2 already accepts.

``targets[].rank`` is the absolute SERP position as of schema_version 2.0
(review chunk D1 / finding D-C-01); 1.0 and 1.1 carried SerpAPI's per-page
``position``. See ``docs/handoff_contract.md``.
"""

import json
import logging
import os

import jsonschema

from domain_utils import normalize_domain

_HANDOFF_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "handoff_schema.json")


def _is_client_host(domain, client_domain_lower):
    """True when *domain* is the client's host or a subdomain of it.

    D-C-08: the old test was ``client_domain_lower in domain``, a
    substring match that dropped any competitor whose host merely
    contained the client's — ``notlivingsystems.ca`` read as the client.
    Both sides are already normalised by ``normalize_domain``.
    """
    if not domain or not client_domain_lower:
        return False
    return (domain == client_domain_lower
            or domain.endswith("." + client_domain_lower))
_HANDOFF_SCHEMA = None
if os.path.exists(_HANDOFF_SCHEMA_PATH):
    with open(_HANDOFF_SCHEMA_PATH) as _f:
        _HANDOFF_SCHEMA = json.load(_f)


#: 2.0 since review chunk D1: `targets[].rank` is now the absolute position on
#: the SERP. Under 1.0/1.1 it was SerpAPI's per-page `position`, so a 3-page
#: run emitted three targets all claiming rank 1 and Tool 2 could not tell a
#: real #1 from a page-3 row (finding D-C-01). The document's *shape* is
#: unchanged — only the meaning of `rank` — but Tool 2 enforces
#: `handoff.supported_versions` and keys its rank-column warning off
#: `handoff.absolute_rank_versions`, so the bump is how it learns the ranks
#: can be trusted. Both values must be registered in Tool 2's shared
#: cross-tool config — see docs/handoff_contract.md, "schema_version 2.0".
SCHEMA_VERSION_BASE = "2.0"
#: Bumped only when the optional `moz` block is actually present, so a run
#: without it emits the smaller document.
SCHEMA_VERSION_WITH_MOZ = "2.1"


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
    # D-C-08: one host, one answer. The omit list, the client domain and
    # each target's host go through the same normalisation, so an entry
    # written as "www.x.ca" excludes x.ca and the handoff's competitor key
    # is the canonical host serp-compete also normalises to at ingest.
    omit_set = {normalize_domain(d) for d in (omit_from_audit or [])}
    omit_set.discard("")
    client_domain_lower = normalize_domain(client_domain)

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
    collapsed_rows = 0
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
            domain = normalize_domain(url)

            if _is_client_host(domain, client_domain_lower):
                client_excluded += 1
                continue
            if domain in omit_set:
                omit_excluded += 1
                omit_domains_hit.add(domain)
                continue

            if url in seen_urls:
                added += 1
                # Google's redirect wrapper leaves only the site, not the
                # ranked page (link_recovery), so two different ranked pages
                # on one site now arrive as the same URL and collapse here.
                # Count it: a target standing for three ranked pages must not
                # look like one that stands for one (P2).
                if not item.get("Is_Destination_Page", True):
                    collapsed_rows += 1
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

    if collapsed_rows:
        logging.warning(
            "%d ranked page(s) could not be told apart as handoff targets: "
            "Google's redirect wrapper left only the site, so same-site pages "
            "collapsed into one target. Tool 2 will audit the site's front "
            "page, not the page that ranked.", collapsed_rows)

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
