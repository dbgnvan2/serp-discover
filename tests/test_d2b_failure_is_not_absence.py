"""D2b — a failed fetch is not an answer.

One fault, two findings. Both caches recorded what the provider said;
neither recorded whether the provider answered, so a failure was served
back as a measurement for the rest of the TTL — and the TTL is exactly the
window in which a retry would have fixed it.

- D-C-02: a GSC 503 / 403 / expired token was written to the cache as
  ``found = 0`` for every unfetched query, so an outage became "this client
  has no impressions for these queries" for 7 days and a retry inside the
  TTL made no request at all.
- D-C-10: a competitor block whose anchor-text call failed was cached with
  top-level ``status = ok``, so the failed sub-call was not retried for 30
  days and its ``items: []`` read as "this competitor has no anchor text".

Spec: docs/review_2026-11-04/PLAN_D2b_a_failed_fetch_is_not_an_answer.md
      (D2b.1-D2b.16)

All external calls are mocked; no API keys required. The two probes in
``docs/review_2026-11-04/probes/discover/`` drive the same paths by hand.
"""

import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

import gsc_client
import gsc_demand
import moz_competitor
import run_gsc_analysis as rga
from moz_jsonrpc import MozRpcError

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


def _response(ok=True, status=200, payload=None):
    r = MagicMock(ok=ok, status_code=status)
    r.json.return_value = payload if payload is not None else {}
    return r


def _rows(*queries):
    return {"rows": [{"keys": [q], "clicks": 1, "impressions": 10,
                      "ctr": 0.1, "position": 3.0} for q in queries]}


# ---------------------------------------------------------------------------
# D-C-02 — GSC
# ---------------------------------------------------------------------------

class TestGscFetchReportsCompleteness(unittest.TestCase):
    """D2b.1 — ``_fetch_all_rows`` says whether it finished."""

    START, END = "2026-08-01", "2026-10-30"

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.client = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=self.tmp.name, token_provider=lambda: "t")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _fetch(self, response):
        with patch.object(gsc_client, "_post_with_transient_retry",
                          return_value=response):
            return self.client._fetch_all_rows(self.START, self.END)

    def test_network_failure_is_incomplete(self):
        rows, complete = self._fetch(None)
        self.assertEqual(rows, {})
        self.assertFalse(complete)

    def test_http_error_is_incomplete(self):
        rows, complete = self._fetch(_response(ok=False, status=503))
        self.assertEqual(rows, {})
        self.assertFalse(complete)

    def test_non_json_body_is_incomplete(self):
        bad = _response()
        bad.json.side_effect = ValueError("not json")
        rows, complete = self._fetch(bad)
        self.assertFalse(complete)

    def test_short_page_is_complete(self):
        rows, complete = self._fetch(_response(payload=_rows("a", "b")))
        self.assertTrue(complete)
        self.assertEqual(set(rows), {"a", "b"})

    def test_mid_pagination_failure_keeps_rows_and_says_incomplete(self):
        """A failure on page 2 returns page 1 — and does not claim to be done."""
        with patch.object(gsc_client, "ROW_LIMIT", 2):
            with patch.object(gsc_client, "_post_with_transient_retry",
                              side_effect=[_response(payload=_rows("a", "b")),
                                           _response(ok=False, status=500)]):
                rows, complete = self.client._fetch_all_rows(self.START, self.END)
        self.assertEqual(set(rows), {"a", "b"})
        self.assertFalse(complete)


