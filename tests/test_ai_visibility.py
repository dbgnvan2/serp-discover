"""
Tests for AI-engine mention probing (probe_ai_visibility.py).

Spec: seo_geo_deferred_spec_v1.md#G.1 (decision gate D-2)
- G.1.1 all API calls mocked; detection verified for mentioned-only,
  cited, neither, and competitor-cited answers.
- G.1.2 table created idempotently; rows written with UTC run_ts and
  engine; per-engine trend query returns runs in order.
- G.1.3 no calls without explicit confirmation; exit message states
  questions x engines.
- G.1.4 engine selection honored (--engines claude runs only ClaudeProbe);
  missing GEMINI_API_KEY skips Gemini with a warning while Claude
  completes; unknown engine names error listing valid options.
- G.1.5 report renders with zero prior history and with history;
  per-engine rates; caveat paragraph always present.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

import probe_ai_visibility as pav

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _analysis_fixture():
    """Minimal market_analysis data with situational probes and PAA rows."""
    return {
        "overview": [
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver",
             "Executed_Query": "family counselling north vancouver"},
        ],
        "organic_results": [
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver",
             "Rank": 1, "Link": "https://www.psychologytoday.com/ca/x"},
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver",
             "Rank": 2, "Link": "https://livingsystems.ca/services"},
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver",
             "Rank": 3, "Link": "https://wellbeings.ca/about"},
        ],
        "situational_probes": [
            {"Executed_Query": "my partner refuses to try counselling what can I do"},
            {"Executed_Query": "how do I know if we actually need family counselling"},
        ],
        "paa_questions": [
            {"Question": "What is family systems therapy and how does it work?"},
            {"Question": "Costs?"},
        ],
    }


class TestConfigDefaults(unittest.TestCase):
    """Gate D-2 defaults live in config.yml."""

    def test_config_yml_ai_visibility_block(self):
        with open(os.path.join(_REPO_ROOT, "config.yml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("ai_visibility", cfg)
        av = cfg["ai_visibility"]
        # Gate Y-D9 (user-approved) engine defaults for this client:
        # gemini + openai + perplexity ON; claude available-but-not-default.
        self.assertEqual(av["engines"], ["gemini", "openai", "perplexity"])
        self.assertEqual(av["max_questions"], 20)
        self.assertFalse(av["assume_yes"])
        # Model ids come from config, never hardcoded in call sites.
        self.assertIn("claude_model", av)
        self.assertIn("gemini_model", av)
        self.assertIn("openai_model", av)
        self.assertIn("perplexity_model", av)

    def test_gitignore_covers_report_glob(self):
        with open(os.path.join(_REPO_ROOT, ".gitignore"), encoding="utf-8") as f:
            gitignore = f.read()
        self.assertIn("ai_visibility_*", gitignore)


class TestDetection(unittest.TestCase):
    """G.1.1 — detection logic for the four answer shapes."""

    PATTERNS = ["Living Systems"]
    DOMAIN = "livingsystems.ca"
    COMPETITORS = ["psychologytoday.com", "wellbeings.ca"]

    def _detect(self, text, urls):
        return pav.detect_visibility(text, urls, self.PATTERNS, self.DOMAIN, self.COMPETITORS)

    def test_mentioned_only(self):
        result = self._detect(
            "Living Systems Counselling in North Vancouver offers Bowen therapy.",
            ["https://example.com/directory"])
        self.assertTrue(result["mentioned"])
        self.assertFalse(result["cited"])
        self.assertEqual(result["competitors_cited"], [])

    def test_cited(self):
        result = self._detect(
            "Several local nonprofits offer counselling.",
            ["https://www.livingsystems.ca/services/"])
        self.assertFalse(result["mentioned"])
        self.assertTrue(result["cited"])

    def test_neither(self):
        result = self._detect(
            "Counselling BC lists many therapists.",
            ["https://counsellingbc.com/listings"])
        self.assertFalse(result["mentioned"])
        self.assertFalse(result["cited"])
        self.assertEqual(result["competitors_cited"], [])

    def test_competitor_cited(self):
        result = self._detect(
            "Psychology Today has a directory of therapists.",
            ["https://www.psychologytoday.com/ca/therapists",
             "https://wellbeings.ca/team"])
        self.assertEqual(result["competitors_cited"],
                         ["psychologytoday.com", "wellbeings.ca"])
        self.assertFalse(result["cited"])

    def test_mention_is_case_insensitive(self):
        result = self._detect("LIVING SYSTEMS is a Bowen theory nonprofit.", [])
        self.assertTrue(result["mentioned"])

    def test_client_subdomain_counts_as_cited(self):
        result = self._detect("", ["https://blog.livingsystems.ca/post"])
        self.assertTrue(result["cited"])

    def test_top_competitor_domains_excludes_client(self):
        domains = pav.top_competitor_domains(_analysis_fixture(), "livingsystems.ca")
        self.assertIn("psychologytoday.com", domains)
        self.assertIn("wellbeings.ca", domains)
        self.assertNotIn("livingsystems.ca", domains)


class TestProbeParsing(unittest.TestCase):
    """G.1.1 — engine responses are parsed with all API calls mocked."""

    def test_claude_probe_extracts_text_and_urls(self):
        text_block = SimpleNamespace(
            type="text",
            text="Living Systems Counselling is one option.",
            citations=[SimpleNamespace(url="https://livingsystems.ca/")])
        search_block = SimpleNamespace(
            type="web_search_tool_result",
            content=[SimpleNamespace(url="https://psychologytoday.com/ca")])
        response = SimpleNamespace(
            content=[search_block, text_block], model="claude-sonnet-4-6")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}):
            with patch.object(pav, "anthropic") as mock_anthropic:
                mock_anthropic.Anthropic.return_value.messages.create.return_value = response
                probe = pav.ClaudeProbe(model="claude-sonnet-4-6")
                answer = probe.ask("where can I get counselling")
        self.assertIn("Living Systems", answer["answer_text"])
        self.assertIn("https://livingsystems.ca/", answer["source_urls"])
        self.assertIn("https://psychologytoday.com/ca", answer["source_urls"])
        self.assertEqual(answer["model_id"], "claude-sonnet-4-6")
        # Web search tool enabled on the call (spec: web search tool enabled).
        call_kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["tools"][0]["name"], "web_search")

    def test_claude_probe_requires_api_key(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                pav.ClaudeProbe(model="claude-sonnet-4-6")

    def test_gemini_probe_extracts_text_and_grounding_urls(self):
        payload = {
            "modelVersion": "gemini-2.5-flash",
            "candidates": [{
                "content": {"parts": [{"text": "Try Living Systems Counselling."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://livingsystems.ca/"}},
                        {"web": {"uri": "https://counsellingbc.com/"}},
                    ]
                },
            }],
        }
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = payload
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gkey"}):
            probe = pav.GeminiProbe(model="gemini-2.5-flash")
            with patch.object(pav.requests, "post", return_value=mock_response) as mock_post:
                answer = probe.ask("where can I get counselling")
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("x-goog-api-key", mock_post.call_args.kwargs["headers"])
        self.assertIn("Living Systems", answer["answer_text"])
        self.assertEqual(answer["source_urls"],
                         ["https://livingsystems.ca/", "https://counsellingbc.com/"])
        self.assertEqual(answer["model_id"], "gemini-2.5-flash")

    def test_gemini_probe_requires_api_key(self):
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                pav.GeminiProbe(model="gemini-2.5-flash")


class TestQuestionSources(unittest.TestCase):
    """Question priority: situational probes > 6+-word PAA > templates."""

    TEMPLATES = ["my partner refuses to try {base} what can I do"]

    def test_situational_probes_preferred(self):
        questions = pav.build_question_set(
            _analysis_fixture(), self.TEMPLATES, "North Vancouver", max_questions=20)
        self.assertTrue(all(q["source"] == "situational" for q in questions))
        self.assertEqual(len(questions), 2)
        # Y.5: with no profile, keyword-derived rows carry persona=None.
        self.assertTrue(all(q["persona"] is None for q in questions))

    def test_paa_fallback_filters_short_questions(self):
        data = _analysis_fixture()
        data["situational_probes"] = []
        questions = pav.build_question_set(
            data, self.TEMPLATES, "North Vancouver", max_questions=20)
        self.assertEqual([q["source"] for q in questions], ["paa"])
        self.assertEqual(questions[0]["query"],
                         "What is family systems therapy and how does it work?")

    def test_template_fallback_uses_root_keywords(self):
        data = _analysis_fixture()
        data["situational_probes"] = []
        data["paa_questions"] = []
        questions = pav.build_question_set(
            data, self.TEMPLATES, "North Vancouver", max_questions=20)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["source"], "template")
        self.assertIn("refuses to try", questions[0]["query"])

    def test_cap_respected(self):
        data = _analysis_fixture()
        data["situational_probes"] = [
            {"Executed_Query": f"unique probing question number {i} about counselling"}
            for i in range(30)
        ]
        questions = pav.build_question_set(
            data, self.TEMPLATES, "North Vancouver", max_questions=20)
        self.assertEqual(len(questions), 20)


class TestPersistence(unittest.TestCase):
    """G.1.2 — idempotent table, UTC run_ts + engine columns, ordered trend."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _row(self, run_ts, engine, mentioned=False, cited=False):
        return {
            "run_ts": run_ts, "engine": engine, "model": f"{engine}-model",
            "question": "q", "mentioned": mentioned, "cited": cited,
            "competitors_cited": ["psychologytoday.com"],
            "answer_excerpt": "answer",
        }

    def test_table_created_idempotently(self):
        pav.init_probe_table(self.tmp.name)
        pav.init_probe_table(self.tmp.name)  # second call must not raise
        with sqlite3.connect(self.tmp.name) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("ai_visibility_probes", tables)

    def test_rows_written_with_utc_run_ts_and_engine(self):
        from datetime import datetime, timezone
        run_ts = datetime.now(timezone.utc).isoformat()
        pav.save_probe_rows(self.tmp.name, [
            self._row(run_ts, "claude", mentioned=True),
            self._row(run_ts, "gemini", cited=True),
        ])
        with sqlite3.connect(self.tmp.name) as conn:
            rows = conn.execute(
                "SELECT run_ts, engine, mentioned, cited, competitor_domains_json "
                "FROM ai_visibility_probes ORDER BY engine").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "claude")
        self.assertEqual(rows[1][1], "gemini")
        # UTC timestamps carry an explicit offset.
        self.assertIn("+00:00", rows[0][0])
        self.assertEqual(json.loads(rows[0][4]), ["psychologytoday.com"])

    def test_per_engine_trend_returns_runs_in_order(self):
        run1 = "2026-06-01T10:00:00+00:00"
        run2 = "2026-07-01T10:00:00+00:00"
        rows = []
        for engine in ("claude", "gemini"):
            rows.append(self._row(run1, engine, mentioned=True))
            rows.append(self._row(run1, engine))
            rows.append(self._row(run2, engine, mentioned=True, cited=True))
        pav.save_probe_rows(self.tmp.name, rows)

        for engine in ("claude", "gemini"):
            trend = pav.get_engine_trend(self.tmp.name, engine)
            self.assertEqual([t["run_ts"] for t in trend], [run1, run2])
            self.assertEqual(trend[0]["questions"], 2)
            self.assertEqual(trend[0]["mention_rate"], 0.5)
            self.assertEqual(trend[1]["citation_rate"], 1.0)

        # Trend is per-engine: a run only for claude must not appear for gemini.
        pav.save_probe_rows(self.tmp.name,
                            [self._row("2026-07-02T10:00:00+00:00", "claude")])
        self.assertEqual(len(pav.get_engine_trend(self.tmp.name, "gemini")), 2)
        self.assertEqual(len(pav.get_engine_trend(self.tmp.name, "claude")), 3)


