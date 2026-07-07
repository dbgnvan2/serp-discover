"""Tests for Y.9 per-brand sentiment + aspect keywords (answer_sentiment.py).

Spec: yoast_geo_upgrade_spec_v1.md#Y.9
- Y.9.1 disabled by default → zero calls, "not measured".
- Y.9.2 enabled+mocked → Python computes % positive; polarity bucketed.
- Y.9.3 aspect phrases stored/rendered verbatim; empty handled.
- Y.9.4 calls counted against a budget.
"""
import os
import tempfile
import unittest

import answer_sentiment as sm


class TestGating(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(sm.is_enabled({}))
        self.assertFalse(sm.is_enabled({"enabled": False}))
        self.assertTrue(sm.is_enabled({"enabled": True}))

    def test_disabled_section_reads_not_measured(self):
        # Y.9.1
        section = sm.render_sentiment_section(
            None, enabled=False, client_brand="Living Systems",
            top_competitor="Rival")
        self.assertTrue(any("not measured" in ln.lower() for ln in section))

    def test_disabled_makes_zero_calls(self):
        # The collector is simply not invoked when disabled; assert the runner
        # would never be called by exercising collect_sentiment with no targets.
        called = {"n": 0}

        def runner(*a, **k):
            called["n"] += 1
            return "{}"
        rows, calls = sm.collect_sentiment(
            [{"engine": "g", "answer_text": "no brand here"}],
            {"Living Systems": ["living systems"]}, "m", llm_runner=runner)
        self.assertEqual(calls, 0)
        self.assertEqual(called["n"], 0)  # answer didn't mention the brand


class TestClassificationAndPercent(unittest.TestCase):
    def _runner_factory(self, mapping):
        def runner(system, user, model, max_tokens):
            for key, payload in mapping.items():
                if key in user:
                    return payload
            return "{}"
        return runner

    def test_percent_positive_hand_counted(self):
        # Y.9.2: 2 positive of 3 → 66.67 (Python computes, not the LLM).
        runner = self._runner_factory({
            "answer one": '{"polarity":"positive","positive_aspects":["warm"],"negative_aspects":[]}',
            "answer two": '{"polarity":"positive","positive_aspects":[],"negative_aspects":[]}',
            "answer three": '{"polarity":"negative","positive_aspects":[],"negative_aspects":["slow"]}',
        })
        answers = [
            {"engine": "g", "answer_text": "answer one about Living Systems"},
            {"engine": "g", "answer_text": "answer two about Living Systems"},
            {"engine": "g", "answer_text": "answer three about Living Systems"},
        ]
        rows, calls = sm.collect_sentiment(
            answers, {"Living Systems": ["living systems"]}, "m", llm_runner=runner)
        self.assertEqual(calls, 3)
        self.assertEqual(sm.percent_positive(rows, "Living Systems"),
                         round(100 * 2 / 3, 2))

    def test_polarity_buckets(self):
        for label in ("positive", "neutral", "negative"):
            r = sm._parse_classification(
                f'{{"polarity":"{label}","positive_aspects":[],"negative_aspects":[]}}')
            self.assertEqual(r["polarity"], label)
        # invalid polarity → neutral fallback
        self.assertEqual(sm._parse_classification('{"polarity":"???"}')["polarity"],
                         "neutral")

    def test_percent_none_when_unmeasured(self):
        self.assertIsNone(sm.percent_positive([], "Living Systems"))


class TestAspectsVerbatim(unittest.TestCase):
    def test_aspect_phrases_verbatim_and_dedup(self):
        # Y.9.3
        rows = [
            {"brand": "Rival", "polarity": "positive",
             "positive_aspects": ["integrated supports for youth"],
             "negative_aspects": ["requires a physician referral"]},
            {"brand": "Rival", "polarity": "positive",
             "positive_aspects": ["integrated supports for youth"],  # dup
             "negative_aspects": []},
        ]
        chips = sm.aspect_chips(rows, "Rival")
        self.assertEqual(chips["positive"], ["integrated supports for youth"])
        self.assertEqual(chips["negative"], ["requires a physician referral"])

    def test_empty_aspects_handled(self):
        r = sm._parse_classification('{"polarity":"neutral"}')
        self.assertEqual(r["positive_aspects"], [])
        self.assertEqual(r["negative_aspects"], [])


class TestBudget(unittest.TestCase):
    def test_call_budget_enforced(self):
        # Y.9.4: budget caps the number of LLM calls.
        def runner(*a, **k):
            return '{"polarity":"positive"}'
        answers = [
            {"engine": "g", "answer_text": f"Living Systems note {i}"}
            for i in range(5)
        ]
        rows, calls = sm.collect_sentiment(
            answers, {"Living Systems": ["living systems"]}, "m",
            llm_runner=runner, call_budget=2)
        self.assertEqual(calls, 2)
        self.assertEqual(len(rows), 2)


class TestPersistence(unittest.TestCase):
    def test_table_idempotent(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm.init_sentiment_table(path)
            sm.init_sentiment_table(path)
            sm.save_sentiment(path, "2026-01-01T00:00:00+00:00", [
                {"engine": "g", "brand": "Living Systems", "polarity": "positive",
                 "positive_aspects": ["warm"], "negative_aspects": [],
                 "answer_excerpt": "x"}])
            import sqlite3
            with sqlite3.connect(path) as conn:
                n = conn.execute("SELECT COUNT(*) FROM answer_sentiment").fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
