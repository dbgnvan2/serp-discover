"""A comment that follows a list is a comment, and must survive a save.

`yaml_io` exists so that a load -> modify -> save cycle keeps the documentation
in the YAML configs. It did not: `_merge_into_commented` assigned `src`'s plain
list over the loaded `CommentedSeq`, and ruamel attaches a comment that FOLLOWS
a list's last item to the sequence object, so that comment went with it. In
`config.yml` such a comment is the block above the NEXT key, which is how the
`ai_visibility.timeout_seconds` rationale and the `negative_terms` explanation
were deleted on ordinary runs while every test said comments survive — the
existing guards used a comment above a scalar.

Found 2026-11-18 by reading an unrelated `config.yml` diff.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md (live-run finding)
"""
import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import yaml_io  # noqa: E402


class TestACommentAfterAListSurvives(unittest.TestCase):

    def _round_trip(self, text, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.yml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            data = yaml.safe_load(open(path, encoding="utf-8"))
            mutate(data)
            yaml_io.save_yaml_preserving_comments(path, data)
            with open(path, encoding="utf-8") as handle:
                out = handle.read()
            return out, yaml.safe_load(out)

    SAMPLE = (
        "section:\n"
        "  listed:\n"
        "  - a\n"
        "  - b\n"
        "  # WHY THIS SETTING EXISTS\n"
        "  scalar: 1\n"
        "other:\n"
        "  # above a scalar\n"
        "  x: 2\n"
    )

    def test_the_comment_after_a_list_is_kept(self):
        out, _ = self._round_trip(
            self.SAMPLE, lambda d: d["section"].__setitem__("scalar", 9))
        self.assertIn("# WHY THIS SETTING EXISTS", out)
        self.assertIn("# above a scalar", out)

    def test_the_data_is_still_exactly_what_was_written(self):
        """Preserving comments may not preserve stale values — the merge has
        to leave the DATA equal to `yaml.safe_dump(src)` (P6)."""
        out, parsed = self._round_trip(
            self.SAMPLE, lambda d: d["section"].__setitem__("scalar", 9))
        self.assertEqual(9, parsed["section"]["scalar"])
        self.assertEqual(["a", "b"], parsed["section"]["listed"])

    def test_a_longer_list_keeps_the_comment_and_the_new_items(self):
        out, parsed = self._round_trip(
            self.SAMPLE, lambda d: d["section"].__setitem__(
                "listed", ["a", "b", "c"]))
        self.assertIn("# WHY THIS SETTING EXISTS", out)
        self.assertEqual(["a", "b", "c"], parsed["section"]["listed"])

    def test_a_shorter_list_keeps_the_comment_and_drops_the_items(self):
        """The merge pops items in place; nothing of the old list may be left
        behind, which an in-place merge gets wrong if it only overwrites."""
        out, parsed = self._round_trip(
            self.SAMPLE, lambda d: d["section"].__setitem__("listed", ["a"]))
        self.assertIn("# WHY THIS SETTING EXISTS", out)
        self.assertEqual(["a"], parsed["section"]["listed"])

    def test_an_emptied_list_is_emptied(self):
        _out, parsed = self._round_trip(
            self.SAMPLE, lambda d: d["section"].__setitem__("listed", []))
        self.assertEqual([], parsed["section"]["listed"])

    def test_a_list_of_mappings_merges_item_by_item(self):
        text = ("rules:\n"
                "- name: one\n"
                "  weight: 1\n"
                "- name: two\n"
                "  weight: 2\n"
                "# AFTER THE RULES\n"
                "trailing: yes\n")
        out, parsed = self._round_trip(
            text, lambda d: d["rules"][1].__setitem__("weight", 7))
        self.assertIn("# AFTER THE RULES", out)
        self.assertEqual(7, parsed["rules"][1]["weight"])
        self.assertEqual("one", parsed["rules"][0]["name"])

    def test_a_string_value_is_not_treated_as_a_sequence(self):
        """`isinstance("ab", list)` is False, but a careless `len`-based merge
        would still iterate it into characters."""
        text = "a:\n- x\nb: hello\n"
        _out, parsed = self._round_trip(
            text, lambda d: d.__setitem__("b", "goodbye"))
        self.assertEqual("goodbye", parsed["b"])


if __name__ == "__main__":
    unittest.main()
