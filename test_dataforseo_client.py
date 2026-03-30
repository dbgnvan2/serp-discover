"""
test_dataforseo_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for DataForSEOClient. All HTTP calls are mocked.
"""
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

DFS_ENV = {
    "DATAFORSEO_LOGIN": "test@example.com",
    "DATAFORSEO_PASSWORD": "testpassword",
}


def _make_dfs_response(domains: list[str], rank: int = 40) -> MagicMock:
    """Build a mock DataForSEO bulk_domain_metrics response."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "tasks": [
            {
                "status_code": 20000,
                "status_message": "Ok.",
                "result": [
                    {
                        "items_count": len(domains),
                        "items": [
                            {"target": domain, "rank": rank}
                            for domain in domains
                        ],
                    }
                ],
            }
        ]
    }
    return mock_resp


class TestDataForSEOClientInit(unittest.TestCase):

    def test_missing_login_raises(self):
        with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "", "DATAFORSEO_PASSWORD": "pw"}):
            from dataforseo_client import DataForSEOClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                with self.assertRaises(RuntimeError):
                    DataForSEOClient(db_path=f.name)

    def test_missing_password_raises(self):
        with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "user@x.com", "DATAFORSEO_PASSWORD": ""}):
            from dataforseo_client import DataForSEOClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                with self.assertRaises(RuntimeError):
                    DataForSEOClient(db_path=f.name)

    def test_valid_credentials_do_not_raise(self):
        with patch.dict(os.environ, DFS_ENV):
            from dataforseo_client import DataForSEOClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = DataForSEOClient(db_path=f.name)
                self.assertIsNotNone(client)

    def test_auth_header_is_basic(self):
        with patch.dict(os.environ, DFS_ENV):
            from dataforseo_client import DataForSEOClient
            with tempfile.NamedTemporaryFile(suffix=".db") as f:
                client = DataForSEOClient(db_path=f.name)
                self.assertTrue(client._auth_header["Authorization"].startswith("Basic "))


class TestDataForSEOClientCacheTable(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, DFS_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from dataforseo_client import DataForSEOClient
        self.client = DataForSEOClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    def test_cache_table_created(self):
        with sqlite3.connect(self.tmp.name) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        self.assertIn("da_cache", tables)

    def test_empty_url_list_returns_empty(self):
        self.assertEqual(self.client.get_domain_metrics([]), {})


class TestDataForSEOClientDomainDedup(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, DFS_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from dataforseo_client import DataForSEOClient
        self.client = DataForSEOClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("dataforseo_client.requests.post")
    def test_multiple_urls_same_domain_one_api_call(self, mock_post):
        urls = [
            "https://psychologytoday.com/page1",
            "https://psychologytoday.com/page2",
            "https://psychologytoday.com/page3",
        ]
        mock_post.return_value = _make_dfs_response(["psychologytoday.com"], rank=91)
        result = self.client.get_domain_metrics(urls)
        # Only one domain → one batch → one API call
        self.assertEqual(mock_post.call_count, 1)
        sent = mock_post.call_args.kwargs["json"][0]["targets"]
        self.assertEqual(len(sent), 1)
        # All three URLs get the same DA
        for url in urls:
            self.assertEqual(result[url]["da"], 91)

    @patch("dataforseo_client.requests.post")
    def test_www_prefix_stripped(self, mock_post):
        url = "https://www.example.com/page"
        mock_post.return_value = _make_dfs_response(["example.com"], rank=55)
        result = self.client.get_domain_metrics([url])
        sent = mock_post.call_args.kwargs["json"][0]["targets"]
        self.assertIn("example.com", sent)
        self.assertNotIn("www.example.com", sent)
        self.assertEqual(result[url]["da"], 55)

    @patch("dataforseo_client.requests.post")
    def test_da_and_pa_both_set_to_domain_rank(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_dfs_response(["example.com"], rank=62)
        result = self.client.get_domain_metrics([url])
        self.assertEqual(result[url]["da"], 62)
        self.assertEqual(result[url]["pa"], 62)


class TestDataForSEOClientCache(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, DFS_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from dataforseo_client import DataForSEOClient
        self.client = DataForSEOClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("dataforseo_client.requests.post")
    def test_cache_hit_avoids_http_call(self, mock_post):
        domain = "example.com"
        now = datetime.now(_UTC).isoformat()
        self.client._cache_store({domain: {"da": 50, "pa": 50, "fetched_at": now}})
        result = self.client.get_domain_metrics(["https://example.com/page"])
        mock_post.assert_not_called()
        self.assertEqual(result["https://example.com/page"]["da"], 50)

    @patch("dataforseo_client.requests.post")
    def test_expired_cache_triggers_api_call(self, mock_post):
        domain = "example.com"
        old = (datetime.now(_UTC) - timedelta(days=60)).isoformat()
        self.client._cache_store({domain: {"da": 30, "pa": 30, "fetched_at": old}})
        mock_post.return_value = _make_dfs_response([domain], rank=45)
        result = self.client.get_domain_metrics(["https://example.com/"])
        mock_post.assert_called_once()
        self.assertEqual(result["https://example.com/"]["da"], 45)

    @patch("dataforseo_client.requests.post")
    def test_results_written_to_cache(self, mock_post):
        url = "https://example.com/"
        mock_post.return_value = _make_dfs_response(["example.com"], rank=33)
        self.client.get_domain_metrics([url])
        mock_post.reset_mock()
        result = self.client.get_domain_metrics([url])
        mock_post.assert_not_called()
        self.assertEqual(result[url]["da"], 33)

    @patch("dataforseo_client.requests.post")
    def test_partial_cache_fetches_only_missing(self, mock_post):
        cached_url = "https://cached.com/"
        fresh_url = "https://fresh.com/"
        now = datetime.now(_UTC).isoformat()
        self.client._cache_store({"cached.com": {"da": 50, "pa": 50, "fetched_at": now}})
        mock_post.return_value = _make_dfs_response(["fresh.com"], rank=25)
        result = self.client.get_domain_metrics([cached_url, fresh_url])
        sent = mock_post.call_args.kwargs["json"][0]["targets"]
        self.assertIn("fresh.com", sent)
        self.assertNotIn("cached.com", sent)
        self.assertIn(cached_url, result)
        self.assertIn(fresh_url, result)


class TestDataForSEOClientErrorHandling(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, DFS_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from dataforseo_client import DataForSEOClient
        self.client = DataForSEOClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    @patch("dataforseo_client.requests.post")
    def test_http_error_returns_empty(self, mock_post):
        mock_post.side_effect = requests.RequestException("connection refused")
        result = self.client.get_domain_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch("dataforseo_client.requests.post")
    def test_non_200_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Unauthorized"}
        mock_post.return_value = mock_resp
        result = self.client.get_domain_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch("dataforseo_client.requests.post")
    def test_task_error_status_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "tasks": [{"status_code": 40000, "status_message": "Bad Request", "result": None}]
        }
        mock_post.return_value = mock_resp
        result = self.client.get_domain_metrics(["https://example.com/"])
        self.assertEqual(result, {})

    @patch("dataforseo_client.requests.post")
    def test_non_json_response_returns_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_post.return_value = mock_resp
        result = self.client.get_domain_metrics(["https://example.com/"])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
