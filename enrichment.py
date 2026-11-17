"""
enrichment.py
~~~~~~~~~~~~~
One organic row's page-level enrichment, extracted from ``serp_audit.py``.

Review chunk D2c, finding D-C-20: the enrichment loop's only gate was
``if fetch_res:``, and ``url_enricher.fetch_url`` returns the body of a 403,
429 or 5xx response as readily as a 200. A Cloudflare challenge page was
therefore classified, word-counted and scored as the ranked page: a six-word
"Checking your browser" body arrived downstream as a real measurement of
`Word_Count`, `Author_Present`, extractability and E-E-A-T.

Every row now carries ``Fetch_Status``, so "this page has no author byline"
and "we never read this page" are different readings. The words themselves
are editorial and live in ``serp_vocab.yml`` (``fetch_status``).
"""
import logging

from pattern_matching import SERP_VOCAB

# The four outcomes a row can report, plus the recovered-link case.
ENRICHED = "enriched"
BLOCKED = "blocked"
UNREACHABLE = "unreachable"
NOT_ATTEMPTED = "not_attempted"
NOT_DESTINATION_PAGE = "not_destination_page"
NO_URL = "no_url"
DISABLED = "enrichment_disabled"

#: What a row's page-level fields read when the page was not read. The same
#: string the recovered-link path already used, so one unmeasured state has
#: one label (the D2a/D2b lesson).
NOT_MEASURED = "Not Measured"

# A response at or above this is an error page, not the ranked page.
ERROR_STATUS_FLOOR = 400


#: Literal fallbacks, so a missing or malformed ``fetch_status`` block in
#: serp_vocab.yml degrades to English rather than putting a state key such as
#: "not_attempted" in a cell the user reads.
_DEFAULTS = {
    ENRICHED: "Enriched",
    BLOCKED: "Blocked ({status})",
    UNREACHABLE: "Unreachable",
    NOT_ATTEMPTED: "Not Fetched",
    NOT_DESTINATION_PAGE: "Not The Ranked Page",
    NO_URL: "No URL",
    DISABLED: "Enrichment Off",
    "blocked_warning": ("{blocked} of {attempted} pages were not read "
                        "(error status or unreachable); their page-level "
                        "figures read Not Measured rather than zero"),
}


def status_text(state, **values):
    """The reader-facing words for one fetch outcome."""
    vocab = SERP_VOCAB.get("fetch_status") or {}
    template = vocab.get(state) or _DEFAULTS.get(state) or state
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError, TypeError):
        fallback = _DEFAULTS.get(state, state)
        try:
            return str(fallback).format(**values)
        except (KeyError, IndexError, ValueError, TypeError):
            return str(fallback)


def mark_unmeasured(item, state, **values):
    """Record one unmeasured outcome on a row, in both forms.

    ``Fetch_State`` is the machine-readable state and ``Fetch_Status`` the
    editable words. A consumer gating on the words would break the moment
    someone edits serp_vocab.yml, which is the opposite of why the words were
    moved there (P4).
    """
    item["Content_Type"] = NOT_MEASURED
    item["Word_Count"] = NOT_MEASURED
    item["Fetch_State"] = state
    item["Fetch_Status"] = status_text(state, **values)
    return state


_mark_unmeasured = mark_unmeasured


def enrich_row(item, url, rank_val, max_urls_to_enrich, enricher,
               content_classifier, entity_classifier, storage, domain=""):
    """Enrich one organic row in place; return which outcome it had.

    The caller counts the outcomes and reports them (P2); this function
    decides them and writes nothing it did not measure.
    """
    # A recovered link is the site root, not the ranked page: fetching it
    # would file the homepage's word count, schema and author signals as the
    # ranked page's. Domain classification by the caller is still sound.
    if not item.get("Is_Destination_Page", True):
        return _mark_unmeasured(item, NOT_DESTINATION_PAGE)

    if rank_val > max_urls_to_enrich:
        return _mark_unmeasured(item, NOT_ATTEMPTED)

    fetch_res = enricher.fetch_url(url)
    if not fetch_res:
        # fetch_url logged the exception and returned None.
        return _mark_unmeasured(item, UNREACHABLE)

    status = fetch_res.get("status_code")
    if status is None or int(status) >= ERROR_STATUS_FLOOR:
        # The body of an error page is the error page. It reaches SQLite as a
        # record of the attempt (P2) and nothing else is taken from it: a
        # challenge page's 6 words are not this page's word count, and its
        # missing byline is not this page's missing byline (P1 — a block is
        # retryable, not a terminal property of the site).
        storage.save_url_features(url, status, NOT_MEASURED, [], None,
                                  ["fetch_blocked"])
        logging.warning(
            "  - %s returned status %s; not read, Fetch_Status recorded.",
            url, status)
        return _mark_unmeasured(item, BLOCKED, status=status)

    features = enricher.extract_features(fetch_res)
    soup = features.get("soup")

    c_type, _c_conf, c_ev = content_classifier.classify(
        url, soup, fetch_res.get("headers"))
    e_type, _e_conf, _e_ev = entity_classifier.classify(domain, soup)

    storage.save_url_features(
        url, status, c_type, features.get("schema_types", []),
        features.get("word_count_est", 0), c_ev)
    storage.save_domain_features(domain, e_type)

    item["Content_Type"] = c_type
    item["Entity_Type"] = e_type
    item["Word_Count"] = features.get("word_count_est", "N/A")
    # Schema/FAQ signals feed the brief's FAQ / Answer-Extraction Plan
    # (Spec: seo_geo_review_20260704.md T.1/G.2).
    item["Schema_Types"] = features.get("schema_types", [])
    item["FAQ_Present"] = features.get("faq_present", False)
    # Answer-extractability signals (T.2).
    item["Question_Heading_Count"] = features.get("question_heading_count", 0)
    item["Question_Headings"] = features.get("question_headings", [])
    item["Intro_Text_Length"] = features.get("intro_text_length", 0)
    # Content freshness signals (Spec: seo_geo_deferred_spec_v1.md#G.6).
    item["Published_Time"] = features.get("published_time")
    item["Modified_Time"] = features.get("modified_time")
    # E-E-A-T author signals (Spec: seo_geo_deferred_spec_v1.md#G.3).
    item["Author_Present"] = features.get("author_present", False)
    item["Credential_Hits"] = features.get("credential_hits", [])
    item["Review_Marker_Present"] = features.get(
        "review_marker_present", False)
    item["Fetch_State"] = ENRICHED
    item["Fetch_Status"] = status_text(ENRICHED)
    return ENRICHED
