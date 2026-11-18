"""Review chunk D4a — the report obeys its own gate.

Four places where the report stated a conclusion it contradicted a few lines
later:

- D-M-06: `_get_best_opportunity_keyword` ranked feasibility first and
  treated intent as a tie-break, so the single best opportunity could be a
  keyword whose own action cell read "⛔ Mismatched intent".
- D-M-07: the extraction and local-pivot plays are reachable on feasibility
  `unknown`, and their strategy text asserted a "high DA gap" beside a note
  saying the DA data was unavailable.
- D-C-14: the RC.4.1 evidence block read `title` / `domain`; the producer
  writes `Title` / `Link` / `Source`, so it never rendered on real data.
- D-C-18: section 6 printed "This run: unknown" for two keys
  `get_volatility_metrics` never returned.

(D4.1-D4.5)
"""
import db_connect
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_validation as bv
import generate_insight_report as gir
import play_rendering
import play_routing

_PREFERRED = ["informational", "transactional", "local"]


def _profile(intent, mixed=False, components=None):
    return {"serp_intent": {"primary_intent": intent, "confidence": "high",
                            "is_mixed": mixed,
                            "mixed_components": components or []}}


def _feas(keyword, status):
    return {"Keyword": keyword, "Query_Label": "A", "feasibility_status": status}


class TestTheBestOpportunityPassesTheIntentGate(unittest.TestCase):
    """D4.1 — the headline pick obeys the gate the action column applies."""

    def test_a_mismatched_intent_keyword_is_never_the_best_opportunity(self):
        profiles = {"kwA": _profile("navigational"),
                    "kwB": _profile("informational")}
        feas = [_feas("kwA", "High Feasibility"),
                _feas("kwB", "Moderate Feasibility")]
        best, reason = gir._get_best_opportunity_keyword(profiles, feas, _PREFERRED)
        self.assertEqual(best, "kwB")
        self.assertIn("informational", reason)
        # And the action column agrees with the pick, which is the point.
        self.assertEqual(
            gir._get_keyword_action("kwA", profiles["kwA"], feas[0], _PREFERRED),
            "⛔ Mismatched intent")

    def test_no_eligible_keyword_says_which_gate_stopped_them(self):
        profiles = {"kwA": _profile("navigational"), "kwC": _profile(None)}
        feas = [_feas("kwA", "High Feasibility"), _feas("kwC", "High Feasibility")]
        best, reason = gir._get_best_opportunity_keyword(profiles, feas, _PREFERRED)
        self.assertIsNone(best)
        self.assertIn("does not serve", reason)
        self.assertIn("no SERP intent verdict", reason)

    def test_a_mixed_serp_with_one_preferred_component_still_qualifies(self):
        profiles = {"kwM": _profile("mixed", mixed=True,
                                    components=["informational", "navigational"])}
        feas = [_feas("kwM", "High Feasibility")]
        best, _ = gir._get_best_opportunity_keyword(profiles, feas, _PREFERRED)
        self.assertEqual(best, "kwM")


    def test_an_unclassified_keyword_is_not_told_to_be_pursued(self):
        """Finding 3: Section 0 and the action column must not disagree.

        The intent gate read `if intent and not intent_matches`, so a keyword
        with no intent verdict skipped it and printed ✅ Pursue below a
        Section 0 saying no keyword passes the intent gate.
        """
        profile = _profile(None)
        action = gir._get_keyword_action(
            "kwC", profile, _feas("kwC", "High Feasibility"), _PREFERRED)
        self.assertEqual(action, "❓ Intent unknown")
        best, _ = gir._get_best_opportunity_keyword(
            {"kwC": profile}, [_feas("kwC", "High Feasibility")], _PREFERRED)
        self.assertIsNone(best)

    def test_a_mixed_serp_with_no_components_has_no_verdict(self):
        """"mixed" is a label, not a verdict, when nothing was classified."""
        self.assertEqual(
            gir._get_keyword_action(
                "kwM", _profile("mixed", mixed=True, components=[]),
                _feas("kwM", "High Feasibility"), _PREFERRED),
            "❓ Intent unknown")


