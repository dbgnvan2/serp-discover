"""Tests for Y.10 engine profiles + per-engine recommendations.

Spec: yoast_geo_upgrade_spec_v1.md#Y.10
- Y.10.1 recommendations sourced from engine_profiles.yml — editing a profile
  changes the output; no advice string hardcoded in Python.
- Y.10.2 prioritisation blend deterministic + config-weighted; a synthetic
  low-AIVI/high-reach engine ranks first (hand-computed order).
- Y.10.3 only enabled engines appear; a disabled engine → no recommendation.
"""
import os
import tempfile
import textwrap
import unittest

import engine_recommendations as er


def _write_profiles(body: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".yml")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(body))
    return path


_PROFILE_BODY = """\
engines:
  openai:
    display_name: ChatGPT
    retrieval_backend: Own index + Bing
    source_bias: [encyclopedic]
    avg_citations: 3.7
    avg_citations_asof: "2026"
    reach_tier: high
    referral_click_tier: medium
    recommended_content_moves:
      - MOVE_CHATGPT_ALPHA
      - MOVE_CHATGPT_BETA
    confidence: shifts over time
  perplexity:
    display_name: Perplexity
    retrieval_backend: Bing hybrid
    source_bias: [fresh]
    avg_citations: 14
    avg_citations_asof: "2026"
    reach_tier: medium
    referral_click_tier: high
    recommended_content_moves:
      - MOVE_PPLX_ALPHA
    confidence: shifts over time
"""


class TestSourcedFromYaml(unittest.TestCase):
    def test_moves_come_from_yaml_editing_changes_output(self):
        # Y.10.1 — the sentinel move strings live ONLY in the YAML, not Python.
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
            recs = er.engine_recommendations(["openai"], profiles, {})
            moves = recs[0]["moves"]
            self.assertIn("MOVE_CHATGPT_ALPHA", moves)
            self.assertIn("MOVE_CHATGPT_BETA", moves)
        finally:
            os.remove(path)

        # Edit the profile → output changes (nothing hardcoded).
        edited = _PROFILE_BODY.replace("MOVE_CHATGPT_ALPHA", "MOVE_CHATGPT_EDITED")
        path2 = _write_profiles(edited)
        try:
            profiles = er.load_engine_profiles(path2)
            recs = er.engine_recommendations(["openai"], profiles, {})
            self.assertIn("MOVE_CHATGPT_EDITED", recs[0]["moves"])
            self.assertNotIn("MOVE_CHATGPT_ALPHA", recs[0]["moves"])
        finally:
            os.remove(path2)

    def test_no_advice_string_hardcoded_in_module(self):
        # Y.10.1 — the recommended_content_moves live ONLY in the YAML; none of
        # the shipped move strings appear as string literals in the module.
        with open(er.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("MOVE_CHATGPT", src)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles = er.load_engine_profiles(os.path.join(repo_root, "engine_profiles.yml"))
        for profile in profiles.values():
            for move in profile.get("recommended_content_moves") or []:
                self.assertNotIn(move, src,
                                 "engine advice move must not be hardcoded in the .py")

    def test_missing_file_returns_empty(self):
        self.assertEqual(er.load_engine_profiles("/nonexistent/nope.yml"), {})


class TestPrioritization(unittest.TestCase):
    def test_low_aivi_high_reach_ranks_first(self):
        # Y.10.2 — hand-computed order.
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
        finally:
            os.remove(path)
        weights = {"opportunity": 0.5, "reach": 0.3, "referral": 0.2}
        # openai: AIVI 10 → opp .9; reach high 1.0; referral med .5
        #   = .5*.9 + .3*1.0 + .2*.5 = .45 + .30 + .10 = .85
        # perplexity: AIVI 90 → opp .1; reach med .5; referral high 1.0
        #   = .5*.1 + .3*.5 + .2*1.0 = .05 + .15 + .20 = .40
        ranked = er.prioritize_engines(
            ["openai", "perplexity"], profiles,
            {"openai": 10.0, "perplexity": 90.0}, weights)
        self.assertEqual([r["engine"] for r in ranked], ["openai", "perplexity"])
        self.assertAlmostEqual(ranked[0]["priority_score"], 0.85, places=3)
        self.assertAlmostEqual(ranked[1]["priority_score"], 0.40, places=3)

    def test_missing_aivi_is_max_opportunity(self):
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
        finally:
            os.remove(path)
        ranked = er.prioritize_engines(["openai"], profiles, {})  # no AIVI
        self.assertEqual(ranked[0]["opportunity"], 1.0)

    def test_deterministic(self):
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
        finally:
            os.remove(path)
        aivi = {"openai": 50.0, "perplexity": 50.0}
        r1 = er.prioritize_engines(["openai", "perplexity"], profiles, aivi)
        r2 = er.prioritize_engines(["openai", "perplexity"], profiles, aivi)
        self.assertEqual(r1, r2)

    def test_weight_resolution_fallback(self):
        self.assertEqual(er.resolve_priority_weights({"weights": "x"}),
                         er.DEFAULT_PRIORITY_WEIGHTS)
        self.assertEqual(
            er.resolve_priority_weights({"weights": {"opportunity": 0, "reach": 0,
                                                     "referral": 0}}),
            er.DEFAULT_PRIORITY_WEIGHTS)


class TestEnabledOnly(unittest.TestCase):
    def test_disabled_engine_no_recommendation(self):
        # Y.10.3 — only openai enabled; perplexity (in the file) must not appear.
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
        finally:
            os.remove(path)
        recs = er.engine_recommendations(["openai"], profiles, {})
        self.assertEqual([r["engine"] for r in recs], ["openai"])
        ranked = er.prioritize_engines(["openai"], profiles, {})
        self.assertEqual([r["engine"] for r in ranked], ["openai"])

    def test_enabled_engine_without_profile_skipped(self):
        path = _write_profiles(_PROFILE_BODY)
        try:
            profiles = er.load_engine_profiles(path)
        finally:
            os.remove(path)
        # "claude" is enabled but has no profile block → skipped, no crash.
        recs = er.engine_recommendations(["openai", "claude"], profiles, {})
        self.assertEqual([r["engine"] for r in recs], ["openai"])


class TestRepoProfilesLoad(unittest.TestCase):
    def test_shipped_engine_profiles_yml_parses(self):
        # The real editorial file must load and cover the four engines.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles = er.load_engine_profiles(os.path.join(repo_root, "engine_profiles.yml"))
        for key in ("openai", "perplexity", "gemini", "claude"):
            self.assertIn(key, profiles)
            self.assertTrue(profiles[key].get("recommended_content_moves"))

    def test_report_section_carries_caveat(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles = er.load_engine_profiles(os.path.join(repo_root, "engine_profiles.yml"))
        recs = er.engine_recommendations(["openai", "gemini"], profiles,
                                         {"openai": {"aivi": 12.0}})
        ranked = er.prioritize_engines(["openai", "gemini"], profiles,
                                       {"openai": 12.0, "gemini": 40.0})
        md = "\n".join(er.render_engine_recommendations_section(recs, ranked))
        self.assertIn("re-measure", md.lower())
        self.assertIn("does not transfer", md.lower())


if __name__ == "__main__":
    unittest.main()
