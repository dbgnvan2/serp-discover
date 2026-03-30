"""
test_moz_client.py
~~~~~~~~~~~~~~~~~~
Tests for MozClient.  All HTTP calls are mocked — no real network or
Moz credentials required.
"""

import os
import sqlite3
import tempfile
import unittest
from base64 import b64encode
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc


def _make_moz_response(urls: list[str], da: int = 40, pa: int = 30) -> MagicMock:
    """Build a mock requests.Response for a Moz url_metrics call."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"url": url, "domain_authority": da, "page_authority": pa}
            for url in urls
        ]
    }
    return mock_resp


class TestMozClientInit(unittest.TestCase):

    def test_missing_access_id_raises(self):
        with patch.dict(os.environ, {"MOZ_ACCESS_ID": "", "MOZ_SECRET_KEY": "secret"}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                with self.assertRaises(RuntimeError):
                    MozClient(db_path=f.name)

    def test_missing_secret_key_raises(self):
        with patch.dict(os.environ, {"MOZ_ACCESS_ID": "myid", "MOZ_SECRET_KEY": ""}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                with self.assertRaises(RuntimeError):
                    MozClient(db_path=f.name)

    def test_valid_credentials_do_not_raise(self):
        with patch.dict(os.environ, {"MOZ_ACCESS_ID": "myid", "MOZ_SECRET_KEY": "secret"}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = MozClient(db_path=f.name)
                self.assertIsNotNone(client)

    def test_auth_header_is_basic_auth(self):
        with patch.dict(os.environ, {"MOZ_ACCESS_ID": "myid", "MOZ_SECRET_KEY": "mysecret"}):
            from moz_client import MozClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = MozClient(db_path=f.name)
                expected = "Basic " + b64encode(b"myid:mysecret").decode()
                self.assertEqual(client._auth_header["Authorization"], expected)


class TestMozClientCacheTable(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, {"MOZ_ACCESS_ID": "id", "MOZ_SECRET_KEY": "secret"})
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from moz_client import MozClient
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    def test_cache_table_created(self):
        with sqlite3.connect(self.tmp.name) as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        self.assertIn("moz_cache", tables)

    def test_empty_url_list_returns_empty(self):
        result = self.client.get_moz_metrics([])
        self.assertEqual(result, {})


class TestMozClientBatching(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, {"MOZ_ACCESS_ID": "id", "MOZ_SECRET_KEY": "secret"})
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from moz_client import MozClient
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("moz_client.requests.post")
    def test_60_urls_calls_fetch_3_times(self, mock_post):
        urls = [f"https://example{i}.com/" for i in range(60)]
        mock_post.side_effect = lambda *a, **kw: _make_moz_response(
            kw["json"]["targets"]
        )
        self.client.get_moz_metrics(urls)
        self.assertEqual(mock_post.call_count, 3)

    @patch("moz_client.requests.post")
    def test_25_urls_calls_fetch_once(self, mock_post):
        urls = [f"https://example{i}.com/" for i in range(25)]
        mock_post.return_value = _make_moz_response(urls)
        self.client.get_moz_metrics(urls)
        self.assertEqual(mock_post.call_count, 1)

    @patch("moz_client.requests.post")
    def test_duplicate_urls_deduplicated(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url])
        self.client.get_moz_metrics([url, url, url])
        # Only one unique URL, so one API call
        self.assertEqual(mock_post.call_count, 1)
        # Payload should contain the URL only once
        sent_targets = mock_post.call_args.kwargs["json"]["targets"]
        self.assertEqual(sent_targets.count(url), 1)

    @patch("moz_client.requests.post")
    def test_results_contain_da_and_pa(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], da=55, pa=42)
        result = self.client.get_moz_metrics([url])
        self.assertEqual(result[url]["da"], 55)
        self.assertEqual(result[url]["pa"], 42)


class TestMozClientCache(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, {"MOZ_ACCESS_ID": "id", "MOZ_SECRET_KEY": "secret"})
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from moz_client import MozClient
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("moz_client.requests.post")
    def test_cache_hit_avoids_http_call(self, mock_post):
        url = "https://example.com/"
        # Pre-populate the cache
        self.client._cache_store({
            url: {"da": 50, "pa": 35, "fetched_at": datetime.now(_UTC).isoformat()}
        })
        result = self.client.get_moz_metrics([url])
        mock_post.assert_not_called()
        self.assertEqual(result[url]["da"], 50)

    @patch("moz_client.requests.post")
    def test_expired_cache_triggers_http_call(self, mock_post):
        url = "https://example.com/"
        # Store an entry older than the TTL
        old_date = (datetime.now(_UTC) - timedelta(days=60)).isoformat()
        self.client._cache_store({
            url: {"da": 50, "pa": 35, "fetched_at": old_date}
        })
        mock_post.return_value = _make_moz_response([url], da=55)
        result = self.client.get_moz_metrics([url])
        mock_post.assert_called_once()
        # Fresh result from API should overwrite stale cache
        self.assertEqual(result[url]["da"], 55)

    @patch("moz_client.requests.post")
    def test_results_written_to_cache(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_moz_response([url], da=45)
        self.client.get_moz_metrics([url])

        # Second call should hit cache, not API
        mock_post.reset_mock()
        result = self.client.get_moz_metrics([url])
        mock_post.assert_not_called()
        self.assertEqual(result[url]["da"], 45)

    @patch("moz_client.requests.post")
    def test_partial_cache_fetches_only_missing(self, mock_post):
        cached_url = "https://cached.com/"
        fresh_url = "https://fresh.com/"
        self.client._cache_store({
            cached_url: {"da": 50, "pa": 35, "fetched_at": datetime.now(_UTC).isoformat()}
        })
        mock_post.return_value = _make_moz_response([fresh_url], da=30)
        result = self.client.get_moz_metrics([cached_url, fresh_url])
        # Only one HTTP call for the uncached URL
        self.assertEqual(mock_post.call_count, 1)
        sent = mock_post.call_args.kwargs["json"]["targets"]
        self.assertIn(fresh_url, sent)
        self.assertNotIn(cached_url, sent)
        self.assertIn(cached_url, result)
        self.assertIn(fresh_url, result)


class TestMozClientErrorHandling(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, {"MOZ_ACCESS_ID": "id", "MOZ_SECRET_KEY": "secret"})
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from moz_client import MozClient
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("moz_client.requests.post")
    def test_http_error_returns_empty_not_raises(self, mock_post):
        mock_post.side_effect = requests.RequestException("connection refused")
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch("moz_client.requests.post")
    def test_partial_batch_failure_returns_successful_batches(self, mock_post):
        """First batch fails, second succeeds — second results still returned."""
        urls_batch1 = [f"https://fail{i}.com/" for i in range(25)]
        urls_batch2 = [f"https://ok{i}.com/" for i in range(5)]
        all_urls = urls_batch1 + urls_batch2

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.RequestException("timeout")
            return _make_moz_response(kwargs["json"]["targets"], da=33)

        mock_post.side_effect = side_effect
        result = self.client.get_moz_metrics(all_urls)
        # Batch 2 results should be present even though batch 1 failed
        for url in urls_batch2:
            self.assertIn(url, result)
        for url in urls_batch1:
            self.assertNotIn(url, result)

    @patch("moz_client.requests.post")
    def test_non_json_response_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_post.return_value = mock_resp
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch("moz_client.requests.post")
    def test_http_status_error_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        mock_post.return_value = mock_resp
        result = self.client.get_moz_metrics(["https://example.com/"])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
