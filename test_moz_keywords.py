"""
test_moz_keywords.py
~~~~~~~~~~~~~~~~~~~~
Tests for Moz keyword metrics.

Spec: moz_api_upgrade_spec_v1.md#T.2

All HTTP calls are mocked — no real network, no Moz credentials required.
Response bodies mirror the shape captured from a real
data.keyword.metrics.fetch call on 2026-08-28 (learnings P19).
"""

import ast
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import brief_data_extraction
import moz_keywords
from moz_keywords import (
    MozKeywordClient,
    STATUS_ERROR,
    STATUS_NO_RECORD,
    STATUS_OK,
    STATUS_SKIPPED_CAP,
    STATUS_SKIPPED_QUOTA,
)

MOZ_ENV = {"MOZ_TOKEN": "test-token-abc123"}
POST_TARGET = "moz_jsonrpc.requests.post"

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

#: The real result object, verbatim from a live call.
REAL_METRICS = {
    "keyword_metrics": {
        "volume": 373,
        "difficulty": 22,
        "organic_ctr": 88,
        "priority": 63,
        "intent": None,
    },
    "serp_query": {
        "keyword": "family of origin therapy",
        "locale": "en-US",
        "device": "desktop",
        "engine": "google",
        "vicinity": "",
    },
}

#: The real 404 body Moz returns when it holds no metrics for a keyword.
REAL_NO_RECORD_BODY = {
    "id": "e467350a-865e-4b7b-aa90-d84cc55a0a50",
    "jsonrpc": "2.0",
    "error": {
        "code": -32655,
        "status": 404,
        "data": {"key": "serp_query", "value": {"keyword": "zzqq"}},
        "message": "No keyword metrics for that query.",
    },
}


def _ok(result=None) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {
        "jsonrpc": "2.0", "id": "x" * 24,
        "result": REAL_METRICS if result is None else result,
    }
    return resp


def _no_record() -> MagicMock:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 404
    resp.json.return_value = REAL_NO_RECORD_BODY
    resp.text = str(REAL_NO_RECORD_BODY)
    return resp


def _server_error() -> MagicMock:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 500
    resp.headers = {}
    resp.json.return_value = {"error": {"code": -32000, "message": "boom"}}
    resp.text = "boom"
    return resp


def _quota(remaining: int, allotted: int = 3000) -> dict:
    return {"path": "api.limits.data.rows", "allotted": allotted,
            "used": allotted - remaining, "remaining": remaining,
            "overage": False}


class _ClientCase(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, MOZ_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.quota = patch.object(
            moz_keywords, "quota_status", return_value=_quota(3000)
        )
        self.quota.start()
        self.client = MozKeywordClient(db_path=self.tmp.name, locale="en-US")

    def tearDown(self):
        self.quota.stop()
        self.env.stop()
        os.unlink(self.tmp.name)


class TestRequestContract(_ClientCase):

    @patch(POST_TARGET)
    def test_t2_sends_all_four_required_serp_query_fields(self, mock_post):
        """The API rejects the call naming any missing field, one at a time."""
        mock_post.return_value = _ok()
        self.client.fetch(["family of origin therapy"])
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["method"], "data.keyword.metrics.fetch")
        query = sent["params"]["data"]["serp_query"]
        self.assertEqual(query["keyword"], "family of origin therapy")
        self.assertEqual(query["engine"], "google")
        self.assertEqual(query["locale"], "en-US")
        self.assertEqual(query["device"], "desktop")

    @patch(POST_TARGET)
    def test_t2_one_call_per_keyword(self, mock_post):
        """Moz has no .multiple variant for this method."""
        mock_post.return_value = _ok()
        self.client.fetch(["a", "b", "c"])
        self.assertEqual(mock_post.call_count, 3)

    @patch(POST_TARGET)
    def test_t2_parses_every_metric_field(self, mock_post):
        mock_post.return_value = _ok()
        block = self.client.fetch(["family of origin therapy"])["family of origin therapy"]
        self.assertTrue(block["data_available"])
        self.assertEqual(block["volume"], 373)
        self.assertEqual(block["difficulty"], 22)
        self.assertEqual(block["organic_ctr"], 88)
        self.assertEqual(block["priority"], 63)


