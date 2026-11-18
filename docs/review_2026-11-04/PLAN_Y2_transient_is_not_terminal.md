# Chunk Y2 — a transient failure is retried, and says it was one

Second adjacent-issue batch (global rule 10). Effort tier **Full**: the
changes touch the fetch path, a status vocabulary a reader acts on, and a
report section.

## Reproduced

1. **The page fetch had no retry.** `url_enricher.fetch_url` did a bare
   `requests.get` with one timeout while every other outbound call in the tool
   — DataForSEO, Moz, GSC, Gemini, the brief's LLM — went through
   `http_retry.post_with_transient_retry`. One connection reset or one 503
   therefore filed a ranked page as unread, and its word count, schema types,
   author signals, freshness and extractability as `Not Measured`, for the
   whole run (P5: a class of calls is hardened together, not one site at a
   time).
2. **A timeout and a dead host were the same fact.** `fetch_url` returned
   `None` for both, and the row read `Unreachable` either way. A reader had no
   way to tell a page that would read fine on the next run from one that never
   will (P1).
3. **A failed write looked like a first run.** `run_gsc_analysis` caught a
   `gsc_demand` persistence failure, logged it, and rendered the branded-demand
   section with no run-over-run Δ — which is exactly what the section prints
   when there is no history yet (P2/P6).

## As built

- `http_retry.get_with_transient_retry`: the GET sibling of the POST helper,
  same policy — retry on `requests.RequestException` and on
  `TRANSIENT_STATUSES`, backoff, `Retry-After` honoured and capped. One retry
  policy for the tool, not two.
- `fetch_url` uses it, and always returns a dict. On failure the dict carries
  `error` and `retryable`: `True` when every attempt failed at the network
  layer, `False` for a request that could not be made at all. The HEAD probe
  is still best-effort and deliberately not retried — it only decides whether
  to skip a PDF body, and the GET below is the real attempt.
- `enrichment.FETCH_RETRYABLE`, with its words in `serp_vocab.yml`
  (`fetch_retryable`) and in the literal fallback beside it, so the degraded
  path does not re-merge the two facts. `serp_audit` counts the state in the
  "N of M pages were not read" warning.
- `gsc_demand.render_demand_section(..., trend_error=...)` says why there is
  no Δ. `run_gsc_analysis` passes the exception's own text.

## Verification

- `tests/test_y2_transient_is_not_terminal.py` — 8 tests: the reset is
  retried `RETRY_ATTEMPTS` times, a 503 is retried and the retry's body is the
  one used, the timeout reaches every attempt, the two failure states render
  differently, the words come from the vocabulary file and its fallback agrees
  with it, the state is counted as unread, and the section names the
  persistence failure.
- Mutation gate: 8 mutations, all fail a guard. One was vacuous — it mutated
  the `_DEFAULTS` literal, which only the degraded path reads — and the guard
  was strengthened to assert every fallback matches the YAML rather than the
  mutation being dropped.
- Suite by exit code: 1987 passed / 68 skipped, exit 0.

## Docs

`docs/USER_MANUAL.md` (the `Fetch_Status` table and the `Fetch_State` list),
`docs/methodology.md` ("Which pages are read"), `CLAUDE.md` (the
`serp_vocab.yml fetch_status` entry).

## Checked and found sound (so it is not re-reviewed)

- `dataforseo_client._fetch_batch` returning `{}` on a failed batch is
  correct: those domains are then absent from `get_domain_metrics`'s result
  and are **not** cached, which is the documented "we never asked" rather
  than a measured absence, and `batch_coverage` reports asked vs answered.
- `gsc_client._fetch_all_rows`'s short-page end condition is already reasoned
  and carries the `complete` flag the caller needs; a failure part-way
  through pagination returns `complete=False` with the rows reached.

## Cold review (learning-qa, after the build)

Tier: Full. 1 high and 4 medium findings, all fixed; the lows are listed
below rather than fixed.

1. **High — the brief counted an unread page as read.**
   `brief_data_extraction._UNREAD_FETCH_STATES` keeps its own list of states,
   and a state missing from it falls into the *read* side of
   `_build_fetch_coverage`. `fetch_retryable` was not in it, so every
   schema / extractability / freshness / E-E-A-T figure in the brief got a
   denominator larger than the number of pages actually read. Added, along
   with `not_destination_page`, which was missing for the same reason. The
   guard now asserts every state in `enrichment.UNREAD_STATES` is a key of
   that map, so a new state cannot recur this.
