# Database — SQLite schema, tables, and migration notes

SQLite at the path `config.yml` gives as `database.path`, `serp_data.db` by
default. A relative path resolves against the repo root, never the current
working directory: the path was a bare literal at 24 sites and a reader
started from another directory created a new empty database beside itself
instead of reporting that the history was missing (review chunk Y12).
`db_connect.database_path()` is the one place the default is read, and it is
read at call time — a configured value taken as a default argument binds at
`def` time, before any config has been loaded.

Key tables:

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
| `moz_keyword_cache` | Moz keyword metrics per keyword (30-day TTL; `status = no_record` records a measured absence; keyed by keyword + engine + locale + device) |
| `moz_intent_cache` | Moz search-intent scores per keyword, same key and same rules — one implementation serves both (review chunk Y14) |
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
- **`serp_results.sent_query`** — the exact search text sent (added
  2026-11-22, NULL on older rows). `metrics.same_search_only` leaves a keyword
  out of volatility and rank deltas when its two runs sent different text, or
  one recorded it and one did not, and says how many it left out: a change of
  search is not rank movement.
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

Every migration in `storage._init_db` runs through
`storage._add_missing_columns`, which adds only the absent columns and lets any
other `sqlite3.OperationalError` out. Until review chunk Y5 the three migration
sites sat inside `except sqlite3.OperationalError: pass`, so "database is
locked", "no such table" and a read-only file all meant "column already
exists": a migration that never ran left the column missing, the run carried on,
and the provenance columns then read "not recorded" — the wording that means a
row written before the migration (P1/P6). A missing table is now raised with
the reason, because a database with no schema is not a migrated one.

A read-only consumer opens the database through `storage.migrated_connection`,
which constructs a `SerpStorage` first, so the migrations have run before the
first query. Bringing a schema forward is a write, and these are read-only
scripts, so it is announced: the helper reports the columns added and the hosts
the Y1 canonicalisation rewrote, because a chart that quietly `UPDATE`d rows
and deleted orphaned `domain_features` rows in the operator's history would
leave no record of it. `create` is False, so an absent file raises
`FileNotFoundError` instead of being created and read back as an empty history
— "no database yet" and "this keyword never ranked" are different answers.
`metrics.py`'s three reads use the same helper, because
`generate_insight_report.py` calls them with no `SerpStorage` constructed
first. `visualize_volatility.py` used a bare `sqlite3.connect`, and every
query it makes filters on `serp_results.query_label` and `runs.completed_at` —
columns a migration added — so against a database written before them the chart
raised `no such column` rather than reporting an empty rank history (review
chunk Y6). The helper returns a `db_connect.connection`
context manager, so the handle is closed on a raised exit too and a write made
through it is committed rather than discarded by the close (review chunk Y9 —
until its cold review this returned `closing(sqlite3.connect(...))`, which
closes the handle *instead of* committing).

**What happens when the cleanup itself fails.** A failing `rollback()` or
`close()` is logged and does not replace the exception the block raised
(review chunk Y11) — but a log line on stderr is not where the GUI operator
looks, and a `close()` that fails once inside a per-keyword or per-domain loop
has usually failed every time, each one holding a file handle open until the
process exits. `db_connect` therefore counts them, keyed by step and database
path, and `cleanup_failure_warning()` renders the tally as one sentence: Tool
1's audit writes it as a `parsing_warnings` row, so it reaches the JSON and the
workbook's Parsing_Warnings sheet, and Tool 2's audit puts it in `run_coverage`,
so it reaches the briefing's coverage block. What the sentence then claims depends on
which step failed: a `close()` comes after the commit, so the writes are
durable and it says so; a counted `roll back` means a block raised and
abandoned its transaction, so it says that instead of telling the reader their
figures stand. The run's exit code does not change either way — a failed
cleanup after a successful commit is not a reason to discard the run. More than
one database involved and the paths are named, because the reader's next action
is to check a file and since chunk Y12 the path is configurable.

