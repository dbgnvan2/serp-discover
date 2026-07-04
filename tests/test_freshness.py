"""
Tests for content freshness / decay tracking.

Spec: seo_geo_deferred_spec_v1.md#G.6
- G.6.1 url_enricher extracts published_time/modified_time from
  article:* meta, JSON-LD, or <time datetime=...>; no-date pages yield None.
- G.6.2 age_days is computed against the run's Created_At, not wall-clock.
- G.6.3 old analysis JSONs (no date columns) -> data_available False, no crash.
- G.6.4 keyword_profiles.freshness reaches the LLM payload.
- G.6.5 canary allowlist entry (covered by test_validation_consistency.py).
"""
import unittest

from url_enricher import UrlEnricher
from brief_data_extraction import (
    _build_freshness,
    _parse_iso_datetime,
    extract_analysis_data_from_json,
)
from brief_prompts import build_main_report_payload


def _features_from_html(html):
    enricher = UrlEnricher()
    return enricher.extract_features({
        "content": html,
        "status_code": 200,
        "headers": {},
        "is_pdf": False,
    })


class TestEnricherDateExtraction(unittest.TestCase):
    """G.6.1 — each date source produces the expected fields."""

    def test_meta_tag_page(self):
        html = """
        <html><head>
        <meta property="article:published_time" content="2026-01-10T08:00:00+00:00">
        <meta property="article:modified_time" content="2026-03-02T09:30:00+00:00">
        </head><body><p>text</p></body></html>
        """
        features = _features_from_html(html)
        self.assertEqual(features["published_time"], "2026-01-10T08:00:00+00:00")
        self.assertEqual(features["modified_time"], "2026-03-02T09:30:00+00:00")

    def test_json_ld_page(self):
        html = """
        <html><head><script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Article",
         "datePublished": "2025-11-20", "dateModified": "2026-02-14"}
        </script></head><body><p>text</p></body></html>
        """
        features = _features_from_html(html)
        self.assertEqual(features["published_time"], "2025-11-20")
        self.assertEqual(features["modified_time"], "2026-02-14")

    def test_meta_beats_json_ld(self):
        html = """
        <html><head>
        <meta property="article:published_time" content="2026-01-01">
        <script type="application/ld+json">
        {"@type": "Article", "datePublished": "2020-01-01",
         "dateModified": "2026-02-02"}
        </script></head><body><p>text</p></body></html>
        """
        features = _features_from_html(html)
        # Meta wins for published; JSON-LD fills the missing modified.
        self.assertEqual(features["published_time"], "2026-01-01")
        self.assertEqual(features["modified_time"], "2026-02-02")

    def test_time_element_page(self):
        html = """
        <html><body>
        <time datetime="2026-04-05">April 5, 2026</time>
        <p>text</p>
        </body></html>
        """
        features = _features_from_html(html)
        self.assertEqual(features["published_time"], "2026-04-05")
        self.assertIsNone(features["modified_time"])

    def test_no_date_page(self):
        html = "<html><body><p>Undated service page.</p></body></html>"
        features = _features_from_html(html)
        self.assertIsNone(features["published_time"])
        self.assertIsNone(features["modified_time"])


class TestIsoParsing(unittest.TestCase):

    def test_trailing_z_is_trimmed(self):
        parsed = _parse_iso_datetime("2026-01-10T08:00:00Z")
        self.assertEqual(parsed.year, 2026)
        self.assertIsNone(parsed.tzinfo)

    def test_unparseable_returns_none(self):
        for bad in ("last Tuesday", "2026-13-45", "", None, "N/A"):
            self.assertIsNone(_parse_iso_datetime(bad), bad)

    def test_offset_normalized_to_utc(self):
        parsed = _parse_iso_datetime("2026-01-10T08:00:00-08:00")
        self.assertEqual(parsed.hour, 16)


