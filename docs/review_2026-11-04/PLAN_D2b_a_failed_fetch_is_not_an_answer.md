# D2b — a failed fetch is not an answer

**Chunk:** D2b of review chunk D2 (`REVIEW_WORKPLAN_2026-11-04.md`).
**Findings:** D-C-02 (S1, GSC transient failure cached as `found=0`),
D-C-10 (S2, Moz competitor block with one failed sub-call cached 30 days
as `ok`).
**Sits after:** D2a (`PLAN_D2_null_is_not_zero.md`, commit `9784690`).
**Effort tier:** Full — data path plus external calls, two caches, two
providers.

---

## The one fault

D2a fixed *absence written down as zero*. This is its sibling: **failure
written down as absence**. Both caches record what the provider said; neither
records whether the provider answered. A call that failed and a call that
answered "nothing here" produce the same cache row, so the failure is served
back as a measurement for the rest of the TTL — and the TTL is the window in
which a retry would have fixed it.

Both probes confirm it live, today, against the current code.

### D-C-02 — a GSC outage becomes a fact about the client's traffic

`probes/discover/probe_04_gsc_failure_cached_absent.py`:

```
GSC 503 error: {'error': 'backend'}
after 503: {} | posts: 1
cache rows now: [('couples counselling', 0, None), ('family therapy', 0, None)]
retry while API is healthy: {} | posts made: 0
report line: - Queries with no GSC data: 1 (no impressions recorded —
             reported as absent, not as zero)
```

`gsc_client._fetch_all_rows` logs the error and `break`s out of the
pagination loop, returning whatever it has — `{}` on a first-page failure.
`get_query_stats` cannot tell that from "the property has no rows for these
queries", so `_cache_store` writes `found=0` for every query in `to_fetch`,
which `_cache_lookup` then serves as a *resolved absence* for
`gsc.cache_ttl_days` (7). A retry inside the TTL makes **zero** requests.

Three things follow from the same break:

1. **A mid-pagination failure truncates silently.** A failure on page 3
   returns pages 1–2, and every query not in them is cached as absent. There
   is no partial state: the function's return type cannot express "these rows,
   and there are more I could not reach".
2. **The report states it as a finding about the client.** "no impressions
   recorded — reported as absent, not as zero" is the honest sentence for a
   real absence and a false one for an outage. So is the sidecar's
   `queries_with_data: 0`, which `_build_gsc_summary` feeds to the brief's LLM
   prompt as the client's private first-party data.
3. **A partial fetch can still write a trend point.** `gsc_demand` already
   refuses to persist a score when `data_available` is false (no tracked rows
   or no clicks) — that guard holds and is not the gap. The gap is a *partial*
   fetch: some queries found, clicks non-zero, so `data_available` is true and
   `branded_click_share` is computed over a truncated denominator and stored
   as that run's real measurement. `get_demand_trend` then compares it with
   complete runs.

### D-C-10 — one failed sub-call freezes a competitor for 30 days

`probes/discover/probe_05_moz_competitor_cache.py` part B:

```
Moz data.site.anchor.text.list failed for 'bowencenter.org': Moz API HTTP 503
(B) first fetch: status=ok data_available=True anchor_texts.status=error (calls=2)
    cached row status: [('ok', '{"status": "error", "items": [], ...}')]
    second run (API now healthy): calls made = 0 |
    served anchor_texts.status = error | items = []
```

`_fetch_one` sets the block's **top-level** status to `ok` when *any* sub-call
returned data. Each sub-block keeps its own status, so nothing is lost at the
point of fetch — but `_cache_store` gates on the top-level status, so the
whole domain is cached for `cache_ttl_days` (30) with a permanently failed
`anchor_texts`. `_cache_lookup`'s `if status != STATUS_OK: continue` ("never
serve a cached failure") never fires, because the status is `ok`. The failed
sub-call is not retried for a month.

What a consumer sees meanwhile: `anchor_texts: {items: [], returned: 0,
truncated: false}` — which reads as "this competitor has no anchor text", a
claim about their backlink profile, from a 503.

---

## What this chunk changes

Two rules, one per provider, and nothing else:

1. **A fetch that did not complete says so, and an incomplete fetch is never
   cached as an absence.**
