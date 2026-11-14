# Plan: keep paid SERP responses and resume a run (M9); no writes before a run starts (M3)

**Status:** approved 2026-11-14 with the four recommended decisions. Chunk C built.
**Source:** `docs/REVIEW-serp-discover-2026-11-14.md` findings M9 and M3.
**Tier (effort-budget):** Full — the paid fetch path and the launcher's config/keyword writes.
Tests for the change, one cold `learning-qa` pass over each diff before pushing.
**Branch:** current (`fix/gui-model-robustness`), two commits, pushed one at a time.

## What the code does now

**M9**
- `save_raw_json` writes `raw/<run_id>/<engine>_response.json`. The name has no keyword in it,
  so each keyword overwrites the last. After a 20-keyword run only the last keyword's raw data
  is on disk.
- Parsed results are held in memory until the final write. A crash, a Stop, or a failed run
  (which now exits non-zero and writes nothing) loses every response already paid for. The only
  other copy is the INFO log, which is not machine-readable as data.
- There are nine callers of `_fetch_serp_api`: main SERP pages, AI Overview, AI probe, related
  questions, Maps, autocomplete, pivot fetches, situational probes and Bing.

**M3**
- `prepare_keyword_run_context` (`serp-me.py:804`) runs at the top of `run_script` for three
  scripts. It writes the keyword CSV, and for the pipeline it also writes `files.input_csv` and
  three `files.output_*` paths with a new timestamp into `config.yml`.
- All of that happens before the "no JSON found" and "have you run feasibility?" checks, which
  can still cancel the run, and before the process starts. A cancelled, stopped or failed run
  leaves `config.yml` pointing at output files that were never written.
- With new keywords and no file selected, the file is named after the first keyword
  (`keywords_<slug>.csv`) and written unconditionally. An existing file of that name is replaced.
- `serp_audit._resolve_output_names` reuses the `output_*` names in `config.yml` when the slug
  matches. That only works because the launcher writes fresh names first.

## Chunk C — call-level checkpoint and resume (`serp_audit.py`, new `serp_checkpoint.py`)

Approach: checkpoint at the one function every paid call goes through, `_fetch_serp_api`, rather
than per keyword. Each successful response is written to its own file as soon as it arrives. A
resumed run re-runs the audit from the start and takes any call it already has from disk instead
of paying for it again. This covers all nine callers with one mechanism and needs no change to
the keyword loop. `serp_audit.py` is at 2,181 of its 2,200-line limit, so the logic lives in a
new module.

| ID | Criterion | Test (`tests/test_serp_checkpoint.py`) |
|---|---|---|
| C1 | Every successful SerpAPI response is saved at once to `raw/<run_id>/calls/<seq>_<engine>_<query-slug>_<hash>.json`, written atomically. No response overwrites another. The API key is never in the file or its name. | `test_each_call_is_saved_under_its_own_name`, `test_api_key_is_not_stored`. |
| C2 | A failed call (error, timeout, `None`) is not saved, so a resume retries it. | `test_failed_call_is_not_checkpointed`. |
| C3 | With `SERP_RESUME_RUN_ID=<old run>` set, a call whose parameters match a stored response (API key excluded) returns the stored response, makes no network call, and does not count as a SerpAPI call. The hit is copied into the new run's folder, so a resumed run can itself be resumed. | `test_resume_reuses_stored_calls_and_fetches_the_rest` — fake client records calls. |
| C4 | Stored responses older than `serpapi.resume_max_age_hours` (default 24) are ignored and counted in the log. A missing or unreadable resume folder is an error with exit non-zero, not a silent full-price run. | `test_stale_checkpoints_are_ignored_and_counted`, `test_missing_resume_run_fails`. |
| C5 | The run prints "Reused N stored responses; made M new SerpAPI calls", and the output JSON's `fetch_summary` gains `resumed_from` and `reused_calls`. | `test_resume_counts_are_reported`. |
| C6 | Each run writes `raw/<run_id>/run_state.json` (`input_csv`, `started_at`, `status`): `running` at start, `complete` or `failed` from `finish_run` and the other exit paths. | `test_run_state_follows_the_run`. |
| C7 | `save_raw_json` stops overwriting: its files carry the same sequence number and query slug. | Existing `test_save_raw_json` updated. |

Launcher (`serp-me.py`, logic in `run_control.py` or a small sibling):

| ID | Criterion | Test |
|---|---|---|
| C8 | When Full Pipeline or Fetch SERPs is started and the newest run for the same keyword file is not `complete` and is inside the age limit, the launcher asks: "The last run for this file stopped after N stored responses, X minutes ago. Reuse them?" Yes sets `SERP_RESUME_RUN_ID` for the child. No runs fresh. | `test_resumable_run_is_found_for_the_same_keyword_file` (pure function over a tmp `raw/`); source check for the env var hand-off. |

Not in this chunk: a per-keyword `try` around the loop body. With C1–C3 a crash on keyword N
costs no credits (fix the cause, resume), and the `try` needs the 270-line loop body extracted
into a function first. Listed as adjacent.

## Chunk M — no writes before the run starts (`serp-me.py`, `serp_audit.py`, `pipeline_status.py`)

