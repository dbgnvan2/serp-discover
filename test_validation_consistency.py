"""Gap 5 — Validation consistency check.

Scans prompts/main_report/system.md and user_template.md for
`keyword_profiles.<field>` references and verifies that each field name
appears somewhere in `validate_llm_report`'s source.

Goal: catch the case where a developer adds a new field to keyword_profiles
and mentions it in the prompt but forgets to add a validation rule.

All currently referenced fields pass in the current codebase.
"""
import inspect
import os
import re

import pytest

import generate_content_brief

SYSTEM_MD = os.path.join(os.path.dirname(__file__), "prompts", "main_report", "system.md")
USER_TEMPLATE = os.path.join(os.path.dirname(__file__), "prompts", "main_report", "user_template.md")

# Fields that appear in prompts as data references only — the LLM reads them
# to ground its analysis, but they don't produce claims that can be
# mechanically rule-checked by regex.  Add new entries here only when the
# field is legitimately not checkable; add a brief reason in the comment.
KNOWN_UNVALIDATED = frozenset({
    "top5_organic",     # used as evidence anchor; no enforceable claim shape
    "schema_signals",   # Section 5b evidence anchor (counts/types of schema
                        # markup on ranking pages); prose claims about markup
                        # gaps have no mechanically checkable shape
    "aio_divergence",   # Section 4 evidence anchor (rank-vs-citation domain
                        # lists); the binding boolean surface is
                        # strategic_flags.geo_alerts, which is pre-computed
    "extractability",   # Section 5b evidence anchor (question-heading and
                        # intro-length measurements per page); descriptive
                        # counts with no enforceable claim shape
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KP_FIELD_RE = re.compile(r"keyword_profiles\.(\w+)")


def _prompt_referenced_fields():
    """Return all distinct field names from keyword_profiles.<field> in prompts."""
    fields: set[str] = set()
    for path in (SYSTEM_MD, USER_TEMPLATE):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in _KP_FIELD_RE.finditer(text):
            fields.add(m.group(1))
    return fields


def _validator_source():
    return inspect.getsource(generate_content_brief.validate_llm_report)


# ---------------------------------------------------------------------------
# Meta-tests: the infrastructure itself is sane
# ---------------------------------------------------------------------------

def test_prompt_files_exist():
    assert os.path.exists(SYSTEM_MD), f"system.md not found at {SYSTEM_MD}"
    assert os.path.exists(USER_TEMPLATE), f"user_template.md not found at {USER_TEMPLATE}"


def test_prompt_files_reference_at_least_one_field():
    fields = _prompt_referenced_fields()
    assert len(fields) >= 1, "Expected at least one keyword_profiles.<field> reference in prompts"


def test_validate_llm_report_is_importable():
    assert callable(generate_content_brief.validate_llm_report)


def test_validator_source_is_nonempty():
    src = _validator_source()
    assert len(src) > 100, "validate_llm_report source unexpectedly short"


# ---------------------------------------------------------------------------
# Consistency check
# ---------------------------------------------------------------------------

def _missing_fields():
    """Return fields referenced in prompts that have no mention in the validator."""
    src = _validator_source()
    missing = []
    for field in sorted(_prompt_referenced_fields()):
        if field in KNOWN_UNVALIDATED:
            continue
        if field not in src:
            missing.append(field)
    return missing


def test_all_prompt_fields_covered_by_validator():
    """Every keyword_profiles.<field> in the prompts must appear in validate_llm_report
    (unless explicitly listed in KNOWN_UNVALIDATED)."""
    missing = _missing_fields()
    assert missing == [], (
        f"Fields referenced in prompts but absent from validate_llm_report: {missing}\n"
        "Add a validation rule or add the field to KNOWN_UNVALIDATED with a reason."
    )


# ---------------------------------------------------------------------------
# Per-field tests (one per currently-known field for clearer failure messages)
# ---------------------------------------------------------------------------

def test_entity_label_covered():
    assert "entity_label" in _validator_source(), \
        "validate_llm_report has no mention of 'entity_label' — Rule 9 / 12 may be unenforceable"


def test_serp_intent_covered():
    assert "serp_intent" in _validator_source(), \
        "validate_llm_report has no mention of 'serp_intent' — Rule 12A may be unenforceable"


def test_top5_organic_is_in_known_unvalidated():
    """top5_organic is a known data-reference field — confirm it stays in the allowlist."""
    assert "top5_organic" in KNOWN_UNVALIDATED


# ---------------------------------------------------------------------------
# KNOWN_UNVALIDATED integrity: every entry must actually appear in the prompts
# ---------------------------------------------------------------------------

def test_known_unvalidated_entries_appear_in_prompts():
    """Guard against stale KNOWN_UNVALIDATED entries — every allowlisted field
    must still be referenced in the prompts (otherwise it's dead weight)."""
    prompt_fields = _prompt_referenced_fields()
    stale = [f for f in KNOWN_UNVALIDATED if f not in prompt_fields]
    assert stale == [], (
        f"KNOWN_UNVALIDATED contains fields no longer referenced in prompts: {stale}\n"
        "Remove them from the allowlist."
    )
