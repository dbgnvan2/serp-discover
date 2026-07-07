"""Tests for Y.11 cross-engine transfer / overlap metric.

Spec: yoast_geo_upgrade_spec_v1.md#Y.11
- Y.11.1 Jaccard + all-vs-one counts deterministic; identical→1.0, disjoint→0.0.
- Y.11.2 client mention/cite transfer statement correct for 0, some, all engines.
- Y.11.3 single-engine run → "not measurable", no crash.
- Y.11.4 table idempotent, UTC ts, trendable.
"""
import os
import tempfile
import unittest

import engine_transfer as et


def _tables(a_domains, b_domains):
    """Two citation tables (Y.8 shape) from bare domain lists."""
    return {
        "openai": [{"domain": d} for d in a_domains],
        "perplexity": [{"domain": d} for d in b_domains],
    }


class TestJaccard(unittest.TestCase):
    def test_identical_is_one(self):
        # Y.11.1
        self.assertEqual(et.jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_is_zero(self):
        # Y.11.1
        self.assertEqual(et.jaccard({"a"}, {"b"}), 0.0)

    def test_both_empty_is_one(self):
        self.assertEqual(et.jaccard(set(), set()), 1.0)

    def test_partial(self):
        # {a,b} vs {b,c} → 1/3
        self.assertEqual(et.jaccard({"a", "b"}, {"b", "c"}), round(1 / 3, 4))

    def test_deterministic(self):
        a, b = {"x", "y", "z"}, {"y", "z", "w"}
        self.assertEqual(et.jaccard(a, b), et.jaccard(a, b))


class TestOverlapCounts(unittest.TestCase):
    def test_all_vs_one(self):
        # Y.11.1 — openai:{a,b,c}, perplexity:{a,b,d}
        #   cited by ALL (both): a,b → 2; cited by exactly ONE: c,d → 2.
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": False, "perplexity": False},
            _tables(["a", "b", "c"], ["a", "b", "d"]),
            {"openai": 3, "perplexity": 5})
        self.assertEqual(r["overlap"]["cited_by_all"], 2)
        self.assertEqual(r["overlap"]["cited_by_exactly_one"], 2)
        self.assertEqual(r["overlap"]["pairwise_jaccard"]["openai|perplexity"],
                         round(2 / 4, 4))

    def test_disjoint_overlap(self):
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": True, "perplexity": True},
            _tables(["a"], ["b"]),
            {"openai": 1, "perplexity": 1})
        self.assertEqual(r["overlap"]["cited_by_all"], 0)
        self.assertEqual(r["overlap"]["cited_by_exactly_one"], 2)
        self.assertEqual(r["overlap"]["avg_jaccard"], 0.0)


class TestVisibilityTransfer(unittest.TestCase):
    def test_none_mentioned(self):
        # Y.11.2 — 0 of 3
        r = et.compute_transfer(
            ["openai", "perplexity", "gemini"],
            {"openai": False, "perplexity": False, "gemini": False},
            {"openai": False, "perplexity": False, "gemini": False},
            {}, {})
        self.assertEqual(r["visibility"]["mention_transfer"], "mentioned on 0 of 3 engines")
        self.assertEqual(r["visibility"]["mentioned_engines"], [])

    def test_some_mentioned(self):
        # Y.11.2 — 2 of 3
        r = et.compute_transfer(
            ["openai", "perplexity", "gemini"],
            {"openai": True, "perplexity": True, "gemini": False},
            {"openai": True, "perplexity": False, "gemini": False},
            {}, {})
        self.assertEqual(r["visibility"]["mention_transfer"], "mentioned on 2 of 3 engines")
        self.assertEqual(r["visibility"]["mentioned_engines"], ["openai", "perplexity"])
        self.assertEqual(r["visibility"]["cite_transfer"], "cited on 1 of 3 engines")

    def test_all_mentioned(self):
        # Y.11.2 — 3 of 3
        r = et.compute_transfer(
            ["openai", "perplexity", "gemini"],
            {"openai": True, "perplexity": True, "gemini": True},
            {"openai": True, "perplexity": True, "gemini": True},
            {}, {})
        self.assertEqual(r["visibility"]["mention_transfer"], "mentioned on 3 of 3 engines")


class TestRankDivergence(unittest.TestCase):
    def test_spread(self):
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": False, "perplexity": False},
            _tables(["a"], ["a"]),
            {"openai": 2, "perplexity": 9})
        self.assertEqual(r["rank_divergence"]["spread"], 7)

    def test_spread_none_with_one_rank(self):
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": False, "perplexity": False},
            _tables(["a"], ["a"]),
            {"openai": 2, "perplexity": None})
        self.assertIsNone(r["rank_divergence"]["spread"])


class TestSingleEngine(unittest.TestCase):
    def test_single_engine_not_measurable(self):
        # Y.11.3 — no crash, explicit statement.
        r = et.compute_transfer(
            ["openai"], {"openai": True}, {"openai": True},
            {"openai": [{"domain": "a"}]}, {"openai": 1})
        self.assertFalse(r["measurable"])
        self.assertIn("single engine", r["reason"])

    def test_single_engine_report(self):
        r = et.compute_transfer(["openai"], {}, {}, {}, {})
        md = "\n".join(et.render_transfer_section(r))
        self.assertIn("not measurable", md.lower())


class TestInterpretation(unittest.TestCase):
    def test_high_overlap_foundational_suffices(self):
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": True, "perplexity": True},
            _tables(["a", "b"], ["a", "b"]),
            {"openai": 1, "perplexity": 1})
        self.assertIn("foundational", r["interpretation"].lower())

    def test_low_overlap_per_engine(self):
        r = et.compute_transfer(
            ["openai", "perplexity"],
            {"openai": True, "perplexity": True},
            {"openai": True, "perplexity": True},
            _tables(["a"], ["b"]),
            {"openai": 1, "perplexity": 1})
        self.assertIn("per-engine", r["interpretation"].lower())


class TestPersistence(unittest.TestCase):
    def test_table_idempotent_and_trendable(self):
        # Y.11.4
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            et.init_transfer_table(db)
            et.init_transfer_table(db)  # idempotent
            r1 = et.compute_transfer(
                ["openai", "perplexity"],
                {"openai": True, "perplexity": False},
                {"openai": True, "perplexity": False},
                _tables(["a"], ["a"]), {"openai": 1, "perplexity": 2})
            single = et.compute_transfer(["openai"], {}, {}, {}, {})
            et.save_transfer(db, "2026-07-06T00:00:00+00:00", r1)
            et.save_transfer(db, "2026-07-06T01:00:00+00:00", single)
            trend = et.get_transfer_trend(db)
            self.assertEqual(len(trend), 2)
            self.assertEqual(trend[0]["engine_count"], 2)   # oldest first
            self.assertEqual(trend[1]["engine_count"], 1)   # single-engine recorded
            self.assertIsNone(trend[1]["avg_jaccard"])
        finally:
            os.remove(db)


if __name__ == "__main__":
    unittest.main()
