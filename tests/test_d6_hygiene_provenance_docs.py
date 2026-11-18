"""D6 — hygiene, provenance, docs.

Review chunk D6 (docs/review_2026-11-04/PLAN_D6_hygiene_provenance_docs.md):
findings D-C-16, D-C-17, D-M-09, D-M-10, D-M-21, D-M-22, D-M-23, D-M-24,
D-M-26 and the title_patterns severity lag.

One class per finding fixed. Each test names the figure or sentence that was
wrong, not the function it lives in, so a refactor that keeps the behaviour
keeps the guard.
"""
import os
import re
import unittest

import yaml

import feasibility
import intent_verdict
import pattern_matching
import thresholds_provenance

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# D-M-09 / D-M-24 — the feasibility statistic
# ---------------------------------------------------------------------------

class TestD6TheMeanIsNotTheWholeAnswer(unittest.TestCase):
    """A mean over a top 10 cannot say whether a DA-35 site has room."""

    def test_the_minimum_and_the_non_directory_minimum_are_reported(self):
        # The review's own probe: one DA-92 directory plus nine DA-18 clinics.
        # The mean (25.4) reads easy; what matters is that the weakest page
        # holding a slot is a DA-18 clinic.
        window = feasibility.DAWindow(
            das=[92] + [18] * 9, measured=10, missing=0, window=10,
            entities=["directory"] + ["counselling"] * 9)
        row = feasibility.compute_feasibility(35, window)
        self.assertEqual(row["avg_serp_da"], 25.4)
        self.assertEqual(row["min_competitor_da"], 18)
        self.assertEqual(row["min_non_directory_da"], 18)
        self.assertEqual(row["non_directory_count"], 9)
        # The other probe: five DA-85 sites plus five DA-12 clinics has the
        # higher mean and the lower floor, which is the point.
        window2 = feasibility.DAWindow(
            das=[85] * 5 + [12] * 5, measured=10, missing=0, window=10,
            entities=["directory"] * 5 + ["counselling"] * 5)
        row2 = feasibility.compute_feasibility(35, window2)
        self.assertGreater(row2["avg_serp_da"], row["avg_serp_da"])
        self.assertLess(row2["min_non_directory_da"],
                        row["min_non_directory_da"])

    def test_an_unresolved_entity_type_is_not_a_non_directory_competitor(self):
        """P1 — "nobody classified these" is not "no directory ranks here"."""
        row = feasibility.compute_feasibility(35, [85, 12, 40])
        self.assertEqual(row["min_competitor_da"], 12)
        self.assertIsNone(row["min_non_directory_da"])
        self.assertEqual(row["entities_known"], 0)
        self.assertIn("not measured", feasibility.minima_phrase(row))
        self.assertEqual(feasibility.minima_cell(row), "12 (?)")

        # Partial classification: the weakest page is the unclassified one.
        # It is not evidence that a non-directory page that weak ranks here,
        # so the non-directory minimum is the DA-40 page whose type is known.
        window = feasibility.DAWindow(
            das=[40, 12], measured=2, missing=0, window=2,
            entities=["counselling", None])
        partial = feasibility.compute_feasibility(35, window)
        self.assertEqual(partial["min_competitor_da"], 12)
        self.assertEqual(partial["min_non_directory_da"], 40)
        self.assertEqual(partial["entities_known"], 1)
        self.assertEqual(partial["non_directory_count"], 1)

    def test_a_partly_classified_window_says_how_many_it_knows(self):
        """D6 cold review — the prose quoted every figure over the window.

        With one of ten competitors classified, the sentence claimed all ten
        were directories, or quoted a non-directory minimum "over 10 scored
        competitors" when it rested on one.
        """
        das = [90, 80, 70, 60, 50, 40, 30, 25, 20, 12]
        # One classified, and it is a directory.
        window = feasibility.DAWindow(
            das=das, measured=10, missing=0, window=10,
            entities=["directory"] + [None] * 9)
        row = feasibility.compute_feasibility(35, window)
        phrase = feasibility.minima_phrase(row)
        self.assertIn("1 of 10", phrase)
        self.assertNotIn("Every one of the 10", phrase)
        self.assertIn("9", phrase)          # the unclassified remainder
        self.assertEqual(feasibility.minima_cell(row), "12 (none?)")
        # One classified, and it is not a directory: 90 is the STRONGEST page,
        # so the sentence may not offer it as what a small site must beat
        # without saying how little it rests on.
        window = feasibility.DAWindow(
            das=das, measured=10, missing=0, window=10,
            entities=["publisher"] + [None] * 9)
        row = feasibility.compute_feasibility(35, window)
        phrase = feasibility.minima_phrase(row)
        self.assertEqual(row["min_non_directory_da"], 90)
        self.assertIn("1 of 10", phrase)
        self.assertIn("not classified", phrase)
        self.assertEqual(feasibility.minima_cell(row), "12 (90?)")
        # A fully classified window carries no qualifier.
        window = feasibility.DAWindow(
            das=[40, 12], measured=2, missing=0, window=2,
            entities=["publisher", "directory"])
        full = feasibility.compute_feasibility(35, window)
        self.assertEqual(feasibility.minima_cell(full), "12 (40)")
        self.assertNotIn("not classified", feasibility.minima_phrase(full))

    def test_a_failing_classifier_is_counted_not_swallowed(self):
        """P2 — every SERP reading "not measured" with nothing saying why."""
        def boom(url):
            raise RuntimeError("classifier down")
        with self.assertLogs(level="WARNING") as logs:
            window = feasibility.competitor_da_window(
                ["https://a.com", "https://b.com"],
                da_for_url=lambda u: 40, entity_for_url=boom)
        self.assertEqual(list(window.entities), [None, None])
        self.assertIn("entity classification failed for 2 of 2",
                      "\n".join(logs.output))

    def test_both_producers_and_the_database_carry_the_minima(self):
        """Finding F9 again: the fields reached the report, not the DB."""
        # The pipeline's row carries the whole assessment, so a new field
        # cannot miss it. Asserted by running the pass that builds the row
        # (it was a grep for `**feas,` in serp_audit.py until the decision
        # moved to pivot_pass.py in chunk Y6); the other names the field set.
        import pivot_pass
        feas = feasibility.compute_feasibility(
            35, feasibility.DAWindow([90] * 8, 8, 0, 8))
        rows, _ = pivot_pass.decide_pivots(
            [{"keyword": "therapy vancouver", "feas": feas,
              "client_da_source": "moz", "is_service_like": True}],
            {}, location="North Vancouver, BC", neighborhoods=["Lonsdale"],
            pivotable_intents=("local",), pivot_fetch=False, storage=None,
            run_id="r1", log=lambda *_: None)
        for key in feasibility.MINIMA_FIELDS:
            self.assertIn(key, rows[0])
        self.assertIn("MINIMA_FIELDS", _read("storage.py"))
        # Both of the standalone producer's rows — the primary keyword and
        # the pivot keyword — carry the set, not just one of them.
        rf = _read("run_feasibility.py")
        for marker in ('"Query_Label": "A"', '"Query_Label": "P"'):
            region = rf[rf.index(marker):]
            region = region[:region.index('"da_provider"')]
            self.assertIn("MINIMA_FIELDS", region, marker)
        import sqlite3, tempfile, os as _os
        import storage as storage_mod
        tmp = tempfile.mkdtemp()
        db = storage_mod.SerpStorage(_os.path.join(tmp, "t.db"))
        db.save_feasibility_from_row(
            {"Keyword": "k", "avg_serp_da": 50.0, "gap": 15.0,
             "feasibility_status": "Low Feasibility",
             "min_competitor_da": 12, "max_competitor_da": 90,
             "min_non_directory_da": 40, "non_directory_count": 3,
             "entities_known": 7},
            run_id="r1", query_label="A")
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            got = dict(conn.execute(
                "SELECT * FROM keyword_feasibility").fetchone())
        for key in feasibility.MINIMA_FIELDS:
            self.assertIn(key, got)
        self.assertEqual(got["min_non_directory_da"], 40)
        self.assertEqual(got["entities_known"], 7)

    def test_the_renderer_names_the_configs_directory_types(self):
        """D6 cold review — the prose said "directory" whatever config said."""
        row = feasibility.compute_feasibility(
            35, feasibility.DAWindow(das=[40, 12], measured=2, missing=0,
                                     window=2,
                                     entities=["counselling", "publisher"]))
        phrase = feasibility.minima_phrase(
            row, directory_types=("directory", "publisher"))
        self.assertIn("directory / publisher", phrase)
        self.assertIn("resolve_directory_entity_types",
                      _read("generate_insight_report.py"))

    def test_every_scored_competitor_a_directory_says_so(self):
        window = feasibility.DAWindow(
            das=[85, 70], measured=2, missing=0, window=2,
            entities=["directory", "directory"])
        row = feasibility.compute_feasibility(35, window)
        self.assertIsNone(row["min_non_directory_da"])
        self.assertEqual(row["entities_known"], 2)
        phrase = feasibility.minima_phrase(row)
        self.assertIn("no evidence either way", phrase)
        self.assertEqual(feasibility.minima_cell(row), "70 (none)")

    def test_directory_types_are_editorial_config(self):
        self.assertEqual(
            feasibility.resolve_directory_entity_types(
                {"feasibility": {"directory_entity_types":
                                 ["directory", "Professional_Association"]}}),
            ("directory", "professional_association"))
        # Absent or malformed: the documented default, never an empty set
        # (an empty set would make every competitor non-directory).
        self.assertEqual(feasibility.resolve_directory_entity_types({}),
                         feasibility.DEFAULT_DIRECTORY_ENTITY_TYPES)
        self.assertEqual(
            feasibility.resolve_directory_entity_types(
                {"feasibility": {"directory_entity_types": "directory"}}),
            feasibility.DEFAULT_DIRECTORY_ENTITY_TYPES)
        cfg = yaml.safe_load(_read("config.yml"))
        self.assertIn("directory_entity_types", cfg["feasibility"])

    def test_the_window_carries_the_entity_type_it_was_given(self):
        urls = ["https://a.com/x", "https://b.com/y"]
        window = feasibility.competitor_da_window(
            urls, lambda u: 50,
            entity_for_url={"https://a.com/x": "directory"}.get)
        self.assertEqual(list(window.entities), ["directory", None])
        # A classifier that raises does not take the run down with it; that
        # URL is simply unclassified.
        window2 = feasibility.competitor_da_window(
            urls, lambda u: 50,
            entity_for_url=lambda u: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(list(window2.entities), [None, None])

    def test_feasibility_score_stays_inside_its_documented_range(self):
        """D-M-24 — a real run wrote 1.47 into SQLite and the workbook."""
        # Gap -15 (client far stronger than the mean) was 1.5.
        row = feasibility.compute_feasibility(35, [20] * 10)
        self.assertEqual(row["gap"], -15.0)
        self.assertEqual(row["feasibility_score"], 1.0)
        # The floor still holds at the other end.
        self.assertEqual(
            feasibility.compute_feasibility(5, [95] * 10)["feasibility_score"],
            0.0)


# ---------------------------------------------------------------------------
# D-M-10 / D-C-17 — coverage is not certainty, and neither knob was dead
# ---------------------------------------------------------------------------

def _rows(informational, commercial):
    rows = [{"link": f"https://x{i}.com", "content_type": "guide",
             "entity_type": "counselling"} for i in range(informational)]
    rows += [{"link": f"https://y{i}.com", "content_type": "service",
              "entity_type": "directory"} for i in range(commercial)]
    return rows


class TestD6CoverageIsNotCertainty(unittest.TestCase):

    def test_a_six_four_split_is_not_a_certain_verdict(self):
        """The review's case: 6/4 read as "high confidence"."""
        verdict = intent_verdict.compute_serp_intent(_rows(6, 4), False)
        self.assertEqual(verdict["primary_intent"], "informational")
        # All ten were classified, so coverage is high — that much was true.
        self.assertEqual(verdict["classification_coverage"], "high")
        self.assertEqual(verdict["confidence"], "high")   # published alias
        # But only 60% of them agreed, which is not high certainty.
        self.assertEqual(verdict["leading_intent_share"], 0.6)
        self.assertEqual(verdict["intent_certainty"], "medium")

    def test_the_share_is_taken_over_the_classified_urls(self):
        """The denominator is the classified URLs, not every organic row."""
        rows = _rows(6, 2) + [{"link": f"https://z{i}.com",
                               "content_type": "unknown",
                               "entity_type": "unknown"} for i in range(4)]
        verdict = intent_verdict.compute_serp_intent(rows, False)
        self.assertEqual(verdict["evidence"]["organic_url_count"], 12)
        self.assertEqual(verdict["evidence"]["classified_organic_url_count"], 8)
        # 6 of the 8 classified agreed — not 6 of 12.
        self.assertEqual(verdict["leading_intent_share"], 0.75)

    def test_thin_coverage_does_not_buy_a_high_rank(self):
        """D6 cold review — one classified URL scores certainty 1.0."""
        import generate_insight_report as gir
        thin = {"intent_certainty": "high", "leading_intent_share": 1.0}
        # Coverage "low" means almost nothing was classified, so the share is
        # not evidence and may not order the list above a covered SERP.
        self.assertEqual(gir._intent_rank_word(thin, "low"), "low")
        self.assertEqual(gir._intent_rank_word(thin, "high"), "high")
        # A SERP nobody could classify falls back too, rather than ranking as
        # if its certainty were a measurement.
        self.assertEqual(
            gir._intent_rank_word({"intent_certainty": "not_measured"},
                                  "medium"), "medium")
        # A row written before D6.3 has no certainty at all.
        self.assertEqual(gir._intent_rank_word({}, "high"), "high")

    def test_the_share_is_named_after_the_leading_intent(self):
        """D6 cold review — the share is taken even when the verdict is
        "mixed" or withheld, so it is not the primary intent's share."""
        import generate_insight_report as gir
        cell = gir._certainty_cell({"intent_certainty": "medium",
                                    "leading_intent_share": 0.6,
                                    "primary_intent": "mixed"})
        self.assertIn("leading intent 60% of classified", cell)
        self.assertNotIn("primary_intent_share", _read("intent_verdict.py"))

    def test_the_certainty_thresholds_have_a_reader(self):
        """D-C-17 — tuning either knob used to change nothing."""
        rows = _rows(6, 4)
        strict = intent_verdict.compute_serp_intent(
            rows, False, thresholds={"confidence_high": 0.95,
                                     "confidence_medium": 0.7})
        self.assertEqual(strict["intent_certainty"], "low")
        loose = intent_verdict.compute_serp_intent(
            rows, False, thresholds={"confidence_high": 0.55})
        self.assertEqual(loose["intent_certainty"], "high")

    def test_nothing_classified_is_not_a_weak_lead(self):
        rows = [{"link": "https://a.com", "content_type": "unknown",
                 "entity_type": "unknown"}]
        verdict = intent_verdict.compute_serp_intent(rows, False)
        self.assertIsNone(verdict["leading_intent_share"])
        self.assertEqual(verdict["intent_certainty"], "not_measured")

    def test_no_serp_intent_threshold_is_without_a_reader(self):
        """Every key under the block is consumed, or this test names it."""
        cfg = yaml.safe_load(_read("config.yml"))
        keys = set(cfg["serp_intent"]["thresholds"])
        source = _read("intent_verdict.py")
        unread = sorted(k for k in keys if k not in source)
        self.assertEqual(unread, [], f"dead config keys: {unread}")
        # And the defaults the module falls back to cover the same keys, so a
        # config that omits one does not silently change behaviour.
        self.assertEqual(set(intent_verdict.DEFAULT_THRESHOLDS), keys)


# ---------------------------------------------------------------------------
# D-M-26 — a fired pattern has to say how much it fired
# ---------------------------------------------------------------------------

class TestD6TriggerPresenceIsQuantified(unittest.TestCase):

    CORPUS = [
        "a clinical assessment and a diagnosis for the patient",
        "treatment plans and a diagnosis",
        "how families work as a system",
    ]
    NGRAMS = [{"Phrase": "clinical assessment", "Count": 3},
              {"Phrase": "diagnosis patient", "Count": 2}]

    def test_a_fired_pattern_reports_its_hits_and_its_denominator(self):
        recs = pattern_matching.analyze_strategic_opportunities(
            self.NGRAMS, texts=self.CORPUS)
        medical = next(r for r in recs
                       if r["Pattern_Name"] == "The Medical Model Trap")
        self.assertEqual(medical["Snippets_Scanned"], 3)
        # "clinical" is in one text block of three, "diagnosis" in two. A
        # pattern that fired in one block of forty used to read the same as
        # one that fired in all forty.
        self.assertEqual(medical["Trigger_Hits"]["clinical"], 1)
        self.assertEqual(medical["Trigger_Hits"]["diagnosis"], 2)
        self.assertEqual(medical["Snippets_With_Trigger"], 2)
        # The denominator counts SERP text blocks — snippets, ad copy,
        # related searches, several per result — not pages, and no field or
        # sentence may call them pages (D6 cold review).
        self.assertNotIn("Pages_Scanned", medical)
        self.assertNotIn("Pages_With_Trigger", medical)

    def test_a_detected_trigger_is_counted_in_the_text_it_fired_in(self):
        """A trigger listed as detected and counted 0 in the same line.

        The fire test ran over the n-gram phrases, which have stop words and
        short words stripped, while the count ran over the raw text — so
        "reach out" fired and then counted zero (D6 cold review).
        """
        # The n-gram phrases name a trigger the text corpus does not carry,
        # so firing off the n-grams would list it as detected and count it 0.
        corpus = ["reach out for help with a diagnosis"]
        ngrams = [{"Phrase": "reach help diagnosis", "Count": 2},
                  {"Phrase": "treatment medication", "Count": 2}]
        recs = pattern_matching.analyze_strategic_opportunities(
            ngrams, texts=corpus)
        for rec in recs:
            hits = rec.get("Trigger_Hits")
            if not isinstance(hits, dict):
                continue
            for trigger in [t.strip() for t
                            in (rec["Detected_Triggers"] or "").split(",")
                            if t.strip()]:
                self.assertGreater(
                    hits.get(trigger, 0), 0,
                    f"{rec['Pattern_Name']}: {trigger} fired but counted 0")

    def test_no_corpus_is_not_zero_hits(self):
        """P1/P2 — a count nobody took is not a count of none."""
        recs = pattern_matching.analyze_strategic_opportunities(self.NGRAMS)
        medical = next(r for r in recs
                       if r["Pattern_Name"] == "The Medical Model Trap")
        self.assertIsNone(medical["Trigger_Hits"])
        self.assertIsNone(medical["Snippets_Scanned"])
        import generate_insight_report as gir
        self.assertIn("not quantified this run",
                      gir._trigger_presence(medical))

    def test_the_pipeline_hands_the_matcher_a_corpus(self):
        """A count nobody took is reported as such, so the caller must supply
        the pages — otherwise every pattern prints "not quantified"."""
        source = _read("serp_audit.py")
        call = source[source.index("analyze_strategic_opportunities("):]
        call = call[:call.index(")") + 1]
        self.assertIn("texts=", call)

    def test_the_report_prints_the_counts_and_says_what_it_measures(self):
        import generate_insight_report as gir
        text = gir._trigger_presence({
            "Detected_Triggers": "clinical, diagnosis",
            "Trigger_Hits": {"clinical": 1, "diagnosis": 2},
            "Snippets_With_Trigger": 2, "Snippets_Scanned": 20})
        self.assertIn("clinical (1 of 20 SERP text blocks)", text)
        self.assertIn("2 of 20 scanned SERP text blocks carry at least one "
                      "(10%)", text)
        source = _read("generate_insight_report.py")
        self.assertIn("trigger-word presence in the SERP text", source)
        self.assertIn("not framing analysis", source)
        # The corpus is snippets and related searches, so the section must
        # not describe it as the ranking pages' own text.
        self.assertNotIn("pages' text, not framing", source)

    def test_triggers_obey_the_files_own_rule(self):
        """The file forbids words that appear everywhere in the domain."""
        patterns = yaml.safe_load(_read("strategic_patterns.yml"))
        triggers = {t.lower() for p in patterns
                    for t in (p.get("Triggers") or [])}
        # Named in the review as appearing on essentially every BC
        # counselling page or every couples page.
        for word in ("registered", "mental health", "close", "communication"):
            self.assertNotIn(word, triggers)
        # The file's own minimum length rule.
        for t in triggers:
            self.assertGreaterEqual(len(t), 4, t)


# ---------------------------------------------------------------------------
# D-M-21 — a threshold states where it came from
# ---------------------------------------------------------------------------

class TestD6ThresholdsStateTheirProvenance(unittest.TestCase):

    def test_an_unrecorded_source_is_said_to_be_uncalibrated(self):
        resolved = thresholds_provenance.resolve({})
        self.assertEqual(set(resolved), set(thresholds_provenance.FAMILIES))
        for family, text in resolved.items():
            self.assertEqual(text, thresholds_provenance.UNRECORDED, family)
        body = "\n".join(thresholds_provenance.lines({}))
        self.assertIn("editorial, uncalibrated", body)
        # Each line names the config keys that hold its numbers, so a reader
        # can check them.
        self.assertIn("`gsc_demand.bands`", body)
        self.assertIn("`serp_intent.thresholds`", body)

    def test_the_figures_are_read_from_config_not_copied_into_python(self):
        """P4/P6 — a provenance section printing stale numbers is worse than
        none, so no family label may carry a figure of its own."""
        labels = " ".join(label for label, _ in
                          thresholds_provenance.FAMILIES.values())
        self.assertFalse([c for c in labels if c.isdigit()],
                         f"a threshold figure is copied into a label: {labels}")
        cfg = {"gsc_demand": {"bands": {"below_avg": 0.077, "top": 0.5}}}
        body = "\n".join(thresholds_provenance.lines(cfg))
        # The live value, not the value that was true when this was written.
        self.assertIn("0.077", body)
        self.assertNotIn("2.4%", body)

    def test_a_key_the_config_does_not_set_says_so(self):
        body = "\n".join(thresholds_provenance.lines({}))
        self.assertIn("`gsc_demand.bands` not set — the code default applies",
                      body)

    def test_a_recorded_source_is_printed_instead(self):
        cfg = {"thresholds_provenance": {
            "feasibility": "Acme 2026 band study, retrieved 2026-03-01"}}
        resolved = thresholds_provenance.resolve(cfg)
        self.assertEqual(resolved["feasibility"],
                         "Acme 2026 band study, retrieved 2026-03-01")
        self.assertEqual(resolved["commodity"],
                         thresholds_provenance.UNRECORDED)
        body = "\n".join(thresholds_provenance.lines(cfg))
        self.assertIn("Acme 2026 band study", body)

    def test_a_malformed_block_reports_rather_than_raises(self):
        self.assertEqual(
            thresholds_provenance.resolve({"thresholds_provenance": "yes"}),
            {f: thresholds_provenance.UNRECORDED
             for f in thresholds_provenance.FAMILIES})
        self.assertEqual(
            thresholds_provenance.resolve(
                {"thresholds_provenance": {"feasibility": 0.5}})["feasibility"],
            thresholds_provenance.UNRECORDED)

    def test_every_family_is_in_config_and_the_report_prints_the_block(self):
        cfg = yaml.safe_load(_read("config.yml"))
        self.assertEqual(set(cfg["thresholds_provenance"]),
                         set(thresholds_provenance.FAMILIES))
        source = _read("generate_insight_report.py")
        self.assertIn("thresholds_provenance.lines(_load_config())", source)

    def test_the_glossary_says_the_bands_are_editorial(self):
        glossary = yaml.safe_load(_read("glossary.yml"))
        by_term = {t["term"]: t["definition"] for t in glossary["terms"]}
        for term in ("feasibility status", "commodity score"):
            self.assertIn("editorial", by_term[term].lower(), term)


# ---------------------------------------------------------------------------
# D-M-22 / D-M-23 / D-C-16 / the title_patterns lag — documents
# ---------------------------------------------------------------------------

class TestD6TheDocsSayWhatTheCodeDoes(unittest.TestCase):

    def test_the_glossary_states_the_da_gap_in_the_codes_direction(self):
        """D-M-23 — a reversed formula printed in every report's section A."""
        glossary = yaml.safe_load(_read("glossary.yml"))
        entry = next(t for t in glossary["terms"] if t["term"] == "DA gap")
        text = entry["definition"].lower()
        self.assertIn("currently ranking, minus yours", text)
        # The code's direction, asserted rather than described.
        row = feasibility.compute_feasibility(35, [50] * 10)
        self.assertEqual(row["gap"], 15.0)      # avg - client, positive = harder
        self.assertIn("positive gap means they are stronger", text)

    def test_the_root_reading_guide_does_not_pose_as_the_contract(self):
        """D-M-22 — two methodology documents, one of them stale."""
        head = _read("methodology.md")[:1800].lower()
        self.assertIn("dated snapshot, not the contract", head)
        self.assertIn("docs/methodology.md", head)
        self.assertIn("where the two disagree", head)
        # The banner names the passages a reader would otherwise trust.
        self.assertIn("known stale passages", head)
        self.assertIn("intent_classifier_triggers.yml", head)

    def test_the_intent_mapping_header_claims_no_count_the_code_never_adds(self):
        """D-M-22 — "the local pack contributes its own local count"."""
        header = _read("intent_mapping.yml")
        self.assertNotIn("local pack contributes its own `local` count", header)
        # And the code still does not count map-pack members as URLs, which is
        # why the sentence had to go rather than the behaviour.
        verdict = intent_verdict.compute_serp_intent(
            _rows(5, 0), True, local_pack_member_count=3)
        self.assertEqual(verdict["evidence"]["organic_url_count"], 5)
        self.assertEqual(sum(verdict["intent_distribution"].values()), 5)

    def test_title_patterns_severity_is_stated_once(self):
        """The code hard-fails; two documents called it soft."""
        import brief_validation
        issue = ("Report contradicts keyword_profiles.title_patterns for 'x': "
                 "claims question dominance, but dominant_pattern='listicle'.")
        self.assertTrue(brief_validation.has_hard_validation_failures([issue]))
        blocking, notes = brief_validation.partition_validation_issues([issue])
        self.assertEqual((blocking, notes), ([issue], []))
        # Which side of the sentence it is on, not whether the word "soft"
        # appears in it: one README sentence correctly says title_patterns
        # hard-fails and mixed_intent_strategy soft-fails. The severity
        # governing a mention is the last one named before it.
        for doc in ("CLAUDE.md", "README.md"):
            for sentence in re.split(r"(?<=[.;])\s+", _read(doc)):
                for match in re.finditer("title_patterns", sentence):
                    before = sentence[:match.start()].upper()
                    said = re.findall(r"HARD|SOFT", before)
                    self.assertNotEqual(
                        said[-1] if said else "HARD", "SOFT",
                        f"{doc} puts title_patterns on the soft side: "
                        f"{sentence.strip()[:160]}")

    def test_the_moz_freshness_test_has_no_hardcoded_date(self):
        """D-C-16 — closed by abcc2aa; this keeps it closed."""
        source = _read("test_moz_competitor.py")
        start = source.index("class TestCollectionFreshness")
        body = source[start:]
        end = body.find("\nclass ")
        body = body[:end] if end > 0 else body
        self.assertIn("timedelta(days=5)", body)
        # A freshness anchor written as a literal date passes until that date
        # falls outside the TTL and then fails forever. Fixture timestamps
        # elsewhere in the file are data, not anchors, so only this class is
        # guarded.
        self.assertIsNone(re.search(r'"20\d\d-\d\d-\d\dT', body),
                          "a literal timestamp here is a date bomb")


if __name__ == "__main__":
    unittest.main()