class TestIncompleteFetchIsNotCachedAsAbsence(unittest.TestCase):
    """D2b.2 — the fabrication itself: an outage must not become ``found=0``."""

    START, END = "2026-08-01", "2026-10-30"
    QUERIES = ["couples counselling", "family therapy"]

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.client = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=self.tmp.name, token_provider=lambda: "t")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _cache_rows(self):
        with sqlite3.connect(self.tmp.name) as conn:
            return conn.execute(
                "SELECT query, found FROM gsc_cache").fetchall()

    def test_503_caches_nothing_and_the_retry_asks_again(self):
        with patch.object(gsc_client, "_post_with_transient_retry",
                          return_value=_response(ok=False, status=503)) as post:
            first = self.client.get_query_stats(self.QUERIES, self.START, self.END)
        self.assertEqual(post.call_count, 1)
        self.assertFalse(first.complete)
        self.assertEqual(sorted(first.not_reached), sorted(self.QUERIES))
        self.assertEqual(first.measured_absent, [])
        self.assertEqual(self._cache_rows(), [],
                         "an outage must leave no cache row at all")

        # The whole point of D-C-02: the retry inside the TTL must make a
        # request. Before D2b this was 0.
        with patch.object(gsc_client, "_post_with_transient_retry",
                          return_value=_response(
                              payload=_rows("couples counselling"))) as post:
            second = self.client.get_query_stats(self.QUERIES, self.START, self.END)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(second.complete)
        self.assertIn("couples counselling", second.stats)
        self.assertEqual(second.measured_absent, ["family therapy"])
        self.assertEqual(second.not_reached, [])

    def test_a_real_absence_is_still_cached(self):
        """The ``found=0`` sentinel stays: only its provenance changed."""
        with patch.object(gsc_client, "_post_with_transient_retry",
                          return_value=_response(
                              payload=_rows("couples counselling"))):
            self.client.get_query_stats(self.QUERIES, self.START, self.END)
        self.assertEqual(sorted(self._cache_rows()),
                         [("couples counselling", 1), ("family therapy", 0)])
        with patch.object(gsc_client, "_post_with_transient_retry") as post:
            again = self.client.get_query_stats(self.QUERIES, self.START, self.END)
        post.assert_not_called()
        self.assertEqual(again.measured_absent, ["family therapy"])

    def test_partial_fetch_caches_what_it_got_and_nothing_more(self):
        """Rows reached are kept; the unreached are not written as absent."""
        with patch.object(gsc_client, "ROW_LIMIT", 1):
            with patch.object(gsc_client, "_post_with_transient_retry",
                              side_effect=[_response(payload=_rows("a")),
                                           _response(ok=False, status=500)]):
                result = self.client.get_query_stats(
                    ["a", "b"], self.START, self.END)
        self.assertFalse(result.complete)
        self.assertEqual(result.not_reached, ["b"])
        self.assertEqual(self._cache_rows(), [("a", 1)])


class TestGscStatusVocabulary(unittest.TestCase, _SourceGuard):
    """D2b.4 — three states, and the words for them live in config."""

    def test_the_three_states_are_distinct(self):
        self.assertEqual(
            len({gsc_client.STATUS_MEASURED, gsc_client.STATUS_MEASURED_ABSENT,
                 gsc_client.STATUS_NOT_REACHED}), 3)

    def test_status_for_separates_absence_from_failure(self):
        stats = gsc_client.GscStats(
            stats={"a": {"clicks": 1}}, complete=False, asked=["a", "b", "c"],
            measured_absent=["b"], not_reached=["c"])
        self.assertEqual(stats.status_for("A"), gsc_client.STATUS_MEASURED)
        self.assertEqual(stats.status_for("b"), gsc_client.STATUS_MEASURED_ABSENT)
        self.assertEqual(stats.status_for("c"), gsc_client.STATUS_NOT_REACHED)

    def test_an_unasked_query_is_not_reported_as_absent(self):
        """A lookup miss must never produce a claim about the client."""
        stats = gsc_client.GscStats(
            stats={}, complete=True, asked=["a"], measured_absent=[],
            not_reached=[])
        self.assertEqual(stats.status_for("never asked"),
                         gsc_client.STATUS_NOT_REACHED)

    def test_the_vocabulary_file_covers_every_state(self):
        messages = gsc_client.load_messages()
        for status in (gsc_client.STATUS_MEASURED,
                       gsc_client.STATUS_MEASURED_ABSENT,
                       gsc_client.STATUS_NOT_REACHED):
            entry = (messages.get("statuses") or {}).get(status)
            self.assertIsInstance(entry, dict, f"{status} has no entry")
            for key in ("label", "cell", "coverage"):
                self.assertTrue(entry.get(key), f"{status}.{key} is empty")

    def test_a_malformed_messages_file_degrades_rather_than_aborting(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml",
                                         delete=False) as handle:
            handle.write("{not: valid: yaml")
            path = handle.name
        try:
            with mock.patch.object(gsc_client, "MESSAGES_FILE", path), \
                    mock.patch.object(gsc_client, "_MESSAGES_CACHE", None):
                self.assertEqual(
                    gsc_client.status_text(gsc_client.STATUS_NOT_REACHED),
                    gsc_client.STATUS_NOT_REACHED)
                self.assertEqual(gsc_client.line("x", "built in"), "built in")
        finally:
            os.unlink(path)
            gsc_client._MESSAGES_CACHE = None

    def test_the_words_are_not_hardcoded_in_python(self):
        """The fault was four Python copies of one status word (D2a's lesson)."""
        self.assertNotInSource("no GSC data", "run_gsc_analysis.py")


