"""Chunk Y11 — a failing cleanup is not the diagnosis, and the lock wait is chosen.

Spec: docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md

Two faults in the Y9 helper, carried as adjacent issues by Y9 (F6) and Y10 (F7):

* `conn.rollback()` and `conn.close()` were unguarded, so an exception from
  either replaced the exception the caller needed to see — and on the clean
  path, a failing `close()` after a successful `commit()` turned a durable
  write into a reported failure.
* `sqlite3.connect`'s `timeout` — the wait for another writer's lock — was
  left at its default of 5.0, a number nobody chose and nobody could change.
"""
import ast
import glob
import logging
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml                  # noqa: E402

import config_tab_models     # noqa: E402
import db_connect           # noqa: E402
import generate_insight_report  # noqa: E402
import report_llm           # noqa: E402
import http_retry           # noqa: E402
import process_config       # noqa: E402
import timeouts             # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _PolicyIsolation(unittest.TestCase):
    """Every policy is process-wide state; a test must not leak its own.

    All eight retry globals, not just the timeout: saving one of them left a
    test's budget installed for whatever ran next (the cold review of chunk
    Y12).
    """

    def setUp(self):
        self._saved = (http_retry.current_retry_policy(),
                       db_connect.LOCK_TIMEOUT_SECONDS,
                       db_connect.DATABASE_PATH)

    def tearDown(self):
        http_retry.install_retry_policy(self._saved[0])
        db_connect.LOCK_TIMEOUT_SECONDS = self._saved[1]
        db_connect.DATABASE_PATH = self._saved[2]


class _CleanupFails:
    """A connection proxy whose `rollback` or `close` raises.

    `sqlite3.Connection` is a C type with read-only attributes, so the failing
    cleanup cannot be patched onto a real one. Everything else is delegated, so
    the commit, the execute and the transaction are the real database's.
    """

    def __init__(self, conn, failing, error=None):
        self._conn = conn
        self._failing = failing
        self._error = error or sqlite3.OperationalError("disk I/O error")

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def rollback(self):
        if self._failing == "rollback":
            raise self._error
        return self._conn.rollback()

    def close(self):
        if self._failing == "close":
            raise self._error
        return self._conn.close()

    def really_close(self):
        self._conn.close()


def _connecting_with_failing_cleanup(failing, error=None):
    """`sqlite3.connect` patched so the connection's *failing* step raises."""
    real = sqlite3.connect

    def connect(*args, **kwargs):
        proxy = _CleanupFails(real(*args, **kwargs), failing, error)
        return proxy
    return mock.patch.object(db_connect.sqlite3, "connect", side_effect=connect)


class TestACleanupFailureDoesNotReplaceTheDiagnosis(unittest.TestCase):

    def _db(self):
        directory = tempfile.mkdtemp()
        return os.path.join(directory, "t.db")

    def test_a_failing_rollback_leaves_the_blocks_exception_intact(self):
        """The `IntegrityError` that says which write was wrong must survive a
        rollback that cannot run. Before Y11 the caller saw the rollback's
        error instead, with the real one buried in `__context__`."""
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback"):
            with self.assertRaises(ValueError) as caught:
                with db_connect.connection(db_path):
                    raise ValueError("the real diagnosis")
        self.assertEqual(str(caught.exception), "the real diagnosis")

    def test_a_failing_close_leaves_the_blocks_exception_intact(self):
        db_path = self._db()
        with _connecting_with_failing_cleanup("close"):
            with self.assertRaises(ValueError) as caught:
                with db_connect.connection(db_path):
                    raise ValueError("the real diagnosis")
        self.assertEqual(str(caught.exception), "the real diagnosis")

    def test_a_failing_close_does_not_fail_a_committed_write(self):
        """The clean path. The commit has already succeeded, so the row is on
        disk; raising from `close()` would make the caller record the write as
        failed and the run report an absence where there is a row (P6)."""
        db_path = self._db()
        with db_connect.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (x)")
        # The commit runs and the close does not: exactly the order that made
        # this a silent data-loss report.
        with _connecting_with_failing_cleanup("close"):
            with db_connect.connection(db_path) as conn:
                conn.execute("INSERT INTO t VALUES (1)")
            conn.really_close()
        with db_connect.connection(db_path) as conn:
            self.assertEqual(conn.execute("SELECT x FROM t").fetchall(), [(1,)])

    def test_a_cleanup_failure_is_logged_not_swallowed(self):
        """P2: the cleanup failure is a second fact, and it is reported."""
        db_path = self._db()
        with self.assertLogs(db_connect.logger, level=logging.ERROR) as logged:
            with _connecting_with_failing_cleanup("rollback"):
                with self.assertRaises(ValueError):
                    with db_connect.connection(db_path):
                        raise ValueError("the real diagnosis")
        joined = "\n".join(logged.output)
        self.assertIn("roll back", joined)
        self.assertIn("disk I/O error", joined)

    def test_an_interrupt_during_cleanup_still_reaches_the_user(self):
        """`_safely` catches `Exception`, not `BaseException`: a Ctrl-C while
        the rollback runs is the user, and swallowing it would make the tool
        uninterruptible at the one moment it is slow."""
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback", KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                with db_connect.connection(db_path):
                    raise ValueError("overtaken by the interrupt")