class TestAbsentData(_ClientCase):
    """T.2 — absent data is stated, never a fabricated zero."""

    @patch(POST_TARGET)
    def test_t2_no_record_404_is_not_an_error(self, mock_post):
        mock_post.return_value = _no_record()
        block = self.client.fetch(["zzqq"])["zzqq"]
        self.assertFalse(block["data_available"])
        self.assertEqual(block["status"], STATUS_NO_RECORD)

    @patch(POST_TARGET)
    def test_t2_no_record_never_reports_zero_metrics(self, mock_post):
        """A volume of 0 would claim "nobody searches this" — a much stronger
        statement than "Moz has no record"."""
        mock_post.return_value = _no_record()
        block = self.client.fetch(["zzqq"])["zzqq"]
        for field in moz_keywords.METRIC_FIELDS:
            self.assertNotIn(field, block)

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t2_server_error_is_distinct_from_no_record(self, mock_post):
        """P1 — a 5xx is retryable; "no record" is Moz's real answer."""
        mock_post.return_value = _server_error()
        block = self.client.fetch(["kw"])["kw"]
        self.assertEqual(block["status"], STATUS_ERROR)
        self.assertFalse(block["data_available"])

    @patch(POST_TARGET)
    def test_t2_every_input_keyword_is_present_in_the_result(self, mock_post):
        """P2 — a dropped keyword must never look like "no demand"."""
        mock_post.side_effect = [_ok(), _no_record()]
        result = self.client.fetch(["good", "absent"])
        self.assertEqual(set(result), {"good", "absent"})

    @patch(POST_TARGET)
    def test_t2_metrics_object_of_nulls_is_absent_not_zero(self, mock_post):
        mock_post.return_value = _ok({"keyword_metrics": {
            "volume": None, "difficulty": None,
            "organic_ctr": None, "priority": None, "intent": None,
        }})
        block = self.client.fetch(["kw"])["kw"]
        self.assertFalse(block["data_available"])

    @patch(POST_TARGET)
    def test_t2_boolean_metric_is_rejected_not_read_as_one(self, mock_post):
        mock_post.return_value = _ok({"keyword_metrics": {"volume": True}})
        block = self.client.fetch(["kw"])["kw"]
        self.assertNotIn("volume", block)


class TestCaching(_ClientCase):

    @patch(POST_TARGET)
    def test_t2_second_run_hits_the_cache(self, mock_post):
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        mock_post.reset_mock()
        block = self.client.fetch(["kw"])["kw"]
        mock_post.assert_not_called()
        self.assertEqual(block["volume"], 373)

    @patch(POST_TARGET)
    def test_t2_no_record_verdict_is_cached(self, mock_post):
        """Moz's real answer — caching it avoids a pointless call next run."""
        mock_post.return_value = _no_record()
        self.client.fetch(["zzqq"])
        mock_post.reset_mock()
        block = self.client.fetch(["zzqq"])["zzqq"]
        mock_post.assert_not_called()
        self.assertEqual(block["status"], STATUS_NO_RECORD)

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t2_errors_are_never_cached(self, mock_post):
        """P1 — caching a failure turns one bad afternoon into a month of
        "no data" with no way to tell why."""
        mock_post.return_value = _server_error()
        self.client.fetch(["kw"])
        with sqlite3.connect(self.tmp.name) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM moz_keyword_cache WHERE keyword='kw'"
            ).fetchone()
        self.assertEqual(rows[0], 0)

        mock_post.reset_mock()
        mock_post.return_value = _ok()
        block = self.client.fetch(["kw"])["kw"]
        mock_post.assert_called()
        self.assertTrue(block["data_available"])

    @patch(POST_TARGET)
    def test_t2_locale_is_part_of_the_cache_key(self, mock_post):
        """The same keyword genuinely differs by locale — en-US had no record
        for a phrase that en-CA answered."""
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        other = MozKeywordClient(db_path=self.tmp.name, locale="en-CA")
        mock_post.reset_mock()
        other.fetch(["kw"])
        mock_post.assert_called_once()

    @patch(POST_TARGET)
    def test_t2_expired_cache_refetches(self, mock_post):
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        stale = (datetime.now(_UTC) - timedelta(days=60)).isoformat()
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(
                "UPDATE moz_keyword_cache SET fetched_at=? WHERE keyword='kw'",
                (stale,),
            )
            conn.commit()
        mock_post.reset_mock()
        self.client.fetch(["kw"])
        mock_post.assert_called_once()