2. **Caching is per sub-call, not per domain:** the sub-calls that succeeded
   are kept, the one that failed is asked again next run.

### Not in scope

- D-C-08 (`www.` normalisation), D-C-20 (error pages enriched), D-C-21
  (`AI_Overview_Mode`) — those are **D2c**.
- The GSC `found=0` *sentinel itself* stays. It is correct for a real absence
  and it is what stops a re-pull of a query the property genuinely has no rows
  for. Only its provenance changes.
- Re-running the owner's existing GSC analyses. Any `gsc_analysis_*` sidecar
  produced during an outage holds fabricated absences; that is **owner work**,
  recorded at the end.

---

## Acceptance criteria

Each is one testable statement. `D2b.n` is the reference a docstring or test
name carries.

### GSC (D-C-02)

- **D2b.1** `gsc_client._fetch_all_rows` returns `(rows, complete)`.
  `complete` is `False` when any page failed at the network layer, returned a
  non-OK status, or returned non-JSON — and `True` only when the loop ended
  on a short page. The rows it did reach are still returned.
- **D2b.2** `get_query_stats` writes `found=0` **only** when `complete` is
  `True`. On an incomplete fetch the queries it could not resolve are left out
  of the cache entirely, so the next call re-asks them.
- **D2b.3** `get_query_stats` reports completeness to its caller. (Shape: a
  `GscStats` NamedTuple `(stats, complete, asked, measured)`, by the same
  argument as `URLWindow` in D2a — the coverage travels with the figures
  rather than being recomputed by each consumer. Existing callers are updated;
  there is one.)
- **D2b.4** A query the fetch could not reach is distinguished from one GSC
  holds no row for. `found: False` is not enough: rows carry
  `gsc_status` of `measured_absent` | `not_reached`, and the three-state
  vocabulary lives in config, not in Python literals (CLAUDE.md editorial
  rule), alongside D2a's `feasibility_messages.yml` precedent.
- **D2b.5** `run_gsc_analysis.run_analysis` states the failure. The log line
  "GSC returned data for N of M queries" is replaced by one that separates
  measured absence from unreached, and the report's "Queries with no GSC data"
  line does not claim "no impressions recorded" for a query that was never
  reached. The per-query table cell reads `not reached` rather than
  `no GSC data`.
- **D2b.6** `build_sidecar` carries `fetch_complete`, `queries_not_reached`
  and the per-query status, and `_build_gsc_summary` passes them to the brief
  payload — so the LLM cannot read an outage as the client having no search
  traffic.
- **D2b.7** `gsc_demand.save_demand` writes no score point from an incomplete
  fetch. `compute_demand`'s `data_available` gains the completeness term, and
  `score` records which it was, so a trend never mixes a truncated run with
  complete ones.
- **D2b.8** The sponge effect and the reformat candidates are computed only
  over reached queries, and both report the denominator they used (P2). A
  band that would have had enough rows but for unreached queries says so
  rather than reporting "insufficient data" as a property of the client's
  traffic.

### Moz competitor (D-C-10)

- **D2b.9** `_cache_store` stores a domain's block only when **every enabled**
  sub-call is `ok` or `no_record`. A sub-call turned off by config
  (`brand_authority`, `link_momentum`) does not make a block partial.
- **D2b.10** A partially successful domain is still cached, per sub-call: the
  `ok`/`no_record` sub-blocks are written with their own `fetched_at`, and the
  failed one is absent from the cache row. The cache table gains a per-signal
  status so this is representable (`ALTER TABLE … ADD COLUMN` in the module's
  existing migration block, as `moz_competitor._init_cache_table` already
  does).
- **D2b.11** `_cache_lookup` returns a domain as needing a **partial**
  refetch: the cached sub-blocks plus the list of signals to ask for.
- **D2b.12** `fetch` asks only for the missing signals on a partial hit and
  merges them with the cached ones, so a failed anchor-text call costs one
  call next run, not four. Row accounting (`rows_consumed`, `row_budget`)
  counts only what was actually asked.
- **D2b.13** A sub-block served from cache carries the `fetched_at` of **its
  own** fetch, not the domain's newest. A ranking-keywords block from 27 days
  ago beside an anchor-text block from today must not both read as today
  (P6; the same argument as the existing `fetched_at` comment in
  `_cache_lookup`).