class TestTheLockWaitIsTheConfiguredOne(_PolicyIsolation):
    """Consequence, not inspection: another connection holds the write lock,
    and the wait before `database is locked` is the configured number."""

    def setUp(self):
        super().setUp()
        directory = tempfile.mkdtemp()
        self.db_path = os.path.join(directory, "t.db")
        with db_connect.connection(self.db_path) as conn:
            conn.execute("CREATE TABLE t (x)")
        self.holder = sqlite3.connect(self.db_path, timeout=0.05)
        self.holder.execute("BEGIN EXCLUSIVE")
        self.addCleanup(self.holder.close)

    def _blocked_write_seconds(self, **kwargs):
        started = time.monotonic()
        with self.assertRaises(sqlite3.OperationalError):
            with db_connect.connection(self.db_path, **kwargs) as conn:
                conn.execute("INSERT INTO t VALUES (1)")
        return time.monotonic() - started

    def test_the_configured_wait_is_how_long_a_blocked_write_waits(self):
        db_connect.apply_lock_timeout({"database": {"lock_timeout_seconds": 0.2}})
        short = self._blocked_write_seconds()
        db_connect.apply_lock_timeout({"database": {"lock_timeout_seconds": 1.4}})
        long = self._blocked_write_seconds()
        # Derived from the two configured numbers, not a floor picked to pass
        # (P29): 1.4 - 0.2 is 1.2, and half of that is a wide margin for a
        # loaded machine while still failing a helper that ignores the config.
        self.assertGreater(long - short, 0.6)
        self.assertLess(short, 1.0)

    def test_a_call_site_that_names_its_own_wait_is_honoured(self):
        """`kwargs.setdefault`, so the configured wait is a default and not an
        override: a caller with a reason to wait less may say so."""
        db_connect.apply_lock_timeout({"database": {"lock_timeout_seconds": 1.4}})
        self.assertLess(self._blocked_write_seconds(timeout=0.1), 0.9)


