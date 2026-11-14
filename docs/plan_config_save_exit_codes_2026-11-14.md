# Plan: Configuration Manager save safety + pipeline exit codes

**Status:** approved 2026-11-14 (B2: partial failure exits 0). Chunk 0 and Chunk A built; Chunk B in progress.
**Source:** `docs/REVIEW-serp-discover-2026-11-14.md` findings M1, M4 (and T1 as a prerequisite).
**Tier (effort-budget):** Full — GUI config data path and pipeline status. Tests for the change, one
cold `learning-qa` pass over the diff before each push.
**Branch:** current (`fix/gui-model-robustness`), three commits, pushed one at a time.

## Chunk 0 — make the suite green (prerequisite)

| ID | Criterion | Test |
|---|---|---|
| P0.1 | `TestCollectionFreshness::test_cached_block_reports_when_it_was_collected_not_now` does not depend on today's date: the stale timestamp is computed relative to now, inside the cache TTL. | The existing test, passing; full suite exit code 0. |

## Chunk A — Configuration Manager (`config_manager.py`)

Approach: each tab keeps the loaded data as its model. `get_edited_data` starts from a deep copy
of that model and overwrites only what a widget edits. The rebuild logic moves into pure
module-level functions so it is tested without tkinter; Tk-gated round-trip tests run in CI under
xvfb.

| ID | Criterion | Test (`tests/test_config_manager_save.py`) |
|---|---|---|
| A1 | A file that exists but fails to parse sets `tab.load_error`; `save_to_disk` refuses with a message naming the file; the error is written to the log pane and shown in the tab. The file on disk is unchanged. | `test_unparseable_file_is_never_overwritten` — tmp file with bad YAML, save, bytes identical. |
| A2 | Save All writes only tabs whose data changed. Opening the manager and pressing Save All with no edits writes zero files. | `test_save_all_without_edits_writes_nothing` — mtimes of all nine tmp files unchanged. |
| A3 | Config Settings: keys with no widget (top-level lists such as `known_brands`, `None` values, empty dicts) survive a save unchanged. | `test_settings_merge_preserves_unwidgeted_keys` — pure function; `known_brands: [a, b]` in, same out. |
| A4 | Config Settings: an unparseable number/list/dict field is a validation error naming the field, not a silent `0` / `[]` / `{}`. | `test_settings_parse_failure_is_reported_not_coerced`. |
| A5 | Intent Mapping: every key on a rule other than the five edited fields (e.g. `rationale`) survives; rules the tree does not show are kept. | `test_intent_rules_keep_rationale` — pure function, run against the real `intent_mapping.yml`: 17 rationales in, 17 out. |
| A6 | Strategic Patterns and Brief Pattern Routing: an edit made in the Edit/Add dialog is in `get_edited_data()`; a renamed pattern keeps its other fields; a new pattern carries what was typed. | `test_pattern_dialog_edit_reaches_saved_data` (both tabs) — pure model functions; one Tk-gated round-trip. |
| A7 | Save All validates every changed tab first and writes nothing if any is invalid; it returns success/failure; Close destroys the window only when the save succeeded; the window X button goes through the same prompt. | `test_save_all_aborts_before_any_write_on_invalid_tab`; source-inspection test that `WM_DELETE_WINDOW` is bound (existing convention). |
| A8 | A file changed on disk since the tab loaded it is not overwritten: save refuses and offers reload. "Discard Changes" rebuilds the tab instead of stacking a second copy. | `test_save_refuses_when_file_changed_on_disk`; Tk-gated `test_revert_does_not_duplicate_widgets`. |

UI contract (ui-regression): no control is removed, renamed or moved. User-visible changes: Save
All reports "Saved N of 9 (others unchanged)"; a load-error banner on a tab that failed to load; a
"changed on disk" prompt; field-level parse errors.

## Chunk B — exit codes (`serp_audit.py`, `run_pipeline.py`, `serp-me.py`)

| ID | Criterion | Test (`tests/test_pipeline_exit_codes.py`) |
|---|---|---|
| B1 | `serp_audit.main()` returns non-zero for: missing serpapi package, missing `SERPAPI_KEY`, unreadable keyword CSV. `__main__` exits with that code. | `test_missing_key_exits_nonzero`, `test_missing_csv_exits_nonzero` — patched globals, no network. |
| B2 | Failed queries are counted and named: the run prints and logs "Fetched N of M queries" with the failed list, and the JSON carries `fetch_summary: {planned, fetched, failed: [...]}`. Zero successful queries exits non-zero and writes no outputs. | `test_failed_queries_are_counted_and_listed`, `test_zero_fetched_exits_nonzero` — `fetch_serp_data` stubbed. |
| B3 | A JSON, XLSX or MD write failure makes the run exit non-zero. `config.yml files.output_*` is updated only when all three files were written. | `test_write_failure_exits_nonzero_and_leaves_config_paths` — write to an unwritable tmp path. |
| B4 | `run_pipeline.py` fails (non-zero, no "Finished Successfully") when the audit's expected outputs are missing, instead of skipping validation. | `test_run_pipeline_fails_when_outputs_missing` — `run_command` stubbed. |
| B5 | The GUI labels a non-zero exit "FAILED (exit N)"; "MISMATCH" is used only for `validate_xlsx_vs_json.py`. | Pure function `exit_label(script, code)` unit test. |

B closes D-C-13 from the Nov 4 review.

**Decision needed (B2):** a run where some but not all queries failed. Recommended: exit 0, with
the count printed and stored in the JSON, so a mostly-good paid run can still be reviewed. The
alternative is a non-zero exit, which stops `run_pipeline` after the audit.

## Order

P0 → A (A1–A3 first: they stop file loss) → B. B does not depend on A.

## Documents updated in the same commits

- `docs/USER_MANUAL.md` — Configuration Manager save behaviour; pipeline failure messages and the
  "Fetched N of M" line.
- `docs/spec_v2_fields.md` or `docs/handoff_contract.md` only if `fetch_summary` belongs there —
  checked during build. `validate_xlsx_vs_json.py` must ignore the new key; checked by test B2.
- `docs/methodology.md` — no behaviour it describes changes; confirmed during build.
- `CLAUDE.md` — test count line and the "66 skipped are GUI tests" claim corrected.

## Adjacent issues found, not fixed

- Run button re-enabled mid-run; no Stop button; no subprocess timeout (review M2).
- Keyword files and `config.yml` written before the run is validated (M3).
- SerpAPI calls have no working timeout (M8) — one line, but a separate change.
- No per-keyword checkpoint; raw responses overwrite each other (M9).
- `verify_enrichment.py` cannot fail.
- Vacuous tab tests in `tests/test_config_manager.py`; they are left as they are.
- LLM truncation checks (M5), retired model IDs (M13).

## Not code-testable

The load-error banner and the "changed on disk" message are checked by a Tk test for presence
only; their wording and layout need a look in the running GUI. tkinter does run in the venv on
this machine, so the Tk tests run locally as well as in CI.
