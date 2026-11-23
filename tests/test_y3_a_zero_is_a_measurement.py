"""Chunk Y3 — a figure nobody measured must not print as a number, and a row
the run dropped must be counted where the reader can see it.

One guard per finding in
``docs/review_2026-11-04/PLAN_Y3_a_zero_is_a_measurement.md``.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk Y3
"""
import db_connect
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import brief_validation            # noqa: E402
import citation_table              # noqa: E402
import foundational_score as fs    # noqa: E402
import metrics                     # noqa: E402
import refresh_analysis_outputs as rao   # noqa: E402
from storage import SerpStorage    # noqa: E402


# ---------------------------------------------------------------------------
# 1. Every reason there is no volatility figure reaches the report
# ---------------------------------------------------------------------------

def _store(db_path):
    return SerpStorage(db_path=db_path)


def _run(store, run_id, run_date, completed=True):
    store.save_run(run_id, "x")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE runs SET run_date = ? WHERE run_id = ?",
                     (run_date, run_id))
    if completed:
        store.mark_run_completed(run_id, completed_at=run_date)


def _result(store, run_id, keyword, rank, url, label="A"):
    store.save_serp_result(run_id, keyword, "organic", rank, "", url,
                           "example.com", "", query_label=label)


class TestVolatilityAlwaysSaysWhy(unittest.TestCase):

    def test_no_database_is_a_status_not_a_none(self):
        with mock.patch.object(db_connect, "DATABASE_PATH", "/nonexistent/x.db"):
            out = metrics.get_volatility_metrics("run_1")
        self.assertEqual(out["status"], "no_database")
        self.assertTrue(out["msg"])

    def test_an_unknown_run_is_a_status_not_a_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            store = _store(db)
            _run(store, "a", "2026-02-01T00:00:00")
            _run(store, "b", "2026-02-02T00:00:00")
            with mock.patch.object(db_connect, "DATABASE_PATH", db):
                out = metrics.get_volatility_metrics("not_a_run")
        self.assertEqual(out["status"], "run_not_found")
        self.assertIn("not_a_run", out["msg"])

    def test_a_failed_query_is_a_status_not_a_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            _store(db)
            with mock.patch.object(db_connect, "DATABASE_PATH", db), \
                 mock.patch.object(metrics.pd, "read_sql",
                                   side_effect=RuntimeError("no such column")):
                out = metrics.get_volatility_metrics("run_1")
        self.assertEqual(out["status"], "query_failed")
        self.assertIn("no such column", out["msg"])

    def test_no_shared_url_is_not_a_volatility_of_nan(self):
        """`merged` empty → the mean is NaN. It used to come back as
        status "success" with that NaN, and section 6 printed its heading and
        nothing else."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            store = _store(db)
            _run(store, "prev", "2026-02-01T00:00:00")
            _run(store, "curr", "2026-02-02T00:00:00")
            _result(store, "prev", "kw", 1, "https://a.example/1")
            _result(store, "curr", "kw", 1, "https://b.example/2")
            with mock.patch.object(db_connect, "DATABASE_PATH", db):
                out = metrics.get_volatility_metrics("curr")
        self.assertEqual(out["status"], "no_shared_urls")
        self.assertNotIn("volatility_score", out)

    def test_the_report_prints_the_reason(self):
        """The section rendered only on success, so four reasons produced no
        section at all and the `msg` reached nothing."""
        import generate_insight_report as gir

        data = {"overview": [{"Run_ID": "curr", "Source_Keyword": "kw",
                              "Query_Label": "A", "Executed_Query": "kw"}],
                "keyword_profiles": {}}
        with mock.patch.object(
                gir.metrics, "get_volatility_metrics",
                return_value={"status": "no_shared_urls",
                              "msg": "no URL ranked for the same keyword in "
                                     "both runs"}):
            report = gir.generate_report(data)
        text = report if isinstance(report, str) else "\n".join(report)
        self.assertIn("6. Market Volatility", text)
        self.assertIn("no URL ranked for the same keyword", text)


# ---------------------------------------------------------------------------
# 2. A foundational readiness nobody measured is not 0.0
# ---------------------------------------------------------------------------

class TestFoundationalZeroIsAMeasurement(unittest.TestCase):

    EMPTY = {"keyword_profiles": {}, "strategic_flags": {"geo_alerts": []}}

    def test_no_subscore_means_no_composite(self):
        r = fs.compute_foundational_score(self.EMPTY, [{"context": "x"}], None)
        self.assertIsNone(r["score"])
        # The reason has to be the right one: "nothing was measured" and
        # "every weight is zero" are different facts, and the weights here
        # are the default equal thirds.
        self.assertIn("sub-score", r["score_reason"])
        self.assertNotIn("weight", r["score_reason"].lower())

    def test_zero_weights_are_a_configuration_error_not_a_zero(self):
        analysis = {"keyword_profiles": {"kw": {"extractability": {
            "data_available": True,
            "client_page": {"has_question_heading": True,
                            "intro_word_count": 120,
                            "has_faq_block": True}}}},
            "strategic_flags": {"geo_alerts": []}}
        r = fs.compute_foundational_score(
            analysis, [{"context": "x"}], None,
            {"accessibility": 0.0, "structure": 0.0, "authority": 0.0})
        self.assertIsNone(r["score"])
        self.assertIn("weight", r["score_reason"].lower())

    def test_the_section_says_not_measured_rather_than_zero(self):
        r = fs.compute_foundational_score(self.EMPTY, [{"context": "x"}], None)
        text = "\n".join(fs.render_foundational_section(r))
        self.assertIn("not measured", text)
        self.assertNotIn("0.0/100", text)

    def test_an_unmeasured_score_is_stored_as_null(self):
        """It was written to the trend table as a real row, so the next run's
        Δ was measured against a fabricated zero."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            r = fs.compute_foundational_score(
                self.EMPTY, [{"context": "x"}], None)
            fs.save_foundational_score(db, "20260704_1200", r)
            trend = fs.get_foundational_trend(db)
        self.assertEqual(len(trend), 1)
        self.assertIsNone(trend[0]["score"])


