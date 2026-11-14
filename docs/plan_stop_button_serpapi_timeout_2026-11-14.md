# Plan: Stop button / run guard, and SerpAPI timeout

**Status:** approved 2026-11-14 with the three recommended decisions. Chunk T built; Chunk S in progress.
**Source:** `docs/REVIEW-serp-discover-2026-11-14.md` findings M8 and M2.
**Tier (effort-budget):** Full — external paid calls and a GUI control that starts and kills
processes. Tests for the change, one cold `learning-qa` pass over each diff before pushing.
**Branch:** current (`fix/gui-model-robustness`), two commits, pushed one at a time.

## What the code does now

- `serp_audit._fetch_serp_api` (line 354) builds `GoogleSearch(params)`. The client's default
  timeout is 60,000 seconds (16.7 hours) and `GoogleSearch.__init__` takes no timeout argument, so
  it has to be set as an attribute. A stalled connection never raises, so the retry loop never runs.
- `serp-me.py` `on_select` (line 491) sets the Run button to normal on any list click, including
  during a run. There is no running flag, so a second click starts a second pipeline.
- The child is started with `subprocess.Popen` (line 948) and the handle is a local variable.
  Nothing can stop it. Closing the launcher leaves it running and spending credits.
- `run_pipeline.py` starts `serp_audit.py` as its own child, so killing only the launcher's child
  would leave the audit running.

## Chunk T — SerpAPI timeout (`serp_audit.py`, `run_feasibility.py`)

| ID | Criterion | Test (`tests/test_serpapi_timeout.py`) |
|---|---|---|
| T1 | Every `GoogleSearch` call has a timeout read from `config.yml` `serpapi.timeout_seconds` (default 60). | `test_search_is_given_the_configured_timeout` — fake `GoogleSearch` records `.timeout` at `get_dict()`. |
| T2 | A timeout is retried by the existing loop, logged with the attempt number, and after the last attempt the query is reported as failed (it then lands in `fetch_summary.failed`). | `test_timeout_is_retried_then_reported_failed` — fake raises `requests.Timeout`; assert attempt count and `None`. |
| T3 | A missing, zero or non-numeric config value falls back to the default with one warning; it never means "no timeout". | `test_bad_timeout_config_falls_back_to_default`. |
| T4 | Siblings: the two `requests.get(..., timeout=15)` SerpAPI calls in `run_feasibility.py` read the same config key instead of a literal. | `test_feasibility_serpapi_calls_use_the_configured_timeout`. |

Docs: `docs/config_reference.md` (new key), `config.yml` (key with a comment), `docs/USER_MANUAL.md`
Troubleshooting entry "SerpAPI rate limited or timed out" (it will now be true that a stall ends).
`docs/methodology.md`: no described behaviour changes.

Line budget: `serp_audit.py` is 2,177 of 2,200 lines; T1–T3 add about 6.

## Chunk S — run guard and Stop button (`serp-me.py`, new `run_control.py`)

Approach: the process logic goes in a small module with no tkinter (`run_control.py`) so it is
tested with real short-lived child processes. The launcher holds one `RunControl` object and the
buttons read their state from it.

| ID | Criterion | Test (`tests/test_run_control.py`) |
|---|---|---|
| S1 | While a run is active, Run is disabled and stays disabled when the list selection changes. A second start request is refused. | `test_second_start_is_refused_while_running`; source check that `on_select` asks the run state before enabling. |
| S2 | Run is disabled before the child is started (house rule), and re-enabled only when the child has exited. | `test_state_is_running_before_the_process_starts`. |
| S3 | A "Stop" button next to Run, enabled only during a run. Stop asks for confirmation, then terminates the whole process group (SIGTERM, then SIGKILL after a grace period from config). | `test_stop_kills_the_child_and_its_own_child` — a real parent that spawns a real grandchild; both gone after stop. |
| S4 | A stopped run is labelled "STOPPED" in the log, not "FAILED (exit -15)", and none of the after-success actions run. | `test_exit_label_for_a_stopped_run`. |
| S5 | Closing the launcher during a run asks "Stop the run and close?". Yes stops the group and closes; No keeps the window open. | `test_close_request_while_running_needs_a_decision` (pure function); source check that `WM_DELETE_WINDOW` is bound. |
| S6 | On launcher start, a `pgrep` check for an already-running pipeline script from this folder disables Run and says so in the log, with a "Check again" path when the selection changes. The `pgrep` call has a timeout. | `test_detects_a_pipeline_started_elsewhere` — real child with a matching command line. |
| S7 | Sibling: the blocking `subprocess.run` that regenerates the report after feasibility (`serp-me.py:1117`) gets a timeout from config and reports a timeout as a failure. | `test_regenerate_timeout_is_reported`. |

