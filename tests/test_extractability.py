"""
Tests for answer-extractability signals.

Spec: seo_geo_review_20260704.md T.2
- url_enricher measures question-shaped H2/H3 headings, intro length
  before the first H2, and (already) FAQ presence.
- brief_data_extraction compares those signals on AIO-cited vs uncited
  ranking pages and locates the client's own page.
"""
import unittest

from url_enricher import UrlEnricher, _is_question_shaped
from brief_data_extraction import _build_extractability
from brief_prompts import build_main_report_payload


def _features_from_html(html):
    enricher = UrlEnricher()
    return enricher.extract_features({
        "content": html,
        "status_code": 200,
        "headers": {},
        "is_pdf": False,
    })


class TestQuestionShapeDetection(unittest.TestCase):

    def test_question_shapes(self):
        for text in (
            "How to choose a couples counsellor",
            "What is differentiation of self?",
            "Is couples therapy worth it",
            "Why do families become estranged?",
            "Can therapy help after an affair?",
        ):
            self.assertTrue(_is_question_shaped(text), text)

    def test_non_question_shapes(self):
        for text in ("Our Services", "Couples Counselling North Vancouver",
                     "About Living Systems"):
            self.assertFalse(_is_question_shaped(text), text)


class TestEnricherExtractabilityFeatures(unittest.TestCase):

    def test_question_headings_counted(self):
        html = """
        <html><head><title>t</title></head><body>
        <p>Short intro.</p>
        <h2>How does couples therapy work?</h2><p>Answer first.</p>
        <h3>What is differentiation of self?</h3><p>Answer.</p>
        <h2>Our Services</h2><p>List.</p>
        </body></html>
        """
        features = _features_from_html(html)
        self.assertEqual(features["question_heading_count"], 2)
        self.assertEqual(len(features["question_headings"]), 2)
        self.assertIn("How does couples therapy work?", features["question_headings"])

    def test_intro_length_measures_text_before_first_h2(self):
        buried = "<html><body>" + "<p>" + ("warm-up " * 100) + "</p>" \
            + "<h2>How to get help?</h2><p>answer</p></body></html>"
        lean = "<html><body><p>Quick.</p><h2>How to get help?</h2><p>answer</p></body></html>"
        self.assertGreater(
            _features_from_html(buried)["intro_text_length"],
            _features_from_html(lean)["intro_text_length"],
        )

    def test_no_h2_uses_full_text_length(self):
        html = "<html><body><p>" + ("prose " * 50) + "</p></body></html>"
        features = _features_from_html(html)
        self.assertGreater(features["intro_text_length"], 100)


class TestBuildExtractability(unittest.TestCase):

    def _rows(self):
        return [
            {"rank": 1, "source": "cited.com", "domain": "cited.com",
             "question_heading_count": 4, "question_headings": [
                 "How do I cope with estrangement?", "What is family therapy?"],
             "intro_text_length": 150, "faq_present": True},
            {"rank": 2, "source": "plain.com", "domain": "plain.com",
             "question_heading_count": 0, "question_headings": [],
             "intro_text_length": 2000, "faq_present": False},
            {"rank": 3, "source": "livingsystems.ca", "domain": "livingsystems.ca",
             "question_heading_count": 1, "question_headings": ["Why choose us?"],
             "intro_text_length": 900, "faq_present": False},
            {"rank": 4, "source": "unenriched.com"},  # no extractability data
        ]

    def test_summary_and_client_page(self):
        result = _build_extractability(
            self._rows(),
            cited_domains={"cited.com": {"count": 2, "example_link": None}},
            paa_questions=["How do I cope with estrangement?"],
            client_domain_lower="livingsystems.ca",
        )
        self.assertTrue(result["data_available"])
        self.assertEqual(len(result["pages"]), 3)
        self.assertEqual(result["cited_avg_question_headings"], 4.0)
        self.assertEqual(result["uncited_avg_question_headings"], 0.5)
        self.assertEqual(result["client_page"]["rank"], 3)
        cited_page = result["pages"][0]
        self.assertTrue(cited_page["is_cited_in_aio"])
        self.assertEqual(cited_page["headings_matching_paa"], 1)

    def test_no_data_flags_unavailable(self):
        result = _build_extractability(
            [{"rank": 1, "source": "a.com"}], {}, [], "livingsystems.ca"
        )
        self.assertFalse(result["data_available"])
        self.assertIsNone(result["client_page"])

    def test_payload_passthrough(self):
        extracted = {
            "keyword_profiles": {
                "kw": {"extractability": {"data_available": True, "pages": []}},
            },
        }
        payload = build_main_report_payload(extracted)
        self.assertTrue(
            payload["keyword_profiles"]["kw"]["extractability"]["data_available"]
        )


if __name__ == "__main__":
    unittest.main()
