"""Chunk Y15 — every editorial file has an editor.

`CLAUDE.md` says editorial content belongs in a YAML or JSON file rather than
in Python, and the review chunks moved a great deal of it out. The
Configuration Manager is how a non-developer reaches those files, and it was
never extended: nine tabs against nineteen editable editorial files. The rule
was followed and the consequence it exists for was not delivered for ten of
them.

The completeness guard here is the part that stops that recurring. The ten
tabs only clear the backlog; a file added tomorrow with no editor fails the
build.

Business logic without tkinter, per `CLAUDE.md`: the declaration table, the
completeness check, the parse and the write are all testable with no widgets.

Spec: docs/review_2026-11-04/PLAN_Y15_every_editorial_file_has_an_editor.md
"""

import ast
import io
import os
import tempfile
import unittest

import config_tab_models as models


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The nine files that have a bespoke form rather than a source tab. Read off
#: the module below, never retyped — a second list is how the first one goes
#: stale, which is the fault this chunk fixes.
def _tabs_registered() -> list:
    """Every `file_name` the window's tab list ends up editing.

    Read from the source with an AST rather than by constructing the window,
    so the guard runs with no tkinter and no config files on disk.
    """
    source = io.open(os.path.join(REPO, "config_manager.py"),
                     encoding="utf-8").read()
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        # `super().__init__(parent, "intent_mapping.yml", "yaml")` in a tab's
        # own __init__ is how a bespoke form declares its file.
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "__init__"):
            continue
        for arg in node.args:
            if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and arg.value.endswith((".yml", ".yaml", ".json"))):
                names.append(arg.value)
    # P29 — the walk asserts it found the thing it is about.
    assert len(names) >= 8, f"found almost no tab file names: {names}"
    return names


class TestEveryEditorialFileIsReachable(unittest.TestCase):

    def test_no_editorial_file_is_left_without_an_editor(self):
        """The standing guard. A new editorial YAML or JSON file must either
        get a tab or be named in `NOT_EDITORIAL` with its reason."""
        covered = set(_tabs_registered())
        covered.update(name for name, _t, _ti, _c in models.EDITORIAL_SOURCE_FILES)
        # The client-profile form is declared by a module constant rather than
        # a literal in its own __init__.
        import config_manager
        covered.add(config_manager.CLIENT_PROFILES_FILE)

        missing = models.files_without_an_editor(REPO, covered)
        self.assertEqual(
            missing, [],
            "these editorial files have no editor and no recorded reason to "
            f"have none: {missing}. Add a row to "
            "config_tab_models.EDITORIAL_SOURCE_FILES, or name the file in "
            "NOT_EDITORIAL with why it is not editable.")

    def test_every_declared_source_file_exists(self):
        """A row naming a file that is not there would show an empty tab and
        write a new file beside the repo on save."""
        for file_name, _type, _title, _check in models.EDITORIAL_SOURCE_FILES:
            with self.subTest(file_name):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO, file_name)),
                    f"{file_name} is declared editable but does not exist")

    def test_every_declared_source_file_has_help_text(self):
        """A source tab shows raw YAML, so the help text is the only thing
        saying what the file decides."""
        import config_manager
        for file_name, _type, title, _check in models.EDITORIAL_SOURCE_FILES:
            with self.subTest(file_name):
                help_text = config_manager.HELP_BY_FILE.get(file_name, "")
                self.assertGreater(
                    len(help_text), 120,
                    f"{file_name} ({title}) has no usable help text")

    def test_no_file_is_both_excluded_and_declared_editable(self):
        declared = {name for name, _t, _ti, _c in models.EDITORIAL_SOURCE_FILES}
        self.assertEqual(declared & set(models.NOT_EDITORIAL), set())

    def test_every_exclusion_records_a_reason(self):
        """An exclusion with no reason is indistinguishable from an
        oversight."""
        for name, reason in models.NOT_EDITORIAL.items():
            with self.subTest(name):
                self.assertGreater(len(reason), 20, name)

    def test_no_file_is_declared_twice(self):
        declared = [name for name, _t, _ti, _c in models.EDITORIAL_SOURCE_FILES]
        self.assertEqual(len(declared), len(set(declared)))

    def test_the_check_reports_a_file_that_has_no_editor(self):
        """The completeness check has to be able to say "missing". A check
        that always answers "nothing" passes the guard above while covering
        nothing, which is how the fault reached the repo in the first place."""
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        for name in ("covered.yml", "orphan.yml", "excluded.json",
                     "notes.txt"):
            io.open(os.path.join(directory, name), "w").write("a: 1\n")
        models.NOT_EDITORIAL["excluded.json"] = (
            "a test fixture, named here so the check has an exclusion to "
            "honour")
        self.addCleanup(models.NOT_EDITORIAL.pop, "excluded.json")

        missing = models.files_without_an_editor(directory, ["covered.yml"])
        self.assertEqual(missing, ["orphan.yml"])

    def test_a_directory_named_like_a_config_file_is_not_a_file(self):
        """`output/` holds generated artefacts; a directory whose name ends in
        .json would otherwise be reported as an editorial file with no
        editor, and the guard would fail for something nobody can edit."""
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        os.mkdir(os.path.join(directory, "looks_like.json"))
        io.open(os.path.join(directory, "real.yml"), "w").write("a: 1\n")
        self.assertEqual(models.editorial_files(directory), ["real.yml"])

    def test_an_untracked_file_at_the_root_is_not_in_the_inventory(self):
        """A run's own output and a reader's scratch files sit at this root.
        Listing the directory meant `touch zz_scratch.yml` failed the standing
        guard, and the gitignored `diff_report.json` was reported as an
        editorial file nobody had wired up (the cold review of chunk Y15,
        finding 4)."""
        import subprocess
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        for name in ("tracked.yml", "scratch.yml"):
            io.open(os.path.join(directory, name), "w").write("a: 1\n")
        subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
        subprocess.run(["git", "add", "tracked.yml"], cwd=directory,
                       check=True)

        self.assertEqual(models.editorial_files(directory), ["tracked.yml"])

    def test_the_inventory_finds_the_repos_editorial_files(self):
        """P29 — the listing asserts it found what it is about."""
        found = models.editorial_files(REPO)
        self.assertIn("config.yml", found)
        self.assertIn("glossary.yml", found)
        self.assertGreater(len(found), 15)


