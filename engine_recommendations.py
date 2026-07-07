#!/usr/bin/env python3
"""engine_recommendations.py — per-engine moves + platform prioritisation.

Spec: yoast_geo_upgrade_spec_v1.md#Y.10 (decision gate Y-D9).

Because citation optimisation does NOT transfer across AI answer engines (see
the spec's "Empirical basis" §1–2), a single set of recommendations is wrong for
a multi-engine world: ChatGPT rewards encyclopedic/consensus content and cites
few sources; Perplexity rewards fresh, forum-referenced content and cites many;
Gemini mirrors Google's index; Claude favours structured depth. This module
emits, for each ENABLED engine, "what to change here" by joining the client's
per-engine results (AIVI, leaderboard rank, citation categories) to the editorial
``engine_profiles.yml`` — NO engine advice is hardcoded in Python (Spec Y.10.1).

It also emits a platform-prioritisation recommendation: the enabled engines
ranked by a documented, config-weighted blend of (a) current gap/low-AIVI
opportunity, (b) engine reach tier, and (c) referral-click tier — with the
audience-source caveat stated in prose and the whole thing labelled indicative
(Spec Y.10.3). Deterministic; no LLM (design principle 1).
"""
from __future__ import annotations

import logging
import os

import yaml

logger = logging.getLogger(__name__)

ENGINE_PROFILES_FILE = "engine_profiles.yml"

#: Ordinal tier → normalised 0–1 weight for the prioritisation blend.
_TIER_SCORE = {"high": 1.0, "medium": 0.5, "low": 0.2}

#: Default prioritisation weights (fallback when config supplies none/invalid).
DEFAULT_PRIORITY_WEIGHTS = {"opportunity": 0.5, "reach": 0.3, "referral": 0.2}

_CAVEAT = (
    "*Retrieval backends shift over time and these figures are indicative "
    "(mostly vendor-reported); a win on one engine does not transfer to "
    "another. Treat this as guidance and re-measure each run.*"
)


def load_engine_profiles(path: str = ENGINE_PROFILES_FILE) -> dict:
    """Load ``engine_profiles.yml`` → ``{engine_key: profile_dict}``.

    A missing or malformed file warns and returns ``{}`` (no crash) — the
    caller then reports that per-engine advice is unavailable (principle 3).
    """
    if not os.path.exists(path):
        logger.warning("engine_profiles.yml not found at %s — no per-engine advice.", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Could not parse engine_profiles.yml: %s", exc)
        return {}
    engines = data.get("engines")
    if not isinstance(engines, dict):
        logger.warning("engine_profiles.yml has no 'engines' mapping.")
        return {}
    return engines


def resolve_priority_weights(prioritization_config: dict | None) -> dict:
    """Resolve the prioritisation blend weights, falling back to defaults.

    A missing block, non-numeric/negative weight, or zero sum falls back to the
    documented defaults with a warning. Weights normalise to sum 1.
    """
    raw = (prioritization_config or {}).get("weights")
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("engine_prioritization.weights is not a mapping — using defaults.")
        return dict(DEFAULT_PRIORITY_WEIGHTS)
    weights: dict[str, float] = {}
    for key in DEFAULT_PRIORITY_WEIGHTS:
        value = raw.get(key)
        try:
            weights[key] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "engine_prioritization.weights.%s missing/non-numeric — using defaults.", key)
            return dict(DEFAULT_PRIORITY_WEIGHTS)
        if weights[key] < 0:
            logger.warning("engine_prioritization.weights.%s negative — using defaults.", key)
            return dict(DEFAULT_PRIORITY_WEIGHTS)
    total = sum(weights.values())
    if total <= 0:
        logger.warning("engine_prioritization.weights sum to zero — using defaults.")
        return dict(DEFAULT_PRIORITY_WEIGHTS)
    return {key: weights[key] / total for key in DEFAULT_PRIORITY_WEIGHTS}


def _tier_value(tier: str | None) -> float:
    return _TIER_SCORE.get(str(tier or "").strip().lower(), 0.0)


def engine_recommendations(enabled_engines: list[str], profiles: dict,
                           per_engine_results: dict | None = None) -> list[dict]:
    """Per-engine "what to change here", sourced from engine_profiles.yml.

    ``per_engine_results`` maps engine → ``{aivi, client_rank, citation_categories}``
    (all optional). Only ENABLED engines with a profile appear; a disabled
    engine produces no recommendation (Spec Y.10.3). Each recommendation echoes
    the editorial ``recommended_content_moves`` verbatim (Spec Y.10.1 — nothing
    hardcoded here) plus the engine's context (backend, source_bias) and the
    client's current standing for that engine.

    Returns a list of ``{engine, display_name, retrieval_backend, source_bias,
    avg_citations, avg_citations_asof, moves, aivi, client_rank, confidence}``.
    """
    per_engine_results = per_engine_results or {}
    out: list[dict] = []
    for engine in enabled_engines:
        profile = profiles.get(engine)
        if not profile:
            logger.warning("No engine_profiles.yml block for enabled engine %r.", engine)
            continue
        result = per_engine_results.get(engine, {}) or {}
        out.append({
            "engine": engine,
            "display_name": profile.get("display_name", engine),
            "retrieval_backend": profile.get("retrieval_backend", ""),
            "source_bias": list(profile.get("source_bias") or []),
            "avg_citations": profile.get("avg_citations"),
            "avg_citations_asof": profile.get("avg_citations_asof"),
            # Moves come straight from the editorial file — never invented here.
            "moves": list(profile.get("recommended_content_moves") or []),
            "aivi": result.get("aivi"),
            "client_rank": result.get("client_rank"),
            "citation_categories": list(result.get("citation_categories") or []),
            "confidence": str(profile.get("confidence") or "").strip(),
        })
    return out


