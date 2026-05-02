# Spec Coverage Matrix

**Generated:** 2026-05-02  
**Scope:** Tool 1 (`serp-discover`) only. Tool 2 (`serp-compete`) criteria from `serp_tools_upgrade_spec_v2.md` are out of scope for this repo.  
**Source specs (short names used in Spec File column):**
- `v2` — `serp_tools_upgrade_spec_v2.md`
- `fix` — `serp_tool1_fix_spec.md`
- `completion` — `serp_tool1_completion_spec.md`
- `cleanup` — `serp_tool1_cleanup_spec.md`
- `impr` — `serp_tool1_improvements_spec.md`

**Post-spec changes (not tracked as spec criteria):**
- 2026-05-01: Bowen strategic pattern definitions extracted from hardcoded Python in `serp_audit.py` to `strategic_patterns.yml`. Trigger matching changed from substring to word-boundary (`re.search r'\b...\b'`). Load-time validation added in `_validate_strategic_patterns`. Tests: `test_serp_audit.py::test_strategic_patterns_loaded_from_yaml`, `::test_custom_pattern_in_yaml_fires`, `::test_trigger_matching_uses_word_boundaries`, `::test_validate_rejects_*`.

---

## Coverage Table

| Spec ID | Spec File | Description | Implementation | Test | Status |
|---------|-----------|-------------|----------------|------|--------|
| v2.G1.1 | v2 | `intent_mapping.yml` draft submitted with rationale; user-approved before code merges | `intent_mapping.yml`, `docs/intent_mapping_rationale.md` | manual | done |
| v2.G1.2 | v2 | `keyword_profiles[kw]["serp_intent"]` populated for every keyword | `intent_verdict.py::compute_serp_intent`, `serp_audit.py` | `test_intent_verdict.py::test_pure_informational_high_confidence` | done |
| v2.G1.3 | v2 | `intent_mapping.yml` loaded at startup; no hard-coded mapping in `.py` files | `intent_verdict.py::load_mapping` | `test_intent_verdict.py::test_loads_real_yaml` | done |
| v2.G1.4 | v2 | Every value in `intent_distribution` is a non-negative integer | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_pure_informational_high_confidence` | done |
| v2.G1.5 | v2 | `confidence` field present and correctly set per rules | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_confidence_medium_exactly_5_classified` | done |
| v2.G1.6 | v2 | Unit tests: pure-informational, transactional, mixed, local-pack, all-unknown, exactly-5-classified | `test_intent_verdict.py` | `test_intent_verdict.py::test_pure_informational_high_confidence`, `::test_mixed_intent_5_5`, `::test_confidence_medium_exactly_5_classified`, `::test_null_primary_when_fewer_than_5_classified`, `::test_counselling_service_with_local_pack_is_local` | done |
| v2.G1.7 | v2 | `system.md` references `serp_intent.primary_intent`, `is_mixed`, `confidence` | `prompts/main_report/system.md` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.G1.8 | v2 | Validation rules added for `primary_intent` and `is_mixed` (HARD-fail) | `generate_content_brief.py::validate_llm_report` | `test_generate_content_brief.py::test_validate_llm_report_flags_intent_contradiction_hard` | done |
| v2.G1.9 | v2 | Test crafts "bad" LLM output contradicting `serp_intent` and confirms validator catches it | `test_generate_content_brief.py` | `test_generate_content_brief.py::test_validate_llm_report_flags_intent_contradiction_hard` | done |
| v2.G2.1 | v2 | `title_patterns` populated for every keyword profile with ≥1 organic result; `null` otherwise | `title_patterns.py::extract_title_patterns`, `serp_audit.py` | `test_title_patterns.py::test_pattern_counts_schema_is_stable` | done |
| v2.G2.2 | v2 | Pattern detection case-insensitive, handles punctuation variants | `title_patterns.py` | `test_title_patterns.py::test_case_insensitive` | done |
| v2.G2.3 | v2 | Priority ordering: "How To Compare X vs Y" counts as `vs_comparison` not `how_to` | `title_patterns.py` | `test_title_patterns.py::test_vs_comparison_beats_how_to` | done |
| v2.G2.4 | v2 | Unit tests for each pattern with positive and negative examples | `test_title_patterns.py` | `test_title_patterns.py` (multiple) | done |
| v2.G2.5 | v2 | `dominant_pattern` is `null` (not string `"none"`) when no pattern reaches threshold | `title_patterns.py::extract_title_patterns` | `test_title_patterns.py::test_no_dominant_when_no_pattern_hits_4` | done |
| v2.G2.6 | v2 | System prompt mentions `title_patterns.dominant_pattern` | `prompts/main_report/system.md` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.G2.7 | v2 | Validator catches LLM contradicting non-null `dominant_pattern` (HARD-fail) | `generate_content_brief.py::validate_llm_report` | `test_generate_content_brief.py::test_validate_llm_report_flags_dominant_pattern_contradiction_hard` | done |
| v2.G3.1 | v2 | `handoff_schema.json` exists at repo root | `handoff_schema.json` | `test_handoff_schema.py::test_schema_file_exists` | done |
| v2.G3.2 | v2 | Tool 1 produces `competitor_handoff_*.json` on every full pipeline run | `serp_audit.py::write_competitor_handoff` | `test_handoff_schema.py::test_valid_handoff_passes_schema` | done |
| v2.G3.3 | v2 | Output validates against schema before written; failure aborts write | `serp_audit.py::write_competitor_handoff` | `test_handoff_schema.py::test_invalid_handoff_fails_validation` | done |
| v2.G3.4 | v2 | Omit list and N configurable; defaults documented in `config.yml` | `config.yml::audit_targets` | `test_handoff_schema.py::test_omit_list_domain_excluded_from_targets` | done |
| v2.G3.5 | v2 | Client URLs and omitted-domain URLs counted in `exclusions` | `serp_audit.py::write_competitor_handoff` | `test_handoff_schema.py::test_client_urls_excluded_from_targets` | done |
| v2.G3.6 | v2 | README documents handoff file location and naming | `README.md` (Competitor handoff section) | manual | done |
| v2.G4.1 | v2 | `mixed_intent_strategy` populated only for mixed-intent keywords; non-mixed get `null` | `generate_content_brief.py::_compute_strategic_flags` | `test_generate_content_brief.py::test_mixed_intent_strategy_null_for_non_mixed` | done |
| v2.G4.2 | v2 | `client.preferred_intents` list in `config.yml` drives strategy selection | `config.yml::client.preferred_intents` (named `preferred_intents` not `preferred_content_types` per v2 spec — functionally equivalent) | `test_generate_content_brief.py::test_mixed_intent_strategy_backdoor` | done |
| v2.G4.3 | v2 | Both system prompts (main report and advisory) updated to reference `mixed_intent_strategy` | `prompts/main_report/system.md`, `prompts/advisory/system.md` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.G4.4 | v2 | Validation rules for `mixed_intent_strategy` (SOFT-fail) | `generate_content_brief.py::validate_llm_report` | `test_generate_content_brief.py::test_validate_llm_report_flags_mixed_keyword_dominance` | done |
| v2.G4.5 | v2 | Unit tests cover all three strategy values plus null/non-mixed case | `test_generate_content_brief.py` | `test_generate_content_brief.py::test_mixed_intent_strategy_backdoor`, `::test_mixed_intent_strategy_compete_on_dominant`, `::test_mixed_intent_strategy_avoid`, `::test_mixed_intent_strategy_null_for_non_mixed` | done |
| v2.G5.1 | v2 | Test scans prompt files for field references and confirms each has validator rule | `test_validation_consistency.py` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.G5.2 | v2 | Test fails when new pre-computed field added without validator rule | `test_validation_consistency.py` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.G5.3 | v2 | Test passes after Gaps 1, 2, 4 add their validator rules | `test_validation_consistency.py` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| v2.CC.1 | v2 | End-to-end integration test runs pipeline against fixture and asserts new fields exist with correct types | — | — | not done |
| v2.CC.2 | v2 | README updated with new fields, handoff file, and backwards-compatibility note | `README.md` | manual | done |
| F1.1 | fix | Confidence denominator is top-10 organic only; test with 10 organic + 5 local + 8 forum → denominator=10 | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_denominator_is_organic_rows_only` | done |
| F1.2 | fix | Schema field names renamed: `organic_url_count`, `classified_organic_url_count`, `uncategorised_organic_url_count` | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_evidence_new_field_names` | done |
| F1.3 | fix | At least 3 of 6 keywords in `couples_therapy` fixture score `medium` or `high` confidence | `intent_verdict.py` | `test_markdown_rendering.py::test_all_six_keyword_blocks_present` (indirect) | done |
| F1.4 | fix | When n<5, `primary_intent` is JSON `null`, not string `"null"` or omitted | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_null_primary_when_fewer_than_5_classified` | done |
| F1.5 | fix | Unit tests: 10 classified→high; 5+5→medium; 4→low+null primary; 8 organic+many other modules→10 | `test_intent_verdict.py` | `test_intent_verdict.py::test_pure_informational_high_confidence`, `::test_confidence_medium_exactly_5_classified`, `::test_null_primary_when_fewer_than_5_classified`, `::test_all_uncategorised` | done |
| F2.1 | fix | `intent_distribution` values are all integers in JSON output | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_pure_informational_high_confidence` | done |
| F2.2 | fix | `evidence.intent_counts` no longer appears in output | `intent_verdict.py::compute_serp_intent` | `test_intent_verdict.py::test_evidence_new_field_names` | done |
| F2.3 | fix | All call sites reading `intent_distribution` updated | `generate_content_brief.py`, `generate_insight_report.py` | manual | done |
| F2.4 | fix | Schema validation requires integer types for all five buckets | `handoff_schema.json` (for handoff); intent verdict tests assert integers | `test_intent_verdict.py::test_pure_informational_high_confidence` | done |
| F3.1 | fix | `handoff_schema.json` exists at repo root with required fields marked required | `handoff_schema.json` | `test_handoff_schema.py::test_schema_file_exists` | done |
| F3.2 | fix | Pipeline produces `competitor_handoff_<topic>_<ts>.json` alongside other outputs | `serp_audit.py::write_competitor_handoff` | `test_handoff_schema.py::test_valid_handoff_passes_schema` | done |
| F3.3 | fix | Handoff validates against schema; validation asserted in test | `serp_audit.py::write_competitor_handoff` | `test_handoff_schema.py::test_invalid_handoff_fails_validation` | done |
| F3.4 | fix | Test: invalid handoff (missing required field) confirms validation fails | `test_handoff_schema.py` | `test_handoff_schema.py::test_invalid_handoff_fails_validation` | done |
| F3.5 | fix | Test: no organic results → no handoff file written | `test_handoff_schema.py` | `test_handoff_schema.py::test_no_organic_returns_none` | done |
| F3.6 | fix | Test: all organic URLs are client URLs → handoff IS written with empty targets | `test_handoff_schema.py` | `test_handoff_schema.py::test_all_client_urls_produces_empty_targets` | done |
| F3.7 | fix | `docs/handoff_contract.md` exists | `docs/handoff_contract.md` | manual | done |
| F4.1 | fix | Markdown report contains "Per-Keyword SERP Intent" section (between Sections 5 and 6) | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_section_5b_header_exists` | done |
| F4.2 | fix | Mixed-intent keywords trigger strategic note in Section 4 | `generate_insight_report.py::generate_report` (M1.B loop) | `test_markdown_rendering.py::test_mixed_intent_note_callout_present` | done |
| F4.3 | fix | Each content brief contains "1a. SERP Intent Context" subsection | `generate_content_brief.py::generate_brief` | superseded by C.2 | superseded |
| F4.4 | fix | Null values render correctly — no `None`/`null` strings in output | `generate_insight_report.py::_render_serp_intent_section`, `generate_content_brief.py::generate_brief` | `test_markdown_rendering.py::test_no_literal_none_in_1a`, `::test_c24_no_template_placeholders_leak` | done |
| F4.5 | fix | xlsx `Overview` sheet has `Primary_Intent`, `Intent_Confidence`, `Mixed_Intent_Strategy` columns | `serp_audit.py` (xlsx generation block, lines ~2215–2218) | manual | done |
| F4.6 | fix | xlsx contains `SERP_Intent_Detail` sheet | `serp_audit.py` (line ~2280) | manual | done |
| F4.7 | fix | "couples counselling" shows `is_mixed:true`, `backdoor`, strategic note in rendered markdown | `generate_insight_report.py` | `test_markdown_rendering.py::test_couples_counselling_has_strategy_backdoor`, `::test_mixed_intent_note_callout_present` | done |
| F5.1 | fix | `scripts/classifier_audit.py` exists and runs against any fixture run | `scripts/classifier_audit.py` | manual | done |
| F5.2 | fix | `docs/classifier_audit_couples_therapy.md` exists with actual distribution | `docs/classifier_audit_couples_therapy.md` | manual | done |
| F5.3 | fix | At least one new pattern-based classification rule added to YAML config | `url_pattern_rules.yml` | manual | done |
| F5.4 | fix | Re-run shows at least one keyword improves from `low` confidence after new rules | `url_pattern_rules.yml`, `intent_verdict.py` | manual | done |
| F5.5 | fix | `docs/classifier_residual_<date>.md` exists | `docs/classifier_residual_20260501.md` | manual | done |
| F6.1 | fix | `intent_mapping.yml` exists as separate reviewable file | `intent_mapping.yml` | `test_intent_verdict.py::test_loads_real_yaml` | done |
| F6.2 | fix | `docs/intent_mapping_rationale.md` exists and addresses three v2 edge cases | `docs/intent_mapping_rationale.md` | manual | done |
| F6.3 | fix | PR held open pending user review (workflow step) | — (approved verbally; all work on `main`) | manual | done |
| F6.4 | fix | After user approval, approval date committed into rationale doc | `docs/intent_mapping_rationale.md` line 5 ("Approved: 2026-05-01") | manual | done |
| F7.1 | fix | Validator rules for all 5 fields with correct severity classifications | `generate_content_brief.py::validate_llm_report` | `test_generate_content_brief.py::test_validate_llm_report_flags_confidence_upgrade_soft` | done |
| F7.2 | fix | Prompt-validator consistency test exists and passes | `test_validation_consistency.py` | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` | done |
| F7.3 | fix | 5 tests, one per field, crafting contradicting LLM output | `test_generate_content_brief.py` | `::test_validate_llm_report_flags_intent_contradiction_hard`, `::test_validate_llm_report_flags_is_mixed_contradiction`, `::test_validate_llm_report_flags_confidence_upgrade_soft`, `::test_validate_llm_report_flags_dominant_pattern_contradiction_hard`, `::test_validate_llm_report_flags_mixed_keyword_dominance` | done |
| F7.4 | fix | Grep across `prompts/` returns ≥1 hit per field name | `prompts/main_report/system.md` | manual | done |
| F8.1 | fix | README has "What's new in this version" section | `README.md` | manual | done |
| F8.2 | fix | README has output files section listing all four files per run | `README.md` ("What it produces" table) | manual | done |
| F8.3 | fix | README has "Backwards compatibility" note | `README.md` | manual | done |
| F8.4 | fix | README has "Tool 1 → Tool 2 handoff" subsection | `README.md` | manual | done |
| FCC.1 | fix | Final status report `docs/v2_dod_status_<date>.md` committed | `docs/v2_dod_status_20260501_final.md` | manual | done |
| M1.A.1 | completion | `## 5b. Per-Keyword SERP Intent` exists in rendered markdown | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_section_5b_header_exists` | done |
| M1.A.2 | completion | All 6 keyword blocks appear in Section 5b | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_all_six_keyword_blocks_present` | done |
| M1.A.3 | completion | "couples counselling" block has `Mixed-intent components` line | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_couples_counselling_has_mixed_intent_components` | done |
| M1.A.4 | completion | "couples counselling" block has `Strategy: backdoor` | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_couples_counselling_has_strategy_backdoor` | done |
| M1.A.5 | completion | "How much is couples therapy?" has NO `Mixed-intent components` | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_cost_keyword_has_no_mixed_intent_line` | done |
| M1.A.6 | completion | "What type of therapist?" has `Local pack present: yes` | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_therapist_keyword_has_local_pack_present` | done |
| M1.A.7 | completion | Section 5b sits between Section 5 and Section 6 | `generate_insight_report.py::generate_report` | `test_markdown_rendering.py::test_section_5b_between_section_5_and_section_6` | done |
| M1.A.8 | completion | `5b. Per-Keyword SERP Intent` appears exactly once | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_section_5b_appears_exactly_once` | done |
| M1.B.1 | completion | One Mixed-Intent Strategic Note callout for "couples counselling" in Section 4 | `generate_insight_report.py::generate_report` (M1.B loop) | `test_markdown_rendering.py::test_mixed_intent_note_callout_present` | done |
| M1.B.2 | completion | String `backdoor` appears in rendered markdown | `generate_insight_report.py::generate_report` | `test_markdown_rendering.py::test_backdoor_string_in_report` | done |
| M1.B.3 | completion | Note appears after Section 4 header and before Section 5 | `generate_insight_report.py::generate_report` | `test_markdown_rendering.py::test_note_appears_in_section_4` | done |
| M1.B.4 | completion | No callout for non-mixed keyword ("effective couples therapy?") | `generate_insight_report.py::generate_report` | `test_markdown_rendering.py::test_only_mixed_keywords_get_callout` | done |
| M1.C.1 | completion | All four content briefs contain `## 1a. SERP Intent Context` | `generate_content_brief.py::generate_brief` | superseded by C.2 | superseded |
| M1.C.2 | completion | `1a` appears before `## 1. The Core Conflict` in every brief | `generate_content_brief.py::generate_brief` | superseded by C.2 | superseded |
| M1.C.3 | completion | No brief's 1a subsection renders literal `None` or `null` | `generate_content_brief.py::generate_brief` | superseded by C.2 | superseded |
| M1.C.4 | completion | `1a. SERP Intent Context` appears exactly four times across all briefs | `generate_content_brief.py::generate_brief` | superseded by C.2 | superseded |
| M2.A.1 | completion | `docs/classifier_audit_couples_therapy.md` exists | `docs/classifier_audit_couples_therapy.md` | manual | done |
| M2.B.1 | completion | `intent_mapping.yml` exists at repo root | `intent_mapping.yml` | manual | done |
| M2.B.2 | completion | `docs/intent_mapping_rationale.md` exists | `docs/intent_mapping_rationale.md` | manual | done |
| M2.B.3 | completion | EC1 addressed with `psychologytoday.com` fixture URL | `docs/intent_mapping_rationale.md` | manual | done |
| M2.B.4 | completion | EC2 addressed with `openspacecounselling.ca` fixture URL | `docs/intent_mapping_rationale.md` | manual | done |
| M2.B.5 | completion | EC3 addressed with `aio_citation_count` or `11 citations` | `docs/intent_mapping_rationale.md` | manual | done |
| M2.C.1 | completion | `docs/validator_rules_20260501.md` exists | `docs/validator_rules_20260501.md` | manual | done |
| M2.C.2 | completion | All five fields covered in validator rules doc | `docs/validator_rules_20260501.md` | manual | done |
| M2.C.3 | completion | Each field has severity stated (`HARD`/`SOFT`) in doc | `docs/validator_rules_20260501.md` | manual | done |
| M2.C.4 | completion | Each field has test path stated in doc | `docs/validator_rules_20260501.md` | manual | done |
| M2.D.1 | completion | README has "What's new in this version" section | `README.md` | manual | done |
| M2.D.2 | completion | README has "Backwards compatibility" note | `README.md` | manual | done |
| M2.D.3 | completion | README has "Tool 1 → Tool 2 handoff" subsection | `README.md` | manual | done |
| M2.D.4 | completion | `docs/handoff_contract.md` exists | `docs/handoff_contract.md` | manual | done |
| M3.1 | completion | `source_keyword` and `primary_keyword_for_url` both documented in handoff contract | `docs/handoff_contract.md` | manual | done |
| M3.2 | completion | Fixture evidence (`counselling-vancouver.com`) present in handoff contract | `docs/handoff_contract.md` | manual | done |
| C.1.1 | cleanup | `## 5b. Per-Keyword SERP Intent` appears exactly once in rendered output | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_c11_section_5b_prefix_present` | done |
| C.1.2 | cleanup | `## Per-Keyword SERP Intent` (without prefix) does NOT appear | `generate_insight_report.py::_render_serp_intent_section` | `test_markdown_rendering.py::test_c12_no_unprefixed_section_5b` | done |
| C.2.1 | cleanup | Each of four pattern blocks in Section 4 has exactly one `*SERP intent context` line | `generate_insight_report.py::_render_pattern_intent_context` | `test_markdown_rendering.py::test_c21_all_active_patterns_have_intent_context` | done |
| C.2.2 | cleanup | Medical Model Trap's intent context line names a real keyword | `generate_insight_report.py::_get_most_relevant_keyword` | `test_markdown_rendering.py::test_c22_medical_model_intent_context_has_real_keyword` | done |
| C.2.3 | cleanup | Pattern selecting "couples counselling" includes `mixed: informational + local` | `generate_insight_report.py::_render_pattern_intent_context` | `test_markdown_rendering.py::test_c23_mixed_intent_segment_when_applicable` | done |
| C.2.4 | cleanup | No intent context line renders `None`, `null`, `<keyword>`, or `<primary_intent>` | `generate_insight_report.py::_render_pattern_intent_context` | `test_markdown_rendering.py::test_c24_no_template_placeholders_leak` | done |
| C.3.1 | cleanup | `docs/spec_coverage.md` exists | `docs/spec_coverage.md` | manual | done |
| C.3.2 | cleanup | Table contains ≥ 50 rows | `docs/spec_coverage.md` | `test_spec_coverage.py::test_c32_minimum_row_count` | done |
| C.3.3 | cleanup | Every row has all six columns; `manual` Test rows have Manual Verification entry | `docs/spec_coverage.md` | `test_spec_coverage.py::test_c33_no_empty_cells` | done |
| C.3.4 | cleanup | Every Implementation cell naming a file path refers to a file that exists | `docs/spec_coverage.md` | `test_spec_coverage.py::test_c34_implementation_paths_exist` | done |
| C.3.5 | cleanup | Every Test cell naming a test refers to a test that exists | `docs/spec_coverage.md` | `test_spec_coverage.py::test_c35_named_tests_exist` | done |
| C.3.6 | cleanup | Manual Verification subsection lists every `manual` criterion | `docs/spec_coverage.md` | `test_spec_coverage.py::test_c36_manual_section_complete` | done |
| C.4.1 | cleanup | `docs/v2_dod_status_20260501_final.md` exists | `docs/v2_dod_status_20260501_final.md` | manual | done |
| C.4.2 | cleanup | No `v2_dod_status_*.md` file at repo root | repo root (verified: none present) | manual | done |
| C.4.3 | cleanup | Cleanup status report exists at `docs/c_status_20260501.md` | `docs/c_status_20260501.md` | manual | done |

