# Implementation Plan: Report Clarity and Decisiveness (RC Spec)

**Date:** 2026-05-05  
**Spec ID Prefix:** RC  
**Spec:** report_clarity_spec.md  
**Status:** Planning phase

---

## Overview

This spec addresses 8 specific issues with `generate_insight_report.py` output:
1. No priority ranking of keywords
2. Missing feasibility section (Section 5c)
3. Misleading "Total Search Volume (Proxy)" label
4. PAA questions not prioritized by relevance
5. Strategic recommendations are template-matched, not data-driven
6. Content briefs not ranked or sequenced
7. Volatility section renders meaningless results without explanation
8. Entity/content dominance has no actionable interpretation

---

## Acceptance Criteria Checklist

### RC.1 — Executive Summary section (new Section 0)

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.1.1 — Best opportunity statement exists | String: `**Best keyword opportunity:**` appears first in Section 0 | `test_rc1_best_opportunity_statement_present` | Must appear before all other RC.1 content |
| RC.1.1 — Feasibility ranking in algorithm | Ranking logic: High > Moderate > Low > null | `test_rc1_feasibility_ranking_order` | Deterministic Python; intent/confidence are tie-breakers |
| RC.1.1 — Tie-breaking is alphabetical | When tied, keyword names sorted A→Z | `test_rc1_tiebreaker_alphabetical` | Must be deterministic |
| RC.1.1 — No feasibility data message | String: `cannot be determined — feasibility data is missing` when `feasibility_rows` empty | `test_rc1_no_feasibility_fallback` | Message must include "See Section 5c" |
| RC.1.1 — Partial feasibility message | Only keywords with DA data are eligible when some absent | `test_rc1_partial_feasibility_unranked_noted` | Keywords without DA data noted as "unranked" |
| RC.1.2 — Content brief priority sentence | String: `**Write first:**` followed by angle and pattern name | `test_rc1_write_first_priority` | Links to best opportunity keyword from RC.1.1 |
| RC.1.2 — Fallback brief selection | Uses first brief in list if no brief matches best keyword | `test_rc1_brief_fallback_first` | Fallback must be stated explicitly |
| RC.1.3 — Keyword action table renders | Table with columns: Keyword \| Intent \| Confidence \| Feasibility \| Action | `test_rc1_action_table_structure` | Must have exactly one row per keyword |
| RC.1.3 — Action vocabulary: Pursue | `✅ Pursue` for High Feasibility + preferred intent | `test_rc1_action_pursue_high` | Exact emoji and text required |
| RC.1.3 — Action vocabulary: Pursue with effort | `⚠️ Pursue with effort` for Moderate + matched intent | `test_rc1_action_pursue_effort` | Exact emoji and text required |
| RC.1.3 — Action vocabulary: Pivot or skip | `🔴 Pivot or skip` for Low Feasibility | `test_rc1_action_pivot` | Exact emoji and text required |
| RC.1.3 — Action vocabulary: Unranked | `📊 Unranked` for absent feasibility data | `test_rc1_action_unranked` | Exact emoji and text required |
| RC.1.3 — Action vocabulary: Mismatched intent | `⛔ Mismatched intent` for intent ∉ preferred_intents | `test_rc1_action_mismatched` | Exact emoji and text required |
| RC.1.3 — Action table sort order | Order: Pursue → Pursue with effort → Unranked → Pivot or skip → Mismatched intent; alphabetical within groups | `test_rc1_action_table_sort_order` | Deterministic Python sort |
| RC.1 — Section placement | `## 0. Executive Summary` appears before `## 1. Market Overview` | `test_rc1_executive_summary_section_placement` | Must be first substantive section |

**Dependencies:** None (foundational)  
**Test file:** `tests/test_report_clarity.py`

---

### RC.2 — Fix misleading "Total Search Volume (Proxy)" label

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.2 — Label removed | String `Total Search Volume (Proxy)` does NOT appear anywhere in rendered `.md` | `test_rc2_no_misleading_volume_label` | Case-sensitive match |
| RC.2 — Replacement content | Either option A (Keywords analyzed + result count + footnote) or option B (Keywords analyzed only) | `test_rc2_replacement_present` | Spec allows either, implementer chooses |

