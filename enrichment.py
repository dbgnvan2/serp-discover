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

#: The states a row's `Fetch_State` can carry. `UNREAD_STATES` below is the
#: subset that means the page was not read; `brief_data_extraction` is checked
#: against it, because a state it does not know is counted as a page that was
#: read (review chunk Y2's cold review).
ENRICHED = "enriched"
BLOCKED = "blocked"
#: No request could be made at all: an unparseable URL or a redirect loop
#: (`http_retry.PERMANENT_REQUEST_ERRORS`). Retrying cannot change it.
UNREACHABLE = "unreachable"
#: Every fetch attempt failed at the network layer after `http_retry`'s
#: retries — a timeout, a reset, a host that did not resolve. The page may
#: well be readable on the next run, which `UNREACHABLE` denied (P1, review
#: chunk Y2).
FETCH_RETRYABLE = "fetch_retryable"
NOT_ATTEMPTED = "not_attempted"
NOT_DESTINATION_PAGE = "not_destination_page"
NO_URL = "no_url"
DISABLED = "enrichment_disabled"

#: Everything except `ENRICHED`: the page was not read, for one reason or
#: another, and its page-level figures read `Not Measured` rather than zero.
UNREAD_STATES = (BLOCKED, FETCH_RETRYABLE, UNREACHABLE, NOT_ATTEMPTED,
                 NOT_DESTINATION_PAGE, NO_URL, DISABLED)

#: The subset of `UNREAD_STATES` where the run tried to read the page and did
#: not get it. The "N of M pages were not read" warning counts these and not
#: the rest: a row past the enrichment rank cap, a row with no URL and a run
#: with enrichment switched off were never meant to be read, and counting them
#: would fire the warning on almost every run. `fetch_retryable` belongs here
#: — it was missing, so a run where every page timed out could warn about 0
#: (review chunk Y2 and its cold review).
FAILED_FETCH_STATES = (BLOCKED, FETCH_RETRYABLE, UNREACHABLE)

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
    FETCH_RETRYABLE: "Not Read (network, retry)",
    NOT_ATTEMPTED: "Not Fetched",
    NOT_DESTINATION_PAGE: "Not The Ranked Page",
    NO_URL: "No URL",
    DISABLED: "Enrichment Off",
    "blocked_warning": ("{blocked} of {attempted} pages were not read (an "
                        "error status, a network failure after the retries, "
                        "or no request possible at all — the rows' own "
                        "Fetch_Status says which); their page-level figures "
                        "read Not Measured rather than zero"),
}


def unread_fetch_count(fetch_outcomes) -> int:
    """How many of this keyword's pages were not read.

    Counts every state in `FAILED_FETCH_STATES`: a retryable
    network exhaustion is a page the run did not read just as a 403 is, and
    leaving one out is how the warning could say "0 of 10 pages were not read"
    on a run where nothing was read at all. Derived from that tuple rather than
    listed here, so a new failure state is counted the moment it exists
    (review chunk Y2 and its cold review).
    """
    return sum(int(fetch_outcomes.get(state, 0) or 0)
               for state in FAILED_FETCH_STATES)


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


#: Content-type cells that record an absence of measurement rather than a
#: type, lower-cased. Same set as `brief_data_extraction._UNMEASURED_CONTENT_TYPES`
#: — `"N/A"` is the field's own missing marker and `"Not Measured"` is
#: `NOT_MEASURED`.
_UNCLASSIFIED_CONTENT_TYPES = {"n/a", "not measured", ""}

#: Fallback wording for the `classification_coverage` block, on the same terms
#: as `_DEFAULTS`: a missing or malformed section degrades to English.
_COVERAGE_DEFAULTS = {
    "line": ("**Ranked results classified:** {classified} of {total}. SERP "
             "intent is read from classified results only. The rest were not "
             "classified because {reasons}."),
    "reason_item": "{count} × {label}",
    "none_classified": ("**Ranked results classified:** none of {total}, so "
                        "no keyword can have a SERP intent verdict this run: "
                        "{reasons}."),
}


def classification_coverage_line(organic_results):
    """One line saying how many ranked results were classified, and why not.

    The report stated "0 of 10 URLs could be classified" per keyword and
    nowhere said what stopped them, so a run whose links came back as Google
    redirects recovering only to a site root produced ten "Deprioritise"
    verdicts and no page recommendation, with the cause recorded on every row
    and reported in no sentence (P2, found by the first live run,
    2026-11-18).

    The reasons are the rows' OWN `Fetch_Status` words, counted — not a cause
    inferred here. Returns "" when every result was classified, or when there
    are no results to speak about.
    """
    rows = [r for r in (organic_results or []) if isinstance(r, dict)]
    if not rows:
        return ""
    unclassified = [r for r in rows
                    if str(r.get("Content_Type") or "").strip().lower()
                    in _UNCLASSIFIED_CONTENT_TYPES]
    if not unclassified:
        return ""
    vocab = SERP_VOCAB.get("classification_coverage") or {}

    def _words(key):
        return str(vocab.get(key) or _COVERAGE_DEFAULTS[key])

    counts = {}
    for row in unclassified:
        label = str(row.get("Fetch_Status") or "").strip() or "no reason recorded"
        counts[label] = counts.get(label, 0) + 1
    item = _words("reason_item")
    reasons = ", ".join(
        item.format(count=count, label=label)
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    classified = len(rows) - len(unclassified)
    key = "none_classified" if classified == 0 else "line"
    try:
        return _words(key).format(classified=classified, total=len(rows),
                                  reasons=reasons).strip()
    except (KeyError, IndexError, ValueError, TypeError):
        return _COVERAGE_DEFAULTS[key].format(
            classified=classified, total=len(rows), reasons=reasons).strip()


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
        # Older injected enrichers (and tests) still return None.
        return _mark_unmeasured(item, UNREACHABLE)
    if "error" in fetch_res:
        # A network failure after every retry is a fact about the attempt; a
        # URL no request can be formed from is a fact about the row. The row
        # said "Unreachable" for both until review chunk Y2, so a run on a bad
        # connection read as a permanent verdict on every page it touched, and
        # a reader had no way to know a re-run would change it (P1).
        return _mark_unmeasured(
            item,
            FETCH_RETRYABLE if fetch_res.get("retryable") else UNREACHABLE)

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