# ---------------------------------------------------------------------------
# 3. The outreach shortlist counts what it dropped
# ---------------------------------------------------------------------------

class TestCitationDropsAreCounted(unittest.TestCase):

    TABLE = [
        {"url": "https://a.example/1", "domain": "a.example",
         "category": "blog", "brand": None, "is_client": False,
         "cite_count": 3},
        {"url": "not a url", "domain": "", "category": "other",
         "brand": None, "is_client": False, "cite_count": 2},
    ]

    def test_the_unreadable_host_is_counted_not_just_skipped(self):
        ordered, dropped, total = citation_table.unattributed_citations(
            self.TABLE)
        self.assertEqual(ordered, [("a.example", 3)])
        self.assertEqual((dropped, total), (2, 5))

    def test_the_section_states_the_dropped_citations(self):
        text = "\n".join(citation_table.render_citation_section(
            "chatgpt", self.TABLE))
        self.assertIn("2 of 5", text)

    def test_a_truncated_table_says_how_much_it_shows(self):
        table = [{"url": f"https://e{i}.example/", "domain": f"e{i}.example",
                  "category": "blog", "brand": None, "is_client": False,
                  "cite_count": 1} for i in range(45)]
        text = "\n".join(citation_table.render_citation_section(
            "chatgpt", table, top_n=40))
        self.assertIn("40 most-cited of 45", text)


# ---------------------------------------------------------------------------
# 4. The refresh counts only the rows it wrote, and writes the file once
# ---------------------------------------------------------------------------

