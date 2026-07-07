"""Tests for Y.7 competitor mention leaderboard (brand_mentions.py).

Spec: yoast_geo_upgrade_spec_v1.md#Y.7
- Y.7.1 gazetteer extraction deterministic + case-insensitive, no LLM.
- Y.7.2 LLM pass mocked, merged/de-duped, unknowns → candidates file;
  llm_extraction=false skips it entirely.
- Y.7.3 leaderboard ranking, client-rank, "not mentioned", deterministic ties.
- Y.7.4 table idempotent, per-engine, UTC ts, trend ordered.
- Y.7.5 candidates file rendered.
"""
import os
import sqlite3
import tempfile
import unittest

import brand_mentions as bm


class TestGazetteer(unittest.TestCase):
    def test_gazetteer_deterministic_case_insensitive(self):
        # Y.7.1: three known brands named (mixed case) → correct counts, no LLM.
        gaz = ["Psychology Today", "Theravive", "BC Association"]
        answers = [
            {"engine": "g", "answer_text": "psychology today and THERAVIVE help."},
            {"engine": "g", "answer_text": "Try Psychology Today or BC Association."},
        ]
        lb = bm.build_leaderboard(answers, gaz, ["living systems"],
                                  llm_extraction=False, model="m")
        counts = {r["brand"]: r["mention_count"] for r in lb["rows"]}
        self.assertEqual(counts["Psychology Today"], 2)
        self.assertEqual(counts["Theravive"], 1)
        self.assertEqual(counts["BC Association"], 1)
        self.assertTrue(all(r["source"] == "gazetteer" for r in lb["rows"]))
        # Determinism: same inputs, same output.
        lb2 = bm.build_leaderboard(answers, gaz, ["living systems"], False, "m")
        self.assertEqual(lb["rows"], lb2["rows"])

    def test_gazetteer_word_boundary(self):
        # "Theravive" should not match inside an unrelated word.
        found = bm.gazetteer_pass("theraviveology is not a brand", ["Theravive"])
        self.assertEqual(found, [])
        found2 = bm.gazetteer_pass("see Theravive.", ["Theravive"])
        self.assertEqual(found2, ["Theravive"])

    def test_build_gazetteer_from_analysis_json(self):
        data = {"organic_results": [
            {"Source": "Psychology Today", "Link": "https://psychologytoday.com/x"},
            {"Source": "Reddit · r/askvan", "Link": "https://reddit.com/x"},
        ]}
        gaz = bm.build_gazetteer(["Known Brand"], data)
        self.assertIn("Known Brand", gaz)
        self.assertIn("Psychology Today", gaz)
        self.assertIn("Reddit", gaz)  # split on "·"

    def test_old_json_without_organic_results_no_crash(self):
        # Principle 3: absent fields flow through, no fabricated brands.
        gaz = bm.build_gazetteer(["A"], {"unrelated": 1})
        self.assertEqual(gaz, ["A"])


class TestLLMPass(unittest.TestCase):
    def test_llm_extraction_false_skips_llm(self):
        # Y.7.2: llm_extraction=false → the runner is never called.
        called = {"n": 0}

        def runner(*a, **k):
            called["n"] += 1
            return "[]"

        lb = bm.build_leaderboard(
            [{"engine": "g", "answer_text": "Psychology Today."}],
            ["Psychology Today"], ["client"], llm_extraction=False,
            model="m", llm_runner=runner)
        self.assertEqual(called["n"], 0)
        self.assertEqual(lb["unknown_candidates"], [])

    def test_llm_pass_merges_dedups_and_surfaces_unknowns(self):
        # Y.7.2: gazetteer + LLM merged, de-duped (gazetteer wins), unknowns out.
        def runner(system, user, model, max_tokens):
            return '["Psychology Today", "New Clinic Inc", "new clinic inc"]'

        gaz = ["Psychology Today"]
        lb = bm.build_leaderboard(
            [{"engine": "g", "answer_text": "Psychology Today is listed."}],
            gaz, ["client"], llm_extraction=True, model="m", llm_runner=runner)
        brands = {r["brand"]: r["source"] for r in lb["rows"]}
        # Gazetteer brand keeps gazetteer source despite LLM also naming it.
        self.assertEqual(brands["Psychology Today"], "gazetteer")
        # Unknown surfaced once (case-normalised de-dup).
        self.assertEqual(lb["unknown_candidates"], ["New Clinic Inc"])

    def test_llm_parse_tolerates_fences(self):
        self.assertEqual(bm._parse_llm_names('```json\n["A","B"]\n```'), ["A", "B"])
        self.assertEqual(bm._parse_llm_names("garbage"), [])

    def test_llm_failure_degrades(self):
        def boom(*a, **k):
            raise RuntimeError("network down")
        self.assertEqual(bm.llm_extract_brands("x", "m", llm_runner=boom), [])


