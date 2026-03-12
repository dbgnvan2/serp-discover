import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import metrics


class TestMetrics(unittest.TestCase):
    def _seed_db(self, db_path):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE runs (run_id TEXT PRIMARY KEY, run_date TEXT, params_hash TEXT)"
            )
            conn.execute(
                """
                CREATE TABLE serp_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    keyword_text TEXT,
                    result_type TEXT,
                    rank INTEGER,
                    title TEXT,
                    url TEXT,
                    domain TEXT,
                    snippet TEXT,
                    features_json TEXT
                )
                """
            )

            conn.execute(
                "INSERT INTO runs (run_id, run_date, params_hash) VALUES (?, ?, ?)",
                ("run_prev", "2026-02-01T00:00:00", "x"),
            )
            conn.execute(
                "INSERT INTO runs (run_id, run_date, params_hash) VALUES (?, ?, ?)",
                ("run_curr", "2026-02-02T00:00:00", "x"),
            )

            # Same URL appears for two keywords; deltas should be tracked separately.
            shared_url = "https://example.com/shared"
            rows = [
                ("run_prev", "kw_a", "organic", 9, shared_url),
                ("run_curr", "kw_a", "organic", 4, shared_url),  # +5
                ("run_prev", "kw_b", "organic", 2, shared_url),
                ("run_curr", "kw_b", "organic", 6, shared_url),  # -4
            ]
            for run_id, keyword_text, result_type, rank, url in rows:
                conn.execute(
                    """
                    INSERT INTO serp_results
                    (run_id, keyword_text, result_type, rank, title, url, domain, snippet, features_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, keyword_text, result_type, rank, "", url, "example.com", "", "{}"),
                )

    def test_get_rank_deltas_keys_by_keyword_and_url(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            self._seed_db(db_path)

            with patch.object(metrics, "DB_PATH", db_path):
                deltas = metrics.get_rank_deltas("run_curr")

        self.assertEqual(deltas[("kw_a", "https://example.com/shared")], 5)
        self.assertEqual(deltas[("kw_b", "https://example.com/shared")], -4)
        self.assertEqual(len(deltas), 2)

    def test_get_volatility_metrics_warns_on_keyword_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "CREATE TABLE runs (run_id TEXT PRIMARY KEY, run_date TEXT, params_hash TEXT)"
                )
                conn.execute(
                    """
                    CREATE TABLE serp_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT,
                        keyword_text TEXT,
                        result_type TEXT,
                        rank INTEGER,
                        title TEXT,
                        url TEXT,
                        domain TEXT,
                        snippet TEXT,
                        features_json TEXT
                    )
                    """
                )
                conn.execute("INSERT INTO runs VALUES ('run_prev', '2026-02-01T00:00:00', 'x')")
                conn.execute("INSERT INTO runs VALUES ('run_curr', '2026-02-02T00:00:00', 'x')")
                rows = [
                    ("run_prev", "kw_old", 1, "https://example.com/a"),
                    ("run_curr", "kw_new", 1, "https://example.com/a"),
                ]
                for run_id, keyword_text, rank, url in rows:
                    conn.execute(
                        """
                        INSERT INTO serp_results
                        (run_id, keyword_text, result_type, rank, title, url, domain, snippet, features_json)
                        VALUES (?, ?, 'organic', ?, '', ?, 'example.com', '', '{}')
                        """,
                        (run_id, keyword_text, rank, url),
                    )
            with patch.object(metrics, "DB_PATH", db_path):
                result = metrics.get_volatility_metrics("run_curr")
        self.assertEqual(result["status"], "success")
        self.assertIn("non-identical keyword sets", result["comparability_warning"])


if __name__ == "__main__":
    unittest.main()
