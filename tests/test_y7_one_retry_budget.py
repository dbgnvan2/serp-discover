"""Review chunk Y7 — one retry budget, read in one place.

The tool makes two kinds of outbound call and had two retry policies. The
SerpAPI pair (`serpapi.retry_max_attempts` / `retry_backoff_seconds`) was read
at `serp_audit` import with a bare `int()` / `float()`: a value that is not a
number aborted the run with a traceback before anything was fetched, and a
negative backoff reached `time.sleep` after the first paid call. The three
`http_retry` keys beside them warned and used the documented default. Two
validators for one kind of setting (P4/P32).

Spec: docs/review_2026-11-04/PLAN_Y7_one_retry_budget.md
"""
import logging
import pathlib
import unittest
from unittest import mock

import requests

import config_manager
import http_retry
import run_gsc_analysis
import serp_audit


#: The globals `apply_retry_policy` rebinds. Restoring them to
#: `DEFAULT_RETRY_POLICY` is not restoring the process: `serp_audit` applies
#: the real `config.yml` at import, and the two agree only while that file
#: holds the documented numbers (cold review of chunk Y7).
_POLICY_GLOBALS = ("RETRY_ATTEMPTS", "RETRY_BACKOFF_SECONDS",
                   "MAX_RETRY_AFTER_SECONDS", "REQUEST_TIMEOUT_SECONDS",
                   "PAGE_FETCH_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS",
                   "SERPAPI_RETRY_ATTEMPTS", "SERPAPI_RETRY_BACKOFF_SECONDS")


def _restore_policy(case):
    """Put back whatever this process was running with, not the defaults."""
    before = {name: getattr(http_retry, name) for name in _POLICY_GLOBALS}

    def _put_back():
        for name, value in before.items():
            setattr(http_retry, name, value)

    case.addCleanup(_put_back)


class TestJunkInTheSerpapiBudgetIsReported(unittest.TestCase):
    """Y7.1 — the same validation as its sibling: a warning naming the key,
    and the documented default, not a traceback."""

    def setUp(self):
        _restore_policy(self)

    def test_a_non_numeric_attempt_count_warns_and_falls_back(self):
        with self.assertLogs("http_retry", level="WARNING") as logs:
            policy = http_retry.resolve_retry_policy(
                {"serpapi": {"retry_max_attempts": "lots"}})
        self.assertEqual(policy["serpapi_attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["serpapi_attempts"])
        joined = "\n".join(logs.output)
        self.assertIn("serpapi.retry_max_attempts", joined)
        self.assertIn("'lots'", joined)

    def test_a_negative_backoff_never_reaches_sleep(self):
        with self.assertLogs("http_retry", level="WARNING"):
            policy = http_retry.resolve_retry_policy(
                {"serpapi": {"retry_backoff_seconds": -5}})
        self.assertEqual(policy["serpapi_backoff"],
                         http_retry.DEFAULT_RETRY_POLICY["serpapi_backoff"])
        self.assertGreater(policy["serpapi_backoff"], 0)

    def test_a_valid_budget_is_taken(self):
        policy = http_retry.resolve_retry_policy(
            {"serpapi": {"retry_max_attempts": 5,
                         "retry_backoff_seconds": 2.5}})
        self.assertEqual(policy["serpapi_attempts"], 5)
        self.assertEqual(policy["serpapi_backoff"], 2.5)

    def test_a_serpapi_block_that_is_not_a_block_warns(self):
        with self.assertLogs("http_retry", level="WARNING") as logs:
            policy = http_retry.resolve_retry_policy({"serpapi": "yes please"})
        self.assertEqual(policy["serpapi_attempts"],
                         http_retry.DEFAULT_RETRY_POLICY["serpapi_attempts"])
        self.assertIn("serpapi", "\n".join(logs.output))

    def test_both_budgets_go_through_one_rule(self):
        """The two blocks are read by the same function, so a rule added to
        one reaches the other. `BUDGET_SOURCES` names both."""
        self.assertEqual({name for name, _ in http_retry.BUDGET_SOURCES},
                         {"http_retry", "serpapi"})


class TestTheAppliedBudgetReachesTheFetchLoop(unittest.TestCase):
    """Y7.1 — read as a function at the call site, so a budget applied after
    import reaches it. A module constant bound at import did not (the Y4
    default-argument trap, the same shape)."""

    def setUp(self):
        _restore_policy(self)

    def test_the_accessors_follow_apply_retry_policy(self):
        http_retry.apply_retry_policy(
            {"serpapi": {"retry_max_attempts": 4,
                         "retry_backoff_seconds": 3.0}})
        self.assertEqual(http_retry.serpapi_retry_attempts(), 4)
        self.assertEqual(http_retry.serpapi_retry_backoff(), 3.0)

    def test_the_fetch_loop_tries_the_configured_number_of_times(self):
        http_retry.apply_retry_policy({"serpapi": {"retry_max_attempts": 4}})
        calls = []

        class _Search:
            def __init__(self, params):
                pass

            def get_dict(self):
                calls.append(1)
                raise requests.Timeout("stalled")

        with mock.patch.object(serp_audit, "GoogleSearch", _Search), \
                mock.patch.object(serp_audit, "SERPAPI_AVAILABLE", True), \
                mock.patch.object(serp_audit.time, "sleep", lambda s: None):
            serp_audit._fetch_serp_api({"q": "x"})
        self.assertEqual(len(calls), 4)

    def test_the_fetch_loop_sleeps_the_configured_backoff(self):
        http_retry.apply_retry_policy(
            {"serpapi": {"retry_max_attempts": 2,
                         "retry_backoff_seconds": 5.0}})
        slept = []

        class _Search:
            def __init__(self, params):
                pass

            def get_dict(self):
                raise requests.Timeout("stalled")

        with mock.patch.object(serp_audit, "GoogleSearch", _Search), \
                mock.patch.object(serp_audit, "SERPAPI_AVAILABLE", True), \
                mock.patch.object(serp_audit.time, "sleep", slept.append):
            serp_audit._fetch_serp_api({"q": "x"})
        # One sleep, between the two attempts, at the configured base plus
        # up to 0.2s of jitter — never a negative number.
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], 5.0)
        self.assertLess(slept[0], 5.3)

    def test_serp_audit_binds_no_retry_constant_at_import(self):
        for name in ("RETRY_MAX_ATTEMPTS", "RETRY_BACKOFF_SECONDS"):
            self.assertFalse(
                hasattr(serp_audit, name),
                f"serp_audit.{name} is bound at import, so a budget applied "
                "afterwards cannot reach the fetch loop (Y7)")


