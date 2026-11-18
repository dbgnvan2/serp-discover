"""Review chunk Y8 — a bug is not a dead network.

The paid SerpAPI fetch loop wrapped the whole attempt body in
`except Exception`, and the body included `serp_checkpoint.save` and
`link_recovery.recover_response`, which run after a response has been paid
for. A `TypeError` in either was logged as `Fetch error (attempt N)`, retried
with up to two more paid calls that failed the same way, and then filed beside
genuine network failures: three paid calls and no data for a fault retrying
cannot change (P1 in reverse, P40).

Spec: docs/review_2026-11-04/PLAN_Y8_a_bug_is_not_a_dead_network.md
"""
import json
import logging
import unittest
from unittest import mock

import requests

import config_tab_models
import http_retry
import run_gsc_analysis
import serp_fetch
import timeouts


class _Search:
    """Stands in for `serpapi.GoogleSearch`, counting the paid calls."""

    calls = 0
    outcome: object = {"organic_results": []}

    def __init__(self, params):
        pass

    def get_dict(self):
        type(self).calls += 1
        if isinstance(self.outcome, type) and issubclass(self.outcome,
                                                         BaseException):
            raise self.outcome("boom")
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _FetchCase(unittest.TestCase):

    def setUp(self):
        _Search.calls = 0
        _Search.outcome = {"organic_results": []}
        patches = [
            mock.patch.object(serp_fetch.time, "sleep", lambda s: None),
            mock.patch.object(serp_fetch.serp_checkpoint, "lookup",
                              lambda params: None),
            mock.patch.object(serp_fetch.serp_checkpoint, "save",
                              lambda params, results: None),
            mock.patch.object(http_retry, "SERPAPI_RETRY_ATTEMPTS", 3),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def fetch(self):
        return serp_fetch.fetch({"q": "x"}, timeout_seconds=5,
                                client=_Search, available=True)


class TestAFaultInThisProcessIsNotRetried(_FetchCase):

    def test_a_broken_checkpoint_write_keeps_the_paid_response(self):
        """`serp_checkpoint.save` documents its own contract — a failed write
        must not fail a paid call — and swallows the write errors it expects.
        A fault that still reaches here is a fault in the checkpoint code, and
        discarding a charged-for SERP over it would be the catch-all mistake
        this chunk removed (cold review of this chunk)."""
        with mock.patch.object(
                serp_fetch.serp_checkpoint, "save",
                mock.Mock(side_effect=TypeError("bug in save"))):
            with self.assertLogs(level="ERROR") as logs:
                out = self.fetch()
        self.assertEqual(out, {"organic_results": []})
        self.assertEqual(
            _Search.calls, 1,
            "a fault in the tool cannot be fixed by paying for two more "
            "SerpAPI calls")
        joined = "\n".join(logs.output)
        self.assertIn("INTERNAL ERROR", joined)
        self.assertIn("resumed run will pay for this call again", joined)
        self.assertNotIn("Fetch error", joined)

    def test_a_broken_link_recovery_drops_the_response(self):
        """Different event: recovery rewrites the response in place, so a
        fault part-way through leaves Google wrappers in the links, and a
        wrapper reaching the parsers makes google.com the competitor."""
        with mock.patch.object(
                serp_fetch.link_recovery, "recover_response",
                mock.Mock(side_effect=KeyError("bug in recovery"))):
            with self.assertLogs(level="ERROR") as logs:
                out, status = serp_fetch.fetch_with_status(
                    {"q": "x"}, timeout_seconds=5, client=_Search,
                    available=True)
        self.assertIsNone(out)
        self.assertEqual(status, serp_fetch.STATUS_INTERNAL_ERROR)
        self.assertEqual(_Search.calls, 1)
        self.assertIn("response is dropped", "\n".join(logs.output))

    def test_a_fault_inside_the_call_is_not_retried_either(self):
        _Search.outcome = AttributeError
        with self.assertLogs(level="ERROR") as logs:
            out = self.fetch()
        self.assertIsNone(out)
        self.assertEqual(_Search.calls, 1)
        joined = "\n".join(logs.output)
        self.assertIn("INTERNAL ERROR", joined)
        self.assertNotIn("CRITICAL ERROR", joined)


class TestATransportErrorStillSpendsTheBudget(_FetchCase):

    def test_a_timeout_is_retried_to_the_configured_budget(self):
        _Search.outcome = requests.Timeout
        with self.assertLogs(level="ERROR") as logs:
            out = self.fetch()
        self.assertIsNone(out)
        self.assertEqual(_Search.calls, 3)
        joined = "\n".join(logs.output)
        self.assertIn("Fetch error", joined)
        self.assertNotIn("INTERNAL ERROR", joined)

    def test_a_malformed_body_is_retried(self):
        _Search.outcome = json.JSONDecodeError("bad", "{", 0)
        out = self.fetch()
        self.assertIsNone(out)
        self.assertEqual(_Search.calls, 3)

    def test_the_transport_tuple_is_named_types_only(self):
        """Caught by name, so a fault in this process cannot enter through
        it: an `except Exception` here costs paid calls."""
        self.assertNotIn(Exception, serp_fetch.SERPAPI_TRANSPORT_ERRORS)
        self.assertNotIn(BaseException, serp_fetch.SERPAPI_TRANSPORT_ERRORS)
        for error in serp_fetch.SERPAPI_TRANSPORT_ERRORS:
            self.assertTrue(isinstance(error, type)
                            and issubclass(error, BaseException))


class TestThePostResponseWorkRunsOnce(_FetchCase):
    """It used to sit inside the retry loop, so a response that needed two
    attempts ran the checkpoint write and the link recovery twice."""

    def test_the_checkpoint_and_the_recovery_run_once_after_a_retry(self):
        saves, recoveries = [], []
        attempts = {"n": 0}

        class _Flaky(_Search):
            def get_dict(self):
                type(self).calls += 1
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise requests.Timeout("stalled")
                return {"organic_results": []}

        with mock.patch.object(serp_fetch.serp_checkpoint, "save",
                               lambda params, results: saves.append(1)), \
             mock.patch.object(serp_fetch.link_recovery, "recover_response",
                               lambda results: recoveries.append(1)):
            out = serp_fetch.fetch({"q": "x"}, timeout_seconds=5,
                                   client=_Flaky, available=True)
        self.assertEqual(out, {"organic_results": []})
        self.assertEqual(_Flaky.calls, 2)
        self.assertEqual(saves, [1])
        self.assertEqual(recoveries, [1])


class TestTheGuiCannotSaveARefusedBudget(unittest.TestCase):

    def test_every_positive_only_field_comes_from_the_loader_tables(self):
        """Derived from the loaders' own tables, not a second list that can
        disagree with them (P32): the retry budgets and timeout paths
        `resolve_retry_policy` drives, plus the keys `timeouts` governs."""
        expected = set()
        for section_name, keys in http_retry.BUDGET_SOURCES:
            for _, cfg_key, _ in keys:
                expected.add((section_name, cfg_key))
        for section_name, cfg_key in http_retry.TIMEOUT_SOURCES.values():
            expected.add((section_name, cfg_key))
        expected.update(timeouts.GOVERNED_FIELDS)
        self.assertEqual(config_tab_models.positive_only_fields(), expected)

    def test_the_serpapi_timeout_is_one_of_them(self):
        """The value this chunk passes into `serp_fetch.fetch` is refused at
        zero by `timeouts.seconds_from_config`, and it is in neither retry
        table, so the first population of this set missed it (P5)."""
        self.assertIn(("serpapi", "timeout_seconds"),
                      config_tab_models.positive_only_fields())

    def test_a_typed_zero_is_refused_rather_than_saved(self):
        """The Spinbox floor constrains the spin arrows only; the save path
        reads the variable's text. A typed 0 used to be written to config.yml,
        where the loader reported it to a log the operator never reads and
        used the built-in default instead (P2)."""
        for section, field in sorted(config_tab_models.positive_only_fields()):
            for typed in ("0", "-1"):
                with self.subTest(field=f"{section}.{field}", typed=typed):
                    field_type = ("int" if field.endswith("attempts")
                                  else "float")
                    current = {section: {field: 3}}
                    data, errors = config_tab_models.merge_settings_edits(
                        current, {section: {field: (typed, field_type)}})
                    self.assertTrue(
                        [e for e in errors
                         if e.startswith(f"{section}.{field}:")
                         and "greater than zero" in e], errors)
                    self.assertEqual(data[section][field], 3,
                                     "the loaded value must be kept")

    def test_a_positive_value_still_saves(self):
        data, errors = config_tab_models.merge_settings_edits(
            {"http_retry": {"attempts": 2}},
            {"http_retry": {"attempts": ("4", "int")}})
        self.assertEqual((data["http_retry"]["attempts"], errors), (4, []))

    def test_a_field_outside_the_set_may_still_be_zero(self):
        """Most settings are legitimately zero (a delay, a cap, a count)."""
        data, errors = config_tab_models.merge_settings_edits(
            {"serpapi": {"request_delay": 1}},
            {"serpapi": {"request_delay": ("0", "float")}})
        self.assertEqual((data["serpapi"]["request_delay"], errors), (0.0, []))


class TestTheTwoArtifactsCarryTheSameProvenance(unittest.TestCase):

    def setUp(self):
        self.addCleanup(run_gsc_analysis.apply_sponge_thresholds, None)

    def test_the_sidecar_records_the_thresholds_the_run_applied(self):
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"min_bucket_size": 7, "reformat_max_position": 14}})
        applied = run_gsc_analysis.active_sponge_thresholds()
        sidecar = run_gsc_analysis.build_sidecar(
            [], {"data_available": False, "bands": []}, [],
            {"gsc": {"property": "sc-domain:x.ca"}},
            "market_analysis_t_20260101_0000.json",
            ("2026-01-01", "2026-03-31"))
        self.assertEqual(sidecar["thresholds"]["min_bucket_size"], 7)
        self.assertEqual(sidecar["thresholds"]["reformat_max_position"], 14)
        self.assertEqual(sidecar["thresholds"], dict(applied))

    def test_an_explicitly_empty_mapping_is_recorded_as_empty(self):
        """`thresholds or ...` read a caller that passed nothing through as a
        caller that passed nothing at all, and filed the applied defaults
        under its name. An empty mapping is a fact about that run (P1)."""
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"min_bucket_size": 7}})
        sidecar = run_gsc_analysis.build_sidecar(
            [], {"data_available": False, "bands": []}, [],
            {"gsc": {"property": "sc-domain:x.ca"}},
            "market_analysis_t_20260101_0000.json",
            ("2026-01-01", "2026-03-31"), thresholds={})
        self.assertEqual(sidecar["thresholds"], {})

    def test_a_real_run_writes_the_same_thresholds_to_both_artifacts(self):
        """The call site is what makes the sidecar's field real: a fallback to
        the applied mapping makes passing it inert, so the criterion is that
        one run's two artifacts agree on the bands that produced its medians
        (P6)."""
        import json
        import os
        import tempfile
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
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(
                tmp, "market_analysis_topic_20260701_1200.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            report, sidecar = run_gsc_analysis.run_analysis(
                data, config, client, path, today=date(2026, 7, 4),
                db_path=None)
        self.assertEqual(sidecar["thresholds"]["min_bucket_size"], 9)
        self.assertEqual(sidecar["thresholds"]["position_bands"],
                         [(2.0, 7.0)])
        self.assertEqual(sidecar["thresholds"]["reformat_max_position"], 15.0)
        # The markdown names the same cap in its own words.
        self.assertIn("position 15 or better", report)

    def test_an_explicit_mapping_wins_over_process_state(self):
        sidecar = run_gsc_analysis.build_sidecar(
            [], {"data_available": False, "bands": []}, [],
            {"gsc": {}}, "market_analysis_t_20260101_0000.json",
            ("2026-01-01", "2026-03-31"),
            thresholds={"min_bucket_size": 99})
        self.assertEqual(sidecar["thresholds"], {"min_bucket_size": 99})


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