def prioritize_engines(enabled_engines: list[str], profiles: dict,
                       per_engine_aivi: dict | None,
                       weights: dict | None = None) -> list[dict]:
    """Rank enabled engines by the documented config-weighted blend (Spec Y.10.2).

    Blend of three normalised 0–1 signals:
      * **opportunity** = (100 - AIVI) / 100 — a low current AIVI is a high
        opportunity. Missing AIVI ⇒ treated as the maximum opportunity (1.0),
        since an unmeasured engine is all upside.
      * **reach** = reach_tier mapped high/medium/low → 1.0/0.5/0.2.
      * **referral** = referral_click_tier mapped the same way.

    Returns a list of ``{engine, display_name, priority_score, opportunity,
    reach, referral}`` sorted by ``priority_score`` desc, ties broken by engine
    name (deterministic). Only enabled engines with a profile are ranked.
    """
    weights = weights or dict(DEFAULT_PRIORITY_WEIGHTS)
    per_engine_aivi = per_engine_aivi or {}
    scored: list[dict] = []
    for engine in enabled_engines:
        profile = profiles.get(engine)
        if not profile:
            continue
        aivi_val = per_engine_aivi.get(engine)
        opportunity = 1.0 if aivi_val is None else max(0.0, min(1.0, (100.0 - float(aivi_val)) / 100.0))
        reach = _tier_value(profile.get("reach_tier"))
        referral = _tier_value(profile.get("referral_click_tier"))
        priority = (
            weights.get("opportunity", 0.0) * opportunity
            + weights.get("reach", 0.0) * reach
            + weights.get("referral", 0.0) * referral
        )
        scored.append({
            "engine": engine,
            "display_name": profile.get("display_name", engine),
            "priority_score": round(priority, 4),
            "opportunity": round(opportunity, 4),
            "reach": round(reach, 4),
            "referral": round(referral, 4),
        })
    scored.sort(key=lambda r: (-r["priority_score"], r["engine"]))
    return scored


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

def render_engine_recommendations_section(recommendations: list[dict],
                                          prioritization: list[dict]) -> list[str]:
    """Render the per-engine "what to change here" + prioritisation list.

    Each carries the "backends shift; re-measure" caveat (Spec Y.10.4).
    """
    out: list[str] = []
    out.append("## Per-engine recommendations (optimisation does not transfer)")
    out.append(
        "Because AI answer engines retrieve from different backends with "
        "different source biases, the highest-value change differs per engine — "
        "there is no single set of moves. The advice below is joined from the "
        "editorial `engine_profiles.yml`; each engine's block is where it is "
        "tuned."
    )
    out.append("")

    if not recommendations:
        out.append("*No enabled engine has a profile in `engine_profiles.yml` — "
                   "per-engine advice unavailable.*")
        out.append("")
    for rec in recommendations:
        out.append(f"### {rec['display_name']} — what to change here")
        standing = []
        if rec.get("aivi") is not None:
            standing.append(f"current AIVI {rec['aivi']:.1f}/100")
        if rec.get("client_rank") is not None:
            standing.append(f"leaderboard rank #{rec['client_rank']}")
        if standing:
            out.append(f"*Client standing here: {', '.join(standing)}.*")
        backend = rec.get("retrieval_backend")
        bias = ", ".join(rec.get("source_bias") or [])
        avg = rec.get("avg_citations")
        asof = rec.get("avg_citations_asof")
        ctx_bits = []
        if backend:
            ctx_bits.append(f"retrieves from {backend}")
        if bias:
            ctx_bits.append(f"favours {bias}")
        if avg is not None:
            ctx_bits.append(f"~{avg} citations/answer (indicative, {asof})")
        if ctx_bits:
            out.append(f"Engine profile: {'; '.join(ctx_bits)}.")
        for move in rec.get("moves") or []:
            out.append(f"- {move}")
        out.append("")

    out.append("### Platform prioritisation (indicative)")
    out.append(
        "Enabled engines ranked for this client by a documented, config-weighted "
        "blend of current opportunity (low AIVI = high opportunity), engine "
        "reach, and referral-click value. This is guidance, not a fixed ranking: "
        "prioritisation is audience-dependent — a site whose audience arrives via "
        "Google organic (a local nonprofit) should usually favour Google AI "
        "surfaces first, since existing SEO partly carries over there."
    )
    out.append("")
    if prioritization:
        out.append("| Rank | Engine | Priority | Opportunity | Reach | Referral |")
        out.append("|------|--------|----------|-------------|-------|----------|")
        for index, row in enumerate(prioritization, start=1):
            out.append(
                f"| {index} | {row['display_name']} | {row['priority_score']:.3f} "
                f"| {row['opportunity']:.2f} | {row['reach']:.2f} | {row['referral']:.2f} |"
            )
    else:
        out.append("*No enabled engines to prioritise.*")
    out.append("")
    out.append(_CAVEAT)
    out.append("")
    return out
