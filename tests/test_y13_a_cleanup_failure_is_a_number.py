"""Chunk Y13 — a cleanup failure is a number, not a line on stderr.

Chunk Y11 made a failing `rollback()` or `close()` unable to replace the
exception that caused it: `db_connect._safely` logs it and carries on. The
second fact then went nowhere a reader looks — `logger.exception` writes to
stderr, and a `close()` that fails inside the audit's per-domain loop fails
every time, each one holding a file handle open, with nothing saying "this
happened N times".

Spec: docs/review_2026-11-04/PLAN_Y13_a_cleanup_failure_is_a_number.md
"""

import ast
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import db_connect
import validate_xlsx_vs_json


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _CleanupFails:
    """A connection proxy whose `rollback` or `close` raises.

    `sqlite3.Connection` is a C type with read-only attributes, so a failing
    cleanup cannot be patched onto a real one (the same proxy chunk Y11 uses).
    """

    def __init__(self, conn, failing):
        self._conn = conn
        self._failing = failing
        _OPENED.append(self)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def rollback(self):
        if self._failing == "rollback":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.rollback()

    def close(self):
        if self._failing == "close":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.close()

    def really_close(self):
        self._conn.close()


#: Every proxy this module builds, so a test whose `close()` is rigged to
#: fail can still release the real handle afterwards (the cold review of this
#: chunk: the test about leaked handles leaked three of them).
_OPENED = []


def _connecting_with_failing_cleanup(failing):
    real = sqlite3.connect

    def connect(*args, **kwargs):
        return _CleanupFails(real(*args, **kwargs), failing)
    return mock.patch.object(db_connect.sqlite3, "connect",
                             side_effect=connect)