- **D2b.14** A consumer can tell "no anchor text" from "the anchor-text call
  failed". `_page_block`'s `status` already carries it; the criterion is that
  the handoff block and every renderer **read** it, and name the failure
  rather than printing an empty list.

### Both

- **D2b.15** A guard test asserts that neither cache has a path from a failed
  call to a served row: source-inspection in the style of
  `tests/test_d2_null_is_not_zero.py::_SourceGuard`, plus the two probes
  flipped into tests.
- **D2b.16** `probe_04` and `probe_05` part B become failing-then-passing
  tests in `tests/test_d2b_failure_is_not_absence.py`, asserting the retry
  **does** make a request once the API is healthy.

---

## Adjacent issues found, not fixed

Per the global rule, flagged rather than swept into this diff:

- **`http_retry._post_with_transient_retry` returns `None` for a network
  failure and the response object for an HTTP error**, so every caller
  re-implements the "did this work?" test and they do not agree.
  `gsc_client` checks `is None` then `.ok`; `moz_competitor._call` returns
  `(None, status)`. A single `Fetched(ok, response, status)` return would make
  D2b.1-style completeness mechanical everywhere instead of per-caller. Larger
  than this chunk and touches every HTTP site — a candidate for its own chunk.
- **`_fetch_all_rows` pages by `startRow` and trusts `len(rows) < ROW_LIMIT`
  as the end of data.** GSC can return a short page before the end under
  sampling. Not a null-vs-zero fault, so out of scope here, but it means
  `complete=True` is "the API said it was done", not a count check.
- **`run_gsc_analysis` catches bare `Exception` around `save_demand`** with
  the comment "persistence must never break the report". That is deliberate
  and defensible, but it currently also swallows a programming error; it
  should log the traceback at debug level. One line, left to D2c or a
  follow-up so this diff stays about one fault.
- **`compute_sponge_effect`'s `min_bucket_size` is a Python default
  (`MIN_BUCKET_SIZE`), not config** (P4). It decides whether a comparison is
  published, so it belongs in `config.yml` under `gsc`. Flagged; it is not a
  failure-vs-absence fault.

---

## Verification

**What can be verified here:** everything, with mocked transports. Both
probes already drive the real code paths with a fake 503 and a healthy retry,
so each acceptance criterion has a mechanical check that does not need
credentials.

**What cannot:** no live GSC property is reachable from this machine —
`gsc.enabled` is `false` in `config.yml` and `GSC_CREDENTIALS_PATH` is unset
— and the Moz account's live behaviour on a partial outage cannot be
provoked on demand. The claim "GSC returns a non-OK status rather than a
200 with an error body" comes from the API's documented behaviour and from
`probe_04`'s synthetic response, not from an observed outage. Recorded here
rather than asserted.

**Owner work after this lands:** any `gsc_analysis_*.json` / `.md` produced
while GSC was failing holds fabricated absences, and any
`moz_competitor_cache` row whose sub-blocks failed is still frozen. The
migration cannot repair the first; for the second, the per-signal columns
start NULL, which means "not recorded" and triggers a refetch — so the stale
failures clear themselves on the next run. State this in the push message.

---

## Order of work

1. GSC: `_fetch_all_rows` → `(rows, complete)`, then the cache gate
   (D2b.1–D2b.2). Smallest change that stops the fabrication.
2. GSC: the completeness value out through `get_query_stats`, the row
   vocabulary, the report, the sidecar, the brief and the demand trend
   (D2b.3–D2b.8).
3. Moz competitor: the per-signal cache columns and the partial-refetch path
   (D2b.9–D2b.14).
4. Tests, the two flipped probes, docs (`docs/architecture.md`,
   `docs/database.md`, `docs/methodology.md`, `docs/USER_MANUAL.md`,
   `docs/config_reference.md`, `glossary.yml` + regenerated
   `docs/glossary.md`), then the `learning-qa` pass over the diff with every
   medium-or-higher finding fixed, then push.

---

## As built

Every criterion is implemented and covered by a test in
`tests/test_d2b_failure_is_not_absence.py` (41 tests). Full suite: 1738
passed, 72 skipped, exit 0.

