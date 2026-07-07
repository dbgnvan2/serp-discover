"""Integration tests for the Phase D read-side enrichment orchestration in
probe_ai_visibility.run_report_enrichment (Y.6–Y.9 wired together).

Spec: yoast_geo_upgrade_spec_v1.md#Y.6/#Y.7/#Y.8/#Y.9
- Sentiment disabled → zero sentiment calls, AIVI sentiment axis n/a
  (renormalised), report says "not measured".
- brand_mentions.llm_extraction=false → gazetteer-only leaderboard, no LLM.
- Enrichment persists brand_mentions / ai_citations / ai_visibility_index rows.
- Old analysis JSON without organic_results flows through without crashing.
"""
import os
import sqlite3
import tempfile
import unittest

import probe_ai_visibility as pav


def _rows():
    """Two mocked answers on one engine: one names a competitor, one is empty."""
    return [
        {"engine": "openai", "mentioned": True, "cited": False,
         "answer_text": "Living Systems and Psychology Today are options.",
         "source_urls": ["https://www.livingsystems.ca/about",
                         "https://www.psychologytoday.com/x?utm_source=openai"]},
        {"engine": "openai", "mentioned": False, "cited": False,
         "answer_text": "Try Psychology Today.",
         "source_urls": ["https://www.psychologytoday.com/y?utm_source=openai"]},
    ]


def _config(sentiment_enabled=False, llm_extraction=False):
    return {
        "analysis_report": {
            "client_name": "Living Systems",
            "client_domain": "livingsystems.ca",
            "client_name_patterns": ["Living Systems"],
        },
        "known_brands": ["Psychology Today"],
        "aivi": {"weights": {"mentions": 0.25, "ranking": 0.25,
                             "citations": 0.25, "sentiment": 0.25}},
        "brand_mentions": {"llm_extraction": llm_extraction, "llm_model": "m"},
        "sentiment": {"enabled": sentiment_enabled, "llm_model": "m"},
    }


class TestEnrichmentDisabledDefaults(unittest.TestCase):
    def test_sentiment_disabled_zero_calls_and_axis_na(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            calls = {"brand": 0, "sent": 0}

            def brand_runner(*a, **k):
                calls["brand"] += 1
                return "[]"

            def sent_runner(*a, **k):
                calls["sent"] += 1
                return "{}"

            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(), {"organic_results": []},
                    "2026-01-01T00:00:00+00:00", "leila", db, "x.json",
                    out_dir=d, brand_llm_runner=brand_runner,
                    sentiment_llm_runner=sent_runner)
                # No LLM calls at all (both gated OFF).
                self.assertEqual(calls["brand"], 0)
                self.assertEqual(calls["sent"], 0)
                self.assertEqual(out["sentiment"]["calls"], 0)
                self.assertFalse(out["sentiment"]["enabled"])
                # AIVI sentiment axis is n/a (excluded), not zero.
                result = out["aivi"]["per_engine"]["openai"]
                self.assertIn("sentiment", result["excluded"])
                self.assertIsNone(result["axes"]["sentiment"])
                # Report section says "not measured".
                section = pav._enrichment_sections(["openai"], out)
                self.assertTrue(any("not measured" in ln.lower() for ln in section))
            finally:
                os.remove(db)

    def test_leaderboard_gazetteer_only_and_persisted(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(), {"organic_results": []},
                    "2026-01-01T00:00:00+00:00", "leila", db, "x.json", out_dir=d)
                lb = out["leaderboards"]["openai"]
                brands = {r["brand"]: r["mention_count"] for r in lb["rows"]}
                # "Psychology Today" named in both answers → 2.
                self.assertEqual(brands["Psychology Today"], 2)
                # Rows persisted.
                with sqlite3.connect(db) as conn:
                    n = conn.execute(
                        "SELECT COUNT(*) FROM brand_mentions WHERE engine='openai'"
                    ).fetchone()[0]
                self.assertGreater(n, 0)
                with sqlite3.connect(db) as conn:
                    cites = conn.execute(
                        "SELECT COUNT(*) FROM ai_citations").fetchone()[0]
                    aivi_rows = conn.execute(
                        "SELECT COUNT(*) FROM ai_visibility_index").fetchone()[0]
                self.assertGreater(cites, 0)
                self.assertEqual(aivi_rows, 1)
            finally:
                os.remove(db)

    def test_old_json_no_crash(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(), {"legacy": True},
                    "2026-01-01T00:00:00+00:00", "leila", db, "x.json", out_dir=d)
                self.assertIn("openai", out["aivi"]["per_engine"])
            finally:
                os.remove(db)


