"""
test_moz_competitor.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for Moz competitor signals and the cross-tool handoff contract.

Spec: moz_api_upgrade_spec_v1.md#T.4

All HTTP calls are mocked. Response bodies mirror shapes captured from real
data.site.ranking.keyword.list and data.site.anchor.text.list calls on
2026-08-28 (learnings P19).
"""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import jsonschema

import handoff_writer
import moz_competitor
from moz_competitor import (
    MozCompetitorClient,
    STATUS_ERROR,
    STATUS_NO_RECORD,
    STATUS_OK,
    STATUS_SKIPPED_CAP,
    STATUS_SKIPPED_QUOTA,
    build_handoff_block,
    competitor_domains,
)

MOZ_ENV = {"MOZ_TOKEN": "test-token-abc123"}
POST_TARGET = "moz_jsonrpc.requests.post"

#: Real ranking_keywords payload (bowencenter.org, en-US).
REAL_RANKING = {
    "ranking_keywords": [
        {"keyword": "bowen eportal", "ranking_page": "https://intranet.bowencenter.org/",
         "rank_position": 21, "difficulty": 17, "volume": 5},
        {"keyword": "bh intranet", "ranking_page": "https://intranet.bowencenter.org/",
         "rank_position": 31, "difficulty": 18, "volume": 8},
    ],
    "target_query": {"query": "https://bowencenter.org", "scope": "domain",
                     "locale": "en-US"},
    "options": {"sort": "rank"},
    "page": {"n": 0, "limit": 25},
}

#: Real anchor_texts payload, trimmed.
REAL_ANCHORS = {
    "site_query": {"query": "https://bowencenter.org", "scope": "domain"},
    "offset": {"provided_token": None, "token": "FznlXWH73dPY", "limit": 25},
    "anchor_texts": [
        {"text": "bowen center", "external_root_domains": 108, "external_pages": 410},
        {"text": "", "external_root_domains": 53, "external_pages": 488},
        {"text": "bowencenter.org", "external_root_domains": 53, "external_pages": 174},
    ],
}


def _resp(result) -> MagicMock:
    r = MagicMock()
    r.ok, r.status_code = True, 200
    r.json.return_value = {"jsonrpc": "2.0", "id": "x" * 24, "result": result}
    return r


def _no_record() -> MagicMock:
    body = {"jsonrpc": "2.0", "id": "x" * 24,
            "error": {"code": -32655, "status": 404, "message": "not found"}}
    r = MagicMock()
    r.ok, r.status_code = False, 404
    r.json.return_value = body
    r.text = str(body)
    return r


def _server_error() -> MagicMock:
    r = MagicMock()
    r.ok, r.status_code = False, 500
    r.headers = {}
    r.json.return_value = {"error": {"code": -32000, "message": "boom"}}
    r.text = "boom"
    return r


def _by_method(ranking=None, anchors=None):
    """Route a mocked POST by the JSON-RPC method in the envelope."""
    def side_effect(*args, **kwargs):
        method = kwargs["json"]["method"]
        if method == moz_competitor.RANKING_KEYWORDS_METHOD:
            return ranking() if callable(ranking) else _resp(REAL_RANKING)
        return anchors() if callable(anchors) else _resp(REAL_ANCHORS)
    return side_effect


def _quota(remaining=3000, allotted=3000):
    return {"path": "api.limits.data.rows", "allotted": allotted,
            "used": allotted - remaining, "remaining": remaining, "overage": False}


