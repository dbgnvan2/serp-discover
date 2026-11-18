# Review chunk Y8 — a bug is not a dead network

From the adjacent list of chunk Y7's cold review. The paid SerpAPI fetch loop
treats every exception the same way, so a programming error is retried with
paid calls and then filed as a failed fetch.

## Findings

1. **`serp_audit._fetch_serp_api` wraps the whole attempt body in
   `except Exception` (P40/P2, medium).** The body includes
   `serp_checkpoint.save(params, results)` and
   `link_recovery.recover_response(results)`, which run *after* a successful,
   already-paid response. A `TypeError` or `KeyError` in either is logged as
   `Fetch error (attempt N)`, retried with up to two more **paid** SerpAPI
   calls that will fail the same way, and then returns `None`: the keyword
   continues with no SERP data, counted under "Fetched N of M queries"
   alongside genuine network failures, with nothing in the output saying a bug
   rather than a dead host caused it. Three paid calls and no data for a fault
   that retrying cannot change (P1 in reverse — a terminal failure given a
   retryable state).
2. **The post-response work runs inside the retry loop at all.** Even without
   an exception, placing the checkpoint write and the link recovery inside the
   `try` means a second attempt re-runs work the first attempt completed.
3. **`config_manager` lets the GUI save a retry budget the loader refuses
   (P2, low).** `_render_field` builds the Spinbox with `from_=0`, so
   `attempts: 0` can be saved; the loader reports it and uses the default, to
   a log the GUI operator never reads. The GUI is where this value is edited,
   so that is where it has to be said.
4. **`run_gsc_analysis.build_sidecar` records no thresholds (P6, low).** The
   markdown names the thresholds the run used; the machine-readable sidecar
   beside it names none, so two artifacts of the same run carry different
   provenance and a consumer reading the sidecar cannot tell which bands
   produced the medians.

## Out of scope

- The ~50 `with sqlite3.connect(...)` sites that commit but never close the
  handle. One sweep across every module that touches the database, with its
  own guard; its own chunk.
- A `config_manager` tab for the editorial keys added in Y1–Y6.

## The fixes

1. The fetch loop catches the transport errors by name —
   `requests.RequestException`, the SerpAPI client's own
   `SerpApiClientException`, and the JSON/value errors a malformed body
   raises — and retries those. Anything else is logged as an internal error,
   **not retried**, and reported as its own fetch outcome, so a bug spends one
   paid call rather than three and is named as a bug.
2. The checkpoint write and the link recovery move after the loop, so they run
   once, on the response that succeeded.
3. The Spinbox floor for a retry budget is 1, and the help text says what the
   loader does with less.
4. The sidecar records the thresholds the run applied, from the same mapping
   the markdown reads.

## Guards (one per finding)

- A `serp_checkpoint.save` that raises spends exactly one SerpAPI call, is
  logged as an internal error rather than a fetch error, and does not report a
  network failure.
- A transport error is still retried to the configured budget.
- The checkpoint write and the link recovery each run exactly once for a
  response that needed two attempts.
- The GUI cannot save a retry budget the loader refuses.
- The sidecar names the same thresholds the markdown does.

## What was built

- **`serp_fetch.py` (new, 230 lines)** — the fetch loop, moved out of
  `serp_audit`, which was at its 2200-line ceiling. `fetch(params, *,
  timeout_seconds, client=None, available=None)` keeps the resume lookup, the
  retry budget from `http_retry`, and the post-response work. It catches
  `SERPAPI_TRANSPORT_ERRORS` — `requests.RequestException`, the client's own
  `SerpApiClientException`, `json.JSONDecodeError`, `OSError` — and retries
  those; anything else is logged with `logging.exception` as `INTERNAL ERROR
  … not retried — this is a fault in the tool, not the network` and returns
  `None` after one paid call. `CALL_COUNT` and `call_count()` live here, with
  the loop that increments them.
- The checkpoint write and the link recovery run **after** the loop, once, on
  the response that succeeded. A fault in either is logged as an internal
  error and the keyword is reported as failed, rather than aborting a run
  whose other keywords are already fetched — a judgement, recorded here: the
  response is real and the checkpoint is a resume optimisation, but a
  half-recovered body is not something to pass downstream.
- `serp_audit._fetch_serp_api` is a six-line wrapper passing its own client,
  availability flag and timeout, so a caller that has replaced any of them on
  `serp_audit` is still honoured.
- `config_tab_models.positive_only_fields()` reads the loaders' own tables
  (`http_retry.BUDGET_SOURCES`, `http_retry.TIMEOUT_SOURCES`,
  `timeouts.GOVERNED_FIELDS`) and `merge_settings_edits` **refuses** a zero or
  negative value for those nine fields: the field keeps its loaded value and
  Save All reports `must be greater than zero`. The numeric Spinbox floor is 1
  (0.1 for a float) for the same fields, which is cosmetic — `from_=` binds the
  spin arrows only — so the refusal is in the save path, where the typed text
  is read. It lives in `config_tab_models` rather than `config_manager`
  because that is where the save path is and it needs no tkinter.
- `run_gsc_analysis.build_sidecar` records `thresholds`, from the mapping the
  run applied.