class TestRefreshCountsWhatItDid(unittest.TestCase):

    class _Classifier:
        def classify(self, domain, _x):
            return "clinic", 1.0, []

    def _workbook(self, tmp, rows):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Organic_Results"
        ws.append(["Link", "Source", "Entity_Type"])
        for row in rows:
            ws.append(row)
        path = os.path.join(tmp, "x.xlsx")
        wb.save(path)
        return path

    def test_a_row_with_no_domain_is_not_counted_as_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp, [
                ["https://a.example/p", "a.example", "N/A"],
                ["", "", "directory"],
            ])
            updated, changed = rao.refresh_xlsx(path, self._Classifier())
        self.assertEqual(updated, 1)
        self.assertEqual(changed, 1)

    def test_the_classification_pass_does_not_write_the_file(self):
        """It wrote a truncating `json.dump` onto the live file and the caller
        then wrote the same data again through the atomic helper."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            payload = {"organic_results": [
                {"Link": "https://a.example/p", "Entity_Type": "N/A"}]}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            with open(path, "rb") as fh:
                before = fh.read()
            before_mtime = os.stat(path).st_mtime_ns
            data, updated, changed = rao.refresh_json(path, self._Classifier())
            with open(path, "rb") as fh:
                after = fh.read()
            after_mtime = os.stat(path).st_mtime_ns
        self.assertEqual(data["organic_results"][0]["Entity_Type"], "clinic")
        # Exact bytes and mtime: a size comparison would pass a restored write
        # that happened to produce the same length.
        self.assertEqual(before, after)
        self.assertEqual(before_mtime, after_mtime)

    def test_a_failed_profile_rebuild_still_writes_the_rows(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"organic_results": [
                    {"Link": "https://a.example/p", "Entity_Type": "N/A"}]}, fh)
            with mock.patch.object(rao, "rebuild_keyword_profiles",
                                   side_effect=RuntimeError("boom")), \
                 mock.patch.object(rao, "refresh_xlsx", return_value=(0, 0)), \
                 mock.patch.object(rao, "regenerate_candidate_report",
                                   return_value=0), \
                 mock.patch.object(rao, "EntityClassifier",
                                   return_value=self._Classifier()):
                result = rao.refresh_analysis_outputs(
                    path, os.path.join(tmp, "x.xlsx"),
                    os.path.join(tmp, "o.yml"), os.path.join(tmp, "c.md"),
                    config={})
            with open(path, encoding="utf-8") as fh:
                on_disk = json.load(fh)
        self.assertIn("could not be rebuilt", result["profiles_error"])
        self.assertEqual(
            on_disk["organic_results"][0]["Entity_Type"], "clinic")


# ---------------------------------------------------------------------------
# 5. One bad validation rule costs that rule only, and the brief says so
# ---------------------------------------------------------------------------

class TestOneBadRuleIsOneBadRule(unittest.TestCase):

    def _rules_file(self, tmp, body):
        path = os.path.join(tmp, "rules.yml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_a_bad_tolerance_does_not_disable_the_other_rules(self):
        body = ("numeric_claims:\n"
                "  client_rank:\n"
                "    label: client rank\n"
                "    tolerance: 0\n"
                "    patterns: ['rank (\\\\d+)']\n"
                "  volume:\n"
                "    label: volume\n"
                "    tolerance: not-a-number\n"
                "    patterns: ['volume (\\\\d+)']\n"
                "market_size_phrases:\n"
                "  - a large market\n")
        with tempfile.TemporaryDirectory() as tmp:
            rules = brief_validation.load_validation_rules(
                self._rules_file(tmp, body))
        self.assertIn("client_rank", rules["numeric_claims"])
        self.assertNotIn("volume", rules["numeric_claims"])
        self.assertEqual(rules["fields_skipped"], ["volume"])
        # The demand phrases used to go with the bad field.
        self.assertEqual(rules["market_size_phrases"], ["a large market"])

    def test_a_missing_file_is_recorded_on_the_result(self):
        rules = brief_validation.load_validation_rules(
            "/nonexistent/rules.yml")
        self.assertTrue(rules["load_error"])
        self.assertEqual(rules["numeric_claims"], {})

    def test_the_sidecar_states_a_file_that_did_not_load(self):
        with mock.patch.object(
                brief_validation, "load_validation_rules",
                return_value={"numeric_claims": {}, "market_size_phrases": [],
                              "load_error": "rules.yml did not load (boom)",
                              "fields_skipped": []}):
            issues = brief_validation.validate_llm_report(
                "# Brief\n\nNothing to see.", {"queries": [],
                                                "keyword_profiles": {}})
        self.assertTrue(any("did not load" in i for i in issues), issues)

    def test_the_brief_sidecar_names_the_checks_that_did_not_run(self):
        """A check that is off is indistinguishable from a brief that passed
        it, and the only trace was one log line."""
        with mock.patch.object(
                brief_validation, "load_validation_rules",
                return_value={"numeric_claims": {}, "market_size_phrases": [],
                              "load_error": None,
                              "fields_skipped": ["volume", "gap"]}):
            issues = brief_validation.validate_llm_report(
                "# Brief\n\nNothing to see.", {"queries": [],
                                               "keyword_profiles": {}})
        self.assertTrue(any("volume" in i and "gap" in i for i in issues),
                        issues)


# ---------------------------------------------------------------------------
# The cold review's own findings
# ---------------------------------------------------------------------------

class TestTheColdReviewFindings(unittest.TestCase):

    def test_an_inactive_check_is_a_note_not_a_blocking_issue(self):
        """It went to `blocking`, so an unreadable editorial file spent a
        second LLM call on a correction prompt that cannot fix a YAML file and
        then exited 2 with no brief written."""
        issue = (f"{brief_validation.INACTIVE_CHECK_PREFIX} "
                 f"brief_validation_rules.yml did not load (boom).")
        blocking, notes = brief_validation.partition_validation_issues([issue])
        self.assertEqual(blocking, [])
        self.assertEqual(notes, [issue])
        self.assertFalse(
            brief_validation.has_hard_validation_failures([issue]))

    def test_a_rule_kept_on_fewer_phrasings_is_recorded(self):
        body = ("numeric_claims:\n"
                "  volume:\n"
                "    label: volume\n"
                "    tolerance: 0\n"
                "    patterns:\n"
                "      - 'volume (\\\\d+)'\n"
                "      - '(unclosed'\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.yml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            rules = brief_validation.load_validation_rules(path)
        self.assertIn("volume", rules["numeric_claims"])
        self.assertEqual(rules["patterns_dropped"], {"volume": 1})

    def test_unreadable_demand_phrases_are_recorded_not_only_logged(self):
        with mock.patch.object(brief_validation.yaml, "safe_load",
                               return_value={"market_size_phrases": 7}):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "r.yml")
                open(path, "w").write("x: 1")
                rules = brief_validation.load_validation_rules(path)
        self.assertIn("market_size_phrases", rules["fields_skipped"])

    def test_a_json_row_with_no_domain_is_not_counted_as_updated(self):
        """The fix was applied to the workbook side only, so the two figures
        over the same data meant different things."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"organic_results": [
                    {"Link": "https://a.example/p", "Entity_Type": "N/A"},
                    {"Link": "", "Source": "", "Entity_Type": "directory"},
                ]}, fh)
            _data, updated, changed = rao.refresh_json(
                path, TestRefreshCountsWhatItDid._Classifier())
        self.assertEqual(updated, 1)
        self.assertEqual(changed, 1)

    def test_measured_axes_with_no_weight_are_named(self):
        """`resolve_weights` replaces an all-zero config with equal thirds, so
        the reachable case is a weighted axis that was not measurable — and
        the report told the owner every weight was zero."""
        analysis = {"keyword_profiles": {"kw": {"extractability": {
            "data_available": True,
            "client_page": {"has_question_heading": True,
                            "intro_word_count": 120,
                            "has_faq_block": True}}}},
            "strategic_flags": {"geo_alerts": []}}
        r = fs.compute_foundational_score(
            analysis, [{"context": "x"}], None,
            {"accessibility": 0.0, "structure": 0.0, "authority": 1.0})
        self.assertIsNone(r["score"])
        self.assertIn("zero weight", r["score_reason"])
        self.assertNotIn("every configured weight", r["score_reason"])

    def test_a_definition_change_is_stated_even_with_no_score_this_run(self):
        r = fs.compute_foundational_score(
            {"keyword_profiles": {}, "strategic_flags": {"geo_alerts": []}},
            [{"context": "x"}], None)
        text = "\n".join(fs.render_foundational_section(r, [
            {"score": 10.0, "definition_version": 1},
            {"score": None, "definition_version": 2}]))
        self.assertIn("not comparable", text)

    def test_a_table_with_no_attributable_host_still_counts_the_drop(self):
        """The count was nested inside the shortlist block, so the case it
        exists for — nothing attributable — printed nothing."""
        table = [{"url": "not a url", "domain": "", "category": "other",
                  "brand": None, "is_client": False, "cite_count": 4}]
        text = "\n".join(citation_table.render_citation_section("x", table))
        self.assertIn("4 of 4", text)
        self.assertIn("no outreach target", text)

    def test_the_section_says_why_when_metrics_is_unavailable(self):
        import generate_insight_report as gir

        data = {"overview": [{"Run_ID": "curr", "Source_Keyword": "kw",
                              "Query_Label": "A", "Executed_Query": "kw"}],
                "keyword_profiles": {}}
        with mock.patch.object(gir, "METRICS_AVAILABLE", False):
            text = gir.generate_report(data)
        self.assertIn("6. Market Volatility", text)
        self.assertIn("could not be imported", text)

    def test_the_section_says_why_when_the_run_has_no_id(self):
        import generate_insight_report as gir

        text = gir.generate_report({"overview": [{"Source_Keyword": "kw",
                                                  "Query_Label": "A",
                                                  "Executed_Query": "kw"}],
                                    "keyword_profiles": {}})
        self.assertIn("no Run_ID", text)


