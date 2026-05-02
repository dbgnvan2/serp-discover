"""
End-to-end integration test for v2 new fields in pipeline JSON output.

Spec: serp_tools_upgrade_spec_v2.md Definition of Done item 3
Spec ID: v2.CC.1
Tests: tests/test_e2e_integration.py::TestV2CC1AllNewFieldsPresent::test_v2_cc1_all_new_fields_present_in_couples_therapy_fixture
"""
import json
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURE_PATH = os.path.join(
    _REPO_ROOT, "output", "market_analysis_couples_therapy_20260501_1517.json"
)

_VALID_INTENTS = {"informational", "commercial_investigation", "transactional", "navigational", "local", "mixed"}
_VALID_STRATEGIES = {None, "compete_on_dominant", "backdoor", "avoid"}
_INTENT_DIST_KEYS = {"informational", "commercial_investigation", "transactional", "navigational", "local"}


def assert_v2_keyword_profile(kw, profile, test_case=None):
    """
    Purpose: Assert every v2 new field exists with the correct type on a single keyword profile.
    Spec:    serp_tools_upgrade_spec_v2.md#Definition-of-Done-item-3
    Tests:   tests/test_e2e_integration.py::test_v2_cc1_all_new_fields_present_in_couples_therapy_fixture

    Can be imported and called by any test or post-run validator:
        from tests.test_e2e_integration import assert_v2_keyword_profile
    """
    def fail(msg):
        if test_case:
            test_case.fail(f"[{kw!r}] {msg}")
        else:
            raise AssertionError(f"[{kw!r}] {msg}")

    def assert_true(cond, msg):
        if not cond:
            fail(msg)

    # ── serp_intent ──────────────────────────────────────────────────────────
    assert_true("serp_intent" in profile, "missing 'serp_intent'")
    si = profile["serp_intent"]
    assert_true(isinstance(si, dict), f"serp_intent must be dict, got {type(si)}")

    primary = si.get("primary_intent")
    assert_true(
        primary is None or isinstance(primary, str),
        f"serp_intent.primary_intent must be str|None, got {type(primary)}",
    )

    is_mixed = si.get("is_mixed")
    assert_true(
        isinstance(is_mixed, bool),
        f"serp_intent.is_mixed must be bool, got {type(is_mixed)}",
    )

    confidence = si.get("confidence")
    assert_true(
        confidence in {"high", "medium", "low"},
        f"serp_intent.confidence must be 'high'|'medium'|'low', got {confidence!r}",
    )

    mixed_components = si.get("mixed_components")
    assert_true(
        isinstance(mixed_components, list),
        f"serp_intent.mixed_components must be list, got {type(mixed_components)}",
    )
    for i, item in enumerate(mixed_components):
        assert_true(
            isinstance(item, str),
            f"serp_intent.mixed_components[{i}] must be str, got {type(item)}",
        )

    dist = si.get("intent_distribution")
    assert_true(
        isinstance(dist, dict),
        f"serp_intent.intent_distribution must be dict, got {type(dist)}",
    )
    assert_true(
        set(dist.keys()) == _INTENT_DIST_KEYS,
        f"serp_intent.intent_distribution keys must be {_INTENT_DIST_KEYS}, got {set(dist.keys())}",
    )
    for intent_key, count in dist.items():
        assert_true(
            isinstance(count, int),
            f"serp_intent.intent_distribution[{intent_key!r}] must be int, got {type(count)}",
        )

    # ── title_patterns ───────────────────────────────────────────────────────
    assert_true("title_patterns" in profile, "missing 'title_patterns'")
    tp = profile["title_patterns"]
    assert_true(isinstance(tp, dict), f"title_patterns must be dict, got {type(tp)}")

    dominant = tp.get("dominant_pattern")
    assert_true(
        dominant is None or isinstance(dominant, str),
        f"title_patterns.dominant_pattern must be str|None, got {type(dominant)}",
    )

    pattern_counts = tp.get("pattern_counts")
    assert_true(
        isinstance(pattern_counts, dict),
        f"title_patterns.pattern_counts must be dict, got {type(pattern_counts)}",
    )
    for pat, cnt in pattern_counts.items():
        assert_true(isinstance(pat, str), f"title_patterns.pattern_counts key must be str, got {type(pat)}")
        assert_true(isinstance(cnt, int), f"title_patterns.pattern_counts[{pat!r}] must be int, got {type(cnt)}")

    # ── mixed_intent_strategy ─────────────────────────────────────────────────
    assert_true(
        "mixed_intent_strategy" in profile,
        "missing 'mixed_intent_strategy'",
    )
    strategy = profile["mixed_intent_strategy"]
    assert_true(
        strategy in _VALID_STRATEGIES,
        f"mixed_intent_strategy must be one of {_VALID_STRATEGIES}, got {strategy!r}",
    )

    # ── No placeholder/template syntax ────────────────────────────────────────
    serialised = json.dumps(profile)
    assert_true(
        "<placeholder>" not in serialised,
        "profile contains '<placeholder>' template syntax",
    )
    for field_name in ("serp_intent", "title_patterns", "mixed_intent_strategy"):
        field_str = json.dumps(profile.get(field_name))
        assert_true(
            not (field_str.startswith('"<') and field_str.endswith('>"')),
            f"{field_name} looks like unrendered template: {field_str!r}",
        )

    # ── Invariant: primary_intent null → classified URL count < 5 ────────────
    if primary is None:
        evidence = si.get("evidence", {})
        classified_count = evidence.get("classified_organic_url_count", 0)
        assert_true(
            classified_count < 5,
            f"primary_intent is null but classified_organic_url_count={classified_count} (expected < 5)",
        )

    # ── Invariant: is_mixed false → mixed_components is empty ────────────────
    if is_mixed is False:
        assert_true(
            mixed_components == [],
            f"is_mixed=False but mixed_components={mixed_components!r} (expected [])",
        )


@unittest.skipUnless(os.path.exists(_FIXTURE_PATH), "fixture JSON not present")
class TestV2CC1AllNewFieldsPresent(unittest.TestCase):
    """
    v2.CC.1 — End-to-end integration test: all new v2 fields present with correct types.

    Purpose: Smoke-test that a complete pipeline run contains every field introduced in
             the v2 upgrade spec. Loads the couples_therapy fixture (an existing pipeline
             output) and calls assert_v2_keyword_profile on each keyword profile.
    Spec:    serp_tools_upgrade_spec_v2.md Definition of Done item 3
    Tests:   this file
    """

    @classmethod
    def setUpClass(cls):
        with open(_FIXTURE_PATH, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_v2_cc1_all_new_fields_present_in_couples_therapy_fixture(self):
        """
        Purpose: Assert every keyword profile in the fixture has all v2 new fields.
        Spec:    serp_tools_upgrade_spec_v2.md#Definition-of-Done-item-3
        Tests:   this function
        """
        keyword_profiles = self.data.get("keyword_profiles", {})
        self.assertGreater(
            len(keyword_profiles), 0,
            "fixture has no keyword_profiles — fixture may be corrupt",
        )
        for kw, profile in keyword_profiles.items():
            with self.subTest(keyword=kw):
                assert_v2_keyword_profile(kw, profile, test_case=self)
