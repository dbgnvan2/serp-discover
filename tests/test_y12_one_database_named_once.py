"""Review chunk Y12 — one database, named once.

The fault: `"serp_data.db"` was a literal at 24 sites in 17 modules, with no
`config.yml` key at all, and every one of those literals was relative to the
current working directory. A reader started from anywhere but the repo root
therefore pointed SQLite at a path that did not exist, and SQLite created a
new empty database beside the caller — so a missing history was reported as
an empty one, which is the same class of fault as Tool 2's `ReportGenerator`
(P4 config-not-constants, P16 wrong-file read, P2 an absence reported as a
measurement).

The fix: `db_connect` owns the path. `database.path` in `config.yml` sets it,
`process_config.apply` applies it beside the lock wait, relative paths resolve
against the repo root, and every call site asks `db_connect.database_path()`
at call time rather than carrying a literal.

Spec: docs/review_2026-11-04/PLAN_Y12_one_database_named_once.md
"""

import ast
import csv
import glob
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import db_connect  # noqa: E402
import http_retry  # noqa: E402
import process_config  # noqa: E402


@contextmanager
def _cwd(path):
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class _PathIsolation(unittest.TestCase):
    """Every test restores every process-wide policy it rebinds.

    Not the path alone: these tests call `process_config.apply` and the real
    loaders with configs that carry no `http_retry` block, which resets the
    retry policy and the lock wait process-wide for whatever runs next. A test
    file that leaves global state behind is an order-dependence waiting to
    happen (the cold review of chunk Y12).
    """

    def setUp(self):
        self._saved_path = db_connect.DATABASE_PATH
        self._saved_wait = db_connect.LOCK_TIMEOUT_SECONDS
        self._saved_retry = http_retry.current_retry_policy()
        self.addCleanup(self._restore)

    def _restore(self):
        db_connect.DATABASE_PATH = self._saved_path
        db_connect.LOCK_TIMEOUT_SECONDS = self._saved_wait
        http_retry.install_retry_policy(self._saved_retry)


def _seed_database(path):
    """A database with one `runs` row, so an export has something to find."""
    with db_connect.connection(path) as conn:
        conn.execute("CREATE TABLE runs (run_ts TEXT, topic TEXT)")
        conn.execute("INSERT INTO runs VALUES ('20261118_0900', 'y12')")
    return path