class _CompCase(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, MOZ_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.quota = patch.object(
            moz_competitor, "row_budget", return_value=_quota()["remaining"])
        self.quota.start()
        self.client = MozCompetitorClient(db_path=self.tmp.name, locale="en-US")

    def tearDown(self):
        self.quota.stop()
        self.env.stop()
        os.unlink(self.tmp.name)


class TestRequestContract(_CompCase):

    @patch(POST_TARGET)
    def test_t4_ranking_keywords_put_locale_inside_target_query(self, mock_post):
        """The API rejects the call when locale sits beside target_query
        rather than inside it — confirmed against the live endpoint."""
        mock_post.side_effect = _by_method()
        self.client.fetch(["bowencenter.org"])
        envelopes = [c.kwargs["json"] for c in mock_post.call_args_list]
        ranking = next(e for e in envelopes
                       if e["method"] == moz_competitor.RANKING_KEYWORDS_METHOD)
        tq = ranking["params"]["data"]["target_query"]
        self.assertEqual(tq["locale"], "en-US")
        self.assertEqual(tq["scope"], "domain")
        self.assertNotIn("locale", ranking["params"]["data"])

    @patch(POST_TARGET)
    def test_t4_anchor_text_uses_site_query_without_locale(self, mock_post):
        mock_post.side_effect = _by_method()
        self.client.fetch(["bowencenter.org"])
        envelopes = [c.kwargs["json"] for c in mock_post.call_args_list]
        anchors = next(e for e in envelopes
                       if e["method"] == moz_competitor.ANCHOR_TEXT_METHOD)
        sq = anchors["params"]["data"]["site_query"]
        self.assertEqual(sq, {"query": "bowencenter.org", "scope": "domain"})

    @patch(POST_TARGET)
    def test_t4_parses_both_payloads(self, mock_post):
        mock_post.side_effect = _by_method()
        block = self.client.fetch(["bowencenter.org"])["bowencenter.org"]
        self.assertTrue(block["data_available"])
        kw = block["ranking_keywords"]["items"][0]
        self.assertEqual(kw["keyword"], "bowen eportal")
        self.assertEqual(kw["rank_position"], 21)
        anchor = block["anchor_texts"]["items"][0]
        self.assertEqual(anchor["text"], "bowen center")
        self.assertEqual(anchor["external_root_domains"], 108)

    @patch(POST_TARGET)
    def test_t4_domains_are_lowercased_once(self, mock_post):
        mock_post.side_effect = _by_method()
        result = self.client.fetch(["BowenCenter.org", "bowencenter.org"])
        self.assertEqual(list(result), ["bowencenter.org"])


class TestAbsentAndTruncation(_CompCase):

    @patch(POST_TARGET)
    def test_t4_no_record_is_not_an_error(self, mock_post):
        mock_post.side_effect = _by_method(ranking=_no_record, anchors=_no_record)
        block = self.client.fetch(["nowhere.example"])["nowhere.example"]
        self.assertFalse(block["data_available"])
        self.assertEqual(block["status"], STATUS_NO_RECORD)

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t4_failure_is_distinct_from_no_record(self, mock_post):
        mock_post.side_effect = _by_method(ranking=_server_error,
                                           anchors=_server_error)
        block = self.client.fetch(["broken.example"])["broken.example"]
        self.assertEqual(block["status"], STATUS_ERROR)

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t4_one_failing_method_does_not_discard_the_other(self, mock_post):
        """A domain with anchor text but no ranking data reports exactly that."""
        mock_post.side_effect = _by_method(ranking=_server_error)
        block = self.client.fetch(["half.example"])["half.example"]
        self.assertTrue(block["data_available"])
        self.assertEqual(block["ranking_keywords"]["status"], STATUS_ERROR)
        self.assertEqual(block["ranking_keywords"]["items"], [])
        self.assertEqual(len(block["anchor_texts"]["items"]), 3)

    @patch(POST_TARGET)
    def test_t4_truncation_is_declared(self, mock_post):
        """P9 — a capped list must not read as the complete set."""
        client = MozCompetitorClient(db_path=self.tmp.name, anchor_text_limit=2)
        mock_post.side_effect = _by_method()
        block = client.fetch(["bowencenter.org"])["bowencenter.org"]
        self.assertTrue(block["anchor_texts"]["truncated"])
        self.assertEqual(block["anchor_texts"]["returned"], 2)
        self.assertFalse(block["ranking_keywords"]["truncated"])

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t4_a_failed_method_reports_the_same_shape_as_a_successful_one(
            self, mock_post):
        """One producer, one shape.

        A block that omits `returned`/`truncated` on failure hands the
        consumer None where every successful block has an integer, so the
        two cases cannot be read the same way (learnings P19).
        """
        mock_post.side_effect = _by_method(ranking=_server_error)
        block = self.client.fetch(["half.example"])["half.example"]
        failed, ok = block["ranking_keywords"], block["anchor_texts"]
        self.assertEqual(set(failed), set(ok))
        self.assertEqual(failed["returned"], 0)
        self.assertIs(failed["truncated"], False)

    @patch(POST_TARGET)
    def test_t4_every_input_domain_appears_in_the_result(self, mock_post):
        """P2 — a dropped domain must never read as "no backlinks"."""
        mock_post.side_effect = _by_method()
        client = MozCompetitorClient(db_path=self.tmp.name, max_competitors=1)
        result = client.fetch(["a.example", "b.example"])
        self.assertEqual(set(result), {"a.example", "b.example"})
        self.assertEqual(result["b.example"]["status"], STATUS_SKIPPED_CAP)


class TestSpendControls(_CompCase):

    @patch(POST_TARGET)
    def test_t4_rows_billed_match_objects_returned(self, mock_post):
        """Measured live: 1 row per object. 2 keywords + 3 anchors = 5."""
        mock_post.side_effect = _by_method()
        self.client.fetch(["bowencenter.org"])
        self.assertEqual(self.client.rows_consumed, 5)

    @patch(POST_TARGET)
    def test_t4_no_record_bills_nothing(self, mock_post):
        mock_post.side_effect = _by_method(ranking=_no_record, anchors=_no_record)
        self.client.fetch(["nowhere.example"])
        self.assertEqual(self.client.rows_consumed, 0)

    @patch(POST_TARGET)
    def test_t4_cap_is_announced(self, mock_post):
        mock_post.side_effect = _by_method()
        client = MozCompetitorClient(db_path=self.tmp.name, max_competitors=1)
        with self.assertLogs("moz_competitor", level="WARNING") as logs:
            client.fetch(["a.example", "b.example"])
        self.assertTrue(any("cap 1" in line for line in logs.output))

    @patch(POST_TARGET)
    def test_t4_stops_before_exceeding_quota(self, mock_post):
        mock_post.side_effect = _by_method()
        with patch.object(moz_competitor, "row_budget", return_value=80):
            client = MozCompetitorClient(
                db_path=self.tmp.name, max_competitors=5,
                ranking_keyword_limit=50, anchor_text_limit=25)
            result = client.fetch(["a.example", "b.example", "c.example"])
        self.assertEqual(result["c.example"]["status"], STATUS_SKIPPED_QUOTA)

    @patch(POST_TARGET)
    def test_t4_unreadable_quota_does_not_disable_the_feature(self, mock_post):
        """P1 — a transient quota read failure must not read as "no budget"."""
        mock_post.side_effect = _by_method()
        with patch.object(moz_competitor, "row_budget", return_value=None):
            client = MozCompetitorClient(db_path=self.tmp.name)
            result = client.fetch(["a.example"])
        self.assertTrue(result["a.example"]["data_available"])


class TestCaching(_CompCase):

    @patch(POST_TARGET)
    def test_t4_second_run_hits_the_cache(self, mock_post):
        mock_post.side_effect = _by_method()
        self.client.fetch(["bowencenter.org"])
        mock_post.reset_mock()
        block = self.client.fetch(["bowencenter.org"])["bowencenter.org"]
        mock_post.assert_not_called()
        self.assertEqual(block["ranking_keywords"]["items"][0]["keyword"],
                         "bowen eportal")

    @patch("http_retry.time.sleep", lambda *_: None)
    @patch(POST_TARGET)
    def test_t4_errors_are_never_cached(self, mock_post):
        """P1 — caching a failure turns one outage into a month of "no data"."""
        mock_post.side_effect = _by_method(ranking=_server_error,
                                           anchors=_server_error)
        self.client.fetch(["broken.example"])
        with sqlite3.connect(self.tmp.name) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM moz_competitor_cache "
                "WHERE domain='broken.example'").fetchone()[0]
        self.assertEqual(count, 0)

    @patch(POST_TARGET)
    def test_t4_locale_is_part_of_the_cache_key(self, mock_post):
        mock_post.side_effect = _by_method()
        self.client.fetch(["bowencenter.org"])
        other = MozCompetitorClient(db_path=self.tmp.name, locale="fr-CA")
        mock_post.reset_mock()
        other.fetch(["bowencenter.org"])
        self.assertTrue(mock_post.called)


