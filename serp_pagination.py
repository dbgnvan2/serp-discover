"""
serp_pagination.py
~~~~~~~~~~~~~~~~~~
SerpAPI pagination helpers: find the next page's ``start`` offset, and merge
the fetched pages into one response object.

Pure functions, no I/O and no module state, so the rank arithmetic they own
can be tested on its own. Extracted from ``serp_audit.py`` by review chunk D1
(file-maintainability: the module is size-capped by
``tests/test_serp_audit_split.py``).

Rank semantics: SerpAPI restarts ``position`` at 1 on every paginated page, so
the merge renumbers it to the absolute merged position. See docs/methodology.md,
Part 1 "Rank semantics (pagination)".
"""

from __future__ import annotations

import re


def _parse_start_from_pagination(results):
    """Returns the next `start` integer from serpapi_pagination.next, if present."""
    pagination = results.get("serpapi_pagination", {}) if isinstance(results, dict) else {}
    next_link = pagination.get("next")
    if not next_link:
        return None
    match = re.search(r"[?&]start=(\d+)", next_link)
    if not match:
        return None
    return int(match.group(1))


def _merge_google_pages(pages):
    """Merge selected paginated Google fields into a single response object.

    SerpAPI restarts ``position`` at 1 on every page, so this renumbers it to
    the merged (absolute) position and keeps the raw value as ``page_position``.
    Rank semantics: docs/methodology.md, Part 1 "Rank semantics (pagination)".
    Spec: review_2026-11-04 chunk D1 (D-C-01 / D-M-01).
    """
    if not pages:
        return {}

    merged = dict(pages[0])
    merged["organic_results"] = []
    merged["related_questions"] = []
    merged["related_searches"] = []
    merged["discussions_and_forums"] = []
    merged["pagination_pages_fetched"] = len(pages)

    seen_org = set()
    seen_paa = set()
    seen_rel = set()
    seen_forums = set()

    for page_index, page in enumerate(pages):
        for item in page.get("organic_results", []) or []:
            key = item.get("link") or f"{item.get('title')}|{item.get('position')}"
            if key in seen_org:
                continue
            seen_org.add(key)
            # Copy before renumbering: the un-merged pages are kept in
            # all_results['google_pages'] and must stay as SerpAPI returned
            # them, and this function is called repeatedly while paginating.
            row = dict(item)
            row["page_position"] = item.get("position")
            row["page_index"] = page_index
            row["position"] = len(merged["organic_results"]) + 1
            merged["organic_results"].append(row)

        for item in page.get("related_questions", []) or []:
            key = item.get("question")
            if not key or key in seen_paa:
                continue
            seen_paa.add(key)
            merged["related_questions"].append(item)

        for item in page.get("related_searches", []) or []:
            key = item.get("query")
            if not key or key in seen_rel:
                continue
            seen_rel.add(key)
            merged["related_searches"].append(item)

        for item in page.get("discussions_and_forums", []) or []:
            key = item.get("link") or item.get("title")
            if not key or key in seen_forums:
                continue
            seen_forums.add(key)
            merged["discussions_and_forums"].append(item)

        if "ai_overview" not in merged and page.get("ai_overview"):
            merged["ai_overview"] = page["ai_overview"]

    return merged


def _merge_maps_pages(pages):
    """Merge paginated maps local results into a single response object."""
    if not pages:
        return {}
    merged = dict(pages[0])
    merged["local_results"] = []
    merged["pagination_pages_fetched"] = len(pages)

    seen_places = set()
    for page in pages:
        for place in page.get("local_results", []) or []:
            key = place.get("place_id") or place.get("data_id") or f"{place.get('title')}|{place.get('address')}"
            if key in seen_places:
                continue
            seen_places.add(key)
            merged["local_results"].append(place)
    return merged
