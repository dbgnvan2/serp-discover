"""
Tests for the Bing secondary-index check.

Spec: seo_geo_deferred_spec_v1.md#G.5
- G.5.1 disabled by default: zero Bing calls (mock-based test).
- G.5.2 parser test against a committed Bing fixture: client rank found;
  client absent -> client_rank None with checked True.
- G.5.3 one call per root keyword when enabled, routed through the
  standard retry path (serp_audit._fetch_serp_api).
- G.5.4 the block is top-level (bing_visibility) — payload passthrough,
  canary unaffected (verified by the full suite staying green).
"""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import yaml

import bing_check
import serp_audit
from brief_data_extraction import (
    _build_bing_visibility,
    extract_analysis_data_from_json,
)
from brief_prompts import build_main_report_payload

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "bing_serp_sample.json")


def _load_fixture():
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _run_checks(keywords, response, enabled=True, num=20):
    """Run bing_check.run_bing_checks with a mocked fetch; returns
    (rows, fetch_mock, printed_output)."""
    fetch = MagicMock(return_value=response)
    with patch.object(bing_check, "_save_raw_bing"):
        with redirect_stdout(io.StringIO()) as out:
            rows = bing_check.run_bing_checks(
                keywords, "test_run",
                enabled=enabled, num=num,
                location="Vancouver, British Columbia, Canada",
                force_local=True,
                fetch_fn=fetch,
                apply_no_cache=lambda p: p,
                api_key="KEY",
                client_domain="livingsystems.ca",
                request_delay=0,
            )
    return rows, fetch, out.getvalue()


