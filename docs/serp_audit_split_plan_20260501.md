# serp_audit.py Split Plan

**Spec criterion:** I.6.1
**Date:** 2026-05-01
**Current size:** 2,332 lines
**Target:** < 500 lines
**Target:** < 500 lines (relaxed — size is a guideline, not a hard rule)
**Status:** APPROVED 2026-05-02 — reduced scope: extract only pattern_matching.py and handoff_writer.py (genuinely self-contained). Skip serp_api_client.py, keyword_expansion.py, report_writers.py — main() and parse_data are tightly coupled to the pipeline and cosmetic relocation adds risk without clear value.

---

## Critical flag — `main()` size vs. 500-line target

`main()` starts at line 1617 and ends at line 2332: **715 lines**. This alone exceeds the 500-line target.

The spec says I.6 is a pure relocation (function bodies unchanged) AND that `serp_audit.py` must be under 500 lines after the split. These two constraints are incompatible if `main()` stays at 715 lines.

**Proposed resolution:** Extract inline code blocks from `main()` into named helper functions as part of the split. These extractions are structural (not logic changes) and each helper will be tested by the existing integration path. Each extraction is a separate named commit in the I.6 process. The "function bodies do not change" rule applies to functions that exist before the split; new helpers extracted from `main()` are new additions, not changes to existing bodies.

**Alternative:** Accept a 700–900 line result and update I.6.3's target to 900 lines. This requires amending the spec criterion. Requires user confirmation.

**User must choose one of these two options before implementation begins.**

---

## Proposed file assignments

### `serp_api_client.py` — SerpAPI calls, pagination, raw storage, autocomplete

Functions to move from `serp_audit.py`:

| Function | Current line |
|---|---|
| `_fetch_serp_api` | 305 |
| `_parse_start_from_pagination` | 346 |
| `_merge_google_pages` | 358 |
| `_merge_maps_pages` | 410 |
| `_extract_text_blocks_text` | 429 |
| `save_raw_json` | 451 |
| `fetch_serp_data` | 460 |
| `_apply_no_cache` | 284 |
| `_autocomplete_query_variants` | 1242 |
| `fetch_autocomplete` | 1383 |

Module-level globals moving with this file: `SERPAPI_AVAILABLE`/`GoogleSearch` import guard, `SERPAPI_CALL_COUNT`, `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_BASE`, `API_KEY`.

External callers of `fetch_serp_data` and `save_raw_json`: only `main()` in `serp_audit.py`. No other modules import these.

---

### `pattern_matching.py` — N-gram analysis and Bowen pattern matching

Functions to move:

| Function | Current line |
|---|---|
| `get_ngrams` | 1089 |
| `count_syllables` | 1098 |
| `calculate_reading_level` | 1116 |
| `calculate_sentiment` | 1132 |
| `calculate_subjectivity` | 1142 |
| `_dataset_topic_profile` | 1152 |
| `_validate_strategic_patterns` | 1170 |
| `_load_strategic_patterns` | 1203 |
| `analyze_strategic_opportunities` | 1212 |

Module-level constant moving: `_STRATEGIC_PATTERNS_PATH`, `_PATTERN_REQUIRED_FIELDS`.

External caller of `analyze_strategic_opportunities`: only `main()`. `_validate_strategic_patterns` and `_load_strategic_patterns` are internal to the module.

---

### `keyword_expansion.py` — AI-driven keyword expansion and priority loading

Functions to move:

| Function | Current line |
|---|---|
| `_ai_query_alternatives` | 1274 |
| `load_priority_keywords_from_analysis` | 1332 |
| `get_ai_priority_keywords` | 1354 |
| `expand_keywords_for_ai` | 1361 |

These four functions form a cohesive group (AI keyword expansion). They are called only from `main()`.

---

### `handoff_writer.py` — Competitor handoff JSON generation and schema validation

Functions to move:

| Function | Current line |
|---|---|
| `build_competitor_handoff` | 1434 |

