"""Review chunk D3a — an engine that was not asked has no score.

Two findings:

- D-C-05 / D-M-03: an engine that answered nothing got mentions/ranking/
  citations axes of 0.0, so AIVI 0.0 was computed, persisted as a trend point,
  averaged into the all-engine mean, counted as "not mentioned" by the
  cross-engine transfer, and ranked FIRST in the prioritisation as the biggest
  opportunity. Two engines that cited nothing scored Jaccard 1.0 — rendered as
  perfect citation overlap.
- D-C-11: a probe call that raised was dropped (the question left the
  denominator); a call that returned no text and no sources was recorded as
  `mentioned=False` — a failure stored as a measured absence.

(D3.1-D3.7)
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_visibility_messages as av_messages
import aivi as aivi_mod
import engine_recommendations as er
import engine_transfer as et
import probe_ai_visibility as pav

_TS = "2026-11-17T00:00:00+00:00"
_REFERENCE_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures", "market_analysis_reference_run.json")
_CONFIG = {
    "analysis_report": {"client_domain": "livingsystems.ca",
                        "client_name": "Living Systems",
                        "client_name_patterns": ["Living Systems"]},
    "known_brands": [], "aivi": {}, "sentiment": {"enabled": False},
}


def _answered(engine, question="q", mentioned=True, cited=True):
    return {"run_ts": _TS, "engine": engine, "model": "m", "question": question,
            "status": pav.STATUS_ANSWERED, "failure_reason": None,
            "mentioned": mentioned, "cited": cited, "competitors_cited": [],
            "answer_excerpt": "", "persona": None, "source": "paa",
            "answer_text": "Living Systems Counselling is one option.",
            "source_urls": ["https://livingsystems.ca/x"] if cited else []}


def _failed(engine, question="q", reason="429 rate limited"):
    return {"run_ts": _TS, "engine": engine, "model": "", "question": question,
            "status": pav.STATUS_FAILED, "failure_reason": reason,
            "mentioned": None, "cited": None, "competitors_cited": [],
            "answer_excerpt": "", "persona": None, "source": "paa",
            "answer_text": "", "source_urls": []}


class TestAFailedCallIsNotAnAbsence(unittest.TestCase):
    """D3.5/D3.6 — the two ways a call produces no answer."""

    class _Raises:
        def ask(self, question):
            raise RuntimeError("429 rate limited")

    class _Empty:
        def ask(self, question):
            return {"answer_text": "  ", "source_urls": [], "model_id": "m"}

    class _Answers:
        def ask(self, question):
            return {"answer_text": "Living Systems Counselling.",
                    "source_urls": [], "model_id": "m"}

    def _run(self, probe):
        return pav.run_engine_probes(
            {"e": probe}, [{"query": "q", "source": "paa", "persona": None}],
            "", ["Living Systems"], "livingsystems.ca", [], _TS)

    def test_a_raised_call_is_recorded_not_dropped(self):
        rows = self._run(self._Raises())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], pav.STATUS_FAILED)
        self.assertIn("429", rows[0]["failure_reason"])

    def test_an_empty_answer_is_a_failure_not_a_non_mention(self):
        rows = self._run(self._Empty())
        self.assertEqual(rows[0]["status"], pav.STATUS_FAILED)
        self.assertIsNone(rows[0]["mentioned"])
        self.assertIsNone(rows[0]["cited"])

    def test_a_failed_row_carries_no_verdict(self):
        for probe in (self._Raises(), self._Empty()):
            with self.subTest(probe=type(probe).__name__):
                rows = self._run(probe)
                self.assertEqual(pav.answered_rows(rows), [])

    def test_a_real_answer_still_gets_its_verdict(self):
        rows = self._run(self._Answers())
        self.assertEqual(rows[0]["status"], pav.STATUS_ANSWERED)
        self.assertTrue(rows[0]["mentioned"])
        self.assertEqual(pav.answered_rows(rows), rows)

    def test_a_row_with_no_status_reads_as_answered(self):
        """Rows written before this chunk were only ever successes."""
        legacy = {"engine": "e", "mentioned": True, "cited": False}
        self.assertEqual(pav.answered_rows([legacy]), [legacy])


class TestTheFailureCountReachesAReader(unittest.TestCase):
    """D3.7 — "answered N of M (K failed)", and the rates over the answers."""

    def test_counts_are_planned_answered_failed(self):
        rows = [_answered("e", "q1"), _failed("e", "q2")]
        counts = pav.engine_call_counts(rows, ["e"], 3)
        self.assertEqual(counts["e"], {"planned": 3, "attempted": 2,
                                       "answered": 1, "failed": 1})

    def test_the_report_states_the_failures(self):
        rows = [_answered("e", "q1", mentioned=True),
                _failed("e", "q2"), _failed("e", "q3")]
        report = pav.generate_report("a.json", _TS, ["e"], rows, {}, [],
                                     "in North Vancouver", "Living Systems")
        self.assertIn("1 of 3 (2 failed)", report)
        # The mention rate is over the one answer, not over the three calls.
        self.assertIn("1/1 (100%)", report)

    def test_an_engine_with_only_failures_reads_not_measured(self):
        rows = [_failed("e", "q1")]
        report = pav.generate_report("a.json", _TS, ["e"], rows, {}, [],
                                     "", "Living Systems")
        self.assertIn("not measured", report)
        self.assertNotIn("0/1 (0%)", report)

    def test_a_failed_call_persists_a_null_verdict(self):
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        self.addCleanup(os.unlink, db)
        pav.save_probe_rows(db, [_answered("e", "q1"), _failed("e", "q2")])
        with sqlite3.connect(db) as conn:
            stored = conn.execute(
                f"SELECT question, status, mentioned, cited FROM {pav.PROBE_TABLE} "
                "ORDER BY question").fetchall()
        self.assertEqual(stored, [("q1", pav.STATUS_ANSWERED, 1, 1),
                                  ("q2", pav.STATUS_FAILED, None, None)])

    def test_the_trend_rate_is_over_the_answers(self):
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        self.addCleanup(os.unlink, db)
        pav.save_probe_rows(db, [_answered("e", "q1", mentioned=True),
                                 _failed("e", "q2"), _failed("e", "q3")])
        trend = pav.get_engine_trend(db, "e")
        self.assertEqual(trend[0]["attempted"], 3)
        self.assertEqual(trend[0]["questions"], 1)
        self.assertEqual(trend[0]["failed"], 2)
        self.assertEqual(trend[0]["mention_rate"], 1.0)

    def test_a_run_where_everything_failed_stays_in_the_trend(self):
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        self.addCleanup(os.unlink, db)
        pav.save_probe_rows(db, [_failed("e", "q1"), _failed("e", "q2")])
        trend = pav.get_engine_trend(db, "e")
        self.assertEqual(len(trend), 1)
        self.assertEqual(trend[0]["questions"], 0)
        self.assertIsNone(trend[0]["mention_rate"])


class TestAnUnmeasuredEngineHasNoScore(unittest.TestCase):
    """D3.1/D3.2 — no row, no place in the average, named instead."""

    def _enrich(self, rows, engines, skipped=None, planned=1):
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        self.addCleanup(os.unlink, db)
        result = pav.run_report_enrichment(
            rows, engines, _CONFIG, {"organic_results": []}, _TS, "topic", db,
            None, out_dir=tempfile.mkdtemp(), skipped=skipped,
            questions_planned=planned)
        return result, db

    def test_no_aivi_row_for_an_engine_with_no_answers(self):
        result, db = self._enrich([_answered("gemini")], ["gemini", "openai"])
        self.assertNotIn("openai", result["aivi"]["per_engine"])
        with sqlite3.connect(db) as conn:
            engines = [r[0] for r in conn.execute(
                "SELECT engine FROM ai_visibility_index").fetchall()]
        self.assertEqual(engines, ["gemini"])

    def test_an_engine_whose_calls_all_failed_is_not_measured(self):
        result, _ = self._enrich(
            [_answered("gemini"), _failed("openai")], ["gemini", "openai"])
        self.assertNotIn("openai", result["aivi"]["per_engine"])
        reason = result["aivi"]["engines_unmeasured"][0]["reason"]
        self.assertIn("0 of 1", reason)
        self.assertIn("1 failed", reason)

    def test_the_average_states_its_own_n(self):
        result, _ = self._enrich([_answered("gemini")], ["gemini", "openai"])
        self.assertEqual(result["aivi"]["all_engine_avg"], 100.0)
        self.assertEqual(result["aivi"]["all_engine_avg_n"], 1)

    def test_a_skipped_engine_carries_its_reason(self):
        result, _ = self._enrich(
            [_answered("gemini")], ["gemini", "openai"],
            skipped=[{"engine": "openai", "reason": "OPENAI_API_KEY not set"}])
        unmeasured = result["aivi"]["engines_unmeasured"]
        self.assertEqual([e["engine"] for e in unmeasured], ["openai"])
        self.assertIn("OPENAI_API_KEY", unmeasured[0]["reason"])

    def test_one_measured_engine_is_not_a_transfer_verdict(self):
        result, _ = self._enrich([_answered("gemini")], ["gemini", "openai"])
        self.assertFalse(result["transfer"].get("measurable"))

    def test_the_trend_keeps_an_engine_measured_only_before(self):
        result, _ = self._enrich([_answered("gemini")], ["gemini", "openai"])
        self.assertIn("openai", result["aivi"]["trends"])


class TestTheOverlapOfTwoSilencesIsNotAgreement(unittest.TestCase):
    """D3.3 — Jaccard of two empty sets."""

    def test_two_empty_sets_are_not_comparable(self):
        self.assertIsNone(et.jaccard(set(), set()))

    def test_real_sets_are_unchanged(self):
        self.assertEqual(et.jaccard({"a"}, {"a"}), 1.0)
        self.assertEqual(et.jaccard({"a"}, {"b"}), 0.0)

    def _transfer(self, tables):
        engines = sorted(tables)
        return et.compute_transfer(
            engines, {e: True for e in engines}, {e: True for e in engines},
            tables, {e: 1 for e in engines})

    def test_no_citations_anywhere_is_not_measurable(self):
        result = self._transfer({"a": [], "b": []})
        overlap = result["overlap"]
        self.assertIsNone(overlap["avg_jaccard"])
        self.assertEqual(overlap["pairs_compared"], 0)
        self.assertEqual(overlap["pairs_not_comparable"], ["a|b"])
        self.assertIn("not measurable", result["interpretation"])

    def test_one_side_citing_nothing_is_still_a_real_zero(self):
        """Only a pair where NEITHER side cited anything is incomparable.

        "a cites x.ca, c cites nothing" is a genuine overlap of zero — the
        two engines really do share no source. That distinction is the whole
        point: 0.0 means measured disagreement, None means nothing to measure.
        """
        result = self._transfer({
            "a": [{"domain": "x.ca"}], "b": [{"domain": "x.ca"}], "c": []})
        overlap = result["overlap"]
        self.assertEqual(overlap["pairs_compared"], 3)
        self.assertEqual(overlap["pairs_not_comparable"], [])
        self.assertEqual(overlap["pairwise_jaccard"]["a|b"], 1.0)
        self.assertEqual(overlap["pairwise_jaccard"]["a|c"], 0.0)
        self.assertEqual(overlap["avg_jaccard"], round(1 / 3, 4))

    def test_the_rendered_section_says_so(self):
        result = self._transfer({"a": [], "b": []})
        rendered = "\n".join(et.render_transfer_section(result))
        self.assertIn("not measurable", rendered)
        self.assertNotIn("1.00", rendered)


class TestAnUnmeasuredEngineIsNotAnOpportunity(unittest.TestCase):
    """D3.4 — the prioritisation."""

    def setUp(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profiles = er.load_engine_profiles(
            os.path.join(repo, "engine_profiles.yml"))

    def test_an_engine_with_no_aivi_is_not_ranked(self):
        ranked = er.prioritize_engines(
            ["openai", "gemini"], self.profiles, {"gemini": 40.0})
        self.assertEqual([r["engine"] for r in ranked], ["gemini"])

    def test_it_is_reported_as_not_measured_instead(self):
        not_measured = er.unmeasured_engines(
            ["openai", "gemini"], self.profiles, {"gemini": 40.0})
        self.assertEqual([r["engine"] for r in not_measured], ["openai"])
        self.assertIn("not measured", not_measured[0]["reason"])

    def test_an_engine_with_no_profile_is_reported_too(self):
        not_measured = er.unmeasured_engines(
            ["nosuchengine"], self.profiles, {"nosuchengine": 10.0})
        self.assertEqual([r["engine"] for r in not_measured], ["nosuchengine"])
        self.assertIn("profile", not_measured[0]["reason"])

    def test_the_rendered_section_names_them(self):
        recs = er.engine_recommendations(["gemini"], self.profiles,
                                         {"gemini": {"aivi": 40.0}})
        ranked = er.prioritize_engines(["gemini"], self.profiles,
                                       {"gemini": 40.0})
        not_measured = er.unmeasured_engines(
            ["openai", "gemini"], self.profiles, {"gemini": 40.0})
        rendered = "\n".join(er.render_engine_recommendations_section(
            recs, ranked, not_measured))
        self.assertIn("Not ranked — not measured", rendered)
        self.assertIn("not a high-opportunity engine", rendered)


class TestTheRenderedReportSaysWhatWasNotMeasured(unittest.TestCase):
    """Cold-review F1-F6 — the data layer was honest, the render layer was not.

    One guard per finding: the fixes were all the same class the chunk set out
    to close (a negative stated about something that was never measured),
    surviving in the artifact the user reads.
    """

    def test_f1_the_all_engine_mean_carries_its_denominator(self):
        """A mean over 1 of 2 engines must not read as a mean over 2."""
        per_engine = {"ok": {"aivi": 62.5, "axes": {"mentions": 100.0}}}
        rendered = "\n".join(aivi_mod.render_aivi_section(
            per_engine, 62.5, {}, engines_measured=1, engines_enabled=2,
            engines_unmeasured=[{"engine": "dead",
                                 "reason": "0 of 5 calls returned an answer (5 failed)"}]))
        self.assertIn("1 of 2 enabled engine", rendered)
        self.assertIn("dead", rendered)
        self.assertIn("is not a zero", rendered)

    def test_f2_an_unmeasured_engine_is_not_a_finding_of_silence(self):
        """"No brands were named" is false when there were no answers."""
        enrichment = {
            "aivi": {"per_engine": {"ok": {"aivi": 50.0, "axes": {}}},
                     "all_engine_avg": 50.0, "all_engine_avg_n": 1,
                     "engines_measured": ["ok"],
                     "engines_unmeasured": [{"engine": "dead",
                                             "reason": "0 of 5 calls returned an answer (5 failed)"}],
                     "trends": {}},
            "leaderboards": {}, "citations": {}, "sentiment": {},
            "engine_strategy": {}, "transfer": {},
        }
        rendered = "\n".join(pav._enrichment_sections(["ok", "dead"], enrichment))
        dead_blocks = [b for b in rendered.split("### ") if b.startswith("dead")]
        ok_blocks = [b for b in rendered.split("### ") if b.startswith("ok")]
        self.assertEqual(len(dead_blocks), 2)  # leaderboard + citations
        self.assertIn("no brand could be named in them", dead_blocks[0])
        self.assertIn("no source could be cited in them", dead_blocks[1])
        for block in dead_blocks:
            self.assertNotIn("No brands were named in this engine", block)
            self.assertNotIn("No sources were returned in this engine", block)
        # A MEASURED engine with no brands is a real finding and keeps saying so.
        self.assertIn("No brands were named in this engine", ok_blocks[0])

    def test_f3_a_rate_limited_run_is_not_a_configuration_state(self):
        """Three engines rate-limited must not read "enable more engines"."""
        unmeasured = [{"engine": e, "reason": "0 of 5 calls returned an answer (5 failed)"}
                      for e in ("openai", "perplexity", "claude")]
        result = et.compute_transfer(
            ["gemini"], {}, {}, {}, {},
            engines_enabled=["gemini", "openai", "perplexity", "claude"],
            engines_unmeasured=unmeasured)
        rendered = "\n".join(et.render_transfer_section(result))
        self.assertFalse(result["measurable"])
        self.assertIn("1 of 4 enabled engines", result["reason"])
        self.assertIn("re-run", rendered.lower())
        self.assertNotIn("Enable at least two engines", rendered)
        # One engine actually enabled is still a configuration state.
        single = et.compute_transfer(["gemini"], {}, {}, {}, {})
        self.assertIn("Enable at least two engines",
                      "\n".join(et.render_transfer_section(single)))

    def test_f4_the_not_measured_wording_lives_in_one_config_file(self):
        """Changing the config word changes every renderer that states it."""
        self.assertEqual(av_messages.status_text("not_measured", "cell"),
                         "not measured")
        original = av_messages._CACHE
        try:
            av_messages._CACHE = {
                "statuses": {"not_measured": {"cell": "NO DATA"}},
                "lines": {"reason_no_questions": "nothing was asked"},
            }
            rendered = pav.generate_report(
                _REFERENCE_JSON, _TS, ["dead"], [], {"dead": []}, [],
                "", "Living Systems")
            self.assertIn("NO DATA", rendered)
            self.assertIn("nothing was asked", rendered)
        finally:
            av_messages._CACHE = original

    def test_f5_an_unknown_plan_is_not_a_guessed_denominator(self):
        """`planned` is None when nobody said how many were planned."""
        rows = [{"engine": e, "status": pav.STATUS_ANSWERED}
                for e in ("a", "a", "b", "b", "b")]
        counts = pav.engine_call_counts(rows, ["a", "b"])
        self.assertIsNone(counts["a"]["planned"])
        self.assertEqual(counts["a"]["attempted"], 2)
        self.assertEqual(pav.engine_call_counts(rows, ["a"], 7)["a"]["planned"], 7)

    def test_f6_the_trend_numerator_is_over_the_answered_rows(self):
        """A NULL verdict on an answered row is not a measured False."""
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        pav.save_probe_rows(db, [
            {"run_ts": _TS, "engine": "e", "model": "m", "question": "q1",
             "status": pav.STATUS_ANSWERED, "failure_reason": None,
             "mentioned": True, "cited": None, "competitors_cited": [],
             "answer_excerpt": "", "persona": None, "source": "paa"},
            {"run_ts": _TS, "engine": "e", "model": "m", "question": "q2",
             "status": pav.STATUS_FAILED, "failure_reason": "429",
             "mentioned": None, "cited": None, "competitors_cited": [],
             "answer_excerpt": "", "persona": None, "source": "paa"},
        ])
        trend = pav.get_engine_trend(db, "e")[-1]
        self.assertEqual((trend["attempted"], trend["questions"], trend["failed"]),
                         (2, 1, 1))
        self.assertEqual(trend["mention_rate"], 1.0)
        self.assertEqual(trend["citation_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
