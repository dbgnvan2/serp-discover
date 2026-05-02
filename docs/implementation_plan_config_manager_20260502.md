# Implementation Plan: Configuration Manager GUI

**Spec:** `config_manager_spec.md`  
**Date:** 2026-05-02  
**Phases:** 8 (foundation → validators → tabs → validation → save → testing)  
**Test Framework:** pytest  
**Git:** Commit after each phase + push to GitHub

---

## Acceptance Criteria → Tests Mapping

### Phase 1: Foundation (Validators + ConfigManager Scaffold)

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| Validators extracted from existing code | `tests/test_config_validators.py::test_validators_import` | Import all validators without error | `import config_validators; assert callable(validate_intent_mapping)` |
| `validate_intent_mapping()` works | `tests/test_config_validators.py::test_validate_intent_mapping_valid` | Valid intent mapping passes | Valid data → (True, [], []) |
| `validate_strategic_patterns()` works | `tests/test_config_validators.py::test_validate_strategic_patterns_valid` | Valid patterns pass | Valid data → (True, [], []) |
| `validate_brief_pattern_routing()` works | `tests/test_config_validators.py::test_validate_brief_pattern_routing_valid` | Valid routing passes | Valid data → (True, [], []) |
| `validate_intent_classifier_triggers()` works | `tests/test_config_validators.py::test_validate_intent_classifier_triggers_valid` | Valid triggers pass | Valid data → (True, [], []) |
| `validate_config_yml()` works | `tests/test_config_validators.py::test_validate_config_yml_valid` | Valid config passes | Valid data → (True, [], []) |
| `validate_domain_overrides()` works | `tests/test_config_validators.py::test_validate_domain_overrides_valid` | Valid overrides pass | Valid data → (True, [], []) |
| `validate_classification_rules()` works | `tests/test_config_validators.py::test_validate_classification_rules_valid` | Valid rules pass | Valid data → (True, [], []) |
| `validate_url_pattern_rules()` works | `tests/test_config_validators.py::test_validate_url_pattern_rules_valid` | Valid rules pass | Valid data → (True, [], []) |
| ConfigManagerWindow class exists | `tests/test_config_manager.py::test_config_manager_window_imports` | Import ConfigManagerWindow | `from config_manager import ConfigManagerWindow` |
| BaseConfigTab class exists | `tests/test_config_manager.py::test_base_config_tab_imports` | Import BaseConfigTab | `from config_manager import BaseConfigTab` |
| 8 tab classes exist (stubs) | `tests/test_config_manager.py::test_all_tab_classes_exist` | All tab classes defined | Check IntentMappingTab, StrategicPatternsTab, etc. exist |
| serp-me.py imports ConfigManagerWindow | `tests/test_serp_me_integration.py::test_serp_me_imports_config_manager` | Import in serp-me.py | grep "from config_manager" serp-me.py |
| serp-me.py has open_config_manager method | `tests/test_serp_me_integration.py::test_serp_me_has_open_config_manager` | Method exists | grep "def open_config_manager" serp-me.py |
| Phase 1 compiles, 0 errors | `pytest tests/test_config_validators.py tests/test_config_manager.py -q` | All Phase 1 tests pass | `pytest` output: X passed, 0 failed |

### Phase 2: Simple Tabs (DomainOverrides + ClassificationRules)

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| DomainOverridesTab loads data | `tests/test_config_manager.py::test_domain_overrides_tab_load` | Load from disk | data = tab.load_current_data(); assert isinstance(data, dict) |
| DomainOverridesTab renders UI | `tests/test_config_manager.py::test_domain_overrides_tab_render` | UI renders without error | tab.render_ui() completes |
| DomainOverridesTab edit/add/delete work | `tests/test_config_manager.py::test_domain_overrides_crud` | CRUD operations | add row, get_edited_data(), delete row |
| DomainOverridesTab validates | `tests/test_config_manager.py::test_domain_overrides_tab_validate` | Validation works | Valid data → (True, []) |
| DomainOverridesTab saves to disk | `tests/test_config_manager.py::test_domain_overrides_tab_save` | Save works | save_to_disk(); file exists; reload matches |
| ClassificationRulesTab loads data | `tests/test_config_manager.py::test_classification_rules_tab_load` | Load from disk | data = tab.load_current_data(); assert "entity_types" in data |
| ClassificationRulesTab renders UI | `tests/test_config_manager.py::test_classification_rules_tab_render` | UI renders without error | tab.render_ui() completes |
| ClassificationRulesTab validates | `tests/test_config_manager.py::test_classification_rules_tab_validate` | Validation works | Valid data → (True, []) |
| ClassificationRulesTab saves to disk | `tests/test_config_manager.py::test_classification_rules_tab_save` | Save works | save_to_disk(); file exists; reload matches |
| Phase 2 compiles, all tests pass | `pytest tests/test_config_manager.py -q -k "domain_overrides or classification_rules"` | Domain + Classification tests pass | X passed, 0 failed |

