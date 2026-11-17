"""D2 — a value that was never measured is never written down as a zero.

One fault, nine findings: a DA that no provider holds was coerced to 0, and
a 0 is a measurement. It dragged the competitor mean down, widened the
client's apparent gap, flipped verdicts from Moderate to Low and queued paid
Maps fetches off the flipped verdict. The client's own DA came from
``config.yml`` on one provider's scale and was subtracted from a mean on
another's.

Spec: docs/review_2026-11-04/PLAN_D2_null_is_not_zero.md (D2a.1-D2a.15)
Findings: D-C-03, D-C-04, D-M-02, D-M-05, D-M-08.

All external calls are mocked; no API keys required.
"""

import json
import logging
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

import dataforseo_client
import feasibility
import moz_client
import play_routing
import shared_config


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _src(name):
    return (_REPO_ROOT / name).read_text(encoding="utf-8")


class _SourceGuard:
    """Mixin: assert on source text without dumping the file on failure."""

    def assertInSource(self, needle, name):
        self.assertTrue(needle in _src(name),
                        f"{needle!r} is missing from {name}")

    def assertNotInSource(self, needle, name):
        self.assertFalse(needle in _src(name),
                         f"{needle!r} is still in {name}")


class _FakeResponse:
    """Minimal `requests.Response` stand-in for the client's happy path."""

    ok = True
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _dfs_payload(items):
    return {"tasks": [{"status_code": 20000,
                       "result": [{"items": items}]}]}


class TestDataForSEO(unittest.TestCase):
    """D2a.1/D2a.2/D2a.4 — the provider that fabricated the zeros."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "cache.sqlite")
        self.addCleanup(self._tmp.cleanup)
        env = {"DATAFORSEO_LOGIN": "l", "DATAFORSEO_PASSWORD": "p"}
        with mock.patch.dict(os.environ, env):
            self.client = dataforseo_client.DataForSEOClient(
                db_path=self.db, cache_ttl_days=30)

    def _fetch(self, items, urls):
        with mock.patch.object(dataforseo_client, "_post_with_transient_retry",
                               return_value=_FakeResponse(_dfs_payload(items))):
            return self.client.get_domain_metrics(urls)

    def test_d2a1_absent_rank_is_none_not_zero(self):
        """A domain DataForSEO holds no rank for has da None, never 0."""
        result = self._fetch(
            [{"target": "scored.example", "rank": 41},
             {"target": "unscored.example"},
             {"target": "null.example", "rank": None}],
            ["https://scored.example/a", "https://unscored.example/b",
             "https://null.example/c"],
        )
        self.assertEqual(result["https://scored.example/a"]["da"], 41)
        self.assertIsNone(result["https://unscored.example/b"]["da"])
        self.assertIsNone(result["https://null.example/c"]["da"])
        # And the absence is not a 0 anywhere in the row.
        self.assertNotIn(0, [v["da"] for v in result.values()])
        self.assertNotIn(0, [v["pa"] for v in result.values()])

    def test_d2a2_a_none_is_cached_as_absence_not_as_zero(self):
        """NULL in the cache, and the domain is not refetched inside the TTL."""
        self._fetch([{"target": "unscored.example"}],
                    ["https://unscored.example/b"])
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                f"SELECT domain, domain_authority, page_authority "
                f"FROM {dataforseo_client.CACHE_TABLE}").fetchall()
        self.assertEqual(rows, [("unscored.example", None, None)])

        # The row's presence says "asked and answered": a second call must
        # serve from cache and POST nothing.
        with mock.patch.object(dataforseo_client, "_post_with_transient_retry") as post:
            again = self.client.get_domain_metrics(["https://unscored.example/b"])
        post.assert_not_called()
        self.assertIsNone(again["https://unscored.example/b"]["da"])

    def test_d2a4_null_rank_absent_from_result_and_cache(self):
        """The workplan's own test: no 0 reaches either side."""
        self._fetch([{"target": "a.example", "rank": 55},
                     {"target": "b.example", "rank": None}],
                    ["https://a.example/1", "https://b.example/2"])
        with sqlite3.connect(self.db) as conn:
            stored = dict(conn.execute(
                f"SELECT domain, domain_authority "
                f"FROM {dataforseo_client.CACHE_TABLE}").fetchall())
        self.assertEqual(stored, {"a.example": 55, "b.example": None})

    def test_d2a1_a_true_zero_rank_is_kept(self):
        """0 is still a measurement when the provider actually sent one."""
        result = self._fetch([{"target": "zero.example", "rank": 0}],
                             ["https://zero.example/x"])
        self.assertEqual(result["https://zero.example/x"]["da"], 0)


