"""SERP intent verdict computation.

Given the TOP-10 organic results for a keyword (each tagged with content_type
and entity_type by classifiers.py) plus local-pack presence and the
client/known-competitor identity of each URL, compute a deterministic intent
verdict using the rule table in intent_mapping.yml.

Output (stored at keyword_profiles[kw]["serp_intent"]):
    {
        "primary_intent": str | None,  # informational | commercial_investigation |
                                       # transactional | navigational | local |
                                       # "mixed" (when is_mixed=True) |
                                       # None (when classified_organic_url_count < 5)
        "intent_distribution": dict,   # INTEGER count per intent among classified
                                       # organic URLs (not fractions)
        "is_mixed": bool,              # True when no intent passes thresholds
        "mixed_components": list,      # intents with ≥2 URLs when is_mixed=True
        "confidence": str,             # high | medium | low — classification
                                       #   COVERAGE, not certainty; alias
                                       #   "classification_coverage"
        "intent_certainty": str,       # high | medium | low | not_measured
        "leading_intent_share": float, # leading intent's share, or None
        "evidence": {
            "organic_url_count": int,
            "classified_organic_url_count": int,
            "uncategorised_organic_url_count": int,
            "local_pack_present": bool,
            "local_pack_member_count": int,
        },
    }

Confidence rules (count-based, not ratio-based):
  - high   if classified_organic_url_count >= 8 AND organic_url_count >= 8
  - medium if classified_organic_url_count >= 5 AND organic_url_count >= 5
  - low    otherwise

When classified_organic_url_count < 5, primary_intent is None (insufficient
data). intent_distribution, is_mixed, and mixed_components are still populated
from what was classified.

The caller MUST cap organic_rows to the top 10 before calling compute_serp_intent.
This module does not enforce the cap — it trusts its input.

Domain judgment lives in intent_mapping.yml. Edit the YAML, not this file.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import yaml


VALID_INTENTS = (
    "informational",
    "commercial_investigation",
    "transactional",
    "navigational",
    "local",
    "uncategorised",
)

DEFAULT_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "intent_mapping.yml"
)

# Share thresholds for determining primary vs mixed intent, and for the
# certainty of the winning intent.
#
# `confidence_high` / `confidence_medium` are the share the leading intent must
# hold for the verdict to be called certain. Until D6.3 nothing read them: the
# only "confidence" the module produced was a count of classified URLs, so
# tuning either knob changed nothing and raising `max_urls_per_keyword` raised
# "confidence" across the board with no SERP having changed (D-C-17, D-M-10).
DEFAULT_THRESHOLDS = {
    "primary_share": 0.60,
    "fallback_share": 0.40,
    "fallback_runner_up_max": 0.20,
    "confidence_high": 0.80,
    "confidence_medium": 0.50,
}


#: What a rule may require of `page_read`. "unknown" is a real state, not a
#: synonym for "no": an analysis JSON written before this key existed says
#: nothing about whether the page was read, and a rule that infers intent
#: from the host alone must not fire on a row that never claimed the page was
#: unread (P1 — unknown is not a terminal value).
PAGE_READ_VALUES = ("yes", "no", "unknown", "any")

#: What a rule may require of `content_type_usable`.
CONTENT_TYPE_USABLE_VALUES = ("yes", "no", "any")

#: Fallback for `unusable_content_types` when the mapping file does not carry
#: it. A malformed or old file must not silently make every content type
#: usable, which would stop section 1b firing at all.
DEFAULT_UNUSABLE_CONTENT_TYPES = ("unknown", "other", "n/a", "not measured", "")


def load_mapping(path: str | None = None) -> dict:
    """Load intent_mapping.yml. Validates schema; raises ValueError on malformed."""
    path = path or DEFAULT_MAPPING_PATH
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError(f"intent_mapping.yml missing top-level 'rules': {path}")

    rules = data["rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"intent_mapping.yml 'rules' must be a non-empty list")

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or "match" not in rule or "intent" not in rule:
            raise ValueError(f"rule {i} missing 'match' or 'intent'")
        if rule["intent"] not in VALID_INTENTS:
            raise ValueError(
                f"rule {i} has invalid intent {rule['intent']!r}; "
                f"must be one of {VALID_INTENTS}"
            )
        match = rule["match"]
        for key in ("content_type", "entity_type", "local_pack", "domain_role"):
            if key not in match:
                raise ValueError(f"rule {i} match missing key {key!r}")
        # `page_read` is optional: a rule that omits it matches whether or not
        # the ranked page was read, which is what every rule written before
        # it existed means. Where it IS given it must be one of the three
        # states, so a typo cannot silently become a rule that never fires.
        if "page_read" in match and match["page_read"] not in PAGE_READ_VALUES:
            raise ValueError(
                f"rule {i} match has invalid page_read "
                f"{match['page_read']!r}; must be one of {PAGE_READ_VALUES}"
            )
        if ("content_type_usable" in match
                and match["content_type_usable"]
                not in CONTENT_TYPE_USABLE_VALUES):
            raise ValueError(
                f"rule {i} match has invalid content_type_usable "
                f"{match['content_type_usable']!r}; must be one of "
                f"{CONTENT_TYPE_USABLE_VALUES}"
            )

    return data


def _domain_role_for_url(
    link: str,
    client_domain: str,
    known_brand_domains: Iterable[str],
) -> str:
    """Compute domain_role for a single URL by substring match on the link."""
    link_lower = (link or "").lower()
    if client_domain and client_domain.lower() in link_lower:
        return "client"
    for brand in known_brand_domains or ():
        if brand and brand.lower() in link_lower:
            return "known_competitor"
    return "other"


def _page_read_state(row: dict) -> str:
    """Whether the ranked page itself was read, as one of PAGE_READ_VALUES.

    The caller sets ``page_read`` on the row. An analysis JSON written before
    the key existed has neither it nor a way to recover the answer, so the
    state is "unknown" and a rule keyed on "no" does not fire — the row keeps
    the treatment it had before this key existed.
    """
    value = row.get("page_read")
    if value in ("yes", "no"):
        return value
    return "unknown"


def _content_type_usable(content_type, mapping: dict) -> str:
    """"yes" / "no" — whether the page's own type can decide an intent.

    "no" covers both ways a result arrives with nothing to go on: the page was
    never read, so the type is a marker like "Not Measured", or it was read
    and the classifier could not type it ("other", "unknown"). The set is
    `unusable_content_types` at the head of `intent_mapping.yml` — editorial,
    and the one place the two cases are declared to be the same case.
    """
    unusable = mapping.get("unusable_content_types")
    if not isinstance(unusable, (list, tuple)):
        unusable = DEFAULT_UNUSABLE_CONTENT_TYPES
    text = str(content_type or "").strip().lower()
    for value in unusable:
        if text == str(value or "").strip().lower():
            return "no"
    return "yes"


def _matches_rule(rule_match: dict, url_attrs: dict) -> bool:
    """A rule matches if every non-'any' criterion equals the URL's attribute."""
    for key, expected in rule_match.items():
        if expected == "any":
            continue
        actual = url_attrs.get(key)
        if actual != expected:
            return False
    return True


