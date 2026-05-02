# Implementation Plan — Improvements Spec (I.1–I.7)

**Spec:** `serp_tool1_improvements_spec.md`
**Date:** 2026-05-01
**Status:** Awaiting user approval before any code changes.

---

## Flags before implementation begins

These issues require user decision before work starts.

### F1 — Test file location: root vs `tests/`

The spec places new tests in `tests/test_brief_routing.py`, `tests/test_intent_classifier_triggers.py`, `tests/test_most_relevant_keyword.py`, `tests/test_module_split.py`, `tests/test_serp_audit_split.py`. No `tests/` directory exists. The project convention (CLAUDE.md, pytest invocation `python3 -m pytest test_*.py -q`) discovers root-level `test_*.py` files. All 377 existing tests live in the root.

**Recommended resolution:** Create test files in the repo root as `test_brief_routing.py`, `test_intent_classifier_triggers.py`, `test_most_relevant_keyword.py`, `test_module_split.py`, `test_serp_audit_split.py`. Treat the spec's `tests/` prefix as a namespace label, not a directory path.

**User must confirm before tests are written.**

---

### F2 — `docs/methodology.md` does not exist

I.3 says: *"Document the change in `docs/methodology.md` Part 2 in the same commit (the file already references the previous logic)."* The file does not exist and has never been created.

**Recommended resolution:** Create `docs/methodology.md` as part of I.3, documenting the three-component keyword scoring introduced by that fix. The I.3 status report will note this was a net-new file, not an update to an existing one.

**User must confirm whether this is the right scope, or whether the file was intended to exist already.**

---

### F3 — `BRIEF_PAA_CATEGORIES` values differ from spec template

The spec YAML template shows `paa_categories: [External Locus]` for The Medical Model Trap and empty lists for the others. The current Python values are:

```python
"The Medical Model Trap":     {"General", "Commercial"}
"The Fusion Trap":            {"General", "Distress"}
"The Resource Trap":          {"Commercial", "Distress"}
"The Blame/Reactivity Trap":  {"Reactivity", "Distress"}
```

These use a different tag vocabulary (`General`, `Commercial`, `Distress`, `Reactivity`) from the intent classifier output (`External Locus`, `Systemic`, `General`). The spec says I.1 is a "pure relocation — no editorial changes," which means the YAML must contain the Python values verbatim, not the spec template values.

**Recommended resolution:** Relocate Python values verbatim. The spec template is illustrative. Any editorial revision to `paa_categories` is deferred to a separate pass after I.1 is reviewed.

**User must confirm this interpretation.**

---

### F4 — I.4 partially completed in previous session

The previous session added two editorial-content bullets to `## Always do this` in `CLAUDE.md`:
- "Edit configuration, not Python" (enhanced)
- "Externalise old content when adding new editorial knobs"

I.4 wants a dedicated `## Editorial content lives in config files` section with a specific inventory listing all editorial YAML/JSON files including `brief_pattern_routing.yml` (I.1) and `intent_classifier_triggers.yml` (I.2), which don't exist yet.

**Recommended resolution:** Implement I.4 after I.1 and I.2 land. Replace the two existing bullets with the fuller dedicated section specified in I.4. The section lists files that will exist by that point.

---

### F5 — I.7 rule number conflicts with existing Rule 7

The spec defines a Rule 7 titled "Old code is not someone else's problem." A different Rule 7 ("Editorial content lives in config files, not code") was added to `~/.claude/CLAUDE.md` in the previous session.

**Recommended resolution:** Append the I.7 rule text as Rule 8, not overwriting Rule 7. Criterion I.7.1 verifies by content, not rule number, so this satisfies the spec.

**User must confirm before modifying `~/.claude/CLAUDE.md`.**

---

### F6 — Baseline artifact for output-unchanged tests (I.1.5, I.2.6)