- `tests/test_y8_a_bug_is_not_a_dead_network.py` — 16 tests. Three
  pre-existing source-text guards over `_fetch_serp_api`
  (`tests/test_link_recovery_wiring.py`, `tests/test_link_recovery_followup.py`)
  became consequence tests over `serp_fetch.fetch`: a wrapped link is
  recovered on both the fresh and the resume path, the checkpoint keeps the
  raw body, and a settled API error spends one paid call while a transient one
  spends the budget (P27 — the third chunk in a row where a source guard broke
  on a behaviour-preserving move).

## Verification

- Full suite: **EXIT=0**, 2161 passed, 68 skipped, 46 subtests passed.
- Mutation gate: `scratchpad/mutate_y8.py`, 15 mutations, **all caught, none
  vacuous**. Two things in the diff are behaviourally inert in production and
  are recorded as such rather than mutated:
  - the Spinbox floors (`from_=1` / `from_=0.1`): `ttk.Spinbox(from_=...)`
    constrains the spin arrows, and the save path reads the variable's text, so
    the floor cannot refuse a typed value. They stay as the first thing an
    operator sees; the refusal itself is mutated and caught.
  - `thresholds=_thresholds` at the `build_sidecar` call: the function falls
    back to the mapping the run applied, set from the same config. The argument
    stays because reading process state is what chunk Y7 moved away from, and
    the criterion — one run's two artifacts name the same thresholds — has its
    own guard (`test_a_real_run_writes_the_same_thresholds_to_both_artifacts`),
    which runs `run_analysis` and compares both.
- Effort tier: **Full** — this changes which failures are retried on a paid
  call. Production: a 177-line new module, ~105 lines removed from
  `serp_audit.py` (now 2150, under the ceiling), 25 changed lines in
  `config_manager.py` and `run_gsc_analysis.py`. Tests: 220 new lines plus 110
  rewritten (≈1.6x). Doc prose: 18 lines (0.1x).


## Cold review of this chunk

A cold `learning-qa` pass over the diff returned 10 findings. The reviewer
verified as sound: the resume path, the save-before-recover order, the
`results = None` that stops an error payload reaching the checkpoint, the
sleep placement, the single home for the call counter, the
`client=` / `available=` injection that keeps `serp_audit`'s patched globals
in force, and `SERPAPI_TRANSPORT_ERRORS` matching what the installed vendor
client actually raises.

Fixed, each with a guard:

- **F1 · medium** — one `try` covered both post-response calls, so a fault in
  the checkpoint write discarded a paid response. They are two events and are
  handled as two: a failed write is logged and the response is still returned;
  a failed link recovery drops the response, because a half-recovered body
  makes google.com the competitor (P1).
- **F2 · medium** — the fetch returned `None` for six different outcomes and
  the failure record said "network/transport failure" for all of them.
  `fetch_with_status` now returns a `STATUS_*` constant, `status_text()` turns
  it into the row's `reason`, and `query_metadata` carries it (P1 — a bug in
  this tool was being filed as a dead network).
- **F3 · medium** — the Spinbox floor was decoration. The refusal is in
  `merge_settings_edits`, so Save All reports `must be greater than zero` and
  the field keeps its loaded value. Before this, a typed `0` for
  `serpapi.retry_max_attempts` saved with `errors: []`, and the loader's
  report went to a log the GUI operator never reads (P2).
- **F4 · medium** — `serpapi.timeout_seconds` is refused at zero by
  `timeouts.seconds_from_config` and was in neither retry table, so the first
  population of the positive-only set missed the one value this chunk passes
  into `serp_fetch.fetch` (P5). `timeouts.GOVERNED_FIELDS` names it, read the
  same way as the other two tables.
- **F5 · low** — `json.dumps(..., default=str)`, so a value the logger cannot
  serialise cannot discard a paid response.
- **F6 · low** — the `SerpApiClientException` import stand-in warns when the
  client is installed but the exception is missing: a narrowed retry policy
  must not be silent.
- **F7 · low** — the guard on the Spinbox floor tested
  `hasattr(config_manager, "ConfigManager")`, which is False (the class is
  `ConfigManagerWindow`), so it ASTed the whole module and pinned the floor
  expression's text (P27). Replaced by the consequence: every positive-only
  field refuses a typed `0` and `-1`, a positive value still saves, and a
  field outside the set may still be zero.
- **F8 · low** — `test_serp_audit.py` still assigned
  `serp_audit.SERPAPI_CALL_COUNT`, creating an attribute nothing reads.
  Deleted; `docs/serp_audit_split_plan_20260501.md` now records that the
  counter and the two retry constants moved.
- **F9 · low** — `dict(thresholds or active_sponge_thresholds())` filed the
  applied defaults under the name of a caller that had explicitly passed an
  empty mapping. `thresholds if thresholds is not None else ...`, with a guard.
- **F10 · low** — a non-positive attempt budget logs before returning
  `STATUS_NO_BUDGET`, rather than returning as if no call had been attempted.

Not a finding, recorded: `serp_fetch` keeps its own `GoogleSearch` /
`SERPAPI_AVAILABLE` import guard while `serp_audit` always passes both, so the
same fact lives in two modules. Harmless today — the injected values win — and
left alone rather than widening the diff.

## Adjacent issues found, not fixed

- `serp_audit.py` has ~50 `with sqlite3.connect(...)` sites that commit but
  never close the connection.
- No `config_manager` tab exists for the editorial keys added by chunks Y1–Y6,
  so they can only be edited by hand.
- Untracked `keyword_enrich.py` is a sixth entry point that loads no config and
  so applies none of the policy the other five apply at startup.
