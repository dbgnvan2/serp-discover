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

## 7. What was checked and found sound (so it is not re-reviewed)

Each finding file ends with a "Checked and found sound" list. Highlights: the handoff schema is byte-identical on both sides and the consumer reads exactly the required fields; the AI-visibility export matches its consumer; `http_retry.py`, `moz_jsonrpc.py`, `moz_keywords.py` never cache an error; `intent_verdict.py`, `play_routing.py`, `aivi.compute_aivi` arithmetic are correct given correct inputs; compete's anchor-spam path, YouTube error/none split, serp_overlap `self_unknown` banner, positioning renormalisation and the "report reads a different DB" fix are all verified. The problems are upstream of the honesty scaffolding, not in it.
