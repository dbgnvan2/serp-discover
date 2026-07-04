"""
Tests for the AI Overview citation-surface and rank-vs-citation analyses.

Spec: seo_geo_review_20260704.md T.3 / T.4 / T.6
- T.3: classify AIO-cited domains by entity type and surface outreach
  candidates (third-party surfaces, not competitor counselling sites).
- T.4: per-keyword divergence between organic rank and AIO citation,
  including the geo_alerts strategic flag (client ranks but is not cited).
- T.6: per-thread discussion/forum detail flows to the brief payload.
"""
import unittest

from brief_data_extraction import (
    _build_aio_citation_surfaces,
    _build_aio_divergence,
    _domain_from_link,
    extract_analysis_data_from_json,
)
from brief_prompts import build_main_report_payload


class TestDomainFromLink(unittest.TestCase):

    def test_strips_www_and_lowercases(self):
        self.assertEqual(_domain_from_link("https://WWW.Example.com/x"), "example.com")

    def test_w_leading_domains_survive(self):
        self.assertEqual(
            _domain_from_link("https://www.wellspringcounselling.ca/a"),
            "wellspringcounselling.ca",
        )

    def test_empty_and_junk(self):
        self.assertEqual(_domain_from_link(None), "")
        self.assertEqual(_domain_from_link("not a url"), "")


class TestAioDivergence(unittest.TestCase):

    def test_no_citations_returns_inert_block(self):
        result = _build_aio_divergence({}, {"livingsystems.ca": 3}, "livingsystems.ca", False)
        self.assertFalse(result["has_aio_citations"])
        self.assertTrue(result["client_in_top10"])
        self.assertFalse(result["client_ranks_but_not_cited"])

    def test_cited_not_ranking_and_ranking_not_cited(self):
        cited = {
            "psychologytoday.com": {"count": 3, "example_link": "https://psychologytoday.com/a"},
            "example.com": {"count": 1, "example_link": "https://example.com/b"},
        }
        top10 = {"example.com": 1, "livingsystems.ca": 4}
        result = _build_aio_divergence(cited, top10, "livingsystems.ca", False)
        self.assertTrue(result["has_aio_citations"])
        self.assertEqual(
            [d["domain"] for d in result["cited_not_ranking_top10"]],
            ["psychologytoday.com"],
        )
        self.assertEqual(
            [d["domain"] for d in result["ranking_top10_not_cited"]],
            ["livingsystems.ca"],
        )

    def test_client_ranks_but_not_cited_flag(self):
        cited = {"psychologytoday.com": {"count": 2, "example_link": None}}
        top10 = {"livingsystems.ca": 3}
        result = _build_aio_divergence(cited, top10, "livingsystems.ca", False)
        self.assertTrue(result["client_ranks_but_not_cited"])
        # Cited client clears the flag
        result = _build_aio_divergence(cited, top10, "livingsystems.ca", True)
        self.assertFalse(result["client_ranks_but_not_cited"])
        # Client not ranking → no flag
        result = _build_aio_divergence(cited, {"other.com": 1}, "livingsystems.ca", False)
        self.assertFalse(result["client_ranks_but_not_cited"])

    def test_client_subdomain_counts_as_client(self):
        result = _build_aio_divergence(
            {"a.com": {"count": 1, "example_link": None}},
            {"blog.livingsystems.ca": 5},
            "livingsystems.ca",
            False,
        )
        self.assertTrue(result["client_in_top10"])


class TestAioCitationSurfaces(unittest.TestCase):

    def _surfaces(self, outreach=("directory", "media")):
        citation_domains_by_kw = {
            "couples therapy": {
                "psychologytoday.com": {"count": 3, "example_link": "https://psychologytoday.com/a"},
                "wellspringcounselling.ca": {"count": 1, "example_link": "https://wellspringcounselling.ca/b"},
                "livingsystems.ca": {"count": 1, "example_link": "https://livingsystems.ca/c"},
            },
            "family therapy": {
                "psychologytoday.com": {"count": 2, "example_link": "https://psychologytoday.com/d"},
            },
        }
        entity_of_domain = {
            "psychologytoday.com": "directory",
            "wellspringcounselling.ca": "counselling",
            "livingsystems.ca": "nonprofit",
        }
        return _build_aio_citation_surfaces(
            citation_domains_by_kw, "livingsystems.ca", entity_of_domain, outreach
        )

    def test_entity_mix_counts_citations(self):
        surfaces = self._surfaces()
        self.assertEqual(surfaces["by_entity_type"]["directory"], 5)
        self.assertEqual(surfaces["by_entity_type"]["counselling"], 1)
        self.assertEqual(surfaces["total_citations"], 7)
        self.assertEqual(surfaces["unique_domains"], 3)

    def test_third_party_excludes_client_and_aggregates_keywords(self):
        surfaces = self._surfaces()
        domains = [e["domain"] for e in surfaces["third_party_sources"]]
        self.assertNotIn("livingsystems.ca", domains)
        top = surfaces["third_party_sources"][0]
        self.assertEqual(top["domain"], "psychologytoday.com")
        self.assertEqual(top["citations"], 5)
        self.assertEqual(sorted(top["keywords"]), ["couples therapy", "family therapy"])

    def test_outreach_candidates_filtered_by_entity_type(self):
        surfaces = self._surfaces(outreach=("directory",))
        outreach_domains = [e["domain"] for e in surfaces["outreach_candidates"]]
        self.assertEqual(outreach_domains, ["psychologytoday.com"])


