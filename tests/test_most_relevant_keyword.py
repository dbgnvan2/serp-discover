"""
Tests for Fix I.3 — three-component keyword scoring in _get_most_relevant_keyword.

Spec: serp_tool1_improvements_spec.md#I.3

Note on I.3.4: The spec expected a fixture-based test demonstrating that the
Medical Model Trap no longer selects the cost keyword. The
output/market_analysis_couples_therapy_20260501_1517.json fixture contains
16 PAA questions all tagged 'General' (none are External Locus), so the PAA
component is zero for all keywords in that run. I.3.4 is therefore implemented
as a synthetic unit test that directly proves the PAA component drives
selection when External Locus data is present. The fixture gap is documented
in docs/i_phaseA_status_20260501.md.
"""
import os
import unittest

# Minimal synthetic fixtures for unit tests

_KW_PROFILES = {
    "therapy options": {"serp_intent": {"primary_intent": "informational", "is_mixed": False, "confidence": "high"}},
    "how much does it cost": {"serp_intent": {"primary_intent": "commercial_investigation", "is_mixed": False, "confidence": "medium"}},
    "family systems counselling": {"serp_intent": {"primary_intent": "informational", "is_mixed": False, "confidence": "high"}},
}

_ORGANIC = [
    {"Root_Keyword": "therapy options", "Title": "Find a registered clinical therapist", "Snippet": "Get a diagnosis and treatment plan"},
    {"Root_Keyword": "therapy options", "Title": "Mental health treatment options", "Snippet": "Clinical intervention for disorder"},
    {"Root_Keyword": "how much does it cost", "Title": "Therapy cost guide", "Snippet": "Affordable options"},
    {"Root_Keyword": "how much does it cost", "Title": "How much does counselling cost?", "Snippet": "Prices vary"},
    {"Root_Keyword": "family systems counselling", "Title": "What is Bowen theory?", "Snippet": "Differentiation of self"},
]

_PAA_QUESTIONS = [
    {"Source_Keyword": "therapy options", "Intent_Tag": "External Locus", "Question": "What is the diagnosis?"},
    {"Source_Keyword": "therapy options", "Intent_Tag": "External Locus", "Question": "Do I have a disorder?"},
    {"Source_Keyword": "how much does it cost", "Intent_Tag": "General", "Question": "How much is therapy?"},
    {"Source_Keyword": "family systems counselling", "Intent_Tag": "Systemic", "Question": "What is differentiation?"},
]

_REC_MEDICAL = {
    "Pattern_Name": "The Medical Model Trap",
    "Detected_Triggers": "clinical, diagnosis, treatment",
}
_REC_FUSION = {
    "Pattern_Name": "The Fusion Trap",
    "Detected_Triggers": "reconnect, contact",
}
_REC_NO_TRIGGERS = {
    "Pattern_Name": "The Medical Model Trap",
    "Detected_Triggers": "",
}


class TestI31ThreeComponentScoring(unittest.TestCase):
    """I.3.1 — _get_most_relevant_keyword uses three-component scoring."""

    def test_i31_three_component_scoring(self):
        from generate_insight_report import _get_most_relevant_keyword, _PATTERN_INTENT_CLASS_CACHE, _KEYWORD_HINTS_CACHE
        import generate_insight_report as gir

        # Reset caches to ensure fresh load from YAML
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        result = _get_most_relevant_keyword(_REC_MEDICAL, _ORGANIC, _KW_PROFILES, _PAA_QUESTIONS)
        # "therapy options" has 2 External Locus PAA questions (PAA score = 6)
        # plus trigger matches in organic results — must win
        self.assertEqual(result, "therapy options",
                         "Medical Model Trap should select 'therapy options' (high PAA score)")


class TestI32PaaIntentClassContributes(unittest.TestCase):
    """I.3.2 — PAA component contributes when Relevant_Intent_Class is set."""

    def test_i32_paa_intent_class_contributes(self):
        from generate_insight_report import _get_most_relevant_keyword
        import generate_insight_report as gir
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        # "therapy options" has 2 External Locus PAA questions → score contribution = 6
        # "how much does it cost" has 0 External Locus PAA questions → PAA score = 0
        # Verify "therapy options" wins despite "how much does it cost" having more trigger matches
        organic_cost_heavy = [
            {"Root_Keyword": "how much does it cost", "Title": "clinical disorder treatment diagnosis intervention", "Snippet": "clinical clinical clinical"},
            {"Root_Keyword": "therapy options", "Title": "therapy", "Snippet": "session"},
        ]
        result = _get_most_relevant_keyword(_REC_MEDICAL, organic_cost_heavy, _KW_PROFILES, _PAA_QUESTIONS)
        self.assertEqual(result, "therapy options",
                         "PAA component (weight 3) should override trigger-text advantage of cost keyword")


