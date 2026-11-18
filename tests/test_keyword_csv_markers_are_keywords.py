"""A keyword CSV cell is read as text, not as pandas' idea of missing.

The sibling of the 2026-11-18 validator fix, swept in the same change (P5:
when you harden one call, harden the class). `serp_audit.load_keywords` read
the input CSV with pandas' defaults, whose missing-value list contains "NA",
"None", "null", "-", "nan" and "N/A". A keyword cell holding any of those came
back as `float('nan')` and was handed on as a search query — a run spending
real SerpAPI calls on the string "nan".

Low likelihood for this client's keywords, which is why it is a guard rather
than an incident: the point is that the file is read as text.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md (live-run finding)
"""
import logging
import unittest.mock
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import serp_audit  # noqa: E402


class TestAKeywordCellIsText(unittest.TestCase):

    def _keywords(self, lines):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "k.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(lines)
            with unittest.mock.patch.object(
                    serp_audit, "SINGLE_KEYWORD_OVERRIDE", ""):
                return serp_audit.load_keywords(path)

    def test_the_default_missing_markers_survive_as_keywords(self):
        for marker in ("NA", "None", "null", "-", "nan", "N/A"):
            with self.subTest(marker=marker):
                self.assertEqual([marker, "family of origin therapy"],
                                 self._keywords(
                                     f"{marker}\nfamily of origin therapy\n"))

    def test_no_keyword_is_a_float(self):
        """The failure mode, asserted directly: a nan reaching the search
        query is not a wrong keyword, it is a paid call for nothing."""
        for keyword in self._keywords("NA\nnull\n-\n"):
            self.assertIsInstance(keyword, str)

    def test_a_blank_line_is_dropped_and_counted(self):
        """Dropped, not searched — and said out loud, because a silently
        shorter keyword list is a run that quietly did less than asked
        (P2)."""
        with self.assertLogs(level=logging.WARNING) as logs:
            keywords = self._keywords("one\n\n   \ntwo\n")
        self.assertEqual(["one", "two"], keywords)
        self.assertTrue(any("blank" in line for line in logs.output),
                        logs.output)

    def test_ordinary_keywords_are_unchanged(self):
        self.assertEqual(["couples counselling", "bowen theory"],
                         self._keywords("couples counselling\nbowen theory\n"))


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
