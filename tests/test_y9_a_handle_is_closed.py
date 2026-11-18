"""Review chunk Y9 — a committed write is not a closed handle.

`with sqlite3.connect(path) as conn:` commits and rolls back but never
closes; `with closing(sqlite3.connect(path))` closes but discards the commit.
`db_connect.connection` does both, and no production module opens a
connection any other way.

Spec: docs/review_2026-11-04/PLAN_Y9_a_handle_is_closed.md
"""

import ast
import os
import pathlib
import sqlite3
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_connect  # noqa: E402

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Everything that is not a test, a vendored dependency or a one-off probe.
_EXCLUDED_DIRS = {"venv", "tests", "docs", "output", "raw", "__pycache__",
                  "scratchpad"}


def _production_modules():
    """Every tracked production module in **this** worktree.

    Driven by `git ls-files`, not `rglob`: a `.claude/worktrees/<name>` holding
    a pre-Y9 branch would otherwise be walked, and the guard would report
    offenders in code that is not in the tree under review (cold review of
    chunk Y9, finding 4).
    """
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=_REPO_ROOT,
                             capture_output=True, text=True, check=True)
    # ...and the new modules of the chunk being worked on, which are not
    # tracked yet. `--exclude-standard` keeps .gitignore'd output out.
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
    for line in sorted(set(tracked.stdout.splitlines())
                       | set(untracked.stdout.splitlines())):
        rel = pathlib.Path(line)
        if set(rel.parts) & _EXCLUDED_DIRS or rel.parts[0].startswith("."):
            continue
        if rel.name.startswith("test_"):
            continue
        yield rel, _REPO_ROOT / rel


def _modules_opening_the_database():
    """The modules that actually open the database, read off their source.

    The expectation is derived rather than floored: a module that drops out of
    the walk is caught by comparing the two sets, not by a count (P29, same
    review, finding 3).
    """
    found = set()
    for rel, path in _production_modules():
        if "db_connect.connection" in path.read_text(encoding="utf-8"):
            found.add(rel.name)
    return found


