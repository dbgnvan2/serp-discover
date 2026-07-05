"""
test_feasibility.py
~~~~~~~~~~~~~~~~~~~
Tests for feasibility.py — compute_feasibility() and generate_hyper_local_pivot().
All tests are pure-Python with no I/O or external dependencies.
"""

import unittest
from feasibility import (
    compute_feasibility,
    generate_hyper_local_pivot,
    HIGH_FEASIBILITY_MAX_GAP,
    MODERATE_FEASIBILITY_MAX_GAP,
    SCORE_NORMALISER,
)

NEIGHBOURHOODS = ["Lonsdale", "Edgemont Village", "Lynn Valley", "Deep Cove", "Canyon Heights"]


class TestComputeFeasibility(unittest.TestCase):

    # --- Status labels ---

    def test_high_feasibility(self):
        result = compute_feasibility(50, [53])
        self.assertEqual(result["feasibility_status"], "High Feasibility")

    def test_moderate_feasibility(self):
        result = compute_feasibility(40, [50])
        self.assertEqual(result["feasibility_status"], "Moderate Feasibility")

    def test_low_feasibility(self):
        result = compute_feasibility(30, [60])
        self.assertEqual(result["feasibility_status"], "Low Feasibility")

    # --- Boundary values (gap must be ≤ threshold for that tier) ---

    def test_boundary_gap_5_is_high(self):
        result = compute_feasibility(45, [50])
        self.assertEqual(result["gap"], 5.0)
        self.assertEqual(result["feasibility_status"], "High Feasibility")

    def test_boundary_gap_6_is_moderate(self):
        result = compute_feasibility(44, [50])
        self.assertEqual(result["gap"], 6.0)
        self.assertEqual(result["feasibility_status"], "Moderate Feasibility")

    def test_boundary_gap_15_is_moderate(self):
        result = compute_feasibility(35, [50])
        self.assertEqual(result["gap"], 15.0)
        self.assertEqual(result["feasibility_status"], "Moderate Feasibility")

    def test_boundary_gap_16_is_low(self):
        result = compute_feasibility(34, [50])
        self.assertEqual(result["gap"], 16.0)
        self.assertEqual(result["feasibility_status"], "Low Feasibility")

    # --- Numeric calculations ---

    def test_avg_serp_da_is_mean_of_competitors(self):
        result = compute_feasibility(30, [40, 60])
        self.assertEqual(result["avg_serp_da"], 50.0)

    def test_gap_is_avg_minus_client(self):
        result = compute_feasibility(30, [40, 60])
        self.assertEqual(result["gap"], 20.0)

    def test_client_da_echoed_in_result(self):
        result = compute_feasibility(35, [50, 60])
        self.assertEqual(result["client_da"], 35)

    def test_feasibility_score_between_0_and_1(self):
        for client, competitors in [(10, [80, 90]), (50, [51]), (0, [100])]:
            result = compute_feasibility(client, competitors)
            score = result["feasibility_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_high_feasibility_has_high_score(self):
        result = compute_feasibility(48, [50])  # gap = 2
        self.assertGreater(result["feasibility_score"], 0.9)

    def test_low_feasibility_has_low_score(self):
        result = compute_feasibility(20, [60])  # gap = 40 → capped at 0
        self.assertEqual(result["feasibility_score"], 0.0)

    def test_multiple_competitors_averaged(self):
        result = compute_feasibility(35, [40, 50, 60])
        self.assertAlmostEqual(result["avg_serp_da"], 50.0)
        self.assertAlmostEqual(result["gap"], 15.0)

    # --- Edge cases ---

    def test_empty_competitor_list_returns_low_feasibility(self):
        result = compute_feasibility(35, [])
        self.assertEqual(result["feasibility_status"], "Low Feasibility")
        self.assertIsNone(result["avg_serp_da"])
        self.assertIsNone(result["gap"])
        self.assertIsNone(result["feasibility_score"])

    def test_client_da_higher_than_competitors_gives_negative_gap(self):
        """Client already outranks competitors — should still be High Feasibility."""
        result = compute_feasibility(70, [50])
        self.assertLess(result["gap"], 0)
        self.assertEqual(result["feasibility_status"], "High Feasibility")


class TestGenerateHyperLocalPivot(unittest.TestCase):

    def _low_feas(self, avg_da=52):
        return {"status": "Low Feasibility", "avg_competitor_da": avg_da}

    def _high_feas(self):
        return {"status": "High Feasibility", "avg_competitor_da": 38}

    # --- Stay the course ---

    def test_high_feasibility_returns_stay_the_course(self):
        result = generate_hyper_local_pivot(
            "Couples Counselling", "North Vancouver", self._high_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(result["pivot_status"], "Stay the course")
        self.assertIsNone(result["suggested_keyword"])

    def test_moderate_feasibility_returns_stay_the_course(self):
        feas = {"status": "Moderate Feasibility", "avg_competitor_da": 45}
        result = generate_hyper_local_pivot(
            "Couples Counselling", "North Vancouver", feas, NEIGHBOURHOODS
        )
        self.assertEqual(result["pivot_status"], "Stay the course")

    # --- Pivot triggered ---

    def test_low_feasibility_returns_pivoting_status(self):
        result = generate_hyper_local_pivot(
            "Couples Counselling", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(result["pivot_status"], "Pivoting to Hyper-Local")

    def test_suggested_keyword_combines_root_and_neighbourhood(self):
        result = generate_hyper_local_pivot(
            "Couples Counselling", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertIn("Couples Counselling", result["suggested_keyword"])
        self.assertTrue(
            any(nb in result["suggested_keyword"] for nb in NEIGHBOURHOODS)
        )

    # --- Determinism ---

    def test_default_strategy_is_deterministic(self):
        r1 = generate_hyper_local_pivot(
            "Family Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        r2 = generate_hyper_local_pivot(
            "Family Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(r1["suggested_keyword"], r2["suggested_keyword"])

    def test_first_strategy_picks_first_neighbourhood(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS, strategy="first"
        )
        self.assertEqual(result["suggested_keyword"], f"Therapy {NEIGHBOURHOODS[0]}")

    def test_random_strategy_still_returns_a_variant(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS, strategy="random"
        )
        self.assertTrue(
            any(result["suggested_keyword"] == f"Therapy {nb}" for nb in NEIGHBOURHOODS)
        )

    # --- all_variants ---

    def test_all_variants_length_equals_neighbourhood_count(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(len(result["all_variants"]), len(NEIGHBOURHOODS))

    def test_all_variants_each_contains_root_keyword(self):
        result = generate_hyper_local_pivot(
            "Anxiety Support", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        for variant in result["all_variants"]:
            self.assertIn("Anxiety Support", variant)

    def test_all_variants_populated_even_for_stay_the_course(self):
        """Variants are always built so the report can show them as options."""
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._high_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(len(result["all_variants"]), len(NEIGHBOURHOODS))

    # --- Strategy text ---

    def test_strategy_text_contains_location(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertIn("North Vancouver", result["strategy"])

    def test_strategy_text_contains_avg_da(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(avg_da=52), NEIGHBOURHOODS
        )
        self.assertIn("52", result["strategy"])

    def test_strategy_text_contains_chosen_neighbourhood(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS, strategy="first"
        )
        self.assertIn(NEIGHBOURHOODS[0], result["strategy"])

    # --- Edge cases ---

    def test_empty_neighbourhoods_returns_stay_the_course(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(), []
        )
        self.assertEqual(result["pivot_status"], "Stay the course")
        self.assertEqual(result["all_variants"], [])

    def test_original_keyword_echoed_in_result(self):
        result = generate_hyper_local_pivot(
            "Family Systems Therapy", "North Vancouver", self._low_feas(), NEIGHBOURHOODS
        )
        self.assertEqual(result["original_keyword"], "Family Systems Therapy")

    def test_avg_competitor_da_echoed_in_result(self):
        result = generate_hyper_local_pivot(
            "Therapy", "North Vancouver", self._low_feas(avg_da=61), NEIGHBOURHOODS
        )
        self.assertEqual(result["avg_competitor_da"], 61)


class TestRecommendedPlayColumn(unittest.TestCase):
    """RP-C.1 — feasibility_*.md renders a Recommended Play column that carries the
    pre-computed verdict for non-service keywords instead of a pivot.
    Spec: seo_geo_review_20260704.md (T.4)."""

    CONFIG = {"analysis_report": {"client_name": "Living Systems"},
              "feasibility": {"client_da": 35}}

    def _row(self, kw, status="Low Feasibility", pivot_status="Stay the course"):
        return {
            "Keyword": kw,
            "Query_Label": "A",
            "client_da": 35,
            "avg_serp_da": 60,
            "gap": 25,
            "feasibility_status": status,
            "pivot_status": pivot_status,
            "suggested_keyword": "",
            "Source_Keyword": kw,
        }

    def test_rpc1_recommended_play_column_extraction_not_pivot(self):
        from run_feasibility import generate_feasibility_report
        kw = "birth order and personality"
        rows = [self._row(kw)]  # non-service informational: chip B emits no pivot
        kp = {kw: {"recommended_play": {
            "play": "extraction_play",
            "label": "Extraction Play",
            "strategy_text": "Reformat the page answer-first for AIO extraction.",
            "evidence": ["AIO present", "cited-but-not-ranking competitors"],
            "data_available": True,
        }}}
        report = generate_feasibility_report(rows, self.CONFIG, "market_analysis_x.json",
                                             keyword_profiles=kp)
        # Header carries the new column.
        self.assertIn("Recommended Play", report)
        # The keyword's row shows the extraction play + strategy, NOT a hyper-local pivot.
        row_line = next(l for l in report.splitlines() if l.startswith(f"| {kw} |"))
        self.assertIn("Extraction Play", row_line)
        self.assertIn("answer-first", row_line)
        self.assertNotIn("Pivoting to Hyper-Local", row_line)
        # No fabricated pivot suggestion for this non-service keyword.
        self.assertIn("*(stay the course)*", row_line)

    def test_rpc1_recommended_play_honest_when_data_missing(self):
        from run_feasibility import generate_feasibility_report
        kw = "estrangement counselling"
        rows = [self._row(kw)]
        kp = {kw: {"recommended_play": {
            "play": "extraction_play",
            "label": "Extraction Play",
            "strategy_text": "",
            "evidence": [],
            "data_available": False,
        }}}
        report = generate_feasibility_report(rows, self.CONFIG, "market_analysis_x.json",
                                             keyword_profiles=kp)
        row_line = next(l for l in report.splitlines() if l.startswith(f"| {kw} |"))
        self.assertIn("inputs missing", row_line.lower())

    def test_rpc1_no_verdict_renders_dash(self):
        from run_feasibility import generate_feasibility_report
        kw = "no play keyword"
        rows = [self._row(kw)]
        report = generate_feasibility_report(rows, self.CONFIG, "market_analysis_x.json",
                                             keyword_profiles={})  # no profile at all
        row_line = next(l for l in report.splitlines() if l.startswith(f"| {kw} |"))
        # Play cell is an em dash, not a crash or a fabricated verdict.
        cells = [c.strip() for c in row_line.split("|")]
        self.assertIn("—", cells)


if __name__ == "__main__":
    unittest.main()