class TestMoz(_SourceGuard, unittest.TestCase):
    """D2a.3 — the same fault in the other provider."""

    def _parse(self, metrics):
        """_parse_site_metrics on a client built without credentials or I/O."""
        client = object.__new__(moz_client.MozClient)
        client._link_count_fields = []
        return client._parse_site_metrics(metrics, "2026-11-16T00:00:00+00:00")

    def test_d2a3_absent_authority_is_none(self):
        parsed = self._parse({"spam_score": 2})
        self.assertIsNone(parsed["da"])
        self.assertIsNone(parsed["pa"])

    def test_d2a3_a_present_authority_is_kept(self):
        parsed = self._parse({"domain_authority": 35, "page_authority": 28})
        self.assertEqual((parsed["da"], parsed["pa"]), (35, 28))

    def test_d2a3_a_true_zero_authority_is_kept(self):
        parsed = self._parse({"domain_authority": 0})
        self.assertEqual(parsed["da"], 0)

    def test_d2a3_the_docstring_no_longer_claims_or_zero(self):
        """The `or 0` was a recorded decision, so reversing it is recorded too.

        Source guard: the docstring documented the coercion as deliberate,
        citing the Moz upgrade's decision gate D-3. A reader who found the
        old text would reinstate the bug, and a spec whose binding gate still
        reads "no scoring change" contradicts the code (CLAUDE.md: a
        behaviour change updates every document that describes it).
        """
        self.assertNotInSource('int(metrics.get("domain_authority") or 0)',
                               "moz_client.py")
        self.assertNotInSource('int(metrics.get("page_authority") or 0)',
                               "moz_client.py")
        self.assertInSource("review chunk D2 reverses that decision",
                            "moz_client.py")
        self.assertInSource("D-3, partly reversed by review chunk D2",
                            "moz_api_upgrade_spec_v1.md")
        self.assertInSource("MIN_DA_FOR_VERDICT",
                            "moz_api_upgrade_spec_v1.md")

    def test_d2a3_booleans_are_not_authorities(self):
        """`isinstance(True, int)` is True in Python, so exclude it."""
        parsed = self._parse({"domain_authority": True})
        self.assertIsNone(parsed["da"])


class TestCoverageCounts(_SourceGuard, unittest.TestCase):
    """D2a.6/D2a.7 — the denominator travels with the mean (P2)."""

    def _window(self, das_by_url, urls=None, client=""):
        urls = urls or list(das_by_url)
        return feasibility.competitor_da_window(
            urls, lambda u: das_by_url.get(u), client_domain=client)

    def test_d2a6_counts_reconcile_with_the_window(self):
        window = self._window({f"https://c{i}.example/": (40 + i if i < 7 else None)
                               for i in range(10)})
        feas = feasibility.compute_feasibility(35, window)
        self.assertEqual(feas["da_count"], 7)
        self.assertEqual(feas["da_missing"], 3)
        self.assertEqual(feas["da_count"] + feas["da_missing"], window.window)
        self.assertEqual(window.window, 10)

    def test_d2a6_a_row_built_from_a_plain_list_still_reconciles(self):
        """compute_feasibility also takes a bare list (its old signature)."""
        feas = feasibility.compute_feasibility(35, [40, 50, 60, 44, 48])
        self.assertEqual((feas["da_count"], feas["da_missing"]), (5, 0))

    def test_d2a7_four_measured_domains_is_not_a_verdict(self):
        """Below MIN_DA_FOR_VERDICT the mean is reported, the verdict is not."""
        window = self._window({f"https://c{i}.example/": (90 if i < 4 else None)
                               for i in range(10)})
        feas = feasibility.compute_feasibility(20, window)
        self.assertEqual(feas["feasibility_status"], "Not Measured")
        # The numbers are still published — withholding them would hide that
        # anything was measured at all (P2).
        self.assertEqual(feas["avg_serp_da"], 90.0)
        self.assertEqual(feas["gap"], 70.0)
        self.assertEqual((feas["da_count"], feas["da_missing"]), (4, 6))

    def test_d2a7_five_measured_domains_is_a_verdict(self):
        window = self._window({f"https://c{i}.example/": (90 if i < 5 else None)
                               for i in range(10)})
        feas = feasibility.compute_feasibility(20, window)
        self.assertEqual(feas["feasibility_status"], "Low Feasibility")

    def test_d2a7_the_minimum_is_config_not_a_literal(self):
        """`technical.min_da_for_verdict` is read, not hardcoded.

        Asserting the value equals 5 pinned the opposite of what the name
        claims: it passes whether or not the config key is ever consulted
        (finding F10). Reload the module against a config that sets a
        different minimum and check the module took it.
        """
        self.assertInSource('tech.get("min_da_for_verdict"', "feasibility.py")

        import importlib
        with tempfile.TemporaryDirectory() as tmp:
            # Named via shared_config, not a second copy of the literal
            # (tests/test_shared_config.py::TestSinglePathOwner).
            path = os.path.join(tmp, os.path.basename(
                shared_config.shared_config_path()))
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"technical": {"min_da_for_verdict": 3}}, fh)
            with mock.patch.dict(os.environ, {shared_config.ENV_VAR: path}):
                reloaded = importlib.reload(feasibility)
                try:
                    self.assertEqual(reloaded.MIN_DA_FOR_VERDICT, 3)
                    self.assertEqual(
                        reloaded.load_thresholds()[3], 3,
                        "load_thresholds must return the configured minimum")
                    # And the threshold is what gates the verdict: three
                    # measured domains now earn one.
                    feas = reloaded.compute_feasibility(
                        35, reloaded.DAWindow(das=[60, 60, 60], measured=3,
                                              missing=7, window=10))
                    self.assertNotEqual(feas["feasibility_status"],
                                        reloaded.NOT_MEASURED)
                finally:
                    importlib.reload(feasibility)

    def test_d2a6_an_unscored_domain_is_not_averaged_as_zero(self):
        """The arithmetic the whole chunk exists to fix (D-C-04/D-M-02).

        ``gap = avg_serp_da - client_da``, so zeros drag the mean down and
        *shrink* the gap: a keyword held by DA-90 directories read as
        winnable because the five domains nobody scored were counted as
        having no authority.
        """
        das = {f"https://c{i}.example/": (90 if i < 5 else None)
               for i in range(10)}
        honest = feasibility.compute_feasibility(35, self._window(das))
        zeroed = feasibility.compute_feasibility(
            35, [v if v is not None else 0 for v in das.values()])
        self.assertEqual(honest["avg_serp_da"], 90.0)
        self.assertEqual(zeroed["avg_serp_da"], 45.0)
        self.assertEqual(honest["gap"], 55.0)
        self.assertEqual(zeroed["gap"], 10.0)
        self.assertEqual(honest["feasibility_status"], "Low Feasibility")
        self.assertEqual(zeroed["feasibility_status"], "Moderate Feasibility")

    def test_d2a9_coverage_phrase_states_the_denominator(self):
        self.assertEqual(feasibility.coverage_phrase(7, 3),
                         "mean of 7 of 10 ranking domains (3 unscored)")
        self.assertEqual(feasibility.coverage_phrase(10, 0),
                         "mean of all 10 ranking domains")
        self.assertEqual(feasibility.coverage_phrase(0, 4),
                         "no ranking domain scored")
        self.assertEqual(feasibility.coverage_phrase(7, 3, short=True),
                         "7/10 (3 unscored)")

    def test_d2a9_a_missing_messages_file_does_not_abort(self):
        """The words are presentation; losing them must not cost the run."""
        with mock.patch.object(feasibility, "MESSAGES_FILE",
                               "/nonexistent/feasibility_messages.yml), "), \
             mock.patch.object(feasibility, "_MESSAGES_CACHE", None):
            with self.assertLogs(level=logging.WARNING):
                phrase = feasibility.coverage_phrase(7, 3)
            self.assertIn("7", phrase)
            self.assertEqual(feasibility.status_label("Not Measured"),
                             "Not Measured")
        feasibility._MESSAGES_CACHE = None