class TestDisabledByDefault(unittest.TestCase):
    """G.5.1 — default OFF (gate D-4): zero Bing calls."""

    def test_config_yml_default_is_disabled(self):
        with open(os.path.join(_REPO_ROOT, "config.yml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("bing_check", cfg)
        self.assertFalse(cfg["bing_check"]["enabled"])
        self.assertEqual(cfg["bing_check"]["num"], 20)

    def test_serp_audit_flag_default_off(self):
        self.assertFalse(serp_audit.BING_CHECK_ENABLED)

    def test_disabled_makes_zero_calls(self):
        rows, fetch, output = _run_checks(["kw one", "kw two"],
                                          _load_fixture(), enabled=False)
        self.assertEqual(fetch.call_count, 0)
        self.assertEqual(rows, [])
        self.assertIn("Bing check: disabled (0 SerpAPI calls)", output)


class TestParser(unittest.TestCase):
    """G.5.2 — parser against the committed fixture."""

    def test_client_rank_found(self):
        result = bing_check.parse_bing_visibility(_load_fixture(),
                                                  "livingsystems.ca")
        self.assertTrue(result["checked"])
        self.assertEqual(result["client_rank"], 5)
        self.assertEqual(result["client_url"],
                         "https://www.livingsystems.ca/family-counselling/")
        self.assertEqual(result["top3_domains"],
                         ["psychologytoday.com", "skylarkclinic.ca",
                          "counsellingbc.com"])

    def test_client_absent_yields_none_with_checked_true(self):
        fixture = _load_fixture()
        fixture["organic_results"] = [
            item for item in fixture["organic_results"]
            if "livingsystems" not in item["link"]
        ]
        result = bing_check.parse_bing_visibility(fixture, "livingsystems.ca")
        self.assertTrue(result["checked"])
        self.assertIsNone(result["client_rank"])
        self.assertIsNone(result["client_url"])
        self.assertEqual(len(result["top3_domains"]), 3)

    def test_subdomain_counts_as_client(self):
        fixture = {"organic_results": [
            {"position": 1, "title": "t",
             "link": "https://blog.livingsystems.ca/post"},
        ]}
        result = bing_check.parse_bing_visibility(fixture, "livingsystems.ca")
        self.assertEqual(result["client_rank"], 1)

    def test_empty_or_malformed_response(self):
        for response in ({}, {"organic_results": []},
                         {"organic_results": ["not-a-dict"]}):
            result = bing_check.parse_bing_visibility(response,
                                                      "livingsystems.ca")
            self.assertTrue(result["checked"])
            self.assertIsNone(result["client_rank"])
            self.assertEqual(result["top3_domains"], [])


class TestRunChecks(unittest.TestCase):
    """G.5.3 — one call per root keyword, standard retry path."""

    def test_one_call_per_root_keyword(self):
        keywords = ["kw one", "kw two", "kw three"]
        rows, fetch, output = _run_checks(keywords, _load_fixture())
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len(rows), 3)
        for call in fetch.call_args_list:
            params = call[0][0]
            self.assertEqual(params["engine"], "bing")
            self.assertEqual(params["count"], 20)
        self.assertIn("Bing check: 3 SerpAPI calls (3 root keywords)", output)

    def test_query_text_mirrors_label_a_query(self):
        rows, fetch, _ = _run_checks(["family counselling"], _load_fixture())
        params = fetch.call_args_list[0][0][0]
        # force_local appends the location, exactly like the Google A query.
        self.assertEqual(params["q"],
                         "family counselling Vancouver, British Columbia, Canada")
        self.assertEqual(rows[0]["Executed_Query"], params["q"])

    def test_row_shape_and_client_rank(self):
        rows, _, _ = _run_checks(["family counselling"], _load_fixture())
        row = rows[0]
        self.assertEqual(row["Source_Keyword"], "family counselling")
        self.assertEqual(row["Query_Label"], "A")
        self.assertTrue(row["Checked"])
        self.assertEqual(row["Client_Rank"], 5)
        self.assertEqual(len(row["Top3_Domains"]), 3)

    def test_failed_fetch_yields_checked_false(self):
        rows, fetch, _ = _run_checks(["kw"], None)
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(rows[0]["Checked"])
        self.assertIsNone(rows[0]["Client_Rank"])

    def test_serp_audit_routes_through_standard_retry_wrapper(self):
        # The pipeline binds fetch_fn=serp_audit._fetch_serp_api — the
        # standard SerpAPI retry wrapper — via bing_check.run_bing_checks.
        with patch.object(serp_audit, "BING_CHECK_ENABLED", True), \
             patch.object(serp_audit, "REQUEST_DELAY_SECONDS", 0), \
             patch.object(bing_check, "_save_raw_bing"), \
             patch.object(serp_audit, "_fetch_serp_api",
                          return_value=_load_fixture()) as mock_fetch:
            with redirect_stdout(io.StringIO()):
                rows = bing_check.run_bing_checks(
                    ["kw one", "kw two"], "test_run",
                    enabled=serp_audit.BING_CHECK_ENABLED,
                    num=serp_audit.BING_CHECK_NUM,
                    location=serp_audit.LOCATION,
                    force_local=serp_audit.FORCE_LOCAL_INTENT,
                    fetch_fn=serp_audit._fetch_serp_api,
                    apply_no_cache=serp_audit._apply_no_cache,
                    api_key="KEY",
                    client_domain="livingsystems.ca",
                    request_delay=serp_audit.REQUEST_DELAY_SECONDS,
                )
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(len(rows), 2)


class TestExtraction(unittest.TestCase):
    """bing_visibility block: per-keyword records + run summary."""

    def _rows(self):
        return [
            {"Source_Keyword": "kw one", "Checked": True, "Client_Rank": 5,
             "Client_URL": "https://www.livingsystems.ca/x",
             "Top3_Domains": ["a.com", "b.com", "c.com"]},
            {"Source_Keyword": "kw two", "Checked": True, "Client_Rank": None,
             "Client_URL": None, "Top3_Domains": ["a.com"]},
            {"Source_Keyword": "kw three", "Checked": False,
             "Client_Rank": None, "Client_URL": None, "Top3_Domains": []},
        ]

    def test_by_keyword_and_summary(self):
        block = _build_bing_visibility(self._rows(),
                                       ["kw one", "kw two", "kw three", "kw four"])
        self.assertTrue(block["data_available"])
        self.assertEqual(block["by_keyword"]["kw one"]["client_rank"], 5)
        self.assertIsNone(block["by_keyword"]["kw two"]["client_rank"])
        self.assertFalse(block["by_keyword"]["kw three"]["checked"])
        # Unchecked keyword filled in honestly, never guessed.
        self.assertFalse(block["by_keyword"]["kw four"]["checked"])
        self.assertEqual(block["summary"],
                         {"keywords_checked": 2, "client_visible_count": 1})

    def test_old_json_without_bing_rows(self):
        data = {
            "overview": [{
                "Run_ID": "r1", "Created_At": "2026-07-01T12:00:00",
                "Source_Keyword": "family counselling", "Query_Label": "A",
                "Executed_Query": "family counselling", "Total_Results": 1000,
            }],
            "organic_results": [],
            # No bing_visibility key at all (pre-G.5 JSON).
        }
        extracted = extract_analysis_data_from_json(data, "livingsystems.ca")
        block = extracted["bing_visibility"]
        self.assertFalse(block["data_available"])
        self.assertFalse(block["by_keyword"]["family counselling"]["checked"])
        self.assertEqual(block["summary"]["keywords_checked"], 0)

    def test_payload_passthrough(self):
        extracted = {"bing_visibility": {
            "data_available": True,
            "by_keyword": {"kw": {"checked": True, "client_rank": 4}},
            "summary": {"keywords_checked": 1, "client_visible_count": 1},
        }}
        payload = build_main_report_payload(extracted)
        self.assertEqual(
            payload["bing_visibility"]["by_keyword"]["kw"]["client_rank"], 4)


if __name__ == "__main__":
    unittest.main()
