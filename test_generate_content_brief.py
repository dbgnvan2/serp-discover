import unittest
import tempfile
from pathlib import Path

import generate_content_brief as gcb


class TestGenerateContentBrief(unittest.TestCase):
    def _sample_data(self):
        return {
            "overview": [
                {
                    "Run_ID": "run_1",
                    "Created_At": "2026-03-10T10:00:00",
                    "Google_URL": "https://google.com/search?q=estrangement",
                    "Source_Keyword": "estrangement",
                    "Query_Label": "A",
                    "Executed_Query": "estrangement vancouver",
                    "Total_Results": 1000,
                    "SERP_Features": "related_questions",
                    "Has_Main_AI_Overview": True,
                    "AI_Overview": "Living Systems helps families.",
                    "Rank_1_Title": "Top result",
                    "Rank_1_Link": "https://example.com/a",
                    "Rank_2_Title": "Second result",
                    "Rank_2_Link": "https://example.com/b",
                    "Rank_3_Title": "Third result",
                    "Rank_3_Link": "https://example.com/c",
                }
            ],
            "organic_results": [
                {
                    "Source_Keyword": "estrangement",
                    "Query_Label": "A",
                    "Rank": 3,
                    "Title": "Client page",
                    "Link": "https://livingsystems.ca/estrangement",
                    "Snippet": "Registered clinical counselling support for estrangement.",
                    "Source": "livingsystems.ca",
                    "Content_Type": "guide",
                    "Entity_Type": "nonprofit",
                    "Rank_Delta": 2,
                }
            ],
            "ai_overview_citations": [
                {
                    "Source_Keyword": "estrangement",
                    "Query_Label": "A",
                    "Title": "Client citation",
                    "Link": "https://livingsystems.ca/guide",
                    "Source": "Living Systems",
                }
            ],
            "paa_questions": [
                {
                    "Question": "How do I cope with estrangement?",
                    "Category": "Distress",
                    "Score": 10,
                    "Source_Keyword": "estrangement",
                    "Snippet": "snippet",
                }
            ],
            "autocomplete_suggestions": [
                {"Source_Keyword": "estrangement", "Suggestion": "estrangement counselling", "Relevance": 500}
            ],
            "related_searches": [
                {"Source_Keyword": "estrangement", "Term": "family estrangement help"}
            ],
            "serp_modules": [
                {"Source_Keyword": "estrangement", "Query_Label": "A", "Present": True, "Module": "ai_overview", "Order": 1}
            ],
            "local_pack_and_maps": [
                {
                    "Source_Keyword": "estrangement",
                    "Query_Label": "A",
                    "Rank": 1,
                    "Name": "Living Systems",
                    "Category": "Counsellor",
                    "Rating": 4.8,
                    "Reviews": 52,
                    "Website": "https://livingsystems.ca",
                }
            ],
            "serp_language_patterns": [
                {"Type": "Bigram", "Phrase": "living systems", "Count": 5},
                {"Type": "Trigram", "Phrase": "family systems theory", "Count": 4},
            ],
            "strategic_recommendations": [
                {
                    "Pattern_Name": "Medical Model Trap",
                    "Triggers": ["clinical", "registered"],
                    "Status_Quo_Message": "Fix the symptom quickly",
                    "Bowen_Bridge_Reframe": "Understand the system",
                    "Content_Angle": "From Symptom to System",
                    "Detected_Triggers": ["clinical"],
                }
            ],
            "competitors_ads": [],
        }

    def test_extract_analysis_data_from_json(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        self.assertEqual(extracted["metadata"]["run_id"], "run_1")
        self.assertIn("estrangement", extracted["root_keywords"])
        self.assertEqual(len(extracted["queries"]), 1)
        self.assertEqual(len(extracted["client_position"]["organic"]), 1)
        self.assertEqual(len(extracted["client_position"]["aio_citations"]), 1)
        self.assertIn("paa_analysis", extracted)
        self.assertIn("tool_recommendations_verified", extracted)
        self.assertIn("keyword_profiles", extracted)
        self.assertIn("competitive_landscape", extracted)
        self.assertIn("strategic_flags", extracted)
        self.assertGreater(
            extracted["tool_recommendations_verified"][0]["verdict_inputs"]["total_trigger_occurrences"],
            0,
        )
        self.assertFalse(extracted["keyword_profiles"]["estrangement"]["has_local_pack"])
        self.assertIn("estrangement", extracted["local_pack_summary"]["serp_local_pack_absent"])
        self.assertEqual(extracted["strategic_flags"]["visibility_concentration"], "critical")
        self.assertEqual(extracted["strategic_flags"]["content_priorities"][0]["action"], "strengthen")

    def test_validate_extraction_warns_for_missing_data(self):
        warnings = gcb.validate_extraction({"root_keywords": [], "queries": []})
        self.assertGreaterEqual(len(warnings), 1)

    def test_generate_local_report_contains_sections(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        report = gcb.generate_local_report(extracted, gcb.DEFAULT_CLIENT_CONTEXT, [])
        self.assertIn("## Section 1: Data Summary", report)
        self.assertIn("## Section 7: Prioritized Content Recommendations", report)
        self.assertIn("estrangement", report)

    def test_load_client_context_from_config(self):
        config = {
            "serpapi": {"location": "Vancouver, BC"},
            "analysis_report": {
                "client_name": "Example Org",
                "client_domain": "example.org",
                "client_name_patterns": ["Example"],
                "org_type": "Nonprofit",
                "framework_description": "Framework",
                "content_focus": "Focus",
                "additional_context": "Context",
                "framework_terms": ["family systems", "differentiation"],
            },
        }
        context = gcb.load_client_context_from_config(config)
        self.assertEqual(context["client_name"], "Example Org")
        self.assertEqual(context["client_domain"], "example.org")
        self.assertEqual(context["location"], "Vancouver, BC")
        self.assertEqual(context["framework_terms"], ["family systems", "differentiation"])

    def test_validate_llm_report_flags_unsupported_claims(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        bad_report = """
**The Medical Model Trap**: SUPPORTED. Registered clinical language appears frequently.
Cross-cutting opportunities appear in toxic relationships.
"toxic family systems" is a high search volume term from autocomplete data.
AI Overviews appear for all 1 queries.
This may indicate a data collection issue.
"""
        issues = gcb.validate_llm_report(bad_report, extracted)
        self.assertGreaterEqual(len(issues), 2)
        self.assertTrue(any("data collection issue" in issue for issue in issues))

    def test_validate_llm_report_flags_monthly_search_claim(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        issues = gcb.validate_llm_report(
            "This keyword gets 1,000 monthly searches.",
            extracted,
        )
        self.assertTrue(any("monthly search volume" in issue.lower() for issue in issues))

    def test_validate_advisory_briefing_flags_overconfident_language(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        extracted["strategic_flags"]["defensive_urgency"] = "high"
        extracted["strategic_flags"]["content_priorities"][0]["keyword"] = "family cutoff counselling Vancouver"
        bad_advisory = """
## The Headline
You are at risk.

## Action 1: Defend
You should work on another page first.
If you don't act now, you'll lose your rank #3 position entirely.

## Action 2
...

## Action 3
...
"""
        issues = gcb.validate_advisory_briefing(bad_advisory, extracted)
        self.assertTrue(any("first action" in issue.lower() for issue in issues))
        self.assertTrue(any("certainty language" in issue.lower() for issue in issues))

    def test_parse_trigger_words_handles_lists(self):
        parsed = gcb._parse_trigger_words(["clinical", " registered ", "", None])
        self.assertEqual(parsed, ["clinical", "registered"])

    def test_write_validation_artifact_creates_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "content_opportunities_report.md"
            artifact = gcb.write_validation_artifact(
                str(out_path),
                "Content Opportunity Report Validation Issues",
                ["Unsupported claim."],
                "Bad draft text.",
            )
            artifact_path = Path(artifact)
            self.assertTrue(artifact_path.exists())
            text = artifact_path.read_text(encoding="utf-8")
            self.assertIn("# Content Opportunity Report Validation Issues", text)
            self.assertIn("- Unsupported claim.", text)
            self.assertIn("Bad draft text.", text)

    def test_generate_brief_uses_theme_relevant_paa_and_competitors(self):
        data = {
            "strategic_recommendations": [
                {
                    "Pattern_Name": "The Resource Trap",
                    "Status_Quo_Message": "Find free help",
                    "Bowen_Bridge_Reframe": "Work the pattern",
                    "Content_Angle": "When free venting costs you more",
                    "Detected_Triggers": "free, low cost, affordable",
                }
            ],
            "paa_questions": [
                {"Question": "When should you stop reaching out to an estranged child?", "Category": "Distress"},
                {"Question": "How to get free grief counselling?", "Category": "Distress"},
                {"Question": "Is there free counseling in BC?", "Category": "Distress"},
                {"Question": "How to get therapy covered in BC?", "Category": "Distress"},
                {"Question": "What are the signs of a toxic adult child?", "Category": "Reactivity"},
            ],
            "organic_results": [
                {"Rank": 1, "Title": "Free grief counselling resources", "Snippet": "Low cost and insurance options."},
                {"Rank": 2, "Title": "Therapy coverage in BC", "Snippet": "How much is covered by insurance."},
                {"Rank": 3, "Title": "Adult child estrangement advice", "Snippet": "When to stop reaching out."},
            ],
        }
        brief = gcb.generate_brief(data, 0)
        self.assertIn("How to get free grief counselling?", brief)
        self.assertIn("How to get therapy covered in BC?", brief)
        self.assertIn("Free grief counselling resources", brief)
        self.assertIn("Therapy coverage in BC", brief)


if __name__ == "__main__":
    unittest.main()
