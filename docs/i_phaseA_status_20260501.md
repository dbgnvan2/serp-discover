# Phase A Status Report — Improvements Spec (I.1–I.4, I.7)

**Spec:** `serp_tool1_improvements_spec.md`
**Date:** 2026-05-01
**Suite:** 407 passed, 5 skipped, 0 errors

---

## I.1 — Externalise PAA theme routing

| Criterion | Status | Evidence |
|---|---|---|
| I.1.1 `brief_pattern_routing.yml` exists at repo root | **done** | `brief_pattern_routing.yml` |
| I.1.2 YAML values match previous Python constants exactly | **done** | `tests/test_brief_routing.py::test_i12_paa_themes_match`, `::test_i12_paa_categories_match`, `::test_i12_keyword_hints_match`, `::test_i12_intent_slot_descriptions_match` |
| I.1.3 No hardcoded routing definitions remain in `generate_content_brief.py` | **done** | `tests/test_brief_routing.py::test_i13_brief_paa_themes_not_defined`, `::test_i13_brief_paa_categories_not_defined`, `::test_i13_brief_keyword_hints_not_defined`, `::test_i13_brief_intent_slots_not_defined` |
| I.1.4 Malformed YAML raises `ValueError` | **done** | `tests/test_brief_routing.py::test_i14_missing_required_key_raises`, `::test_i14_unknown_pattern_name_raises` |
| I.1.5 Pipeline brief output unchanged after externalisation | **done** | `tests/test_brief_routing.py::test_i15_rec0_output_unchanged`, `::test_i15_rec1_output_unchanged`, `::test_i15_rec2_output_unchanged` (diffed against `tests/fixtures/brief_baseline_couples_therapy_r{0,1,2}.md`) |

**Deviation noted:** `BRIEF_PAA_CATEGORIES` in Python used category tags (`General`, `Commercial`, `Distress`, `Reactivity`) that differ from the intent classifier tag vocabulary (`External Locus`, `Systemic`, `General`). Per F3 confirmation, verbatim relocation applied — values were not changed. A separate editorial pass can revisit whether these category tags are correct.

---

## I.2 — Externalise intent classifier triggers

| Criterion | Status | Evidence |
|---|---|---|
| I.2.1 `intent_classifier_triggers.yml` exists at repo root | **done** | `intent_classifier_triggers.yml` |
| I.2.2 YAML values match previous `DEFAULT_*` constants (set equality) | **done** | `tests/test_intent_classifier_triggers.py::test_i22_medical_triggers_set_equality`, `::test_i22_systemic_triggers_set_equality` |
| I.2.3 No `DEFAULT_MEDICAL_TRIGGERS` or `DEFAULT_SYSTEMIC_TRIGGERS` in `intent_classifier.py` | **done** | `tests/test_intent_classifier_triggers.py::test_i23_no_default_medical_triggers_constant`, `::test_i23_no_default_systemic_triggers_constant` |
| I.2.4 Trigger < min length raises `ValueError` | **done** | `tests/test_intent_classifier_triggers.py::test_i24_short_trigger_raises` |
| I.2.5 Constructor override hook still works | **done** | `tests/test_intent_classifier_triggers.py::test_i25_medical_override_used`, `::test_i25_systemic_override_used` |
| I.2.6 PAA intent tags unchanged after externalisation | **done** | `tests/test_intent_classifier_triggers.py::test_i26_live_tags_match_stored_tags`, `::test_i26_all_questions_classified` |

**Deviation noted:** The spec specified a 4-character minimum trigger length "per the same rule in `strategic_patterns.yml`." The trigger `"fix"` in `DEFAULT_MEDICAL_TRIGGERS` is 3 characters. Applying a 4-char minimum would exclude `"fix"` and break I.2.2's set-equality requirement. A 3-character minimum was applied instead. The I.2.4 test uses a 2-character trigger as the failing case. Rationale: the 4-char rule was established for ngram corpus matching (where short words like "mean" cause false positives); PAA intent classification is a different context where `"fix"` is a legitimate clinical term.

---

## I.3 — Improve most-relevant-keyword selection