class TestEditedSourceIsParsedBeforeItIsWritten(unittest.TestCase):
    """What a source tab adds over a text editor: a syntax error is caught
    with its line instead of breaking the next run."""

    def test_valid_yaml_parses(self):
        data, error = models.parse_source("a: 1\nb:\n  - x\n", "yaml")
        self.assertIsNone(error)
        self.assertEqual(data, {"a": 1, "b": ["x"]})

    def test_broken_yaml_reports_the_failure_rather_than_raising(self):
        data, error = models.parse_source("a: [1, 2\n", "yaml")
        self.assertIsNone(data)
        self.assertIn("Error", error)

    def test_broken_json_reports_the_failure(self):
        data, error = models.parse_source('{"a": 1,}', "json")
        self.assertIsNone(data)
        self.assertIsNotNone(error)

    def test_an_empty_file_is_an_empty_mapping_not_a_failure(self):
        self.assertEqual(models.parse_source("", "yaml"), ({}, None))
        self.assertEqual(models.parse_source("# only a comment\n", "yaml"),
                         ({}, None))

    def test_a_scalar_is_refused(self):
        """A file that reduces to a bare string or number would be saved and
        then read by a loader expecting a mapping."""
        data, error = models.parse_source("just a sentence\n", "yaml")
        self.assertIsNone(data)
        self.assertIn("mapping or a list", error)

    def test_a_top_level_list_is_allowed(self):
        data, error = models.parse_source("- a\n- b\n", "yaml")
        self.assertIsNone(error)
        self.assertEqual(data, ["a", "b"])


class TestValidSyntaxIsNotAValidRuleTable(unittest.TestCase):
    """What the structural check adds over the parse. Valid YAML that is not a
    usable rule table saved cleanly and the next run died inside
    `brief_data_extraction`, or ran with every numeric check silently off (the
    cold review of chunk Y15, finding 3)."""

    def test_a_play_table_with_no_rules_is_reported(self):
        problems = models.structural_errors_for_text(
            "play_routing.yml", "plays: {}\nrules: []\n")
        self.assertTrue(problems)
        self.assertIn("play_routing.yml", problems[0])

    def test_the_real_play_table_is_accepted(self):
        text = io.open(os.path.join(REPO, "play_routing.yml"),
                       encoding="utf-8").read()
        self.assertEqual(
            models.structural_errors_for_text("play_routing.yml", text), [])

    def test_a_validation_file_declaring_no_checks_is_reported(self):
        """A loader that degrades rather than raising has to be asked what it
        dropped. Deleting `numeric_claims:` left every numeric check off and
        the result reported no skipped fields."""
        import yaml
        text = io.open(os.path.join(REPO, "brief_validation_rules.yml"),
                       encoding="utf-8").read()
        data = yaml.safe_load(text)
        data.pop("numeric_claims")
        problems = models.structural_errors_for_text(
            "brief_validation_rules.yml", yaml.safe_dump(data))
        self.assertTrue(problems)
        self.assertIn("numeric_claims", problems[0])

    def test_a_single_unusable_rule_is_reported(self):
        import yaml
        text = io.open(os.path.join(REPO, "brief_validation_rules.yml"),
                       encoding="utf-8").read()
        data = yaml.safe_load(text)
        data["numeric_claims"]["client_rank"] = "not a mapping"
        problems = models.structural_errors_for_text(
            "brief_validation_rules.yml", yaml.safe_dump(data))
        self.assertTrue(any("client_rank" in p for p in problems), problems)

    def test_a_file_with_no_declared_check_is_not_blocked(self):
        self.assertEqual(
            models.structural_errors_for_text("glossary.yml", "a: 1\n"), [])