The audit clears the tally where its own run begins, and reports again at the
end: the workbook cannot be amended once it is on disk and the run keeps
writing to the database after it — the report's trend reads and the write that
marks the run complete both come later — so failures that arrive after the row
was built are stated as "N further cleanup step(s) failed after this run's
output was written". The other entry points are separate processes
(`run_pipeline` and the GUI launch each step with `subprocess`), and only the
audit renders the sentence into an artefact; for the rest the floor is an
`atexit` hook in `db_connect`, which prints a non-empty tally on the way out if
nothing else has, including on an abort (review chunk Y13 and its cold review).

**How every other module opens the database.** `db_connect.connection(db_path)`
(review chunk Y9). It commits on a clean exit, rolls back on an exception and
closes the handle in a `finally`, which neither of the two obvious forms does:
`with sqlite3.connect(path) as conn:` commits but leaves the handle to the
garbage collector, and `with closing(sqlite3.connect(path)) as conn:` closes
the handle and discards the commit, because `closing` does not run the
connection's own `__exit__`. 61 production sites used the first form — the DA,
keyword, intent, GSC, AI-visibility and citation caches all open per lookup
inside per-keyword and per-engine loops — and `export_history.py` and
`verify_enrichment.py` opened bare connections that were closed on the happy
path or not at all. A standing guard
(`tests/test_y9_a_handle_is_closed.py::TestNoProductionModuleLeavesAHandleOpen`)
fails the build when any production module opens `sqlite3.connect` outside this
helper or a `contextlib.closing`.

Two things the first version of the helper got wrong, fixed in review chunk
Y11:

* **A failing cleanup no longer replaces the diagnosis.** `rollback()` and
  `close()` can each raise — a disk I/O error, a file that has gone away — and
  when either did, its exception replaced the one the block raised, so the
  `IntegrityError` saying which write was wrong arrived as an
  `OperationalError` from the cleanup. On the clean path it was worse: a
  `close()` that failed *after* a successful `commit()` raised out of a block
  whose write was already durable, so the caller recorded the write as failed
  and the run reported an absence where there was a row. Both steps now run
  through `_safely`, which logs the cleanup failure and lets the original
  outcome stand. It catches `Exception`, not `BaseException`, so a Ctrl-C
  during cleanup still reaches the user.
* **The lock wait is a configured number.** `sqlite3.connect(timeout=)` — how
  long a writer waits for another writer's lock before raising `database is
  locked` — was left at its default of 5.0, chosen by nobody and changeable by
  nobody, while the GUI runs `refresh_analysis_outputs` in the same process as
  a run and the AI probe writes the same file. It is now
  `config.yml database.lock_timeout_seconds`, shipped at 5.0 so the change was
  not a behaviour change, read through `timeouts.seconds_from_config` and
  applied by `process_config.apply` — the one function every loader of
  `config.yml` calls to set this process's policies.

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

### The two keyword caches share one implementation

`moz_keyword_cache` and `moz_intent_cache` hold different payloads — four
integer metrics against two JSON columns — but answer the same question under
the same key (`keyword, engine, locale, device`), and three rules have to hold
for both:

1. A row older than `moz.cache_ttl_days` is ignored, and so is a row carrying
   no `fetched_at` at all: a missing timestamp is not evidence of freshness.
2. A cached failure is never served. Only `ok` and `no_record` are written, so
   a keyword whose last fetch errored is re-fetched rather than reported as
   absent for a month.
3. A measured absence **is** served. `no_record` means Moz holds nothing for
   that keyword, which is a fact worth keeping rather than a fetch to repeat
   every run, and the reason names the signal, so an intent block never reports
   "no metrics".

Until review chunk Y14 each client carried its own `_init_cache_table`,
`_cache_lookup` and `_cache_store` and all three rules were written twice. They
now live once on `_KeywordSignalClient`, built from the subclass's
`CACHE_TABLE_NAME` and `CACHE_PAYLOAD_COLUMNS`; a subclass supplies only
`_block_from_cache` and `_payload_for_cache`, which exchange a mapping
keyed by column name so that the order of the column spec carries no
meaning. A column added to the spec is added to a table already on disk
(`_add_missing_columns`), keeping its rows — `CREATE TABLE IF NOT EXISTS`
does not alter an existing table, so without that every installation but a
fresh one would fail on the first write and report the signal as
unavailable for every keyword, every run. The guards in
`tests/test_y14_one_cache_for_both_signals.py` assert every rule against both
clients through the same test, so neither can drift from the other unnoticed.

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