class TestBuildFreshness(unittest.TestCase):
    """G.6.2 — ages anchored to run Created_At; undated pages counted honestly."""

    RUN_CREATED_AT = "2026-07-01T12:00:00"

    def _rows(self):
        return [
            {"rank": 1, "source": "fresh.com", "domain": "fresh.com",
             "published_time": "2026-06-01T12:00:00",
             "modified_time": "2026-06-21T12:00:00"},
            {"rank": 2, "source": "stale.com", "domain": "stale.com",
             "published_time": "2024-07-01T12:00:00", "modified_time": None},
            {"rank": 3, "source": "livingsystems.ca", "domain": "livingsystems.ca",
             "published_time": "2026-05-02T12:00:00", "modified_time": None},
            {"rank": 4, "source": "undated.com", "domain": "undated.com",
             "published_time": None, "modified_time": None},
            {"rank": 5, "source": "unenriched.com"},  # no freshness keys
        ]

    def test_exact_ages_from_fixture_dates(self):
        result = _build_freshness(self._rows(), self.RUN_CREATED_AT,
                                  "livingsystems.ca")
        self.assertTrue(result["data_available"])
        by_rank = {p["rank"]: p for p in result["pages"]}
        # modified_time preferred over published_time for age.
        self.assertEqual(by_rank[1]["age_days"], 10)
        self.assertEqual(by_rank[2]["age_days"], 730)
        self.assertEqual(by_rank[3]["age_days"], 60)
        self.assertIsNone(by_rank[4]["age_days"])  # undated != age 0
        self.assertNotIn(5, by_rank)  # unenriched row excluded
        self.assertEqual(result["dated_page_count"], 3)
        self.assertEqual(result["median_age_days"], 60)
        self.assertEqual(result["client_page"]["rank"], 3)

    def test_ages_independent_of_wall_clock(self):
        # Same fixture, different run anchor -> different exact ages.
        result = _build_freshness(self._rows(), "2026-07-31T12:00:00",
                                  "livingsystems.ca")
        by_rank = {p["rank"]: p for p in result["pages"]}
        self.assertEqual(by_rank[1]["age_days"], 40)

    def test_even_count_median_averages_middle_pair(self):
        rows = [
            {"rank": 1, "source": "a.com", "domain": "a.com",
             "published_time": "2026-06-21T12:00:00", "modified_time": None},
            {"rank": 2, "source": "b.com", "domain": "b.com",
             "published_time": "2026-06-11T12:00:00", "modified_time": None},
            {"rank": 3, "source": "c.com", "domain": "c.com",
             "published_time": "2026-05-02T12:00:00", "modified_time": None},
            {"rank": 4, "source": "d.com", "domain": "d.com",
             "published_time": "2026-01-02T12:00:00", "modified_time": None},
        ]
        result = _build_freshness(rows, self.RUN_CREATED_AT, "livingsystems.ca")
        # ages 10, 20, 60, 180 -> median (20 + 60) / 2
        self.assertEqual(result["median_age_days"], 40.0)

    def test_unparseable_run_created_at_yields_null_ages(self):
        result = _build_freshness(self._rows(), "unknown", "livingsystems.ca")
        self.assertTrue(result["data_available"])
        self.assertTrue(all(p["age_days"] is None for p in result["pages"]))
        self.assertEqual(result["dated_page_count"], 0)
        self.assertIsNone(result["median_age_days"])

    def test_no_freshness_rows_flags_unavailable(self):
        result = _build_freshness(
            [{"rank": 1, "source": "a.com"}], self.RUN_CREATED_AT,
            "livingsystems.ca")
        self.assertFalse(result["data_available"])
        self.assertEqual(result["dated_page_count"], 0)
        self.assertIsNone(result["client_page"])


class TestOldJsonCompatibility(unittest.TestCase):
    """G.6.3 — analysis JSONs predating date capture flow through extraction."""

    def test_old_json_yields_data_available_false(self):
        data = {
            "overview": [{
                "Run_ID": "r1", "Created_At": "2026-07-01T12:00:00",
                "Source_Keyword": "family counselling", "Query_Label": "A",
                "Total_Results": 1000,
            }],
            "organic_results": [{
                "Source_Keyword": "family counselling", "Query_Label": "A",
                "Rank": 1, "Title": "t", "Source": "a.com",
                "Link": "https://a.com/p", "Snippet": "s",
                # No Published_Time / Modified_Time columns at all.
            }],
        }
        extracted = extract_analysis_data_from_json(data, "livingsystems.ca")
        freshness = extracted["keyword_profiles"]["family counselling"]["freshness"]
        self.assertFalse(freshness["data_available"])
        self.assertEqual(freshness["pages"], [])


class TestPayloadPassthrough(unittest.TestCase):
    """G.6.4 — keyword_profiles.freshness reaches the LLM payload."""

    def test_payload_passthrough(self):
        extracted = {
            "keyword_profiles": {
                "kw": {"freshness": {"data_available": True,
                                     "median_age_days": 42}},
            },
        }
        payload = build_main_report_payload(extracted)
        self.assertEqual(
            payload["keyword_profiles"]["kw"]["freshness"]["median_age_days"],
            42,
        )


if __name__ == "__main__":
    unittest.main()