class TestTheConnectionIsCommittedAndClosed(unittest.TestCase):
    """Criterion 1 — both halves, which neither stock form gives."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.addCleanup(os.unlink, self.tmp.name)
        with db_connect.connection(self.tmp.name) as conn:
            conn.execute("CREATE TABLE t (v TEXT)")

    def _rows(self):
        with db_connect.connection(self.tmp.name) as conn:
            return conn.execute("SELECT v FROM t").fetchall()

    def test_a_write_inside_the_block_is_committed(self):
        """`closing(sqlite3.connect(...))` alone would roll this back."""
        with db_connect.connection(self.tmp.name) as conn:
            conn.execute("INSERT INTO t VALUES ('kept')")
        self.assertEqual(self._rows(), [("kept",)])

    def test_the_handle_is_closed_on_the_way_out(self):
        with db_connect.connection(self.tmp.name) as conn:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_an_exception_rolls_the_write_back_and_still_closes(self):
        class _Boom(Exception):
            pass

        with self.assertRaises(_Boom):
            with db_connect.connection(self.tmp.name) as conn:
                conn.execute("INSERT INTO t VALUES ('lost')")
                raise _Boom()
        self.assertEqual(self._rows(), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_keyword_arguments_reach_sqlite3_connect(self):
        with db_connect.connection(self.tmp.name, timeout=1.5) as conn:
            self.assertEqual(conn.execute("SELECT 1").fetchone(), (1,))


class TestNoProductionModuleLeavesAHandleOpen(unittest.TestCase):
    """Criterion 2 — the repo, not the two files chunk Y6 could reach.

    This replaces `test_y6_the_pipeline_agrees_with_the_run.py`'s
    `TestTheTwoHistoryReadersCloseTheirHandles`, whose own docstring recorded
    that it was scoped to two files because converting the other ~50 sites was
    a sweeping diff. Chunk Y9 is that diff.
    """

    def test_the_walk_sees_every_module_that_opens_the_database(self):
        """A guard that walks nothing passes (P21), and a floor two times
        below the real figure would not notice half the repo falling out of
        the walk (P29, cold review of chunk Y9, finding 3). So the
        expectation is derived: every module that contains a
        `db_connect.connection` call must be one the walk reached."""
        names = {rel.name for rel, _ in _production_modules()}
        opening = _modules_opening_the_database()
        self.assertGreaterEqual(len(opening), 20, sorted(opening))
        self.assertTrue(opening <= names, sorted(opening - names))
        self.assertIn("db_connect.py", names)
        self.assertIn("storage.py", opening)

    @staticmethod
    def _connect_calls(tree):
        """Every call that opens a SQLite connection, however it is spelled.

        `sqlite3.connect(...)`, `db.connect(...)` after `import sqlite3 as
        db`, and a bare `connect(...)` after `from sqlite3 import connect` are
        the same call; matching only the first spelling left two ways to
        reintroduce the leak past the guard (cold review of chunk Y9,
        finding 5).
        """
        aliases = {"sqlite3"}
        bare = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "sqlite3":
                        aliases.add(a.asname or a.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                for a in node.names:
                    if a.name == "connect":
                        bare.add(a.asname or a.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "connect"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in aliases):
                yield node
            elif isinstance(func, ast.Name) and func.id in bare:
                yield node

    def test_no_module_opens_a_connection_in_a_with(self):
        offenders = []
        for rel, path in _production_modules():
            if rel.name == "db_connect.py":
                continue        # the one place the pairing is written
            tree = ast.parse(path.read_text(encoding="utf-8"))
            opened = {id(call) for call in self._connect_calls(tree)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.With):
                    continue
                for item in node.items:
                    if id(item.context_expr) in opened:
                        offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], (
            "these open a connection in a `with` that commits but never "
            "closes the handle — use db_connect.connection: "
            + ", ".join(offenders)))

    def test_every_module_that_opens_the_database_uses_the_helper(self):
        """A connection opened outside the helper leaks, and the one form
        that closes it — `contextlib.closing` — discards the commit instead,
        so it is not excused either (cold review of chunk Y9, finding 2:
        `storage.migrated_connection` was the last site using it)."""
        offenders = []
        for rel, path in _production_modules():
            if rel.name == "db_connect.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in self._connect_calls(tree):
                offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], (
            "a connection opened outside db_connect.connection is left to "
            "the garbage collector, or closed without its commit: "
            + ", ".join(offenders)))


class TestARealCacheWriteStillLands(unittest.TestCase):
    """Criterion 3 — the conversion must not have silenced the caches.

    The commit is what `closing` alone would have dropped, so one real
    writer/reader pair is exercised rather than trusting the unit test on the
    helper (P6).
    """

    @unittest.skipUnless(os.path.isdir("/dev/fd"),
                         "no /dev/fd to count open handles on")
    def test_a_run_of_real_writes_and_reads_releases_every_handle(self):
        """The quantity the bug was about, at a real call site.

        Everything else here proves the helper's behaviour or the call sites'
        spelling. A guard on spelling cannot fail while the code is shaped
        right and leaking anyway — through a spelling the walk does not know,
        or a library that opens its own connection (P30, cold review of chunk
        Y9, finding 1). Measured on python 3.12: the pre-Y9 form leaks 46
        descriptors over these 50 iterations; the helper leaks none.
        """
        import tempfile

        import aivi

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "serp_data.db")
            aivi.save_aivi(db, "warm", "claude", {"axes": {}})
            before = len(os.listdir("/dev/fd"))
            for i in range(50):
                aivi.save_aivi(db, f"r{i}", "claude", {"axes": {}})
                aivi.get_aivi_trend(db, "claude")
            self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_a_written_row_survives_the_close(self):
        import tempfile

        import storage

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "serp_data.db")
            store = storage.SerpStorage(db)
            store.save_run("run1", "hash1")
            store.save_domain_features("example.ca", "counselling")
            with db_connect.connection(db) as conn:
                self.assertEqual(
                    conn.execute("SELECT run_id FROM runs").fetchall(),
                    [("run1",)])
                self.assertEqual(
                    conn.execute("SELECT entity_type FROM domain_features"
                                 ).fetchone()[0], "counselling")


if __name__ == "__main__":
    unittest.main()
