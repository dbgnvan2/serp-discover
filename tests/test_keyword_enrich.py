"""keyword_enrich.py reads the config, the vocabulary and the shared fetch path.

The script was untracked and named its own database, spent Moz rows with no
cap and with `moz.search_intent.enabled: false`, filed a failed autocomplete
call as "no suggestions", and graded phrases with word lists in Python. Each
class below guards one of those. No network: Moz clients and the SerpAPI
client are fakes.
"""

import os
import sys
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import keyword_enrich as ke  # noqa: E402
import pattern_matching  # noqa: E402
import serp_fetch  # noqa: E402


class _FakeClient:
    """Stands in for a Moz signal client; records how it was built."""
    CONFIG_KEY = "keyword_metrics"
    built_with = None

    def __init__(self, cfg, db_path):
        self.cfg, self.db_path = cfg, db_path

    @classmethod
    def from_config(cls, cfg, db_path=None):
        cls.built_with = (cfg, db_path)
        return cls(cfg, db_path)

    def fetch(self, phrases):
        return {p: {"data_available": True, "status": "ok", "volume": 10} for p in phrases}


class TestTheConfigGovernsMozSpend(unittest.TestCase):
    def setUp(self):
        _FakeClient.built_with = None

    def test_the_client_is_built_from_config(self):
        """from_config is what carries max_keywords, so the testing cap holds."""
        cfg = {"moz": {"keyword_metrics": {"enabled": True, "max_keywords": 25}}}
        ke.fetch_moz_signal(_FakeClient, cfg, ["a"])
        self.assertIs(_FakeClient.built_with[0], cfg)
        self.assertIsNone(_FakeClient.built_with[1],
                          "no --db means db_connect.database_path(), not a name of its own")

    def test_a_disabled_signal_spends_nothing_and_says_so(self):
        for cfg in ({"moz": {"keyword_metrics": {"enabled": False}}},
                    {"moz": {"enabled": False, "keyword_metrics": {"enabled": True}}}):
            with self.subTest(cfg=cfg):
                _FakeClient.built_with = None
                out = ke.fetch_moz_signal(_FakeClient, cfg, ["a", "b"])
                self.assertIsNone(_FakeClient.built_with)
                self.assertEqual({b["status"] for b in out.values()}, {ke.STATUS_NOT_ENABLED})
                self.assertFalse(any(b["data_available"] for b in out.values()))

    def test_no_database_name_of_its_own(self):
        src = open(os.path.join(REPO, "keyword_enrich.py"), encoding="utf-8").read()
        self.assertNotIn("serp_data.db", src)
        self.assertNotIn("requests.get", src, "SerpAPI goes through serp_fetch")


class _Search:
    """Fake GoogleSearch: answers from a per-query table, or raises."""
    answers = {}

    def __init__(self, params):
        self.params = params

    def get_dict(self):
        a = self.answers[self.params["q"]]
        if isinstance(a, Exception):
            raise a
        return a


class TestAFailedCallIsNotAnEmptyAnswer(unittest.TestCase):
    def setUp(self):
        os.environ["SERPAPI_KEY"] = "test-key-not-real"

    def tearDown(self):
        os.environ.pop("SERPAPI_KEY", None)

    def test_three_outcomes_stay_three(self):
        import requests
        _Search.answers = {
            "has": {"suggestions": [{"value": "has one"}]},
            "none": {"suggestions": []},
            "dead": requests.exceptions.ConnectionError("reset"),
        }
        with mock.patch("http_retry.serpapi_retry_attempts", return_value=1):
            out = ke.expand_autocomplete(["has", "none", "dead"], {},
                                         client=_Search, available=True)
        self.assertEqual(out["has"], {"status": serp_fetch.STATUS_OK, "suggestions": ["has one"]})
        self.assertEqual(out["none"], {"status": serp_fetch.STATUS_OK, "suggestions": []})
        self.assertNotEqual(out["dead"]["status"], serp_fetch.STATUS_OK)
        md = ke.render_shortlist({"generated_at": "2026-11-22T00:00", "source_csv": "x.csv",
                                  "quota_remaining_before": 0, "quota_remaining_after": 0,
                                  "rows": [], "autocomplete": out})
        self.assertIn("**none** — Google returned no suggestions", md)
        self.assertIn("Not fetched (1 of 3): dead (", md)

    def test_no_key_is_not_attempted(self):
        os.environ.pop("SERPAPI_KEY", None)
        out = ke.expand_autocomplete(["a"], {})
        self.assertEqual(out["a"]["status"], ke.STATUS_NOT_ATTEMPTED)

    def test_config_market_is_sent(self):
        seen = {}

        class Capture(_Search):
            def get_dict(self):
                seen.update(self.params)
                return {"suggestions": []}

        ke.expand_autocomplete(["a"], {"serpapi": {"gl": "us", "hl": "fr"}},
                               client=Capture, available=True)
        self.assertEqual((seen["gl"], seen["hl"]), ("us", "fr"))