class TestTheGuiExplainsBothBudgets(unittest.TestCase):
    """Y7.3 — the GUI had help text for SerpAPI's two keys and none for the
    four `http_retry` keys, so it showed one of the two policies."""

    def _expected_paths(self):
        """Read off the tables `resolve_retry_policy` drives, so a key added
        to the policy is a key this guard requires help text for — a
        hardcoded list would have passed a seventh key by silence (P27)."""
        paths = set()
        for section_name, keys in http_retry.BUDGET_SOURCES:
            for _, cfg_key, _ in keys:
                paths.add(f"config.yml.{section_name}.{cfg_key}")
        for section_name, cfg_key in http_retry.TIMEOUT_SOURCES.values():
            paths.add(f"config.yml.{section_name}.{cfg_key}")
        return paths

    def test_every_retry_and_timeout_key_has_help_text(self):
        for path in sorted(self._expected_paths()):
            with self.subTest(path=path):
                text = config_manager.HELP_BY_FIELD.get(path)
                self.assertTrue(text and len(text) > 20,
                                f"{path} has no help text in the GUI")

    def test_the_attempt_counts_are_described_as_total_tries(self):
        """`attempts` is the total number of tries, not the extra ones: the
        loops are `range(1, attempts + 1)`. Help text reading "how many times
        to retry" sends an operator who wants one retry to `1`, which is no
        retry at all on a paid single-vendor call (P1)."""
        for path in ("config.yml.serpapi.retry_max_attempts",
                     "config.yml.http_retry.attempts"):
            with self.subTest(path=path):
                text = config_manager.HELP_BY_FIELD[path].lower()
                self.assertIn("total tries", text)
                self.assertIn("no retry at all", text)

    def test_only_the_serpapi_backoff_is_described_as_doubling(self):
        """`http_retry` sleeps `backoff * attempt` (linear); the SerpAPI loop
        sleeps `backoff * 2 ** (attempt - 1)`. One sentence cannot describe
        both, and the first draft of this help text used the wrong one."""
        self.assertIn(
            "doubles",
            config_manager.HELP_BY_FIELD[
                "config.yml.serpapi.retry_backoff_seconds"].lower())
        shared = config_manager.HELP_BY_FIELD[
            "config.yml.http_retry.backoff_seconds"].lower()
        self.assertIn("linear", shared)
        self.assertNotIn("it doubles", shared)

    def test_a_mangled_block_is_reported_not_silently_replaced(self):
        """Both blocks are read the same way. `http_retry` was read as
        `cfg.get(...) or {}`, so an indentation typo that made the block `0`
        or empty was replaced by the defaults with nothing in the log, while
        the same mistake under `serpapi` warned (P2/P9)."""
        for section in ("http_retry", "serpapi"):
            for value in (0, "", {}, None):
                with self.subTest(section=section, value=value):
                    with self.assertLogs("http_retry",
                                         level="WARNING") as logs:
                        http_retry.resolve_retry_policy({section: value})
                    self.assertIn(section, "\n".join(logs.output))