if __name__ == "__main__":
    unittest.main()


class TestAChangedSearchIsNotRankMovement(unittest.TestCase):
    """query_location_fix_spec_v1.md (Risks): a keyword whose two runs sent
    different search text measured two searches, so its rank change is the
    fix, not the market."""

    def _db(self, tmp, prev_sent, curr_sent):
        db = os.path.join(tmp, "t.db")
        store = _store(db)
        _run(store, "prev", "2026-02-01T00:00:00")
        _run(store, "curr", "2026-02-02T00:00:00")
        for run, sent in (("prev", prev_sent), ("curr", curr_sent)):
            for kw in ("kw1", "kw2"):
                store.save_serp_result(run, kw, "organic", 1 if run == "prev" else 5,
                                       "", f"https://a.example/{kw}", "a.example", "",
                                       query_label="A", sent_query=sent.get(kw))
        return db

    def test_changed_text_is_left_out_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp, {"kw1": "kw1 Place", "kw2": None},
                          {"kw1": "kw1", "kw2": "kw2"})
            with mock.patch.object(db_connect, "DATABASE_PATH", db):
                vol = metrics.get_volatility_metrics("curr")
                deltas, reason = metrics.get_rank_deltas("curr", with_reason=True)
        self.assertEqual(vol["status"], "search_changed")
        self.assertIn("2 of 2 keywords not compared", vol["msg"])
        self.assertEqual(deltas, {})
        self.assertIn("2 of 2 keywords not compared", reason)

    def test_same_text_and_two_old_runs_still_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp, {"kw1": "kw1", "kw2": None}, {"kw1": "kw1", "kw2": None})
            with mock.patch.object(db_connect, "DATABASE_PATH", db):
                vol = metrics.get_volatility_metrics("curr")
        self.assertEqual(vol["status"], "success")
        self.assertEqual(vol["total_compared"], 2)
        self.assertFalse(vol.get("comparability_warning"))

    def test_a_partial_change_is_named_in_the_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp, {"kw1": "kw1 Place", "kw2": "kw2"},
                          {"kw1": "kw1", "kw2": "kw2"})
            with mock.patch.object(db_connect, "DATABASE_PATH", db):
                vol = metrics.get_volatility_metrics("curr")
        self.assertEqual(vol["status"], "success")
        self.assertEqual(vol["total_compared"], 1)
        self.assertIn("1 of 2 keywords not compared", vol["comparability_warning"])
        self.assertIn("kw1", vol["comparability_warning"])
