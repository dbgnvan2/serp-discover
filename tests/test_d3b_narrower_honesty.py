"""Review chunk D3b — four narrower cases of the same fault.

- D-M-18: `generate` emits every question of persona 1 first, so both caps
  (`max_questions` and the `max_total_calls` truncation) took a prefix. A
  27-question plan over three personas asked 20 questions that were all the
  first persona's, and the other two showed "no data" — a cap reading as a
  finding about those personas.
- D-M-14: the gazetteer harvested bare generic words ("Indeed") that matched
  ordinary answer text; equal mention counts were ranked by alphabetical
  order, so a tie read as a loss; and a bare substring test counted "living
  systems theory" as a mention of Living Systems Counselling.
- D-M-04: the structure sub-score read the whole top-10's markup, so a client
  with no page in any top-10 scored 66.67 on its competitors' schema.
- D-M-25: a failed or unparseable sentiment classification was stored as
  "neutral", so three rate-limited calls became a measured 0.0 axis.

(D3.8-D3.14)
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_sentiment as asent
import brand_mentions as bm
import brief_data_extraction as bde
import foundational_score as fs
import probe_ai_visibility as pav
from profile_questions import interleave_by_persona

_TS = "2026-11-17T00:00:00+00:00"


class TestEveryPersonaThatAskedIsAsked(unittest.TestCase):
    """D3.8/D3.9 — a cap must cost every persona, not the last personas all."""

    def _profile_rows(self):
        return ([{"question": f"client q{i}", "persona": "prospective_client"}
                 for i in range(1, 21)]
                + [{"question": f"trainee q{i}", "persona": "clinician_trainee"}
                   for i in range(1, 4)]
                + [{"question": f"referrer q{i}", "persona": "referrer"}
                   for i in range(1, 3)])

    def test_the_cap_takes_a_persona_fair_slice(self):
        built = pav.build_question_set(
            {}, [], "", max_questions=6, min_words=3,
            profile_questions=self._profile_rows())
        personas = [q["persona"] for q in built]
        self.assertEqual(len(built), 6)
        self.assertEqual(set(personas),
                         {"prospective_client", "clinician_trainee", "referrer"})
        # The first three are one of each, not three of the first persona.
        self.assertEqual(len(set(personas[:3])), 3)

    def test_interleave_is_deterministic_and_loses_nothing(self):
        rows = self._profile_rows()
        once = interleave_by_persona(rows)
        self.assertEqual(once, interleave_by_persona(rows))
        self.assertEqual(len(once), len(rows))
        self.assertEqual({q["question"] for q in once},
                         {q["question"] for q in rows})

    def test_rows_without_a_persona_keep_their_order(self):
        rows = [{"question": "a"}, {"question": "b"}, {"question": "c"}]
        self.assertEqual([q["question"] for q in interleave_by_persona(rows)],
                         ["a", "b", "c"])


class TestAGenericWordIsNotABrand(unittest.TestCase):
    """D3.10 — a harvested source needs two words, or its own domain."""

    _DATA = {"organic_results": [
        {"Source": "Indeed", "Link": "https://vch.ca/jobs"},
        {"Source": "Pathways", "Link": "https://vch.ca/p"},
        {"Source": "Psychology Today", "Link": "https://psychologytoday.com/a"},
        {"Source": "ZipRecruiter", "Link": "https://ziprecruiter.com/j"},
    ]}

    def test_a_bare_generic_token_is_dropped(self):
        gaz = bm.build_gazetteer([], self._DATA)
        self.assertNotIn("Indeed", gaz)
        self.assertNotIn("Pathways", gaz)
        self.assertIn("Psychology Today", gaz)
        # A single token that IS its own domain is a brand.
        self.assertIn("ZipRecruiter", gaz)

    def test_the_stoplist_is_editorial_and_drops_outright(self):
        gaz = bm.build_gazetteer(
            [], self._DATA, generic_source_stoplist=["ziprecruiter"])
        self.assertNotIn("ZipRecruiter", gaz)

    def test_known_brands_are_never_filtered(self):
        """The user listed it, so it is a brand — even one generic word."""
        gaz = bm.build_gazetteer(["Pathways"], self._DATA)
        self.assertIn("Pathways", gaz)


class TestATieIsNotAWin(unittest.TestCase):
    """D3.11 — equal mention counts share a rank."""

    def test_equal_counts_share_a_rank_and_carry_the_tie(self):
        answers = [{"engine": "g", "answer_text": "Alpha and Bravo and Client Co."},
                   {"engine": "g", "answer_text": "Alpha again."}]
        lb = bm.build_leaderboard(answers, ["Alpha", "Bravo", "Client Co"],
                                  ["client co"], False, "m")
        by_brand = {r["brand"]: r for r in lb["rows"]}
        self.assertEqual(by_brand["Alpha"]["rank"], 1)
        self.assertEqual(by_brand["Bravo"]["rank"], 2)
        self.assertEqual(by_brand["Client Co"]["rank"], 2)
        self.assertEqual(by_brand["Bravo"]["tied_with"], 1)
        self.assertEqual(lb["client_rank"], 2)
        self.assertEqual(lb["client_tied_with"], 1)

    def test_competition_ranking_skips_the_shared_positions(self):
        """1, 2, 2, 4 — not 1, 2, 2, 3. A brand counts once per answer."""
        answers = [
            {"engine": "g", "answer_text": "Alpha, Bravo, Charlie and Delta."},
            {"engine": "g", "answer_text": "Alpha, Bravo and Charlie."},
            {"engine": "g", "answer_text": "Alpha only."},
        ]
        lb = bm.build_leaderboard(
            answers, ["Alpha", "Bravo", "Charlie", "Delta"], [], False, "m")
        by_brand = {r["brand"]: (r["mention_count"], r["rank"])
                    for r in lb["rows"]}
        self.assertEqual(by_brand["Alpha"], (3, 1))
        self.assertEqual(by_brand["Bravo"], (2, 2))
        self.assertEqual(by_brand["Charlie"], (2, 2))
        self.assertEqual(by_brand["Delta"], (1, 4))

    def test_the_report_states_the_tie(self):
        lb = bm.build_leaderboard(
            [{"engine": "g", "answer_text": "Alpha and Client Co."}],
            ["Alpha", "Client Co"], ["client co"], False, "m")
        rendered = "\n".join(bm.render_leaderboard_section("g", lb))
        self.assertIn("tied with 1 other brand(s)", rendered)
        self.assertIn("not ahead of them", rendered)


class TestTheClientsOwnNameOnAWordBoundary(unittest.TestCase):
    """D3.12 — mirrors `gsc_demand.is_branded`."""

    _PATTERNS = ["Living Systems", "Bowen"]
    _NEGATIVES = ["living systems theory"]

    def _mentioned(self, text):
        return pav.detect_visibility(
            text, [], self._PATTERNS, "livingsystems.ca", [],
            negative_terms=self._NEGATIVES)["mentioned"]

    def test_a_negative_term_is_not_a_mention(self):
        self.assertFalse(self._mentioned(
            "Living systems theory holds that families are systems."))

    def test_a_real_mention_still_counts(self):
        self.assertTrue(self._mentioned("Living Systems Counselling can help."))

    def test_a_pattern_inside_a_longer_word_is_not_a_mention(self):
        self.assertFalse(self._mentioned("Bowenville is a town in Queensland."))
        self.assertTrue(self._mentioned("Bowen family systems therapy."))

    def test_no_negative_terms_configured_changes_nothing_else(self):
        self.assertTrue(pav.detect_visibility(
            "Living Systems Counselling can help.", [], self._PATTERNS,
            "livingsystems.ca", [])["mentioned"])


class TestTheStructureScoreIsTheClientsOwn(unittest.TestCase):
    """D3.13 — the client's markup, or no score at all."""

    _RECS = [{"label": "FAQ markup", "schema_types": ["FAQPage"]},
             {"label": "Service markup", "schema_types": ["Service"]},
             {"label": "Local markup", "schema_types": ["LocalBusiness"]}]

    def _analysis(self, client_page):
        return {"keyword_profiles": {"kw": {"schema_signals": {
            "data_available": True,
            "schema_type_counts": {"FAQPage": 2, "LocalBusiness": 1, "Service": 1},
            "client_page": client_page,
        }}}}

    def test_no_client_page_is_not_measured(self):
        score, gaps, reason = fs.compute_structure(
            self._analysis(None), self._RECS)
        self.assertIsNone(score)
        # Cold-review finding 6: the n/a says WHICH unmeasured state this is,
        # and the schema recommendations still stand — they are advice, not a
        # measurement, and the client with no page in any top-10 is the one
        # that needs them.
        self.assertIn("no enriched page", reason)
        self.assertTrue(gaps)
        self.assertTrue(any("FAQPage" in g for g in gaps))

    def test_no_recommendations_is_a_different_reason(self):
        score, gaps, reason = fs.compute_structure(self._analysis(None), [])
        self.assertIsNone(score)
        self.assertEqual(gaps, [])
        self.assertIn("schema_recommendations", reason)
        self.assertNotIn("no enriched page", reason)

    def test_the_score_counts_only_the_clients_types(self):
        score, gaps, _reason = fs.compute_structure(
            self._analysis({"schema_types": ["FAQPage"]}), self._RECS)
        self.assertEqual(score, 33.33)
        self.assertTrue(any("Service" in g for g in gaps))
        self.assertFalse(any("FAQ markup" in g for g in gaps))

    def test_the_competitors_markup_does_not_lift_the_score(self):
        """The aggregate holds all three types; the client holds one."""
        with_client = fs.compute_structure(
            self._analysis({"schema_types": ["FAQPage"]}), self._RECS)[0]
        self.assertLess(with_client, 100.0)

    def test_the_schema_signals_carry_the_clients_row(self):
        rows = [{"rank": 1, "domain": "psychologytoday.com",
                 "source": "Psychology Today", "schema_types": ["FAQPage"]},
                {"rank": 4, "domain": "livingsystems.ca",
                 "source": "Living Systems", "schema_types": ["LocalBusiness"],
                 "faq_present": True}]
        signals = bde._build_schema_signals(rows, "livingsystems.ca")
        self.assertIsNotNone(signals["client_page"])
        self.assertEqual(signals["client_page"]["rank"], 4)
        self.assertEqual(signals["client_page"]["schema_types"], ["LocalBusiness"])
        # No client row at all -> None, not the first competitor's.
        self.assertIsNone(
            bde._build_schema_signals(rows[:1], "livingsystems.ca")["client_page"])


