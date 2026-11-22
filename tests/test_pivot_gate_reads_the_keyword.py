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
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import brief_data_extraction
import feasibility
import play_routing
import profile_questions
import run_feasibility

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(REPO, "serp_vocab.yml")


def _DEFAULT_LINE(src: str) -> int:
    """The line of the documented ``_NEAR_ME_DEFAULT`` fallback assignment."""
    for i, line in enumerate(src.splitlines(), start=1):
        if line.startswith("_NEAR_ME_DEFAULT ="):
            return i
    return -1

MARKERS = ("near me", "nearby", "in my area")
LOW = {"status": "Low Feasibility", "avg_competitor_da": 79}


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


class TestTheNeighbourhoodReplacesTheMarker(unittest.TestCase):
    """The variant is built on the keyword WITHOUT its "near me".

    The first run after the gate shipped produced "family of origin therapist
    near me West Vancouver" — a phrase nobody searches, which SerpAPI's Maps
    engine refused with a 400. The neighbourhood names the place the marker
    left unnamed, so it replaces it.
    """

    def test_the_live_keyword_pivots_to_a_searchable_phrase(self):
        pivot = _pivot("family of origin therapist near me",
                       {"primary_intent": "commercial_investigation"})
        self.assertEqual(pivot["suggested_keyword"],
                         "family of origin therapist Lonsdale")
        self.assertEqual(pivot["all_variants"],
                         ["family of origin therapist Lonsdale"])
        for variant in pivot["all_variants"] + [pivot["suggested_keyword"]]:
            self.assertNotIn("near me", variant.lower())

    def test_the_output_records_the_base_and_the_marker_removed(self):
        pivot = _pivot("family of origin therapist near me",
                       {"primary_intent": "commercial_investigation"})
        self.assertEqual(pivot["pivot_base_keyword"],
                         "family of origin therapist")
        self.assertEqual(pivot["stripped_local_marker"], "near me")

    def test_the_keyword_itself_is_still_reported_unchanged(self):
        pivot = _pivot("family of origin therapist near me",
                       {"primary_intent": "commercial_investigation"})
        self.assertEqual(pivot["original_keyword"],
                         "family of origin therapist near me")

    def test_a_keyword_with_no_marker_is_untouched(self):
        base, marker = feasibility.pivot_base_keyword(
            "family of origin therapist", MARKERS)
        self.assertEqual(base, "family of origin therapist")
        self.assertEqual(marker, "")

    def test_only_a_trailing_marker_is_stripped(self):
        # Removing a marker from the middle would change what is left, so
        # the keyword is returned whole and the caller can see no strip.
        base, marker = feasibility.pivot_base_keyword(
            "therapist near my house", ("near my",))
        self.assertEqual(base, "therapist near my house")
        self.assertEqual(marker, "")

    def test_a_keyword_that_is_only_a_marker_is_not_emptied(self):
        base, marker = feasibility.pivot_base_keyword("near me", MARKERS)
        self.assertEqual(base, "near me")
        self.assertEqual(marker, "")

    def test_every_shipped_marker_strips_cleanly(self):
        markers = feasibility.resolve_local_intent_markers(
            yaml.safe_load(open(VOCAB_PATH, encoding="utf-8")))
        for marker in markers:
            with self.subTest(marker=marker):
                base, got = feasibility.pivot_base_keyword(
                    f"family therapist {marker}", markers)
                self.assertEqual(base, "family therapist")
                self.assertEqual(got, marker)

    def test_the_unmeasured_branch_uses_the_same_base(self):
        # run_feasibility builds its own variant list for an unmeasured
        # keyword; it used to build it from the raw keyword.
        src = open(os.path.join(REPO, "run_feasibility.py"),
                   encoding="utf-8").read()
        self.assertIn('f"{_pivot_base} {nb}"', src)
        self.assertNotIn('f"{kw} {nb}"', src)


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
        self.assertIn("local_intent_markers=feasibility_module."
                      "resolve_local_intent_markers(SERP_VOCAB)", src)

    def test_the_pass_hands_what_it_was_given_to_the_generator(self):
        src = self._src("pivot_pass.py")
        self.assertIn("local_intent_markers=local_intent_markers", src)


