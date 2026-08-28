"""Tests for run_feasibility.py — pivot gating, fetch-failure honesty, secret scrub.

Spec: seo_geo_review_20260704.md (chip B).
  B.1.c — informational keywords produce NO neighbourhood pivot; service keywords do.
  B.2   — a failed validation fetch renders "not measured", never "✗ not in local pack".
  B.3   — a failing request's logged URL contains no API key.

All external calls are mocked; no API keys required.
"""
import logging
import os
import unittest
from unittest import mock
from unittest.mock import patch

import run_feasibility as rf


def _organic_row(keyword, url, rank):
    return {
        "Query_Label": "A",
        "Source_Keyword": keyword,
        "Link": url,
        "Rank": rank,
    }


class TestPivotGating(unittest.TestCase):
    """B.1.c — the pivot is gated on service intent, end-to-end in
    run_feasibility_analysis (DA client mocked so both keywords score Low)."""

    def _run(self):
        # Two keywords, both dominated by high-DA competitors → Low Feasibility.
        # One is a service query, one is informational (with a neighbourhood in
        # it — the exact adversarial shape from the bug report).
        service_kw = "couples counselling North Vancouver"
        info_kw = "how does birth order affect personality West Vancouver"
        data = {
            "organic_results": [
                _organic_row(service_kw, "https://bigdirectory.com/a", 1),
                _organic_row(service_kw, "https://hugesite.org/b", 2),
                _organic_row(info_kw, "https://bigdirectory.com/c", 1),
                _organic_row(info_kw, "https://hugesite.org/d", 2),
            ]
        }
        config = {
            "feasibility": {"client_da": 20, "neighborhoods": ["Lonsdale", "Lynn Valley"],
                            "non_profit_location": "North Vancouver"},
            "analysis_report": {"client_domain": "livingsystems.ca"},
        }
        # High competitor DA → Low Feasibility for both keywords.
        fake_metrics = {
            "bigdirectory.com": {"da": 90, "pa": 80},
            "hugesite.org": {"da": 85, "pa": 75},
        }

        class _FakeDA:
            def get_domain_metrics(self, urls):
                # keyed by domain (matches domain_to_da build in run_feasibility)
                return fake_metrics

        with mock.patch.object(rf, "DATAFORSEO_AVAILABLE", True), \
             mock.patch.dict("os.environ", {"DATAFORSEO_LOGIN": "x", "DATAFORSEO_PASSWORD": "y"}), \
             mock.patch.object(rf, "DataForSEOClient", return_value=_FakeDA()):
            rows = rf.run_feasibility_analysis(data, config, do_pivot_serp=False)
        return {r["Keyword"]: r for r in rows if r.get("Query_Label") == "A"}, service_kw, info_kw

    def test_b1c_informational_keyword_produces_no_pivot_or_variants(self):
        by_kw, service_kw, info_kw = self._run()
        info_row = by_kw[info_kw]
        self.assertEqual(info_row["feasibility_status"], "Low Feasibility")
        self.assertNotEqual(info_row["pivot_status"], "Pivoting to Hyper-Local")
        self.assertEqual(info_row["pivot_status"], "No pivot — informational")
        self.assertEqual(info_row["all_variants"], [])
        self.assertIsNone(info_row["suggested_keyword"])

    def test_b1c_service_keyword_still_pivots(self):
        by_kw, service_kw, info_kw = self._run()
        svc_row = by_kw[service_kw]
        self.assertEqual(svc_row["feasibility_status"], "Low Feasibility")
        self.assertEqual(svc_row["pivot_status"], "Pivoting to Hyper-Local")
        self.assertTrue(svc_row["all_variants"])
        self.assertIsNotNone(svc_row["suggested_keyword"])

    def test_b1c_no_da_branch_still_gates_informational_variants(self):
        """Even with no DA data (No DA Data branch), an informational keyword
        must carry NO neighbourhood variants; a service keyword still does."""
        service_kw = "couples counselling North Vancouver"
        info_kw = "how does birth order affect personality West Vancouver"
        data = {
            "organic_results": [
                _organic_row(service_kw, "https://a.com/x", 1),
                _organic_row(info_kw, "https://b.com/y", 1),
            ]
        }
        config = {
            "feasibility": {"client_da": 20, "neighborhoods": ["Lonsdale"],
                            "non_profit_location": "North Vancouver"},
            "analysis_report": {"client_domain": "livingsystems.ca"},
        }
        # No DA credentials → da_data_available stays False → No DA Data branch.
        with mock.patch.object(rf, "DATAFORSEO_AVAILABLE", False), \
             mock.patch.object(rf, "MOZ_AVAILABLE", False):
            rows = rf.run_feasibility_analysis(data, config, do_pivot_serp=False)
        by_kw = {r["Keyword"]: r for r in rows if r.get("Query_Label") == "A"}
        self.assertEqual(by_kw[service_kw]["feasibility_status"], "No DA Data")
        self.assertEqual(by_kw[info_kw]["all_variants"], [])
        self.assertTrue(by_kw[service_kw]["all_variants"])


