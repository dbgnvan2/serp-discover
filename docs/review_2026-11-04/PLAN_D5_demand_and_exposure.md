# D5 — GSC demand and AI-Overview exposure

Review chunk D5 of `REVIEW_WORKPLAN_2026-11-04.md`: four findings (D-M-15,
D-M-16, D-M-17, D-M-20) across `run_gsc_analysis.py`, `gsc_demand.py`,
`gsc_client.py`, `demand_dashboard.py` and `aio_exposure.py`.

## Reproduced before building

### D-M-15 — reformat candidates are the below-median half

Seven queries at position 5, four without an AI Overview (one of them with two
impressions), three with one:

```
no-AIO median CTR: 0.025   (bucket sufficient: True)
candidates: [('q0', 0.01, has_ai_overview=False), ('q1', 0.02, False)]
includes a 2-impression query:        True
candidates with NO AI Overview:       ['q0', 'q1']
```

`find_reformat_candidates` admits any found row at position ≤ 10 whose CTR is
below its band's no-AIO median. That is by construction about half the rows, it
does not require an AI Overview to be present, it has no margin, and it has no
impression floor — a query with two impressions and one click qualifies.

### D-M-17 — "traffic at risk" exceeds the clicks that exist

One query, 1,000 impressions, 5 clicks, position 8, AIO present, client not
cited:

```
clicks: 5   impressions: 1000   est_traffic_at_risk: 15.0
```

`intercepted = impressions × est_ctr_loss` is computed against the modeled CTR
curve, not against the clicks GSC measured, so the figure is three times the
client's entire click count for that query. `gsc_cache` stores `ctr` and
`position`, and `_latest_gsc` selects neither.

### D-M-16 — the branded share's denominator and its bands

`gsc_demand.compute_demand` divides over the rows it was handed, which are the
run's **tracked** queries. `GscClient._fetch_all_rows` already pulls every query
row for the property and `fetch_stats` discards the untracked ones, so the
property-level figure is available and thrown away. `DEFAULT_BANDS =
{"below_avg": 0.024, "top": 0.10}` carries the comment "industry REFERENCE
points" and no source.

### D-M-20 — the trend compares unlike runs, and the constants have no source

`get_aio_exposure_trend` groups `ai_aio_exposure` by `run_ts` and returns the
per-run rollups with no test that the runs cover the same keywords. The table
does store `keyword` per row, so the comparison is available. `metrics.py`
already carries the pattern (`comparability_warning`, lines 133-144).

