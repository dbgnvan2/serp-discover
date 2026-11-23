"""metrics.py: rank history is taken only from completed runs and primary queries.

The fixtures build their database through ``storage.SerpStorage`` rather than
hand-written DDL. The hand-written copy had drifted from the real schema, so a
column added in production was missing here and the tests passed against a
table shape no run ever writes.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk D1
(finding D-C-22).
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import db_connect
import metrics
from storage import SerpStorage


SHARED_URL = "https://example.com/shared"


def _store(db_path):
    """A real, migrated database — the same code path a run uses."""
    return SerpStorage(db_path=db_path)


def _run(store, run_id, run_date, completed=True):
    store.save_run(run_id, "x")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE runs SET run_date = ? WHERE run_id = ?",
                     (run_date, run_id))
    if completed:
        store.mark_run_completed(run_id, completed_at=run_date)


def _result(store, run_id, keyword, rank, url=SHARED_URL, label="A"):
    store.save_serp_result(run_id, keyword, "organic", rank, "", url,
                           "example.com", "", query_label=label, sent_query=None)


class TestRankDeltas(unittest.TestCase):

    def _seed(self, db_path):
        store = _store(db_path)
        _run(store, "run_prev", "2026-02-01T00:00:00")
        _run(store, "run_curr", "2026-02-02T00:00:00")
        # Same URL appears for two keywords; deltas are tracked separately.
        _result(store, "run_prev", "kw_a", 9)
        _result(store, "run_curr", "kw_a", 4)   # +5
        _result(store, "run_prev", "kw_b", 2)
        _result(store, "run_curr", "kw_b", 6)   # -4
        return store

    def test_keys_by_keyword_and_url(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            self._seed(db_path)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")
        self.assertEqual(deltas[("kw_a", SHARED_URL)], 5)
        self.assertEqual(deltas[("kw_b", SHARED_URL)], -4)
        self.assertEqual(len(deltas), 2)

    def test_alternative_query_rows_do_not_cross_product(self):
        """An A.1 row for the same keyword+URL must not multiply the merge."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = self._seed(db_path)
            # Alternative-query rows are stored under the root keyword.
            _result(store, "run_prev", "kw_a", 1, label="A.1")
            _result(store, "run_curr", "kw_a", 2, label="A.1")
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")
        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[("kw_a", SHARED_URL)], 5)

    def test_pivot_rows_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = self._seed(db_path)
            _result(store, "run_prev", "kw_a", 1, url="https://p.example/x",
                    label="P")
            _result(store, "run_curr", "kw_a", 1, url="https://p.example/x",
                    label="P")
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")
        self.assertNotIn(("kw_a", "https://p.example/x"), deltas)

    def test_an_aborted_run_is_not_the_baseline(self):
        """The baseline is the previous *completed* run, not the previous one."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = self._seed(db_path)
            # An aborted run between the two: one keyword, then nothing.
            _run(store, "run_aborted", "2026-02-01T12:00:00", completed=False)
            _result(store, "run_aborted", "kw_a", 1)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")
        # Against run_prev (rank 9) the delta is +5; against the aborted run
        # (rank 1) it would be -3.
        self.assertEqual(deltas[("kw_a", SHARED_URL)], 5)

    def test_an_empty_result_says_why(self):
        """P2: `{}` meant no runs, no baseline, or no label-A rows alike.

        serp_audit printed "No historical data for rank comparison yet" over a
        database holding thousands of rows whose runs were simply not
        comparable.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_prev", "2026-02-01T00:00:00")
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_prev", "kw", 9, label=None)
            _result(store, "run_curr", "kw", 4, label=None)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas, reason = metrics.get_rank_deltas(
                    "run_curr", with_reason=True)
        self.assertEqual(deltas, {})
        self.assertIn("query_label", reason)

    def test_no_completed_prior_run_yields_no_deltas(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_prev", "2026-02-01T00:00:00", completed=False)
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_prev", "kw_a", 9)
            _result(store, "run_curr", "kw_a", 4)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")
        self.assertEqual(deltas, {})


class TestVolatility(unittest.TestCase):

    def test_warns_on_keyword_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_prev", "2026-02-01T00:00:00")
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_prev", "kw_old", 1, url="https://example.com/a")
            _result(store, "run_curr", "kw_new", 1, url="https://example.com/a")
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                result = metrics.get_volatility_metrics("run_curr")
        # The two runs share a URL but not a keyword, so the merge is empty.
        # This used to be status "success" with a NaN score, and report
        # section 6 printed its heading and nothing else (review chunk Y3).
        self.assertEqual(result["status"], "no_shared_urls")
        self.assertIn("non-identical keyword sets", result["comparability_warning"])

    def test_aborted_prior_run_reports_how_many_were_skipped(self):
        """P2: say what was excluded, do not just report 'no history'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_a", "2026-02-01T00:00:00", completed=False)
            _run(store, "run_b", "2026-02-01T12:00:00", completed=False)
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_a", "kw", 1)
            _result(store, "run_curr", "kw", 2)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                result = metrics.get_volatility_metrics("run_curr")
        self.assertEqual(result["status"], "insufficient_history")
        self.assertIn("2 earlier", result["msg"])

    def test_unlabelled_legacy_rows_are_reported_not_compared(self):
        """Rows written before the query_label migration carry NULL."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_prev", "2026-02-01T00:00:00")
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_prev", "kw", 9, label=None)
            _result(store, "run_curr", "kw", 4, label=None)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                result = metrics.get_volatility_metrics("run_curr")
        self.assertEqual(result["status"], "empty_data")
        self.assertIn("query_label", result["msg"])


