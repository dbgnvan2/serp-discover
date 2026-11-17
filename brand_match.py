#!/usr/bin/env python3
"""brand_match.py — the one place a brand name is matched against answer text.

Spec: D3.12 (review chunk D3b, cold-review findings 2 and 5).

Three functions used to decide independently whether an AI answer names a
brand, and each got it differently wrong:

  * ``probe_ai_visibility.detect_visibility`` — a bare substring test, so
    "living systems theory" (the academic subject this client teaches about)
    counted as a mention of Living Systems Counselling, and a brand token
    matched inside a longer word.
  * ``brand_mentions.gazetteer_pass`` — a word boundary but no negative
    terms, so the same false positive still reached the leaderboard, the
    client's rank, the AIVI Ranking axis and the authority sub-score.
  * ``answer_sentiment.answer_mentions_brand`` — a bare substring and no
    negative terms, so the false positive still bought a paid sentiment
    classification and a stored sentiment row.

P5: a fix to one matcher is a fix to the class. All three now call
``matches_patterns`` here, and the editorial negative terms
(``config.yml ai_visibility.negative_terms``) reach all three.

The veto is **per match, not per document**. An AI answer runs to several
paragraphs, so "Living systems theory, developed by Bowen... Living Systems
Counselling in North Vancouver offers..." names the client once and the
subject once. Vetoing the whole answer on the presence of a negative phrase
dropped the real mention and understated every axis built on it, so a
client-pattern hit is rejected only when that occurrence lies inside a
negative phrase. (``gsc_demand.is_branded`` vetoes the whole string, which is
right there — a GSC query is a handful of words, not a document.)
"""
from __future__ import annotations

import re

__all__ = ["matches_patterns", "negative_spans"]


def negative_spans(text_lower: str,
                   negative_terms: list[str] | None) -> list[tuple[int, int]]:
    """Every ``(start, end)`` occurrence of every negative term, lower-cased.

    Overlapping occurrences are all returned; the caller only ever tests
    containment, so overlap is harmless.
    """
    spans: list[tuple[int, int]] = []
    if not text_lower:
        return spans
    for term in negative_terms or []:
        needle = str(term or "").strip().lower()
        if not needle:
            continue
        start = text_lower.find(needle)
        while start != -1:
            spans.append((start, start + len(needle)))
            start = text_lower.find(needle, start + 1)
    return spans


def matches_patterns(text: str, patterns: list[str] | None,
                     negative_terms: list[str] | None = None) -> bool:
    """True when any *pattern* appears in *text* on a word boundary, outside
    every *negative_terms* occurrence.

    Case-insensitive. An empty text, an empty pattern list, or patterns that
    are all blank → ``False``; nothing is matched by accident.
    """
    text_lower = str(text or "").lower()
    if not text_lower:
        return False
    spans = negative_spans(text_lower, negative_terms)
    for pattern in patterns or []:
        needle = str(pattern or "").strip().lower()
        if not needle:
            continue
        for match in re.finditer(r"\b" + re.escape(needle) + r"\b", text_lower):
            if not any(start <= match.start() and match.end() <= end
                       for start, end in spans):
                return True
    return False
