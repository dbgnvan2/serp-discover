"""Tests for Y.2 (OpenAI/ChatGPT probe) and Y.3 (Perplexity probe).

Spec: yoast_geo_upgrade_spec_v1.md#Y.2 / #Y.3
- Y.2.1 / Y.3.1 all calls mocked; detection verified for mentioned-only,
  cited, neither, and competitor-cited answers on each new probe's output,
  including Perplexity's citation-URL mapping.
- Y.2.2 / Y.3.2 --engines openai runs only ChatGPTProbe, --engines perplexity
  only PerplexityProbe; missing key skips with a warning while other engines
  complete.
- Y.2.3 / Y.3.3 rows written with the right engine value + configured model id;
  per-engine trend query returns the engine's runs in order.
- Y.2.4 / Y.3.4 config keys + docs (docs asserted in TestDocs below).

All API calls are mocked; ZERO live calls.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import probe_ai_visibility as pav

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _analysis_fixture():
    return {
        "overview": [
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver"},
        ],
        "organic_results": [
            {"Query_Label": "A", "Rank": 1, "Link": "https://www.psychologytoday.com/ca/x"},
            {"Query_Label": "A", "Rank": 3, "Link": "https://wellbeings.ca/about"},
        ],
        "situational_probes": [
            {"Executed_Query": "my partner refuses to try counselling what can I do"},
            {"Executed_Query": "how do I know if we actually need family counselling"},
        ],
        "paa_questions": [
            {"Question": "What is family systems therapy and how does it work?"},
        ],
    }


def _fake_probe(answer_text, urls, model="mock-model"):
    probe = MagicMock()
    probe.ask.return_value = {
        "answer_text": answer_text, "source_urls": urls, "model_id": model}
    return probe


def _mock_response(payload, ok=True, status=200):
    resp = MagicMock(ok=ok, status_code=status, text="")
    resp.json.return_value = payload
    return resp


# ---------------------------------------------------------------------------
# Y.2 — ChatGPTProbe (OpenAI Responses API + web_search)
# ---------------------------------------------------------------------------

class TestChatGPTProbeParsing(unittest.TestCase):
    """Y.2.1 — Responses-API answer + url_citation annotations parsed; mocked."""

    def _openai_payload(self, text, citation_urls, source_urls=(),
                        model="gpt-4o"):
        annotations = [
            {"type": "url_citation", "url": u, "title": "t"} for u in citation_urls
        ]
        output = [
            {"type": "web_search_call",
             "action": {"sources": [{"url": u} for u in source_urls]}},
            {"type": "message",
             "content": [{"type": "output_text", "text": text,
                          "annotations": annotations}]},
        ]
        return {"model": model, "output": output}

    def _ask(self, payload, model="gpt-4o"):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "okey"}):
            probe = pav.ChatGPTProbe(model=model)
            with patch.object(pav.requests, "post",
                              return_value=_mock_response(payload)) as mock_post:
                answer = probe.ask("where can I get counselling")
        return answer, mock_post

    def test_extracts_text_urls_and_model(self):
        payload = self._openai_payload(
            "Living Systems Counselling is one option.",
            ["https://livingsystems.ca/"],
            source_urls=["https://psychologytoday.com/ca"])
        answer, mock_post = self._ask(payload)
        self.assertEqual(mock_post.call_count, 1)
        # web_search tool enabled + Bearer auth on the call.
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["tools"][0]["type"], "web_search")
        self.assertIn("Bearer okey",
                      mock_post.call_args.kwargs["headers"]["Authorization"])
        self.assertIn("Living Systems", answer["answer_text"])
        self.assertIn("https://livingsystems.ca/", answer["source_urls"])
        self.assertIn("https://psychologytoday.com/ca", answer["source_urls"])
        self.assertEqual(answer["model_id"], "gpt-4o")

    def test_output_text_fallback(self):
        payload = {"model": "gpt-4o", "output_text": "Plain answer.", "output": []}
        answer, _ = self._ask(payload)
        self.assertEqual(answer["answer_text"], "Plain answer.")

    def test_requires_api_key(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                pav.ChatGPTProbe(model="gpt-4o")

    def test_http_error_raises(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "okey"}):
            probe = pav.ChatGPTProbe(model="gpt-4o")
            bad = _mock_response({}, ok=False, status=500)
            bad.text = "boom"
            with patch.object(pav.requests, "post", return_value=bad):
                with self.assertRaises(RuntimeError):
                    probe.ask("q")


class TestChatGPTDetection(unittest.TestCase):
    """Y.2.1 — detection on ChatGPTProbe output for the four answer shapes."""

    PATTERNS = ["Living Systems"]
    DOMAIN = "livingsystems.ca"
    COMPETITORS = ["psychologytoday.com", "wellbeings.ca"]

    def _probe_and_detect(self, text, citation_urls):
        payload = {
            "model": "gpt-4o",
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": text,
                "annotations": [{"type": "url_citation", "url": u}
                                for u in citation_urls]}]}],
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "okey"}):
            probe = pav.ChatGPTProbe(model="gpt-4o")
            with patch.object(pav.requests, "post",
                              return_value=_mock_response(payload)):
                answer = probe.ask("q")
        return pav.detect_visibility(
            answer["answer_text"], answer["source_urls"],
            self.PATTERNS, self.DOMAIN, self.COMPETITORS)

    def test_mentioned_only(self):
        r = self._probe_and_detect(
            "Living Systems Counselling offers Bowen therapy.",
            ["https://example.com/x"])
        self.assertTrue(r["mentioned"])
        self.assertFalse(r["cited"])
        self.assertEqual(r["competitors_cited"], [])

    def test_cited(self):
        r = self._probe_and_detect(
            "Some nonprofits offer counselling.",
            ["https://www.livingsystems.ca/services/"])
        self.assertFalse(r["mentioned"])
        self.assertTrue(r["cited"])

    def test_neither(self):
        r = self._probe_and_detect(
            "Counselling BC lists therapists.", ["https://counsellingbc.com/x"])
        self.assertFalse(r["mentioned"])
        self.assertFalse(r["cited"])
        self.assertEqual(r["competitors_cited"], [])

    def test_competitor_cited(self):
        r = self._probe_and_detect(
            "Psychology Today has a directory.",
            ["https://www.psychologytoday.com/ca/therapists",
             "https://wellbeings.ca/team"])
        self.assertEqual(r["competitors_cited"],
                         ["psychologytoday.com", "wellbeings.ca"])
        self.assertFalse(r["cited"])


# ---------------------------------------------------------------------------
# Y.3 — PerplexityProbe (Sonar, OpenAI-compatible chat/completions)
# ---------------------------------------------------------------------------

class TestPerplexityProbeParsing(unittest.TestCase):
    """Y.3.1 — Sonar answer + citation-URL mapping parsed; mocked."""

    def _payload(self, text, search_results=(), citations=(), model="sonar"):
        return {
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant",
                                                 "content": text}}],
            "search_results": [{"title": "t", "url": u} for u in search_results],
            "citations": list(citations),
        }

    def _ask(self, payload, model="sonar"):
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "pkey"}):
            probe = pav.PerplexityProbe(model=model)
            with patch.object(pav.requests, "post",
                              return_value=_mock_response(payload)) as mock_post:
                answer = probe.ask("where can I get counselling")
        return answer, mock_post

    def test_maps_search_results_to_source_urls(self):
        payload = self._payload(
            "Try Living Systems Counselling.",
            search_results=["https://livingsystems.ca/", "https://counsellingbc.com/"])
        answer, mock_post = self._ask(payload)
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("Bearer pkey",
                      mock_post.call_args.kwargs["headers"]["Authorization"])
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "sonar")
        self.assertIn("Living Systems", answer["answer_text"])
        self.assertEqual(answer["source_urls"],
                         ["https://livingsystems.ca/", "https://counsellingbc.com/"])
        self.assertEqual(answer["model_id"], "sonar")

    def test_flat_citations_list_merged_and_deduped(self):
        # search_results and citations overlap; the flat list adds a new URL.
        payload = self._payload(
            "Answer.",
            search_results=["https://livingsystems.ca/"],
            citations=["https://livingsystems.ca/", "https://wellbeings.ca/team"])
        answer, _ = self._ask(payload)
        self.assertEqual(answer["source_urls"],
                         ["https://livingsystems.ca/", "https://wellbeings.ca/team"])

    def test_requires_api_key(self):
        env = {k: v for k, v in os.environ.items() if k != "PERPLEXITY_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                pav.PerplexityProbe(model="sonar")

    def test_http_error_raises(self):
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "pkey"}):
            probe = pav.PerplexityProbe(model="sonar")
            bad = _mock_response({}, ok=False, status=502)
            bad.text = "boom"
            with patch.object(pav.requests, "post", return_value=bad):
                with self.assertRaises(RuntimeError):
                    probe.ask("q")


class TestPerplexityDetection(unittest.TestCase):
    """Y.3.1 — detection on PerplexityProbe output incl. citation-URL mapping."""

    PATTERNS = ["Living Systems"]
    DOMAIN = "livingsystems.ca"
    COMPETITORS = ["psychologytoday.com", "wellbeings.ca"]

    def _probe_and_detect(self, text, search_results):
        payload = {
            "model": "sonar",
            "choices": [{"message": {"content": text}}],
            "search_results": [{"url": u} for u in search_results],
        }
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "pkey"}):
            probe = pav.PerplexityProbe(model="sonar")
            with patch.object(pav.requests, "post",
                              return_value=_mock_response(payload)):
                answer = probe.ask("q")
        return pav.detect_visibility(
            answer["answer_text"], answer["source_urls"],
            self.PATTERNS, self.DOMAIN, self.COMPETITORS)

    def test_mentioned_only(self):
        r = self._probe_and_detect(
            "Living Systems Counselling offers therapy.", ["https://example.com/x"])
        self.assertTrue(r["mentioned"])
        self.assertFalse(r["cited"])

    def test_cited_via_citation_mapping(self):
        # cited detection relies on the mapped citation URLs.
        r = self._probe_and_detect(
            "Several options exist.", ["https://livingsystems.ca/services"])
        self.assertFalse(r["mentioned"])
        self.assertTrue(r["cited"])

    def test_neither(self):
        r = self._probe_and_detect(
            "Counselling BC lists therapists.", ["https://counsellingbc.com/x"])
        self.assertFalse(r["mentioned"])
        self.assertFalse(r["cited"])
        self.assertEqual(r["competitors_cited"], [])

    def test_competitor_cited_via_citation_mapping(self):
        r = self._probe_and_detect(
            "Psychology Today has a directory.",
            ["https://www.psychologytoday.com/ca/therapists",
             "https://wellbeings.ca/team"])
        self.assertEqual(r["competitors_cited"],
                         ["psychologytoday.com", "wellbeings.ca"])
        self.assertFalse(r["cited"])


# ---------------------------------------------------------------------------
# build_probes — key-gated skip for the new engines (Y.2.2 / Y.3.2)
# ---------------------------------------------------------------------------

class TestBuildProbesNewEngines(unittest.TestCase):

    def test_openai_and_perplexity_built_with_configured_model(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o",
                                     "PERPLEXITY_API_KEY": "p"}):
            probes, skipped = pav.build_probes(
                ["openai", "perplexity"],
                {"openai_model": "gpt-4o-mini", "perplexity_model": "sonar-pro"})
        self.assertEqual(skipped, [])
        self.assertIsInstance(probes["openai"], pav.ChatGPTProbe)
        self.assertIsInstance(probes["perplexity"], pav.PerplexityProbe)
        self.assertEqual(probes["openai"].model, "gpt-4o-mini")
        self.assertEqual(probes["perplexity"].model, "sonar-pro")

    def test_missing_openai_key_skips_with_warning_others_complete(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        env["PERPLEXITY_API_KEY"] = "p"
        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs(pav.logger, level="WARNING") as logs:
                probes, skipped = pav.build_probes(["openai", "perplexity"], {})
        self.assertNotIn("openai", probes)
        self.assertIn("perplexity", probes)
        self.assertEqual(skipped[0]["engine"], "openai")
        self.assertTrue(any("OPENAI_API_KEY" in m for m in logs.output))

    def test_missing_perplexity_key_skips_with_warning_others_complete(self):
        env = {k: v for k, v in os.environ.items() if k != "PERPLEXITY_API_KEY"}
        env["OPENAI_API_KEY"] = "o"
        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs(pav.logger, level="WARNING") as logs:
                probes, skipped = pav.build_probes(["openai", "perplexity"], {})
        self.assertIn("openai", probes)
        self.assertNotIn("perplexity", probes)
        self.assertEqual(skipped[0]["engine"], "perplexity")
        self.assertTrue(any("PERPLEXITY_API_KEY" in m for m in logs.output))


# ---------------------------------------------------------------------------
# resolve_engines accepts the new engines (Y.2.2 / Y.3.2)
# ---------------------------------------------------------------------------

class TestResolveNewEngines(unittest.TestCase):

    def test_openai_and_perplexity_valid(self):
        self.assertEqual(pav.resolve_engines("openai", {}), ["openai"])
        self.assertEqual(pav.resolve_engines("perplexity", {}), ["perplexity"])

    def test_default_engine_list_is_y_d9(self):
        self.assertEqual(pav.resolve_engines(None, {}),
                         ["gemini", "openai", "perplexity"])


# ---------------------------------------------------------------------------
# Persistence — rows written with the right engine + model; trend ordered
# (Y.2.3 / Y.3.3)
# ---------------------------------------------------------------------------

class TestNewEnginePersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _row(self, run_ts, engine, model, mentioned=False, cited=False):
        return {
            "run_ts": run_ts, "engine": engine, "model": model,
            "question": "q", "mentioned": mentioned, "cited": cited,
            "competitors_cited": [], "answer_excerpt": "a",
        }

    def test_rows_written_with_engine_and_model(self):
        run_ts = "2026-07-04T10:00:00+00:00"
        pav.save_probe_rows(self.tmp.name, [
            self._row(run_ts, "openai", "gpt-4o", mentioned=True),
            self._row(run_ts, "perplexity", "sonar", cited=True),
        ])
        with sqlite3.connect(self.tmp.name) as conn:
            rows = conn.execute(
                "SELECT engine, model FROM ai_visibility_probes ORDER BY engine"
            ).fetchall()
        self.assertEqual(rows, [("openai", "gpt-4o"), ("perplexity", "sonar")])

    def test_per_engine_trend_ordered(self):
        run1 = "2026-06-01T10:00:00+00:00"
        run2 = "2026-07-01T10:00:00+00:00"
        rows = []
        for engine, model in (("openai", "gpt-4o"), ("perplexity", "sonar")):
            rows.append(self._row(run1, engine, model, mentioned=True))
            rows.append(self._row(run2, engine, model, cited=True))
        pav.save_probe_rows(self.tmp.name, rows)
        for engine, model in (("openai", "gpt-4o"), ("perplexity", "sonar")):
            trend = pav.get_engine_trend(self.tmp.name, engine)
            self.assertEqual([t["run_ts"] for t in trend], [run1, run2])
            self.assertEqual(trend[0]["model"], model)
        # Trend is per-engine: openai rows never appear under perplexity.
        pav.save_probe_rows(self.tmp.name,
                            [self._row("2026-07-02T10:00:00+00:00", "openai", "gpt-4o")])
        self.assertEqual(len(pav.get_engine_trend(self.tmp.name, "perplexity")), 2)
        self.assertEqual(len(pav.get_engine_trend(self.tmp.name, "openai")), 3)


# ---------------------------------------------------------------------------
# End-to-end main() — single-engine runs the right probe only (Y.2.2 / Y.3.2)
# ---------------------------------------------------------------------------

class TestMainSingleNewEngine(unittest.TestCase):

    def _run_main(self, engine, env_overrides=None):
        env = dict(os.environ)
        env.setdefault("OPENAI_API_KEY", "okey")
        env.setdefault("PERPLEXITY_API_KEY", "pkey")
        for k, v in (env_overrides or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        config = {
            "ai_visibility": {"engines": [engine], "max_questions": 20,
                              "openai_model": "gpt-4o", "perplexity_model": "sonar"},
            "analysis_report": {
                "client_name": "Living Systems Counselling",
                "client_domain": "livingsystems.ca",
                "client_name_patterns": ["Living Systems"],
                "location": "North Vancouver, BC, Canada",
            },
        }
        openai_cls = MagicMock(return_value=_fake_probe("openai answer", [], "gpt-4o"))
        perp_cls = MagicMock(return_value=_fake_probe("perplexity answer", [], "sonar"))
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            db_path = os.path.join(tmpdir, "test.db")
            out_path = os.path.join(tmpdir, "out.md")
            args = ["--json", json_path, "--db", db_path, "--out", out_path,
                    "--engines", engine, "--yes",
                    "--config", os.path.join(tmpdir, "missing.yml")]
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ChatGPTProbe", openai_cls):
                            with patch.object(pav, "PerplexityProbe", perp_cls):
                                exit_code = pav.main(args)
            report = None
            if os.path.exists(out_path):
                with open(out_path, encoding="utf-8") as f:
                    report = f.read()
        return SimpleNamespace(exit_code=exit_code, openai_cls=openai_cls,
                               perp_cls=perp_cls, report=report)

    def test_engines_openai_runs_only_chatgpt(self):
        result = self._run_main("openai")
        self.assertEqual(result.exit_code, 0)
        result.openai_cls.assert_called_once()
        result.perp_cls.assert_not_called()
        self.assertEqual(result.openai_cls.return_value.ask.call_count, 2)
        self.assertIn("| openai | gpt-4o |", result.report)

    def test_engines_perplexity_runs_only_perplexity(self):
        result = self._run_main("perplexity")
        self.assertEqual(result.exit_code, 0)
        result.perp_cls.assert_called_once()
        result.openai_cls.assert_not_called()
        self.assertEqual(result.perp_cls.return_value.ask.call_count, 2)
        self.assertIn("| perplexity | sonar |", result.report)

    def test_missing_openai_key_skips_but_run_completes_with_message(self):
        # openai constructor raises (no key); the run still completes and the
        # report notes the skip, mirroring the Gemini contract.
        openai_cls = MagicMock(side_effect=RuntimeError("OPENAI_API_KEY is not set."))
        config = {
            "ai_visibility": {"engines": ["openai"]},
            "analysis_report": {"client_name_patterns": ["Living Systems"],
                                "client_domain": "livingsystems.ca"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            out_path = os.path.join(tmpdir, "out.md")
            db_path = os.path.join(tmpdir, "test.db")
            env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ChatGPTProbe", openai_cls):
                            with self.assertLogs(pav.logger, level="WARNING"):
                                exit_code = pav.main([
                                    "--json", json_path, "--db", db_path,
                                    "--out", out_path, "--yes",
                                    "--config", os.path.join(tmpdir, "nope.yml")])
        # All engines skipped ⇒ nothing to run ⇒ exit 1, warning logged.
        self.assertEqual(exit_code, 1)

    def test_missing_perplexity_key_skips_openai_completes(self):
        # Two engines; perplexity has no key, openai does — openai must finish.
        config = {
            "ai_visibility": {"engines": ["openai", "perplexity"],
                              "openai_model": "gpt-4o"},
            "analysis_report": {"client_name_patterns": ["Living Systems"],
                                "client_domain": "livingsystems.ca"},
        }
        openai_probe = _fake_probe("Living Systems can help.",
                                   ["https://livingsystems.ca/"], "gpt-4o")
        openai_cls = MagicMock(return_value=openai_probe)
        perp_cls = MagicMock(side_effect=RuntimeError("PERPLEXITY_API_KEY is not set."))
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            out_path = os.path.join(tmpdir, "out.md")
            db_path = os.path.join(tmpdir, "test.db")
            env = {k: v for k, v in os.environ.items() if k != "PERPLEXITY_API_KEY"}
            env["OPENAI_API_KEY"] = "okey"
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ChatGPTProbe", openai_cls):
                            with patch.object(pav, "PerplexityProbe", perp_cls):
                                with self.assertLogs(pav.logger, level="WARNING"):
                                    exit_code = pav.main([
                                        "--json", json_path, "--db", db_path,
                                        "--out", out_path, "--yes",
                                        "--config", os.path.join(tmpdir, "nope.yml")])
            with open(out_path, encoding="utf-8") as f:
                report = f.read()
        self.assertEqual(exit_code, 0)
        self.assertEqual(openai_probe.ask.call_count, 2)
        self.assertIn("skipped — PERPLEXITY_API_KEY is not set.", report)
        self.assertIn("| openai |", report)


# ---------------------------------------------------------------------------
# Docs (Y.2.4 / Y.3.4)
# ---------------------------------------------------------------------------

class TestDocs(unittest.TestCase):

    def _read(self, rel):
        with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_config_reference_documents_new_engines(self):
        doc = self._read("docs/config_reference.md")
        self.assertIn("openai_model", doc)
        self.assertIn("perplexity_model", doc)

    def test_user_manual_documents_new_engines(self):
        doc = self._read("docs/USER_MANUAL.md")
        self.assertIn("ChatGPT", doc)
        self.assertIn("Perplexity", doc)


if __name__ == "__main__":
    unittest.main()