class TestSkipCountMatchesTheMessage(unittest.TestCase):
    """The number reported must be the number actually passed over.

    `skipped` counted every earlier incomplete run, but the message calls them
    "more recent run(s) skipped". On this client's database (54 pre-migration
    runs, all with completed_at NULL) the first comparable pair would have
    logged "54 more recent run(s) skipped" with nothing in that window.
    """

    def test_runs_older_than_the_baseline_are_not_counted_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "old_1", "2026-01-01T00:00:00", completed=False)
            _run(store, "old_2", "2026-01-02T00:00:00", completed=False)
            _run(store, "baseline", "2026-02-01T00:00:00")
            _run(store, "between", "2026-02-01T12:00:00", completed=False)
            _run(store, "run_curr", "2026-02-02T00:00:00")
            import pandas as pd
            with sqlite3.connect(db_path) as conn:
                runs_df = pd.read_sql(metrics._RUNS_SQL, conn)
        prev_id, skipped = metrics._previous_completed_run(
            runs_df, "2026-02-02T00:00:00")
        self.assertEqual(prev_id, "baseline")
        self.assertEqual(skipped, 1)   # "between" only, not old_1/old_2

    def test_with_no_baseline_every_earlier_run_is_counted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "old_1", "2026-01-01T00:00:00", completed=False)
            _run(store, "old_2", "2026-01-02T00:00:00", completed=False)
            _run(store, "run_curr", "2026-02-02T00:00:00")
            import pandas as pd
            with sqlite3.connect(db_path) as conn:
                runs_df = pd.read_sql(metrics._RUNS_SQL, conn)
        prev_id, skipped = metrics._previous_completed_run(
            runs_df, "2026-02-02T00:00:00")
        self.assertIsNone(prev_id)
        self.assertEqual(skipped, 2)


class TestEntityDominanceSaysWhyItIsEmpty(unittest.TestCase):
    """A bare `{}` made report section 5 vanish with no note."""

    def test_unlabelled_rows_report_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            _run(store, "run_curr", "2026-02-02T00:00:00")
            _result(store, "run_curr", "kw", 4, label=None)
            with patch.object(db_connect, "DATABASE_PATH", db_path):
                result = metrics.get_entity_dominance("run_curr")
        self.assertEqual(result["status"], "empty_data")
        self.assertIn("query_label", result["msg"])
        self.assertNotIn("entity_dominance", result)


class TestCompletionStampSurvivesASecondSaveRun(unittest.TestCase):
    """`save_run` is called once per keyword, so the upsert must not reset it.

    `INSERT OR REPLACE` deletes the row and re-inserts it, wiping
    `completed_at` — and every test in this file passed against that, because
    none of them saved the same run twice.
    """

    def test_resaving_a_run_keeps_completed_at(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            store = _store(db_path)
            store.save_run("run_x", "params")
            store.mark_run_completed("run_x", completed_at="2026-02-02T00:00:00")
            store.save_run("run_x", "params")      # the next keyword
            with sqlite3.connect(db_path) as conn:
                stamp = conn.execute(
                    "SELECT completed_at FROM runs WHERE run_id = ?",
                    ("run_x",)).fetchone()[0]
        self.assertEqual(stamp, "2026-02-02T00:00:00")


class TestFixtureSchemaMatchesProduction(unittest.TestCase):
    """The fixtures must keep using the real schema, not a copy of it."""

    def test_runs_and_serp_results_carry_the_review_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            _store(db_path)
            with sqlite3.connect(db_path) as conn:
                runs_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
                serp_cols = {r[1] for r in
                             conn.execute("PRAGMA table_info(serp_results)")}
        self.assertIn("completed_at", runs_cols)
        self.assertIn("query_label", serp_cols)


if __name__ == "__main__":
    unittest.main()
