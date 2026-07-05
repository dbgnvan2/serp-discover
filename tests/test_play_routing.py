"""Tests for the Recommended-Play decision engine.

Spec: seo_geo_review_20260704.md — Part 4 priority summary; T.4
      ("rank-vs-citation divergence"). Foundation chip A.

Covers:
  RP.1  loader validates; malformed YAML fails loudly
  RP.2  rank_play for High AND Moderate feasibility
  RP.3  birth-order case (Low + informational + AIO, non-service) → extraction,
        NOT local_pivot
  RP.3b reformat_play wins over extraction_play
  RP.4  local_pivot for service-like local/transactional; NEVER for non-service
  RP.4b mixed + AIO + Low → extraction
  RP.5  deprioritize for Low + navigational
  RP.7  missing-input honesty flag
"""
import os
import tempfile
import unittest

import play_routing
from play_routing import (
    compute_recommended_play,
    load_play_routing,
)


# Real service_like_tokens from serp_vocab.yml (kept literal so the test is
# self-contained and does not depend on file I/O for the token list).
SERVICE_TOKENS = (
    "counselling", "counseling", "counsellor", "counselor",
    "therapist", "therapy", "psychologist", "mental health",
)

# The production routing table, loaded once for the routing tests.
ROUTING = load_play_routing()


def _profile(
    primary_intent="informational",
    is_mixed=False,
    has_ai_overview=True,
    has_local_pack=False,
    client_ranks_but_not_cited=False,
    mixed_intent_strategy=None,
):
    """Build a realistic keyword_profiles[kw] fixture with the routed fields."""
    return {
        "has_ai_overview": has_ai_overview,
        "has_local_pack": has_local_pack,
        "mixed_intent_strategy": mixed_intent_strategy,
        "serp_intent": {
            "primary_intent": primary_intent,
            "is_mixed": is_mixed,
        },
        "aio_divergence": {
            "client_ranks_but_not_cited": client_ranks_but_not_cited,
        },
    }


def _feas(status):
    """A keyword_feasibility row (Query_Label != 'P')."""
    return {"feasibility_status": status, "gap": 12.0, "Query_Label": "A"}


def _play(profile, feas_row=None, keyword="", tokens=SERVICE_TOKENS):
    return compute_recommended_play(
        profile,
        feasibility_row=feas_row,
        keyword=keyword,
        service_like_tokens=tokens,
        routing=ROUTING,
    )


# ─── RP.1 — loader validation ────────────────────────────────────────────────

class TestRp1LoaderValidation(unittest.TestCase):

    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_rp1_valid_production_table_loads(self):
        data = load_play_routing()
        self.assertIn("plays", data)
        self.assertIn("rules", data)
        # Every rule references a play defined in 'plays'.
        for rule in data["rules"]:
            self.assertIn(rule["play"], data["plays"])

    def test_rp1_malformed_yaml_syntax_raises(self):
        path = self._write("plays: {rank_play: [broken\nrules: -\n")
        with self.assertRaises(Exception):
            load_play_routing(path)

    def test_rp1_missing_plays_raises(self):
        path = self._write("rules:\n  - play: deprioritize\n    match: {}\n")
        with self.assertRaises(ValueError):
            load_play_routing(path)

    def test_rp1_empty_rules_raises(self):
        path = self._write(
            "plays:\n  deprioritize:\n    label: X\n    strategy_text: Y\n"
            "rules: []\n"
        )
        with self.assertRaises(ValueError):
            load_play_routing(path)

    def test_rp1_unknown_play_referenced_raises(self):
        path = self._write(
            "plays:\n  deprioritize:\n    label: X\n    strategy_text: Y\n"
            "rules:\n  - play: not_a_play\n    match: {}\n"
        )
        with self.assertRaises(ValueError):
            load_play_routing(path)

    def test_rp1_play_referenced_but_not_defined_raises(self):
        # rank_play is a VALID play id but is not defined in this file's 'plays'.
        path = self._write(
            "plays:\n  deprioritize:\n    label: X\n    strategy_text: Y\n"
            "rules:\n  - play: rank_play\n    match: {}\n"
        )
        with self.assertRaises(ValueError):
            load_play_routing(path)

    def test_rp1_unknown_match_field_raises(self):
        path = self._write(
            "plays:\n  deprioritize:\n    label: X\n    strategy_text: Y\n"
            "rules:\n  - play: deprioritize\n    match: {bogus_field: true}\n"
        )
        with self.assertRaises(ValueError):
            load_play_routing(path)

    def test_rp1_play_missing_strategy_text_raises(self):
        path = self._write(
            "plays:\n  deprioritize:\n    label: X\n"
            "rules:\n  - play: deprioritize\n    match: {}\n"
        )
        with self.assertRaises(ValueError):
            load_play_routing(path)


