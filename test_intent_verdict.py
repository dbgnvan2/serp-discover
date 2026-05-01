"""Unit tests for intent_verdict.py.

Covers:
  - YAML schema validation (load_mapping)
  - Each rule path in intent_mapping.yml fires correctly
  - Aggregation: distribution, primary_intent, is_mixed, confidence
  - Edge cases: empty SERP, all uncategorised, exactly-on-threshold, ties
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from intent_verdict import (
    DEFAULT_THRESHOLDS,
    VALID_INTENTS,
    _classify_url,
    _domain_role_for_url,
    _matches_rule,
    compute_serp_intent,
    load_mapping,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_mapping():
    """The committed intent_mapping.yml — proves the file we ship loads."""
    return load_mapping()


@pytest.fixture
def minimal_mapping():
    """A tiny in-memory mapping for isolated rule tests."""
    return {
        "version": 1,
        "rules": [
            {
                "match": {
                    "domain_role": "client",
                    "content_type": "any",
                    "entity_type": "any",
                    "local_pack": "any",
                },
                "intent": "navigational",
            },
            {
                "match": {
                    "content_type": "guide",
                    "entity_type": "any",
                    "local_pack": "any",
                    "domain_role": "any",
                },
                "intent": "informational",
            },
            {
                "match": {
                    "content_type": "service",
                    "entity_type": "counselling",
                    "local_pack": "yes",
                    "domain_role": "any",
                },
                "intent": "local",
            },
            {
                "match": {
                    "content_type": "any",
                    "entity_type": "any",
                    "local_pack": "any",
                    "domain_role": "any",
                },
                "intent": "uncategorised",
            },
        ],
    }


def _row(rank, link, content_type, entity_type, title="t", source=None):
    return {
        "rank": rank,
        "title": title,
        "source": source or link,
        "link": link,
        "content_type": content_type,
        "entity_type": entity_type,
    }


# ─── load_mapping schema validation ──────────────────────────────────────────


class TestLoadMapping:
    def test_loads_real_yaml(self, real_mapping):
        assert "rules" in real_mapping
        assert len(real_mapping["rules"]) > 0

    def test_real_yaml_has_catch_all(self, real_mapping):
        last = real_mapping["rules"][-1]
        assert all(v == "any" for v in last["match"].values())

    def test_real_yaml_yes_no_are_strings(self, real_mapping):
        # Regression: PyYAML would otherwise convert unquoted yes/no to booleans
        # and break string comparison in the matcher.
        for rule in real_mapping["rules"]:
            lp = rule["match"]["local_pack"]
            assert lp in ("yes", "no", "any"), f"local_pack={lp!r} got bool-converted"

    def test_real_yaml_intents_are_valid(self, real_mapping):
        for rule in real_mapping["rules"]:
            assert rule["intent"] in VALID_INTENTS

    def test_rejects_missing_rules(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text("version: 1\n")
        with pytest.raises(ValueError, match="missing top-level 'rules'"):
            load_mapping(str(bad))

    def test_rejects_invalid_intent(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text(yaml.safe_dump({
            "rules": [{
                "match": {"content_type": "any", "entity_type": "any",
                          "local_pack": "any", "domain_role": "any"},
                "intent": "buying",
            }]
        }))
        with pytest.raises(ValueError, match="invalid intent"):
            load_mapping(str(bad))

    def test_rejects_missing_match_key(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text(yaml.safe_dump({
            "rules": [{
                "match": {"content_type": "any", "entity_type": "any",
                          "local_pack": "any"},  # missing domain_role
                "intent": "informational",
            }]
        }))
        with pytest.raises(ValueError, match="missing key"):
            load_mapping(str(bad))


# ─── _domain_role_for_url ────────────────────────────────────────────────────


class TestDomainRole:
    def test_client_match(self):
        assert _domain_role_for_url(
            "https://livingsystems.ca/about", "livingsystems.ca", []
        ) == "client"

    def test_known_competitor_match(self):
        assert _domain_role_for_url(
            "https://example-rival.ca/foo",
            "livingsystems.ca",
            ["example-rival.ca"],
        ) == "known_competitor"

    def test_other_when_no_match(self):
        assert _domain_role_for_url(
            "https://psychologytoday.com/x", "livingsystems.ca", []
        ) == "other"

    def test_client_takes_precedence_over_known(self):
        # If client domain accidentally appears in known_brands, client wins.
        assert _domain_role_for_url(
            "https://livingsystems.ca/x",
            "livingsystems.ca",
            ["livingsystems.ca"],
        ) == "client"

    def test_empty_link_returns_other(self):
        assert _domain_role_for_url("", "livingsystems.ca", []) == "other"

    def test_case_insensitive(self):
        assert _domain_role_for_url(
            "https://LivingSystems.ca/x", "livingsystems.ca", []
        ) == "client"


# ─── _matches_rule ───────────────────────────────────────────────────────────


class TestMatchesRule:
    def test_any_matches_anything(self):
        assert _matches_rule(
            {"content_type": "any", "entity_type": "any",
             "local_pack": "any", "domain_role": "any"},
            {"content_type": "guide", "entity_type": "media",
             "local_pack": "yes", "domain_role": "other"},
        )

    def test_specific_must_match_exactly(self):
        assert not _matches_rule(
            {"content_type": "service", "entity_type": "any",
             "local_pack": "any", "domain_role": "any"},
            {"content_type": "guide", "entity_type": "any",
             "local_pack": "any", "domain_role": "any"},
        )

    def test_yes_does_not_match_no(self):
        assert not _matches_rule(
            {"content_type": "any", "entity_type": "any",
             "local_pack": "yes", "domain_role": "any"},
            {"content_type": "guide", "entity_type": "any",
             "local_pack": "no", "domain_role": "any"},
        )


# ─── _classify_url with minimal_mapping ──────────────────────────────────────


class TestClassifyUrl:
    def test_client_overrides_content(self, minimal_mapping):
        # Client URL with content_type=guide → client rule fires first → navigational
        intent = _classify_url(
            {"content_type": "guide", "entity_type": "counselling",
             "local_pack": "yes", "domain_role": "client"},
            minimal_mapping["rules"],
        )
        assert intent == "navigational"

    def test_guide_when_not_client(self, minimal_mapping):
        intent = _classify_url(
            {"content_type": "guide", "entity_type": "counselling",
             "local_pack": "yes", "domain_role": "other"},
            minimal_mapping["rules"],
        )
        assert intent == "informational"

    def test_local_when_service_counselling_local(self, minimal_mapping):
        intent = _classify_url(
            {"content_type": "service", "entity_type": "counselling",
             "local_pack": "yes", "domain_role": "other"},
            minimal_mapping["rules"],
        )
        assert intent == "local"

    def test_falls_through_to_catch_all(self, minimal_mapping):
        intent = _classify_url(
            {"content_type": "news", "entity_type": "media",
             "local_pack": "no", "domain_role": "other"},
            minimal_mapping["rules"],
        )
        assert intent == "uncategorised"


# ─── Real intent_mapping.yml — spot-check critical edge cases ────────────────


class TestRealMappingEdgeCases:
    """Exercises the actual rules in intent_mapping.yml for the cases the
    rationale block calls out explicitly."""

    def test_service_on_directory_is_commercial_investigation(self, real_mapping):
        # Edge case 1: Psychology Today therapist profile
        intent = _classify_url(
            {"content_type": "service", "entity_type": "directory",
             "local_pack": "yes", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "commercial_investigation"

    def test_guide_on_counselling_with_local_pack_is_informational(self, real_mapping):
        # Edge case 2: provider-hosted guide + local pack on SERP
        intent = _classify_url(
            {"content_type": "guide", "entity_type": "counselling",
             "local_pack": "yes", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "informational"

    def test_nonprofit_service_is_transactional(self, real_mapping):
        # Edge case 4: free vs paid is irrelevant
        intent = _classify_url(
            {"content_type": "service", "entity_type": "nonprofit",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "transactional"

    def test_other_content_is_uncategorised(self, real_mapping):
        # Edge case 5: Reddit/YouTube classified as 'other'
        intent = _classify_url(
            {"content_type": "other", "entity_type": "media",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "uncategorised"

    def test_unknown_content_is_uncategorised(self, real_mapping):
        intent = _classify_url(
            {"content_type": "unknown", "entity_type": "N/A",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "uncategorised"

    def test_client_url_always_navigational(self, real_mapping):
        # Edge case from clarification 3: client URL on informational keyword
        intent = _classify_url(
            {"content_type": "guide", "entity_type": "counselling",
             "local_pack": "no", "domain_role": "client"},
            real_mapping["rules"],
        )
        assert intent == "navigational"

    def test_counselling_service_no_local_pack_is_transactional(self, real_mapping):
        intent = _classify_url(
            {"content_type": "service", "entity_type": "counselling",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "transactional"

    def test_counselling_service_with_local_pack_is_local(self, real_mapping):
        intent = _classify_url(
            {"content_type": "service", "entity_type": "counselling",
             "local_pack": "yes", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "local"

    def test_directory_listicle_is_commercial_investigation(self, real_mapping):
        intent = _classify_url(
            {"content_type": "directory", "entity_type": "media",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "commercial_investigation"

    def test_news_is_informational(self, real_mapping):
        intent = _classify_url(
            {"content_type": "news", "entity_type": "media",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "informational"

    def test_pdf_is_informational(self, real_mapping):
        intent = _classify_url(
            {"content_type": "pdf", "entity_type": "government",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "informational"

    def test_government_service_is_transactional(self, real_mapping):
        intent = _classify_url(
            {"content_type": "service", "entity_type": "government",
             "local_pack": "no", "domain_role": "other"},
            real_mapping["rules"],
        )
        assert intent == "transactional"


# ─── compute_serp_intent integration ─────────────────────────────────────────


class TestComputeSerpIntent:
    def test_empty_serp(self, real_mapping):
        result = compute_serp_intent(
            organic_rows=[], has_local_pack=False, mapping=real_mapping
        )
        assert result["primary_intent"] == "uncategorised"
        assert result["is_mixed"] is False
        assert result["confidence"] == "low"
        assert result["evidence"]["total_url_count"] == 0
        assert result["evidence"]["classified_url_count"] == 0

    def test_all_uncategorised(self, real_mapping):
        rows = [
            _row(1, "https://example.com/1", "other", "media"),
            _row(2, "https://example.com/2", "unknown", "N/A"),
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        assert result["primary_intent"] == "uncategorised"
        assert result["confidence"] == "low"
        assert result["evidence"]["uncategorised_count"] == 2

    def test_pure_informational_high_confidence(self, real_mapping):
        rows = [
            _row(i, f"https://e{i}.com/g", "guide", "media")
            for i in range(1, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        assert result["primary_intent"] == "informational"
        assert result["is_mixed"] is False
        assert result["confidence"] == "high"
        assert result["intent_distribution"]["informational"] == 1.0

    def test_pure_local(self, real_mapping):
        rows = [
            _row(i, f"https://clinic{i}.ca/", "service", "counselling")
            for i in range(1, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=True, mapping=real_mapping
        )
        assert result["primary_intent"] == "local"
        assert result["is_mixed"] is False

    def test_mixed_intent_5_5(self, real_mapping):
        # 5 informational guides + 5 transactional services, no local pack
        rows = [
            _row(i, f"https://g{i}.com/", "guide", "media")
            for i in range(1, 6)
        ] + [
            _row(i, f"https://s{i}.ca/", "service", "counselling")
            for i in range(6, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        # 50/50: top share = 0.5, second share = 0.5 → fails primary (≥0.6)
        # and fallback (≥0.4 with second ≤0.2) → mixed
        assert result["is_mixed"] is True
        assert result["primary_intent"] == "mixed"
        assert set(result["mixed_components"]) == {"informational", "transactional"}

    def test_fallback_threshold_40_with_low_runner_up(self, real_mapping):
        # 4 informational + 1 transactional + 5 uncategorised → among classified
        # (5 total): info 0.8, transactional 0.2 — primary should be informational.
        rows = [
            _row(i, f"https://g{i}.com/", "guide", "media")
            for i in range(1, 5)  # 4 guides
        ] + [
            _row(5, "https://s.ca/", "service", "counselling"),  # 1 service
        ] + [
            _row(i, f"https://other{i}.com/", "other", "media")
            for i in range(6, 11)  # 5 uncategorised
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        assert result["primary_intent"] == "informational"
        assert result["is_mixed"] is False
        # 5 classified out of 10 total → confidence_share = 0.5 → medium
        assert result["confidence"] == "medium"

    def test_confidence_low_when_few_classified(self, real_mapping):
        # 2 classified out of 10 → 0.2 share → low
        rows = [
            _row(1, "https://g.com/", "guide", "media"),
            _row(2, "https://s.ca/", "service", "counselling"),
        ] + [
            _row(i, f"https://x{i}.com/", "other", "media")
            for i in range(3, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        assert result["confidence"] == "low"

    def test_client_urls_dilute_but_dont_dominate(self, real_mapping):
        # 1 client URL + 9 informational guides → primary still informational
        rows = [
            _row(1, "https://livingsystems.ca/about", "service", "counselling"),
        ] + [
            _row(i, f"https://g{i}.com/", "guide", "media")
            for i in range(2, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows,
            has_local_pack=False,
            client_domain="livingsystems.ca",
            mapping=real_mapping,
        )
        assert result["primary_intent"] == "informational"
        # 9/10 informational = 0.9 share, classified=10/10 → high confidence
        assert result["confidence"] == "high"

    def test_branded_serp_dominated_by_client(self, real_mapping):
        # 7 client URLs + 3 directory results → primary navigational
        rows = [
            _row(i, f"https://livingsystems.ca/p{i}", "guide", "counselling")
            for i in range(1, 8)
        ] + [
            _row(i, f"https://psychologytoday.com/p{i}", "directory", "directory")
            for i in range(8, 11)
        ]
        result = compute_serp_intent(
            organic_rows=rows,
            has_local_pack=False,
            client_domain="livingsystems.ca",
            mapping=real_mapping,
        )
        assert result["primary_intent"] == "navigational"
        assert result["is_mixed"] is False

    def test_known_competitor_tagged_navigational(self, real_mapping):
        rows = [
            _row(1, "https://rival.ca/services", "service", "counselling"),
            _row(2, "https://elsewhere.ca/", "service", "counselling"),
        ]
        result = compute_serp_intent(
            organic_rows=rows,
            has_local_pack=False,
            client_domain="livingsystems.ca",
            known_brand_domains=["rival.ca"],
            mapping=real_mapping,
        )
        # rival.ca → navigational; elsewhere.ca → transactional (no local pack)
        counts = result["evidence"]["intent_counts"]
        assert counts["navigational"] == 1
        assert counts["transactional"] == 1

    def test_evidence_counts_sum_to_total(self, real_mapping):
        rows = [
            _row(1, "https://a.com/", "guide", "media"),
            _row(2, "https://b.com/", "service", "counselling"),
            _row(3, "https://c.com/", "other", "media"),
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        ev = result["evidence"]
        assert ev["total_url_count"] == 3
        assert ev["classified_url_count"] + ev["uncategorised_count"] == 3
        assert sum(ev["intent_counts"].values()) == 3

    def test_distribution_excludes_uncategorised(self, real_mapping):
        rows = [
            _row(1, "https://a.com/", "guide", "media"),
            _row(2, "https://b.com/", "other", "media"),
        ]
        result = compute_serp_intent(
            organic_rows=rows, has_local_pack=False, mapping=real_mapping
        )
        assert "uncategorised" not in result["intent_distribution"]
        # 1 informational of 1 classified URL → 1.0
        assert result["intent_distribution"]["informational"] == 1.0


# ─── Threshold customisation ─────────────────────────────────────────────────


class TestThresholdOverrides:
    def test_custom_thresholds_change_primary_decision(self, real_mapping):
        # Same rows, two threshold configs → different mixed verdicts
        rows = [
            _row(i, f"https://g{i}.com/", "guide", "media") for i in range(1, 6)
        ] + [
            _row(i, f"https://s{i}.ca/", "service", "counselling") for i in range(6, 11)
        ]
        # Stricter: requires ≥0.7 share → 5/10 fails → mixed
        strict = compute_serp_intent(
            rows, has_local_pack=False, mapping=real_mapping,
            thresholds={"primary_share": 0.7, "fallback_share": 0.7,
                        "fallback_runner_up_max": 0.0},
        )
        assert strict["is_mixed"] is True
        assert strict["primary_intent"] == "mixed"
        assert "mixed_components" in strict
        # Loose: ≥0.5 share counts → 5/10 passes
        loose = compute_serp_intent(
            rows, has_local_pack=False, mapping=real_mapping,
            thresholds={"primary_share": 0.5, "fallback_share": 0.5,
                        "fallback_runner_up_max": 0.5},
        )
        assert loose["is_mixed"] is False