class TestOneLabel(_SourceGuard, unittest.TestCase):
    """D2a.10 — one label for one state."""

    SOURCES = ("feasibility.py", "run_feasibility.py", "serp_audit.py",
               "generate_insight_report.py", "play_routing.py",
               "moz_client.py", "dataforseo_client.py")

    def test_d2a10_no_second_label_for_an_unmeasured_verdict(self):
        for name in self.SOURCES:
            self.assertNotInSource("No DA Data", name)

    def test_d2a10_the_status_icon_map_has_one_home(self):
        """Four Python copies of the map are how the two labels diverged."""
        for name in ("run_feasibility.py", "serp_audit.py",
                     "generate_insight_report.py"):
            self.assertNotInSource("STATUS_ICONS", name)
        self.assertInSource("statuses:", "feasibility_messages.yml")

    def test_d2a10_every_configured_status_is_one_feasibility_returns(self):
        configured = set((feasibility.load_messages().get("statuses") or {}))
        self.assertEqual(
            configured,
            {"High Feasibility", "Moderate Feasibility", "Low Feasibility",
             "Not Measured"})


class TestPivotGate(_SourceGuard, unittest.TestCase):
    """D2a.8 — an unmeasured keyword queues no paid fetch."""

    def test_d2a8_no_pivot_job_without_a_gap(self):
        self.assertInSource('feas["gap"] is not None', "run_feasibility.py")
        self.assertNotInSource("da_data_available", "run_feasibility.py")

    def test_d2a8_an_unmeasured_keyword_has_no_gap_to_pivot_on(self):
        feas = feasibility.compute_feasibility(
            None, feasibility.DAWindow([], 0, 10, 10))
        self.assertIsNone(feas["gap"])
        self.assertEqual(feas["feasibility_status"], "Not Measured")

    def test_d2a8_serp_audit_gates_its_pivot_queue_on_a_verdict(self):
        self.assertInSource('feas["feasibility_status"] == "Low Feasibility"',
                            "serp_audit.py")


class TestPerKeywordAvailability(_SourceGuard, unittest.TestCase):
    """D2a.5 — availability is a fact about a keyword, not about the run."""

    def test_d2a5_one_measured_keyword_does_not_score_the_unmeasured_ones(self):
        measured = feasibility.compute_feasibility(
            35, feasibility.DAWindow([50] * 6, 6, 0, 6))
        unmeasured = feasibility.compute_feasibility(
            35, feasibility.DAWindow([], 0, 8, 8))
        self.assertEqual(measured["feasibility_status"], "Moderate Feasibility")
        self.assertEqual(unmeasured["feasibility_status"], "Not Measured")
        self.assertIsNone(unmeasured["avg_serp_da"])

    def test_d2a5_one_unmeasured_keyword_does_not_blank_the_run(self):
        """The run-level flag is gone, so one hole cannot blank the rest."""
        self.assertNotInSource("da_data_available", "run_feasibility.py")


