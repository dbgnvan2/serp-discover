"""
Tests for E-E-A-T author-signal detection.

Spec: seo_geo_deferred_spec_v1.md#G.3
- G.3.1 serp_vocab.yml gains eeat_signals; the loader requires it.
- G.3.2 credential matching: word boundaries for short tokens
  ("harp" must not fire "RP"), substring for multi-word phrases.
- G.3.3 enricher detection: JSON-LD-author page, byline-only page,
  no-author page.
- G.3.4 old analysis JSONs -> data_available False, no crash; payload
  passthrough (canary coverage lives in test_validation_consistency.py).
"""
import os
import tempfile
import unittest

from pattern_matching import load_serp_vocab
from url_enricher import UrlEnricher, match_credential_tokens
from brief_data_extraction import (
    _build_eeat_signals,
    extract_analysis_data_from_json,
)
from brief_prompts import build_main_report_payload


_TEST_VOCAB = {
    "credential_tokens": [
        "RCC", "MSW", "PhD", "RP",
        "registered clinical counsellor",
        "marriage and family therapist",
    ],
    "review_markers": ["medically reviewed", "clinically reviewed",
                       "reviewed by"],
}


def _features_from_html(html, **enricher_kwargs):
    enricher_kwargs.setdefault("eeat_vocab", _TEST_VOCAB)
    enricher = UrlEnricher(**enricher_kwargs)
    return enricher.extract_features({
        "content": html,
        "status_code": 200,
        "headers": {},
        "is_pdf": False,
    })


