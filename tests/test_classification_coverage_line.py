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


def _row(content_type, fetch_status="Enriched"):
    return {"Content_Type": content_type, "Fetch_Status": fetch_status}


class TestClassificationCoverageLine(unittest.TestCase):

    def test_the_live_run_shape_names_every_cause_with_its_count(self):
        rows = ([_row("guide")] * 15
                + [_row("Not Measured", "Not The Ranked Page")] * 125
                + [_row("Not Measured", "Not Fetched")] * 58
                + [_row("Not Measured", "Blocked (403)")] * 14)
        line = enrichment.classification_coverage_line(rows)
        self.assertIn("15 of 212", line)
        self.assertIn("125 × Not The Ranked Page", line)
        self.assertIn("58 × Not Fetched", line)
        self.assertIn("14 × Blocked (403)", line)

    def test_the_largest_cause_is_named_first(self):
        """The operator's next action depends on which cause dominates — a
        link that never resolved and a page that was blocked need different
        responses."""
        rows = ([_row("Not Measured", "Not Fetched")] * 2
                + [_row("Not Measured", "Blocked (403)")] * 7)
        line = enrichment.classification_coverage_line(rows)
        self.assertLess(line.index("Blocked (403)"), line.index("Not Fetched"))

    def test_none_classified_is_not_reported_as_a_count_of_zero(self):
        """"0 of 10 were classified" reads as a measurement; none at all means
        no keyword can have an intent verdict this run, which is a different
        statement and the one the reader needs (P1)."""
        line = enrichment.classification_coverage_line(
            [_row("Not Measured", "Not Fetched")] * 10)
        self.assertIn("none of 10", line)
        self.assertIn("no keyword", line.lower())

    def test_a_fully_classified_run_says_nothing(self):
        self.assertEqual("", enrichment.classification_coverage_line(
            [_row("guide"), _row("news")]))

    def test_no_results_says_nothing(self):
        for empty in ([], None, [None, "not a row"]):
            with self.subTest(empty=empty):
                self.assertEqual(
                    "", enrichment.classification_coverage_line(empty))

    def test_the_fields_own_na_marker_counts_as_unclassified(self):
        line = enrichment.classification_coverage_line(
            [_row("guide"), _row("N/A", "No URL")])
        self.assertIn("1 of 2", line)
        self.assertIn("No URL", line)

    def test_a_row_with_no_recorded_reason_is_counted_not_dropped(self):
        """A row that is unclassified for a reason nothing wrote down is still
        a row the reader's total has to account for."""
        line = enrichment.classification_coverage_line(
            [_row("guide")] * 3 + [{"Content_Type": "Not Measured"}])
        self.assertIn("3 of 4", line)
        self.assertIn("no reason recorded", line)

    def test_the_words_come_from_serp_vocab(self):
        with patch.dict(enrichment.SERP_VOCAB,
                        {"classification_coverage": {
                            "line": "EDITED {classified}/{total}: {reasons}",
                            "reason_item": "{label} ({count})"}},
                        clear=False):
            line = enrichment.classification_coverage_line(
                [_row("guide"), _row("Not Measured", "Not Fetched")])
        self.assertEqual("EDITED 1/2: Not Fetched (1)", line)

    def test_a_malformed_template_degrades_to_english(self):
        """The words are editable, so they can be edited wrongly. A report
        that aborts because a placeholder was mistyped is worse than one
        carrying the built-in wording."""
        with patch.dict(enrichment.SERP_VOCAB,
                        {"classification_coverage": {
                            "line": "{no_such_placeholder}"}},
                        clear=False):
            line = enrichment.classification_coverage_line(
                [_row("guide"), _row("Not Measured", "Not Fetched")])
        self.assertIn("1 of 2", line)


class TestItReachesTheReport(unittest.TestCase):

    def test_section_0_renders_the_line(self):
        import generate_insight_report as gir
        rows = [_row("guide")] + [_row("Not Measured", "Not Fetched")] * 4
        section = gir._render_executive_summary(
            {"organic_results": rows, "keyword_profiles": {},
             "keyword_feasibility": [], "strategic_recommendations": []},
            None, "feasibility data is missing.")
        self.assertIn("1 of 5", "\n".join(section))


if __name__ == "__main__":
    unittest.main()
