"""
test_moz_intent.py
~~~~~~~~~~~~~~~~~~
Tests for the Moz search-intent cross-check.

Spec: moz_api_upgrade_spec_v1.md#T.3

All HTTP calls are mocked. Response bodies mirror the shape captured from a
real data.keyword.search.intent.fetch call on 2026-08-28 (learnings P19).

The binding rule under test: Moz's intent is a second opinion. It is stored
and compared, and it never overrides intent_mapping.yml.
"""

import ast
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import brief_data_extraction
import moz_keywords
from moz_keywords import (
    DEFAULT_REPO_TO_MOZ_INTENT,
    MozIntentClient,
    STATUS_ERROR,
    STATUS_NO_RECORD,
    STATUS_OK,
    crosscheck_intent,
)

MOZ_ENV = {"MOZ_TOKEN": "test-token-abc123"}
POST_TARGET = "moz_jsonrpc.requests.post"

#: The real result object, verbatim from a live call for
#: "family counselling north vancouver" (en-CA).
REAL_INTENT = {
    "keyword_intent": {
        "primary_intents": ["transactional"],
        "all_intents": [
            {"label": "informational", "score": 0.31},
            {"label": "navigational", "score": 0.13},
            {"label": "commercial", "score": 0.11},
            {"label": "transactional", "score": 0.45},
        ],
    },
    "serp_query": {
        "keyword": "family counselling north vancouver",
        "locale": "en-CA", "device": "desktop",
        "engine": "google", "vicinity": "",
    },
}

REAL_NO_RECORD_BODY = {
    "id": "d333e602-fd47-4a7c-bb39-accd58518665",
    "jsonrpc": "2.0",
    "error": {"code": -32655, "status": 404, "data": {"key": "serp_query"},
              "message": "Search intent not found for that query."},
}


def _ok(result=None) -> MagicMock:
    resp = MagicMock()
    resp.ok, resp.status_code = True, 200
    resp.json.return_value = {
        "jsonrpc": "2.0", "id": "x" * 24,
        "result": REAL_INTENT if result is None else result,
    }
    return resp


def _no_record() -> MagicMock:
    resp = MagicMock()
    resp.ok, resp.status_code = False, 404
    resp.json.return_value = REAL_NO_RECORD_BODY
    resp.text = str(REAL_NO_RECORD_BODY)
    return resp


def _quota(remaining=3000, allotted=3000):
    return {"path": "api.limits.data.rows", "allotted": allotted,
            "used": allotted - remaining, "remaining": remaining, "overage": False}


class _IntentCase(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, MOZ_ENV)
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.quota = patch.object(
            moz_keywords, "quota_status", return_value=_quota())
        self.quota.start()
        self.client = MozIntentClient(db_path=self.tmp.name, locale="en-CA")

    def tearDown(self):
        self.quota.stop()
        self.env.stop()
        os.unlink(self.tmp.name)


class TestIntentFetch(_IntentCase):

    @patch(POST_TARGET)
    def test_t3_calls_the_search_intent_method(self, mock_post):
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["method"], "data.keyword.search.intent.fetch")
        self.assertEqual(sent["params"]["data"]["serp_query"]["locale"], "en-CA")

    @patch(POST_TARGET)
    def test_t3_parses_all_four_scores_and_the_primary(self, mock_post):
        mock_post.return_value = _ok()
        block = self.client.fetch(["kw"])["kw"]
        self.assertTrue(block["data_available"])
        self.assertEqual(block["primary_intents"], ["transactional"])
        self.assertEqual(block["scores"], {
            "informational": 0.31, "navigational": 0.13,
            "commercial": 0.11, "transactional": 0.45,
        })

    @patch(POST_TARGET)
    def test_t3_absent_data_flag_per_keyword(self, mock_post):
        mock_post.return_value = _no_record()
        block = self.client.fetch(["kw"])["kw"]
        self.assertFalse(block["data_available"])
        self.assertEqual(block["status"], STATUS_NO_RECORD)
        self.assertNotIn("scores", block)

    @patch(POST_TARGET)
    def test_t3_absent_reason_names_intent_not_metrics(self, mock_post):
        """The shared base must not report "no metrics" for the intent signal."""
        mock_post.return_value = _no_record()
        block = self.client.fetch(["kw"])["kw"]
        self.assertIn("intent scores", block["reason"])
        self.assertNotIn("keyword metrics", block["reason"])

    @patch(POST_TARGET)
    def test_t3_intent_bills_one_row_not_four(self, mock_post):
        """Measured live: intent costs 1 row where keyword metrics cost 4."""
        mock_post.return_value = _ok()
        self.client.fetch(["a", "b"])
        self.assertEqual(self.client.rows_consumed, 2)

    @patch(POST_TARGET)
    def test_t3_unknown_labels_are_ignored(self, mock_post):
        mock_post.return_value = _ok({"keyword_intent": {
            "primary_intents": ["local"],
            "all_intents": [{"label": "local", "score": 0.9},
                            {"label": "informational", "score": 0.2}],
        }})
        block = self.client.fetch(["kw"])["kw"]
        self.assertEqual(block["primary_intents"], [])
        self.assertEqual(block["scores"], {"informational": 0.2})

    @patch(POST_TARGET)
    def test_t3_empty_intent_object_is_absent_not_empty_scores(self, mock_post):
        mock_post.return_value = _ok(
            {"keyword_intent": {"primary_intents": [], "all_intents": []}})
        block = self.client.fetch(["kw"])["kw"]
        self.assertFalse(block["data_available"])

    @patch(POST_TARGET)
    def test_t3_intent_cache_round_trips_scores(self, mock_post):
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        mock_post.reset_mock()
        block = self.client.fetch(["kw"])["kw"]
        mock_post.assert_not_called()
        self.assertEqual(block["scores"]["transactional"], 0.45)
        self.assertEqual(block["primary_intents"], ["transactional"])

    @patch(POST_TARGET)
    def test_t3_intent_uses_its_own_cache_table(self, mock_post):
        """Sharing a table with keyword metrics would collide on the same key."""
        mock_post.return_value = _ok()
        self.client.fetch(["kw"])
        with sqlite3.connect(self.tmp.name) as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("moz_intent_cache", names)