class TestEnrichmentEnabled(unittest.TestCase):
    def test_sentiment_enabled_counts_calls(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            def sent_runner(system, user, model, max_tokens):
                return '{"polarity":"positive","positive_aspects":["warm"],"negative_aspects":[]}'

            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(sentiment_enabled=True),
                    {"organic_results": []}, "2026-01-01T00:00:00+00:00",
                    "leila", db, "x.json", out_dir=d,
                    sentiment_llm_runner=sent_runner, sentiment_call_budget=10)
                self.assertTrue(out["sentiment"]["enabled"])
                self.assertGreater(out["sentiment"]["calls"], 0)
                # Client sentiment axis now present (not n/a).
                result = out["aivi"]["per_engine"]["openai"]
                self.assertIsNotNone(result["axes"]["sentiment"])
            finally:
                os.remove(db)

    def test_brand_llm_surfaces_candidates_file(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            def brand_runner(system, user, model, max_tokens):
                return '["Psychology Today", "Brand New Clinic"]'

            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(llm_extraction=True),
                    {"organic_results": []}, "2026-01-01T00:00:00+00:00",
                    "leila", db, "x.json", out_dir=d,
                    brand_llm_runner=brand_runner)
                self.assertIsNotNone(out["candidates_file"])
                body = open(out["candidates_file"]).read()
                self.assertIn("Brand New Clinic", body)
            finally:
                os.remove(db)


class TestPhaseEWiring(unittest.TestCase):
    """Phase E (Y.10–Y.12) wired into run_report_enrichment + report render."""

    def _analysis(self):
        # Minimal keyword_profiles so foundational sub-scores are measurable.
        return {
            "organic_results": [],
            "keyword_profiles": {
                "kw1": {
                    "extractability": {
                        "data_available": True,
                        "client_page": {"question_heading_count": 2,
                                        "intro_text_length": 300, "faq_present": True},
                    },
                    "schema_signals": {
                        "data_available": True,
                        "schema_type_counts": {"FAQPage": 1}},
                },
            },
            "strategic_flags": {"geo_alerts": [
                {"keyword": "kw1", "detail": "Client ranks but AIO cites others."}]},
        }

    def test_foundational_and_transfer_persisted_and_rendered(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            try:
                # Two engines so transfer is measurable.
                rows = _rows() + [
                    {"engine": "perplexity", "mentioned": True, "cited": True,
                     "answer_text": "Living Systems is great.",
                     "source_urls": ["https://www.livingsystems.ca/x"]},
                ]
                out = pav.run_report_enrichment(
                    rows, ["openai", "perplexity"], _config(), self._analysis(),
                    "2026-01-01T00:00:00+00:00", "leila", db, "x.json", out_dir=d)
                # Phase E blocks present.
                self.assertIn("foundational", out)
                self.assertIn("engine_strategy", out)
                self.assertIn("transfer", out)
                self.assertTrue(out["transfer"]["measurable"])
                # Foundational is engine-agnostic and has a score.
                self.assertIsInstance(out["foundational"]["result"]["score"], float)
                # New tables persisted.
                with sqlite3.connect(db) as conn:
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM foundational_score").fetchone()[0], 1)
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM engine_transfer").fetchone()[0], 1)
                # Report: foundational section leads, before AIVI.
                section = "\n".join(pav._enrichment_sections(["openai", "perplexity"], out))
                self.assertLess(section.index("Foundational GEO readiness"),
                                section.index("AI Visibility Index"))
                self.assertIn("Per-engine recommendations", section)
                self.assertIn("Cross-engine transfer", section)
            finally:
                os.remove(db)

    def test_single_engine_transfer_not_measurable(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with tempfile.TemporaryDirectory() as d:
            try:
                out = pav.run_report_enrichment(
                    _rows(), ["openai"], _config(), self._analysis(),
                    "2026-01-01T00:00:00+00:00", "leila", db, "x.json", out_dir=d)
                self.assertFalse(out["transfer"]["measurable"])
                section = "\n".join(pav._enrichment_sections(["openai"], out))
                self.assertIn("not measurable", section.lower())
            finally:
                os.remove(db)


if __name__ == "__main__":
    unittest.main()