Tests `test_i15_pipeline_output_unchanged_after_externalisation` and `test_i26_pipeline_output_unchanged` need a pinned baseline brief to diff against. No such artifact is committed.

**Recommended resolution:** Before implementing I.1, generate a reference brief from the `couples_therapy` fixture and commit it as `tests/fixtures/brief_baseline_couples_therapy.md` (or root-level equivalent, per F1 resolution). The output-unchanged tests compare against this file. This is the first commit in Phase A.

---

## Implementation order

```
User confirms F1–F6
    └─► Commit baseline artifact (F6)
        └─► I.1  Externalise brief routing
            └─► I.2  Externalise intent classifier triggers
                └─► I.3  Improve keyword selection (confirm Relevant_Intent_Class
                │         mapping with user before committing YAML change)
                    └─► I.4  Update CLAUDE.md inventory (depends on I.1 + I.2 files)
                        └─► Phase A status report  →  user approves Phase B
                            └─► I.5  Split generate_content_brief.py (7 commits)
                                └─► I.6  Split serp_audit.py (7 commits)
                                    └─► Phase B status report

I.7  Independent — can land any time after F5 confirmed
```

---

## Phase A — Criteria, tests, and steps

### I.1 — Externalise PAA theme routing from `generate_content_brief.py`

| Criterion | Description | Evidence |
|---|---|---|
| I.1.1 | `brief_pattern_routing.yml` exists at repo root | file existence: `brief_pattern_routing.yml` |
| I.1.2 | YAML values match previous Python constants exactly | `test_brief_routing.py::test_i12_yaml_matches_previous_constants` |
| I.1.3 | No `BRIEF_PAA_THEMES`, `BRIEF_PAA_CATEGORIES`, `BRIEF_KEYWORD_HINTS`, `_BRIEF_INTENT_SLOTS` literal definitions remain in `generate_content_brief.py` | `test_brief_routing.py::test_i13_no_hardcoded_routing_in_python` |
| I.1.4 | Malformed YAML raises `ValueError` at startup | `test_brief_routing.py::test_i14_malformed_yaml_raises` (two sub-cases: missing key; unrecognised pattern_name) |
| I.1.5 | Pipeline brief output unchanged after externalisation | `test_brief_routing.py::test_i15_pipeline_output_unchanged_after_externalisation` (diffs against F6 baseline) |

**Steps:**
1. Extract constants verbatim from `generate_content_brief.py:74–107` and `2510–2517`.
2. Write `brief_pattern_routing.yml` using Python values (per F3), following spec YAML header/schema.
3. Add `load_brief_pattern_routing()` with validation: all `pattern_name` values must exist in `strategic_patterns.yml`; all keys required by `get_relevant_paa` must be present; `intent_slot_descriptions` must cover all intent buckets.
4. Module-level cache: loaded once per process.
5. Update all call sites in `generate_content_brief.py` (lines 2228–2230, 2269, 2552) to read from the loaded structure.
6. Write `test_brief_routing.py`.
7. Run full suite. Pass.
8. Commit: `[I.1] Externalise brief PAA routing to brief_pattern_routing.yml`.

---

### I.2 — Externalise `intent_classifier.py` trigger lists

| Criterion | Description | Evidence |
|---|---|---|
| I.2.1 | `intent_classifier_triggers.yml` exists at repo root | file existence: `intent_classifier_triggers.yml` |
| I.2.2 | YAML values match previous `DEFAULT_*` constants (set equality) | `test_intent_classifier_triggers.py::test_i22_yaml_matches_previous_constants` |
| I.2.3 | No `DEFAULT_MEDICAL_TRIGGERS` or `DEFAULT_SYSTEMIC_TRIGGERS` in `intent_classifier.py` | `test_intent_classifier_triggers.py::test_i23_no_hardcoded_triggers_in_python` |
| I.2.4 | Trigger < 4 chars in YAML raises `ValueError` | `test_intent_classifier_triggers.py::test_i24_short_trigger_raises` |
| I.2.5 | Constructor override hook still works | `test_intent_classifier_triggers.py::test_i25_constructor_override_still_works` |
| I.2.6 | PAA intent tags unchanged after externalisation | `test_intent_classifier_triggers.py::test_i26_pipeline_output_unchanged` |