class TestFromConfig(unittest.TestCase):

    def _client(self, config):
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            return MozCompetitorClient.from_config(config, db_path=f.name)

    def test_t4_from_config_maps_every_key(self):
        c = self._client({"moz": {"cache_ttl_days": 9, "competitor": {
            "scope": "subdomain", "locale": "fr-CA", "max_competitors": 7,
            "ranking_keyword_limit": 11, "anchor_text_limit": 3}}})
        self.assertEqual(c._scope, "subdomain")
        self.assertEqual(c._locale, "fr-CA")
        self.assertEqual(c._max_competitors, 7)
        self.assertEqual(c._ranking_keyword_limit, 11)
        self.assertEqual(c._anchor_text_limit, 3)

    def test_t4_is_enabled_requires_both_switches(self):
        self.assertFalse(MozCompetitorClient.is_enabled({}))
        self.assertFalse(MozCompetitorClient.is_enabled(
            {"moz": {"enabled": False, "competitor": {"enabled": True}}}))
        self.assertTrue(MozCompetitorClient.is_enabled(
            {"moz": {"competitor": {"enabled": True}}}))

    def test_t4_shipped_config_enables_competitor(self):
        """Enabled at the user's instruction; the spec's default was false."""
        import yaml
        with open("config.yml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertTrue(cfg["moz"]["competitor"]["enabled"])
        self.assertIsInstance(cfg["moz"]["competitor"]["max_competitors"], int)


class TestDomainResolution(unittest.TestCase):
    """T.4 — reuse the existing resolution; no new competitor list."""

    ORGANIC = [
        {"Query_Label": "A", "Link": "https://bowencenter.org/x"},
        {"Query_Label": "A", "Link": "https://www.livingsystems.ca/y"},
        {"Query_Label": "A", "Link": "https://psychologytoday.com/z"},
        {"Query_Label": "S", "Link": "https://probe.example/s"},
        {"Query_Label": "A", "Link": "N/A"},
        {"Query_Label": "A", "Link": "https://bowencenter.org/again"},
    ]

    def test_t4_excludes_client_probe_rows_and_duplicates(self):
        domains = competitor_domains(self.ORGANIC, "livingsystems.ca")
        self.assertEqual(domains, ["bowencenter.org", "psychologytoday.com"])

    def test_t4_honours_the_omit_list(self):
        domains = competitor_domains(
            self.ORGANIC, "livingsystems.ca", ["psychologytoday.com"])
        self.assertEqual(domains, ["bowencenter.org"])


class TestHandoffBlock(unittest.TestCase):
    """T.4 — the block reaches the handoff, and only when enabled."""

    ORGANIC = [{"Query_Label": "A", "Link": "https://bowencenter.org/x"}]

    def test_t4_disabled_config_yields_no_block(self):
        self.assertIsNone(build_handoff_block({}, self.ORGANIC, "livingsystems.ca"))

    def test_t4_enabled_config_fetches_and_wraps(self):
        fake = MagicMock()
        fake.fetch.return_value = {"bowencenter.org": {"data_available": True,
                                                       "status": STATUS_OK}}
        fake._locale, fake._scope = "en-CA", "domain"
        with patch.object(MozCompetitorClient, "from_config", return_value=fake):
            block = build_handoff_block(
                {"moz": {"competitor": {"enabled": True}}},
                self.ORGANIC, "livingsystems.ca")
        fake.fetch.assert_called_once_with(["bowencenter.org"])
        self.assertEqual(block["locale"], "en-CA")
        self.assertIn("bowencenter.org", block["domains"])

    def test_t4_fetch_failure_yields_no_block_not_an_abort(self):
        with patch.object(MozCompetitorClient, "from_config",
                          side_effect=RuntimeError("boom")):
            self.assertIsNone(build_handoff_block(
                {"moz": {"competitor": {"enabled": True}}},
                self.ORGANIC, "livingsystems.ca"))


class TestHandoffContract(unittest.TestCase):
    """T.4 — the cross-tool contract, checked against BOTH schema copies."""

    ORGANIC = [
        {"Query_Label": "A", "Link": "https://bowencenter.org/x", "Rank": 1,
         "Root_Keyword": "bowen theory", "Title": "T",
         "Entity_Type": "nonprofit", "Content_Type": "article"},
    ]

    MOZ_BLOCK = {
        "generated_at": "2026-08-28T12:00:00+00:00",
        "locale": "en-CA",
        "scope": "domain",
        "domains": {
            "bowencenter.org": {
                "data_available": True, "status": STATUS_OK,
                "ranking_keywords": {"status": "ok", "items": [], "returned": 0,
                                     "truncated": False},
                "anchor_texts": {"status": "ok", "items": [], "returned": 0,
                                 "truncated": False},
            }
        },
    }

    def _build(self, moz_competitor_block=None):
        return handoff_writer.build_competitor_handoff(
            self.ORGANIC, run_id="r1",
            run_timestamp="2026-08-28T12:00:00+00:00",
            client_domain="livingsystems.ca", client_brand_names=["LS"],
            moz_competitor=moz_competitor_block,
        )

    def test_t4_handoff_without_moz_is_unchanged_v1_0(self):
        """A run with the block absent must emit exactly what Tool 2 accepts."""
        handoff = self._build()
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff["schema_version"], "1.0")
        self.assertNotIn("moz", handoff)

    def test_t4_handoff_with_moz_bumps_the_version(self):
        handoff = self._build(self.MOZ_BLOCK)
        self.assertIsNotNone(handoff, "schema rejected the moz block")
        self.assertEqual(handoff["schema_version"], "1.1")
        self.assertIn("bowencenter.org", handoff["moz"]["domains"])

    def test_t4_moz_block_is_top_level_not_inside_targets(self):
        """Targets keep additionalProperties:false in both repos, so a per-
        target field would be fatal downstream."""
        handoff = self._build(self.MOZ_BLOCK)
        for target in handoff["targets"]:
            self.assertNotIn("moz", target)

    def test_t4_serp_compete_schema_accepts_the_v1_1_handoff(self):
        """The binding cross-tool check.

        serp-compete validates against its OWN copy of handoff_schema.json and
        calls sys.exit(1) on failure, so "additive and ignored-safe" is only
        true if that copy allows the block. This test reads Tool 2's real
        schema from disk — the artifact, not a copy of our own (P6/P19).
        """
        path = "/Users/davemini2/ProjectsLocal/serp-compete/handoff_schema.json"
        if not os.path.exists(path):
            self.skipTest("serp-compete not present on this machine")
        with open(path, encoding="utf-8") as f:
            tool2_schema = json.load(f)
        handoff = self._build(self.MOZ_BLOCK)
        try:
            jsonschema.validate(instance=handoff, schema=tool2_schema)
        except jsonschema.ValidationError as exc:
            self.fail(
                "serp-compete would hard-exit on this handoff: "
                f"{exc.message} at {list(exc.path)}"
            )

    def test_t4_serp_compete_schema_still_accepts_a_v1_0_handoff(self):
        """Tool 2 must keep accepting a producer that never sets the block."""
        path = "/Users/davemini2/ProjectsLocal/serp-compete/handoff_schema.json"
        if not os.path.exists(path):
            self.skipTest("serp-compete not present on this machine")
        with open(path, encoding="utf-8") as f:
            tool2_schema = json.load(f)
        jsonschema.validate(instance=self._build(), schema=tool2_schema)


class TestAuditWiring(unittest.TestCase):
    """T.4 — serp_audit must actually pass the block (P25)."""

    def test_t4_serp_audit_passes_moz_competitor_to_the_handoff(self):
        import ast
        with open("serp_audit.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "build_competitor_handoff"
        ]
        self.assertTrue(calls, "serp_audit never builds a handoff")
        for call in calls:
            self.assertIn("moz_competitor", {kw.arg for kw in call.keywords})


if __name__ == "__main__":
    unittest.main()