# ─── RP.2 — rank_play ────────────────────────────────────────────────────────

class TestRp2RankPlay(unittest.TestCase):

    def test_rp2_rank_play_high(self):
        v = _play(_profile(primary_intent="informational"),
                  _feas("High Feasibility"), keyword="what is anxiety")
        self.assertEqual(v["play"], "rank_play")
        self.assertEqual(v["confidence"], "high")

    def test_rp2_rank_play_moderate(self):
        v = _play(_profile(primary_intent="commercial_investigation"),
                  _feas("Moderate Feasibility"), keyword="best therapy books")
        self.assertEqual(v["play"], "rank_play")

    def test_rp2_rank_play_beats_extraction(self):
        # High feasibility informational + AIO would otherwise look extraction-y;
        # rank_play (rule 2) must win because ranking is achievable.
        v = _play(_profile(primary_intent="informational", has_ai_overview=True),
                  _feas("High Feasibility"), keyword="what is grief")
        self.assertEqual(v["play"], "rank_play")


# ─── RP.3 — extraction_play (the real birth-order case) ──────────────────────

class TestRp3ExtractionPlay(unittest.TestCase):

    def test_rp3_birth_order_extraction_not_local_pivot(self):
        # "how does birth order affect personality": Low feasibility,
        # informational, AIO present, NOT service-like.
        v = _play(
            _profile(primary_intent="informational", has_ai_overview=True,
                     has_local_pack=False),
            _feas("Low Feasibility"),
            keyword="how does birth order affect personality",
        )
        self.assertEqual(v["play"], "extraction_play")
        self.assertNotEqual(v["play"], "local_pivot_play")

    def test_rp3_commercial_investigation_extraction(self):
        v = _play(
            _profile(primary_intent="commercial_investigation", has_ai_overview=True),
            _feas("Low Feasibility"),
            keyword="types of family therapy compared",
        )
        self.assertEqual(v["play"], "extraction_play")

    def test_rp3_low_informational_no_aio_is_not_extraction(self):
        # No AI Overview → extraction has no target; falls to deprioritize.
        v = _play(
            _profile(primary_intent="informational", has_ai_overview=False),
            _feas("Low Feasibility"),
            keyword="how does birth order affect personality",
        )
        self.assertEqual(v["play"], "deprioritize")


# ─── RP.3b — reformat_play wins over extraction_play ─────────────────────────

class TestRp3bReformatWins(unittest.TestCase):

    def test_rp3b_reformat_beats_extraction(self):
        # Identical to the extraction case BUT client already ranks top-10 and
        # is not AIO-cited → reformat_play (rule 1) must win.
        v = _play(
            _profile(primary_intent="informational", has_ai_overview=True,
                     client_ranks_but_not_cited=True),
            _feas("Low Feasibility"),
            keyword="how does birth order affect personality",
        )
        self.assertEqual(v["play"], "reformat_play")
        self.assertEqual(v["evidence"]["matched_rule"]["index"], 0)

    def test_rp3b_reformat_fires_regardless_of_feasibility(self):
        v = _play(
            _profile(primary_intent="commercial_investigation",
                     client_ranks_but_not_cited=True),
            _feas("High Feasibility"),
            keyword="couples counselling north vancouver",
        )
        self.assertEqual(v["play"], "reformat_play")


# ─── RP.4 — local_pivot_play ─────────────────────────────────────────────────