2. **Medium — a malformed URL was retried.** `fetch_url` sent every
   `RequestException` through the retry loop, so a URL with no scheme spent
   `attempts × timeout` to reach the same answer. `http_retry` now re-raises
   `PERMANENT_REQUEST_ERRORS` (`MissingSchema`, `InvalidSchema`,
   `InvalidURL`, `URLRequired`, `TooManyRedirects`) instead of retrying them,
   and those become `unreachable` rather than `fetch_retryable`.
3. **Medium — the docs described a different split from the code.** The
   manual and `docs/methodology.md` put "a host that does not resolve" under
   `Unreachable`; a resolver failure raises `ConnectionError`, which is
   retried and ends as `fetch_retryable`. All five places (manual table,
   methodology, `fetch_url` docstring, `enrich_row` comment, the
   `serp_vocab.yml` comments) now state the same split: `fetch_retryable` =
   the network layer failed after the retries (timeout, reset, resolver);
   `unreachable` = no request could be made at all.
4. **Medium — the "no Δ" reason was a bare `str(exc)`.** Three of the four
   reasons there is no run-over-run Δ are a configuration gap, not a failed
   write, and none of the wording was in config. `gsc_messages.yml` now holds
   a `demand_trend` block (`write_failed`, `no_property`, `no_database`,
   `no_run_timestamp`, `first_run`, `line`) and `run_gsc_analysis._trend_reason`
   reads it.
5. **Medium — the unread warning blamed the sites.** "(error status or
   unreachable)" was written before a local network failure could land in
   that count, so a run on a bad connection read as a verdict on the pages.
   Reworded in `serp_vocab.yml`, and the count itself is now
   `serp_audit._unread_fetch_count`, derived from the new
   `enrichment.FAILED_FETCH_STATES` — the three states where the run tried
   and did not get the page, so a row past the rank cap still does not fire
   the warning.
6. **Low, fixed as a consequence** — the two source-text guards
   (`inspect.getsource` greps on `run_gsc_analysis` and `serp_audit`) were
   replaced with behavioural ones: the GSC guard drives the real
   `run_analysis` with `save_demand` patched to raise and asserts the reason
   reaches the report markdown, and the unread-count guard calls
   `_unread_fetch_count`. Both would have caught finding 4 and finding 5.

Mutation gate: 12 mutations, every one fails at least one guard.

## Adjacent issues found, not fixed

- `compute_sponge_effect.MIN_BUCKET_SIZE` is a Python constant (P4).
- The top-competitor tie-break is alphabetical;
  `_mixed_keyword_dominance_profiles` breaks a tie on dict order.
- `get_volatility_metrics` returns NaN with no `comparability_warning`, so
  report §6 is silently empty.
- `compute_foundational_score` returns `0.0` when every sub-score is `None`.
- `load_validation_rules` wraps the whole load in one `except` and caches the
  result, so one bug disables every numeric check for the process behind one
  warning.
- `refresh_analysis_outputs.refresh_xlsx` counts a row with no domain as
  `updated`; `refresh_json` writes twice.
- `serp_audit`'s in-pipeline pivot pass runs before `keyword_profiles` exists.
- `storage.py`'s `ALTER TABLE` migrations swallow lock and missing-table
  errors with the already-exists case.
- `visualize_volatility.py` is missing the `query_label` filter.
- `step_dag.py` is unreachable.
- No run-level retry budget for the page fetch: `attempts` and `backoff` are
  `http_retry`'s module defaults and are not in `config.yml`, so a run on a
  bad connection cannot be told to give up sooner (P4, low — the fetch is
  already bounded by `timeout × attempts` per URL).
- `url_enricher`'s HEAD probe is deliberately unretried (it only decides
  whether to skip a PDF body) and takes no `get=` injection point, so the
  `get=` convention the GET helper offers is inconsistent across the two
  calls in that one function.
- `citation_table.build_citation_table` drops a citation it cannot attribute
  to a brand from `top_cited_domains` with no "N of M" count (P2).
- `tests/test_y1_one_definition_each.py::test_no_module_strips_the_prefix_by_hand`
  matches source literals rather than walking the AST, so a differently
  spelled hand-rolled strip would pass it.
- `serp_audit.py:1517` still calls `urlparse(url).netloc` itself rather than
  `domain_utils.normalize_domain` (Y1's eight sites did not include it).
- `enrichment.NOT_DESTINATION_PAGE` is a page the run tried to read and did
  not get, but it is not in `FAILED_FETCH_STATES`, so it does not fire the
  "N of M" warning. Widening the warning is an editorial call about what the
  reader should be told, not a bug in this chunk.