class TestSpendControls(_ClientCase):
    """T.2 — a paid call is capped and never silently overspends."""

    @patch(POST_TARGET)
    def test_t2_run_cap_limits_keywords_fetched(self, mock_post):
        mock_post.return_value = _ok()
        client = MozKeywordClient(db_path=self.tmp.name, max_keywords=2)
        result = client.fetch(["a", "b", "c", "d"])
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result["d"]["status"], STATUS_SKIPPED_CAP)

    @patch(POST_TARGET)
    def test_t2_capped_keywords_are_announced(self, mock_post):
        """P9/P2 — a cap that drops input must say how much it dropped."""
        mock_post.return_value = _ok()
        client = MozKeywordClient(db_path=self.tmp.name, max_keywords=1)
        with self.assertLogs("moz_keywords", level="WARNING") as logs:
            client.fetch(["a", "b", "c"])
        self.assertTrue(any("run cap" in line for line in logs.output))

    @patch(POST_TARGET)
    def test_t2_rows_consumed_counts_four_per_successful_fetch(self, mock_post):
        """Measured live: a successful fetch bills 4 rows, not 1."""
        mock_post.return_value = _ok()
        self.client.fetch(["a", "b"])
        self.assertEqual(self.client.rows_consumed, 8)

    @patch(POST_TARGET)
    def test_t2_no_record_bills_nothing(self, mock_post):
        mock_post.return_value = _no_record()
        self.client.fetch(["zzqq"])
        self.assertEqual(self.client.rows_consumed, 0)

    @patch(POST_TARGET)
    def test_t2_stops_before_exceeding_the_monthly_quota(self, mock_post):
        mock_post.return_value = _ok()
        with patch.object(moz_keywords, "quota_status", return_value=_quota(9)):
            client = MozKeywordClient(db_path=self.tmp.name)
            result = client.fetch(["a", "b", "c", "d"])
        self.assertEqual(mock_post.call_count, 2)  # 9 rows / 4 per call
        self.assertEqual(result["c"]["status"], STATUS_SKIPPED_QUOTA)
        self.assertEqual(result["d"]["status"], STATUS_SKIPPED_QUOTA)

    @patch(POST_TARGET)
    def test_t2_quota_skips_are_announced(self, mock_post):
        mock_post.return_value = _ok()
        with patch.object(moz_keywords, "quota_status", return_value=_quota(4)):
            client = MozKeywordClient(db_path=self.tmp.name)
            with self.assertLogs("moz_keywords", level="WARNING") as logs:
                client.fetch(["a", "b"])
        self.assertTrue(any("quota exhausted" in line for line in logs.output))

    @patch(POST_TARGET)
    def test_t2_unreadable_quota_does_not_disable_the_feature(self, mock_post):
        """P1 — a transient quota read failure must not read as "no budget"."""
        mock_post.return_value = _ok()
        with patch.object(moz_keywords, "quota_status",
                          side_effect=RuntimeError("transient")):
            client = MozKeywordClient(db_path=self.tmp.name)
            result = client.fetch(["a"])
        self.assertTrue(result["a"]["data_available"])