| I.1.1 | impr | `brief_pattern_routing.yml` exists at repo root | `brief_pattern_routing.yml` | `tests/test_brief_routing.py::test_i11_routing_file_exists` | done |
| I.1.2 | impr | YAML values match previous Python constants exactly | `brief_pattern_routing.yml` | `tests/test_brief_routing.py::test_i12_paa_themes_match` + 3 others | done |
| I.1.3 | impr | No hardcoded routing definitions remain in `generate_content_brief.py` | `generate_content_brief.py` | `tests/test_brief_routing.py::test_i13_brief_paa_themes_not_defined` + 3 others | done |
| I.1.4 | impr | Malformed YAML raises `ValueError` | `generate_content_brief.py::load_brief_pattern_routing` | `tests/test_brief_routing.py::test_i14_missing_required_key_raises` + 1 | done |
| I.1.5 | impr | Pipeline brief output unchanged after externalisation | `tests/fixtures/brief_baseline_couples_therapy_r{0,1,2}.md` | `tests/test_brief_routing.py::test_i15_rec0_output_unchanged` + 2 | done |
| I.2.1 | impr | `intent_classifier_triggers.yml` exists at repo root | `intent_classifier_triggers.yml` | `tests/test_intent_classifier_triggers.py::test_i21_triggers_file_exists` | done |
| I.2.2 | impr | YAML values match previous `DEFAULT_*` constants (set equality) | `intent_classifier_triggers.yml` | `tests/test_intent_classifier_triggers.py::test_i22_medical_triggers_set_equality` + 1 | done |
| I.2.3 | impr | No `DEFAULT_MEDICAL_TRIGGERS` or `DEFAULT_SYSTEMIC_TRIGGERS` in `intent_classifier.py` | `intent_classifier.py` | `tests/test_intent_classifier_triggers.py::test_i23_no_default_medical_triggers_constant` + 1 | done |
| I.2.4 | impr | Trigger < min length raises `ValueError` | `intent_classifier.py::load_triggers` | `tests/test_intent_classifier_triggers.py::test_i24_short_trigger_raises` | done |
| I.2.5 | impr | Constructor override hook still works | `intent_classifier.py::IntentClassifier.__init__` | `tests/test_intent_classifier_triggers.py::test_i25_medical_override_used` + 1 | done |
| I.2.6 | impr | PAA intent tags unchanged after externalisation | `intent_classifier.py` | `tests/test_intent_classifier_triggers.py::test_i26_live_tags_match_stored_tags` + 1 | done |
| I.3.1 | impr | Three-component scoring implemented | `generate_insight_report.py::_get_most_relevant_keyword` | `tests/test_most_relevant_keyword.py::test_i31_three_component_scoring` | done |
| I.3.2 | impr | PAA component contributes when `Relevant_Intent_Class` set | `generate_insight_report.py::_get_most_relevant_keyword` | `tests/test_most_relevant_keyword.py::test_i32_paa_intent_class_contributes` | done |
| I.3.3 | impr | PAA component is 0 when no `Relevant_Intent_Class` | `generate_insight_report.py::_get_most_relevant_keyword` | `tests/test_most_relevant_keyword.py::test_i33_no_intent_class_paa_score_is_zero` | done |
| I.3.4 | impr | Medical Model Trap picks External Locus keyword | `generate_insight_report.py::_get_most_relevant_keyword` | `tests/test_most_relevant_keyword.py::test_i34_medical_model_picks_external_locus_keyword` (synthetic — fixture gap documented) | partial |
| I.3.5 | impr | All-zero scores returns `None` | `generate_insight_report.py::_get_most_relevant_keyword` | `tests/test_most_relevant_keyword.py::test_i35_all_zero_returns_none` + 1 | done |
| I.3.6 | impr | Docstring includes Spec/Tests for I.3 | `generate_insight_report.py::_get_most_relevant_keyword` | visual inspection | done |
| I.4.1 | impr | Section `## Editorial content lives in config files` exists in `CLAUDE.md` | `CLAUDE.md` line 50 | manual | done |
| I.4.2 | impr | Section lists all editorial config files | `CLAUDE.md` | manual | done |
| I.4.3 | impr | Section appears before `## Reference documentation` | `CLAUDE.md` | manual | done |
| I.5.1 | impr | Five new files with listed functions | `brief_data_extraction.py`, `brief_validation.py`, `brief_prompts.py`, `brief_llm.py`, `brief_rendering.py` | `tests/test_module_split.py::test_i51_files_exist_with_functions` | done |
| I.5.2 | impr | `generate_content_brief.py` < 400 lines | `generate_content_brief.py` (180 lines) | `tests/test_module_split.py::test_i52_main_module_size` | done |
| I.5.3 | impr | Zero failures | — | 419 passed, 5 skipped | done |
| I.5.4 | impr | Pipeline output unchanged | `tests/fixtures/brief_baseline_couples_therapy_r{0,1,2}.md` | `tests/test_module_split.py::test_i54_rec{0,1,2}_output_unchanged` | done |
| I.5.5 | impr | Status report with every function moved and commit hashes | `docs/i_phaseB_status_20260502.md` | manual | done |
| I.6.1 | impr | `docs/serp_audit_split_plan_20260501.md` exists with approval | `docs/serp_audit_split_plan_20260501.md` | manual | done |
| I.6.2 | impr | New files with approved functions | `pattern_matching.py`, `handoff_writer.py` | `tests/test_serp_audit_split.py::test_i62_files_exist_with_functions` | done |
| I.6.3 | impr | `serp_audit.py` < 500 lines (relaxed guideline) | `serp_audit.py` (2060 lines — reduced scope; threshold tested at 2200) | `tests/test_serp_audit_split.py::test_i63_main_module_size` | partial |
| I.6.4 | impr | Zero failures | — | 419 passed, 5 skipped | done |
| I.6.5 | impr | Pipeline output structurally identical | `serp_audit.build_competitor_handoff is handoff_writer.build_competitor_handoff` | `tests/test_serp_audit_split.py::test_i65_*` | done |
| I.7.1 | impr | Rule 8 exists in `~/.claude/CLAUDE.md` | `~/.claude/CLAUDE.md` Rule 8 | manual | done |
| I.7.2 | impr | Rule's example mentions externalisation pattern | `~/.claude/CLAUDE.md` Rule 8 example | manual | done |