class TestTheConfiguredPathIsResolvedOnce(_PathIsolation):

    def test_a_relative_path_resolves_against_the_repo_root(self):
        """The whole point of the chunk. `serp_data.db` in the config means
        the one database this tool keeps, not a new file in whatever directory
        the command happened to be run from."""
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as elsewhere:
            with mock.patch.object(db_connect, "_REPO_ROOT", root), _cwd(elsewhere):
                resolved = db_connect.resolve_database_path("serp_data.db")
        self.assertEqual(resolved, os.path.join(root, "serp_data.db"))
        self.assertNotEqual(os.path.dirname(resolved), elsewhere)

    def test_an_absolute_path_is_used_as_given(self):
        self.assertEqual(
            db_connect.resolve_database_path("/var/data/serp.db"),
            "/var/data/serp.db")

    def test_a_tilde_is_expanded(self):
        resolved = db_connect.resolve_database_path("~/serp.db")
        self.assertEqual(resolved, os.path.join(os.path.expanduser("~"), "serp.db"))

    def test_an_absent_key_gives_the_documented_default(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(db_connect, "_REPO_ROOT", root):
                self.assertEqual(db_connect.apply_database_path({}),
                                 os.path.join(root, "serp_data.db"))

    def test_a_value_that_is_not_a_path_is_reported_not_used(self):
        """P2: a blank or non-string value is somebody's mistake, and silently
        falling back would hide it."""
        for bad in (42, "", "   ", [], True):
            with self.subTest(bad=bad):
                with self.assertLogs(db_connect.logger, "WARNING") as logs:
                    resolved = db_connect.resolve_database_path(bad)
                self.assertIn("serp_data.db", os.path.basename(resolved))
                self.assertIn("database", "".join(logs.output))


class TestOneLoaderCarriesBothPolicies(_PathIsolation):

    def test_process_config_apply_sets_the_path_beside_the_lock_wait(self):
        """One function, every process-wide policy (review chunk Y11). A
        loader cannot pick up the lock wait and miss the database."""
        saved_timeout = db_connect.LOCK_TIMEOUT_SECONDS
        self.addCleanup(setattr, db_connect, "LOCK_TIMEOUT_SECONDS", saved_timeout)
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(db_connect, "_REPO_ROOT", root):
                process_config.apply({
                    "database": {"path": "hist.db", "lock_timeout_seconds": 21.0},
                })
                self.assertEqual(db_connect.database_path(),
                                 os.path.join(root, "hist.db"))
                self.assertEqual(db_connect.lock_timeout(), 21.0)


class TestAReaderRunFromElsewhereFindsTheHistory(_PathIsolation):
    """The consequence the chunk exists for.

    `export_history.py` loaded no config and opened the literal
    `"serp_data.db"`. Run from any other directory it reported "Database
    serp_data.db not found" against a history that was there all along — or,
    in the writers, created an empty file beside the caller.
    """

    def test_export_history_exports_the_configured_database(self):
        import export_history
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            _seed_database(os.path.join(root, "hist.db"))
            config_path = os.path.join(root, "config.yml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("database:\n  path: hist.db\n")
            with mock.patch.object(db_connect, "_REPO_ROOT", root), _cwd(elsewhere):
                export_history.load_config(config_path)
                self.assertEqual(db_connect.database_path(),
                                 os.path.join(root, "hist.db"))
                export_history.export_tables()
                exported = os.path.join(elsewhere, "exports", "runs.csv")
                self.assertTrue(os.path.exists(exported),
                                "the reader did not find the configured database")
                with open(exported, encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                # The seeded row, not an empty table: proof it read the real file.
                self.assertEqual([r["topic"] for r in rows], ["y12"])
                # And nothing was created beside the caller.
                self.assertFalse(os.path.exists(os.path.join(elsewhere, "serp_data.db")))

    def test_verify_enrichment_reports_an_absent_database_rather_than_making_one(self):
        """P2/P16: the honest outcome for a missing file is a report, never a
        new empty database that reads as an empty history."""
        import verify_enrichment
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            config_path = os.path.join(root, "config.yml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("database:\n  path: never_written.db\n")
            with mock.patch.object(db_connect, "_REPO_ROOT", root), _cwd(elsewhere):
                verify_enrichment.load_config(config_path)
                captured = io.StringIO()
                with mock.patch.object(sys, "stdout", captured):
                    verify_enrichment.verify_db()
                self.assertIn("never_written.db", captured.getvalue())
                self.assertFalse(os.path.exists(os.path.join(elsewhere, "serp_data.db")))
                self.assertFalse(os.path.exists(os.path.join(root, "never_written.db")))


class TestTheDefaultReachesEveryClient(_PathIsolation):
    """Every gateway that took the literal now asks at call time."""

    def test_the_storage_classes_take_the_configured_database(self):
        import storage
        with tempfile.TemporaryDirectory() as root:
            configured = os.path.join(root, "configured.db")
            db_connect.DATABASE_PATH = configured
            self.assertEqual(storage.SerpStorage().db_path, configured)

    def test_migrated_connection_takes_the_configured_database(self):
        """The Y4 trap at a call site: `db_path=db_connect.database_path()` in
        the signature reads the path at `def` time, so a configured path set
        later never reaches it. An absent database must raise rather than be
        created."""
        import storage
        with tempfile.TemporaryDirectory() as root:
            configured = os.path.join(root, "configured.db")
            db_connect.DATABASE_PATH = configured
            with self.assertRaises(FileNotFoundError) as caught:
                storage.migrated_connection()
            self.assertEqual(str(caught.exception), configured)

    def test_the_api_clients_take_the_configured_database(self):
        import dataforseo_client
        import gsc_client
        import moz_client
        import moz_keywords
        import moz_competitor
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"DATAFORSEO_LOGIN": "l",
                                             "DATAFORSEO_PASSWORD": "p",
                                             "MOZ_TOKEN": "t"}):
            configured = os.path.join(root, "configured.db")
            db_connect.DATABASE_PATH = configured
            built = [
                dataforseo_client.DataForSEOClient(),
                gsc_client.GscClient(property_url="https://example.test/",
                                     token_provider=lambda: "token"),
                moz_client.MozClient(),
                moz_keywords.MozKeywordClient(),
                moz_competitor.MozCompetitorClient(),
            ]
            for client in built:
                with self.subTest(client=type(client).__name__):
                    paths = [getattr(client, name) for name in ("db_path", "_db_path")
                             if hasattr(client, name)]
                    self.assertTrue(paths, "client records no database path")
                    self.assertEqual(paths[0], configured)

    def test_the_script_level_readers_take_the_configured_database(self):
        import export_history
        import metrics
        import verify_enrichment
        import visualize_volatility
        with tempfile.TemporaryDirectory() as root:
            configured = os.path.join(root, "configured.db")
            db_connect.DATABASE_PATH = configured
            for module in (metrics, visualize_volatility, export_history,
                           verify_enrichment):
                with self.subTest(module=module.__name__):
                    self.assertEqual(module._db_path(), configured)


class TestTheNameLivesInOnePlace(_PathIsolation):
    """P4/P32: one home for the name, so the next call site cannot acquire a
    second one."""

    #: The one module allowed to contain the string.
    #:
    #: `keyword_enrich.py` held a 25th copy of it while untracked — its own
    #: `--db` default and no config load, so it cached Moz rows into a
    #: different database than the run reads. It was fixed when it was
    #: committed (2026-11-22): it now loads config.yml through
    #: `process_config` and takes the path from `db_connect`.
    _OWNERS = {"db_connect"}

    @staticmethod
    def _tracked_modules():
        """The repo's own top-level modules.

        Tracked files only: the working tree also holds local scratch scripts
        that are not part of the repo, and a guard that failed on one of those
        would be failing on something no commit can fix."""
        listed = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True).stdout.split()
        return [name for name in listed if "/" not in name]

    def test_no_module_carries_the_database_name_as_a_literal(self):
        offenders = []
        tracked = self._tracked_modules()
        self.assertIn("db_connect.py", tracked)  # P21: the listing worked
        for name in sorted(tracked):
            path = os.path.join(REPO_ROOT, name)
            module = name[:-3]
            if module in self._OWNERS:
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # Exact equality, so a docstring that merely mentions the name
                # while recording what it used to be is not a match; only a
                # literal the code could hand to `sqlite3.connect` is.
                if isinstance(node, ast.Constant) and node.value == "serp_data.db":
                    offenders.append(f"{module}:{node.lineno}")
        self.assertEqual(offenders, [], "the database name is a literal here")

    def test_the_walk_would_see_a_literal_if_one_were_there(self):
        """P21: a guard that walks nothing passes."""
        found = []
        tree = ast.parse(open(os.path.join(REPO_ROOT, "db_connect.py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "serp_data.db":
                found.append(node.lineno)
        self.assertEqual(len(found), 1,
                         "db_connect should name the database exactly once")

    def test_config_yml_declares_the_setting(self):
        """P4: the default and the config key resolve to the same file, so the
        only thing that makes the path editable is the key being there to
        edit. A key nobody can find is a constant."""
        import yaml
        with open(os.path.join(REPO_ROOT, "config.yml"), encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        section, key = db_connect.DATABASE_PATH_SOURCE
        self.assertIn(key, config.get(section, {}),
                      f"config.yml {section}.{key} is where the database is set")
        self.assertEqual(config[section][key], db_connect.DEFAULT_DATABASE_NAME)

    def test_the_gui_explains_the_setting(self):
        """The Configuration Manager renders every key in a `config.yml`
        section, so adding one adds a field; a field with no help text is a
        path an operator can change without being told what it does (P2)."""
        import config_manager
        section, key = db_connect.DATABASE_PATH_SOURCE
        self.assertIn(f"config.yml.{section}.{key}", config_manager.HELP_BY_FIELD)

    def test_the_config_reference_documents_the_setting(self):
        with open(os.path.join(REPO_ROOT, "docs", "config_reference.md"),
                  encoding="utf-8") as handle:
            reference = handle.read()
        self.assertIn("database.path", reference)

    def test_every_db_option_defaults_to_the_configured_path(self):
        """A `--db` default of `"serp_data.db"` is the same bug wearing an
        argparse hat: it is relative to the caller's directory and it is read
        before any config is loaded."""
        for name in ("export_ai_visibility", "generate_insight_report",
                     "probe_ai_visibility", "run_gsc_analysis"):
            with self.subTest(module=name):
                tree = ast.parse(open(os.path.join(REPO_ROOT, name + ".py"),
                                      encoding="utf-8").read())
                defaults = []
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "add_argument"):
                        continue
                    if not (node.args and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value == "--db"):
                        continue
                    for kw in node.keywords:
                        if kw.arg == "default":
                            defaults.append(kw.value)
                self.assertEqual(len(defaults), 1, "expected one --db option")
                self.assertIsInstance(defaults[0], ast.Constant)
                self.assertIsNone(defaults[0].value,
                                  "--db must default to None and be resolved "
                                  "after the config loader")


class TestEveryLoaderNamesTheSameConfig(_PathIsolation):
    """P5/P16 — the configured path only reached the entry points when the
    process's working directory happened to be the repo root.

    Eight loaders defaulted to the bare `"config.yml"`, so starting the tool
    from anywhere else found no config, reset every policy, and abandoned a
    configured `database.path` for the built-in one — which on an installation
    that had ever run before exists and reads as a real, stale history.
    """

    #: Every loader whose config path is a default rather than an argument.
    _LOADERS = (
        ("export_history", "load_config"),
        ("verify_enrichment", "load_config"),
        ("export_ai_visibility", "_load_config"),
        ("probe_ai_visibility", "_load_config"),
        ("run_gsc_analysis", "_load_config"),
        ("run_feasibility", "_load_config"),
        ("refresh_analysis_outputs", "load_config"),
        ("report_llm", "load_settings"),
    )

    def test_no_loader_defaults_to_a_cwd_relative_config(self):
        for module_name, function_name in self._LOADERS:
            with self.subTest(loader=f"{module_name}.{function_name}"):
                tree = ast.parse(open(os.path.join(
                    REPO_ROOT, module_name + ".py"), encoding="utf-8").read())
                found = [node for node in tree.body
                         if isinstance(node, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))
                         and node.name == function_name]
                self.assertEqual(len(found), 1)  # P21
                for default in found[0].args.defaults:
                    self.assertNotEqual(
                        getattr(default, "value", None), "config.yml",
                        "a bare 'config.yml' default is read against the "
                        "caller's working directory")

    def test_each_loader_reads_the_named_config_from_another_directory(self):
        """The consequence. Each loader is called with no path, from a
        directory that is not the repo root, and must pick up the database the
        named config sets."""
        import process_config
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            config_path = os.path.join(root, "config.yml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("database:\n  path: named.db\n")
            expected = os.path.join(root, "named.db")
            for module_name, function_name in self._LOADERS:
                with self.subTest(loader=f"{module_name}.{function_name}"):
                    db_connect.DATABASE_PATH = "/nowhere/stale.db"
                    module = __import__(module_name)
                    with mock.patch.object(db_connect, "_REPO_ROOT", root), \
                            mock.patch.object(process_config,
                                              "DEFAULT_CONFIG_PATH",
                                              config_path), \
                            _cwd(elsewhere):
                        getattr(module, function_name)()
                    self.assertEqual(db_connect.database_path(), expected)

    def test_the_audit_and_the_gui_name_the_same_config(self):
        """`serp_audit` reads the config at module level and the GUI launches
        it with `cwd=os.getcwd()`, so the GUI's own path and the audit's had
        to agree — and both had to stop being the working directory."""
        import process_config
        for name in ("serp_audit.py", "serp-me.py"):
            with self.subTest(module=name):
                source = open(os.path.join(REPO_ROOT, name),
                              encoding="utf-8").read()
                self.assertIn("process_config.config_path()", source)
                self.assertNotIn('os.path.join(os.getcwd(), "config.yml")',
                                 source)
        self.assertEqual(process_config.config_path(),
                         os.path.join(REPO_ROOT, "config.yml"))
        self.assertEqual(process_config.config_path("given.yml"), "given.yml")


class TestANewDatabaseIsAnnounced(_PathIsolation):
    """P1/P2/P6 — `sqlite3.connect` creates whatever path it is handed. While
    the name was a literal that could not be wrong this did not matter; now
    that `database.path` is editable, a typo or an unmounted volume produces a
    new empty history that every reader then reports as "no history yet"."""

    def test_creating_a_database_says_so_once(self):
        with tempfile.TemporaryDirectory() as root:
            fresh = os.path.join(root, "fresh.db")
            db_connect._ANNOUNCED_NEW.discard(fresh)
            self.addCleanup(db_connect._ANNOUNCED_NEW.discard, fresh)
            with self.assertLogs(db_connect.logger, "WARNING") as logs:
                with db_connect.connection(fresh) as conn:
                    conn.execute("CREATE TABLE t (a TEXT)")
            message = "".join(logs.output)
            self.assertIn(fresh, message)
            self.assertIn("database", message)
            # Opening the database it just made is not news.
            with self.assertRaises(AssertionError):
                with self.assertLogs(db_connect.logger, "WARNING"):
                    with db_connect.connection(fresh) as conn:
                        conn.execute("SELECT 1")

    def test_opening_an_existing_database_says_nothing(self):
        """Created outside `db_connect`, so the per-process "already told you"
        set is empty and the check has to look at the file itself."""
        with tempfile.TemporaryDirectory() as root:
            existing = os.path.join(root, "seeded.db")
            conn = sqlite3.connect(existing)
            conn.execute("CREATE TABLE runs (run_ts TEXT)")
            conn.commit()
            conn.close()
            self.assertNotIn(existing, db_connect._ANNOUNCED_NEW)
            with self.assertRaises(AssertionError):
                with self.assertLogs(db_connect.logger, "WARNING"):
                    with db_connect.connection(existing) as handle:
                        handle.execute("SELECT 1")


class TestTheRetryPolicyCanBePutBack(unittest.TestCase):
    """A test that rebinds the process's retry policy has to restore all eight
    globals. The first base to try saved one of them, which left a test's
    budget installed for whatever ran next (the cold review of chunk Y12)."""

    def test_the_policy_survives_a_round_trip(self):
        saved = http_retry.current_retry_policy()
        self.addCleanup(http_retry.install_retry_policy, saved)
        self.assertEqual(sorted(saved), sorted(http_retry.POLICY_GLOBALS))
        http_retry.apply_retry_policy({"http_retry": {"attempts": 7,
                                                      "timeout_seconds": 3}})
        self.assertNotEqual(http_retry.current_retry_policy(), saved)
        http_retry.install_retry_policy(saved)
        self.assertEqual(http_retry.current_retry_policy(), saved)
        for name, value in saved.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(http_retry, name), value)

    def test_every_global_apply_rebinds_is_in_the_named_set(self):
        """P21/P32: the set is what both bases save, so a ninth global added to
        `apply_retry_policy` and not to it would be restored by nobody."""
        tree = ast.parse(open(os.path.join(REPO_ROOT, "http_retry.py"),
                              encoding="utf-8").read())
        declared = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "apply_retry_policy":
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Global):
                        declared.update(inner.names)
        self.assertTrue(declared)
        self.assertEqual(declared, set(http_retry.POLICY_GLOBALS))

    def test_a_name_that_is_not_a_policy_global_is_refused(self):
        with self.assertRaises(ValueError):
            http_retry.install_retry_policy({"NOT_A_POLICY": 1})


class TestTheReportResolvesAfterItsLoader(_PathIsolation):
    """`main` read the path before anything had loaded the config, so a
    configured `database.path` never reached the AIO-exposure write: the run's
    rows went to the configured database and the trend to the default one,
    with nothing logged (P4/P16)."""

    def test_main_passes_the_configured_database_to_generate_report(self):
        import generate_insight_report as gir
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            with open(os.path.join(root, "config.yml"), "w",
                      encoding="utf-8") as handle:
                handle.write("database:\n  path: named.db\n")
            json_path = os.path.join(elsewhere,
                                     "market_analysis_x_20261118_0900.json")
            with open(json_path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            seen = {}

            def _fake_generate_report(data, db_path=None, run_ts=None):
                seen["db_path"] = db_path
                return "# report"

            db_connect.DATABASE_PATH = "/nowhere/stale.db"
            with mock.patch.object(db_connect, "_REPO_ROOT", root), \
                    mock.patch.object(gir, "_REPO_ROOT", root), \
                    mock.patch.dict(gir._CONFIG_CACHE, {}, clear=True), \
                    mock.patch.object(gir, "load_data", lambda path: {}), \
                    mock.patch.object(gir, "generate_report",
                                      _fake_generate_report), \
                    mock.patch.object(sys, "argv",
                                      ["generate_insight_report.py",
                                       "--json", json_path,
                                       "--out", os.path.join(elsewhere,
                                                             "out.md")]), \
                    _cwd(elsewhere):
                gir.main()
            self.assertEqual(seen["db_path"], os.path.join(root, "named.db"))


class TestTheExportUsesTheConfiguredDatabase(_PathIsolation):

    def test_export_ai_visibility_reads_the_configured_database(self):
        """`main` with no `--db`: the path comes from the config it just
        loaded, not from the directory it was started in."""
        import export_ai_visibility
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            configured = _seed_database(os.path.join(root, "hist.db"))
            config_path = os.path.join(root, "config.yml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("database:\n  path: hist.db\n")
            seen = {}

            def _fake_build(db_path, client_name=None):
                seen["db_path"] = db_path
                return None  # stops before any write

            with mock.patch.object(db_connect, "_REPO_ROOT", root), \
                    mock.patch.object(export_ai_visibility,
                                      "build_ai_visibility_export", _fake_build), \
                    _cwd(elsewhere):
                code = export_ai_visibility.main(
                    ["--config", config_path, "--out", elsewhere])
        self.assertEqual(code, 1)  # the stubbed builder reports a schema failure
        self.assertEqual(seen["db_path"], configured)


if __name__ == "__main__":
    unittest.main()
