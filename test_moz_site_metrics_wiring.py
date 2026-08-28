"""
test_moz_site_metrics_wiring.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every front end that builds a MozClient must pass the `moz.site_metrics`
config through to it.

Spec: moz_api_upgrade_spec_v1.md#T.1

A test at the client proves the client works; it says nothing about whether
the callers above it actually pass the values (learnings P25 — "wired at the
library, unreachable from the front end"). One assertion per surface.
"""

import ast
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

import moz_client
import run_feasibility as rf
from moz_client import MozClient

SITE_METRICS_CFG = {
    "scope": "subdomain",
    "batch_size": 7,
    "link_count_fields": ["root_domains_to_page"],
}

CONFIG = {
    "moz": {"cache_ttl_days": 11, "site_metrics": SITE_METRICS_CFG},
    "feasibility": {"client_da": 35, "neighborhoods": [], "non_profit_location": "X"},
    "analysis_report": {"client_domain": "livingsystems.ca"},
}

DATA = {
    "organic_results": [
        {"Query_Label": "A", "Source_Keyword": "bowen theory",
         "Link": "https://example.com/a", "Rank": 1},
    ]
}


class TestFromConfigMapping(unittest.TestCase):
    """The single config→argument mapping every surface shares."""

    def _client(self, config):
        with patch.dict(os.environ, {"MOZ_TOKEN": "t"}), \
                tempfile.NamedTemporaryFile(suffix=".db") as f:
            return MozClient.from_config(config, db_path=f.name)

    def test_t1_from_config_maps_every_site_metrics_key(self):
        c = self._client(CONFIG)
        self.assertEqual(c._scope, "subdomain")
        self.assertEqual(c._batch_size, 7)
        self.assertEqual(c._link_count_fields, ("root_domains_to_page",))
        self.assertEqual(c._cache_ttl, timedelta(days=11))

    def test_t1_from_config_falls_back_when_the_block_is_absent(self):
        c = self._client({})
        self.assertEqual(c._scope, moz_client.DEFAULT_SITE_SCOPE)
        self.assertEqual(c._batch_size, moz_client.MOZ_BATCH_SIZE)
        self.assertEqual(
            c._link_count_fields, moz_client.DEFAULT_LINK_COUNT_FIELDS
        )

    def test_t1_from_config_tolerates_a_null_site_metrics_block(self):
        """A key present but empty in YAML parses as None, not {}."""
        c = self._client({"moz": {"cache_ttl_days": 5, "site_metrics": None}})
        self.assertEqual(c._scope, moz_client.DEFAULT_SITE_SCOPE)
        self.assertEqual(c._cache_ttl, timedelta(days=5))


class TestRunFeasibilitySurface(unittest.TestCase):
    """Surface 1 — run_feasibility.py (the standalone feasibility run)."""

    def test_t1_run_feasibility_builds_its_client_from_the_config(self):
        """Intercept the boundary and check the config actually arrives.

        A MozClient built with bare defaults here would leave every
        `moz.site_metrics` setting inert while the client's own tests stayed
        green (learnings P25).
        """
        fake_client = MagicMock()
        fake_client.get_moz_metrics.return_value = {}
        fake_cls = MagicMock()
        fake_cls.from_config.return_value = fake_client
        env = {"MOZ_TOKEN": "t", "DATAFORSEO_LOGIN": "", "DATAFORSEO_PASSWORD": ""}
        with patch.dict(os.environ, env), \
                patch.object(rf, "MozClient", fake_cls), \
                patch.object(rf, "MOZ_AVAILABLE", True), \
                patch.object(rf, "DATAFORSEO_AVAILABLE", False):
            rf.run_feasibility_analysis(DATA, CONFIG, do_pivot_serp=False)

        self.assertTrue(
            fake_cls.from_config.called,
            "run_feasibility built a MozClient without going through from_config, "
            "so the moz.site_metrics config never reaches it",
        )
        passed_config = fake_cls.from_config.call_args.args[0]
        self.assertEqual(
            passed_config.get("moz", {}).get("site_metrics"), SITE_METRICS_CFG
        )


class TestSerpAuditSurface(unittest.TestCase):
    """Surface 2 — serp_audit.py (the main audit run).

    serp_audit builds its MozClient deep inside the audit flow, behind a
    credential gate, so the call is checked by walking the AST for the call
    site rather than by executing the pipeline. Matching source *text* would
    also match a comment; parsing cannot (learnings P19 corollary).
    """

    @staticmethod
    def _moz_client_call() -> ast.Call:
        with open("serp_audit.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            if (isinstance(node, ast.Call) and isinstance(func, ast.Attribute)
                    and func.attr == "from_config"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "MozClient"):
                return node
        raise AssertionError(
            "serp_audit.py does not build its MozClient via MozClient.from_config, "
            "so the moz.site_metrics config never reaches it"
        )

    def test_t1_serp_audit_builds_its_client_from_the_config(self):
        call = self._moz_client_call()
        self.assertTrue(call.args, "MozClient.from_config called with no config")
        self.assertEqual(ast.unparse(call.args[0]), "CONFIG")

    def test_t1_serp_audit_has_no_bare_mozclient_construction(self):
        """A second, un-configured construction would silently bypass the seam."""
        with open("serp_audit.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        bare = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "MozClient"
        ]
        self.assertEqual(bare, [], "serp_audit.py builds a MozClient directly")


if __name__ == "__main__":
    unittest.main()