class TestTheGradingWordsAreEditorial(unittest.TestCase):
    def test_the_vocabulary_ships_and_loads(self):
        vocab = ke.load_shortlist_vocab()
        self.assertTrue(vocab["ad_grade_intents"])
        self.assertTrue(vocab["ad_groups"])
        self.assertNotIn("local", vocab["ad_grade_intents"], "Moz has no local label")

    def test_grouping_and_grading_follow_the_vocabulary(self):
        vocab = ke.load_shortlist_vocab({"ads_shortlist": {
            "ad_grade_intents": ["navigational"],
            "ad_groups": [{"group": "First", "triggers": ["x"]},
                          {"group": "Second", "triggers": ["x", "y"]}],
            "default_group": "Other"}})
        self.assertEqual(ke.ad_group("an X phrase", vocab), "First", "first match wins")
        self.assertEqual(ke.ad_group("why", vocab), "Second")
        self.assertEqual(ke.ad_group("none", vocab), "Other")
        hit = {"data_available": True, "primary_intents": ["Navigational"]}
        self.assertEqual(ke.classify_intent(hit, vocab), "ad-grade")
        self.assertEqual(ke.classify_intent({"data_available": False}, vocab), "unknown")
        other = {"data_available": True, "primary_intents": ["informational"]}
        self.assertEqual(ke.classify_intent(other, vocab), "not ad-grade")
        empty = {"data_available": True, "primary_intents": []}
        self.assertEqual(ke.classify_intent(empty, vocab), "no primary intent")

    def test_a_missing_block_is_refused_not_guessed(self):
        for bad in ({}, {"ads_shortlist": {"ad_grade_intents": [], "ad_groups": [],
                                           "default_group": "x"}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ke.load_shortlist_vocab(bad)

    def test_no_grading_words_left_in_python(self):
        src = open(os.path.join(REPO, "keyword_enrich.py"), encoding="utf-8").read()
        for word in ('"bowen"', '"couple"', '"sibling"', '"anxiety"'):
            self.assertNotIn(word, src)
        self.assertIn("ads_shortlist", pattern_matching.SERP_VOCAB)


class TestTheShortlistSaysWhatItLacks(unittest.TestCase):
    def test_an_unmeasured_cell_names_its_reason(self):
        payload = {"generated_at": "2026-11-22T00:00", "source_csv": "x.csv",
                   "quota_remaining_before": 0, "quota_remaining_after": 0,
                   "metrics_coverage": ke._counts({"a": {"status": "skipped_quota",
                                                         "data_available": False}}),
                   "rows": [{"phrase": "a", "volume": None, "difficulty": None,
                             "metrics_status": "skipped_quota", "intent": None,
                             "intent_status": "not_enabled", "verdict": "unknown",
                             "ad_group": "Family"}],
                   "autocomplete": {}}
        md = ke.render_shortlist(payload)
        self.assertIn("| a | — (skipped_quota) | — (skipped_quota) | — (not_enabled) |", md)
        self.assertIn("Volume/difficulty: 0 of 1 measured; 1 skipped_quota", md)

    def test_an_expansion_that_did_not_run_says_so(self):
        payload = {"generated_at": "2026-11-22T00:00", "source_csv": "x.csv",
                   "quota_remaining_before": 0, "quota_remaining_after": 0,
                   "intent_coverage": "0 of 2 measured; 2 not_enabled",
                   "rows": [{"phrase": p, "volume": 1, "difficulty": 1, "intent": None,
                             "intent_status": "not_enabled", "verdict": "unknown",
                             "ad_group": "Family"} for p in ("a", "b")],
                   "autocomplete": {}}
        md = ke.render_shortlist(payload)
        self.assertIn("## Autocomplete expansions (ad-grade only)", md)
        self.assertIn("Not run: 0 of 2 phrases graded ad-grade "
                      "(intent: 0 of 2 measured; 2 not_enabled).", md)


if __name__ == "__main__":
    unittest.main()
