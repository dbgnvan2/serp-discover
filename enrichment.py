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


#: Fallback wording for the `classification_coverage` block, on the same terms
#: as `_DEFAULTS`: a missing or malformed section degrades to English.
_COVERAGE_DEFAULTS = {
    "line": ("**Ranked results classified:** {classified} of {total}."
             "{host_inferred_clause} SERP intent is read from classified "
             "results only. The rest were not classified because {reasons}."),
    "reason_item": "{count} × {label}",
    "host_inferred_clause": ("{count} of those were classified from the site "
                             "alone, because the page's own type could not be "
                             "determined \u2014 the site's type is known, its "
                             "page's is not."),
    "none_classified": ("**Ranked results classified:** none of {total}, so "
                        "no keyword can have a SERP intent verdict this run: "
                        "{reasons}."),
    "unmapped_type": "their page type does not map to a search intent",
}


def _intent_window_counts(keyword_profiles):
    """`(classified, total, host_inferred)` from the keywords' intent evidence.

    `host_inferred` is how many of `classified` were reached from the host
    alone because the ranked page could not be read. It is reported beside the
    figure rather than folded into it: the sentence would otherwise say the
    run classified results it never read.

    This is the SAME measurement the per-keyword sections print as "only N of
    M URLs could be classified": `serp_intent.evidence`, counted over the
    top-10 window `compute_serp_intent` was given. The first version of this
    line counted rows whose `Content_Type` was an unmeasured marker instead,
    which is a different measurement in both directions — a client or
    known-competitor row classifies without a content type at all, and a page
    read as `other` or `unknown` has a content type but no intent — and on the
    2026-11-18 run the two gave "15 of 221" and "6 of 100" in one report under
    one word (cold review of this fix, finding 1). Returns `(None, None)` when
    no keyword recorded any evidence.
    """
    if not isinstance(keyword_profiles, dict):
        return None, None, 0
    classified = total = host_inferred = 0
    seen = False
    for profile in keyword_profiles.values():
        if not isinstance(profile, dict):
            continue
        evidence = ((profile.get("serp_intent") or {}).get("evidence") or {})
        if not isinstance(evidence, dict):
            continue
        rows = evidence.get("organic_url_count")
        if not isinstance(rows, int):
            continue
        seen = True
        total += rows
        hit = evidence.get("classified_organic_url_count")
        classified += hit if isinstance(hit, int) else 0
        inferred = evidence.get("host_inferred_classified_count")
        host_inferred += inferred if isinstance(inferred, int) else 0
    return (classified, total, host_inferred) if seen else (None, None, 0)


def _unread_states_in_window(keyword_profiles):
    """`{state: count}` over the same top-10 windows, from `fetch_coverage`.

    `brief_data_extraction._build_fetch_coverage` already counts the unread
    states per keyword over `kw_rows[:10]` — the very window the intent
    verdict uses — so the causes are counted against the same denominator as
    the figure they explain. Reading the raw rows instead pooled every rank
    and produced cause counts larger than their own total.
    """
    counts = {}
    if not isinstance(keyword_profiles, dict):
        return counts
    for profile in keyword_profiles.values():
        if not isinstance(profile, dict):
            continue
        for block in profile.values():
            if not isinstance(block, dict):
                continue
            coverage = block.get("fetch_coverage")
            if not isinstance(coverage, dict):
                continue
            for state, count in (coverage.get("by_state") or {}).items():
                if isinstance(count, int):
                    counts[str(state)] = counts.get(str(state), 0) + count
            break  # one coverage block per keyword; they are the same object
    return counts


def _host_inferred_by_state_in_window(keyword_profiles):
    """`{fetch_state: count}` of rows classified from the host, not the page.

    These rows sit on both sides of the coverage sentence's arithmetic: they
    count as classified, and their fetch state also appears among the unread
    states. Subtracting them per state is what keeps the causes equal to the
    deficit they explain instead of exceeding it (P2).
    """
    counts = {}
    if not isinstance(keyword_profiles, dict):
        return counts
    for profile in keyword_profiles.values():
        if not isinstance(profile, dict):
            continue
        evidence = ((profile.get("serp_intent") or {}).get("evidence") or {})
        if not isinstance(evidence, dict):
            continue
        by_state = evidence.get("host_inferred_by_fetch_state")
        if not isinstance(by_state, dict):
            continue
        for state, count in by_state.items():
            if isinstance(count, int) and count > 0:
                counts[str(state)] = counts.get(str(state), 0) + count
    return counts