**Steps:**
1. Extract `DEFAULT_MEDICAL_TRIGGERS` (`intent_classifier.py:36–77`) and `DEFAULT_SYSTEMIC_TRIGGERS` (`80–113`) verbatim. Preserve the multi_word / single_word split per existing comments.
2. Write `intent_classifier_triggers.yml`.
3. Add `load_triggers(path)` with 4-char minimum validation.
4. Update `IntentClassifier.__init__`: `medical_triggers=None, systemic_triggers=None`; call `load_triggers()` when both are `None`.
5. Remove `DEFAULT_MEDICAL_TRIGGERS` and `DEFAULT_SYSTEMIC_TRIGGERS` constants.
6. Write `test_intent_classifier_triggers.py`.
7. Run full suite. Pass.
8. Commit: `[I.2] Externalise intent classifier triggers to intent_classifier_triggers.yml`.

---

### I.3 — Improve most-relevant-keyword selection

| Criterion | Description | Evidence |
|---|---|---|
| I.3.1 | Three-component scoring implemented | `test_most_relevant_keyword.py::test_i31_three_component_scoring` |
| I.3.2 | PAA component contributes when `Relevant_Intent_Class` set | `test_most_relevant_keyword.py::test_i32_paa_intent_class_contributes` |
| I.3.3 | PAA component is 0 when `Relevant_Intent_Class` absent | `test_most_relevant_keyword.py::test_i33_no_intent_class_falls_back` |
| I.3.4 | Medical Model Trap matched to External Locus keyword in `1517` fixture (not cost keyword) | `test_most_relevant_keyword.py::test_i34_medical_model_picks_external_locus_keyword` |
| I.3.5 | All-zero scores returns `None` | `test_most_relevant_keyword.py::test_i35_all_zero_returns_none` |
| I.3.6 | Updated docstring contains Spec/Tests references for I.3 | Visual inspection of `generate_insight_report.py::_get_most_relevant_keyword` | *Non-automated — human reviewer checks* |

**Steps:**
1. Add `Relevant_Intent_Class` to `strategic_patterns.yml` entries. **Pause and present proposed mapping to user before committing:**
   - The Medical Model Trap → `External Locus`
   - The Fusion Trap → omit
   - The Resource Trap → omit
   - The Blame/Reactivity Trap → `External Locus`
2. Update `_get_most_relevant_keyword()` signature to include `paa_questions: list`.
3. Implement three-component scoring formula (weights 3 / 2 / 1).
4. Trace `paa_questions` availability: verify it is accessible in `generate_report()` via `data.get("paa_questions", [])` and passed to `_render_pattern_intent_context()`. Adjust call chain if needed.
5. Update `_render_pattern_intent_context()` call site to pass `paa_questions`.
6. Update docstring for `_get_most_relevant_keyword()` with Spec/Tests for I.3.
7. Create `docs/methodology.md` (per F2) documenting the three-component scoring.
8. Write `test_most_relevant_keyword.py`.
9. Run full suite. Pass.
10. Run before/after comparison against `1517` fixture. Document which keyword each pattern selects before and after. Include diff in status report.
11. Commit: `[I.3] Improve keyword selection: three-component scoring with PAA intent class`.

---

### I.4 — Update CLAUDE.md editorial content section

| Criterion | Description | Evidence |
|---|---|---|
| I.4.1 | `## Editorial content lives in config files` section exists in project-level `CLAUDE.md` | `grep "## Editorial content lives in config files" CLAUDE.md` |
| I.4.2 | Section lists all editorial config files including `brief_pattern_routing.yml` and `intent_classifier_triggers.yml` | Visual inspection |
| I.4.3 | Section appears before `## Reference documentation` | `grep -n` position check |

