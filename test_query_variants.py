"""Tests for query_variants.is_service_like — the shared service-intent gate.

Spec: seo_geo_review_20260704.md (chip B, B.1.a). The predicate is the single
source of the "service-like" definition reused by the AI-alternative generator
and the hyper-local pivot gate; the token list stays editorial in
serp_vocab.yml.
"""
import unittest

from pattern_matching import SERP_VOCAB
from query_variants import ai_query_alternatives, is_service_like

SERVICE_TOKENS = SERP_VOCAB["service_like_tokens"]
AI_TEMPLATES = SERP_VOCAB["ai_alternative_templates"]


class TestIsServiceLike(unittest.TestCase):
    def test_b1a_service_keyword_is_service_like(self):
        self.assertTrue(is_service_like("Couples Counselling North Vancouver", SERVICE_TOKENS))
        self.assertTrue(is_service_like("family therapy", SERVICE_TOKENS))
        self.assertTrue(is_service_like("registered psychologist Lonsdale", SERVICE_TOKENS))

    def test_b1a_informational_keyword_is_not_service_like(self):
        # Adversarial: reads plausibly local (has a neighbourhood) but nobody
        # searches an informational question with a neighbourhood — no service token.
        self.assertFalse(
            is_service_like("how does birth order affect personality West Vancouver", SERVICE_TOKENS)
        )
        self.assertFalse(is_service_like("what is differentiation of self", SERVICE_TOKENS))
        self.assertFalse(is_service_like("signs of a toxic parent", SERVICE_TOKENS))

    def test_b1a_empty_keyword_is_not_service_like(self):
        self.assertFalse(is_service_like("", SERVICE_TOKENS))
        self.assertFalse(is_service_like(None, SERVICE_TOKENS))

    def test_b1a_city_delocalisation_does_not_change_service_verdict(self):
        # De-localising is harmless for the boolean: a service token present in
        # the delocalised core is still present.
        self.assertTrue(
            is_service_like("Couples Counselling North Vancouver", SERVICE_TOKENS, city="North Vancouver")
        )
        self.assertFalse(
            is_service_like("how does birth order affect personality West Vancouver",
                            SERVICE_TOKENS, city="West Vancouver")
        )


class TestAiQueryAlternativesUnaffected(unittest.TestCase):
    """The refactor of ai_query_alternatives onto is_service_like must not
    change its branch selection (regression guard)."""

    def test_b1a_service_branch_still_selected(self):
        alts = ai_query_alternatives("couples counselling", "North Vancouver",
                                     SERVICE_TOKENS, AI_TEMPLATES)
        self.assertTrue(alts)

    def test_b1a_default_branch_for_informational(self):
        alts = ai_query_alternatives("family estrangement", "North Vancouver",
                                     SERVICE_TOKENS, AI_TEMPLATES)
        self.assertTrue(alts)


if __name__ == "__main__":
    unittest.main()