### GSC (D-C-02)

| Criterion | Where | Proof |
|---|---|---|
| D2b.1 | `gsc_client._fetch_all_rows` → `(rows, complete)`; all three failure paths return `False`, the short-page path `True` | `TestGscFetchReportsCompleteness` (5 tests, including a mid-pagination failure that keeps page 1 and still says incomplete) |
| D2b.2 | `get_query_stats` caches `found=0` only when `complete`; on an incomplete fetch the unresolved queries get no row at all | `TestIncompleteFetchIsNotCachedAsAbsence::test_503_caches_nothing_and_the_retry_asks_again` — the retry now makes 1 request where it made 0 |
| D2b.3 | `GscStats(stats, complete, asked, measured_absent, not_reached)` with `status_for()` | the whole file; the one caller (`run_gsc_analysis.run_analysis`) updated |
| D2b.4 | three `gsc_client.STATUS_*` constants; wording in the new `gsc_messages.yml`, read by `load_messages()` / `status_text()` / `line()` | `TestGscStatusVocabulary` (6 tests: every state has all three words, a malformed file degrades, no status word left in Python) |
| D2b.5 | `run_analysis` sets `row["gsc_status"]` and logs measured-absence apart from unreached; `generate_report` prints an "Incomplete fetch" warning, suppresses the "reported as absent" line when nothing is absent, and prints `not reached` in the cell | `TestReportNamesTheFailure` (4 tests) |
| D2b.6 | `build_sidecar` adds `fetch_complete`, `queries_not_reached`, `queries_no_impressions`; `_build_gsc_summary` passes the first two on; the prompt tells the model what to do with them | `TestSidecarAndBriefCarryCompleteness` (3 tests) |
| D2b.7 | `compute_demand(..., fetch_complete=)` folds completeness into `data_available`, so the existing `save_demand` guard refuses the point; the section says the fetch failed rather than that demand is absent | `TestDemandTrendRefusesAPartialFetch` (4 tests, incl. the partial-fetch-with-clicks case the old guard passed) |
| D2b.8 | `compute_sponge_effect` returns `queries_considered` / `queries_usable` / `not_reached`; the band cell, the "no band had enough" paragraph and the reformat section all name the fetch gap | `test_sponge_reports_its_denominator`, `test_insufficient_data_names_the_fetch_gap` |

### Moz competitor (D-C-10)

| Criterion | Where | Proof |
|---|---|---|
| D2b.9 | `_cache_store` stores only sub-blocks whose own status is in `_CACHEABLE`; `enabled_signals()` means a config-disabled signal is not a gap | `test_a_failed_sub_call_is_not_cached`, `test_disabled_signals_do_not_make_a_block_partial` |
| D2b.10 | four `<signal>_at` columns via the existing `PRAGMA table_info` migration block; the failed signal keeps no blob and no stamp | `test_a_failed_sub_call_is_not_cached` (asserts one column set, the other NULL) |
| D2b.11 | `_cache_lookup` → `({domain: {signal: block}}, {domain: [signals]})` | `test_enabling_a_signal_later_asks_only_for_it`, `test_a_signal_expires_on_its_own` |
| D2b.12 | `fetch` asks only for `needed[domain]` and `_signal_cost` prices only those | `test_the_retry_asks_for_the_failed_signal_only` (one call, not four), `test_row_budget_counts_only_the_signals_asked_for` |
| D2b.13 | each block stamped at collection; `_assemble` reports the **oldest** stamp as the block's `fetched_at`, plus a `signals_fetched_at` map | `TestMozSignalFreshnessIsPerSignal` (2 tests) |
| D2b.14 | `_page_block` always carries `data_available` and `reason` (empty when there is nothing to say — one producer, one shape, P19); `_fetch_link_momentum` reports `error` rather than `no_record` when both sub-calls failed; a capped or quota-skipped domain keeps its skip status instead of being recomputed to `no_record` | `TestMozConsumerCanNameTheFailure` (3 tests) |
| D2b.15 | source-inspection guards on both cache gates | `TestNoPathFromAFailureToAServedRow` (4 tests) |
| D2b.16 | both probes rewritten to assert the fixed behaviour and to fail if it regresses | `probe_04` and `probe_05` run clean; the same three expectations are pinned as tests |