class TestCrosscheck(unittest.TestCase):
    """T.3 — divergence is reported, never auto-resolved."""

    OK_BLOCK = {"data_available": True, "status": STATUS_OK,
                "primary_intents": ["transactional"],
                "scores": {"transactional": 0.45}}

    def test_t3_agreement_is_reported(self):
        out = crosscheck_intent("transactional", self.OK_BLOCK)
        self.assertTrue(out["agrees"])
        self.assertIsNone(out["divergence"])

    def test_t3_divergence_is_reported_with_both_readings(self):
        out = crosscheck_intent("informational", self.OK_BLOCK)
        self.assertFalse(out["agrees"])
        self.assertIn("informational", out["divergence"])
        self.assertIn("transactional", out["divergence"])

    def test_t3_repo_verdict_is_never_overwritten(self):
        """The whole point: Moz disagreeing must not change the repo's call."""
        out = crosscheck_intent("informational", self.OK_BLOCK)
        self.assertEqual(out["repo_intent"], "informational")
        self.assertNotIn("primary_intent", out)
        self.assertNotIn("serp_intent", out)

    def test_t3_vocabulary_is_mapped_before_comparing(self):
        """The repo says commercial_investigation; Moz says commercial. Those
        are the same verdict, and must not read as a disagreement."""
        block = {**self.OK_BLOCK, "primary_intents": ["commercial"]}
        out = crosscheck_intent("commercial_investigation", block)
        self.assertTrue(out["agrees"])

    def test_t3_local_maps_to_transactional(self):
        """Moz has no `local` label — it scores local service queries
        transactional, as the live probe showed."""
        out = crosscheck_intent("local", self.OK_BLOCK)
        self.assertTrue(out["agrees"])

    def test_t3_unmappable_repo_label_is_not_comparable_not_disagreement(self):
        out = crosscheck_intent("uncategorised", self.OK_BLOCK)
        self.assertIsNone(out["agrees"])
        self.assertIn("not comparable", out["divergence"])

    def test_t3_mixed_intent_keyword_is_not_comparable(self):
        out = crosscheck_intent(None, self.OK_BLOCK)
        self.assertIsNone(out["agrees"])

    def test_t3_builder_treats_a_mixed_keyword_as_not_comparable(self):
        """The is_mixed branch itself, not just crosscheck_intent's None path.

        A mixed-intent keyword has no single repo verdict, so comparing its
        `primary_intent` (literally "mixed") against Moz would manufacture a
        disagreement on every such keyword.
        """
        mixed = {"primary_intent": "mixed", "is_mixed": True}
        out = brief_data_extraction._build_moz_intent(mixed, self.OK_BLOCK, None)
        self.assertIsNone(out["agrees"])
        self.assertIsNone(out["repo_intent"])

    def test_t3_builder_compares_a_single_intent_keyword(self):
        single = {"primary_intent": "transactional", "is_mixed": False}
        out = brief_data_extraction._build_moz_intent(single, self.OK_BLOCK, None)
        self.assertTrue(out["agrees"])
        self.assertEqual(out["repo_intent"], "transactional")

    def test_t3_absent_moz_data_yields_none_not_false(self):
        """P1/P14 — "no data" must never render as "they disagree"."""
        out = crosscheck_intent(
            "informational", {"data_available": False, "status": STATUS_NO_RECORD})
        self.assertIsNone(out["agrees"])
        self.assertIsNone(out["divergence"])

    def test_t3_moz_with_no_primary_is_not_comparable(self):
        block = {**self.OK_BLOCK, "primary_intents": []}
        out = crosscheck_intent("informational", block)
        self.assertIsNone(out["agrees"])

    def test_t3_config_mapping_overrides_the_fallback(self):
        out = crosscheck_intent(
            "local", self.OK_BLOCK, mapping={"local": "informational"})
        self.assertFalse(out["agrees"])

    def test_t3_shipped_config_mapping_covers_every_repo_label(self):
        """A repo label missing from the table would silently become
        "not comparable" for every keyword that uses it."""
        import yaml
        with open("config.yml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        mapping = cfg["moz"]["search_intent"]["repo_to_moz_intent"]
        with open("intent_mapping.yml", encoding="utf-8") as f:
            rules = yaml.safe_load(f)
        labels = {
            rule.get("intent")
            for rule in (rules.get("rules") or [])
            if isinstance(rule, dict) and rule.get("intent")
        }
        self.assertTrue(labels, "no intents found in intent_mapping.yml")
        self.assertEqual(labels - set(mapping), set())


class TestBriefWiring(unittest.TestCase):
    """T.3 — the block must reach the brief payload (P25)."""

    @staticmethod
    def _extract(**kwargs):
        from test_generate_content_brief import TestGenerateContentBrief as _T
        return brief_data_extraction.extract_analysis_data_from_json(
            _T._sample_data(_T), "livingsystems.ca", ["Living Systems"], **kwargs
        )

    def test_t3_extraction_attaches_moz_intent_per_keyword(self):
        extracted = self._extract(moz_intent_metrics={
            "estrangement": {"data_available": True, "status": STATUS_OK,
                             "primary_intents": ["informational"],
                             "scores": {"informational": 0.8}},
        })
        block = extracted["keyword_profiles"]["estrangement"]["moz_intent"]
        self.assertTrue(block["data_available"])
        self.assertIn("agrees", block)
        self.assertEqual(block["scores"]["informational"], 0.8)

    def test_t3_extraction_marks_unfetched_keywords_explicitly(self):
        block = self._extract()["keyword_profiles"]["estrangement"]["moz_intent"]
        self.assertFalse(block["data_available"])
        self.assertEqual(block["status"], "not_fetched")

    def test_t3_serp_intent_survives_a_moz_disagreement(self):
        """The repo's verdict must be identical whether Moz agrees or not."""
        base = self._extract()["keyword_profiles"]["estrangement"]["serp_intent"]
        clashing = self._extract(moz_intent_metrics={
            "estrangement": {"data_available": True, "status": STATUS_OK,
                             "primary_intents": ["transactional"], "scores": {}},
        })["keyword_profiles"]["estrangement"]["serp_intent"]
        self.assertEqual(base, clashing)

    def test_t3_brief_rendering_passes_intent_to_the_extractor(self):
        with open("brief_rendering.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "extract_analysis_data_from_json"
        ]
        self.assertTrue(calls)
        for call in calls:
            names = {kw.arg for kw in call.keywords}
            self.assertIn("moz_intent_metrics", names)
            self.assertIn("moz_intent_mapping", names)

    def test_t3_intent_is_off_by_default(self):
        """A second opinion should not spend quota unless asked."""
        import brief_rendering
        data = {"organic_results": [
            {"Query_Label": "A", "Source_Keyword": "kw", "Link": "x"}]}
        self.assertEqual(brief_rendering._fetch_moz_intent(data, {"moz": {}}), {})

    def test_t3_shipped_config_has_intent_disabled(self):
        import yaml
        with open("config.yml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertFalse(cfg["moz"]["search_intent"]["enabled"])

    def test_t3_enabled_intent_is_fetched_and_passed(self):
        import brief_rendering
        data = {"organic_results": [
            {"Query_Label": "A", "Source_Keyword": "kw", "Link": "x"}]}
        fake = MagicMock()
        fake.fetch.return_value = {"kw": {"data_available": False}}
        with patch("moz_keywords.MozIntentClient.from_config", return_value=fake):
            out = brief_rendering._fetch_moz_intent(
                data, {"moz": {"search_intent": {"enabled": True}}})
        fake.fetch.assert_called_once_with(["kw"])
        self.assertIn("kw", out)

    def test_t3_mapping_is_read_from_config(self):
        import brief_rendering
        mapping = {"local": "informational"}
        self.assertEqual(
            brief_rendering._moz_intent_mapping(
                {"moz": {"search_intent": {"repo_to_moz_intent": mapping}}}),
            mapping,
        )
        self.assertIsNone(brief_rendering._moz_intent_mapping({}))


if __name__ == "__main__":
    unittest.main()
