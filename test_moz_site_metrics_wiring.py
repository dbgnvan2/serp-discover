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


class TestCredentialGate(unittest.TestCase):
    """T.1 — the gate must name the credential this project actually uses.

    serp_audit.py gated its whole DA block on MOZ_ACCESS_ID / MOZ_SECRET_KEY,
    names that appear nowhere else in the repo, so MOZ_AVAILABLE was always
    False and the Moz enrichment never ran from the audit path (P25).
    """

    def test_t1_credentials_present_reads_moz_token(self):
        with patch.dict(os.environ, {"MOZ_TOKEN": "abc"}):
            self.assertTrue(moz_client.credentials_present())

    def test_t1_credentials_absent_when_moz_token_unset(self):
        with patch.dict(os.environ, {"MOZ_TOKEN": ""}):
            self.assertFalse(moz_client.credentials_present())

    def test_t1_gate_does_not_depend_on_the_phantom_variables(self):
        """MOZ_ACCESS_ID / MOZ_SECRET_KEY must not gate anything: setting them
        without a token must not enable Moz, and a token alone must suffice."""
        with patch.dict(os.environ,
                        {"MOZ_TOKEN": "", "MOZ_ACCESS_ID": "a", "MOZ_SECRET_KEY": "b"}):
            self.assertFalse(moz_client.credentials_present())
        with patch.dict(os.environ,
                        {"MOZ_TOKEN": "abc", "MOZ_ACCESS_ID": "", "MOZ_SECRET_KEY": ""}):
            self.assertTrue(moz_client.credentials_present())

    def test_t1_serp_audit_gates_on_the_shared_credential_check(self):
        """The audit surface must use the shared check, not its own env read."""
        with open("serp_audit.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        assigns = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "MOZ_AVAILABLE"
                    for t in node.targets)
        ]
        sources = [ast.unparse(node.value) for node in assigns]
        self.assertIn("credentials_present()", sources)
        for src in sources:
            self.assertNotIn("MOZ_ACCESS_ID", src)
            self.assertNotIn("MOZ_SECRET_KEY", src)

    def test_t1_phantom_variables_are_gone_from_live_strings(self):
        """No live string may still name them — the message did, too.

        Docstrings are excluded: the code that fixed this describes the old
        names to explain itself, and a check that trips on its own
        explanation is the P19-corollary trap (a needle matching the prose
        about the needle).
        """
        for path in ("serp_audit.py", "run_feasibility.py", "moz_client.py"):
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            live = [
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ]
            for value in live:
                self.assertNotIn("MOZ_ACCESS_ID", value, path)
                self.assertNotIn("MOZ_SECRET_KEY", value, path)


class TestRowsConsumedAccounting(unittest.TestCase):
    """T.1 — the run log must state rows billed, never spend silently."""

    def setUp(self):
        self.env = patch.dict(os.environ, {"MOZ_TOKEN": "t"})
        self.env.start()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.client = MozClient(db_path=self.tmp.name)

    def tearDown(self):
        self.env.stop()
        os.unlink(self.tmp.name)

    def test_t1_rows_consumed_starts_at_zero(self):
        self.assertEqual(self.client.rows_consumed, 0)

    @patch("moz_jsonrpc.requests.post")
    def test_t1_rows_consumed_counts_fetched_targets(self, mock_post):
        from test_moz_client import _make_moz_response
        urls = ["https://a.com/", "https://b.com/"]
        mock_post.return_value = _make_moz_response(urls)
        self.client.get_moz_metrics(urls)
        self.assertEqual(self.client.rows_consumed, 2)

    @patch("moz_jsonrpc.requests.post")
    def test_t1_cache_hits_bill_no_rows(self, mock_post):
        """The 30-day cache is the whole quota argument — a hit must cost 0."""
        from test_moz_client import _make_moz_response
        urls = ["https://a.com/"]
        mock_post.return_value = _make_moz_response(urls)
        self.client.get_moz_metrics(urls)
        first = self.client.rows_consumed

        mock_post.reset_mock()
        self.client.get_moz_metrics(urls)
        mock_post.assert_not_called()
        self.assertEqual(self.client.rows_consumed, first)


if __name__ == "__main__":
    unittest.main()
