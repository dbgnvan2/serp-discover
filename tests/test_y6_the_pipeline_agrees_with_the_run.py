"""Y6 — the in-pipeline run decides the same way the standalone one does.

`serp_audit` decided every keyword's pivot inside the SERP fetch loop, before
`keyword_profiles` existed, so it called
`feasibility.generate_hyper_local_pivot` with neither `serp_intent` nor
`entity_distribution` while `run_feasibility.py` passed both. Same SERP,
different pivot, and the pipeline's strategy paragraph could not name the
market composition it had measured. Three siblings came with it: a fifth
config loader applying no retry policy, a chart opening the database around
`SerpStorage`'s migrations, and two sponge helpers naming module constants as
default arguments.

Spec: docs/review_2026-11-04/PLAN_Y6_the_pipeline_agrees_with_the_run.md

All external calls are mocked; no API keys required.
"""

import ast
import logging
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

import feasibility
import gsc_client
import http_retry
import metrics
import pivot_pass
import run_gsc_analysis as rga
import storage


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_LOW = feasibility.compute_feasibility(
    35, feasibility.DAWindow([90] * 8, 8, 0, 8))
_UNMEASURED = feasibility.compute_feasibility(
    35, feasibility.DAWindow([], 0, 10, 10))


def _pending(keyword, feas=None, is_service_like=False):
    return {"keyword": keyword, "feas": feas or _LOW,
            "client_da_source": "moz", "is_service_like": is_service_like}


def _decide(pending, profiles, **kw):
    kwargs = {"location": "North Vancouver, BC",
              "neighborhoods": ["Lonsdale"],
              "pivotable_intents": ("local", "transactional"),
              "pivot_fetch": True, "storage": None, "run_id": "r1",
              "log": lambda *_: None}
    kwargs.update(kw)
    return pivot_pass.decide_pivots(pending, profiles, **kwargs)


class TestTheMeasuredIntentDecides(unittest.TestCase):
    """Y6.1 — the pipeline's gate reads the verdict, not the keyword text."""

    def test_a_measured_local_intent_pivots_a_keyword_the_tokens_refuse(self):
        """The reproduced defect: `bowen theory explained` carries no service
        token, and its SERP measured `local`."""
        profiles = {"bowen theory explained": {
            "serp_intent": {"primary_intent": "local", "is_mixed": False}}}
        rows, _ = _decide([_pending("bowen theory explained")], profiles)
        self.assertEqual(rows[0]["pivot_status"], "Pivoting to Hyper-Local")
        self.assertEqual(rows[0]["gate_source"], "serp_intent.primary_intent")

    def test_a_measured_informational_intent_refuses_a_service_keyword(self):
        """Both directions: the verdict can also stop a pivot the tokens want."""
        profiles = {"counselling vancouver": {
            "serp_intent": {"primary_intent": "informational",
                            "is_mixed": False}}}
        rows, jobs = _decide(
            [_pending("counselling vancouver", is_service_like=True)],
            profiles)
        self.assertTrue(feasibility.is_no_pivot(rows[0]["pivot_status"]))
        self.assertIn("informational", rows[0]["pivot_status"])
        self.assertEqual(jobs, [])

    def test_no_profile_decides_on_the_tokens_and_says_so(self):
        """A keyword the builder produced no profile for is decided exactly as
        it was before this pass existed, and the refusal names that."""
        rows, _ = _decide([_pending("bowen theory explained")], {})
        self.assertTrue(feasibility.is_no_pivot(rows[0]["pivot_status"]))
        self.assertTrue(rows[0]["gate_source"].startswith("is_service_like"),
                        rows[0]["gate_source"])

    def test_both_entry_points_reach_the_same_decision(self):
        """The standalone producer's call and the pipeline's, same inputs."""
        profile = {"serp_intent": {"primary_intent": "local",
                                   "is_mixed": False},
                   "entity_distribution": {"directory": 6, "clinic": 4}}
        standalone = feasibility.generate_hyper_local_pivot(
            primary_keyword="bowen theory explained",
            non_profit_location="North Vancouver, BC",
            feasibility_results={"status": _LOW["feasibility_status"],
                                 "avg_competitor_da": _LOW["avg_serp_da"]},
            neighborhoods=["Lonsdale"], is_service_like=False,
            serp_intent=profile["serp_intent"],
            entity_distribution=profile["entity_distribution"],
            pivotable_intents=("local", "transactional"))
        rows, _ = _decide([_pending("bowen theory explained")],
                          {"bowen theory explained": profile})
        for key in ("pivot_status", "gate_source", "suggested_keyword",
                    "strategy"):
            self.assertEqual(rows[0][key], standalone[key], key)