class TestTheWaitIsReadLikeEveryOtherWait(_PolicyIsolation):

    def test_an_absent_block_leaves_the_documented_default(self):
        self.assertEqual(db_connect.apply_lock_timeout({}),
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)
        self.assertEqual(db_connect.apply_lock_timeout(None),
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)

    def test_the_default_is_sqlite3s_own_so_the_change_is_not_a_behaviour_change(self):
        """5.0 is what `sqlite3.connect` has always used here. Naming it is the
        point; silently changing the wait would be a different chunk."""
        self.assertEqual(db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS, 5.0)

    def test_a_non_positive_or_non_numeric_wait_is_refused_and_reported(self):
        for value in (0, -3, "soon", True, [5]):
            with self.subTest(value=value):
                with self.assertLogs(level=logging.WARNING):
                    resolved = db_connect.apply_lock_timeout(
                        {"database": {"lock_timeout_seconds": value}})
                self.assertEqual(resolved,
                                 db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)

    def test_a_mangled_or_empty_block_is_reported(self):
        """The three shapes `http_retry` was fixed for in the cold review of
        chunk Y7, and this missed in its own: a block mangled to a scalar or
        to nothing. An indentation typo is enough, and the configured wait was
        discarded in silence (P2/P5)."""
        for section in (None, 5, "nonsense", [], {}):
            with self.subTest(section=section):
                with self.assertLogs(db_connect.logger,
                                     level=logging.WARNING) as logged:
                    resolved = db_connect.apply_lock_timeout(
                        {"database": section})
                self.assertEqual(resolved,
                                 db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)
                self.assertIn("database", "\n".join(logged.output))

    def test_a_wait_longer_than_the_ceiling_is_reported_and_capped(self):
        """A contended write blocks the thread that makes it, and the GUI
        calls `refresh_analysis_outputs` on the Tk thread: `5000` for `5.0`
        would freeze the window for 83 minutes with nothing in the log until
        the wait ended. The sibling policy bounds its wait for the same
        reason (`max_retry_after_seconds`); this one had no bound at all
        (P4/P9, cold review of chunk Y11)."""
        with self.assertLogs(db_connect.logger, level=logging.WARNING):
            resolved = db_connect.apply_lock_timeout(
                {"database": {"lock_timeout_seconds": 5000}})
        self.assertEqual(resolved, db_connect.MAX_LOCK_TIMEOUT_SECONDS)
        self.assertEqual(db_connect.lock_timeout(),
                         db_connect.MAX_LOCK_TIMEOUT_SECONDS)

    def test_a_wait_at_the_ceiling_is_honoured(self):
        """The bound is a bound, not a narrower refusal."""
        self.assertEqual(
            db_connect.apply_lock_timeout(
                {"database": {"lock_timeout_seconds":
                              db_connect.MAX_LOCK_TIMEOUT_SECONDS}}),
            db_connect.MAX_LOCK_TIMEOUT_SECONDS)

    def test_a_key_written_with_nothing_after_it_is_reported(self):
        """`lock_timeout_seconds:` with no value parses as `None`, which
        `seconds_from_config` reads as "key absent" and would accept in
        silence — the distinction `http_retry` already makes (P2)."""
        with self.assertLogs(db_connect.logger, level=logging.WARNING) as logged:
            db_connect.apply_lock_timeout({"database": {"lock_timeout_seconds": None}})
        self.assertIn("is empty", "\n".join(logged.output))

    def test_the_wait_is_read_through_the_repos_one_rule(self):
        """Not a second validator (P32): `timeouts.seconds_from_config` is
        where "a positive number of seconds, else the default with a warning"
        is defined, and this reads through it."""
        self.assertIs(db_connect.seconds_from_config,
                      timeouts.seconds_from_config)
        self.assertEqual(
            db_connect.apply_lock_timeout(
                {"database": {"lock_timeout_seconds": 9}}), 9.0)

    def test_the_wait_is_read_through_a_function_not_a_default_argument(self):
        """The Y4 trap: a default argument binds at `def` time, before any
        config is read, so the configured value would never reach the call."""
        db_connect.apply_lock_timeout({"database": {"lock_timeout_seconds": 3.5}})
        self.assertEqual(db_connect.lock_timeout(), 3.5)


# ---------------------------------------------------------------------------
# One apply site
# ---------------------------------------------------------------------------

