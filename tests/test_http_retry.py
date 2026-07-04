"""
Tests for http_retry — transient-error retry shared by the DA clients.

Spec: seo_geo_review_20260704.md C.6
"""
import unittest
from unittest.mock import MagicMock, patch

import requests

from http_retry import post_with_transient_retry


def _response(status=200, retry_after=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.headers = {"Retry-After": retry_after} if retry_after else {}
    return resp


@patch("http_retry.time.sleep")
class TestPostWithTransientRetry(unittest.TestCase):

    def test_network_error_then_success_recovers(self, _sleep):
        ok = _response(200)
        post = MagicMock(side_effect=[requests.RequestException("boom"), ok])
        result = post_with_transient_retry("X", "http://u", {}, {}, "b", post=post)
        self.assertIs(result, ok)
        self.assertEqual(post.call_count, 2)

    def test_persistent_network_error_returns_none(self, _sleep):
        post = MagicMock(side_effect=requests.RequestException("boom"))
        result = post_with_transient_retry("X", "http://u", {}, {}, "b", post=post)
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 2)

    def test_transient_status_is_retried(self, _sleep):
        ok = _response(200)
        post = MagicMock(side_effect=[_response(503), ok])
        result = post_with_transient_retry("X", "http://u", {}, {}, "b", post=post)
        self.assertIs(result, ok)
        self.assertEqual(post.call_count, 2)

    def test_retry_after_header_honored_and_capped(self, sleep):
        ok = _response(200)
        post = MagicMock(side_effect=[_response(429, retry_after="120"), ok])
        post_with_transient_retry("X", "http://u", {}, {}, "b", post=post)
        # 120s Retry-After capped at 30s
        sleep.assert_called_once_with(30.0)

    def test_non_transient_status_not_retried(self, _sleep):
        unauthorized = _response(401)
        post = MagicMock(return_value=unauthorized)
        result = post_with_transient_retry("X", "http://u", {}, {}, "b", post=post)
        self.assertIs(result, unauthorized)
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