class TestTheStrategyParagraphNamesWhatWasMeasured(unittest.TestCase):
    """Y6.2 — the composition the run measured reaches the paragraph."""

    def test_a_measured_distribution_is_named(self):
        profiles = {"therapy vancouver": {
            "serp_intent": {"primary_intent": "local", "is_mixed": False},
            "entity_distribution": {"directory": 7, "clinic": 3}}}
        rows, _ = _decide([_pending("therapy vancouver")], profiles)
        self.assertIn("directory", rows[0]["strategy"])
        self.assertIn("7 of 10", rows[0]["strategy"])

    def test_no_distribution_claims_no_composition(self):
        """P35 — with nothing measured the paragraph says nothing about what
        the page holds, rather than asserting directories."""
        profiles = {"therapy vancouver": {
            "serp_intent": {"primary_intent": "local", "is_mixed": False}}}
        rows, _ = _decide([_pending("therapy vancouver")], profiles)
        self.assertNotIn("director", rows[0]["strategy"].split(
            "We recommend")[0])
        self.assertIn("out of reach on domain authority alone",
                      rows[0]["strategy"])


class TestThePassSaysHowManyWereMeasured(unittest.TestCase):
    """Y6.3 — P2: a run whose profiles failed does not read like one whose
    profiles built."""

    def test_the_gate_counts_the_measured_keywords(self):
        lines = []
        _decide([_pending("a"), _pending("b")],
                {"a": {"serp_intent": {"primary_intent": "local"}}},
                log=lines.append)
        gate = [line for line in lines if "[Pivot gate]" in line]
        self.assertEqual(len(gate), 1)
        self.assertIn("1 of 2", gate[0])

    def test_a_block_with_no_verdict_is_not_a_measured_keyword(self):
        """`compute_serp_intent` always returns a dict.

        When fewer than five of the ten URLs classified, `primary_intent` is
        None and the token guess decides — and the block is still truthy, so
        counting its presence reported "1 of 1 decided on a measured SERP
        intent" in exactly the degraded case the line exists to make loud
        (cold review of chunk Y6, finding 1).
        """
        unclassified = {"primary_intent": None, "is_mixed": False,
                        "confidence": 0.0, "distribution": {}}
        self.assertTrue(unclassified)   # the shape the builder really returns
        lines = []
        rows, _ = _decide([_pending("a")],
                          {"a": {"serp_intent": unclassified}},
                          log=lines.append)
        gate = [line for line in lines if "[Pivot gate]" in line]
        self.assertIn("0 of 1", gate[0])
        self.assertTrue(rows[0]["gate_source"].startswith("is_service_like"))

    def test_every_branch_reports_what_decided_the_gate(self):
        """The count reads `gate_source`, so no branch may omit it."""
        profiles = {"k": {"serp_intent": {"primary_intent": "local",
                                          "is_mixed": False}}}
        for feas, expected in ((_LOW, "Pivoting to Hyper-Local"),
                               (_UNMEASURED, "Stay the course")):
            rows, _ = _decide([_pending("k", feas)], profiles)
            self.assertEqual(rows[0]["pivot_status"], expected)
            self.assertEqual(rows[0]["gate_source"],
                             "serp_intent.primary_intent")
        moderate = feasibility.compute_feasibility(
            35, feasibility.DAWindow([50] * 6, 6, 0, 6))
        rows, _ = _decide([_pending("k", moderate)], profiles)
        self.assertEqual(rows[0]["pivot_status"], "Stay the course")
        self.assertEqual(rows[0]["gate_source"], "serp_intent.primary_intent")

    def test_a_build_failure_degrades_to_the_token_guess(self):
        with mock.patch("brief_data_extraction.build_keyword_profiles",
                        side_effect=RuntimeError("boom")):
            with self.assertLogs("pivot_pass", level="WARNING") as logs:
                profiles = pivot_pass.build_pivot_profiles(
                    {}, [], [], [], [], [], ["k"], {}, "livingsystems.ca")
        self.assertEqual(profiles, {})
        self.assertIn("keyword text alone", "\n".join(logs.output))

    def test_a_malformed_routing_table_is_still_a_hard_error(self):
        """A `ValueError` from the builder means a broken editorial file, and
        the catch-all would have degraded it to "no profiles" (cold review of
        chunk Y6, finding 10)."""
        with mock.patch("brief_data_extraction.build_keyword_profiles",
                        side_effect=ValueError("play_routing.yml is junk")):
            with self.assertRaises(ValueError):
                pivot_pass.build_pivot_profiles(
                    {}, [], [], [], [], [], ["k"], {}, "livingsystems.ca")

    def test_the_builders_per_keyword_warnings_are_not_doubled(self):
        """The end of the run calls the same builder again, so this pass
        keeps the per-keyword lines quiet and restores the level."""
        builder_log = logging.getLogger("brief_data_extraction")
        before = builder_log.level
        seen = []

        def _warn_then_return(*_a, **_kw):
            seen.append(builder_log.isEnabledFor(logging.WARNING))
            return {}

        with mock.patch("brief_data_extraction.build_keyword_profiles",
                        side_effect=_warn_then_return):
            pivot_pass.build_pivot_profiles(
                {}, [], [], [], [], [], ["k"], {}, "c.ca")
        self.assertEqual(seen, [False])
        self.assertEqual(builder_log.level, before)

    def test_the_profiles_come_from_the_shared_builder(self):
        """P32 — not a second definition of what this SERP is."""
        with mock.patch("brief_data_extraction.build_keyword_profiles",
                        return_value={"k": {}}) as spy:
            pivot_pass.build_pivot_profiles(
                {"k": {}}, [], [], [], [], [], ["k"], {"a": 1}, "c.ca")
        self.assertEqual(spy.call_count, 1)


