# Chunk Y7 — one retry budget, validated the same way

Adjacent issue carried since chunk Y4 and logged again by Y5 and Y6: this tool
has **two** retry budgets. `http_retry` owns the policy for every `requests`
call — DA providers, Moz, Search Console, the LLM engines, the ranked-page
fetch — and `serpapi.retry_max_attempts` / `serpapi.retry_backoff_seconds`
own `serp_audit`'s own loop around the SerpAPI client, which is a different
transport with its own error payload. Two policies is defensible; two
policies that behave differently when the operator gets a value wrong, with
only one of them explained in the GUI, is not.

## The findings

1. **The SerpAPI budget is read at import with bare `int()` / `float()`
   (`serp_audit.py:143-144`), so a value that is not a number aborts the run
   with a traceback and a negative backoff raises mid-run.** Reproduced
   against `{"serpapi": {"retry_max_attempts": "lots",
   "retry_backoff_seconds": -5}}`:

   ```
   attempts RAISED: ValueError invalid literal for int() with base 10: 'lots'
   backoff: -5.0 -> first sleep: -5.0
   ```

   `time.sleep(-5.0)` raises `ValueError`, and it raises *after* the first
   SerpAPI call has been paid for. The same two kinds of value against
   `http_retry`:

   ```
   WARNING http_retry.attempts is 'lots', which is not a number; using the
           documented default 2.
   WARNING http_retry.backoff_seconds is -5, which is -5.0 as a retry policy;
           zero or less makes every transient failure terminal (P1). Using
           the documented default 1.0.
   policy: {'attempts': 2, 'backoff': 1.0}
   ```

   The sibling key in the same config block, `serpapi.timeout_seconds`, is
   validated too — it goes through `timeouts.seconds_from_config`. Only the
   two retry-budget keys skip the validator the repo already owns (P4/P32).

2. **The two budgets have different defaults and nothing records why.**
   SerpAPI: 3 attempts, 1.0s backoff. `http_retry`: 2 attempts, 1.0s. A paid
   call may well be worth one more attempt than a free DA lookup, but that is
   an editorial judgement nobody wrote down, so the pair reads as drift.

3. **The GUI explains one half of the pair.** `config_manager.py` carries help
   text for `serpapi.retry_max_attempts` and `serpapi.retry_backoff_seconds`
   and says nothing about `http_retry.*`, so the policy governing every
   outbound call except the SERP fetch is invisible to the operator who is
   given a field for the one that is not.

