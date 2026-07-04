"""
Tests for serp_vocab.yml — externalised editorial SERP vocabulary.

Spec: seo_geo_review_20260704.md C.4
The YAML must match the constants previously hardcoded in serp_audit.py /
pattern_matching.py exactly (parity), and the consumers must read from it.
"""
import os
import tempfile
import unittest

import pattern_matching
from pattern_matching import load_serp_vocab

# Previous Python constants — recorded verbatim before the C.4 change.
_PREV_STOP_WORDS = {
    "the", "and", "to", "of", "a", "in", "is", "for", "on", "with", "as", "at", "by", "an", "be", "or", "are", "from", "that",
    "this", "it", "we", "our", "us", "can", "will", "your", "you", "my", "me", "not", "have", "has", "but", "so", "if", "their", "they",
    "vancouver", "bc", "british", "columbia", "canada", "north", "west", "counselling", "counseling", "therapy", "therapist",
    "counsellor", "counselor", "service", "services", "clinic", "centre", "center", "help", "support",
    "highlytrained",
}

_PREV_TRIGGER_MAP = {
    "Commercial": ["cost", "price", "how much", "fees"],
    "Distress": ["survive", "divorce", "infidelity", "leave", "separation"],
    "Reactivity": ["narcissist", "toxic", "signs", "mean", "angry", "cut off", "hate"],
}

_PREV_SERVICE_TOKENS = (
    "counselling", "counseling", "counsellor", "counselor",
    "therapist", "therapy", "psychologist", "mental health",
)


class TestVocabParity(unittest.TestCase):
    """The YAML must reproduce the previously hardcoded lists exactly."""

    def setUp(self):
        self.vocab = load_serp_vocab()

    def test_stop_words_match_previous_constant(self):
        self.assertEqual(set(self.vocab["stop_words"]), _PREV_STOP_WORDS)

    def test_paa_category_triggers_match_previous_constant(self):
        self.assertEqual(self.vocab["paa_category_triggers"], _PREV_TRIGGER_MAP)

    def test_service_tokens_match_previous_constant(self):
        self.assertEqual(tuple(self.vocab["service_like_tokens"]), _PREV_SERVICE_TOKENS)

    def test_templates_have_all_three_branches(self):
        templates = self.vocab["ai_alternative_templates"]
        for branch in ("service", "help_with", "default"):
            self.assertIn(branch, templates)
            self.assertEqual(len(templates[branch]), 2)

    def test_situational_templates_present(self):
        # Spec: seo_geo_deferred_spec_v1.md#T.5 (T.5.5) — loader-required
        # editorial section; detailed tests in tests/test_situational_probes.py.
        templates = self.vocab["situational_templates"]
        self.assertIsInstance(templates, list)
        self.assertTrue(templates)
        self.assertTrue(all(isinstance(t, str) and t.strip() for t in templates))


class TestVocabLoader(unittest.TestCase):

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_serp_vocab("/nonexistent/serp_vocab.yml")

    def test_missing_key_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("stop_words: [the]\n")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_serp_vocab(path)
        finally:
            os.unlink(path)

    def test_pattern_matching_stop_words_come_from_vocab(self):
        self.assertEqual(
            pattern_matching.STOP_WORDS,
            set(pattern_matching.SERP_VOCAB["stop_words"]),
        )


class TestConsumersUnchanged(unittest.TestCase):
    """Behavioral parity of the serp_audit consumers after externalisation."""

    def test_ai_query_alternatives_service_branch(self):
        import serp_audit
        alts = serp_audit._ai_query_alternatives("couples counselling")
        self.assertEqual(len(alts), 2)
        self.assertEqual(alts[0], "how to choose the right couples counselling?")
        self.assertTrue(alts[1].startswith("how much does couples counselling cost in "))

    def test_ai_query_alternatives_help_with_branch(self):
        import serp_audit
        alts = serp_audit._ai_query_alternatives("help with anxiety")
        self.assertEqual(alts[0], "what are effective ways to manage anxiety?")
        self.assertTrue(alts[1].startswith("where to get help for anxiety in "))

    def test_ai_query_alternatives_default_branch(self):
        import serp_audit
        alts = serp_audit._ai_query_alternatives("family estrangement")
        self.assertEqual(alts[0], "what are the best options for family estrangement?")

    def test_serp_audit_trigger_map_is_vocab(self):
        import serp_audit
        self.assertEqual(serp_audit.PAA_CATEGORY_TRIGGERS, _PREV_TRIGGER_MAP)


if __name__ == "__main__":
    unittest.main()
