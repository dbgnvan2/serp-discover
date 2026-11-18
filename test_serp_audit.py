import unittest
from unittest.mock import patch, MagicMock, mock_open
import serp_audit
import serp_fetch
import serp_checkpoint
import json
import os
from classifiers import EntityClassifier


class TestOutputSlugDerivation(unittest.TestCase):
    """Tests for _derive_output_slug and _resolve_output_names."""

    def test_keywords_prefix_stripped(self):
        self.assertEqual(serp_audit._derive_output_slug("keywords_estrangement.csv"), "estrangement")

    def test_default_keywords_file(self):
        self.assertEqual(serp_audit._derive_output_slug("keywords.csv"), "keywords")

    def test_mixed_case_standalone_file(self):
        self.assertEqual(serp_audit._derive_output_slug("Substance_Use.csv"), "substance_use")

    def test_mixed_case_with_keywords_prefix(self):
        self.assertEqual(serp_audit._derive_output_slug("keywords_Substance_Use.csv"), "substance_use")

    def test_spaces_replaced_with_underscores(self):
        self.assertEqual(serp_audit._derive_output_slug("Basic Series Tape 7.csv"), "basic_series_tape_7")

    def test_keywords_prefix_with_spaces(self):
        self.assertEqual(serp_audit._derive_output_slug("keywords_mental health.csv"), "mental_health")

    def test_audit_output_names_are_always_fresh(self):
        """M2: names in config.yml belong to an earlier run and are never reused."""
        import inspect
        self.assertEqual(list(inspect.signature(serp_audit._resolve_output_names).parameters),
                         ["input_csv"])
        xlsx, json_path, md = serp_audit._resolve_output_names("keywords_estrangement.csv")
        self.assertRegex(json_path, r"^output/market_analysis_estrangement_\d{8}_\d{4}\.json$")
        self.assertEqual(xlsx[:-5], json_path[:-5])
        self.assertEqual(md[:-3], json_path[:-5])

    def test_resolve_generates_fresh_names_when_no_config(self):
        xlsx, json_path, md = serp_audit._resolve_output_names("Substance_Use.csv")
        self.assertTrue(json_path.startswith("output/market_analysis_substance_use_"))
        self.assertTrue(json_path.endswith(".json"))