class TestAFailedClassificationIsNotNeutral(unittest.TestCase):
    """D3.14 — a call that never answered carries no opinion."""

    def test_a_raised_call_has_no_polarity(self):
        def raises(*a, **k):
            raise RuntimeError("429 rate limited")
        result = asent.classify_answer("text", "Brand", "m", llm_runner=raises)
        self.assertIsNone(result["polarity"])
        self.assertEqual(result["status"], asent.STATUS_FAILED)
        self.assertIn("429", result["failure_reason"])

    def test_an_unparseable_response_has_no_polarity(self):
        for raw in ("", "I'm sorry, I can't help.", '{"polarity": "???"}',
                    '["not", "an", "object"]'):
            with self.subTest(raw=raw):
                result = asent._parse_classification(raw)
                self.assertIsNone(result["polarity"])
                self.assertEqual(result["status"], asent.STATUS_FAILED)

    def test_a_real_neutral_verdict_is_still_neutral(self):
        result = asent._parse_classification(
            '{"polarity":"neutral","positive_aspects":[],"negative_aspects":[]}')
        self.assertEqual(result["polarity"], "neutral")
        self.assertEqual(result["status"], asent.STATUS_CLASSIFIED)

    def test_all_failed_is_not_zero_percent(self):
        rows = [{"engine": "g", "brand": "B", "polarity": None,
                 "positive_aspects": [], "negative_aspects": [],
                 "status": asent.STATUS_FAILED, "failure_reason": "429"}] * 3
        self.assertIsNone(asent.percent_positive(rows, "B"))
        rendered = "\n".join(asent.render_sentiment_section(rows, True, "B", None))
        self.assertIn("all 3 classification(s) failed", rendered)
        self.assertIn("Not a neutral portrayal", rendered)

    def test_the_percentage_states_what_it_is_over(self):
        rows = [
            {"engine": "g", "brand": "B", "polarity": "positive",
             "positive_aspects": ["warm"], "negative_aspects": [],
             "status": asent.STATUS_CLASSIFIED, "failure_reason": None},
            {"engine": "g", "brand": "B", "polarity": None,
             "positive_aspects": [], "negative_aspects": [],
             "status": asent.STATUS_FAILED, "failure_reason": "429"},
        ]
        self.assertEqual(asent.percent_positive(rows, "B"), 100.0)
        rendered = "\n".join(asent.render_sentiment_section(rows, True, "B", None))
        self.assertIn("1 classified of 2 attempted", rendered)

    def test_a_failure_raises_no_negative_alert(self):
        rows = [{"engine": "g", "brand": "B", "polarity": None,
                 "positive_aspects": [], "negative_aspects": ["bad"],
                 "status": asent.STATUS_FAILED, "failure_reason": "429"}]
        self.assertEqual(asent.render_negative_sentiment_alert(rows, True, "B"), [])

    def test_the_status_persists_and_an_old_row_reads_as_classified(self):
        db = os.path.join(tempfile.mkdtemp(), "s.db")
        asent.save_sentiment(db, _TS, [
            {"engine": "g", "brand": "B", "polarity": "positive",
             "positive_aspects": [], "negative_aspects": [], "answer_excerpt": "",
             "status": asent.STATUS_CLASSIFIED, "failure_reason": None},
            {"engine": "g", "brand": "B", "polarity": None,
             "positive_aspects": [], "negative_aspects": [], "answer_excerpt": "",
             "status": asent.STATUS_FAILED, "failure_reason": "429"},
        ])
        with sqlite3.connect(db) as conn:
            stored = conn.execute(
                f"SELECT polarity, status, failure_reason FROM "
                f"{asent.SENTIMENT_TABLE} ORDER BY status").fetchall()
        self.assertEqual(stored, [("positive", "classified", None),
                                  (None, "failed", "429")])
        # A pre-D3b row carries no status and was only written on a parsed
        # response, so it reads as classified.
        self.assertEqual(len(asent.classified_rows(
            [{"brand": "B", "polarity": "neutral"}])), 1)


