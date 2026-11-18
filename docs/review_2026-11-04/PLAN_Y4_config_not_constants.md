# Chunk Y4 — the numbers live in config, the ties are decided on purpose

Adjacent-issue batch 4. One rule: a number a non-developer might reasonably
want to change belongs in `config.yml` with the module constant as its
documented default (P4), and a tie between two measured things is resolved on
a stated basis, not on dict or alphabetical order (P12/P19).

## The findings, reproduced

1. **The sponge comparison's two thresholds are Python constants.**
   `run_gsc_analysis.MIN_BUCKET_SIZE = 3` and `DEFAULT_POSITION_BANDS =
   [(1,3),(4,10),(11,20)]` decide whether an AIO-vs-no-AIO CTR comparison is
   reported at all and at which rank bands, while their two siblings —
   `min_impressions` and `reformat_ctr_margin` — are already editorial keys
   under `gsc` read by `resolve_sponge_thresholds`. A property with few
   tracked queries never reports a band at a bucket size of 3, and the only
   way to say so is to edit Python.
2. **`http_retry`'s retry budget is not configurable.** `RETRY_ATTEMPTS = 2`,
   `RETRY_BACKOFF_SECONDS = 1.0` and `MAX_RETRY_AFTER_SECONDS = 30.0` are
   module constants, and every DataForSEO, Moz, GSC, LLM-probe and page-fetch
   call takes them as defaults. SerpAPI's own retry has been configurable
   (`serpapi.retry_max_attempts` / `retry_backoff_seconds`) since the start,
   so one of the two retry policies in the tool can be tuned and the other
   cannot (P4, P25 — one config→argument mapping).
3. **A tie at the top of a keyword's entity mix is broken by dict order, and
   the check it feeds then misses the contradiction.**
   `brief_validation._mixed_keyword_dominance_profiles` sorts the entity
   distribution on count alone, so with `clinic: 4, directory: 4` whichever
   key came first in the JSON becomes `top_entity`. The check then looks for
   "`{top_entity}` … dominat" in that keyword's section: if the brief says
   "directories dominate" and dict order picked `clinic`, the contradiction is
   not reported at all. The figures in the message are right; the entity name
   is a coin toss.
4. **`visualize_volatility.py` charts alternative-query rows as rank history.**
   Its query reads `serp_results` on `keyword_text` with no `query_label`
   filter and no completed-run filter, so a pivot row ("P") or an
   AI-alternative row ("S") for the same keyword text plots as if it were the
   primary SERP, and an aborted run contributes a point. `metrics.py` has
   filtered on `PRIMARY_QUERY_LABEL` and on run completion since chunk D1
   (D-C-22); this module was missed.
5. **`serp_audit.py:1531` still derives a host by hand.** `urlparse(url).netloc`
   keeps the port, the userinfo and the `www.` prefix, so the `serp_results`
   row it writes can carry a host form that does not match the canonical one
   every other table and the handoff use. Chunk Y1 routed eight such sites
   through `domain_utils.normalize_domain` and did not include this one;
   `storage.save_serp_result` canonicalises what it is given, so the stored
   row is right — the value passed to the classifier beside it is not.

## The fixes

1. `resolve_sponge_thresholds` also resolves `min_bucket_size` and
   `position_bands`, both validated (a positive whole number; a list of
   low/high pairs with low ≤ high), with the module constants as the
   documented defaults and a warning on anything unusable.
