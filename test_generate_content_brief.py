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
        self.assertEqual(
            extracted["keyword_profiles"]["estrangement"]["entity_label"],
            "dominated_by_nonprofit",
        )
        self.assertIn("estrangement", extracted["local_pack_summary"]["serp_local_pack_absent"])
        self.assertEqual(extracted["strategic_flags"]["visibility_concentration"], "critical")
        self.assertEqual(extracted["strategic_flags"]["content_priorities"][0]["action"], "strengthen")

    def test_validate_extraction_warns_for_missing_data(self):
        warnings = gcb.validate_extraction({"root_keywords": [], "queries": []})
        self.assertGreaterEqual(len(warnings), 1)

    def test_build_main_report_payload_is_compact_and_preserves_needed_fields(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        payload = gcb.build_main_report_payload(extracted)
        self.assertIn("keyword_profiles", payload)
        self.assertIn("client_position", payload)
        self.assertEqual(
            payload["keyword_profiles"]["estrangement"]["entity_label"],
            "dominated_by_nonprofit",
        )
        full_size = len(gcb.json.dumps(extracted, separators=(",", ":"), default=str))
        payload_size = len(gcb.json.dumps(payload, separators=(",", ":"), default=str))
        self.assertLess(payload_size, full_size)

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

    def test_load_prompt_blocks_from_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir) / "prompts"
            prompt_dir.mkdir()
            (prompt_dir / "system.md").write_text("SYSTEM", encoding="utf-8")
            (prompt_dir / "user_template.md").write_text("USER", encoding="utf-8")
            system_prompt, user_template = gcb.load_prompt_blocks(str(prompt_dir))
            self.assertEqual(system_prompt, "SYSTEM")
            self.assertEqual(user_template, "USER")

    def test_load_prompt_blocks_from_legacy_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "legacy.md"
            prompt_file.write_text(
                "### System Prompt\n```text\nSYSTEM\n```\n\n### User Prompt Template\n```text\nUSER\n```\n",
                encoding="utf-8",
            )
            system_prompt, user_template = gcb.load_prompt_blocks(str(prompt_file))
            self.assertEqual(system_prompt, "SYSTEM")
            self.assertEqual(user_template, "USER")

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

    def test_validate_llm_report_flags_speculative_anomaly_language(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        issues = gcb.validate_llm_report(
            "AI Overview is present but returned 0 citations, indicating technical issues or content filtering.",
            extracted,
        )
        self.assertTrue(any("speculative causal language" in issue.lower() for issue in issues))

    def test_validate_llm_report_flags_aio_count_mismatch(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        issues = gcb.validate_llm_report(
            "0 of 1 queries feature AI Overviews.",
            extracted,
        )
        self.assertTrue(any("queries have ai overviews" in issue.lower() for issue in issues))

    def test_has_hard_validation_failures_flags_count_and_entity_issues(self):
        self.assertTrue(
            gcb.has_hard_validation_failures([
                "Report says 5 of 6 queries have AI Overviews, but keyword_profiles shows 6 of 6."
            ])
        )
        self.assertFalse(
            gcb.has_hard_validation_failures([
                "Report contradicts keyword_profiles.entity_label for 'estrangement from adult children': mixed_counselling_legal_media should be described as mixed or contested, not dominant."
            ])
        )
        self.assertFalse(
            gcb.has_hard_validation_failures([
                "Report contains speculative causal language matching pattern: possibly due to"
            ])
        )

    def test_partition_validation_issues_treats_entity_label_as_note(self):
        blocking, notes = gcb.partition_validation_issues([
            "Report contradicts keyword_profiles.entity_label for 'estrangement from adult children': mixed_counselling_legal_media should be described as mixed or contested, not dominant.",
            "Report says 5 of 6 queries have AI Overviews, but keyword_profiles shows 6 of 6.",
        ])
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(blocking), 1)

    def test_append_interpretation_notes_adds_client_facing_note(self):
        report = "## Section 2\nExisting content."
        updated = gcb.append_interpretation_notes(report, [
            "Report contradicts keyword_profiles.entity_label for 'parental alienation therapy BC': mixed_counselling_legal should be described as mixed or contested, not dominant."
        ])
        self.assertIn("## Data Interpretation Notes", updated)
        self.assertIn("parental alienation therapy BC", updated)
        self.assertIn("mixed_counselling_legal", updated)

    def test_validate_llm_report_flags_mixed_keyword_dominance(self):
        extracted = {
            "queries": [],
            "autocomplete_summary": {"trigger_word_hits": {}},
            "tool_recommendations_verified": [],
            "keyword_profiles": {
                "estrangement from adult children": {
                    "entity_distribution": {
                        "counselling": 6,
                        "legal": 4,
                        "directory": 1,
                    },
                    "entity_label": "counselling_plurality",
                }
            },
        }
        report = """
**estrangement from adult children (16,400 total results)**
Counselling entities dominate this landscape, with legal entities secondary.
"""
        issues = gcb.validate_llm_report(report, extracted)
        self.assertTrue(any("too close" in issue.lower() for issue in issues))

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

    def test_validate_advisory_briefing_flags_scope_overstatement(self):
        extracted = gcb.extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )
        issues = gcb.validate_advisory_briefing(
            "Further decline could eliminate your digital presence entirely.",
            extracted,
        )
        self.assertTrue(any("consequence scope" in issue.lower() for issue in issues))

    def test_parse_trigger_words_handles_lists(self):
        parsed = gcb._parse_trigger_words(["clinical", " registered ", "", None])
        self.assertEqual(parsed, ["clinical", "registered"])

    def test_classify_entity_distribution_outputs_expected_labels(self):
        dominant, label = gcb._classify_entity_distribution(
            {"counselling": 6, "media": 6, "legal": 4, "directory": 3}
        )
        self.assertEqual(dominant, "counselling")
        self.assertEqual(label, "mixed_counselling_legal_media")
        dominant, label = gcb._classify_entity_distribution(
            {"legal": 12, "counselling": 5, "government": 7}
        )
        self.assertEqual(dominant, "legal")
        self.assertEqual(label, "legal_plurality")

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

    def test_build_correction_message_uses_template_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "correction.md"
            template_path.write_text(
                "Fix these:\n{{VALIDATION_ISSUES}}\n",
                encoding="utf-8",
            )
            message = gcb.build_correction_message(
                ["Issue one", "Issue two"],
                template_path=str(template_path),
            )
            self.assertIn("Fix these:", message)
            self.assertIn("- Issue one", message)
            self.assertIn("- Issue two", message)

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

    def test_generate_brief_dedupes_and_separates_blame_questions(self):
        data = {
            "strategic_recommendations": [
                {
                    "Pattern_Name": "The Blame/Reactivity Trap",
                    "Status_Quo_Message": "They are the problem",
                    "Bowen_Bridge_Reframe": "Observe self",
                    "Content_Angle": "Reactivity content",
                    "Detected_Triggers": "toxic, abusive",
                }
            ],
            "paa_questions": [
                {"Question": "What are the signs of a toxic adult child?", "Category": "Reactivity", "Source_Keyword": "estrangement"},
                {"Question": "What are the signs of a toxic adult child?", "Category": "Reactivity", "Source_Keyword": "estrangement"},
                {"Question": "When should you stop reaching out to an estranged child?", "Category": "Distress", "Source_Keyword": "estrangement"},
                {"Question": "When to go no-contact with a family member?", "Category": "Reactivity", "Source_Keyword": "estrangement"},
            ],
            "organic_results": [
                {"Rank": 1, "Title": "Toxic family signs", "Snippet": "abusive mean behaviour"},
                {"Rank": 2, "Title": "No-contact with family member", "Snippet": "toxic family member guidance"},
            ],
        }
        brief = gcb.generate_brief(data, 0)
        self.assertEqual(brief.count("What are the signs of a toxic adult child?"), 1)
        self.assertIn("When to go no-contact with a family member?", brief)

    # ─── Spec v2: serp_intent + title_patterns validation ───────────────────

    def _intent_extracted(self, primary_intent, is_mixed=False, confidence="high",
                          dominant_pattern=None):
        """Minimal extracted dict for testing validate_llm_report against
        the new serp_intent / title_patterns fields."""
        return {
            "queries": [],
            "autocomplete_summary": {"trigger_word_hits": {}},
            "tool_recommendations_verified": [],
            "paa_analysis": {"cross_cluster": []},
            "keyword_profiles": {
                "couples therapy vancouver": {
                    "entity_distribution": {},
                    "entity_label": "unclassified",
                    "serp_intent": {
                        "primary_intent": primary_intent,
                        "is_mixed": is_mixed,
                        "confidence": confidence,
                        "intent_distribution": {},
                        "evidence": {
                            "total_url_count": 10,
                            "classified_url_count": 9,
                            "uncategorised_count": 1,
                            "intent_counts": {},
                        },
                    },
                    "title_patterns": (
                        {"pattern_counts": {}, "dominant_pattern": dominant_pattern,
                         "examples": {}, "total_titles": 10}
                        if dominant_pattern is not None
                        else {"pattern_counts": {}, "dominant_pattern": None,
                              "examples": {}, "total_titles": 10}
                    ),
                }
            },
        }

    def test_validate_llm_report_flags_intent_contradiction_hard(self):
        # primary_intent is local but report claims transactional — HARD-FAIL
        extracted = self._intent_extracted(primary_intent="local")
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "This is a transactional-intent SERP dominated by service pages.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        intent_issues = [i for i in issues if "transactional intent" in i.lower()]
        self.assertGreaterEqual(len(intent_issues), 1)
        # Hard-fail check: the issue string must trigger has_hard_validation_failures
        self.assertTrue(gcb.has_hard_validation_failures(intent_issues))

    def test_validate_llm_report_flags_is_mixed_contradiction(self):
        # is_mixed=True but report claims single-intent — HARD-FAIL
        extracted = self._intent_extracted(
            primary_intent="informational", is_mixed=True, confidence="medium"
        )
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "This is a cleanly informational SERP with uniform intent.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        mixed_issues = [i for i in issues if "mixed" in i.lower() and "single-intent" in i.lower()]
        self.assertGreaterEqual(len(mixed_issues), 1)

    def test_validate_llm_report_does_not_flag_low_confidence_intent(self):
        # Low confidence verdicts should NOT trigger hard-fail validation
        extracted = self._intent_extracted(primary_intent="local", confidence="low")
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "This is a transactional-intent SERP — low confidence verdict.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        intent_issues = [i for i in issues if "transactional intent" in i.lower()
                         and "couples therapy vancouver" in i]
        self.assertEqual(len(intent_issues), 0)

    def test_validate_llm_report_passes_correct_intent_verdict(self):
        extracted = self._intent_extracted(primary_intent="informational")
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "This is primarily informational — guides dominate the top results.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        intent_issues = [i for i in issues if "intent" in i.lower()
                         and "couples therapy vancouver" in i]
        self.assertEqual(len(intent_issues), 0)

    def test_validate_llm_report_flags_dominant_pattern_contradiction_soft(self):
        # dominant_pattern=how_to but report claims listicles dominate — SOFT-FAIL
        extracted = self._intent_extracted(
            primary_intent="informational", dominant_pattern="how_to"
        )
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "Listicles dominate the top 10 titles.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        pattern_issues = [i for i in issues if "title_patterns" in i.lower()
                          and "couples therapy vancouver" in i]
        self.assertGreaterEqual(len(pattern_issues), 1)
        # Soft-fail: should NOT trigger has_hard_validation_failures
        self.assertFalse(gcb.has_hard_validation_failures(pattern_issues))
        # Should partition to notes, not blocking
        blocking, notes = gcb.partition_validation_issues(pattern_issues)
        self.assertEqual(len(blocking), 0)
        self.assertGreaterEqual(len(notes), 1)

    def test_mixed_intent_strategy_compete_on_dominant(self):
        """A mixed SERP whose dominant intent matches an intent the client
        already ranks for → compete_on_dominant."""
        keyword_profiles = {
            # Already-ranked client keyword (informational)
            "what is bowen theory": {
                "client_visible": True,
                "client_rank": 5,
                "client_rank_delta": 0,
                "serp_intent": {
                    "primary_intent": "informational",
                    "is_mixed": False,
                    "confidence": "high",
                    "intent_distribution": {"informational": 1.0},
                },
                "total_results": 5000,
                "entity_dominant_type": "media",
                "entity_label": "media_plurality",
            },
            # Mixed-intent target keyword
            "bowen theory courses": {
                "client_visible": False,
                "client_rank": None,
                "client_rank_delta": None,
                "serp_intent": {
                    "primary_intent": "informational",
                    "is_mixed": True,
                    "confidence": "medium",
                    "intent_distribution": {
                        "informational": 0.5,
                        "transactional": 0.5,
                    },
                },
                "total_results": 3000,
                "entity_dominant_type": "education",
                "entity_label": "mixed_education_media",
            },
        }
        flags = gcb._compute_strategic_flags(
            root_keywords=list(keyword_profiles.keys()),
            keyword_profiles=keyword_profiles,
            client_position={"organic": [], "summary": {"keywords_with_any_visibility": ["what is bowen theory"]}},
            total_results_by_kw={},
            paa_analysis={},
            preferred_intents=[],
        )
        target = flags["opportunity_scale"]["bowen theory courses"]
        self.assertEqual(target["mixed_intent_strategy"], "compete_on_dominant")
        # Persisted onto the keyword profile too
        self.assertEqual(
            keyword_profiles["bowen theory courses"]["mixed_intent_strategy"],
            "compete_on_dominant",
        )

    def test_mixed_intent_strategy_backdoor(self):
        """Dominant intent is uncompetable, but a non-dominant intent is in
        preferred_intents → backdoor."""
        keyword_profiles = {
            "couples therapy": {
                "client_visible": False,
                "client_rank": None,
                "client_rank_delta": None,
                "serp_intent": {
                    "primary_intent": "transactional",
                    "is_mixed": True,
                    "confidence": "medium",
                    "intent_distribution": {
                        "transactional": 0.5,
                        "informational": 0.5,
                    },
                },
                "total_results": 10000,
                "entity_dominant_type": "counselling",
                "entity_label": "counselling_plurality",
            },
        }
        flags = gcb._compute_strategic_flags(
            root_keywords=["couples therapy"],
            keyword_profiles=keyword_profiles,
            client_position={"organic": [], "summary": {"keywords_with_any_visibility": []}},
            total_results_by_kw={},
            paa_analysis={},
            preferred_intents=["informational"],  # client can do informational
        )
        target = flags["opportunity_scale"]["couples therapy"]
        self.assertEqual(target["mixed_intent_strategy"], "backdoor")

    def test_mixed_intent_strategy_avoid(self):
        """Dominant intent uncompetable AND no non-dominant intents in
        preferred_intents → avoid."""
        keyword_profiles = {
            "buy therapy app": {
                "client_visible": False,
                "client_rank": None,
                "client_rank_delta": None,
                "serp_intent": {
                    "primary_intent": "commercial_investigation",
                    "is_mixed": True,
                    "confidence": "medium",
                    "intent_distribution": {
                        "commercial_investigation": 0.5,
                        "navigational": 0.5,
                    },
                },
                "total_results": 50000,
                "entity_dominant_type": "directory",
                "entity_label": "directory_plurality",
            },
        }
        flags = gcb._compute_strategic_flags(
            root_keywords=["buy therapy app"],
            keyword_profiles=keyword_profiles,
            client_position={"organic": [], "summary": {"keywords_with_any_visibility": []}},
            total_results_by_kw={},
            paa_analysis={},
            preferred_intents=["informational"],  # not in distribution
        )
        target = flags["opportunity_scale"]["buy therapy app"]
        self.assertEqual(target["mixed_intent_strategy"], "avoid")

    def test_mixed_intent_strategy_null_for_non_mixed(self):
        """Non-mixed keywords get None / null."""
        keyword_profiles = {
            "what is therapy": {
                "client_visible": False,
                "client_rank": None,
                "client_rank_delta": None,
                "serp_intent": {
                    "primary_intent": "informational",
                    "is_mixed": False,
                    "confidence": "high",
                    "intent_distribution": {"informational": 1.0},
                },
                "total_results": 1000,
                "entity_dominant_type": "media",
                "entity_label": "media_plurality",
            },
        }
        flags = gcb._compute_strategic_flags(
            root_keywords=["what is therapy"],
            keyword_profiles=keyword_profiles,
            client_position={"organic": [], "summary": {"keywords_with_any_visibility": []}},
            total_results_by_kw={},
            paa_analysis={},
            preferred_intents=["informational"],
        )
        target = flags["opportunity_scale"]["what is therapy"]
        self.assertIsNone(target["mixed_intent_strategy"])
        self.assertIsNone(keyword_profiles["what is therapy"]["mixed_intent_strategy"])

    def test_validate_llm_report_flags_invented_dominant_pattern(self):
        # dominant_pattern=null but report claims a pattern dominates
        extracted = self._intent_extracted(
            primary_intent="informational", dominant_pattern=None
        )
        report = (
            "**couples therapy vancouver (50,000 total results)**\n"
            "How-to guides dominate the top 10 titles.\n"
        )
        issues = gcb.validate_llm_report(report, extracted)
        invented = [i for i in issues
                    if "no pattern reached the dominance threshold" in i.lower()]
        self.assertGreaterEqual(len(invented), 1)


if __name__ == "__main__":
    unittest.main()