class TestClientProvenance(_SourceGuard, unittest.TestCase):
    """D2a.12-D2a.15 — both sides of the gap off one provider's scale."""

    def test_d2a12_the_client_da_comes_from_the_provider(self):
        da, source = feasibility.resolve_client_da(
            "livingsystems.ca",
            lambda d: {"da": 19, "fetched_at": "2026-11-16T09:00:00+00:00"},
            "dataforseo", config_value=35)
        self.assertEqual(da, 19)
        self.assertEqual(source, "dataforseo@2026-11-16")

    def test_d2a12_the_client_rides_in_the_competitors_batch(self):
        """One batch is what makes the two sides the same scale."""
        batch = feasibility.with_client_url(
            ["https://comp1.example/a"], "https://livingsystems.ca")
        self.assertEqual(batch, ["https://comp1.example/a",
                                 "https://livingsystems.ca"])
        # Idempotent: the client is not fetched twice.
        self.assertEqual(feasibility.with_client_url(batch,
                                                     "https://livingsystems.ca"),
                         batch)
        for name in ("serp_audit.py", "run_feasibility.py"):
            self.assertInSource("with_client_url", name)

    def test_d2a12_resolution_reads_the_batch_by_domain(self):
        da, source = feasibility.client_da_from_batch(
            {"https://www.livingsystems.ca/": {"da": 22,
                                               "fetched_at": "2026-11-16"}},
            "livingsystems.ca", "moz", config_value=35)
        self.assertEqual(da, 22)
        self.assertEqual(source, "moz@2026-11-16")

    def test_d2a13_config_is_an_override_and_is_logged(self):
        logger = mock.Mock()
        da, source = feasibility.resolve_client_da(
            "livingsystems.ca", lambda d: {}, "moz",
            config_value=35, override=40, log_info=logger)
        self.assertEqual((da, source), (40, "operator override"))
        logged = " ".join(str(a) for a in logger.call_args[0])
        self.assertIn("40", logged)
        self.assertIn("moz", logged)
        self.assertIn("35", logged)

    def test_d2a13_a_measured_value_wins_over_config_and_says_so(self):
        logger = mock.Mock()
        da, _ = feasibility.resolve_client_da(
            "livingsystems.ca",
            lambda d: {"da": 19, "fetched_at": "2026-11-16T00:00:00+00:00"},
            "dataforseo", config_value=35, log_info=logger)
        self.assertEqual(da, 19)
        logged = " ".join(str(a) for a in logger.call_args[0])
        self.assertIn("19", logged)
        self.assertIn("35", logged)
        self.assertIn("2026-11-16", logged)

    def test_d2a13_config_is_a_labelled_fallback_when_the_provider_is_silent(self):
        da, source = feasibility.resolve_client_da(
            "livingsystems.ca", lambda d: {}, "moz", config_value=35)
        self.assertEqual(da, 35)
        self.assertEqual(source, "config fallback (unmeasured, moz)")

    def test_d2a14_rows_are_tagged(self):
        for name in ("serp_audit.py", "run_feasibility.py"):
            self.assertInSource('"da_provider"', name)
            self.assertInSource('"client_da_source"', name)

    def test_d2a14_no_cross_provider_trend(self):
        """A config DA on one scale minus a mean on another is not a gap.

        The scales are genuinely different: the code's own worked example
        puts this client at 19 on DataForSEO against the 35 in config.yml.
        """
        measured = feasibility.resolve_client_da(
            "livingsystems.ca",
            lambda d: {"da": 19, "fetched_at": "2026-11-16"},
            "dataforseo", config_value=35)
        fallback = feasibility.resolve_client_da(
            "livingsystems.ca", lambda d: {}, "dataforseo", config_value=35)
        self.assertNotEqual(measured[1], fallback[1],
                            "a measured value and a config value must not "
                            "carry the same provenance")
        self.assertIn("config", fallback[1])

    def test_d2a15_no_provider_is_not_a_measurement(self):
        logger = mock.Mock()
        da, source = feasibility.resolve_client_da(
            "livingsystems.ca", lambda d: {}, "none",
            config_value=35, log_warning=logger)
        self.assertIsNone(da)
        self.assertEqual(source, "not measured (no provider)")
        self.assertIn("35", " ".join(str(a) for a in logger.call_args[0]))

    def test_d2a15_an_unmeasured_client_gives_no_verdict(self):
        feas = feasibility.compute_feasibility(
            None, feasibility.DAWindow([50] * 8, 8, 0, 8))
        self.assertEqual(feas["feasibility_status"], "Not Measured")
        self.assertIsNone(feas["gap"])

    def test_d2a15_and_the_row_says_why(self):
        text = feasibility.no_measurement_text(
            "none", feasibility.DAWindow([], 0, 0, 0))
        self.assertIn("DATAFORSEO_LOGIN", text)
        thin = feasibility.no_measurement_text(
            "moz", feasibility.DAWindow([50] * 3, 3, 7, 10))
        self.assertIn("3", thin)
        self.assertIn("10", thin)
        self.assertIn("moz", thin)

    def test_d2a15_a_config_da_is_marked_as_unmeasured_where_it_renders(self):
        self.assertEqual(
            feasibility.client_da_cell(35, "config fallback (unmeasured, moz)"),
            "35 (config, not measured by moz)")
        self.assertEqual(feasibility.client_da_cell(19, "dataforseo@2026-11-16"),
                         "19")
        self.assertEqual(feasibility.client_da_cell(None,
                                                    "not measured (no provider)"),
                         "not measured")