class TestReportNamesTheFailure(unittest.TestCase):
    """D2b.5/D2b.8 — the report states which it was, and over what."""

    CONFIG = {"gsc": {"enabled": True, "property": "sc-domain:x",
                      "lookback_days": 90},
              "analysis_report": {"client_name": "C"}}

    @staticmethod
    def _rows(*statuses):
        out = []
        for index, status in enumerate(statuses):
            row = {"query": f"q{index}", "query_label": "A",
                   "source_keyword": f"q{index}", "has_ai_overview": False,
                   "found": status == gsc_client.STATUS_MEASURED,
                   "gsc_status": status}
            if row["found"]:
                row.update(clicks=1, impressions=10, ctr=0.1, position=3.0)
            out.append(row)
        return out

    def test_unreached_row_is_not_called_measured_absence(self):
        rows = self._rows(gsc_client.STATUS_NOT_REACHED)
        report = rga.generate_report(
            rows, rga.compute_sponge_effect(rows, not_reached=1), [],
            self.CONFIG, "x.json", ("a", "b"), fetch_complete=False)
        self.assertIn("not reached", report)
        self.assertIn("Incomplete fetch", report)
        self.assertNotIn("reported as absent, not as zero", report)

    def test_measured_absence_is_still_stated_as_such(self):
        rows = self._rows(gsc_client.STATUS_MEASURED,
                          gsc_client.STATUS_MEASURED_ABSENT)
        report = rga.generate_report(
            rows, rga.compute_sponge_effect(rows), [], self.CONFIG,
            "x.json", ("a", "b"), fetch_complete=True)
        self.assertIn("no impressions", report)
        self.assertNotIn("not reached", report)
        self.assertNotIn("Incomplete fetch", report)

    def test_sponge_reports_its_denominator(self):
        rows = self._rows(gsc_client.STATUS_MEASURED,
                          gsc_client.STATUS_NOT_REACHED)
        sponge = rga.compute_sponge_effect(rows, not_reached=1)
        self.assertEqual(sponge["queries_considered"], 2)
        self.assertEqual(sponge["queries_usable"], 1)
        self.assertEqual(sponge["not_reached"], 1)

    def test_insufficient_data_names_the_fetch_gap(self):
        rows = self._rows(gsc_client.STATUS_NOT_REACHED)
        report = rga.generate_report(
            rows, rga.compute_sponge_effect(rows, not_reached=1), [],
            self.CONFIG, "x.json", ("a", "b"), fetch_complete=False)
        self.assertIn("never reached", report)
        self.assertNotIn(
            "More keywords or a longer lookback window will fill the buckets",
            report)


