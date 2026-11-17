"""Review chunk D4b — four numbers whose name did not describe their input.

- D-M-11: `mixed_intent_strategy` gated on where the client ALREADY RANKS, so
  a dominant intent the client serves was labelled a "backdoor" and a client
  with no rankings could never get `compete_on_dominant`; ties were resolved
  by dict order, i.e. SERP row order.
- D-M-12: "market too small" was decided from Google's `total_results`
  estimate — how many pages exist, not how many people search — and a missing
  estimate counted as a measured zero.
- D-M-13: `serp_homogeneity` took `max()` over `pattern_counts` including the
  `other` catch-all, so ten unclassifiable titles scored "perfectly uniform";
  the entity distribution counted every query label while the intent verdict
  beside it used label A only.
- D-M-19: the pivot gate read a token guess from the keyword string, not the
  measured SERP intent, and the explanation asserted directory dominance
  whatever the page held.

(D4.6-D4.10)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_data_extraction as bde
import commodity_score
import feasibility


def _flags(profiles, preferred, min_volume=None):
    return bde._compute_strategic_flags(
        root_keywords=list(profiles),
        keyword_profiles=profiles,
        client_position={"organic": [],
                         "summary": {"keywords_with_any_visibility": [
                             kw for kw, p in profiles.items()
                             if p.get("client_visible")]}},
        total_results_by_kw={kw: p.get("total_results", 1000)
                             for kw, p in profiles.items()},
        paa_analysis={},
        preferred_intents=preferred,
        min_volume_for_investment=min_volume)


def _mixed(dist, **extra):
    return dict({"client_visible": False, "total_results": 1000,
                 "total_results_measured": True,
                 "serp_intent": {"primary_intent": "mixed", "is_mixed": True,
                                 "confidence": "medium",
                                 "intent_distribution": dist}}, **extra)


class TestMixedIntentIsDefinedByWhatTheClientServes(unittest.TestCase):
    """D4.6"""

    def test_a_dominant_preferred_intent_is_not_a_backdoor(self):
        profiles = {"kw": _mixed({"informational": 6, "local": 4})}
        _flags(profiles, ["informational", "local"])
        self.assertEqual(profiles["kw"]["mixed_intent_strategy"],
                         "compete_on_dominant")

    def test_a_tie_gives_one_answer_whatever_the_row_order(self):
        answers = []
        for dist in ({"local": 5, "informational": 5},
                     {"informational": 5, "local": 5}):
            profiles = {"kw": _mixed(dist)}
            _flags(profiles, ["informational"])
            answers.append((profiles["kw"]["mixed_intent_strategy"],
                            tuple(profiles["kw"]["mixed_intent_dominant"]),
                            profiles["kw"]["mixed_intent_dominant_tied"]))
        self.assertEqual(answers[0], answers[1])
        self.assertTrue(answers[0][2], "the tie must be reported as a tie")

class TestOnlyADemandFigureConcludesAboutDemand(unittest.TestCase):
    """D4.7"""

    def _action(self, moz, total=150, measured=True):
        profiles = {"kw": {
            "client_visible": False, "moz": moz, "total_results": total,
            "total_results_measured": measured,
            "serp_intent": {"primary_intent": "informational",
                            "is_mixed": False}}}
        flags = _flags(profiles, ["informational"], min_volume=20)
        row = flags["opportunity_scale"]["kw"]
        return row["action"], row["reason"]

    def test_a_measured_volume_below_the_floor_is_a_skip(self):
        action, reason = self._action({"data_available": True, "volume": 10})
        self.assertEqual(action, "skip")
        self.assertIn("Monthly search volume 10", reason)

    def test_a_small_result_count_is_not_a_small_market(self):
        """150 results used to mean "market too small"; it means 150 pages."""
        action, reason = self._action(
            {"data_available": True, "volume": 400}, total=150)
        self.assertEqual(action, "enter")
        self.assertNotIn("too small", reason)

class TestUnclassifiedIsNotUniform(unittest.TestCase):
    """D4.8"""

    def test_titles_that_matched_no_shape_are_not_one_shape(self):
        self.assertIsNone(commodity_score.serp_homogeneity(
            None, {"pattern_counts": {"other": 10}}))

    def test_an_unmeasurable_homogeneity_stays_in_the_denominator(self):
        """P7: it is floored, never renormalised away, like similarity."""
        profiles = {"kw": {"entity_distribution": {},
                           "title_patterns": {"pattern_counts": {"other": 5}},
                           "has_ai_overview": True,
                           "top5_organic": [{"title": "a"}, {"title": "b"},
                                            {"title": "c"}]}}
        rows, _ = commodity_score.compute_commodity(
            profiles, {"organic_results": []}, None)
        row = rows[0]
        self.assertIsNone(row["serp_homogeneity"])
        self.assertTrue(row["low_confidence"])
        # Floored and KEPT in the denominator: the published score is the one
        # _composite gives for homogeneity 0.0, not the higher one it would
        # give if the unmeasured term were excluded and its weight
        # redistributed. Read from the module's own weights, so a config edit
        # cannot make this guard vacuous.
        weights = commodity_score.resolve_weights(None)
        floored = {"answer_similarity": 0.0, "serp_homogeneity": 0.0,
                   "aio_present": 1.0, "one_paragraph_answerable": None}
        dropped = dict(floored, serp_homogeneity=None)
        self.assertEqual(row["commodity_score"],
                         commodity_score._composite(floored, weights))
        self.assertGreater(commodity_score._composite(dropped, weights),
                           row["commodity_score"])


class TestANullSubScoreDoesNotDestroyTheSection(unittest.TestCase):
    """D4b cold review, finding 1."""

    def test_an_unmeasurable_homogeneity_renders_as_a_dash(self):
        """Reproduced: float(None) raised inside _safe_section, which drops the
        whole commodity table for EVERY keyword because one keyword had
        nothing to measure. answer_similarity had the guard; homogeneity did
        not."""
        profiles = {
            "measurable": {"entity_distribution": {"directory": 8, "clinic": 2},
                           "title_patterns": {"pattern_counts": {"listicle": 7}},
                           "has_ai_overview": True,
                           "top5_organic": [{"title": "a b c"}, {"title": "a b d"},
                                            {"title": "a b e"}]},
            "unmeasurable": {"entity_distribution": {},
                             "title_patterns": {"pattern_counts": {"other": 5}},
                             "has_ai_overview": False,
                             "top5_organic": [{"title": "x"}, {"title": "y"},
                                              {"title": "z"}]},
        }
        rows, rollup = commodity_score.compute_commodity(
            profiles, {"organic_results": []}, None)
        self.assertIsNone(
            [r for r in rows if r["keyword"] == "unmeasurable"][0]
            ["serp_homogeneity"])
        out = "\n".join(commodity_score.render_commodity_section(rows, rollup))
        # The table is there, both keywords in it, the unmeasured cell a dash.
        self.assertIn("| measurable |", out)
        self.assertIn("| unmeasurable |", out)
        self.assertIn(" — |", out)


class TestEntityShareIsAShareOfOneSerp(unittest.TestCase):
    """D4.9"""

    @staticmethod
    def _rows(label_a, other_labels):
        rows = []
        for i, entity in enumerate(label_a):
            rows.append({"Source_Keyword": "kw", "Query_Label": "A",
                         "Rank": i + 1, "Entity_Type": entity,
                         "Content_Type": "service_page", "Title": f"t{i}",
                         "Link": f"https://a{i}.com", "Source": f"a{i}.com"})
        for i, entity in enumerate(other_labels):
            rows.append({"Source_Keyword": "kw", "Query_Label": "P",
                         "Rank": i + 1, "Entity_Type": entity,
                         "Content_Type": "directory", "Title": f"b{i}",
                         "Link": f"https://b{i}.com", "Source": f"b{i}.com"})
        return rows

    def _profile(self, label_a, other_labels):
        data = {"organic_results": self._rows(label_a, other_labels),
                "overview": [{"Source_Keyword": "kw", "Query_Label": "A",
                              "Total_Results": 5000}],
                "paa_questions": []}
        out = bde.extract_analysis_data_from_json(
            data, client_domain="example.ca", preferred_intents=["local"])
        return out["keyword_profiles"]["kw"]

    def test_other_labels_do_not_enter_the_distribution(self):
        profile = self._profile(["clinic"] * 10, ["directory"] * 14)
        self.assertEqual(profile["entity_distribution"], {"clinic": 10})
        self.assertEqual(profile["entity_distribution_rows"], 10)

    def _from_rows(self, rows):
        data = {"organic_results": rows,
                "overview": [{"Source_Keyword": "kw", "Query_Label": "A",
                              "Total_Results": 5000}],
                "paa_questions": []}
        out = bde.extract_analysis_data_from_json(
            data, client_domain="example.ca", preferred_intents=["local"])
        return out["keyword_profiles"]["kw"]

    def test_the_rows_are_one_serps_worth_or_say_they_are_not(self):
        """P2: the same result twice is dropped; a real second fetch is marked.

        Measured on this project's own runs: one keyword had 28 label-A rows,
        two or three per rank, all carrying one Run_ID — so scoping to label A
        alone left the denominator inflated, and the share was still quoted as
        a top-10 share (D4b cold review, finding 3).
        """
        one_serp = self._rows(["clinic"] * 10, [])

        # The identical result written twice: kept once, the drop counted.
        duplicated = self._from_rows(one_serp + one_serp)
        self.assertEqual(duplicated["entity_distribution_rows"], 10)
        self.assertEqual(duplicated["entity_distribution_duplicate_rows"], 10)
        self.assertTrue(duplicated["entity_distribution_single_serp"])

        # A DIFFERENT result at the same rank: a real second fetch. Kept, and
        # the share is marked as not one SERP's rather than passing as a
        # top-10 share.
        second_fetch = [dict(r, Entity_Type="directory",
                             Link=f"https://second{i}.com")
                        for i, r in enumerate(one_serp)]
        two_serps = self._from_rows(one_serp + second_fetch)
        self.assertEqual(two_serps["entity_distribution_rows"], 20)
        self.assertEqual(two_serps["entity_distribution_rank_repeats"], 10)
        self.assertFalse(two_serps["entity_distribution_single_serp"])


class TestThePivotReadsWhatWasMeasured(unittest.TestCase):
    """D4.10"""

    _BASE = dict(primary_keyword="couples counselling north vancouver",
                 non_profit_location="North Vancouver",
                 feasibility_results={"status": "Low Feasibility",
                                      "avg_serp_da": 70},
                 neighborhoods=["Lonsdale"])

    def _pivot(self, **kwargs):
        return feasibility.generate_hyper_local_pivot(**self._BASE, **kwargs)

    def test_a_measured_informational_verdict_blocks_the_pivot(self):
        result = self._pivot(
            is_service_like=True,
            serp_intent={"primary_intent": "informational", "is_mixed": False})
        self.assertEqual(result["pivot_status"], "No pivot — informational")
        self.assertEqual(result["gate_source"], "serp_intent.primary_intent")

    def test_a_serp_of_clinics_is_not_called_directory_dominated(self):
        result = self._pivot(
            is_service_like=True,
            serp_intent={"primary_intent": "local", "is_mixed": False},
            entity_distribution={"counselling": 10})
        self.assertNotIn("directories", result["strategy"])
        self.assertIn("dominated by counselling results (10 of 10)",
                      result["strategy"])

if __name__ == "__main__":
    unittest.main()