class TestTheColdReviewFindings(unittest.TestCase):
    """One guard per medium-or-higher finding of the D3b cold review.

    Every one of these is the same class the chunk set out to close: a fix
    applied to one matcher, one tie-break or one status and not to its
    siblings, so the bug stayed live on the axis next door.
    """

    # --- finding 1: a one-word brand on a subdomained host is still a brand
    def test_a_single_token_brand_survives_a_subdomain(self):
        data = {"organic_results": [
            {"Source": "Indeed", "Link": "https://ca.indeed.com/jobs"},
            {"Source": "Pathways", "Link": "https://www2.pathways.ca/x"},
            {"Source": "Pathways", "Link": "https://vch.ca/other"},
        ]}
        gaz = bm.build_gazetteer([], data)
        self.assertIn("Indeed", gaz)   # "indeed" is a label of ca.indeed.com
        self.assertIn("Pathways", gaz)  # "pathways" is a label of www2.pathways.ca
        # A public-suffix or hosting label is never the brand.
        self.assertEqual(bm._domain_labels("https://ca.indeed.com"), {"indeed"})
        self.assertEqual(
            bm.build_gazetteer([], {"organic_results": [
                {"Source": "Resources", "Link": "https://vch.ca/x"}]}),
            [])

    # --- finding 2: the negative terms reach every matcher, not just one
    def test_every_matcher_honours_the_negative_terms(self):
        text = "Living systems theory is a framework taught widely."
        neg = ["living systems theory"]
        patterns = ["Living Systems"]
        self.assertFalse(pav.detect_visibility(
            text, [], patterns, "livingsystems.ca", [],
            negative_terms=neg)["mentioned"])
        self.assertEqual(bm.gazetteer_pass(text, patterns, neg), [])
        self.assertFalse(asent.answer_mentions_brand(text, patterns, neg))
        # And the leaderboard built from it gives the client no rank.
        lb = bm.build_leaderboard(
            [{"engine": "g", "answer_text": text}], patterns, patterns,
            False, "", negative_terms=neg)
        self.assertEqual(lb["rows"], [])
        self.assertIsNone(lb["client_rank"])

    # --- finding 3: the export is measured values only
    def test_the_export_carries_no_unclassified_sentiment(self):
        import ai_visibility_export as ave
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            asent.save_sentiment(path, _TS, [
                {"engine": "g", "brand": "B", "polarity": "positive",
                 "positive_aspects": [], "negative_aspects": [],
                 "answer_excerpt": "", "status": asent.STATUS_CLASSIFIED,
                 "failure_reason": None},
                {"engine": "g", "brand": "B", "polarity": None,
                 "positive_aspects": [], "negative_aspects": [],
                 "answer_excerpt": "", "status": asent.STATUS_FAILED,
                 "failure_reason": "call raised"},
                {"engine": "g", "brand": "B", "polarity": None,
                 "positive_aspects": [], "negative_aspects": [],
                 "answer_excerpt": "", "status": asent.STATUS_SKIPPED_BUDGET,
                 "failure_reason": "budget spent"},
            ])
            with sqlite3.connect(path) as conn:
                rows = ave._read_answer_sentiment(conn, _TS)
            self.assertEqual(rows, [{"engine": "g", "brand": "B",
                                     "polarity": "positive"}])
        finally:
            os.unlink(path)

    # --- finding 4: an exhausted budget is not an absence of mentions
    def test_an_exhausted_budget_says_so(self):
        answers = [{"engine": "g", "answer_text": "Living Systems helps."}
                   for _ in range(3)]
        rows, calls = asent.collect_sentiment(
            answers, {"Living Systems": ["Living Systems"]}, "m",
            llm_runner=lambda *a, **k: "", call_budget=0)
        self.assertEqual(calls, 0)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["status"] == asent.STATUS_SKIPPED_BUDGET
                            for r in rows))
        text = "\n".join(asent.render_sentiment_section(
            rows, True, "Living Systems", None))
        self.assertIn("budget", text)
        self.assertNotIn("no answer this run portrayed this brand", text)

    # --- finding 5: the veto is per match, not per answer
    def test_one_paragraph_about_the_subject_does_not_erase_a_mention(self):
        text = ("Living systems theory, developed by Bowen, is a framework. "
                "Living Systems Counselling in North Vancouver offers therapy.")
        neg = ["living systems theory"]
        self.assertTrue(pav.detect_visibility(
            text, [], ["Living Systems Counselling"], "livingsystems.ca", [],
            negative_terms=neg)["mentioned"])
        self.assertEqual(
            bm.gazetteer_pass(text, ["Living Systems Counselling"], neg),
            ["Living Systems Counselling"])

    # --- finding 6: two unmeasured states are two facts, and a definition
    #     change is not a readiness delta
    def test_the_n_a_structure_cell_states_which_unmeasured_state_it_is(self):
        recs = [{"label": "FAQ", "schema_types": ["FAQPage"]}]
        data = {"keyword_profiles": {"k": {"schema_signals": {
            "data_available": True, "client_page": None}}}}
        result = fs.compute_foundational_score(data, recs, None)
        self.assertIsNone(result["subscores"]["structure"])
        self.assertIn("no enriched page", result["reasons"]["structure"])
        self.assertEqual(result["definition_version"], fs.DEFINITION_VERSION)
        text = "\n".join(fs.render_foundational_section(result))
        self.assertIn("no enriched page", text)
        # A score written under the old definition is not comparable.
        crossed = "\n".join(fs.render_foundational_section(result, [
            {"score": 10.0, "definition_version": 1},
            {"score": 40.0, "definition_version": 2}]))
        self.assertIn("not comparable", crossed)
        self.assertNotIn("+30.0", crossed)
        same = "\n".join(fs.render_foundational_section(result, [
            {"score": 10.0, "definition_version": 2},
            {"score": 40.0, "definition_version": 2}]))
        self.assertIn("+30.0", same)

    # --- finding 7: a shared rank is not an outright rank 1
    def test_a_tied_rank_one_is_not_a_perfect_ranking_axis(self):
        self.assertEqual(bm.client_ranking_axis(1, 6, 0), 100.0)
        self.assertLess(bm.client_ranking_axis(1, 6, 5), 100.0)
        self.assertEqual(bm.client_ranking_axis(None, 6, 0), 0.0)

    # --- finding 8: the alphabet does not pick the benchmark competitor
    def test_a_tie_for_top_competitor_is_stated(self):
        text = "\n".join(asent.render_sentiment_section(
            [], True, "Client", "Alpha",
            tied_top_competitors=["Alpha", "Zeta"]))
        self.assertIn("tie", text)
        self.assertIn("Zeta", text)


if __name__ == "__main__":
    unittest.main()
