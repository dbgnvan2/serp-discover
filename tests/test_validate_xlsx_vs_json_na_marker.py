"""A written-out "N/A" is a value, not a blank cell.

Found by the first live run after the 2026-11-04 review (2026-11-18). The
pipeline hard-failed at step 1.2 — `validate_xlsx_vs_json.py` reported one
organic result as missing from BOTH files at once:

    "missing_in_xlsx_sample": ["('20261118_153321', 9, 'N/A')"]
    "missing_in_json_sample": ["('20261118_153321', 9, nan)"]

`Link` is part of that sheet's key, a SERP result with no link carries the
string `"N/A"` (this tool states an absence rather than leaving it blank), and
pandas' DEFAULT missing-value list contains `"N/A"`. So the workbook read back
a `NaN` where the JSON held `"N/A"`, and the two key tuples could not match.

No mocked test could have found it: the collision is between a real workbook
and pandas' own defaults, and every fixture in the suite builds its frames in
memory. That is the point of this file — it round-trips through a real .xlsx.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md (live-run finding)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#: One keyed row per sheet the validator knows about, so the comparison runs
#: over a workbook shaped like a real one rather than over a single sheet.
RUN_ID = "20261118_153321"


def _organic(link):
    return {"Run_ID": RUN_ID, "Rank": 9, "Link": link,
            "Title": "A result whose link the provider did not give",
            "Snippet": "", "Source": "LinkedIn", "Content_Type": "Not Measured",
            "Entity_Type": "Not Measured", "Word_Count": None,
            "Rank_Delta": None}


class TestAStatedNAIsNotAMissingCell(unittest.TestCase):

    def _run(self, organic_rows):
        """Write a workbook and a JSON from the same rows, then validate.

        Returns `(exit_code, diff)`. The two files are written from one list,
        so ANY difference the validator reports is an artefact of the round
        trip rather than a real disagreement between the two writers.
        """
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = os.path.join(tmp, "m.xlsx")
            js = os.path.join(tmp, "m.json")
            out = os.path.join(tmp, "diff.json")
            with pd.ExcelWriter(xlsx) as writer:
                pd.DataFrame(organic_rows).to_excel(
                    writer, sheet_name="Organic_Results", index=False)
            with open(js, "w", encoding="utf-8") as handle:
                json.dump({"organic_results": organic_rows}, handle)
            proc = subprocess.run(
                [sys.executable, "validate_xlsx_vs_json.py",
                 "--xlsx", xlsx, "--json", js, "--out", out],
                cwd=REPO, capture_output=True, text=True)
            with open(out, encoding="utf-8") as handle:
                return proc.returncode, json.load(handle)

    def _assert_organic_agrees(self, diff):
        """The fixture writes ONE sheet, so the validator rightly reports the
        others as missing and the overall verdict is False. The claim under
        test is about this sheet, so it is this sheet's entry that is
        asserted — not the exit code, which would pass for the wrong
        reason."""
        self.assertNotIn("Organic_Results", diff["sheet_diffs"], diff)

    def test_a_link_written_as_na_round_trips(self):
        _code, diff = self._run([_organic("N/A")])
        self._assert_organic_agrees(diff)

    def test_the_other_default_na_strings_round_trip_too(self):
        """`N/A` is one of about twenty strings pandas treats as missing by
        default. Any of them could reach a key column — `NA` and `None` are
        plausible provider values, and `-` and `null` are plausible markers —
        so the fix is asserted over the list, not over the one string the live
        run happened to produce."""
        for marker in ("N/A", "NA", "n/a", "None", "null", "NULL", "-",
                       "NaN", "nan"):
            with self.subTest(marker=marker):
                _code, diff = self._run([_organic(marker)])
                self._assert_organic_agrees(diff)

    def test_the_one_marker_that_cannot_round_trip_is_recorded(self):
        """`#N/A` is Excel's own error literal, and pandas maps it to `NaN` at
        the Excel layer whatever `na_values` says — `openpyxl` reads the same
        cell back as the string `"#N/A"`, so the loss is in pandas, not in the
        file. It is recorded here rather than left as a comment because it is
        a real residual limitation: nothing in this tool writes `#N/A` today
        (the marker is `N/A`), but a provider value of `#N/A` in a key column
        would reproduce the original false positive, and the fix would be to
        read that sheet through openpyxl rather than to widen `na_values`."""
        _code, diff = self._run([_organic("#N/A")])
        self.assertIn("Organic_Results", diff["sheet_diffs"],
                      "pandas now round-trips Excel's #N/A error literal; "
                      "this limitation can be dropped and #N/A folded back "
                      "into the list above")

    def test_a_key_written_as_an_empty_string_round_trips(self):
        """The other half of the same defect, found by this fix's cold review.

        The first version of the fix normalised `""` to `None` on the
        WORKBOOK side only, so a key cell that is `""` in the JSON and blank
        in the sheet reproduced the identical both-sides-missing signature.
        `Rich_Features.Details` is a key column written as
        `primary_results[key].get("title")`, which is `""` for a Knowledge
        Panel with no title, so this was reachable on a real run. The collapse
        now happens in `index_records`, where both record sets pass through.
        """
        _code, diff = self._run([_organic("")])
        self._assert_organic_agrees(diff)

    def test_a_key_of_only_whitespace_round_trips(self):
        """A cell of spaces strips to the empty string, which is the same
        absence; `norm_text` already stripped it and then returned `""`."""
        _code, diff = self._run([_organic("   ")])
        self._assert_organic_agrees(diff)

    def test_an_empty_cell_still_reads_as_absent(self):
        """The fix must not turn a blank into the empty string: the JSON side
        writes `null` for the same absence, and a key of `""` would not match
        one of `None`."""
        _code, diff = self._run([_organic(None)])
        self._assert_organic_agrees(diff)

    def test_a_real_mismatch_still_fails(self):
        """The negative control. A validator that passes everything is worse
        than the bug it replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = os.path.join(tmp, "m.xlsx")
            js = os.path.join(tmp, "m.json")
            out = os.path.join(tmp, "diff.json")
            with pd.ExcelWriter(xlsx) as writer:
                pd.DataFrame([_organic("https://example.com/a")]).to_excel(
                    writer, sheet_name="Organic_Results", index=False)
            with open(js, "w", encoding="utf-8") as handle:
                json.dump({"organic_results":
                           [_organic("https://example.com/DIFFERENT")]}, handle)
            proc = subprocess.run(
                [sys.executable, "validate_xlsx_vs_json.py",
                 "--xlsx", xlsx, "--json", js, "--out", out],
                cwd=REPO, capture_output=True, text=True)
            self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
            with open(out, encoding="utf-8") as handle:
                diff = json.load(handle)
            self.assertFalse(diff["matches"])
            self.assertIn("Organic_Results", diff["sheet_diffs"])
            self.assertIn("missing_in_xlsx_sample",
                          diff["sheet_diffs"]["Organic_Results"])


if __name__ == "__main__":
    unittest.main()