**Dependencies:** None  
**Test file:** `tests/test_report_clarity.py`

---

### RC.3 — Section 2 PAA: categorised output with question-to-offer mapping

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.3.1 — Section opening line | String: `These are the questions your audience is already asking. Use them as headings, FAQ items, or opening hooks in content targeting these keywords.` | `test_rc3_paa_opening_line` | Must appear at top of Section 2 |
| RC.3.2 — Categorized PAA unchanged | When categories present, existing category subsections (`🚨 High Distress Signals` etc.) render as now | `test_rc3_paa_categorized_unchanged` | No change to categorization logic |
| RC.3.3 — Uncategorized PAA intro | String: `No category signals detected. Questions are listed by frequency across keywords.` when no categories | `test_rc3_paa_uncategorized_intro` | Only when categories absent |
| RC.3.3 — Question ordering by frequency | Questions deduplicated and ordered by `count(distinct Source_Keyword)` descending | `test_rc3_paa_frequency_ordering` | Deterministic Python; no LLM |
| RC.3.4 — Most common question block | Format: `**Most common question:** <top question>\n**Appears for:** <keywords>` | `test_rc3_paa_most_common_block` | Appears when ≥1 PAA question exists |
| RC.3 — Removed editorializing | String `frantically searching for` does NOT appear in output | `test_rc3_no_emotional_editorializing` | Remove all unsupported emotional language |

**Dependencies:** None  
**Test file:** `tests/test_report_clarity.py`

---

### RC.4 — Section 4: make pattern triggers and competitor evidence visible

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.4.1 — Evidence block present | String: `> **Why this pattern fired:**` appears after `*Triggers found:*` for patterns with triggers | `test_rc4_evidence_block_present` | Markdown blockquote format |
| RC.4.1 — Evidence shows keyword | Evidence block contains `appeared in SERP results for **<most_relevant_keyword>**` | `test_rc4_evidence_shows_keyword` | Links trigger to specific keyword |
| RC.4.1 — Evidence shows competitor titles | At least 1 competitor title with trigger word and domain in evidence | `test_rc4_evidence_shows_competitor_titles` | Format: `*"<title>"* — <domain>` |
| RC.4.1 — Evidence title cap | Maximum 3 competitor title examples in evidence block | `test_rc4_evidence_title_cap` | Truncate if more than 3 found |
| RC.4.1 — Empty evidence omitted | When no organic results contain trigger, omit evidence block entirely | `test_rc4_empty_evidence_omitted` | Do NOT render empty blockquote |
| RC.4.2 — Template labels added | Strings: `Status Quo (template):`, `Bowen Reframe (template):`, `Content Angle (template):` appear in pattern blocks | `test_rc4_template_labels_present` | Prefix labels to distinguish editorial content |

**Dependencies:** None  
**Test file:** `tests/test_report_clarity.py`

---

### RC.5 — Section 5c: always render, explain absence

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.5 — Section always present | `## 5c. Keyword Feasibility & Pivot Recommendations` appears in all reports | `test_rc5_section_always_rendered` | Must render regardless of data |
| RC.5 — Absent data message | When `feasibility_rows` empty, section contains credential instructions and exact string `Re-run with credentials` | `test_rc5_no_data_credential_message` | Copy provided in spec |
| RC.5 — Partial data handling | When some keywords have DA data, keywords without show `—` in DA columns and `📊 No DA data` in Status | `test_rc5_partial_data_handling` | Render table with mixed data |

**Dependencies:** None (but related to RC.1 for understanding feasibility rankings)  
**Test file:** `tests/test_report_clarity.py`

---

