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

Runs recorded before 2026-11-16 therefore produce no deltas: `metrics.py`
returns an `empty_data` status naming the missing labels instead of comparing
rows it cannot interpret. Re-running rebuilds the history.

## Feasibility coverage and provenance

`keyword_feasibility` carries four columns added by review chunk D2
(finding F9), so the figure and the confidence in it travel together into
rank history:

- **`da_count` / `da_missing`** — how many of the keyword's top-10 positions
  carried a DA figure and how many did not. `avg_serp_da` over two domains
  and over ten read identically without them.
- **`da_provider`** — which provider was asked (`dataforseo`, `moz`,
  `none`). DataForSEO's backlink rank and Moz's Domain Authority are both
  0–100 and are different vendors' models, so a trend that mixes them is not
  a trend.
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