class TestFetchFailureHonesty(unittest.TestCase):
    """B.2 — distinguish "measured: not in pack" from "could not measure"."""

    def _report(self, client_in_local_pack):
        primary = [{
            "Keyword": "couples counselling", "Query_Label": "A", "client_da": 20,
            "avg_serp_da": 90.0, "gap": 70.0, "feasibility_score": 0.0,
            "feasibility_status": "Low Feasibility",
            "pivot_status": "Pivoting to Hyper-Local",
            "suggested_keyword": "couples counselling Lonsdale",
            "all_variants": ["couples counselling Lonsdale"],
        }]
        pivot = [{
            "Keyword": "couples counselling Lonsdale", "Query_Label": "P",
            "Source_Keyword": "couples counselling", "client_da": 20,
            "avg_serp_da": None, "gap": None, "feasibility_score": None,
            "feasibility_status": "Not Measured" if client_in_local_pack is None else "Low Feasibility",
            "Client_In_Local_Pack": client_in_local_pack,
        }]
        return rf.generate_feasibility_report(primary + pivot, {}, "market_analysis_x.json")

    def test_b2_failed_fetch_renders_not_measured(self):
        report = self._report(client_in_local_pack=None)
        self.assertIn("not measured", report.lower())
        self.assertNotIn("✗ not in local pack", report)

    def test_b2_measured_absence_still_renders_x(self):
        report = self._report(client_in_local_pack=0)
        self.assertIn("✗ not in local pack", report)
        self.assertNotIn("not measured", report.lower())

    def test_b2_measured_presence_renders_check(self):
        report = self._report(client_in_local_pack=1)
        self.assertIn("✓ in local pack", report)


class TestSecretScrub(unittest.TestCase):
    """B.3 — API keys never reach a log line."""

    def test_b3_scrub_removes_serpapi_key_value(self):
        with mock.patch.dict("os.environ", {"SERPAPI_KEY": "SUPERSECRET123"}):
            out = rf._scrub_secrets("boom: https://serpapi.com/search?api_key=SUPERSECRET123&q=x")
        self.assertNotIn("SUPERSECRET123", out)
        self.assertIn("REDACTED", out)

    def test_b3_scrub_redacts_credential_params_generically(self):
        # Even if the concrete value isn't the env key, param names are redacted.
        out = rf._scrub_secrets("url?token=abc123&password=hunter2&q=ok")
        self.assertNotIn("abc123", out)
        self.assertNotIn("hunter2", out)
        self.assertIn("q=ok", out)

    def test_b3_failed_local_pack_fetch_logs_no_api_key(self):
        """A real failing request must not leak the key via the exception URL."""
        key = "LEAKY_KEY_9999"
        config = {"serpapi": {}}

        def _raise(*args, **kwargs):
            # Mimic requests raising with the full URL (incl. api_key) in the message.
            raise RuntimeError(
                "HTTPSConnectionPool: failed for url: "
                f"https://serpapi.com/search?api_key={key}&engine=google_maps&q=x"
            )

        with mock.patch.dict("os.environ", {"SERPAPI_KEY": key}), \
             mock.patch.object(rf, "REQUESTS_AVAILABLE", True), \
             mock.patch.object(rf._requests, "get", side_effect=_raise), \
             self.assertLogs(rf.logger, level="WARNING") as cm:
            rows, ok = rf._fetch_pivot_local_pack("couples counselling Lonsdale", config)

        self.assertEqual((rows, ok), ([], False))
        joined = "\n".join(cm.output)
        self.assertNotIn(key, joined)
        self.assertIn("REDACTED", joined)


