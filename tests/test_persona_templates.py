"""Tests for the persona-keyed situational_templates axis.

Spec: yoast_geo_upgrade_spec_v1.md#Y.4
- Y.4.1 backward compatible: no profile expands ALL persona blocks and is a
  superset of the previous flat-list output (every old template still appears).
- Y.4.2 situational_template_probes fills persona templates, including the new
  {service} placeholder when supplied and omitting it cleanly when absent.
- Y.4.3 a profile listing only `clinician` expands only clinician templates.
- Y.4.4 documented + editorial-listed (asserted lightly here; prose in docs).
"""
import unittest

import query_variants
from pattern_matching import load_serp_vocab

# The exact flat list shipped before Y.4 (now the therapy_seeker block).
_LEGACY_FLAT = [
    "my partner refuses to try {base} what can I do",
    "how do I know if we actually need {base} or if it is too late",
    "what should I expect from a first {base} session in {city}",
    "I feel stuck dealing with {topic} on my own where do I start",
    "my family keeps having the same fight over and over will {base} help",
]


class TestFlattenBackwardCompat(unittest.TestCase):
    """Y.4.1 — no profile -> all persona blocks; superset of old flat list."""

    def setUp(self):
        self.vocab = load_serp_vocab()
        self.map = self.vocab["situational_templates"]

    def test_no_profile_expands_all_personas(self):
        flat = query_variants.flatten_situational_templates(self.map)
        # Every previously-shipped template is still present.
        for template in _LEGACY_FLAT:
            self.assertIn(template, flat)
        # And the map added the new persona blocks (superset).
        self.assertGreater(len(flat), len(_LEGACY_FLAT))

    def test_flatten_accepts_legacy_flat_list(self):
        # A plain list is returned as-is (a legacy vocab still loads).
        self.assertEqual(
            query_variants.flatten_situational_templates(_LEGACY_FLAT),
            _LEGACY_FLAT)

    def test_flatten_dedupes_and_keeps_order(self):
        m = {"a": ["x", "y"], "b": ["y", "z"]}
        self.assertEqual(
            query_variants.flatten_situational_templates(m), ["x", "y", "z"])

    def test_non_mapping_non_list_returns_empty(self):
        self.assertEqual(query_variants.flatten_situational_templates(None), [])


class TestPersonaSelection(unittest.TestCase):
    """Y.4.3 — a profile listing only one persona expands only that block."""

    MAP = {
        "therapy_seeker": ["seeker {base} one"],
        "clinician_trainee": ["clinician {base} two"],
        "referrer": ["referrer {base} three"],
    }

    def test_only_clinician_expands_clinician(self):
        flat = query_variants.flatten_situational_templates(
            self.MAP, personas=["clinician_trainee"])
        self.assertEqual(flat, ["clinician {base} two"])

    def test_unknown_persona_is_skipped(self):
        flat = query_variants.flatten_situational_templates(
            self.MAP, personas=["clinician_trainee", "does_not_exist"])
        self.assertEqual(flat, ["clinician {base} two"])

    def test_none_personas_expands_all(self):
        flat = query_variants.flatten_situational_templates(self.MAP)
        self.assertEqual(len(flat), 3)


class TestServicePlaceholder(unittest.TestCase):
    """Y.4.2 — {service} filled when supplied, omitted cleanly when absent."""

    def test_service_filled_when_supplied(self):
        out = query_variants.situational_template_probes(
            "family counselling", ["what does {service} involve for me really"],
            "Vancouver", service="Bowen family systems counselling")
        self.assertEqual(
            out, ["what does Bowen family systems counselling "
                  "involve for me really"])

    def test_service_absent_fills_empty_without_error(self):
        # No service supplied -> {service} becomes empty; no crash, no leftover.
        out = query_variants.situational_template_probes(
            "family counselling", ["is {service} worth it for {base} really"],
            "Vancouver")
        self.assertEqual(len(out), 1)
        self.assertNotIn("{service}", out[0])
        self.assertIn("family counselling", out[0])

    def test_existing_placeholders_still_fill(self):
        out = query_variants.situational_template_probes(
            "couples counselling in vancouver",
            ["what should I expect from a first {base} session in {city}"],
            "Vancouver")
        self.assertEqual(
            out,
            ["what should I expect from a first couples counselling "
             "session in Vancouver"])

    def test_unknown_placeholder_skipped(self):
        out = query_variants.situational_template_probes(
            "family counselling", ["broken {nope} template here now"],
            "Vancouver")
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