2. `http_retry.resolve_retry_policy(cfg)` reads a new top-level `http_retry`
   block in `config.yml` (`attempts`, `backoff_seconds`,
   `max_retry_after_seconds`), validated, with `DEFAULT_RETRY_POLICY` as the
   documented default; `apply_retry_policy(cfg)` sets the process's policy and
   every entry point that loads config applies it. The two helpers resolve the
   policy inside their bodies rather than naming the constants as default
   arguments — a default is bound when the module is defined, so the rebind
   would have reached no caller that omitted the argument.
   (`config.yml`, not `technical.*` as this plan first said: `technical.*` is
   the cross-tool namespace that lives in `shared_config.json`, and this is one
   tool's own outbound policy.)
3. The dominance sort breaks its tie explicitly, and the check tests **every**
   entity tied at the top, so the contradiction is found whichever name the
   brief used; the message names the tie.
4. `visualize_volatility.py` filters on the primary query label and on
   completed runs, and says how many rows each filter excluded.
5. `serp_audit.py` uses `domain_utils.normalize_domain`.

## Verification

- Full suite green by exit code: 2058 passed, 68 skipped, 10 subtests passed.
- 38 mutations over the five fixes and the cold review's eleven
  (`scratchpad/mutate_y4.py`); every one fails
  at least one guard, and none is vacuous — the first pass found nine that
  were, including four whose anchors had gone stale, one that fell through to
  an identical sibling value (`PRIMARY_QUERY_LABEL = "A"` is the same literal),
  and one that proved only the wording of the excluded-row line.
- Guards: `tests/test_y4_config_not_constants.py`, one per finding.

## Cold review

A cold `learning-qa` pass over the diff returned 11 findings (2 high, 5 medium,
1 medium-low, 3 low). All eleven are fixed, and the gate grew to 38 mutations.

- **The tie fix dropped the case the check exists for (high — a regression in
  this diff).** Taking the runner-up as the next *strictly lower* count made
  `{clinic: 4, directory: 4}` a runner-up of 0, which the `second_count >= 3`
  gate discarded: a brief calling a perfect 4-4 split dominant passed with no
  issue at all. The runner-up is `ranked[1][1]` again, ties included, and the
  guards now cover `{4, 4}` and `{4, 4, 1}`.
- **The retry policy was applied by one entry point out of five (high, P5).**
  `serp_audit.py` called `apply_retry_policy(CONFIG)`; `run_feasibility.py`,
  `run_gsc_analysis.py` and `probe_ai_visibility.py` load the same
  `config.yml` and make outbound calls through `http_retry`, and applied
  nothing. A `http_retry` block would have changed the audit's behaviour and
  silently done nothing in the other three — worse than no setting at all. Each
  `_load_config` now applies it, and a missing config file resets the policy to
  the documented default so a second run in the same process does not inherit
  the first run's.
- **The resolver read its fallback from mutable state (medium).**
  `resolve_retry_policy` built its defaults from `RETRY_ATTEMPTS` and friends,
  which `apply_retry_policy` rebinds — so applying a config with `attempts: 7`
  and then a config with no `attempts` kept 7 instead of the documented 2. The
  defaults are now frozen in `DEFAULT_RETRY_POLICY`.
- **A malformed config section killed the run instead of warning (medium).**
  `resolve_retry_policy` and `resolve_sponge_thresholds` both did `key in
  block` on whatever the YAML held, so `http_retry: 2` raised a `TypeError` —
  and because `serp_audit` applies the policy at module level, every run died
  on import. Both now report the section and use the documented defaults.
- **The chart's "N of M" folded three reasons into one, and named a cause it
  could not know (medium, P2/P35).** The denominator also carried the `rank <=
  10` clause, so a client sitting at 11-20 saw a one-point chart and no
  explanation, and `get_keywords` applied a different filter set, offering
  keywords the chart then reported no data for. The filter is now one constant
  both queries use, each exclusion reason is counted separately, and a row
  whose `query_label` or `completed_at` is NULL — written before those
  migrations — is reported as unknown rather than as a pivot or an aborted run.
- **The bands were validated pair by pair, and what they excluded was not
  counted (medium, P2/P9).** `[[1,3],[3,10]]` counted a position-3 query in two
  medians and `[[1,3],[6,10]]` silently dropped 4-5. Overlaps and gaps are now
  refused, out-of-order bands are sorted, and the rollup carries
  `queries_in_no_band`.
- **The reformat shortlist's depth cap did not move with the bands
  (medium-low, P4/P25).** `REFORMAT_MAX_POSITION = 10.0` stayed a constant, so
  configuring `position_bands: [[11, 20]]` — the case the new manual text
  invites — produced an always-empty shortlist with nothing saying why. It is
  now `gsc.reformat_max_position`, the report states the figure it used, and
  the run warns when the cap and the bands cannot agree.
- **The policy guard proved wording, not consequence (medium).** An
  `inspect.getsource` substring match on `apply_retry_policy(CONFIG)` would
  have passed on a docstring and broken green on a rename, and it could not see
  the four unconfigured entry points. Replaced with a subprocess that imports
  `serp_audit` in a temp directory holding `attempts: 4` and asserts the
  resolved number, plus a per-entry-point guard.
- **`resolve_retry_policy` accepted a boolean and misquoted the value (low).**
  `attempts: true` became 1 silently, and `attempts: 0.5` warned "is 0". Bools
  are refused and the warning quotes what the file says alongside what it
  resolves to.
- **`DEFAULT_RETRY_POLICY` was documented "frozen" and was a plain dict
  (low).** Now a `MappingProxyType`, so the invariant the comment claims is
  enforced.
- **A dead `urlparse` import remained in `serp_audit.py` (low)**, the only
  reference being the one the new AST guard forbids.
- **The tie-break was guarded as a set, not an order (low).** The first guard
  sorted the returned entities before comparing, so reverting the `str(item[0])`
  tie-break failed nothing. The guard now asserts the order, over two
  distributions that differ only in dict order.
- **The host fix was guarded by a source grep (low).** Replaced with an AST
  walk asserting no `.netloc` read remains anywhere in `serp_audit.py`, plus an
  identity check that the module binds `domain_utils.normalize_domain` rather
  than a copy.

## Adjacent issues found, not fixed

- `compute_sponge_effect` still names `MIN_BUCKET_SIZE` and
  `DEFAULT_MIN_IMPRESSIONS` as default arguments. Nothing rebinds those module
  globals, so the Y4 trap does not apply, but the pattern is the one that bit
  `http_retry`.
- `refresh_analysis_outputs.py` loads `config.yml` with its own loader and does
  not apply the retry policy. It makes no outbound calls, so nothing is wrong
  today; it is the fifth loader of the same file.
- The per-module `REQUEST_TIMEOUT` constants (`gsc_client.py`,
  `dataforseo_client.py`, `probe_ai_visibility.py`, `url_enricher`'s
  `timeout=10`, `http_retry`'s `timeout=30`) did not become editorial with the
  retry budget, though "how long the tool may spend on a flaky host" is one
  judgement (P4/P5 — the same argument this chunk makes for `attempts`).
- Two retry policies now coexist: `serpapi.retry_max_attempts` with its own
  backoff loop in `serp_audit.py`, and the new `http_retry` block. Both are
  documented; nothing reconciles them.
- The new editorial keys have no `config_manager` GUI surface.
- `visualize_volatility` opens the DB with a raw `sqlite3.connect`, so it is
  the only reader that bypasses `SerpStorage`'s migrations.
- `storage.py`'s `ALTER TABLE` migrations swallow lock and missing-table errors
  along with the already-exists case (three `except sqlite3.OperationalError:
  pass` sites).
- `serp_audit`'s in-pipeline pivot pass runs before `keyword_profiles` exists.
- `citation_table.build_citation_table` drops a citation whose **brand** cannot
  be attributed without counting it (the host drop was fixed in Y3).
- `tests/test_y1_one_definition_each.py::test_no_module_strips_the_prefix_by_hand`
  matches source literals rather than walking the AST.
- `metrics.get_volatility_metrics` opens and closes its connection by hand on
  seven paths.
- `enrichment.NOT_DESTINATION_PAGE` is not in `FAILED_FETCH_STATES` (an
  editorial call, not a defect).