class TestEndToEndExtraction(unittest.TestCase):
    """Divergence, geo_alerts, and forum threads through the real extractor."""

    def _sample_data(self):
        return {
            "overview": [{
                "Run_ID": "run_1",
                "Created_At": "2026-07-01T10:00:00",
                "Google_URL": "https://google.com/search?q=x",
                "Source_Keyword": "estrangement",
                "Query_Label": "A",
                "Executed_Query": "estrangement vancouver",
                "Total_Results": 1000,
                "SERP_Features": "related_questions",
            }],
            "organic_results": [
                {
                    "Source_Keyword": "estrangement", "Query_Label": "A", "Rank": 3,
                    "Title": "Client page", "Link": "https://livingsystems.ca/estrangement",
                    "Snippet": "support", "Source": "livingsystems.ca",
                    "Content_Type": "guide", "Entity_Type": "nonprofit", "Rank_Delta": 0,
                },
                {
                    "Source_Keyword": "estrangement", "Query_Label": "A", "Rank": 1,
                    "Title": "Directory page", "Link": "https://www.psychologytoday.com/est",
                    "Snippet": "find a therapist", "Source": "Psychology Today",
                    "Content_Type": "directory", "Entity_Type": "directory", "Rank_Delta": 0,
                },
            ],
            "ai_overview_citations": [
                # Cites the directory (which ranks) and a media site (which
                # does not rank) — but never the client, who ranks #3.
                {"Source_Keyword": "estrangement", "Query_Label": "A",
                 "Title": "Dir", "Link": "https://www.psychologytoday.com/est",
                 "Source": "Psychology Today"},
                {"Source_Keyword": "estrangement", "Query_Label": "A",
                 "Title": "News", "Link": "https://www.cbc.ca/estrangement-story",
                 "Source": "CBC"},
            ],
            "paa_questions": [],
            "autocomplete_suggestions": [],
            "related_searches": [],
            "derived_expansions": [
                {"Source_Keyword": "estrangement", "Query_Label": "A",
                 "Type": "Discussion/Forum", "Term": "Estranged from my sister",
                 "Link": "https://www.reddit.com/r/family/comments/x1",
                 "Forum": "Reddit", "Date": "2 months ago"},
                {"Source_Keyword": "estrangement", "Query_Label": "A",
                 "Type": "Related Search", "Term": "estrangement help",
                 "Link": "https://google.com/search?q=estrangement+help"},
            ],
            "serp_modules": [],
            "local_pack_and_maps": [],
            "serp_language_patterns": [],
            "strategic_recommendations": [],
            "competitors_ads": [],
        }

    def setUp(self):
        self.extracted = extract_analysis_data_from_json(
            self._sample_data(), "livingsystems.ca", ["Living Systems"]
        )

    def test_divergence_in_keyword_profile(self):
        divergence = self.extracted["keyword_profiles"]["estrangement"]["aio_divergence"]
        self.assertTrue(divergence["has_aio_citations"])
        self.assertEqual(
            [d["domain"] for d in divergence["cited_not_ranking_top10"]],
            ["cbc.ca"],
        )
        self.assertEqual(
            [d["domain"] for d in divergence["ranking_top10_not_cited"]],
            ["livingsystems.ca"],
        )
        self.assertTrue(divergence["client_ranks_but_not_cited"])

    def test_geo_alert_raised(self):
        alerts = self.extracted["strategic_flags"]["geo_alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["keyword"], "estrangement")

    def test_citation_surfaces_built(self):
        surfaces = self.extracted["aio_citation_surfaces"]
        self.assertEqual(surfaces["total_citations"], 2)
        domains = {e["domain"]: e for e in surfaces["third_party_sources"]}
        self.assertIn("psychologytoday.com", domains)
        # psychologytoday.com is a known directory in classification_rules.json
        self.assertEqual(domains["psychologytoday.com"]["entity_type"], "directory")

    def test_forum_threads_extracted_with_detail(self):
        threads = self.extracted["forum_threads_by_keyword"]["estrangement"]
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["domain"], "reddit.com")
        self.assertEqual(threads[0]["forum"], "Reddit")
        self.assertEqual(threads[0]["title"], "Estranged from my sister")

    def test_payload_passthrough(self):
        payload = build_main_report_payload(self.extracted)
        self.assertIn("aio_citation_surfaces", payload)
        self.assertIn("estrangement", payload["forum_threads_by_keyword"])
        self.assertTrue(
            payload["keyword_profiles"]["estrangement"]["aio_divergence"]
            ["client_ranks_but_not_cited"]
        )


if __name__ == "__main__":
    unittest.main()