### Phase 3: List-of-Dicts Tabs (IntentMapping + StrategicPatterns)

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| IntentMappingTab loads data in order | `tests/test_config_manager.py::test_intent_mapping_tab_load_order` | Order preserved | Rules in same order after reload |
| IntentMappingTab edit dialog works | `tests/test_config_manager.py::test_intent_mapping_edit_dialog` | Edit nested dict | Edit rule fields, save, verify |
| IntentMappingTab reorder (↑/↓) works | `tests/test_config_manager.py::test_intent_mapping_tab_reorder` | Move rule up/down | Move rule 0→1, verify order |
| IntentMappingTab validates rules | `tests/test_config_manager.py::test_intent_mapping_tab_validate` | Rule schema check | Missing intent → error; valid → pass |
| IntentMappingTab cross-file validation | `tests/test_config_manager.py::test_intent_mapping_cross_file_validate` | Entity type check | Invalid entity_type → error |
| StrategicPatternsTab loads patterns | `tests/test_config_manager.py::test_strategic_patterns_tab_load` | Load from disk | patterns list loaded |
| StrategicPatternsTab edit pattern | `tests/test_config_manager.py::test_strategic_patterns_edit_pattern` | Edit dialog | Change triggers, save, verify |
| StrategicPatternsTab add pattern | `tests/test_config_manager.py::test_strategic_patterns_add_pattern` | Add new pattern | New row added, editable |
| StrategicPatternsTab validates triggers | `tests/test_config_manager.py::test_strategic_patterns_validate_triggers` | Min 4 chars per trigger | Short trigger → error |
| StrategicPatternsTab required fields | `tests/test_config_manager.py::test_strategic_patterns_required_fields` | All required fields check | Missing Status_Quo_Message → error |
| StrategicPatternsTab cross-file validation | `tests/test_config_manager.py::test_strategic_patterns_cross_file_validate` | Pattern in brief_pattern_routing | Orphan pattern → warning |
| Phase 3 compiles, tests pass | `pytest tests/test_config_manager.py -q -k "intent_mapping or strategic_patterns"` | Intent + Patterns tests pass | X passed, 0 failed |

### Phase 4: Complex Tabs (BriefPatternRouting + IntentClassifierTriggers)

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| BriefPatternRoutingTab renders intent slot descriptions | `tests/test_config_manager.py::test_brief_routing_intent_slots` | Descriptions editable | 6 intent slots present |
| BriefPatternRoutingTab edit pattern routing | `tests/test_config_manager.py::test_brief_routing_edit_pattern` | Edit PAA themes/categories | Edit nested lists, save |
| BriefPatternRoutingTab validates pattern name ref | `tests/test_config_manager.py::test_brief_routing_validate_pattern_ref` | Cross-file check | Invalid pattern_name → error |
| BriefPatternRoutingTab cross-file with strategic patterns | `tests/test_config_manager.py::test_brief_routing_strategic_patterns_ref` | All pattern_names in strategic_patterns | Orphan ref → error |
| IntentClassifierTriggersTab loads medical triggers | `tests/test_config_manager.py::test_intent_triggers_load_medical` | Medical triggers loaded | multi_word + single_word present |
| IntentClassifierTriggersTab loads systemic triggers | `tests/test_config_manager.py::test_intent_triggers_load_systemic` | Systemic triggers loaded | Both present |
| IntentClassifierTriggersTab add trigger | `tests/test_config_manager.py::test_intent_triggers_add_trigger` | Add to trigger list | New trigger added |
| IntentClassifierTriggersTab validates min length | `tests/test_config_manager.py::test_intent_triggers_validate_min_length` | Min 3 chars | Trigger "ab" → error |
| IntentClassifierTriggersTab validates non-empty | `tests/test_config_manager.py::test_intent_triggers_validate_non_empty` | At least one trigger | Empty medical_triggers → error |
| Phase 4 compiles, tests pass | `pytest tests/test_config_manager.py -q -k "brief_routing or intent_triggers"` | Routing + Triggers tests pass | X passed, 0 failed |

