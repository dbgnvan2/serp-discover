"""profile_questions.py — persona-segmented AI-visibility question generation.

Spec: yoast_geo_upgrade_spec_v1.md#Y.1 (decision gate Y-D1: profile questions
AUGMENT keyword-seeded probing, they do not replace it; Y-D5: profiles live in
the shared editorial ``client_profiles.yml``, one block per client slug).

Pure functions, patterned on ``query_variants.py``: no I/O beyond the single
``load_client_profiles`` loader, no network, no LLM. Question generation is
deterministic given a profile (templates ordered, no randomness) so tests are
stable.

A real AI-assistant user does not type keywords — they ask natural questions
shaped by WHO they are (persona) and WHAT they need. This module turns a
structured client profile into those questions:

  * ``seed_questions`` are the client's hand-authored queries, probed VERBATIM
    (no templating, no city suffixing). A ``{city}`` inside a seed is literal.
  * ``templates`` (persona-level or under a named intent TIER) are expanded.
    A tier flagged ``local: true`` (booking-intent) expands its templates
    across ``[primary_city] + secondary_cities`` PLUS a "near me" variant PLUS
    a de-localised copy (reusing ``query_variants.delocalise_keyword``), so the
    booking-intent local queries are covered alongside the top-of-funnel
    concept queries. Non-local tiers are probed as-is.

Output of :func:`generate` is a list of ``{question, persona, city, intent}``
dicts, de-duplicated by (question, persona) with insertion order preserved.
"""
from __future__ import annotations

import logging
import os

import yaml

from query_variants import delocalise_keyword

logger = logging.getLogger(__name__)

_CLIENT_PROFILES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "client_profiles.yml"
)

# The optional {service} placeholder is filled from the profile's
# service_description (Y.4 also supports it in situational templates).
_NEAR_ME = "near me"


def load_client_profiles(path: str = _CLIENT_PROFILES_PATH) -> dict:
    """Parse ``client_profiles.yml`` into a dict keyed by client slug.

    A missing or malformed file warns (one line naming the file) and returns
    ``{}`` — never raises — so a deployment without a profile degrades to
    "no profile, profile questions skipped" rather than aborting the run
    (Spec: yoast_geo_upgrade_spec_v1.md#Y.1.1, design principle 3).
    """
    if not os.path.exists(path):
        logger.warning(
            "client_profiles.yml not found at %s — no client profile; "
            "profile questions skipped.", path
        )
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:  # malformed YAML
        logger.warning(
            "Malformed client_profiles.yml at %s (%s) — no client profile; "
            "profile questions skipped.", path, exc
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "client_profiles.yml at %s is not a mapping of client slug -> "
            "profile — no client profile; profile questions skipped.", path
        )
        return {}
    # Keep only well-formed profile blocks; a malformed single block warns but
    # does not sink the others.
    profiles = {}
    for slug, profile in data.items():
        if isinstance(profile, dict):
            profiles[str(slug)] = profile
        else:
            logger.warning(
                "client_profiles.yml: profile %r is not a mapping — skipped.",
                slug,
            )
    return profiles


def _cities(profile: dict) -> list[str]:
    """Ordered, de-duplicated [primary_city] + secondary_cities."""
    out: list[str] = []
    seen: set[str] = set()
    primary = str(profile.get("primary_city") or "").strip()
    if primary:
        out.append(primary)
        seen.add(primary.lower())
    for city in profile.get("secondary_cities") or []:
        city = str(city or "").strip()
        if city and city.lower() not in seen:
            out.append(city)
            seen.add(city.lower())
    return out


def _fill(template: str, city: str, service: str) -> str | None:
    """Fill a template's placeholders, tolerating a missing {service}.

    Returns None when the template references an unknown placeholder (logged),
    matching ``query_variants.situational_template_probes`` behaviour.
    """
    try:
        return template.format(city=city, service=service).strip()
    except (KeyError, IndexError):
        logger.warning(
            "client_profiles.yml template has an unknown placeholder, "
            "skipping: %r", template
        )
        return None