def _classify_url_with_rule(url_attrs: dict, rules: list):
    """Walk rules top-to-bottom; first match wins.

    Returns ``(intent, rule)`` — the rule so the caller can tell WHY the row
    was classified. A rule that required ``page_read: "no"`` reached its
    intent from the host alone, without the ranked page's own evidence, and
    that difference has to survive into the coverage figures rather than be
    averaged into them.
    """
    for rule in rules:
        if _matches_rule(rule["match"], url_attrs):
            return rule["intent"], rule
    # Belt-and-suspenders: well-formed YAML always has a catch-all rule.
    return "uncategorised", None


def _is_host_inferred(rule) -> bool:
    """True when ``rule`` reached its intent from the host, not the page.

    That is any rule requiring the page's own type to be unusable: it decided
    on the host alone, so the row must not count toward classification
    coverage, which is a statement about the pages.
    """
    if not rule:
        return False
    match = rule.get("match") or {}
    return (match.get("content_type_usable") == "no"
            or match.get("page_read") == "no")


def _classify_url(url_attrs: dict, rules: list) -> str:
    """Walk rules top-to-bottom; first match wins. Returns intent string."""
    return _classify_url_with_rule(url_attrs, rules)[0]


def _bucket_coverage(classified_count: int, organic_count: int) -> str:
    """How much of the result page was classified — NOT how clear the intent is.

    high   if classified >= 8 AND organic >= 8
    medium if classified >= 5 AND organic >= 5
    low    otherwise

    This is a count, and the count is capped by ``enrichment.max_urls_per_keyword``:
    ranks below that get a content type only where ``url_pattern_rules.yml``
    matches. So it rises when the operator enriches more pages and says nothing
    about whether the SERP's intent is clear. It is reported as "classification
    coverage" for that reason (D-M-10); the certainty of the verdict is
    :func:`_bucket_certainty`, which is about the shares.

    The old name ``_bucket_confidence`` is kept as an alias because the output
    key is a published contract (JSON, workbook, brief prompts) — the words a
    reader sees changed; the field did not.
    """
    if classified_count >= 8 and organic_count >= 8:
        return "high"
    if classified_count >= 5 and organic_count >= 5:
        return "medium"
    return "low"


