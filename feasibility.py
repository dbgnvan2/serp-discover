"""
feasibility.py
~~~~~~~~~~~~~~
Competitive-gap and hyper-local pivot logic for the SERP intelligence tool.

Two public functions:

    compute_feasibility(client_da, competitor_das)
        Given the client's Domain Authority and a list of competitor DAs from
        the top-10 organic results, return a structured feasibility assessment.

    generate_hyper_local_pivot(primary_keyword, non_profit_location,
                               feasibility_results, neighborhoods, strategy)
        When a keyword is "Low Feasibility", suggest a hyper-local neighbourhood
        variant that is likely to have a smaller DA gap.

This module is intentionally free of I/O beyond the shared cross-tool
config read (owned by ``shared_config.py``) so it can be tested in
isolation and reused without side effects.
"""

from __future__ import annotations

import logging
import os
import random as _random
from typing import Callable, Literal, NamedTuple

import yaml
from urllib.parse import urlparse

from shared_config import load_shared_config
from domain_utils import normalize_domain


def load_thresholds():
    """Read feasibility thresholds from the shared cross-tool config.

    Path resolution, the SERP_SHARED_CONFIG env override, and
    malformed-file handling (warn + defaults) are owned by
    ``shared_config.load_shared_config`` — do not duplicate them here.
    Spec: seo_geo_deferred_spec_v1.md#C.9.
    """
    tech = load_shared_config().get("technical", {})
    if not isinstance(tech, dict):
        tech = {}
    return (
        tech.get("feasibility_threshold", 5),
        tech.get("moderate_feasibility_max_gap", 15),
        tech.get("score_normaliser", 30.0),
        tech.get("min_da_for_verdict", 5),
    )

(HIGH_FEASIBILITY_MAX_GAP, MODERATE_FEASIBILITY_MAX_GAP, SCORE_NORMALISER,
 MIN_DA_FOR_VERDICT) = load_thresholds()

#: The status a row carries when nothing (or too little) was measured. A key,
#: not wording — the words a reader sees come from ``feasibility_messages.yml``
#: via :func:`status_label`. It is a constant because consumers branch on it
#: (the report withholds its DA comparison, run_feasibility skips the pivot),
#: and four files comparing against their own copy of the string is how one
#: unmeasured state came to carry two labels before D2a.
NOT_MEASURED = "Not Measured"

StatusLiteral = Literal["High Feasibility", "Moderate Feasibility",
                       "Low Feasibility", "Not Measured"]


# ---------------------------------------------------------------------------
# One definition of the feasibility input set
# ---------------------------------------------------------------------------
#
# Two producers used to build this set differently, from the same SERP, and
# both wrote `keyword_feasibility`: the in-pipeline pass in serp_audit took the
# first 10 links in page order with the client's own URL among them, while
# run_feasibility took the top 10 by rank with the client excluded. The two
# therefore reported different Avg Comp DA for the same keyword, and the
# report's §5c and the play router disagreed about which row was authoritative.
# Both now call the helpers below.
#
# Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk D1
# (finding D-C-19).

#: How many of a keyword's ranking URLs the DA average is taken over.
TOP_N_FOR_FEASIBILITY = 10

#: How many competitor DAs a published verdict needs — read above from
#: ``technical.min_da_for_verdict`` in the shared config, default 5. A mean of
#: one or two domains out of a top 10 is not a measurement of that SERP's
#: authority, and a verdict drawn from it reads exactly like one drawn from all
#: ten. Below this the status is "Not Measured" and the numbers are reported
#: with their coverage rather than suppressed (D-C-03/D-M-08). It decides how
#: many verdicts a report publishes at all, so it is an operator's dial and
#: lives beside the gap thresholds rather than in this file.


def domain_of(url: str) -> str:
    """Return the bare, lower-cased domain of *url*, ``www.`` removed.

    Delegates to ``domain_utils.normalize_domain``, which also handles the
    scheme-less keys the Moz cache writes (``"example.com/page"``), a port and
    userinfo. This module held a seventh copy of the rule (review chunk Y1);
    a copy that merely agrees today is still a copy that can drift.
    """
    if not url:
        return ""
    try:
        return normalize_domain(url)
    except Exception:
        return ""


class URLWindow(NamedTuple):
    """The window's resolvable URLs and the positions it could not resolve.

    The hole count has to leave this function with the URLs. Returning the
    filtered list alone threw the real denominator away one line after
    computing it, so a top 10 with four unresolvable links published
    ``da_missing=0`` and a coverage of "all 6 ranking domains" — a complete
    measurement of a window that was 60% measured (P9/P31).
    """

    urls: list       #: the resolvable URLs, best-ranked first
    unresolved: int  #: positions in the window with no usable URL
    window: int      #: positions considered — ``len(urls) + unresolved``


def usable_url(url) -> bool:
    """True when *url* is something a DA provider can be asked about.

    One definition of "this position has no URL". An empty value and the
    literal ``"N/A"`` both mean link recovery could not resolve the row, and
    both must count against coverage rather than be sent to the provider as
    a target. Three call sites tested for this separately and one of them
    tested only for emptiness, so an ``"N/A"`` reached the fetch batch.
    """
    return bool(url) and str(url).strip() not in ("N/A", "n/a")


def url_window(rows, what="", log=None) -> URLWindow:
    """The top-N URLs by absolute rank, with the unmeasurable ones counted.

    One definition of the window, beside :func:`competitor_da_window`
    which consumes it. Filtering before slicing would slide ranks 11, 12 ... into a
    set the report, the handoff and docs/feasibility.md all call "the top 10"
    (P9/P31). The window is the top N rows; a row whose link recovery could
    not resolve leaves a hole in it, and the hole travels with the URLs rather
    than being quietly backfilled from deeper, weaker results or dropped from
    the denominator.
    """
    window_rows = rows[:TOP_N_FOR_FEASIBILITY]
    urls = [r.get("Link") for r in window_rows if usable_url(r.get("Link"))]
    unresolved = len(window_rows) - len(urls)
    if unresolved and log is not None:
        log(f"{what}: {unresolved} of the top {len(window_rows)} result(s) "
            f"have no URL, so the Domain Authority average is taken from "
            f"{len(urls)} of them, not {len(window_rows)}. The rows report "
            f"the shortfall as unscored coverage.")
    return URLWindow(urls=urls, unresolved=unresolved,
                     window=len(window_rows))


