# Implementation Plan — `serp_tool1_cleanup_spec.md`

**Date:** 2026-05-01  
**Spec:** `serp_tool1_cleanup_spec.md`  
**Status:** Plan (awaiting approval)

---

## Pre-flight findings (critical — read before approving)

### Flag 1 — C.1 appears pre-satisfied

`generate_insight_report.py:327` already emits `"\n## 5b. Per-Keyword SERP Intent"` — the `5b.` prefix is present in the current code. The spec says the bug is a missing prefix, but the code already has it (likely added in the M1.A pass). The existing test `test_section_5b_header_exists` passes.

**Resolution:** C.1.1 and C.1.2 tests will be written. If they pass against the current code, C.1 is marked `done` at no implementation cost. If they fail, the one-line fix is applied. Either way, the tests are required deliverables.

### Flag 2 — C.2 section numbering discrepancy

The spec references "Section 6 ('Tool Recommendation Assessment')". The current code has no Section 6 by that name — Section 6 is "Market Volatility" (`generate_insight_report.py:291`). The Bowen pattern blocks ("Medical Model Trap" etc.) are in **Section 4** (`## 4. Strategic Recommendations`), rendered from the `strategic_recommendations` list.

**Resolution:** C.2 will be implemented in the Section 4 loop where `strategic_recommendations` are rendered. The status report will document this structural deviation from the spec's section numbering.

### Flag 3 — `serp_tools_upgrade_spec_v2.md` not found

C.3 requires the coverage matrix to cover all criteria from `serp_tools_upgrade_spec_v2.md`. This file does not exist in the repo (searched all paths including `docs/specs/`). Found only in cross-references in other docs.

**Resolution before approving:** Two options:
- **Option A:** Proceed without it. C.3's coverage matrix covers the three specs that do exist (`serp_tool1_fix_spec.md`, `serp_tool1_completion_spec.md`, `serp_tool1_cleanup_spec.md`). The `v2` spec rows are omitted with a note in the matrix. C.3 row counts will be lower.
- **Option B:** Locate and provide `serp_tools_upgrade_spec_v2.md`. If you have it elsewhere, paste or upload it and I'll include it.

**Awaiting your decision on Option A or B before executing C.3.**

### Flag 4 — `tests/` directory convention

The spec names tests as `tests/test_markdown_rendering.py` and `tests/test_spec_coverage.py`. The project runs `python3 -m pytest test_*.py -q`, which discovers only root-level `test_*.py` files. A `tests/` subdirectory would be silently skipped.

**Resolution:** New C tests go into the existing root-level files:
- C.1.1, C.1.2 → added to `test_markdown_rendering.py` (root)
- C.3.2–C.3.6 → new `test_spec_coverage.py` (root)

The status report will note the path substitution. The spec's `tests/` paths are recorded as `superseded` naming in the coverage matrix.

### Flag 5 — C.4 appears pre-satisfied

`docs/v2_dod_status_20260501_final.md` already exists in `docs/` (created there directly — never placed at root). No `v2_dod_status*.md` file exists at the repo root. C.4.1 and C.4.2 are pre-satisfied.

---

## Acceptance criteria

### C.1 — Section 5b prefix

| ID | Criterion | Test |
|----|-----------|------|
| C.1.1 | `## 5b. Per-Keyword SERP Intent` appears exactly once in rendered output for `couples_therapy` fixture | `test_markdown_rendering.py::test_c11_section_5b_prefix_present` |
| C.1.2 | `## Per-Keyword SERP Intent` (without prefix) does NOT appear | `test_markdown_rendering.py::test_c12_no_unprefixed_section_5b` |

### C.2 — SERP Intent Context in Section 4 pattern blocks

