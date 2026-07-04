"""
Tests for the FAQ / Answer-Extraction Plan payload wiring.

Spec: seo_geo_review_20260704.md T.1 / G.2 / C.2
- C.2: bowen_reframe_faqs must carry External Locus (medical-model)
  questions — the reframe candidates — not the Systemic bucket.
- G.2: schema_recommendations.yml is the editorial source for markup
  recommendations; schema_signals summarise observed markup per keyword.
"""
import os
import tempfile
import unittest

from brief_data_extraction import _build_schema_signals
from brief_prompts import build_main_report_payload, load_schema_recommendations

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestBowenReframeFaqWiring(unittest.TestCase):
    """C.2 — the reframe FAQ slot carries External Locus questions."""

    def setUp(self):
        self.extracted = {
            "paa_by_intent": {
                "External Locus": ["How is anxiety diagnosed?"],
                "Systemic": ["How does family of origin affect relationships?"],
                "General": ["How much does therapy cost?"],
            },
        }

    def test_bowen_reframe_faqs_uses_external_locus_bucket(self):
        payload = build_main_report_payload(self.extracted)
        self.assertEqual(payload["bowen_reframe_faqs"], ["How is anxiety diagnosed?"])

    def test_aligned_demand_faqs_uses_systemic_bucket(self):
        payload = build_main_report_payload(self.extracted)
        self.assertEqual(
            payload["aligned_demand_faqs"],
            ["How does family of origin affect relationships?"],
        )

    def test_buckets_capped_at_ten(self):
        self.extracted["paa_by_intent"]["External Locus"] = [f"q{i}" for i in range(15)]
        payload = build_main_report_payload(self.extracted)
        self.assertEqual(len(payload["bowen_reframe_faqs"]), 10)

    def test_missing_paa_by_intent_yields_empty_lists(self):
        payload = build_main_report_payload({})
        self.assertEqual(payload["bowen_reframe_faqs"], [])
        self.assertEqual(payload["aligned_demand_faqs"], [])


class TestSchemaRecommendationsLoader(unittest.TestCase):
    """G.2 — editorial schema recommendation table."""

    def test_repo_file_loads_and_validates(self):
        entries = load_schema_recommendations(
            os.path.join(REPO_ROOT, "schema_recommendations.yml")
        )
        self.assertTrue(entries, "repo schema_recommendations.yml should not be empty")
        contexts = {e["context"] for e in entries}
        self.assertIn("faq_block", contexts)
        faq = next(e for e in entries if e["context"] == "faq_block")
        self.assertIn("FAQPage", faq["schema_types"])

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(load_schema_recommendations("/nonexistent/nope.yml"), [])

    def test_malformed_file_raises_value_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("recommendations:\n  - context: broken\n")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_schema_recommendations(path)
        finally:
            os.unlink(path)

    def test_payload_includes_schema_recommendations(self):
        payload = build_main_report_payload({})
        contexts = {e["context"] for e in payload["schema_recommendations"]}
        self.assertIn("faq_block", contexts)


class TestSchemaSignals(unittest.TestCase):
    """G.2 — per-keyword structured-data summary from enriched rows."""

    def test_rows_without_schema_data_flag_unavailable(self):
        rows = [{"rank": 1, "source": "a.com", "title": "t",
                 "entity_type": "counselling", "content_type": "service"}]
        signals = _build_schema_signals(rows)
        self.assertFalse(signals["data_available"])
        self.assertEqual(signals["enriched_count"], 0)
        self.assertEqual(signals["schema_type_counts"], {})

    def test_enriched_rows_are_summarised(self):
        rows = [
            {"rank": 1, "source": "a.com", "schema_types": ["FAQPage", "Organization"],
             "faq_present": True},
            {"rank": 2, "source": "b.com", "schema_types": ["Organization"],
             "faq_present": False},
            {"rank": 3, "source": "c.com", "schema_types": [], "faq_present": False},
            {"rank": 4, "source": "d.com"},  # not enriched
        ]
        signals = _build_schema_signals(rows)
        self.assertTrue(signals["data_available"])
        self.assertEqual(signals["enriched_count"], 3)
        self.assertEqual(signals["faq_page_count"], 1)
        self.assertEqual(signals["schema_type_counts"],
                         {"Organization": 2, "FAQPage": 1})
        self.assertEqual(len(signals["pages_with_schema"]), 2)
        self.assertEqual(signals["pages_with_schema"][0]["rank"], 1)
        self.assertTrue(signals["pages_with_schema"][0]["faq_present"])

    def test_duplicate_types_on_one_page_count_once(self):
        rows = [{"rank": 1, "source": "a.com",
                 "schema_types": ["FAQPage", "FAQPage"], "faq_present": True}]
        signals = _build_schema_signals(rows)
        self.assertEqual(signals["schema_type_counts"], {"FAQPage": 1})

    def test_only_top_ten_rows_considered(self):
        rows = [{"rank": i, "source": f"s{i}.com", "schema_types": ["Article"],
                 "faq_present": False} for i in range(1, 13)]
        signals = _build_schema_signals(rows)
        self.assertEqual(signals["enriched_count"], 10)

    def test_profile_payload_passes_schema_signals_through(self):
        extracted = {
            "keyword_profiles": {
                "couples therapy": {
                    "schema_signals": {"data_available": True, "enriched_count": 5,
                                       "schema_type_counts": {"FAQPage": 2},
                                       "faq_page_count": 2, "pages_with_schema": []},
                },
            },
        }
        payload = build_main_report_payload(extracted)
        self.assertEqual(
            payload["keyword_profiles"]["couples therapy"]["schema_signals"]
            ["schema_type_counts"],
            {"FAQPage": 2},
        )


if __name__ == "__main__":
    unittest.main()
