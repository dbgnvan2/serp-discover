"""Tests for Y.6 AI Visibility Index composite (aivi.py).

Spec: yoast_geo_upgrade_spec_v1.md#Y.6
- Y.6.1 deterministic; all-zero→0, all-max→100, mixed=hand-computed.
- Y.6.2 sentiment OFF → axis n/a, weights renormalised, still 0–100.
- Y.6.3 weights from config; changing them changes score; malformed→equal+warn.
- Y.6.4 table idempotent, UTC ts+engine, trend ordered, prior-run delta.
"""
import os
import tempfile
import unittest

import aivi


class TestComputeAivi(unittest.TestCase):
    def test_all_zero_and_all_max(self):
        # Y.6.1
        self.assertEqual(
            aivi.compute_aivi({"mentions": 0, "ranking": 0, "citations": 0,
                               "sentiment": 0})["aivi"], 0.0)
        self.assertEqual(
            aivi.compute_aivi({"mentions": 100, "ranking": 100, "citations": 100,
                               "sentiment": 100})["aivi"], 100.0)

    def test_mixed_hand_computed(self):
        # Equal weights: (80+60+40+20)/4 = 50.0
        r = aivi.compute_aivi({"mentions": 80, "ranking": 60, "citations": 40,
                               "sentiment": 20})
        self.assertEqual(r["aivi"], 50.0)
        self.assertEqual(r["excluded"], [])

    def test_deterministic(self):
        axes = {"mentions": 33, "ranking": 66, "citations": 12, "sentiment": 90}
        self.assertEqual(aivi.compute_aivi(axes), aivi.compute_aivi(axes))

    def test_clamping(self):
        r = aivi.compute_aivi({"mentions": 150, "ranking": -20, "citations": 50,
                               "sentiment": 50})
        # clamps to 100, 0, 50, 50 → mean 50
        self.assertEqual(r["aivi"], 50.0)


class TestSentimentNa(unittest.TestCase):
    def test_sentiment_na_renormalises(self):
        # Y.6.2: sentiment None → excluded; mean over remaining three.
        r = aivi.compute_aivi({"mentions": 90, "ranking": 60, "citations": 30,
                               "sentiment": None})
        self.assertEqual(r["aivi"], 60.0)  # (90+60+30)/3
        self.assertEqual(r["excluded"], ["sentiment"])
        self.assertIsNone(r["axes"]["sentiment"])
        self.assertTrue(0 <= r["aivi"] <= 100)

    def test_all_na_scores_zero(self):
        r = aivi.compute_aivi({"mentions": None, "ranking": None,
                               "citations": None, "sentiment": None})
        self.assertEqual(r["aivi"], 0.0)


class TestWeights(unittest.TestCase):
    def test_weights_change_score(self):
        # Y.6.3
        axes = {"mentions": 100, "ranking": 0, "citations": 0, "sentiment": 0}
        heavy_mentions = {"mentions": 0.7, "ranking": 0.1, "citations": 0.1,
                          "sentiment": 0.1}
        w = aivi.resolve_weights({"weights": heavy_mentions})
        self.assertEqual(aivi.compute_aivi(axes, w)["aivi"], 70.0)
        equal = aivi.resolve_weights({"weights": aivi.DEFAULT_WEIGHTS})
        self.assertEqual(aivi.compute_aivi(axes, equal)["aivi"], 25.0)

    def test_malformed_weights_fall_back_to_equal(self):
        self.assertEqual(aivi.resolve_weights({"weights": "oops"}), aivi.DEFAULT_WEIGHTS)
        self.assertEqual(aivi.resolve_weights({"weights": {"mentions": "x"}}),
                         aivi.DEFAULT_WEIGHTS)
        self.assertEqual(aivi.resolve_weights({}), aivi.DEFAULT_WEIGHTS)
        # zero-sum falls back
        self.assertEqual(
            aivi.resolve_weights({"weights": {"mentions": 0, "ranking": 0,
                                              "citations": 0, "sentiment": 0}}),
            aivi.DEFAULT_WEIGHTS)

    def test_weights_normalised(self):
        w = aivi.resolve_weights({"weights": {"mentions": 2, "ranking": 2,
                                              "citations": 2, "sentiment": 2}})
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertAlmostEqual(w["mentions"], 0.25)


class TestPersistence(unittest.TestCase):
    def test_table_idempotent_trend_and_delta(self):
        # Y.6.4
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            aivi.init_aivi_table(path)
            aivi.init_aivi_table(path)  # idempotent
            r1 = aivi.compute_aivi({"mentions": 40, "ranking": 40, "citations": 40,
                                    "sentiment": 40})
            r2 = aivi.compute_aivi({"mentions": 60, "ranking": 60, "citations": 60,
                                    "sentiment": 60})
            aivi.save_aivi(path, "2026-01-01T00:00:00+00:00", "openai", r1)
            aivi.save_aivi(path, "2026-02-01T00:00:00+00:00", "openai", r2)
            trend = aivi.get_aivi_trend(path, "openai")
            self.assertEqual([t["run_ts"] for t in trend],
                             ["2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"])
            self.assertEqual(trend[0]["aivi"], 40.0)
            self.assertEqual(trend[1]["aivi"], 60.0)
            # delta rendered in the report section
            section = aivi.render_aivi_section({"openai": r2}, 60.0,
                                               {"openai": trend})
            self.assertTrue(any("+20.0" in ln for ln in section))
        finally:
            os.remove(path)

    def test_all_engine_average(self):
        self.assertIsNone(aivi.all_engine_average({}))
        self.assertEqual(
            aivi.all_engine_average({"a": {"aivi": 20.0}, "b": {"aivi": 40.0}}),
            30.0)

    def test_na_axis_rendered(self):
        r = aivi.compute_aivi({"mentions": 50, "ranking": 50, "citations": 50,
                               "sentiment": None})
        section = aivi.render_aivi_section({"openai": r}, 50.0)
        self.assertTrue(any("n/a" in ln for ln in section))


if __name__ == "__main__":
    unittest.main()