| Criterion | Status | Evidence |
|---|---|---|
| I.3.1 Three-component scoring implemented | **done** | `tests/test_most_relevant_keyword.py::test_i31_three_component_scoring` |
| I.3.2 PAA component contributes when `Relevant_Intent_Class` set | **done** | `tests/test_most_relevant_keyword.py::test_i32_paa_intent_class_contributes` |
| I.3.3 PAA component is 0 when no `Relevant_Intent_Class` | **done** | `tests/test_most_relevant_keyword.py::test_i33_no_intent_class_paa_score_is_zero` |
| I.3.4 Medical Model Trap matched to External Locus keyword, not cost keyword | **partial** | `tests/test_most_relevant_keyword.py::test_i34_medical_model_picks_external_locus_keyword` — test passes, but is synthetic unit test, not fixture-based. See note below. |
| I.3.5 All-zero scores returns `None` | **done** | `tests/test_most_relevant_keyword.py::test_i35_all_zero_returns_none`, `::test_i35_empty_organic_returns_none` |
| I.3.6 Docstring includes Spec/Tests for I.3 | **done** | `generate_insight_report.py::_get_most_relevant_keyword` and `::_render_pattern_intent_context` — both docstrings updated |

**I.3.4 fixture gap:** The `output/market_analysis_couples_therapy_20260501_1517.json` fixture contains 16 PAA questions, all tagged `General` (no `External Locus` tags). This is because the couples therapy keyword set produces cost, success-rate, and process questions — none of which use medical-model vocabulary that triggers External Locus classification. Consequently, the PAA component is 0 for all keywords in that run, and the new scoring cannot produce a different result than the old single-component scoring for this specific fixture.

I.3.4 is therefore verified via a synthetic unit test with injected data that directly proves the PAA component overrides trigger-text advantage. The test passes and the formula is correct. A future run with a keyword set that generates External Locus PAA questions (e.g., `estrangement` or `anxiety disorder`) would produce the fixture-based evidence the spec anticipated.

**Before/after comparison on 1517 fixture:**

| Pattern | Before I.3 | After I.3 | Change |
|---|---|---|---|
| The Medical Model Trap | "How much is couples therapy in Vancouver?" | "How much is couples therapy in Vancouver?" | No change (PAA score = 0 for all kws) |
| The Fusion Trap | "effective couples therapy?" | "effective couples therapy?" | No change |
| The Resource Trap | "How much is couples therapy in Vancouver?" | "How much is couples therapy in Vancouver?" | No change |

No regression. The 1517 fixture is not an External Locus run, so the improvement is latent pending a future run with appropriate keywords.

---

## I.4 — CLAUDE.md editorial content section

| Criterion | Status | Evidence |
|---|---|---|
| I.4.1 Section `## Editorial content lives in config files` exists in project-level `CLAUDE.md` | **done** | `CLAUDE.md` line 50 |
| I.4.2 Section lists all editorial config files including `brief_pattern_routing.yml` and `intent_classifier_triggers.yml` | **done** | Visual inspection: all 9 files listed |
| I.4.3 Section appears before `## Reference documentation` | **done** | `CLAUDE.md` lines 50 vs 81 |

---

## I.7 — Rule 8 in `~/.claude/CLAUDE.md`

| Criterion | Status | Evidence |
|---|---|---|
| I.7.1 Rule exists in `~/.claude/CLAUDE.md` with adjacent-issues text | **done** | `~/.claude/CLAUDE.md` — Rule 8 "Old code is not someone else's problem" appended |
| I.7.2 Rule's example mentions the externalisation pattern | **done** | Example reads: "when externalising a new trigger list to YAML, look for other hardcoded trigger lists in adjacent files" |

**Note:** Appended as Rule 8 per F5 resolution. Rule 7 ("Editorial content lives in config files, not code") was retained unchanged.

---

## Summary

| Fix | Status |
|---|---|
| I.1 Externalise brief routing | **done** — 14 tests passing |
| I.2 Externalise intent classifier triggers | **done** — 10 tests passing |
| I.3 Three-component keyword scoring | **done** (I.3.4 partial — synthetic test, fixture gap documented) |
| I.4 CLAUDE.md editorial section | **done** |
| I.7 Rule 8 in ~/.claude/CLAUDE.md | **done** |

**Phase B readiness:** Phase B (I.5 split `generate_content_brief.py`, I.6 split `serp_audit.py`) is ready to begin on your approval. A separate implementation plan will be produced for each fix before work starts.
