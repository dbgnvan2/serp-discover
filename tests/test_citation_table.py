"""Tests for Y.8 categorized, brand-attributed citation table (citation_table.py).

Spec: yoast_geo_upgrade_spec_v1.md#Y.8
- Y.8.1 category sourced from the EXISTING classifier (publisher + directory).
- Y.8.2 brand attribution via gazetteer/domain; unknown→null; client flagged.
- Y.8.3 URL de-dup with cite_count; tracking params preserved.
- Y.8.4 table idempotent, per-engine, UTC ts.
"""
import os
import tempfile
import unittest

import citation_table as ct


class TestCategoryFromExistingClassifier(unittest.TestCase):
    def test_publisher_and_directory_labels(self):
        # Y.8.1: labels come from the existing editorial files (classifiers.py +
        # classification_rules.json). "publisher" was added there, not here.
        answers = [{"source_urls": [
            "https://wikipedia.org/wiki/Family_therapy",  # publisher
            "https://www.psychologytoday.com/us/therapists",  # directory
        ]}]
        table = ct.build_citation_table(answers, "livingsystems.ca")
        by_domain = {r["domain"]: r["category"] for r in table}
        self.assertEqual(by_domain["wikipedia.org"], "publisher")
        self.assertEqual(by_domain["psychologytoday.com"], "directory")

    def test_unknown_domain_falls_to_other(self):
        table = ct.build_citation_table(
            [{"source_urls": ["https://randomsite.example/x"]}], "livingsystems.ca")
        self.assertEqual(table[0]["category"], "other")


class TestBrandAttribution(unittest.TestCase):
    def test_gazetteer_and_domain_match(self):
        # Y.8.2
        table = ct.build_citation_table(
            [{"source_urls": [
                "https://www.psychologytoday.com/x",
                "https://theravive.com/y",
                "https://unknownsite.example/z",
            ]}],
            client_domain="livingsystems.ca",
            brand_domains={"psychologytoday.com": "Psychology Today"},
            brand_names=["Theravive"])
        by_domain = {r["domain"]: r["brand"] for r in table}
        self.assertEqual(by_domain["psychologytoday.com"], "Psychology Today")
        self.assertEqual(by_domain["theravive.com"], "Theravive")
        self.assertIsNone(by_domain["unknownsite.example"])  # unknown → null

    def test_client_flag(self):
        table = ct.build_citation_table(
            [{"source_urls": ["https://www.livingsystems.ca/about"]}],
            client_domain="livingsystems.ca",
            brand_domains={"livingsystems.ca": "Living Systems"})
        self.assertTrue(table[0]["is_client"])
        self.assertEqual(table[0]["brand"], "Living Systems")


class TestDedupAndTrackingParams(unittest.TestCase):
    def test_dedup_cite_count_and_tracking_params_preserved(self):
        # Y.8.3: identical URL merged with count; utm param NOT stripped.
        url = "https://www.psychologytoday.com/x?utm_source=openai"
        table = ct.build_citation_table(
            [{"source_urls": [url]}, {"source_urls": [url]},
             {"source_urls": ["https://other.example/a"]}],
            "livingsystems.ca")
        pt = [r for r in table if r["domain"] == "psychologytoday.com"][0]
        self.assertEqual(pt["cite_count"], 2)
        self.assertEqual(pt["url"], url)  # tracking param retained verbatim
        self.assertIn("utm_source=openai", pt["url"])

    def test_top_cited_and_citations_axis(self):
        table = ct.build_citation_table(
            [{"source_urls": ["https://www.livingsystems.ca/a"]},
             {"source_urls": ["https://a.example/x", "https://a.example/y"]}],
            "livingsystems.ca")
        # 1 client cite of 3 → 33.33
        self.assertAlmostEqual(ct.citations_axis(table), round(100 / 3, 2))
        top = ct.top_cited_domains(table)
        self.assertEqual(top[0][0], "a.example")
        self.assertEqual(top[0][1], 2)

    def test_empty_table_axis_zero(self):
        self.assertEqual(ct.citations_axis([]), 0.0)


class TestPersistence(unittest.TestCase):
    def test_table_idempotent_per_engine(self):
        # Y.8.4
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ct.init_citations_table(path)
            ct.init_citations_table(path)  # idempotent
            table = ct.build_citation_table(
                [{"source_urls": ["https://a.example/x?utm_source=openai"]}],
                "livingsystems.ca")
            ct.save_citations(path, "2026-01-01T00:00:00+00:00", "openai", table)
            got = ct.get_citations_for_run(path, "2026-01-01T00:00:00+00:00", "openai")
            self.assertEqual(len(got), 1)
            self.assertIn("utm_source=openai", got[0]["url"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
