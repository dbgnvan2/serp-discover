"""Every editorial key in config.yml can be edited in the GUI.

`ConfigSettingsTab` rendered a widget per field of each top-level MAPPING.
A top-level value that is not a mapping printed as a static label, and a
field whose loaded value was `None` or an empty mapping got no widget at all,
so `get_edited_data`'s own docstring recorded them as "kept exactly as
loaded". `known_brands` — the competitor-brand gazetteer the Y.7 brand pass
and the Y.8 citation attribution both read, named as editorial in CLAUDE.md —
is a top-level list, so the one editorial list a non-developer is most likely
to want to extend was the one thing the config editor could not touch
(2026-11-19).

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §9 C4
"""
import unittest

import yaml

from config_tab_models import SECTION_VALUE, merge_settings_edits


class TestASectionThatIsOneValue(unittest.TestCase):

    def test_a_top_level_list_is_replaced_by_the_edit(self):
        data, errors = merge_settings_edits(
            {"known_brands": ["alpha"], "serpapi": {"gl": "ca"}},
            {"known_brands": (
                {SECTION_VALUE: ("- alpha\n- beta\n", "yaml")})})
        self.assertEqual([], errors)
        self.assertEqual(["alpha", "beta"], data["known_brands"])
        # And nothing else moved.
        self.assertEqual({"gl": "ca"}, data["serpapi"])

    def test_an_emptied_box_becomes_null_not_an_empty_list(self):
        """Two different states, and the one the operator typed is the one
        that is saved: an empty list says "there are no brands", a null says
        "nothing recorded here" (P1)."""
        data, errors = merge_settings_edits(
            {"known_brands": ["alpha"]},
            {"known_brands": {SECTION_VALUE: ("", "yaml")}})
        self.assertEqual([], errors)
        self.assertIsNone(data["known_brands"])

    def test_broken_yaml_is_reported_and_the_loaded_value_kept(self):
        data, errors = merge_settings_edits(
            {"known_brands": ["alpha"]},
            {"known_brands": {SECTION_VALUE: ("- [unclosed\n", "yaml")}})
        self.assertTrue(errors)
        self.assertIn("known_brands", errors[0])
        self.assertEqual(["alpha"], data["known_brands"])

    def test_a_field_edit_on_a_non_mapping_section_is_reported_not_raised(self):
        """Defensive: this shape means the renderer registered a field widget
        for a section that holds one value. A TypeError inside Save would lose
        every other tab's edits with it."""
        data, errors = merge_settings_edits(
            {"known_brands": ["alpha"]},
            {"known_brands": {"gl": ("ca", "str")}})
        self.assertTrue(errors)
        self.assertEqual(["alpha"], data["known_brands"])


class TestAFieldWithNothingInItYet(unittest.TestCase):

    def test_a_null_field_can_be_filled_in(self):
        """`thresholds_provenance` families are deliberately blank until
        somebody records a source; the report prints "editorial,
        uncalibrated" for them, and until now the only way to answer that was
        to hand-edit the file."""
        data, errors = merge_settings_edits(
            {"thresholds_provenance": {"feasibility": None}},
            {"thresholds_provenance": {
                "feasibility": ("Moz 2026 study, 2026-11-19", "yaml")}})
        self.assertEqual([], errors)
        self.assertEqual("Moz 2026 study, 2026-11-19",
                         data["thresholds_provenance"]["feasibility"])

    def test_an_empty_mapping_field_can_be_filled_in(self):
        data, errors = merge_settings_edits(
            {"aivi": {"weights": {}}},
            {"aivi": {"weights": ("citation: 0.5\nsentiment: 0.5\n", "yaml")}})
        self.assertEqual([], errors)
        self.assertEqual({"citation": 0.5, "sentiment": 0.5},
                         data["aivi"]["weights"])

    def test_a_yaml_field_left_empty_is_null_not_an_empty_mapping(self):
        data, errors = merge_settings_edits(
            {"aivi": {"weights": {"citation": 1.0}}},
            {"aivi": {"weights": ("", "yaml")}})
        self.assertEqual([], errors)
        self.assertIsNone(data["aivi"]["weights"])


class TestTheRendererRegistersThem(unittest.TestCase):
    """Source-level, so it holds without tkinter (the pattern
    `tests/test_config_manager.py::TestTabInitializationOrder` uses)."""

    def _source(self):
        with open("config_manager.py", encoding="utf-8") as handle:
            return handle.read()

    def test_a_non_mapping_section_is_no_longer_a_read_only_label(self):
        self.assertNotIn('text=f"Value: {section_data}"', self._source())

    def test_the_section_renderer_calls_the_yaml_editor(self):
        source = self._source()
        self.assertIn("_render_yaml_value(section_frame, section_name, SECTION_VALUE",
                      source)

    def test_the_real_config_known_brands_is_a_top_level_list(self):
        """The anchor for all of the above: if `known_brands` ever became a
        mapping this file's premise would be wrong, and the test should say
        so rather than passing vacuously."""
        with open("config.yml", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        self.assertIn("known_brands", config)
        self.assertIsInstance(config["known_brands"], list)


if __name__ == "__main__":
    unittest.main()