class _TallyIsolation(unittest.TestCase):
    """The tally is per-process state: a test must not leak it to the next."""

    def setUp(self):
        self._before = db_connect.cleanup_failures()
        db_connect.reset_cleanup_failures()
        _OPENED.clear()

    def tearDown(self):
        db_connect.reset_cleanup_failures()
        db_connect._CLEANUP_FAILURES.update(self._before)
        for proxy in _OPENED:
            try:
                proxy.really_close()
            except Exception:
                pass
        _OPENED.clear()

    def _db(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return os.path.join(directory, "t.db")


class TestAFailedCleanupIsCounted(_TallyIsolation):

    def test_a_failing_close_is_counted_every_time_it_fails(self):
        """The audit opens and closes a connection per domain. Three failed
        closes are three leaked handles, and before Y13 they were three log
        lines nobody could count."""
        db_path = self._db()
        with _connecting_with_failing_cleanup("close"):
            for _ in range(3):
                with db_connect.connection(db_path) as conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS t (a)")
        self.assertEqual(db_connect.cleanup_failure_count(), 3)
        self.assertEqual(db_connect.cleanup_failures(),
                         {("close", db_path): 3})

    def test_a_failing_rollback_is_counted_as_its_own_step(self):
        """Rolling back and closing are two steps; one failing says something
        different about the database than the other."""
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback"):
            with self.assertRaises(ValueError):
                with db_connect.connection(db_path) as conn:
                    conn.execute("CREATE TABLE t (a)")
                    raise ValueError("the caller's own failure")
        self.assertEqual(db_connect.cleanup_failures(),
                         {("roll back", db_path): 1})

    def test_a_clean_run_counts_nothing(self):
        db_path = self._db()
        with db_connect.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (a)")
        self.assertEqual(db_connect.cleanup_failure_count(), 0)

    def test_the_tally_can_be_reset_for_the_next_step(self):
        """The audit reports what its own run could not do, not what an
        earlier run in the same process could not (P6)."""
        db_connect._CLEANUP_FAILURES[("close", "/x.db")] = 4
        db_connect.reset_cleanup_failures()
        self.assertEqual(db_connect.cleanup_failure_count(), 0)


class TestTheTallyBecomesASentenceAReaderCanAct_On(_TallyIsolation):

    def test_no_failures_means_no_warning_at_all(self):
        """A clean run must not add an empty row to the workbook."""
        self.assertIsNone(db_connect.cleanup_failure_warning())

    def test_the_warning_carries_the_count_and_the_step(self):
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 3
        db_connect._CLEANUP_FAILURES[("roll back", "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("4 database cleanup step(s) failed", text)
        self.assertIn("3 x close", text)
        self.assertIn("1 x roll back", text)

    def test_the_same_step_on_two_databases_is_one_number(self):
        """"3 x close" is the actionable fact: one database failing three
        times and three failing once each are the same leaked handles."""
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 1
        db_connect._CLEANUP_FAILURES[("close", "/b.db")] = 2
        text = db_connect.cleanup_failure_warning()
        self.assertIn("3 x close", text)

    def test_a_failed_close_says_the_runs_figures_still_stand(self):
        """The whole point of chunk Y11: a close fails after the commit, so
        the data is durable. An operator reading the row has to be told that,
        or they discard a good run."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("writes were committed and its figures stand", text)
        self.assertNotIn("abandoned its transaction", text)

    def test_a_failed_rollback_does_not_claim_the_figures_stand(self):
        """A counted rollback means a block raised and its transaction was
        abandoned. The first version of the sentence told that reader their
        figures stood, which is the opposite of what happened (P6)."""
        db_connect._CLEANUP_FAILURES[(db_connect.ROLL_BACK, "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("abandoned its transaction", text)
        self.assertNotIn("writes were committed and its figures stand", text)

    def test_more_than_one_database_is_named(self):
        """The reader's next action is to check a file, and since chunk Y12
        the path is configurable — so "3 x close" alone does not say which."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/b.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("/a.db", text)
        self.assertIn("/b.db", text)

    def test_one_database_is_not_named_twice_over(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 2
        self.assertNotIn("/a.db", db_connect.cleanup_failure_warning())


class TestTheWordsAreEditorial(_TallyIsolation):
    """The wording lives in `serp_vocab.yml`, like `fetch_status` beside it."""

    def test_the_vocabulary_file_supplies_the_sentence(self):
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 2
        vocab = {"db_cleanup": {"warning": "edited: {failures} ({detail})",
                                "detail_item": "{what} {count}"}}
        with mock.patch.dict("pattern_matching.SERP_VOCAB", vocab,
                             clear=False):
            self.assertEqual(db_connect.cleanup_failure_warning(),
                             "edited: 2 (close 2)")

    def test_serp_vocab_yml_declares_the_block(self):
        import pattern_matching
        block = pattern_matching.SERP_VOCAB.get("db_cleanup")
        self.assertIsInstance(block, dict)
        for key in db_connect._CLEANUP_DEFAULTS:
            self.assertIn(key, block)

    def test_the_python_fallback_is_the_files_own_text(self):
        """The fallback exists for a vocabulary file that cannot be read, and
        the first version of it stopped at "its figures stand" — so in the one
        situation it is for, the operator got the sentence without the
        diagnosis (P32, the cold review of this chunk)."""
        import pattern_matching
        block = pattern_matching.SERP_VOCAB["db_cleanup"]
        for key, text in db_connect._CLEANUP_DEFAULTS.items():
            self.assertEqual(text, block[key], key)

    def test_a_broken_template_still_produces_a_sentence(self):
        """A vocabulary edit that drops a placeholder must not abort a run
        whose data is fine — the same contract `enrichment.status_text` has."""
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 2
        vocab = {"db_cleanup": {"warning": "{not_a_field}",
                                "detail_item": "{also_not}"}}
        with mock.patch.dict("pattern_matching.SERP_VOCAB", vocab,
                             clear=False):
            text = db_connect.cleanup_failure_warning()
        self.assertIn("2 database cleanup step(s) failed", text)
        self.assertIn("2 x close", text)

    def test_a_missing_vocabulary_file_still_produces_a_sentence(self):
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 1
        with mock.patch.dict("sys.modules", {"pattern_matching": None}):
            self.assertIn("1 database cleanup step(s) failed",
                          db_connect.cleanup_failure_warning())


def _audit_function(name):
    """One top-level function of `serp_audit.py` as a syntax tree."""
    path = os.path.join(_REPO_ROOT, "serp_audit.py")
    for node in ast.walk(ast.parse(io.open(path, encoding="utf-8").read())):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"serp_audit.{name} not found")


class TestTheRowTheWorkbookGets(_TallyIsolation):
    """The row's shape lives beside the tally, so the workbook contract can be
    checked without running the audit."""

    def test_a_clean_run_builds_no_row(self):
        self.assertIsNone(db_connect.cleanup_warning_row("R1"))

    def test_the_row_carries_every_column_validation_requires(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        row = db_connect.cleanup_warning_row("R1")
        spec = [x for x in validate_xlsx_vs_json.SPECS
                if x.sheet_name == "Parsing_Warnings"][0]
        missing = set(spec.required_cols) - set(row)
        self.assertFalse(missing, f"the row would fail validation: {missing}")
        self.assertEqual(row["Run_ID"], "R1")
        self.assertIn("1 x close", row["Message"])

    def test_the_row_is_one_line(self):
        """`validate_xlsx_vs_json` compares the JSON and the sheet cell by
        cell after collapsing whitespace, and a folded YAML scalar is one
        line; a template with a newline in it would still read as a block."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        self.assertNotIn("\n", db_connect.cleanup_warning_row("R1")["Message"])


class TestAFailureAfterTheOutputIsStated(_TallyIsolation):
    """The workbook cannot be amended once it is on disk, and the run keeps
    writing to the database after it — the report's trend reads and the write
    that marks the run complete both come later (the cold review of this
    chunk)."""

    def test_nothing_further_means_nothing_said(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 2
        self.assertIsNone(db_connect.cleanup_failures_after(2))

    def test_a_later_failure_says_the_output_does_not_carry_it(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 5
        text = db_connect.cleanup_failures_after(2)
        self.assertIn("3 further database cleanup step(s) failed", text)
        self.assertIn("only the 2", text)

    def test_the_reporter_says_both_and_only_once(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 5
        said = []
        db_connect.report_cleanup_failures(printer=said.append, counted=2)
        self.assertEqual(len(said), 2)
        self.assertIn("5 database cleanup step(s) failed", said[0])
        self.assertIn("3 further", said[1])

    def test_the_exit_hook_does_not_repeat_what_was_reported(self):
        """The audit prints the tally itself. The exit hook is the floor for
        the steps that do not, so it must stay quiet when one already has."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        db_connect.report_cleanup_failures(printer=lambda line: None)
        again = []
        with mock.patch.object(db_connect, "report_cleanup_failures",
                               side_effect=lambda **kw: again.append(1)):
            db_connect._report_cleanup_failures_at_exit()
        self.assertEqual(again, [], "the tally was reported twice")

    def test_a_step_that_writes_no_artefact_still_says_it_at_exit(self):
        """Fifteen modules open the database through `db_connect` and only the
        audit renders the sentence into an artefact; the rest had nothing but
        the log (P5, the cold review of this chunk)."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        said = []
        with mock.patch.object(db_connect, "report_cleanup_failures",
                               side_effect=lambda **kw: said.append(1)):
            db_connect._report_cleanup_failures_at_exit()
        self.assertEqual(said, [1])

    def test_the_exit_hook_is_registered_at_import(self):
        """P29 — the test above calls the hook directly, which does not prove
        it runs in production. `atexit`'s registry is not readable, so this
        asserts the module-level registration itself."""
        tree = ast.parse(io.open(os.path.join(_REPO_ROOT, "db_connect.py"),
                                 encoding="utf-8").read())
        registered = [n for n in tree.body
                      if isinstance(n, ast.Expr)
                      and isinstance(n.value, ast.Call)
                      and isinstance(n.value.func, ast.Attribute)
                      and n.value.func.attr == "register"
                      and n.value.args
                      and isinstance(n.value.args[0], ast.Name)
                      and n.value.args[0].id
                      == "_report_cleanup_failures_at_exit"]
        self.assertEqual(len(registered), 1)


class TestTheAuditWiresItUp(unittest.TestCase):
    """`serp_audit._run` fetches live SERPs, so what it does with the tally is
    checked structurally: each assertion is anchored on a real call node, not
    on a name appearing anywhere in the tree."""

    def setUp(self):
        self.main = _audit_function("main")
        self.run = _audit_function("_run")

    @staticmethod
    def _calls(tree, attr):
        return [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "db_connect"]

    def test_the_audit_appends_the_row_to_parsing_warnings(self):
        self.assertTrue(self._calls(self.run, "cleanup_warning_row"),
                        "the audit never asks for the tally's row")
        appends = [n for n in ast.walk(self.run)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "append"
                   and isinstance(n.func.value, ast.Name)
                   and n.func.value.id == "all_parsing_warnings"]
        # P29 — the walk found the appends it is about.
        self.assertTrue(appends, "no parsing_warnings row is built at all")
        names = {ast.dump(n.args[0]) for n in appends if n.args}
        self.assertTrue(any("cleanup_row" in n for n in names),
                        "the cleanup row is never appended")

    def test_the_audit_resets_the_tally_where_the_run_begins(self):
        self.assertTrue(self._calls(self.main, "reset_cleanup_failures"),
                        "a previous run's failures would be reported as this "
                        "run's")

    def test_the_audit_reports_what_arrived_after_the_output(self):
        calls = self._calls(self.run, "report_cleanup_failures")
        self.assertTrue(calls, "the audit never reports the final tally")
        counted = [k for call in calls for k in call.keywords
                   if k.arg == "counted"]
        self.assertTrue(counted,
                        "the audit reports the tally without saying how much "
                        "of it the output already carried")
        # A literal `None` there is the same silence with the argument
        # present, so the value has to be the count the row carried.
        self.assertTrue(
            all(isinstance(k.value, ast.Name) for k in counted),
            "the final report is passed a constant instead of the count the "
            "output carried")


if __name__ == "__main__":
    unittest.main()
