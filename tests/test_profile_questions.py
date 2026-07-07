"""Tests for profile_questions.py — persona-segmented question generation.

Spec: yoast_geo_upgrade_spec_v1.md#Y.1
- Y.1.1 loader parses the file / warns + returns {} on missing/malformed.
- Y.1.2 generate() is deterministic; expected de-duplicated count for a
  synthetic 2-persona / 2-template / 2-city profile.
- Y.1.2a seed_questions verbatim (a {city} in a seed is literal, not expanded).
- Y.1.2b local_transactional templates expand across cities + near-me + a
  de-localised copy; the informational tier is never city-suffixed.
- Y.1.3 graceful degradation (no templates, empty secondary_cities, missing
  service_description).
"""
import os
import tempfile
import unittest

import yaml

import profile_questions

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLoader(unittest.TestCase):
    """Y.1.1 — loader returns dict keyed by slug; tolerant of bad input."""

    def test_loads_shipped_file_keyed_by_slug(self):
        profiles = profile_questions.load_client_profiles(
            os.path.join(_REPO_ROOT, "client_profiles.yml"))
        self.assertIn("living_systems", profiles)
        self.assertEqual(
            profiles["living_systems"]["brand_name"],
            "Living Systems Counselling and Training")

    def test_missing_file_warns_and_returns_empty(self):
        with self.assertLogs(level="WARNING"):
            profiles = profile_questions.load_client_profiles(
                "/nonexistent/client_profiles.yml")
        self.assertEqual(profiles, {})

    def test_malformed_file_warns_and_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("brand_name: [unterminated\n")  # invalid YAML
            path = f.name
        try:
            with self.assertLogs(level="WARNING"):
                profiles = profile_questions.load_client_profiles(path)
            self.assertEqual(profiles, {})
        finally:
            os.unlink(path)

    def test_non_mapping_top_level_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("- just\n- a\n- list\n")
            path = f.name
        try:
            with self.assertLogs(level="WARNING"):
                profiles = profile_questions.load_client_profiles(path)
            self.assertEqual(profiles, {})
        finally:
            os.unlink(path)


class TestSyntheticCount(unittest.TestCase):
    """Y.1.2 — deterministic count on a synthetic 2p / 2t / 2c profile."""

    PROFILE = {
        "primary_city": "Alpha",
        "secondary_cities": ["Beta"],
        "personas": [
            {"label": "p1", "intents": {
                "local_transactional": {
                    "local": True,
                    "templates": ["svc a {city}", "svc b {city}"],
                }}},
            {"label": "p2", "intents": {
                "local_transactional": {
                    "local": True,
                    "templates": ["svc c {city}", "svc d {city}"],
                }}},
        ],
    }

    def test_expected_deduplicated_count(self):
        out = profile_questions.generate(self.PROFILE)
        # Per persona, per template (2): 2 cities + near-me + de-localised = 4.
        # 2 templates x 4 = 8 per persona; 2 personas = 16.
        self.assertEqual(len(out), 16)

    def test_deterministic_across_calls(self):
        a = profile_questions.generate(self.PROFILE)
        b = profile_questions.generate(self.PROFILE)
        self.assertEqual(a, b)

    def test_every_row_has_required_keys(self):
        for row in profile_questions.generate(self.PROFILE):
            self.assertEqual(
                set(row), {"question", "persona", "city", "intent"})


class TestLivingSystemsDefault(unittest.TestCase):
    """Y.1.2a / Y.1.2b — the shipped default profile behaves as specified."""

    @classmethod
    def setUpClass(cls):
        profiles = profile_questions.load_client_profiles(
            os.path.join(_REPO_ROOT, "client_profiles.yml"))
        cls.rows = profile_questions.generate(profiles["living_systems"])
        cls.questions = [r["question"] for r in cls.rows]

    def test_seed_questions_verbatim_and_unmodified(self):
        # A concept seed appears exactly once, unmodified, city-agnostic.
        matches = [r for r in self.rows
                   if r["question"] == "family of origin issues"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["persona"], "prospective_client")
        self.assertEqual(matches[0]["intent"], "informational")
        self.assertIsNone(matches[0]["city"])

    def test_seed_with_city_placeholder_is_literal(self):
        # A {city} inside a seed_questions entry is NOT expanded.
        literal = "clinical supervision family systems {city}"
        self.assertIn(literal, self.questions)
        # And it is never city-expanded into a concrete city.
        self.assertNotIn("clinical supervision family systems North Vancouver",
                         self.questions)

    def test_local_transactional_expands_cities_nearme_delocalised(self):
        for expected in (
            "relationship counselling North Vancouver",
            "relationship counselling West Vancouver",
            "relationship counselling Vancouver",
            "relationship counselling near me",
            "relationship counselling",  # de-localised copy
        ):
            self.assertIn(expected, self.questions,
                          f"missing local expansion: {expected!r}")

    def test_informational_tier_never_city_suffixed(self):
        # No informational seed acquires a city suffix.
        for r in self.rows:
            if r["intent"] == "informational":
                self.assertIsNone(
                    r["city"],
                    f"informational question tagged with a city: {r}")

    def test_local_rows_tagged_with_intent(self):
        local_rows = [r for r in self.rows
                      if r["question"].startswith("relationship counselling")]
        self.assertTrue(local_rows)
        self.assertTrue(
            all(r["intent"] == "local_transactional" for r in local_rows))


class TestGracefulDegradation(unittest.TestCase):
    """Y.1.3 — sparse profiles never raise; produce fewer questions."""

    def test_persona_with_no_templates_and_no_secondary_cities(self):
        profile = {
            "primary_city": "Solo",
            # no secondary_cities, no service_description
            "personas": [
                {"label": "seedonly", "seed_questions": ["just a seed"]},
            ],
        }
        out = profile_questions.generate(profile)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["question"], "just a seed")
        self.assertEqual(out[0]["persona"], "seedonly")

    def test_missing_service_description_and_empty_personas(self):
        self.assertEqual(profile_questions.generate({}), [])
        self.assertEqual(profile_questions.generate({"personas": []}), [])

    def test_service_placeholder_filled_when_present(self):
        profile = {
            "primary_city": "Solo",
            "service_description": "family systems counselling",
            "personas": [
                {"label": "p", "templates": ["get {service} help"]},
            ],
        }
        out = profile_questions.generate(profile)
        self.assertIn("get family systems counselling help",
                      [r["question"] for r in out])

    def test_malformed_persona_entries_skipped(self):
        profile = {"primary_city": "X", "personas": ["not a dict", 42, None]}
        self.assertEqual(profile_questions.generate(profile), [])


if __name__ == "__main__":
    unittest.main()