4. **`run_gsc_analysis.main` resolves the sponge thresholds a second time**
   and passes all five explicitly, so `_ACTIVE_SPONGE_THRESHOLDS` — the
   mechanism chunk Y6 added — has no production reader. Two live mappings of
   the same config keys in one process is the shape that lets them diverge.
   (Logged as finding 8 of Y6's cold review.)

## Out of scope

- **Merging the two retry loops.** `serp_audit`'s loop reads SerpAPI's error
  payload and classifies quota, auth and bad-parameter errors as
  non-retryable; `http_retry`'s wraps `requests` and reads status codes.
  One loop for both transports is a rewrite, not a fix.
- **A `config_manager` tab for the editorial keys added in Y1–Y6.** Help text
  for existing fields is an entry in a dict; a new tab needs its own
  initialisation-order guard and is its own chunk.

## The fixes

1. The SerpAPI retry budget is resolved through `http_retry`, beside the one
   it is a sibling of, with the same validation, the same warnings and the
   same documented defaults — `http_retry.serpapi_retry_attempts()` and
   `serpapi_retry_backoff()`, read as functions at the call site so
   `apply_retry_policy` reaches them (the Y4 default-argument trap).
2. `config.yml` records why the SerpAPI budget may differ from the shared one.
3. `config_manager.py` gains help text for the four `http_retry` keys.
4. `run_gsc_analysis.main` drops its explicit threshold arguments, so one
   path is exercised.

## Guards (one per finding)

- A non-numeric `serpapi.retry_max_attempts` warns and uses the documented
  default instead of raising, and the warning names the key.
- A zero or negative `serpapi.retry_backoff_seconds` never reaches
  `time.sleep`.
- The SerpAPI budget is applied after import and reaches the fetch loop.
- Every `http_retry` and `serpapi` retry key the config carries has GUI help
  text.
- `main` passes no threshold the active mapping already holds, and a value
  applied before `main` runs reaches the sponge comparison.

## What was built

- `http_retry.py` — `DEFAULT_RETRY_POLICY` gained `serpapi_attempts: 3` /
  `serpapi_backoff: 1.0` with the editorial reason recorded beside them.
  `BUDGET_SOURCES` names both config blocks and the inline validation became
  `_read_budget(section, section_name, keys, out)`, so one rule reads both and
  the warnings name whichever key was wrong. `serpapi_retry_attempts()` and
  `serpapi_retry_backoff()` are functions; `apply_retry_policy` rebinds the
  two globals behind them.
- `serp_audit.py` — the module constants `RETRY_MAX_ATTEMPTS` /
  `RETRY_BACKOFF_SECONDS` are gone. The fetch loop asks for the budget at call
  time, so a config applied after import reaches it.
- `config.yml` — a comment under the two serpapi keys saying they are read and
  validated by `http_retry` and why this budget is one attempt longer.
- `config_manager.py` — help text for `http_retry.attempts`,
  `backoff_seconds`, `max_retry_after_seconds` and `timeout_seconds`, and the
  two serpapi entries now say how the two budgets relate.
- `run_gsc_analysis.py` — `run_analysis` applies this run's `gsc` block once
  (`apply_sponge_thresholds(config)`) and passes none of the five values on,
  so the mapping the two helpers read when an argument is omitted is the one
  the run holds. Resolved from the config argument, not from process state, so
  a caller that has not been through `_load_config` still gets its own numbers
  (P28). `generate_report`'s fallback still reads the config it was handed.
- `tests/test_y7_one_retry_budget.py` — 13 tests, one or more per finding.
  `tests/test_serp_checkpoint.py` and `tests/test_serpapi_timeout.py` patch
  `http_retry.SERPAPI_RETRY_ATTEMPTS` instead of the removed constant;
  `tests/test_y4_config_not_constants.py`'s "the resolved bands reach the
  comparison" guard now checks the applied mapping and that the run passes
  nothing explicitly, which is the same criterion under the new shape.

## Verification

- Full suite: `python3 -m pytest test_*.py tests/ -q` → **EXIT=0**, 2139
  passed, 68 skipped, 16 subtests passed.
- Mutation gate: `scratchpad/mutate_y7.py`, 12 mutations, all caught, none
  vacuous. Each reverts one production change — the serpapi block leaving
  `BUDGET_SOURCES`, the `<= 0` check, the cast's `except`, the non-dict
  section check, `apply_retry_policy` not rebinding, the fetch loop reading a
  frozen default, the sleep ignoring the configured backoff, each new GUI help
  entry, the run resolving without applying, and the run passing the five
  thresholds explicitly as well.
- Effort tier: **Full** — this changes the retry behaviour of the paid fetch
  loop, which can lose a run's data. Production: 94 changed lines in
  `http_retry.py`, 23 in `run_gsc_analysis.py`, 15 in `serp_audit.py`, 11 in
  `config_manager.py` (≈100 net added). Tests: 215 lines (≈2.1x, at the
  ceiling for a fix batch with one guard per finding). Doc prose: 25 lines
  (0.25x, under the 0.3x ceiling).

## Cold review of this chunk (learning-qa, P1–P45)

Seven findings, none high, three medium. Every medium-or-higher one is fixed
with a guard; the two low findings that were judgements rather than defects are
recorded below.

1. **MEDIUM — the new GUI help text misstated both retry semantics.** It said
   "how many times to retry" of `attempts`, which is the *total* number of
   tries (`range(1, attempts + 1)` in both loops), so an operator wanting one
   retry on the paid SERP fetch would set `1` and get no retry at all (P1); and
   it said the shared `backoff_seconds` "doubles", which is true only of the
   SerpAPI loop (`backoff * 2 ** (attempt - 1)`) and not of `http_retry`
   (`backoff * attempt`, linear). Fixed: both entries state total tries and
   name the growth, and `docs/config_reference.md` says the same.
2. **MEDIUM — the help-text guard proved length, not meaning.** Any 21
   characters passed it, so it could not fail for finding 1, and it hardcoded
   six key paths, so a seventh key would pass by silence (P21/P27). Fixed: the
   paths are derived from `http_retry.BUDGET_SOURCES` and `TIMEOUT_SOURCES`,
   and two further guards assert the load-bearing wording. Deriving the paths
   immediately found two more keys with no help text at all
   (`ai_visibility.timeout_seconds`, and `enrichment.timeout_seconds` had only
   a one-line restatement of its own name).
3. **MEDIUM — a production call now writes process state and the test that
   makes it had no cleanup.** `run_analysis` applies the thresholds, and
   `tests/test_y4_config_not_constants.py`'s `run_analysis` case left
   `min_bucket_size: 9` and `position_bands: [[2,7]]` applied for every later
   test that omits a threshold argument; the suite was green only on
   collection order (P28/P34). Fixed: the class restores the mapping, and
   `TestNoTestLeavesTheThresholdsApplied` runs that case and checks the
   process is as it was.
4. **LOW — the Y7 cleanup restored the documented defaults, not the process.**
   `apply_retry_policy(None)` resets all eight globals to
   `DEFAULT_RETRY_POLICY`, which equals the live `config.yml` only by
   coincidence. Fixed: `_restore_policy` snapshots the eight globals and puts
   them back.
5. **LOW — "one rule for both budgets" still had two block-level rules, and
   one dropped a configured block in silence.** `http_retry` was read as
   `cfg.get("http_retry") or {}`, so a block mangled to `0`, `""` or empty was
   replaced by the defaults with no warning while `serpapi: 0` warned (P2/P9).
   Fixed: both sections are read the same way, with separate warnings for
   "present and not a block" and "empty".
6. **A duplicate dict key, found while fixing finding 2.** Adding
   `enrichment.timeout_seconds` to the help table while a vaguer entry for the
   same key sat thirteen lines below produced a literal with the key twice,
   where the later one silently wins. Fixed, and
   `TestTheHelpTableHasNoDuplicateKeys` walks every dict literal in
   `config_manager.py` for the class.

### Recorded, not changed

- **LOW — `generate_report`'s threshold fallback is now a test-only path.**
  `run_analysis` always passes `thresholds=`, so the `resolve_sponge_thresholds`
  fallbacks are unreachable in production. Left in place, with a comment saying
  they are for a direct caller (a script rendering a report from stored rows),
  because deleting them would make the function unusable without a run.
- **LOW — the sleep patch in two guards is process-wide.**
  `mock.patch.object(serp_audit.time, "sleep", …)` sets the attribute on the
  shared stdlib module for the duration of the block. Restored on exit;
  narrowing it means adding a `serp_audit`-level indirection for a test's sake.

## Adjacent issues found, not fixed

- **`serp_audit.py:415-423` — `except Exception` wraps the whole attempt body,
  including `serp_checkpoint.save` and `link_recovery.recover_response`
  (P40/P2, medium if it fires).** A programming error in either is logged as
  "Fetch error (attempt N)", retried with up to two more **paid** SerpAPI
  calls, and then returns `None`, so the keyword continues with no SERP data
  and no signal distinguishing a bug from a dead network. The fix is to catch
  `requests.RequestException` plus the SerpAPI client's own errors by name and
  move the checkpoint and recovery calls after the `try`. Its own chunk,
  because it changes which failures are retried on a paid call.
- **`config_manager.py` `_render_field` Spinbox `from_=0` (P2, low).** The GUI
  lets the operator save `attempts: 0`; the loader refuses it and warns to a
  log the GUI operator never reads. The widget should refuse the value or echo
  the fallback.
- **`run_gsc_analysis.build_sidecar` (P6, low).** The markdown names the
  thresholds the run used; the machine-readable sidecar records none, so two
  artifacts of the same run differ in provenance.
- Still open from earlier chunks: no `config_manager` tab for the editorial
  keys added in Y1–Y6; ~50 `with sqlite3.connect(...)` sites that commit but
  never close; untracked `keyword_enrich.py` as a sixth entry point that loads
  no config and applies no policy.