class TestTheRowIsStillWrittenOnce(unittest.TestCase):
    """Y6.4 — the pass writes the same row the loop wrote."""

    def test_storage_gets_the_row_and_its_variants(self):
        saved = []

        class _Storage:
            def save_feasibility_from_row(self, row, run_id, label,
                                          pivot_variants=None):
                saved.append((row, run_id, label, pivot_variants))

        profiles = {"therapy vancouver": {
            "serp_intent": {"primary_intent": "local", "is_mixed": False}}}
        _decide([_pending("therapy vancouver")], profiles,
                storage=_Storage())
        self.assertEqual(len(saved), 1)
        row, run_id, label, variants = saved[0]
        self.assertEqual((run_id, label), ("r1", "A"))
        self.assertEqual(row["Query_Label"], "A")
        self.assertEqual(variants, ["therapy vancouver Lonsdale"])

    def test_enrichment_off_writes_nothing(self):
        rows, _ = _decide([_pending("therapy vancouver")], {}, storage=None)
        self.assertEqual(len(rows), 1)


class TestThePipelineStillRunsThePass(unittest.TestCase):
    """Y6.9 — the pass is wired into `serp_audit._run`.

    Every other guard calls `pivot_pass.decide_pivots` directly, so deleting
    the call from the fetch pipeline would leave the suite green while every
    pivot row, every feasibility write and every queued pivot fetch vanished
    from a real run (cold review of chunk Y6, finding 6). A consequence test
    would have to drive a whole SERP run, so this asserts the wiring: the
    call exists, its result reaches both lists, and `serp_audit` decides no
    pivot of its own.
    """

    def test_serp_audit_calls_the_pass_and_uses_both_of_its_results(self):
        tree = ast.parse((_REPO_ROOT / "serp_audit.py").read_text(
            encoding="utf-8"))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "decide_pivots"]
        self.assertEqual(len(calls), 1, "serp_audit must run the pivot pass")

        source = (_REPO_ROOT / "serp_audit.py").read_text(encoding="utf-8")
        self.assertIn("all_feasibility.extend(", source)
        self.assertIn("pending_pivot_jobs.extend(", source)
        # The decision itself is not made twice.
        self.assertNotIn("generate_hyper_local_pivot", source)


class TestEveryLoaderAppliesThePolicy(unittest.TestCase):
    """Y6.5 — `refresh_analysis_outputs` was the fifth config loader."""

    def setUp(self):
        self.addCleanup(http_retry.apply_retry_policy, None)

    def test_the_refresh_script_applies_the_configured_policy(self):
        import refresh_analysis_outputs as rao

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.yml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("http_retry:\n  attempts: 7\n")
            rao.load_config(path)
        self.assertEqual(http_retry.RETRY_ATTEMPTS, 7)

    def test_a_missing_config_resets_the_policy(self):
        import refresh_analysis_outputs as rao

        http_retry.apply_retry_policy({"http_retry": {"attempts": 6}})
        rao.load_config("no-such-config.yml")
        self.assertEqual(http_retry.RETRY_ATTEMPTS,
                         http_retry.DEFAULT_RETRY_POLICY["attempts"])


