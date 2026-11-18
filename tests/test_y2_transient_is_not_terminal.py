"""Review chunk Y2 — a retryable failure is retried, and says it was one.

Adjacent issues logged by earlier chunks' cold reviews (global rule 10):

- `url_enricher.fetch_url` fetched every ranked page with a bare
  `requests.get` and one timeout. Every other outbound call in this tool
  retries with backoff (`http_retry`), so one connection reset filed a page
  as unreachable and its word count, schema, author signals and
  extractability as not measured for the whole run (P5 — a class of calls is
  hardened together).
- It returned `None` for a timeout and for a URL that cannot be requested at
  all, so the row read "Unreachable" either way. A reader could not tell a
  page that may be readable next run from a host that does not resolve
  (P1).
- `run_gsc_analysis` caught a `gsc_demand` persistence failure, logged it and
  rendered the section with no trend line — which is exactly what a first run
  looks like (P2/P6).

Spec: docs/review_2026-11-04/PLAN_Y2_transient_is_not_terminal.md
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enrichment
import gsc_demand
import http_retry
import url_enricher

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Resp:
    def __init__(self, status=200, body=b"<html><h1>x</h1></html>", headers=None):
        self.status_code = status
        self.content = body
        self.text = body.decode("utf-8", "replace")
        self.headers = headers or {"Content-Type": "text/html"}

    @property
    def ok(self):
        return self.status_code < 400


class TestThePageFetchRetriesLikeEveryOtherCall(unittest.TestCase):

    def setUp(self):
        self.sleeps = []
        patch = mock.patch.object(http_retry.time, "sleep", self.sleeps.append)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_connection_reset_is_retried_before_giving_up(self):
        import requests

        calls = []

        def _get(url, **kwargs):
            calls.append(url)
            raise requests.ConnectionError("reset by peer")

        with mock.patch.object(url_enricher.requests, "head",
                               side_effect=requests.RequestException("no head")), \
             mock.patch.object(http_retry.requests, "get", _get):
            result = url_enricher.UrlEnricher().fetch_url("https://x.ca/p")
        self.assertEqual(len(calls), http_retry.RETRY_ATTEMPTS)
        self.assertTrue(result["retryable"])
        self.assertIsNone(result["status_code"])

    def test_a_transient_status_is_retried_and_the_retry_is_used(self):
        import requests

        responses = [_Resp(503), _Resp(200, b"<html>ok</html>")]

        def _get(url, **kwargs):
            return responses.pop(0)

        with mock.patch.object(url_enricher.requests, "head",
                               side_effect=requests.RequestException("no head")), \
             mock.patch.object(http_retry.requests, "get", _get):
            result = url_enricher.UrlEnricher().fetch_url("https://x.ca/p")
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(responses, [])
        self.assertNotIn("error", result)

    def test_the_timeout_is_passed_to_every_attempt(self):
        """A retry policy that drops the timeout hangs the run instead."""
        import requests

        seen = []

        def _get(url, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise requests.Timeout("too slow")

        with mock.patch.object(url_enricher.requests, "head",
                               side_effect=requests.RequestException("no head")), \
             mock.patch.object(http_retry.requests, "get", _get):
            url_enricher.UrlEnricher(timeout=7).fetch_url("https://x.ca/p")
        self.assertEqual(seen, [7] * http_retry.RETRY_ATTEMPTS)


class TestARetryableFailureReadsAsRetryable(unittest.TestCase):

    def _row(self, fetch_result):
        item = {"Is_Destination_Page": True}
        enricher = mock.Mock()
        enricher.fetch_url.return_value = fetch_result
        storage = mock.Mock()
        outcome = enrichment.enrich_row(
            item, "https://x.ca/p", 1, 10, enricher,
            mock.Mock(), mock.Mock(), storage, domain="x.ca")
        return outcome, item

    def test_a_network_exhaustion_is_not_the_same_as_a_dead_host(self):
        retryable, _ = self._row(
            {"status_code": None, "error": "network", "retryable": True})
        dead, _ = self._row(
            {"status_code": None, "error": "No host supplied",
             "retryable": False})
        self.assertEqual(retryable, enrichment.FETCH_RETRYABLE)
        self.assertEqual(dead, enrichment.UNREACHABLE)
        self.assertNotEqual(enrichment.status_text(retryable),
                            enrichment.status_text(dead))

    def test_the_words_come_from_the_vocabulary_file(self):
        import yaml

        with open(os.path.join(REPO, "serp_vocab.yml"), encoding="utf-8") as f:
            vocab = yaml.safe_load(f)["fetch_status"]
        self.assertEqual(enrichment.status_text(enrichment.FETCH_RETRYABLE),
                         vocab["fetch_retryable"])
        # And the literal fallback used when the file is missing or malformed
        # says the same thing. It is the path a reader gets when the YAML
        # cannot be read, so a fallback that still called this state
        # "Unreachable" would re-merge the two facts there.
        for state, fallback in enrichment._DEFAULTS.items():
            self.assertEqual(fallback, vocab[state], state)

    def test_the_state_is_counted_as_a_page_not_read(self):
        """Left out of the unread count, the warning could say "0 of 10
        pages were not read" on a run where nothing was read at all."""
        import serp_audit

        outcomes = {enrichment.ENRICHED: 2,
                    enrichment.BLOCKED: 1,
                    enrichment.FETCH_RETRYABLE: 3,
                    enrichment.UNREACHABLE: 1}
        self.assertEqual(serp_audit._unread_fetch_count(outcomes), 5)
        # A row past the rank cap was never meant to be read, so it must not
        # make the warning fire.
        outcomes[enrichment.NOT_ATTEMPTED] = 7
        self.assertEqual(serp_audit._unread_fetch_count(outcomes), 5)
        self.assertIn(enrichment.FETCH_RETRYABLE,
                      enrichment.FAILED_FETCH_STATES)

    def test_the_brief_counts_the_same_pages_as_unread(self):
        """`brief_data_extraction` keeps its own list of unread states, and a
        state missing from it is counted as a page that WAS read — so the
        brief's schema, extractability, freshness and E-E-A-T figures get a
        denominator larger than the number of pages read."""
        import brief_data_extraction

        for state in enrichment.UNREAD_STATES:
            self.assertIn(state, brief_data_extraction._UNREAD_FETCH_STATES,
                          state)
        rows = [{"fetch_state": enrichment.ENRICHED},
                {"fetch_state": enrichment.FETCH_RETRYABLE},
                {"fetch_state": enrichment.UNREACHABLE},
                {"fetch_state": enrichment.NOT_DESTINATION_PAGE}]
        coverage = brief_data_extraction._build_fetch_coverage(rows)
        self.assertEqual(coverage["read"], 1)
        self.assertEqual(coverage["unread"], 3)

    def test_the_unread_warning_does_not_blame_the_sites(self):
        """It said "(error status or unreachable)" after the count started
        including a local network failure."""
        text = enrichment.status_text("blocked_warning", blocked=5, attempted=5)
        self.assertIn("network", text)
        self.assertNotIn("error status or unreachable", text)


