"""
Tests for the Google Search Console integration (gsc_client.py +
run_gsc_analysis.py). All HTTP is mocked; no credentials needed.

Spec: seo_geo_deferred_spec_v1.md#G.4 (decision gate D-3)
- G.4.1 auth header construction, request batching (pagination), cache
  hit/miss, and the bound-variable batching on cache lookups (patterns
  from test_dataforseo_client.py).
- G.4.2 sponge computation on synthetic data with known medians, and the
  <3-queries insufficient-data path.
- G.4.3 reformat_candidates intersects with strategic_flags.geo_alerts.
- G.4.4 disabled / no-credentials runs exit with a clear message and zero
  API calls; the main pipeline never imports gsc_client.
- G.4.5 outputs follow the gitignored gsc_analysis_* naming glob.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import yaml

import gsc_client
import run_gsc_analysis as rga
from gsc_client import GscClient

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gsc_response(rows):
    """Mock a Search Analytics API response with the given row dicts."""
    response = MagicMock(ok=True)
    response.json.return_value = {"rows": rows}
    return response


def _api_row(query, clicks=10, impressions=100, ctr=0.1, position=3.0):
    return {"keys": [query], "clicks": clicks, "impressions": impressions,
            "ctr": ctr, "position": position}


class TestGscClientAuthAndBatching(unittest.TestCase):
    """G.4.1 — auth header, pagination, and request shape."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.client = GscClient(
            "sc-domain:livingsystems.ca", db_path=self.tmp.name,
            token_provider=lambda: "tok123")

    def tearDown(self):
        os.unlink(self.tmp.name)

    @patch("gsc_client.requests.post")
    def test_bearer_auth_header_and_payload(self, mock_post):
        mock_post.return_value = _gsc_response([_api_row("family counselling")])
        result = self.client.get_query_stats(
            ["family counselling"], "2026-04-01", "2026-07-01")
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer tok123")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["dimensions"], ["query"])
        self.assertEqual(payload["startDate"], "2026-04-01")
        self.assertEqual(payload["endDate"], "2026-07-01")
        # Property is URL-encoded into the endpoint path.
        self.assertIn("sc-domain%3Alivingsystems.ca", mock_post.call_args.args[0])
        self.assertEqual(result["family counselling"]["clicks"], 10)

    @patch("gsc_client.requests.post")
    def test_pagination_batches_until_short_page(self, mock_post):
        with patch.object(gsc_client, "ROW_LIMIT", 2):
            mock_post.side_effect = [
                _gsc_response([_api_row("q one"), _api_row("q two")]),
                _gsc_response([_api_row("q three")]),
            ]
            result = self.client.get_query_stats(
                ["q one", "q two", "q three"], "2026-04-01", "2026-07-01")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[0].kwargs["json"]["startRow"], 0)
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["startRow"], 2)
        self.assertEqual(len(result), 3)

    @patch("gsc_client.requests.post")
    def test_matching_is_case_insensitive(self, mock_post):
        mock_post.return_value = _gsc_response([_api_row("family counselling")])
        result = self.client.get_query_stats(
            ["Family Counselling"], "2026-04-01", "2026-07-01")
        self.assertIn("family counselling", result)

    @patch("gsc_client.requests.post")
    def test_http_error_returns_empty_not_fake_zeros(self, mock_post):
        response = MagicMock(ok=False, status_code=403)
        response.json.return_value = {"error": "forbidden"}
        mock_post.return_value = response
        result = self.client.get_query_stats(["q"], "2026-04-01", "2026-07-01")
        self.assertEqual(result, {})

    def test_missing_credentials_raise_clear_error(self):
        env = {k: v for k, v in os.environ.items() if k != "GSC_CREDENTIALS_PATH"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                GscClient("sc-domain:livingsystems.ca", db_path=self.tmp.name)
        self.assertIn("GSC_CREDENTIALS_PATH", str(ctx.exception))


class TestGscClientCache(unittest.TestCase):
    """G.4.1 — 7-day cache hit/miss and IN(...) lookup batching (C.7)."""

    START, END = "2026-04-01", "2026-07-01"

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.client = GscClient(
            "sc-domain:livingsystems.ca", db_path=self.tmp.name,
            token_provider=lambda: "tok")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_cache_table_created(self):
        with sqlite3.connect(self.tmp.name) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("gsc_cache", tables)

    @patch("gsc_client.requests.post")
    def test_cache_hit_avoids_http_call(self, mock_post):
        self.client._cache_store(
            {"family counselling": {"clicks": 5, "impressions": 50,
                                    "ctr": 0.1, "position": 4.0}},
            self.START, self.END)
        result = self.client.get_query_stats(
            ["family counselling"], self.START, self.END)
        mock_post.assert_not_called()
        self.assertEqual(result["family counselling"]["clicks"], 5)

    @patch("gsc_client.requests.post")
    def test_cached_absence_avoids_refetch(self, mock_post):
        # A query GSC had no row for is cached with found=0 and omitted —
        # measured absence, no re-pull inside the TTL, no fabricated zeros.
        self.client._cache_store({"unseen query": None}, self.START, self.END)
        result = self.client.get_query_stats(["unseen query"], self.START, self.END)
        mock_post.assert_not_called()
        self.assertEqual(result, {})

    @patch("gsc_client.requests.post")
    def test_expired_cache_triggers_api_call(self, mock_post):
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(
                "INSERT INTO gsc_cache VALUES (?,?,?,?,?,?,?,?,?)",
                ("family counselling", self.START, self.END, 1, 10, 0.1, 5.0, 1, old))
        mock_post.return_value = _gsc_response([_api_row("family counselling", clicks=7)])
        result = self.client.get_query_stats(
            ["family counselling"], self.START, self.END)
        mock_post.assert_called_once()
        self.assertEqual(result["family counselling"]["clicks"], 7)

    @patch("gsc_client.requests.post")
    def test_different_date_range_is_a_cache_miss(self, mock_post):
        self.client._cache_store(
            {"q": {"clicks": 5, "impressions": 50, "ctr": 0.1, "position": 4.0}},
            self.START, self.END)
        mock_post.return_value = _gsc_response([_api_row("q", clicks=9)])
        result = self.client.get_query_stats(["q"], "2026-01-01", "2026-03-31")
        mock_post.assert_called_once()
        self.assertEqual(result["q"]["clicks"], 9)

    @patch("gsc_client.requests.post")
    def test_cache_lookup_batches_bound_variables(self, mock_post):
        # 1200 queries exceed SQLite's historic 999-bound-variable cap; the
        # lookup must chunk (500 per IN(...)) and still resolve everything
        # (pattern: dataforseo_client._cache_lookup, seo_geo_review C.7).
        queries = [f"query number {i}" for i in range(1200)]
        self.client._cache_store(
            {q: {"clicks": 1, "impressions": 10, "ctr": 0.1, "position": 2.0}
             for q in queries},
            self.START, self.END)
        result = self.client.get_query_stats(queries, self.START, self.END)
        mock_post.assert_not_called()
        self.assertEqual(len(result), 1200)

    @patch("gsc_client.requests.post")
    def test_partial_cache_fetches_only_missing(self, mock_post):
        self.client._cache_store(
            {"cached q": {"clicks": 5, "impressions": 50, "ctr": 0.1, "position": 4.0}},
            self.START, self.END)
        mock_post.return_value = _gsc_response([_api_row("fresh q")])
        result = self.client.get_query_stats(
            ["cached q", "fresh q"], self.START, self.END)
        mock_post.assert_called_once()
        self.assertIn("cached q", result)
        self.assertIn("fresh q", result)
        # And the freshly fetched row is now cached for next time.
        mock_post.reset_mock()
        self.client.get_query_stats(["fresh q"], self.START, self.END)
        mock_post.assert_not_called()


class TestSpongeComputation(unittest.TestCase):
    """G.4.2 — known medians on synthetic data; insufficient-data path."""

    @staticmethod
    def _row(query, position, ctr, has_aio, found=True):
        return {"query": query, "query_label": "A", "source_keyword": query,
                "position": position, "ctr": ctr, "has_ai_overview": has_aio,
                "found": found, "clicks": 1, "impressions": 10}

    def test_known_medians_both_buckets(self):
        rows = [
            # AIO bucket in band 1-3: CTRs 0.02, 0.03, 0.10 → median 0.03
            self._row("a1", 1.0, 0.02, True),
            self._row("a2", 2.0, 0.03, True),
            self._row("a3", 3.0, 0.10, True),
            # No-AIO bucket in band 1-3: CTRs 0.06, 0.08, 0.12 → median 0.08
            self._row("n1", 1.5, 0.06, False),
            self._row("n2", 2.5, 0.08, False),
            self._row("n3", 3.0, 0.12, False),
        ]
        sponge = rga.compute_sponge_effect(rows)
        band = sponge["bands"][0]
        self.assertTrue(band["sufficient"])
        self.assertEqual(band["aio_median_ctr"], 0.03)
        self.assertEqual(band["no_aio_median_ctr"], 0.08)
        self.assertEqual(band["ctr_delta"], -0.05)
        self.assertTrue(sponge["data_available"])

    def test_insufficient_data_path(self):
        rows = [
            self._row("a1", 1.0, 0.02, True),
            self._row("a2", 2.0, 0.03, True),   # only 2 AIO queries (< 3)
            self._row("n1", 1.5, 0.06, False),
            self._row("n2", 2.5, 0.08, False),
            self._row("n3", 3.0, 0.12, False),
        ]
        sponge = rga.compute_sponge_effect(rows)
        band = sponge["bands"][0]
        self.assertFalse(band["sufficient"])
        self.assertIsNone(band["aio_median_ctr"])
        self.assertIsNone(band["ctr_delta"])
        # No-AIO median still computed (anchors reformat candidates).
        self.assertEqual(band["no_aio_median_ctr"], 0.08)
        self.assertFalse(sponge["data_available"])
        # The report states insufficient data rather than guessing.
        report = rga.generate_report(
            rows, sponge, [], {"gsc": {"property": "x"}},
            "market_analysis_x.json", ("2026-04-01", "2026-07-01"))
        self.assertIn("insufficient data", report)

    def test_unknown_aio_state_and_missing_data_excluded(self):
        rows = [
            self._row("paa", 2.0, 0.5, None),           # AIO unknown (PAA)
            self._row("gone", 2.0, 0.5, True, found=False),  # no GSC data
        ]
        sponge = rga.compute_sponge_effect(rows)
        self.assertEqual(sponge["bands"][0]["aio_query_count"], 0)
        self.assertEqual(sponge["bands"][0]["no_aio_query_count"], 0)


class TestReformatCandidates(unittest.TestCase):
    """G.4.3 — geo_alerts cross-reference."""

    def _fixture_rows(self):
        rows = [
            # Enough no-AIO queries in band 1-3 for the median (0.08).
            {"query": "n1", "query_label": "A", "source_keyword": "kw n1",
             "position": 1.5, "ctr": 0.06, "has_ai_overview": False, "found": True},
            {"query": "n2", "query_label": "A", "source_keyword": "kw n2",
             "position": 2.5, "ctr": 0.08, "has_ai_overview": False, "found": True},
            {"query": "n3", "query_label": "A", "source_keyword": "kw n3",
             "position": 3.0, "ctr": 0.12, "has_ai_overview": False, "found": True},
            # Candidate 1: good position, CTR below the no-AIO median,
            # source keyword carries a GEO alert.
            {"query": "family counselling north vancouver", "query_label": "A",
             "source_keyword": "family counselling north vancouver",
             "position": 2.0, "ctr": 0.01, "has_ai_overview": True, "found": True},
            # Candidate 2: below-median CTR but NOT geo-alerted.
            {"query": "grief counselling", "query_label": "A",
             "source_keyword": "grief counselling",
             "position": 3.0, "ctr": 0.02, "has_ai_overview": True, "found": True},
            # Not a candidate: position too deep.
            {"query": "deep query", "query_label": "A", "source_keyword": "deep",
             "position": 15.0, "ctr": 0.001, "has_ai_overview": True, "found": True},
        ]
        return rows

    def test_intersection_with_geo_alerts(self):
        rows = self._fixture_rows()
        sponge = rga.compute_sponge_effect(rows)
        candidates = rga.find_reformat_candidates(
            rows, sponge, {"family counselling north vancouver"})
        queries = {c["query"]: c for c in candidates}
        self.assertIn("family counselling north vancouver", queries)
        self.assertTrue(queries["family counselling north vancouver"]["geo_alert"])
        self.assertIn("grief counselling", queries)
        self.assertFalse(queries["grief counselling"]["geo_alert"])
        self.assertNotIn("deep query", queries)
        # Geo-alerted candidates sort first.
        self.assertEqual(candidates[0]["query"], "family counselling north vancouver")

    def test_geo_alert_keywords_from_strategic_flags(self):
        data = {"strategic_flags": {"geo_alerts": [
            {"keyword": "family counselling north vancouver", "detail": "x"}]}}
        self.assertEqual(rga.geo_alert_keywords(data),
                         {"family counselling north vancouver"})

    def test_geo_alert_keywords_derived_from_profiles(self):
        data = {"keyword_profiles": {
            "kw a": {"aio_divergence": {"client_ranks_but_not_cited": True}},
            "kw b": {"aio_divergence": {"client_ranks_but_not_cited": False}},
        }}
        self.assertEqual(rga.geo_alert_keywords(data), {"kw a"})


class TestQueryCollection(unittest.TestCase):
    """Root keywords + A.1/A.2/S variants + top PAA phrasings, AIO joined."""

    def test_collects_all_sources_with_aio_flags(self):
        data = {
            "overview": [
                {"Query_Label": "A", "Source_Keyword": "kw",
                 "Executed_Query": "kw", "Has_Main_AI_Overview": True},
                {"Query_Label": "A.1", "Source_Keyword": "kw",
                 "Executed_Query": "how to choose kw?", "Has_Main_AI_Overview": False},
                {"Query_Label": "B", "Source_Keyword": "kw",
                 "Executed_Query": "excluded label"},
            ],
            "situational_probes": [
                {"Executed_Query": "my partner refuses kw what do I do",
                 "Source_Keyword": "kw", "Has_AI_Overview": True},
            ],
            "paa_questions": [
                {"Question": "What is kw?", "Source_Keyword": "kw"},
            ],
        }
        rows = rga.collect_queries(data)
        by_label = {r["query_label"]: r for r in rows}
        self.assertEqual(set(by_label), {"A", "A.1", "S", "PAA"})
        self.assertTrue(by_label["A"]["has_ai_overview"])
        self.assertFalse(by_label["A.1"]["has_ai_overview"])
        self.assertTrue(by_label["S"]["has_ai_overview"])
        self.assertIsNone(by_label["PAA"]["has_ai_overview"])

    def test_paa_capped(self):
        data = {"paa_questions": [
            {"Question": f"Question number {i} about counselling?"} for i in range(50)]}
        rows = rga.collect_queries(data, max_paa=20)
        self.assertEqual(len(rows), 20)


class TestDisabledAndIsolation(unittest.TestCase):
    """G.4.4 — clear message + zero calls when disabled; pipeline isolation."""

    def test_config_yml_default_is_disabled(self):
        with open(os.path.join(_REPO_ROOT, "config.yml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("gsc", cfg)
        self.assertFalse(cfg["gsc"]["enabled"])
        self.assertEqual(cfg["gsc"]["property"], "sc-domain:livingsystems.ca")
        self.assertEqual(cfg["gsc"]["lookback_days"], 90)
        self.assertFalse(cfg["gsc"]["feed_strategic_flags"])

    def test_disabled_run_exits_with_message_and_zero_calls(self):
        printed = []
        with patch.object(rga, "_load_config",
                          return_value={"gsc": {"enabled": False}}):
            with patch("gsc_client.requests.post") as mock_post:
                with patch("builtins.print",
                           side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
                    exit_code = rga.main([])
        self.assertEqual(exit_code, 0)
        mock_post.assert_not_called()
        self.assertIn("disabled", "\n".join(printed))
        self.assertIn("0 API calls", "\n".join(printed))

    def test_no_credentials_exits_with_message_and_zero_calls(self):
        env = {k: v for k, v in os.environ.items() if k != "GSC_CREDENTIALS_PATH"}
        printed = []
        with patch.dict(os.environ, env, clear=True):
            with patch.object(rga, "_load_config",
                              return_value={"gsc": {"enabled": True}}):
                with patch.object(rga, "_load_env"):
                    with patch("gsc_client.requests.post") as mock_post:
                        with patch("builtins.print",
                                   side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
                            exit_code = rga.main([])
        self.assertEqual(exit_code, 0)
        mock_post.assert_not_called()
        self.assertIn("GSC_CREDENTIALS_PATH", "\n".join(printed))

    def test_pipeline_never_imports_gsc_client(self):
        # Import-time isolation: importing the pipeline modules must not
        # pull in gsc_client (G.4.4).
        for module in ("gsc_client", "run_gsc_analysis", "gsc_demand"):
            sys.modules.pop(module, None)
        import serp_audit  # noqa: F401
        import generate_content_brief  # noqa: F401
        import brief_rendering  # noqa: F401
        self.assertNotIn("gsc_client", sys.modules)
        self.assertNotIn("run_gsc_analysis", sys.modules)
        self.assertNotIn("gsc_demand", sys.modules)   # D2: GSC-path only, not pipeline

    def test_pipeline_sources_have_no_gsc_client_import(self):
        for module in ("serp_audit.py", "generate_content_brief.py",
                       "brief_data_extraction.py", "brief_rendering.py",
                       "run_pipeline.py"):
            with open(os.path.join(_REPO_ROOT, module), encoding="utf-8") as f:
                source = f.read()
            self.assertNotIn("import gsc_client", source,
                             f"{module} must not import gsc_client")
            self.assertNotIn("from gsc_client", source,
                             f"{module} must not import gsc_client")
            self.assertNotIn("import gsc_demand", source,
                             f"{module} must not import gsc_demand (GSC-path only)")
            self.assertNotIn("from gsc_demand", source,
                             f"{module} must not import gsc_demand (GSC-path only)")


class TestEndToEndRun(unittest.TestCase):
    """G.4.5 — outputs follow the gitignored naming glob; sidecar shape."""

    def _run(self, tmpdir):
        data = {
            "overview": [
                {"Query_Label": "A", "Source_Keyword": "kw one",
                 "Executed_Query": "kw one", "Has_Main_AI_Overview": True},
                {"Query_Label": "A", "Source_Keyword": "kw two",
                 "Executed_Query": "kw two", "Has_Main_AI_Overview": False},
            ],
            "strategic_flags": {"geo_alerts": [{"keyword": "kw one"}]},
        }
        json_path = os.path.join(tmpdir, "market_analysis_topic_20260701_1200.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        config = {
            "gsc": {"enabled": True, "property": "sc-domain:livingsystems.ca",
                    "lookback_days": 90, "cache_ttl_days": 7},
            "analysis_report": {"client_name": "Living Systems Counselling"},
        }
        client = MagicMock()
        client.get_query_stats.return_value = {
            "kw one": {"clicks": 2, "impressions": 100, "ctr": 0.02, "position": 3.2},
        }
        report, sidecar = rga.run_analysis(
            data, config, client, json_path, today=date(2026, 7, 4))
        return report, sidecar, client

    def test_run_analysis_report_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report, sidecar, client = self._run(tmpdir)
        client.get_query_stats.assert_called_once()
        # Lookback window computed from config (90 days back from today).
        args = client.get_query_stats.call_args.args
        self.assertEqual(args[1], "2026-04-05")
        self.assertEqual(args[2], "2026-07-04")
        self.assertIn("kw one", report)
        self.assertIn("no GSC data", report)          # measured absence stated
        self.assertIn("never quote them", report)     # private-data note
        self.assertEqual(sidecar["queries_checked"], 2)
        self.assertEqual(sidecar["queries_with_data"], 1)
        self.assertIn("sponge", sidecar)
        self.assertIn("reformat_candidates", sidecar)

    def test_output_base_matches_gitignored_glob(self):
        base = rga._derive_output_base("market_analysis_leila_20260504_2020.json")
        self.assertTrue(base.startswith("gsc_analysis_leila_"))
        with open(os.path.join(_REPO_ROOT, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("gsc_analysis_*", f.read())


class TestGscSummaryFeedForward(unittest.TestCase):
    """Optional gsc_summary payload block (config-gated, G.4 item 3)."""

    SIDECAR = {
        "generated_at": "2026-07-04T10:00:00",
        "source_analysis": "market_analysis_x.json",
        "lookback_days": 90,
        "date_range": {"start": "2026-04-05", "end": "2026-07-04"},
        "queries_checked": 5,
        "queries_with_data": 3,
        "per_query": [
            {"query": "q1", "query_label": "A", "found": True, "clicks": 5,
             "impressions": 200, "ctr": 0.025, "position": 3.0,
             "has_ai_overview": True},
            {"query": "q2", "query_label": "A", "found": False},
        ],
        "sponge": {"data_available": False, "min_bucket_size": 3, "bands": []},
        "reformat_candidates": [{"query": "q1", "geo_alert": True}],
    }

    def test_build_gsc_summary_compacts_sidecar(self):
        from brief_data_extraction import _build_gsc_summary
        summary = _build_gsc_summary(self.SIDECAR)
        self.assertEqual(summary["queries_with_data"], 3)
        self.assertEqual(summary["reformat_candidates"][0]["query"], "q1")
        self.assertEqual(len(summary["top_queries"]), 1)  # found rows only
        self.assertIsNone(_build_gsc_summary(None))

    def test_payload_passthrough(self):
        from brief_prompts import build_main_report_payload
        from brief_data_extraction import _build_gsc_summary
        payload = build_main_report_payload(
            {"gsc_summary": _build_gsc_summary(self.SIDECAR)})
        self.assertIsNotNone(payload["gsc_summary"])
        self.assertEqual(payload["gsc_summary"]["lookback_days"], 90)
        # Absent by default (feed off / no sidecar): key present, value None.
        self.assertIsNone(build_main_report_payload({})["gsc_summary"])

    def test_find_latest_gsc_sidecar(self):
        from brief_data_extraction import find_latest_gsc_sidecar
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(find_latest_gsc_sidecar(tmpdir), (None, None))
            older = os.path.join(tmpdir, "gsc_analysis_a_20260601_1000.json")
            newer = os.path.join(tmpdir, "gsc_analysis_a_20260704_1000.json")
            with open(older, "w", encoding="utf-8") as f:
                json.dump({"generated_at": "old"}, f)
            with open(newer, "w", encoding="utf-8") as f:
                json.dump({"generated_at": "new"}, f)
            os.utime(older, (1, 1))
            path, data = find_latest_gsc_sidecar(tmpdir)
        self.assertEqual(path, newer)
        self.assertEqual(data["generated_at"], "new")

    def test_prompt_documents_private_data_hard_rule(self):
        with open(os.path.join(_REPO_ROOT, "prompts", "main_report", "system.md"),
                  encoding="utf-8") as f:
            system_prompt = f.read()
        self.assertIn("gsc_summary", system_prompt)
        self.assertIn("PRIVATE", system_prompt)
        self.assertIn("NEVER as market-level claims", system_prompt)


if __name__ == "__main__":
    unittest.main()
