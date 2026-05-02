"""
Tests for Fix I.1 — externalise PAA theme routing to brief_pattern_routing.yml.

Spec: serp_tool1_improvements_spec.md#I.1
"""
import json
import os
import tempfile
import unittest

import yaml

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "output",
    "market_analysis_couples_therapy_20260501_1517.json",
)
BASELINE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Previous Python constants — recorded verbatim before I.1 change. Used as
# the authoritative source for I.1.2 (YAML must match these exactly).
_PREV_PAA_THEMES = {
    "The Medical Model Trap": [
        "therapy", "therapist", "counselling", "counselor",
        "session", "diagnosis", "mental health", "treatment",
        "professional", "psychologist",
    ],
    "The Fusion Trap": [
        "reach out", "reconnect", "contact", "close",
        "relationship", "communicate", "talking",
        "stop reaching", "go no contact",
    ],
    "The Resource Trap": [
        "cost", "free", "afford", "pay", "price", "insurance",
        "covered", "sliding scale", "low cost", "how much",
    ],
    "The Blame/Reactivity Trap": [
        "toxic", "narcissist", "abusive", "signs", "fault",
        "blame", "anger", "deal with", "mean",
    ],
}
_PREV_PAA_CATEGORIES = {
    "The Medical Model Trap": {"General", "Commercial"},
    "The Fusion Trap": {"General", "Distress"},
    "The Resource Trap": {"Commercial", "Distress"},
    "The Blame/Reactivity Trap": {"Reactivity", "Distress"},
}
_PREV_KEYWORD_HINTS = {
    "The Medical Model Trap": ["therapy", "counselling", "counseling", "mental health"],
    "The Fusion Trap": ["estrangement", "adult child", "reach out", "contact"],
    "The Resource Trap": ["grief", "counselling", "therapy", "bc"],
    "The Blame/Reactivity Trap": ["estrangement", "toxic", "no-contact", "family member"],
}
_PREV_INTENT_SLOTS = {
    "informational": "informational/educational",
    "commercial_investigation": "research/comparison",
    "transactional": "service/booking",
    "navigational": "brand-search",
    "local": "local-service",
    "mixed": "mixed (see Section 5b for components)",
}


class TestI11YamlExists(unittest.TestCase):
    """I.1.1 — brief_pattern_routing.yml exists at repo root."""

    def test_i11_yaml_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "brief_pattern_routing.yml")
        self.assertTrue(os.path.exists(path), "brief_pattern_routing.yml must exist at repo root")


class TestI12YamlMatchesPreviousConstants(unittest.TestCase):
    """I.1.2 — YAML values match the previous Python constants exactly."""

    @classmethod
    def setUpClass(cls):
        import generate_content_brief as gcb
        gcb._BRIEF_ROUTING_CACHE = None  # ensure fresh load
        cls.routing = gcb.load_brief_pattern_routing()

    def test_i12_paa_themes_match(self):
        for pattern, expected in _PREV_PAA_THEMES.items():
            actual = self.routing["paa_themes"].get(pattern, [])
            self.assertEqual(sorted(actual), sorted(expected),
                             f"paa_themes mismatch for {pattern!r}")

    def test_i12_paa_categories_match(self):
        for pattern, expected in _PREV_PAA_CATEGORIES.items():
            actual = self.routing["paa_categories"].get(pattern, set())
            self.assertEqual(actual, expected,
                             f"paa_categories mismatch for {pattern!r}")

    def test_i12_keyword_hints_match(self):
        for pattern, expected in _PREV_KEYWORD_HINTS.items():
            actual = self.routing["keyword_hints"].get(pattern, [])
            self.assertEqual(sorted(actual), sorted(expected),
                             f"keyword_hints mismatch for {pattern!r}")

    def test_i12_intent_slot_descriptions_match(self):
        actual = self.routing["intent_slot_descriptions"]
        self.assertEqual(actual, _PREV_INTENT_SLOTS)


class TestI13NoHardcodedRoutingInPython(unittest.TestCase):
    """I.1.3 — No literal definitions of the four routing constants remain in generate_content_brief.py."""

    def _read_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "generate_content_brief.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_i13_brief_paa_themes_not_defined(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^BRIEF_PAA_THEMES\s*=",
                            "BRIEF_PAA_THEMES literal definition must not exist in generate_content_brief.py")

    def test_i13_brief_paa_categories_not_defined(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^BRIEF_PAA_CATEGORIES\s*=",
                            "BRIEF_PAA_CATEGORIES literal definition must not exist")

    def test_i13_brief_keyword_hints_not_defined(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^BRIEF_KEYWORD_HINTS\s*=",
                            "BRIEF_KEYWORD_HINTS literal definition must not exist")

    def test_i13_brief_intent_slots_not_defined(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^_BRIEF_INTENT_SLOTS\s*=",
                            "_BRIEF_INTENT_SLOTS literal definition must not exist")


class TestI14MalformedYamlRaises(unittest.TestCase):
    """I.1.4 — Malformed YAML raises ValueError at startup."""

    def _write_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_i14_missing_required_key_raises(self):
        import generate_content_brief as gcb
        path = self._write_yaml("""
version: 1
patterns:
  - pattern_name: The Medical Model Trap
    paa_themes: []
    # paa_categories missing
    keyword_hints: []
intent_slot_descriptions:
  informational: test
""")
        try:
            with self.assertRaises(ValueError):
                gcb.load_brief_pattern_routing(path=path)
        finally:
            os.unlink(path)

    def test_i14_unknown_pattern_name_raises(self):
        import generate_content_brief as gcb
        path = self._write_yaml("""
version: 1
patterns:
  - pattern_name: Nonexistent Pattern
    paa_themes: []
    paa_categories: []
    keyword_hints: []
intent_slot_descriptions:
  informational: test
""")
        try:
            with self.assertRaises(ValueError):
                gcb.load_brief_pattern_routing(path=path)
        finally:
            os.unlink(path)


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestI15PipelineOutputUnchanged(unittest.TestCase):
    """I.1.5 — Brief output is identical to baseline captured before externalisation."""

    @classmethod
    def setUpClass(cls):
        import generate_content_brief as gcb
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        recs = data.get("strategic_recommendations", [])
        cls.briefs = [gcb.generate_brief(data, rec_index=i) for i in range(len(recs))]

    def _load_baseline(self, index: int) -> str:
        path = os.path.join(BASELINE_DIR, f"brief_baseline_couples_therapy_r{index}.md")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_i15_rec0_output_unchanged(self):
        self.assertEqual(self.briefs[0], self._load_baseline(0),
                         "Brief for rec 0 changed after routing externalisation")

    def test_i15_rec1_output_unchanged(self):
        self.assertEqual(self.briefs[1], self._load_baseline(1),
                         "Brief for rec 1 changed after routing externalisation")

    def test_i15_rec2_output_unchanged(self):
        self.assertEqual(self.briefs[2], self._load_baseline(2),
                         "Brief for rec 2 changed after routing externalisation")


if __name__ == "__main__":
    unittest.main()