| ID | Criterion | Test |
|----|-----------|------|
| C.2.1 | Each of the four pattern blocks in Section 4 contains exactly one line beginning with `*SERP intent context` | `test_markdown_rendering.py::test_c21_all_four_patterns_have_intent_context` |
| C.2.2 | The Medical Model Trap's intent context line names a real keyword (not literal `<keyword>`) | `test_markdown_rendering.py::test_c22_medical_model_intent_context_has_real_keyword` |
| C.2.3 | Any pattern whose most-relevant keyword is "couples counselling" includes `mixed: informational + local` | `test_markdown_rendering.py::test_c23_mixed_intent_segment_when_applicable` |
| C.2.4 | No intent context line renders `None`, `null`, `<keyword>`, or `<primary_intent>` | `test_markdown_rendering.py::test_c24_no_template_placeholders_leak` |

### C.3 — Spec coverage matrix

| ID | Criterion | Test |
|----|-----------|------|
| C.3.1 | `docs/spec_coverage.md` exists | File existence: `docs/spec_coverage.md` |
| C.3.2 | Table contains ≥ 50 rows | `test_spec_coverage.py::test_c32_minimum_row_count` |
| C.3.3 | Every row has all six columns populated; Test=`manual` rows have Manual Verification entry | `test_spec_coverage.py::test_c33_no_empty_cells` |
| C.3.4 | Every Implementation cell naming a file path refers to a file that exists | `test_spec_coverage.py::test_c34_implementation_paths_exist` |
| C.3.5 | Every Test cell naming a test refers to a test that exists (via `pytest --collect-only`) | `test_spec_coverage.py::test_c35_named_tests_exist` |
| C.3.6 | Manual Verification subsection lists every `manual` criterion with a human-review description | `test_spec_coverage.py::test_c36_manual_section_complete` |

### C.4 — Status report location

| ID | Criterion | Test |
|----|-----------|------|
| C.4.1 | `docs/v2_dod_status_20260501_final.md` exists | File existence: `docs/v2_dod_status_20260501_final.md` |
| C.4.2 | No `v2_dod_status_*.md` at repo root | Shell: `ls *.md \| grep -c v2_dod_status` returns 0 |
| C.4.3 | This spec's status report exists at `docs/c_status_20260501.md` | File existence: `docs/c_status_20260501.md` |

---

## Implementation order

Dependencies flow as follows:

1. **Verify C.1** — run existing `test_section_5b_header_exists`; if passes, write C.1.1/C.1.2 tests immediately. If fails, apply one-line fix first.
2. **C.2 implementation** — add SERP intent context lines to the Section 4 pattern block loop in `generate_insight_report.py`. Requires understanding `strategic_recommendations` trigger data structure. No dependencies.
3. **C.1.1 / C.1.2 tests** — add to `test_markdown_rendering.py`. Depends on step 1 confirmation.
4. **C.2.1–C.2.4 tests** — add to `test_markdown_rendering.py`. Depends on C.2 implementation.
5. **C.3 — `docs/spec_coverage.md`** — read all three available specs, inspect codebase, populate table. No code dependency. Depends on Flag 3 decision (Option A vs B).
6. **C.3 tests — `test_spec_coverage.py`** — new file at repo root. Depends on `docs/spec_coverage.md` existing.
7. **C.4 verification** — confirm pre-satisfied; no action needed unless files are mislocated.
8. **Status report — `docs/c_status_20260501.md`** — produced last, after all tests pass.

---

## Files to create / modify

| Action | File | Purpose |
|--------|------|---------|
| Modify | `generate_insight_report.py` | C.2: insert intent context line per pattern block |
| Modify (tests) | `test_markdown_rendering.py` | C.1.1, C.1.2, C.2.1–C.2.4 |
| Create | `test_spec_coverage.py` | C.3.2–C.3.6 |
| Create | `docs/spec_coverage.md` | C.3.1 |
| Create | `docs/c_status_20260501.md` | C.4.3 + final status report |

No other code files modified.

---

## Blocking question

**Flag 3** is blocking C.3: do you want Option A (proceed without `serp_tools_upgrade_spec_v2.md`) or Option B (provide the file)?