class TestVocabSection(unittest.TestCase):
    """G.3.1 — eeat_signals is a required serp_vocab.yml section."""

    def test_vocab_has_eeat_signals(self):
        vocab = load_serp_vocab()
        self.assertIn("eeat_signals", vocab)
        self.assertIn("RCC", vocab["eeat_signals"]["credential_tokens"])
        self.assertIn("registered clinical counsellor",
                      vocab["eeat_signals"]["credential_tokens"])
        self.assertIn("medically reviewed",
                      vocab["eeat_signals"]["review_markers"])

    def test_missing_eeat_signals_raises(self):
        # All pre-G.3 required keys present, eeat_signals absent.
        content = (
            "stop_words: [the]\n"
            "paa_category_triggers: {Commercial: [cost]}\n"
            "service_like_tokens: [therapy]\n"
            "ai_alternative_templates: {default: ['x {base}']}\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                load_serp_vocab(path)
            self.assertIn("eeat_signals", str(ctx.exception))
        finally:
            os.unlink(path)


class TestCredentialMatching(unittest.TestCase):
    """G.3.2 — word boundaries for short tokens, substring for phrases."""

    TOKENS = _TEST_VOCAB["credential_tokens"]

    def test_byline_credential_fires(self):
        self.assertIn("RCC", match_credential_tokens("Jane Doe, RCC", self.TOKENS))

    def test_short_token_does_not_fire_inside_word(self):
        hits = match_credential_tokens(
            "She played the harp at the sharp turn", self.TOKENS)
        self.assertNotIn("RP", hits)
        self.assertEqual(hits, [])

    def test_short_token_fires_as_whole_word(self):
        self.assertIn("RP", match_credential_tokens("John Smith, RP", self.TOKENS))

    def test_phrase_fires_as_substring(self):
        hits = match_credential_tokens(
            "Jane is a Registered Clinical Counsellor in North Vancouver",
            self.TOKENS)
        self.assertIn("registered clinical counsellor", hits)

    def test_hits_are_distinct(self):
        hits = match_credential_tokens("RCC and again RCC, MSW", self.TOKENS)
        self.assertEqual(hits.count("RCC"), 1)
        self.assertIn("MSW", hits)


class TestEnricherAuthorSignals(unittest.TestCase):
    """G.3.3 — JSON-LD-author page, byline-only page, no-author page."""

    def test_json_ld_author_page(self):
        html = """
        <html><head><script type="application/ld+json">
        {"@type": "Article", "author": {"@type": "Person",
         "name": "Jane Doe", "honorificSuffix": "RCC"}}
        </script></head><body><p>Body text with no visible byline.</p></body></html>
        """
        features = _features_from_html(html)
        self.assertTrue(features["author_present"])
        self.assertIn("RCC", features["credential_hits"])
        self.assertFalse(features["review_marker_present"])

    def test_byline_only_page(self):
        html = """
        <html><body>
        <div class="author-byline">By John Smith, MSW</div>
        <p>Clinically reviewed by our team.</p>
        </body></html>
        """
        features = _features_from_html(html)
        self.assertTrue(features["author_present"])
        self.assertIn("MSW", features["credential_hits"])
        self.assertTrue(features["review_marker_present"])

    def test_rel_author_link_page(self):
        html = """
        <html><body><a rel="author" href="/about">Jane Doe</a>
        <p>text</p></body></html>
        """
        features = _features_from_html(html)
        self.assertTrue(features["author_present"])

    def test_no_author_page(self):
        html = """
        <html><body><p>Our services help families in North Vancouver.
        We play the harp on Tuesdays.</p></body></html>
        """
        features = _features_from_html(html)
        self.assertFalse(features["author_present"])
        self.assertEqual(features["credential_hits"], [])
        self.assertFalse(features["review_marker_present"])

    def test_scan_window_limits_body_matches(self):
        # Credential appears beyond the scan window -> not counted.
        html = ("<html><body><p>" + ("filler " * 50) +
                "</p><p>Jane Doe, PhD</p></body></html>")
        features = _features_from_html(html, eeat_scan_chars=100)
        self.assertEqual(features["credential_hits"], [])
        # Same page with the default window finds it.
        features_full = _features_from_html(html)
        self.assertIn("PhD", features_full["credential_hits"])


class TestBuildEeatSignals(unittest.TestCase):

    def _rows(self):
        return [
            {"rank": 1, "source": "cred.com", "domain": "cred.com",
             "author_present": True, "credential_hits": ["RCC"],
             "review_marker_present": True},
            {"rank": 2, "source": "plain.com", "domain": "plain.com",
             "author_present": False, "credential_hits": [],
             "review_marker_present": False},
            {"rank": 3, "source": "livingsystems.ca",
             "domain": "livingsystems.ca", "author_present": False,
             "credential_hits": [], "review_marker_present": False},
            {"rank": 4, "source": "unenriched.com"},  # no eeat keys
        ]

    def test_counts_and_client_page(self):
        result = _build_eeat_signals(self._rows(), "livingsystems.ca")
        self.assertTrue(result["data_available"])
        self.assertEqual(len(result["pages"]), 3)
        self.assertEqual(result["credentialed_page_count"], 1)
        self.assertEqual(result["client_page"]["rank"], 3)
        self.assertFalse(result["client_page"]["author_present"])

    def test_no_data_flags_unavailable(self):
        result = _build_eeat_signals(
            [{"rank": 1, "source": "a.com"}], "livingsystems.ca")
        self.assertFalse(result["data_available"])
        self.assertEqual(result["credentialed_page_count"], 0)
        self.assertIsNone(result["client_page"])


class TestOldJsonAndPayload(unittest.TestCase):
    """G.3.4 — old JSONs flow through; payload passthrough."""

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
                # No Author_Present column at all.
            }],
        }
        extracted = extract_analysis_data_from_json(data, "livingsystems.ca")
        eeat = extracted["keyword_profiles"]["family counselling"]["eeat_signals"]
        self.assertFalse(eeat["data_available"])
        self.assertEqual(eeat["pages"], [])

    def test_payload_passthrough(self):
        extracted = {
            "keyword_profiles": {
                "kw": {"eeat_signals": {"data_available": True,
                                        "credentialed_page_count": 7}},
            },
        }
        payload = build_main_report_payload(extracted)
        self.assertEqual(
            payload["keyword_profiles"]["kw"]["eeat_signals"][
                "credentialed_page_count"],
            7,
        )


if __name__ == "__main__":
    unittest.main()
