# Implementation Plan — Completion Spec (`serp_tool1_completion_spec.md`)

**Date:** 2026-05-01  
**Spec:** `serp_tool1_completion_spec.md`  
**Status:** Plan (precedes implementation)

---

## Acceptance criteria and verification

Each criterion comes from the spec's acceptance criterion lists under Fix M1, M2, and M3.

### M1.A — Section 5b. Per-Keyword SERP Intent

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 1 | `## 5b. Per-Keyword SERP Intent` exists in rendered markdown | `test_markdown_rendering.py::test_section_5b_header_exists` — `assertIn("## 5b. Per-Keyword SERP Intent", report)` |
| 2 | All 6 keyword blocks appear in Section 5b | `test_markdown_rendering.py::test_all_six_keyword_blocks_present` — loops over all 6 keyword strings |
| 3 | "couples counselling" block has `Mixed-intent components` line | `test_markdown_rendering.py::test_couples_counselling_has_mixed_intent_components` |
| 4 | "couples counselling" block has `Strategy: backdoor` | `test_markdown_rendering.py::test_couples_counselling_has_strategy_backdoor` |
| 5 | "How much is couples therapy?" block has NO `Mixed-intent components` | `test_markdown_rendering.py::test_cost_keyword_has_no_mixed_intent_line` |
| 6 | "What type of therapist?" block has `Local pack present: yes` | `test_markdown_rendering.py::test_therapist_keyword_has_local_pack_present` |
| 7 | Section 5b sits between Section 5 and Section 6 | `test_markdown_rendering.py::test_section_5b_between_section_5_and_section_6` |
| 8 | Regex `Section 5b\. Per-Keyword SERP Intent` appears exactly once | `test_markdown_rendering.py::test_section_5b_appears_exactly_once` |

**Non-testable criterion:** None. All can be expressed as string matches against `generate_insight_report.generate_report(fixture_data)`.

**Discrepancy to resolve before implementation:** `generate_insight_report.py:187` uses `## 5b. Keyword Feasibility`. Proposed fix: rename to `## 5c`. Must be called out in status report.

---

### M1.B — Mixed-Intent Strategic Note in Section 4

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 9 | One Mixed-Intent Strategic Note callout for "couples counselling" in Section 4 | `test_markdown_rendering.py::test_mixed_intent_note_callout_present` — `assertIn("⚖️ Mixed-Intent Strategic Note: couples counselling", report)` |
| 10 | String `backdoor` appears in the rendered markdown | `test_markdown_rendering.py::test_backdoor_string_in_report` |
| 11 | Note appears after Section 4 header and before Section 5 | `test_markdown_rendering.py::test_note_appears_in_section_4` — position comparison |
| 12 | No callout for non-mixed keyword ("effective couples therapy?") | `test_markdown_rendering.py::test_only_mixed_keywords_get_callout` |

---

### M1.C — `## 1a. SERP Intent Context` in each content brief

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 13 | All four content briefs contain `## 1a. SERP Intent Context` | `test_markdown_rendering.py::test_all_briefs_have_1a_section` |
| 14 | `1a` appears before `## 1. The Core Conflict` in every brief | `test_markdown_rendering.py::test_1a_appears_before_section_1` |
| 15 | No brief's 1a subsection renders literal `None` or `null` | `test_markdown_rendering.py::test_no_literal_none_in_1a` |
| 16 | Regex `1a\. SERP Intent Context` appears exactly four times across all briefs | `test_markdown_rendering.py::test_1a_section_count_in_combined_report` |

---

### M2.A — Classifier audit output

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 17 | `docs/classifier_audit_couples_therapy_<date>.md` exists with audit output | File existence check: `os.path.exists("docs/classifier_audit_couples_therapy.md")` |

**Note:** File already committed in prior pass. This criterion is pre-satisfied.

---

### M2.B — Intent mapping rationale with fixture URLs

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 18 | `intent_mapping.yml` exists at repo root | File existence: `os.path.exists("intent_mapping.yml")` |
| 19 | `docs/intent_mapping_rationale.md` exists | File existence check |
| 20 | EC1 addressed with fixture URL | String match: `"psychologytoday.com"` in `docs/intent_mapping_rationale.md` |
| 21 | EC2 addressed with fixture URL | String match: `"openspacecounselling.ca"` in doc |
| 22 | EC3 addressed with fixture URL | String match: `"aio_citation_count"` or `"11 citations"` in doc |

---

### M2.C — Validator rules document

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 23 | `docs/validator_rules_20260501.md` exists | File existence |
| 24 | All five fields (`primary_intent`, `is_mixed`, `confidence`, `dominant_pattern`, `mixed_intent_strategy`) covered | String match: all five field names appear in the doc |
| 25 | Each field has severity stated | String match: `HARD` and `SOFT` appear in the doc |
| 26 | Each field has a test path | String match: `test_generate_content_brief.py` appears for each field |

---

### M2.D — README and documentation

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 27 | README has "What's new" section | `assertIn("What's new in this version", open("README.md").read())` |
| 28 | README has backwards compatibility note | `assertIn("Backwards compatibility", open("README.md").read())` |
| 29 | README has Tool 1 → Tool 2 handoff subsection | `assertIn("Tool 1 → Tool 2", open("README.md").read())` |
| 30 | `docs/handoff_contract.md` exists | File existence |

**Note:** All four sub-criteria were satisfied in the prior pass.

---

### M3 — Handoff schema clarification

| # | Criterion | Test / Evidence |
|---|-----------|-----------------|
| 31 | Option A or B implemented and stated | String match: `"source_keyword"` and `"primary_keyword_for_url"` both appear in `docs/handoff_contract.md` |
| 32 | Fixture evidence of divergence present | String match: `"counselling-vancouver.com"` (one of the 4 diverging URLs) in `docs/handoff_contract.md` |

---

## Implementation order

Dependencies flow as follows:

1. **Write status report** (`docs/v2_dod_status_20260501_completion.md`) — Rule 1 first deliverable, no code changes yet. [Already done: commit `10a0e09`]
2. **M1.A** — `generate_insight_report.py`: add `_render_serp_intent_section()`, insert between Section 5 and feasibility, rename feasibility to `## 5c`. No dependencies.
3. **M1.B** — `generate_insight_report.py`: add Mixed-Intent Strategic Note loop in Section 4. Depends on `keyword_profiles` being available in `data` dict (it is).
4. **M1.C** — `generate_content_brief.py`: update `generate_brief()` to add `## 1a.` block. Depends on `get_relevant_paa()` already returning `Source_Keyword` records (it does).
5. **M2.B** — `docs/intent_mapping_rationale.md`: add fixture URLs for EC1/EC2/EC3. No code dependency.
6. **M2.C** — `docs/validator_rules_20260501.md`: new file. No code dependency.
7. **M3** — `docs/handoff_contract.md`: add source_keyword/primary_keyword_for_url section. No code dependency.
8. **Tests** — `test_markdown_rendering.py`: write after M1 implementation to assert against fixture. Depends on steps 2–4.
9. **Final status report** — `docs/implementation_plan_20260501.md` status column updated to `done`. Produced after all tests pass.

---

## Non-testable criteria and resolutions

All 32 criteria above can be expressed as one of: string match in file, file existence check, or pytest assertion. No criteria required flagging as untestable.

---

*This plan is committed before any implementation code is written. Implementation begins only after user approval.*