class _MainRunMixin:
    """Run pav.main() against a temp analysis JSON with probes mocked."""

    def _run_main(self, extra_args=(), env_overrides=None, config=None,
                  claude_probe=None, gemini_probe=None):
        env = dict(os.environ)
        env.setdefault("ANTHROPIC_API_KEY", "key")
        env.setdefault("GEMINI_API_KEY", "gkey")
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        config = config if config is not None else {
            "ai_visibility": {"engines": ["claude", "gemini"], "max_questions": 20},
            "analysis_report": {
                "client_name": "Living Systems Counselling",
                "client_domain": "livingsystems.ca",
                "client_name_patterns": ["Living Systems"],
                "location": "North Vancouver, BC, Canada",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            db_path = os.path.join(tmpdir, "test.db")
            out_path = os.path.join(tmpdir, "ai_visibility_out.md")
            args = ["--json", json_path, "--db", db_path, "--out", out_path,
                    "--config", os.path.join(tmpdir, "missing_config.yml")]
            args.extend(extra_args)

            claude_cls = MagicMock()
            claude_cls.return_value = claude_probe or _fake_probe("claude answer", [])
            gemini_cls = MagicMock()
            gemini_cls.return_value = gemini_probe or _fake_probe("gemini answer", [])
            if claude_probe is None and gemini_probe is None:
                pass
            printed = []
            # These tests assert the pre-Y.5 (G.1) precedence, so neutralise the
            # profile source: with no profile, behaviour equals G.1 (Y.5.1).
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ClaudeProbe", claude_cls):
                            with patch.object(pav, "GeminiProbe", gemini_cls):
                                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
                                    exit_code = pav.main(args)
            report = None
            if os.path.exists(out_path):
                with open(out_path, encoding="utf-8") as f:
                    report = f.read()
            return SimpleNamespace(
                exit_code=exit_code, printed="\n".join(printed),
                claude_cls=claude_cls, gemini_cls=gemini_cls, report=report)


def _fake_probe(answer_text, urls, model="mock-model"):
    probe = MagicMock()
    probe.ask.return_value = {
        "answer_text": answer_text, "source_urls": urls, "model_id": model}
    return probe


class TestCostGuard(_MainRunMixin, unittest.TestCase):
    """G.1.3 — no calls without explicit confirmation."""

    def test_default_run_makes_zero_api_calls(self):
        result = self._run_main()  # no --yes, assume_yes false
        self.assertEqual(result.exit_code, 0)
        # No probe was even constructed, so no API call could have happened.
        result.claude_cls.assert_not_called()
        result.gemini_cls.assert_not_called()
        self.assertIn("Cost guard: no API calls were made", result.printed)
        # Exit message states questions x engines.
        self.assertIn("2 questions x 2 engines", result.printed)
        self.assertIn("= 4 paid API calls", result.printed)

    def test_assume_yes_config_confirms(self):
        config = {
            "ai_visibility": {"engines": ["claude"], "assume_yes": True},
            "analysis_report": {"client_name_patterns": ["Living Systems"],
                                "client_domain": "livingsystems.ca"},
        }
        result = self._run_main(config=config)
        self.assertEqual(result.exit_code, 0)
        result.claude_cls.assert_called_once()


class TestEngineSelection(_MainRunMixin, unittest.TestCase):
    """G.1.4 — --engines override, unknown names, missing GEMINI_API_KEY."""

    def test_engines_flag_runs_only_claude(self):
        result = self._run_main(extra_args=["--engines", "claude", "--yes"])
        self.assertEqual(result.exit_code, 0)
        result.claude_cls.assert_called_once()
        result.gemini_cls.assert_not_called()
        self.assertEqual(result.claude_cls.return_value.ask.call_count, 2)

    def test_unknown_engine_errors_listing_valid_options(self):
        with self.assertRaises(SystemExit) as ctx:
            pav.resolve_engines("bing", {})
        self.assertIn("bing", str(ctx.exception))
        self.assertIn("claude", str(ctx.exception))
        self.assertIn("gemini", str(ctx.exception))

    def test_config_engine_list_used_when_no_flag(self):
        self.assertEqual(pav.resolve_engines(None, {"engines": ["gemini"]}), ["gemini"])
        # No config engines ⇒ the Y-D9 default engine list.
        self.assertEqual(pav.resolve_engines(None, {}),
                         ["gemini", "openai", "perplexity"])

    def test_missing_gemini_key_skips_with_warning_and_claude_completes(self):
        # Exercise build_probes with the REAL GeminiProbe constructor (no
        # GEMINI_API_KEY in the env) and a mocked anthropic client.
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY",)}
        env["ANTHROPIC_API_KEY"] = "key"
        with patch.dict(os.environ, env, clear=True):
            with patch.object(pav, "anthropic") as mock_anthropic:
                mock_anthropic.Anthropic.return_value = MagicMock()
                with patch.object(pav, "ANTHROPIC_AVAILABLE", True):
                    with self.assertLogs(pav.logger, level="WARNING") as logs:
                        probes, skipped = pav.build_probes(["claude", "gemini"], {})
        self.assertIn("claude", probes)
        self.assertNotIn("gemini", probes)
        self.assertEqual(skipped[0]["engine"], "gemini")
        self.assertTrue(any("GEMINI_API_KEY" in msg for msg in logs.output))

    def test_run_completes_claude_when_gemini_skipped(self):
        """End-to-end: gemini constructor raises, claude still records answers."""
        gemini_cls = MagicMock(side_effect=RuntimeError("GEMINI_API_KEY is not set."))
        claude_probe = _fake_probe(
            "Living Systems Counselling can help.", ["https://livingsystems.ca/"])
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            out_path = os.path.join(tmpdir, "out.md")
            db_path = os.path.join(tmpdir, "test.db")
            config = {
                "ai_visibility": {"engines": ["claude", "gemini"]},
                "analysis_report": {"client_name_patterns": ["Living Systems"],
                                    "client_domain": "livingsystems.ca"},
            }
            claude_cls = MagicMock(return_value=claude_probe)
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ClaudeProbe", claude_cls):
                            with patch.object(pav, "GeminiProbe", gemini_cls):
                                with self.assertLogs(pav.logger, level="WARNING"):
                                    exit_code = pav.main([
                                    "--json", json_path, "--db", db_path,
                                    "--out", out_path, "--yes",
                                    "--config", os.path.join(tmpdir, "nope.yml"),
                                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(claude_probe.ask.call_count, 2)
            with open(out_path, encoding="utf-8") as f:
                report = f.read()
        self.assertIn("skipped — GEMINI_API_KEY is not set.", report)
        self.assertIn("| claude |", report)

    def test_geo_context_prefixed_to_every_question(self):
        result = self._run_main(extra_args=["--engines", "claude", "--yes"])
        for call in result.claude_cls.return_value.ask.call_args_list:
            self.assertTrue(call.args[0].startswith("I'm in North Vancouver"))


class TestReport(unittest.TestCase):
    """G.1.5 — report with and without history; caveat always present."""

    ROWS = [
        {"run_ts": "2026-07-04T10:00:00+00:00", "engine": "claude",
         "model": "claude-sonnet-4-6", "question": "q1",
         "mentioned": True, "cited": True, "competitors_cited": ["psychologytoday.com"],
         "answer_excerpt": "a"},
        {"run_ts": "2026-07-04T10:00:00+00:00", "engine": "claude",
         "model": "claude-sonnet-4-6", "question": "q2",
         "mentioned": False, "cited": False, "competitors_cited": [],
         "answer_excerpt": "a"},
        {"run_ts": "2026-07-04T10:00:00+00:00", "engine": "gemini",
         "model": "gemini-2.5-flash", "question": "q1",
         "mentioned": False, "cited": False, "competitors_cited": [],
         "answer_excerpt": "a"},
    ]

    def _report(self, trends):
        return pav.generate_report(
            "market_analysis_x.json", "2026-07-04T10:00:00+00:00",
            ["claude", "gemini"], self.ROWS, trends, [],
            "I'm in North Vancouver, BC.", "Living Systems Counselling")

    def test_report_with_zero_history(self):
        report = self._report({"claude": [], "gemini": []})
        self.assertIn("No history yet", report)
        self.assertIn("| claude | claude-sonnet-4-6 | 2 | 1/2 (50%) | 1/2 (50%) |", report)
        self.assertIn("| gemini | gemini-2.5-flash | 1 | 0/1 (0%) | 0/1 (0%) |", report)

    def test_report_with_history_shows_per_engine_trend(self):
        trends = {
            "claude": [
                {"run_ts": "2026-06-01T00:00:00+00:00", "model": "claude-old",
                 "questions": 4, "mentioned": 1, "cited": 0,
                 "mention_rate": 0.25, "citation_rate": 0.0},
                {"run_ts": "2026-07-04T10:00:00+00:00", "model": "claude-sonnet-4-6",
                 "questions": 2, "mentioned": 1, "cited": 1,
                 "mention_rate": 0.5, "citation_rate": 0.5},
            ],
            "gemini": [],
        }
        report = self._report(trends)
        self.assertIn("| 2026-06-01T00:00:00+00:00 | claude-old | 4 | 25% | 0% |", report)
        self.assertIn("claude-sonnet-4-6", report)

    def test_caveat_paragraph_always_present(self):
        for trends in ({"claude": [], "gemini": []},
                       {"claude": [{"run_ts": "x", "model": "m", "questions": 1,
                                    "mentioned": 0, "cited": 0,
                                    "mention_rate": 0.0, "citation_rate": 0.0}],
                        "gemini": []}):
            report = self._report(trends)
            self.assertIn("single-run values are snapshots", report)
            self.assertIn(pav.SNAPSHOT_CAVEAT, report)

    def test_model_ids_listed(self):
        report = self._report({"claude": [], "gemini": []})
        self.assertIn("claude-sonnet-4-6", report)
        self.assertIn("gemini-2.5-flash", report)

    def test_output_name_matches_gitignored_glob(self):
        path = pav._derive_output_path("market_analysis_leila_20260504_2020.json")
        self.assertTrue(path.startswith("ai_visibility_leila_"))
        self.assertTrue(path.endswith(".md"))


class TestPipelineIsolation(unittest.TestCase):
    """The main pipeline must not import probe_ai_visibility at import time."""

    def test_pipeline_modules_do_not_import_probe_module(self):
        for module in ("serp_audit.py", "generate_content_brief.py",
                       "brief_data_extraction.py", "run_pipeline.py"):
            with open(os.path.join(_REPO_ROOT, module), encoding="utf-8") as f:
                source = f.read()
            self.assertNotIn("probe_ai_visibility", source,
                             f"{module} must not import probe_ai_visibility")


if __name__ == "__main__":
    unittest.main()
