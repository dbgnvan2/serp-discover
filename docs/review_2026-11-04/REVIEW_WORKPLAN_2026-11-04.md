# serp-discover + serp-compete — Review Work Plan (2026-11-04)

**Status:** proposed — for the owner to review, then for a coding agent to implement chunk by chunk.
**Scope:** correctness / data-path (P1–P22 class) and methodology validity of both tools. Not covered: style, GUI ergonomics, test-coverage breadth, architecture refactors (beyond what a fix needs).
**Method:** four independent review passes in a cloud sandbox on a copy of both repos (source only; no `venv`, outputs, databases or secrets). Every finding carries `file:line` evidence; **79 of 87 are CONFIRMED by a probe script or an exact trace**, the rest are PLAUSIBLE (strong code reading, not reproduced). The probes are shipped alongside this plan so each fix can start from a failing reproduction and end with the same probe passing (or, better, converted into a test).
**Canonical copy:** `serp-discover/docs/review_2026-11-04/`. The same plan is in `serp-compete/docs/review_2026-11-04/`; edit the discover copy and re-sync.

## Package contents

```
docs/review_2026-11-04/
  REVIEW_WORKPLAN_2026-11-04.md      ← this file
  discover_correctness.md            22 findings D-C-01..22  (S1×5, S2×10, S3×7)
  discover_methodology.md            27 findings D-M-01..27  (WRONG 15, HEURISTIC 6, PROVENANCE 3, DRIFT 4)
  compete_correctness.md             18 findings C-C-01..18  (S1×4, S2×8, S3×6)
  compete_methodology.md             20 findings C-M-01..20  (WRONG 10, HEURISTIC 7, DRIFT 2, PROVENANCE 1)
  probes/discover/*.py               reproductions for D-C-*  (mocked external calls)
  probes/discover_method/*.py        reproductions for D-M-*  (run against tests/fixtures/market_analysis_reference_run.json)
  probes/compete/*.py                reproductions for C-C-*
  probes/compete_method/*.py + *_output.txt   reproductions for C-M-* and their captured output
```

Probe scripts were written against `/home/claude/review/<repo>` and have been path-rewritten to `/Users/davemini2/ProjectsLocal/<repo>`. Run them from the repo root with the repo venv active; compete probes need `PYTHONPATH=Serp-compete`. They are throwaway reproductions, not tests — the plan below says which ones to promote.

## Local verification, 2026-11-14

Run on davemini2 before any of this was handed to a cloud agent, and limited to
the checks that need local-only artifacts: `raw/`, `serp_data.db` and `.env` are
all gitignored, so no cloud session can do them.

**H1 re-confirmed on real data, as the plan asked.** Three independent ways:

- `raw/20260828_143328/google_response.json` — the archived merged SerpAPI
  response, `pagination_pages_fetched: 3` — carries 28 organic rows whose
  `position` runs `[1..9, 1..10, 1..10]`.
- `_merge_google_pages` (`serp_audit.py:401`) appends each page's items verbatim
  and `serp_audit.py:941` stores `item["position"]` as `Rank`. There is no
  offset on either path.
- `serp_data.db`, run `20260828_143328`: every keyword holds three rows at rank
  1, three at rank 2, and so on — `childhood emotional neglect` has rank 1 three
  times. `probe_01` against current code reports `client_rank = 7` while 17
  competitors sit above the client, `top5_organic` ranks `[1, 1, 1]`, and
  `run_feasibility`'s "top 10" resolves to true merged positions
  `[30, 31, 32, 33, 39, 40, 41, 42, 49, 50]`.

**The probes still hold against current code (`f99c095`).** All ten
`probes/discover/*.py` reproduce their findings; all ten
`probes/discover_method/*.py` run and print the evidence their findings cite.
That keeps D-C-01, 02, 03, 04, 05, 07, 08, 09, 10, 11 and 14 live — none of them
has gone stale.

**`serp_results` still has no `query_label` column**, so D-C-22's remedy is
needed as written.

**D-C-16 is already fixed.** `abcc2aa fix(tests): make the cache-freshness test
independent of the calendar` applies exactly the fix the finding proposed, and
`test_moz_competitor.py::TestCollectionFreshness` passes (2 passed). `probe_05`
still prints the old premise because it carries its own copy of the hard-coded
date. Close D-C-16; do not re-fix it.

**Treat the plan as 10 days stale.** Nine commits landed on 2026-11-14 in the
same area — `abcc2aa`, `45bda18`, `e161b91`, `eba59f5`, `4120705`, `c7778b0`,
`0864d58`, `ca7851a`, `f99c095` — touching `serp_audit.py`, the launcher,
SerpAPI timeouts and pipeline exit codes. D-C-06, D-C-13 and D-C-20 may be
partly addressed by them. So every chunk begins by running its probes and
confirming the finding still reproduces; one that no longer reproduces is closed
with that evidence rather than re-fixed.

Not verified locally: the compete findings (separate repo, and its baseline ran
clean in the cloud without needing any local-only artifact), and the unprobed
discover items D-C-06, 12, 13, 15, 17, 18, 20, 21 and 22.

## Baseline (what the suites say today)

| Repo | Command | Result (Python 3.13, cloud) |
|---|---|---|
| serp-discover | `python3 -m pytest test_*.py tests/ -q` | 1359 passed, 102 skipped, **1 real failure** (`test_moz_competitor.py::TestCollectionFreshness::test_cached_block_reports_when_it_was_collected_not_now` — a date-bomb in the test, not a cache bug; see D-C-16), plus 3 failures + 1 error that are tkinter-missing (ignore in headless venv) |
| serp-compete | `python3 -m pytest -q` (pytest.ini runs both suites) | 440 passed (needs `spacy` + `en_core_web_sm`) |

