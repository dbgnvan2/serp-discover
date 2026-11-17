# Chunk D2 — Null is not zero: implementation plan

Status: **decisions settled 2026-11-16, awaiting go-ahead to code.** No
implementation code written.
Plan written 2026-11-16, against `9c9f6e6`.
Source: `docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md` chunk D2.
Effort tier: **Full** (`standards/effort-budget.md`) — data path, external
calls, scoring. Tests for the change, full sweep budget, one cold
`learning-qa` pass before each push.

## The one fault, in nine places

Every finding in D2 is the same mistake: a value that was never measured is
written down as a measured zero or a measured negative. DataForSEO sends no
`rank` for a domain it has not crawled, and the client coerces it to `0`; a
Google Search Console 503 produces no rows, and the absence is cached as
"this query has no demand"; a Cloudflare block page returns 403, and its body
is parsed as the competitor's content. Each one then propagates. `gap =
avg_serp_da - client_da`, so a DA of 0 drags the competitor mean down, which
*shrinks* the apparent gap, which flips a verdict toward feasible: the tool
recommends chasing a keyword held by DA-90 directories because the domains
nobody scored were counted as having no authority. The same zeros also reach
the pivot gate, and a flipped verdict queues a paid Maps fetch.

## Verified current state

Each item below was read in the code at `9c9f6e6`, not taken from the
workplan's line numbers (which have moved). Two items the workplan lists are
already partly closed by D1's follow-up, and one of its instructions now
conflicts with what shipped — see **Decisions** below.

| Finding | Where it is now | Open? |
|---|---|---|
| D-C-04 / D-M-02 | `dataforseo_client.py:206` `int(item.get("rank") or 0)`; `moz_client.py:335-336` `int(... or 0)`, whose docstring records the `or 0` as a deliberate deferral ("spec decision gate D-3") | open |
| D-C-03 / D-M-08 | `feasibility.compute_feasibility([])` already returns `"Not Measured"` and `select_competitor_das` already drops `None` (D1 follow-up). Still open: the per-run `da_data_available = bool(da_metrics)` at `run_feasibility.py:337`, the ungated pivot queue, `da_count`/`da_missing`, the N-of-M rendering, the `da_count < 5` rule | part open |
| D-M-05 | `run_feasibility.py:287` `client_da = ... feasibility_cfg.get("client_da", 35)`; no `da_provider` tag exists anywhere in the repo | open |
| D-C-02 | `gsc_client._fetch_all_rows` `break`s on a non-OK response and returns partial rows; the caller then builds `{q: None}` and calls `_cache_store`, so a 503 is cached as absence for the TTL | open |
| D-C-10 | `moz_competitor._fetch_one` returns `STATUS_OK` when *any* sub-call produced items; `fetch` caches that whole block, so ranking-OK + anchors-5xx is cached 30 days as `ok` and the failed sub-call never refetches | open |
| D-C-08 | `EntityClassifier.classify` tests `domain in self.overrides` and `domain_l in self.overrides` with no `www.` strip, while `generate_domain_override_candidates.normalize_domain` does strip it — the two disagree | open |
| D-C-20 | `serp_audit.py:1499` `if fetch_res:` is true for 403/429/5xx; `extract_features` then parses the error body. The status code is already in hand at `:1511` and does not gate anything | open |
| D-C-21 | `parse_data` sources the overview from `google_ai_overview_probe` (`serp_audit.py:802-807`) — the *no-location* fallback probe — and sets `Has_Main_AI_Overview` from it. `ai_overview_mode` is recorded on `aio_log` only, so no consumer can tell the two apart | open |

## Decisions needed before coding

**1. One label for one state.** Two strings mean "no DA was measured":
`"Not Measured"` (shipped by D1, in `feasibility.StatusLiteral`, `glossary.yml`,
`generate_insight_report.py:1622`) and `"No DA Data"` (`run_feasibility.py:390`
and its own emoji map at `:511`). The workplan's D2 bullet says
`compute_feasibility(da, [])` should return `"No DA Data"`, which would now
reverse D1. **Proposed:** standardise on `"Not Measured"`, retire
`"No DA Data"` with a one-line note in the workplan recording the deviation
from its own instruction. This is a routine call and I will take it unless told
otherwise.

**2. `client_da` provenance (D-M-05) — DECIDED: look it up.** The client's
domain is looked up through the active provider in the same batch as the
competitors, so both sides of the gap come off one scale. The `config.yml`
value becomes an override, logged with the provider and the date it was
measured. Every row carries `da_provider`, and a trend never mixes providers.
This costs one paid row per run and **changes the published gap on every
keyword** — the code's own example puts the client at 19 on DataForSEO against
the 35 in config. Criteria: D2a.12-D2a.14 below.

**3. Push shape — DECIDED: three pushes.** D2a (providers + verdict), D2b (the
two caches), D2c (classifier + the two flags). Each self-contained, with its
own tests and its own cold `learning-qa` pass. This is a deliberate deviation
from the workplan's "one chunk = one push", and will be recorded there as one.

## Acceptance criteria → the test that verifies each

Every criterion below names the automated test that proves it. All external
calls are mocked, per `CLAUDE.md` ("Tests do not require API keys").

### D2a — The providers and the verdict (the root; everything else reads it)

| ID | Criterion | Test |
|---|---|---|
| D2a.1 | DataForSEO returns `da: None` for an item with no `rank`, never 0 | `tests/test_d2_null_is_not_zero.py::TestDataForSEO::test_d2a1_absent_rank_is_none_not_zero` |
| D2a.2 | A `None` DA is cached as SQL `NULL` and read back as `None`, and the domain still counts as fetched (no refetch inside the TTL) | `::TestDataForSEO::test_d2a2_a_none_is_cached_as_absence_not_as_zero` |
| D2a.3 | Moz returns `da: None` / `pa: None` for absent values; the `or 0` docstring at `moz_client.py:330-336` is corrected in the same change | `::TestMoz::test_d2a3_absent_authority_is_none`, plus a source guard `::test_d2a3_the_docstring_no_longer_claims_or_zero` |
| D2a.4 | `rank: null` is absent from both the returned result and the cache table (workplan's own test) | `::TestDataForSEO::test_d2a4_null_rank_absent_from_result_and_cache` |
| D2a.5 | `run_feasibility` decides DA availability **per keyword**, not per run: a keyword with records is scored even when others have none, and a keyword with none reads "Not Measured" even when the run as a whole got data | `::TestPerKeywordAvailability::test_d2a5_one_measured_keyword_does_not_score_the_unmeasured_ones` and `::test_d2a5_one_unmeasured_keyword_does_not_blank_the_run` |
| D2a.6 | Every feasibility row carries `da_count` and `da_missing`, and they reconcile: `da_count + da_missing == len(window)` | `::TestCoverageCounts::test_d2a6_counts_reconcile_with_the_window` |
| D2a.7 | `da_count < 5` → `"Not Measured"`, not a verdict from four domains | `::TestCoverageCounts::test_d2a7_four_measured_domains_is_not_a_verdict` |
| D2a.8 | A pivot job is queued only when `gap is not None`; an unmeasured keyword queues no paid Maps fetch | `::TestPivotGate::test_d2a8_no_pivot_job_without_a_gap` |
| D2a.9 | §5c and `feasibility_*.md` render "mean of N of M ranking domains (K unscored)" | `tests/test_markdown_rendering.py::test_d2a9_coverage_is_rendered`, `test_report_sections.py::test_d2a9_section_5c_states_coverage` |
| D2a.10 | One label for one state: `"No DA Data"` appears nowhere in the Python sources | source guard `::TestOneLabel::test_d2a10_no_second_label_for_an_unmeasured_verdict` |
| D2a.11 | `play_routing` maps the unmeasured status to `unknown` with `data_available.feasibility False` | `tests/test_play_routing.py::test_d2a11_unmeasured_routes_to_unknown` |
| D2a.12 | The client's own domain is looked up through the active provider in the same batch as the competitors, and that value is what the gap uses | `::TestClientProvenance::test_d2a12_the_client_da_comes_from_the_provider` |
| D2a.13 | A `config.yml client_da` is an override, not the default: when set it is used, and the run logs the value, the provider it overrode and the date | `::TestClientProvenance::test_d2a13_config_is_an_override_and_is_logged` |
| D2a.14 | Every feasibility row carries `da_provider`; a trend never mixes two providers' values | `::TestClientProvenance::test_d2a14_rows_are_tagged`, `::test_d2a14_no_cross_provider_trend` |
| D2a.15 | When no provider is reachable, the client DA is not fabricated from config and silently compared: the row reads `"Not Measured"` and says why | `::TestClientProvenance::test_d2a15_no_provider_is_not_a_measurement` |

### D2b — The caches that remember a failure as a fact

| ID | Criterion | Test |
|---|---|---|
| D2b.1 | `gsc_client._fetch_all_rows` returns `(rows, complete)`; `complete` is False on any non-OK response or network failure | `::TestGSC::test_d2b1_a_partial_pull_reports_incomplete` |
| D2b.2 | Absences are cached **only** when `complete`; a 503 writes no `found=0` row and the next call re-POSTs | `::TestGSC::test_d2b2_a_503_caches_nothing_and_refetches` (the workplan's own test) |
| D2b.3 | `run_gsc_analysis` prints "GSC fetch failed — N queries not measured" instead of the absent line | `::TestGSC::test_d2b3_the_failure_is_reported_not_rendered_as_zero_demand` |
| D2b.4 | `gsc_demand.save_demand` writes no trend point for a failed fetch (a trend of fabricated zeros is worse than a gap) | `::TestGSC::test_d2b4_no_trend_point_from_a_failed_fetch` |
| D2b.5 | `moz_competitor._cache_store` runs only when every **enabled** sub-call is `ok`/`no_record`; otherwise the OK sub-blocks are stored and the failed one refetches next run | `::TestMozCompetitor::test_d2b5_a_failed_subcall_is_not_cached_as_ok` and `::test_d2b5_ranking_ok_plus_anchors_5xx_reposts_anchors` (the workplan's own test) |
| D2b.6 | `_fetch_one`'s block-level `status` is not `ok` when a sub-call errored | `::TestMozCompetitor::test_d2b6_partial_is_not_ok` |

### D2c — Classification and the two flags

| ID | Criterion | Test |
|---|---|---|
| D2c.1 | `EntityClassifier.classify` normalises the host once (lower-case, strip `www.`), so `classify("www.x.ca") == classify("x.ca")` for **every** entry in `domain_overrides.yml` | `::TestOverrideNormalisation::test_d2c1_every_override_matches_with_and_without_www` (parameterised over the real file) |
| D2c.2 | The pipeline, `refresh_analysis_outputs` and the override-candidate report agree on one normalisation — one definition, asserted by source guard | `::TestOverrideNormalisation::test_d2c2_one_normaliser` |
| D2c.3 | Enrichment treats `status_code >= 400` as not enriched: `Fetch_Status` carries the code, page-level fields read `Not Measured`, and no HTML is parsed | `::TestErrorPages::test_d2c3_a_403_page_is_not_content` (workplan's: status 403 → `Content_Type N/A`) |
| D2c.4 | The run counts and logs "N of M pages blocked" (P2) | `::TestErrorPages::test_d2c4_blocked_pages_are_counted` |
| D2c.5 | `AI_Overview_Mode` is carried onto the overview row, not only `aio_log` | `::TestAIOProvenance::test_d2c5_the_mode_reaches_the_row` |
| D2c.6 | `Has_Main_AI_Overview` excludes `fallback_without_location`; a separate flag carries the fallback observation so it is not lost | `::TestAIOProvenance::test_d2c6_a_no_location_probe_is_not_the_local_overview` |

## Implementation order and dependencies

Three pushes, in this order.

1. **D2a** first and alone. `select_competitor_das` already drops `None`, but
   no provider can currently return one, so the D1 fix is inert until this
   lands. Everything numeric in the report moves when it does.
2. **D2b** is independent of D2a (different subsystems: GSC, Moz competitor)
   and can follow in either order.
3. **D2c** last: D2c.1 changes which overrides fire, which changes
   `Entity_Type` across the corpus, so it should land after the numbers have
   settled rather than mixed in with them.

## D2a as built (2026-11-16)

All fifteen criteria implemented. Suite: **1668 passed, 72 skipped, exit 0**
(1621 before; 47 new tests in `tests/test_d2_null_is_not_zero.py`).

Deviations from the plan above, and why:

1. **`select_competitor_das` became `competitor_da_window`,** returning a
   `DAWindow(das, measured, missing, window)` rather than a bare list. The
   coverage has to come out of the same loop that builds the window: a second
   function counting the denominator would be a second definition, and the two
   would drift. The rename is why 19 existing tests moved.
2. **The D2a.9 tests live here, not where the plan named them.**
   `tests/test_markdown_rendering.py` drives archived-run fixtures that are
   gitignored and skipped without a real run, and `test_report_sections.py`
   does not exist. Both are `::TestRendering` in
   `tests/test_d2_null_is_not_zero.py`.
3. **The causal claim in "The one fault" was backwards and is corrected
   above.** `gap = avg_serp_da - client_da`, so fabricated zeros drag the
   competitor mean down and *shrink* the gap: they made hard keywords look
   winnable. The same reversed wording was in the `dataforseo_client` comment
   and the `moz_client` docstring and is corrected in both.
4. **`feasibility_messages.yml` was not in the plan.** The CLAUDE.md editorial
   rule required it: `no_measurement_text` was about to put user-facing prose
   in Python, and the status-icon map was already hardcoded in four places. It
   also bought back the lines `serp_audit.py` needed under its 2200-line cap.
   `MIN_DA_FOR_VERDICT` stays in Python — a threshold, not wording.
5. **Three things fixed in passing, each the same fault as a D2a criterion:**
   - the pivot pass printed the *previous* keyword's status icon
     (`feas[...]` where `pivot_feas[...]` was meant);
   - the feasibility report's Summary counted High/Moderate/Low but not
     "Not Measured", so the four totals disagreed with the keyword count;
   - its "no DA data" note was all-or-nothing and named only `MOZ_TOKEN`
     though DataForSEO is primary. One scored keyword silenced it for the
     other nine — the same per-run-not-per-keyword fault as D2a.5.
6. **Two helpers extracted for one definition:** `with_client_url` (the client
   rides in the competitors' batch) and `client_da_from_batch`, because the
   in-pipeline and standalone passes each had their own copy.
7. **`glossary.yml`'s "DA gap" definition had the formula reversed** against
   the code and is corrected; new entries cover `da_count` / `da_missing`,
   `da_provider`, `client_da_source`, "DA coverage" and "Not measured".
   `docs/glossary.md` regenerated.

## The cold review pass, and what it found (2026-11-16)

A `learning-qa` pass over the D2a diff returned 11 findings, all medium or
higher. Every one is fixed; the working process requires it. Each had a guard
added in `tests/test_d2_null_is_not_zero.py`.

1. **F1 — the window was filtered before it was sliced, in three producers.**
   `url_window` dropped unusable rows and *then* the window was taken, so
   ranks 11, 12 … slid into a set every output calls "the top 10" AND the
   real denominator was discarded: a 6-of-10 window published
   `da_missing=0` beside "mean of all 6 ranking domains" — the exact claim
   D2a exists to stop, from the code that was meant to stop it. Same fault in
   `_get_organic_urls_by_keyword` (which printed `10/10`) and
   `_fetch_pivot_organic_urls`. All three now slice, then filter, then count
   the holes, through `URLWindow`. One further fault surfaced here: a
   `URLWindow` passed to `with_client_url` would have put hole counts into
   the provider's target list. `feasibility.usable_url` is now the one
   definition of "this position has no URL" — one of the three call sites
   tested only for emptiness, so an `"N/A"` reached the fetch batch.
2. **F2 — `gap is None` was the wrong gate.** A thin window has a real gap,
   so a "Not Measured" row reached `generate_hyper_local_pivot` and was
   answered with "Current keyword is feasible. No pivot required." The gate
   is now the status, and the refusal is *inside*
   `generate_hyper_local_pivot` as well, because `serp_audit`'s in-pipeline
   pass calls it unconditionally and a caller that forgets must not be able
   to publish the false sentence.
3. **F3 — the honest explanation was written and rendered nowhere.**
   `no_measurement_text` went into `row["strategy"]`, whose only consumer is
   the Low Feasibility block that a "Not Measured" row never enters. It now
   has its own field, `no_measurement_reason`, and a **Not measured — why**
   section in both report writers.
4. **F4 — absent coverage rendered as `0/10`.** A legacy row with no
   `da_count` printed a fabricated denominator beside a real mean, and a
   config client DA printed bare as though measured. Absent is now a third
   state ("coverage not recorded for this run" / "—"). The test that passed
   through this asserted only "does not crash"; it now asserts the rendering.
5. **F5 — nothing counted the new nulls at the provider boundary.**
   `len(da_metrics)` counts records, not measurements, so the run logged
   "returned DA for 3 URLs" when none carried a figure and `if not
   da_metrics:` never fired on a batch that measured nothing.
   `feasibility.batch_coverage` is the one definition of that count, used by
   both DA clients and the standalone run.
6. **F6 — a cached absence was held for the full 30-day TTL** with no
   re-check path, so a keyword read "Not Measured" for a month after the
   figure became available (P1: a transient absence held as terminal).
   Absences now expire on `moz.negative_cache_ttl_days` (default 7, clamped
   to the positive TTL) in both clients. Recorded honestly in
   `dataforseo_client`: that DataForSEO encodes "no rank" as a missing or
   null `rank` is **unverified against a live response** — the premise comes
   from the synthetic payload in
   `probes/discover/probe_03_dataforseo_null_rank.py`. The branch keeps a
   numeric rank and turns anything else into `None`, so an unseen shape
   degrades to "not measured" rather than to a fabricated 0.
7. **F7 — the report drew conclusions a withheld verdict refuses to draw.**
   `_why_this_keyword` printed "they are stronger than you" off a mean over
   two of ten domains; `_rank_keywords` gave "Not Measured" the same rank as
   never-attempted, saying an unmeasured keyword is a *worse* bet than one
   measured as hard; and `_get_best_opportunity_keyword` could name an
   unmeasured keyword as the single best opportunity. The direction is now
   withheld and the coverage stated, measured rows state their coverage too,
   unknown ranks above absent, and §0 recommends only off a verdict.
8. **F8 — the brief's prompt could not see the unmeasured keywords.**
   `_build_feasibility_summary` bucketed only the three verdicts, so an
   unscored keyword was absent with no count and the LLM saw a ten-keyword
   run as a three-keyword one. It now carries `not_measured` (with each
   keyword's coverage) and an `n of m` count.
9. **F9 — the coverage reached every output except the one rank history
   reads.** `keyword_feasibility` gained `da_count`, `da_missing`,
   `da_provider` and `client_da_source` (migrated with `ALTER TABLE`; old
   rows hold NULL, which is "not recorded", never 0 of 0), and `client_da`
   is documented as nullable. Rows are now written by
   `storage.save_feasibility_from_row`, which takes the assessment dict
   whole — re-listing the fields at each call site is how two new fields came
   to be dropped on the way to the database. That extraction also returned
   15 lines to `serp_audit.py` under its 2200-line cap.
10. **F10 — `MIN_DA_FOR_VERDICT` was a literal**, and its own test pinned the
    value rather than proving the config key is read. It is now
    `technical.min_da_for_verdict` (default 5), documented in
    `docs/config_reference.md`, and the test reloads the module against a
    config setting 3 and checks the verdict gate moved with it.
11. **F11 — the messages path could abort §5c**, which is deliberately
    outside `_safe_section`. `_render` catches a malformed template and falls
    back; `_as_count` keeps a non-count out of the arithmetic.

**Not verifiable here (blocker on verification, not implementation):** no DA
provider is reachable from this machine — `DATAFORSEO_LOGIN` /
`DATAFORSEO_PASSWORD` are absent from `.env` and Moz returned nothing on
2026-11-14 — so D2a cannot be exercised end-to-end against a live provider.
Every path is covered by mocked tests. **Owner work:** re-run
`run_feasibility.py` and the briefs over every `market_analysis_*.json` still
relied on; their feasibility figures were computed with absences as zeros.

## Criteria that cannot be made code-testable

- **The scale question behind D-M-05.** That DataForSEO `rank` and Moz
  `domain_authority` are different scales is a fact about two vendors, not
  about this code. No test can assert it. **Proposed human review:** a
  paragraph in `docs/feasibility.md` stating it, with the code's own 19-vs-35
  example, plus the mechanical test that a trend never mixes `da_provider`
  values (D2a.14).
- **End-to-end confirmation against live data.** No DA provider is reachable
  (`DATAFORSEO_LOGIN`/`PASSWORD` absent from `.env`; Moz returned nothing on
  2026-11-14), and every `market_analysis_*.json` on disk came from the
  wrong city with wrapped links. So D2a can be proven against mocks and
  archived fixtures but **cannot** be verified end-to-end in this chunk. This
  is a blocker on verification, not on implementation; it is recorded here
  rather than worked around, and the chunk's status report will say so.

## Probes the workplan expects to flip

`probe_02`, `probe_03`, `probe_04`, `probe_05` (part B),
`discover_method/p07`. These read archived **outputs**, so they can only stop
reproducing after a re-run with a reachable provider — the owner work above.
The live code paths they exercise will be covered by the tests named here.

## Adjacent issues already visible, to be flagged not fixed

- `moz_client._map_site_metrics`'s docstring cites "spec decision gate D-3" as
  the reason for `or 0`. That gate is what D2a.3 reverses, so the spec document
  holding it needs the same correction — a documentation change in the same
  push, per the standing rule that a behaviour change updates every document
  describing it.
- `run_feasibility.py` carries its own emoji map for feasibility statuses
  (`:511-512`) duplicating `generate_insight_report.py:1622`. One table,
  two copies — editorial content that belongs in a config file.
