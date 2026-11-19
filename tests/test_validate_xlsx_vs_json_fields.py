"""Step 1.2 compares the rows' VALUES, not only their keys.

The gate the pipeline labels "Data Validation" compared row counts and key
tuples only: `normalize_text_cols` was computed into a record that was then
discarded and `required_cols` was never read, so a workbook whose `Title`,
`Snippet`, `Word_Count` or `Content_Type` disagreed with the JSON passed.
Found as an adjacent issue by the cold review of the 2026-11-18 live-run
fixes; fixed 2026-11-19.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §9 C2
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

import validate_xlsx_vs_json as v

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN_ID = "20261119_090000"


def _organic(**over):
    row = {"Run_ID": RUN_ID, "Rank": 3, "Link": "https://example.com/a",
           "Title": "A page title", "Snippet": "A snippet.",
           "Source": "example.com", "Content_Type": "Article",
           "Entity_Type": "clinic", "Word_Count": 1200, "Rank_Delta": -1}
    row.update(over)
    return row


def _run(xlsx_rows, json_rows):
    """Write the two files from DIFFERENT rows and validate them."""
    with tempfile.TemporaryDirectory() as tmp:
        xlsx = os.path.join(tmp, "m.xlsx")
        js = os.path.join(tmp, "m.json")
        out = os.path.join(tmp, "diff.json")
        with pd.ExcelWriter(xlsx) as writer:
            pd.DataFrame(xlsx_rows).to_excel(
                writer, sheet_name="Organic_Results", index=False)
        with open(js, "w", encoding="utf-8") as handle:
            json.dump({"organic_results": json_rows}, handle)
        proc = subprocess.run(
            [sys.executable, "validate_xlsx_vs_json.py", "--xlsx", xlsx,
             "--json", js, "--out", out], cwd=REPO,
            capture_output=True, text=True)
        with open(out, encoding="utf-8") as handle:
            return proc.returncode, json.load(handle)


class TestANonKeyFieldDivergenceIsReported(unittest.TestCase):

    def _assert_caught(self, column, xlsx_value, json_value):
        _code, diff = _run([_organic(**{column: xlsx_value})],
                           [_organic(**{column: json_value})])
        entry = diff["sheet_diffs"].get("Organic_Results", {})
        self.assertIn("field_mismatch_sample", entry, diff)
        self.assertEqual(
            [column], sorted({m["column"]
                              for m in entry["field_mismatch_sample"]}), diff)
        self.assertFalse(diff["matches"])

    def test_a_different_title_is_caught(self):
        self._assert_caught("Title", "A page title", "A DIFFERENT title")

    def test_a_different_snippet_is_caught(self):
        self._assert_caught("Snippet", "A snippet.", "Another snippet.")

    def test_a_different_word_count_is_caught(self):
        self._assert_caught("Word_Count", 1200, 2400)

    def test_a_different_content_type_is_caught(self):
        self._assert_caught("Content_Type", "Article", "Directory")

    def test_a_value_present_on_one_side_only_is_caught(self):
        self._assert_caught("Snippet", "A snippet.", None)

    def test_the_exit_code_fails_the_pipeline_step(self):
        """The gate has to FAIL, not merely record: step 1.2 reads the exit
        code."""
        code, _diff = _run([_organic()], [_organic(Title="Other")])
        self.assertEqual(1, code)


class TestTheExcelRoundTripIsNotAMismatch(unittest.TestCase):
    """The negative controls. A gate that cries on every real run is worse
    than one that never cries: the first thing it costs is the operator's
    trust in step 1.2, and the second is the habit of reading its report."""

    def _assert_agrees(self, row_xlsx, row_json):
        _code, diff = _run([row_xlsx], [row_json])
        self.assertNotIn("Organic_Results", diff["sheet_diffs"], diff)

    def test_identical_rows_agree(self):
        self._assert_agrees(_organic(), _organic())

    def test_an_integer_read_back_as_a_float_agrees(self):
        """A workbook stores every number as a float."""
        self._assert_agrees(_organic(Word_Count=1200),
                            _organic(Word_Count=1200.0))

    def test_a_number_against_its_own_decimal_spelling_agrees(self):
        self._assert_agrees(_organic(Word_Count=1200),
                            _organic(Word_Count="1200"))

    def test_a_trailing_newline_agrees(self):
        self._assert_agrees(_organic(Snippet="A snippet."),
                            _organic(Snippet="A snippet.\n"))

    def test_a_blank_against_an_empty_string_agrees(self):
        self._assert_agrees(_organic(Snippet=None), _organic(Snippet=""))

    def test_a_stated_na_marker_agrees_with_itself(self):
        self._assert_agrees(_organic(Content_Type="N/A"),
                            _organic(Content_Type="N/A"))


class TestWhatIsNotComparedIsStated(unittest.TestCase):

    def test_an_undeclared_column_is_listed_not_silently_skipped(self):
        """A column no spec declares is not checked. Saying so is the point:
        the report named the step a cross-check while checking three columns
        of nine (P2)."""
        _code, diff = _run([_organic(Extra_Column="a")],
                           [_organic(Extra_Column="b")])
        self.assertIn("Extra_Column",
                      diff["columns_not_compared"]["Organic_Results"], diff)
        self.assertNotIn("Organic_Results", diff["sheet_diffs"], diff)

    def test_a_declared_column_is_not_in_the_not_compared_list(self):
        _code, diff = _run([_organic()], [_organic()])
        listed = diff["columns_not_compared"]["Organic_Results"]
        for column in ("Title", "Snippet", "Word_Count", "Content_Type"):
            self.assertNotIn(column, listed, diff)


class TestValuesAgree(unittest.TestCase):
    """The comparison itself, without the subprocess."""

    def test_none_only_matches_none(self):
        self.assertTrue(v.values_agree(None, ""))
        self.assertFalse(v.values_agree(None, 0))
        self.assertFalse(v.values_agree(None, "0"))

    def test_zero_is_not_an_absence(self):
        """P1/P2 in miniature: a measured zero and an unmeasured field are
        two different facts and must not compare equal."""
        self.assertFalse(v.values_agree(0, None))
        self.assertTrue(v.values_agree(0, 0.0))

    def test_a_bool_is_not_its_integer(self):
        self.assertFalse(v.values_agree(True, 1))

    def test_unparseable_text_against_a_number_differs(self):
        self.assertFalse(v.values_agree(1200, "about 1200"))


if __name__ == "__main__":
    unittest.main()