def _expand_templates(templates, cities, service, is_local):
    """Expand a template list into concrete question strings, ordered.

    Non-local tiers: each template is filled once per city (city-bearing
    templates vary by city; city-free templates collapse to one copy).

    Local tiers: additionally emit a "near me" fill and a de-localised copy of
    each city fill (reusing ``query_variants.delocalise_keyword``), so
    booking-intent queries cover the local, near-me, and non-local forms.
    """
    out: list[str] = []
    for template in templates or []:
        template = str(template)
        has_city = "{city}" in template
        # Per-city fills (or a single fill when the template has no {city}).
        for city in (cities or [""]):
            filled = _fill(template, city, service)
            if filled:
                out.append(filled)
            if not has_city:
                # City-free template: only one copy regardless of city count.
                break
        if is_local and has_city:
            # "near me" variant.
            near = _fill(template, _NEAR_ME, service)
            if near:
                out.append(near)
            # De-localised copy: strip the city from the first city fill.
            first_city = cities[0] if cities else ""
            base_fill = _fill(template, first_city, service)
            if base_fill:
                delocalised = delocalise_keyword(base_fill, first_city)
                if delocalised:
                    out.append(delocalised)
    return out


def _persona_questions(persona: dict, cities, service):
    """Yield (question, intent) pairs for one persona, ordered.

    A persona may carry ``seed_questions`` / ``templates`` directly (a single
    implicit tier) and/or an ``intents`` map of named funnel tiers, each with
    its own ``seed_questions`` / ``templates`` and optional ``local`` flag.
    Seeds are always verbatim; only templates expand.
    """
    pairs: list[tuple[str, str | None]] = []

    def _emit_tier(tier_data, intent_name, is_local):
        # seed_questions — verbatim, no templating, no city suffixing.
        for seed in tier_data.get("seed_questions") or []:
            seed = str(seed).strip()
            if seed:
                pairs.append((seed, intent_name))
        # templates — expanded.
        for question in _expand_templates(
            tier_data.get("templates"), cities, service, is_local
        ):
            pairs.append((question, intent_name))

    # Persona-level (untiered) seeds/templates: intent = None, non-local.
    if persona.get("seed_questions") or persona.get("templates"):
        _emit_tier(persona, None, False)

    # Named intent tiers.
    intents = persona.get("intents")
    if isinstance(intents, dict):
        for intent_name, tier_data in intents.items():
            if not isinstance(tier_data, dict):
                continue
            is_local = bool(tier_data.get("local"))
            _emit_tier(tier_data, str(intent_name), is_local)

    return pairs


def _city_tag(question: str, cities) -> str | None:
    """Best-effort city tag: the city name present in the question, else None.

    A verbatim seed or a de-localised / "near me" fill carries no single city;
    those are tagged ``None`` (city-agnostic).
    """
    q_lower = question.lower()
    for city in cities:
        if city.lower() in q_lower:
            return city
    return None


def generate(profile: dict) -> list[dict]:
    """Generate persona-segmented questions from a client profile.

    Returns a deterministic list of ``{question, persona, city, intent}``
    dicts. Local-tier templates are expanded across
    ``[primary_city] + secondary_cities`` plus a "near me" and a de-localised
    copy; seed_questions are emitted verbatim; non-local templates are filled
    per city without a local suffix. Results are de-duplicated by
    ``(question, persona)`` with insertion order preserved.

    Missing ``secondary_cities``, personas without templates, and a missing
    ``service_description`` all degrade gracefully (fewer questions, never a
    raise) — Spec: yoast_geo_upgrade_spec_v1.md#Y.1.3.
    """
    if not isinstance(profile, dict):
        return []
    cities = _cities(profile)
    service = str(profile.get("service_description") or "").strip()

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for persona in profile.get("personas") or []:
        if not isinstance(persona, dict):
            continue
        label = str(persona.get("label") or "").strip() or "unlabeled"
        for question, intent in _persona_questions(persona, cities, service):
            key = (question.lower(), label)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "question": question,
                "persona": label,
                "city": _city_tag(question, cities),
                "intent": intent,
            })
    return out