**Steps:**
1. Replace the two existing editorial-content bullets in `## Always do this` with the dedicated `## Editorial content lives in config files` section placed immediately before `## Reference documentation`.
2. Section text matches spec I.4 verbatim, with inventory updated to include `brief_pattern_routing.yml` and `intent_classifier_triggers.yml`.
3. Commit: `[I.4] Add editorial-content section to CLAUDE.md with full config inventory`.

---

### I.7 — Add "Old code is not someone else's problem" to `~/.claude/CLAUDE.md`

| Criterion | Description | Evidence |
|---|---|---|
| I.7.1 | Rule exists in `~/.claude/CLAUDE.md` with the adjacent-issues text | Visual inspection (file path confirmed) |
| I.7.2 | Rule's example mentions the externalisation pattern | Visual inspection |

**Steps:**
1. Append I.7 rule text as Rule 8 to `~/.claude/CLAUDE.md` (per F5 resolution).
2. Local change only — no repo commit.

---

## Phase B — Criteria summary (gated)

**Phase B does not begin until Phase A is complete, the Phase A status report is reviewed, and the user explicitly approves.**

A separate per-fix implementation plan is produced before each Phase B fix begins.

### I.5 — Split `generate_content_brief.py`

| Criterion | Evidence |
|---|---|
| I.5.1 Five new files with listed functions | `test_module_split.py::test_i51_files_exist_with_functions` |
| I.5.2 `generate_content_brief.py` < 400 lines | `test_module_split.py::test_i52_main_module_size` |
| I.5.3 Zero failures | test suite output |
| I.5.4 Pipeline output unchanged | `test_module_split.py::test_i54_pipeline_output_unchanged` |
| I.5.5 Status report lists every function moved with commit hashes | `docs/i_phaseB_status_<date>.md` |

Binding constraint: seven numbered commits, one per step. Agent stops and reports on any test failure.

### I.6 — Split `serp_audit.py`

| Criterion | Evidence |
|---|---|
| I.6.1 `docs/serp_audit_split_plan_<date>.md` with user approval before code moves | file existence + approval annotation |
| I.6.2 New files with approved functions | `test_serp_audit_split.py::test_i62_files_exist_with_functions` |
| I.6.3 `serp_audit.py` < 500 lines | `test_serp_audit_split.py::test_i63_main_module_size` |
| I.6.4 Zero failures | test suite output |
| I.6.5 Pipeline output structurally identical to previous run | `test_serp_audit_split.py::test_i65_pipeline_output_unchanged` |

---

## Adjacent issues found, not fixed

Per spec Rule 7 / CLAUDE.md — listed here for user awareness; none are in scope for this spec:

1. **`generate_content_brief.py:95` category tag mismatch** — `BRIEF_PAA_CATEGORIES` uses tags (`General`, `Commercial`, `Distress`, `Reactivity`) that differ from intent classifier output (`External Locus`, `Systemic`, `General`). Relocation is verbatim (F3), but the tag mismatch may be a latent bug. Candidate for a dedicated editorial pass after I.1 is reviewed.
2. **`generate_content_brief.py:2510` layout inconsistency** — `_BRIEF_INTENT_SLOTS` is placed 2,400 lines below the other three routing constants. Resolved naturally by I.1 (all move to YAML).
3. **`generate_insight_report.py:332` stale docstring** — References `test_c21_all_four_patterns_have_intent_context`; that test was renamed to `test_c21_all_active_patterns_have_intent_context` in the previous session. Resolved naturally when I.3 rewrites the docstring.

---

## Status report locations

- Phase A: `docs/i_phaseA_status_20260501.md`
- Phase B: `docs/i_phaseB_status_<date>.md`
- Spec coverage: `docs/spec_coverage.md` — updated after each phase to include all I.* criteria
