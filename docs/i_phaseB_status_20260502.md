# Phase B Status Report — I.5 + I.6

**Spec:** `serp_tool1_improvements_spec.md`
**Date:** 2026-05-02
**Suite:** 419 passed, 5 skipped, 0 errors

---

## I.5 — Split `generate_content_brief.py`

| Criterion | Status | Evidence |
|---|---|---|
| I.5.1 Five new files with listed functions | **done** | `tests/test_module_split.py::test_i51_files_exist_with_functions` |
| I.5.2 `generate_content_brief.py` < 400 lines | **done** | 180 lines. `tests/test_module_split.py::test_i52_main_module_size` |
| I.5.3 Zero failures | **done** | 419 passed, 5 skipped |
| I.5.4 Pipeline output unchanged | **done** | `tests/test_module_split.py::test_i54_rec{0,1,2}_output_unchanged` |
| I.5.5 Status report with function list and commit hashes | **done** | This document |

### Functions moved per module

**`brief_data_extraction.py`** (commit `557c969`):
`extract_analysis_data_from_json`, `_extract_domain`, `_safe_int`, `_top_sources_for_keyword`, `_normalize_text`, `_classify_entity_distribution`, `_entity_label_reason_text`, `_client_match_patterns`, `_contains_phrase`, `_extract_excerpt`, `_parse_trigger_words`, `_count_terms_in_texts`, `_compute_strategic_flags`, `_classify_paa_intent`, `_build_feasibility_summary`

Constants moved: `DEFAULT_CLIENT_CONTEXT`
Added: `load_yaml_config`, `load_client_context_from_config` (needed by `brief_rendering.py`; entry point re-imports these)

**`brief_validation.py`** (commit `557c969`):
`validate_llm_report`, `validate_extraction`, `validate_advisory_briefing`, `_mixed_keyword_dominance_profiles`, `_label_requires_mixed`, `_label_requires_plurality`, `has_hard_validation_failures`, `partition_validation_issues`

**`brief_prompts.py`** (commit `557c969`):
`_extract_code_block_after_heading`, `_read_prompt_file`, `load_prompt_blocks`, `load_single_prompt`, `build_user_prompt`, `build_main_report_payload`, `build_correction_message`, `append_interpretation_notes`

Constants moved: `MAIN_REPORT_PROMPT_DEFAULT`, `ADVISORY_PROMPT_DEFAULT`, `CORRECTION_PROMPT_DEFAULT`

**`brief_llm.py`** (commit `557c969`):
`run_llm_report`

Constants/imports moved: `anthropic` import guard, `ANTHROPIC_AVAILABLE`, `MAIN_REPORT_DEFAULT_MODEL`, `ADVISORY_DEFAULT_MODEL`, `SUPPORTED_REPORT_MODELS`

**`brief_rendering.py`** (commit `557c969`):
`generate_brief`, `generate_local_report`, `list_recommendations`, `generate_serp_intent_section`, `score_paa_for_brief`, `get_relevant_paa`, `get_relevant_competitors`, `_dedupe_question_records`, `_infer_intent_text`, `_score_keyword_opportunity`, `write_validation_artifact`, `load_brief_pattern_routing`

### Deviations noted

1. `load_yaml_config` and `load_client_context_from_config` were listed as entry-point functions in the plan. However, `list_recommendations` (in `brief_rendering.py`) calls them, and importing from the entry point creates a circular import. Resolution: added both to `brief_data_extraction.py` (alongside `DEFAULT_CLIENT_CONTEXT`). Entry point imports them from there.

2. `progress` was a global helper in the monolith. Resolution: each sub-module that calls `progress` defines its own copy (`def progress(message): print(message, flush=True)`).

3. `load_brief_pattern_routing` and its cache variables remain in BOTH `generate_content_brief.py` (for I.1 test backward compat — `tests/test_brief_routing.py` resets `gcb._BRIEF_ROUTING_CACHE`) and `brief_rendering.py` (authoritative for rendering). Two independent instances, same YAML source.

---

## I.6 — Extract from `serp_audit.py`

**Approved reduced scope** (per `docs/serp_audit_split_plan_20260501.md`): `pattern_matching.py` + `handoff_writer.py` only. 500-line target relaxed — size is a guideline.

| Criterion | Status | Evidence |
|---|---|---|
| I.6.1 `docs/serp_audit_split_plan_20260501.md` exists with approval | **done** | File exists. Approval annotation present: "APPROVED 2026-05-02" |
| I.6.2 New files with approved functions | **done** | `tests/test_serp_audit_split.py::test_i62_files_exist_with_functions` |
| I.6.3 `serp_audit.py` < 500 lines | **partial** | 2060 lines. Target relaxed; reduction from 2332 to 2060 (-272 lines). Test threshold set at 2200. `tests/test_serp_audit_split.py::test_i63_main_module_size` |
| I.6.4 Zero failures | **done** | 419 passed, 5 skipped |
| I.6.5 Pipeline output structurally identical | **done** | `tests/test_serp_audit_split.py::test_i65_*` — passthrough assertions verify same function objects |

### Functions moved per module

**`pattern_matching.py`** (commit `16ffa8d`):
`get_ngrams`, `count_syllables`, `calculate_reading_level`, `calculate_sentiment`, `calculate_subjectivity`, `_dataset_topic_profile`, `_validate_strategic_patterns`, `_load_strategic_patterns`, `analyze_strategic_opportunities`

Constants moved: `_STRATEGIC_PATTERNS_PATH`, `_PATTERN_REQUIRED_FIELDS`, `STOP_WORDS` (default)

Note: `serp_audit.py` syncs `pattern_matching.STOP_WORDS = STOP_WORDS` at startup so config-driven stop words take effect in the extracted module.

**`handoff_writer.py`** (commit `16ffa8d`):
`build_competitor_handoff`

Constants moved: `_HANDOFF_SCHEMA_PATH`, `_HANDOFF_SCHEMA` (loaded at module import)

External caller updated: `test_handoff_schema.py` — changed import from `serp_audit` to `handoff_writer`.

---

## Summary

| Fix | Status |
|---|---|
| I.5 Split generate_content_brief.py | **done** — 180 lines, 5 new modules, 4 tests passing |
| I.6 Extract from serp_audit.py | **done** (reduced scope) — 2 new modules, 7 tests passing |

**Phase B complete.** Next: Phase C (if applicable) or close out the improvements spec.
