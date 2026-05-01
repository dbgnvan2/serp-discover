"""SERP intent verdict computation.

Given the organic results for a keyword (each tagged with content_type and
entity_type by classifiers.py) plus local-pack presence and the client/known-
competitor identity of each URL, compute a deterministic intent verdict using
the rule table in intent_mapping.yml.

Output (stored at keyword_profiles[kw]["serp_intent"]):
    {
        "primary_intent": str,        # informational | commercial_investigation |
                                      # transactional | navigational | local
        "intent_distribution": dict,  # share per intent among CLASSIFIED URLs
        "is_mixed": bool,             # True when no intent passes thresholds
        "confidence": str,            # high | medium | low
        "evidence": {
            "total_url_count": int,
            "classified_url_count": int,
            "uncategorised_count": int,
            "intent_counts": dict,    # raw counts including uncategorised
        },
    }

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

# Fallback thresholds if config doesn't supply them. Spec defaults:
#   - primary share ≥ 0.60  → that intent is primary
#   - else, top share ≥ 0.40 AND second share ≤ 0.20 → that intent is primary
#   - else → mixed (primary = highest count, is_mixed = True)
#   - confidence: classified ratio ≥ 0.80 = high, ≥ 0.50 = medium, else low
DEFAULT_THRESHOLDS = {
    "primary_share": 0.60,
    "fallback_share": 0.40,
    "fallback_runner_up_max": 0.20,
    "confidence_high": 0.80,
    "confidence_medium": 0.50,
}


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


def _matches_rule(rule_match: dict, url_attrs: dict) -> bool:
    """A rule matches if every non-'any' criterion equals the URL's attribute."""
    for key, expected in rule_match.items():
        if expected == "any":
            continue
        actual = url_attrs.get(key)
        if actual != expected:
            return False
    return True


def _classify_url(url_attrs: dict, rules: list) -> str:
    """Walk rules top-to-bottom; first match wins. Returns intent string."""
    for rule in rules:
        if _matches_rule(rule["match"], url_attrs):
            return rule["intent"]
    # Final safety net: if no rule (including catch-all) matched, treat as
    # uncategorised. The well-formed YAML always has a catch-all so this is
    # belt-and-suspenders.
    return "uncategorised"


def _bucket_confidence(classified_share: float, thresholds: dict) -> str:
    if classified_share >= thresholds["confidence_high"]:
        return "high"
    if classified_share >= thresholds["confidence_medium"]:
        return "medium"
    return "low"


def _determine_primary(
    intent_counts: dict, classified_total: int, thresholds: dict
) -> tuple[str, bool]:
    """Apply primary/mixed thresholds. Returns (primary_intent, is_mixed)."""
    if classified_total == 0:
        return ("uncategorised", False)

    # Sort intents by count descending (excluding uncategorised; it never
    # competes for primary).
    competing = sorted(
        ((k, v) for k, v in intent_counts.items() if k != "uncategorised"),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not competing or competing[0][1] == 0:
        return ("uncategorised", False)

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
    return (top_intent, True)


def compute_serp_intent(
    organic_rows: list[dict],
    has_local_pack: bool,
    client_domain: str = "",
    known_brand_domains: Iterable[str] = (),
    mapping: dict | None = None,
    thresholds: dict | None = None,
) -> dict:
    """Compute the serp_intent block for one keyword.

    Args:
        organic_rows: list of {"rank", "title", "source", "entity_type",
            "content_type", ...}. Either 'source' or 'link' must identify the
            URL/domain for client/competitor matching; we accept both keys.
        has_local_pack: True if SerpAPI returned a `local_results` block.
        client_domain: client's primary domain (e.g., "livingsystems.ca").
        known_brand_domains: iterable of competitor domains/brand strings.
        mapping: pre-loaded mapping dict (from load_mapping()). If None, load
            from DEFAULT_MAPPING_PATH.
        thresholds: thresholds dict. If None, DEFAULT_THRESHOLDS used.
    """
    if mapping is None:
        mapping = load_mapping()
    rules = mapping["rules"]
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    local_pack_value = "yes" if has_local_pack else "no"

    intent_counts = {intent: 0 for intent in VALID_INTENTS}
    total = 0

    for row in organic_rows or []:
        total += 1
        link_or_source = row.get("link") or row.get("source") or ""
        url_attrs = {
            "content_type": row.get("content_type") or "unknown",
            "entity_type": row.get("entity_type") or "unknown",
            "local_pack": local_pack_value,
            "domain_role": _domain_role_for_url(
                link_or_source, client_domain, known_brand_domains
            ),
        }
        intent = _classify_url(url_attrs, rules)
        intent_counts[intent] += 1

    classified_total = sum(
        v for k, v in intent_counts.items() if k != "uncategorised"
    )
    uncategorised_count = intent_counts["uncategorised"]

    # Distribution among classified URLs only (uncategorised excluded).
    distribution = {}
    if classified_total > 0:
        for intent in VALID_INTENTS:
            if intent == "uncategorised":
                continue
            distribution[intent] = intent_counts[intent] / classified_total
    else:
        for intent in VALID_INTENTS:
            if intent == "uncategorised":
                continue
            distribution[intent] = 0.0

    primary_intent, is_mixed = _determine_primary(intent_counts, classified_total, th)

    classified_share = (classified_total / total) if total else 0.0
    confidence = _bucket_confidence(classified_share, th)

    return {
        "primary_intent": primary_intent,
        "intent_distribution": distribution,
        "is_mixed": is_mixed,
        "confidence": confidence,
        "evidence": {
            "total_url_count": total,
            "classified_url_count": classified_total,
            "uncategorised_count": uncategorised_count,
            "intent_counts": dict(intent_counts),
        },
    }
