"""Recommended-Play decision engine.

Purpose: Route a keyword's pre-computed SERP/feasibility signals to one of
         five "Recommended Play" verdicts (rank / extraction / reformat /
         local pivot / deprioritise).
Spec:    seo_geo_review_20260704.md — Part 4 priority summary; T.4
         ("rank-vs-citation divergence"). Foundation chip A.
Tests:   tests/test_play_routing.py

Google rank and AI-Overview citation are two SEPARATE scores. The extraction
layer already computes every signal needed to route this decision; this module
makes the call. Deterministic Python here only NORMALISES raw signals into
primitives — every routing decision lives in the editorial rule table
play_routing.yml. Edit the YAML, not this file, to change how plays are chosen.

Output (stored at keyword_profiles[kw]["recommended_play"]):
    {
        "play": str,            # rank_play | extraction_play | reformat_play |
                                #   local_pivot_play | deprioritize
        "label": str,           # human label from play_routing.yml
        "strategy_text": str,   # one-line strategy from play_routing.yml
        "evidence": {
            "matched_rule": {"index": int|None, "match": dict},
            "inputs_used": dict,  # the normalised signals routed on
        },
        "data_available": {"feasibility": bool, "serp_intent": bool, "aio": bool},
        "confidence": str,      # "high" | "low"
        "note": str | None,     # honesty note when an input was missing
    }
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import yaml


VALID_PLAYS = (
    "rank_play",
    "extraction_play",
    "reformat_play",
    "local_pivot_play",
    "deprioritize",
)

# Every field a rule's `match` block may key on. Any other key is a config error.
MATCHABLE_FIELDS = (
    "feasibility",
    "primary_intent",
    "is_mixed",
    "mixed_intent_strategy",
    "has_ai_overview",
    "client_ranks_but_not_cited",
    "is_service_like",
    "has_local_pack",
)

DEFAULT_ROUTING_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "play_routing.yml"
)


def load_play_routing(path: str | None = None) -> dict:
    """Load play_routing.yml. Validates schema; raises ValueError on malformed.

    Fails loudly (never silently returns a partial/empty table) so a broken
    editorial file can never route every keyword to an accidental default.
    """
    path = path or DEFAULT_ROUTING_PATH
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"play_routing.yml must be a mapping: {path}")

    plays = data.get("plays")
    if not isinstance(plays, dict) or not plays:
        raise ValueError(f"play_routing.yml missing non-empty 'plays' map: {path}")
    for play_id, play in plays.items():
        if not isinstance(play, dict):
            raise ValueError(f"play {play_id!r} must be a mapping")
        for key in ("label", "strategy_text"):
            if not isinstance(play.get(key), str) or not play.get(key).strip():
                raise ValueError(f"play {play_id!r} missing non-empty {key!r}")

    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"play_routing.yml 'rules' must be a non-empty list: {path}")

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or "play" not in rule or "match" not in rule:
            raise ValueError(f"rule {i} missing 'play' or 'match'")
        play_id = rule["play"]
        if play_id not in VALID_PLAYS:
            raise ValueError(
                f"rule {i} references unknown play {play_id!r}; "
                f"must be one of {VALID_PLAYS}"
            )
        if play_id not in plays:
            raise ValueError(f"rule {i} play {play_id!r} is not defined in 'plays'")
        match = rule["match"]
        if not isinstance(match, dict):
            raise ValueError(f"rule {i} 'match' must be a mapping")
        for key in match:
            if key not in MATCHABLE_FIELDS:
                raise ValueError(
                    f"rule {i} match uses unknown field {key!r}; "
                    f"must be one of {MATCHABLE_FIELDS}"
                )

    return data


def _normalize_feasibility(status: Any) -> str:
    """Map a feasibility_status label to a routing token.

    "High Feasibility" → high, "Moderate Feasibility" → moderate,
    "Low Feasibility" → low, anything unrecognised/absent → unknown.
    """
    if not status:
        return "unknown"
    s = str(status).strip().lower()
    if s.startswith("high"):
        return "high"
    if s.startswith("moderate"):
        return "moderate"
    if s.startswith("low"):
        return "low"
    return "unknown"


def _is_service_like(keyword: str, service_like_tokens: Iterable[str]) -> bool:
    """True if the keyword text contains a service_like_token (substring match).

    Mirrors query_variants.ai_query_alternatives — the project's existing
    service-detection convention.
    """
    kw = (keyword or "").lower()
    return any(str(tok).lower() in kw for tok in (service_like_tokens or ()))


def _rule_matches(match: dict, signals: dict) -> bool:
    """A rule matches when every non-'any' criterion equals the signal.

    A list criterion matches when the signal is a member of the list.
    """
    for key, expected in match.items():
        if expected == "any":
            continue
        actual = signals.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def compute_recommended_play(
    profile: dict,
    feasibility_row: dict | None = None,
    keyword: str = "",
    service_like_tokens: Iterable[str] = (),
    routing: dict | None = None,
) -> dict:
    """Compute the recommended_play verdict for one keyword profile.

    Args:
        profile: a keyword_profiles[kw] dict (must carry serp_intent,
            has_ai_overview, has_local_pack, aio_divergence, and — if computed —
            mixed_intent_strategy).
        feasibility_row: the keyword's row from data["keyword_feasibility"]
            (Query_Label != "P"), or None if no DA/feasibility data was fetched.
        keyword: the keyword text (used for service-like detection).
        service_like_tokens: serp_vocab.yml → service_like_tokens.
        routing: pre-loaded play_routing.yml dict. If None, loaded fresh.

    Returns the verdict dict documented at the top of this module. Absent data
    is stated (data_available/confidence/note), never faked.
    """
    if routing is None:
        routing = load_play_routing()
    plays = routing["plays"]
    rules = routing["rules"]

    profile = profile or {}
    si = profile.get("serp_intent") or {}
    divergence = profile.get("aio_divergence") or {}

    primary_intent = si.get("primary_intent")
    feas_status = (feasibility_row or {}).get("feasibility_status")

    signals = {
        "feasibility": _normalize_feasibility(feas_status),
        "primary_intent": primary_intent if primary_intent else "unknown",
        "is_mixed": bool(si.get("is_mixed")),
        "mixed_intent_strategy": profile.get("mixed_intent_strategy") or "none",
        "has_ai_overview": bool(profile.get("has_ai_overview")),
        "client_ranks_but_not_cited": bool(divergence.get("client_ranks_but_not_cited")),
        "is_service_like": _is_service_like(keyword, service_like_tokens),
        "has_local_pack": bool(profile.get("has_local_pack")),
    }

    # Honesty flags: which routing inputs were actually available.
    data_available = {
        "feasibility": feasibility_row is not None
        and signals["feasibility"] != "unknown",
        "serp_intent": primary_intent is not None,
        "aio": "has_ai_overview" in profile,
    }

    matched = None
    matched_index = None
    for i, rule in enumerate(rules):
        if _rule_matches(rule["match"], signals):
            matched = rule
            matched_index = i
            break

    if matched is not None:
        play_id = matched["play"]
        matched_rule = {"index": matched_index, "match": dict(matched["match"])}
    else:
        # Belt-and-suspenders: a well-formed table has a catch-all. If none
        # matched, fall back to deprioritize and say so in the note.
        play_id = "deprioritize"
        matched_rule = {"index": None, "match": {}}

    play_def = plays.get(play_id, {})

    # Assemble the honesty note from any missing input.
    missing_notes = []
    if not data_available["feasibility"]:
        missing_notes.append(
            "feasibility/DA data unavailable — routed on intent + AI-Overview only"
        )
    if not data_available["serp_intent"]:
        missing_notes.append(
            "SERP intent inconclusive (insufficient classified results)"
        )
    if matched is None:
        missing_notes.append("no routing rule matched — fell back to deprioritise")
    note = "; ".join(missing_notes) if missing_notes else None

    confidence = "high" if (
        data_available["feasibility"] and data_available["serp_intent"]
    ) else "low"

    return {
        "play": play_id,
        "label": play_def.get("label", play_id),
        "strategy_text": play_def.get("strategy_text", ""),
        "evidence": {
            "matched_rule": matched_rule,
            "inputs_used": signals,
        },
        "data_available": data_available,
        "confidence": confidence,
        "note": note,
    }
