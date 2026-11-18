# Database — SQLite schema, tables, and migration notes

SQLite at `serp_data.db`. Key tables:

| Table | Contents |
|-------|----------|
| `runs` | Each audit run (run_id, date, params_hash, completed_at) |
| `serp_results` | All ranked results per keyword per run (rank, query_label) |
| `url_features` | Enriched URL data including Moz DA/PA columns |
| `domain_features` | Entity type per domain |
| `autocomplete_suggestions` | Search autocomplete data |
| `keyword_feasibility` | DA gap scores, feasibility status, pivot variants per run |
| `da_cache` | DataForSEO domain rank cache (30-day TTL; 7 days for a row with no rank) |
| `moz_cache` | Moz DA/PA cache (30-day TTL; 7 days for a row with no DA) |
| `moz_competitor_cache` | Per-competitor Moz signals, cached **per signal** (30-day TTL) |
| `gsc_cache` | Search Console query stats (7-day TTL; `found = 0` records a measured absence; keyed by query + window + `filters`, so one country/device pull never overwrites another) |

All schema changes use `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE … ADD COLUMN` wrapped in `try/except OperationalError` — migrations run automatically on first use.

## Rank history: which rows are comparable

Two columns decide what rank history may be measured against what. Both were
added by review chunk D1 (findings D-C-22, D-C-01); rows written before that
carry NULL in both, which means *unknown* — not "completed" and not "primary".

- **`runs.completed_at`** — NULL until the run has written every output.
  `storage.save_run` is called before the first fetch, so a `runs` row exists
  even for a run that aborts on keyword 1; only `storage.mark_run_completed`,
  called after `pipeline_status.finish_run` returns OK, stamps this column.
  `pipeline_status.finish_run` checks each output against the file on disk
  before returning OK, not only against the in-process "written" flags, so a
  truncated or deleted output cannot earn a completion stamp (P6).
  `metrics.py` takes its baseline from the most recent **completed** run
  before the current one, and counts and logs the runs it passed over rather
  than reporting a bare "no history" (P2). The count is scoped to the runs
  between that baseline and the current run, which is what the message says.
- **`serp_results.query_label`** — `"A"` for the primary keyword, `"A.1"` /
  `"A.2"` for AI-alternative phrasings, `"P"` for a pivot fetch. Every label
  is stored under the **root** keyword, so merging two runs on
  `(keyword_text, url)` without filtering produced cross-products and
  invented rank deltas. `metrics.py` filters `query_label = 'A'` in
  `get_volatility_metrics`, `get_rank_deltas` and `get_entity_dominance`.