### RC.6 — Section 5 entity dominance: add interpretive sentence

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.6 — Config key added | `report_thresholds.entity_dominance` exists in `config.yml` with threshold keys | `test_rc6_config_thresholds_present` | Must be in config, not hardcoded |
| RC.6 — One interpretation sentence | Exactly one interpretive sentence appears after entity dominance list in Section 5 | `test_rc6_single_interpretation_sentence` | Not more, not fewer |
| RC.6 — Counselling+directory branch | When `(counselling + directory) > 40%`: String contains `competitors are primarily counselling providers and directories` | `test_rc6_interpretation_counselling_directory` | Deterministic based on threshold |
| RC.6 — Education branch | When `education > 15%`: String contains `educational institutions hold significant SERP share` | `test_rc6_interpretation_education` | Only when threshold met |
| RC.6 — Government branch | When `government > 20%`: String contains `government sources dominate` | `test_rc6_interpretation_government` | Only when threshold met |
| RC.6 — Default (no dominance) | When no thresholds met: String contains `no single entity type dominates` | `test_rc6_interpretation_default` | Fallback message |

**Dependencies:** RC.6 config changes must be done before implementing rendering logic  
**Test file:** `tests/test_report_clarity.py`

---

### RC.7 — Section 6 volatility: suppress or explain non-comparable runs

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.7 — Nan suppression | String `nan` does NOT appear in rendered output when `volatility_score` is nan/null | `test_rc7_nan_suppressed` | Must not show invalid number |
| RC.7 — Non-comparable message | When `volatility_score` is nan and `comparability_warning` present: section contains "Not applicable for this run" and explains keyword set mismatch | `test_rc7_non_comparable_explanation` | Lists keywords in current run only and previous run only |
| RC.7 — Valid score rendering | When `volatility_score` is valid number, section renders as currently including comparability warning if present | `test_rc7_valid_score_renders` | No change to happy path |

**Dependencies:** None  
**Test file:** `tests/test_report_clarity.py`

---

### RC.8 — Content brief sequencing block

| Criterion | Verification | Test Name | Notes |
|-----------|--------------|-----------|-------|
| RC.8 — Sequencing block present | String `**Recommended writing order:**` appears before first `## Brief` block | `test_rc8_sequencing_block_header` | Must be before brief content |
| RC.8 — List format | Numbered list with format: `1. <brief title> — targets <keyword>` | `test_rc8_sequencing_list_format` | Link brief to its target keyword |
| RC.8 — List item count | Number of items equals number of content briefs in JSON | `test_rc8_sequencing_item_count` | One per brief, no more no fewer |
| RC.8 — Best opportunity first | First item targets best opportunity keyword from RC.1.1 | `test_rc8_best_keyword_first` | Uses matching `most_relevant_keyword` from brief |
| RC.8 — Remaining order | Remaining briefs ordered by feasibility/intent ranking of their `most_relevant_keyword` | `test_rc8_remaining_order_by_ranking` | Follows RC.1 ranking logic |
| RC.8 — Same keyword alphabetical | When two briefs map to same keyword, ordered alphabetically by pattern name | `test_rc8_same_keyword_alphabetical` | Tie-breaker within keyword group |
| RC.8 — No feasibility message | When feasibility absent, message states: `Without feasibility data, briefs are ordered by intent confidence (high → medium → low)` | `test_rc8_no_feasibility_message` | Clarify ordering method |

**Dependencies:** RC.1 (uses best opportunity keyword and ranking logic)  
**Test file:** `tests/test_report_clarity.py`

---

## Implementation Order

### Phase 0: Setup
1. ✅ Review spec and acceptance criteria (current phase)
2. Create `tests/test_report_clarity.py` scaffold with all test names
3. Verify `output/market_analysis_leila_20260504_2020.json` exists and load as fixture
4. Check if `docs/spec_coverage.md` exists; create if not

### Phase 1: Config Changes (Foundation)
5. **RC.6 config update**: Add `report_thresholds.entity_dominance` keys to `config.yml`
   - Thresholds: `counselling_directory_combined: 0.4`, `education: 0.15`, `government: 0.20`

### Phase 2: Foundational Logic (RC.1, RC.1.1, RC.1.2, RC.1.3)
6. **RC.1 full implementation**: Add Section 0 with best opportunity ranking
   - Extract keyword ranking logic (feasibility > intent > confidence)
   - Implement RC.1.1 best opportunity statement
   - Implement RC.1.2 content brief priority
   - Implement RC.1.3 keyword action table with all 5 action values
   - Tests: All RC.1.* tests