### Phase 5: Config Settings + URL Patterns

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| ConfigSettingsTab renders serpapi section | `tests/test_config_manager.py::test_config_settings_serpapi` | All serpapi fields editable | engine, gl, num, etc. present |
| ConfigSettingsTab renders files section | `tests/test_config_manager.py::test_config_settings_files` | File paths editable | Browse buttons work |
| ConfigSettingsTab type-safe widgets | `tests/test_config_manager.py::test_config_settings_widget_types` | Widget auto-detection | int → Spinbox, bool → Checkbutton |
| ConfigSettingsTab validates numeric ranges | `tests/test_config_manager.py::test_config_settings_validate_ranges` | Threshold 0-1 check | threshold > 1 → error |
| ConfigSettingsTab validates file paths | `tests/test_config_manager.py::test_config_settings_validate_paths` | File existence check (warn) | Missing file → warning |
| UrlPatternRulesTab loads rules in order | `tests/test_config_manager.py::test_url_pattern_rules_load_order` | Order preserved | First-match-wins order |
| UrlPatternRulesTab edit pattern | `tests/test_config_manager.py::test_url_pattern_rules_edit` | Edit regex + content_type | Change pattern, save |
| UrlPatternRulesTab validates regex | `tests/test_config_manager.py::test_url_pattern_rules_validate_regex` | Regex compiles | Invalid regex → error |
| UrlPatternRulesTab validates content_type | `tests/test_config_manager.py::test_url_pattern_rules_validate_content_type` | Enum check | Invalid type → error |
| UrlPatternRulesTab reorder | `tests/test_config_manager.py::test_url_pattern_rules_reorder` | Move rule up/down | Order changes preserved |
| Phase 5 compiles, tests pass | `pytest tests/test_config_manager.py -q -k "config_settings or url_pattern"` | Config + URL Pattern tests pass | X passed, 0 failed |

### Phase 6: Cross-File Validation + Help System

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| Cross-file constraint: intent_mapping entity_types | `tests/test_config_validators.py::test_cross_file_intent_mapping_entity_types` | All entity_types valid | Invalid type → error |
| Cross-file constraint: strategic_patterns refs | `tests/test_config_validators.py::test_cross_file_strategic_patterns_refs` | All patterns in brief_pattern_routing exist | Orphan ref → error |
| Cross-file constraint: domain_overrides entity_types | `tests/test_config_validators.py::test_cross_file_domain_overrides_entity_types` | All types in classification_rules | Invalid type → error |
| Help registry: HELP_BY_FILE populated | `tests/test_config_manager.py::test_help_by_file_populated` | All files have help text | len(HELP_BY_FILE) == 8 |
| Help registry: HELP_BY_FIELD populated | `tests/test_config_manager.py::test_help_by_field_populated` | ≥10 fields have help | len(HELP_BY_FIELD) >= 10 |
| Help buttons render | `tests/test_config_manager.py::test_help_buttons_render` | (?) buttons appear | Visual inspection (manual) |
| Validation error report dialog | `tests/test_config_manager.py::test_validation_error_report` | Error dialog shows errors | Format: tab + field + error |
| Phase 6 compiles, tests pass | `pytest tests/test_config_validators.py tests/test_config_manager.py -q -k "cross_file or help"` | Validation + Help tests pass | X passed, 0 failed |