def classification_coverage_line(keyword_profiles):
    """One line saying how many ranked results were classified, and why not.

    The report stated "0 of 10 URLs could be classified" per keyword and
    nowhere said what stopped them, so a run whose links came back as Google
    redirects recovering only to a site root produced ten "Deprioritise"
    verdicts and no page recommendation, with the cause recorded on every row
    and reported in no sentence (P2, found by the first live run,
    2026-11-18).

    Both numbers come from the keywords' own `serp_intent.evidence` and
    `fetch_coverage` blocks, so the figure and its causes are the same
    measurement the per-keyword sections print, over the same top-10 window.
    A deficit the unread states do not account for is named as what it is —
    pages that were read and whose type does not map to a search intent —
    rather than left as the difference between two numbers.

    Returns "" when every result in the window was classified, or when no
    keyword recorded any evidence to speak about.
    """
    classified, total, host_inferred = _intent_window_counts(keyword_profiles)
    if not total or classified is None or classified >= total:
        return ""
    vocab = SERP_VOCAB.get("classification_coverage") or {}

    def _words(key):
        return str(vocab.get(key) or _COVERAGE_DEFAULTS[key])

    def _host_clause(count):
        """The "N of these came from the site, not the page" clause, or ""."""
        if count <= 0:
            return ""
        for words in (vocab.get("host_inferred_clause"),
                      _COVERAGE_DEFAULTS["host_inferred_clause"]):
            try:
                text = str(words).format(count=count).strip()
            except (KeyError, IndexError, ValueError, TypeError, AttributeError):
                continue
            if text:
                return " " + text
        return ""

    def _join(template):
        parts = []
        unread = _unread_states_in_window(keyword_profiles)
        inferred_by_state = _host_inferred_by_state_in_window(keyword_profiles)
        accounted = 0
        for state, raw_count in sorted(unread.items(),
                                       key=lambda kv: (-kv[1], kv[0])):
            # A row that was unread AND classified from its host is not part
            # of the deficit, so it is not one of its causes either.
            count = raw_count - inferred_by_state.get(state, 0)
            if count <= 0:
                continue
            accounted += count
            parts.append(template.format(count=count,
                                         label=reason_text(state)))
        remainder = (total - classified) - accounted
        if remainder > 0:
            # Read, and still not classified. Saying nothing here would make
            # the causes add up to less than the deficit they explain, which
            # is how a reader concludes the rest is unexplained (P2).
            parts.append(template.format(count=remainder,
                                         label=_words("unmapped_type")))
        return ", ".join(parts)

    key = "none_classified" if classified == 0 else "line"
    for words, template in ((_words(key), _words("reason_item")),
                            (_COVERAGE_DEFAULTS[key],
                             _COVERAGE_DEFAULTS["reason_item"])):
        # The reason join is inside the guard with the sentence: a mistyped
        # placeholder in `reason_item` raised before the fallback could run,
        # and `serp_vocab.yml` is the file users are told to edit (cold review
        # of this fix, finding 2).
        try:
            return words.format(classified=classified, total=total,
                                host_inferred=host_inferred,
                                host_inferred_clause=_host_clause(host_inferred),
                                reasons=_join(template)).strip()
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return ""


#: Phrase fallbacks for `reason_text`, mirroring `_DEFAULTS`.
_REASON_DEFAULTS = {
    BLOCKED: "the site returned an error status",
    FETCH_RETRYABLE: "every attempt failed at the network layer",
    UNREACHABLE: "the page could not be reached",
    NOT_ATTEMPTED: "the per-run page budget stopped before this rank",
    NOT_DESTINATION_PAGE: "the link resolved to the site root, not the "
                          "ranked page",
    NO_URL: "the row carried no URL",
    DISABLED: "page enrichment was switched off for this run",
}


def page_read_state(fetch_state) -> str:
    """Whether the ranked page itself was read: "yes" / "no" / "unknown".

    `intent_mapping.yml` keys its host-inference rules on this, so the three
    states have to stay distinct: ENRICHED is the only state in which the
    page's own evidence exists, every UNREAD_STATES member means it does not,
    and anything else — including a row from an analysis JSON written before
    the field existed — is "unknown" and must not be read as "no" (P1).
    """
    state = str(fetch_state or "").strip().lower()
    if state == ENRICHED:
        return "yes"
    if state in UNREAD_STATES:
        return "no"
    return "unknown"


def reason_text(state):
    """One unread outcome as a PHRASE, for a sentence rather than a cell.

    "4 because the link resolved to the site root" needs different words from
    the `Fetch_Status` cell's "Not The Ranked Page", and the phrases were a
    Python dict in `brief_data_extraction._UNREAD_FETCH_STATES` — a second
    home for the same facts as `fetch_status` above, which is what moving
    those words out of Python was for. They live in `serp_vocab.yml` under
    `fetch_status.reasons`; a state with no phrase falls back to its cell
    label, so a new state is readable before anyone writes its sentence.
    """
    reasons = ((SERP_VOCAB.get("fetch_status") or {}).get("reasons") or {})
    phrase = reasons.get(state) or _REASON_DEFAULTS.get(state)
    return str(phrase) if phrase else status_text(state, status="an error")


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
