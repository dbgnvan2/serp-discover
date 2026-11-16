"""Tests for Gap 3 — competitor handoff schema generation and validation."""
import json
import os
import pytest
import jsonschema

from handoff_writer import (build_competitor_handoff, _HANDOFF_SCHEMA,
                            SCHEMA_VERSION_BASE, SCHEMA_VERSION_WITH_MOZ)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "handoff_schema.json")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_organic(keyword, rank, url, entity="practice", content="service_page"):
    return {
        "Root_Keyword": keyword,
        "Rank": rank,
        "Link": url,
        "Title": f"Title for {url}",
        "Entity_Type": entity,
        "Content_Type": content,
        "Snippet": "A snippet.",
    }


SAMPLE_ORGANIC = [
    _make_organic("couples therapy", 1, "https://aaa.com/page"),
    _make_organic("couples therapy", 2, "https://bbb.com/page"),
    _make_organic("couples therapy", 3, "https://ccc.com/page"),
    _make_organic("couples therapy", 4, "https://livingsystems.ca/page"),  # client
    _make_organic("marriage counselling", 1, "https://bbb.com/other"),
    _make_organic("marriage counselling", 2, "https://ddd.com/page"),
    _make_organic("marriage counselling", 3, "https://omit-me.com/page"),  # omit list
]


def _build(n=10, omit=None, organic=None):
    return build_competitor_handoff(
        organic or SAMPLE_ORGANIC,
        run_id="run_abc123",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="livingsystems.ca",
        client_brand_names=["Living Systems"],
        n=n,
        omit_from_audit=omit or [],
    )


# ---------------------------------------------------------------------------
# Schema file existence
# ---------------------------------------------------------------------------

def test_schema_file_exists():
    assert os.path.exists(SCHEMA_PATH), "handoff_schema.json must exist at repo root"


def test_schema_is_valid_json():
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#"


def test_schema_loaded_into_module():
    assert _HANDOFF_SCHEMA is not None, "_HANDOFF_SCHEMA should be loaded at import time"


# ---------------------------------------------------------------------------
# Valid handoff passes schema
# ---------------------------------------------------------------------------

def test_valid_handoff_passes_schema():
    handoff = _build()
    assert handoff is not None
    jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)


def test_top_level_keys_present():
    handoff = _build()
    for key in ("schema_version", "source_run_id", "source_run_timestamp",
                "client_domain", "client_brand_names", "targets", "exclusions"):
        assert key in handoff, f"Missing top-level key: {key}"


def test_schema_version_is_string():
    handoff = _build()
    assert isinstance(handoff["schema_version"], str)
    assert handoff["schema_version"] == SCHEMA_VERSION_BASE


def test_schema_version_is_2_x_because_rank_is_absolute():
    """Tool 2 keys `absolute_rank_versions` off this, so the major version
    must move with the rank semantics (review chunk D1 / finding D-C-01)."""
    assert SCHEMA_VERSION_BASE.startswith("2.")
    assert SCHEMA_VERSION_WITH_MOZ.startswith("2.")
    assert SCHEMA_VERSION_WITH_MOZ != SCHEMA_VERSION_BASE


def test_targets_are_list():
    handoff = _build()
    assert isinstance(handoff["targets"], list)


def test_each_target_has_required_fields():
    handoff = _build()
    required = {"url", "domain", "rank", "entity_type", "content_type",
                "title", "source_keyword", "primary_keyword_for_url"}
    for target in handoff["targets"]:
        missing = required - target.keys()
        assert not missing, f"Target missing fields: {missing}"


def test_rank_is_integer():
    handoff = _build()
    for target in handoff["targets"]:
        assert isinstance(target["rank"], int), f"rank must be int, got {type(target['rank'])}"


# ---------------------------------------------------------------------------
# Client URL exclusion
# ---------------------------------------------------------------------------

def test_client_urls_excluded_from_targets():
    handoff = _build()
    urls = [t["url"] for t in handoff["targets"]]
    assert not any("livingsystems.ca" in u for u in urls), \
        "Client domain URLs must not appear in targets"


def test_client_exclusion_counted():
    handoff = _build()
    assert handoff["exclusions"]["client_urls_excluded"] >= 1


# ---------------------------------------------------------------------------
# omit_from_audit exclusion
# ---------------------------------------------------------------------------

def test_omit_list_domain_excluded_from_targets():
    handoff = _build(omit=["omit-me.com"])
    urls = [t["url"] for t in handoff["targets"]]
    assert not any("omit-me.com" in u for u in urls)