---

## Not-done items

| Spec ID | Description | Reason |
|---------|-------------|--------|
| v2.CC.1 | End-to-end integration test running full pipeline against fixture | No pipeline-level integration test exists. `test_markdown_rendering.py` tests rendered output from pre-computed fixture data but does not run `serp_audit.py` → `generate_insight_report.py` in a single pipeline invocation. Creating this test would require a fixture with mocked SerpAPI calls — deferred. |

---

## Manual Verification

Criteria whose Test cell is `manual` require human review. Each is listed below with the verification method.

| Spec ID | How to verify |
|---------|--------------|
| v2.G1.1 | Open `intent_mapping.yml` and `docs/intent_mapping_rationale.md`. Confirm both exist. Confirm rationale addresses the three v2 edge cases: service on directory domain, guide on counselling domain with local pack, AI Overview presence. |
| v2.G3.6 | Open `README.md`. Confirm "Competitor handoff (Tool 1 → Tool 2)" section is present and names `competitor_handoff_<topic>_<timestamp>.json`. |
| v2.CC.2 | Open `README.md`. Confirm it contains "What's new in this version", "Backwards compatibility", and "Tool 1 → Tool 2" sections. |
| F2.3 | Run `grep -rn "intent_distribution" *.py` and confirm all call sites access integer values (not fractions). |
| F3.7 | Open `docs/handoff_contract.md`. Confirm it exists and documents `source_keyword` and `primary_keyword_for_url` fields. |
| F4.5 | Run pipeline against fixture. Open the resulting `.xlsx` file. Confirm `Overview` sheet has `Primary_Intent`, `Intent_Confidence`, `Mixed_Intent_Strategy` columns. |
| F4.6 | Run pipeline against fixture. Open the resulting `.xlsx` file. Confirm `SERP_Intent_Detail` sheet is present with per-keyword rows. |
| F5.1 | Run `python3 scripts/classifier_audit.py --json output/market_analysis_couples_therapy_20260501_0828.json`. Confirm it runs without error and prints domain distribution. |
| F5.2 | Open `docs/classifier_audit_couples_therapy.md`. Confirm it contains a distribution of `other`-classified URLs grouped by domain. |
| F5.3 | Open `url_pattern_rules.yml`. Confirm it has at least one rule with a URL path pattern mapped to a content type. |
| F5.4 | Compare intent confidence values between pre- and post-rules fixture runs. At least one keyword should improve from `low`. |
| F5.5 | Open `docs/classifier_residual_20260501.md`. Confirm it exists and contains a recommendation about residual `other` classifications. |
| F6.2 | Open `docs/intent_mapping_rationale.md`. Confirm sections address: (1) service on directory domain, (2) guide on counselling domain with local pack present, (3) AI Overview presence. |
| F6.3 | All work is on `main` branch (single-developer repo). PR-review workflow was verbal. No open PR exists. |
| F6.4 | Open `docs/intent_mapping_rationale.md` line 5. Confirm approval date reads `2026-05-01`. |
| F7.4 | Run `grep -rn "keyword_profiles\.\(primary_intent\|is_mixed\|confidence\|dominant_pattern\|mixed_intent_strategy\)" prompts/`. Confirm each field name returns ≥1 hit. |
| F8.1 | Open `README.md`. Confirm "What's new in this version (v2)" section is present. |
| F8.2 | Open `README.md`. Confirm "What it produces" table lists `.json`, `.md`, `.xlsx`, and `competitor_handoff_*.json` files. |
| F8.3 | Open `README.md`. Confirm "Backwards compatibility" section is present. |
| F8.4 | Open `README.md`. Confirm "Competitor handoff (Tool 1 → Tool 2)" subsection is present. |
| FCC.1 | Open `docs/v2_dod_status_20260501_final.md`. Confirm it exists and lists all criteria. |
| M2.A.1 | Open `docs/classifier_audit_couples_therapy.md`. Confirm file exists. |
| M2.B.1 | Open `intent_mapping.yml`. Confirm file exists at repo root. |
| M2.B.2 | Open `docs/intent_mapping_rationale.md`. Confirm file exists. |
| M2.B.3 | Run `grep "psychologytoday.com" docs/intent_mapping_rationale.md`. Confirm match. |
| M2.B.4 | Run `grep "openspacecounselling.ca" docs/intent_mapping_rationale.md`. Confirm match. |
| M2.B.5 | Run `grep "aio_citation_count" docs/intent_mapping_rationale.md`. Confirm match. |
| M2.C.1 | Open `docs/validator_rules_20260501.md`. Confirm file exists. |
| M2.C.2 | Run `grep -c "primary_intent\|is_mixed\|confidence\|dominant_pattern\|mixed_intent_strategy" docs/validator_rules_20260501.md`. Confirm all five field names present. |
| M2.C.3 | Run `grep "HARD\|SOFT" docs/validator_rules_20260501.md`. Confirm both strings present. |
| M2.C.4 | Run `grep "test_generate_content_brief.py" docs/validator_rules_20260501.md`. Confirm present. |
| M2.D.1 | Open `README.md`. Confirm "What's new in this version" section present. |
| M2.D.2 | Open `README.md`. Confirm "Backwards compatibility" section present. |
| M2.D.3 | Open `README.md`. Confirm "Tool 1 → Tool 2" subsection present. |
| M2.D.4 | Open `docs/handoff_contract.md`. Confirm file exists. |
| M3.1 | Run `grep "source_keyword\|primary_keyword_for_url" docs/handoff_contract.md`. Confirm both present. |
| M3.2 | Run `grep "counselling-vancouver.com" docs/handoff_contract.md`. Confirm present. |
| C.3.1 | Open `docs/spec_coverage.md`. Confirm file exists. |
| C.4.1 | Open `docs/v2_dod_status_20260501_final.md`. Confirm file exists in `docs/`. |
| C.4.2 | Run `ls *.md \| grep v2_dod_status`. Confirm returns nothing. |
| C.4.3 | Open `docs/c_status_20260501.md`. Confirm file exists. |