class TestTheChartReadsAMigratedDatabase(unittest.TestCase):
    """Y6.6 — a schema that was never brought forward is not a crash."""

    def _legacy_db(self, tmp):
        """A database as it was before the query_label / completed_at
        migrations: the columns the chart filters on do not exist."""
        path = os.path.join(tmp, "legacy.db")
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, "
                         "run_date TEXT, params_hash TEXT)")
            conn.execute("CREATE TABLE serp_results (run_id TEXT, "
                         "keyword_text TEXT, result_type TEXT, rank INTEGER, "
                         "domain TEXT, url TEXT)")
            conn.execute("INSERT INTO runs VALUES ('r1', '2026-11-01', 'h')")
            conn.execute("INSERT INTO serp_results VALUES "
                         "('r1', 'k', 'organic', 1, 'a.com', 'u')")
        return path

    def test_a_pre_migration_database_still_lists_keywords(self):
        import visualize_volatility as viz

        with tempfile.TemporaryDirectory() as tmp:
            path = self._legacy_db(tmp)
            with mock.patch.object(viz, "DB_PATH", path):
                # The row predates the migrations, so its query_label is NULL
                # and it is not plottable — an empty list, not `no such
                # column`.
                self.assertEqual(viz.get_keywords(), [])

    def test_the_chart_reports_the_unplottable_row_rather_than_raising(self):
        import visualize_volatility as viz

        with tempfile.TemporaryDirectory() as tmp:
            path = self._legacy_db(tmp)
            printed = []
            with mock.patch.object(viz, "DB_PATH", path), \
                 mock.patch("builtins.print", printed.append):
                viz.plot_history("k")
        text = "\n".join(printed)
        self.assertIn("No primary-query data", text)
        self.assertIn("migrations", text)

    def test_an_absent_database_is_not_an_empty_history(self):
        """P35 — `SerpStorage` creates the file, so opening an absent path
        would answer every query with "nothing found" and leave a new empty
        database behind (cold review of chunk Y6, finding 2)."""
        import visualize_volatility as viz

        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.db")
            printed = []
            with mock.patch.object(viz, "DB_PATH", missing), \
                 mock.patch("builtins.print", printed.append):
                self.assertEqual(viz.get_keywords(), [])
                viz.plot_history("k")
            self.assertFalse(os.path.exists(missing))
        text = "\n".join(printed)
        self.assertIn("No history database", text)
        self.assertNotIn("No primary-query data", text)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                storage.migrated_connection(os.path.join(tmp, "nope.db"))
            self.assertEqual(os.listdir(tmp), [])

    def test_bringing_a_schema_forward_is_announced(self):
        """A read path that rewrites the operator's history says so (finding
        3): the migration adds columns, and the Y1 canonicalisation rewrites
        stored hosts and deletes orphaned feature rows."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._legacy_db(tmp)
            said = []
            with storage.migrated_connection(path, log=said.append) as conn:
                conn.execute("SELECT 1")
            text = "\n".join(said)
            self.assertIn("brought forward", text)
            self.assertIn("column(s) added", text)

            # Second open: nothing left to change, so nothing is claimed.
            said = []
            with storage.migrated_connection(path, log=said.append):
                pass
            self.assertEqual(said, [])

    def test_the_history_reader_brings_a_legacy_schema_forward(self):
        """`generate_insight_report.py` calls `metrics` standalone with no
        `SerpStorage` constructed first, so against a pre-migration database
        the dominance query printed "no such column: s.query_label" instead
        of bringing the schema forward (cold review of chunk Y6, finding 5).
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = self._legacy_db(tmp)
            with mock.patch.object(metrics, "DB_PATH", path), \
                 mock.patch("builtins.print", lambda *_a, **_k: None):
                dominance = metrics.get_entity_dominance("r1")
                volatility = metrics.get_volatility_metrics("r1")
        self.assertEqual(dominance["status"], "empty_data")
        self.assertNotIn("no such column", dominance["msg"])
        self.assertEqual(volatility["status"], "insufficient_history")

    def test_the_helper_migrates_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._legacy_db(tmp)
            with storage.migrated_connection(path) as conn:
                columns = [row[1] for row in
                           conn.execute("PRAGMA table_info(serp_results)")]
                self.assertIn("query_label", columns)
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


# Y6.7 — `with sqlite3.connect(...)` commits on exit but never closes the
# handle. This chunk's guard walked the two rank-history readers it touched,
# because converting the other ~50 sites was a sweeping diff logged as an
# adjacent issue. Review chunk Y9 is that diff: every production module now
# opens the database through `db_connect.connection`, and the guard that
# covers these two files along with the rest is
# `tests/test_y9_a_handle_is_closed.py::TestNoProductionModuleLeavesAHandleOpen`.


