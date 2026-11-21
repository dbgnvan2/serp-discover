"""The neighbourhood-pivot gate reads the keyword's own words.

Found by running feasibility on 2026-11-21: `family of origin therapist near
me` was refused a pivot because its SERP classified as `commercial_
investigation`, and the report told the owner that proximity substitutes for
authority "only when the searcher wants a service in a place" — about a query
that says near me. The classified intent describes the page Google served; a
marker in the keyword is what the searcher asked for.

These tests pin three things: a marker permits a pivot whatever the SERP was
classified as, a marker never refuses one, and the phrase has exactly one
editorial home.
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import feasibility
import profile_questions

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(REPO, "serp_vocab.yml")


def _DEFAULT_LINE(src: str) -> int:
    """The line of the documented ``_NEAR_ME_DEFAULT`` fallback assignment."""
    for i, line in enumerate(src.splitlines(), start=1):
        if line.startswith("_NEAR_ME_DEFAULT ="):
            return i
    return -1

MARKERS = ("near me", "nearby", "in my area")
LOW = {"status": "🔴 Low Feasibility", "avg_competitor_da": 79}


def _pivot(keyword, serp_intent, **kw):
    return feasibility.generate_hyper_local_pivot(
        keyword, "North Vancouver", LOW, ["Lonsdale"],
        is_service_like=False, serp_intent=serp_intent,
        pivotable_intents=("local", "transactional"),
        local_intent_markers=MARKERS, **kw)


class TestAMarkerPermitsThePivot(unittest.TestCase):
    """The live case: a near-me keyword on a commercial_investigation SERP."""

    def test_near_me_keyword_gets_a_pivot_despite_the_serp_intent(self):
        pivot = _pivot("family of origin therapist near me",
                       {"primary_intent": "commercial_investigation"})
        self.assertFalse(feasibility.is_no_pivot(pivot["pivot_status"]),
                         pivot["pivot_status"])
        self.assertTrue(pivot["all_variants"])

    def test_the_gate_source_names_the_marker_that_decided(self):
        pivot = _pivot("therapist near me",
                       {"primary_intent": "commercial_investigation"})
        self.assertEqual(pivot["gate_source"], "keyword local marker (near me)")

    def test_every_marker_is_honoured(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                ok, source = feasibility._pivot_gate(
                    {"primary_intent": "informational"}, False,
                    ("local",), keyword=f"family therapist {marker}",
                    local_intent_markers=MARKERS)
                self.assertTrue(ok)
                self.assertIn(marker, source)

    def test_a_marker_beats_a_mixed_serp_with_no_pivotable_component(self):
        ok, source = feasibility._pivot_gate(
            {"is_mixed": True, "mixed_components": ["informational",
                                                    "navigational"]},
            False, ("local",), keyword="counsellor near me",
            local_intent_markers=MARKERS)
        self.assertTrue(ok)
        self.assertIn("near me", source)

    def test_the_match_ignores_case(self):
        ok, _ = feasibility._pivot_gate(
            {"primary_intent": "informational"}, False, ("local",),
            keyword="Therapist NEAR ME", local_intent_markers=MARKERS)
        self.assertTrue(ok)


class TestAMarkerNeverRefusesAPivot(unittest.TestCase):
    """Keywords with no marker are gated exactly as they were."""

    def test_a_local_serp_still_pivots_without_a_marker(self):
        ok, source = feasibility._pivot_gate(
            {"primary_intent": "local"}, False, ("local",),
            keyword="family of origin therapist", local_intent_markers=MARKERS)
        self.assertTrue(ok)
        self.assertEqual(source, "serp_intent.primary_intent")

    def test_an_informational_keyword_is_still_refused(self):
        pivot = _pivot("how my childhood affects my relationships",
                       {"primary_intent": "informational"})
        self.assertTrue(feasibility.is_no_pivot(pivot["pivot_status"]))
        self.assertEqual(pivot["all_variants"], [])

    def test_the_service_token_fallback_still_decides_with_no_verdict(self):
        ok, source = feasibility._pivot_gate(
            {"primary_intent": None}, True, ("local",),
            keyword="couples counselling", local_intent_markers=MARKERS)
        self.assertTrue(ok)
        self.assertIn("is_service_like", source)

    def test_an_empty_keyword_changes_nothing(self):
        ok, source = feasibility._pivot_gate(
            {"primary_intent": "informational"}, False, ("local",),
            keyword="", local_intent_markers=MARKERS)
        self.assertFalse(ok)
        self.assertEqual(source, "serp_intent.primary_intent")


class TestTheMarkersAreEditorialAndInConfig(unittest.TestCase):

    def setUp(self):
        with open(VOCAB_PATH, encoding="utf-8") as fh:
            self.vocab = yaml.safe_load(fh) or {}
        self.block = self.vocab.get("local_intent") or {}

    def test_the_vocabulary_file_carries_the_block(self):
        self.assertTrue(self.block.get("markers"))
        self.assertTrue(self.block.get("near_me_phrase"))

    def test_near_me_phrase_is_one_of_the_markers(self):
        markers = [str(m).strip().lower() for m in self.block["markers"]]
        self.assertIn(str(self.block["near_me_phrase"]).strip().lower(), markers)

    def test_the_shipped_markers_catch_the_keyword_that_found_this(self):
        markers = feasibility.resolve_local_intent_markers(self.vocab)
        self.assertEqual(
            feasibility.keyword_local_marker(
                "family of origin therapist near me", markers), "near me")

    def test_no_marker_can_hide_inside_an_unrelated_word(self):
        # Substring match: a one-word marker would fire on any word
        # containing it. Every shipped marker is a phrase or a whole word.
        for marker in feasibility.resolve_local_intent_markers(self.vocab):
            with self.subTest(marker=marker):
                self.assertFalse(
                    feasibility.keyword_local_marker(
                        "family of origin counselling north vancouver",
                        (marker,)),
                    f"{marker!r} fired on an unrelated keyword")

    def test_a_missing_block_degrades_to_the_default(self):
        self.assertEqual(feasibility.resolve_local_intent_markers({}),
                         feasibility.DEFAULT_LOCAL_INTENT_MARKERS)
        self.assertEqual(feasibility.resolve_local_intent_markers(None),
                         feasibility.DEFAULT_LOCAL_INTENT_MARKERS)

    def test_a_malformed_block_warns_and_degrades(self):
        with self.assertLogs(level="WARNING") as log:
            got = feasibility.resolve_local_intent_markers(
                {"local_intent": {"markers": []}})
        self.assertEqual(got, feasibility.DEFAULT_LOCAL_INTENT_MARKERS)
        self.assertTrue(any("local_intent.markers" in m for m in log.output))

    def test_the_phrase_has_one_home(self):
        # profile_questions used to hold its own copy of "near me".
        self.assertEqual(profile_questions._near_me_phrase(),
                         str(self.block["near_me_phrase"]).strip())
        # The phrase may be NAMED in prose — a docstring explaining the line
        # is not a copy of the fact. Only a string used as data is. Parsed,
        # not grepped, so the two cannot be confused.
        src = open(os.path.join(REPO, "profile_questions.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        phrase = str(self.block["near_me_phrase"]).strip()
        used_as_data = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.strip().lower() == phrase.lower()
            and node.value not in docstrings
            # The documented fallback, guarded by the assertion above.
            and node.lineno != _DEFAULT_LINE(src)
        ]
        self.assertEqual(used_as_data, [],
                         f"second home for the phrase at line(s) {used_as_data}")


class TestEveryPipelineInjectsTheConfiguredList(unittest.TestCase):
    """A default that silently applies would leave the config list dead.

    `decide_pivots` defaults the markers to None so an old caller keeps
    working, which means nothing would notice the two pipelines failing to
    pass the resolved list. Source inspection, because the alternative is
    running a whole audit.
    """

    def _src(self, name):
        return open(os.path.join(REPO, name), encoding="utf-8").read()

    def test_the_standalone_pass_resolves_and_injects(self):
        src = self._src("run_feasibility.py")
        self.assertIn("resolve_local_intent_markers", src)
        self.assertEqual(src.count("local_intent_markers=local_intent_markers"),
                         2, "both the gate call and the pivot call must inject")

    def test_the_audit_resolves_and_injects(self):
        src = self._src("serp_audit.py")
        self.assertIn("FEASIBILITY_LOCAL_INTENT_MARKERS = "
                      "feasibility_module.resolve_local_intent_markers", src)
        self.assertIn("local_intent_markers=FEASIBILITY_LOCAL_INTENT_MARKERS",
                      src)

    def test_the_pass_hands_what_it_was_given_to_the_generator(self):
        src = self._src("pivot_pass.py")
        self.assertIn("local_intent_markers=local_intent_markers", src)


if __name__ == "__main__":
    unittest.main()