class TestSecretScrubCoversEverySibling(unittest.TestCase):
    """P5 — hardening one provider's redaction and not its siblings.

    MOZ_TOKEN was absent from the scrub list while Moz exceptions were being
    logged through it (Spec: moz_api_upgrade_spec_v1.md#T.1).
    """

    def test_t1_scrub_redacts_every_credential_env_value(self):
        secrets = {
            "SERPAPI_KEY": "serp-VALUE-1111",
            "MOZ_TOKEN": "moz-VALUE-2222",
            "ANTHROPIC_API_KEY": "anthropic-VALUE-3333",
            "DATAFORSEO_PASSWORD": "dfs-VALUE-4444",
            "GEMINI_API_KEY": "gemini-VALUE-5555",
        }
        message = "failure: " + " ".join(secrets.values())
        with patch.dict(os.environ, secrets):
            out = rf._scrub_secrets(message)
        for name, value in secrets.items():
            self.assertNotIn(value, out, f"{name} leaked into the log line")

    def test_t1_moz_token_in_an_exception_is_redacted(self):
        token = "moz-token-LEAKY-7777"
        with patch.dict(os.environ, {"MOZ_TOKEN": token}):
            out = rf._scrub_secrets(
                RuntimeError(f"Moz API HTTP 401: invalid token {token}")
            )
        self.assertNotIn(token, out)
        self.assertIn("REDACTED", out)


class TestDomainToDaMapping(unittest.TestCase):
    """T.1 — both DA providers key results by URL; the domain must be parsed.

    `split('/')[0]` yielded "https:" for every DataForSEO key, collapsing the
    map onto one bogus entry so no competitor DA ever resolved.
    """

    def test_t1_extract_domain_handles_scheme_and_schemeless_keys(self):
        self.assertEqual(rf._extract_domain("https://www.example.com/a/b"), "example.com")
        self.assertEqual(rf._extract_domain("example.com/a/b"), "example.com")
        self.assertEqual(rf._extract_domain("http://example.com"), "example.com")

    def test_t1_extract_domain_does_not_strip_leading_w_characters(self):
        """`lstrip('www.')` strips characters, not a prefix: it turned
        "worldbank.org" into "orldbank.org"."""
        self.assertEqual(rf._extract_domain("https://worldbank.org/x"), "worldbank.org")
        self.assertEqual(rf._extract_domain("wattpad.com/x"), "wattpad.com")

    def test_t1_url_keyed_da_metrics_produce_a_real_avg_serp_da(self):
        """The mapping itself, not just the helper.

        Both DA providers key results by the caller's input URL. With
        `split('/')[0]` every key collapsed to "https:", no competitor domain
        resolved, and `avg_serp_da` came back None on every keyword — a
        silent total loss of feasibility scoring (learnings P25: the helper
        having a test says nothing about the loop that uses it).
        """
        data = {"organic_results": [
            {"Query_Label": "A", "Source_Keyword": "bowen theory",
             "Link": "https://www.psychologytoday.com/ca", "Rank": 1},
            {"Query_Label": "A", "Source_Keyword": "bowen theory",
             "Link": "https://goodtherapy.org/x", "Rank": 2},
        ]}
        config = {
            "moz": {},
            "feasibility": {"client_da": 35, "neighborhoods": [],
                            "non_profit_location": "X"},
            "analysis_report": {"client_domain": "livingsystems.ca"},
        }
        fake = mock.MagicMock()
        fake.get_moz_metrics.return_value = {
            "https://www.psychologytoday.com/ca": {"da": 90, "pa": 60},
            "https://goodtherapy.org/x": {"da": 70, "pa": 50},
        }
        fake_cls = mock.MagicMock()
        fake_cls.from_config.return_value = fake
        env = {"MOZ_TOKEN": "t", "DATAFORSEO_LOGIN": "", "DATAFORSEO_PASSWORD": ""}
        with patch.dict(os.environ, env), \
                mock.patch.object(rf, "MozClient", fake_cls), \
                mock.patch.object(rf, "MOZ_AVAILABLE", True), \
                mock.patch.object(rf, "DATAFORSEO_AVAILABLE", False):
            rows = rf.run_feasibility_analysis(data, config, do_pivot_serp=False)

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["avg_serp_da"], 80.0,
            "competitor DA did not resolve — the domain map dropped every URL",
        )

    def test_t1_scheme_bearing_keys_resolve_to_distinct_domains(self):
        """The DataForSEO key format must not collapse onto a single entry."""
        keys = [
            "https://www.psychologytoday.com/ca",
            "https://livingsystems.ca/therapy",
        ]
        domains = {rf._extract_domain(k) for k in keys}
        self.assertEqual(domains, {"psychologytoday.com", "livingsystems.ca"})
        self.assertNotIn("https:", domains)


if __name__ == "__main__":
    unittest.main()
