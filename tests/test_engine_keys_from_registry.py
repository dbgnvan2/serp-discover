"""The engines read the same key registry the content brief reads.

Four engines read four environment variables; content-brief generation reads
the shared registry (`~/.config/llm/keys.json`). On a machine whose keys live
in the registry, the brief was written and all four engines skipped with
"KEY is not set" — the key existed and the probe could not see it. These
tests hold the fallback, and hold the three things that must not change with
it: the environment still wins, a key never reaches a log or a record, and
an engine with no key anywhere is still reported rather than zeroed.

No test here touches the network or the real registry.
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import probe_ai_visibility as probe  # noqa: E402

SECRET = "sk-test-not-a-real-key-0001"


class _Provider:
    def __init__(self, name, api_key):
        self.name = name
        self.api_key = api_key


class _Registry:
    """A stand-in for the shared `llm_providers` module."""

    def __init__(self, providers=None, raises=None):
        self._providers = providers or {}
        self._raises = raises

    def get_provider(self, name):
        if self._raises is not None:
            raise self._raises
        try:
            return self._providers[name]
        except KeyError:
            raise RuntimeError(f"unknown provider '{name}'") from None


class _Base(unittest.TestCase):

    def _fill(self, mapping, env, registry=_Registry):
        """Run the fill with `registry` swapped in, never the real one."""
        original = probe.report_llm.load_registry
        probe.report_llm.load_registry = lambda: registry
        try:
            return probe.fill_keys_from_registry(
                {"key_registry_providers": mapping}, env=env)
        finally:
            probe.report_llm.load_registry = original


class TestTheEnvironmentWins(_Base):

    def test_a_key_already_set_is_not_replaced(self):
        env = {"ANTHROPIC_API_KEY": "from-dot-env"}
        reg = _Registry({"anthropic": _Provider("anthropic", SECRET)})
        records = self._fill({"ANTHROPIC_API_KEY": "anthropic"}, env, reg)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "from-dot-env")
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ENVIRONMENT)
        self.assertIsNone(records[0]["provider"])

    def test_whitespace_only_counts_as_unset(self):
        env = {"GEMINI_API_KEY": "   "}
        reg = _Registry({"gemini-serp": _Provider("gemini-serp", SECRET)})
        records = self._fill({"GEMINI_API_KEY": "gemini-serp"}, env, reg)
        self.assertEqual(env["GEMINI_API_KEY"], SECRET)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_REGISTRY)


class TestTheFallbackFills(_Base):

    def test_a_missing_key_comes_from_the_named_provider(self):
        env = {}
        reg = _Registry({"openai-serp": _Provider("openai-serp", SECRET)})
        records = self._fill({"OPENAI_API_KEY": "openai-serp"}, env, reg)
        self.assertEqual(env["OPENAI_API_KEY"], SECRET)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_REGISTRY)
        self.assertEqual(records[0]["provider"], "openai-serp")

    def test_the_default_map_is_used_when_config_has_none(self):
        for mapping in (None, {}, "not a dict", []):
            with self.subTest(mapping=mapping):
                original = probe.report_llm.load_registry
                probe.report_llm.load_registry = lambda: _Registry()
                try:
                    records = probe.fill_keys_from_registry(
                        {"key_registry_providers": mapping}, env={})
                finally:
                    probe.report_llm.load_registry = original
                self.assertEqual(
                    {r["env_var"] for r in records},
                    set(probe.DEFAULT_KEY_REGISTRY_PROVIDERS))


class TestEveryWayItCanHaveNoKey(_Base):
    """Four different reasons, four different sentences — not one 'absent'."""

    def test_no_provider_configured_says_nobody_decided(self):
        env = {}
        records = self._fill({"PERPLEXITY_API_KEY": ""}, env, _Registry())
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ABSENT)
        self.assertIn("no key-registry provider is configured",
                      records[0]["reason"])
        self.assertNotIn("PERPLEXITY_API_KEY", env)

    def test_an_absent_registry_says_so(self):
        records = self._fill({"OPENAI_API_KEY": "openai-serp"}, {},
                             registry=None)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ABSENT)
        self.assertIn("key registry", records[0]["reason"])

    def test_a_provider_lookup_failure_is_reported_not_raised(self):
        reg = _Registry(raises=RuntimeError("registry file is malformed"))
        records = self._fill({"OPENAI_API_KEY": "openai-serp"}, {}, reg)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ABSENT)
        self.assertIn("registry file is malformed", records[0]["reason"])

    def test_an_unknown_provider_name_is_reported(self):
        reg = _Registry({"openai-serp": _Provider("openai-serp", SECRET)})
        records = self._fill({"OPENAI_API_KEY": "typo-provider"}, {}, reg)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ABSENT)
        self.assertIn("typo-provider", records[0]["reason"])

    def test_a_provider_with_no_api_key_is_reported(self):
        reg = _Registry({"openai-serp": _Provider("openai-serp", "")})
        records = self._fill({"OPENAI_API_KEY": "openai-serp"}, {}, reg)
        self.assertEqual(records[0]["source"], probe.KEY_SOURCE_ABSENT)
        self.assertIn("no api_key", records[0]["reason"])


class TestNoKeyEverLeaves(_Base):

    def test_no_record_carries_the_key_value(self):
        env = {}
        reg = _Registry({"openai-serp": _Provider("openai-serp", SECRET)})
        records = self._fill({"OPENAI_API_KEY": "openai-serp"}, env, reg)
        self.assertEqual(env["OPENAI_API_KEY"], SECRET)   # it did arrive
        for rec in records:                               # and is not in the record
            self.assertNotIn(SECRET, repr(rec))

    def test_nothing_logged_carries_the_key_value(self):
        env = {}
        reg = _Registry({"openai-serp": _Provider("openai-serp", SECRET),
                         "gemini-serp": _Provider("gemini-serp", "")})
        records = self._fill({"OPENAI_API_KEY": "openai-serp",
                              "GEMINI_API_KEY": "gemini-serp"}, env, reg)
        with self.assertLogs(probe.logger, level="INFO") as caught:
            probe.log_key_sources(records)
        joined = "\n".join(caught.output)
        self.assertNotIn(SECRET, joined)
        self.assertIn("openai-serp", joined)

    def test_the_log_counts_n_of_m(self):
        records = [
            {"env_var": "A", "provider": "p", "source": probe.KEY_SOURCE_REGISTRY,
             "reason": None},
            {"env_var": "B", "provider": None, "source": probe.KEY_SOURCE_ABSENT,
             "reason": "nothing configured"},
        ]
        with self.assertLogs(probe.logger, level="INFO") as caught:
            probe.log_key_sources(records)
        self.assertTrue(any("1 of 2 engine key(s) unavailable" in line
                            for line in caught.output))

    def test_a_full_set_logs_no_warning(self):
        records = [{"env_var": "A", "provider": "p",
                    "source": probe.KEY_SOURCE_REGISTRY, "reason": None}]
        with self.assertLogs(probe.logger, level="INFO") as caught:
            probe.log_key_sources(records)
        self.assertFalse(any("unavailable" in line for line in caught.output))


class TestTheMapIsEditorialAndInConfig(unittest.TestCase):

    def test_config_yml_names_a_provider_for_every_engine_variable(self):
        import yaml
        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as fh:
            av = (yaml.safe_load(fh) or {}).get("ai_visibility") or {}
        mapping = av.get("key_registry_providers")
        self.assertIsInstance(mapping, dict,
                              "ai_visibility.key_registry_providers is missing")
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                    "PERPLEXITY_API_KEY"):
            with self.subTest(var=var):
                self.assertIn(
                    var, mapping,
                    "every engine variable is listed even when blank, so "
                    "'no key on this machine' is visible beside the others")

    def test_no_api_key_value_sits_in_config_yml(self):
        """The map names providers. A key in it would be a secret in git."""
        import yaml
        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as fh:
            av = (yaml.safe_load(fh) or {}).get("ai_visibility") or {}
        for var, name in (av.get("key_registry_providers") or {}).items():
            with self.subTest(var=var):
                self.assertNotIn("sk-", str(name))
                self.assertLess(len(str(name)), 40)


if __name__ == "__main__":
    unittest.main()
