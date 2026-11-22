"""The §5c "Weakest (non-dir)" cell says what its figures mean.

It rendered "0 (0?)" and "0 (61?)": a bare figure in brackets and a trailing
question mark with nothing naming what was being asked. On
`how my childhood affects my relationships` in the 2026-11-19 run that cell
held the run's strongest evidence in the client's favour — a DA-0
non-directory page holding a top-10 slot, so authority is not the barrier on
that keyword — and no reader could have told.

These tests pin that each of the five states names itself, that the words are
editorial, and that the cell and the prose cannot disagree about which state
a row is in.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import feasibility

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGES_PATH = os.path.join(REPO, "feasibility_messages.yml")

# The five states, as the rows the report hands the cell.
FULL = {"min_competitor_da": 12, "min_non_directory_da": 40,
        "da_count": 10, "entities_known": 10}
PARTIAL = {"min_competitor_da": 0, "min_non_directory_da": 61,
           "da_count": 10, "entities_known": 7}
ALL_DIR = {"min_competitor_da": 70, "da_count": 10, "entities_known": 10}
ALL_DIR_PARTIAL = {"min_competitor_da": 12, "da_count": 10,
                   "entities_known": 1}
UNKNOWN = {"min_competitor_da": 12, "da_count": 10, "entities_known": 0}
NO_DA = {"min_competitor_da": None, "da_count": 0, "entities_known": 0}


class TestNoFigureIsUnlabelled(unittest.TestCase):

    def test_the_non_directory_figure_is_named(self):
        self.assertEqual(feasibility.minima_cell(FULL), "12 · non-dir 40")

    def test_a_partial_window_says_how_many_were_typed(self):
        cell = feasibility.minima_cell(PARTIAL)
        self.assertEqual(cell, "0 · non-dir 61 (7 of 10 typed)")

    def test_no_cell_carries_a_bare_question_mark(self):
        for name, row in (("full", FULL), ("partial", PARTIAL),
                          ("all_dir", ALL_DIR),
                          ("all_dir_partial", ALL_DIR_PARTIAL),
                          ("unknown", UNKNOWN), ("no_da", NO_DA)):
            with self.subTest(state=name):
                cell = feasibility.minima_cell(row)
                self.assertNotIn("?", cell, f"{name} still asks a question")

    def test_a_directory_only_page_says_so_in_words(self):
        self.assertEqual(feasibility.minima_cell(ALL_DIR),
                         "70 · all directories")
        self.assertEqual(feasibility.minima_cell(ALL_DIR_PARTIAL),
                         "12 · all typed are directories (1 of 10 typed)")

    def test_an_unmeasured_split_is_not_an_absence_of_directories(self):
        # "nobody classified these" and "no directory ranks here" are two
        # facts; the old cell printed "(?)" for the first and "(none)" for
        # the second, which no reader could distinguish.
        self.assertEqual(feasibility.minima_cell(UNKNOWN),
                         "12 · non-dir not measured")
        self.assertNotEqual(feasibility.minima_cell(UNKNOWN),
                            feasibility.minima_cell(ALL_DIR))

    def test_no_da_measured_is_still_a_dash(self):
        self.assertEqual(feasibility.minima_cell(NO_DA), "—")


class TestTheCellFitsATable(unittest.TestCase):

    def test_no_cell_contains_a_pipe_or_a_newline(self):
        for row in (FULL, PARTIAL, ALL_DIR, ALL_DIR_PARTIAL, UNKNOWN, NO_DA):
            cell = feasibility.minima_cell(row)
            with self.subTest(cell=cell):
                self.assertNotIn("|", cell)
                self.assertNotIn("\n", cell)

    def test_the_longest_state_stays_short(self):
        longest = max((feasibility.minima_cell(r) for r in
                       (FULL, PARTIAL, ALL_DIR, ALL_DIR_PARTIAL, UNKNOWN)),
                      key=len)
        self.assertLessEqual(len(longest), 48, longest)


class TestTheWordsAreEditorial(unittest.TestCase):

    def setUp(self):
        with open(MESSAGES_PATH, encoding="utf-8") as fh:
            self.messages = yaml.safe_load(fh) or {}

    def test_the_messages_file_carries_every_state(self):
        block = self.messages.get("minima_cell") or {}
        for key in ("no_da", "with_non_directory",
                    "with_non_directory_partial", "all_directory",
                    "all_classified_directory", "entities_unknown"):
            with self.subTest(key=key):
                self.assertTrue(str(block.get(key, "")).strip(), key)

    def test_the_cell_renders_the_configured_words(self):
        # Not the Python fallback: a change in the file must reach the report.
        original = feasibility.load_messages
        try:
            feasibility.load_messages = lambda: {
                "minima_cell": {"with_non_directory": "weakest {min_da}, "
                                                      "non-directory "
                                                      "{min_non_directory_da}"}}
            self.assertEqual(feasibility.minima_cell(FULL),
                             "weakest 12, non-directory 40")
        finally:
            feasibility.load_messages = original

    def test_a_broken_template_degrades_to_the_built_in_wording(self):
        original = feasibility.load_messages
        try:
            feasibility.load_messages = lambda: {
                "minima_cell": {"with_non_directory": "{nope}"}}
            with self.assertLogs(level="WARNING"):
                self.assertEqual(feasibility.minima_cell(FULL),
                                 "12 · non-dir 40")
        finally:
            feasibility.load_messages = original

    def test_no_state_wording_is_left_in_python(self):
        src = open(os.path.join(REPO, "generate_insight_report.py"),
                   encoding="utf-8").read()
        # The report asks feasibility for the cell; it must not assemble one.
        self.assertIn("feasibility.minima_cell(row)", src)
        self.assertNotIn("min_non_directory_da}", src)


class TestTheCellAndThePhraseAgree(unittest.TestCase):
    """Both read the same keys, so they cannot report different states."""

    def test_a_partial_window_is_partial_in_both(self):
        cell = feasibility.minima_cell(PARTIAL)
        phrase = feasibility.minima_phrase(PARTIAL)
        self.assertIn("7 of 10", cell)
        self.assertIn("7 of 10", phrase)

    def test_a_directory_only_page_is_directory_only_in_both(self):
        self.assertIn("directories", feasibility.minima_cell(ALL_DIR))
        self.assertIn("no evidence either way",
                      feasibility.minima_phrase(ALL_DIR))

    def test_an_unmeasured_split_is_unmeasured_in_both(self):
        self.assertIn("not measured", feasibility.minima_cell(UNKNOWN))
        self.assertIn("not measured", feasibility.minima_phrase(UNKNOWN))


if __name__ == "__main__":
    unittest.main()