class TestRendering(unittest.TestCase):
    """D2a.9 — the coverage is printed beside every mean it qualifies.

    The plan named these tests in `tests/test_markdown_rendering.py` and a
    `test_report_sections.py`. The first drives archived-run fixtures that
    are gitignored and skipped without a real run, and the second does not
    exist, so both land here with the rest of D2a and the plan records it.
    """

    CONFIG = {"feasibility": {"client_da": 35,
                              "neighborhoods": ["Lonsdale"],
                              "non_profit_location": "North Vancouver"},
              "analysis_report": {"client_domain": "livingsystems.ca"}}

    def _row(self, **over):
        row = {"Keyword": "couples counselling", "Query_Label": "A",
               "client_da": 35, "avg_serp_da": 60.0, "gap": 25.0,
               "feasibility_score": 0.2,
               "feasibility_status": "Low Feasibility",
               "da_count": 7, "da_missing": 3, "da_provider": "moz",
               "client_da_source": "moz@2026-11-16",
               "pivot_status": "No pivot — informational",
               "suggested_keyword": None, "all_variants": [],
               "Source_Keyword": "couples counselling"}
        row.update(over)
        return row

    def _feasibility_md(self, row):
        import run_feasibility
        return run_feasibility.generate_feasibility_report(
            [row], self.CONFIG, "market_analysis_x.json", keyword_profiles={})

    def _market_md(self, row):
        import generate_insight_report
        return generate_insight_report.generate_report(
            {"overview": [{"Run_ID": "r1", "Created_At": "2026-11-16"}],
             "keyword_feasibility": [row], "keyword_profiles": {}})

    def _row_line(self, report, keyword="couples counselling"):
        return next(line for line in report.splitlines()
                    if line.startswith(f"| {keyword} |"))

    def test_d2a9_coverage_is_rendered(self):
        """feasibility_*.md states the denominator beside the mean."""
        report = self._feasibility_md(self._row())
        self.assertIn("DA Coverage", report)
        self.assertIn("7/10 (3 unscored)", self._row_line(report))

    def test_d2a9_section_5c_states_coverage(self):
        report = self._market_md(self._row())
        self.assertIn("DA Coverage", report)
        self.assertIn("7/10 (3 unscored)", self._row_line(report))

    def test_d2a9_complete_coverage_says_so_without_a_caveat(self):
        for report in (self._feasibility_md(self._row(da_count=10, da_missing=0)),
                       self._market_md(self._row(da_count=10, da_missing=0))):
            line = self._row_line(report)
            self.assertIn("10/10", line)
            self.assertNotIn("unscored", line)

    def test_d2a9_a_config_client_da_is_marked_in_both_reports(self):
        row = self._row(client_da_source="config fallback (unmeasured, moz)")
        for report in (self._feasibility_md(row), self._market_md(row)):
            self.assertIn("config, not measured by moz", self._row_line(report))

    def test_d2a9_an_unmeasured_row_renders_without_a_verdict(self):
        row = self._row(feasibility_status="Not Measured", avg_serp_da=None,
                        gap=None, feasibility_score=None,
                        da_count=0, da_missing=10,
                        client_da=None,
                        client_da_source="not measured (no provider)")
        for report in (self._feasibility_md(row), self._market_md(row)):
            line = self._row_line(report)
            self.assertIn("Not measured", line)
            self.assertIn("not measured", line)
            self.assertIn("0/10", line)
            # No fabricated figures in the numeric cells.
            self.assertNotIn("+0", line)

    def test_d2a9_a_legacy_row_without_the_counts_states_it_is_unknown(self):
        """Old market_analysis_*.json has no da_count — absent, not 0 of 0.

        "does not crash" was the whole assertion, and it passed while the
        row rendered "0/10" beside a real mean and a bare config client DA
        (finding F4). Absent coverage is a third state and says so.
        """
        row = self._row()
        del row["da_count"], row["da_missing"], row["client_da_source"]
        for report in (self._feasibility_md(row), self._market_md(row)):
            self.assertIn("couples counselling", report)
            line = self._row_line(report)
            self.assertNotIn("0/10", line)
            self.assertNotIn("/10", line,
                             "an unrecorded denominator must not be invented")
            self.assertIn("—", line)
            # The client DA is 35 with no provenance: it must not read as a
            # measurement.
            self.assertNotIn("| 35 |", line, line)

    def test_d2a9_absent_coverage_reads_as_unknown_in_prose(self):
        """The long form says so too, not just the table cell."""
        self.assertEqual(feasibility.coverage_phrase(None, None),
                         "coverage not recorded for this run")
        self.assertEqual(feasibility.coverage_phrase(7, None, short=True), "—")


class TestPlayRouting(unittest.TestCase):
    """D2a.11 — no play is chosen from a verdict that was never measured."""

    def test_d2a11_unmeasured_routes_to_unknown(self):
        self.assertEqual(play_routing._normalize_feasibility("Not Measured"),
                         "unknown")

    def test_d2a11_no_configured_label_collides_with_a_routing_token(self):
        """A rename of "Not Measured" must not start with low/moderate/high.

        The fall-through is a prefix test, so a label like "Low coverage"
        would route as a measured `low` and pick an extraction play from no
        data at all.
        """
        expected = {"High Feasibility": "high",
                    "Moderate Feasibility": "moderate",
                    "Low Feasibility": "low",
                    "Not Measured": "unknown"}
        for label in (feasibility.load_messages().get("statuses") or {}):
            self.assertEqual(play_routing._normalize_feasibility(label),
                             expected[label], label)

    def test_d2a11_unknown_feasibility_is_not_available_data(self):
        verdict = play_routing.compute_recommended_play(
            {"serp_intent": {"primary_intent": "commercial"},
             "has_ai_overview": True},
            feasibility_row={"feasibility_status": "Not Measured"},
            keyword="couples counselling North Vancouver",
        )
        self.assertFalse(verdict["data_available"]["feasibility"])
        self.assertEqual(verdict["evidence"]["inputs_used"]["feasibility"],
                         "unknown")
        self.assertIn("unavailable", (verdict.get("note") or "").lower())

    def test_d2a11_a_measured_verdict_is_available_data(self):
        verdict = play_routing.compute_recommended_play(
            {"serp_intent": {"primary_intent": "commercial"},
             "has_ai_overview": True},
            feasibility_row={"feasibility_status": "Low Feasibility"},
            keyword="couples counselling North Vancouver",
        )
        self.assertTrue(verdict["data_available"]["feasibility"])