class DAWindow(NamedTuple):
    """The feasibility input set, with the measurement it is missing.

    ``das`` alone cannot say whether a mean of three came from a SERP with
    three competitors or from a top 10 where seven were never scored. Both
    numbers travel together so every row can state its own coverage
    ("mean of N of M ranking domains, K unscored") instead of publishing a
    figure whose basis is invisible (D-C-03/D-M-08, P2).
    """

    das: list       #: the measured competitor DAs, best-ranked first
    measured: int   #: how many competitors had a DA record (``len(das)``)
    missing: int    #: competitors in the window with no DA record
    window: int     #: competitors considered — ``measured + missing``
    entities: list = ()  #: entity type per entry of ``das``, ``None`` where unknown

    # ``entities`` is parallel to ``das`` so the minimum can be taken over the
    # competitors the client actually competes with (D-M-09/D6.1). It defaults
    # to empty because the caller that has no entity type for a URL must say
    # so rather than guess: an unknown type is ``None``, which keeps that
    # competitor out of the non-directory minimum instead of counting it as a
    # clinic (P1 — unknown is not a measurement).


def competitor_da_window(
    ranked_urls,
    da_for_url: Callable[[str], object],
    client_domain: str = "",
    top_n: int = TOP_N_FOR_FEASIBILITY,
    entity_for_url: Callable[[str], object] | None = None,
) -> DAWindow:
    """Return the competitor DA values the feasibility gap is measured over.

    *ranked_urls* is a :class:`URLWindow` from :func:`url_window` — already
    sliced, carrying the positions it could not resolve — or a plain list in
    rank order, best first, which is sliced here. Since review chunk D1 the
    merged SERP rows are in absolute rank order, because ``Rank`` is absolute.
    The window is the first *top_n* URLs **of the SERP**, and the client's own
    domain is then dropped from that window — so a keyword where the client
    ranks 4th is scored against the 9 competitors in its true top 10, not
    against 10 competitors drawn from further down the page.

    A position with no usable URL counts against coverage, not as a competitor
    with no authority: ``URLWindow.unresolved`` seeds ``missing``.

    *da_for_url* returns the DA for one URL, or ``None`` when that URL has no
    DA record. ``None`` is not zero: an unscored domain is left out of the
    average rather than counted as a DA of 0 (finding D-C-04). An empty
    result therefore means "nothing measured here", which
    :func:`compute_feasibility` reports as ``"Not Measured"`` — never as
    ``"Low Feasibility"``.

    Callers must take their slice from ``TOP_N_FOR_FEASIBILITY`` rather than
    their own literal, or raising it here would have no effect.

    This is the only place the window is built. Returning the coverage from
    the same loop is deliberate: a second function counting the denominator
    would be a second definition of the window, and the two would drift.
    """
    client = domain_of(client_domain) if client_domain else ""
    das = []
    entities = []
    classifier_errors = []
    if isinstance(ranked_urls, URLWindow):
        # Already the window: slicing again would be applying it twice, and
        # the unresolved positions are holes in this same window.
        urls, missing = list(ranked_urls.urls), ranked_urls.unresolved
    else:
        urls, missing = list(ranked_urls or [])[:top_n], 0
    for url in urls:
        if not usable_url(url):
            # No URL at all: link recovery could not resolve it, so this
            # position was never measured and is not a competitor with no
            # authority. It counts against coverage (P1/P14).
            missing += 1
            continue
        if client and domain_of(url) == client:
            continue
        da = da_for_url(url)
        if da is None:
            missing += 1
        else:
            das.append(da)
            # A caller with no classifier passes none, and every entity is
            # then unknown — which the minimum below reports as unmeasured
            # rather than as "no directories on this SERP".
            entity = None
            if entity_for_url is not None:
                try:
                    entity = entity_for_url(url)
                except Exception as exc:
                    entity = None
                    classifier_errors.append(f"{url}: {exc}")
            entities.append(entity)
    if classifier_errors:
        # Unknown is the right value, but a classifier raising on every URL
        # would make every SERP read "directory split not measured" with
        # nothing saying why. Count it and name the first (P2).
        logging.warning(
            "entity classification failed for %d of %d scored competitors; "
            "their directory split is reported as not measured. First: %s",
            len(classifier_errors), len(das), classifier_errors[0])
    return DAWindow(das=das, measured=len(das), missing=missing,
                    window=len(das) + missing, entities=entities)


#: Where the status labels, icons, no-measurement sentences and coverage
#: phrases live. Editorial content, so it is a config file, not a dict here.
MESSAGES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "feasibility_messages.yml")

_MESSAGES_CACHE = None


def load_messages() -> dict:
    """Read ``feasibility_messages.yml``, or ``{}`` when it cannot be read.

    A missing or malformed file degrades to the bare status string rather than
    aborting a report: the words are presentation, and losing them must not
    cost the run. Read once and cached, since every row asks for them.
    """
    global _MESSAGES_CACHE
    if _MESSAGES_CACHE is not None:
        return _MESSAGES_CACHE
    data = {}
    try:
        with open(MESSAGES_FILE, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, yaml.YAMLError) as exc:
        logging.warning(
            "feasibility_messages.yml could not be read (%s); feasibility "
            "statuses will render as plain text.", exc)
    _MESSAGES_CACHE = data
    return data


def status_label(status, bare_icon=False) -> str:
    """The configured label (or icon) for *status*, else *status* itself."""
    entry = (load_messages().get("statuses") or {}).get(status) or {}
    key = "icon" if bare_icon else "label"
    value = entry.get(key)
    return str(value) if value else ("" if bare_icon else str(status or ""))


def _render(template, fallback, **values) -> str:
    """Format a configured string, falling back rather than raising.

    §5c is deliberately not inside ``_safe_section``, so a ``KeyError`` from a
    placeholder someone added to ``feasibility_messages.yml`` would take down
    the whole market report — the opposite of the documented contract that a
    malformed messages file degrades to plain text and never aborts a run.
    """
    if not template:
        return fallback
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        logging.warning(
            "feasibility_messages.yml: %r could not be rendered (%s); using "
            "the built-in wording.", template, exc)
        return fallback


