"""Review chunk Y5 — an error is not an absence, and one wait is not three.

Adjacent issues logged by earlier chunks' cold reviews (global rule 10):

- `storage.py` ran its three schema migrations inside
  `except sqlite3.OperationalError: pass`, so "duplicate column" (expected),
  "no such table" (the schema was never created) and "database is locked"
  (transient) all meant "migration done" (P1/P6).
- `metrics.get_volatility_metrics` closed its sqlite handle on some exits and
  not others, including the `except` path, so a run that could not be compared
  left a reader open and the next write met "database is locked".
- The citations table printed "—" in the Brand column for a cited domain the
  gazetteer does not know, which reads the same as "this citation has no
  brand". Nothing counted them, so an engine citing twenty untracked
  competitors looked like an engine citing nobody (P2/P9).
- The Y1 guard against hand-stripping the `www.` prefix was an
  `inspect.getsource` grep for two spellings, so a third spelling passed.
- Four clients each carried their own `REQUEST_TIMEOUT` Python constant, and
  three different waits — an API call, a ranked page, an LLM answer — were
  being served by the same number (P4/P25).

Spec: docs/review_2026-11-04/PLAN_Y5_an_error_is_not_an_absence.md
"""
import ast
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import citation_table
import http_retry
import storage
from timeouts import seconds_from_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAFailedMigrationIsNotAFinishedOne(unittest.TestCase):

    def test_a_missing_table_is_raised_not_counted_as_migrated(self):
        with sqlite3.connect(":memory:") as conn:
            cur = conn.cursor()
            with self.assertRaises(sqlite3.OperationalError) as caught:
                storage._add_missing_columns(
                    cur, "serp_results", [("x", "TEXT")])
        self.assertIn("does not exist", str(caught.exception))

    def test_an_already_migrated_table_is_a_no_op(self):
        with sqlite3.connect(":memory:") as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE t (a TEXT, b TEXT)")
            self.assertEqual(
                storage._add_missing_columns(cur, "t", [("b", "TEXT")]), [])
            self.assertEqual(
                storage._add_missing_columns(cur, "t", [("c", "INTEGER")]),
                ["c"])
            cols = {row[1] for row in
                    cur.execute("PRAGMA table_info(t)").fetchall()}
        self.assertEqual(cols, {"a", "b", "c"})

    def test_a_locked_database_is_raised_rather_than_skipped(self):
        """The failure that used to pass silently: the column is absent
        afterwards, and nothing said so."""
        with sqlite3.connect(":memory:") as conn:
            real = conn.cursor()
            real.execute("CREATE TABLE t (a TEXT)")

            class _Locked:
                def execute(self, sql, *args):
                    if sql.startswith("ALTER TABLE"):
                        raise sqlite3.OperationalError("database is locked")
                    return real.execute(sql, *args)

            with self.assertRaises(sqlite3.OperationalError) as caught:
                storage._add_missing_columns(_Locked(), "t", [("b", "TEXT")])
        self.assertIn("locked", str(caught.exception))

    def test_the_real_schema_migrates_and_is_idempotent(self):
        """The consequence, not the helper: a fresh database gets every
        migrated column, and opening it a second time changes nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            storage.SerpStorage(db_path=path)
            storage.SerpStorage(db_path=path)
            with sqlite3.connect(path) as conn:
                cols = {row[1] for row in conn.execute(
                    "PRAGMA table_info(keyword_feasibility)").fetchall()}
        # One column from each of the three migration sites that used to run
        # inside `except sqlite3.OperationalError: pass`.
        for col in ("entities_known", "da_provider", "min_non_directory_da"):
            self.assertIn(col, cols, col)


class TestEverySiblingMigrationRaisesToo(unittest.TestCase):
    """The same `except sqlite3.OperationalError: pass` lived in three more
    tables, each citing the storage.py convention this chunk repudiated, so
    fixing storage alone left three places where a locked table counted as a
    finished migration (P5, cold review of chunk Y5)."""

    TABLES = (
        ("probe_ai_visibility", "init_probe_table"),
        ("answer_sentiment", "init_sentiment_table"),
        ("foundational_score", "init_foundational_table"),
    )

    def test_a_failed_migration_is_raised_by_every_table(self):
        import importlib

        for module_name, func_name in self.TABLES:
            module = importlib.import_module(module_name)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "t.db")
                with mock.patch.object(
                        storage, "_add_missing_columns",
                        side_effect=sqlite3.OperationalError("locked")):
                    with self.assertRaises(sqlite3.OperationalError,
                                           msg=module_name):
                        getattr(module, func_name)(path)

    def test_every_table_still_migrates_and_is_idempotent(self):
        import importlib

        for module_name, func_name in self.TABLES:
            module = importlib.import_module(module_name)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "t.db")
                getattr(module, func_name)(path)
                getattr(module, func_name)(path)
                with sqlite3.connect(path) as conn:
                    tables = {row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(tables, module_name)


class TestTheHistoryReaderIsAlwaysClosed(unittest.TestCase):
    """A status is not an excuse to leak the handle: `empty_data`,
    `run_not_found`, `insufficient_history` and `query_failed` are the exits
    that used to return without a `close()`."""

    def _statuses_leak(self, rows_sql_error=False):
        import metrics

        opened = []

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            sqlite3.connect(path).close()
            real_connect = sqlite3.connect

            def _connect(*a, **kw):
                conn = real_connect(*a, **kw)
                opened.append(conn)
                return conn

            with mock.patch.object(metrics, "DB_PATH", path), \
                 mock.patch.object(metrics.sqlite3, "connect", _connect):
                if rows_sql_error:
                    with mock.patch.object(
                            metrics.pd, "read_sql",
                            side_effect=sqlite3.OperationalError("no table")):
                        result = metrics.get_volatility_metrics("r1")
                else:
                    result = metrics.get_volatility_metrics("r1")
        self.assertTrue(opened, "no connection was opened at all")
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
        return result

    def test_a_status_exit_closes_the_connection(self):
        result = self._statuses_leak()
        self.assertIn("status", result)
        self.assertNotEqual(result["status"], "success")

    def test_a_failed_query_closes_the_connection(self):
        result = self._statuses_leak(rows_sql_error=True)
        self.assertEqual(result["status"], "query_failed")

    def test_the_composition_reader_closes_on_its_failing_path(self):
        """The sibling of the same call: it closed after the read and not on
        the `except` return, so a failing dominance query held the handle for
        the life of the call (P5)."""
        import metrics

        opened = []

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            sqlite3.connect(path).close()
            real_connect = sqlite3.connect

            def _connect(*a, **kw):
                conn = real_connect(*a, **kw)
                opened.append(conn)
                return conn

            with mock.patch.object(metrics, "DB_PATH", path), \
                 mock.patch.object(metrics.sqlite3, "connect", _connect), \
                 mock.patch.object(
                     metrics.pd, "read_sql",
                     side_effect=sqlite3.OperationalError("no table")):
                result = metrics.get_entity_dominance("r1")
        self.assertEqual(result["status"], "error")
        self.assertTrue(opened)
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_the_schema_builder_closes_when_a_migration_raises(self):
        """`_init_db` closed by hand at the end, and a raising migration does
        not reach the end."""
        opened = []
        real_connect = sqlite3.connect

        def _connect(*a, **kw):
            conn = real_connect(*a, **kw)
            opened.append(conn)
            return conn

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            with mock.patch.object(storage.sqlite3, "connect", _connect), \
                 mock.patch.object(storage, "_add_missing_columns",
                                   side_effect=sqlite3.OperationalError(
                                       "database is locked")):
                with self.assertRaises(sqlite3.OperationalError):
                    storage.SerpStorage(db_path=path)
        self.assertTrue(opened)
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


class TestAnUntrackedBrandIsCounted(unittest.TestCase):

    TABLE = [
        {"url": "https://a.ca/1", "domain": "a.ca", "category": "competitor",
         "brand": "A Clinic", "is_client": False, "cite_count": 2},
        {"url": "https://b.ca/1", "domain": "b.ca", "category": "competitor",
         "brand": None, "is_client": False, "cite_count": 7},
        {"url": "https://c.ca/1", "domain": "c.ca", "category": "publisher",
         "brand": None, "is_client": False, "cite_count": 1},
    ]

    def test_it_counts_citations_not_rows(self):
        """Two rows carry no brand, but they carry eight citations. Counting
        rows would report 2 of 3 and understate it fourfold."""
        attributed, unattributed, total = citation_table.unattributed_brands(
            self.TABLE)
        self.assertEqual((attributed, unattributed, total), (2, 8, 10))

    def test_the_section_says_how_many_and_where_to_fix_it(self):
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", self.TABLE))
        self.assertIn("8 of 10 citation(s)", text)
        self.assertIn("known_brands", text)

    def test_nothing_attributed_reads_differently_from_some_attributed(self):
        """The case the count exists for: every citation is from a brand this
        run does not track, so the leaderboard above is empty of competitors
        and a reader would otherwise read that as "no competitor is cited"."""
        none_tracked = [dict(row, brand=None) for row in self.TABLE]
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", none_tracked))
        some = "\n".join(citation_table.render_citation_section(
            "perplexity", self.TABLE))
        self.assertIn("none of this engine's citations", text)
        self.assertNotIn("none of this engine's citations", some)
        self.assertIn("10 of 10 citation(s)", text)

    def test_the_actionable_figure_is_the_categories_a_rival_sits_in(self):
        """A directory or a publisher carries no brand by design, so the
        whole-table count is high on every run. The subset that matters is
        printed beside it (cold review of chunk Y5)."""
        table = [
            {"url": "u", "domain": "a.ca", "category": "counselling",
             "brand": None, "is_client": False, "cite_count": 3},
            {"url": "v", "domain": "b.ca", "category": "directory",
             "brand": None, "is_client": False, "cite_count": 9},
            {"url": "w", "domain": "c.ca", "category": "counselling",
             "brand": "X", "is_client": False, "cite_count": 2},
        ]
        self.assertEqual(
            citation_table.unattributed_brands(table, ["counselling"]),
            (2, 3, 5))
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", table,
            brand_relevant_categories=["counselling", "nonprofit"]))
        self.assertIn("12 of 14 citation(s)", text)
        self.assertIn("3 of the 5 citation(s)", text)
        self.assertIn("counselling, nonprofit", text)

    def test_the_figure_is_printed_at_zero_too(self):
        """Zero rivals missing from the gazetteer is the answer, not a reason
        to say nothing (P2)."""
        table = [
            {"url": "u", "domain": "a.ca", "category": "counselling",
             "brand": "X", "is_client": False, "cite_count": 3},
            {"url": "v", "domain": "b.ca", "category": "directory",
             "brand": None, "is_client": False, "cite_count": 9},
        ]
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", table, brand_relevant_categories=["counselling"]))
        self.assertIn("0 of the 3 citation(s)", text)

    def test_the_wording_does_not_claim_the_truncated_table(self):
        """Above `top_n` the table is truncated, so some counted citations are
        in the rows the section just said it was hiding."""
        table = [{"url": f"u{i}", "domain": f"d{i}.ca", "category": "other",
                  "brand": None, "is_client": False, "cite_count": 1}
                 for i in range(45)]
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", table))
        self.assertIn("45 of 45 citation(s)", text)
        self.assertNotIn("in the table above", text)

    def test_a_fully_attributed_table_says_nothing(self):
        full = [dict(row, brand="X") for row in self.TABLE]
        text = "\n".join(citation_table.render_citation_section(
            "perplexity", full))
        self.assertNotIn("known_brands", text)


class TestTheAliasGuardSeesEverySpelling(unittest.TestCase):
    """The Y1 guard grepped the source for two spellings. An AST walk sees
    every call on a string literal that is an alias prefix, including the ones
    nobody thought to grep for."""

    def _guard_on(self, body):
        from tests import test_y1_one_definition_each as y1

        return y1.hand_stripped_prefixes(body)

    def test_a_spelling_the_old_grep_missed_is_caught(self):
        for body in ('x = url.removeprefix("www.")\n',
                     'x = url.replace("www.", "")\n',
                     'x = url.lstrip("www.")\n',
                     'x = url.split("www.")[-1]\n',
                     'x = url.partition("www.")[2]\n',
                     'x = url.removesuffix("m.")\n',
                     # Neither of these is a string-method call, and the
                     # second is the most idiomatic hand-roll of the lot
                     # (cold review of chunk Y5).
                     'import re\nx = re.sub(r"^www\\.", "", url)\n',
                     'x = url[4:] if url.startswith("www.") else url\n',
                     'x = url.startswith(("www.", "m."))\n'):
            self.assertTrue(self._guard_on(body), body)

    def test_an_unrelated_string_operation_is_not_caught(self):
        self.assertFalse(self._guard_on('x = url.replace("https://", "")\n'))
        self.assertFalse(self._guard_on('x = normalize_domain(url)\n'))
        self.assertFalse(
            self._guard_on('import re\nx = re.sub(r"\\s+", " ", url)\n'))
        self.assertFalse(self._guard_on('x = url.startswith("https")\n'))

    def test_the_prefixes_come_from_domain_utils(self):
        import domain_utils
        from tests import test_y1_one_definition_each as y1

        self.assertEqual(
            y1._ALIAS_LABELS,
            {p.strip(".").lower() for p in domain_utils.ALIAS_PREFIXES})


class TestThreeWaitsAreThreeSettings(unittest.TestCase):

    def setUp(self):
        self.addCleanup(http_retry.apply_retry_policy, None)

    def test_each_class_is_read_from_the_section_that_owns_it(self):
        policy = http_retry.resolve_retry_policy({
            "http_retry": {"timeout_seconds": 11},
            "enrichment": {"timeout_seconds": 3},
            "ai_visibility": {"timeout_seconds": 99},
        })
        self.assertEqual(policy["timeout"], 11)
        self.assertEqual(policy["page_fetch_timeout"], 3)
        self.assertEqual(policy["llm_timeout"], 99)

    def test_the_shipped_config_sets_all_three(self):
        """A class with no key in `config.yml` is one nobody can tune, which
        is the state Y5 found."""
        import yaml

        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for key, (section, cfg_key) in http_retry.TIMEOUT_SOURCES.items():
            self.assertIn(cfg_key, cfg.get(section, {}), key)
        # Not an assertion that the three shipped numbers differ: they are
        # editorial and an owner may retune them to the same value. What must
        # hold is that each class is resolved and positive, so a class nobody
        # can tune is caught (the state Y5 found).
        policy = http_retry.resolve_retry_policy(cfg)
        for key in http_retry.TIMEOUT_SOURCES:
            self.assertGreater(policy[key], 0, key)

    def test_a_timeout_cannot_be_switched_off_or_set_to_a_bool(self):
        for bad in (0, -1, True, "soon", None):
            policy = http_retry.resolve_retry_policy({
                "http_retry": {"timeout_seconds": bad},
                "enrichment": {"timeout_seconds": bad},
                "ai_visibility": {"timeout_seconds": bad},
            })
            self.assertEqual(policy["timeout"],
                             http_retry.DEFAULT_RETRY_POLICY["timeout"], bad)
            self.assertEqual(
                policy["page_fetch_timeout"],
                http_retry.DEFAULT_RETRY_POLICY["page_fetch_timeout"], bad)
            self.assertEqual(policy["llm_timeout"],
                             http_retry.DEFAULT_RETRY_POLICY["llm_timeout"],
                             bad)

    def test_the_validation_is_the_repo_s_own(self):
        """`seconds_from_config` is the rule this repo already owns; a second
        copy here is how two validators come to disagree (P32)."""
        self.assertEqual(seconds_from_config(0, 7.0, "x"), 7.0)
        self.assertEqual(
            http_retry.resolve_retry_policy(
                {"http_retry": {"timeout_seconds": "12.5"}})["timeout"],
            seconds_from_config("12.5", 30.0, "x"))

    def test_applying_the_policy_reaches_the_accessors(self):
        http_retry.apply_retry_policy({
            "http_retry": {"timeout_seconds": 11},
            "enrichment": {"timeout_seconds": 3},
            "ai_visibility": {"timeout_seconds": 99},
        })
        self.assertEqual(http_retry.request_timeout(), 11)
        self.assertEqual(http_retry.page_fetch_timeout(), 3)
        self.assertEqual(http_retry.llm_timeout(), 99)

    def test_applying_twice_does_not_compound(self):
        http_retry.apply_retry_policy({"http_retry": {"timeout_seconds": 11}})
        first = http_retry.resolve_retry_policy({})
        http_retry.apply_retry_policy({"http_retry": {"timeout_seconds": 11}})
        self.assertEqual(http_retry.resolve_retry_policy({}), first)
        self.assertEqual(first["timeout"],
                         http_retry.DEFAULT_RETRY_POLICY["timeout"])

    def test_no_client_passes_its_own_constant_to_the_retry_wrapper(self):
        """One config→argument mapping (P25). A client that passes its own
        constant takes the setting out of play for its own calls."""
        for module in ("dataforseo_client.py", "gsc_client.py",
                       "moz_client.py", "probe_ai_visibility.py"):
            tree = ast.parse(open(os.path.join(REPO, module),
                                  encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "timeout":
                        continue
                    self.assertFalse(
                        isinstance(kw.value, ast.Name)
                        and kw.value.id == "REQUEST_TIMEOUT",
                        f"{module} line {node.lineno} passes its own constant")

    def test_the_page_fetch_timeout_is_never_none(self):
        """`requests` reads `timeout=None` as "wait forever", so a default of
        `None` is worse than the constant it replaced."""
        import requests

        import url_enricher

        http_retry.apply_retry_policy({"enrichment": {"timeout_seconds": 4}})
        seen = []

        def _get(url, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise requests.Timeout("too slow")

        with mock.patch.object(url_enricher.requests, "head",
                               side_effect=requests.RequestException("no")), \
             mock.patch.object(http_retry.requests, "get", _get):
            url_enricher.UrlEnricher().fetch_url("https://x.ca/p")
        self.assertEqual(set(seen), {4})

    def test_an_explicit_timeout_still_wins(self):
        import requests

        import url_enricher

        http_retry.apply_retry_policy({"enrichment": {"timeout_seconds": 4}})
        seen = []

        def _get(url, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise requests.Timeout("too slow")

        with mock.patch.object(url_enricher.requests, "head",
                               side_effect=requests.RequestException("no")), \
             mock.patch.object(http_retry.requests, "get", _get):
            url_enricher.UrlEnricher(timeout=7).fetch_url("https://x.ca/p")
        self.assertEqual(set(seen), {7})

    def test_the_head_probe_uses_the_same_timeout(self):
        """It was the one call site still reading `self.timeout` directly, so
        it got `None` once the default moved to the config."""
        import requests

        import url_enricher

        http_retry.apply_retry_policy({"enrichment": {"timeout_seconds": 4}})
        seen = []

        def _head(url, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise requests.RequestException("no head")

        with mock.patch.object(url_enricher.requests, "head", _head), \
             mock.patch.object(http_retry.requests, "get",
                               side_effect=requests.Timeout("slow")):
            url_enricher.UrlEnricher().fetch_url("https://x.ca/p")
        self.assertEqual(seen, [4])

    def test_the_pipeline_has_one_mapping_for_the_page_fetch(self):
        """`serp_audit` passed `enrichment.timeout_seconds` to the enricher as
        well, which is a second mapping for one setting and the one the tests
        did not take."""
        tree = ast.parse(open(os.path.join(REPO, "serp_audit.py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "UrlEnricher"):
                self.assertNotIn(
                    "timeout", [kw.arg for kw in node.keywords],
                    f"serp_audit.py line {node.lineno}")

    def test_every_engine_is_bounded_by_the_configured_llm_wait(self):
        """Per engine, not per file: the first form of this guard grepped the
        source for `http_retry.llm_timeout()`, which three of the four engines
        satisfied while `ClaudeProbe` built an SDK client with no timeout at
        all and waited the SDK's own ten minutes (P5, cold review)."""
        import probe_ai_visibility as probe

        http_retry.apply_retry_policy({"ai_visibility": {"timeout_seconds": 99}})
        seen = []

        def _post(label, url, headers, payload, **kwargs):
            seen.append((label, kwargs.get("timeout")))
            raise RuntimeError("stop here")

        keys = {"GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k",
                "PERPLEXITY_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}
        with mock.patch.dict(os.environ, keys), \
             mock.patch.object(probe, "post_with_transient_retry", _post):
            for cls in (probe.GeminiProbe, probe.ChatGPTProbe,
                        probe.PerplexityProbe):
                with self.assertRaises(RuntimeError):
                    cls(model="m").ask("q")
        self.assertEqual({timeout for _label, timeout in seen}, {99})
        self.assertEqual(len(seen), 3)

        # The Claude engine goes through the Anthropic SDK, so the timeout is
        # on the client it builds.
        clients = []

        class _Anthropic:
            def __init__(self, **kwargs):
                clients.append(kwargs)

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), \
             mock.patch.object(probe.anthropic, "Anthropic", _Anthropic):
            _ = probe.ClaudeProbe(model="m")._client
        self.assertEqual([c.get("timeout") for c in clients], [99])

    def test_the_documented_default_matches_the_policy_default(self):
        """The module constant is documentation now, so a reader who trusts it
        must not be reading a different number from the one in force."""
        import probe_ai_visibility as probe

        self.assertEqual(
            float(probe.REQUEST_TIMEOUT),
            http_retry.DEFAULT_RETRY_POLICY["llm_timeout"])

    def test_an_empty_key_is_reported_rather_than_silently_defaulted(self):
        """`timeout_seconds:` with nothing after it is a typo, and
        `seconds_from_config` reads `None` as "key absent" and says nothing."""
        with self.assertLogs(http_retry.logger, level="WARNING") as caught:
            policy = http_retry.resolve_retry_policy(
                {"enrichment": {"timeout_seconds": None}})
        self.assertEqual(policy["page_fetch_timeout"],
                         http_retry.DEFAULT_RETRY_POLICY["page_fetch_timeout"])
        self.assertIn("enrichment.timeout_seconds",
                      "\n".join(caught.output))


if __name__ == "__main__":
    unittest.main()