#: Back-compatible alias. Same function, honest name above.
_bucket_confidence = _bucket_coverage


def _bucket_certainty(primary_share: float | None, thresholds: dict) -> str:
    """How clearly one intent leads, from its share of the classified URLs.

    ``high`` at or above ``confidence_high``, ``medium`` at or above
    ``confidence_medium``, else ``low``; ``"not_measured"`` when nothing was
    classified, because a share of nothing is not a weak lead (P1).

    The share is over the **classified** URLs, not over the top 10, so it must
    be read beside the coverage: eight of ten unclassified and the remaining
    two agreeing is a share of 1.0 over a coverage of "low". The two figures
    are deliberately independent — one says how much of the page was read, the
    other how much of what was read agreed — and the report prints both. This
    where ``serp_intent.thresholds.confidence_high`` / ``confidence_medium``
    are read — before D6.3 they had no reader at all (D-C-17), so a user who
    raised either saw no change and no warning.
    """
    if primary_share is None:
        return "not_measured"
    high = float(thresholds.get("confidence_high",
                                DEFAULT_THRESHOLDS["confidence_high"]))
    medium = float(thresholds.get("confidence_medium",
                                  DEFAULT_THRESHOLDS["confidence_medium"]))
    if primary_share >= high:
        return "high"
    if primary_share >= medium:
        return "medium"
    return "low"