### Phase 3: Dependent on RC.1 (RC.8)
7. **RC.8 brief sequencing**: Uses ranking from RC.1
   - Insert sequencing block before brief list
   - Order briefs by best opportunity keyword + ranking
   - Tests: All RC.8.* tests

### Phase 4: Independent Changes
8. **RC.2 label fix**: Remove/replace "Total Search Volume (Proxy)"
   - Simpler change; can do anytime
   - Tests: RC.2.* tests

9. **RC.3 PAA improvements**: Categorization + frequency ordering
   - Update opening line
   - Add uncategorized frequency ordering
   - Add "Most common question" block
   - Remove editorializing
   - Tests: All RC.3.* tests

10. **RC.4 pattern evidence**: Add trigger evidence blocks
    - Extract evidence from `organic_results`
    - Add template labels
    - Tests: All RC.4.* tests

11. **RC.5 feasibility always render**: Unconditional Section 5c
    - Move guard condition; always render
    - Add credential instructions when absent
    - Handle partial data with `—` and `📊 No DA data`
    - Tests: All RC.5.* tests

12. **RC.6 entity dominance interpretation**: Add interpretation sentences
    - Load thresholds from config.yml
    - Implement threshold-based message selection
    - Tests: All RC.6.* tests

13. **RC.7 volatility handling**: Suppress/explain nan scores
    - Detect `volatility_score` nan/null
    - Replace with explanation when non-comparable
    - Tests: All RC.7.* tests

### Phase 5: Validation
14. Run full test suite: `pytest tests/test_report_clarity.py -v` (all tests pass)
15. Run full project tests: `pytest test_*.py tests/ -q` (no regression, count stays ≥ 476 passing)
16. Generate rendered report from leila fixture
17. Verify rendered report contains all RC items
18. Update `docs/spec_coverage.md` with RC.* coverage

---

## Dependency Graph

```
RC.6 Config    RC.1 (Foundation)
    ↓                ↓
  RC.6       →      RC.8
              
RC.2  RC.3  RC.4  RC.5  RC.7  (Independent)
```

**No blockers identified.** Config is simple YAML. Rendering changes are isolated by section.

---

## Recommendations & Observations

