"""Tests for play_rendering.py — the shared Recommended Play renderers.

Spec: seo_geo_review_20260704.md (T.4). These cover the post-review hardening:
pipe/newline sanitization for table cells, falsy data_available honesty, and
cache isolation.
"""
import unittest

import play_rendering as pr


class TestFormatPlayCell(unittest.TestCase):

    def test_no_verdict_renders_dash(self):
        self.assertEqual(pr.format_play_cell(None), "—")
        self.assertEqual(pr.format_play_cell({}), "—")

    def test_pipe_in_strategy_is_escaped_for_table_integrity(self):
        """A strategy containing '|' must not add a spurious table column."""
        cell = pr.format_play_cell({
            "play": "rank_play", "label": "Rank Play",
            "strategy_text": "Target rank | then extract", "data_available": True,
        })
        # Every pipe is escaped (no raw '|' that would add a spurious column).
        self.assertIn(r"\|", cell)
        self.assertEqual(cell.count("|"), cell.count(r"\|"))

    def test_newline_in_strategy_collapsed(self):
        cell = pr.format_play_cell({
            "play": "rank_play", "label": "Rank Play",
            "strategy_text": "line one\nline two", "data_available": True,
        })
        self.assertNotIn("\n", cell)

    def test_data_available_false_is_honest(self):
        cell = pr.format_play_cell({
            "play": "extraction_play", "label": "Extraction Play",
            "strategy_text": "should not appear", "data_available": False,
        })
        self.assertIn("inputs missing", cell.lower())
        self.assertNotIn("should not appear", cell)

    def test_data_available_falsy_zero_is_honest(self):
        """Renderer and validator both treat a present-but-falsy value as
        'not available' — they must not disagree for the same record."""
        cell = pr.format_play_cell({
            "play": "extraction_play", "label": "Extraction Play",
            "strategy_text": "should not appear", "data_available": 0,
        })
        self.assertIn("inputs missing", cell.lower())
        self.assertNotIn("should not appear", cell)

    def test_missing_data_available_key_defaults_to_available(self):
        cell = pr.format_play_cell({
            "play": "rank_play", "label": "Rank Play",
            "strategy_text": "do the thing",
        })
        self.assertIn("do the thing", cell)
        self.assertNotIn("inputs missing", cell.lower())


class TestFormatPlayLine(unittest.TestCase):

    def test_none_when_no_verdict(self):
        self.assertIsNone(pr.format_play_line(None))
        self.assertIsNone(pr.format_play_line({}))

    def test_success_metric_from_config(self):
        line = pr.format_play_line({
            "play": "extraction_play", "label": "Extraction Play",
            "strategy_text": "reformat", "data_available": True,
        })
        self.assertIn("AI Overview (AIO) citation gain", line)

    def test_newline_collapsed_stays_one_bullet(self):
        line = pr.format_play_line({
            "play": "rank_play", "label": "Rank Play",
            "strategy_text": "a\nb", "data_available": True,
        })
        self.assertNotIn("\n", line)


class TestVocabCacheIsolation(unittest.TestCase):

    def test_returned_vocab_is_a_copy(self):
        """Mutating the returned vocab must not poison later callers."""
        v1 = pr.load_play_vocab()
        v1.setdefault("play_labels", {})["__poison__"] = "BAD"
        v2 = pr.load_play_vocab()
        self.assertNotIn("__poison__", v2.get("play_labels", {}))


if __name__ == "__main__":
    unittest.main()