class TestAFailedWriteIsNotAFirstRun(unittest.TestCase):

    SCORE = {"reportable": True, "data_available": True,
             "branded_click_share": 0.4, "branded_clicks": 4,
             "nonbranded_clicks": 6, "benchmark_band": "typical",
             "matched_patterns": [], "tracked_query_count": 3,
             "band_basis": "tracked", "property_branded_click_share": None,
             "property_query_count": 0, "fetch_complete": True,
             "branded_query_count": 1, "property_branded_clicks": 0,
             "property_nonbranded_clicks": 0}

    def test_the_section_says_why_there_is_no_delta(self):
        quiet = "\n".join(gsc_demand.render_demand_section(self.SCORE, None))
        broken = "\n".join(gsc_demand.render_demand_section(
            self.SCORE, None, trend_error="database is locked"))
        self.assertIn("database is locked", broken)
        self.assertNotIn("database is locked", quiet)
        self.assertNotEqual(quiet, broken)

    def _report(self, *, db_path, property_, save_raises=False):
        """The real `run_analysis` report, so the reason has to travel the
        whole way rather than merely appear in the source."""
        import json
        import tempfile
        from datetime import date

        import gsc_client
        import run_gsc_analysis

        data = {"overview": [
            {"Query_Label": "A", "Source_Keyword": "kw one",
             "Executed_Query": "kw one", "Has_Main_AI_Overview": False}]}
        config = {"gsc": {"enabled": True, "property": property_,
                          "lookback_days": 90},
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
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            ctx = (mock.patch.object(
                run_gsc_analysis.gsc_demand, "save_demand",
                side_effect=RuntimeError("database is locked"))
                if save_raises else mock.patch.object(
                    run_gsc_analysis.gsc_demand, "get_demand_trend",
                    return_value=[]))
            with ctx:
                report, _sidecar = run_gsc_analysis.run_analysis(
                    data, config, client, path, today=date(2026, 7, 4),
                    db_path=(os.path.join(tmp, "t.db") if db_path else None))
        return report

    def test_a_failed_write_is_named_in_the_report(self):
        report = self._report(db_path=True, property_="sc-domain:x.ca",
                              save_raises=True)
        self.assertIn("database is locked", report)

    def test_a_missing_property_is_named_rather_than_printing_nothing(self):
        """`gsc.property` unset means no history ever accumulates. The report
        said nothing, which reads as a first run."""
        report = self._report(db_path=True, property_="")
        self.assertIn("gsc.property", report)

    def test_a_first_run_says_it_is_a_first_run(self):
        report = self._report(db_path=True, property_="sc-domain:x.ca")
        self.assertIn("first run", report)

    def test_every_reason_comes_from_the_messages_file(self):
        import yaml

        import run_gsc_analysis

        with open(os.path.join(REPO, "gsc_messages.yml"), encoding="utf-8") as f:
            block = yaml.safe_load(f)["demand_trend"]
        for key in ("write_failed", "no_property", "no_database",
                    "no_run_timestamp", "first_run", "line"):
            self.assertIn(key, block, key)
        self.assertEqual(run_gsc_analysis._trend_reason("no_property"),
                         block["no_property"].strip())


if __name__ == "__main__":
    unittest.main()