A stopped audit writes no outputs and leaves `config.yml` paths alone: `finish_run` only runs at
the end. Raw responses already saved under `raw/<run_id>/` stay on disk.

UI contract (ui-regression): one control added (Stop, beside Run). Nothing removed, renamed or
moved. New prompts: stop confirmation, close-while-running.

Platform: process groups use `start_new_session` and `os.killpg`, which are POSIX only. Both of
your machines are Macs. On Windows the Stop button would fall back to terminating the direct
child and say so in the log.

## Decisions needed

1. **SerpAPI timeout default.** Recommended: 60 seconds per call, in `config.yml`. I have no
   measurement of how long your slowest real calls take; the raw logs under `raw/` would show it,
   and I will check them before fixing the default.
2. **Hard cap on a whole run.** Your `external-api.md` E1 says every subprocess call has a
   timeout. Recommended: add `launcher.max_run_minutes`, default `0` (off), because I do not know
   how long a Deep Research run takes and a wrong cap kills a paid run part-way. With the
   per-call timeout and the Stop button, a hung run can no longer last for hours unseen. The
   alternative is a default cap (for example 120 minutes).
3. **Closing the window during a run.** Recommended: the two-way prompt in S5. The alternative
   is a third choice, "close and let it finish", which keeps today's orphan behaviour on purpose.

## Checked during the build

- **Call times.** 296 calls in `raw/*/serp_api.log`: median 2.1s, 95th percentile 12.7s, slowest
  30.3s. The 60s default is twice the slowest. The old 15s literal in `run_feasibility.py` was
  below the 99th percentile (27s).
- **Billing after a timeout.** SerpAPI's pricing page says cached, errored and failed searches
  are not counted. Its API pages do not say what happens when the client gives up first. Its CLI
  page says a timed-out search "may still finish on SerpApi's side, count against your searches".
  So a retry after a timeout can cost a second credit unless the first attempt finished and the
  retry is served from the one-hour cache (not available when `no_cache` is on).
- **Review pass (T):** retry-loop errors are now scrubbed of the API key; a test runs the real
  client to prove `.timeout` reaches `requests`.

## Order

T first (small, independent), then S.

## Adjacent issues found, not fixed

- `run_pipeline.run_command` has no per-step timeout (covered only if decision 2 adds the cap).
- `keyword_enrich.py` (untracked work in progress) calls SerpAPI directly with a literal
  `timeout=15`; not touched.
- The Anthropic clients in `brief_llm.py` and `probe_ai_visibility.py` are built with no explicit
  timeout (the SDK default applies).
- `timeouts.py` has no upper bound, so `timeout_seconds: 60000` would be accepted.
- `_fetch_serp_api` retries on every exception type, including ones that cannot succeed
  (for example a JSON decode error). E5 says permanent errors are not retried.
- `_fetch_serp_api` logs the full API response at INFO on every call.
- Keyword files and `config.yml` are written before a run is validated (M3); no checkpoint or
  resume (M9).

## Not code-testable

The Stop button's placement and the wording of the two prompts need a look in the running GUI.
The process-group kill is tested with stand-in processes, not with a real SerpAPI run.
