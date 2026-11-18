"""Review chunk Y1 — one definition of each rule this tool keys things by.

Every finding here was logged as an adjacent issue by an earlier chunk's cold
review and left unfixed per rule 10: a second copy of a rule that merely
agrees today. The guards below are about the copies, not the behaviour — a
behaviour test passes just as well with eight copies, which is how this
accumulated.

Spec: docs/review_2026-11-04/PLAN_Y1_one_definition_each.md
"""
import inspect
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand_mentions
import brief_data_extraction
import brief_validation
import citation_table
import dataforseo_client
import feasibility
import keyword_demand
import probe_ai_visibility
import run_feasibility
import storage
import title_patterns
import yaml
from domain_utils import ALIAS_PREFIXES, normalize_domain

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every module that derives "which host is this". A hand-rolled strip here is
#: a ninth definition waiting to drift from `domain_utils`.
HOST_MODULES = (brand_mentions, citation_table, dataforseo_client, feasibility,
                probe_ai_visibility, run_feasibility, storage)


#: The labels `domain_utils` owns, without the dots, so the guard below
#: recognises a hand-rolled strip of any of them.
_ALIAS_LABELS = {p.strip(".").lower() for p in ALIAS_PREFIXES}


#: String methods that could take an alias prefix off a host by hand.
_STRIPPERS = frozenset({"removeprefix", "lstrip", "rstrip", "strip", "replace",
                        "split", "partition", "removesuffix"})


#: Shapes that take a prefix off without a string method: a regex, or the
#: idiomatic `startswith` test followed by a slice. Added by the cold review of
#: chunk Y5, which found the AST walk blind to both.
_RE_FUNCS = frozenset({"sub", "match", "fullmatch", "search"})


def _alias_literal(value):
    """True when *value* is an alias prefix, written plainly or as a regex."""
    if not isinstance(value, str):
        return False
    label = value.replace("\\", "").strip("^$").strip(".").lower()
    return label in _ALIAS_LABELS


def hand_stripped_prefixes(source):
    """``[(line, method, literal)]`` for every hand-rolled alias strip.

    Walked, not grepped: the first form of this guard matched three spellings
    of the `www.` strip as source text, so a fourth spelling passed and any
    reformat broke it green (review chunk Y5). It covers a string method
    (`removeprefix`, `replace`, `split`, …), `re.sub`/`re.match` and the
    `startswith` test that precedes a slice — not every conceivable spelling,
    but every one this repo has reached for.
    """
    import ast

    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr in _STRIPPERS or func.attr == "startswith":
            names = node.args
        elif (func.attr in _RE_FUNCS
              and isinstance(func.value, ast.Name) and func.value.id == "re"):
            names = node.args
        else:
            continue
        for arg in names:
            if isinstance(arg, ast.Constant) and _alias_literal(arg.value):
                found.append((node.lineno, func.attr, arg.value))
            elif isinstance(arg, (ast.Tuple, ast.List)):
                for item in arg.elts:
                    if (isinstance(item, ast.Constant)
                            and _alias_literal(item.value)):
                        found.append((node.lineno, func.attr, item.value))
    return found