class TestFromConfig(unittest.TestCase):

    def _client(self, config):
        with patch.dict(os.environ, MOZ_ENV), \
                tempfile.NamedTemporaryFile(suffix=".db") as f:
            return MozKeywordClient.from_config(config, db_path=f.name)

    def test_t2_from_config_maps_every_key(self):
        c = self._client({"moz": {"cache_ttl_days": 9, "keyword_metrics": {
            "engine": "bing", "locale": "fr-CA", "device": "mobile",
            "max_keywords": 3, "rows_per_call": 7,
        }}})
        self.assertEqual(c._engine, "bing")
        self.assertEqual(c._locale, "fr-CA")
        self.assertEqual(c._device, "mobile")
        self.assertEqual(c._max_keywords, 3)
        self.assertEqual(c._rows_per_call, 7)
        self.assertEqual(c._cache_ttl, timedelta(days=9))

    def test_t2_from_config_falls_back_when_absent(self):
        c = self._client({})
        self.assertEqual(c._engine, moz_keywords.DEFAULT_ENGINE)
        self.assertEqual(c._locale, moz_keywords.DEFAULT_LOCALE)
        self.assertEqual(c._max_keywords, moz_keywords.DEFAULT_MAX_KEYWORDS)

    def test_t2_shipped_config_enables_keyword_metrics(self):
        """Gate D-2: keyword metrics are ON by default."""
        import yaml
        with open("config.yml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        kw = cfg["moz"]["keyword_metrics"]
        self.assertTrue(kw["enabled"])
        self.assertIsInstance(kw["max_keywords"], int)


class TestBriefWiring(unittest.TestCase):
    """T.2 — the block must reach the brief payload, per front end (P25)."""

    @staticmethod
    def _extract(moz_keyword_metrics):
        """Run the real extractor over the shared sample fixture."""
        from test_generate_content_brief import TestGenerateContentBrief as _T
        data = _T._sample_data(_T)
        return brief_data_extraction.extract_analysis_data_from_json(
            data, "livingsystems.ca", ["Living Systems"],
            moz_keyword_metrics=moz_keyword_metrics,
        )

    def test_t2_extraction_attaches_the_moz_block_per_keyword(self):
        extracted = self._extract(
            {"estrangement": {"data_available": True, "status": STATUS_OK,
                              "volume": 373, "difficulty": 22}}
        )
        block = extracted["keyword_profiles"]["estrangement"]["moz"]
        self.assertTrue(block["data_available"])
        self.assertEqual(block["volume"], 373)

    def test_t2_extraction_marks_unfetched_keywords_explicitly(self):
        """A keyword with no entry says "not_fetched" — distinguishable from
        "Moz has no record", and never silently absent (P2)."""
        extracted = self._extract({})
        block = extracted["keyword_profiles"]["estrangement"]["moz"]
        self.assertFalse(block["data_available"])
        self.assertEqual(block["status"], "not_fetched")

    def test_t2_extraction_without_the_argument_still_carries_the_block(self):
        """Every caller that has not been updated still gets an honest block."""
        from test_generate_content_brief import TestGenerateContentBrief as _T
        extracted = brief_data_extraction.extract_analysis_data_from_json(
            _T._sample_data(_T), "livingsystems.ca", ["Living Systems"]
        )
        self.assertEqual(
            extracted["keyword_profiles"]["estrangement"]["moz"]["status"],
            "not_fetched",
        )

    def test_t2_extractor_accepts_the_parameter(self):
        import inspect
        sig = inspect.signature(
            brief_data_extraction.extract_analysis_data_from_json
        )
        self.assertIn("moz_keyword_metrics", sig.parameters)

    def test_t2_extractor_defaults_to_a_not_fetched_block(self):
        """A keyword with no entry must say so, not be silently absent —
        "not_fetched" and "no_record" are different facts (P2)."""
        tree = ast.parse(open("brief_data_extraction.py", encoding="utf-8").read())
        literals = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == "not_fetched"
        ]
        self.assertTrue(literals, "extraction has no not_fetched fallback")

    def test_t2_brief_rendering_passes_the_metrics_to_the_extractor(self):
        """The front end must actually pass the argument, not merely have
        access to it (P25)."""
        tree = ast.parse(open("brief_rendering.py", encoding="utf-8").read())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "extract_analysis_data_from_json"
        ]
        self.assertTrue(calls, "brief_rendering never calls the extractor")
        for call in calls:
            names = {kw.arg for kw in call.keywords}
            self.assertIn("moz_keyword_metrics", names)

    def test_t2_fetch_helper_respects_the_enabled_flags(self):
        import brief_rendering
        data = {"organic_results": [
            {"Query_Label": "A", "Source_Keyword": "kw", "Link": "x"}]}
        self.assertEqual(
            brief_rendering._fetch_moz_keyword_metrics(
                data, {"moz": {"enabled": False}}), {})
        self.assertEqual(
            brief_rendering._fetch_moz_keyword_metrics(
                data, {"moz": {"keyword_metrics": {"enabled": False}}}), {})

    def test_t2_fetch_helper_passes_root_keywords_only(self):
        import brief_rendering
        data = {"organic_results": [
            {"Query_Label": "A", "Source_Keyword": "root kw", "Link": "x"},
            {"Query_Label": "B", "Source_Keyword": "variant kw", "Link": "y"},
        ]}
        fake = MagicMock()
        fake.fetch.return_value = {}
        with patch("moz_keywords.MozKeywordClient.from_config", return_value=fake):
            brief_rendering._fetch_moz_keyword_metrics(data, {"moz": {}})
        fake.fetch.assert_called_once_with(["root kw"])


if __name__ == "__main__":
    unittest.main()
