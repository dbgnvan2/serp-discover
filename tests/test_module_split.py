"""
Tests for Fix I.5 — split generate_content_brief.py into five sub-modules.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import importlib
import json
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURE_JSON = os.path.join(_REPO_ROOT, "output", "market_analysis_couples_therapy_20260501_1517.json")
_BASELINE_DIR = os.path.join(_REPO_ROOT, "tests", "fixtures")


class TestI51FilesExistWithFunctions(unittest.TestCase):
    """I.5.1 — Five new files exist and contain the listed functions."""

    _EXPECTED = {
        "brief_data_extraction": [
            "extract_analysis_data_from_json",
            "_extract_domain",
            "_safe_int",
            "_top_sources_for_keyword",
            "_normalize_text",
            "_classify_entity_distribution",
            "_entity_label_reason_text",
            "_client_match_patterns",
            "_contains_phrase",
            "_extract_excerpt",
            "_parse_trigger_words",
            "_count_terms_in_texts",
            "_compute_strategic_flags",
            "_classify_paa_intent",
            "_build_feasibility_summary",
        ],
        "brief_validation": [
            "validate_llm_report",
            "validate_extraction",
            "validate_advisory_briefing",
            "_mixed_keyword_dominance_profiles",
            "_label_requires_mixed",
            "_label_requires_plurality",
            "has_hard_validation_failures",
            "partition_validation_issues",
        ],
        "brief_prompts": [
            "_extract_code_block_after_heading",
            "_read_prompt_file",
            "load_prompt_blocks",
            "load_single_prompt",
            "build_user_prompt",
            "build_main_report_payload",
            "build_correction_message",
            "append_interpretation_notes",
        ],
        "brief_llm": [
            "run_llm_report",
        ],
        "brief_rendering": [
            "generate_brief",
            "generate_local_report",
            "list_recommendations",
            "generate_serp_intent_section",
            "score_paa_for_brief",
            "get_relevant_paa",
            "get_relevant_competitors",
            "_dedupe_question_records",
            "_infer_intent_text",
            "_score_keyword_opportunity",
            "write_validation_artifact",
            "load_brief_pattern_routing",
        ],
    }

    def test_i51_files_exist_with_functions(self):
        for module_name, expected_fns in self._EXPECTED.items():
            path = os.path.join(_REPO_ROOT, f"{module_name}.py")
            self.assertTrue(os.path.exists(path), f"{module_name}.py does not exist")
            mod = importlib.import_module(module_name)
            for fn in expected_fns:
                self.assertTrue(
                    hasattr(mod, fn),
                    f"{module_name}.{fn} not found after split"
                )


class TestI52MainModuleSize(unittest.TestCase):
    """I.5.2 — generate_content_brief.py is under 400 lines after split."""

    def test_i52_main_module_size(self):
        path = os.path.join(_REPO_ROOT, "generate_content_brief.py")
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        self.assertLessEqual(
            len(lines), 400,
            f"generate_content_brief.py is {len(lines)} lines (limit: 400)"
        )


class TestI54PipelineOutputUnchanged(unittest.TestCase):
    """I.5.4 — Brief pipeline output is structurally unchanged after the split."""

    @classmethod
    def setUpClass(cls):
        import generate_content_brief as gcb
        if not os.path.exists(_FIXTURE_JSON):
            raise unittest.SkipTest(f"Fixture not found: {_FIXTURE_JSON}")
        with open(_FIXTURE_JSON, encoding="utf-8") as f:
            data = json.load(f)
        recs = data.get("strategic_recommendations", [])
        cls.briefs = [gcb.generate_brief(data, rec_index=i) for i in range(len(recs))]

    def _load_baseline(self, index: int) -> str:
        path = os.path.join(_BASELINE_DIR, f"brief_baseline_couples_therapy_r{index}.md")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_i54_rec0_output_unchanged(self):
        self.assertEqual(self.briefs[0], self._load_baseline(0),
                         "Brief for rec 0 changed after module split")

    def test_i54_rec1_output_unchanged(self):
        self.assertEqual(self.briefs[1], self._load_baseline(1),
                         "Brief for rec 1 changed after module split")

    def test_i54_rec2_output_unchanged(self):
        self.assertEqual(self.briefs[2], self._load_baseline(2),
                         "Brief for rec 2 changed after module split")
