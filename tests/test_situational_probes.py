"""
Tests for situational (conversational) query probes.

Spec: seo_geo_deferred_spec_v1.md#T.5
- T.5.1 with enabled: false (default), zero extra SerpAPI calls occur.
- T.5.2 probe generation: PAA-sourced probes come verbatim from that
  keyword's 6+-word questions (External Locus preferred); template probes
  fill placeholders; totals respect both caps.
- T.5.3 probe rows carry Query_Label == "S" and are absent from the
  competitor handoff, keyword_profiles.serp_intent inputs, and volatility
  (one test per surface).
- T.5.4 aio_trigger_analysis computes correct bucket rates on a fixture
  with known word counts and AIO flags.
- T.5.5 serp_vocab.yml gains situational_templates (loader-required).
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import yaml

import query_variants
import serp_audit
from pattern_matching import load_serp_vocab
from handoff_writer import build_competitor_handoff
from brief_data_extraction import (
    _build_aio_trigger_analysis,
    _word_count_bucket,
    extract_analysis_data_from_json,
)
from brief_prompts import build_main_report_payload

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _paa_row(keyword, question, intent_tag="General"):
    return {"Source_Keyword": keyword, "Query_Label": "A",
            "Question": question, "Intent_Tag": intent_tag}


class TestVocabSection(unittest.TestCase):
    """T.5.5 — situational_templates is a required serp_vocab.yml section."""

    def test_vocab_has_situational_templates(self):
        # Restructured into a persona-keyed map (Y.4): {persona_label: [...]}.
        vocab = load_serp_vocab()
        self.assertIn("situational_templates", vocab)
        templates = vocab["situational_templates"]
        self.assertIsInstance(templates, dict)
        self.assertGreaterEqual(len(templates), 1)
        for entries in templates.values():
            self.assertIsInstance(entries, list)
            self.assertTrue(all(isinstance(t, str) and t.strip() for t in entries))

    def _all_templates(self):
        import query_variants
        return query_variants.flatten_situational_templates(
            load_serp_vocab()["situational_templates"])

    def test_templates_use_only_known_placeholders(self):
        for template in self._all_templates():
            # Must format cleanly with the documented placeholders (incl.
            # the optional {service} added in Y.4).
            formatted = template.format(base="couples counselling",
                                        topic="stress", city="Vancouver",
                                        service="family systems counselling")
            self.assertTrue(formatted.strip())

    def test_templates_are_situational_length(self):
        # The probes exist to measure 6+-word queries; a short template
        # would sabotage the measurement.
        for template in self._all_templates():
            formatted = template.format(base="counselling", topic="stress",
                                        city="Vancouver",
                                        service="family systems counselling")
            self.assertGreaterEqual(
                len(formatted.split()), 6,
                f"template shorter than 6 words when filled: {template!r}")

    def test_missing_situational_templates_raises(self):
        # All other required keys present, situational_templates absent.
        content = (
            "stop_words: [the]\n"
            "paa_category_triggers: {Commercial: [cost]}\n"
            "service_like_tokens: [therapy]\n"
            "ai_alternative_templates: {default: ['x {base}']}\n"
            "eeat_signals: {credential_tokens: [RCC], review_markers: [reviewed by]}\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                load_serp_vocab(path)
            self.assertIn("situational_templates", str(ctx.exception))
        finally:
            os.unlink(path)


class TestDisabledByDefault(unittest.TestCase):
    """T.5.1 — default config makes zero extra SerpAPI calls."""

    def test_config_yml_default_is_disabled(self):
        with open(os.path.join(_REPO_ROOT, "config.yml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("situational_probes", cfg)
        self.assertFalse(cfg["situational_probes"]["enabled"])
        self.assertEqual(cfg["situational_probes"]["max_probes_per_run"], 6)
        self.assertEqual(cfg["situational_probes"]["probes_per_keyword"], 2)

    def test_disabled_makes_zero_calls(self):
        paa = [_paa_row("kw", "why does my partner refuse to go to counselling",
                        "External Locus")]
        with patch.object(serp_audit, "SITUATIONAL_PROBES_ENABLED", False), \
             patch.object(serp_audit, "_fetch_serp_api") as mock_fetch:
            with redirect_stdout(io.StringIO()) as out:
                probe_rows, citation_rows = serp_audit.run_situational_probes(
                    ["kw"], paa, "test_run")
        self.assertEqual(mock_fetch.call_count, 0)
        self.assertEqual(probe_rows, [])
        self.assertEqual(citation_rows, [])
        self.assertIn("Situational probes: 0 SerpAPI calls", out.getvalue())

    def test_low_api_mode_forces_probes_off(self):
        with patch.object(serp_audit, "LOW_API_MODE", True), \
             patch.object(serp_audit, "BALANCED_MODE", True), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", False), \
             patch.object(serp_audit, "SITUATIONAL_PROBES_ENABLED", True), \
             patch.object(serp_audit, "AI_QUERY_ALTERNATIVES_ENABLED", False), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_MAX_CALLS", 0), \
             patch.object(serp_audit, "GOOGLE_MAX_PAGES", 1), \
             patch.object(serp_audit, "MAPS_MAX_PAGES", 1), \
             patch.object(serp_audit, "AI_FALLBACK_WITHOUT_LOCATION", False), \
             patch.object(serp_audit, "RELATED_QUESTIONS_AI_FOLLOWUP", False), \
             patch.object(serp_audit, "NO_CACHE_ENABLED", False):
            serp_audit.configure_runtime_mode()
            self.assertFalse(serp_audit.SITUATIONAL_PROBES_ENABLED)

    def test_deep_research_mode_enables_probes(self):
        with patch.object(serp_audit, "LOW_API_MODE", False), \
             patch.object(serp_audit, "BALANCED_MODE", False), \
             patch.object(serp_audit, "DEEP_RESEARCH_MODE", True), \
             patch.object(serp_audit, "SITUATIONAL_PROBES_ENABLED", False):
            serp_audit.configure_runtime_mode()
            self.assertTrue(serp_audit.SITUATIONAL_PROBES_ENABLED)


class TestProbeGeneration(unittest.TestCase):
    """T.5.2 — sources, verbatim PAA, placeholders, caps."""

    KW = "couples counselling north vancouver"
    CITY = "Vancouver"

    @classmethod
    def setUpClass(cls):
        # situational_templates is now a persona-keyed map (Y.4); flatten all
        # persona blocks to the legacy flat list the generator consumes.
        cls.TEMPLATES = query_variants.flatten_situational_templates(
            load_serp_vocab()["situational_templates"])

    def _generate(self, keywords, paa, max_total=6, per_keyword=2):
        return query_variants.generate_situational_probes(
            keywords, paa, max_total=max_total, per_keyword=per_keyword,
            templates=self.TEMPLATES, city=self.CITY)

    def _paa(self):
        return [
            # 4 words -> too short, never probed.
            _paa_row(self.KW, "what is couples counselling", "External Locus"),
            # General 6+ words: eligible, but after External Locus.
            _paa_row(self.KW, "how do we stop having the same argument", "General"),
            # External Locus 6+ words: first pick, verbatim.
            _paa_row(self.KW, "why does my partner refuse to go to counselling",
                     "External Locus"),
        ]

    def test_paa_probes_verbatim_external_locus_first(self):
        probes = self._generate([self.KW], self._paa())
        self.assertEqual(len(probes), 2)
        self.assertEqual(probes[0]["query"],
                         "why does my partner refuse to go to counselling")
        self.assertEqual(probes[1]["query"],
                         "how do we stop having the same argument")
        for probe in probes:
            self.assertEqual(probe["probe_source"], "paa")
            self.assertEqual(probe["source_keyword"], self.KW)

    def test_template_probes_fill_placeholders(self):
        # No PAA at all -> editorial templates fill the slots.
        probes = self._generate(["family counselling in vancouver"], [],
                                per_keyword=5)
        self.assertTrue(probes)
        self.assertTrue(all(p["probe_source"] == "template" for p in probes))
        queries = [p["query"] for p in probes]
        # {base} de-localised.
        self.assertIn("my partner refuses to try family counselling what can I do",
                      queries)
        # {city} filled.
        self.assertTrue(any(self.CITY in q for q in queries),
                        f"no template filled {{city}}={self.CITY}: {queries}")
        # No placeholder left unfilled.
        self.assertFalse(any("{" in q for q in queries))

    def test_short_paa_question_not_probed(self):
        probes = self._generate([self.KW], self._paa(), per_keyword=6)
        self.assertNotIn("what is couples counselling",
                         [p["query"] for p in probes])

    def test_both_caps_respected(self):
        keywords = [f"keyword {i}" for i in range(5)]
        paa = []
        for kw in keywords:
            for j in range(4):
                paa.append(_paa_row(
                    kw, f"why does everything about {kw} feel so hard number {j}",
                    "External Locus"))
        probes = self._generate(keywords, paa)
        self.assertEqual(len(probes), 6)  # run cap (gate D-1)
        per_kw = {}
        for probe in probes:
            per_kw[probe["source_keyword"]] = per_kw.get(probe["source_keyword"], 0) + 1
        self.assertTrue(all(count <= 2 for count in per_kw.values()))
        # 2 per keyword, cap 6 -> exactly the first 3 keywords probed.
        self.assertEqual(sorted(per_kw), sorted(keywords[:3]))

    def test_duplicate_queries_deduped_across_keywords(self):
        question = "why does my partner refuse to go to counselling"
        paa = [_paa_row("kw one", question, "External Locus"),
               _paa_row("kw two", question, "External Locus")]
        probes = self._generate(["kw one", "kw two"], paa, per_keyword=1)
        self.assertEqual(
            sum(1 for p in probes if p["query"] == question), 1)

    def test_priority_order_follows_content_priorities(self):
        analysis = {"strategic_flags": {"content_priorities": [
            {"keyword": "kw b", "action": "defend"},
            {"keyword": "kw a", "action": "enter"},
        ]}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(analysis, f)
            path = f.name
        try:
            order = query_variants.situational_keyword_order(
                ["kw a", "kw b", "kw c"], "priority", path)
            self.assertEqual(order, ["kw b", "kw a", "kw c"])
        finally:
            os.unlink(path)

    def test_all_mode_keeps_csv_order(self):
        order = query_variants.situational_keyword_order(
            ["kw a", "kw b"], "all", "")
        self.assertEqual(order, ["kw a", "kw b"])


class TestProbeRun(unittest.TestCase):
    """Probe execution: S labels, single call per probe, run log line."""

    PAA = [_paa_row("kw", "why does my partner refuse to go to counselling",
                    "External Locus"),
           _paa_row("kw", "how do we stop having the same argument", "General")]

    AIO_RESPONSE = {
        "ai_overview": {
            "text_blocks": [{"text": "Counselling can help."}],
            "references": [
                {"title": "Client page", "link": "https://livingsystems.ca/couples",
                 "source": "livingsystems.ca"},
                {"title": "Directory", "link": "https://psychologytoday.com/x",
                 "source": "psychologytoday.com"},
            ],
        },
        "organic_results": [
            {"position": 1, "title": "t", "link": "https://example.com/a"},
        ],
    }

    def _run(self, response):
        with patch.object(serp_audit, "SITUATIONAL_PROBES_ENABLED", True), \
             patch.object(serp_audit, "SITUATIONAL_MAX_PROBES_PER_RUN", 6), \
             patch.object(serp_audit, "SITUATIONAL_PROBES_PER_KEYWORD", 2), \
             patch.object(serp_audit, "SITUATIONAL_KEYWORDS_MODE", "all"), \
             patch.object(serp_audit, "CLIENT_DOMAIN", "livingsystems.ca"), \
             patch.object(serp_audit, "REQUEST_DELAY_SECONDS", 0), \
             patch.object(serp_audit, "save_raw_json"), \
             patch.object(serp_audit, "_fetch_serp_api",
                          return_value=response) as mock_fetch:
            with redirect_stdout(io.StringIO()) as out:
                probe_rows, citation_rows = serp_audit.run_situational_probes(
                    ["kw"], self.PAA, "test_run")
        return probe_rows, citation_rows, mock_fetch, out.getvalue()

    def test_one_call_per_probe_and_s_labels(self):
        probe_rows, citation_rows, mock_fetch, output = self._run(self.AIO_RESPONSE)
        self.assertEqual(mock_fetch.call_count, 2)  # 2 probes, 1 call each
        self.assertEqual(len(probe_rows), 2)
        self.assertTrue(all(r["Query_Label"] == "S" for r in probe_rows))
        self.assertTrue(all(r["Query_Label"] == "S" for r in citation_rows))
        # Probe queries went out verbatim, single page, no maps engine.
        for call in mock_fetch.call_args_list:
            params = call[0][0]
            self.assertEqual(params["engine"], serp_audit.GOOGLE_ENGINE)
            self.assertNotIn("start", params)
        self.assertIn("Situational probes: 2 SerpAPI calls (cap 6)", output)

    def test_aio_detection_and_client_citation(self):
        probe_rows, citation_rows, _, _ = self._run(self.AIO_RESPONSE)
        self.assertTrue(all(r["Has_AI_Overview"] for r in probe_rows))
        self.assertTrue(all(r["Client_Cited"] for r in probe_rows))
        self.assertEqual(len(citation_rows), 4)  # 2 refs x 2 probes
        self.assertIn("https://livingsystems.ca/couples",
                      [c["Link"] for c in citation_rows])

    def test_no_aio_response(self):
        probe_rows, citation_rows, _, _ = self._run({"organic_results": []})
        self.assertTrue(all(not r["Has_AI_Overview"] for r in probe_rows))
        self.assertTrue(all(not r["Client_Cited"] for r in probe_rows))
        self.assertEqual(citation_rows, [])

    def test_failed_fetch_recorded_without_crash(self):
        probe_rows, citation_rows, _, _ = self._run(None)
        self.assertEqual(len(probe_rows), 2)
        self.assertTrue(all(r["Fetch_Failed"] for r in probe_rows))
        self.assertEqual(citation_rows, [])


class TestSurfaceExclusion(unittest.TestCase):
    """T.5.3 — probes stay out of handoff, serp_intent inputs, volatility."""

    def test_handoff_excludes_s_label_rows(self):
        organic = [
            {"Source_Keyword": "kw", "Root_Keyword": "kw", "Query_Label": "A",
             "Rank": 1, "Title": "a", "Link": "https://competitor.com/a",
             "Entity_Type": "counselling", "Content_Type": "service"},
            {"Source_Keyword": "kw", "Root_Keyword": "kw", "Query_Label": "S",
             "Rank": 1, "Title": "s", "Link": "https://probe-only.com/s",
             "Entity_Type": "counselling", "Content_Type": "service"},
        ]
        handoff = build_competitor_handoff(
            organic, run_id="r1", run_timestamp="2026-07-04T00:00:00Z",
            client_domain="livingsystems.ca", client_brand_names=["Living Systems"])
        urls = [t["url"] for t in handoff["targets"]]
        self.assertIn("https://competitor.com/a", urls)
        self.assertNotIn("https://probe-only.com/s", urls)

    def test_serp_intent_inputs_exclude_s_label_rows(self):
        data = {
            "overview": [{
                "Run_ID": "r1", "Created_At": "2026-07-01T12:00:00",
                "Source_Keyword": "kw", "Query_Label": "A",
                "Executed_Query": "kw", "Total_Results": 1000,
            }],
            "organic_results": [
                {"Source_Keyword": "kw", "Query_Label": "A", "Rank": 1,
                 "Title": "a", "Source": "a.com", "Link": "https://a.com/x",
                 "Snippet": "s"},
                # Defensive: an S organic row must not feed serp_intent.
                {"Source_Keyword": "kw", "Query_Label": "S", "Rank": 1,
                 "Title": "probe", "Source": "probe-only.com",
                 "Link": "https://probe-only.com/x", "Snippet": "s"},
            ],
        }
        extracted = extract_analysis_data_from_json(data, "livingsystems.ca")
        profile = extracted["keyword_profiles"]["kw"]
        evidence = profile["serp_intent"]["evidence"]
        self.assertEqual(evidence["organic_url_count"], 1)
        self.assertEqual([r["source"] for r in profile["top5_organic"]], ["a.com"])

    def test_probe_pass_writes_nothing_to_storage(self):
        # Volatility (metrics.get_rank_deltas / get_volatility_metrics) reads
        # the serp_results SQLite table; the probe pass must never write it.
        paa = [_paa_row("kw", "why does my partner refuse to go to counselling",
                        "External Locus")]
        with patch.object(serp_audit, "SITUATIONAL_PROBES_ENABLED", True), \
             patch.object(serp_audit, "SITUATIONAL_KEYWORDS_MODE", "all"), \
             patch.object(serp_audit, "REQUEST_DELAY_SECONDS", 0), \
             patch.object(serp_audit, "save_raw_json"), \
             patch.object(serp_audit, "SerpStorage", MagicMock()) as mock_storage, \
             patch.object(serp_audit, "_fetch_serp_api",
                          return_value={"ai_overview": {"references": []}}):
            with redirect_stdout(io.StringIO()):
                probe_rows, _ = serp_audit.run_situational_probes(
                    ["kw"], paa, "test_run")
        self.assertTrue(probe_rows)
        mock_storage.assert_not_called()
        # And the pass yields no organic-shaped rows at all.
        self.assertTrue(all("Rank" not in r for r in probe_rows))


class TestAioTriggerAnalysis(unittest.TestCase):
    """T.5.4 — bucket rates on known word counts and AIO flags."""

    OVERVIEW = [
        {"Executed_Query": "couples counselling", "Has_Main_AI_Overview": False},
        {"Executed_Query": "family therapy vancouver", "Has_Main_AI_Overview": True},
        {"Executed_Query": "how to choose a counsellor", "Has_Main_AI_Overview": True},
    ]
    PROBES = [
        {"Executed_Query": "my partner refuses to try counselling what can I do",
         "Word_Count": 10, "Has_AI_Overview": True, "Client_Cited": True,
         "Source_Keyword": "couples counselling", "Query_Label": "S"},
        # Word_Count omitted -> derived from the query text (8 words).
        {"Executed_Query": "how do I know if we need counselling",
         "Has_AI_Overview": False, "Client_Cited": False,
         "Source_Keyword": "couples counselling", "Query_Label": "S"},
    ]

    def test_bucket_boundaries(self):
        self.assertEqual(_word_count_bucket(1), "1-3")
        self.assertEqual(_word_count_bucket(3), "1-3")
        self.assertEqual(_word_count_bucket(4), "4-5")
        self.assertEqual(_word_count_bucket(5), "4-5")
        self.assertEqual(_word_count_bucket(6), "6+")
        self.assertEqual(_word_count_bucket(12), "6+")

    def test_exact_bucket_rates(self):
        result = _build_aio_trigger_analysis(self.OVERVIEW, self.PROBES)
        self.assertTrue(result["data_available"])
        buckets = result["by_word_count_bucket"]
        self.assertEqual(buckets["1-3"], {"queries": 2, "aio_present": 1, "rate": 0.5})
        self.assertEqual(buckets["4-5"], {"queries": 1, "aio_present": 1, "rate": 1.0})
        self.assertEqual(buckets["6+"], {"queries": 2, "aio_present": 1, "rate": 0.5})

    def test_probe_results_content(self):
        result = _build_aio_trigger_analysis(self.OVERVIEW, self.PROBES)
        self.assertEqual(result["probe_count"], 2)
        first, second = result["probe_results"]
        self.assertEqual(first["word_count"], 10)
        self.assertTrue(first["client_cited"])
        self.assertEqual(second["word_count"], 8)  # derived fallback
        self.assertFalse(second["has_aio"])

    def test_empty_run_flags_unavailable(self):
        result = _build_aio_trigger_analysis([], [])
        self.assertFalse(result["data_available"])
        self.assertTrue(all(b["rate"] is None
                            for b in result["by_word_count_bucket"].values()))
        self.assertEqual(result["probe_results"], [])

    def test_old_json_without_probes_extracts_cleanly(self):
        data = {
            "overview": [{
                "Run_ID": "r1", "Created_At": "2026-07-01T12:00:00",
                "Source_Keyword": "family counselling", "Query_Label": "A",
                "Executed_Query": "family counselling", "Total_Results": 1000,
                "Has_Main_AI_Overview": True,
            }],
            "organic_results": [],
            # No situational_probes key at all (pre-T.5 JSON).
        }
        extracted = extract_analysis_data_from_json(data, "livingsystems.ca")
        analysis = extracted["aio_trigger_analysis"]
        self.assertTrue(analysis["data_available"])
        self.assertEqual(analysis["probe_results"], [])
        self.assertEqual(analysis["by_word_count_bucket"]["1-3"]["queries"], 1)

    def test_payload_passthrough(self):
        extracted = {"aio_trigger_analysis": {
            "data_available": True,
            "by_word_count_bucket": {"6+": {"queries": 2, "aio_present": 2,
                                            "rate": 1.0}},
            "probe_count": 2,
            "probe_results": [],
        }}
        payload = build_main_report_payload(extracted)
        self.assertEqual(
            payload["aio_trigger_analysis"]["by_word_count_bucket"]["6+"]["rate"],
            1.0)


if __name__ == "__main__":
    unittest.main()