`DEFAULT_AIO_CTR_MULTIPLIER = 0.60` ("industry '~60% AIO CTR interception'
reference"), `DEFAULT_CITATION_CREDIT = 0.5` ("recovers half") and
`DEFAULT_CTR_CURVE` (ten positions) each have a descriptive comment and no
citation or date.

### D-M-15 (second half) / the GSC request

`_fetch_all_rows` sends `dimensions: ["query"]` with no
`dimensionFilterGroups`, so the figures are all countries and all devices while
the SERP fetch is `gl: ca`, `device: desktop`. The report prints neither the
window nor the filters.

---

## Criteria

- **D5.1** The sponge table says what it is: an association at comparable
  position, confounded by intent, not a measured effect. Its medians rest on
  queries with enough impressions to carry a CTR, and the floor travels with
  the figures.
- **D5.2** A reformat candidate requires an AI Overview to be present, a
  position inside the band, and a CTR a stated margin below the band's no-AIO
  median. The margin and the impression floor are editorial, in config.
- **D5.3** `est_traffic_at_risk` for a query never exceeds the clicks measured
  for it, and GSC's own `ctr`/`position` are used where the row has them. The
  dashboard states the GSC window it read.
- **D5.4** The branded click share is computed over the whole property when the
  fetch covered it, with the tracked-query share kept beside it and both
  labelled. The bands carry a source and date, or are marked the owner's
  assumption.
- **D5.5** The AIO exposure trend compares only runs covering the same keyword
  set, and names the runs it excluded and why.
- **D5.6** The CTR curve, the AIO interception multiplier and the citation
  credit each carry a stated provenance in `config.yml`, and the report and
  glossary say whose assumption they are.
- **D5.7** The GSC pull is filtered to the country and device the SERP fetch
  uses, both configurable, and the report prints the filters with the window.

---

## As built

### D5.1 / D5.2 — the sponge and the shortlist need real traffic (D-M-15)

`run_gsc_analysis.py` gained `DEFAULT_MIN_IMPRESSIONS = 50`,
`DEFAULT_REFORMAT_CTR_MARGIN = 0.25` and `resolve_sponge_thresholds(cfg)`, which
reads `gsc.min_impressions` / `gsc.reformat_ctr_margin` and warns-and-degrades on
a non-numeric or negative value (P4). `compute_sponge_effect` filters on the
floor and returns `min_impressions` plus `queries_below_impression_floor`, so
what was dropped is counted rather than silently absent (P2/P9).
`find_reformat_candidates` now requires `row.get("has_ai_overview") is True` (an
unknown AIO state is not a present one), impressions at or above the floor, and
`ctr < no_aio_median * (1 - margin)`; each candidate carries `impressions`,
`ctr_threshold` and `ctr_margin`, and the table shows the first two. The sponge
section states, above the table, that it is an association between two groups of
queries and not a measured effect, and the candidates section prints the margin
and the floor.

### D5.3 — at risk is bounded by the clicks that exist (D-M-17)

`demand_dashboard._latest_gsc` now selects `ctr, position, start_date, end_date`.
`compute_dashboard` takes `modelled = min(est_ctr_loss, measured ctr)` where GSC
supplied a CTR, and `intercepted = min(clicks, impressions * modelled)`. The
return carries `gsc_window` (`{start, end, mixed}`) and
`render_dashboard_section` prints it with the capped-estimate wording.

### D5.4 — the branded share is about the property (D-M-16)

`gsc_client.GscStats` gained `property_rows`, populated only when a pull happened
and covered the whole property (a cache-only answer or a truncated pull leaves it
`None`). `gsc_demand.compute_demand` takes it and reports both shares:
`branded_click_share` (tracked, unchanged) and `property_branded_click_share`,
with `band_basis` naming which the band came from and `property_available` saying
whether there is a property figure at all. `band_source(cfg)` returns
`gsc_demand.bands.source` or the statement that the two band figures are the
owner's assumption. The score table gained
`property_branded_click_share`, `property_query_count` and `band_basis`, added in
place by `init_demand_tables` for databases written earlier; `get_demand_trend`
reads them, and the Δ is suppressed with a reason when two runs measured
different bases.

### D5.5 — the trend compares like with like (D-M-20)

`aio_exposure.get_aio_exposure_trend` now rolls the runs up in Python so each
point carries `keyword_count`, `comparable` (same keyword set as the newest run)
and `keyword_diff`. `_trend_lines` takes the Δ between the two newest comparable
points, names the keyword count it rests on, and names every excluded run with
what differed (up to `EXCLUSION_NAMES_SHOWN` keywords each way, then a count).

### D5.6 — the modelled constants state their origin (D-M-20)

`aio_exposure.DEFAULT_PROVENANCE` + `resolve_provenance(cfg)` read
`aio_exposure.sources.{aio_ctr_multiplier,citation_credit,ctr_curve}`;
`estimate_caveat(cfg)` replaces the `_ESTIMATE_CAVEAT` constant and prints each
one's provenance. `glossary.yml`'s CTR entry says the same, so the standalone
`docs/glossary.md` and the report's own glossary carry it.

### D5.7 — one country, one device (D-M-20)

`gsc_client.resolve_query_filters(cfg)` resolves `gsc.country` / `gsc.device`,
defaulting to `serpapi.gl` / `serpapi.device`, mapping alpha-2 to the alpha-3
code GSC wants, honouring an explicit `all`, and reporting rather than guessing
an unmappable value. `GscClient` takes `filters`, sends them as
`dimensionFilterGroups`, and includes them in the `gsc_cache` key via a new
`filters` column (added in place; pre-D5.7 rows carry `''` and are not served to
a filtered pull). `generate_report` prints the filters beside the window and adds
a "Mixed populations" warning when either side is unfiltered; `build_sidecar`
records them as `query_filters`.

---

## Verification

- Full suite: `python3 -m pytest test_*.py tests/ -q` → **1907 passed, 68
  skipped, 10 subtests passed, exit 0** (after the cold-review fixes).
- Guards: `tests/test_d5_demand_and_exposure.py`, four classes — one per finding
  fixed (D-M-15, D-M-17, D-M-16, D-M-20), 16 tests. The cold review's cases are
  folded into those four classes rather than given classes of their own, which
  keeps the fix batch at one guard per finding (effort tier Full).
- Mutation check: **19** production changes reverted one at a time (the
  impression floor, the AIO requirement, the CTR margin and its config read in
  two forms, the interception share and the citation credit inside it, the
  zero-click naming, the property band basis and its separate gate, the
  clicking-query count, the privacy note, the band provenance, the trend
  comparability flag, the constant provenance, the dimension filters, the
  known-code check, the cache key, and the population wording). Each failed a
  guard, and each failed only guards covering its own criterion. One mutation
  (the CTR margin read from config) initially failed nothing, because the
  fallback path read config too; the mutation was rewritten to cover both paths
  and a second added for the fallback.
- Pre-existing tests corrected to the new behaviour, with the reason stated in
  each: `tests/test_demand_dashboard.py::test_connected_traffic_at_risk` (the
  uncapped 168), `tests/test_aio_exposure.py::test_av1_9_dirty_state_trend` (two
  runs, different keywords), `tests/test_gsc.py` (positional cache INSERT),
  `tests/test_d2b_failure_is_not_absence.py` (10-impression fixture below the
  new floor).
- Effort (tier Full): code + config 973 lines added, tests 470 (0.48x, ceiling
  2x), prose 365 (0.38x against a 0.3x ceiling — the plan record and the
  methodology/manual/config-reference updates mandated by CLAUDE.md account for
  it, as in D4c).
- Reference report against a true HEAD baseline
  (`git stash push` of the six changed source files, regenerate, `stash pop`):
  nine changed lines, all intended — the Δ line now names the run and the
  keyword count, three non-comparable runs are named as excluded, the estimates
  caveat states each constant's provenance, and the glossary's CTR entry says
  the same. Regenerated after the cold-review fixes: the same nine lines. The
  demand section and the connected-traffic dashboard are absent from this
  reference report, because the run it was built from has no GSC data — those
  two sections are covered by their guards, not by this diff.

---

## Cold review

A cold `learning-qa` pass over the D5 diff (effort tier **Full** — the change
touches the GSC fetch, its cache and three report sections, so code that can
break something) returned ten findings. The eight medium-or-higher ones are
fixed; the two low ones are dropped per the tier and recorded below as adjacent
issues.

Fixed:

1. **The measured-CTR cap was dead code, and the model was the wrong quantity**
   (P19). The at-risk estimate was `impressions × min(est_ctr_loss,
   measured_ctr)`, capped at the measured clicks. GSC's `ctr` is exactly
   `clicks / impressions`, so for every keyword whose measured CTR sat below the
   modelled CTR-point loss the product was `clicks` — the cap never bound and
   the report said the client's whole click count was at risk. Replaced with
   `aio_exposure.interception_share`, the position-free form of the model
   (`aio_ctr_multiplier`, reduced by `citation_credit` where cited) applied to
   the measured clicks, which is bounded by them by construction and needs no
   cap. `test_connected_traffic_at_risk` moved 100 → 60.0 with the reason in the
   test.
2. **The filter resolver was being imported across the isolation boundary.**
   `demand_dashboard` has to scope its cache read to the configured population,
   but `tests/test_gsc.py::test_pipeline_never_imports_gsc_client` (G.4.4)
   forbids the read side pulling in `gsc_client`. A first attempt used
   `importlib.import_module` inside the function, which still loads the client
   into the process. Extracted the resolution into a new `gsc_filters.py` —
   config reading only, no network, no heavy imports — re-exported by
   `gsc_client` and imported directly by `demand_dashboard`.
3. **`filters` was a plain column, not part of the cache key.** Two
   configurations could not coexist: the second pull overwrote the first's row
   for the same query and window. `filters` is now in the PRIMARY KEY, and
   `_init_cache_table` migrates a table that lacks either the column or the key
   (rename → recreate → `INSERT OR REPLACE ... SELECT` → drop), recording
   carried rows as unfiltered.
4. **An absence under a filter was still worded as an absence.** A query whose
   traffic is all mobile has no row in a desktop pull, and the per-query cell,
   the coverage count and the completion line all called that "no impressions"
   with no mention of the population. `gsc_messages.yml` gained
   `measured_absent.population_suffix` and a `{population}` placeholder in the
   two lines. Such a query is still cached as an absence, which is correct now
   that the cache key carries the filter: it is an absence *for that
   population*, and a pull for another one does not read the row.
5. **The property figure was gated on the tracked set.** `reportable` required
   `data_available` (the tracked rows having clicks), so a keyword file that
   matched no clicking query discarded a complete property-wide measurement —
   the exact case D5.4 exists for. The two are gated separately now
   (`property_available` / `data_available`, either making the section
   reportable).
6. **`property_query_count` counted every query in the property rows**, clicks
   or not, while the share it sits beside is over clicking queries only.
   `_property_split` now returns the clicking-query count.
7. **The branded share leans branded and the report did not say so.** Search
   Console withholds rare queries to protect searchers' privacy; those are
   mostly long-tail and generic, so a share computed over what it does return
   is biased by an amount nobody can measure. `render_demand_section` states
   this with the figure.
8. **An unrecognised country code was sent to GSC anyway.** GSC accepts an
   unknown dimension filter, returns no rows, and every query would then have
   been cached as measured absence — D-C-02 again, through the new path. Only
   codes in `gsc_filters.KNOWN_ALPHA3` are sent; anything else is reported and
   the filter left off.

Dropped (low), and so **adjacent issues found, not fixed**:

9. `gsc_window` is computed over the whole cache rather than the rows that
   produced the printed figures, so an unrelated cached query can set
   `mixed = True` or widen the printed span.
10. The exposure trend's coverage denominator is distinct normalised keywords
    while its numerators are row sums, so a duplicate row for one run (a second
    `source`, two profile keys differing only in case) could push
    `aio_coverage_pct` above 100.