#: Every module-level function in this repo that parses `config.yml` and the
#: callable to exercise. Derived expectation: the AST test below fails when a
#: function parses `config.yml` and is in neither this map nor the exemptions,
#: so a loader added later cannot quietly skip the policies.
_LOADERS = {
    ("refresh_analysis_outputs", "load_config"): None,
    # Review chunk Y12 gave these three a loader: the first two read no config
    # at all, and the third read it for the client slug alone, so none of them
    # took the configured database path or lock wait.
    ("export_history", "load_config"): None,
    ("verify_enrichment", "load_config"): None,
    ("export_ai_visibility", "_load_config"): None,
    # Launches every step as a subprocess and opens no database itself, but
    # its closing summary names the configured one, so it reads a policy it
    # has to set. It was exempt until the cold review of chunk Y12. The
    # structural half covers it; calling it would run the whole pipeline, so
    # it carries the reason its consequence is not observed here.
    ("run_pipeline", "main"): "calling it runs every step of the pipeline",
    ("run_feasibility", "_load_config"): None,
    ("probe_ai_visibility", "_load_config"): None,
    ("report_llm", "load_settings"): None,
    ("run_gsc_analysis", "_load_config"): None,
    ("generate_insight_report", "_load_config"): None,
}

#: Functions that parse `config.yml` and legitimately set no policy, each with
#: the reason. An exemption is a claim about the function, so it is written
#: down rather than left as an absence.
_EXEMPT = {
    # Writes the finished run's output paths back into config.yml.
    ("pipeline_status", "finish_run"),
    # Runs inside the report, after `_load_config` has applied the policies.
    ("generate_insight_report", "build_content_briefs_section"),
    # A generic reader for whatever .yml path its caller passes — the
    # editorial files, and config.yml itself from `brief_rendering`'s CLI.
    # Exempt because it is a reader, not an entry point: nothing on the brief
    # path opens the database, and the CLI that passes it config.yml applies
    # the policies itself. Its first stated reason, that the path is never
    # config.yml, was simply wrong (the cold review of chunk Y12).
    ("brief_data_extraction", "load_yaml_config"),
}


def _functions_parsing_the_config():
    """`(module, function)` for every module-level function that parses
    `config.yml`: it calls `yaml.safe_load` and either names the file or takes
    a `config_path`/`config_file` to read it from.

    The parameter half was added in review chunk Y12: a loader whose path
    arrives as an argument names no file, and `export_ai_visibility._load_config`
    escaped the first version of this walk for exactly that reason."""
    found = set()
    config_params = {"config_path", "config_file"}
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "*.py"))):
        module = os.path.basename(path)[:-3]
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            dumped = ast.dump(node)
            if "'safe_load'" not in dumped:
                continue
            params = ({arg.arg for arg in node.args.args}
                      | {arg.arg for arg in node.args.kwonlyargs})
            if "'config.yml'" in dumped or (params & config_params):
                found.add((module, node.name))
    return found


