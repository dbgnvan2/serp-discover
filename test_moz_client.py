"""
test_moz_client.py
~~~~~~~~~~~~~~~~~~
Tests for MozClient.  All HTTP calls are mocked — no real network or
Moz credentials required.

Spec: moz_api_upgrade_spec_v1.md#T.1
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

MOZ_ENV = {"MOZ_TOKEN": "test-token-abc123"}

# The JSON-RPC transport owns the HTTP call now, so that is where requests is
# patched. Response bodies below mirror the shape captured from a real
# data.site.metrics.fetch.multiple call on 2026-08-28 (learnings P19).
POST_TARGET = "moz_jsonrpc.requests.post"

#: A trimmed but faithful subset of the real site_metrics object.
SAMPLE_LINK_COUNTS = {
    "root_domains_to_root_domain": 157,
    "external_pages_to_root_domain": 756,
    "nofollow_root_domains_to_root_domain": 71,
    "root_domains_to_page": 112,
    "external_pages_to_page": 298,
    "pages_to_page": 481,
}


def _site_metrics(url: str, da: int, pa: int, spam=1, extra=None) -> dict:
    metrics = {
        "page": url.removeprefix("https://").removeprefix("http://"),
        "domain_authority": da,
        "page_authority": pa,
        "link_propensity": 0.147,
        **SAMPLE_LINK_COUNTS,
    }
    if spam is not None:
        metrics["spam_score"] = spam
    if extra:
        metrics.update(extra)
    return metrics


def _make_moz_response(
    urls: list[str], da: int = 40, pa: int = 30, spam=1,
    errors: list | None = None, omit: set | None = None,
) -> MagicMock:
    """Build a mock JSON-RPC response for data.site.metrics.fetch.multiple."""
    omit = omit or set()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": "b1b39f52-0520-4eb8-9bda-b1cb642c98f6",
        "result": {
            "results_by_site": [
                {
                    "site_query": {
                        "query": url,
                        "scope": "url",
                        "original_site_query": {"query": url, "scope": "url"},
                        "site_query_suggestion": None,
                    },
                    "site_metrics": _site_metrics(url, da, pa, spam),
                }
                for url in urls if url not in omit
            ],
            "errors_by_site": errors or [],
        },
    }
    return mock_resp


def _sent_queries(mock_post) -> list[dict]:
    """Return the site_queries list from the last posted envelope."""
    return mock_post.call_args.kwargs["json"]["params"]["data"]["site_queries"]


def _sent_targets(mock_post) -> list[str]:
    return [q["query"] for q in _sent_queries(mock_post)]


class TestMozClientInit(unittest.TestCase):

    def test_missing_token_raises(self):
        with patch.dict(os.environ, {"MOZ_TOKEN": ""}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                with self.assertRaises(RuntimeError):
                    MozClient(db_path=f.name)

    def test_valid_token_does_not_raise(self):
        with patch.dict(os.environ, MOZ_ENV):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = MozClient(db_path=f.name)
                self.assertIsNotNone(client)

    def test_auth_header_uses_x_moz_token(self):
        with patch.dict(os.environ, {"MOZ_TOKEN": "mytoken123"}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = MozClient(db_path=f.name)
                self.assertEqual(client._auth_header["x-moz-token"], "mytoken123")


class _ClientTestCase(unittest.TestCase):
    """Shared fixture: a client backed by a throwaway SQLite file."""

    def setUp(self):
        self.env = patch.dict(os.environ, MOZ_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from moz_client import MozClient
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)


class TestMozClientCacheTable(_ClientTestCase):

    def test_cache_table_created(self):
        with sqlite3.connect(self.tmp.name) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='moz_cache'"
            ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_empty_url_list_returns_empty(self):
        self.assertEqual(self.client.get_moz_metrics([]), {})


class TestMozClientBatching(_ClientTestCase):

    @patch(POST_TARGET)
    def test_100_urls_calls_fetch_twice(self, mock_post):
        urls = [f"https://example{i}.com/" for i in range(100)]
        mock_post.side_effect = lambda *a, **kw: _make_moz_response(
            [q["query"] for q in kw["json"]["params"]["data"]["site_queries"]]
        )
        self.client.get_moz_metrics(urls)
        self.assertEqual(mock_post.call_count, 2)

    @patch(POST_TARGET)
    def test_50_urls_calls_fetch_once(self, mock_post):
        urls = [f"https://example{i}.com/" for i in range(50)]
        mock_post.return_value = _make_moz_response(urls)
        self.client.get_moz_metrics(urls)
        self.assertEqual(mock_post.call_count, 1)

    @patch(POST_TARGET)
    def test_duplicate_urls_deduplicated(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url])
        self.client.get_moz_metrics([url, url, url])
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(_sent_targets(mock_post).count(url), 1)

    @patch(POST_TARGET)
    def test_results_contain_da_and_pa(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], da=55, pa=42)
        result = self.client.get_moz_metrics([url])
        self.assertEqual(result[url]["da"], 55)
        self.assertEqual(result[url]["pa"], 42)


class TestSiteMetricsContract(_ClientTestCase):
    """T.1 — the data.site.metrics contract and its new additive fields."""

    @patch(POST_TARGET)
    def test_t1_calls_the_site_metrics_multiple_method(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url])
        self.client.get_moz_metrics([url])
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["method"], "data.site.metrics.fetch.multiple")

    @patch(POST_TARGET)
    def test_t1_site_query_carries_the_configured_scope(self, mock_post):
        from moz_client import MozClient
        client = MozClient(db_path=self.tmp.name, scope="subdomain")
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url])
        client.get_moz_metrics([url])
        self.assertEqual(_sent_queries(mock_post)[0]["scope"], "subdomain")

    @patch(POST_TARGET)
    def test_t1_results_are_keyed_by_the_callers_input_url(self, mock_post):
        """The key contract serp_audit.py depends on: `url in moz_results`.

        The legacy path keyed by the response's scheme-stripped URL, so that
        lookup never matched and the DA writeback silently never fired (P2/P22).
        """
        url = "https://www.example.com/some/page"
        mock_post.return_value = _make_moz_response([url], da=61)
        result = self.client.get_moz_metrics([url])
        self.assertIn(url, result)
        self.assertEqual(result[url]["da"], 61)
        self.assertNotIn("www.example.com/some/page", result)

    @patch(POST_TARGET)
    def test_t1_spam_score_and_link_counts_returned(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], spam=7)
        entry = self.client.get_moz_metrics([url])[url]
        self.assertEqual(entry["spam_score"], 7)
        self.assertEqual(
            entry["link_counts"]["root_domains_to_root_domain"],
            SAMPLE_LINK_COUNTS["root_domains_to_root_domain"],
        )

    @patch(POST_TARGET)
    def test_t1_absent_spam_score_is_none_not_zero(self, mock_post):
        """Design principle 3 — a fabricated 0 would read as "clean site"."""
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], spam=None)
        entry = self.client.get_moz_metrics([url])[url]
        self.assertIsNone(entry["spam_score"])

    @patch(POST_TARGET)
    def test_t1_link_count_fields_are_configurable(self, mock_post):
        from moz_client import MozClient
        client = MozClient(
            db_path=self.tmp.name,
            link_count_fields=["root_domains_to_page"],
        )
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url])
        entry = client.get_moz_metrics([url])[url]
        self.assertEqual(list(entry["link_counts"]), ["root_domains_to_page"])

    @patch(POST_TARGET)
    def test_t1_targets_with_no_metrics_are_counted_in_the_log(self, mock_post):
        """P2 — a dropped target must be announced, not silently vanish."""
        urls = ["https://a.com/", "https://b.com/"]
        mock_post.return_value = _make_moz_response(urls, omit={"https://b.com/"})
        with self.assertLogs("moz_client", level="WARNING") as logs:
            result = self.client.get_moz_metrics(urls)
        self.assertNotIn("https://b.com/", result)
        self.assertTrue(any("1 of 2" in line for line in logs.output))

    @patch(POST_TARGET)
    def test_t1_errors_by_site_are_logged(self, mock_post):
        urls = ["https://a.com/"]
        mock_post.return_value = _make_moz_response(
            urls, errors=[{"query": "https://a.com/", "error": "not found"}]
        )
        with self.assertLogs("moz_client", level="WARNING") as logs:
            self.client.get_moz_metrics(urls)
        self.assertTrue(any("errors for" in line for line in logs.output))


class TestCacheMigration(_ClientTestCase):
    """T.1 — the moz_cache migration must be idempotent and legacy-safe."""

    def test_t1_migration_adds_spam_score_and_link_counts(self):
        with sqlite3.connect(self.tmp.name) as conn:
            columns = {
                row[1] for row in
                conn.execute("PRAGMA table_info(moz_cache)").fetchall()
            }
        self.assertIn("spam_score", columns)
        self.assertIn("link_counts", columns)

    def test_t1_migration_is_idempotent_on_a_legacy_table(self):
        """A DB written by the pre-T.1 client upgrades in place, twice over."""
        from moz_client import MozClient
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            legacy_db = f.name
        try:
            with sqlite3.connect(legacy_db) as conn:
                conn.execute("""
                    CREATE TABLE moz_cache (
                        url TEXT PRIMARY KEY,
                        domain_authority INTEGER,
                        page_authority INTEGER,
                        fetched_at TEXT
                    )
                """)
                conn.execute(
                    "INSERT INTO moz_cache VALUES (?,?,?,?)",
                    ("legacy.com/", 42, 33, datetime.now(_UTC).isoformat()),
                )
                conn.commit()
            MozClient(db_path=legacy_db)
            MozClient(db_path=legacy_db)  # second construction must not raise
            with sqlite3.connect(legacy_db) as conn:
                columns = {
                    row[1] for row in
                    conn.execute("PRAGMA table_info(moz_cache)").fetchall()
                }
                surviving = conn.execute(
                    "SELECT domain_authority FROM moz_cache WHERE url='legacy.com/'"
                ).fetchone()
            self.assertIn("spam_score", columns)
            self.assertIn("link_counts", columns)
            self.assertEqual(surviving[0], 42, "migration must preserve rows")
        finally:
            os.unlink(legacy_db)

    @patch(POST_TARGET)
    def test_t1_legacy_cache_row_still_hits_after_migration(self, mock_post):
        """P8 dirty-state: a row written by the legacy client must still hit.

        Legacy rows are keyed scheme-stripped and have no spam/link columns —
        the lookup normalises the input URL to the same key, and the absent
        columns come back as None/{} rather than blocking the hit.
        """
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(
                "INSERT INTO moz_cache (url, domain_authority, page_authority, "
                "fetched_at) VALUES (?,?,?,?)",
                ("example.com/page", 51, 40, datetime.now(_UTC).isoformat()),
            )
            conn.commit()
        result = self.client.get_moz_metrics(["https://example.com/page"])
        mock_post.assert_not_called()
        entry = result["https://example.com/page"]
        self.assertEqual(entry["da"], 51)
        self.assertIsNone(entry["spam_score"])
        self.assertEqual(entry["link_counts"], {})

    @patch(POST_TARGET)
    def test_t1_spam_and_link_counts_round_trip_through_the_cache(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], spam=4)
        self.client.get_moz_metrics([url])

        mock_post.reset_mock()
        entry = self.client.get_moz_metrics([url])[url]
        mock_post.assert_not_called()
        self.assertEqual(entry["spam_score"], 4)
        self.assertEqual(entry["link_counts"], SAMPLE_LINK_COUNTS)

    def test_t1_unreadable_link_counts_blob_degrades_to_empty(self):
        from moz_client import _decode_link_counts
        self.assertEqual(_decode_link_counts("{not json"), {})
        self.assertEqual(_decode_link_counts(None), {})
        self.assertEqual(_decode_link_counts('["a list"]'), {})
        self.assertEqual(_decode_link_counts('{"a": 1}'), {"a": 1})


class TestMozClientCache(_ClientTestCase):

    @patch(POST_TARGET)
    def test_cache_hit_avoids_http_call(self, mock_post):
        url = "https://example.com/"
        self.client._cache_store({
            url: {"da": 50, "pa": 35, "fetched_at": datetime.now(_UTC).isoformat()}
        })
        result = self.client.get_moz_metrics([url])
        mock_post.assert_not_called()
        self.assertEqual(result[url]["da"], 50)

    @patch(POST_TARGET)
    def test_expired_cache_triggers_http_call(self, mock_post):
        url = "https://example.com/"
        old_date = (datetime.now(_UTC) - timedelta(days=60)).isoformat()
        self.client._cache_store({
            url: {"da": 50, "pa": 35, "fetched_at": old_date}
        })
        mock_post.return_value = _make_moz_response([url], da=55)
        result = self.client.get_moz_metrics([url])
        mock_post.assert_called_once()
        self.assertEqual(result[url]["da"], 55)

    @patch(POST_TARGET)
    def test_results_written_to_cache(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], da=45)
        self.client.get_moz_metrics([url])

        mock_post.reset_mock()
        result = self.client.get_moz_metrics([url])
        mock_post.assert_not_called()
        self.assertEqual(result[url]["da"], 45)

    @patch(POST_TARGET)
    def test_partial_cache_fetches_only_missing(self, mock_post):
        cached_url = "https://cached.com/"
        fresh_url = "https://fresh.com/"
        self.client._cache_store({
            cached_url: {"da": 50, "pa": 35, "fetched_at": datetime.now(_UTC).isoformat()}
        })
        mock_post.return_value = _make_moz_response([fresh_url], da=30)
        result = self.client.get_moz_metrics([cached_url, fresh_url])
        self.assertEqual(mock_post.call_count, 1)
        sent = _sent_targets(mock_post)
        self.assertIn(fresh_url, sent)
        self.assertNotIn(cached_url, sent)
        self.assertIn(cached_url, result)
        self.assertIn(fresh_url, result)


@patch("http_retry.time.sleep", lambda *_: None)
class TestMozClientErrorHandling(_ClientTestCase):

    @patch(POST_TARGET)
    def test_http_error_returns_empty_not_raises(self, mock_post):
        mock_post.side_effect = requests.RequestException("connection refused")
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch(POST_TARGET)
    def test_partial_batch_failure_returns_successful_batches(self, mock_post):
        """First batch fails, second succeeds — second results still returned."""
        urls_batch1 = [f"https://fail{i}.com/" for i in range(50)]
        urls_batch2 = [f"https://ok{i}.com/" for i in range(5)]
        all_urls = urls_batch1 + urls_batch2

        def side_effect(*args, **kwargs):
            targets = [
                q["query"] for q in
                kwargs["json"]["params"]["data"]["site_queries"]
            ]
            if targets and "fail" in targets[0]:
                raise requests.RequestException("timeout")
            return _make_moz_response(targets, da=33)

        mock_post.side_effect = side_effect
        result = self.client.get_moz_metrics(all_urls)
        for url in urls_batch2:
            self.assertIn(url, result)
        for url in urls_batch1:
            self.assertNotIn(url, result)

    @patch(POST_TARGET)
    def test_non_json_response_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        mock_post.return_value = mock_resp
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch(POST_TARGET)
    def test_http_status_error_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": "Forbidden"}
        mock_resp.text = "Forbidden"
        mock_post.return_value = mock_resp
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch(POST_TARGET)
    def test_t1_jsonrpc_error_returns_empty_not_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0", "id": "x" * 24,
            "error": {"code": -32652, "message": "Invalid params"},
        }
        mock_post.return_value = mock_resp
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