class TestOneHostRule(unittest.TestCase):

    def test_no_module_strips_the_prefix_by_hand(self):
        for module in HOST_MODULES:
            hits = hand_stripped_prefixes(inspect.getsource(module))
            self.assertEqual(
                hits, [],
                f"{module.__name__} has its own copy of the host rule: "
                + "; ".join(f"line {line} calls .{attr}({lit!r})"
                            for line, attr, lit in hits)
                + " — call domain_utils.normalize_domain")

    def test_every_local_helper_agrees_with_the_one_definition(self):
        cases = ["https://WWW.Example.com:8080/p", "example.com/page",
                 "https://m.yelp.com/biz", "www.m.yelp.com", "m.ca",
                 "not a url", ""]
        helpers = (citation_table.domain_of, feasibility.domain_of,
                   run_feasibility._extract_domain,
                   dataforseo_client.DataForSEOClient._extract_domain,
                   probe_ai_visibility._domain_from_url)
        for case in cases:
            expected = normalize_domain(case)
            for helper in helpers:
                self.assertEqual(helper(case), expected,
                                 f"{helper.__qualname__}({case!r})")

    def test_a_mobile_host_is_the_same_site(self):
        """`m.x.ca` counted as its own competitor took a top-10 slot twice."""
        self.assertIn("m.", ALIAS_PREFIXES)
        self.assertEqual(normalize_domain("https://m.yelp.com/x"), "yelp.com")
        self.assertEqual(normalize_domain("www.m.yelp.com"), "yelp.com")

    def test_a_first_label_that_is_m_is_not_stripped(self):
        """`m.ca` is a registrable domain; stripping leaves a public suffix."""
        self.assertEqual(normalize_domain("m.ca"), "m.ca")
        self.assertEqual(normalize_domain("www.ca"), "www.ca")
        self.assertEqual(normalize_domain("mail.example.com"),
                         "mail.example.com")

    def test_every_case_in_the_shared_table_comes_out_canonical(self):
        """`tests/host_canonical_cases.json` is the definition both repos are
        checked against — scheme, path, port, userinfo and free text, not just
        the prefix list."""
        with open(os.path.join(REPO, "tests", "host_canonical_cases.json"),
                  encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        for raw, expected in cases.items():
            self.assertEqual(normalize_domain(raw), expected, repr(raw))

    def test_the_consumer_is_checked_against_the_same_table(self):
        """serp-compete holds the consumer's copy by design (handoff files on
        disk carry the old form). The table is byte-identical on both sides,
        the way `handoff_schema.json` is; the previous guard compared the
        prefix *list* in the sibling's source, and compete's rule had kept the
        port, the path and the userinfo throughout."""
        path = os.path.join(os.path.dirname(REPO), "serp-compete",
                            "Serp-compete", "tests",
                            "host_canonical_cases.json")
        if not os.path.exists(path):           # the sibling repo is optional
            self.skipTest("serp-compete not checked out beside this repo")
        with open(path, "rb") as f:
            theirs = f.read()
        with open(os.path.join(REPO, "tests", "host_canonical_cases.json"),
                  "rb") as f:
            mine = f.read()
        self.assertEqual(theirs, mine,
                         "the two repos' host case tables have drifted")


class TestBothSidesOfEveryHostCompareAreCanonical(unittest.TestCase):
    """Cold review of Y1 — canonicalising one side of a compare is worse than
    canonicalising neither: the value that used to match no longer does."""

    def test_a_www_spelled_competitor_entry_still_matches_a_citation(self):
        import probe_ai_visibility

        result = probe_ai_visibility.detect_visibility(
            "Some answer text.",
            ["https://www.psychologytoday.com/ca/therapists/x",
             "https://m.yelp.com/biz/y"],
            client_domain="livingsystems.ca",
            client_name_patterns=["Living Systems"],
            competitor_domains=["www.psychologytoday.com", "m.yelp.com"])
        self.assertEqual(sorted(result["competitors_cited"]),
                         ["psychologytoday.com", "yelp.com"])

    def test_a_www_spelled_known_brand_is_attributed(self):
        import probe_ai_visibility

        mapping = probe_ai_visibility._brand_domain_map(
            ["WWW.PsychologyToday.com"], "www.livingsystems.ca", "Living")
        self.assertEqual(mapping.get("psychologytoday.com"),
                         "WWW.PsychologyToday.com")
        self.assertEqual(mapping.get("livingsystems.ca"), "Living")


class TestTheDatabaseKeysOneSitePerRow(unittest.TestCase):

    def test_both_sides_of_the_entity_join_are_canonical(self):
        """`metrics.get_entity_dominance` joins `serp_results.domain` against
        `domain_features.domain`; the first held `urlparse(url).netloc`
        verbatim, so one site could hold two rows with one entity type each."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db = storage.SerpStorage(os.path.join(tmp, "t.db"))
            db.save_run("r1", "hash")
            db.save_serp_result("r1", "kw", "organic", 1, "T",
                                "https://WWW.Example.com/a",
                                "WWW.Example.com", "s", query_label="A")
            db.save_domain_features("https://m.Example.com/b", "directory")
            import sqlite3
            with sqlite3.connect(os.path.join(tmp, "t.db")) as conn:
                hosts = [r[0] for r in conn.execute(
                    "SELECT domain FROM serp_results")]
                features = [r[0] for r in conn.execute(
                    "SELECT domain FROM domain_features")]
        self.assertEqual(hosts, ["example.com"])
        self.assertEqual(features, ["example.com"])

    def test_an_unreadable_host_writes_no_entity_row(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            db = storage.SerpStorage(path)
            db.save_domain_features("not a host", "directory")
            import sqlite3
            with sqlite3.connect(path) as conn:
                rows = list(conn.execute("SELECT * FROM domain_features"))
        self.assertEqual(rows, [])


class TestTheRowsAlreadyStoredAreBroughtForward(unittest.TestCase):
    """Cold review of Y1 — canonicalising the write path alone splits history.

    `visualize_volatility` pivots `serp_results.domain` across runs, so a
    competitor present throughout would show its `www.x.ca` line stopping at
    the change and an `x.ca` line starting: a competitor leaving and another
    arriving, in a chart, with nothing saying otherwise.
    """

    def _db(self, tmp, rows, features):
        import sqlite3

        path = os.path.join(tmp, "t.db")
        db = storage.SerpStorage(path)
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO runs (run_id, run_date) VALUES ('r0', 'd')")
        for host in rows:
            conn.execute(
                "INSERT INTO serp_results (run_id, keyword_text, domain, "
                "rank) VALUES ('r0', 'k', ?, 1)", (host,))
        for host, entity in features:
            conn.execute(
                "INSERT INTO domain_features (domain, entity_type) "
                "VALUES (?, ?)", (host, entity))
        conn.commit()
        conn.close()
        return path

    def test_the_old_raw_hosts_are_migrated_on_the_next_open(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(tmp, ["www.x.ca", "m.y.ca", "z.ca"],
                            [("www.x.ca", "directory")])
            storage.SerpStorage(path)       # re-open runs the migration
            conn = sqlite3.connect(path)
            hosts = sorted(r[0] for r in conn.execute(
                "SELECT DISTINCT domain FROM serp_results"))
            features = sorted(r[0] for r in conn.execute(
                "SELECT domain FROM domain_features"))
            conn.close()
        self.assertEqual(hosts, ["x.ca", "y.ca", "z.ca"])
        self.assertEqual(features, ["x.ca"])

    def test_a_collision_keeps_the_canonical_rows_entity_type(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(tmp, [], [("www.x.ca", "directory"),
                                      ("x.ca", "practice")])
            storage.SerpStorage(path)
            conn = sqlite3.connect(path)
            rows = sorted(conn.execute(
                "SELECT domain, entity_type FROM domain_features"))
            conn.close()
        self.assertEqual(rows, [("x.ca", "practice")])


class TestOneDemandPredicate(unittest.TestCase):
    """Four implementations of "is this keyword's demand measured" is four
    chances to lose the unmeasured-vs-small distinction (P1)."""

    MEASURED = {"moz": {"data_available": True, "volume": 10}}
    UNMEASURED = {"moz": {"data_available": False, "status": "no record"}}
    NO_VOLUME = {"moz": {"data_available": True, "volume": None}}

    def test_the_two_modules_share_one_implementation(self):
        self.assertIs(brief_validation._keyword_volume,
                      keyword_demand.measured_volume)
        self.assertIs(brief_validation._any_demand_measured,
                      keyword_demand.any_measured)
        self.assertIs(brief_data_extraction._demand_too_small,
                      keyword_demand.too_small)
        self.assertIs(brief_data_extraction._demand_assessment,
                      keyword_demand.assessment)

    def test_an_unmeasured_keyword_is_never_a_small_market(self):
        for profile in (self.UNMEASURED, self.NO_VOLUME):
            self.assertFalse(keyword_demand.too_small(profile, 100))
            self.assertIsNone(keyword_demand.measured_volume(profile))
        self.assertTrue(keyword_demand.too_small(self.MEASURED, 100))

    def test_the_reason_distinguishes_the_three_states(self):
        self.assertEqual(
            keyword_demand.assessment(self.MEASURED, 100)[1], "measured")
        self.assertIn("not measured",
                      keyword_demand.assessment(self.UNMEASURED, 100)[1])
        self.assertIn("no volume floor",
                      keyword_demand.assessment(self.MEASURED, None)[1])


class TestTheCollapseDidNotNarrowTheInputs(unittest.TestCase):

    def test_a_non_dict_moz_block_is_unmeasured_not_a_crash(self):
        """The two predicates this module replaced returned "not measured" for
        a truthy non-dict; `assessment` raised `AttributeError`."""
        import keyword_demand

        for bad in ("ok", 3, [1]):
            self.assertEqual(
                keyword_demand.assessment({"moz": bad}, 50)[0], False, bad)
            self.assertEqual(keyword_demand.too_small({"moz": bad}, 50), False)
            self.assertIsNone(keyword_demand.measured_volume({"moz": bad}))


class TestEditorialValuesLiveInConfig(unittest.TestCase):

    def _config(self):
        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def test_the_title_dominance_threshold_is_config(self):
        cfg = self._config()
        self.assertIn("title_patterns", cfg)
        self.assertEqual(
            title_patterns.resolve_thresholds(cfg),
            (int(cfg["title_patterns"]["top_n"]),
             int(cfg["title_patterns"]["dominant_threshold"])))

    def test_a_nonsense_threshold_degrades_to_the_documented_default(self):
        """A `dominant_threshold` of 0 would make every pattern dominant, and
        a report cannot tell a configured 0 from a typo."""
        for bad in (0, -1, "four", None):
            self.assertEqual(
                title_patterns.resolve_thresholds(
                    {"title_patterns": {"dominant_threshold": bad}})[1],
                title_patterns.DOMINANT_THRESHOLD)

    def test_the_configured_count_decides_how_many_titles_are_read(self):
        titles = ["How to cope"] * 3 + ["What is bowen theory"] * 7
        wide = title_patterns.compute_title_patterns(titles, top_n=10,
                                                     dominant_threshold=4)
        narrow = title_patterns.compute_title_patterns(titles, top_n=3,
                                                       dominant_threshold=4)
        self.assertEqual(wide["dominant_pattern"], "what_is")
        self.assertIsNone(narrow["dominant_pattern"])

    def test_the_pipeline_reads_the_configured_threshold(self):
        """The profile builder took `(10, 4)` from Python. A config nobody
        reads is the fault P4 is about, not a tidier constant."""
        rows = [{"Source_Keyword": "couples therapy", "Rank": i + 1,
                 "Link": f"https://e{i}.com/p",
                 "Title": "What Is Bowen Theory" if i < 2 else f"Ten Tips {i}",
                 "Query_Label": "A", "Entity_Type": "practice",
                 "Content_Type": "service_page",
                 "Source": f"e{i}.com"}
                for i in range(10)]
        # `root_keywords` is read off the overview rows, so a run with no
        # overview has no profiles at all.
        data = {"organic_results": rows,
                "overview": [{"Source_Keyword": "couples therapy",
                              "Query_Label": "A", "Run_ID": "r1",
                              "Created_At": "2026-11-17",
                              "Total_Results": 1000}]}

        def _dominant(cfg):
            extracted = brief_data_extraction.extract_analysis_data_from_json(
                data, client_domain="livingsystems.ca",
                title_pattern_thresholds=title_patterns.resolve_thresholds(cfg))
            profile = (extracted.get("keyword_profiles") or {}).get(
                "couples therapy") or {}
            return (profile.get("title_patterns") or {}).get("dominant_pattern")

        # Two of ten titles are `what_is`: dominant at a threshold of 2,
        # not at the default 4.
        self.assertEqual(
            _dominant({"title_patterns": {"dominant_threshold": 2,
                                          "top_n": 10}}), "what_is")
        self.assertNotEqual(
            _dominant({"title_patterns": {"dominant_threshold": 4,
                                          "top_n": 10}}), "what_is")

    def test_a_threshold_that_can_never_be_reached_is_refused(self):
        """`dominant_threshold` above `top_n` makes `dominant_pattern` `None`
        on every SERP, which the brief reads as a fact about the SERP."""
        self.assertEqual(
            title_patterns.resolve_thresholds(
                {"title_patterns": {"top_n": 3, "dominant_threshold": 4}}),
            (title_patterns.TOP_N_DEFAULT, title_patterns.DOMINANT_THRESHOLD))
        # Equal is reachable: all three titles sharing a pattern.
        self.assertEqual(
            title_patterns.resolve_thresholds(
                {"title_patterns": {"top_n": 3, "dominant_threshold": 3}}),
            (3, 3))

    def test_the_provenance_line_names_the_config_keys(self):
        import thresholds_provenance

        label, keys = thresholds_provenance.FAMILIES["title_patterns"]
        self.assertEqual(keys, ("title_patterns.dominant_threshold",
                                "title_patterns.top_n"))
        self.assertNotIn("code constant", label)

    def test_the_feasibility_icons_come_from_the_messages_file(self):
        """This summary printed ⚠️ for "Not measured" while the configured
        icon is ❓ — one state, two glyphs, in one run's outputs.

        Asserted over the rendered markdown, not the source: a source guard
        passes just as well with a dict literal somewhere else in the file.
        """
        with open(os.path.join(REPO, "feasibility_messages.yml"),
                  encoding="utf-8") as f:
            statuses = yaml.safe_load(f)["statuses"] or {}
        rows = [{"Keyword": "couples therapy", "Query_Label": "A",
                 "feasibility_status": "Not Measured", "client_da": None,
                 "avg_serp_da": None, "gap": None, "feasibility_score": None,
                 "da_count": 0, "da_missing": 10},
                {"Keyword": "family therapy", "Query_Label": "A",
                 "feasibility_status": "High Feasibility", "client_da": 35,
                 "avg_serp_da": 20, "gap": -15, "feasibility_score": 0.9,
                 "da_count": 10, "da_missing": 0}]
        markdown = run_feasibility.generate_feasibility_report(
            rows, {"analysis_report": {"client_name": "C"}}, "nonexistent.json",
            keyword_profiles={})
        summary = markdown.split("## Summary", 1)[1].split("\n\n", 1)[0]
        table = markdown.split("## Keyword Feasibility Table", 1)[1]
        for status in ("Not Measured", "High Feasibility"):
            # The summary carries the configured words, not a literal with a
            # special case for one status.
            self.assertIn(f"{statuses[status]['label']}: ", summary, status)
            # And the table, twenty lines down, carries the same glyph for
            # the same state: `Not Measured` was \u2753 here and \u26a0\ufe0f there, which
            # is also `Moderate Feasibility`'s glyph.
            self.assertIn(statuses[status]["label"], table, status)
            self.assertTrue(
                statuses[status]["label"].startswith(statuses[status]["icon"]),
                f"{status}: the icon and the label disagree in the config")

    def test_no_two_statuses_share_a_glyph(self):
        """\u26a0\ufe0f meant both "Moderate Feasibility" and "Not measured", so the
        glyph alone did not identify the state."""
        with open(os.path.join(REPO, "feasibility_messages.yml"),
                  encoding="utf-8") as f:
            statuses = yaml.safe_load(f)["statuses"] or {}
        icons = [v["icon"] for v in statuses.values()]
        self.assertEqual(len(icons), len(set(icons)), icons)


class TestTheParityRuleSurvivesASpelling(unittest.TestCase):

    def test_either_spelling_of_the_label_trips_the_rule(self):
        """`play_routing.yml` says "Deprioritise"; a draft writing
        "Deprioritize" evaded a HARD rule built from the label."""
        import re

        pattern = brief_validation._play_assignment_phrase(
            "Deprioritise (no investment)")
        for text in ("recommended play: **deprioritize**",
                     "recommended play: deprioritise (no investment)"):
            self.assertTrue(re.search(pattern, text), text)

    def test_a_different_play_still_does_not_match(self):
        import re

        pattern = brief_validation._play_assignment_phrase("Rank play")
        self.assertIsNone(re.search(pattern,
                                    "recommended play: extraction play"))


if __name__ == "__main__":
    unittest.main()