if __name__ == "__main__":
    unittest.main()


class TestWindowIsSlicedBeforeFiltering(_SourceGuard, unittest.TestCase):
    """Review finding F1 — filter-then-slice both widens and hides the window.

    Dropping unusable rows first slides rank 11 into a set every output calls
    "the top 10", AND throws away the denominator: a 6-of-10 window published
    ``da_missing=0`` beside "mean of all 6 ranking domains". Three producers
    had the same fault.
    """

    def _rows(self):
        # Ranks 1-3 unresolvable, 4-14 usable.
        return [{"Rank": i, "Link": "N/A" if i <= 3 else f"https://r{i}.ca",
                 "Query_Label": "A", "Source_Keyword": "kw"}
                for i in range(1, 15)]

    def test_f1_url_window_counts_the_holes_it_cannot_resolve(self):
        window = feasibility.url_window(self._rows())
        self.assertEqual(window.window, feasibility.TOP_N_FOR_FEASIBILITY)
        self.assertEqual(window.unresolved, 3)
        self.assertNotIn("https://r11.ca", window.urls)

    def test_f1_the_holes_become_missing_coverage_not_zero_competitors(self):
        window = feasibility.url_window(self._rows())
        das = feasibility.competitor_da_window(window, lambda u: 60)
        self.assertEqual((das.measured, das.missing, das.window), (7, 3, 10))
        # And the mean is over the 7, with the 10 printed beside it.
        feas = feasibility.compute_feasibility(35, das)
        self.assertEqual(feas["avg_serp_da"], 60.0)
        self.assertEqual((feas["da_count"], feas["da_missing"]), (7, 3))
        self.assertIn("7 of 10", feasibility.coverage_phrase(7, 3))

    def test_f1_a_window_is_not_sliced_twice(self):
        """Passing an already-sliced URLWindow must not re-slice or re-count."""
        window = feasibility.url_window(self._rows())
        once = feasibility.competitor_da_window(window, lambda u: 60)
        twice = feasibility.competitor_da_window(
            feasibility.URLWindow(urls=window.urls, unresolved=0, window=10),
            lambda u: 60)
        self.assertEqual(once.measured, twice.measured)
        self.assertEqual((once.missing, twice.missing), (3, 0))

    def test_f1_the_standalone_producer_slices_first_too(self):
        import run_feasibility
        windows = run_feasibility._get_organic_urls_by_keyword(
            {"organic_results": self._rows()})
        window = windows["kw"]
        self.assertEqual(window.window, feasibility.TOP_N_FOR_FEASIBILITY)
        self.assertEqual(window.unresolved, 3)
        self.assertNotIn("https://r11.ca", window.urls)

    def test_f1_an_na_link_is_a_hole_in_every_producer(self):
        """One definition of "no URL here": "N/A" is not a target.

        `_get_organic_urls_by_keyword` tested only for emptiness, so an
        "N/A" went to the provider as a target and the position was counted
        as resolved.
        """
        self.assertFalse(feasibility.usable_url("N/A"))
        self.assertFalse(feasibility.usable_url(""))
        self.assertTrue(feasibility.usable_url("https://r1.ca"))
        self.assertInSource("usable_url", "run_feasibility.py")

    def test_f1_the_fetch_batch_carries_urls_not_the_window(self):
        """with_client_url must receive the URLs, never the URLWindow.

        A URLWindow handed to it would put the hole counts into the list of
        targets sent to the provider.
        """
        window = feasibility.url_window(self._rows())
        batch = feasibility.with_client_url(window.urls, "https://client.ca")
        self.assertTrue(all(isinstance(u, str) for u in batch), batch)
        self.assertIn("https://client.ca", batch)


