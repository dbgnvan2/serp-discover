"""The report says how many ranked results were classified, and why not.

The 2026-11-18 live run produced ten "Deprioritise" verdicts and no page
recommendation for any keyword, because 125 of 221 ranked results came back as
a Google redirect that recovered only to a site root and 58 were never
fetched, so almost nothing could be classified and no keyword could have a
SERP intent verdict. The cause was recorded on every row in `Fetch_Status`
and stated in no sentence anywhere: §0 said only that feasibility was missing,
and each keyword's section said "0 of 10 URLs could be classified" without
saying what stopped them (P2).

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §9 C3
"""
import unittest
from unittest.mock import patch

import enrichment


def _profile(total, classified, by_state=None):
    """One keyword profile carrying the two blocks the line reads."""
    return {"serp_intent": {"evidence": {
                "organic_url_count": total,
                "classified_organic_url_count": classified}},
            "schema_signals": {"fetch_coverage": {
                "rows": total, "by_state": dict(by_state or {})}}}


class TestItCountsWhatTheVerdictCounts(unittest.TestCase):
    """Finding 1 of this fix's cold review. The first version counted rows
    whose `Content_Type` was an unmeasured marker, which is a different
    measurement from the one the per-keyword sections print: on the
    2026-11-18 run it gave "15 of 221" against §5b's "6 of 100", in one
    report, under one word."""

    def test_the_figure_is_the_sum_of_the_keywords_own_evidence(self):
        line = enrichment.classification_coverage_line({
            "a": _profile(10, 2, {"not_attempted": 8}),
            "b": _profile(10, 4, {"blocked": 6})})
        self.assertIn("6 of 20", line)

    def test_a_page_read_but_unmapped_is_still_counted_and_named(self):
        """The suppression arm the review found: on a SERP where every page
        types as `other`, no row carries an unmeasured content type, so the
        first version returned "" and the report fell silent again — the
        exact 2026-11-18 failure."""
        line = enrichment.classification_coverage_line({"a": _profile(10, 0)})
        self.assertNotEqual("", line)
        self.assertIn("10", line)
        self.assertIn("page type", line)

    def test_the_causes_add_up_to_the_deficit(self):
        """A reader who totals the causes and finds them short of the deficit
        concludes the rest is unexplained (P2)."""
        line = enrichment.classification_coverage_line({
            "a": _profile(10, 3, {"not_attempted": 4, "blocked": 1})})
        self.assertIn("4 \u00d7", line)
        self.assertIn("1 \u00d7", line)
        # 10 - 3 = 7 unclassified; 5 unread, so 2 read-but-unmapped.
        self.assertIn("2 \u00d7 their page type", line)

    def test_the_causes_are_counted_over_the_same_window(self):
        """`fetch_coverage.by_state` counts the top-10 window the verdict
        used. Counting the raw rows pooled every rank, so a cause could
        outnumber its own total."""
        line = enrichment.classification_coverage_line({
            "a": _profile(10, 0, {"not_destination_page": 10})})
        self.assertIn("10 \u00d7", line)
        self.assertNotIn("20", line)

    def test_a_fully_classified_run_says_nothing(self):
        self.assertEqual("", enrichment.classification_coverage_line(
            {"a": _profile(10, 10)}))

    def test_no_evidence_says_nothing(self):
        for empty in ({}, None, {"a": {}}, {"a": {"serp_intent": {}}},
                      "not a mapping"):
            with self.subTest(empty=empty):
                self.assertEqual(
                    "", enrichment.classification_coverage_line(empty))

    def test_none_classified_is_not_reported_as_a_count_of_zero(self):
        """"0 of 10 were classified" reads as a measurement; none at all means
        no keyword can have an intent verdict this run (P1)."""
        line = enrichment.classification_coverage_line(
            {"a": _profile(10, 0, {"not_attempted": 10})})
        self.assertIn("none of 10", line)
        self.assertIn("no keyword", line.lower())


class TestTheWordsAreEditable(unittest.TestCase):

    def test_the_words_come_from_serp_vocab(self):
        with patch.dict(enrichment.SERP_VOCAB,
                        {"classification_coverage": {
                            "line": "EDITED {classified}/{total}: {reasons}",
                            "reason_item": "{label} ({count})"}},
                        clear=False):
            line = enrichment.classification_coverage_line(
                {"a": _profile(10, 9, {"no_url": 1})})
        self.assertEqual("EDITED 9/10: the row carried no URL (1)", line)

    def test_a_malformed_sentence_degrades_to_english(self):
        with patch.dict(enrichment.SERP_VOCAB,
                        {"classification_coverage": {
                            "line": "{no_such_placeholder}"}},
                        clear=False):
            line = enrichment.classification_coverage_line(
                {"a": _profile(10, 9, {"no_url": 1})})
        self.assertIn("9 of 10", line)

    def test_a_malformed_reason_item_degrades_too(self):
        """Finding 2: the reason join ran OUTSIDE the guard, so a mistyped
        placeholder in the one sub-template users are most likely to edit
        raised a KeyError and took the whole report down."""
        with patch.dict(enrichment.SERP_VOCAB,
                        {"classification_coverage": {
                            "reason_item": "{cnt} x {label}"}},
                        clear=False):
            line = enrichment.classification_coverage_line(
                {"a": _profile(10, 9, {"no_url": 1})})
        self.assertIn("9 of 10", line)
        self.assertIn("no URL", line)


class TestTheUnreadPhrasesHaveOneHome(unittest.TestCase):

    def test_reason_text_reads_serp_vocab(self):
        with patch.dict(enrichment.SERP_VOCAB,
                        {"fetch_status": {"reasons": {"no_url": "EDITED"}}},
                        clear=False):
            self.assertEqual("EDITED",
                             enrichment.reason_text(enrichment.NO_URL))

    def test_every_unread_state_has_a_phrase(self):
        for state in enrichment.UNREAD_STATES:
            with self.subTest(state=state):
                phrase = enrichment.reason_text(state)
                self.assertTrue(phrase)
                # Not the raw state key, which is what a missing entry would
                # put in a sentence the operator reads.
                self.assertNotEqual(state, phrase)

    def test_the_brief_reads_the_same_phrases(self):
        """They were a second Python copy in `brief_data_extraction`."""
        import brief_data_extraction as bde
        for state in enrichment.UNREAD_STATES:
            with self.subTest(state=state):
                self.assertEqual(enrichment.reason_text(state),
                                 bde._UNREAD_FETCH_STATES[state])


class TestItReachesTheReport(unittest.TestCase):

    def test_section_0_renders_the_line(self):
        import generate_insight_report as gir
        section = gir._render_executive_summary(
            {"keyword_profiles": {"a": _profile(10, 1, {"no_url": 9})},
             "keyword_feasibility": [], "strategic_recommendations": []},
            None, "feasibility data is missing.")
        self.assertIn("1 of 10", "\n".join(section))


if __name__ == "__main__":
    unittest.main()