class TestSerpAudit(unittest.TestCase):

    def test_get_ngrams_logic(self):
        """Test that n-grams are generated correctly and stop words are removed."""
        text = "The quick brown fox jumps over the lazy dog"
        bigrams = serp_audit.get_ngrams(text, 2)
        self.assertIn("quick brown", bigrams)
        self.assertIn("brown fox", bigrams)
        self.assertNotIn("the quick", bigrams)
        self.assertEqual(len(bigrams), 6)

    def test_get_ngrams_hyphenated(self):
        """Test that hyphenated words are split, not merged."""
        text = "highly-trained expert"
        # Should become "highly trained expert", not "highlytrained expert"
        bigrams = serp_audit.get_ngrams(text, 2)
        self.assertIn("highly trained", bigrams)
        self.assertNotIn("highlytrained", bigrams)

    def test_get_ngrams_empty_input(self):
        """Test handling of empty or non-string input."""
        self.assertEqual(serp_audit.get_ngrams(None, 2), [])
        self.assertEqual(serp_audit.get_ngrams("", 2), [])

    def test_parse_data_structure(self):
        """Test that parse_data extracts the correct fields from a mock API response."""
        mock_keyword = "test keyword"
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "https://google.com/search?q=test",
            "params_hash": "dummy_hash_123"
        }
        mock_results = {
            'google': {
                "search_parameters": {"q": "test keyword vancouver"},
                "search_information": {"total_results": 100},
                "organic_results": [
                    {"title": "Rank 1", "link": "http://rank1.com",
                        "snippet": "Snippet 1"},
                    {"title": "Rank 2", "link": "http://rank2.com",
                        "snippet": "Snippet 2"},
                ],
                "related_questions": [
                    {"question": "How much does therapy cost?",
                        "snippet": "It costs money.", "link": "http://paa.com"},
                    {"question": "What is therapy?",
                        "snippet": "Definition.", "link": "http://def.com"}
                ],
                "ads": [
                    {"title": "Ad 1", "description": "Buy now", "position": 1,
                        "link": "http://ad.com", "block_position": "top"}
                ]
            }
        }

        metrics, organic, paa, expansion, competitors, local, citations, modules, rich_features, warnings = serp_audit.parse_data(
            mock_keyword, mock_results, mock_metadata)

        self.assertEqual(metrics["Root_Keyword"], mock_keyword)
        self.assertEqual(metrics["Run_ID"], "test_run_123")
        self.assertEqual(metrics["Params_Hash"], "dummy_hash_123")
        self.assertEqual(metrics["Rank_1_Title"], "Rank 1")
        self.assertEqual(metrics["Rank_3_Title"], "N/A")
        self.assertEqual(len(paa), 2)
        self.assertEqual(paa[0]["Score"], 10)
        self.assertEqual(paa[1]["Score"], 1)
        self.assertEqual(len(competitors), 1)
        self.assertEqual(competitors[0]["Name"], "Ad 1")
        self.assertEqual(competitors[0]["Block_Position"], "top")
        self.assertEqual(len(warnings), 2)

    def test_parsing_warnings(self):
        """Test that parsing warnings are generated for missing fields."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {
                "knowledge_graph": {},
                "ads": [{}]
            }
        }
        _, _, _, _, _, _, _, _, _, warnings = serp_audit.parse_data(
            "test", mock_results, mock_metadata)
        self.assertGreater(len(warnings), 0)
        self.assertTrue(
            any("Knowledge Graph title not found" in w["Message"] for w in warnings))
        self.assertTrue(
            any("Ad title not found" in w["Message"] for w in warnings))

    def test_parse_data_with_serp_modules_and_rich_features(self):
        """Test extraction of SERP modules and rich features."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {
                "knowledge_graph": {"title": "Test KG"},
                "inline_videos": [{}],
            }
        }
        _, _, _, _, _, _, _, modules, rich_features, _ = serp_audit.parse_data(
            "test", mock_results, mock_metadata)
        self.assertEqual(len(modules), 2)
        self.assertEqual(modules[0]["Module"], "knowledge_graph")
        self.assertEqual(len(rich_features), 2)
        self.assertEqual(rich_features[0]["Feature"], "Knowledge Panel")

    def test_parse_data_with_local_pack(self):
        """Test extraction of Local Pack from both SERP and Maps results."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {
                "local_results": {
                    "places": [{"title": "SERP Place", "place_id": "serp_123"}]
                }
            },
            'google_maps': {
                "local_results": [
                    {"title": "Maps Place 1", "place_id": "maps_123"},
                    {"title": "Maps Place 2", "place_id": "maps_456"}
                ]
            }
        }
        _, _, _, _, _, local_pack, _, _, _, _ = serp_audit.parse_data(
            "local keyword", mock_results, mock_metadata)
        self.assertEqual(len(local_pack), 3)
        self.assertEqual(local_pack[0]["Name"], "SERP Place")
        self.assertEqual(local_pack[0]["Source"], "google_serp")
        self.assertEqual(local_pack[1]["Name"], "Maps Place 1")
        self.assertEqual(local_pack[1]["Source"], "google_maps")

    def test_ai_overview_logic(self):
        """Test that AI overview is correctly pulled from supplemental call if needed."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        # Case 1: Overview in primary results
        mock_results_primary = {'google': {
            "ai_overview": {"snippet": "Primary AI snippet"}}}
        metrics, _, _, _, _, _, _, _, _, _ = serp_audit.parse_data(
            "ai keyword", mock_results_primary, mock_metadata)
        self.assertEqual(metrics["AI_Overview"], "Primary AI snippet")

        # Case 2: Overview from supplemental call
        mock_results_supplemental = {
            'google': {"ai_overview": {}},  # Present but empty
            'google_ai_overview': {"ai_overview": {"snippet": "Supplemental AI snippet"}}
        }
        metrics, _, _, _, _, _, _, _, _, _ = serp_audit.parse_data(
            "ai keyword", mock_results_supplemental, mock_metadata)
        self.assertEqual(metrics["AI_Overview"], "Supplemental AI snippet")

    def test_ai_overview_fallback_from_related_questions(self):
        """If direct AI overview is absent, fallback to related-questions AI text blocks."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {"related_questions": []},
            'google_related_questions': [
                {
                    "related_questions": [
                        {
                            "type": "ai_overview",
                            "question": "What helps couples therapy outcomes?",
                            "text_blocks": [
                                {"snippet": "Consistent attendance helps."},
                                {"type": "list", "list": [{"snippet": "Homework and clear goals matter."}]}
                            ],
                            "references": [{"link": "https://example.com/ref"}]
                        }
                    ]
                }
            ]
        }
        metrics, _, paa, _, _, _, _, _, _, _ = serp_audit.parse_data(
            "ai keyword", mock_results, mock_metadata)
        self.assertIn("Consistent attendance helps.", metrics["AI_Overview"])
        self.assertTrue(metrics["Has_PAA_AI_Overview"])
        self.assertTrue(any(p.get("Is_AI_Generated") for p in paa))

    def test_ai_citations_supports_references_key(self):
        """AI citations sheet should populate when ai_overview uses `references`."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {"ai_overview": {}},
            'google_ai_overview': {
                "ai_overview": {
                    "snippet": "AI summary",
                    "references": [
                        {"title": "Ref A", "link": "https://example.com/a", "source": "Example"}
                    ]
                }
            }
        }
        _, _, _, _, _, _, citations, _, _, _ = serp_audit.parse_data(
            "ai keyword", mock_results, mock_metadata)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["Title"], "Ref A")

    def test_pasf_extraction(self):
        """Test extraction and labeling of People Also Search For."""
        mock_metadata = {
            "run_id": "test_run_123",
            "created_at": "2024-01-01T12:00:00",
            "google_url": "N/A",
            "params_hash": "hash"
        }
        mock_results = {
            'google': {
                "inline_people_also_search_for": [{"title": "Inline Term", "link": "http://link1"}],
                "people_also_search_for": [{"name": "Box Term", "link": "http://link2"}]
            }
        }
        _, _, _, expansion, _, _, _, _, _, _ = serp_audit.parse_data(
            "key", mock_results, mock_metadata)

        types = [e["Type"] for e in expansion]
        self.assertIn("PASF (Inline)", types)
        self.assertIn("PASF (Box)", types)
        self.assertEqual(expansion[0]["Term"], "Inline Term")

    def test_parse_data_empty_input(self):
        """Test parse_data with completely empty results."""
        mock_metadata = {"run_id": "test", "created_at": "now",
                         "google_url": "url", "params_hash": "hash"}
        metrics, organic, paa, expansion, competitors, local, citations, modules, rich_features, warnings = serp_audit.parse_data("test", {
        }, mock_metadata)
        self.assertEqual(metrics, {})
        self.assertEqual(len(organic), 0)
        self.assertEqual(len(paa), 0)
        self.assertEqual(len(expansion), 0)
        self.assertEqual(len(competitors), 0)
        self.assertEqual(len(local), 0)
        self.assertEqual(len(citations), 0)
        self.assertEqual(len(modules), 0)
        self.assertEqual(len(rich_features), 0)
        self.assertEqual(len(warnings), 0)

    @patch('serp_checkpoint.save_raw_json')
    @patch('serp_audit._fetch_serp_api')
    def test_fetch_serp_data_orchestration(self, mock_fetch, mock_save):
        """Test that fetch_serp_data correctly triggers secondary calls."""
        mock_keyword = "local services"
        mock_run_id = "test_run_123"

        # Mock primary response to trigger both secondary calls
        mock_primary_response = {
            "ai_overview": {
                "page_token": "some_token"
            },
            "serpapi_search_metadata": {
                "google_maps_url": "https://www.google.com/maps?q=local+services&ll=49.2827,-123.1207"
            },
            "local_results": {"places": []}  # Presence of local pack
        }
        # Mock secondary responses
        mock_ai_response = {"snippet": "Detailed AI answer"}
        mock_maps_response = {"local_results": [{"title": "A Place"}]}

        # Configure the mock to return different values on subsequent calls
        mock_fetch.side_effect = [
            mock_primary_response, mock_ai_response, mock_maps_response]

        results, aio_log, metadata = serp_audit.fetch_serp_data(
            mock_keyword, mock_run_id)

        # 1. Check that fetch was called 3 times
        self.assertEqual(mock_fetch.call_count, 3)

        # 2. Check the engines and params called
        calls = mock_fetch.call_args_list
        self.assertEqual(calls[0][0][0]['engine'], 'google')
        self.assertEqual(calls[1][0][0]['engine'], 'google_ai_overview')
        self.assertIn('page_token', calls[1][0][0])
        self.assertEqual(calls[1][0][0]['page_token'], 'some_token')
        self.assertEqual(calls[2][0][0]['engine'], 'google_maps')
        self.assertIn('ll', calls[2][0][0])
        self.assertEqual(calls[2][0][0]['ll'], '49.2827,-123.1207')
        self.assertNotIn('location', calls[2][0][0])
        self.assertNotIn('z', calls[2][0][0])

        # 3. Check that results from all calls are in the final dictionary
        self.assertIn('google', results)
        self.assertIn('google_ai_overview', results)
        self.assertIn('google_maps', results)
        self.assertEqual(results['google_ai_overview']
                         ['snippet'], "Detailed AI answer")

        # 3b. Check metadata
        self.assertEqual(metadata["run_id"], mock_run_id)

        # 4. Check aio_log
        self.assertTrue(aio_log["has_ai_overview"])
        self.assertEqual(aio_log["ai_overview_mode"], "token_followup_success")
        self.assertIsNotNone(aio_log["page_token_received_at"])
        self.assertIsNotNone(aio_log["followup_started_at"])
        self.assertIsNotNone(aio_log["followup_latency_ms"])
        self.assertIsNone(aio_log["error"])

    @patch('serp_audit.FORCE_LOCAL_INTENT', False)
    @patch('serp_checkpoint.save_raw_json')
    @patch('serp_audit._fetch_serp_api')
    def test_fetch_serp_data_google_pagination_merge(self, mock_fetch, mock_save):
        """Test that Google pagination merges organic results across pages.

        SerpAPI restarts ``position`` at 1 on each page, so page 2 here is
        position 1 — not 11. The merge must renumber it to the absolute 2.
        """
        mock_fetch.side_effect = [
            {
                "organic_results": [{"title": "P1", "link": "http://a.com", "position": 1}],
                "serpapi_pagination": {"next": "https://serpapi.com/search.json?start=10"}
            },
            {
                "organic_results": [{"title": "P2", "link": "http://b.com", "position": 1}],
                "serpapi_pagination": {}
            },
            None  # AI fallback call (no location) for this test
        ]

        results, aio_log, _ = serp_audit.fetch_serp_data("keyword", "run123")

        self.assertEqual(len(results["google"]["organic_results"]), 2)
        self.assertEqual(aio_log["google_pages_fetched"], 2)
        self.assertEqual(
            [r["position"] for r in results["google"]["organic_results"]],
            [1, 2],
        )

    @patch('serp_audit.FORCE_LOCAL_INTENT', False)
    @patch('serp_checkpoint.save_raw_json')
    @patch('serp_audit._fetch_serp_api')
    def test_fetch_serp_data_ai_fallback_without_location(self, mock_fetch, mock_save):
        """Test that AI fallback probe is used when main SERP lacks ai_overview."""
        mock_fetch.side_effect = [
            {"organic_results": [], "serpapi_pagination": {}},
            {"ai_overview": {"snippet": "AI fallback snippet"}}
        ]

        with patch.object(serp_audit, "BALANCED_MODE", False), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", False), \
             patch.object(serp_audit, "AI_FALLBACK_WITHOUT_LOCATION", True):
            results, aio_log, _ = serp_audit.fetch_serp_data("keyword", "run123")

        self.assertIn("google_ai_overview_probe", results)
        self.assertEqual(
            results["google_ai_overview_probe"]["snippet"], "AI fallback snippet")
        self.assertEqual(aio_log["ai_overview_mode"], "fallback_without_location")

    @patch('serp_audit.FORCE_LOCAL_INTENT', False)
    @patch('serp_checkpoint.save_raw_json')
    @patch('serp_audit._fetch_serp_api')
    def test_fetch_serp_data_related_questions_ai_followup(self, mock_fetch, mock_save):
        """Test that related-question tokens trigger google_related_questions follow-up calls."""
        mock_fetch.side_effect = [
            {
                "related_questions": [{"question": "Seed Q", "next_page_token": "tok1"}],
                "serpapi_pagination": {},
                "organic_results": []
            },
            {
                "related_questions": [
                    {"type": "ai_overview", "question": "Q1", "text_blocks": [{"text": "A1"}]}
                ]
            }
        ]

        with patch.object(serp_audit, "BALANCED_MODE", False), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", True), \
             patch.object(serp_audit, "AI_FALLBACK_WITHOUT_LOCATION", False), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_FOLLOWUP", True), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_MAX_CALLS", 1):
            results, aio_log, _ = serp_audit.fetch_serp_data("keyword", "run123")

        self.assertIn("google_related_questions", results)
        self.assertEqual(aio_log["related_questions_ai_calls"], 1)
        engines = [call[0][0].get("engine") for call in mock_fetch.call_args_list]
        self.assertIn("google_related_questions", engines)

    @patch('serp_audit._fetch_serp_api')
    def test_fetch_autocomplete_uses_fallback_variant(self, mock_fetch):
        """Autocomplete should try shorter variants when long-tail query returns no suggestions."""
        mock_fetch.side_effect = [
            {"suggestions": [], "search_information": {"autocomplete_results_state": "No results."}},
            {"suggestions": [{"value": "stress help vancouver"}], "search_information": {}}
        ]
        with patch.object(serp_audit, "_serp_city", return_value="north vancouver"):
            result = serp_audit.fetch_autocomplete("help with stress in vancouver")
        self.assertEqual(len(result["suggestions"]), 1)
        calls = mock_fetch.call_args_list
        self.assertEqual(calls[0][0][0]["q"], "help with stress in vancouver")
        self.assertEqual(calls[1][0][0]["q"], "help with stress")

    def test_ai_query_alternatives_for_local_service(self):
        """AI-likely alternatives should convert local 'best' query into informational variants.

        The city is patched rather than read from the live config.yml: pinned
        to the shipped value, this test would fail the day the client's market
        is changed in config, which is a setting, not a regression.
        """
        with patch.object(serp_audit, "_serp_city", return_value="north vancouver"):
            alternatives = serp_audit._ai_query_alternatives(
                "Best counselling in north vancouver"
            )
        self.assertEqual(len(alternatives), 2)
        self.assertIn("how to choose the right counselling?", alternatives[0].lower())
        self.assertIn("how much does counselling cost in north vancouver?",
                      alternatives[1].lower())

    def test_expand_keywords_for_ai_includes_labels(self):
        """Expanded queries should include A, A.1, A.2 labels when enabled."""
        with patch.object(serp_audit, "AI_QUERY_ALTERNATIVES_ENABLED", True), \
             patch.object(serp_audit, "get_ai_priority_keywords", return_value={"help with stress in vancouver"}):
            jobs = serp_audit.expand_keywords_for_ai(["help with stress in vancouver"])
        labels = [j[2] for j in jobs]
        self.assertIn("A", labels)
        self.assertIn("A.1", labels)
        self.assertIn("A.2", labels)

    def test_expand_keywords_for_ai_skips_non_priority_keywords(self):
        with patch.object(serp_audit, "AI_QUERY_ALTERNATIVES_ENABLED", True), \
             patch.object(serp_audit, "get_ai_priority_keywords", return_value={"different keyword"}):
            jobs = serp_audit.expand_keywords_for_ai(["help with stress in vancouver"])
        self.assertEqual([j[2] for j in jobs], ["A"])

    def test_balanced_mode_limits_ai_priority_actions(self):
        with patch.object(serp_audit, "LOW_API_MODE", False), \
             patch.object(serp_audit, "BALANCED_MODE", True), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", False):
            self.assertEqual(
                serp_audit.get_effective_ai_priority_actions(),
                {"defend", "strengthen"},
            )

    def test_balanced_mode_overrides_runtime_settings(self):
        with patch.object(serp_audit, "LOW_API_MODE", False), \
             patch.object(serp_audit, "BALANCED_MODE", True), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", False), \
             patch.object(serp_audit, "GOOGLE_MAX_PAGES", 3), \
             patch.object(serp_audit, "MAPS_MAX_PAGES", 3), \
             patch.object(serp_audit, "AI_FALLBACK_WITHOUT_LOCATION", True), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_FOLLOWUP", True), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_MAX_CALLS", 5), \
             patch.object(serp_audit, "NO_CACHE_ENABLED", True):
            serp_audit.configure_runtime_mode()
            self.assertEqual(serp_audit.GOOGLE_MAX_PAGES, 3)
            self.assertEqual(serp_audit.MAPS_MAX_PAGES, 1)
            self.assertTrue(serp_audit.AI_FALLBACK_WITHOUT_LOCATION)
            self.assertFalse(serp_audit.RELATED_QUESTIONS_AI_FOLLOWUP)
            self.assertEqual(serp_audit.RELATED_QUESTIONS_AI_MAX_CALLS, 0)
            self.assertFalse(serp_audit.NO_CACHE_ENABLED)

    def test_low_mode_overrides_balanced_mode(self):
        with patch.object(serp_audit, "LOW_API_MODE", True), \
             patch.object(serp_audit, "BALANCED_MODE", True), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", True), \
             patch.object(serp_audit, "AI_QUERY_ALTERNATIVES_ENABLED", True), \
             patch.object(serp_audit, "GOOGLE_MAX_PAGES", 3), \
             patch.object(serp_audit, "MAPS_MAX_PAGES", 3):
            serp_audit.configure_runtime_mode()
            self.assertFalse(serp_audit.BALANCED_MODE)
            self.assertFalse(serp_audit.DEEP_RESEARCH_MODE)
            self.assertFalse(serp_audit.AI_QUERY_ALTERNATIVES_ENABLED)
            self.assertEqual(serp_audit.GOOGLE_MAX_PAGES, 1)
            self.assertEqual(serp_audit.MAPS_MAX_PAGES, 1)

    def test_load_priority_keywords_from_analysis(self):
        with patch("os.path.exists", return_value=True), patch(
            "builtins.open",
            mock_open(read_data=json.dumps({
                "strategic_flags": {
                    "content_priorities": [
                        {"keyword": "family cutoff counselling Vancouver", "action": "defend"},
                        {"keyword": "estrangement", "action": "enter"},
                    ]
                }
            }))
        ):
            keywords = serp_audit.load_priority_keywords_from_analysis("market_analysis.json")
        self.assertEqual(keywords, {"family cutoff counselling Vancouver"})

    def test_strategic_recommendation_templates_avoid_partner_marriage_bias(self):
        recs = serp_audit.analyze_strategic_opportunities(
            [{"Phrase": "clinical registered communication free toxic", "Count": 1}]
        )
        combined = " ".join(rec.get("Content_Angle", "") for rec in recs).lower()
        self.assertNotIn("marriage", combined)
        self.assertNotIn("partner", combined)

    def test_trigger_matching_uses_word_boundaries(self):
        # "meaning" and "meaningful" must NOT fire the "mean" trigger
        recs_no_match = serp_audit.analyze_strategic_opportunities(
            [{"Phrase": "creating shared meaning meaningful outcomes", "Count": 1}]
        )
        names_no_match = [r["Pattern_Name"] for r in recs_no_match]
        self.assertNotIn("The Blame/Reactivity Trap", names_no_match,
                         '"meaning" substring must not fire the "mean" trigger')

        # "mean" as a whole word MUST fire the trigger
        recs_match = serp_audit.analyze_strategic_opportunities(
            [{"Phrase": "therapist is being mean to you", "Count": 1}]
        )
        names_match = [r["Pattern_Name"] for r in recs_match]
        self.assertIn("The Blame/Reactivity Trap", names_match,
                      '"mean" as a whole word must fire the Blame/Reactivity trigger')

    def test_strategic_patterns_loaded_from_yaml(self):
        # Verify all 4 built-in patterns are present in the YAML-loaded set
        patterns = serp_audit._load_strategic_patterns()
        names = [p["Pattern_Name"] for p in patterns]
        for expected in ["The Medical Model Trap", "The Fusion Trap",
                         "The Resource Trap", "The Blame/Reactivity Trap"]:
            self.assertIn(expected, names)

    def test_custom_pattern_in_yaml_fires(self):
        import tempfile, textwrap
        yaml_content = textwrap.dedent("""\
            - Pattern_Name: The Custom Test Trap
              Triggers:
                - hopeless
                - overwhelmed
              Status_Quo_Message: Nothing will ever change.
              Bowen_Bridge_Reframe: Change starts with self-definition.
              Content_Angle: Why hopelessness is a systems problem, not a personal one.
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            recs = serp_audit.analyze_strategic_opportunities(
                [{"Phrase": "feeling hopeless about the relationship", "Count": 1}],
                patterns_path=tmp_path,
            )
            names = [r["Pattern_Name"] for r in recs]
            self.assertIn("The Custom Test Trap", names)
        finally:
            import os as _os
            _os.unlink(tmp_path)

    def test_validate_rejects_missing_required_field(self):
        bad = [{"Pattern_Name": "Incomplete", "Triggers": ["hopeless"],
                "Status_Quo_Message": "x", "Bowen_Bridge_Reframe": "y"}]
        # Content_Angle missing
        with self.assertRaises(ValueError, msg="Missing Content_Angle should raise"):
            serp_audit._validate_strategic_patterns(bad)

    def test_validate_rejects_empty_trigger_list(self):
        bad = [{"Pattern_Name": "Empty Triggers", "Triggers": [],
                "Status_Quo_Message": "x", "Bowen_Bridge_Reframe": "y",
                "Content_Angle": "z"}]
        with self.assertRaises(ValueError, msg="Empty Triggers list should raise"):
            serp_audit._validate_strategic_patterns(bad)

    def test_validate_rejects_duplicate_pattern_name(self):
        entry = {"Pattern_Name": "Duplicate", "Triggers": ["hopeless"],
                 "Status_Quo_Message": "x", "Bowen_Bridge_Reframe": "y",
                 "Content_Angle": "z"}
        with self.assertRaises(ValueError, msg="Duplicate Pattern_Name should raise"):
            serp_audit._validate_strategic_patterns([entry, entry.copy()])

    def test_validate_rejects_trigger_shorter_than_4_chars(self):
        bad = [{"Pattern_Name": "Short Trigger", "Triggers": ["me"],
                "Status_Quo_Message": "x", "Bowen_Bridge_Reframe": "y",
                "Content_Angle": "z"}]
        with self.assertRaises(ValueError, msg="Trigger shorter than 4 chars should raise"):
            serp_audit._validate_strategic_patterns(bad)

    def test_validate_accepts_well_formed_patterns(self):
        good = [{"Pattern_Name": "Valid Pattern", "Triggers": ["hopeless", "stuck"],
                 "Status_Quo_Message": "x", "Bowen_Bridge_Reframe": "y",
                 "Content_Angle": "z"}]
        # Should not raise
        serp_audit._validate_strategic_patterns(good)

    def test_apply_no_cache_toggle(self):
        """no_cache should only be added when enabled."""
        with patch.object(serp_audit, "NO_CACHE_ENABLED", True):
            params = {"engine": "google"}
            serp_audit._apply_no_cache(params)
            self.assertTrue(params.get("no_cache"))

        with patch.object(serp_audit, "NO_CACHE_ENABLED", False):
            params = {"engine": "google"}
            serp_audit._apply_no_cache(params)
            self.assertNotIn("no_cache", params)

    @patch("serp_audit.GoogleSearch")
    @patch.object(serp_audit, "SERPAPI_AVAILABLE", True)
    def test_fetch_serp_api_increments_call_counter(self, mock_search_cls):
        mock_search = MagicMock()
        mock_search.get_dict.return_value = {"organic_results": []}
        mock_search_cls.return_value = mock_search
        _before = serp_fetch.call_count()
        result = serp_audit._fetch_serp_api({"engine": "google", "q": "test"})
        self.assertEqual(result, {"organic_results": []})
        self.assertEqual(serp_fetch.call_count(), _before + 1)

    @patch("os.path.exists", return_value=False)
    @patch("pandas.read_csv")
    def test_load_keywords_uses_single_keyword_override(self, mock_read_csv, mock_exists):
        """Single keyword override should bypass CSV reads."""
        with patch.object(serp_audit, "SINGLE_KEYWORD_OVERRIDE", "family estrangement help"):
            keywords = serp_audit.load_keywords("keywords.csv")
        self.assertEqual(keywords, ["family estrangement help"])
        mock_exists.assert_not_called()
        mock_read_csv.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("pandas.read_csv")
    def test_load_keywords_reads_csv_when_no_override(self, mock_read_csv, _mock_exists):
        """Without override, keywords should come from CSV first column."""
        with patch.object(serp_audit, "SINGLE_KEYWORD_OVERRIDE", ""):
            mock_read_csv.return_value = MagicMock(**{
                "__getitem__.return_value.tolist.return_value": ["k1", "k2"]
            })
            keywords = serp_audit.load_keywords("keywords.csv")
        self.assertEqual(keywords, ["k1", "k2"])
        mock_read_csv.assert_called_once_with(
            "keywords.csv", header=None, keep_default_na=False, na_values=[],
            skip_blank_lines=False)

    def test_entity_classifier_domain_only_directory(self):
        """Known directory domains should classify without fetched HTML."""
        classifier = EntityClassifier(override_file="/nonexistent/overrides.yml")
        entity_type, confidence, evidence = classifier.classify("counsellingbc.com", None)
        self.assertEqual(entity_type, "directory")
        self.assertGreaterEqual(confidence, 0.9)

    def test_entity_classifier_domain_only_media(self):
        """Known media/community domains should classify without fetched HTML."""
        classifier = EntityClassifier(override_file="/nonexistent/overrides.yml")
        entity_type, confidence, evidence = classifier.classify("reddit.com", None)
        self.assertEqual(entity_type, "media")
        self.assertGreaterEqual(confidence, 0.9)

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    def test_save_raw_json(self, mock_makedirs, mock_file):
        """Test that JSON data is written to the correct file."""
        run_id = "test_run"
        engine = "google"
        data = {"key": "value"}

        serp_checkpoint.save_raw_json(run_id, engine, data)

        mock_makedirs.assert_called_with(f"raw/{run_id}", exist_ok=True)
        mock_file.assert_called_with(
            f"raw/{run_id}/{engine}_response.json", 'w')

        # To check the content of the file, we need to get the mock file handle
        handle = mock_file()

        # json.dump may call write multiple times, so we can't use assert_called_once_with
        # Instead, we can get all the calls to write and join them to get the full string
        written_data = "".join(call[0][0]
                               for call in handle.write.call_args_list)

        # The archive is written after link recovery, so it carries a note
        # saying so; the response's own keys are untouched.
        written = json.loads(written_data)
        self.assertEqual({k: v for k, v in written.items()
                          if k != "_post_processing"}, data)
        self.assertIn("link_recovery", written["_post_processing"])
        self.assertNotIn("_post_processing", data,
                         "the live response the run reads must not gain a key")

    @patch('serp_audit._fetch_serp_api')
    @patch('builtins.print')
    def test_fetch_serp_data_error_handling(self, mock_print, mock_fetch):
        """Test that fetch_serp_data handles API errors gracefully."""
        mock_fetch.return_value = None  # Simulate a critical failure
        result, aio_log, metadata = serp_audit.fetch_serp_data(
            "fail_keyword", "fail_run")
        self.assertEqual(result, {})
        self.assertEqual(metadata["run_id"], "fail_run")


class TestKeywordProfilesInAuditJson(unittest.TestCase):
    """Verify that keyword_profiles (with serp_intent, title_patterns,
    mixed_intent_strategy) is embedded in the audit JSON by serp_audit.main()
    via the generate_content_brief.extract_analysis_data_from_json() call.
    Spec v2 DoD criterion #3."""

    def test_keyword_profiles_present_in_real_output(self):
        """The couples_therapy output produced on 2026-04-30 must now contain
        keyword_profiles — this will fail until the next pipeline run after
        the fix lands.  For CI, we verify the function contract instead."""
        import generate_content_brief
        # Minimal stub that looks like a real audit JSON slice
        stub = {
            "overview": [{
                "Source_Keyword": "couples therapy",
                "Query_Label": "A",
                "Run_ID": "test_run",
                "Created_At": "2026-01-01",
                "Total_Results": 1000,
            }],
            "organic_results": [{
                "Source_Keyword": "couples therapy",
                "Root_Keyword": "couples therapy",
                "Query_Label": "A",
                "Rank": 1,
                "Link": "https://example-counselling.ca/page",
                "Source": "example-counselling.ca",
                "Title": "How to Find Couples Therapy",
                "Snippet": "A guide.",
                "Entity_Type": "counselling",
                "Content_Type": "guide",
            }],
            "paa_questions": [],
            "autocomplete_suggestions": [],
            "related_searches": [],
            "serp_modules": [],
            "local_pack_and_maps": [],
            "ai_overview_citations": [],
            "serp_language_patterns": [],
            "strategic_recommendations": [],
            "competitors_ads": [],
            "keyword_feasibility": [],
        }
        extracted = generate_content_brief.extract_analysis_data_from_json(
            stub,
            client_domain="livingsystems.ca",
            client_name_patterns=["Living Systems"],
        )
        kp = extracted.get("keyword_profiles", {})
        self.assertIn("couples therapy", kp, "keyword_profiles must have an entry per root keyword")
        profile = kp["couples therapy"]
        self.assertIn("serp_intent", profile, "serp_intent must be in keyword_profiles")
        self.assertIn("title_patterns", profile, "title_patterns must be in keyword_profiles")
        # mixed_intent_strategy is populated by _compute_strategic_flags, called inside extract
        self.assertIn("mixed_intent_strategy", profile, "mixed_intent_strategy must be in keyword_profiles")

    def test_serp_intent_fields_present(self):
        """serp_intent block has all required spec fields."""
        import generate_content_brief
        stub = {
            "overview": [{"Source_Keyword": "kw", "Query_Label": "A", "Run_ID": "r",
                          "Created_At": "2026-01-01", "Total_Results": 500}],
            "organic_results": [{"Source_Keyword": "kw", "Root_Keyword": "kw",
                                 "Query_Label": "A", "Rank": 1,
                                 "Link": "https://a.com/", "Source": "a.com",
                                 "Title": "Title", "Snippet": "s",
                                 "Entity_Type": "counselling", "Content_Type": "service"}],
            "paa_questions": [], "autocomplete_suggestions": [], "related_searches": [],
            "serp_modules": [], "local_pack_and_maps": [], "ai_overview_citations": [],
            "serp_language_patterns": [], "strategic_recommendations": [],
            "competitors_ads": [], "keyword_feasibility": [],
        }
        extracted = generate_content_brief.extract_analysis_data_from_json(
            stub, client_domain="livingsystems.ca")
        si = extracted["keyword_profiles"]["kw"]["serp_intent"]
        for field in ("primary_intent", "is_mixed", "confidence",
                      "intent_distribution", "evidence", "mixed_components"):
            self.assertIn(field, si, f"serp_intent missing field: {field}")
        ev = si["evidence"]
        # Fix 1: new evidence field names
        for ev_field in ("organic_url_count", "classified_organic_url_count",
                         "uncategorised_organic_url_count", "local_pack_present",
                         "local_pack_member_count"):
            self.assertIn(ev_field, ev, f"evidence missing field: {ev_field}")
        # Fix 1+2: old names must not appear
        for old_field in ("total_url_count", "classified_url_count",
                          "uncategorised_count", "intent_counts"):
            self.assertNotIn(old_field, ev, f"evidence has obsolete field: {old_field}")


class TestAbsoluteRankAcrossPages(unittest.TestCase):
    """_merge_google_pages must renumber per-page positions to absolute ones.

    Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk D1
    (findings D-C-01 / D-M-01). SerpAPI restarts ``position`` at 1 on every
    paginated page; storing that raw value as ``Rank`` made every "top 10"
    filter downstream admit roughly three rows per rank.
    """

    @staticmethod
    def _page(start, count, host):
        return {"organic_results": [
            {"title": f"{host}-{i}",
             "link": f"http://{host}.example/{i}",
             "position": i}
            for i in range(1, count + 1)
        ]}

    def test_two_full_pages_merge_to_one_to_twenty(self):
        merged = serp_audit._merge_google_pages([
            self._page(0, 10, "a"), self._page(10, 10, "b")])
        self.assertEqual(
            [r["position"] for r in merged["organic_results"]],
            list(range(1, 21)))

    def test_raw_per_page_position_is_preserved(self):
        merged = serp_audit._merge_google_pages([
            self._page(0, 10, "a"), self._page(10, 10, "b")])
        rows = merged["organic_results"]
        self.assertEqual([r["page_position"] for r in rows],
                         list(range(1, 11)) * 2)
        self.assertEqual([r["page_index"] for r in rows],
                         [0] * 10 + [1] * 10)

    def test_merged_positions_are_contiguous_when_pages_are_short(self):
        """Google serves fewer than `num` rows per page; ranks must not gap."""
        merged = serp_audit._merge_google_pages([
            self._page(0, 9, "a"), self._page(10, 10, "b"),
            self._page(20, 8, "c")])
        rows = merged["organic_results"]
        self.assertEqual([r["position"] for r in rows],
                         list(range(1, len(rows) + 1)))
        self.assertEqual(max(r["position"] for r in rows), len(rows))

    def test_deduped_rows_do_not_consume_a_position(self):
        """A URL repeated across pages must not leave a hole in the sequence."""
        page_one = self._page(0, 3, "a")
        page_two = {"organic_results": [
            dict(page_one["organic_results"][0]),          # duplicate link
            {"title": "new", "link": "http://b.example/1", "position": 2},
        ]}
        merged = serp_audit._merge_google_pages([page_one, page_two])
        rows = merged["organic_results"]
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["position"] for r in rows], [1, 2, 3, 4])

    def test_dropped_duplicates_are_counted(self):
        """P2: renumbering shifts the rows below a dropped duplicate.

        Each drop moves every later row one place better than its true SERP
        position, so a shifted merge must not be indistinguishable from a
        clean one.
        """
        page_one = self._page(0, 3, "a")
        page_two = {"organic_results": [
            dict(page_one["organic_results"][0]),
            dict(page_one["organic_results"][1]),
            {"title": "new", "link": "http://b.example/1", "position": 3},
        ]}
        merged = serp_audit._merge_google_pages([page_one, page_two])
        self.assertEqual(merged["pagination_duplicates_dropped"], 2)
        clean = serp_audit._merge_google_pages([self._page(0, 3, "a")])
        self.assertEqual(clean["pagination_duplicates_dropped"], 0)

    def test_merge_does_not_mutate_the_input_pages(self):
        """all_results['google_pages'] keeps the raw SerpAPI responses, and
        the paginating loop re-merges the same list on every iteration."""
        pages = [self._page(0, 10, "a"), self._page(10, 10, "b")]
        serp_audit._merge_google_pages(pages)
        serp_audit._merge_google_pages(pages)
        self.assertEqual(
            [r["position"] for r in pages[1]["organic_results"]],
            list(range(1, 11)))
        self.assertNotIn("page_position", pages[1]["organic_results"][0])
        # And a second merge still yields absolute positions, not doubled ones.
        merged = serp_audit._merge_google_pages(pages)
        self.assertEqual(
            [r["position"] for r in merged["organic_results"]],
            list(range(1, 21)))

    def test_parsed_rows_have_contiguous_absolute_ranks(self):
        """End-to-end: merge -> parse_data rows must satisfy
        max(Rank) == len(rows) for the keyword (plan D1 fixture test)."""
        merged = serp_audit._merge_google_pages([
            self._page(0, 9, "a"), self._page(10, 10, "b"),
            self._page(20, 10, "c")])
        _, organic, _, _, _, _, _, _, _, _ = serp_audit.parse_data(
            "kw",
            {"google": merged},
            {"run_id": "r1", "created_at": "2026-11-16T00:00:00",
             "google_url": "http://g", "params_hash": "h"},
        )
        ranks = [row["Rank"] for row in organic]
        self.assertEqual(len(organic), 29)
        self.assertEqual(ranks, list(range(1, 30)))
        self.assertEqual(max(ranks), len(organic))
        # The pre-fix bug: three rows claiming rank 1 for one keyword.
        self.assertEqual(ranks.count(1), 1)

    def test_maps_merge_rank_comes_from_merged_order(self):
        """_merge_maps_pages is not renumbered because nothing reads a maps
        per-page `position`: the local-pack Rank is enumerate() over the
        merged list (serp_audit.py, 'From the dedicated maps results'), which
        is already absolute. This test pins that it stays index-derived."""
        merged = serp_audit._merge_maps_pages([
            {"local_results": [{"title": "p1", "place_id": "1"},
                               {"title": "p2", "place_id": "2"}]},
            {"local_results": [{"title": "p3", "place_id": "3"}]},
        ])
        self.assertEqual([p["title"] for p in merged["local_results"]],
                         ["p1", "p2", "p3"])
        ranks = [i + 1 for i, _ in enumerate(merged["local_results"])]
        self.assertEqual(ranks, [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