class TestTheReportDoesNotContradictItself(unittest.TestCase):
    """The play table reads the marker too.

    It keyed local routing on the classified intent alone, so
    "family of origin therapist near me" was routed to the extraction play
    while the feasibility pass recommended a neighbourhood pivot for the same
    keyword — both printed on one row of the same report.
    """

    PROFILE = {"serp_intent": {"primary_intent": "commercial_investigation"},
               "has_ai_overview": True, "has_local_pack": False}
    ROW = {"feasibility_status": "Low Feasibility"}

    def _play(self, keyword, markers=MARKERS):
        return play_routing.compute_recommended_play(
            self.PROFILE, feasibility_row=self.ROW, keyword=keyword,
            service_like_tokens=("therapist",),
            local_intent_markers=markers)["play"]

    def test_a_near_me_keyword_routes_to_the_local_pivot(self):
        self.assertEqual(self._play("family of origin therapist near me"),
                         "local_pivot_play")

    def test_the_same_keyword_without_the_marker_is_unchanged(self):
        self.assertEqual(self._play("family of origin therapist"),
                         "extraction_play")

    def test_a_marker_without_a_service_does_not_route_to_a_pivot(self):
        # Rule 3b keeps `is_service_like`: a neighbourhood is meaningless
        # for a question, marker or not.
        play = play_routing.compute_recommended_play(
            self.PROFILE, feasibility_row=self.ROW,
            keyword="how my childhood affects my relationships near me",
            service_like_tokens=("therapist",),
            local_intent_markers=MARKERS)["play"]
        self.assertEqual(play, "extraction_play")

    def test_the_signal_is_declared_matchable(self):
        self.assertIn("has_local_intent_marker", play_routing.MATCHABLE_FIELDS)

    def test_the_brief_path_loads_the_markers_itself(self):
        # attach_recommended_plays is the one definition of "route the plays";
        # a caller that passes no markers must still get them.
        profiles = {"family of origin therapist near me": dict(self.PROFILE)}
        rows = [{"Keyword": "family of origin therapist near me",
                 "Query_Label": "A", "feasibility_status": "Low Feasibility"}]
        brief_data_extraction.attach_recommended_plays(
            profiles, rows, service_like_tokens=("therapist",))
        play = (profiles["family of origin therapist near me"]
                ["recommended_play"]["play"])
        self.assertEqual(play, "local_pivot_play")

    def test_the_shipped_markers_are_what_it_loads(self):
        self.assertEqual(brief_data_extraction.load_local_intent_markers(),
                         feasibility.resolve_local_intent_markers(
                             yaml.safe_load(open(VOCAB_PATH,
                                                 encoding="utf-8"))))


class TestThePivotLocalPackCanActuallyBeMeasured(unittest.TestCase):
    """SerpAPI requires `z` with `location`, and this pass sent none.

    Every pivot Maps call answered 400 "Missing `z` or `m` parameter", so the
    local-pack check could never succeed. It was invisible until the gate fix
    produced a pivot to check. The audit had passed z=14 as a literal all
    along — the same fact in one module and missing from the other.
    """

    def test_the_fetch_sends_the_zoom_with_the_location(self):
        captured = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"local_results": [{"title": "x"}]}

        def _get(url, params=None, timeout=None):
            captured.update(params or {})
            return _Resp()

        with unittest.mock.patch.object(run_feasibility, "_requests") as req:
            req.get = _get
            with unittest.mock.patch.dict(os.environ,
                                          {"SERPAPI_KEY": "k"}, clear=False):
                rows, ok = run_feasibility._fetch_pivot_local_pack(
                    "family of origin therapist Lonsdale",
                    {"serpapi": {"location": "North Vancouver", "maps_zoom": 12}})
        self.assertTrue(ok)
        self.assertEqual(captured.get("z"), "12")
        self.assertIn("location", captured)

    def test_the_zoom_defaults_when_config_omits_it(self):
        captured = {}

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"local_results": []}

        def _get(url, params=None, timeout=None):
            captured.update(params or {})
            return _Resp()

        with unittest.mock.patch.object(run_feasibility, "_requests") as req:
            req.get = _get
            with unittest.mock.patch.dict(os.environ,
                                          {"SERPAPI_KEY": "k"}, clear=False):
                run_feasibility._fetch_pivot_local_pack("x", {"serpapi": {}})
        self.assertEqual(captured.get("z"),
                         str(run_feasibility.DEFAULT_MAPS_ZOOM))

    def test_the_zoom_is_editorial_and_in_config(self):
        cfg = yaml.safe_load(open(os.path.join(REPO, "config.yml"),
                                  encoding="utf-8"))
        self.assertIn("maps_zoom", cfg.get("serpapi", {}))

    def test_both_maps_callers_read_the_same_key(self):
        audit = open(os.path.join(REPO, "serp_audit.py"), encoding="utf-8").read()
        self.assertIn('CONFIG.get("serpapi", {}).get("maps_zoom"', audit)
        self.assertIn('maps_params["z"] = MAPS_ZOOM', audit)
        self.assertNotIn('maps_params["z"] = "14"', audit)


if __name__ == "__main__":
    unittest.main()