class TestTheUsersOwnTextIsWhatIsSaved(unittest.TestCase):
    """A source tab shows the file's comments, so a comment the user adds has
    to survive the save. `save_yaml_preserving_comments` merges a structure
    into the comments already on disk, which would discard a new one."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        self.path = os.path.join(directory, "x.yml")

    def test_a_comment_the_user_added_survives(self):
        text = "# why this threshold is 30\nthreshold: 30\n"
        models.write_source(self.path, text)
        self.assertEqual(io.open(self.path, encoding="utf-8").read(), text)

    def test_the_text_is_written_byte_for_byte(self):
        """Including blank lines and the order of keys, which a re-dump would
        normalise."""
        text = "b: 2\n\n# a note\na: 1\n"
        models.write_source(self.path, text)
        self.assertEqual(io.open(self.path, encoding="utf-8").read(), text)

    def test_a_missing_final_newline_is_added(self):
        models.write_source(self.path, "a: 1")
        self.assertEqual(io.open(self.path, encoding="utf-8").read(), "a: 1\n")

    def test_the_write_leaves_no_temporary_file_behind(self):
        models.write_source(self.path, "a: 1\n")
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["x.yml"])

    def test_a_failed_write_leaves_nothing_beside_the_file(self):
        """A fixed `<file>.tmp` left partial content beside the file when the
        write failed, with nothing to clean it up or mention it (the cold
        review of chunk Y15, finding 7)."""
        io.open(self.path, "w", encoding="utf-8").write("good: 1\n")
        original = os.replace

        def boom(_src, _dst):
            raise OSError("disk full")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                models.write_source(self.path, "new: 2\n")
        finally:
            os.replace = original
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["x.yml"])
        self.assertEqual(io.open(self.path, encoding="utf-8").read(),
                         "good: 1\n")

    def test_two_writes_of_one_file_do_not_share_a_temporary_name(self):
        """Two tabs saving the same file, or a save while another is in
        flight, collided on `<file>.tmp` and one overwrote the other's
        half-written content."""
        seen = []
        original = os.replace

        def record(src, dst):
            seen.append(src)
            return original(src, dst)

        os.replace = record
        try:
            models.write_source(self.path, "a: 1\n")
            models.write_source(self.path, "a: 2\n")
        finally:
            os.replace = original
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1], seen)

    def test_the_previous_contents_are_replaced_whole(self):
        models.write_source(self.path, "a: 1\nb: 2\nc: 3\n")
        models.write_source(self.path, "a: 1\n")
        self.assertEqual(io.open(self.path, encoding="utf-8").read(), "a: 1\n")


class TestTheTabInitialisesItsStateBeforeRendering(unittest.TestCase):
    """Source-code inspection, per `CLAUDE.md`: a tab that sets instance
    attributes AFTER `super().__init__()` passes in the venv and fails at
    runtime, because the base class calls `render_ui` from its own
    `__init__`."""

    def test_the_source_tab_sets_its_attributes_before_super(self):
        source = io.open(os.path.join(REPO, "config_manager.py"),
                         encoding="utf-8").read()
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef)
                    and node.name == "EditorialSourceTab"):
                continue
            for item in node.body:
                if not (isinstance(item, ast.FunctionDef)
                        and item.name == "__init__"):
                    continue
                found = True
                statements = item.body
                super_index = next(
                    i for i, stmt in enumerate(statements)
                    if any(isinstance(sub, ast.Call)
                           and getattr(sub.func, "id", None) == "super"
                           for sub in ast.walk(stmt)))
                assigned = {
                    target.attr
                    for stmt in statements[:super_index]
                    if isinstance(stmt, ast.Assign)
                    for target in stmt.targets
                    if isinstance(target, ast.Attribute)
                }
                # Every attribute `render_ui` and the save path read.
                for name in ("title", "source_widget", "source_text",
                             "_parse_error"):
                    self.assertIn(
                        name, assigned,
                        f"self.{name} is set after super().__init__(), which "
                        f"calls render_ui()")
        self.assertTrue(found, "EditorialSourceTab.__init__ not found")


if __name__ == "__main__":
    unittest.main()