def _calls_process_config_apply(module, function):
    tree = ast.parse(open(os.path.join(REPO_ROOT, module + ".py"),
                          encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == function:
            for call in ast.walk(node):
                if isinstance(call, ast.Call) \
                        and isinstance(call.func, ast.Attribute) \
                        and call.func.attr == "apply" \
                        and isinstance(call.func.value, ast.Name) \
                        and call.func.value.id == "process_config":
                    return True
    return False


class TestEveryConfigReaderAppliesEveryPolicy(_PolicyIsolation):

    def test_the_walk_found_the_loaders_it_is_about(self):
        """P21: a guard that walks nothing passes. The six known loaders must
        be in what the walk returns, or the walk is broken and the structural
        test below is vacuous."""
        found = _functions_parsing_the_config()
        self.assertGreaterEqual(len(found), len(_LOADERS) + len(_EXEMPT))
        for key in _LOADERS:
            self.assertIn(key, found)

    def test_every_config_parser_applies_the_policies_or_is_exempt(self):
        """The structural half. A loader added later has no consequence to
        observe until it exists, so this is the only form the guard can take —
        and it is paired with the consequence tests below, which prove the
        existing loaders actually set both policies."""
        for key in sorted(_functions_parsing_the_config()):
            with self.subTest(key=key):
                if key in _EXEMPT:
                    self.assertNotIn(key, _LOADERS)
                    continue
                self.assertIn(
                    key, _LOADERS,
                    f"{key[0]}.{key[1]} parses config.yml but is neither a "
                    f"registered loader nor a documented exemption")
                self.assertTrue(_calls_process_config_apply(*key))

    def test_serp_audit_applies_the_policies_at_import(self):
        """`serp_audit` reads config.yml at module level rather than in a
        loader function, so it is not in the walk above."""
        tree = ast.parse(open(os.path.join(REPO_ROOT, "serp_audit.py"),
                              encoding="utf-8").read())
        applied = [
            node for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "apply"
            and getattr(node.value.func.value, "id", None) == "process_config"
        ]
        self.assertEqual(len(applied), 1)

    def _call_loader(self, module_name, function_name, config_path):
        module = __import__(module_name)
        loader = getattr(module, function_name)
        if module_name == "generate_insight_report":
            # Its loader takes no path: the file is `_REPO_ROOT/config.yml`.
            with mock.patch.object(module, "_REPO_ROOT",
                                   os.path.dirname(config_path)):
                return loader()
        return loader(config_path)

    def test_each_loader_sets_both_policies(self):
        """The consequence half, and the point of the chunk: one function sets
        every process-wide policy, so a loader cannot pick up the retry budget
        and miss the lock wait. Five of the six called
        `http_retry.apply_retry_policy` directly and the sixth called
        nothing."""
        directory = tempfile.mkdtemp()
        config_path = os.path.join(directory, "config.yml")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("http_retry:\n  timeout_seconds: 7\n"
                         "database:\n  lock_timeout_seconds: 11.5\n")
        # A directory of its own: `generate_insight_report._load_config` takes
        # no path and reads `_REPO_ROOT/config.yml`, so "absent" has to mean an
        # empty directory rather than another name in this one.
        missing = os.path.join(tempfile.mkdtemp(), "config.yml")
        skipped = []
        for (module_name, function_name), reason in sorted(_LOADERS.items()):
            with self.subTest(loader=f"{module_name}.{function_name}"):
                if reason:
                    skipped.append((module_name, function_name))
                    continue
                process_config.apply(None)
                self._call_loader(module_name, function_name, config_path)
                self.assertEqual(http_retry.request_timeout(), 7.0)
                self.assertEqual(db_connect.lock_timeout(), 11.5)
                # The absent-config branch resets both rather than inheriting
                # what the previous loader left: the GUI calls these in one
                # process, one after another.
                self._call_loader(module_name, function_name, missing)
                self.assertEqual(
                    http_retry.request_timeout(),
                    http_retry.DEFAULT_RETRY_POLICY["timeout"])
                self.assertEqual(db_connect.lock_timeout(),
                                 db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)
        # P21: the loop must have had something to do. A reason that silences
        # a loader is written down above, so this only guards against the
        # reasons quietly outnumbering the tests.
        self.assertLess(len(skipped), len(_LOADERS))

    def test_apply_returns_the_outbound_policy_its_callers_expect(self):
        policy = process_config.apply({"http_retry": {"timeout_seconds": 7}})
        self.assertEqual(policy["timeout"], 7.0)

class TestTheGuiCannotSaveAZeroLockWait(unittest.TestCase):
    """The wait is a config key, so it is editable in the GUI, so it is one of
    the fields the GUI must refuse at zero — the Y8 fault, which had to be
    fixed for the nine fields that existed then. A tenth that nobody added to
    the set would save a 0 that the loader refuses and reports to a log the
    operator never reads (P2/P5)."""

    def test_the_wait_is_one_of_the_fields_refused_at_zero(self):
        self.assertIn(db_connect.LOCK_TIMEOUT_SOURCE,
                      config_tab_models.positive_only_fields())

    def test_a_typed_zero_is_refused_and_the_loaded_value_kept(self):
        section, field = db_connect.LOCK_TIMEOUT_SOURCE
        for typed in ("0", "-1"):
            with self.subTest(typed=typed):
                data, errors = config_tab_models.merge_settings_edits(
                    {section: {field: 5.0}},
                    {section: {field: (typed, "float")}})
                self.assertTrue([e for e in errors
                                 if e.startswith(f"{section}.{field}:")
                                 and "greater than zero" in e], errors)
                self.assertEqual(data[section][field], 5.0)

    def test_a_positive_wait_still_saves(self):
        section, field = db_connect.LOCK_TIMEOUT_SOURCE
        data, errors = config_tab_models.merge_settings_edits(
            {section: {field: 5.0}}, {section: {field: ("20", "float")}})
        self.assertEqual((data[section][field], errors), (20.0, []))


class TestTheReportReadsTheConfigOnce(unittest.TestCase):
    """`_report_number` reaches `_load_config` on the per-keyword narrative
    path, so applying the policies there re-parsed the file and re-emitted
    every config warning once per keyword — one typo producing N identical
    lines, with the reader unable to tell one problem from N (P2/P25, cold
    review of chunk Y11)."""

    def _report_with_config(self, text):
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, "config.yml"), "w",
                  encoding="utf-8") as handle:
            handle.write(text)
        generate_insight_report._CONFIG_CACHE.clear()
        return directory

    def test_the_file_is_parsed_once_however_often_it_is_asked_for(self):
        directory = self._report_with_config("database:\n  lock_timeout_seconds: 9\n")
        with mock.patch.object(generate_insight_report, "_REPO_ROOT", directory):
            with mock.patch.object(generate_insight_report.yaml, "safe_load",
                                   wraps=generate_insight_report.yaml.safe_load) as parsed:
                for _ in range(5):
                    generate_insight_report._load_config()
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(db_connect.lock_timeout(), 9.0)

    def test_an_unreadable_config_is_reported_not_silently_defaulted(self):
        """The branch degraded to every default — thresholds, retry budget and
        lock wait — and said nothing anywhere (P2)."""
        directory = self._report_with_config("database: [unclosed\n")
        with mock.patch.object(generate_insight_report, "_REPO_ROOT", directory):
            with self.assertLogs(level=logging.ERROR) as logged:
                self.assertEqual(generate_insight_report._load_config(), {})
        self.assertIn("config.yml", "\n".join(logged.output))
        self.assertEqual(db_connect.lock_timeout(),
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)

    def tearDown(self):
        generate_insight_report._CONFIG_CACHE.clear()