### Found while building, fixed in this chunk

- **`_fetch_link_momentum` reported `no_record` when both of its sub-calls
  failed**, because its rollup was `STATUS_OK if available else
  STATUS_NO_RECORD`. The same failure-as-absence fault, one level below the
  one the chunk is about, so it was fixed here rather than flagged.
- **A capped or quota-skipped domain lost its skip status.** The first
  version of `_assemble` recomputed the top-level status from availability
  for every path, which turned `skipped_run_cap` into `no_record` — a skip
  stated as a measurement of the domain (P1). `_assemble` now keeps the skip
  status, and serves whatever signals were already cached for that domain
  rather than discarding them.
- **`_page_block`'s key set diverged.** Adding `reason` only on a failure
  handed the consumer `None` where a sibling block had a string, which an
  existing test (P19, "one producer, one shape") caught. `reason` is now
  always present, empty when there is nothing to say.

### Found by the cold review pass, fixed before the push

A `learning-qa` pass over the diff returned three high-confidence findings.
All three are fixed:

1. **`_fetch_link_momentum` still cached a half-failed signal as `ok`.** Its
   rollup was `ok` whenever *either* sub-call returned items, so a 503 on
   `lost` alone produced a cacheable `ok` block — the chunk's own fault,
   surviving one level down. Any errored sub-call now yields `error`, which is
   not cacheable.
2. **A partial block presented itself as complete.** A domain with cached
   ranking keywords whose anchor fetch was cap-skipped assembled as top-level
   `status: ok`, `data_available: true`, with an `anchor_texts` stub carrying
   no `items`, so `block["anchor_texts"].get("items", [])` read `[]` — "this
   competitor has no anchor text". The block now carries `complete` and
   `signals_missing`, the missing page-signal stub carries the page shape
   (`items: []`, `returned: 0`, `truncated: false`) beside its status, and
   both copies of `handoff_schema.json` document `status`, `data_available`
   and `reason` on every signal sub-object. They are deliberately NOT in
   `required`: making them required rejected handoffs written before this
   chunk, and serp-compete exits 1 on a validation error, so the stricter
   schema broke five of its rendering tests. The producer always emits them
   (an existing "one producer, one shape" test holds that); the schema
   stays additive.
3. **`_decode`'s fallback was `no_record`**, which is cacheable, so an
   unreadable cache blob was served as a measured absence and blocked its own
   refetch for the TTL. It now falls back to `not_fetched`.

Lower-severity notes from the same pass, also fixed: `gsc_client.py`'s module
docstring still described the old dict return and the pre-D2b cache rule;
`run_gsc_analysis.py` carried a dead lazy import under a comment that was no
longer true; the partial-fetch warning fired when the fetch called itself
incomplete but every query asked for resolved, printing "0 of N queries were
never reached"; `_assemble` took a `missing` argument it never read; and four
tests asserted on source comment text, which `standards/effort-budget.md` §5
forbids — they are replaced by behavioural guards on the same two gates.

### Documentation updated in this change

`docs/database.md` (both cache tables, with a new section on why a cache must
record whether the provider answered), `docs/architecture.md`,
`docs/methodology.md` (both the GSC section and the Moz competitor-signals
boundary), `docs/USER_MANUAL.md` (what "not reached" means for the reader and
what to do about it), `docs/config_reference.md` (`gsc_messages.yml`),
`CLAUDE.md` (the editorial-content list), `prompts/main_report/system.md`,
`docs/handoff_contract.md` + both copies of `handoff_schema.json`.
`docs/glossary.md` regenerated — unchanged, as the GSC analysis report is not
the market report the glossary guard covers.

### Owner work

- Any `gsc_analysis_*.json` / `.md` produced while GSC was failing holds
  fabricated absences, and any branded-share trend point written from a
  partial fetch is a share of a truncated denominator. Neither can be
  repaired by a migration: re-run `run_gsc_analysis.py` once credentials are
  in place, and discard the older sidecars rather than comparing against
  them.
- `moz_competitor_cache` rows frozen by the old whole-domain cache clear
  themselves: the new per-signal columns start NULL, which reads as "not
  recorded" and makes the next run ask for that signal.