| ID | Criterion | Test (`tests/test_keyword_run_plan.py`) |
|---|---|---|
| M1 | Preparing a run is split into a plan (no writes) and an apply step. The plan is made first; every check that can cancel the run happens next; the apply step runs immediately before the process starts. A cancelled run changes no file. | `test_plan_writes_nothing` (pure function); Tk test: cancel at the feasibility prompt, keyword file and `config.yml` bytes unchanged. |
| M2 | The launcher no longer writes `files.output_*`. The audit always generates fresh timestamped names, and `finish_run` records them only after all outputs are written (already built). | `test_audit_output_names_are_always_fresh` (replaces the reuse case in `test_serp_audit.py`). |
| M3 | The launcher no longer writes `files.input_csv` before the run. It passes the keyword file to the child as `SERP_INPUT_CSV`; `serp_audit` reads that first and `config.yml` second. `finish_run` records `input_csv` together with the output paths. A stopped or failed run leaves `config.yml` byte-identical. | `test_input_csv_env_overrides_config`, `test_finish_run_records_input_csv`, `test_failed_run_leaves_config_untouched` (extends the existing test). |
| M4 | New keywords with no file selected: if `keywords_<slug>.csv` already exists with different contents, the launcher asks before touching it (see decision 3). It is never silently replaced. | `test_existing_keyword_file_is_not_overwritten`. |
| M5 | Adding keywords to a selected file still happens, but only at the apply step, and the log names the file and the keywords added. | `test_added_keywords_are_written_at_apply`. |

UI contract (ui-regression): no control added, removed, renamed or moved. New prompts: the
resume question (C8) and the existing-keyword-file question (M4).

## Decisions needed

1. **How resume is offered.** Recommended: the automatic question in C8, no new control. The
   alternative is a "Resume last run" checkbox beside Run.
2. **How old a stored response may be.** Recommended: 24 hours, in `config.yml`. SERPs change;
   a resumed run mixes results fetched at different times, and the output JSON will say so
   (`resumed_from`). Zero would mean "never reuse".
3. **Existing keyword file with the same name (M4).** Recommended: ask "keywords_x.csv already
   exists (N keywords). Add the new keywords to it?" with Yes / Cancel. The alternative is to
   write a new file with a numbered name.
4. **Old raw folders.** Stored responses add to `raw/` (10 MB for the 8 runs there now, and the
   INFO log already holds a copy of every response). Recommended: no automatic deletion in this
   change; listed as adjacent.

## Risks

- **Resume correctness.** A stored response is reused only when every request parameter except
  the API key matches. Changing the mode, location or page count between runs means those calls
  are fetched again. That is the intended behaviour and is what the tests pin down.
- **`no_cache`.** With `no_cache` on, the user asked for fresh results; a resume still reuses
  its own stored responses from the interrupted run, because they were fresh when fetched. The
  resume question will say how old they are.
- **M2 changes a tested behaviour.** `_resolve_output_names` reusing configured names has a test
  that asserts the old behaviour; it is replaced, not deleted. I will check
  `refresh_analysis_outputs.py` and `run_feasibility.py` do not rely on the old hand-off.

## Changes made after the review pass (C)

- A run that exits 0 with failed queries is recorded as `incomplete`, not `complete`, and is
  offered for resume. Before the fix it was not, so the fetched keywords were paid for twice.
- A stored response is not reused when its token follow-ups were unfinished (the AI Overview
  token has no stored follow-up, or the run stopped before the next ordinary call). Reusing it
  would send an expired token on every resume. Token expiry was not verified against the live
  API; the rule costs at most one repeated search per resume.
- A reused call is logged as "Served from run X (no SerpAPI call)".

Below medium, not fixed: `run_feasibility.py` pivot calls are not checkpointed; only the newest
run for a file is considered; rows from a reused response are stamped with the resumed run's
time; a resume folder where every file is stale warns and pays for everything; the launcher
env hand-off is checked by a source-string test.

## Order

C first (it protects money already spent), then M.

## Documents updated in the same commits

- `docs/USER_MANUAL.md` — resuming a run; what a cancelled run leaves behind (nothing).
- `docs/config_reference.md` — `serpapi.resume_max_age_hours`; `files.*` are now written by the
  audit at the end of a successful run, not by the launcher.
- `docs/methodology.md` — a resumed run mixes fetch times; `fetch_summary.resumed_from`.
- `docs/architecture.md` — new module(s). `docs/api_modes.md` only if it describes raw files.
- `CLAUDE.md` — test count; the "GUI auto-updates `config.yml` with the latest paths" line.

## Adjacent issues found, not fixed

- No per-keyword `try` in the audit loop: one parse error on keyword N still stops the run
  (recoverable for free by resume once this is built).
- `probe_ai_visibility.py` saves only after every engine finishes (the second half of M9).
- `raw/` is never pruned; `_fetch_serp_api` logs every full response at INFO.
- `sanitize_keyword_slug` names a keyword file after the first keyword only.
- DataForSEO and Moz calls are not checkpointed (Moz results are cached in `serp_data.db`).

## Not code-testable

The wording of the two prompts, and a resume after a real interrupted SerpAPI run. I can
exercise the second with the Stop button and a small keyword file if you want it checked with
real calls; that spends credits, so I will not do it unasked.
