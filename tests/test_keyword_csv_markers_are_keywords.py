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

    def test_a_header_row_is_not_searched(self):
        """`keywords_family-of-origin-seo-phrases.csv` is a three-column file
        headed `keyword,intent,why_it_matters` while the repo's other six
        keyword files have no header. Read with `header=None`, which is right
        for the six, the word "keyword" became the run's first search term: a
        paid call, a row in every output sheet, and a keyword in the market
        report that no human typed."""
        self.assertEqual(
            ["family of origin therapy", "sibling estrangement therapy"],
            self._keywords("keyword,intent,why\n"
                           "family of origin therapy,topical,core\n"
                           "sibling estrangement therapy,transactional,gap\n"))

    def test_the_skipped_header_is_announced(self):
        """Dropping a row quietly is the defect's mirror image (P2)."""
        with self.assertLogs(level=logging.WARNING) as logs:
            self._keywords("Keywords\nfamily of origin therapy\n")
        self.assertTrue(any("header row" in line for line in logs.output),
                        logs.output)

    def test_only_the_first_row_is_tested_for_a_header(self):
        """A keyword that happens to equal a header token further down the
        file is a keyword. "Family roles" and "family dynamics" are in the
        real file; a client could legitimately target "terms"."""
        self.assertEqual(
            ["family dynamics", "terms"],
            self._keywords("family dynamics\nterms\n"))

    def test_the_token_list_is_configurable(self):
        """Editorial: whoever maintains the keyword files decides what a
        header column is called. `config.yml`
        `files.keyword_csv_header_tokens` overrides the default list, and
        `serp_audit.load_keywords` passes it through."""
        self.assertEqual(
            ["real keyword"],
            self._keywords_with_tokens("spreadsheet\nreal keyword\n",
                                       ("spreadsheet",)))
        # And a token that is no longer in the list is an ordinary keyword.
        self.assertEqual(
            ["keyword", "real keyword"],
            self._keywords_with_tokens("keyword\nreal keyword\n",
                                       ("spreadsheet",)))

    def _keywords_with_tokens(self, lines, tokens):
        import keyword_input
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "k.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(lines)
            return keyword_input.load_keywords(path, "", tokens)

    def test_ordinary_keywords_are_unchanged(self):
        self.assertEqual(["couples counselling", "bowen theory"],
                         self._keywords("couples counselling\nbowen theory\n"))


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
