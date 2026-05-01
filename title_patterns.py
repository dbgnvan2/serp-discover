"""Title pattern extraction for SERP top results.

Given the titles of the top 10 organic results for a keyword, classify each
title against a fixed set of regex-based patterns, then summarise. The result
is consumed by the LLM as a deterministic SERP-shape signal so it doesn't have
to infer "this SERP is mostly listicles" from raw titles itself.

Output (stored at keyword_profiles[kw]["title_patterns"]):
    {
        "pattern_counts": {
            "how_to": int,
            "what_is": int,
            "best_of": int,
            "vs_comparison": int,
            "listicle_numeric": int,
            "brand_only": int,
            "question": int,
            "other": int,
        },
        "dominant_pattern": str | None,    # set if any pattern has ≥4 of top 10
        "examples": {pattern: [up to 3 example titles]},
        "total_titles": int,
    }

Patterns are tried in PRIORITY ORDER (declared below). First match wins per
title. This means "How To Compare X vs Y" is classified as vs_comparison (not
how_to), which is the spec's required behaviour.
"""

from __future__ import annotations

import re
from typing import Iterable


# ─── Patterns, in priority order (top of list = highest priority) ────────────
#
# Each entry: (name, compiled_regex, description)
#
# Priority rationale:
#   1. vs_comparison — most specific structural signal; subsumes how_to/best_of
#      when "vs" appears (e.g., "How to Compare X vs Y")
#   2. listicle_numeric — numeric prefix is unambiguous and dominates the
#      shape of the title (e.g., "5 Best Therapists in Vancouver")
#   3. best_of — strong commercial-investigation marker
#   4. how_to — instructional shape
#   5. what_is — definitional shape
#   6. question — generic interrogative; lower priority so "What is X?" hits
#      what_is, not question
#   7. brand_only — only when none of the above apply (short, no separator)
#   8. other — fallback

PATTERNS = [
    (
        "vs_comparison",
        # "X vs Y", "X versus Y", with word boundaries
        re.compile(r"\b(?:vs\.?|versus)\b", re.IGNORECASE),
    ),
    (
        "listicle_numeric",
        # Title starts with a number (≥2 digits or 2-99) or "Top N"
        # e.g., "5 Best…", "10 Things…", "Top 7…"
        re.compile(r"^\s*(?:top\s+)?\d{1,3}\b", re.IGNORECASE),
    ),
    (
        "best_of",
        # "best", "top" qualifier (without leading number — that's listicle)
        # e.g., "Best Therapists in Vancouver", "Top Rated Counselling"
        re.compile(r"\b(?:best|top[-\s]?rated|top\s+\d*\s*\w)\b", re.IGNORECASE),
    ),
    (
        "how_to",
        # "How to X" or "How do I X" at start of title
        re.compile(r"^\s*how\s+(?:to|do|can|should|does)\b", re.IGNORECASE),
    ),
    (
        "what_is",
        # "What is X", "What are X" — definitional
        re.compile(r"^\s*what\s+(?:is|are|does|do)\b", re.IGNORECASE),
    ),
    (
        "question",
        # Other interrogatives at start, OR ends with "?"
        re.compile(
            r"^\s*(?:why|when|where|who|which|can|should|are|is|do|does)\b"
            r"|\?\s*$",
            re.IGNORECASE,
        ),
    ),
    # brand_only and other are decided separately below
]

DOMINANT_THRESHOLD = 4  # ≥4 of top 10 → dominant_pattern set
TOP_N_DEFAULT = 10
EXAMPLES_PER_PATTERN = 3


def _strip_site_suffix(title: str) -> str:
    """Strip trailing " | Site Name" or " - Site Name" before brand detection.

    Title detail before brand detection: SerpAPI titles often look like
    "Best Couples Therapists in Vancouver | Psychology Today". For brand_only
    detection we want the leftmost segment.
    """
    for sep in (" | ", " - ", " — ", " · "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def _is_brand_only(
    title: str, brand_aliases: Iterable[str]
) -> bool:
    """A title counts as brand_only if its leftmost segment EQUALS a known
    brand string (case-insensitive). Substring matches don't count — the title
    "Living Systems Counselling Couples Programs" is NOT brand_only because
    the segment carries a topical phrase past the brand.
    """
    leftmost = _strip_site_suffix(title).lower()
    for alias in brand_aliases or ():
        if not alias:
            continue
        a = alias.lower().strip()
        if leftmost == a:
            return True
    return False


def _classify_title(title: str, brand_aliases: Iterable[str]) -> str:
    """Return the pattern name for one title (priority order)."""
    if not title or not title.strip():
        return "other"

    if _is_brand_only(title, brand_aliases):
        return "brand_only"

    for name, pattern in PATTERNS:
        if pattern.search(title):
            return name

    return "other"


def compute_title_patterns(
    titles: list[str],
    brand_aliases: Iterable[str] = (),
    top_n: int = TOP_N_DEFAULT,
    dominant_threshold: int = DOMINANT_THRESHOLD,
) -> dict:
    """Classify the top N titles and summarise.

    Args:
        titles: list of SERP titles (in rank order).
        brand_aliases: client/competitor brand names for brand_only detection.
            Pass the same `known_brands` list used by intent_verdict (plus the
            client's own brand strings).
        top_n: how many titles to analyse (default 10 per spec).
        dominant_threshold: count needed to declare dominant_pattern (default 4).

    Returns the title_patterns dict, or None if no titles supplied.
    """
    if not titles:
        return None

    sliced = [t for t in titles[:top_n] if t and t.strip()]
    if not sliced:
        return None

    # Initialise all known patterns to 0 so the schema is stable even when a
    # pattern has zero hits.
    pattern_names = [name for name, _ in PATTERNS] + ["brand_only", "other"]
    counts = {name: 0 for name in pattern_names}
    examples: dict[str, list[str]] = {name: [] for name in pattern_names}

    for title in sliced:
        name = _classify_title(title, brand_aliases)
        counts[name] += 1
        if len(examples[name]) < EXAMPLES_PER_PATTERN:
            examples[name].append(title)

    # "other" is the catch-all; 4+ unclassifiable titles is NOT a meaningful
    # SERP-shape signal, so it's never eligible to be the dominant pattern.
    dominant_pattern = None
    dominant_count = 0
    for name in pattern_names:
        if name == "other":
            continue
        # If multiple patterns hit the threshold (rare on top-10), prefer the
        # one with the higher count; ties broken by priority order (the
        # iteration order of pattern_names).
        if counts[name] >= dominant_threshold and counts[name] > dominant_count:
            dominant_pattern = name
            dominant_count = counts[name]

    # Drop empty examples lists so the JSON is tidier.
    examples_compact = {k: v for k, v in examples.items() if v}

    return {
        "pattern_counts": counts,
        "dominant_pattern": dominant_pattern,
        "examples": examples_compact,
        "total_titles": len(sliced),
    }