class TestSidecarAndBriefCarryCompleteness(unittest.TestCase):
    """D2b.6 — the LLM payload cannot read an outage as the client's traffic."""

    CONFIG = {"gsc": {"property": "sc-domain:x", "lookback_days": 90}}

    def test_sidecar_names_the_unreached_queries(self):
        rows = [
            {"query": "a", "found": True, "clicks": 1, "impressions": 10,
             "ctr": 0.1, "position": 2.0,
             "gsc_status": gsc_client.STATUS_MEASURED},
            {"query": "b", "found": False,
             "gsc_status": gsc_client.STATUS_NOT_REACHED},
            {"query": "c", "found": False,
             "gsc_status": gsc_client.STATUS_MEASURED_ABSENT},
        ]
        sidecar = rga.build_sidecar(
            rows, {"bands": []}, [], self.CONFIG, "x.json", ("a", "b"),
            fetch_complete=False)
        self.assertFalse(sidecar["fetch_complete"])
        self.assertEqual(sidecar["queries_not_reached"], ["b"])
        self.assertEqual(sidecar["queries_no_impressions"], ["c"])

    def test_brief_payload_passes_completeness_through(self):
        import brief_data_extraction
        summary = brief_data_extraction._build_gsc_summary({
            "queries_checked": 3, "queries_with_data": 1,
            "fetch_complete": False, "queries_not_reached": ["b", "c"],
            "per_query": [], "sponge": {}, "reformat_candidates": [],
        })
        self.assertFalse(summary["fetch_complete"])
        self.assertEqual(summary["queries_not_reached"], 2)

    def test_the_prompt_tells_the_model_what_to_do_with_it(self):
        prompt = _src("prompts/main_report/system.md")
        self.assertIn("fetch_complete", prompt)
        self.assertIn("queries_not_reached", prompt)


