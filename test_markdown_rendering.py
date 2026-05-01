"""
Acceptance tests for Fix M1 — markdown rendering of pre-computed SERP intent fields.

Spec: serp_tool1_completion_spec.md M1 acceptance criteria.
Fixture: output/market_analysis_couples_therapy_20260501_0828.json

Note: tests placed in repo root (not tests/) to match this project's test discovery
convention (pytest test_*.py). All existing tests live in the root directory.
"""
import json
import os
import re
import unittest

import generate_insight_report
import generate_content_brief as gcb

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "output",
    "market_analysis_couples_therapy_20260501_0828.json",
)


def _load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestInsightReportSerpIntentSection(unittest.TestCase):
    """M1.A — Section 5b. Per-Keyword SERP Intent in market_analysis MD."""

    @classmethod
    def setUpClass(cls):
        data = _load_fixture()
        cls.report = generate_insight_report.generate_report(data)

    def test_section_5b_header_exists(self):
        self.assertIn("## 5b. Per-Keyword SERP Intent", self.report,
                      "Section ## 5b. Per-Keyword SERP Intent must be present")

    def test_section_5b_appears_exactly_once(self):
        count = len(re.findall(r"5b\. Per-Keyword SERP Intent", self.report))
        self.assertEqual(count, 1)

    def test_section_5b_between_section_5_and_section_6(self):
        pos_5 = self.report.find("## 5. SERP Composition")
        pos_5b = self.report.find("## 5b. Per-Keyword SERP Intent")
        pos_6 = self.report.find("## 6. Market Volatility")
        if pos_5 == -1:
            # Section 5 absent when no metrics DB available — skip position check
            self.assertGreater(pos_5b, 0)
            return
        self.assertGreater(pos_5b, pos_5, "5b must come after Section 5")
        if pos_6 != -1:
            self.assertLess(pos_5b, pos_6, "5b must come before Section 6")

    def test_all_six_keyword_blocks_present(self):
        keywords = [
            "How much is couples therapy in Vancouver?",
            "What type of therapist is best for couples therapy?",
            "couples counselling",
            "effective couples therapy?",
            "how does couples counselling work",
            "success rate of couples therapy?",
        ]
        for kw in keywords:
            self.assertIn(kw, self.report, f"Keyword block missing: {kw}")

    def test_couples_counselling_has_mixed_intent_components(self):
        idx = self.report.find("### couples counselling")
        self.assertGreater(idx, 0)
        block = self.report[idx:idx + 600]
        self.assertIn("Mixed-intent components", block)

    def test_couples_counselling_has_strategy_backdoor(self):
        idx = self.report.find("### couples counselling")
        self.assertGreater(idx, 0)
        block = self.report[idx:idx + 600]
        self.assertIn("backdoor", block)

    def test_cost_keyword_has_no_mixed_intent_line(self):
        # "How much is couples therapy in Vancouver?" is not mixed-intent
        idx = self.report.find("### How much is couples therapy in Vancouver?")
        self.assertGreater(idx, 0)
        # Find end of this keyword block (next ### or ##)
        rest = self.report[idx + 10:]
        next_header = re.search(r"\n(##|###) ", rest)
        block = rest[:next_header.start()] if next_header else rest[:600]
        self.assertNotIn("Mixed-intent components", block)

    def test_therapist_keyword_has_local_pack_present(self):
        idx = self.report.find("### What type of therapist is best for couples therapy?")
        self.assertGreater(idx, 0)
        block = self.report[idx:idx + 600]
        self.assertIn("**Local pack present:** yes", block)

    def test_no_old_feasibility_5b_header(self):
        self.assertNotIn("## 5b. Keyword Feasibility", self.report,
                         "Feasibility must now be Section 5c, not 5b")


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestInsightReportMixedIntentNote(unittest.TestCase):
    """M1.B — Mixed-Intent Strategic Note callout in Section 4."""

    @classmethod
    def setUpClass(cls):
        data = _load_fixture()
        cls.report = generate_insight_report.generate_report(data)

    def test_mixed_intent_note_callout_present(self):
        self.assertIn("⚖️ Mixed-Intent Strategic Note: couples counselling", self.report)

    def test_backdoor_string_in_report(self):
        self.assertIn("backdoor", self.report)

    def test_note_appears_in_section_4(self):
        pos_4 = self.report.find("## 4. Strategic Recommendations")
        pos_note = self.report.find("Mixed-Intent Strategic Note: couples counselling")
        pos_5 = self.report.find("## 5.")
        self.assertGreater(pos_note, pos_4,
                           "Mixed-Intent Note must appear after Section 4 header")
        if pos_5 != -1:
            self.assertLess(pos_note, pos_5,
                            "Mixed-Intent Note must appear before Section 5")

    def test_only_mixed_keywords_get_callout(self):
        # "effective couples therapy?" is NOT mixed — should have no callout
        self.assertNotIn(
            "Mixed-Intent Strategic Note: effective couples therapy?", self.report
        )


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestBriefSerpIntentContext(unittest.TestCase):
    """M1.C — ## 1a. SERP Intent Context in each content brief."""

    @classmethod
    def setUpClass(cls):
        data = _load_fixture()
        cls.data = data
        cls.recs = data.get("strategic_recommendations", [])
        cls.briefs = [gcb.generate_brief(data, rec_index=i) for i in range(len(cls.recs))]

    def test_four_briefs_exist(self):
        self.assertEqual(len(self.briefs), 4)

    def test_all_briefs_have_1a_section(self):
        for i, brief in enumerate(self.briefs):
            self.assertIn(
                "## 1a. SERP Intent Context", brief,
                f"Brief {i + 1} is missing ## 1a. SERP Intent Context"
            )

    def test_1a_appears_before_section_1(self):
        for i, brief in enumerate(self.briefs):
            pos_1a = brief.find("## 1a. SERP Intent Context")
            pos_1 = brief.find("## 1. The Core Conflict")
            self.assertLess(pos_1a, pos_1,
                            f"Brief {i + 1}: 1a must appear before Section 1")

    def test_no_literal_none_in_1a(self):
        for i, brief in enumerate(self.briefs):
            idx = brief.find("## 1a. SERP Intent Context")
            end = brief.find("## 1. The Core Conflict", idx)
            section = brief[idx:end] if end > idx else brief[idx:idx + 400]
            self.assertNotIn("None", section,
                             f"Brief {i + 1}: 1a must not render literal 'None'")
            self.assertNotIn(": null", section.lower(),
                             f"Brief {i + 1}: 1a must not render literal 'null'")

    def test_1a_section_count_in_combined_report(self):
        # Simulate what serp_audit.py produces — count 1a across all 4 briefs combined
        combined = "\n".join(self.briefs)
        count = len(re.findall(r"1a\. SERP Intent Context", combined))
        self.assertEqual(count, 4,
                         f"Expected 4 occurrences of '1a. SERP Intent Context', got {count}")


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestCleanupC1SectionPrefix(unittest.TestCase):
    """C.1 — Section 5b must have the '5b.' prefix."""

    @classmethod
    def setUpClass(cls):
        data = _load_fixture()
        cls.report = generate_insight_report.generate_report(data)

    def test_c11_section_5b_prefix_present(self):
        count = len(re.findall(r"## 5b\. Per-Keyword SERP Intent", self.report))
        self.assertEqual(count, 1,
                         "## 5b. Per-Keyword SERP Intent must appear exactly once")

    def test_c12_no_unprefixed_section_5b(self):
        self.assertNotIn("## Per-Keyword SERP Intent", self.report,
                         "Header without '5b.' prefix must not appear")


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestCleanupC2PatternIntentContext(unittest.TestCase):
    """C.2 — SERP Intent Context line in each Section 4 pattern block."""

    PATTERN_NAMES = [
        "The Medical Model Trap",
        "The Fusion Trap",
        "The Resource Trap",
        "The Blame/Reactivity Trap",
    ]

    @classmethod
    def setUpClass(cls):
        data = _load_fixture()
        cls.report = generate_insight_report.generate_report(data)

    def _get_pattern_block(self, pattern_name: str) -> str:
        idx = self.report.find(f"### 🌉 {pattern_name}")
        if idx == -1:
            return ""
        rest = self.report[idx + len(pattern_name):]
        next_header = re.search(r"\n(##|###) ", rest)
        return rest[:next_header.start()] if next_header else rest[:800]

    def test_c21_all_four_patterns_have_intent_context(self):
        for name in self.PATTERN_NAMES:
            block = self._get_pattern_block(name)
            matches = re.findall(r"\*SERP intent context", block)
            self.assertEqual(len(matches), 1,
                             f"Pattern '{name}' must have exactly one *SERP intent context line")

    def test_c22_medical_model_intent_context_has_real_keyword(self):
        block = self._get_pattern_block("The Medical Model Trap")
        match = re.search(r"\*SERP intent context \(most relevant keyword: ([^)]+)\)", block)
        self.assertIsNotNone(match, "Medical Model Trap must name a specific keyword")
        kw = match.group(1)
        self.assertNotIn("<keyword>", kw)
        self.assertGreater(len(kw), 3)

    def test_c23_mixed_intent_segment_when_applicable(self):
        # "couples counselling" is mixed: informational + local
        # whichever pattern selects it must include the mixed segment
        for name in self.PATTERN_NAMES:
            block = self._get_pattern_block(name)
            if "most relevant keyword: couples counselling" in block:
                self.assertIn("mixed: informational + local", block,
                              f"Pattern '{name}' selects couples counselling — must show mixed components")

    def test_c24_no_template_placeholders_leak(self):
        for name in self.PATTERN_NAMES:
            block = self._get_pattern_block(name)
            for placeholder in ("None", "null", "<keyword>", "<primary_intent>"):
                self.assertNotIn(placeholder, block,
                                 f"Pattern '{name}' must not render literal '{placeholder}'")


if __name__ == "__main__":
    unittest.main()
