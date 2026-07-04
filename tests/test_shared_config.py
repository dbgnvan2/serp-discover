"""
Tests for the formalized shared_config.json contract.

Spec: seo_geo_deferred_spec_v1.md#C.9
- C.9.1 the path is constructed in exactly one module (shared_config.py)
- C.9.2 SERP_SHARED_CONFIG redirects loading; an overridden threshold
  visibly changes feasibility._gap_to_status
- C.9.3 a malformed shared config logs one warning naming the file and
  falls back to defaults
- C.9.4 with no file present, consumers behave identically to before
"""
import glob
import importlib
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

import feasibility
import shared_config
from shared_config import load_shared_config, shared_config_path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSinglePathOwner(unittest.TestCase):
    """C.9.1 — only shared_config.py may name the shared config file."""

    def test_literal_appears_in_exactly_one_module(self):
        offenders = []
        py_files = glob.glob(os.path.join(_REPO_ROOT, "*.py")) + glob.glob(
            os.path.join(_REPO_ROOT, "tests", "*.py")
        )
        for path in py_files:
            if os.path.basename(path) in ("shared_config.py", "test_shared_config.py"):
                continue
            with open(path, encoding="utf-8") as f:
                if "shared_config.json" in f.read():
                    offenders.append(os.path.basename(path))
        self.assertEqual(
            offenders, [],
            "shared_config.json path logic must live only in shared_config.py "
            f"— found the literal in: {offenders}",
        )


class TestEnvOverride(unittest.TestCase):
    """C.9.2 — SERP_SHARED_CONFIG redirects loading."""

    def _reload_feasibility_with(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            importlib.reload(feasibility)

    def tearDown(self):
        # Restore module-level thresholds to the no-override state so other
        # tests see default behavior.
        os.environ.pop(shared_config.ENV_VAR, None)
        importlib.reload(feasibility)

    def test_env_var_redirects_path(self):
        with mock.patch.dict(os.environ, {shared_config.ENV_VAR: "/tmp/x.json"}):
            self.assertEqual(shared_config_path(), "/tmp/x.json")

    def test_env_var_absent_uses_parent_dir_default(self):
        env = {k: v for k, v in os.environ.items() if k != shared_config.ENV_VAR}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(shared_config_path().endswith(
                os.path.join("..", "shared_config.json")))

    def test_overridden_threshold_changes_gap_to_status(self):
        # Default thresholds: gap 3 -> High Feasibility. Override the high
        # threshold down to 0 via a temp shared config and the same gap must
        # become Moderate.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as f:
            json.dump({"technical": {"feasibility_threshold": 0,
                                     "moderate_feasibility_max_gap": 15}}, f)
            override_path = f.name
        try:
            self._reload_feasibility_with({shared_config.ENV_VAR: override_path})
            self.assertEqual(feasibility._gap_to_status(3), "Moderate Feasibility")
        finally:
            os.unlink(override_path)

    def test_default_thresholds_without_override(self):
        # No shared config file -> code defaults (5 / 15 / 30).
        missing = os.path.join(tempfile.gettempdir(), "nonexistent_shared_config_c9.json")
        self._reload_feasibility_with({shared_config.ENV_VAR: missing})
        self.assertEqual(feasibility._gap_to_status(3), "High Feasibility")
        self.assertEqual(feasibility._gap_to_status(10), "Moderate Feasibility")
        self.assertEqual(feasibility._gap_to_status(20), "Low Feasibility")
        self.assertEqual(feasibility.load_thresholds(), (5, 15, 30.0))


class TestMalformedConfig(unittest.TestCase):
    """C.9.3 — malformed file: one warning naming the file, defaults returned."""

    def _load_with_content(self, content):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            with self.assertLogs("shared_config", level="WARNING") as captured:
                result = load_shared_config(path)
        finally:
            os.unlink(path)
        return result, captured, path

    def test_invalid_json_warns_and_falls_back(self):
        result, captured, path = self._load_with_content("{not valid json")
        self.assertEqual(result, {})
        warnings = [r for r in captured.records if r.levelno == logging.WARNING]
        self.assertEqual(len(warnings), 1)
        self.assertIn(path, warnings[0].getMessage())

    def test_non_object_json_warns_and_falls_back(self):
        result, captured, path = self._load_with_content('["a", "list"]')
        self.assertEqual(result, {})
        self.assertEqual(len(captured.records), 1)
        self.assertIn(path, captured.records[0].getMessage())


class TestAbsentAndPresentFile(unittest.TestCase):
    """C.9.4 — absent file: empty dict, INFO log, no exceptions."""

    def test_missing_file_returns_empty_dict_with_info(self):
        missing = os.path.join(tempfile.gettempdir(), "nonexistent_shared_config_c9.json")
        with self.assertLogs("shared_config", level="INFO") as captured:
            self.assertEqual(load_shared_config(missing), {})
        self.assertIn("not found", captured.records[0].getMessage())

    def test_valid_file_loads_and_logs_consumed_keys(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"stop_words": ["the"], "client": {"da": 30}}, f)
            path = f.name
        try:
            with self.assertLogs("shared_config", level="INFO") as captured:
                result = load_shared_config(path)
        finally:
            os.unlink(path)
        self.assertEqual(result["client"]["da"], 30)
        message = captured.records[0].getMessage()
        self.assertIn("client", message)
        self.assertIn("stop_words", message)

    def test_consumers_import_from_shared_config_module(self):
        # Both consumers must use the single owner, not their own path logic.
        import serp_audit
        self.assertEqual(serp_audit.SHARED_CONFIG_PATH, shared_config_path())
        src = open(os.path.join(_REPO_ROOT, "feasibility.py"), encoding="utf-8").read()
        self.assertIn("from shared_config import load_shared_config", src)


if __name__ == "__main__":
    unittest.main()