class TestNoVerdictIsNotAVerdict(_SourceGuard, unittest.TestCase):
    """Review findings F2/F3 — an unmeasured keyword gets neither a pivot
    recommendation nor silence."""

    def test_f2_the_pivot_generator_refuses_to_call_it_feasible(self):
        result = feasibility.generate_hyper_local_pivot(
            "couples counselling", "North Vancouver",
            {"status": feasibility.NOT_MEASURED, "avg_competitor_da": 12.0},
            ["Lonsdale"])
        self.assertIsNone(result["suggested_keyword"])
        self.assertNotIn("feasible", result["strategy"].lower())
        self.assertIn("no feasibility verdict", result["strategy"].lower())

    def test_f2_a_thin_window_has_a_gap_so_the_gate_is_the_status(self):
        """Gating on `gap is None` let a thin window through — it has a gap."""
        feas = feasibility.compute_feasibility(
            35, feasibility.DAWindow(das=[60, 60], measured=2, missing=8,
                                     window=10))
        self.assertEqual(feas["feasibility_status"], feasibility.NOT_MEASURED)
        self.assertIsNotNone(feas["gap"])
        self.assertInSource(
            'feas["feasibility_status"] == feasibility_module.NOT_MEASURED',
            "run_feasibility.py")

    def test_f3_the_reason_has_its_own_field_not_strategy(self):
        """`strategy` renders only in the Low Feasibility block, so the
        reason written there was never shown."""
        self.assertInSource('"no_measurement_reason"', "run_feasibility.py")
        self.assertInSource('row.get("no_measurement_reason")',
                            "run_feasibility.py")
        self.assertInSource('row.get("no_measurement_reason")',
                            "generate_insight_report.py")

    def test_f3_both_reports_render_the_reason(self):
        row = {"Keyword": "couples counselling", "Query_Label": "A",
               "client_da": None, "avg_serp_da": 60.0, "gap": None,
               "feasibility_score": None,
               "feasibility_status": feasibility.NOT_MEASURED,
               "da_count": 2, "da_missing": 8, "da_provider": "moz",
               "client_da_source": "not measured (no provider)",
               "no_measurement_reason":
                   "Only 2 of 10 ranking domain(s) have a DA record from moz, "
                   "below the 5 a verdict needs.",
               "pivot_status": "Stay the course", "suggested_keyword": None,
               "all_variants": [], "strategy": "",
               "Source_Keyword": "couples counselling"}
        import run_feasibility
        import generate_insight_report
        feas_md = run_feasibility.generate_feasibility_report(
            [row], TestRendering.CONFIG, "market_analysis_x.json",
            keyword_profiles={})
        market_md = generate_insight_report.generate_report(
            {"overview": [{"Run_ID": "r1", "Created_At": "2026-11-16"}],
             "keyword_feasibility": [row], "keyword_profiles": {}})
        for report in (feas_md, market_md):
            self.assertIn("Not measured — why", report)
            self.assertIn("below the 5 a verdict needs", report)


class TestProviderBoundaryCountsTheNulls(_SourceGuard, unittest.TestCase):
    """Review finding F5 — `len(result)` counts records, not measurements."""

    def test_f5_batch_coverage_separates_records_from_figures(self):
        cov = feasibility.batch_coverage(
            {"a": {"da": 5}, "b": {"da": None}}, asked=["a", "b", "c"])
        self.assertEqual((cov.measured, cov.records, cov.asked), (1, 2, 3))
        self.assertEqual(cov.unmeasured, 1)

    def test_f5_a_batch_of_pure_absence_is_not_an_empty_batch(self):
        cov = feasibility.batch_coverage({"a": {"da": None}})
        self.assertTrue(cov.records)
        self.assertFalse(cov.measured)

    def test_f5_the_run_gates_its_warning_on_measurements(self):
        self.assertInSource("if not cov.measured:", "run_feasibility.py")
        self.assertNotInSource("if not da_metrics:", "run_feasibility.py")

    def test_f5_both_providers_report_their_own_coverage(self):
        for name in ("moz_client.py", "dataforseo_client.py"):
            self.assertInSource("batch_coverage", name)


class TestAbsenceExpiresSooner(unittest.TestCase):
    """Review finding F6 — a cached absence is not a 30-day fact."""

    def _db(self, tmp):
        return os.path.join(tmp, "cache.db")

    def test_f6_a_cached_null_is_re_asked_before_a_cached_figure(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ,
                                {"DATAFORSEO_LOGIN": "x",
                                 "DATAFORSEO_PASSWORD": "y"}):
            client = dataforseo_client.DataForSEOClient(
                db_path=self._db(tmp), cache_ttl_days=30,
                negative_cache_ttl_days=7)
            stale = "2026-11-01T00:00:00+00:00"   # 15 days old
            with mock.patch(
                    "dataforseo_client.datetime") as dt:
                dt.now.return_value = dateutil = __import__(
                    "datetime").datetime.fromisoformat(
                        "2026-11-16T00:00:00+00:00")
                client._cache_store({
                    "measured.ca": {"da": 40, "pa": 40, "fetched_at": stale},
                    "absent.ca": {"da": None, "pa": None,
                                  "fetched_at": stale},
                })
                cached, to_fetch = client._cache_lookup(
                    ["measured.ca", "absent.ca"])
            self.assertIn("measured.ca", cached)
            self.assertEqual(to_fetch, ["absent.ca"],
                             "a 15-day-old absence must be asked again")

    def test_f6_the_negative_ttl_never_exceeds_the_positive_one(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ,
                                {"DATAFORSEO_LOGIN": "x",
                                 "DATAFORSEO_PASSWORD": "y"}):
            client = dataforseo_client.DataForSEOClient(
                db_path=self._db(tmp), cache_ttl_days=3,
                negative_cache_ttl_days=30)
            self.assertEqual(client._negative_cache_ttl.days, 3)

    def test_f6_moz_maps_the_config_key(self):
        with mock.patch.dict(os.environ, {"MOZ_TOKEN": "t"}):
            client = moz_client.MozClient.from_config(
                {"moz": {"cache_ttl_days": 30,
                         "negative_cache_ttl_days": 2}})
        self.assertEqual(client._negative_cache_ttl.days, 2)

    def test_f6_the_premise_records_where_it_came_from(self):
        """The null encoding is unverified against a live response."""
        src = _src("dataforseo_client.py")
        self.assertIn("probe_03_dataforseo_null_rank.py", src)
        self.assertIn("unverified", src)