def test_omit_list_exclusion_counted():
    handoff = _build(omit=["omit-me.com"])
    assert handoff["exclusions"]["omit_list_excluded"] >= 1


def test_omit_list_used_recorded():
    handoff = _build(omit=["omit-me.com"])
    assert "omit-me.com" in handoff["exclusions"]["omit_list_used"]


def test_empty_omit_list_counts_zero():
    handoff = _build(omit=[])
    assert handoff["exclusions"]["omit_list_excluded"] == 0
    assert handoff["exclusions"]["omit_list_used"] == []


# ---------------------------------------------------------------------------
# Top-N cap per keyword
# ---------------------------------------------------------------------------

def test_n_cap_respected():
    organic = [_make_organic("kw", i + 1, f"https://site{i}.com/p") for i in range(20)]
    handoff = build_competitor_handoff(
        organic,
        run_id="r1",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="client.com",
        client_brand_names=[],
        n=5,
    )
    # Only one keyword → max 5 targets
    assert len(handoff["targets"]) <= 5


def test_n_ten_default():
    organic = [_make_organic("kw", i + 1, f"https://site{i}.com/p") for i in range(15)]
    handoff = build_competitor_handoff(
        organic,
        run_id="r1",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="client.com",
        client_brand_names=[],
    )
    assert len(handoff["targets"]) <= 10


# ---------------------------------------------------------------------------
# primary_keyword_for_url logic
# ---------------------------------------------------------------------------

def test_primary_keyword_is_best_rank():
    organic = [
        _make_organic("kw_a", 3, "https://shared.com/p"),
        _make_organic("kw_b", 1, "https://shared.com/p"),  # best rank for this URL
    ]
    handoff = build_competitor_handoff(
        organic,
        run_id="r1",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="client.com",
        client_brand_names=[],
        n=10,
    )
    shared_targets = [t for t in handoff["targets"] if "shared.com" in t["url"]]
    # URL appears once (deduplicated)
    assert len(shared_targets) == 1
    assert shared_targets[0]["primary_keyword_for_url"] == "kw_b"


# ---------------------------------------------------------------------------
# Schema rejects invalid data
# ---------------------------------------------------------------------------

def test_missing_required_field_rejected():
    bad = {
        "schema_version": "1.0",
        # missing source_run_id, etc.
        "targets": [],
        "exclusions": {"client_urls_excluded": 0, "omit_list_excluded": 0, "omit_list_used": []},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=_HANDOFF_SCHEMA)


def test_extra_top_level_field_rejected():
    handoff = _build()
    handoff["unexpected_field"] = "oops"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)


def test_rank_as_string_rejected():
    handoff = _build()
    if handoff["targets"]:
        handoff["targets"][0]["rank"] = "1"  # must be int
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)


def test_extra_target_field_rejected():
    handoff = _build()
    if handoff["targets"]:
        handoff["targets"][0]["extra"] = "nope"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)


# ---------------------------------------------------------------------------
# Empty organic list
# ---------------------------------------------------------------------------

def test_no_organic_returns_none():
    """Fix 3: empty/None organic_results → no handoff file (return None)."""
    assert build_competitor_handoff(
        [],
        run_id="r_empty",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="livingsystems.ca",
        client_brand_names=[],
    ) is None
    assert build_competitor_handoff(
        None,
        run_id="r_none",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="livingsystems.ca",
        client_brand_names=[],
    ) is None


def test_all_client_urls_produces_empty_targets():
    """Fix 3: all organic URLs are client → empty targets list, file IS written."""
    all_client_organic = [
        _make_organic("couples therapy", i, f"https://livingsystems.ca/page-{i}")
        for i in range(1, 6)
    ]
    handoff = build_competitor_handoff(
        all_client_organic,
        run_id="r_client",
        run_timestamp="2026-04-30T12:00:00Z",
        client_domain="livingsystems.ca",
        client_brand_names=["Living Systems"],
    )
    assert handoff is not None
    assert handoff["targets"] == []
    assert handoff["exclusions"]["client_urls_excluded"] > 0
    jsonschema.validate(instance=handoff, schema=_HANDOFF_SCHEMA)


def test_invalid_handoff_fails_validation():
    """Fix 3: a handoff with a missing required field fails schema validation."""
    bad_handoff = {
        "schema_version": "1.0",
        # missing source_run_id and other required fields
        "targets": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_handoff, schema=_HANDOFF_SCHEMA)