def _as_count(value) -> int | None:
    """*value* as a non-negative count, or ``None`` when it is not one.

    Counts arrive from JSON, where an old run has no such key at all and a
    hand-edited one can hold a string. ``int(x or 0)`` turned both into a
    measured zero (P35).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def coverage_phrase(da_count, da_missing, short=False) -> str:
    """"mean of 7 of 10 ranking domains (3 unscored)" for one row.

    The denominator travels with the mean wherever it is printed, because a
    mean of three domains and a mean of ten read identically otherwise (P2,
    finding D-C-03). *short* gives the table-cell form ("7/10 (3 unscored)")
    — the same numbers from the same config file, for a column that cannot
    hold the sentence.
    """
    measured = _as_count(da_count)
    missing = _as_count(da_missing)
    if measured is None or missing is None:
        # A row from before coverage was recorded. Unknown, not zero: "0/0"
        # beside a real mean says the window was never measured, which is a
        # different and false claim (P35, finding F4).
        unknown = load_messages().get("coverage_unknown") or {}
        return _render(unknown.get("short" if short else "long"),
                       "—" if short else "coverage not recorded for this run")
    window = measured + missing
    phrases = load_messages().get(
        "coverage_short" if short else "coverage") or {}
    if not measured:
        key = "none"
    elif missing:
        key = "partial"
    else:
        key = "complete"
    if short:
        fallback = f"{measured}/{window}" if window else "—"
    else:
        fallback = (f"mean of {measured} of {window} ranking domains"
                    if window else "no ranking domain scored")
    return _render(phrases.get(key), fallback, measured=measured,
                   window=window, missing=missing)


def minima_cell(feas_record: dict) -> str:
    """The same five states as a table cell, from ``minima_cell`` wording.

    The cell used to be built here as f-strings and read "0 (0?)" — a bare
    figure in brackets and a trailing question mark with nothing saying what
    was being asked. On one keyword of the 2026-11-19 run that cell held the
    run's strongest evidence in the client's favour and no reader could have
    told. The words are editorial and live in ``feasibility_messages.yml``
    (2026-11-21); the sentence form is :func:`minima_phrase`, and both read
    the same keys so the table and the prose cannot disagree.
    """
    cells = load_messages().get("minima_cell") or {}
    min_da = feas_record.get("min_competitor_da")
    if min_da is None:
        return _render(cells.get("no_da"), "—")
    non_dir = feas_record.get("min_non_directory_da")
    n = _as_count(feas_record.get("da_count")) or 0
    known = _as_count(feas_record.get("entities_known")) or 0
    # Only some of the scored competitors had a resolved entity type, so the
    # non-directory figure stands over those and not over the window. Partial
    # classification is the normal outcome — a domain-only classification
    # returns "N/A" for anything matching no pattern — so the cell says how
    # many were typed rather than implying the figure covers all ten.
    partial = bool(known) and bool(n) and known < n
    values = dict(min_da=min_da, min_non_directory_da=non_dir,
                  known=known, n=n, unknown=max(n - known, 0))
    if non_dir is not None:
        key = "with_non_directory_partial" if partial else "with_non_directory"
        fallback = (f"{min_da} · non-dir {non_dir} ({known} of {n} typed)"
                    if partial else f"{min_da} · non-dir {non_dir}")
    elif known:
        key = "all_classified_directory" if partial else "all_directory"
        fallback = (f"{min_da} · all typed are directories "
                    f"({known} of {n} typed)" if partial
                    else f"{min_da} · all directories")
    else:
        key = "entities_unknown"
        fallback = f"{min_da} · non-dir not measured"
    return _render(cells.get(key), fallback, **values)


def minima_phrase(feas_record: dict, directory_types=None) -> str:
    """The rankability sentence the mean cannot carry, or "" when there is none.

    Five states, five sentences (``feasibility_messages.yml`` ``minima``): a
    non-directory minimum over a fully classified window, or over a partly
    classified one; every scored competitor a directory, or every *classified*
    one a directory with the rest unclassified; or no entity type resolved at
    all. These are different facts — "no directory ranks here", "nobody
    classified these pages" and "one of ten was classified and it was a
    directory" — and this review has found one reported as another five times
    (P1/P2). Spec: D6.1 / D-M-09, partial states added by D6's cold review.
    """
    min_da = feas_record.get("min_competitor_da")
    n = _as_count(feas_record.get("da_count"))
    if min_da is None or not n:
        return ""
    phrases = load_messages().get("minima") or {}
    names = list(directory_types or DEFAULT_DIRECTORY_ENTITY_TYPES)
    label = " / ".join(names) if names else "directory"
    non_dir = feas_record.get("min_non_directory_da")
    known = _as_count(feas_record.get("entities_known")) or 0
    # Every figure below a non-directory claim stands over the competitors
    # whose entity type was resolved, which is often fewer than the window.
    # Quoting it over the window asserts a classification nobody made.
    partial = bool(known) and known < n
    if non_dir is not None:
        key = "with_non_directory_partial" if partial else "with_non_directory"
        return _render(
            phrases.get(key),
            f"Weakest non-{label} competitor {non_dir}, of the {known} of {n} "
            f"scored competitors whose type was resolved; weakest of any kind "
            f"{min_da}.",
            min_da=min_da, min_non_directory_da=non_dir, n=n, known=known,
            unknown=max(n - known, 0), directory_types=label)
    if known:
        key = "all_classified_directory" if partial else "all_directory"
        return _render(
            phrases.get(key),
            f"All {known} of {n} scored competitors whose type was resolved "
            f"are a {label}; the weakest of the {n} scores {min_da}.",
            min_da=min_da, n=n, known=known, unknown=max(n - known, 0),
            directory_types=label)
    return _render(
        phrases.get("entities_unknown"),
        f"Weakest page holding a slot scores {min_da} over {n} scored "
        f"competitors; the {label} split is not measured.",
        min_da=min_da, n=n, directory_types=label)


def client_da_cell(client_da, source="") -> str:
    """The client's DA for a report cell, with its provenance when it has one.

    A config value printed bare reads as a measurement, and the reader then
    subtracts it from a measured competitor mean as though both were on one
    provider's scale — the fault D-M-05 records. ``client_da_source`` is on
    every row for this reason, and this is where it becomes visible.
    """
    if client_da is None:
        key = "not_measured"
    elif not str(source or "").strip():
        # No provenance on the row: a run written before it was recorded.
        # Rendering it bare asserts it was measured, which is the D-M-05
        # fault for every legacy report (finding F4).
        key = "unknown_source"
    elif str(source).startswith("operator override"):
        key = "override"
    elif str(source).startswith("config fallback"):
        key = "config_fallback"
    else:
        key = "measured"
    provider = str(source).split("unmeasured, ")[-1].rstrip(")") \
        if key == "config_fallback" else str(source)
    templates = load_messages().get("client_da") or {}
    fallbacks = {"not_measured": "not measured", "override": "{da} (override)",
                 "config_fallback": "{da} (config, not measured by {provider})",
                 "unknown_source": "{da} (source not recorded)",
                 "measured": "{da}"}
    return _render(templates.get(key), fallbacks[key],
                   da=client_da, provider=provider)


def no_measurement_text(provider, da_window) -> str:
    """Why this keyword has no verdict, in the words config gives.

    Three cases, deliberately not one sentence: no provider is an operator
    fix, an empty window is a fact about the keyword, and thin coverage is a
    number the reader should see.
    """
    templates = load_messages().get("no_measurement") or {}
    measured = getattr(da_window, "measured", 0) or 0
    window = getattr(da_window, "window", 0) or 0
    if not provider or provider == "none":
        key, fallback = "no_provider", (
            "No DA provider reachable — set DATAFORSEO_LOGIN/PASSWORD or "
            "MOZ_TOKEN and run again.")
    elif window == 0:
        key, fallback = "nothing_in_window", (
            f"No ranking competitor could be scored for this keyword "
            f"({provider} was queried).")
    else:
        key, fallback = "below_minimum", (
            f"Only {measured} of {window} ranking domain(s) have a DA record "
            f"from {provider}, below the {MIN_DA_FOR_VERDICT} a verdict needs.")
    return _render(templates.get(key), fallback, provider=provider,
                   measured=measured, window=window,
                   minimum=MIN_DA_FOR_VERDICT)


def resolve_client_da(client_domain, metrics_for_domain, provider,
                      config_value=None, override=None,
                      log_info=None, log_warning=None):
    """``(client_da, source)`` — where the client's own DA came from.

    Both sides of the gap must come off one scale. DataForSEO's backlink rank
    and Moz's Domain Authority are both 0-100 and are not the same number:
    the code's own worked example puts this client at 19 on DataForSEO against
    the 35 in ``config.yml``. Subtracting one from the other produced a gap
    that measured the difference between two vendors (D-M-05).

    Precedence: an explicit operator override wins, because it was asked for;
    then the live provider figure, looked up in the same batch as the
    competitors; then ``config.yml``, a fallback whose scale is unverified and
    which is labelled as such on every row. With no provider reachable the DA
    is ``None``, and :func:`compute_feasibility` then reports "Not Measured"
    rather than scoring live competitors against a constant.

    One definition for both producers: the in-pipeline pass in ``serp_audit``
    and the standalone ``run_feasibility`` pass had to agree about the client
    for the same reason they had to agree about the window (D-C-19).

    *metrics_for_domain* maps a bare domain to that domain's metrics dict, so
    this function does no I/O; *provider* is its name, or "none".

    Spec: docs/review_2026-11-04/PLAN_D2_null_is_not_zero.md#D2a.12-D2a.15
    Tests: tests/test_d2_null_is_not_zero.py::TestClientProvenance
    """
    info = log_info or (lambda *a: None)
    warn = log_warning or (lambda *a: None)

    if override is not None:
        info("Client DA: %s from an explicit override (overrides %s and the "
             "config value %s)", override, provider, config_value)
        return override, "operator override"

    measured = metrics_for_domain(domain_of(client_domain)) if client_domain else {}
    da = (measured or {}).get("da")
    if da is not None:
        fetched = str((measured or {}).get("fetched_at") or "")[:10]
        if config_value is not None and config_value != da:
            info("Client DA: %s measured by %s%s — the config value %s is not "
                 "used (it may be on another provider's scale)",
                 da, provider, f" on {fetched}" if fetched else "", config_value)
        return da, f"{provider}@{fetched}" if fetched else provider

    if not provider or provider == "none":
        warn("Client DA: no DA provider reachable, so the client's own "
             "authority was not measured; every keyword reads 'Not Measured' "
             "rather than being scored against the config value %s.",
             config_value)
        return None, "not measured (no provider)"

    warn("Client DA: %s returned no record for '%s'; falling back to the "
         "config value %s, whose scale against %s is unverified. Rows carry "
         "client_da_source so the gap is not read as like-for-like.",
         provider, client_domain, config_value, provider)
    return config_value, f"config fallback (unmeasured, {provider})"


class BatchCoverage(NamedTuple):
    """How much of a provider's answer carries an actual figure.

    *measured* counts the records whose ``da`` is a number; *records* counts
    the records returned at all; *asked* counts the targets sent.
    """

    measured: int
    records: int
    asked: int

    @property
    def unmeasured(self) -> int:
        """Records the provider answered about but holds no DA for."""
        return self.records - self.measured


def batch_coverage(metrics_by_target, asked=None) -> BatchCoverage:
    """Count the measured DA values in a provider's batch result.

    ``len(result)`` is not the number of DA figures: since review chunk D2 a
    target the provider answered about but holds no rank for is present with
    ``da: None`` (the presence says "asked and answered", the null says
    "no figure"). A caller that logs ``len(result)`` as "returned DA for N
    URLs", or gates on ``if not result``, reports measurements that do not
    exist and never warns on a batch that measured nothing (P2/P6).

    This is the one definition of that count, shared by both DA providers
    and both feasibility producers.
    """
    records = metrics_by_target or {}
    measured = sum(
        1 for v in records.values()
        if isinstance(v, dict) and v.get("da") is not None
    )
    return BatchCoverage(
        measured=measured,
        records=len(records),
        asked=len(records) if asked is None else len(asked),
    )


def with_client_url(urls, client_url):
    """*urls* plus the client's own URL, so one batch carries both sides.

    The client's DA has to come off the same provider, on the same scale, as
    the competitors it is subtracted from (D-M-05). Fetching it in the same
    batch is what makes that true, and the provider caches by URL, so it
    costs one row on the first keyword and nothing after. One definition for
    both producers, for the reason given on :func:`resolve_client_da`.
    """
    batch = list(urls or [])
    if client_url and client_url not in batch:
        batch.append(client_url)
    return batch


def client_da_from_batch(metrics_by_url, client_domain, provider,
                         config_value=None, override=None,
                         log_info=None, log_warning=None):
    """:func:`resolve_client_da` against a batch of metrics keyed by URL."""
    return resolve_client_da(
        client_domain,
        lambda d: next((m for u, m in (metrics_by_url or {}).items()
                        if domain_of(u) == d), {}),
        provider, config_value, override, log_info, log_warning)


def index_feasibility_by_keyword(feasibility_rows) -> dict:
    """Map keyword -> its primary feasibility row (pivot rows excluded).

    First-wins, so the primary ``A`` row is never overwritten by an AI-
    alternative ``A.1``/``A.2`` row for the same keyword. Every consumer of
    ``keyword_feasibility`` goes through this, because the last-wins dict
    comprehensions it replaces made §0/§1/§5c of the report disagree with the
    play router about the same keyword (finding D-C-19).
    """
    by_kw = {}
    for row in feasibility_rows or []:
        label = row.get("Query_Label") or row.get("query_label")
        if label == "P":
            continue  # pivot rows are not the primary keyword's verdict
        kw = row.get("Keyword") or row.get("keyword_text") or ""
        if kw and kw not in by_kw:
            by_kw[kw] = row
    return by_kw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Fallback only. Which entity types count as a *directory* for the
#: non-directory minimum — EDITORIAL, so the list lives in ``config.yml``
#: ``feasibility.directory_entity_types`` and this is the documented default.
#: A directory holding a top-10 slot is not evidence that a DA-35 clinic can
#: hold one, which is the whole point of reporting the minimum separately.
DEFAULT_DIRECTORY_ENTITY_TYPES = ("directory",)


def resolve_directory_entity_types(cfg: dict | None) -> tuple[str, ...]:
    """Resolve ``feasibility.directory_entity_types``; default when unusable."""
    block = ((cfg or {}).get("feasibility") or {})
    raw = block.get("directory_entity_types")
    if raw is None:
        return DEFAULT_DIRECTORY_ENTITY_TYPES
    if not isinstance(raw, (list, tuple)) or not all(
            isinstance(v, str) and v.strip() for v in raw):
        logging.warning(
            "feasibility.directory_entity_types is not a list of names (%r); "
            "using the default %s.", raw, list(DEFAULT_DIRECTORY_ENTITY_TYPES))
        return DEFAULT_DIRECTORY_ENTITY_TYPES
    return tuple(v.strip().lower() for v in raw)


# The keys :func:`competitor_minima` adds to every feasibility assessment.
# Named once because the alternative — each producer re-listing them — is how
# the coverage fields reached the JSON but not the database (finding F9, and
# again in D6's cold review). Every producer copies this set; a test asserts
# that each key reaches the row, the workbook and the database.
MINIMA_FIELDS = (
    "min_competitor_da",
    "max_competitor_da",
    "min_non_directory_da",
    "non_directory_count",
    "entities_known",
)


def competitor_minima(das, entities, directory_types=None) -> dict:
    """Return the minima the mean cannot show.

    The mean answers "how strong is this SERP on average"; the question a
    DA-35 nonprofit is actually asking is "does anything my size hold a slot
    here". A SERP of ``[92] + [18]*9`` has a mean of 25.4 and a SERP of
    ``[85]*5 + [12]*5`` a mean of 48.5, so the second reads as the harder page
    although five DA-12 pages demonstrably rank on it (D-M-09).

    ``min_non_directory_da`` is ``None`` when no competitor's entity type was
    resolved: "no directory ranks here" and "nobody classified these" are
    different facts, and reporting the second as the first is exactly the
    failure this review keeps finding (P1/P2). ``entities_known`` says which
    it is.
    """
    das = [d for d in (das or []) if d is not None]
    directory = set(directory_types or DEFAULT_DIRECTORY_ENTITY_TYPES)
    entities = list(entities or [])
    known = [(d, (e or "").lower()) for d, e in zip(das, entities) if e]
    non_dir = [d for d, e in known if e not in directory]
    return {
        "min_competitor_da": min(das) if das else None,
        "max_competitor_da": max(das) if das else None,
        "min_non_directory_da": min(non_dir) if non_dir else None,
        "non_directory_count": len(non_dir),
        "entities_known": len(known),
    }


def compute_feasibility(
    client_da: int,
    competitor_das,
    window: int | None = None,
    directory_types=None,
) -> dict:
    """Return a feasibility assessment for a keyword.

    Parameters
    ----------
    client_da:
        Domain Authority of the non-profit client (0–100).
    competitor_das:
        A :class:`DAWindow` from :func:`competitor_da_window`, or a plain list
        of DA values. An empty set means **no competitor DA was measured** for
        this keyword, and returns a ``status`` of ``"Not Measured"`` with all
        numeric fields ``None``. It used to return ``"Low Feasibility"``, which
        published a verdict — and a hyper-local pivot recommendation, and a
        Maps fetch to support it — from zero measurements (P1/P14: unknown is
        not a terminal negative). Callers still do not have to special-case
        missing data; they just no longer get a false negative.

        Fewer than :data:`MIN_DA_FOR_VERDICT` measured competitors is also
        ``"Not Measured"``: the mean and the gap are still reported, with
        ``da_count``/``da_missing`` saying what they rest on, but no verdict
        is published from them.
    window:
        How many competitors were considered, when *competitor_das* is a plain
        list. Ignored when it is a :class:`DAWindow`, which carries its own.

    Returns
    -------
    dict with keys:
        avg_serp_da          : float | None – mean DA of competitors
        client_da            : int          – the value passed in
        gap                  : float | None – avg_serp_da − client_da
        feasibility_score    : float | None – 0.0 (worst) … 1.0 (best), clamped
        feasibility_status   : str          – human-readable label
        da_count             : int          – competitors with a DA record;
                                              this IS the n the mean rests on
        da_missing           : int          – competitors with none
        min_competitor_da    : int | None   – weakest measured competitor
        max_competitor_da    : int | None   – strongest measured competitor
        min_non_directory_da : int | None   – weakest competitor that is not a
                                              directory, or None when no
                                              entity type was resolved
        non_directory_count  : int          – measured competitors known not to
                                              be directories
        entities_known       : int          – measured competitors whose entity
                                              type was resolved at all

    Examples
    --------
    >>> r = compute_feasibility(35, [40, 38, 52, 61, 45, 33, 27, 50, 44, 39])
    >>> r["gap"], r["feasibility_status"], r["da_count"]
    (7.9, 'Moderate Feasibility', 10)
    """
    if isinstance(competitor_das, DAWindow):
        das = list(competitor_das.das)
        missing = competitor_das.missing
        entities = list(competitor_das.entities or [])
    else:
        das = list(competitor_das or [])
        entities = []
        # With no window given, nothing is known to be missing. A caller that
        # wants honest coverage passes a DAWindow.
        missing = max(0, (window or len(das)) - len(das))

    minima = competitor_minima(das, entities, directory_types)

    if not das or client_da is None:
        return {
            "avg_serp_da": None,
            "client_da": client_da,
            "gap": None,
            "feasibility_score": None,
            "feasibility_status": NOT_MEASURED,
            "da_count": len(das),
            "da_missing": missing,
            **minima,
        }

    avg_serp_da = round(sum(das) / len(das), 1)
    gap = round(avg_serp_da - client_da, 1)
    # Clamped at both ends. The docstring has always said 0.0-1.0 and the
    # field is persisted to SQLite and the workbook, but a negative gap (the
    # client stronger than the mean) produced 1.47 and 1.5 in real runs
    # (D-M-24). A score above its own maximum is not a stronger result, it is
    # a broken scale; the gap itself carries the magnitude.
    score = round(min(1.0, max(0.0, 1.0 - gap / SCORE_NORMALISER)), 2)
    # The numbers stand; the verdict does not. Reporting the mean of two
    # domains beside "Low Feasibility" would read as a measurement of the
    # SERP, which it is not.
    status = (_gap_to_status(gap) if len(das) >= MIN_DA_FOR_VERDICT
              else NOT_MEASURED)

    return {
        "avg_serp_da": avg_serp_da,
        "client_da": client_da,
        "gap": gap,
        "feasibility_score": score,
        "feasibility_status": status,
        "da_count": len(das),
        "da_missing": missing,
        **minima,
    }


#: Fallback only. The list is EDITORIAL — a client serving a different market
#: widens or narrows it — so it lives in ``config.yml feasibility.pivotable_intents``
#: and this is the documented default used when config supplies none
#: (D-M-19 / D4.10; moved to config by that chunk's cold review, finding 2).
DEFAULT_PIVOTABLE_INTENTS = ("local", "transactional")

#: Back-compatible alias. Reads as a constant but is only the default; callers
#: that need the configured list pass ``pivotable_intents``.
PIVOTABLE_INTENTS = DEFAULT_PIVOTABLE_INTENTS


def resolve_pivotable_intents(cfg: dict | None) -> tuple[str, ...]:
    """Resolve ``feasibility.pivotable_intents``; default + warning when unusable."""
    raw = ((cfg or {}).get("feasibility") or {}).get("pivotable_intents")
    if raw is None:
        return DEFAULT_PIVOTABLE_INTENTS
    if not isinstance(raw, (list, tuple)) or not raw:
        logging.warning(
            "feasibility.pivotable_intents is not a non-empty list — using %s.",
            list(DEFAULT_PIVOTABLE_INTENTS))
        return DEFAULT_PIVOTABLE_INTENTS
    return tuple(str(v).strip().lower() for v in raw if str(v).strip())


#: Fallback only. The list is EDITORIAL and lives in ``serp_vocab.yml``
#: ``local_intent.markers``; this is the documented default used when a caller
#: supplies none (2026-11-21, found by running feasibility).
DEFAULT_LOCAL_INTENT_MARKERS = (
    "near me", "nearby", "near my", "close to me", "closest",
    "in my area", "around me", "walking distance",
)


def resolve_local_intent_markers(vocab: dict | None) -> tuple[str, ...]:
    """Resolve ``serp_vocab.yml local_intent.markers``; default + warning."""
    raw = ((vocab or {}).get("local_intent") or {}).get("markers")
    if raw is None:
        return DEFAULT_LOCAL_INTENT_MARKERS
    if not isinstance(raw, (list, tuple)) or not raw:
        logging.warning(
            "serp_vocab.yml local_intent.markers is not a non-empty list — "
            "using %s.", list(DEFAULT_LOCAL_INTENT_MARKERS))
        return DEFAULT_LOCAL_INTENT_MARKERS
    return tuple(str(v).strip().lower() for v in raw if str(v).strip())


def keyword_local_marker(keyword: str,
                         markers: tuple[str, ...] | None = None) -> str:
    """The local-intent phrase the keyword itself carries, or ``""``.

    Substring match on the lower-cased keyword. Returns the marker rather than
    a bool so the gate can record which phrase decided.
    """
    text = (keyword or "").strip().lower()
    if not text:
        return ""
    for marker in (markers or DEFAULT_LOCAL_INTENT_MARKERS):
        if marker and marker in text:
            return marker
    return ""


def pivot_base_keyword(keyword: str,
                       markers: tuple[str, ...] | None = None) -> tuple[str, str]:
    """The keyword with a TRAILING local marker removed, and the marker.

    A neighbourhood pivot replaces the searcher's "near me" with a named
    place, so the variant must be built on the keyword without it: the first
    run after the marker gate shipped produced "family of origin therapist
    near me West Vancouver", which nobody searches and which SerpAPI's Maps
    engine refused with a 400.

    Only a trailing marker is stripped. A marker in the middle of a keyword
    ("therapist near my house") cannot be removed without changing what is
    left, so the keyword is returned unchanged and the caller records that no
    strip happened rather than publishing a mangled phrase.
    """
    text = (keyword or "").strip()
    if not text:
        return "", ""
    lowered = text.lower()
    for marker in (markers or DEFAULT_LOCAL_INTENT_MARKERS):
        if marker and lowered.endswith(marker):
            base = text[:len(text) - len(marker)].strip(" -,")
            # Never return an empty keyword: a keyword that is nothing but the
            # marker ("near me") has no service to pivot.
            return (base or text), (marker if base else "")
    return text, ""


def _pivot_gate(serp_intent: dict | None,
                is_service_like: bool,
                pivotable_intents: tuple[str, ...] | None = None,
                *,
                keyword: str = "",
                local_intent_markers: tuple[str, ...] | None = None,
                ) -> tuple[bool, str]:
    """Is a neighbourhood pivot meaningful for this keyword, and on what basis?

    Spec: review_2026-11-04 D4.10 (D-M-19); keyword markers 2026-11-21.

    The gate was ``is_service_like`` alone — a token-list guess made from the
    keyword STRING by ``query_variants.is_service_like``. By the time this
    runs, the SERP itself has been classified, so the measured verdict decides
    and the guess is only the fallback for a keyword with no verdict. Returns
    (pivotable, which basis decided), so the caller can record it.

    A keyword that states local intent in its own words ("near me") is
    checked FIRST and permits the pivot whatever the SERP was classified as.
    The classified intent describes the page Google served; the marker is what
    the searcher asked for, and the two are different facts. Before this,
    "family of origin therapist near me" was refused a pivot as
    ``commercial_investigation`` and the report explained to the owner that
    proximity matters "only when the searcher wants a service in a place" —
    about a query that says near me. A marker only ever PERMITS a pivot, so a
    keyword with no marker is gated exactly as it was.
    """
    marker = keyword_local_marker(keyword, local_intent_markers)
    if marker:
        return True, f"keyword local marker ({marker})"
    pivotable = pivotable_intents or DEFAULT_PIVOTABLE_INTENTS
    si = serp_intent if isinstance(serp_intent, dict) else {}
    primary = si.get("primary_intent")
    components = si.get("mixed_components") or []

    if si.get("is_mixed") and components:
        return (any(c in pivotable for c in components),
                "serp_intent.mixed_components")
    if primary and primary != "mixed":
        return primary in pivotable, "serp_intent.primary_intent"
    # No verdict: too little of the page was classified. Fall back to the
    # keyword-string guess rather than refusing every pivot.
    return bool(is_service_like), "is_service_like (no SERP intent verdict)"


#: The prefix every "no pivot" status carries. The rest of the status names the
#: intent that refused it, so consumers must test the PREFIX, not one phrasing
#: (D4b cold review, finding 2).
NO_PIVOT_PREFIX = "No pivot — "


def is_no_pivot(pivot_status) -> bool:
    """True when a pivot_status says no pivot applies, whatever the intent named."""
    return str(pivot_status or "").startswith(NO_PIVOT_PREFIX)


def _refused_intent_phrase(serp_intent: dict | None, gate_source: str) -> str:
    """Name the intent that blocked the pivot, in words a reader can check.

    Spec: review_2026-11-04 D4.10 (D-M-19), cold-review finding 2.
    """
    si = serp_intent if isinstance(serp_intent, dict) else {}
    if gate_source == "serp_intent.mixed_components":
        parts = [str(c).replace("_", " ") for c in (si.get("mixed_components") or [])]
        return "mixed (" + ", ".join(parts) + ")" if parts else "mixed"
    if gate_source == "serp_intent.primary_intent":
        return str(si.get("primary_intent") or "unclassified").replace("_", " ")
    return "non-service (no SERP intent verdict — judged from the keyword text)"


def _market_composition_clause(entity_distribution: dict | None) -> str:
    """What the SERP actually shows, as a clause for the pivot explanation.

    Spec: review_2026-11-04 D4.10 (D-M-19)

    The explanation asserted "is currently dominated by high-authority
    directories" whatever the page held, so a SERP of ten low-authority
    clinics with a Low Feasibility verdict was reported as directory-
    dominated. The clause now describes the distribution, and says nothing
    about composition when there is no distribution to describe.
    """
    dist = entity_distribution if isinstance(entity_distribution, dict) else {}
    counts = {str(k): n for k, n in dist.items()
              if isinstance(n, (int, float)) and n > 0}
    total = sum(counts.values())
    if not total:
        return "is out of reach on domain authority alone"

    top_share = max(counts.values())
    leaders = sorted(k for k, n in counts.items() if n == top_share)
    share = top_share / total
    label = " and ".join(leaders) if len(leaders) <= 2 else "several entity types"

    if share >= 0.5 and len(leaders) == 1:
        return f"is dominated by {label} results ({top_share} of {total})"
    if share >= 0.5:
        return f"is led jointly by {label} ({top_share} of {total} each)"
    return (f"has no dominant entity type — {label} leads with "
            f"{top_share} of {total} results")


def generate_hyper_local_pivot(
    primary_keyword: str,
    non_profit_location: str,
    feasibility_results: dict,
    neighborhoods: list[str],
    strategy: Literal["first", "all", "random"] = "first",
    is_service_like: bool = True,
    serp_intent: dict | None = None,
    entity_distribution: dict | None = None,
    pivotable_intents: tuple[str, ...] | None = None,
    local_intent_markers: tuple[str, ...] | None = None,
) -> dict:
    """Suggest a hyper-local neighbourhood variant for a Low Feasibility keyword.

    When a city-wide keyword is dominated by high-authority directories the
    non-profit cannot match their DA.  Appending a specific neighbourhood
    (e.g. "Lonsdale") narrows the competitive set to locally-present businesses
    and activates Google's neighbourhood-intent ranking signals.

    A neighbourhood pivot only makes sense for **service-intent** keywords,
    where physical proximity substitutes for domain authority. For an
    informational query ("how does birth order affect personality") a
    neighbourhood variant is nonsense — nobody searches it that way, and
    ranking is not the game. Such keywords get NO pivot and NO neighbourhood
    variants; the strategy for them is content extractability, not geography
    (see the ``is_service_like`` parameter).

    Spec: seo_geo_review_20260704.md (chip B, B.1.b).

    Parameters
    ----------
    primary_keyword:
        The root service keyword, e.g. ``"Couples Counselling"``.
    non_profit_location:
        Broad location used in the original keyword, e.g. ``"North Vancouver"``.
        Used in the strategy explanation text only.
    feasibility_results:
        Dict containing at minimum ``"status"`` and ``"avg_competitor_da"``
        keys, as returned by :func:`compute_feasibility`.
    neighborhoods:
        Ordered list of neighbourhood names to use as pivot candidates.
        Sourced from ``config.yml → feasibility.neighborhoods``.
    is_service_like:
        Whether the keyword names a service (proximity can substitute for
        authority). Determined by the caller via
        ``query_variants.is_service_like`` reading the editorial
        ``service_like_tokens`` (serp_vocab.yml). Defaults to ``True`` so
        existing callers/tests keep their behaviour; the two pipeline callers
        pass it explicitly. When ``False`` no neighbourhood pivot is emitted.
    serp_intent:
        The keyword's measured ``serp_intent`` block. When it carries a
        verdict, that verdict decides the gate and ``is_service_like`` is
        only a fallback: the run has already classified this SERP from its
        own results, and a token guess from the keyword string should not
        overrule it (D-M-19 / D4.10). An intent in
        ``PIVOTABLE_INTENTS`` — or a mixed SERP with one of them among its
        components — is pivotable.
    local_intent_markers:
        The editorial phrases that state local intent in the keyword's own
        words (``serp_vocab.yml local_intent.markers``, resolved by
        ``resolve_local_intent_markers``). One of them in ``primary_keyword``
        permits the pivot whatever the SERP was classified as; a keyword
        carrying none is gated exactly as before. Defaults to
        ``DEFAULT_LOCAL_INTENT_MARKERS`` so existing callers keep working.
    entity_distribution:
        ``{entity_type: count}`` for the keyword's SERP, used to decide
        whether the explanation may say the page is directory-dominated. The
        sentence used to assert it unconditionally, so a page of ten
        low-authority clinics with a Low Feasibility verdict was reported as
        dominated by high-authority directories.
    strategy:
        How to pick the suggested neighbourhood:

        ``"first"`` *(default)* — deterministic, always picks ``neighborhoods[0]``.
        Use this in production so repeated runs on the same data yield the
        same report.

        ``"all"`` — ``suggested_keyword`` is the first variant; ``all_variants``
        contains every neighbourhood combination.

        ``"random"`` — non-deterministic pick.  Useful for demos; **do not**
        use as the pipeline default because it makes test assertions brittle.

    Returns
    -------
    dict with keys:
        original_keyword  : str
        pivot_status      : "Pivoting to Hyper-Local" | "Stay the course"
                            | "No pivot — <the intent that refused it>"
                            (test with ``is_no_pivot``, never by equality)
        suggested_keyword : str | None
        all_variants      : list[str]  – all neighbourhood combinations
                            (empty for informational keywords)
        strategy          : str        – human-readable explanation paragraph
        avg_competitor_da : float | None
        recommended_play  : str | None – SEAM for chip C: informational
                            keywords will carry an extraction-play here; this
                            function only stops the bogus geo pivot.

    Examples
    --------
    >>> result = generate_hyper_local_pivot(
    ...     "Couples Counselling", "North Vancouver",
    ...     {"status": "Low Feasibility", "avg_competitor_da": 52},
    ...     ["Lonsdale", "Edgemont Village"],
    ... )
    >>> result["suggested_keyword"]
    'Couples Counselling Lonsdale'
    >>> result["pivot_status"]
    'Pivoting to Hyper-Local'
    """
    # Accept both key conventions: compute_feasibility returns
    # feasibility_status/avg_serp_da while callers historically remapped to
    # status/avg_competitor_da (seo_geo_review C.10).
    status = feasibility_results.get("status") or feasibility_results.get("feasibility_status", "")
    avg_da = feasibility_results.get("avg_competitor_da")
    if avg_da is None:
        avg_da = feasibility_results.get("avg_serp_da")

    # Gate: a neighbourhood pivot only substitutes proximity for authority on
    # SERVICE-intent keywords. Informational keywords ("how does birth order
    # affect personality") must NOT get a pivot or neighbourhood variants —
    # ranking is not the game for them (B.1.b). No variants are built here.
    pivotable, gate_source = _pivot_gate(
        serp_intent, is_service_like, pivotable_intents,
        keyword=primary_keyword, local_intent_markers=local_intent_markers)
    if not pivotable:
        # The refusal names what decided it. It said "informational"
        # unconditionally, so a SERP measured `commercial_investigation` or
        # `navigational` was reported as informational — the same fault class
        # this gate was built to remove (D4b cold review, finding 2).
        refused_intent = _refused_intent_phrase(serp_intent, gate_source)
        return {
            "original_keyword": primary_keyword,
            "pivot_status": NO_PIVOT_PREFIX + refused_intent,
            "gate_source": gate_source,
            "suggested_keyword": None,
            "all_variants": [],
            "strategy": (
                f"{refused_intent.capitalize()} keyword — a neighbourhood pivot "
                "does not apply (proximity substitutes for authority only when "
                "the searcher wants a service in a place). Compete on content "
                "extractability, not geography."
            ),
            "avg_competitor_da": avg_da,
            # SEAM (chip C): the extraction_play recommendation slots in here.
            "recommended_play": None,
        }

    # The neighbourhood replaces the searcher's "near me" rather than sitting
    # beside it, so variants are built on the keyword without that phrase.
    pivot_base, stripped_marker = pivot_base_keyword(primary_keyword,
                                                     local_intent_markers)
    all_variants = [f"{pivot_base} {nb}" for nb in neighborhoods] if neighborhoods else []

    if status == NOT_MEASURED:
        # No verdict is not a verdict of feasible. This fell into the branch
        # below and answered an unmeasured keyword with "Current keyword is
        # feasible. No pivot required." — a claim in the opposite direction
        # from the data (P6/P14, finding F2). run_feasibility does not call
        # this for an unmeasured keyword at all; the branch is here because
        # serp_audit's in-pipeline pass does, and a caller that forgets must
        # not be able to publish the false sentence.
        return {
            "original_keyword": primary_keyword,
            "pivot_status": "Stay the course",
            # Every branch reports what decided the gate, so a caller can
            # count the pivots decided on a measured SERP without guessing
            # from the presence of a `serp_intent` block (cold review of
            # review chunk Y6, finding 1).
            "gate_source": gate_source,
            "suggested_keyword": None,
            "all_variants": all_variants,
            # What the variants were built on: the keyword without its
            # trailing local marker, which the neighbourhood replaces.
            "pivot_base_keyword": pivot_base,
            "stripped_local_marker": stripped_marker,
            "strategy": (
                "No feasibility verdict for this keyword — too little of the "
                "result page has a Domain Authority record to say whether a "
                "pivot is needed. Nothing here recommends staying or pivoting."
            ),
            "avg_competitor_da": avg_da,
            "recommended_play": None,
        }

    if status != "Low Feasibility" or not neighborhoods:
        return {
            "original_keyword": primary_keyword,
            "pivot_status": "Stay the course",
            "gate_source": gate_source,
            "suggested_keyword": None,
            "all_variants": all_variants,
            # What the variants were built on: the keyword without its
            # trailing local marker, which the neighbourhood replaces.
            "pivot_base_keyword": pivot_base,
            "stripped_local_marker": stripped_marker,
            "strategy": "Current keyword is feasible. No pivot required.",
            "avg_competitor_da": avg_da,
            "recommended_play": None,
        }

    # Pick neighbourhood
    if strategy == "random":
        chosen = _random.choice(neighborhoods)
    else:
        # "first" and "all" both default to the first entry
        chosen = neighborhoods[0]

    suggested = f"{pivot_base} {chosen}"

    da_display = f"{avg_da:.0f}" if avg_da is not None else "unknown"
    explanation = (
        f"The city-wide market for '{non_profit_location}' "
        f"{_market_composition_clause(entity_distribution)} "
        f"(Avg DA: {da_display}). "
        f"We recommend pivoting to '{chosen}' where you can compete on geographic "
        f"relevance rather than domain strength. "
        f"Google's neighbourhood-intent signals favour a practitioner physically "
        f"present in {chosen} over a national directory for a user searching in that area."
    )

    return {
        "original_keyword": primary_keyword,
        "pivot_status": "Pivoting to Hyper-Local",
        "gate_source": gate_source,
        "suggested_keyword": suggested,
        "all_variants": all_variants,
        # What the variants were built on: the keyword without its
        # trailing local marker, which the neighbourhood replaces.
        "pivot_base_keyword": pivot_base,
        "stripped_local_marker": stripped_marker,
        "strategy": explanation,
        "avg_competitor_da": avg_da,
        "recommended_play": None,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gap_to_status(gap: float) -> StatusLiteral:
    """Map a DA gap to a human-readable feasibility status."""
    if gap <= HIGH_FEASIBILITY_MAX_GAP:
        return "High Feasibility"
    if gap <= MODERATE_FEASIBILITY_MAX_GAP:
        return "Moderate Feasibility"
    return "Low Feasibility"