class TestThinCoverageMakesNoClaim(unittest.TestCase):
    """Review finding F7 — no direction, and no recommendation, off a mean
    the status line refuses to read."""

    PROFILE = {"serp_intent": {"primary_intent": "informational",
                               "confidence": "high", "is_mixed": False},
               "has_ai_overview": False, "has_local_pack": False}

    def test_f7_an_unmeasured_row_withholds_the_direction(self):
        import generate_insight_report as gir
        why = gir._why_this_keyword(
            {"feasibility_status": feasibility.NOT_MEASURED,
             "client_da": 35, "avg_serp_da": 12.0, "gap": -23.0,
             "da_count": 2, "da_missing": 8},
            self.PROFILE)
        self.assertNotIn("stronger", why)
        self.assertIn("2 of 10", why)

    def test_f7_a_measured_row_states_its_coverage(self):
        import generate_insight_report as gir
        why = gir._why_this_keyword(
            {"feasibility_status": "Low Feasibility",
             "client_da": 35, "avg_serp_da": 60.0, "gap": 25.0,
             "da_count": 9, "da_missing": 1},
            self.PROFILE)
        self.assertIn("stronger than you", why)
        self.assertIn("9 of 10", why)

    def test_f7_unknown_ranks_above_never_attempted(self):
        import generate_insight_report as gir
        profiles = {"measured": self.PROFILE, "unknown": self.PROFILE,
                    "absent": self.PROFILE}
        rows = [{"Keyword": "measured", "Query_Label": "A",
                 "feasibility_status": "Low Feasibility"},
                {"Keyword": "unknown", "Query_Label": "A",
                 "feasibility_status": feasibility.NOT_MEASURED}]
        order = [r[0] for r in gir._rank_keywords(
            profiles, rows, ["informational"])]
        self.assertEqual(order, ["measured", "unknown", "absent"])

    def test_f7_an_unmeasured_keyword_is_never_the_best_opportunity(self):
        import generate_insight_report as gir
        best, reason = gir._get_best_opportunity_keyword(
            {"unknown": self.PROFILE},
            [{"Keyword": "unknown", "Query_Label": "A",
              "feasibility_status": feasibility.NOT_MEASURED}],
            ["informational"])
        self.assertIsNone(best)
        self.assertIn("verdict", reason.lower())


class TestTheBriefSeesWhatWasNotMeasured(unittest.TestCase):
    """Review finding F8 — the LLM prompt counted only the three verdicts."""

    def test_f8_unmeasured_keywords_are_listed_with_their_coverage(self):
        import brief_data_extraction
        summary = brief_data_extraction._build_feasibility_summary([
            {"Keyword": "a", "Query_Label": "A",
             "feasibility_status": feasibility.NOT_MEASURED,
             "da_count": 2, "da_missing": 8},
            {"Keyword": "b", "Query_Label": "A",
             "feasibility_status": "High Feasibility"},
        ])
        self.assertEqual([e["keyword"] for e in summary["not_measured"]], ["a"])
        self.assertIn("2 of 10", summary["not_measured"][0]["coverage"])
        self.assertEqual(summary["coverage"],
                         {"with_verdict": 1, "attempted": 2})


class TestCoverageReachesTheDatabase(unittest.TestCase):
    """Review finding F9 — the coverage travelled to every output except the
    one rank history reads."""

    def test_f9_the_columns_are_persisted_and_read_back(self):
        import storage
        with tempfile.TemporaryDirectory() as tmp:
            st = storage.SerpStorage(os.path.join(tmp, "t.db"))
            st.save_run("r1", "h")
            st.save_feasibility_from_row(
                {"Keyword": "kw", "avg_serp_da": 60.0, "client_da": None,
                 "gap": None, "feasibility_score": None,
                 "feasibility_status": feasibility.NOT_MEASURED,
                 "da_count": 2, "da_missing": 8, "da_provider": "moz",
                 "client_da_source": "not measured (no provider)"},
                "r1", "A")
            row = st.get_keyword_feasibility("r1")[0]
        self.assertEqual((row["da_count"], row["da_missing"]), (2, 8))
        self.assertEqual(row["da_provider"], "moz")
        self.assertEqual(row["client_da_source"], "not measured (no provider)")
        self.assertIsNone(row["client_da"])

    def test_f9_a_legacy_database_migrates_rather_than_failing(self):
        import storage
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE keyword_feasibility (keyword_text TEXT, "
                "run_id TEXT, query_label TEXT, avg_serp_da REAL, "
                "client_da INTEGER, gap REAL, feasibility_score REAL, "
                "feasibility_status TEXT, client_in_local_pack INTEGER, "
                "pivot_variants TEXT, computed_at TEXT, "
                "PRIMARY KEY (keyword_text, run_id))")
            conn.commit()
            conn.close()
            storage.SerpStorage(path)
            cols = {r[1] for r in sqlite3.connect(path).execute(
                "PRAGMA table_info(keyword_feasibility)")}
        for col in ("da_count", "da_missing", "da_provider",
                    "client_da_source"):
            self.assertIn(col, cols)

    def test_f9_a_row_without_the_counts_stores_null_not_zero(self):
        import storage
        with tempfile.TemporaryDirectory() as tmp:
            st = storage.SerpStorage(os.path.join(tmp, "t.db"))
            st.save_run("r1", "h")
            st.save_feasibility_from_row(
                {"Keyword": "kw", "avg_serp_da": 60.0, "client_da": 35,
                 "gap": 25.0, "feasibility_score": 0.2,
                 "feasibility_status": "Low Feasibility"}, "r1", "A")
            row = st.get_keyword_feasibility("r1")[0]
        self.assertIsNone(row["da_count"])
        self.assertIsNone(row["da_missing"])