class TestTheHelpTableHasNoDuplicateKeys(unittest.TestCase):
    """Adding `enrichment.timeout_seconds` to the help table while a vaguer
    entry for the same key already sat 13 lines below it produced a dict
    literal with the key twice, where the last one silently wins. A dict is
    not a place to notice that by eye (cold review of chunk Y7)."""

    def test_no_help_key_is_defined_twice(self):
        import ast
        import collections
        source = pathlib.Path(config_manager.__file__).read_text(
            encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            duplicates = [k for k, n in collections.Counter(keys).items()
                          if n > 1]
            self.assertFalse(
                duplicates,
                f"config_manager.py line {node.lineno}: {duplicates} appear "
                "more than once in one dict literal, so the earlier entry is "
                "dead text")


class TestTheSpongeThresholdsAreResolvedOnce(unittest.TestCase):
    """Y7.4 — `main` resolved the thresholds a second time and passed all five
    explicitly, so the mapping `_load_config` applied had no production
    reader: a value applied in-process was computed and then ignored (P25)."""

    def setUp(self):
        self.addCleanup(run_gsc_analysis.apply_sponge_thresholds, None)

    def test_a_value_applied_before_the_comparison_reaches_it(self):
        rows = [self._row(f"q{i}", position=2.0, has_ai_overview=i % 2 == 0)
                for i in range(20)]
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"min_bucket_size": 50}})
        sponge = run_gsc_analysis.compute_sponge_effect(rows)
        self.assertFalse(
            any(b.get("sufficient") for b in sponge["bands"]),
            "a min_bucket_size of 50 was applied, so ten queries a bucket "
            "cannot be enough")
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"min_bucket_size": 2}})
        sponge = run_gsc_analysis.compute_sponge_effect(rows)
        self.assertTrue(any(b.get("sufficient") for b in sponge["bands"]))

    def test_the_reformat_shortlist_follows_the_applied_cap(self):
        rows = []
        for i in range(6):
            row = self._row(f"healthy{i}", position=12.0,
                            has_ai_overview=False)
            row["ctr"] = 0.10
            rows.append(row)
        starving = self._row("deep", position=12.0, has_ai_overview=True)
        starving["ctr"] = 0.0
        rows.append(starving)
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"reformat_max_position": 20}})
        sponge = run_gsc_analysis.compute_sponge_effect(rows)
        self.assertTrue(run_gsc_analysis.find_reformat_candidates(
            rows, sponge, set()))
        run_gsc_analysis.apply_sponge_thresholds(
            {"gsc": {"reformat_max_position": 5}})
        self.assertFalse(
            run_gsc_analysis.find_reformat_candidates(rows, sponge, set()),
            "a cap of position 5 was applied, so a query at 12 cannot be "
            "shortlisted")

    def test_the_run_passes_no_threshold_the_active_mapping_holds(self):
        """A consequence test would need a whole GSC run; this walks the one
        call site's AST instead of matching its text (P27)."""
        import ast
        import inspect
        src = inspect.getsource(run_gsc_analysis.run_analysis)
        tree = ast.parse("if 1:\n" + "\n".join(
            "    " + line for line in src.splitlines()))
        banned = {"bands", "min_bucket_size", "min_impressions",
                  "max_position", "ctr_margin"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(
                node.func, "attr", None)
            if name not in ("compute_sponge_effect",
                            "find_reformat_candidates"):
                continue
            passed = {kw.arg for kw in node.keywords}
            self.assertFalse(
                passed & banned,
                f"run_analysis passes {sorted(passed & banned)} to {name} as "
                "well as applying them, so the one mapping and the explicit "
                "arguments can disagree (Y7.4)")

    @staticmethod
    def _row(query, *, position, has_ai_overview):
        import gsc_client
        return {"query": query, "source_keyword": query, "query_label": "A",
                "found": True, "gsc_status": gsc_client.STATUS_MEASURED,
                "has_ai_overview": has_ai_overview,
                "clicks": 5, "impressions": 500, "ctr": 0.01,
                "position": position}


class TestNoTestLeavesTheThresholdsApplied(unittest.TestCase):
    """`run_analysis` now writes the module mapping, so a test that calls it
    changes what every later test in the process reads when it omits a
    threshold argument. The suite was green only on collection order
    (P28/P34, cold review of chunk Y7). This runs the one test that calls
    `run_analysis` and checks the process is as it was."""

    def test_running_the_run_analysis_case_restores_the_mapping(self):
        import io
        from tests import test_y4_config_not_constants as y4

        before = run_gsc_analysis.active_sponge_thresholds()
        suite = unittest.TestLoader().loadTestsFromName(
            "TestSpongeThresholdsComeFromConfig."
            "test_the_run_passes_the_resolved_bands_and_bucket_size", y4)
        result = unittest.TextTestRunner(
            stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        "the case this guard runs must itself pass")
        self.assertEqual(
            run_gsc_analysis.active_sponge_thresholds(), before,
            "a test applied this run's thresholds and left them applied, so "
            "every later test that omits a threshold argument reads them")


if __name__ == "__main__":
    unittest.main()
