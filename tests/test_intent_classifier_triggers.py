"""
Tests for Fix I.2 — externalise intent_classifier.py trigger lists to YAML.

Spec: serp_tool1_improvements_spec.md#I.2
"""
import json
import os
import tempfile
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "output",
    "market_analysis_couples_therapy_20260501_1517.json",
)
BASELINE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Previous DEFAULT_MEDICAL_TRIGGERS — recorded verbatim before I.2 change.
_PREV_MEDICAL = frozenset([
    "mental illness", "mental health condition", "evidence-based treatment",
    "evidence based treatment", "cognitive behavioral", "cognitive behavioural",
    "diagnosis", "diagnose", "treatment", "patient", "symptoms", "symptom",
    "disorder", "medication", "medicate", "medicated", "prescription", "fix",
    "heal", "cure", "condition", "clinical", "clinician", "psychiatrist",
    "psychiatry", "pathology", "pathological", "dysfunction", "dysfunctional",
    "illness", "disease", "recovery", "rehabilitation", "intervention",
    "borderline", "narcissist", "narcissistic", "toxic",
])
_PREV_SYSTEMIC = frozenset([
    "family system", "family systems", "emotional system", "emotional process",
    "emotional cutoff", "differentiation of self", "level of differentiation",
    "multigenerational transmission", "nuclear family", "sibling position",
    "societal emotional process", "differentiation", "differentiated",
    "triangulation", "triangle", "triangles", "reactivity", "reactive",
    "cutoff", "functioning", "multigenerational", "intergenerational", "bowen",
    "togetherness", "individuality", "chronic anxiety", "anxiety", "fusion",
    "fused", "projection", "undifferentiated",
])


class TestI21YamlExists(unittest.TestCase):
    """I.2.1 — intent_classifier_triggers.yml exists at repo root."""

    def test_i21_yaml_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "intent_classifier_triggers.yml")
        self.assertTrue(os.path.exists(path),
                        "intent_classifier_triggers.yml must exist at repo root")


class TestI22YamlMatchesPreviousConstants(unittest.TestCase):
    """I.2.2 — YAML values match the previous DEFAULT_* constants (set equality)."""

    @classmethod
    def setUpClass(cls):
        from intent_classifier import load_triggers, _TRIGGERS_CACHE
        import intent_classifier as ic
        ic._TRIGGERS_CACHE = None  # fresh load
        cls.medical, cls.systemic = load_triggers()

    def test_i22_medical_triggers_set_equality(self):
        self.assertEqual(self.medical, _PREV_MEDICAL,
                         "medical triggers from YAML must equal previous DEFAULT_MEDICAL_TRIGGERS")

    def test_i22_systemic_triggers_set_equality(self):
        self.assertEqual(self.systemic, _PREV_SYSTEMIC,
                         "systemic triggers from YAML must equal previous DEFAULT_SYSTEMIC_TRIGGERS")


class TestI23NoHardcodedTriggersInPython(unittest.TestCase):
    """I.2.3 — No DEFAULT_MEDICAL_TRIGGERS or DEFAULT_SYSTEMIC_TRIGGERS in intent_classifier.py."""

    def _read_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "intent_classifier.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_i23_no_default_medical_triggers_constant(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^DEFAULT_MEDICAL_TRIGGERS\s*=",
                            "DEFAULT_MEDICAL_TRIGGERS definition must not exist in intent_classifier.py")

    def test_i23_no_default_systemic_triggers_constant(self):
        src = self._read_source()
        self.assertNotRegex(src, r"^DEFAULT_SYSTEMIC_TRIGGERS\s*=",
                            "DEFAULT_SYSTEMIC_TRIGGERS definition must not exist in intent_classifier.py")


class TestI24ShortTriggerRaises(unittest.TestCase):
    """I.2.4 — Trigger shorter than 3 characters raises ValueError at load."""

    def test_i24_short_trigger_raises(self):
        from intent_classifier import load_triggers
        content = """
version: 1
medical_triggers:
  multi_word: []
  single_word:
    - is
systemic_triggers:
  multi_word: []
  single_word: []
"""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        try:
            with self.assertRaises(ValueError):
                load_triggers(path=f.name)
        finally:
            os.unlink(f.name)


class TestI25ConstructorOverrideStillWorks(unittest.TestCase):
    """I.2.5 — Constructor override hook still works."""

    def test_i25_medical_override_used(self):
        from intent_classifier import IntentClassifier
        custom = frozenset({"specialword"})
        clf = IntentClassifier(medical_triggers=custom)
        self.assertEqual(clf._medical, custom,
                         "passed medical_triggers must override YAML value")

    def test_i25_systemic_override_used(self):
        from intent_classifier import IntentClassifier
        custom = frozenset({"bowenterm"})
        clf = IntentClassifier(systemic_triggers=custom)
        self.assertEqual(clf._systemic, custom,
                         "passed systemic_triggers must override YAML value")


@unittest.skipUnless(os.path.exists(FIXTURE_PATH), "fixture JSON not present")
class TestI26PipelineOutputUnchanged(unittest.TestCase):
    """I.2.6 — PAA intent tags unchanged after externalisation.

    Compares live classifier output against Intent_Tag values stored in the
    fixture JSON (computed before this change). A mismatch means the trigger
    relocation altered classification behaviour.
    """

    @classmethod
    def setUpClass(cls):
        from intent_classifier import IntentClassifier
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        clf = IntentClassifier()
        cls.comparisons = []
        for q in data.get("paa_questions", []):
            text = q.get("Question", "")
            stored = q.get("Intent_Tag")
            live = clf.classify_paa(text)["intent"]
            cls.comparisons.append((text[:60], stored, live))

    def test_i26_live_tags_match_stored_tags(self):
        mismatches = [
            (text, stored, live)
            for text, stored, live in self.comparisons
            if stored != live
        ]
        self.assertEqual(
            mismatches, [],
            f"PAA tags changed after trigger externalisation: {mismatches[:3]}"
        )

    def test_i26_all_questions_classified(self):
        self.assertGreater(len(self.comparisons), 0, "No PAA questions found in fixture")


if __name__ == "__main__":
    unittest.main()
