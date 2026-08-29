import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from tk_probe import tkinter_usable

# Not "is tkinter importable" — "can a window actually be created here".
TKINTER_AVAILABLE = tkinter_usable()

MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serp-me.py")


def load_serp_me():
    spec = importlib.util.spec_from_file_location("serp_me_mod", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(TKINTER_AVAILABLE, "tkinter not available in this environment")
class TestSerpLauncherResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_serp_me()

    def make_app(self):
        app = object.__new__(self.mod.SerpLauncherApp)
        app.read_keyword_file = self.mod.SerpLauncherApp.read_keyword_file.__get__(app)
        app.load_config = self.mod.SerpLauncherApp.load_config.__get__(app)
        app.find_latest_topic_output = self.mod.SerpLauncherApp.find_latest_topic_output.__get__(app)
        app.find_latest_any_output = self.mod.SerpLauncherApp.find_latest_any_output.__get__(app)
        app.find_matching_topic_slug = self.mod.SerpLauncherApp.find_matching_topic_slug.__get__(app)
        app.resolve_existing_analysis_outputs = self.mod.SerpLauncherApp.resolve_existing_analysis_outputs.__get__(app)
        return app

    def test_derive_topic_slug_from_default_keywords_file(self):
        self.assertEqual(self.mod.derive_topic_slug_from_keyword_file("keywords.csv"), "keywords")
        self.assertEqual(
            self.mod.derive_topic_slug_from_keyword_file("keywords_estrangement.csv"),
            "estrangement",
        )

    def test_derive_topic_slug_normalizes_to_lowercase(self):
        # Mixed-case standalone file
        self.assertEqual(
            self.mod.derive_topic_slug_from_keyword_file("Substance_Use.csv"),
            "substance_use",
        )
        # Mixed-case keywords_ prefixed file
        self.assertEqual(
            self.mod.derive_topic_slug_from_keyword_file("keywords_Substance_Use.csv"),
            "substance_use",
        )

    def test_derive_topic_slug_replaces_spaces_with_underscores(self):
        self.assertEqual(
            self.mod.derive_topic_slug_from_keyword_file("Basic Series Tape 7.csv"),
            "basic_series_tape_7",
        )
        self.assertEqual(
            self.mod.derive_topic_slug_from_keyword_file("keywords_mental health.csv"),
            "mental_health",
        )

    def test_resolve_existing_analysis_outputs_uses_matching_keyword_file_slug(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                Path("keywords.csv").write_text("estrangement\nestrangement grief\n", encoding="utf-8")
                Path("keywords_estrangement.csv").write_text(
                    "estrangement\nestrangement grief\n",
                    encoding="utf-8",
                )
                Path("market_analysis_estrangement_20260311_1733.json").write_text("{}", encoding="utf-8")
                Path("market_analysis_estrangement_20260311_1733.xlsx").write_text("", encoding="utf-8")
                Path("market_analysis_estrangement_20260311_1733.md").write_text("", encoding="utf-8")

                slug, latest_json, latest_xlsx, latest_md = app.resolve_existing_analysis_outputs(
                    os.path.join(tmpdir, "keywords.csv"),
                    "keywords",
                )
                self.assertEqual(slug, "estrangement")
                self.assertTrue(latest_json.endswith("market_analysis_estrangement_20260311_1733.json"))
                self.assertTrue(latest_xlsx.endswith("market_analysis_estrangement_20260311_1733.xlsx"))
                self.assertTrue(latest_md.endswith("market_analysis_estrangement_20260311_1733.md"))
            finally:
                os.chdir(cwd)

    def test_resolve_existing_analysis_outputs_uses_configured_output_for_keywords_csv(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                Path("keywords.csv").write_text("estrangement\n", encoding="utf-8")
                Path("config.yml").write_text(
                    "files:\n"
                    "  output_json: market_analysis_estrangement_20260311_1733.json\n"
                    "  output_xlsx: market_analysis_estrangement_20260311_1733.xlsx\n"
                    "  output_md: market_analysis_estrangement_20260311_1733.md\n",
                    encoding="utf-8",
                )
                Path("market_analysis_estrangement_20260311_1733.json").write_text("{}", encoding="utf-8")
                Path("market_analysis_estrangement_20260311_1733.xlsx").write_text("", encoding="utf-8")
                Path("market_analysis_estrangement_20260311_1733.md").write_text("", encoding="utf-8")

                slug, latest_json, latest_xlsx, latest_md = app.resolve_existing_analysis_outputs(
                    os.path.join(tmpdir, "keywords.csv"),
                    "keywords",
                )
                self.assertEqual(slug, "estrangement")
                self.assertTrue(latest_json.endswith("market_analysis_estrangement_20260311_1733.json"))
                self.assertTrue(latest_xlsx.endswith("market_analysis_estrangement_20260311_1733.xlsx"))
                self.assertTrue(latest_md.endswith("market_analysis_estrangement_20260311_1733.md"))
            finally:
                os.chdir(cwd)


class TestConfigCommentPreservation(unittest.TestCase):
    """Regression: save_config wiped every comment in config.yml.

    The GUI re-dumps the whole document on each run of run_pipeline.py just
    to refresh the four ``files:`` output paths. Under yaml.safe_dump this
    stripped all comments, including the paid-feature / gating docs under
    ``ai_visibility:``, ``gsc:`` and ``geo:``. Round-trip YAML must survive
    a load -> mutate ``files:`` -> save cycle with comments intact.

    No tkinter required: load_config/save_config only touch config_path().
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_serp_me()

    def make_config_app(self):
        app = object.__new__(self.mod.SerpLauncherApp)
        app.config_path = self.mod.SerpLauncherApp.config_path.__get__(app)
        app._yaml = self.mod.SerpLauncherApp._yaml.__get__(app)
        app.load_config = self.mod.SerpLauncherApp.load_config.__get__(app)
        app.save_config = self.mod.SerpLauncherApp.save_config.__get__(app)
        return app

    def test_save_config_preserves_comments_on_files_update(self):
        app = self.make_config_app()
        original = (
            "# top-of-file banner comment\n"
            "files:\n"
            "  input_csv: old.csv\n"
            "  output_json: old.json\n"
            "ai_visibility:\n"
            "  # Paid feature: cost guard requires --yes before any call.\n"
            "  assume_yes: false\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                Path("config.yml").write_text(original, encoding="utf-8")

                # Mimic the run_pipeline.py branch: load, mutate files:, save.
                config = app.load_config()
                files_cfg = config.setdefault("files", {})
                files_cfg["input_csv"] = "new.csv"
                files_cfg["output_json"] = "new.json"
                app.save_config(config)

                written = Path("config.yml").read_text(encoding="utf-8")
            finally:
                os.chdir(cwd)

        # The mutation landed...
        self.assertIn("input_csv: new.csv", written)
        self.assertIn("output_json: new.json", written)
        # ...and every comment survived the round-trip.
        self.assertIn("# top-of-file banner comment", written)
        self.assertIn(
            "# Paid feature: cost guard requires --yes before any call.",
            written,
        )
        # Untouched keys are still present.
        self.assertIn("assume_yes: false", written)


class TestRunButtonSelectionRegression(unittest.TestCase):
    """Regression: the Run button silently did nothing.

    Tkinter Listbox defaults to exportselection=1, so clicking any other
    selection-exporting widget (keyword-file combobox, model combobox,
    new-keywords entry) cleared the script selection WITHOUT firing
    <<ListboxSelect>>. The Run button stayed enabled while run_script()
    saw an empty curselection() and returned silently.

    Source-inspection tests (no tkinter required) per the CLAUDE.md GUI
    testing convention.
    """

    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, encoding="utf-8") as fh:
            cls.source = fh.read()

    def _extract_call(self, anchor):
        start = self.source.index(anchor)
        depth = 0
        for i in range(start + len(anchor) - 1, len(self.source)):
            if self.source[i] == "(":
                depth += 1
            elif self.source[i] == ")":
                depth -= 1
                if depth == 0:
                    return self.source[start:i + 1]
        raise AssertionError(f"Unbalanced call for anchor {anchor!r}")

    def test_script_listbox_disables_exportselection(self):
        call = self._extract_call("self.script_listbox = tk.Listbox(")
        self.assertIn(
            "exportselection=False", call,
            "script_listbox must set exportselection=False or the selection "
            "is silently cleared when another widget takes the X selection",
        )

    def test_run_script_never_fails_silently_on_empty_selection(self):
        start = self.source.index("def run_script(self):")
        end = self.source.index("\n    def ", start)
        body = self.source[start:end]
        guard = body.split("if not selection:", 1)[1].split("return", 1)[0]
        self.assertIn(
            "messagebox.", guard,
            "run_script's empty-selection guard must inform the user, "
            "not return silently",
        )

    def test_startup_preselect_targets_a_real_script_not_a_header(self):
        """Startup default selection must resolve via listbox_to_script_index.

        The script listbox contains non-selectable rows — a blank spacer at
        index 0 and section headers (e.g. "A) Generate & Validate Data") — so
        the first real script is NOT at listbox index 0. A bare
        select_set(0) selects the blank spacer, on_select maps it to no
        script, and the Run button stays disabled at startup: the "Run
        button does nothing" symptom. The default selection must target the
        first real script through the listbox_to_script_index mapping.
        """
        # Never hardcode index 0 as the default script row.
        self.assertNotIn(
            "self.script_listbox.select_set(0)", self.source,
            "startup must not select listbox index 0 — a blank spacer / "
            "section-header row — which leaves Run disabled. Select the "
            "first real script via listbox_to_script_index instead.",
        )
        # Isolate the startup default-selection region (between the log-pane
        # setup and the startup banner) and require it to derive the row
        # from the script-index mapping.
        region_start = self.source.index("refresh_keyword_file_options()")
        region_end = self.source.index("Startup banner", region_start)
        region = self.source[region_start:region_end]
        self.assertIn(
            "listbox_to_script_index", region,
            "startup pre-selection must map through listbox_to_script_index "
            "so it lands on a real script row, not a header/spacer.",
        )
        self.assertIn(
            "select_set", region,
            "startup must actually pre-select a script row so the Run "
            "button is live when the window opens.",
        )


if __name__ == "__main__":
    unittest.main()