class TestRankingAndClientRank(unittest.TestCase):
    def test_client_rank_and_ties(self):
        # Y.7.3: ties broken alphabetically; client rank computed.
        answers = [
            {"engine": "g", "answer_text": "Alpha and Bravo."},
            {"engine": "g", "answer_text": "Alpha and Living Systems."},
        ]
        gaz = ["Bravo", "Alpha", "Living Systems"]
        lb = bm.build_leaderboard(answers, gaz, ["living systems"], False, "m")
        # Alpha=2 first; Bravo=1, Living Systems=1 tie -> alpha order (Bravo<Living).
        order = [r["brand"] for r in lb["rows"]]
        self.assertEqual(order[0], "Alpha")
        self.assertEqual(order[1:], ["Bravo", "Living Systems"])
        self.assertEqual(lb["client_rank"], 3)

    def test_not_mentioned(self):
        lb = bm.build_leaderboard(
            [{"engine": "g", "answer_text": "Alpha only."}],
            ["Alpha"], ["living systems"], False, "m")
        self.assertIsNone(lb["client_rank"])
        section = bm.render_leaderboard_section("g", lb)
        self.assertTrue(any("not mentioned" in ln for ln in section))

    def test_ranking_axis_normalisation(self):
        self.assertEqual(bm.client_ranking_axis(1, 5), 100.0)
        self.assertEqual(bm.client_ranking_axis(5, 5), 0.0)
        self.assertEqual(bm.client_ranking_axis(None, 5), 0.0)
        self.assertEqual(bm.client_ranking_axis(1, 1), 100.0)


class TestPersistence(unittest.TestCase):
    def test_table_idempotent_per_engine_trend(self):
        # Y.7.4: idempotent create, per-engine trend ordered oldest→newest.
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            bm.init_brand_mentions_table(path)
            bm.init_brand_mentions_table(path)  # second call must not raise
            lb1 = bm.build_leaderboard(
                [{"engine": "g", "answer_text": "Alpha."}], ["Alpha"], [], False, "m")
            lb2 = bm.build_leaderboard(
                [{"engine": "g", "answer_text": "Alpha Bravo."}],
                ["Alpha", "Bravo"], [], False, "m")
            bm.save_brand_mentions(path, "2026-01-01T00:00:00+00:00", "g", lb1)
            bm.save_brand_mentions(path, "2026-02-01T00:00:00+00:00", "g", lb2)
            trend = bm.get_brand_mentions_trend(path, "g")
            self.assertEqual([t["run_ts"] for t in trend],
                             ["2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"])
            self.assertEqual(len(trend[1]["rows"]), 2)
        finally:
            os.remove(path)


class TestCandidatesFile(unittest.TestCase):
    def test_candidates_file_written(self):
        # Y.7.5: unknowns → brand_mentions_candidates_<topic>_<ts>.md
        with tempfile.TemporaryDirectory() as d:
            path = bm.write_candidates_file(
                ["New Clinic Inc"], "leila", "2026-07-06T12:00:00+00:00",
                "market_analysis_leila.json", out_dir=d)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.basename(path).startswith(
                "brand_mentions_candidates_leila_"))
            body = open(path).read()
            self.assertIn("New Clinic Inc", body)
            self.assertIn("known_brands", body)

    def test_no_candidates_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(bm.write_candidates_file([], "leila", "ts", None, out_dir=d))


if __name__ == "__main__":
    unittest.main()