class TestTheSpongeHelpersSeeTheConfiguredValue(unittest.TestCase):
    """Y6.8 — a default argument binds at `def` time."""

    def setUp(self):
        self.addCleanup(rga.apply_sponge_thresholds, None)

    @staticmethod
    def _rows(n, aio, ctr, prefix=""):
        return [{"query": f"{prefix}q{i}", "source_keyword": f"{prefix}q{i}",
                 "query_label": "A", "found": True,
                 "gsc_status": gsc_client.STATUS_MEASURED,
                 "has_ai_overview": aio, "clicks": 5, "impressions": 900,
                 "ctr": ctr, "position": 3.0} for i in range(n)]

    def _mixed(self):
        return (self._rows(4, True, 0.005, "aio-")
                + self._rows(4, False, 0.05, "plain-"))

    def test_a_bucket_size_applied_after_import_reaches_an_omitted_argument(self):
        rows = self._mixed()
        rga.apply_sponge_thresholds({"gsc": {"min_bucket_size": 99}})
        bands = rga.compute_sponge_effect(rows)["bands"]
        self.assertFalse(any(band["sufficient"] for band in bands), bands)

        rga.apply_sponge_thresholds({"gsc": {"min_bucket_size": 3}})
        bands = rga.compute_sponge_effect(rows)["bands"]
        self.assertTrue(any(band["sufficient"] for band in bands), bands)

    def test_a_margin_applied_after_import_reaches_an_omitted_argument(self):
        rows = self._mixed()
        sponge = rga.compute_sponge_effect(rows)

        rga.apply_sponge_thresholds({"gsc": {"reformat_ctr_margin": 0.99}})
        self.assertEqual(
            rga.find_reformat_candidates(rows, sponge, set()), [])

        rga.apply_sponge_thresholds({"gsc": {"reformat_ctr_margin": 0.25}})
        self.assertTrue(rga.find_reformat_candidates(rows, sponge, set()))

    def test_a_position_cap_applied_after_import_reaches_an_omitted_argument(self):
        rows = self._mixed()
        sponge = rga.compute_sponge_effect(rows)
        rga.apply_sponge_thresholds({"gsc": {"reformat_max_position": 1.0}})
        self.assertEqual(
            rga.find_reformat_candidates(rows, sponge, set()), [])
        rga.apply_sponge_thresholds({"gsc": {"reformat_max_position": 10.0}})
        self.assertTrue(rga.find_reformat_candidates(rows, sponge, set()))

    def test_bands_applied_after_import_reach_an_omitted_argument(self):
        rows = self._mixed()
        rga.apply_sponge_thresholds({"gsc": {"position_bands": [[1, 20]]}})
        bands = rga.compute_sponge_effect(rows)["bands"]
        self.assertEqual([band["band"] for band in bands], ["1-20"])

    def test_an_impression_floor_applied_after_import_is_counted(self):
        rows = self._mixed()
        rga.apply_sponge_thresholds({"gsc": {"min_impressions": 5000}})
        sponge = rga.compute_sponge_effect(rows)
        self.assertEqual(sponge["min_impressions"], 5000)
        self.assertEqual(sponge["queries_below_impression_floor"], len(rows))

    def test_no_sponge_default_names_a_module_constant(self):
        """The signatures resolve in the body, so the AST carries no constant
        name as a default."""
        tree = ast.parse((_REPO_ROOT / "run_gsc_analysis.py").read_text(
            encoding="utf-8"))
        for node in ast.walk(tree):
            if (not isinstance(node, ast.FunctionDef)
                    or node.name not in ("compute_sponge_effect",
                                         "find_reformat_candidates")):
                continue
            for default in node.args.defaults:
                self.assertNotIsInstance(default, ast.Name,
                                         f"{node.name} names a constant")

    def test_the_live_thresholds_cannot_be_mutated_from_outside(self):
        """Process state a caller can edit in place is state nobody owns
        (cold review of chunk Y6, finding 7)."""
        rga.apply_sponge_thresholds({"gsc": {"min_bucket_size": 7}})
        taken = rga.active_sponge_thresholds()
        taken["min_bucket_size"] = 999
        self.assertEqual(
            rga.active_sponge_thresholds()["min_bucket_size"], 7)
        applied = rga.apply_sponge_thresholds({"gsc": {"min_bucket_size": 8}})
        applied["min_bucket_size"] = 999
        self.assertEqual(
            rga.active_sponge_thresholds()["min_bucket_size"], 8)

    def test_the_loader_applies_the_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.yml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("gsc:\n  min_bucket_size: 11\n")
            rga._load_config(path)
        self.assertEqual(
            rga.active_sponge_thresholds()["min_bucket_size"], 11)


if __name__ == "__main__":
    unittest.main()
