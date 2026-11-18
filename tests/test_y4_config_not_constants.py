"""Chunk Y4 — the numbers live in config, the ties are decided on purpose.

One guard per finding in
``docs/review_2026-11-04/PLAN_Y4_config_not_constants.md``.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk Y4
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import brief_validation          # noqa: E402
import http_retry                # noqa: E402
import run_gsc_analysis as rga    # noqa: E402
from storage import SerpStorage   # noqa: E402


# ---------------------------------------------------------------------------
# 1. The sponge comparison's shape is editorial
# ---------------------------------------------------------------------------

class TestSpongeThresholdsComeFromConfig(unittest.TestCase):

    def test_the_bucket_size_and_bands_are_read_from_config(self):
        out = rga.resolve_sponge_thresholds(
            {"gsc": {"min_bucket_size": 5,
                     "position_bands": [[1, 5], [6, 20]]}})
        self.assertEqual(out["min_bucket_size"], 5)
        self.assertEqual(out["position_bands"], [(1.0, 5.0), (6.0, 20.0)])

    def test_the_documented_defaults_apply_when_absent(self):
        out = rga.resolve_sponge_thresholds({"gsc": {}})
        self.assertEqual(out["min_bucket_size"], rga.MIN_BUCKET_SIZE)
        self.assertEqual(out["position_bands"],
                         list(rga.DEFAULT_POSITION_BANDS))

    def test_a_bucket_size_of_zero_is_refused(self):
        """It would report a median over one query as a comparison."""
        out = rga.resolve_sponge_thresholds({"gsc": {"min_bucket_size": 0}})
        self.assertEqual(out["min_bucket_size"], rga.MIN_BUCKET_SIZE)

    def test_a_band_that_cannot_hold_a_query_is_refused(self):
        for bands in ([[10, 3]], [[0, 5]], [["a", "b"]], [[1]], "nope", []):
            out = rga.resolve_sponge_thresholds(
                {"gsc": {"position_bands": bands}})
            self.assertEqual(out["position_bands"],
                             list(rga.DEFAULT_POSITION_BANDS), bands)

    def test_a_malformed_gsc_block_is_reported_not_raised(self):
        for block in (5, "deep", ["gsc"]):
            out = rga.resolve_sponge_thresholds({"gsc": block})
            self.assertEqual(out["min_bucket_size"], rga.MIN_BUCKET_SIZE,
                             block)

    def test_bands_that_overlap_or_leave_a_gap_are_refused(self):
        """Overlapping bands count one query in two medians; a gap drops a
        query from every denominator with nothing saying so."""
        for bands in ([[1, 3], [3, 10]], [[1, 3], [6, 10]]):
            out = rga.resolve_sponge_thresholds(
                {"gsc": {"position_bands": bands}})
            self.assertEqual(out["position_bands"],
                             list(rga.DEFAULT_POSITION_BANDS), bands)

    def test_bands_given_out_of_order_are_used_in_order(self):
        out = rga.resolve_sponge_thresholds(
            {"gsc": {"position_bands": [[4, 10], [1, 3]]}})
        self.assertEqual(out["position_bands"], [(1.0, 3.0), (4.0, 10.0)])

    def test_a_usable_query_in_no_band_is_counted(self):
        """With the default bands that is positions above 20; with a narrow
        `position_bands` it can be most of the set, and the report read as a
        clean comparison over what was left (P2/P9)."""
        rows = [{"found": True, "has_ai_overview": aio, "position": pos,
                 "ctr": 0.1, "impressions": 500}
                for pos in (1, 2, 3, 25) for aio in (True, False)]
        out = rga.compute_sponge_effect(
            rows, bands=[(1.0, 3.0)], min_bucket_size=3, min_impressions=1)
        self.assertEqual(out["queries_in_no_band"], 2)
        self.assertEqual(out["position_bands"], [[1.0, 3.0]])

    def test_the_shortlist_cap_is_read_from_config(self):
        out = rga.resolve_sponge_thresholds(
            {"gsc": {"reformat_max_position": 20,
                     "position_bands": [[1, 3], [4, 20]]}})
        self.assertEqual(out["reformat_max_position"], 20.0)
        self.assertEqual(
            rga.resolve_sponge_thresholds({"gsc": {}})[
                "reformat_max_position"], rga.REFORMAT_MAX_POSITION)

    def test_a_deeper_band_without_a_deeper_cap_shortlists_nothing(self):
        """The cap stayed a Python constant when the bands became config, so a
        client whose pages sit at 11-20 configured the bands and got an
        always-empty shortlist with nothing saying why."""
        sponge = {"bands": [{"band_range": [11, 20], "sufficient": True,
                             "no_aio_median_ctr": 0.10}]}
        row = {"found": True, "position": 14.0, "has_ai_overview": True,
               "ctr": 0.01, "impressions": 500, "query": "kw",
               "source_keyword": "kw"}
        self.assertEqual(
            rga.find_reformat_candidates([row], sponge, set(),
                                         max_position=10.0), [])
        self.assertEqual(
            len(rga.find_reformat_candidates([row], sponge, set(),
                                             max_position=20.0)), 1)

    def test_the_run_passes_the_resolved_bands_and_bucket_size(self):
        """Resolving them is no use if the run still calls the comparison with
        its own defaults — the call site is the only thing that makes the
        config keys real."""
        import json
        from datetime import date

        import gsc_client

        data = {"overview": [
            {"Query_Label": "A", "Source_Keyword": "kw one",
             "Executed_Query": "kw one", "Has_Main_AI_Overview": False}]}
        config = {"gsc": {"enabled": True, "lookback_days": 90,
                          "min_bucket_size": 9,
                          "position_bands": [[2, 7]],
                          "reformat_max_position": 15},
                  "analysis_report": {"client_name": "C"}}
        client = mock.MagicMock()
        client.get_query_stats.return_value = gsc_client.GscStats(
            stats={"kw one": {"clicks": 5, "impressions": 100,
                              "ctr": 0.05, "position": 3.0}},
            complete=True, asked=["kw one"], measured_absent=[],
            not_reached=[])
        seen = {}
        shortlist_seen = {}
        real = rga.compute_sponge_effect
        real_shortlist = rga.find_reformat_candidates

        def _spy(rows, **kwargs):
            seen.update(kwargs)
            return real(rows, **kwargs)

        def _shortlist_spy(rows, sponge, kws, **kwargs):
            shortlist_seen.update(kwargs)
            return real_shortlist(rows, sponge, kws, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(
                tmp, "market_analysis_topic_20260701_1200.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            with mock.patch.object(rga, "compute_sponge_effect", _spy), \
                 mock.patch.object(rga, "find_reformat_candidates",
                                   _shortlist_spy):
                rga.run_analysis(data, config, client, path,
                                 today=date(2026, 7, 4), db_path=None)
        self.assertEqual(seen.get("min_bucket_size"), 9)
        self.assertEqual(seen.get("bands"), [(2.0, 7.0)])
        # And the shortlist's own cap, which stayed a constant when the bands
        # became config.
        self.assertEqual(shortlist_seen.get("max_position"), 15.0)

    def test_the_configured_bands_reach_the_comparison(self):
        rows = [{"found": True, "has_ai_overview": aio, "position": pos,
                 "ctr": 0.1, "impressions": 500}
                for pos in (1, 2, 3, 4, 5) for aio in (True, False)]
        out = rga.compute_sponge_effect(
            rows, bands=[(1.0, 5.0)], min_bucket_size=5, min_impressions=1)
        self.assertEqual(len(out["bands"]), 1)


# ---------------------------------------------------------------------------
# 2. The retry budget is editorial, and one mapping reaches every caller
# ---------------------------------------------------------------------------

class TestRetryPolicyComesFromConfig(unittest.TestCase):

    def test_the_policy_is_read_from_config(self):
        out = http_retry.resolve_retry_policy(
            {"http_retry": {"attempts": 4, "backoff_seconds": 2.5,
                            "max_retry_after_seconds": 10}})
        # The retry budget only. Y5 added the three timeout classes to the
        # same policy, each from the section that owns it, so this asserts its
        # own three keys rather than the whole dict.
        self.assertEqual({k: out[k] for k in ("attempts", "backoff",
                                              "max_retry_after")},
                         {"attempts": 4, "backoff": 2.5,
                          "max_retry_after": 10.0})

    def test_a_policy_of_zero_is_refused(self):
        """Zero attempts makes every transient failure terminal (P1)."""
        out = http_retry.resolve_retry_policy(
            {"http_retry": {"attempts": 0, "backoff_seconds": -1}})
        self.assertEqual(out["attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])
        self.assertEqual(out["backoff"],
                         http_retry.DEFAULT_RETRY_POLICY["backoff"])

    def test_an_unreadable_value_falls_back_to_the_documented_default(self):
        out = http_retry.resolve_retry_policy(
            {"http_retry": {"attempts": "lots"}})
        self.assertEqual(out["attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])

    def test_applying_twice_does_not_compound(self):
        """The fallback used to be read from the module constants, which
        `apply_retry_policy` rebinds — so a second config with no `attempts`
        kept the first config's number instead of the documented default."""
        try:
            http_retry.apply_retry_policy({"http_retry": {"attempts": 7}})
            policy = http_retry.apply_retry_policy({"http_retry": {}})
        finally:
            http_retry.apply_retry_policy(None)
        self.assertEqual(policy["attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])

    def test_one_mapping_reaches_a_caller_that_passes_nothing(self):
        """The helpers used to take the constants as DEFAULT ARGUMENTS, which
        are bound at def time — so setting the policy would have reached no
        caller at all."""
        calls = []

        def _get(url, **kwargs):
            calls.append(url)
            raise http_retry.requests.exceptions.ConnectionError("reset")

        try:
            http_retry.apply_retry_policy(
                {"http_retry": {"attempts": 4, "backoff_seconds": 0.01}})
            self.assertEqual(http_retry.RETRY_ATTEMPTS, 4)
            out = http_retry.get_with_transient_retry(
                "test", "https://x.example/", {}, "x", get=_get)
            self.assertIsNone(out)
            self.assertEqual(len(calls), 4)
        finally:
            http_retry.apply_retry_policy(None)
        self.assertEqual(http_retry.RETRY_ATTEMPTS,
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])

    def test_the_config_file_carries_the_block(self):
        import yaml

        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        self.assertIn("http_retry", cfg)
        for key in ("attempts", "backoff_seconds", "max_retry_after_seconds"):
            self.assertIn(key, cfg["http_retry"], key)

    def test_every_entry_point_applies_the_policy(self):
        """A setting that changes one script and silently does nothing in the
        other three is worse than no setting (P5)."""
        import importlib
        import run_gsc_analysis as _rga

        # This calls the real loaders against the repo's own `config.yml`,
        # which leaves `run_gsc_analysis`' sponge thresholds set to whatever
        # that file says for every later test in the process. Latent only
        # while those five values equal the documented defaults (cold review
        # of chunk Y6, finding 7).
        self.addCleanup(_rga.apply_sponge_thresholds, None)

        # `refresh_analysis_outputs` joined the list in chunk Y6: it re-runs
        # the entity classifier, which fetches, and was the one loader of five
        # that applied no policy.
        for name in ("run_feasibility", "run_gsc_analysis",
                     "probe_ai_visibility", "report_llm",
                     "refresh_analysis_outputs"):
            module = importlib.import_module(name)
            loader = (getattr(module, "_load_config", None)
                      or getattr(module, "load_config", None)
                      or module.load_settings)
            with mock.patch.object(http_retry, "apply_retry_policy") as spy:
                loader("config.yml")
            self.assertEqual(spy.call_count, 1, name)
            self.assertIsNotNone(spy.call_args.args[0], name)

    def test_a_missing_config_still_resets_the_policy(self):
        """Otherwise a second run in the same process keeps the first run's
        policy."""
        import run_gsc_analysis

        http_retry.apply_retry_policy({"http_retry": {"attempts": 6}})
        run_gsc_analysis._load_config("no-such-config.yml")
        self.assertEqual(http_retry.RETRY_ATTEMPTS,
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])

    def test_the_audit_really_retries_the_configured_number_of_times(self):
        """A consequence test in a real process: `serp_audit` applies the
        policy at import time, so what matters is the number a caller that
        passes nothing ends up with — not that a line of source exists."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "config.yml"), "w",
                      encoding="utf-8") as fh:
                fh.write("http_retry:\n  attempts: 4\n  backoff_seconds: 0.1\n")
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import serp_audit, http_retry; "
                 "print(http_retry.RETRY_ATTEMPTS)"],
                cwd=tmp, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": REPO})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertEqual(proc.stdout.strip().splitlines()[-1], "4",
                         proc.stdout + proc.stderr[-2000:])

    def test_a_malformed_block_is_reported_not_raised(self):
        """`serp_audit` applies the policy at module level, so a TypeError
        here killed every run on import instead of warning."""
        for block in (2, "fast", ["attempts"]):
            out = http_retry.resolve_retry_policy({"http_retry": block})
            self.assertEqual(out, dict(http_retry.DEFAULT_RETRY_POLICY), block)

    def test_a_boolean_is_not_a_number_of_attempts(self):
        out = http_retry.resolve_retry_policy(
            {"http_retry": {"attempts": True}})
        self.assertEqual(out["attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])

    def test_the_documented_default_cannot_be_rewritten(self):
        with self.assertRaises(TypeError):
            http_retry.DEFAULT_RETRY_POLICY["attempts"] = 99

# ---------------------------------------------------------------------------
# 3. A tie at the top of the entity mix is tested on every tied entity
# ---------------------------------------------------------------------------

class TestTheDominanceTieIsNotADictOrder(unittest.TestCase):

    def _data(self, distribution):
        return {"keyword_profiles": {"couples therapy": {
            "entity_distribution": distribution}}}

    def test_every_tied_entity_is_returned(self):
        out = brief_validation._mixed_keyword_dominance_profiles(
            self._data({"clinic": 4, "directory": 4, "blog": 3}))
        self.assertEqual(len(out), 1)
        keyword, top_entities, top_count, second_count, _share = out[0]
        self.assertEqual(keyword, "couples therapy")
        self.assertEqual(sorted(top_entities), ["clinic", "directory"])
        self.assertEqual((top_count, second_count), (4, 4))

    def test_the_tied_entities_come_out_in_a_stated_order(self):
        """Dict order decided it, so the same data could produce two different
        issue messages (P12/P19). The tie-break is count then name."""
        for distribution in ({"clinic": 4, "directory": 4, "blog": 3},
                             {"directory": 4, "clinic": 4, "blog": 3}):
            out = brief_validation._mixed_keyword_dominance_profiles(
                self._data(distribution))
            self.assertEqual(out[0][1], ["clinic", "directory"], distribution)

    def test_the_contradiction_is_found_whichever_tied_name_is_used(self):
        """The check tested one of the tied entities, picked by the order the
        entities happened to appear in the JSON, so a brief naming the other
        one passed with no issue raised."""
        for named in ("clinic", "directory"):
            report = (f"**couples therapy (informational)**\n\n"
                      f"The {named} entities dominate this SERP.\n\n")
            issues = brief_validation.validate_llm_report(
                report, {"queries": [],
                         "keyword_profiles": {"couples therapy": {
                             "entity_distribution": {"clinic": 4,
                                                     "directory": 4,
                                                     "blog": 3}}}})
            self.assertTrue(
                any("too close" in i and named in i for i in issues),
                (named, issues))

    def test_the_tie_is_named_in_the_issue(self):
        report = ("**couples therapy (informational)**\n\n"
                  "The clinic entities dominate this SERP.\n\n")
        issues = brief_validation.validate_llm_report(
            report, {"queries": [],
                     "keyword_profiles": {"couples therapy": {
                         "entity_distribution": {"clinic": 4, "directory": 4,
                                                 "blog": 3}}}})
        self.assertTrue(any("tie between" in i for i in issues), issues)

    def test_the_second_count_is_the_next_lower_count_not_the_tie(self):
        out = brief_validation._mixed_keyword_dominance_profiles(
            self._data({"clinic": 6, "directory": 4, "blog": 4}))
        self.assertEqual(out[0][1], ["clinic"])
        self.assertEqual(out[0][3], 4)


# ---------------------------------------------------------------------------
# 4. The rank chart plots the primary query of completed runs only
# ---------------------------------------------------------------------------

class TestTheChartPlotsTheRankHistory(unittest.TestCase):

    def _db(self, tmp):
        db = os.path.join(tmp, "serp.db")
        store = SerpStorage(db_path=db)

        def _run(run_id, date, completed=True):
            store.save_run(run_id, "x")
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE runs SET run_date = ? WHERE run_id = ?",
                             (date, run_id))
            if completed:
                store.mark_run_completed(run_id, completed_at=date)

        _run("done", "2026-02-01T00:00:00")
        _run("aborted", "2026-02-02T00:00:00", completed=False)
        store.save_serp_result("done", "kw", "organic", 4, "", "https://a/1",
                               "a.example", "", query_label="A")
        # A pivot row: the same keyword text, a different query.
        store.save_serp_result("done", "kw", "organic", 1, "", "https://b/1",
                               "b.example", "", query_label="P")
        store.save_serp_result("aborted", "kw", "organic", 1, "",
                               "https://c/1", "c.example", "",
                               query_label="A")
        # Deeper than the chart's depth: excluded, and said so.
        store.save_serp_result("done", "kw", "organic", 14, "",
                               "https://d/1", "d.example", "",
                               query_label="A")
        return db

    def test_only_primary_rows_of_completed_runs_are_plotted(self):
        import visualize_volatility as vv

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            with mock.patch.object(vv, "DB_PATH", db), \
                 mock.patch.object(vv.plt, "show"), \
                 mock.patch.object(vv.plt, "savefig"):
                captured = []
                with mock.patch("builtins.print", captured.append):
                    vv.plot_history("kw")
                    keywords = vv.get_keywords()
        # 3 stored rows, 1 plottable → 2 excluded, and it says so.
        self.assertTrue(any("Of 4 stored row(s)" in str(c) for c in captured),
                        captured)
        self.assertTrue(any("deeper than rank 10" in str(c)
                            for c in captured), captured)
        self.assertTrue(any("different query" in str(c) for c in captured),
                        captured)
        self.assertTrue(any("did not finish" in str(c) for c in captured),
                        captured)
        self.assertEqual(keywords, ["kw"])

    def test_a_row_of_unknown_provenance_is_not_called_a_pivot(self):
        """`query_label` and `completed_at` are NULL on rows written before
        their migrations. NULL means unknown — naming it a pivot or an
        aborted run is an invented cause (P35)."""
        import visualize_volatility as vv

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "serp.db")
            store = SerpStorage(db_path=db)
            store.save_run("old", "x")
            store.mark_run_completed("old", completed_at="2026-02-01")
            store.save_serp_result("old", "kw", "organic", 3, "",
                                   "https://a/1", "a.example", "",
                                   query_label="A")
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE serp_results SET query_label = NULL")
            with mock.patch.object(vv, "DB_PATH", db), \
                 mock.patch.object(vv.plt, "show"), \
                 mock.patch.object(vv.plt, "savefig"):
                captured = []
                with mock.patch("builtins.print", captured.append):
                    vv.plot_history("kw")
        text = " ".join(str(c) for c in captured)
        self.assertIn("unknown", text)
        self.assertNotIn("different query", text)

    def test_a_keyword_seen_only_in_an_aborted_run_is_not_offered(self):
        import visualize_volatility as vv

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "serp.db")
            store = SerpStorage(db_path=db)
            store.save_run("aborted", "x")
            store.save_serp_result("aborted", "half run", "organic", 1, "",
                                   "https://b/1", "b.example", "",
                                   query_label="A")
            with mock.patch.object(vv, "DB_PATH", db):
                self.assertEqual(vv.get_keywords(), [])

    def test_an_aborted_run_is_not_plotted(self):
        import visualize_volatility as vv

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            with mock.patch.object(vv, "DB_PATH", db), \
                 mock.patch.object(vv.plt, "show"), \
                 mock.patch.object(vv.plt, "savefig"):
                plotted = []
                with mock.patch.object(vv.pd, "read_sql",
                                       side_effect=self._capture(vv, plotted)):
                    vv.plot_history("kw")
        # Only the one primary row of the completed run reaches the chart.
        self.assertEqual(plotted[-1], 1, plotted)

    def _capture(self, vv, plotted):
        real = vv.pd.read_sql

        def _read(sql, conn, **kwargs):
            out = real(sql, conn, **kwargs)
            if "s.rank," in sql:
                plotted.append(len(out))
            return out

        return _read

    def test_a_keyword_with_only_pivot_rows_is_not_offered(self):
        import visualize_volatility as vv

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "serp.db")
            store = SerpStorage(db_path=db)
            store.save_run("done", "x")
            store.mark_run_completed("done", completed_at="2026-02-01")
            store.save_serp_result("done", "pivot kw", "organic", 1, "",
                                   "https://b/1", "b.example", "",
                                   query_label="P")
            with mock.patch.object(vv, "DB_PATH", db):
                self.assertEqual(vv.get_keywords(), [])

    def test_the_label_has_one_definition(self):
        import metrics
        import visualize_volatility as vv

        self.assertEqual(vv.PRIMARY_QUERY_LABEL, metrics.PRIMARY_QUERY_LABEL)


# ---------------------------------------------------------------------------
# 5. One host form in the audit's own row
# ---------------------------------------------------------------------------

class TestTheAuditUsesTheCanonicalHost(unittest.TestCase):

    def test_no_netloc_host_is_derived_anywhere_in_the_audit(self):
        """Walked, not grepped: a `.netloc` read is the hand-rolled host, and
        it keeps the port, the userinfo and the `www.` prefix that every other
        table in the tool strips."""
        import ast

        with open(os.path.join(REPO, "serp_audit.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        netloc = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute) and node.attr == "netloc"]
        self.assertEqual(
            [n.lineno for n in netloc], [],
            "serp_audit reads .netloc; use domain_utils.normalize_domain")

    def test_the_audit_binds_the_shared_rule_not_a_copy(self):
        import domain_utils
        import serp_audit

        self.assertIs(serp_audit.normalize_domain,
                      domain_utils.normalize_domain)

    def test_the_row_the_audit_stores_carries_the_canonical_host(self):
        import serp_audit

        for url, expected in (("https://WWW.Example.com:8080/p", "example.com"),
                              ("https://user:pw@example.com/p", "example.com")):
            self.assertEqual(serp_audit.normalize_domain(url), expected, url)


if __name__ == "__main__":
    unittest.main()