The green suites are not evidence of correctness for the items below: most of the S1 findings are in paths the tests lock to the wrong shape (e.g. `test_serp_audit.py:391-395` models SerpAPI page 2 as `position: 11`; `serp-compete/tests/test_api_clients.py:39` mocks a Moz response key the API doesn't return).

---

## 1. The headline — read this before anything else

Three findings invalidate numbers in every report either tool has ever produced. They are cheap to fix and everything else is downstream of them.

**H1 · serp-discover ranks are page-relative (D-C-01 = D-M-01, S1, CONFIRMED on the committed reference run).** SerpAPI's `position` restarts at 1 on each paginated page; `serp_audit.py:941` stores it verbatim as `Rank` and `_merge_google_pages` (`serp_audit.py:401`) concatenates pages without an offset. In Balanced mode (3 pages) the reference run carries Rank sequences `[1..9, 1..10, 1..10]`. Every "top-10" is therefore ~the first 3–4 results of each of three pages: the intent verdict, title patterns, entity mix, feasibility mean, `client_rank` (the 2026-08-26 brief told the owner "client ranks #7" for a page-3 result), AIO CTR-loss, rank-history deltas, and the handoff's `rank` / `primary_keyword_for_url` that serp-compete consumes. **Re-confirm on one raw `raw/{run_id}/` SerpAPI response before coding** (the fixture is a trimmed copy; the agent that found this asked for that check and I agree).

**H2 · "No data" is coerced to zero, in both tools, and then averaged, cached and alerted on.** serp-discover: DataForSEO `rank: null` → DA 0 (`dataforseo_client.py:206`), Moz `or 0` (`moz_client.py:334`), a keyword with no scored competitors → "Low Feasibility" (`feasibility.py:86-93`), skipped AI engines → AIVI 0 persisted and ranked #1 priority (`probe_ai_visibility.py:1002-1014`), a GSC 503 → every query cached as `found=0` for the TTL (`gsc_client.py:174-178`). serp-compete: a Moz failure → PA 0 → "Fragile Magnet — publish now" with drift −35 (`main.py:401-412, 453`), a failed volume call → "0 branded demand" (`brand_demand.py:84-92`). These are D-C-02/03/04/05, D-M-02/03/08, C-C-03/11, C-M-06. The owner's own principle ("state absence, don't fake it") is implemented in the *rendering* layer of both tools and bypassed in the *data* layer.

**H3 · serp-compete does not audit what the handoff says (C-M-01, CONFIRMED).** `main.py:386-393` groups the handoff targets by domain and discards them; it audits each domain's DataForSEO `ranked_keywords/live` top-10 (Canada, API default order, no position filter — `api_clients.py:17-45`). `group_targets` is never read. run_11's "Traffic Magnets" are "archdiocese of vancouver", "airport heights medical clinic" (a St John's NL page), "555 homer street". Every downstream section — vacuums, reframes (gpt-4o spent on the Archdiocese), overlap cells, barbell top-10 counts, velocity, cliff — inherits that universe. FEATURE_GUIDE §2.1 says "nothing is invented". **This is a design decision for the owner, not a patch** (see §4, decision 1).

---

## 2. Ordering principle

1. Fix data shape before data semantics (H1 before any metric that uses rank).
2. Fix null-vs-zero before any alert or composite (H2 before velocity/AIVI/feasibility work).
3. Fix the audit universe before any serp-compete scoring work (H3 before vacuums/overlap/barbell).
4. Then correct the metrics that are wrong; then label the ones that are heuristic; then provenance and docs.
5. One chunk = one push. Each chunk lists the probes that must flip from reproducing to not reproducing, and the tests that lock it. Judge test runs by exit code (CLAUDE.md P24).
6. `docs/methodology.md` (discover) and `docs/FEATURE_GUIDE.md` §9 (compete) are contracts: every chunk that changes a metric updates them in the same push. Regenerate `docs/spec_coverage.md` (discover) after spec-driven chunks.

---

## 3. Chunks

Effort: S (< ½ day), M (½–1 day), L (1–2 days) for an agent with the repo loaded. Severity/impact as in the finding files.

### serp-discover

#### Chunk D1 — Absolute rank (H1)
*Findings:* D-C-01/D-M-01 (S1), D-C-19 (S3, two feasibility producers), D-C-22 (S3, rank history pollution). *Effort:* M.
- `_merge_google_pages`: compute `absolute = organic_rows_merged_so_far + i` (or `start` from `serpapi_pagination`) and store it as `Rank`; keep the raw per-page `position` in a new field. Same for `_merge_maps_pages` if maps rank is consumed.
- Audit every consumer of `Rank`/`rank`: `serp_audit.py:1547` (enrich `rank_val <= MAX_URLS_TO_ENRICH` — currently enriches ~14 pages/keyword, not 5), `:1530` (SQLite), `brief_data_extraction.py:1368,1698,1736,1781`, `run_feasibility.py:225-242`, `handoff_writer.py:116`, `metrics.py:137`, `aio_exposure.py:219`.
- D-C-19: route the in-pipeline feasibility (`serp_audit.py:1604-1631`, client URL included, `A.1/A.2` rows) through the same helper as `run_feasibility.py:333-339` (client excluded, label A only); make all consumers use `index_feasibility_by_keyword`.
- D-C-22: write the `runs` row (or a `completed` flag) only at run end; `metrics.py` picks the previous *completed* run; store `query_label` in `serp_results` and filter `= 'A'` in `metrics`.
- Config: `serpapi.num: 100` / `google_max_results: 300` are stale (Google serves ~10/page); document that 3 pages ≈ top 30.
- *Tests:* two pages with `position 1..10` each → merged `1..20`; fixture test `max(Rank) == len(rows)` per keyword; fix `test_serp_audit.py:391-395` (page-2 `position` must be 1, not 11); pipeline feasibility rows == standalone rows for the same organic set.
- *Probes to flip:* `probes/discover/probe_01_pagination_rank.py`, `probes/discover_method/p02_fixture_ranks.py`, `p03_page_evidence.py`, `p09_handoff_rank_mix.py`.
- *After:* re-run `run_feasibility.py` and the brief on every `market_analysis_*.json` the owner still relies on; previous `client_rank`, feasibility and handoff files are wrong.

#### Chunk D2 — Null is not zero (H2, discover side)
*Status (2026-11-16):* split into three pushes. **D2a is done** — commit
`9784690`, closing D-C-03, D-C-04, D-M-02, D-M-05, D-M-08; the plan, the
15 acceptance criteria as built, and the 11 cold-review findings are in
`PLAN_D2_null_is_not_zero.md`. **D2b is done** — closing D-C-02 and D-C-10;
the plan, its 16 acceptance criteria as built and the three faults found
while building are in `PLAN_D2b_a_failed_fetch_is_not_an_answer.md`. Both
caches now record whether the provider answered, not only what it said:
GSC caches an absence only on a completed fetch, and the Moz competitor
cache is per signal with its own timestamps, so one failed sub-call costs
one call next run instead of freezing four for 30 days. **D2c is done** —
closing D-C-08, D-C-20 and D-C-21; the plan and its 14 acceptance criteria
as built are in `PLAN_D2c_one_host_one_answer.md`. `domain_utils.normalize_domain`
is now the one definition of a host, so all 121 overrides answer for `x.ca`
and `www.x.ca` alike; a response at or above 400 is recorded and not read,
with the outcome on every row as `Fetch_Status`; and an AI Overview only the
un-located fallback probe returned no longer counts as exposure for this
market. **Chunk D2 is complete.** The verdict label landed as `"Not Measured"`, not the
`"No DA Data"` this plan wrote — one state, one label, held by a test.
*Findings:* D-C-04/D-M-02 (S1), D-C-03/D-M-08 (S1), D-M-05 (client_da provenance, High), D-C-02 (S1 GSC), D-C-10 (S2 Moz competitor cache), D-C-08 (S2 `www.` bypasses overrides), D-C-20 (S3 error pages enriched), D-C-21 (S3 AIO fallback flag). *Effort:* L.
- D-C-08: normalise once in `EntityClassifier.classify` (strip `www.`, lower-case) so the pipeline, `refresh_analysis_outputs` and the override-candidate report agree; test `classify("www.x.ca") == classify("x.ca")` for every override.
- DA providers: return `None` for absent `rank` / `domain_authority` (`dataforseo_client.py:206`, `moz_client.py:334`); never cache a `None` as 0 (cache a `found=0` sentinel the consumer omits). `serp_audit.py:1625-1628,1752` and `run_feasibility.py:331-335` exclude `None`.
- `feasibility.compute_feasibility(da, [])` → `"No DA Data"` (never "Low"); `run_feasibility.py:306-321` decides availability per keyword, not per run; gate pivot jobs on `gap is not None`; add `da_count`/`da_missing` to every feasibility row and render "mean of N of M ranking domains (K unscored)" in §5c and `feasibility_*.md`; `da_count < 5` → "Not Measured".
- D-M-05: look the client domain up through the active provider in the same batch and use that as `client_da` (config value becomes an override, logged with provider + date); tag rows with `da_provider`; never compare across providers in a trend. Document in `docs/feasibility.md` that DataForSEO rank and Moz DA are different scales (the code's own example shows the client at 19 on DataForSEO vs 35 in config).
- D-C-02: `gsc_client._fetch_all_rows` returns `(rows, complete)` or raises on non-OK; `_cache_store` absences only when `complete`; `run_gsc_analysis` prints "GSC fetch failed — N queries not measured" instead of the absent line; `gsc_demand.save_demand` must not write a trend point for a failed fetch.
- D-C-10: `moz_competitor._cache_store` only when every enabled sub-call is `ok`/`no_record`; otherwise store the OK sub-blocks and refetch the failed one next run.
- D-C-20: enrichment treats `status_code >= 400` as "not enriched" (`Fetch_Status`), counts "N of M pages blocked".
- D-C-21: carry `AI_Overview_Mode` onto the overview row; `has_ai_overview` excludes `fallback_without_location` (or exposes a separate flag).
- *Tests:* `rank: null` absent from result and cache; `compute_feasibility(35, [])` → No DA Data; GSC 503 → no `found=0` rows and the second call re-posts; ranking OK + anchors 5xx → second fetch re-POSTs anchors; status 403 page → `Content_Type N/A`.
- *Probes to flip:* `probe_02`, `probe_03`, `probe_04`, `probe_05` (part B), `discover_method/p07` (feasibility edges).

#### Chunk D3 — AI-visibility honesty
*Findings:* D-C-05/D-M-03 (S1), D-C-11 (S2), D-M-18 (persona cap), D-M-14 (gazetteer / ranking ties), D-M-04 (foundational structure measures competitors), D-M-25 (sentiment failure → neutral). *Effort:* M–L.
- `run_report_enrichment` iterates `probes.keys()` (engines that ran) and requires `total > 0`; never persist an `ai_visibility_index` row for an engine with zero answers; exclude such engines from `all_engine_average`, `compute_transfer` (two empty sets → `None`, not Jaccard 1.0) and `prioritize_engines` (unmeasured ≠ max opportunity); report "not measured (0 answers / skipped)".
- D-C-11: count failures per engine; render "answered N of M (K failed)"; store `questions_planned`/`failed` per run; an empty `answer_text` with no sources is a failed call, not `mentioned=False`.
- D-M-18: when truncating to `max_total_calls // engines`, sample round-robin across personas and de-duplicate city variants first; print "N of M generated questions asked; personas dropped: …".
- D-M-14: `build_gazetteer` stop-lists single-token generic sources ("Indeed", "Pathways", "LinkedIn"…) or requires ≥2 tokens / domain match; `client_ranking_axis` uses competition ranking (ties share a rank) or reports "tied with N"; add `negative_terms` ("living systems theory") to `detect_visibility` as `gsc_demand.is_branded` already has.
- D-M-04: `foundational_score.compute_structure` must read the *client's* enriched rows only (same filter as `_client_extractability_pages`) and return `None` when the client is in no enriched top-10; fix `docs/USER_MANUAL.md:1331-1334`.
- D-M-25: failed sentiment → `polarity None / status failed`, excluded from the axis; print "n classified of m attempted".
- *Tests:* enrichment with an engine that has no rows writes no AIVI row; half the questions raising → report line carries the failure count; empty answer → no `mentioned=0` row; gazetteer excludes "Indeed"; four-way tie → axis 100; structure score `None` when client absent.
- *Probes to flip:* `probe_06`, `probe_10`, `discover_method/p05`, `p06`, `p08`.

#### Chunk D4 — Report and brief logic
*Findings:* D-M-06 (best opportunity ignores intent gate, High), D-M-07 (extraction text claims "high DA gap" when unmeasured, High), D-M-11 (mixed-intent strategy), D-M-12 ("market too small" from `total_results`), D-M-13 (commodity counts `other` as homogeneous), D-M-19 (pivot text/gate), D-C-14 (§4 evidence block dead), D-C-18 (§6 "unknown"), D-C-12 (GUI regenerate drops Content Briefs), D-C-09 (refresh leaves profiles stale), D-C-13 (failed keyword vanishes), D-C-06 (CLI re-run overwrites outputs), D-C-07 (play parity validator can't fire), D-C-15 (`max_tokens` unchecked), D-M-27 (validator numerics). *Effort:* L (split into two pushes: report logic / brief+validator).
- `_rank_keywords` / `_get_best_opportunity_keyword`: exclude `intent_match == 0` from the best-opportunity pick (or make intent the first key) and align `docs/USER_MANUAL.md` §"Keyword Prioritization".
- `play_routing.yml`: a `strategy_text_unknown_feasibility` variant so `feasibility == unknown` never renders "high DA gap"; validator rule: no DA-gap direction for `data_available.feasibility == false`.
- `brief_data_extraction.py:405-425`: `compete_on_dominant` if dominant ∈ `preferred_intents`; `backdoor` only if dominant ∉ preferred and a non-dominant is; ties reported as ties, not dict order.
- `:385-389`: remove the `total_results < 200 → skip` rule or re-key on `moz.volume` with "demand not measured" otherwise.
- `commodity_score.py:147-165`: exclude `other` from title concentration (component `None` → renormalise); entity concentration over the same top-10 rows as the intent verdict.
- `feasibility.py:244-252` / pivot gate: gate on `serp_intent.primary_intent ∈ {local, transactional}` (token test only as fallback); build the explanation from `entity_distribution` or drop the "dominated by directories" clause.
- `generate_insight_report.py:1513-1521`: read `Title` / `_domain_from_link(Link)`; replace the vacuous RC.4 test with one that plants a trigger in a `Title`.
- `metrics.get_volatility_metrics` returns `keywords_current/previous`.
- Move the Content Briefs assembly into a shared function called by both `serp_audit.main` and `generate_insight_report.main`.
- `refresh_analysis_outputs`: rebuild `keyword_profiles` via `extract_analysis_data_from_json`, re-attach plays, re-classify AIO citations, regenerate the `.md`, log "N profiles changed".
- `generate_report`/`validate_extraction`: "N of M keywords returned SERP data; failed: …"; `serp_audit` exits non-zero if a primary fetch failed.
- `_resolve_output_names`: reuse configured names only when they do not exist on disk.
- `brief_validation`: scan "Recommended play" across the whole report grouped by keyword heading; label match with the parenthetical optional; add rules that `client_rank`, `avg_serp_da`, `gap`, `total_results` quoted by the model equal the profile; forbid market-size language unless `moz.data_available`; drop the keyword-specific "estrangement" rule.
- `brief_llm.run_llm_report` returns `(text, stop_reason)`; `max_tokens` is a hard failure.
- *Probes to flip:* `probe_07`, `probe_08`, `probe_09`, `discover_method/p04`, `p07`, `p10`.

#### Chunk D5 — GSC demand and AIO exposure
*Findings:* D-M-15 (sponge = cross-sectional, candidates = below-median half), D-M-16 (branded share over tracked set vs property-level bands), D-M-17 ("at risk" exceeds actual clicks), D-M-20 (AIO constants without source; trend across unlike keyword sets). *Effort:* M.
- Label the sponge table "association, confounded by intent"; impression floor and weighting; reformat candidates require `has_ai_overview is True` and a stated margin below the no-AIO median (or same-query before/after across runs); pull GSC with `country=can`, `device=DESKTOP` to match the SERP fetch; print the window.
- `gsc_demand`: compute branded share over the full `_fetch_all_rows` result (already in memory) and keep the tracked-query view secondary; cite or drop the 2.4 % / 10 % bands.
- `demand_dashboard.py:96`: `at_risk = min(actual_clicks, impressions × ctr_loss)`; prefer GSC's own `position`/`ctr` where a row exists.
- `aio_exposure.get_aio_exposure_trend`: only compare runs with the same keyword set (reuse `metrics.py:81-91` comparability warning); name the source/date of the CTR curve, 0.60 interception and 0.5 citation credit in `config.yml` and `glossary.yml`, or mark them "owner's assumption".
- *Probes:* `discover_method/p10` (at-risk arithmetic).

#### Chunk D6 — Hygiene, provenance, docs
*Findings:* D-C-16 (test date-bomb), D-C-17 (dead `serp_intent.thresholds.confidence_*`), D-M-09 (feasibility statistic: add `n_scored`, `min_competitor_da`, `min_non_directory_da`), D-M-10 (rename "confidence" → classification coverage; wire or delete the dead knobs; fix three manual statements), D-M-21 (`source:` note beside every threshold/weight), D-M-22 (root `methodology.md` stale → retitle with banner; fix `intent_mapping.yml` edge-case-2 sentence), D-M-23 (glossary DA-gap formula reversed), D-M-24 (`feasibility_score` clamp), D-M-26 (trigger words that violate `strategic_patterns.yml`'s own rule; print hit counts / share of pages). *Effort:* M.
- `test_moz_competitor.py:907`: `stale = now − 5 days`.
- Also fix the docs lag noted in the correctness "sound" list: CLAUDE.md/README say `title_patterns` contradictions are SOFT; `brief_validation.py:515` treats them as HARD.

### serp-compete

#### Chunk C1 — Audit universe and brand identity (H3)
*Findings:* C-M-01 (High), C-M-02 (vacuum = any systems-0 page, High), C-M-15 (reframe prompt asserts "Medical Model" at medical 0; PAA never present), C-C-01 (`www.` → brand "www", S1), C-C-13 (`client_brand_names` dropped), C-M-03 (branded demand for dictionary words, High). *Effort:* L. **Decisions 1 and 2 both answered 2026-11-14 (see §4), so all of C1 is unblocked.** Decision 4 (which side owns canonical domain form) is still open, but it only decides where the fix lives long-term: normalise defensively in this repo either way.
- Per decision 1: audit the handoff's `url` / `primary_keyword_for_url` (what Tool 1 ranked); if `ranked_keywords` is kept as enrichment, filter to keywords in the handoff set or containing a clinical term, drop keywords containing the domain's brand token, and print each keyword's source in the report.
- `identify_strategic_openings` and the magnets query: require `medical_score ≥ penalty_thresholds.tier_1_max` (or a new `vacuum_min_medical`) AND keyword relevance before a row is a vacuum / reframe target; rename or implement the "top 10, medical-only" definition the README gives.
- `reframe_engine`: gate on the relevance test; pass `medical_score` only when > 0; add the marker "generated by gpt-4o from keyword, URL and score — no page content supplied"; drop the PAA sentence from FEATURE_GUIDE §6.1 until Tool 1 exports PAA.
- `brand_utils.derive_brand_name` and `youtube_presence._stem`: apply `normalise_domain()` first; better, canonicalise once in `convert_handoff_to_targets` (see decision 4 for which side owns canonical form).
- Thread `client_brand_names` from the handoff into `run_comparison_features` (fallback `client.name`); delete the non-existent `client.brand_names` read.
- Branded demand: query the display brand ("Lavender Counselling"), not the stripped token; add a sanity gate (volume(bare token) ≫ volume(token + "counselling") → `estimation_basis = ambiguous_brand`, withhold share/growth); print the query strings in the Excel sheet.
- *Tests:* `www.jerichocounselling.com → jericho`; YouTube search term never "www"; two `www.` domains never share a query set; medical 0 / systems 0 page is never a vacuum; a handoff with `client_brand_names` drives the client's query set.
- *Probes to flip:* `probes/compete/probe_brand_www.py`, `probe_brand_demand.py`, `compete_method/p02` §B, `p04` §C.

#### Chunk C2 — Null is not zero, alerts that mean something (H2, compete side)
*Findings:* C-C-03 (PA 0 → Fragile Magnet, S1), C-C-04 (Moz endpoint/shape, S1 PLAUSIBLE), C-C-05/C-M-06 (velocity not run-scoped; 1-point drift; two detectors), C-C-06/C-M-07 (`visibility_cliff` on ≤3-row per-day sample), C-C-11 (per-brand volume failure → 0), C-C-12 (`get_relevant_pages` no retry; dropped domain has no trace; abort after `create_run`), C-C-18 (homepage warm-up failure burns an audit slot), C-C-09 (`"BLOCK"` sentinel in `gsc_performance`). *Effort:* L.
- Store `NULL` PA when Moz failed/absent (`competitor_history.pa`, `market_history.da`); skip drift when either side is NULL; high-authority filter and `save_competitor_summary` skip and say "unmeasured" on an empty map; persist "N of M URLs had PA".
- C-C-04: confirm the live Moz endpoint and key (`page` vs `url`) on the next live run — add a Moz line to `docs/TEST_RUN_CHECKLIST.md` §1; prefer reusing discover's `moz_client` shape; log "Moz returned N metrics for M URLs". (Discover migrated to JSON-RPC `api.moz.com/jsonrpc`; compete still calls `api.moz.com/v2/url_metrics` and reads `url`, which discover's real-response fixture models as `page`.)
- One drift detector, threshold in config (e.g. `pa_drop_min: 3` over ≥2 consecutive runs), run-scoped (`market_history` gets a `run_id` column — ALTER beside CREATE, per TODO.md); null-guard `rank`.
- `visibility_cliff`: series from `competitor_metrics` keyed by `run_id`, divided by pages attempted; config floor `risk_signals.cliff_min_sample`; errored scrape → `rank NULL` snapshot, not omission. Until a data source with ≥10 ranked keywords per snapshot exists, consider not emitting the signal at all (decision 5).
- `get_search_volume` returns `None` on failure; `compute_branded_demand` writes `NULL` + `estimation_basis = volume_unavailable` per domain; "N of M brands measured".
- Harden `get_relevant_pages` / `get_url_metrics` / `scrape_content` like `get_search_volume` (timeout + retry + backoff; 429 vs 4xx); `run_audit` collects `skipped_domains` with reasons → "Audited N of M handoff domains; skipped: …" in the report; timeout on the pre-flight `requests.get`.
- `semantic.py:72-77`: homepage warm-up in its own `try`; retry the page once.
- `gsc_performance.py:333-338`: branch on `extraction_status` like `main.py:476-484`; never persist blocked pages.
- *Tests:* second-run with `pa=None` → no drift alert and no `competitors` row; three runs with URL absent from the third → no stale velocity alert; "one of three rows missing is not a cliff"; two runs same day; one-of-three provider failure → NULL row, share over measured rows; `get_relevant_pages` `[]` for one domain → report names it; homepage raising + page 200 → `complete`; blocked own page → no `semantic_audits` row.
- *Probes to flip:* `probe_pa_zero_fragile.py`, `probe_visibility_cliff.py`, `probe_brand_demand.py`, `probe_dfs_abort.py`, `probe_gsc_block_sentinel.py`, `compete_method/p02` §D–G.

#### Chunk C3 — Report correctness
*Findings:* C-C-02/C-M-04 (`total_keywords` cross join, S1), C-C-07 (LIMIT 30/20 truncation in MD and Excel), C-C-08/C-M-05 (cache-hit tier estimate flips `market_position`; depth from one token; raw vs weighted comparison), C-C-10 (feasibility table all-time), C-C-16 (orchestrator ignores selected handoff / reports dir), C-M-20 (smaller drifts: `est_traffic` undefined, `keyword_volume` is best-rival ETV, D2 sentence, sign convention, executive summary lacks coverage). *Effort:* M.
- `reporting.py:107-123`: `COUNT(DISTINCT m.keyword)`; magnet aggregates via a per-domain subquery; rename the column `sampled_keywords (n≤10)`.
- Markdown display cap with "showing N of M"; Excel gets the full frame; sort EEAT/GEO by tier then url.
- Persist `t2_count`/`t3_count` in `semantic_audits` (ALTER + CREATE) and return them from `was_audited_recently`; delete the estimate; depth bands on `t3_count ≥ 1` / t2 density; never compare `medical_score` to weighted `systems_score`.
- `get_competitor_das` scoped to this run's domains.
- Orchestrator passes `--handoff <selected>` to `main.py`; report header names the handoff file; `ReportGenerator` honours `orchestrator.reports_dir`.
- Executive Summary states run coverage (domains attempted / PA-filtered / blocked / cached) — the console already has the numbers.
- *Probes to flip:* `probe_reporting_crossjoin.py`, `probe_report_truncation.py`, `probe_cache_estimate_flip.py`, `probe_feasibility_stale.py`, `compete_method/p02` §A.

#### Chunk C4 — Methodology: what the scores actually measure
*Findings:* C-M-08 ("therapy", "trauma", "condition", "patient" are Tier-1 medical — the client's own copy scores as medical model), C-M-19 (counting mechanics: no lemmas, hyphenated entries unreachable, nested phrases double-counted, menu text counted, no length normalisation), C-C-15 (`self-regulation` can never match; position thresholds hard-coded), C-M-09 (barbell authority: client DA vs competitors' avg *Page* Authority of sampled URLs; client `authoritative` by construction; `+5` hard-coded), C-M-10 (focus undefined at ≤3 pages), C-M-11 (overlap cells are sampling artefacts; GSC 90-day global average vs DataForSEO Canada snapshot), C-C-17 (GSC 5000-row page, `rank_absolute` vs `position`), C-M-12 (EEAT composites of near-constant booleans at 2 dp with "high" confidence always), C-M-13 (cluster label from 3 pages; www/non-www mismatch → "isolated"), C-M-14 (GEO tier rewards WordPress defaults; "Why Competitors Get Cited" asserts causation), C-M-16 (YouTube `none_found` rendered as "no channel"), C-M-17 (SoV: mentioned-not-cited rivals vanish into "other"; `presence_rate` never printed), C-M-18 (provenance; dead keys; hard-coded live thresholds), C-C-14 (documented config keys with no reader). *Effort:* L (two or three pushes). **Decisions 3, 6, 7 in §4 apply.**
- Dictionary: Tier-1 = diagnostic/pathology vocabulary only; move "therapy", "counselling", "patient", "condition", "trauma" to neutral; word-boundary matching in `classify_query_tiers`.
- Counting: `token.lemma_` with lemmatised entries; spaCy `PhraseMatcher` for every multi-token/hyphenated entry (longest match wins, count once); strip `<header>` and `menu`/`nav` classes; count body once; report densities per 1000 words with the window size; Surface-Level as a density threshold. Move `tag_competitor_position` thresholds, `avg_pa > 50`, `+5`, volatility `>= 3` into config and delete the dead keys (`technical.feasibility_threshold`, `moderate_feasibility_max_gap`, `score_normaliser`, `pseudo_systems_threshold`, `gsc_settings.*`, `handoff.supported_versions` unless enforced, `step_dag.*`, `orchestrator.step_timeout_seconds`).
- Barbell: fetch Moz `domain_authority` for each competitor root and label the column `domain_authority`; same top-10 keyword universe for client and competitors (or drop the component); `min_focus_tokens` before computing focus, else `insufficient_data`; entropy over unweighted counts; print the counts.
- Overlap: keyword universe from the handoff; exclude rival-brand keywords; GSC `country=can`; paginate GSC with `startRow`; `rank_group` for the top-N test; state "n of ≤10 sampled per rival" in the section.
- EEAT: render the booleans as ✓/✗ columns (or 1 dp composite with the value set stated); confidence from signal coverage as config promises; pass domain-level DA; fix the manual's duplicated "HTTPS"; mark weights "editorial, 2026-05".
- Cluster: either `max_audit_pages_per_domain ≥ 8` for cluster purposes or report only `hub_is_homepage` + `pages_sampled` and remove the isolated/clustered advice; host-normalise before matching.
- GEO: weight FAQPage / question headings above Organization/Person; exclude generic bylines; rename the section "Extractability signals (structural, unvalidated)"; if the AV export is present, join `ai_citations.domain` to show whether Strong-tier domains are actually cited.
- YouTube: `high` only for handle == stem; `none_found` → "none matched (name search, top 3)", `has_channel NULL`.
- SoV: match competitor brands by `derive_brand_name(export brand)`; print `presence_rate` ("named in k of n answers") and the "other" remainder; require `questions > 0` per engine (D-C-11 upstream).
- Provenance: `_source` note per threshold in `shared_config.json`; "Provenance" column in FEATURE_GUIDE §9.
- *Probes to flip:* `probe_semantic_terms.py`, `compete_method/p01`, `p03`, `p04` §A/B/D/E.

### Cross-tool

#### Chunk X — Handoff and export contract
*Effort:* S–M, but it needs both repos open. Do after D1 and C1.
- **Domain canonical form.** Tool 1 writes `targets[].domain` and `moz.domains` keys as `netloc.lower()` (www kept) while its own citation/brand paths strip www; Tool 2 breaks on the www form (C-C-01) and its omit-list fix (`normalise_domain`) exists but is applied in one place. Decide which side canonicalises (decision 4), encode it in `docs/handoff_contract.md`, and add a contract test on both sides.
- **Rank semantics.** After D1, `targets[*].rank` becomes absolute; bump `schema_version` and document it; Tool 2 should assert the version it expects (`handoff.supported_versions` is decorative today — C-C-14).
- **PAA.** FEATURE_GUIDE §6.1 promises PAA context in reframes; the handoff has no PAA field. Either add `paa_questions` per target to the handoff (Tool 1 has them) or drop the promise.
- **`client_brand_names`** is written by Tool 1 and dropped by Tool 2 (C-C-13).
- **Moz.** One client shape for both tools (C-C-04). Tool 1's `moz.domains[*].anchor_texts.status == "error"` can be a 30-day-stale cached error (D-C-10) — Tool 2's `anchor_coverage` should not read repeated `errored` as a fresh outage.
- **AI-visibility export.** The export itself is sound (checked both sides). As of review chunk D3a Tool 1 no longer writes brand_mentions / ai_citations / ai_visibility_index rows for an engine with zero answers, so the export carries only measured engines. Tool 2's SoV consumer should still require `questions_total > 0` per engine: it is cheap, and it also covers the exports written before D3a.
- **GSC.** Both tools pull GSC with different windows and filters (discover: 90-day all-device; compete: 90-day, one 5000-row page, global). Agree one window and `country=can` and state it in both reports.

**DONE 2026-11-17.** `docs/review_2026-11-04/PLAN_X_handoff_contract.md`.
Canonical host form, absolute rank and its `schema_version`,
`client_brand_names`, and the GSC pull (both tools now filter window, country
and device, each report states its own pull and neither states the other's) are
closed with a contract test on both sides. Not taken: `paa_questions` in the
handoff and the stale-cached-Moz-error read, both of which need an owner
decision on what the consumer should do with them.

---

## 4. Decisions the owner must make (the agent should not guess these)

1. **serp-compete audit universe (C-M-01).** (a) Audit the handoff URLs/keywords only — the documented behaviour; or (b) keep DataForSEO `ranked_keywords` as an *additional* enrichment with the relevance filters above; or (c) keep today's behaviour and rewrite FEATURE_GUIDE §2.1 and the magnet/vacuum definitions to say what is actually sampled. Everything in C1, C3, C4 depends on this.

   **DECIDED 2026-11-14 by the owner: (b).** The handoff is the primary audit
   universe — `url` / `primary_keyword_for_url` is what Tool 1 actually ranked, and
   it is what FEATURE_GUIDE §2.1 promises. DataForSEO `ranked_keywords` stays, but
   only as an additional enrichment, filtered: keep a keyword when it is in the
   handoff set or contains a clinical term, drop any keyword containing the
   domain's own brand token, and print each keyword's source in the report so a
   reader can tell a ranked fact from an enrichment guess. `group_targets` must
   actually be read. C1, C3 and C4 are unblocked on this point.
2. **Vacuum / reframe definition (C-M-02).** Minimum medical score and relevance test, or rename the section.

   **DECIDED 2026-11-14 by the owner: the floor, not the rename.** A page has to
   clear a minimum medical score and a relevance test before it can be a vacuum
   or a reframe target. Implement it as a **new** editorial key
   `technical.vacuum_min_medical` in `shared_config.json`, not by reusing
   `penalty_thresholds.tier_1_max` as a floor — that key means "the highest score
   still counted as Tier 1", so reading it as a minimum inverts its sense. Default
   it to `10`, today's `tier_1_max`, so the starting point is anchored to
   something real rather than invented, and label it in the config as editorial
   and uncalibrated as of 2026-11-14 (decision 7's convention). The relevance test
   is the one C-M-02 defines and decision 1 already uses: the keyword is in the
   handoff set, or contains a Tier-1 / Tier-2 clinical term, and does not contain
   the domain's own brand token.

   Taken with decision 1, this means the documented magnet filter gets
   implemented rather than the section renamed: "rank well" now reads as the
   handoff rank, and "uses only medical language" as the floor above. C-M-15
   follows — gate reframes on the same relevance test, pass `medical_score` only
   when it is above 0, and otherwise say no medical vocabulary was detected
   instead of asserting a Medical Model page.
3. **Tier-1 vocabulary (C-M-08).** Is "therapy" medical-model vocabulary for this client's purposes? The current answer makes the client's own copy and every "couples therapy" query Tier-1.

   **DECIDED 2026-11-15 by the owner: no — "therapy" is neutral, not Tier-1.**
   Tier-1 is diagnostic and pathology vocabulary only. Remove these five from
   `tier_1_medical` in `serp-compete/clinical_dictionary.json`: `therapy`,
   `patient`, `patients`, `condition`, `trauma`. (`counselling`, which the C4
   bullet also names, is not in the list today — nothing to remove.) That leaves
   15 of the current 20: `symptom`, `symptoms`, `treatment`, `disorder`,
   `disorders`, `diagnosis`, `clinical`, `medical`, `disease`, `medication`,
   `prognosis`, `pathology`, `syndrome`, `healthcare`, `illness`.

   Record the removed words in the dictionary itself — a `neutral_clinical` list
   with a comment saying they were deliberately excluded on this date and why —
   so the editorial decision is visible in the file and the words do not drift
   back in. Also add the word-boundary matching the C4 bullet requires: without
   it `condition` matches "conditioning" and `trauma` matches "traumatic", so the
   removal is only half-effective.

   **This decision interacts with decision 2 and must not be shipped without
   re-examining it.** `medical_score` is a raw count of Tier-1 hits
   (`semantic.py:445`), and decision 2's floor gates on `medical_score >= 10`
   (`database.py:52`, `technical.vacuum_min_medical`). Dropping a quarter of the
   Tier-1 vocabulary — including `therapy`, the most common word in this market —
   lowers every page's `medical_score`, so a floor anchored to the *old*
   vocabulary will silently stop Traffic Magnets and Systemic Vacuums firing at
   all. `reframe_engine.py:87` gates on `medical_score <= 0` and is affected the
   same way. Chunk C4 must re-run the detectors on real stored audits before and
   after the dictionary change, report how many rows each threshold admits either
   side, and re-set `vacuum_min_medical` to a value that means the same thing
   under the new vocabulary. State the new value as editorial and uncalibrated
   with its date, as decision 2 requires.

   Three words left in Tier-1 are arguable on the "diagnostic and pathology
   only" test and were **not** part of this decision: `treatment`, `clinical` and
   `healthcare` are medical-model framing rather than diagnoses. They stay for
   now; raise them as a separate question if the C4 before/after numbers show
   them driving the score.
4. **Domain canonical form.** Tool 1 strips `www.` at write time (simplest), or Tool 2 normalises at ingest.

   **ANSWERED 2026-11-16 in chunk D2c: both, with Tool 1 writing the canonical
   form.** `domain_utils.normalize_domain` (lowercase, no port, no credentials,
   no leading `www.`) is now the single definition in Tool 1, applied to
   `targets[].domain`, the `moz.domains` keys, the client domain from
   `config.yml` and every `omit_from_audit` entry. Tool 2 keeps normalising at
   ingest (`src/brand_utils.py`, `src/handoff_moz.py`) — defence on both sides
   costs nothing and means neither tool has to trust the other's spelling. The
   client test is equality or a dot-suffix match, never a substring one.
   Recorded in `docs/handoff_contract.md` ("The canonical host form"); the
   contract test on Tool 1's side is
   `tests/test_d2c_one_host_one_answer.py::TestTheHandoffAgreesOnWhichHostIsWhich`.

   **SETTLED 2026-11-17 in chunk X.** The D2c paragraph above overstated what
   had been done: `targets[].domain` was canonical, but `moz_competitor` built
   the `moz.domains` keys with its own `netloc.lower()` and kept the leading
   `www.`, and `client_domain` was published as typed in `config.yml` — so one
   handoff carried two forms of one host, and the client and omit tests still
   compared raw strings. Chunk X routes all four through `normalize_domain`.
   Both halves of the contract test now exist and call the real code:
   `tests/test_handoff_contract.py` here and
   `Serp-compete/tests/test_handoff_contract.py` there.
5. **`visibility_cliff` and the velocity alerts.** Keep with a real data source and floor, or remove until one exists.

   **RECOMMENDED by the agent 2026-11-16 (owner may overrule): remove the
   signal until a data source exists, and keep the stored series.** The cliff
   is computed from `competitor_metrics` snapshots whose denominator is "pages
   we happened to scrape this run", which moves run to run for reasons that
   have nothing to do with the competitor's visibility; a drop of three ranked
   keywords out of five sampled pages is indistinguishable from a scrape that
   got two fewer pages. An alert that cannot tell those apart is worse than no
   alert, because the report states it as a competitor movement. So: stop
   emitting the signal and its velocity alerts in the report, keep writing the
   snapshots (the series is the only way a real floor will ever be
   calibrated), and keep the config floor `risk_signals.cliff_min_sample` in
   place with its reader, so re-enabling it is a config change plus a report
   section rather than a rebuild. An errored scrape must write a `rank NULL`
   snapshot rather than be omitted, otherwise the series being kept is itself
   biased (P1/P2). Revisit when a snapshot routinely carries ten or more
   ranked keywords per domain.
6. **Client DA source (D-M-05).** Live provider lookup (recommended) vs the fixed 35 — and which provider is "the" scale for feasibility going forward.

   **DECIDED 2026-11-14 by the owner: the live provider lookup.** Look the client
   domain up through the active provider in the same batch and use that as
   `client_da`, logging the provider and the fetch date. `config.yml`'s
   `client_da: 35` stays only as an explicit override, and
   `run_feasibility.py:334` must stop excluding the client domain from the
   provider lookup. This is what D2's bullet list already implements, so the
   coding agent should treat D-M-05 as authorised rather than as an open
   decision.

   **DECIDED 2026-11-14 by the owner on the second half too: leave the rows
   tagged; do not name a canonical provider.** No provider is "the" scale for
   feasibility. Instead:

   - Tag every feasibility row, cache entry and report figure with the
     `da_provider` that produced it, alongside the fetch date already required
     above. A DA figure without its provider is not a usable figure.
   - Never compare or average across providers inside one trend, one chart or one
     "has the gap closed?" claim. Where a trend's rows do not share a provider,
     the honest output is to say so and show the segments separately, not to
     splice them (P2: surface, never silently drop).
   - State in `docs/feasibility.md` that a DataForSEO Domain Rank and a Moz
     Domain Authority are different models on different scales and are not
     interchangeable. The code's own example has livingsystems.ca at 19 on
     DataForSEO against the 35 in `config.yml`.

   Rationale, recorded so this is not revisited blind: naming DataForSEO would be
   the obvious default since it is the primary provider, but it rescales every
   historical feasibility figure in the repo, and this review has not established
   which existing rows came from which provider. Tagging costs nothing and makes
   the mismatch visible. Naming one provider stays available later, once D2 has
   landed and the tagged rows show how much history each provider actually
   accounts for; that is a calibration decision (see decision 7), not a
   correctness one.
7. **Thresholds without provenance (D-M-21, C-M-18).** Accept "editorial, uncalibrated, <date>" labels in config and reports, or schedule a calibration (e.g. feasibility gap vs whether the client actually ranked over successive runs).

   **DECIDED 2026-11-15 by the owner: accept the editorial labels.** No
   calibration is scheduled. An honest label on an uncalibrated number is
   sufficient, and is preferred over leaving the number undocumented or over
   blocking a chunk on a calibration exercise.

   What this requires, in both repos:

   - Every threshold and weight that drives a stated verdict carries a
     provenance note beside it in config — the basis (`editorial`, `derived`,
     or `vendor`), whether it is calibrated, and the date it was last set. The
     mechanism is already specified in the chunk bullets: a `_source` note per
     threshold in `shared_config.json` (C4) and a `source:` note beside every
     threshold and weight in `config.yml` (D6), plus a "Provenance" column in
     `docs/FEATURE_GUIDE.md` §9.
   - The report says so once per section that depends on an uncalibrated
     threshold, not once per number — a label on every figure is noise and
     stops being read.
   - A threshold added later without a provenance note is a defect, not a style
     lapse. **Suggested, not decided:** a guard test that walks the config for
     threshold keys and fails when one has no provenance sibling is the only
     thing that will keep this from rotting; both repos already use standing
     guard tests this way. Treat it as preferred unless it proves awkward.

   **What this decision does not license.** "Editorial and uncalibrated" is a
   statement about where a number came from. It is not permission to report a
   confidence or precision the data cannot support, so the findings about
   unjustified confidence language stand on their own: C-M-12 (EEAT composites
   of near-constant booleans rendered to 2 dp with "high" confidence always),
   D-M-10 (a "confidence" figure that is really classification coverage) and
   C-M-14 ("Why Competitors Get Cited" asserting causation) are still to be
   fixed, and labelling the threshold does not close them.

   **Interaction with decision 3.** The `vacuum_min_medical` re-set that
   decision 3 forces still has to happen — without it the Traffic Magnet and
   Systemic Vacuum detectors go silent once the Tier-1 vocabulary shrinks. Under
   this decision the new value lands labelled `editorial`, `uncalibrated` and
   dated, with the before/after row counts recorded as its basis in the
   provenance note. Those counts are evidence that the number admits roughly
   what it used to; they are not a calibration, and C4 must not describe them as
   one.
8. **Barbell / EEAT / cluster at N≤3 (C-M-10/12/13).** Raise `max_audit_pages_per_domain` (cost) or demote these sections to boolean evidence tables.

   **RECOMMENDED by the agent 2026-11-16 (owner may overrule — this one
   spends API money either way): demote the sections now, raise the cap only
   for a named shortlist.** Three sampled pages cannot carry a barbell
   authority split, an E-E-A-T composite to two decimal places, or a cluster
   label; raising the cap to the ten or so pages those statistics would need
   multiplies the per-domain scrape cost across every audited competitor,
   most of which the owner will never act on. So: rewrite the three sections
   as boolean evidence tables — "author byline present on 2 of 3 pages
   sampled", "schema present: yes/no", "pages sampled: 3" — with the sample
   size in every row and no composite scores, averages or confidence words
   where n ≤ `risk_signals.min_sample_for_statistics` (new, editorial,
   uncalibrated). Then, separately, allow a per-domain override so the owner
   can raise `max_audit_pages_per_domain` for two or three named rivals they
   actually compete with and get real statistics there, at a cost they chose.
   This keeps every number honest at today's spend and puts the extra spend
   where it is worth it. The demotion is chunk C4 work and does not need the
   override to land first.

   Not a decision, for the record: the three arguable Tier-1 words
   (`treatment`, `clinical`, `healthcare`) already have their answer in
   decision 3 — they stay until the C4 before/after numbers show them driving
   the score. And `step_dag.py` lives in serp-compete
   (`Serp-compete/src/step_dag.py`, imported only by its own test), so the
   wire-it-or-delete-it call belongs to that repo's chunks, not here.

---

## 5. Verification protocol for the coding agent (every chunk)

1. Run the chunk's probes **before** touching code; they must reproduce (compare with the `*_output.txt` where captured). If a probe does not reproduce on the live repo, stop and report — the finding may be stale.
2. Implement; promote each probe to a behaviour test (not a source-grep test — see serp-compete TODO.md's own note on `test_coverage_is_persisted…`).
3. Full suite, judged by exit code. Discover: `python3 -m pytest test_*.py tests/ -q`; compete: `python3 -m pytest -q`.
4. Regenerate the reports from the committed reference run (discover: `tests/fixtures/market_analysis_reference_run.json`; compete: a fresh audit from `competitor_handoff_couples_therapy_20260502_1634.json` with mocked APIs if available) and diff the markdown against the pre-chunk output; every changed number must be explained by the chunk.
5. Update the contract docs in the same push: `docs/methodology.md`, `docs/USER_MANUAL.md`, `glossary.yml`, `docs/spec_coverage.md` (discover); `docs/FEATURE_GUIDE.md` (§9 especially), `docs/USER_MANUAL.md`, `LEARNINGS.md` fix log (compete).
6. Never `git add .`; push per chunk.

---

## 6. Finding index

| ID | Sev/Impact | Chunk | One line | Status (2026-11-16) |
|---|---|---|---|---|
| D-C-01 | S1 | D1 | SerpAPI per-page `position` stored as absolute `Rank` | fixed `2285828` |
| D-C-02 | S1 | D2 | GSC transient failure cached as `found=0` for the TTL | fixed (D2b) |
| D-C-03 | S1 | D2 | Zero DA-covered keyword → "Low Feasibility"; no N-of-M | fixed `9784690` (D2a) |
| D-C-04 | S1 | D2 | DataForSEO `rank: null` → DA 0, averaged, cached 30 days | fixed `9784690` (D2a); null encoding unverified against a live response |
| D-C-05 | S1 | D3 | Skipped/failed engines get AIVI 0 persisted and ranked #1 | fixed (D3a) |
| D-C-06 | S2 | D4 | CLI re-run overwrites previous timestamped outputs | fixed (0864d58) |
| D-C-07 | S2 | D4 | Play-parity HARD-fail can never fire | fixed (D4c) |
| D-C-08 | S2 | D2/D6 | `www.` hosts bypass `domain_overrides` (35/121 overrides) | fixed (D2c) |
| D-C-09 | S2 | D4 | `refresh_analysis_outputs` leaves `keyword_profiles`/report stale | fixed (D4c) |
| D-C-10 | S2 | D2 | Moz competitor block with one failed sub-call cached 30 days as `ok` | fixed (D2b) |
| D-C-11 | S2 | D3 | Probe failures drop from denominators; empty answers = "not mentioned" | fixed (D3a) |
| D-C-12 | S2 | D4 | GUI post-feasibility regenerate drops "# Content Briefs" | fixed (D4c) |
| D-C-13 | S2 | D4 | Keyword whose fetch failed vanishes without an N-of-M line | fixed (D4c) |
| D-C-14 | S2 | D4 | §4 evidence block reads keys the producer never writes | fixed (D4a) |
| D-C-15 | S2 | D4 | `stop_reason == max_tokens` never checked | fixed (c742f68) |
| D-C-16 | S3 | D6 | Failing Moz test is a hard-coded-date bomb | already fixed `abcc2aa` — close, do not re-fix |
| D-C-17 | S3 | D6 | `serp_intent.thresholds.confidence_*` have no reader | fixed (D6) — the two confidence thresholds now drive intent certainty; a test fails if any key under the block loses its reader |
| D-C-18 | S3 | D4 | §6 prints "unknown" for keys metrics never returns | fixed (D4a) |
| D-C-19 | S3 | D1 | Two feasibility producers with different definitions | fixed `2285828` |
| D-C-20 | S3 | D2 | 403/429/5xx bodies are classified as content | fixed (D2c) |
| D-C-21 | S3 | D2 | `Has_Main_AI_Overview` set from the no-location fallback | fixed (D2c) |
| D-C-22 | S3 | D1 | Rank history polluted by aborted runs and alt-query rows | fixed `2285828` |
| D-M-01 | High | D1 | = D-C-01 (methodology consequences) | fixed `2285828` |
| D-M-02 | High | D2 | Unscorable domain enters the feasibility mean as 0 | fixed `9784690` (D2a) |
| D-M-03 | High | D3 | = D-C-05 plus Jaccard(∅,∅)=1 and prioritisation | fixed (D3a) |
| D-M-04 | High | D3 | Foundational structure sub-score measures competitors' schema | fixed (D3b) |
| D-M-05 | High | D2 | `client_da` fixed 35 vs live provider on a different scale | fixed `9784690` (D2a); config value is now an override |
| D-M-06 | High | D4 | Best opportunity ignores the mandatory intent gate | fixed (D4a) |
| D-M-07 | High | D4 | Extraction play asserts "high DA gap" when unmeasured | fixed (D4a) |
| D-M-08 | High | D2 | = D-C-03 (fake verdict + paid pivot fetch) | fixed `9784690` (D2a) |
| D-M-09 | Med | D6 | Mean DA is the wrong statistic; no n / min / entity split | fixed (D6) — min_competitor_da / min_non_directory_da / n on the row, in §5b and §5c |
| D-M-10 | Med | D6 | "Confidence" is a classification count capped by enrichment budget | fixed (D6) — coverage and certainty are separate figures, both printed; certainty is the ranking key |
| D-M-11 | Med | D4 | Mixed-intent strategy says "backdoor" when dominant is preferred; dict-order ties | fixed (D4b) |
| D-M-12 | Med | D4 | "Market too small" decided from `total_results` | fixed (D4b) |
| D-M-13 | Med | D4 | Commodity homogeneity counts `other` titles as homogeneous | fixed (D4b) |
| D-M-14 | Med | D3 | Gazetteer matches "Indeed"; ranking ties broken alphabetically | fixed (D3b) |
| D-M-15 | Med | D5 | Sponge is cross-sectional; reformat candidates = below-median half | fixed (D5) |
| D-M-16 | Med | D5 | Branded share over tracked set vs property-level bands | fixed (D5) |
| D-M-17 | Med | D5 | "Traffic at risk" can exceed actual clicks | fixed (D5) |
| D-M-18 | Med | D3 | 20-question cap drops whole personas | fixed (D3b) |
| D-M-19 | Med | D4 | Pivot text asserts directory dominance; gate ignores intent verdict | fixed (D4b) |
| D-M-20 | Med | D5 | AIO constants without source; trend across unlike keyword sets | fixed (D5) |
| D-M-21 | Med | D6 | Core thresholds/weights without stated derivation | fixed (D6) — thresholds_provenance, printed in §A; blank prints as editorial, uncalibrated |
| D-M-22 | Low–Med | D6 | Root `methodology.md` stale and contradictory | fixed (D6) — root guide banner-marked a dated snapshot; intent_mapping.yml sentence corrected |
| D-M-23 | Low | D6 | Glossary DA-gap formula reversed | already fixed before D6 — verified and guarded |
| D-M-24 | Low | D6 | `feasibility_score` exceeds documented 0–1 | fixed (D6) — feasibility_score clamped to 0–1 |
| D-M-25 | Low | D3 | Failed sentiment stored as "neutral" | fixed (D3b) |
| D-M-26 | Low–Med | D6 | Bowen triggers include ubiquitous words; no counts | fixed (D6) — per-trigger page counts + share; four ubiquitous triggers removed; §4 relabelled |
| D-M-27 | Low–Med | D4 | Validator cannot check the claims most likely wrong upstream | fixed (D4c) |
| C-C-01 | S1 | C1 | `www.` domains derive brand "www" | fixed `f7b09bf` (C1) |
| C-C-02 | S1 | C3 | `total_keywords` inflated by cross join | fixed `3d56e0a` (C3) |
| C-C-03 | S1 | C2 | Missing/failed PA stored as 0 → Fragile Magnet | fixed `7a6405b` (C2) |
| C-C-04 | S1 (plausible) | C2 | Moz endpoint/response key assumed, not checked | fixed `7a6405b` (C2) |
| C-C-05 | S2 | C2 | Velocity alerts not run-scoped | fixed `7a6405b` (C2) |
| C-C-06 | S2 | C2 | `visibility_cliff` on ≤3-row per-day sample | fixed `7a6405b` (C2) |
| C-C-07 | S2 | C3 | LIMIT 30/20 truncate MD and Excel silently | fixed `3d56e0a` (C3) |
| C-C-08 | S2 | C3 | Cache-hit tier estimate flips `market_position` | fixed `3d56e0a` (C3) |
| C-C-09 | S2 | C2 | Dead `"BLOCK"` sentinel in `gsc_performance` | fixed `7a6405b` (C2) |
| C-C-10 | S2 | C3 | Feasibility table lists all-time competitors | fixed `3d56e0a` (C3) |
| C-C-11 | S2 | C2 | Per-brand volume failure persisted as 0 | fixed `7a6405b` (C2) |
| C-C-12 | S2 | C2 | `get_relevant_pages` no retry; dropped domain untraced; abort after `create_run` | fixed `7a6405b` (C2) |
| C-C-13 | S3 | C1 | `client_brand_names` dropped; config key doesn't exist | fixed `f7b09bf` (C1) |
| C-C-14 | S3 | C4 | Documented config keys with no reader | fixed `f48953f` (C4c) |
| C-C-15 | S3 | C4 | `self-regulation` unmatchable; position thresholds hard-coded | fixed `7c98967` (C4a) |
| C-C-16 | S3 | C3 | Orchestrator ignores selected handoff / reports dir | fixed `3d56e0a` (C3) |
| C-C-17 | S3 | C4 | GSC 5000-row page; `rank_absolute` vs `position` | fixed `f48953f` (C4c) |
| C-C-18 | S3 | C2 | Homepage warm-up failure burns an audit slot | fixed `7a6405b` (C2) |
| C-M-01 | High | C1 | Audited keywords are DataForSEO per-domain top-10, not the handoff | fixed `f7b09bf` (C1) |
| C-M-02 | High | C1 | Vacuum = any systems-0 page | fixed `f7b09bf` (C1) |
| C-M-03 | High | C1 | Branded demand for dictionary words | fixed `f7b09bf` (C1) |
| C-M-04 | Med | C3 | = C-C-02 | fixed `3d56e0a` (C3) |
| C-M-05 | Med | C3 | Depth "High" from one token; raw vs weighted; cache estimate | fixed `3d56e0a` (C3) |
| C-M-06 | High | C2 | Fragile-Magnet / velocity fire on outages, 1-pt noise, forever | fixed `7a6405b` (C2) |
| C-M-07 | High | C2 | `visibility_cliff` measures the tool's sampling | fixed `7a6405b` (C2) |
| C-M-08 | Med | C4 | "therapy" is Tier-1 medical | fixed `7c98967` (C4a) |
| C-M-09 | Med | C4 | Barbell authority: DA vs PA; client authoritative by construction | fixed `977b52f` (C4b) |
| C-M-10 | Med | C4 | Focus undefined at ≤3 pages | fixed `977b52f` (C4b) |
| C-M-11 | Med | C4 | Overlap cells are sampling artefacts; unlike position scales | fixed `f48953f` (C4c) |
| C-M-12 | Med | C4 | EEAT composites of near-constant booleans, always "high" confidence | fixed `977b52f` (C4b) |
| C-M-13 | Med | C4 | Cluster label from 3 pages; www mismatch → isolated | fixed `977b52f` (C4b) |
| C-M-14 | Med | C4 | GEO tier rewards WP defaults; section asserts causation | fixed `977b52f` (C4b) |
| C-M-15 | Med | C1 | Reframe prompt asserts Medical Model at medical 0; PAA never present | fixed `f7b09bf` (C1) |
| C-M-16 | Low–Med | C4 | YouTube `none_found` rendered as "no channel" | fixed `f48953f` (C4c) |
| C-M-17 | Low–Med | C4 | SoV drops mentioned-not-cited rivals; `presence_rate` unprinted | fixed `f48953f` (C4c) |
| C-M-18 | Med | C4 | Provenance; dead keys; hard-coded live thresholds | fixed `f48953f` (C4c) |
| C-M-19 | Med | C4 | Vocabulary counting mechanics | fixed `7c98967` (C4a) |
| C-M-20 | Low | C3 | Smaller doc/label drifts | fixed `3d56e0a` (C3) |


Status is per-finding as of 2026-11-16. `fixed <sha>` means that commit's message
claims the finding and the chunk shipped behaviour tests for it. Independently
spot-checked against the code by this session: C-C-01/C-M-01 (`group_targets` is
read at `main.py:415,430`), C-M-02 (`vacuum_min_medical` is a new key and
`tier_1_max` still carries its original sense at `scoring_logic.py:74`), C-C-03
(`moz_metrics_map.get(url)` with no `0` default; the `PA > 50` filter is skipped
rather than silently disabled), C-C-11 (unmeasured brands excluded from the share
denominator), C-C-02 (`COUNT(DISTINCT m.keyword)`), C-C-07 ("showing N of M"),
C-C-08 (`t2_count`/`t3_count` persisted, estimate gone), C-C-10
(`get_competitor_das` requires `run_id`), C-C-16 (`--handoff` passed from both
the orchestrator and `run_audit.sh`), C-M-08 (`tier_1_medical` is 13 lemmas with
`therapy`, `patient`, `patients`, `condition`, `trauma` moved to
`neutral_clinical`; the 15 words decision 3 listed became 13 because matching
lemmatises the page text — verified at `semantic.py:124-160` — so the plural
entries were redundant) and C-C-14 (`main._unsupported_handoff_version` really
does refuse an unlisted version, exercised again by chunk X's second half).
The rest of each chunk's list is taken from its commit and its tests, not
separately re-derived. The compete suite is 952 passed, exit 0, at `6164008`.

Chunk D1 shipped at `2285828` (serp-discover), closing D-C-01/D-M-01, D-C-19 and
D-C-22; the discover suite is 1540 passed, 72 skipped, exit 0. The absolute-rank
fix was verified on real data, not only on synthetic pages: the archived
2026-08-26 response's rows, split back into pages at each `position` restart and
re-merged by the fixed function, renumber to a contiguous 1..27, putting the
client's page at its true position 25 where the stored `Rank` said 7 — which
matches `probe_01`'s independent estimate. `probe_01`, `p02`, `p03` and `p09`
still reproduce on the archived *outputs*, because those are stored data from
before the fix; the live code path they also exercise
(`_merge_google_pages`) now returns 1..20 for two full pages. They can only stop
reproducing after a re-run, which is the owner work the chunk's *After:* line
assigns.

The pre-push `learning-qa` pass over `2285828` returned 10 findings against
P1-P45 (2 at S2, 5 at S3, 3 at S4). Every S2/S3 one is fixed in the follow-up
commit, with one guard test each:

- An unmeasured keyword was published as "Low Feasibility", which also
  produced a pivot recommendation and a paid Maps fetch from zero
  measurements. `compute_feasibility([])` now returns "Not Measured", and the
  in-pipeline pass writes that row instead of dropping the keyword.
- `runs.completed_at` was stamped from in-process flags. `finish_run` now
  checks every output against the file on disk before returning OK (P6).
- Both pivot passes averaged every measured DA, counting the client as its own
  competitor whenever it ranked in the pivot SERP. All four passes now use
  `select_competitor_das`, guarded by a source-inspection test — the
  behavioural tests re-implement each call site, so they could not catch this.
- `TOP_N_FOR_FEASIBILITY` did not bind: both producers pre-sliced to a literal
  10, so raising it had no effect.
- Dropped pagination duplicates are counted and logged
  (`pagination_duplicates_dropped`): renumbering shifts the rows below a drop.
- The "N more recent run(s) skipped" count included every earlier incomplete
  run, which on this database would have reported 54 with none in the window.
- `get_rank_deltas` and `get_entity_dominance` returned a bare `{}` for three
  different reasons; the caller printed "no historical data" over 6,540 rows,
  and report section 5 vanished with no note. Both now carry a reason, which
  the audit prints and the report renders.
- The `INSERT OR REPLACE` → upsert change in `save_run` was untested although
  it is the only change in the diff that can destroy live data.

**Adjacent issues found, not fixed** (S4, dropped per the effort budget; each
is a real defect, not a false positive):

- `storage.py` migration `except sqlite3.OperationalError: pass` also swallows
  lock and missing-table errors. It then fails loudly on the first write
  instead of at init, so the effect is a worse error message, not bad data.
- `visualize_volatility.py` runs the same top-10 organic query as
  `metrics.get_entity_dominance` with no `query_label` filter, and its
  `pivot_table` averages A/A.1/A.2/P ranks into one plotted point. Same defect
  class as D-C-22, in a dev-facing script.
- `step_dag.py` is built, correct and covered by 13 passing tests, and is
  reachable from nothing. Either wire it in or delete it with its test.

### Follow-up to the 2026-11-14 reading: the market setting and the wrapped links

Not a numbered chunk. The 2026-11-14 reading turned up two faults in the run
itself, and the user authorised both fixes ("Yes, both").

**The market.** `config.yml serpapi.location` said `Vancouver, British
Columbia, Canada` while `feasibility.non_profit_location` said
`North Vancouver`: the run measured one city and scored another, so the
client's absence from all nine map packs described the wrong market.
`serpapi.location` is now the SerpAPI `canonical_name`
`North Vancouver,British Columbia,Canada`, confirmed against a live
`locations.json` lookup before the change. `run_feasibility.DEFAULT_LOCATION`
replaces two hardcoded fallbacks and `probe_ai_visibility` holds the same
value with a test asserting they agree. `config_validators.validate_config_yml`
warns when the two settings disagree — a warning, not an error, because
measuring a neighbouring market on purpose is legitimate.

**The wrapped links.** Every organic link and every AI-Overview citation of
that run arrived as `https://www.google.com/goto?url=CAES...`, an opaque
Google payload. SerpAPI passes it through, so every URL-derived stage read
`www.google.com`: entity and content classification, Domain Authority lookup,
client-rank detection, handoff targets, citation attribution. New module
`link_recovery.py` recovers what Google still sends in the clear — the host,
from `displayed_link`, a reference's `source_icon`, `source` where it is a
hostname, or the host already recovered for the row a sitelink sits inside —
and walks every dict in a response rather than a named list of containers
(enumerating them missed four: ads, ad sitelinks, organic sitelinks, and
AI-Overview `snippet_links`). A recovered link is the site root, not the
ranked page, so the row is marked `Is_Destination_Page: false` and
`Link_Status: site_root`, and every page-level figure reads `Not Measured`
rather than the front page's value. A row whose host cannot be recovered
carries no URL at all: unknown, not `google.com`, whose Domain Authority
would otherwise be scored as a competitor's (P1/P14).

Verified on the archived run, not only on synthetic rows: 203 wrapped links,
160 recovered, 43 lost (all AI-Overview inline `snippet_links`), 0 lost
organic rows, 0 wrappers surviving anywhere. `parse_data` over
`raw/20261114_155451/calls/0001_*.json` yields ranks 1-4 as yellowpages.ca,
thebestvancouver.com, reddit.com and allycouples.com, and the six AI-Overview
citations resolve to psychologytoday.com, goodlifetherapy.ca, reddit.com and
janeapp.com.

Three helpers were extracted because the gates they carry have to hold in the
primary pass and the pivot pass alike, and a source guard can only honestly
assert "there is exactly one writer": `moz_client.write_metrics` (Domain
Authority is a property of the domain and survives a site-root recovery; Page
Authority is a property of the page and does not, and the row and the database
are gated together — P43), `feasibility.url_window` (slices the top N *first*,
then drops blanks, and reports the hole; filtering first slides rank 11 into a
set everything calls "the top 10" — P9/P31) and `link_recovery.link_status`.
Moving them also kept `serp_audit.py` under its 2200-line cap, which the
first version of the change exceeded; the cap was not raised.

**Effort tier: Full** (`standards/effort-budget.md`), because the change is on
the data path and touches external calls. Tests for the change, a full sweep
budget, one cold `learning-qa` pass.

That pass returned 8 findings, all fixed in this chunk with one guard test
each (`tests/test_link_recovery_followup.py`, 24 tests):

- My own guard `test_page_authority_is_gated_but_domain_authority_is_not`
  sliced the source at the *first* `item["Competitor_DA"] =` and stayed green
  while the pivot pass wrote an ungated Page Authority 180 lines below. This
  is why the three helpers above were extracted.
- `_GOOGLE_HOST` matched `google.example.com` — someone else's subdomain —
  contradicting its own comment. Tightened and verified against 8 hosts.
- Three readers go back over stored output written before the fix.
  `generate_domain_override_candidates.normalize_domain` now returns no domain
  for a wrapper, so google.com cannot enter the override review queue;
  `refresh_analysis_outputs` keeps a row's existing `Entity_Type` rather than
  overwriting it with `N/A`, which would turn an unknown into a measured
  negative; each reports its count (P2).
- A probe citation whose host could not be recovered voted "client not cited".
  `Citations_Unresolved` now travels with `Client_Cited` onto the probe row and
  into the brief data, and is logged.
- `raw/<run_id>/*_response.json` is written *after* recovery, so a file named
  "raw" held processed links. It now carries a `_post_processing` key pointing
  at `raw/<run_id>/calls/`, which is written before recovery runs. The writer
  moved to `serp_checkpoint`, which owns the archive.
- The market comparison read only the first comma field, so
  `North Vancouver,Washington,United States` passed and
  `North Vancouver, British Columbia` false-fired. It now compares every field
  both settings name.
- `place_phrases` was used through a bare `in` test, so with the city set to
  "North Bay" the keyword "therapy for bayside families" read as already
  naming the place and went out with no location. `query_variants.names_place`
  matches on word boundaries.
- "unsupported location" and the other parameter errors were retried three
  times with backoff. They are now in `_fetch_serp_api`'s `non_retryable`
  markers: a setting SerpAPI has rejected once will be rejected again.
- Two tests were pinned to the live `config.yml`, so changing the client's
  market in config would have failed the suite. They patch `_serp_city`.

Honest limits of that pass: it ran before `handoff_writer.py`,
`config_manager.py`, `report_writing_directives.yml` and the `"N/A"` change
landed, and it covers one family of failure modes (the failure-hides family),
not general correctness.

**Adjacent issues found, not fixed:**

- The handoff's targets assert a site root is the ranked page and carry no
  destination-page flag. Fixing it needs a `schema_version` bump agreed with
  Tool 2, so it is recorded in `docs/methodology.md` rather than changed here.
- `play_routing.yml` rules 3 and 4 match `feasibility: [low, unknown]` and
  their strategy text asserts a high DA gap, which an unmeasured keyword does
  not have. This is already open finding **D-M-07**, covering both
  `extraction_play` and `local_pivot_play` — tracked, not newly discovered.
- City aliases ("North Van", "NVan") are editorial content with no home. There
  is no hardcoded list to externalise, so nothing was moved; a
  `location_aliases` key in `serp_vocab.yml` is the place for one if the need
  is ever shown with real keywords.
- The `Situational_Probes` sheet has no glossary coverage beyond the two
  columns this change touched (`Client_Cited`, `Citations_Unresolved`).

The discover suite is 1621 passed, 72 skipped, exit 0.

**After:** the owner work the market fix creates. Every
`market_analysis_*.json` on disk was produced against the wrong city with
wrapped links, so `run_feasibility.py` and the briefs need re-running over any
that are still relied on. No DA provider is currently reachable
(`DATAFORSEO_LOGIN`/`PASSWORD` absent from `.env`, Moz returned nothing on
2026-11-14), so feasibility stays unmeasured until one is.

Chunk X's open half shipped with it at `6164008` (serp-compete): the handoff moved
to `schema_version` 2.0/2.1 and those versions are now in compete's
`handoff.supported_versions` and `absolute_rank_versions`, so the rank-column
warning retires itself on new files and still fires on the v1.x files on disk.
Without the `supported_versions` entry the next real handoff would have been a
hard fail. Compete's suite is 952 passed, exit 0. The "`rank <= magnet_max_position`
admits 29 of 29" figure in its FEATURE_GUIDE is kept but labelled: it was measured
on page-relative data and does not describe a v2.x run, and what the filter admits
on absolute ranks has not been measured — no v2.x handoff exists yet.

All 87 findings in the index read fixed as of chunk X (2026-11-17); none is
open. Chunk Y1 is the first of the adjacent-issue batches — the issues the
earlier chunks' cold reviews logged under "Adjacent issues found, not fixed"
rather than fixing in a sweeping diff. It closed nine of them, one rule per
finding (`docs/review_2026-11-04/PLAN_Y1_one_definition_each.md`). Chunk Y2
is the second: the page fetch had no retry while every other outbound call in
the tool had one, so a single connection reset filed a page as permanently
unreachable, and three of the four reasons a GSC demand section shows no
run-over-run Δ printed as a first run
(`docs/review_2026-11-04/PLAN_Y2_transient_is_not_terminal.md`). Chunk Y3 is the third:
a figure the run did not measure must not print as a number, and a row the run
dropped must be counted where the reader can see it — report section 6
disappeared on four reasons it had already built the wording for, a
foundational readiness nobody measured printed as 0.0 and entered the trend
table, and one unreadable validation rule disabled every validation rule
(`docs/review_2026-11-04/PLAN_Y3_a_zero_is_a_measurement.md`). Chunk Y4 is the
fourth: a number that decides what a report says belongs in config, and a tie
has to be broken on purpose — the sponge comparison's position bands and
minimum bucket size were Python constants, the retry policy behind every
outbound call could not be tuned while SerpAPI's own could, the "entity mix too
close to call dominant" check broke its tie on dict order so the contradiction
went unreported half the time, the rank-history chart plotted pivot queries and
aborted runs as if they were the keyword's own history, and the audit's organic
row stored a host form no other table used
(`docs/review_2026-11-04/PLAN_Y4_config_not_constants.md`). Chunk Y5 is the
fifth: an error is not an absence, and one wait is not three — three schema
migrations ran inside `except sqlite3.OperationalError: pass`, so a locked or
missing table counted as a finished migration and the provenance columns then
read "not recorded"; the volatility reader closed its sqlite handle on some
exits and not the failing one; a cited domain the brand gazetteer does not know
printed the same dash as a citation with no brand and nothing counted them; the
Y1 guard against hand-stripping `www.` was a source grep that a fourth spelling
would pass; and four clients each carried their own `REQUEST_TIMEOUT`, so one
number served an API call, a ranked-page fetch and an LLM answer
(`docs/review_2026-11-04/PLAN_Y5_an_error_is_not_an_absence.md`). Chunk Y6 is
the sixth: the pipeline agrees with the standalone run — `serp_audit` decided
each keyword's neighbourhood pivot inside the SERP fetch loop, before
`keyword_profiles` existed, so it called `generate_hyper_local_pivot` with
neither the measured SERP intent nor the measured entity distribution while
`run_feasibility.py` passed both, and the same SERP produced different pivots
from the two entry points; `refresh_analysis_outputs.py` was the one config
loader of five that applied no retry policy; the rank-history chart opened the
database around `SerpStorage`'s migrations and raised `no such column` against
a database written before them; and the two sponge helpers named module
constants as default arguments, so a configured threshold reached `main` and no
other caller
(`docs/review_2026-11-04/PLAN_Y6_the_pipeline_agrees_with_the_run.md`). Chunk
Y7 is the seventh: one retry budget, read in one place — the SerpAPI loop's own
budget was read at `serp_audit` import with a bare `int()` / `float()`, so a
value that is not a number aborted the run with a traceback before any keyword
was fetched and a negative backoff reached `time.sleep` after the first paid
call, while the three `http_retry` keys beside it warned and used the
documented default; nothing recorded why the two budgets differ; the GUI
explained SerpAPI's two keys and none of `http_retry`'s four; and
`run_gsc_analysis.run_analysis` applied this run's sponge thresholds and also
passed all five explicitly, so the applied mapping had no production reader
(`docs/review_2026-11-04/PLAN_Y7_one_retry_budget.md`). Chunk Y8 is the
eighth: a bug is not a dead network — the paid SerpAPI fetch loop wrapped every
attempt in `except Exception`, and the body included the checkpoint write and
the link recovery, which run after a response has been paid for, so a
`TypeError` in either was retried with two more paid calls and then filed
beside genuine network failures; the GUI offered a retry budget of zero that
the loader refuses to a log the operator never reads; and the GSC sidecar
recorded none of the thresholds the markdown beside it names. The loop now
lives in `serp_fetch.py` with a failure taxonomy of its own — a `STATUS_*` per
outcome, reaching the failed-keyword record's `reason` — the Configuration
Manager refuses a zero for any of the nine settings whose loader refuses it,
and the sidecar names the thresholds the run applied
(`docs/review_2026-11-04/PLAN_Y8_a_bug_is_not_a_dead_network.md`). 

**Chunk Y9 — a committed write is not a closed handle.** The adjacent issue
both Y5 and Y6 carried, and the reason the Y6 guard named two files instead of
the repo: `with sqlite3.connect(path) as conn:` commits and rolls back but
never closes the handle, and `with closing(sqlite3.connect(path))` closes but
discards the commit, so converting 61 sites the obvious way would have stopped
every cache being written. `db_connect.connection` does both, once, and every
production module now opens the database through it — including two bare
connections the adjacent issue had not counted, in `export_history.py` and
`verify_enrichment.py`. The guard is the repo, not the two files
(`docs/review_2026-11-04/PLAN_Y9_a_handle_is_closed.md`).

**Chunk Y10 — Tool 2 closes its handles too.** The same class, one level
further in: `DatabaseManager._get_connection` and
`VelocityModule._get_connection` returned a bare `sqlite3.connect`, used as
`with ... as conn:` at 43 sites that commit and never close, and taken bare by
two writers (`eeat_scorer`, `cluster_detector`) that never closed it at all.
Both factories now return the same `db_connect.connection` helper and are
renamed `connection()`; the old name is removed rather than aliased, because
two doors is how one of them stays unfixed
(`docs/review_2026-11-04/PLAN_Y10_tool2_closes_its_handles.md`).

**Chunk Y11 — a rollback is not the diagnosis, and five seconds is not a
decision.** Both repos, because both share the helper Y9 and Y10 wrote, and
both carried its two faults. `conn.rollback()` and `conn.close()` were
unguarded, so an exception from either replaced the exception the caller needed
to see — and on the clean path a failing `close()` after a successful
`commit()` raised out of a block whose write was already durable, so the caller
recorded the write as failed and the run reported an absence where there was a
row. And `sqlite3.connect`'s `timeout` — the wait for another writer's lock —
was left at its default of 5.0, a number nobody chose and nobody could change,
while the GUI runs `refresh_analysis_outputs` in the same process as a run and
Tool 2's Streamlit orchestrator writes the same file as an audit. Both steps
now run through `_safely`, which logs the cleanup failure and lets the original
outcome stand, and the wait is `config.yml database.lock_timeout_seconds` /
`shared_config.json technical.db_lock_timeout_seconds`, shipped at 5.0 so
naming it changed no behaviour. Applying it is the part that would have rotted:
six loaders in Tool 1 read `config.yml`, five called
`http_retry.apply_retry_policy` directly and the sixth applied nothing at all
although it opens the database, so there is now one `process_config.apply` that
every loader calls, guarded by a consequence test over all six
(`docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md`). The
remaining adjacent issues are listed at the end of each chunk's own plan.

**Chunk Y12 — one database, named once.** `"serp_data.db"` was a literal at
24 sites in 17 modules of Tool 1, with no `config.yml` key at all, and every
one of those literals was relative to the current working directory. A reader
started from anywhere but the repo root therefore pointed SQLite at a path that
did not exist, and SQLite created a new empty file beside the caller: a missing
history reported as an empty one, which is the fault Tool 2's `ReportGenerator`
had and the review had already recorded there. `db_connect` now owns the name —
one literal, in one module — `database.path` sets it, a relative path resolves
against the repo root, and every call site asks `db_connect.database_path()` at
call time rather than taking it as a default argument, which binds at `def`
time before any config has been read. Three entry points that opened the
database and loaded no config at all (`export_history.py`,
`verify_enrichment.py`, `export_ai_visibility.py`) got a loader, closing Y11's
cold-review finding F5, and the four `--db` options now default to `None` and
resolve after that loader. Tool 2 had one branch of the same fault left: `load_db_path` resolved a configured name against its config directory but returned the bare default when no config was present, so that path created a database beside the caller — it now resolves on every branch. The cold reviews of the two halves found twelve findings, five high, two of them the chunk's own bug surviving inside the fix: the report resolved its database before any loader had run, and eight loaders still read `config.yml` from the caller's working directory, so starting the tool from anywhere else abandoned the configured database for the built-in one. A second hand-rolled resolver in Tool 2's `VelocityTracker`, with a different default name, sent the competitor rows and the velocity reads to two different databases (`docs/review_2026-11-04/PLAN_Y12_one_database_named_once.md`).

**Chunk Y13 — a cleanup failure is a number, not a line on stderr.** Chunk Y11
stopped a failing `rollback()` or `close()` replacing the exception that caused
it: `db_connect._safely` logs it and carries on. The second fact then went
nowhere a reader looks. `logger.exception` writes to stderr, and the audits open
and close a connection inside their per-keyword and per-domain loops, so a
`close()` that fails once has usually failed every time — each one holding a
file handle open until the process exits, with nothing saying "this happened N
times". Both repos now count them, keyed by step and database path, and render
the tally as one sentence: Tool 1 writes it as a `parsing_warnings` row, so it
reaches the JSON and the workbook's Parsing_Warnings sheet; Tool 2 puts it in
`run_coverage`, so it reaches the briefing's coverage block. Each audit clears
the tally where its own run begins; the other entry points are separate
processes and report at exit through an `atexit` hook, the floor for the
fourteen consumers that write no artefact.
The run's exit code does not change — a failed cleanup after a successful commit
does not make the data wrong, which is the whole point of Y11. What the sentence then claims depends on which
step failed: a `close()` comes after the commit, so the writes are durable; a
counted `roll back` means a block raised and abandoned its transaction, and
saying "the figures stand" there was the chunk's own bug, found by its cold
review. Tool 1 reports again after its workbook is written, because the run
keeps writing to the database and a workbook cannot be amended. The words are
editorial, in Tool 1's `serp_vocab.yml` under `db_cleanup`; Tool 2 has no
vocabulary file at all, which is recorded as an adjacent issue
(`docs/review_2026-11-04/PLAN_Y13_a_cleanup_failure_is_a_number.md`).

**Chunk Y14 — one cache for both keyword signals.** Carried as an adjacent
issue by Y11's cold review. `_KeywordSignalClient` exists so the fetch, quota
and "404 is not an error" rules cannot drift between the two per-keyword Moz
signals; the cache was left outside it, and `MozKeywordClient` and
`MozIntentClient` each carried their own `_init_cache_table`, `_cache_lookup`
and `_cache_store`. Three rules were therefore written twice: a row past its
TTL (or carrying no timestamp) is ignored, a cached failure is never served,
and a measured absence is served. What actually differs between the signals is
the table name, the payload columns, and the two conversions between a row and
a block — so the base class now owns the cache, built from
`CACHE_TABLE_NAME` + `CACHE_PAYLOAD_COLUMNS`, and each subclass supplies only
`_block_from_cache` and `_payload_for_cache`. The duplication had already
drifted in one visible way: both Moz caches chunked their `IN (...)` at a bare
literal `500` while `gsc_client` named the same SQLite fact
`CACHE_LOOKUP_CHUNK` and explained it; the name now lives in `db_connect` and
all three read it. No behaviour change — the existing Moz suites are the
regression evidence, and the new guards assert each rule against **both**
clients through one test. Its cold review found the chunk's own rule had
stopped at two of five caches — `moz_client`, `dataforseo_client` and
`moz_competitor` still carried the literal — so all five now read the named
constant and the guard walks every production module instead of two files by
name. Four more findings were fixed with guards: an existing table now gains a
declared payload column rather than failing every write, the two cache hooks
exchange a mapping keyed by column name so the column order carries no
meaning, a cached row the signal cannot read is counted, and an incomplete
subclass spec names the class and the attribute instead of raising an SQL
syntax error
(`docs/review_2026-11-04/PLAN_Y14_one_cache_for_both_signals.md`).

**Chunk Y15 — every editorial file has an editor.** Carried as an adjacent
issue by the cold reviews of chunks Y1–Y6. `CLAUDE.md` says editorial content
belongs in a YAML or JSON file rather than in Python, and the review chunks
moved a great deal of it out; the Configuration Manager is how a non-developer
reaches those files, and it was never extended. It registered nine tabs while
the repo held nineteen editable editorial files, so ten — the feasibility,
Search Console and AI-visibility wording, the SERP vocabulary, the glossary,
the play routing table, the engine profiles, the report directives, the brief
validation rules and the schema recommendations — were reachable only by
opening the file in a text editor. The rule was followed and the consequence it
exists for was not delivered for them.

Each of the ten now has a source tab: it shows the file's own text, parses it
before the write so a syntax error is reported with its line instead of
breaking the next run, runs the file's validator if it has one, joins Save All
and Discard under the same all-or-nothing rule, and writes the text verbatim so
a comment the user adds survives. They are source rather than forms because
these files nest arbitrarily — `engine_profiles.yml` and
`report_writing_directives.yml` are three and four levels deep with prose
leaves — and a widget tree over arbitrary nesting is more GUI surface than the
editorial benefit justifies; a form for a given file stays available as a later
per-file upgrade, which is what the nine bespoke tabs are.

The part that stops the fault recurring is the guard, not the ten tabs: the
files are declared in one table in `config_tab_models`, every exclusion is
named with its reason, and a standing test walks the repo's editorial YAML and
JSON and fails the build when a file has neither. The old test asserted the tab
count equalled nine, which is exactly what went stale. Building it found one
real bug by driving a real tab: `BaseConfigTab.validate` returns early for a
file with no validator, so reading the remembered parse error there read
whenever the text was last parsed, and a broken edit to `glossary.yml` saved
successfully (P16).

The chunk's cold review returned seven findings, four of them high, and all
seven are fixed with a guard each. The two that mattered most were not in the
new code's logic but in where and what it wrote: the tab joined the file name
onto the **current directory** while nine of the ten readers anchor on the
module's own, so a GUI started from elsewhere showed a blank tab, reported no
error, and saved a new file nothing reads; and it checked **syntax only**, so
deleting `rules:` from `play_routing.yml` saved cleanly and killed the next run,
and deleting `numeric_claims:` from `brief_validation_rules.yml` turned every
numeric check off with nothing saying so. A file's own loader is now run where
it can tell a usable table from valid YAML that is not one. Also fixed: a
syntax repair typed into a source tab was discarded with no prompt and its red
warning was squeezed to one pixel; every save appended a blank line, because a
Tk text widget carries an implicit final newline; a non-OSError lost the
partial-save report; and the temp file was a fixed name, left behind on failure.
Final mutation gate 18/18 caught, none vacuous
(`docs/review_2026-11-04/PLAN_Y15_every_editorial_file_has_an_editor.md`).

**Chunk Y16 — one reader for the shared config.** Carried as an adjacent issue
by the cold reviews of chunks Y11, Y13, Y14 and Y15. `shared_config.json` is
the editorial config both tools share — scoring weights, penalty thresholds,
position thresholds, risk signals, the database path, the clinical vocabulary
tiers — and Tool 2 had **five** bodies reading it, with different behaviour on
a file that would not parse, and **five** modules each building the path to it
from their own `__file__`. The serious one was on the scoring path:
`scoring_logic` read the file at import time into module globals with an
`except Exception: pass` behind it, so a `shared_config.json` with a trailing
comma meant every competitor in the run was scored with the Python fallback
weights and an **empty** clinical vocabulary — page scores of 0, a run that
completed, a briefing whose numbers reconciled with nothing the owner had
configured, and nothing logged, because the swallow was the only place that
could have said so (P40 + P16, and the same shape as the bind-time trap of
chunk Y4). The same import-time read also meant editing the config and running
again inside one Streamlit process changed nothing.

There is one reader now (`src/config_io.py::load_config`, which raises on a
file it cannot parse, the rule `database.load_shared_config` already
documented), one definition of the path, and the values are read when they are
used — through accessors that take an already-loaded config so a caller holding
it does not re-read the file (P25). The scoring path reads **once per run, when
the analyser is built**: the cold review of this chunk found that a per-page
read put the read inside `scrape_content`'s `except Exception`, where a config
that could not be parsed mid-run became a per-URL record saying the competitor's
PAGE was unreadable, with `rank` / `systems_score` / `medical_score` all NULL and
the run completing (its F1, high). Built once per run, the read is outside every
per-page handler, so the failure stops the run before the first page is fetched
— and one analyser scores every page against one version of the file, so the
weights and the vocabulary behind a single score can no longer come from two
reads either side of a GUI edit. No cache: one read and parse is 0.095 ms over
34 KB, measured rather than assumed, and a cache keyed on nothing is how the
import-time read became a bug. The eleven Python fallbacks that mirror the
file's own values are now asserted verbatim equal to them, so "degrades to the
documented default" cannot degrade to a different number than the document.

The cold review returned **8 findings (1 high, 7 medium)**, all fixed with a
guard: the swallowed raise above; two opposite policies for the same file
280 lines apart in `semantic.py`; four stale docstrings and doc paragraphs
describing the behaviour the chunk reversed; a new guard that asserted the five
path constants *agreed* (they always had — the five expressions resolved to the
same string — so it was vacuous for its own criterion), replaced by a check that
the file is NAMED once; a source-text guard that would stay green against a
re-introduction of the import-time read, replaced by a consequence; the same
EMPTY-vocabulary outcome still reachable through `load_dictionary`'s
`except Exception: pass` on the `clinical_dictionary.json` fallback; three more
mirrored fallbacks the equality sweep had not reached; and one score computable
from two reads. Writing those guards also surfaced a P43 defect in the chunk
itself: `scoring_logic` did `from src.config_io import load_config`, which binds
at import, so patching the one reader did not reach the scoring path and several
of the chunk's own tests were testing nothing. Mutation gate 33 mutations, 33 caught, none vacuous; the
import-time guards run in a subprocess, because a test that imports the module
in-process would pass either way
(`docs/review_2026-11-04/PLAN_Y16_one_reader_for_the_shared_config.md`, in
serp-compete).

**Chunk Y17 — the briefing's prose gets a file.** Carried as an adjacent issue
by the cold reviews of Y13 and Y15, and named in Tool 1's `CLAUDE.md` for over a
month. Tool 1 has ten editorial text files; Tool 2 had none, so every sentence
the strategic briefing renders — the caveats, the comparability warnings, the
"why there is no number here" lines, the headings — was a Python literal, which
the rule both repos are built on says it should not be. Three consequences were
already in the code, and they are what made it a defect rather than a
preference: the EEAT heuristic caveat existed in **four** wordings, one of them
`shared_config.eeat_client_messaging.caveat` which no module read and one a
dataclass default stored on every score row; the handoff's page-relative rank
convention was warned about in **four** separately worded places, each citing
the same finding, so rewording the fact meant finding all four and no
de-duplication tool finds them because they are not duplicates; and
`UNKNOWN_CELL = "—"` had a bare duplicate of itself in the cluster table.
`briefing_messages.json` at the repo root now holds every one of them, about
240 values sectioned by the report section that renders it, read by
`src/briefing_messages.py` once per render and held outside every per-section
handler. JSON rather than YAML because PyYAML is not in this repo's
`requirements.txt` and is not importable in its venv, and a text file is not a
reason to pin a new runtime dependency on the render path. Its own loader
rather than `shared_config.json`'s, because Y16 deliberately made that one
*raise* on a key it cannot read, and a messages file needs the opposite rule
for a missing key: a missing or malformed FILE raises — a briefing without its
caveats states every figure in it as fact — while a missing KEY prints
`[message missing: <key>]` where the sentence would be and the report ends with
how many it could not find (P2). Workbook sheet names and column headers stayed
in Python: they are a format contract other tools and tests read by name. Scope
was every sentence the briefing renders, not the three modules first guessed,
because leaving `risk_radar`'s and `db_connect`'s wording in Python while
`reporting.py`'s moved is the half-migrated state the rule itself forbids.
The build corrected the plan on eight points, all recorded in it: the EEAT
caveat's fourth wording; three dead `framework_caption` keys in
`shared_config.json` rather than one dead block; the feasibility sentence
interpolating the *existing* `technical.feasibility_threshold` rather than a
new key for the same number; four keys the migration had itself duplicated,
found by the two-way key-coverage guard before any commit; and the ~25 test
files that pin rendered wording, left alone on the judgement that a test
asserting what the report *says* is the contract with the reader, while one
asserting `Messages().get(...)` on both sides asserts only that the renderer
rendered the file. The chunk's own mutation gate found two of its guards
vacuous — a `report.extend(...)` moved inside a comment still satisfied
`source.index(...)`, and the action-queue truncation note was a closure over
the render's cap, so hardcoding its number was invisible — and a third that
passed while the call site held the literal beside the reader; all three became
consequence tests on extracted methods (P19/P27/P30). It also found a real
defect in the loader: `get` short-circuited on `if not fields`, so a caller
that passed no arguments at all printed a literal `{domain}` into the briefing
and nothing counted it. The cold `learning-qa` pass then found nine
medium-or-higher findings, all fixed with guards: a missing prompt block would
have been sent to the model as a marker, paid for and its answer written in as
a reframe, so prompts now have a reader of their own that returns `None` and
the caller does not call (P14); the shortfall count covered only the report's
own keys while six other modules build a throwaway `Messages`, so the ledger is
process-level and reset by the entry point; the action-queue row cap was a
number in a file of sentences and moved to `shared_config.json`, degrading with
a logged warning rather than printing an empty queue; a stray brace in a
hand-editable file aborted the render; `db_connect` asked the messages file
from inside an `except` and an `atexit` hook, where it may be the broken thing,
and degrades to two named fallbacks instead; the file was parsed ten-plus times
per run and the parse is cached on `(path, mtime, size)`; an
`icons.unknown_cell` of `""` would have satisfied every assertion while the
cells rendered blank; and the migration had stopped at the briefing while three
standalone markdown reports kept every sentence in Python, two of them near-
identical rewordings of keys that *had* moved, so the defect had come to span
two files. The last also indicted the prose guard, which named six modules by
hand (P29). Two claims are still worded more than once on purpose — the EEAT
caveat's long and stored-row forms, and three `framework_caption` keys that
restate their own `intro` — recorded as editorial decisions for the owner and
guarded against gaining a further home, because that is how the original defect
was built. Mutation gate re-run at **49 mutations, 49 caught, none vacuous**
(three were vacuous on the first run: the prompt policy, the brace catch and
the fallback degradation each had a fix and no consequence test); compete core
967 passed, compete root 162 passed, Tool 1 unchanged at 2325
(`docs/review_2026-11-04/PLAN_Y17_the_briefing_prose_gets_a_file.md`, in
serp-compete).

## 7. What was checked and found sound (so it is not re-reviewed)

Each finding file ends with a "Checked and found sound" list. Highlights: the handoff schema is byte-identical on both sides and the consumer reads exactly the required fields; the AI-visibility export matches its consumer; `http_retry.py`, `moz_jsonrpc.py`, `moz_keywords.py` never cache an error; `intent_verdict.py`, `play_routing.py`, `aivi.compute_aivi` arithmetic are correct given correct inputs; compete's anchor-spam path, YouTube error/none split, serp_overlap `self_unknown` banner, positioning renormalisation and the "report reads a different DB" fix are all verified. The problems are upstream of the honesty scaffolding, not in it.

## 8. What the first live run found (2026-11-18)

The review closed with all 87 indexed findings fixed and 2330 tests passing, so
the next step was a small live run — two keywords, Low API mode — to confirm
the tool end to end on real data. It found two defects in one run. Both are
recorded here because of what they say about the review itself: neither was
reachable from a mocked suite, and the second was a rule the project had
written down and not enforced.

**L1 — a written-out "N/A" was read back as a blank cell, and the pipeline
hard-failed.** Step 1.2 (`validate_xlsx_vs_json.py`) reported the same organic
result as missing from BOTH files:

    "missing_in_xlsx_sample": ["('20261118_153321', 9, 'N/A')"]
    "missing_in_json_sample": ["('20261118_153321', 9, nan)"]

`Link` is part of that sheet's key tuple, a SERP result with no link carries the
string `"N/A"` — this tool states an absence rather than leaving a blank, which
is the whole H2 family of fixes — and pandas' DEFAULT missing-value list
contains `"N/A"`. So the workbook read back `NaN` where the JSON held `"N/A"`
and the two keys could not match. Any run where one result has no link, which
is most real runs, aborted at step 1.2. Fixed by reading every sheet with
`keep_default_na=False` and an empty `na_values`
(`validate_xlsx_vs_json.READ_OPTIONS`), and guarded by
`tests/test_validate_xlsx_vs_json_na_marker.py`, which round-trips through a
real `.xlsx` via `subprocess` rather than building frames in memory — the
collision is between a real workbook and pandas' own defaults, so no fixture in
the suite could have produced it. The residual limitation is recorded as a test
rather than a comment: Excel's own error literal `#N/A` cannot round-trip at
all, because pandas maps it to `NaN` at the Excel layer whatever `na_values`
says (`openpyxl` reads the same cell back as the string). Nothing writes `#N/A`
today; if a provider value ever does, the fix is to read that sheet through
openpyxl, not to widen `na_values`.

**L2 — the report printed a Moz plan figure the project forbids hardcoding.**
With no DA measured, section 5c rendered its "no feasibility data" branch,
which said `MOZ_TOKEN` in `.env` "(free tier, 50 rows/month)". The figure is
wrong — this account is on Starter Medium, `config.yml` records
`moz.rows_per_month: 3000` — and `CLAUDE.md` states that the real allowance is
read at runtime via `quota.lookup` and that a plan figure must never be
hardcoded. Two further copies of the same claim were found by the guard, in
`serp-me.py` and in `report_clarity_spec.md`, which is the familiar shape: one
claim, three homes, all stale together. The words now live in
`feasibility_messages.yml` `no_data_section`, where the rest of this family's
vocabulary already lives, and name no figure at all.
`tests/test_moz_plan_figure_is_not_hardcoded.py` fails on any plan figure or
free-tier claim in a Python module, scoped to lines that name a provider or a
plan so a module's estimate of its own usage ("~4 rows a month" in
`moz_competitor.brand_authority_for`) is not swept up.

A detail that makes L2 worse than a stale string. `moz_api_upgrade_spec_v1.md`
(2026-08) already carried the correction as an explicit task: "`MOZ_TOKEN` is
*not* 'free tier: 50 rows/month' — it is the **Starter Medium** API plan;
correct the note and say the real quota is read at runtime via
`quota.lookup`." The `CLAUDE.md` note named in that task was fixed. The two
copies in `generate_insight_report.py` and `serp-me.py` were not, because the
task named one document rather than the claim, and nobody searched for the
other homes. That is the same shape as the defects this review spent eighty-
seven findings on, committed while fixing one of them: the fix that corrects
one copy of a claim and does not grep for the rest leaves the claim alive. The
guard is the part that was missing — it fails on the claim wherever it appears,
so the next copy cannot be added quietly.

**What the run also established, which is not a defect.** Feasibility was
absent although `MOZ_TOKEN` is present: `run_pipeline.py` runs steps 1.1-1.4
and feasibility is not one of them, so a pipeline run never fetches DA however
`.env` is set. The 5c text listed only credentials, which sent the reader to
fix the one thing that was not wrong; it now names `run_feasibility.py`. The
same correction went into `docs/USER_MANUAL.md`, where step 7 was headed
"(Optional)".

**And what the run confirms works.** On real data with no DA provider reached,
the report says feasibility is unavailable, routes every play on intent and
AI-Overview alone with "inputs missing" stated, prints "insufficient data —
only 2 of 9 URLs could be classified", "1 of 57 SERP text blocks (2%)" and
"Not Measured: 16.7%", and closes with a §A appendix declaring all ten
threshold families "editorial, uncalibrated". Pre-review, the same run would
have produced DA 0 and a confident "Low Feasibility". That is the H2 family of
fixes behaving as designed, measured rather than asserted.

**The lesson for the process.** 2330 mocked tests did not reach either defect.
One lived in the boundary between real file formats, the other in prose nobody
executes. A live run is not a formality at the end of a review; it is a test
class of its own, and these two are the argument for making one the last step
of any chunk that touches an output a person reads.

### The cold review of those two fixes, and what it changed

Run over the diff after the suite was green. It returned five findings, two
high; all five are fixed with a guard, because every one of them was in the
fix itself rather than in the old code.

**F1 (high) — the N/A fix normalised one side.** The `"" → None` collapse went
into `df_to_records`, the WORKBOOK reader. `norm_text` left a JSON `""` as
`""`, so a key cell that is an empty string in the JSON and blank in the sheet
reproduced the identical both-sides-missing signature the fix was for.
Reproduced against the real validator with a `Rich_Features` row, where
`Details` is a key column written as `primary_results[key].get("title")` and
yields `""` for a Knowledge Panel with no title. One absence now has one
representation: `blank_to_none` is applied in `index_records`, where both
record sets pass through, and to every key part whether or not its column is
declared in `normalize_text_cols` — `Details` is not.

**F2 (high) — a wrong-shaped YAML edit aborted the whole market report.**
`.get("no_data_section") or {}` guards `None`, not a wrong type, and §5c is
deliberately outside `_safe_section`. `no_data_section` written as a plain
string — the likeliest typo in a block whose entire purpose is to be
hand-edited by a non-developer — raised `AttributeError` and took the report
down, while the comment above it claimed the loader degraded. Type-checked
now, and subtested against a string, a list and an int.

**F3 (medium) — and an unreadable file made the warning vanish.** Before the
change the "feasibility data unavailable" line was unconditional; after it, a
missing messages file rendered the heading with nothing under it, which reads
as "nothing to report" rather than "DA was never fetched". The test asserted
that silence as the contract, so the weaker behaviour was defended rather than
caught. `generate_insight_report.FALLBACK_NO_FEASIBILITY` is the built-in
wording now, the same shape as `db_connect.FALLBACK_*`, and it says that it
was used.

**F4 (medium) — the new guard proved an absence over a narrowed population.**
It globbed `REPO/*.py`, so `scripts/` and any future package directory were
outside a claim worded "no module may know this number", and it matched
physical lines, so the offending literal — an implicitly-concatenated
multi-line string — tripped it only because one fragment happened to carry
both the figure and the word "tier". Re-wrapped, the defect would have passed.
It walks the tree now and matches against AST string constants, with
docstrings excluded, which is what lets `moz_competitor.brand_authority_for`
keep explaining that its uncached call costs "~4 rows a month" — a statement
about this code, not a claim about the account.

**F5 (medium) — the sibling pandas read was not swept.** `load_keywords` read
the keyword CSV with pandas' defaults, so a keyword cell of `NA`, `null`, `-`
or `nan` came back as `float('nan')` and was handed on as a paid search query.
Same root cause, same class, and `CLAUDE.md` says fix the class. Fixed, and
`skip_blank_lines=False` with it: pandas drops blank lines before the caller
sees them, so the "N of M lines were blank" warning could never have fired and
a keyword file with a gap in it ran shorter than the operator wrote with
nothing said (P2).

**What F5 cost, and why that is the right price.** Hardening it added eighteen
lines to `serp_audit.py`, which sat at exactly the 2200-line cap its own test
enforces. Raising a cap to fit a fix is how a 2200-line module comes about, so
the function moved to `keyword_input.py` instead; `serp_audit.load_keywords`
is a wrapper, so no caller or test changed. The module is 2194 lines.

Also taken from the review: the `("heading", "body")` key list meant a third
paragraph added to the YAML block was silently unread (P36), so the block's
own order is the render order now.

**Verification after the fixes.** 2349 passed, 68 skipped, 214 subtests, exit
0. Mutation gate over 12 reverts — one per fix plus the three parts of F1 —
**12 caught, 0 vacuous, 0 anchor-failures**.

**Adjacent issues found, not fixed.** `validate_xlsx_vs_json.py` compares only
row counts and key tuples: `normalize_text_cols` is applied into a record that
is then discarded and `required_cols` is never read, so the step-1.2 gate
cannot see a divergence in `Title`, `Snippet`, `Word_Count` or any other
non-key field, while its name and the pipeline's step label both say "validate
xlsx vs json" (P33 — complete along one axis, presented as a full
cross-check). `config_manager.py` carries an unprovenanced "max 3 for free
tier" claim about SerpAPI page limits. `norm_text`'s nan arm covers
`float`/`numpy.float64` but not `pd.NaT` or `pd.NA`; neither can reach a key
column today.

---

## 9. Correctness fixes after the live run (2026-11-19)

Recorded at three sentences per finding — the defect, the consequence, the fix
(`~/.claude/standards/effort-budget.md` §9a).

### C1 — `gsc_client._fetch_all_rows` treated a short page as end-of-data

The loop ended when a page carried fewer than `ROW_LIMIT` rows, and GSC can
serve a short page part-way through a set under sampling. Every query after
that page was recorded as having no impressions and cached for the TTL, which
is the D-C-02 fault — a fetch that did not finish reported as a measured
absence — in miniature, described by this function's own docstring and then
contradicted by its loop. The loop now ends only on an EMPTY page, a short
page logs at INFO and continues, and `MAX_PAGES = 200` bounds an API that
never empties by returning the rows with `complete=False` rather than looping
forever. Cost: one extra request per fetch, the empty page that confirms the
end. Mutation-checked: restoring the short-page exit fails 6 tests.

### C2 — step 1.2 compared keys only, while calling itself validation

`validate_xlsx_vs_json.py` compared row counts and key tuples:
`normalize_text_cols` was computed into a record that was then discarded and
`required_cols` was never read at all. A workbook whose `Title`, `Snippet`,
`Word_Count` or `Content_Type` disagreed with the JSON passed the gate the
pipeline labels "Data Validation", so the one check that exists to prove the
two deliverables say the same thing could only see a row appear or disappear
(P33 — complete along one axis, presented as a full cross-check). The rows
both files hold are now compared field by field over each sheet's declared
columns through `values_agree`, which tolerates what the Excel round trip
genuinely changes (an integer stored as a float, a number against its own
decimal spelling, line endings, blank against empty string) and nothing else;
`columns_not_compared` names, per sheet, every column the files carry that no
spec declares, so what the gate does not check is stated rather than inferred
from silence (P2).

Checked against the real 2026-11-18 run outputs: exit 0, no mismatch — the
gate does not cry on a genuine workbook.

### Backlog (found sideways, one line each — rule 11)

- The Overview sheet writes the string `"null"` for an unmeasured
  `Primary_Intent` and carried `Intent_Confidence: "low"` where the JSON held
  `null`, for one row of the 2026-11-18 run (`serp_audit.py:2042`).
- `values_agree` cannot yet compare a list/dict column against the `str()` the
  workbook stores for it, which is what blocks widening the comparison from
  each sheet's declared columns to every column both files carry.
- `config_manager.py` carries an unprovenanced "max 3 for free tier" claim
  about SerpAPI page limits.
- `norm_text`'s nan arm covers `float`/`numpy.float64` but not `pd.NaT` or
  `pd.NA`; neither can reach a key column today.

### C3 — the report never said why nothing could be classified

The 2026-11-18 run recommended no page for any of ten keywords: 15 of 221
ranked results were classified, so no keyword had a SERP intent verdict, every
action read `❓ Intent unknown` and every play read "Deprioritise". The cause
was on every row — 125 `Not The Ranked Page` (a Google redirect that resolved
only to the competitor's site root), 58 `Not Fetched`, 14 `Blocked (403)`, 9
`No URL` — and in no sentence anywhere: §0 said only that feasibility was
missing, and each keyword's section said "0 of 10 URLs could be classified"
without saying what stopped them, so ten absences of evidence read as ten
judgements about the keywords (P2). §0 now carries one line counting the
classified results and naming each cause with its own count, built from the
rows' own `Fetch_Status` words rather than a cause inferred at render time;
a run where nothing was classified says "none of M" rather than "0 of M",
because no keyword can have a verdict at all on such a run. Words in
`serp_vocab.yml` `classification_coverage`; `docs/USER_MANUAL.md` says what
each cause means and what to change.

Verified by regenerating the 2026-11-18 report from its own JSON: the line
reads "15 of 221" and names all four causes.

### C4 — the config editor could not edit config.yml's editorial lists

`ConfigSettingsTab` rendered a widget per field of each top-level MAPPING, so
a top-level value that is not a mapping printed as a read-only label and a
field whose loaded value was `None` or an empty mapping got no widget at all
— `get_edited_data`'s own docstring recorded them as "kept exactly as
loaded". `known_brands` is a top-level list, so the competitor-brand
gazetteer that CLAUDE.md names as editorial and that the Y.7 brand pass and
Y.8 citation attribution both read could only be changed by hand-editing the
file, as could any blank `thresholds_provenance` family — the very keys whose
blankness the report asks the operator to fill in. Both now render as an
editable YAML box (`SECTION_VALUE` for a whole section, the `yaml` field type
for a field), an emptied box saves `null` rather than `[]` because "nothing
recorded" and "there are none" are two different statements, broken YAML is
reported and keeps the loaded value, and a field edit arriving for a
non-mapping section is reported rather than raising a `TypeError` inside Save
and losing every other tab's edits with it.

Verified against the real `config.yml` in a live tkinter instance: the
`known_brands` box round-trips the list, and opening the tab reports no
unsaved changes — a round trip that reformatted would mark every open dirty.

### Checked and left alone

Two items carried on the correctness list turned out to be already handled;
they are recorded here so the list does not grow a change that nothing needs.

- **Top-competitor tie-break.** `probe_ai_visibility.py:1209` sorts the tied
  brands, picks the first, logs how many tied on what count, and carries
  `tied_top_competitors` into the sidecar, where `answer_sentiment` renders
  it. The pick is deterministic across runs and the tie is stated, which is
  what D-M-14 and its cold review asked for. No change.
- **`_rank_keywords` sorting feasibility first.** The order is deliberate
  (finding F7: "Not Measured" sits below the three verdicts but above a
  keyword with no row, because last means "cannot be ranked on DA", not
  "ranked worst"), and the one place the order becomes a recommendation —
  `_get_best_opportunity_keyword` — requires a feasibility VERDICT and a
  matching intent, and says which gate stopped the rest. No change.

### Backlog (continued)

- City aliases ("North Van", "NVan") have no home: `client_profiles.yml`
  carries `primary_city` / `secondary_cities`, which only expand probe query
  templates, so the aliases people actually type are never probed. A feature,
  not a defect — nothing is wrong today.

### The cold review of C1-C3: six findings, all fixed

**1 (high) — the §0 line counted a different thing from the figure it
explains.** It counted rows whose `Content_Type` was an unmeasured marker;
the per-keyword sections count `serp_intent.evidence`, over the top-10 window
the verdict was computed on. The two disagree in both directions — a client
or known-competitor row classifies with no content type at all, and a page
read as `other` has a content type but no intent — so the 2026-11-18 report
would have said "15 of 221" where §5b says "6 of 100", and on a SERP where
every readable page types as `other` the line would have vanished exactly
when it was needed. It now sums the keywords' own evidence, counts the causes
from their own `fetch_coverage.by_state` over the same window, and names the
remainder — pages that were read and whose type maps to no intent — so the
causes add up to the shortfall.

**2 (high) — a mistyped placeholder in `reason_item` aborted the report.**
The reason join ran before the `try` that was supposed to degrade the wording
to English, and `serp_vocab.yml` is the file users are told to edit. Both the
sentence and the join are now inside one guard.

**3 — a declared column neither file carries was reported as covered.**
`compared` is `declared & present` and `not_compared` is `present - declared`,
so a `required_cols` entry the writers have stopped emitting fell out of both
and the gate showed full coverage of a contract column that no longer exists.
Reported as `declared_columns_missing` and fails.

**4 — `columns_not_compared` was the last row's value.** It was reassigned
each iteration, so it described whichever key sorted last, and it was `()`
when no row was compared at all — which reads as "nothing was left
unchecked". It is a union now, and `rows_field_compared` says per sheet how
many rows the comparison ran over.

**5 — a repeated key hid rows from the comparison, and the keys did not
identify a row.** The index keeps one row per key, so of a repeat only the
survivor was compared. Fixing it surfaced the larger fault: every keyword of
a run shares one `Run_ID`, and `Overview`'s key was `("Run_ID",)`, so ten
keywords' rows collapsed to one and step 1.2 compared ONE of them — invisible
until now, because both files collapsed identically. `Source_Keyword` is part
of the key of every per-keyword sheet; on the 2026-11-18 outputs the gate now
compares 10 Overview rows instead of 1 and 221 organic rows instead of 212.
Three sheets still repeat a key legitimately (the same related search
harvested twice, with no field telling the rows apart); those 13 rows are
reported as `rows_not_individually_compared`, and only a DIFFERENCE in how
often a key repeats between the two files fails.

**6 — no no-progress stop in the GSC loop.** A backend that ignores
`startRow` re-serves the same page, and `MAX_PAGES` alone meant 199 further
25k-row requests that learn nothing. A page adding no query the fetch had not
already seen now stops it, as INCOMPLETE.

**Also taken from the review's reading.** The unread-state phrases ("the link
resolved to the site root, not the ranked page") were a Python dict in
`brief_data_extraction._UNREAD_FETCH_STATES` — a second home for the same
facts as `serp_vocab.yml` `fetch_status`. They are in that file now under
`fetch_status.reasons`, read through `enrichment.reason_text`, and the brief's
dict is derived from `enrichment.UNREAD_STATES` rather than listed.

**Verification.** 2415 passed, 68 skipped, 233 subtests, exit 0. Mutation gate
over 8 reverts, one per fix: 8 caught, 0 vacuous. The 2026-11-18 outputs
revalidate at exit 0 and their report regenerates with the corrected line.

### Backlog (continued)

- `gsc_client.MAX_PAGES` is a hardcoded operational bound in a repo that moved
  `http_retry.attempts` and `database.lock_timeout_seconds` into `config.yml`
  (P4). Defensible as a pure safety rail; nobody should need to tune it.

## Measurement 2026-11-19 — why no keyword gets an intent verdict

**The cap.** `enrichment.max_urls_per_keyword: 5` stopped the page fetch before
rank 6, so half of every keyword's verdict window could be classified only
where `url_pattern_rules.yml` matched. Raised to 10: that cause went from 18 of
the 90 unclassified results to 0, and classification coverage rose from 10 of
100 to 16 of 100. Still no keyword reached the five classified results
`intent_verdict` requires, so the raise alone does not produce a verdict.

**The binding constraint is upstream.** 52 of the 100 ranked results in the
verdict window arrive as `https://www.google.com/goto?url=CAES…`, which
SerpAPI passes through verbatim; measured live on 2026-11-19 at 5–6 of every
9 organic results on this client's keywords, at `num=10` and `num=100` alike,
so it is not a function of the request. Three recovery routes were tested and
none returns the destination: the `url=` payload base64url-decodes to a
protobuf whose 142-byte field is ciphertext with no URL in it, SerpAPI's
`google_about_this_result` endpoint answers with an `error`, and
`displayed_link` carries a truncated breadcrumb rather than a path.
`link_recovery.recover_row` already extracts the host, which is the maximum
available, and marks the row `link_is_destination_page: False` — the module is
correct and there is nothing to fix in it.

**What this leaves as a decision, not a defect.** A host-only result has a
known `entity_type` (psychologytoday.com is a directory) but
`content_type: unknown`, and `intent_mapping.yml`'s rule 2 drops it with the
rationale "classifier could not read the page; do not guess". That rule was
written when unreadable pages were rare; at a 52% wrapper rate it means no
keyword in this topic set can ever carry a verdict. Whether a decisive entity
type on its own counts as evidence of intent is an editorial judgement for the
owner, and changing it would also inflate the classification-coverage figure,
so it is recorded here rather than changed.

### 2026-11-19 — the host settles the intent where the page cannot be read

**The defect.** Every keyword in the 2026-11-19 run carried no intent verdict
and no page recommendation, because 52 of the 100 results in the verdict window
arrived as encrypted Google `/goto` wrappers whose page could not be read, and
an unreadable page was dropped outright. The rule that dropped it —
`intent_mapping.yml` rule 2, "classifier could not read the page; do not
guess" — was written when unreadable pages were rare; at a 52% wrapper rate it
meant no keyword in the topic set could ever carry a verdict, however much the
operator enriched. Section 1b now reaches an intent from the host for the three
entity types whose intent does not vary page to page (directory →
commercial_investigation, government → transactional, publisher →
informational), gated on a new optional `page_read` match key that
`enrichment.page_read_state` derives from the row's fetch state.

**The consequence of getting it wrong, and what stops it.** Inferring from the
host could have overstated what the run knew, so three properties are pinned by
tests: the rules fire only on `page_read: "no"`, so a page that was read and
came back untypable keeps its drop and a pre-existing JSON reads `"unknown"`
and is unaffected (P1); `counselling` and `media` are excluded because neither
host type carries one intent; and a host-inferred row is counted in
`serp_intent.evidence.host_inferred_classified_count`, excluded from the
classification-coverage bucket, stated in the report's §0 line, and subtracted
per fetch state from that line's causes so they equal the deficit they explain
rather than exceeding it (P2).

**One hop inside the fix.** `pathwaysbc.ca` — one health-services directory
served per region — classified three ways at once: `bc.` as a directory,
`vancouver.` and `qathet.` as government, and three further regions as nothing,
from per-host entries in `domain_overrides.yml`. Host inference would have
given one site three different intents, so it is now listed once at the
registrable domain in `classification_rules.json` `directory_domains` and the
three contradictory overrides are gone. Result on the 2026-11-19 data:
classified results 16 of 100 → 46 of 100, keywords with a verdict 0 of 10 →
7 of 10.

**Verification.** 2435 passed, 68 skipped, 244 subtests, exit 0. Mutation gate
over 6 reverts: 6 caught, 0 vacuous. Re-measured end to end by
`refresh_analysis_outputs.py` plus a report regeneration on the real run — no
SerpAPI calls.

### Backlog (continued)


### 2026-11-19b — section 1b gates on the page's type, not on the fetch

**The defect.** Section 1b fired on `page_read: "no"`, so one site was
classified two ways: for `childhood emotional neglect`, three Pathways BC pages
that were read came back `other` and were dropped while four that were not read
were inferred from the same host. Reading a page therefore produced a worse
answer than failing to read it, and the split was decided by whether a fetch
happened to succeed rather than by anything about the SERP.

**The consequence.** A keyword's verdict moved with the run's fetch luck, and
the rows the classifier had actually looked at were the ones discarded. The
gate is now `content_type_usable: "no"`, derived by
`intent_verdict._content_type_usable` from the new editorial
`unusable_content_types` list at the head of `intent_mapping.yml` — the one
place the two cases (never read; read and untypable) are declared to be the
same case. A page WITH a usable type still wins over its host, so a directory
host whose page reads as a `guide` stays `informational`.

**What it did not change.** Which hosts may speak: `counselling` and `media`
are still excluded, and a host-inferred row is still excluded from the
classification-coverage bucket and stated separately in the report's §0 line.
`page_read` remains a supported match key, since whether the page was read is a
separate fact from whether its type was usable, but no shipped rule keys on it.
On the 2026-11-19 data: classified results 46 of 100 → 51 of 100, keywords with
a verdict 7 of 10, the Pathways inconsistency gone (`childhood emotional
neglect` now reports `host_inferred_by_fetch_state: {enriched: 3,
not_destination_page: 4}`).

**Verification.** 2442 passed, 68 skipped, 257 subtests, exit 0. Mutation gate
over 4 reverts on the widened logic: 4 caught. Re-measured end to end with
`refresh_analysis_outputs.py` plus a report regeneration and step 1.2 at exit
0 — no SerpAPI calls.

### 2026-11-19c — news is a publisher, not `media`

**The defect.** `publisher_domains` listed no Canadian news host, so the four
that ranked on the 2026-11-19 run — globalnews.ca, ctvnews.ca, sootoday.com,
rmoutlook.com — classified as `N/A` and carried nothing. Three more (cbc.ca,
vancouversun.com, canadianaffairs.news) were pinned to `media` by
`domain_overrides.yml`, the type that also holds reddit.com, youtube.com and
amazon.ca.

**The consequence.** `media` mixed reporting with social and retail, so it
carried no single intent and had to be excluded from the host inference in
`intent_mapping.yml` section 1b — which meant a news-dominated SERP produced no
verdict even though news reporting answers questions, i.e. `informational`. The
three overridden hosts are now `publisher` in `domain_overrides.yml` (an
override beats the pattern lists, so moving the list entry alone would have
changed nothing), the same three are out of `media_domains`, and
`publisher_domains` gained 21 Canadian national, BC and North Shore news hosts.
`media_domains` is now `reddit.com`, `youtube.com`, `amazon.ca` — social and
retail only, still excluded from section 1b.

**Result on the 2026-11-19 data.** Classified results 51 of 100 → 56 of 100,
keywords with a verdict 7 of 10 → 8 of 10. `my parents and siblings` came out
`informational` at 83% agreement — the first keyword in the set whose verdict
matches `client.preferred_intents`, so the first whose action is not
"Mismatched intent".

**Verification.** 2451 passed, 68 skipped, 271 subtests, exit 0. Tests:
`tests/test_news_is_a_publisher.py`, including a guard that the two lists stay
disjoint (the classifier checks `publisher_domains` first, so an overlap would
be a silently dead `media` entry rather than an error). Re-measured with
`refresh_analysis_outputs.py`, a report regeneration and step 1.2 at exit 0 —
no SerpAPI calls.

## 2026-11-19d — a job board is off topic, not unmeasured

**Defect.** `family roles` ranked ten job boards and no counselling result —
Google read the query as an employment search — and job boards had no entity
type at all, so every row fell through to `N/A`.

**Consequence.** The keyword reported `❓ Intent unknown`, which reads as a
measurement failure in the tool, hiding the one finding that matters about that
keyword: it belongs to another market and should be dropped. Worse, two
Glassdoor job-listing pages that *were* read came back `guide` and were counted
as `informational` evidence for a counselling keyword.

**Fix.** `job_board` is a new entity type (`classification_rules.json`
`job_board_domains`, 14 hosts), checked **before** `directory_domains` so an
employment SERP is never filed beside a page of therapist directories. Rule 1a
of `intent_mapping.yml` gives it `uncategorised` deliberately, for a read page
as much as an unread one: a job listing holds no counselling-search intent to
infer, and forcing one would put an employment SERP under
`commercial_investigation` where no reader could separate it from a SERP full
of directories. The finding is carried instead by
`serp_intent.evidence.off_topic_organic_url_count` and the new
`🚫 Off-topic SERP` action, which fires when a keyword has no verdict and
off-topic rows hold at least `off_topic_min_share` of its ranked results. Both
keys are editorial, in `intent_mapping.yml`, and validated by `load_mapping`.

**Result on the 2026-11-19 data.** `family roles` now reads
`🚫 Off-topic SERP`; all 14 of its job-board rows type as `job_board` and no
other row changed type. Classified results 56 of 100 → **54 of 100** — the
correction, not a loss: the two lost rows are the Glassdoor listings that had
been counted as informational. Keywords with a verdict stayed 8 of 10.
`family dynamics` remains `❓ Intent unknown`, correctly: six of its ten hosts
are unrecognised small sites, which is a measurement gap.

**Verification.** 2483 passed, 68 skipped, 325 subtests, exit 0. Tests:
`tests/test_job_boards_are_off_topic.py` (32 tests, 54 subtests). Mutation gate
8 of 8 caught. Two standing guards caught real omissions a new entity type
creates — `serp-me.py`'s `DOMAIN_REVIEW_TAG_STYLES` colour and
`config_validators._LITERAL_ENTITY_TYPES` — both filled. Re-measured with
`refresh_analysis_outputs.py` plus a report regeneration: no SerpAPI calls.

**`family roles` dropped from the keyword set, 2026-11-19, on the owner's
decision.** Ten of its ten ranked results were job boards and none was a
counselling result, so the phrase competes in the employment market and no
content change wins it. Removed from `keywords_family-of-origin-seo-phrases.csv`
(now 9 keywords); recorded here because that file is untracked, like the other
recent client keyword sets, so git holds no history of the edit and this is its
only durable record. The measurement that produced the decision is the
`🚫 Off-topic SERP` action above.

## 2026-11-19e — `total_results` is a page size, not a market

**Defect.** SerpAPI's `search_information.total_results` returned 98-100 for
all ten queries of the 2026-11-19 run, which asked for `serpapi.num: 100`.
Google has largely stopped publishing the "About N results" estimate; what
comes back is the count of results on the page that was fetched. Nothing
checked the figure against the request, so `total_results_measured` was `True`
for all ten.

**Consequence.** The brief printed the figure in every keyword heading as that
keyword's scale, was told it could call it "estimated market scale", summed it
across PAA clusters, broke every content-priority tie on the difference
between 98 and 100, had its restatement of it checked for faithfulness by
`brief_validation`, and ran the prompt's "note if `total_results < 500`" on
every keyword of every run. D-M-12 had removed the demand *conclusion* from
this field but left the figure in the brief's prose.

**Fix.** `serp_audit.py` records `Results_Requested` on each overview row, so
the figure is judged against the run's own request rather than a config file
that may have changed since (P6).
`brief_data_extraction._total_results_is_credible` requires
`Total_Results > Results_Requested`, falls back to the configured `serpapi.num`
for a run written before the field existed, and withholds the figure when
neither is known — a market size nobody can check is one the brief must not
state. `total_results_basis` records which of the three it was. Downstream,
absent now means absent: the prompt payload omits the field (the rule the Moz
metrics already followed), the tie-break falls back to the action group,
`combined_total_results` sums only credible figures and publishes
`combined_total_results_keywords` beside it (P2), and the prompts drop both the
unconditional heading and "estimated market scale" as a gloss.

**Result on the 2026-11-19 data.** All ten keywords now read
`total_results_measured: false`, basis `serpapi_num_from_config`. The brief's
scale sentence reads "Google reported no result-count estimate" in place of
"100 total results". The markdown report never printed the figure, so it is
unchanged; `report_clarity_spec.md`'s instruction to start printing it is
marked superseded.

**Verification.** Tests: `tests/test_total_results_is_not_a_market.py` (26
tests, 44 subtests), including a guard on the premise — that the run's raw
figures really are page-sized — so the suite cannot pass for the wrong reason.
Mutation gate 10 of 10 caught. `serp_audit.py`'s 2200-line ceiling guard
forced the new comment to be shortened rather than the ceiling raised.
Re-measured with `refresh_analysis_outputs.py` plus a report regeneration,
step 1.2 at exit 0 — no SerpAPI calls.


### Backlog (continued)

- `docs/USER_MANUAL.md`'s worked example of the "Ranked results classified"
  line still quotes a pre-2026-11-19 run and omits the host-inferred clause the
  line now carries. Adjacent, found while documenting this chunk, not fixed.
- `_get_keyword_action`'s seven action labels are Python literals in
  `generate_insight_report.py`. They are editorial words with no config home,
  the same class of debt the vocabulary files were created to hold. Adjacent,
  not fixed: externalising all seven is its own chunk.
- `my parents and siblings` carries an `informational` verdict at 83% but 5 of
  its 6 classified rows are host-inferred and only 1 is the page's own
  evidence, and its real top 10 is Canadian news about bereavement (harm
  reduction deaths, missing and murdered women, Portapique) with no
  counselling site at all. Intent classification says nothing about topical
  fit; nothing in the report pairs the verdict with the host-inferred share
  beside it, so a verdict resting almost entirely on inference reads like any
  other.
- `family dynamics` ranks six unrecognised small hosts and still has no
  verdict. Unlike `family roles` this is a genuine measurement gap, not a
  keyword problem.
- `publisher_domains` contains `psychologytoday.com/us/blog`, a path. The
  classifier matches hosts only, and checks `directory_domains` first anyway,
  so the entry can never fire — it is dead, and the path distinction it was
  reaching for is not expressible in these lists.
- `media_domains` holds `amazon.ca`, a retailer, under a name meaning media.
  The type is excluded from host inference, so nothing reads it wrongly today.
- Every keyword of the 2026-11-19 run recorded `moz: {"data_available": false,
  "status": "not_fetched"}`, and the account's rows for the period are spent —
  Moz authenticates and answers, it returned HTTP 403 `insufficient-quota`.
  `not_fetched` collapses that into the same state as a call never attempted,
  so the report cannot say whether the demand figures are missing until a
  reset date or missing until somebody changes the config. The states want
  separating the way `fetch_retryable` and `unreachable` were in chunk Y2,
  with the words in a vocabulary file rather than Python. Adjacent, found
  while checking demand, not fixed.

## 2026-11-21 — the first run with real Domain Authority

DataForSEO credentials were added and `run_feasibility.py` ran against the
2026-11-19 JSON: 72 of 72 URLs answered, 69 carrying a rank, 3 with no rank
record, and the client's own DA measured at 32. Ten keywords scored — 0 High,
3 Moderate, 7 Low — and `recommended_play` re-routed for 3 of them now that
the DA data exists. Nothing in the run failed.

Two checks that came back clean, recorded so they are not re-investigated:

* **DA 0 is real, not a null coerced to zero.** Eight of ten keywords report a
  weakest competitor of 0, which has the shape of the H2 defect. It is not:
  `da_cache` holds 2 genuinely NULL rows beside 15 zeros, so the two states are
  still distinct, and today's zeros are small local sites
  (`heirloomtherapy.com`, `norgate.sd44.ca`, `familydynamics.business`) for
  which a DataForSEO rank of 0 is plausible.
* **The client DA measurement beat the config value.** `feasibility.client_da`
  says 35; DataForSEO measured 32; the run used 32 and said in the log that the
  config value was not used because it may be on another provider's scale.

### Backlog (continued)

- The neighbourhood-pivot gate never reads the keyword's own text, so
  `family of origin therapist near me` is refused a pivot on the grounds that
  it is `commercial_investigation` — the report tells the owner that
  "proximity substitutes for authority only when the searcher wants a service
  in a place" about a query that says "near me". `pivot_gate_source` is
  `serp_intent.primary_intent` alone and `feasibility.pivotable_intents` is
  `[local, transactional]`, so the single strongest local-intent signal in
  search is invisible to the gate. The repo already knows this —
  `profile_questions._NEAR_ME` treats "near me" as a local marker when
  generating AI-visibility questions — so one fact is implemented in one
  module and contradicted in another, and it suppresses the lever the report
  itself calls "the equalizer for non-profits". Found by running feasibility.
  **Fixed 2026-11-21** — see below.
- Report §5c's "Weakest (non-dir)" cell renders as `{min_competitor_da}
  ({min_non_directory_da}?)`, which prints `0 (0?)` and `0 (61?)` — a bare
  trailing question mark with nothing saying what is being asked. On
  `how my childhood affects my relationships` that cell is `0 (0?)`, which is
  the run's strongest piece of evidence in the client's favour: a DA-0
  non-directory page holds a top-10 slot, so authority is not the barrier on
  that keyword. The verdict is right (Moderate, rank play) and the evidence
  for it is illegible. Adjacent, not fixed.
- `feasibility.client_da: 35` is stale — measured 32 on 2026-11-21. Harmless
  while a measurement exists, because the run prefers the measurement and
  says so, but it is the value used when no provider answers, and a
  three-point error there moves every gap. Adjacent, not fixed.

## 2026-11-21 — the pivot gate reads the keyword's own words

- The neighbourhood-pivot gate read the SERP's classified intent and never the
  keyword text, so `family of origin therapist near me` was refused a pivot as
  `commercial_investigation`. The report then explained to the owner that
  proximity substitutes for authority "only when the searcher wants a service
  in a place" — about a query that says near me — suppressing the one lever
  the report calls the equalizer for non-profits. `_pivot_gate` now checks the
  keyword against the editorial `local_intent.markers` list in
  `serp_vocab.yml` first; a marker permits the pivot whatever the SERP was
  classified as, never refuses one, and `gate_source` records which marker
  decided (`keyword local marker (near me)`).
- The phrase "near me" had two homes: `profile_questions._NEAR_ME` used it to
  generate a question variant while the gate that decides whether such a
  keyword pivots at all knew nothing about it. One fact implemented in one
  module and contradicted in another is how the defect above survived.
  `serp_vocab.yml local_intent.near_me_phrase` is now the single home, read by
  `profile_questions`, and a test fails the build when the phrase is not among
  the markers or when a second copy of it appears in Python as data.
- Verified on the run that found it: the gate answers
  `(True, 'keyword local marker (near me)')` for the live keyword and its
  measured `commercial_investigation` block. 19 tests + 11 subtests in
  `tests/test_pivot_gate_reads_the_keyword.py`; both mutations of the decisive
  line (never matching, and matching inverted) fail the suite.