class TestDemandTrendRefusesAPartialFetch(unittest.TestCase):
    """D2b.7 — the case the existing no-clicks guard does not catch."""

    ROWS = [{"query": "brandy co", "found": True, "clicks": 8,
             "impressions": 90, "position": 2.0},
            {"query": "family therapy", "found": True, "clicks": 2,
             "impressions": 40, "position": 6.0}]
    CFG = {"analysis_report": {"client_name_patterns": ["brandy"]}}

    def test_a_complete_fetch_still_scores(self):
        _, score = gsc_demand.compute_demand(
            [dict(r) for r in self.ROWS], self.CFG, fetch_complete=True)
        self.assertTrue(score["data_available"])
        self.assertTrue(score["fetch_complete"])

    def test_a_partial_fetch_with_clicks_does_not_score(self):
        """Clicks are present, so the old guard passes — this is the gap."""
        _, score = gsc_demand.compute_demand(
            [dict(r) for r in self.ROWS], self.CFG, fetch_complete=False)
        self.assertFalse(score["data_available"])
        self.assertFalse(score["fetch_complete"])

    def test_no_trend_point_is_written_from_a_partial_fetch(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            rows, score = gsc_demand.compute_demand(
                [dict(r) for r in self.ROWS], self.CFG, fetch_complete=False)
            gsc_demand.save_demand(tmp.name, "sc-domain:x", "20261116_1200",
                                   rows, score, fetched_at="20261116_1200")
            self.assertEqual(
                gsc_demand.get_demand_trend(tmp.name, "sc-domain:x"), [])
        finally:
            os.unlink(tmp.name)

    def test_the_section_says_the_fetch_failed_not_that_demand_is_absent(self):
        _, score = gsc_demand.compute_demand(
            [dict(r) for r in self.ROWS], self.CFG, fetch_complete=False)
        text = "\n".join(gsc_demand.render_demand_section(score))
        self.assertIn("did not reach every", text)
        self.assertNotIn("Insufficient GSC data", text)


# ---------------------------------------------------------------------------
# D-C-10 — Moz competitor
# ---------------------------------------------------------------------------

def _moz_payload(ranking=True, anchors=True):
    def call(method, data):
        if method == moz_competitor.RANKING_KEYWORDS_METHOD:
            if ranking is not True:
                raise MozRpcError("Moz API HTTP 503", status=503)
            return {"ranking_keywords": [
                {"keyword": "bowen theory", "ranking_page": "/",
                 "rank_position": 3, "difficulty": 20, "volume": 100}]}
        if method == moz_competitor.ANCHOR_TEXT_METHOD:
            if anchors is not True:
                raise MozRpcError("Moz API HTTP 503", status=503)
            return {"anchor_texts": [
                {"text": "bowen center", "external_root_domains": 9,
                 "external_pages": 30}]}
        raise MozRpcError("Action not found", status=404, code=-32601)
    return call


class TestMozPartialBlockIsNotFrozen(unittest.TestCase):
    """D2b.9-D2b.12 — the failed sub-call is asked again, and only it."""

    DOMAIN = "bowencenter.org"

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _client(self):
        return moz_competitor.MozCompetitorClient(
            db_path=self.tmp.name, locale="en-US")

    def _fetch(self, call, calls):
        def recording(method, data):
            calls.append(method)
            return call(method, data)
        with patch.object(moz_competitor, "moz_call", recording), \
                patch.object(moz_competitor, "row_budget", return_value=None):
            return self._client().fetch([self.DOMAIN])[self.DOMAIN]

    def test_a_failed_sub_call_is_not_cached(self):
        calls = []
        self._fetch(_moz_payload(anchors=False), calls)
        with sqlite3.connect(self.tmp.name) as conn:
            row = conn.execute(
                "SELECT ranking_keywords_at, anchor_texts_at "
                f"FROM {moz_competitor.CACHE_TABLE}").fetchone()
        self.assertIsNotNone(row[0], "the call that answered must be cached")
        self.assertIsNone(row[1], "the call that failed must not be cached")

    def test_the_retry_asks_for_the_failed_signal_only(self):
        self._fetch(_moz_payload(anchors=False), [])
        calls = []
        block = self._fetch(_moz_payload(), calls)
        self.assertEqual(calls, [moz_competitor.ANCHOR_TEXT_METHOD])
        self.assertEqual(block["anchor_texts"]["status"], "ok")
        self.assertTrue(block["ranking_keywords"]["items"],
                        "the cached signal must still be served")

    def test_a_fully_cached_domain_costs_nothing(self):
        self._fetch(_moz_payload(), [])
        calls = []
        self._fetch(_moz_payload(), calls)
        self.assertEqual(calls, [])

    def test_a_failure_is_never_served_from_cache(self):
        self._fetch(_moz_payload(anchors=False), [])
        calls = []
        block = self._fetch(_moz_payload(anchors=False), calls)
        # It asked again (not frozen), and what it reports is the failure,
        # not an empty list standing in for one.
        self.assertEqual(calls, [moz_competitor.ANCHOR_TEXT_METHOD])
        self.assertEqual(block["anchor_texts"]["status"], "error")
        self.assertFalse(block["anchor_texts"]["data_available"])
        self.assertIn("failed", block["anchor_texts"]["reason"])

    def test_disabled_signals_do_not_make_a_block_partial(self):
        """D2b.9 — an off switch is not a gap to refetch every run."""
        self._fetch(_moz_payload(), [])
        client = self._client()
        self.assertEqual(client.enabled_signals(),
                         (moz_competitor.SIGNAL_RANKING,
                          moz_competitor.SIGNAL_ANCHORS))
        _, needed = client._cache_lookup([self.DOMAIN])
        self.assertEqual(needed, {})

    def test_enabling_a_signal_later_asks_only_for_it(self):
        self._fetch(_moz_payload(), [])
        client = moz_competitor.MozCompetitorClient(
            db_path=self.tmp.name, locale="en-US", brand_authority=True)
        _, needed = client._cache_lookup([self.DOMAIN])
        self.assertEqual(needed, {self.DOMAIN: [moz_competitor.SIGNAL_BRAND]})

    def test_row_budget_counts_only_the_signals_asked_for(self):
        """D2b.12 — a one-signal refetch must not reserve a four-call budget."""
        self._fetch(_moz_payload(anchors=False), [])
        seen = {}

        def fake_budget(estimate, kind):
            seen["estimate"] = estimate
            return None

        with patch.object(moz_competitor, "moz_call", _moz_payload()), \
                patch.object(moz_competitor, "row_budget", fake_budget):
            self._client().fetch([self.DOMAIN])
        self.assertEqual(seen["estimate"],
                         moz_competitor.DEFAULT_ANCHOR_TEXT_LIMIT
                         * moz_competitor.ROWS_PER_OBJECT)


class TestMozSignalFreshnessIsPerSignal(unittest.TestCase):
    """D2b.13 — a stale signal must not borrow a fresh sibling's timestamp."""

    DOMAIN = "bowencenter.org"

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch.object(moz_competitor, "moz_call", _moz_payload()), \
                patch.object(moz_competitor, "row_budget", return_value=None):
            moz_competitor.MozCompetitorClient(
                db_path=self.tmp.name, locale="en-US").fetch([self.DOMAIN])

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_each_signal_reports_its_own_collection_time(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(
                f"UPDATE {moz_competitor.CACHE_TABLE} SET ranking_keywords_at=?",
                (old,))
            conn.commit()
        with patch.object(moz_competitor, "moz_call", _moz_payload()), \
                patch.object(moz_competitor, "row_budget", return_value=None):
            block = moz_competitor.MozCompetitorClient(
                db_path=self.tmp.name, locale="en-US").fetch([self.DOMAIN])[
                    self.DOMAIN]
        self.assertEqual(block["ranking_keywords"]["fetched_at"], old)
        self.assertNotEqual(block["anchor_texts"]["fetched_at"], old)
        # And the block as a whole is only as current as its stalest part.
        self.assertEqual(block["fetched_at"], old)

    def test_a_signal_expires_on_its_own(self):
        from datetime import datetime, timedelta, timezone
        expired = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(
                f"UPDATE {moz_competitor.CACHE_TABLE} SET anchor_texts_at=?",
                (expired,))
            conn.commit()
        client = moz_competitor.MozCompetitorClient(
            db_path=self.tmp.name, locale="en-US")
        _, needed = client._cache_lookup([self.DOMAIN])
        self.assertEqual(needed, {self.DOMAIN: [moz_competitor.SIGNAL_ANCHORS]})


class TestMozConsumerCanNameTheFailure(unittest.TestCase):
    """D2b.14 — ``items: []`` never has to stand in for "the call failed"."""

    def test_every_page_block_carries_the_same_keys(self):
        client = moz_competitor.MozCompetitorClient(db_path=":memory:")
        ok = client._page_block([{"text": "x"}], [{"text": "x"}], "ok")
        failed = client._page_block([], [], "error")
        self.assertEqual(set(ok), set(failed))
        self.assertTrue(failed["reason"])
        self.assertEqual(ok["reason"], "")
        self.assertFalse(failed["data_available"])

    def test_link_momentum_failure_is_not_reported_as_no_record(self):
        def call(method, data):
            if method == moz_competitor.LINKING_DOMAIN_METHOD:
                raise MozRpcError("Moz API HTTP 503", status=503)
            raise MozRpcError("Action not found", status=404, code=-32601)
        client = moz_competitor.MozCompetitorClient(
            db_path=":memory:", link_momentum=True)
        with patch.object(moz_competitor, "moz_call", call):
            block, _ = client._fetch_link_momentum("x.example")
        self.assertEqual(block["status"], "error")
        self.assertFalse(block["data_available"])

    def test_a_skipped_domain_says_skipped_not_no_record(self):
        """A cap or a quota is not a measurement of the domain (P1)."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            with patch.object(moz_competitor, "moz_call", _moz_payload()), \
                    patch.object(moz_competitor, "row_budget",
                                 return_value=None):
                result = moz_competitor.MozCompetitorClient(
                    db_path=tmp.name, max_competitors=1).fetch(
                        ["a.example", "b.example"])
            self.assertEqual(result["b.example"]["status"], "skipped_run_cap")
            self.assertIn("cap", result["b.example"]["reason"])
        finally:
            os.unlink(tmp.name)


class TestNoPathFromAFailureToAServedRow(unittest.TestCase, _SourceGuard):
    """D2b.15 — the two gates, pinned in source so a refactor cannot drop them."""

    def test_gsc_caches_absences_only_on_a_complete_fetch(self):
        source = _src("gsc_client.py")
        self.assertIn("if complete:", source)
        self.assertInSource("not_reached = missing", "gsc_client.py")

    def test_moz_cache_store_gates_on_each_sub_block(self):
        self.assertInSource("if signal in SIGNALS and block.get(\"status\") "
                            "in _CACHEABLE", "moz_competitor.py")

    def test_moz_cache_lookup_no_longer_gates_on_a_top_level_status(self):
        self.assertNotInSource("continue  # never serve a cached failure",
                               "moz_competitor.py")

    def test_both_caches_name_the_finding_they_fix(self):
        self.assertInSource("D-C-02", "gsc_client.py")
        self.assertInSource("D-C-10", "moz_competitor.py")


if __name__ == "__main__":
    unittest.main()
