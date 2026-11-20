"""`Total_Results` is the fetched page's result count, not a market size.

Google has largely stopped publishing the "About N results" estimate. On the
2026-11-19 run, which asked for 100 results per query, it returned 98-100 for
all ten — and that figure was being printed as each keyword's scale, summed
across PAA clusters, used as the content-plan tie-break, and checked by the
brief validator for faithful restatement.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_data_extraction as bde
import brief_prompts

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_JSON = os.path.join(
    REPO, "output",
    "market_analysis_family-of-origin-seo-phrases_20261119_1442.json")


class TestTheCredibilityRule(unittest.TestCase):

    def test_a_figure_no_larger_than_the_request_is_not_an_estimate(self):
        for value in (1, 10, 98, 99, 100):
            with self.subTest(value=value):
                credible, _ = bde._total_results_is_credible(
                    {"Total_Results": value, "Results_Requested": 100})
                self.assertFalse(credible)

    def test_a_figure_larger_than_the_request_is_an_estimate(self):
        for value in (101, 4300, 4_300_000):
            with self.subTest(value=value):
                credible, _ = bde._total_results_is_credible(
                    {"Total_Results": value, "Results_Requested": 100})
                self.assertTrue(credible)

    def test_the_boundary_is_the_request_itself(self):
        """100 of 100 is the page; 101 of 100 cannot be."""
        self.assertFalse(bde._total_results_is_credible(
            {"Total_Results": 100, "Results_Requested": 100})[0])
        self.assertTrue(bde._total_results_is_credible(
            {"Total_Results": 101, "Results_Requested": 100})[0])

    def test_a_smaller_request_makes_the_same_figure_credible(self):
        """At num=10, a 98 estimate is not the page we asked for."""
        self.assertTrue(bde._total_results_is_credible(
            {"Total_Results": 98, "Results_Requested": 10})[0])


class TestWhatTheJudgementRestedOn(unittest.TestCase):

    def test_the_runs_own_record_is_preferred(self):
        _, basis = bde._total_results_is_credible(
            {"Total_Results": 500, "Results_Requested": 100}, 10)
        self.assertEqual(basis, bde.TOTAL_RESULTS_BASIS_RECORDED)

    def test_config_is_the_fallback_for_an_older_run(self):
        credible, basis = bde._total_results_is_credible(
            {"Total_Results": 100}, 100)
        self.assertFalse(credible)
        self.assertEqual(basis, bde.TOTAL_RESULTS_BASIS_CONFIG)

    def test_an_unknowable_request_size_withholds_the_figure(self):
        """Not a claim that the market is small — the absence of a claim."""
        for default in (None, 0, "", "many"):
            with self.subTest(default=default):
                credible, basis = bde._total_results_is_credible(
                    {"Total_Results": 4_300_000}, default)
                self.assertFalse(credible)
                self.assertEqual(basis, bde.TOTAL_RESULTS_BASIS_UNKNOWN)

    def test_a_missing_figure_is_not_credible(self):
        for row in ({}, {"Total_Results": None}, {"Total_Results": "N/A"},
                    {"Total_Results": ""}):
            with self.subTest(row=row):
                self.assertFalse(
                    bde._total_results_is_credible(dict(row, Results_Requested=100))[0])


class TestTheRealRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(RUN_JSON):
            raise unittest.SkipTest("run output not present")
        with open(RUN_JSON, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        cls.extracted = bde.extract_analysis_data_from_json(
            cls.data, "livingsystems.ca", results_requested_default=100)

    def test_no_keyword_claims_a_measured_market_size(self):
        profiles = self.extracted["keyword_profiles"]
        self.assertEqual(len(profiles), 10)
        for kw, profile in profiles.items():
            with self.subTest(keyword=kw):
                self.assertFalse(profile["total_results_measured"])

    def test_the_raw_figures_really_are_page_sized(self):
        """Guards the premise, so the test cannot pass for the wrong reason."""
        values = [r.get("Total_Results") for r in self.data["overview"]]
        self.assertTrue(values)
        self.assertTrue(all(0 < v <= 100 for v in values), values)

    def test_the_basis_is_recorded(self):
        for kw, profile in self.extracted["keyword_profiles"].items():
            with self.subTest(keyword=kw):
                self.assertEqual(profile["total_results_basis"],
                                 bde.TOTAL_RESULTS_BASIS_CONFIG)


class TestNothingDownstreamStatesIt(unittest.TestCase):

    def _extract(self, total_results, requested=100, default=100):
        data = {
            "overview": [{
                "Run_ID": "r1", "Source_Keyword": "kw one", "Query_Label": "A",
                "Search_Query_Used": "kw one", "Total_Results": total_results,
                "Results_Requested": requested,
            }],
            "organic_results": [],
        }
        return bde.extract_analysis_data_from_json(
            data, "livingsystems.ca", results_requested_default=default)

    def test_the_prompt_payload_omits_an_uncredible_figure(self):
        extracted = self._extract(100)
        payload = brief_prompts.build_main_report_payload(extracted)
        profile = payload["keyword_profiles"]["kw one"]
        self.assertNotIn("total_results", profile)

    def test_the_prompt_payload_carries_a_real_estimate(self):
        extracted = self._extract(4_300_000)
        payload = brief_prompts.build_main_report_payload(extracted)
        self.assertEqual(
            payload["keyword_profiles"]["kw one"]["total_results"], 4_300_000)

    def test_the_queries_block_omits_it_too(self):
        extracted = self._extract(100)
        payload = brief_prompts.build_main_report_payload(extracted)
        self.assertTrue(payload.get("queries"), "no query rows to check")
        for item in payload["queries"]:
            with self.subTest(query=item.get("query_label")):
                self.assertNotIn("total_results", item)

    def test_the_scale_sentence_says_no_estimate_was_given(self):
        extracted = self._extract(100)
        scale = extracted["strategic_flags"]["opportunity_scale"]["kw one"]
        self.assertIn("no result-count estimate", scale["reason"])
        self.assertNotIn("100 total results", scale["reason"])

    def test_the_tie_break_ignores_an_uncredible_figure(self):
        extracted = self._extract(100)
        priorities = extracted["strategic_flags"]["content_priorities"]
        self.assertTrue(priorities)
        for row in priorities:
            with self.subTest(keyword=row["keyword"]):
                self.assertFalse(row["total_results_measured"])

    def test_the_tie_break_reads_the_measured_flag(self):
        src = open(os.path.join(REPO, "brief_data_extraction.py"),
                   encoding="utf-8").read()
        self.assertIn(
            '-(x["total_results"] if x["total_results_measured"] else 0)', src)


class TestTheClusterSumSaysWhatItRestsOn(unittest.TestCase):

    def _extract(self, totals, requested=100):
        overview, organic = [], []
        for i, (kw, total) in enumerate(totals.items()):
            overview.append({
                "Run_ID": "r1", "Source_Keyword": kw, "Query_Label": "A",
                "Search_Query_Used": kw, "Total_Results": total,
                "Results_Requested": requested,
                "PAA_Questions": "shared question?",
            })
            organic.append({
                "Run_ID": "r1", "Source_Keyword": kw, "Root_Keyword": kw,
                "Rank": 1, "Link": f"https://e{i}.ca", "Title": "t",
            })
        return bde.extract_analysis_data_from_json(
            {"overview": overview, "organic_results": organic,
             "paa_questions": [
                 {"Source_Keyword": kw, "Question": "shared question?"}
                 for kw in totals]},
            "livingsystems.ca", results_requested_default=requested)

    def test_page_sized_figures_contribute_nothing_to_the_sum(self):
        extracted = self._extract({"kw a": 100, "kw b": 98})
        entries = (extracted["paa_analysis"]["cross_cluster"]
                   + extracted["paa_analysis"]["single_cluster"])
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(question=entry["question"]):
                self.assertEqual(entry["combined_total_results"], 0)
                self.assertEqual(entry["combined_total_results_keywords"], 0)

    def test_a_real_estimate_contributes_and_is_counted(self):
        extracted = self._extract({"kw a": 4_300_000, "kw b": 98})
        entries = (extracted["paa_analysis"]["cross_cluster"]
                   + extracted["paa_analysis"]["single_cluster"])
        totals = {e["combined_total_results"] for e in entries}
        counts = {e["combined_total_results_keywords"] for e in entries}
        self.assertIn(4_300_000, totals)
        self.assertIn(1, counts)


class TestTheRunRecordsWhatItAskedFor(unittest.TestCase):

    def test_the_audit_writes_results_requested(self):
        src = open(os.path.join(REPO, "serp_audit.py"), encoding="utf-8").read()
        self.assertIn('"Results_Requested"', src)

    def test_both_production_call_sites_inject_the_configured_num(self):
        for module in ("brief_data_extraction.py", "brief_rendering.py"):
            with self.subTest(module=module):
                src = open(os.path.join(REPO, module), encoding="utf-8").read()
                self.assertIn("results_requested_default=", src)


class TestThePromptNoLongerCallsItMarketScale(unittest.TestCase):

    def test_no_prompt_offers_estimated_market_scale_as_a_phrase(self):
        for name in ("main_report/system.md", "advisory/system.md",
                     "advisory/user_template.md"):
            with self.subTest(prompt=name):
                text = open(os.path.join(REPO, "prompts", name),
                            encoding="utf-8").read()
                self.assertNotIn('"estimated market scale,"', text)

    def test_the_prompt_says_an_absent_figure_is_not_a_small_one(self):
        text = open(os.path.join(REPO, "prompts/main_report/system.md"),
                    encoding="utf-8").read()
        self.assertIn("absence of a measurement", text)

    def test_the_unconditional_heading_is_gone(self):
        """It printed "(100 total results)" in every keyword heading."""
        text = open(os.path.join(REPO, "prompts/main_report/system.md"),
                    encoding="utf-8").read()
        self.assertNotIn("**[keyword] ([total_results] total results)**", text)

    def test_the_under_500_note_is_conditional(self):
        text = open(os.path.join(REPO, "prompts/main_report/system.md"),
                    encoding="utf-8").read()
        self.assertNotIn("Note if\ntotal_results < 500.", text)


class TestTheValidatorDoesNotCheckAnAbsentFigure(unittest.TestCase):

    def test_the_claim_is_gated_on_measured(self):
        src = open(os.path.join(REPO, "brief_validation.py"),
                   encoding="utf-8").read()
        self.assertIn(
            '"total_results": (profile.get("total_results")\n'
            '                              if profile.get("total_results_measured") else None)',
            src)


if __name__ == "__main__":
    unittest.main()
