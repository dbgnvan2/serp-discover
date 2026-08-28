"""
test_moz_jsonrpc.py
~~~~~~~~~~~~~~~~~~~
Tests for the Moz Data API JSON-RPC transport.

Spec: moz_api_upgrade_spec_v1.md#T.0

Every HTTP call is mocked — no real network, no Moz credentials required
(CLAUDE.md: "Tests do not require API keys").
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from moz_jsonrpc import (
    MOZ_JSONRPC_ENDPOINT,
    MozRpcError,
    build_envelope,
    moz_call,
    parse_quota,
    quota_lookup,
    quota_status,
)

TEST_TOKEN = "moz-token-0123456789abcdef"
MOZ_ENV = {"MOZ_TOKEN": TEST_TOKEN}


def _rpc_response(result: dict, status: int = 200) -> MagicMock:
    """Build a mock requests.Response carrying a JSON-RPC success body."""
    resp = MagicMock()
    resp.ok = 200 <= status < 300
    resp.status_code = status
    resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": "b1b39f52-0520-4eb8-9bda-b1cb642c98f6",
        "result": result,
    }
    return resp


def _error_response(body: dict, status: int) -> MagicMock:
    """Build a mock requests.Response carrying an HTTP error body."""
    resp = MagicMock()
    resp.ok = 200 <= status < 300
    resp.status_code = status
    resp.json.return_value = body
    resp.text = str(body)
    return resp


class TestEnvelope(unittest.TestCase):
    """T.0 — the JSON-RPC 2.0 envelope shape is binding (spec, Moz docs)."""

    def test_t0_envelope_has_jsonrpc_version_method_and_data(self):
        env = build_envelope("data.site.metrics.fetch", {"site_query": {}})
        self.assertEqual(env["jsonrpc"], "2.0")
        self.assertEqual(env["method"], "data.site.metrics.fetch")
        self.assertEqual(env["params"], {"data": {"site_query": {}}})

    def test_t0_envelope_id_is_at_least_24_chars(self):
        env = build_envelope("quota.lookup", {})
        self.assertGreaterEqual(len(env["id"]), 24)

    def test_t0_envelope_id_is_unique_per_call(self):
        first = build_envelope("quota.lookup", {})["id"]
        second = build_envelope("quota.lookup", {})["id"]
        self.assertNotEqual(first, second)


class TestMozCall(unittest.TestCase):

    @patch("moz_jsonrpc.requests.post")
    def test_t0_missing_token_raises_runtimeerror(self, mock_post):
        """Same discipline as MozClient: absent token is a RuntimeError.

        `requests.post` is mocked with a *success* response so removing the
        guard makes this test go green-free: it would then return normally
        and raise nothing. Asserting a bare RuntimeError is not enough —
        MozRpcError subclasses it, so an unguarded call reaching the network
        and failing would satisfy assertRaises for the wrong reason.
        """
        mock_post.return_value = _rpc_response(QUOTA_RESULT_FIXTURE)
        with patch.dict(os.environ, {"MOZ_TOKEN": ""}):
            with self.assertRaises(RuntimeError) as ctx:
                moz_call("quota.lookup", {})
        self.assertNotIsInstance(ctx.exception, MozRpcError)
        self.assertEqual(mock_post.call_count, 0)

    @patch("moz_jsonrpc.requests.post")
    def test_t0_posts_to_jsonrpc_endpoint_with_token_header(self, mock_post):
        mock_post.return_value = _rpc_response({"ok": True})
        with patch.dict(os.environ, MOZ_ENV):
            moz_call("quota.lookup", {"path": "api.limits.data.rows"})
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], MOZ_JSONRPC_ENDPOINT)
        self.assertEqual(kwargs["headers"]["x-moz-token"], TEST_TOKEN)

    @patch("moz_jsonrpc.requests.post")
    def test_t0_posted_payload_is_the_jsonrpc_envelope(self, mock_post):
        mock_post.return_value = _rpc_response({"ok": True})
        with patch.dict(os.environ, MOZ_ENV):
            moz_call("data.keyword.metrics.fetch", {"keyword": "bowen theory"})
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["jsonrpc"], "2.0")
        self.assertEqual(sent["method"], "data.keyword.metrics.fetch")
        self.assertEqual(sent["params"], {"data": {"keyword": "bowen theory"}})
        self.assertGreaterEqual(len(sent["id"]), 24)

    @patch("moz_jsonrpc.requests.post")
    def test_t0_timeout_is_passed_to_the_request(self, mock_post):
        """external-api E1 — every call carries an explicit timeout."""
        mock_post.return_value = _rpc_response({"ok": True})
        with patch.dict(os.environ, MOZ_ENV):
            moz_call("quota.lookup", {}, timeout=7)
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 7)

    @patch("moz_jsonrpc.requests.post")
    def test_t0_returns_the_result_object(self, mock_post):
        mock_post.return_value = _rpc_response({"quota": {"rows_remaining": 42}})
        with patch.dict(os.environ, MOZ_ENV):
            result = moz_call("quota.lookup", {})
        self.assertEqual(result, {"quota": {"rows_remaining": 42}})

    @patch("moz_jsonrpc.requests.post")
    def test_t0_jsonrpc_error_body_raises(self, mock_post):
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = {
            "jsonrpc": "2.0",
            "id": "x" * 24,
            "error": {"code": -32602, "message": "Invalid params"},
        }
        mock_post.return_value = resp
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError) as ctx:
                moz_call("quota.lookup", {})
        self.assertIn("Invalid params", str(ctx.exception))

    @patch("moz_jsonrpc.requests.post")
    def test_t0_missing_result_raises_not_empty_dict(self, mock_post):
        """A body with neither result nor error is a protocol failure."""
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = {"jsonrpc": "2.0", "id": "x" * 24}
        mock_post.return_value = resp
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                moz_call("quota.lookup", {})

    @patch("moz_jsonrpc.requests.post")
    def test_t0_http_4xx_raises_with_body_snippet(self, mock_post):
        mock_post.return_value = _error_response(
            {"status": 403, "message": "Forbidden"}, status=403
        )
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError) as ctx:
                moz_call("quota.lookup", {})
        self.assertIn("403", str(ctx.exception))
        self.assertIn("Forbidden", str(ctx.exception))

    @patch("moz_jsonrpc.requests.post")
    def test_t0_non_json_response_raises(self, mock_post):
        """external-api E2 — an HTML error page must not crash on .json()."""
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.side_effect = ValueError("Expecting value")
        mock_post.return_value = resp
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                moz_call("quota.lookup", {})

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch("moz_jsonrpc.requests.post")
    def test_t0_network_failure_raises_rather_than_returning_empty(self, mock_post):
        """external-api E4 / P2 — "failed" must not look like "found nothing"."""
        import requests as _requests
        mock_post.side_effect = _requests.RequestException("connection reset")
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                moz_call("quota.lookup", {})

    @patch("moz_jsonrpc.requests.post")
    def test_t0_token_echoed_in_error_body_is_redacted(self, mock_post):
        """Adversarial (security S1): the API echoes the token back in its error.

        The literal token must appear nowhere in the raised message, which is
        what gets logged.
        """
        mock_post.return_value = _error_response(
            {"message": f"invalid token {TEST_TOKEN}",
             "request": f"https://api.moz.com/jsonrpc?token={TEST_TOKEN}"},
            status=401,
        )
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError) as ctx:
                moz_call("quota.lookup", {})
        self.assertNotIn(TEST_TOKEN, str(ctx.exception))
        self.assertIn("REDACTED", str(ctx.exception))

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch("moz_jsonrpc.requests.post")
    def test_t0_transient_status_is_retried_then_succeeds(self, mock_post):
        """Behavioural proof the shared retry helper is wired in (P5).

        Asserts the retry happens, not that the source mentions it (P19).
        """
        transient = MagicMock()
        transient.ok = False
        transient.status_code = 503
        transient.headers = {}
        mock_post.side_effect = [transient, _rpc_response({"ok": True})]
        with patch.dict(os.environ, MOZ_ENV):
            result = moz_call("quota.lookup", {})
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result, {"ok": True})


class TestQuotaLookup(unittest.TestCase):

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_lookup_sends_the_data_rows_path(self, mock_post):
        mock_post.return_value = _rpc_response(QUOTA_RESULT_FIXTURE)
        with patch.dict(os.environ, MOZ_ENV):
            quota_lookup()
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["method"], "quota.lookup")
        self.assertEqual(sent["params"]["data"]["path"], "api.limits.data.rows")

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_lookup_parses_remaining_rows(self, mock_post):
        mock_post.return_value = _rpc_response(QUOTA_RESULT_FIXTURE)
        with patch.dict(os.environ, MOZ_ENV):
            rows = quota_lookup()
        self.assertEqual(rows, QUOTA_FIXTURE_EXPECTED_ROWS)

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_status_returns_full_figures(self, mock_post):
        mock_post.return_value = _rpc_response(QUOTA_RESULT_FIXTURE)
        with patch.dict(os.environ, MOZ_ENV):
            status = quota_status()
        self.assertEqual(status["allotted"], 3000)
        self.assertEqual(status["used"], 77)
        self.assertEqual(status["remaining"], 2923)
        self.assertFalse(status["overage"])

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_lookup_absent_figure_raises_not_zero(self, mock_post):
        """Design principle 3: absent data is stated, never a fabricated zero.

        A 0 here would read as "quota exhausted" and silently disable every
        downstream Moz call (P1/P2).
        """
        mock_post.return_value = _rpc_response({"unexpected": "shape"})
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                quota_lookup()

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_lookup_missing_used_raises_not_zero(self, mock_post):
        """A quota object without `used` must not be read as "nothing spent"."""
        mock_post.return_value = _rpc_response({"quota": {"allotted": 3000}})
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                quota_lookup()

    @patch("moz_jsonrpc.requests.post")
    def test_t0_quota_lookup_rejects_boolean_figures(self, mock_post):
        """bool is a subclass of int — a True flag must not become "1 row"."""
        mock_post.return_value = _rpc_response(
            {"quota": {"allotted": True, "used": 0}}
        )
        with patch.dict(os.environ, MOZ_ENV):
            with self.assertRaises(MozRpcError):
                quota_lookup()

    def test_t0_overage_floors_remaining_at_zero_but_keeps_the_flag(self):
        """An over-consumed account reports 0 left, not a negative count —
        and the overage stays visible after the floor."""
        status = parse_quota(
            {"quota": {"allotted": 3000, "used": 3200, "overage": True}}
        )
        self.assertEqual(status["remaining"], 0)
        self.assertTrue(status["overage"])


# ---------------------------------------------------------------------------
# Captured response fixture
# ---------------------------------------------------------------------------
# The `result` object from a REAL quota.lookup call made on 2026-08-27, copied
# verbatim (account_id left as returned; the token never appears in a response
# body). Not hand-authored — the shape a first guess assumed ("rows_remaining")
# does not exist in the real response, which reports `allotted`/`used` and
# leaves the caller to derive what is left (learnings P19).

QUOTA_RESULT_FIXTURE = {
    "quota": {
        "path": "api.limits.data.rows",
        "account_id": 24729587,
        "allotted": 3000,
        "used": 77,
        "reset": "month",
        "report": "day",
        "overage": False,
        "period_start": 1785567600,
        "period_reset": 1788246000,
    }
}
QUOTA_FIXTURE_EXPECTED_ROWS = 3000 - 77


if __name__ == "__main__":
    unittest.main()
