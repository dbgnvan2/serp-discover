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

import random as _random
from typing import Callable, Literal
from urllib.parse import urlparse

from shared_config import load_shared_config


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
    )

HIGH_FEASIBILITY_MAX_GAP, MODERATE_FEASIBILITY_MAX_GAP, SCORE_NORMALISER = load_thresholds()

StatusLiteral = Literal["High Feasibility", "Moderate Feasibility", "Low Feasibility"]


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


def domain_of(url: str) -> str:
    """Return the bare, lower-cased domain of *url*, ``www.`` removed.

    ``urlparse`` puts everything in ``path`` when there is no ``//``, so a
    scheme-less key such as ``"example.com/page"`` (the format the Moz cache
    writes) would otherwise yield an empty domain. ``removeprefix`` is correct
    where ``lstrip("www.")`` is not: ``lstrip`` strips *characters*, so it
    turns "worldbank.org" into "orldbank.org".
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url if "//" in url else "//" + url)
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def select_competitor_das(
    ranked_urls: list[str],
    da_for_url: Callable[[str], object],
    client_domain: str = "",
    top_n: int = TOP_N_FOR_FEASIBILITY,
) -> list:
    """Return the competitor DA values the feasibility gap is measured over.

    *ranked_urls* must already be in rank order, best first; since review
    chunk D1 the merged SERP rows are, because ``Rank`` is absolute. The
    window is the first *top_n* URLs **of the SERP**, and the client's own
    domain is then dropped from that window — so a keyword where the client
    ranks 4th is scored against the 9 competitors in its true top 10, not
    against 10 competitors drawn from further down the page.

    *da_for_url* returns the DA for one URL, or ``None`` when that URL has no
    DA record. ``None`` is not zero: an unscored domain is left out of the
    average rather than counted as a DA of 0 (finding D-C-04).
    """
    client = domain_of(client_domain) if client_domain else ""
    das = []
    for url in (ranked_urls or [])[:top_n]:
        if not url or url == "N/A":
            continue
        if client and domain_of(url) == client:
            continue
        da = da_for_url(url)
        if da is not None:
            das.append(da)
    return das


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

def compute_feasibility(
    client_da: int,
    competitor_das: list[int],
) -> dict:
    """Return a feasibility assessment for a keyword.

    Parameters
    ----------
    client_da:
        Domain Authority of the non-profit client (0–100).
    competitor_das:
        DA values for the top-10 organic results.  An empty list returns a
        ``status`` of ``"Low Feasibility"`` with all numeric fields set to
        ``None`` so callers don't have to special-case missing data.

    Returns
    -------
    dict with keys:
        avg_serp_da       : float | None  – mean DA of competitors
        client_da         : int           – the value passed in
        gap               : float | None  – avg_serp_da − client_da
        feasibility_score : float | None  – 0.0 (worst) … 1.0 (best)
        feasibility_status: str           – human-readable label

    Examples
    --------
    >>> compute_feasibility(35, [40, 38, 52, 61, 45, 33, 27, 50, 44, 39])
    {'avg_serp_da': 42.9, 'client_da': 35, 'gap': 7.9,
     'feasibility_score': 0.74, 'feasibility_status': 'Moderate Feasibility'}
    """
    if not competitor_das:
        return {
            "avg_serp_da": None,
            "client_da": client_da,
            "gap": None,
            "feasibility_score": None,
            "feasibility_status": "Low Feasibility",
        }

    avg_serp_da = round(sum(competitor_das) / len(competitor_das), 1)
    gap = round(avg_serp_da - client_da, 1)
    status = _gap_to_status(gap)
    score = round(max(0.0, 1.0 - gap / SCORE_NORMALISER), 2)

    return {
        "avg_serp_da": avg_serp_da,
        "client_da": client_da,
        "gap": gap,
        "feasibility_score": score,
        "feasibility_status": status,
    }


def generate_hyper_local_pivot(
    primary_keyword: str,
    non_profit_location: str,
    feasibility_results: dict,
    neighborhoods: list[str],
    strategy: Literal["first", "all", "random"] = "first",
    is_service_like: bool = True,
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
                            | "No pivot — informational"
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
    if not is_service_like:
        return {
            "original_keyword": primary_keyword,
            "pivot_status": "No pivot — informational",
            "suggested_keyword": None,
            "all_variants": [],
            "strategy": (
                "Informational keyword — a neighbourhood pivot does not apply "
                "(nobody searches an informational question with a neighbourhood). "
                "Compete on content extractability, not geography."
            ),
            "avg_competitor_da": avg_da,
            # SEAM (chip C): the extraction_play recommendation slots in here.
            "recommended_play": None,
        }

    all_variants = [f"{primary_keyword} {nb}" for nb in neighborhoods] if neighborhoods else []

    if status != "Low Feasibility" or not neighborhoods:
        return {
            "original_keyword": primary_keyword,
            "pivot_status": "Stay the course",
            "suggested_keyword": None,
            "all_variants": all_variants,
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

    suggested = f"{primary_keyword} {chosen}"

    da_display = f"{avg_da:.0f}" if avg_da is not None else "unknown"
    explanation = (
        f"The city-wide market for '{non_profit_location}' is currently dominated by "
        f"high-authority directories (Avg DA: {da_display}). "
        f"We recommend pivoting to '{chosen}' where you can compete on geographic "
        f"relevance rather than domain strength. "
        f"Google's neighbourhood-intent signals favour a practitioner physically "
        f"present in {chosen} over a national directory for a user searching in that area."
    )

    return {
        "original_keyword": primary_keyword,
        "pivot_status": "Pivoting to Hyper-Local",
        "suggested_keyword": suggested,
        "all_variants": all_variants,
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