class TestI33NoIntentClassFallsBack(unittest.TestCase):
    """I.3.3 — PAA component is 0 when Relevant_Intent_Class absent (Fusion/Resource Trap)."""

    def test_i33_no_intent_class_paa_score_is_zero(self):
        from generate_insight_report import _get_most_relevant_keyword, _load_pattern_intent_classes
        import generate_insight_report as gir
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        # Fusion Trap has no Relevant_Intent_Class → PAA score must be 0
        # Result should be driven by trigger-text only
        paa_all_external = [
            {"Source_Keyword": "therapy options", "Intent_Tag": "External Locus", "Question": "q"},
            {"Source_Keyword": "family systems counselling", "Intent_Tag": "External Locus", "Question": "q"},
        ]
        # Fusion triggers: reconnect, contact — only appear in family_systems organic below
        organic_fusion = [
            {"Root_Keyword": "therapy options", "Title": "Reconnect with your family", "Snippet": "make contact"},
            {"Root_Keyword": "family systems counselling", "Title": "No reconnection mentioned", "Snippet": "plain text"},
        ]
        result = _get_most_relevant_keyword(_REC_FUSION, organic_fusion, _KW_PROFILES, paa_all_external)
        # PAA score must be 0 for both → trigger-text drives the result
        self.assertEqual(result, "therapy options",
                         "Without Relevant_Intent_Class, trigger-text drives selection")


class TestI34MedicalModelPicksExternalLocusKeyword(unittest.TestCase):
    """I.3.4 — Medical Model Trap selects keyword with External Locus PAA questions.

    Synthetic test: demonstrates that a keyword with External Locus PAA tags
    is preferred over a keyword with only trigger-text matches. The
    couples_therapy_1517 fixture has no External Locus PAA tags, so this
    criterion is verified via synthetic data rather than the fixture.
    """

    def test_i34_medical_model_picks_external_locus_keyword(self):
        from generate_insight_report import _get_most_relevant_keyword
        import generate_insight_report as gir
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        kw_profiles = {
            "couples counselling": {},
            "how much is couples therapy": {},
        }
        organic = [
            # "how much is couples therapy" has lots of clinical language in competitor titles
            {"Root_Keyword": "how much is couples therapy", "Title": "Clinical registered therapist", "Snippet": "diagnosis treatment disorder"},
            {"Root_Keyword": "how much is couples therapy", "Title": "Registered clinical therapist cost", "Snippet": "disorder treatment clinical"},
            {"Root_Keyword": "couples counselling", "Title": "Session info", "Snippet": "couples session"},
        ]
        paa = [
            # "couples counselling" has 2 External Locus PAA questions
            {"Source_Keyword": "couples counselling", "Intent_Tag": "External Locus", "Question": "Do I have a disorder?"},
            {"Source_Keyword": "couples counselling", "Intent_Tag": "External Locus", "Question": "What diagnosis applies?"},
            # "how much is couples therapy" has only General PAA
            {"Source_Keyword": "how much is couples therapy", "Intent_Tag": "General", "Question": "How much does it cost?"},
        ]
        rec = {"Pattern_Name": "The Medical Model Trap", "Detected_Triggers": "clinical, diagnosis, treatment"}

        result = _get_most_relevant_keyword(rec, organic, kw_profiles, paa)
        self.assertEqual(
            result, "couples counselling",
            "Medical Model Trap must prefer keyword with External Locus PAA questions "
            "over keyword with only clinical-language competitor titles"
        )


class TestI35AllZeroReturnsNone(unittest.TestCase):
    """I.3.5 — When all keywords score 0, returns None."""

    def test_i35_all_zero_returns_none(self):
        from generate_insight_report import _get_most_relevant_keyword
        import generate_insight_report as gir
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        organic = [
            {"Root_Keyword": "unrelated keyword", "Title": "Nothing here", "Snippet": "no matches"},
        ]
        kw_profiles = {"unrelated keyword": {}}
        paa = []
        rec = {"Pattern_Name": "The Medical Model Trap", "Detected_Triggers": "zzznomatch"}
        result = _get_most_relevant_keyword(rec, organic, kw_profiles, paa)
        self.assertIsNone(result, "All-zero scores must return None")

    def test_i35_empty_organic_returns_none(self):
        from generate_insight_report import _get_most_relevant_keyword
        import generate_insight_report as gir
        gir._PATTERN_INTENT_CLASS_CACHE = None
        gir._KEYWORD_HINTS_CACHE = None

        result = _get_most_relevant_keyword(_REC_MEDICAL, [], _KW_PROFILES, _PAA_QUESTIONS)
        self.assertIsNone(result, "Empty organic_results must return None")


if __name__ == "__main__":
    unittest.main()
