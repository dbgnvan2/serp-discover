# Validator Rules — v2 Pre-Computed Fields

**Date:** 2026-05-01  
**File:** `brief_validation.py` — `validate_llm_report()` and helpers  
**Spec:** `serp_tool1_fix_spec.md` Fix 7, `serp_tool1_completion_spec.md` M2.C

This document lists every validator rule in effect for the five pre-computed fields added in v2 of the SERP intelligence tool. Each rule has a severity, a description, and a pointer to the test that asserts it catches a contradicting LLM output.

---

## Fields and rules

### 1. `serp_intent.primary_intent`

**Severity: HARD-FAIL** (no retry; run aborts)

**Rule:** If the computed `primary_intent` is a known intent value (not `null`, not `"uncategorised"`) and `confidence != "low"` and `is_mixed == False`, and the LLM report asserts a *different* intent for that keyword (using phrases like "primarily transactional," "informational-intent SERP," "local-intent SERP"), a validation issue is raised.

The issue string contains `"but keyword_profiles shows serp_intent.primary_intent="`, which causes `has_hard_validation_failures()` to return `True`.

Low-confidence verdicts (`confidence == "low"`) are deliberately not enforced — the LLM is permitted interpretive latitude when the classifier had insufficient data.

**Detection location:** `brief_validation.py::validate_llm_report()` — `INTENT_CLAIM_PHRASES` loop

**Test:** `test_validate_llm_report_flags_intent_contradiction_hard` (`test_generate_content_brief.py:474`)

---

### 2. `serp_intent.is_mixed`

**Severity: HARD-FAIL** (no retry; run aborts)

**Rule:** When `confidence != "low"`:
- If `is_mixed == True` and the report describes the SERP as "single-intent," "uniform intent," or "cleanly informational/transactional/navigational," a validation issue is raised.
- If `is_mixed == False` and the report uses phrases like "mixed-intent SERP" or "mixed intent," a validation issue is raised.

Both issue strings contain `"but keyword_profiles shows serp_intent.is_mixed="`, triggering hard-fail.

**Detection location:** `brief_validation.py::validate_llm_report()` — is_mixed block

**Test:** `test_validate_llm_report_flags_is_mixed_contradiction` (`test_generate_content_brief.py:487`)

---

### 3. `serp_intent.confidence`

**Severity: SOFT-FAIL** (routes to `notes`, appended to report; does not abort)

**Rule:** The LLM may downplay confidence (say "low" when computed is "medium") but may not upgrade it. If the computed confidence is `"low"` and the report contains phrases like "confidence: high," "high-confidence," or "highly confident," an issue is raised. If computed confidence is `"medium"` and the report claims "high confidence," an issue is raised.

The issue string contains `"keyword_profiles.serp_intent.confidence="`, which `partition_validation_issues()` routes to `notes` (not `blocking`), and `has_hard_validation_failures()` does NOT trigger.

**Detection location:** `brief_validation.py::validate_llm_report()` — confidence upgrade block (HIGH/MEDIUM_CONFIDENCE_PHRASES check)

**Test:** `test_validate_llm_report_flags_confidence_upgrade_soft` (`test_generate_content_brief.py`)

---

### 4. `title_patterns.dominant_pattern`

**Severity: HARD-FAIL** (no retry; run aborts)

**Rule:** Two sub-cases:
- **Non-null dominant pattern:** If the computed `dominant_pattern` is (e.g.) `"how_to"` and the report asserts a *different* pattern dominates (e.g., "listicles dominate"), an issue is raised.
- **Null dominant pattern:** If `dominant_pattern` is `null` (no pattern reached the dominance threshold) and the report nonetheless asserts that any pattern dominates, an issue is raised.

Both issue strings contain `"contradicts keyword_profiles.title_patterns"`, which `has_hard_validation_failures()` catches via the string pattern `"contradicts keyword_profiles.title_patterns"`. The issue routes to `blocking` in `partition_validation_issues()` (not to `notes`).

**Upgrade from prior spec:** This field was SOFT in earlier code. Fix 7 of `serp_tool1_fix_spec.md` promoted it to HARD.

**Detection location:** `brief_validation.py::validate_llm_report()` — `PATTERN_CLAIM_PHRASES` loop

**Tests:**
- `test_validate_llm_report_flags_dominant_pattern_contradiction_hard` (non-null case, `test_generate_content_brief.py:523`)
- `test_validate_llm_report_flags_invented_dominant_pattern` (null case, `test_generate_content_brief.py:693`)

---

### 5. `mixed_intent_strategy`

**Severity: SOFT-FAIL** (routes to `notes`; does not abort) — with one HARD sub-case

**Rule (soft):** If the report contradicts the computed strategy for a mixed-intent keyword (e.g., computed is `"backdoor"` but the report recommends competing directly on the dominant intent), an issue string containing `"contradicts keyword_profiles.mixed_intent_strategy"` is raised. This routes to `notes` via `partition_validation_issues()`.

**Rule (hard sub-case):** If the keyword is NOT mixed-intent (`is_mixed == False`) but the report uses backdoor strategy language ("backdoor strategy," "compete on the dominant intent"), this is a HARD-FAIL — invoking mixed-intent framing on a single-intent keyword. The issue string contains `"but keyword_profiles shows serp_intent.is_mixed=False"`, caught by `has_hard_validation_failures()`.

**Detection location:** `brief_validation.py::validate_llm_report()` — mixed_intent_strategy block

**Test:** `test_validate_llm_report_flags_mixed_keyword_dominance` (`test_generate_content_brief.py:276`) — asserts the non-mixed keyword hard-fail sub-case.

---

## Summary table

| Field | Severity | Has validator | Has test | Test path |
|-------|----------|--------------|---------|-----------|
| `primary_intent` | HARD | ✅ | ✅ | `test_generate_content_brief.py:474` |
| `is_mixed` | HARD | ✅ | ✅ | `test_generate_content_brief.py:487` |
| `confidence` | SOFT | ✅ | ✅ | `test_generate_content_brief.py` (confidence upgrade test) |
| `dominant_pattern` | HARD | ✅ | ✅ | `test_generate_content_brief.py:523` |
| `mixed_intent_strategy` | SOFT (HARD sub-case) | ✅ | ✅ | `test_generate_content_brief.py:276` |

All five fields have validator rules and passing tests. No fields are missing coverage.

---

## Validation flow

```
validate_llm_report(report_text, extracted_data)
    → returns list of issue strings

has_hard_validation_failures(issues)
    → True if any issue contains hard-fail marker strings
    → Causes the run to abort (no LLM output saved)

partition_validation_issues(issues)
    → (blocking, notes)
    → notes: entity_label, mixed_intent_strategy, confidence issues
    → blocking: everything else (primary_intent, is_mixed, dominant_pattern)

If blocking: hard abort
If notes only: append as interpretation caveats to saved report
If retry: correction prompt sent once; if still failing → .validation.md written
```

---

## Prompt coverage

A grep of `prompts/main_report/system.md` confirms all five fields are referenced:

| Field | Prompt reference |
|-------|-----------------|
| `primary_intent` | lines 44, 256, 295 |
| `is_mixed` | lines 48, 257 |
| `confidence` | lines 49–50, 255, 260 |
| `dominant_pattern` | lines 71, 264, 297 |
| `mixed_intent_strategy` | lines 58–68 |