- **`serp_results.rank`** is the absolute SERP position, not SerpAPI's
  per-page `position` (see docs/methodology.md, Part 1 "Rank semantics
  (pagination)"), so `rank <= 10` in `get_entity_dominance` is the real top 10.

- **`serp_results.domain` and `domain_features.domain`** hold the canonical
  host (`domain_utils.normalize_domain`: lower-cased, no port, no userinfo, no
  leading `www.` or `m.`). They are joined on each other, so both sides have
  to agree about which host is which; before review chunk Y1 (2026-11-17) the
  first held `urlparse(url).netloc` verbatim and one site could hold two rows
  with one entity type each. Opening a database written before that runs a
  one-off canonicalising pass over both columns — it is idempotent, logs how
  many hosts it moved, and on a `domain_features` collision keeps the
  canonical row's entity type and drops the alias. Without it a reader that
  spans runs (`visualize_volatility.py` pivots this column) would see a
  `www.x.ca` series stop at the change and an `x.ca` series start, which reads
  as one competitor leaving and another arriving. A row whose URL has no
  readable host is still stored, with an empty `domain` and a warning: it
  joins against nothing, and the rank, title and URL are still facts about
  the SERP.

Runs recorded before 2026-11-16 therefore produce no deltas: `metrics.py`
returns an `empty_data` status naming the missing labels instead of comparing
rows it cannot interpret. Re-running rebuilds the history.

## Feasibility coverage and provenance

`keyword_feasibility` carries four columns added by review chunk D2
(finding F9) and five more added by D6, so the figure and the confidence in
it travel together into rank history:

- **`da_count` / `da_missing`** — how many of the keyword's top-10 positions
  carried a DA figure and how many did not. `avg_serp_da` over two domains
  and over ten read identically without them.
- **`da_provider`** — which provider was asked (`dataforseo`, `moz`,
  `none`). DataForSEO's backlink rank and Moz's Domain Authority are both
  0–100 and are different vendors' models, so a trend that mixes them is not
  a trend.
- **`min_competitor_da` / `max_competitor_da` / `min_non_directory_da` /
  `non_directory_count` / `entities_known`** (review chunk D6) — the minima
  the mean cannot show. `min_non_directory_da` NULL means no competitor's
  entity type was resolved, which is not "no directory ranks here";
  `entities_known` says how many were, so a figure taken over 1 of 10 is
  never read as taken over 10. NULL in every one of them means a row written
  before D6, which is "not recorded", not 0. Added to existing databases by
  migration.
- **`client_da_source`** — how `client_da` was obtained: measured by the
  active provider, an operator override, the `config.yml` fallback (whose
  scale against that provider is unverified), or not measured at all.

Rows written before the migration hold NULL in all four. NULL means *not
recorded*, never `0 of 0`: every reader keeps absent and zero apart, and the
reports print "coverage not recorded for this run" rather than inventing a
denominator. `client_da` is nullable for the same reason — with no provider
reachable there is no figure, and a 0 would read as a measurement.

A row is written by `storage.save_feasibility_from_row`, which takes the
assessment dict whole rather than re-listing its fields at each call site.

## Caches record whether the provider answered, not only what it said

Review chunk D2b. Both caches used to store the provider's reply without
storing whether there had been a reply, so a failure was served back as a
measurement for the rest of the TTL — and the TTL is exactly the window in
which a retry would have fixed it.

### `gsc_cache` — `found = 0` means GSC answered "nothing"

`found = 0` is a measured absence: Search Console answered, and holds no row
for that query in the window. It is cached so a query the property genuinely
has no impressions for is not re-pulled every run.

It is written **only** when the fetch completed. When any page of the pull
failed at the network layer, returned a non-OK status or returned non-JSON,
`gsc_client.get_query_stats` writes nothing for the queries it could not
resolve: no row means "not asked yet", so the next call asks again. Before
D2b a 503 wrote `found = 0` for every unfetched query and the retry inside
the TTL made no request at all (finding D-C-02).

The three states a query can be in are `measured`, `measured_absent` and
`not_reached` (`gsc_client.STATUS_*`); the words a reader sees for each live
in `gsc_messages.yml`.

An absence is an absence **for one population**. Since D5.7 the pull is
restricted to the country and device the SERP fetch used, and the `filters`
column (`""` for unfiltered, else `"{country}|{device}"`, built by
`gsc_filters.cache_filter_key`) is part of the PRIMARY KEY, so rows for two
configurations coexist instead of overwriting each other and a filtered row is
never served to an unfiltered read. A cache written before this is migrated in
place by `_init_cache_table`, its rows recorded as unfiltered. The per-query
wording names the population, because a query whose traffic is all mobile is
absent from a desktop pull and that is not a finding about the client.

`gsc_demand_score` carries `property_branded_click_share`,
`property_query_count` and `band_basis` (D5.4): the branded share over the
whole property, the number of its *clicking* queries, and which of the two
figures — `property` or `tracked` — the benchmark band was read from. Rows
written before D5.4 have no basis recorded and `get_demand_trend` reports them
as `tracked`, which is what they were.

### `moz_competitor_cache` — one row, four independently cached signals

Each of `ranking_keywords`, `anchor_texts`, `brand_authority` and
`link_momentum` has its own JSON column **and its own `<signal>_at`
timestamp**. Freshness, expiry and refetch are decided per signal:

- A sub-call that failed is not written, so it has no timestamp, so the next
  run asks for it — and only for it. A failed anchor-text call costs one
  call next run, not a four-call refetch of billed rows.
- A sub-block served from cache reports **its own** `fetched_at`. The block's
  top-level `fetched_at` is the **oldest** of them: the block as a whole is
  only as current as its stalest part.
- A signal switched off by config is not a gap. It reports
  `status: disabled` and never triggers a refetch.

The legacy whole-row `status` and `fetched_at` columns are kept for
diagnostics only; nothing reads them to decide freshness. The per-signal
columns start NULL on an existing database, which reads as *not recorded* and
makes the next run ask — so rows frozen by the old whole-domain cache clear
themselves on the next run. Before D2b, `_fetch_one` set the top-level status
to `ok` whenever any sub-call returned data, `_cache_store` gated on that, and
`_cache_lookup`'s "never serve a cached failure" branch therefore never fired
(finding D-C-10).