### 1. **Test Fixture Strategy**
The spec mentions the "leila run fixture" — this appears to be `output/market_analysis_leila_20260504_2020.json`. Consider:
- Load this as a pytest fixture (`@pytest.fixture`) to avoid duplication across all RC tests
- Also render report against it for manual verification (required in Definition of Done #3)

### 2. **Keyword Ranking Logic (Feasibility > Intent > Confidence)**
RC.1.1 implements a ranking algorithm: feasibility (High > Moderate > Low) > intent match (preferred > not preferred) > confidence (high > medium > low). This needs:
- A reusable function `_rank_keywords()` in `generate_insight_report.py`
- Deterministic (no LLM, no randomness)
- Used by both RC.1.1 (best opportunity keyword) and RC.8 (brief sequencing)
- Documented in `docs/USER_MANUAL.md::Keyword Prioritization` with examples

Extract the ranking function early and test it in isolation before using in both places.

### 3. **Config Thresholds Externalization (RC.6)**
The spec moves entity dominance thresholds to `config.yml`. This is good practice. Consider:
- Validate threshold keys exist during `load_data()` 
- Fail gracefully with helpful message if keys missing
- Document thresholds in `docs/config_reference.md`

### 4. **Feasibility Data is Expected**
DA is assumed to always be available (APIs properly configured). RC.5's credential instructions are a safeguard if APIs fail, not the normal path. Tests should focus on:
- **Happy path:** All keywords have DA data
- **Error case:** No keywords have DA data (show credential instructions)
- **Partial case:** Some keywords have DA data, some don't (rare, but render `—` in DA columns and `📊 No DA data` status)

Prioritize the happy path; the error cases are defensive.

### 5. **PAA Categorization Logic Already Exists**
RC.3.2 says "No change to categorization logic" — existing category rendering stays. The change is:
- Add intro line (RC.3.1)
- When no categories, add frequency ordering + most common block (RC.3.3, RC.3.4)
- Remove editorializing (RC.3)

This suggests the code already computes whether categories exist. Verify this before implementing.

### 6. **Competitor Evidence Extraction (RC.4)**
RC.4.1 requires finding competitor titles that contain trigger words. The data is in `organic_results`. Need to:
- For each pattern's `Detected_Triggers`, search `organic_results[*]["title"]` for trigger text
- Return up to 3 matches with domain
- This is new logic; test it independently from pattern rendering

### 7. **String Matching Tests**
Many acceptance criteria are "does X string appear in output?" — these are string-matching tests. Consider:
- Use `assertIn(substring, rendered_output)` not exact equality
- Be careful with whitespace/newlines (use `textwrap.dedent()` for multiline assertions)
- Consider case sensitivity — spec doesn't say case-insensitive, so assume case-sensitive

### 8. **Rendered Output Verification**
Definition of Done #3 requires verifying the rendered leila report. Recommend:
- Generate the report programmatically in a test
- Write to temp file or capture in memory
- Assert all required strings present
- Optionally save to `output/` for manual review

### 9. **Feasibility Data Structure Unknown**
The spec mentions `feasibility_rows` in the JSON — need to verify:
- What does the JSON structure look like?
- Where does `feasibility_score` / `feasibility_status` come from?
- What fields exist on each row? (Client DA, Comp DA, Gap, Status)
- Load the leila fixture and inspect before implementing RC.1 and RC.5

### 10. **Backward Compatibility (RC-P5)**
Spec says "no fields added to JSON schema." This means:
- All changes are in `generate_report()` rendering logic, not in data loading
- No new keys in the JSON output
- Can safely render old JSON files with new code

This is good — no migration needed.

---

## Key Clarifications (from user review)

**Domain Authority is always available.** The report assumes DA credentials are properly set up (DataForSEO or Moz). The "feasibility data is missing" scenario in RC.1.1 and RC.5 is an error/edge case, not a normal operating path.

**SERP Intent is a ranking factor, not a substitute for DA.** When ranking keywords:
1. **Feasibility** (High > Moderate > Low) is the primary factor
2. **Intent alignment** (matches `preferred_intents` > doesn't match) is mandatory — if intent doesn't match, skip the keyword
3. **Confidence** (high > medium > low) is the tie-breaker

This hierarchy is documented in `docs/USER_MANUAL.md::Keyword Prioritization section.` RC.1.1 and RC.8 implement this ranking logic.

---

## Known Questions to Resolve Before Coding

1. **Feasibility data structure**: What does `feasibility_rows` contain? What fields?
2. **PAA categories**: Where is the category detection logic? How does it work?
3. **Brief routing**: How does the code find `most_relevant_keyword` for each brief? Need to understand before RC.1.2 and RC.8.
4. **Organic results**: Where in the JSON are `organic_results`? Need to validate structure before RC.4.

**→ Recommend:** Load `output/market_analysis_leila_20260504_2020.json` and inspect structure before beginning Phase 2.

---

## Status Report Template

After implementation, the status report will follow this format:

```markdown
# Implementation Status: Report Clarity Spec

## All Acceptance Criteria

| ID | Description | Status | Evidence |
|---|---|---|---|
| RC.1.1 | Best opportunity statement | done/partial/not done | File + test name |
| ... | ... | ... | ... |

## Test Coverage

- `tests/test_report_clarity.py`: NN tests, all passing
- Pytest count: 476+ passing (≥ original count)

## Definition of Done Checklist

- [ ] All RC.1-RC.8 acceptance criteria met
- [ ] pytest passes, test count unchanged
- [ ] Leila fixture report verified
- [ ] config.yml has report_thresholds keys
- [ ] docs/spec_coverage.md updated

## Blockers / Known Issues

(None expected; will update if encountered)
```

---

## Next Steps

1. ✅ Plan approved (current phase)
2. Inspect JSON fixture structure
3. Implement Phase 1 (config)
4. Implement Phase 2-5 (features + tests)
5. Generate status report