def _determine_primary(
    intent_counts: dict, classified_total: int, thresholds: dict
) -> tuple[str | None, bool]:
    """Apply primary/mixed thresholds. Returns (primary_intent, is_mixed).

    Returns (None, False) when classified_total < 5 (insufficient data).
    Returns ("mixed", True) when no single intent clears the thresholds.
    """
    if classified_total == 0:
        return (None, False)

    # Sort intents by count descending (uncategorised never competes for primary).
    competing = sorted(
        ((k, v) for k, v in intent_counts.items() if k != "uncategorised"),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not competing or competing[0][1] == 0:
        return (None, False)

    top_intent, top_count = competing[0]
    top_share = top_count / classified_total
    second_share = (competing[1][1] / classified_total) if len(competing) > 1 else 0.0

    if top_share >= thresholds["primary_share"]:
        return (top_intent, False)
    if (
        top_share >= thresholds["fallback_share"]
        and second_share <= thresholds["fallback_runner_up_max"]
    ):
        return (top_intent, False)
    return ("mixed", True)


def compute_serp_intent(
    organic_rows: list[dict],
    has_local_pack: bool,
    client_domain: str = "",
    known_brand_domains: Iterable[str] = (),
    local_pack_member_count: int = 0,
    mapping: dict | None = None,
    thresholds: dict | None = None,
) -> dict:
    """Compute the serp_intent block for one keyword.

    Args:
        organic_rows: TOP-10 organic results (caller must cap). Each row is a
            dict with "rank", "title", "source" or "link", "entity_type",
            "content_type". The len() of this list becomes organic_url_count.
        has_local_pack: True if SerpAPI returned a local_results block.
        client_domain: client's primary domain (e.g., "livingsystems.ca").
        known_brand_domains: iterable of competitor domains/brand strings.
        local_pack_member_count: number of entries in the local pack (0 if none).
        mapping: pre-loaded mapping dict (from load_mapping()). If None, loads
            from DEFAULT_MAPPING_PATH.
        thresholds: primary/mixed share thresholds. If None, DEFAULT_THRESHOLDS used.
    """
    if mapping is None:
        mapping = load_mapping()
    rules = mapping["rules"]
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    local_pack_value = "yes" if has_local_pack else "no"

    intent_counts = {intent: 0 for intent in VALID_INTENTS}
    organic_count = 0
    host_inferred_count = 0
    host_inferred_by_state: dict[str, int] = {}

    for row in organic_rows or []:
        organic_count += 1
        link_or_source = row.get("link") or row.get("source") or ""
        url_attrs = {
            "content_type": row.get("content_type") or "unknown",
            "entity_type": row.get("entity_type") or "unknown",
            "local_pack": local_pack_value,
            "domain_role": _domain_role_for_url(
                link_or_source, client_domain, known_brand_domains
            ),
            # A row that does not carry the key says nothing about whether
            # the page was read, which is not the same as saying it was not.
            "page_read": _page_read_state(row),
            # Whether the page's own type can decide an intent. Section 1b
            # gates on this rather than on the fetch, so a page read as
            # "other" and a page never read are treated alike.
            "content_type_usable": _content_type_usable(
                row.get("content_type"), mapping),
        }
        intent, rule = _classify_url_with_rule(url_attrs, rules)
        intent_counts[intent] += 1
        if intent != "uncategorised" and _is_host_inferred(rule):
            host_inferred_count += 1
            # Which unread state this row had, so the report's "the rest were
            # not classified because…" causes can subtract exactly the rows
            # that were unread AND still classified, instead of counting them
            # on both sides of its own arithmetic.
            state = str(row.get("fetch_state") or "").strip().lower()
            if state:
                host_inferred_by_state[state] = (
                    host_inferred_by_state.get(state, 0) + 1)

    classified_total = sum(
        v for k, v in intent_counts.items() if k != "uncategorised"
    )
    uncategorised_count = intent_counts["uncategorised"]

    # intent_distribution: INTEGER counts per intent bucket (not fractions).
    # uncategorised is excluded — it is not a "classified" intent.
    distribution = {
        intent: intent_counts[intent]
        for intent in VALID_INTENTS
        if intent != "uncategorised"
    }

    # primary_intent is None when classified_total < 5 (insufficient data).
    if classified_total < 5:
        primary_intent = None
        is_mixed = False
    else:
        primary_intent, is_mixed = _determine_primary(intent_counts, classified_total, th)

    # mixed_components: intents with ≥2 URLs when no single intent wins.
    if is_mixed:
        mixed_components = sorted(
            intent for intent in VALID_INTENTS
            if intent != "uncategorised" and intent_counts.get(intent, 0) >= 2
        )
    else:
        mixed_components = []

    # Coverage stays a statement about the PAGES, so a host-inferred intent
    # does not raise it. The verdict above may rest on host inference; the
    # coverage figure beside it must still say how much of the result page
    # was actually read, or the report would claim evidence it never had.
    page_evidence_classified = classified_total - host_inferred_count
    coverage = _bucket_coverage(page_evidence_classified, organic_count)

    # The leading intent's share of the classified URLs. `primary_intent` is
    # None below five classified, and "mixed" when no intent clears the
    # thresholds; in both cases the leader's share is still the honest input to
    # certainty, so it is taken from the distribution rather than from the
    # verdict word.
    leader_share = None
    if classified_total:
        leader = max(
            (v for k, v in intent_counts.items() if k != "uncategorised"),
            default=0)
        leader_share = round(leader / classified_total, 3)
    certainty = _bucket_certainty(leader_share, th)

    return {
        "primary_intent": primary_intent,
        "intent_distribution": distribution,
        "is_mixed": is_mixed,
        "mixed_components": mixed_components,
        # `confidence` is the published key and stays. It has always been the
        # classification coverage, and `classification_coverage` is its honest
        # name — the same value, so no consumer has to choose (D-M-10).
        "confidence": coverage,
        "classification_coverage": coverage,
        # New in D6.3: how clearly one intent leads, read from
        # serp_intent.thresholds.confidence_high / confidence_medium.
        "intent_certainty": certainty,
        # The LEADING intent's share, which is the primary intent only when
        # one intent carried the verdict: it is computed even when the verdict
        # was "mixed" or withheld for too little classification, so naming it
        # after the primary intent invited the reader to attribute it to a
        # word the figure does not describe (D6 cold review).
        "leading_intent_share": leader_share,
        "evidence": {
            "organic_url_count": organic_count,
            "classified_organic_url_count": classified_total,
            "uncategorised_organic_url_count": uncategorised_count,
            # Of the classified, how many carried the ranked page's own
            # evidence and how many were reached from the host alone because
            # the page could not be read. The two always sum to
            # classified_organic_url_count.
            "page_evidence_classified_count": page_evidence_classified,
            "host_inferred_classified_count": host_inferred_count,
            "host_inferred_by_fetch_state": dict(host_inferred_by_state),
            "local_pack_present": has_local_pack,
            "local_pack_member_count": local_pack_member_count,
        },
    }