class TestRp4LocalPivot(unittest.TestCase):

    def test_rp4_local_pivot_service_local_intent(self):
        v = _play(
            _profile(primary_intent="local", has_local_pack=True,
                     has_ai_overview=False),
            _feas("Low Feasibility"),
            keyword="marriage counselling north vancouver",
        )
        self.assertEqual(v["play"], "local_pivot_play")

    def test_rp4_local_pivot_service_transactional_intent(self):
        v = _play(
            _profile(primary_intent="transactional", has_local_pack=True),
            _feas("Low Feasibility"),
            keyword="book a therapist appointment",
        )
        self.assertEqual(v["play"], "local_pivot_play")

    def test_rp4_local_pivot_service_intent_indeterminate_with_pack(self):
        # primary_intent None (insufficient classified results) but a local pack
        # is present and the keyword is service-like → pivot (rule 4).
        v = _play(
            _profile(primary_intent=None, has_local_pack=True),
            _feas("Low Feasibility"),
            keyword="family therapist",
        )
        self.assertEqual(v["play"], "local_pivot_play")

    def test_rp4_local_pivot_never_fires_for_nonservice(self):
        # Non-service local keyword must NEVER route to local_pivot.
        v = _play(
            _profile(primary_intent="local", has_local_pack=True),
            _feas("Low Feasibility"),
            keyword="best hiking trails north vancouver",
        )
        self.assertNotEqual(v["play"], "local_pivot_play")

    def test_rp4_service_informational_extracts_not_pivots(self):
        # Service-like BUT informational intent (even with a local pack) must
        # extract, not pivot — has_local_pack never overrides a clear intent.
        v = _play(
            _profile(primary_intent="informational", has_local_pack=True,
                     has_ai_overview=True),
            _feas("Low Feasibility"),
            keyword="how does family therapy work",
        )
        self.assertEqual(v["play"], "extraction_play")


# ─── RP.4b — mixed-intent extraction path ────────────────────────────────────

class TestRp4bMixedExtraction(unittest.TestCase):

    def test_rp4b_mixed_aio_low_extracts(self):
        v = _play(
            _profile(primary_intent="mixed", is_mixed=True, has_ai_overview=True,
                     mixed_intent_strategy="backdoor"),
            _feas("Low Feasibility"),
            keyword="anxiety help",
        )
        self.assertEqual(v["play"], "extraction_play")


# ─── RP.5 — deprioritize ─────────────────────────────────────────────────────

class TestRp5Deprioritize(unittest.TestCase):

    def test_rp5_low_navigational_deprioritized(self):
        v = _play(
            _profile(primary_intent="navigational", has_ai_overview=True),
            _feas("Low Feasibility"),
            keyword="livingsystems login",
        )
        self.assertEqual(v["play"], "deprioritize")


# ─── RP.7 — missing-input honesty ────────────────────────────────────────────

class TestRp7Honesty(unittest.TestCase):

    def test_rp7_no_feasibility_row_marks_unknown_and_low_confidence(self):
        # No feasibility row: extraction can still fire on intent+AIO, but the
        # verdict must be honest that DA data was missing.
        v = _play(
            _profile(primary_intent="informational", has_ai_overview=True),
            feas_row=None,
            keyword="how does birth order affect personality",
        )
        self.assertEqual(v["play"], "extraction_play")
        self.assertFalse(v["data_available"]["feasibility"])
        self.assertEqual(v["confidence"], "low")
        self.assertIsNotNone(v["note"])
        self.assertIn("feasibility", v["note"].lower())

    def test_rp7_inconclusive_intent_marks_low_confidence(self):
        v = _play(
            _profile(primary_intent=None, has_ai_overview=True),
            _feas("Low Feasibility"),
            keyword="some vague keyword",
        )
        self.assertFalse(v["data_available"]["serp_intent"])
        self.assertEqual(v["confidence"], "low")
        self.assertIsNotNone(v["note"])

    def test_rp7_all_inputs_present_is_high_confidence(self):
        v = _play(
            _profile(primary_intent="informational", has_ai_overview=True),
            _feas("Low Feasibility"),
            keyword="how does birth order affect personality",
        )
        self.assertTrue(v["data_available"]["feasibility"])
        self.assertTrue(v["data_available"]["serp_intent"])
        self.assertEqual(v["confidence"], "high")
        self.assertIsNone(v["note"])

    def test_rp7_inputs_used_payload_present(self):
        v = _play(_profile(), _feas("Low Feasibility"), keyword="anxiety")
        inputs = v["evidence"]["inputs_used"]
        for key in play_routing.MATCHABLE_FIELDS:
            self.assertIn(key, inputs)


if __name__ == "__main__":
    unittest.main()