class TestNoPlayClaimsAGapNothingMeasured(unittest.TestCase):
    """D4.2 — the strategy text cannot assert an unmeasured DA gap."""

    _SIGNALS = {"serp_intent": {"primary_intent": "informational"},
                "has_ai_overview": True, "has_local_pack": False,
                "aio_divergence": {}}

    def test_unknown_feasibility_gets_the_unknown_wording(self):
        result = play_routing.compute_recommended_play(
            self._SIGNALS, None, "k", ["therapy"])
        self.assertEqual(result["play"], "extraction_play")
        self.assertFalse(result["data_available"]["feasibility"])
        self.assertNotIn("high DA gap", result["strategy_text"])
        self.assertIn("No Domain Authority data", result["strategy_text"])

    def test_measured_low_feasibility_keeps_the_normal_wording(self):
        result = play_routing.compute_recommended_play(
            self._SIGNALS, {"feasibility_status": "Low Feasibility"}, "k",
            ["therapy"])
        self.assertTrue(result["data_available"]["feasibility"])
        self.assertIn("high DA gap", result["strategy_text"])

    def test_the_local_pivot_play_has_the_variant_too(self):
        signals = dict(self._SIGNALS,
                       serp_intent={"primary_intent": "local"},
                       has_ai_overview=False)
        result = play_routing.compute_recommended_play(
            signals, None, "family counselling north vancouver", ["counselling"])
        self.assertEqual(result["play"], "local_pivot_play")
        self.assertNotIn("high DA gap", result["strategy_text"])


    def test_every_play_that_claims_a_gap_on_unknown_feasibility_has_the_variant(self):
        """P5 / finding 4: the catch-all `deprioritize` was reachable too.

        The rule is not "every reachable play needs a variant" —
        `reformat_play` is reachable and makes no DA claim. It is: a play
        reachable on unknown feasibility whose text states a DA direction
        needs one, and the variant must not state it.
        """
        import re
        routing = play_routing.load_play_routing()
        phrases = play_rendering.load_play_vocab()["da_gap_claim_phrases"]

        def claims_a_gap(text):
            return [p.pattern for p in phrases if p.search(text or "")]

        reachable = set()
        for rule in routing["rules"]:
            feas = rule["match"].get("feasibility")
            if feas is None or "unknown" in (
                    feas if isinstance(feas, list) else [feas]):
                reachable.add(rule["play"])
        self.assertIn("deprioritize", reachable)

        claimants = [p for p in reachable
                     if claims_a_gap(routing["plays"][p]["strategy_text"])]
        self.assertTrue(claimants, "no play states a DA direction — "
                                   "the phrase list and the texts have drifted")
        for play_id in claimants:
            variant = routing["plays"][play_id].get(
                "strategy_text_unknown_feasibility")
            self.assertTrue(variant, f"{play_id} claims a DA gap and is "
                                     f"reachable on unknown feasibility, "
                                     f"with no variant")
            self.assertEqual(claims_a_gap(variant), [],
                             f"{play_id}'s variant trips the validator")

    def test_a_play_with_no_variant_falls_back_to_its_normal_text(self):
        """Finding 9: the fallback branch was asserted but never exercised."""
        routing = play_routing.load_play_routing()
        stripped = json.loads(json.dumps(
            {k: v for k, v in routing.items() if k != "rules"}))
        for play in stripped["plays"].values():
            play.pop("strategy_text_unknown_feasibility", None)
        stripped["rules"] = routing["rules"]
        with unittest.mock.patch.object(
                play_routing, "load_play_routing", return_value=stripped):
            result = play_routing.compute_recommended_play(
                self._SIGNALS, None, "k", ["therapy"])
        self.assertFalse(result["data_available"]["feasibility"])
        self.assertEqual(
            result["strategy_text"],
            routing["plays"][result["play"]]["strategy_text"])


class TestTheValidatorCatchesTheClaimComingBack(unittest.TestCase):
    """D4.3 — the LLM narrates the play in its own words."""

    _DATA = {
        "root_keywords": ["k1"],
        "keyword_profiles": {"k1": {
            "serp_intent": {"primary_intent": "informational",
                            "confidence": "low", "is_mixed": False},
            "recommended_play": {
                "play": "extraction_play",
                "label": "Extraction play (GEO)",
                "data_available": {"feasibility": False}},
        }},
    }

    def _report(self, sentence):
        return ("## k1\n**k1 (100 total results)**\n"
                "Recommended play: Extraction play (GEO). " + sentence + "\n")

    def test_a_da_direction_with_no_da_measured_is_a_hard_failure(self):
        issues = bv.validate_llm_report(
            self._report("Ranking is unlikely for this term."), self._DATA)
        self.assertTrue(any("data_available.feasibility is false" in i
                            for i in issues), issues)
        self.assertTrue(bv.has_hard_validation_failures(issues))

    def test_the_same_claim_is_allowed_when_da_was_measured(self):
        data = json.loads(json.dumps(self._DATA))
        data["keyword_profiles"]["k1"]["recommended_play"][
            "data_available"]["feasibility"] = True
        issues = bv.validate_llm_report(
            self._report("Ranking is unlikely for this term."), data)
        self.assertFalse(any("data_available.feasibility is false" in i
                             for i in issues), issues)