class TestEveryFieldRefusedAtZeroComesFromItsOwnLoader(unittest.TestCase):
    """The set is derived, but it was extended by hand in this chunk, and the
    hand-extension is how `report_llm`'s three stayed out of it: its wait is
    read by the same `timeouts.seconds_from_config` rule and its token limits
    by `_token_limit`, and the GUI saved a typed 0 for all three after chunk
    Y8 had fixed the other nine (P5/P32, cold review of chunk Y11)."""

    def test_the_briefs_wait_and_token_limits_are_refused_at_zero(self):
        for field in ("timeout_seconds", "main_max_tokens",
                      "advisory_max_tokens"):
            with self.subTest(field=field):
                self.assertIn(("report_llm", field),
                              config_tab_models.positive_only_fields())
                data, errors = config_tab_models.merge_settings_edits(
                    {"report_llm": {field: 600}},
                    {"report_llm": {field: ("0", "float")}})
                self.assertTrue([e for e in errors
                                 if e.startswith(f"report_llm.{field}:")],
                                errors)
                self.assertEqual(data["report_llm"][field], 600)

    def test_each_loader_names_the_keys_it_refuses(self):
        """Read off the loaders, not appended at the reader: a key refused by
        `report_llm` is named in `report_llm`."""
        self.assertTrue(set(report_llm.GOVERNED_FIELDS)
                        <= config_tab_models.positive_only_fields())


class TestTheShippedConfigCarriesTheKey(unittest.TestCase):

    def test_config_yml_has_the_block_and_the_documented_default(self):
        """A setting nobody can find is not configurable (P4). The shipped
        value is sqlite3's own default, so adding the block changed no
        behaviour."""
        with open(os.path.join(REPO_ROOT, "config.yml"), encoding="utf-8") as f:
            shipped = yaml.safe_load(f)
        section, field = db_connect.LOCK_TIMEOUT_SOURCE
        self.assertEqual(shipped[section][field],
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
