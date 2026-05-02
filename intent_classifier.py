"""
intent_classifier.py
~~~~~~~~~~~~~~~~~~~~
Classifies PAA questions and keyword phrases as "External Locus" (medical
model framing), "Systemic" (Bowen Family Systems Theory framing), or
"General" (neither).

This distinction drives the "Bowen Reframe FAQ" section of the content brief:
questions tagged External Locus are prime candidates for a systems-based
reframe that differentiates Living Systems Counselling from the dominant
medical-model content in the SERP.

Design notes
------------
- Rules-based, no ML dependency — deterministic and auditable.
- Matching is case-insensitive and checks both single-word triggers and
  multi-word phrases (checked first to avoid partial-word false positives).
- Confidence reflects the ratio of matched triggers relative to total tokens,
  capped at 1.0, so short questions with one strong trigger score higher than
  long questions with the same number of matches.
- The class accepts optional custom trigger sets at init time so the trigger
  vocabulary can be extended via config without code changes.
"""

from __future__ import annotations

import os
import re
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Trigger vocabulary loader
# ---------------------------------------------------------------------------

_TRIGGERS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "intent_classifier_triggers.yml"
)
_TRIGGERS_CACHE: tuple[frozenset, frozenset] | None = None


def load_triggers(path: str | None = None) -> tuple[frozenset, frozenset]:
    """Load medical and systemic trigger vocabularies from YAML.

    Purpose: Externalise editorial trigger lists from Python source.
    Spec:    serp_tool1_improvements_spec.md#I.2
    Tests:   tests/test_intent_classifier_triggers.py::test_i22_yaml_matches_previous_constants

    Returns (medical_triggers, systemic_triggers) as frozensets.
    Minimum trigger length is 3 characters; 1-2 char triggers raise ValueError.
    """
    global _TRIGGERS_CACHE
    if _TRIGGERS_CACHE is not None and path is None:
        return _TRIGGERS_CACHE

    fpath = path or _TRIGGERS_PATH
    with open(fpath, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    for block in ("medical_triggers", "systemic_triggers"):
        if block not in raw or not isinstance(raw[block], dict):
            raise ValueError(f"{fpath}: '{block}' block must be present and a dict")
        for subkey in ("multi_word", "single_word"):
            if subkey not in raw[block] or not isinstance(raw[block][subkey], list):
                raise ValueError(f"{fpath}: '{block}.{subkey}' must be a list")

    medical: list[str] = []
    systemic: list[str] = []

    for block_key, out in (("medical_triggers", medical), ("systemic_triggers", systemic)):
        for subkey in ("multi_word", "single_word"):
            for t in raw[block_key][subkey]:
                if not isinstance(t, str) or not t.strip():
                    raise ValueError(f"{fpath}: {block_key}.{subkey}: each entry must be a non-empty string")
                if len(t.strip()) < 3:
                    raise ValueError(
                        f"{fpath}: {block_key}.{subkey}: trigger {t!r} is too short "
                        "(minimum 3 characters)"
                    )
                out.append(t.strip())

    result = (frozenset(medical), frozenset(systemic))
    if path is None:
        _TRIGGERS_CACHE = result
    return result


IntentLabel = Literal["External Locus", "Systemic", "General"]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """Classify text strings by Bowen/medical intent.

    Parameters
    ----------
    medical_triggers:
        Override the default medical-model trigger vocabulary.
    systemic_triggers:
        Override the default Bowen/systemic trigger vocabulary.

    Examples
    --------
    >>> clf = IntentClassifier()
    >>> clf.classify_paa("What is the diagnosis for anxiety disorder?")
    {'intent': 'External Locus', 'confidence': 0.67, 'triggers': ['diagnosis', 'disorder']}
    >>> clf.classify_paa("How does differentiation affect the family system?")
    {'intent': 'Systemic', 'confidence': 0.71, 'triggers': ['differentiation', 'family system']}
    """

    def __init__(
        self,
        medical_triggers: frozenset[str] | None = None,
        systemic_triggers: frozenset[str] | None = None,
    ) -> None:
        if medical_triggers is None and systemic_triggers is None:
            self._medical, self._systemic = load_triggers()
        else:
            _defaults = load_triggers()
            self._medical = medical_triggers if medical_triggers is not None else _defaults[0]
            self._systemic = systemic_triggers if systemic_triggers is not None else _defaults[1]

        # Pre-sort triggers: longest first so multi-word phrases are matched
        # before their constituent words.
        self._medical_sorted = sorted(self._medical, key=len, reverse=True)
        self._systemic_sorted = sorted(self._systemic, key=len, reverse=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_paa(self, question: str) -> dict:
        """Classify a PAA (People Also Ask) question string.

        Parameters
        ----------
        question:
            Raw question text, e.g. ``"What is the treatment for depression?"``.

        Returns
        -------
        dict with keys:
            intent     : "External Locus" | "Systemic" | "General"
            confidence : float  0.0–1.0
            triggers   : list[str]  matched trigger words/phrases
        """
        return self._classify(question)

    def classify_keyword(self, keyword: str) -> dict:
        """Classify a search keyword phrase.

        Same return schema as :meth:`classify_paa`.
        """
        return self._classify(keyword)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classify(self, text: str) -> dict:
        if not text or not isinstance(text, str):
            return {"intent": "General", "confidence": 0.0, "triggers": []}

        text_lower = text.lower()
        med_score, med_triggers = self._match_triggers(text_lower, self._medical_sorted)
        sys_score, sys_triggers = self._match_triggers(text_lower, self._systemic_sorted)

        token_count = max(1, len(re.findall(r"\w+", text_lower)))

        if med_score == 0 and sys_score == 0:
            return {"intent": "General", "confidence": 0.0, "triggers": []}

        if med_score >= sys_score:
            intent: IntentLabel = "External Locus"
            matched = med_triggers
            raw_confidence = med_score / token_count
        else:
            intent = "Systemic"
            matched = sys_triggers
            raw_confidence = sys_score / token_count

        confidence = round(min(1.0, raw_confidence), 2)
        return {"intent": intent, "confidence": confidence, "triggers": matched}

    def _match_triggers(
        self, text_lower: str, triggers_sorted: list[str]
    ) -> tuple[int, list[str]]:
        """Return (score, matched_triggers) for *text_lower* against *triggers_sorted*.

        Score is the sum of token-lengths of matched triggers (so a 3-word
        phrase scores 3, not 1, giving multi-word matches their proper weight).
        Already-matched spans are consumed so a phrase match doesn't also
        count its constituent words.
        """
        remaining = text_lower
        score = 0
        matched: list[str] = []

        for trigger in triggers_sorted:
            # Use word-boundary matching for single words, substring for phrases
            if " " in trigger:
                pattern = re.escape(trigger)
            else:
                pattern = r"\b" + re.escape(trigger) + r"\b"

            if re.search(pattern, remaining):
                matched.append(trigger)
                word_count = len(trigger.split())
                score += word_count
                # Consume matched span so sub-words aren't double-counted
                remaining = re.sub(pattern, " ", remaining)

        return score, matched