### Phase 7: Save Workflow (Backup, Validate, Write, Reload)

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| Save creates backup files | `tests/test_config_manager.py::test_save_backup_created` | Backup files exist | *.backup.<timestamp> files created |
| Save validates before write | `tests/test_config_manager.py::test_save_validates_first` | Validation blocks bad save | Invalid data → no write, error dialog |
| Save error → restore from backup | `tests/test_config_manager.py::test_save_restore_on_error` | Backup restore works | Simulate write error, verify restore |
| Save success → reload from disk | `tests/test_config_manager.py::test_save_reload_from_disk` | Data reloaded after save | Save, modify, reload, verify match |
| Save discard changes prompt | `tests/test_config_manager.py::test_save_discard_changes_prompt` | Prompt if unsaved edits | Edit, click Cancel, get prompt |
| Save produces success dialog | `tests/test_config_manager.py::test_save_success_dialog` | Confirmation shows files updated | Dialog text includes file count |
| Save logs to serp-me log | `tests/test_config_manager.py::test_save_log_output` | Changes logged (manual) | Visual inspection |
| Phase 7 compiles, tests pass | `pytest tests/test_config_manager.py -q -k "save"` | Save workflow tests pass | X passed, 0 failed |

### Phase 8: Testing + Documentation

| Spec Criterion | Test Location | Test Name | Verification |
|---|---|---|---|
| Unit tests: validators on valid + invalid data | `tests/test_config_validators.py::test_validators_comprehensive` | All validators tested | Valid → pass, Invalid → error |
| Integration test: load → edit → validate → save → reload | `tests/test_config_manager.py::test_config_manager_integration` | Full workflow works | All 8 tabs round-trip correctly |
| Integration test: all tabs operate independently | `tests/test_config_manager.py::test_config_tabs_independent` | Tab isolation | Modify one tab, others unaffected |
| End-to-end: pipeline produces identical output | `tests/test_config_manager.py::test_e2e_pipeline_output_unchanged` | No regression | Run pipeline after save, output matches |
| Project docs updated | `docs/config_manager_guide.md` | User guide exists | Comprehensive usage guide |
| README updated | `README.md` | Configuration Manager documented | New section: "Configuration Manager" |
| Docstrings + Spec traceability | `config_manager.py`, `config_validators.py` | All functions have docstrings | Purpose + Spec + Tests lines |
| `docs/spec_coverage.md` updated | `docs/spec_coverage.md` | All criteria traced | Table with Status column |
| All 419+ tests pass | `pytest tests/ -q` | Regression test | 0 failures, 0 errors |

---

## Implementation Order + Dependencies

1. **Phase 1** (Foundation) — No dependencies
   - Extract validators (depends on existing code)
   - Create ConfigManager + BaseConfigTab scaffold
   - Update serp-me.py
   - Run Phase 1 tests

2. **Phase 2** (Simple tabs) — Depends on Phase 1
   - DomainOverridesTab (no nested structures)
   - ClassificationRulesTab (flat dict + list)
   - Run Phase 2 tests

3. **Phase 3** (List-of-dicts) — Depends on Phase 1-2
   - IntentMappingTab (reorder, edit dialogs)
   - StrategicPatternsTab (nested triggers list)
   - Run Phase 3 tests

4. **Phase 4** (Complex tabs) — Depends on Phase 1-3
   - BriefPatternRoutingTab (cross-file refs)
   - IntentClassifierTriggersTab (dual lists)
   - Run Phase 4 tests

5. **Phase 5** (Config + URL) — Depends on Phase 1-4
   - ConfigSettingsTab (type-safe widgets, file dialogs)
   - UrlPatternRulesTab (regex validation)
   - Run Phase 5 tests

6. **Phase 6** (Validation + Help) — Depends on Phase 1-5
   - Cross-file constraint validators
   - Help registry (HELP_BY_FILE, HELP_BY_FIELD)
   - Validation error report dialog
   - Run Phase 6 tests

7. **Phase 7** (Save workflow) — Depends on Phase 1-6
   - Backup logic
   - Validation before write
   - Error recovery (restore from backup)
   - Reload from disk after save
   - Run Phase 7 tests

8. **Phase 8** (Testing + Docs) — Depends on Phase 1-7
   - Comprehensive unit tests
   - Integration tests
   - E2E pipeline test
   - User guide (config_manager_guide.md)
   - Update README + docstrings
   - Update spec_coverage.md
   - Run all tests (419+)

---

## Adjacent Issues Found, Not Fixed

None at this stage. Will identify during Phase 1-2 code review.

---

## Implementation Ready

All acceptance criteria testable. No blocking issues. Ready to begin Phase 1.