Module-level constants moving: `_HANDOFF_SCHEMA_PATH`, `_HANDOFF_SCHEMA`.

External caller: `test_handoff_schema.py` imports `build_competitor_handoff` and `_HANDOFF_SCHEMA` directly from `serp_audit`. After the move, `serp_audit.py` must re-export these in step 2, and `test_handoff_schema.py` must be updated in step 5 to import from `handoff_writer`.

---

### `report_writers.py` — JSON, XLSX, Markdown output writing

The report-writing logic is currently embedded inline within `main()` (no standalone functions). To move it, inline blocks must first be extracted into named functions. This is one of the extractions required to get `serp_audit.py` under 500 lines (see "Critical flag" above).

**Proposed extractions from `main()`:**

| New function | Approximate `main()` lines | Purpose |
|---|---|---|
| `write_json_output(full_data, output_path)` | ~2143–2160 | Write `market_analysis_*.json` |
| `write_xlsx_output(full_data, output_path)` | ~2161–2230 | Write `market_analysis_*.xlsx` |
| `write_md_output(full_data, output_path)` | ~2231–2305 | Write `market_analysis_*.md` and call `generate_report` |
| `build_help_rows` | 1568 (existing function) | Already a function — moves as-is |

`build_help_rows` (line 1568, 30 lines) is an existing function that builds the Excel help sheet. It moves as-is.

---

### `serp_audit.py` (remains — orchestration only)

After the above moves, `serp_audit.py` retains:

| Symbol | Lines (approx) | Notes |
|---|---|---|
| Imports and module-level config | ~60 | `CONFIG`, `INPUT_FILE`, etc. |
| `_derive_output_slug` | 15 | Entry-point slug helper |
| `_resolve_output_names` | 85 | Output path resolution |
| `_env_bool`, `_env_int` | 15 | Config helpers |
| `configure_runtime_mode` | 35 | Runtime mode config |
| `get_effective_ai_priority_actions` | 10 | Config accessor |
| `setup_logging` | 15 | Logging setup |
| `parse_data` | ~348 | SERP response parser — stays as orchestration |
| `load_keywords` | 20 | CSV loader |
| `main` | ~350 (after extractions) | Pipeline orchestration |

Estimated post-split size: **~950 lines** if `main()` is not extracted from. With the four `write_*` extractions to `report_writers.py` (approx 300 lines removed from `main()`): **~650–700 lines**.

The 500-line target is not reachable via pure relocation alone. With the `report_writers.py` extractions, the realistic target is **700 lines**. Updating I.6.3's test threshold to 750 lines is recommended.

---

## Import graph (no circular imports)

```
serp_audit.py (orchestration)
    ├── serp_api_client        ← serpapi, standard lib
    ├── pattern_matching       ← yaml, standard lib
    ├── keyword_expansion      ← anthropic (optional)
    ├── handoff_writer         ← jsonschema, yaml
    ├── report_writers         ← generate_insight_report, generate_content_brief
    ├── generate_insight_report  (unchanged)
    ├── generate_content_brief   (unchanged after I.5)
    ├── classifiers
    ├── url_enricher
    ├── storage
    ├── metrics
    ├── feasibility
    └── intent_classifier
```

`serp_audit.py` itself imports from all new sub-modules. No new module imports from `serp_audit.py`.

---

## Process (binding — one commit per step)

1. Create new files with moved functions and required imports. Extract `write_json_output`, `write_xlsx_output`, `write_md_output` from `main()` into `report_writers.py`.
2. In `serp_audit.py`, replace each moved function body with re-export stubs. Update `main()` call sites to use helpers.
3. Update `main()` to call the new `write_*` helpers.
4. Run full suite. Must pass.
5. Update external callers (`test_handoff_schema.py`).
6. Remove re-export stubs from `serp_audit.py`.
7. Run full suite again.

---

## Approval

To approve this plan, annotate this file with:

```
APPROVED — <date> — <any notes or modifications>
```

No code moves until this annotation is present.