class TestTheEvidenceBlockReadsTheProducersKeys(unittest.TestCase):
    """D4.4 — the block never rendered on real data."""

    @staticmethod
    def _data():
        return {
            "overview": [],
            "organic_results": [
                {"Root_Keyword": "family therapy", "Query_Label": "A",
                 "Rank": 1, "Title": "Registered clinical counsellor in Vancouver",
                 "Link": "https://www.psychologytoday.com/ca/x",
                 "Source": "Psychology Today"},
                {"Root_Keyword": "family therapy", "Query_Label": "A",
                 "Rank": 2, "Title": "A page with no trigger word",
                 "Link": "https://example.org/y", "Source": "Example"},
            ],
            "keyword_profiles": {"family therapy": {
                "serp_intent": {"primary_intent": "informational",
                                "confidence": "high", "is_mixed": False}}},
            "strategic_recommendations": [{
                "Pattern_Name": "The Medical Model Trap",
                "Status_Quo_Message": "sq", "Bowen_Bridge_Reframe": "br",
                "Content_Angle": "ca",
                "Detected_Triggers": "clinical, registered",
            }],
            "paa_questions": [],
            "keyword_feasibility": [],
        }

    def test_a_trigger_in_a_Title_renders_the_evidence_block(self):
        report = gir.generate_report(self._data())
        self.assertIn("Why this pattern fired:", report)
        self.assertIn("Registered clinical counsellor in Vancouver", report)
        # The domain comes from Link, normalised — not the literal row key.
        self.assertIn("psychologytoday.com", report)

    def test_the_producers_no_link_sentinel_is_not_a_domain(self):
        """Finding 1: serp_audit writes `"Link": ... or "N/A"`.

        `normalize_domain("N/A")` returned "n", which is truthy, so the
        `Source` fallback was dead code for exactly the rows it was for.
        """
        data = self._data()
        data["organic_results"][0]["Link"] = "N/A"
        report = gir.generate_report(data)
        self.assertIn("`Psychology Today`", report)
        self.assertNotIn("— `n`", report)

    def test_a_trigger_in_a_snippet_is_quoted_and_marked(self):
        """Finding 2: the selector scores Title + Snippet; so does this."""
        data = self._data()
        data["organic_results"][0]["Title"] = "A neutral title"
        data["organic_results"][0]["Snippet"] = (
            "Our registered clinical team can help.")
        report = gir.generate_report(data)
        self.assertIn("Why this pattern fired:", report)
        self.assertIn("(snippet)", report)
        self.assertIn("Our registered clinical team can help.", report)

    def test_no_trigger_anywhere_renders_no_block(self):
        data = self._data()
        for row in data["organic_results"]:
            row["Title"] = "nothing to see"
        report = gir.generate_report(data)
        self.assertNotIn("Why this pattern fired:", report)


class TestVolatilityReturnsTheKeysTheReportPrints(unittest.TestCase):
    """D4.5 — section 6 printed 'unknown' for keys never returned."""

    def test_the_metric_returns_both_keyword_lists(self):
        import metrics
        from storage import SerpStorage

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = SerpStorage(db_path=db_path)
            for run_id, date in (("run_prev", "2026-02-01T00:00:00"),
                                 ("run_curr", "2026-02-02T00:00:00")):
                store.save_run(run_id, "x")
                with sqlite3.connect(db_path) as conn:
                    conn.execute("UPDATE runs SET run_date = ? WHERE run_id = ?",
                                 (date, run_id))
                store.mark_run_completed(run_id, completed_at=date)
            store.save_serp_result("run_prev", "kw_old", "organic", 1, "",
                                   "https://example.com/a", "example.com", "",
                                   query_label="A")
            store.save_serp_result("run_curr", "kw_new", "organic", 1, "",
                                   "https://example.com/a", "example.com", "",
                                   query_label="A")
            with unittest.mock.patch.object(db_connect, "DATABASE_PATH", db_path):
                result = metrics.get_volatility_metrics("run_curr")

        self.assertTrue(result["comparability_warning"])
        self.assertEqual(result["keywords_current"], ["kw_new"])
        self.assertEqual(result["keywords_previous"], ["kw_old"])
        # And the report renders those lists, not "unknown".
        rendered = gir._render_volatility_keyword_sets(result)
        self.assertIn("kw_new", rendered)
        self.assertIn("kw_old", rendered)
        self.assertNotIn("unknown", rendered)

    def test_the_report_renders_a_list_not_a_python_repr(self):
        lines = gir._render_volatility_keyword_sets(
            {"keywords_current": ["b", "a"], "keywords_previous": ["a"]})
        self.assertIn("- **This run:** b, a", lines)
        self.assertIn("- **Previous run:** a", lines)

if __name__ == "__main__":
    unittest.main()
