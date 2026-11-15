# Serp-Compete — correctness / data-path review

**Scope & method.** Read fully: `CLAUDE.md`, `README.md`, `LEARNINGS.md`, `TODO.md`, `RECONCILIATION_CHANGES.md`, `docs/FEATURE_GUIDE.md`, `docs/DATA_PERSISTENCE_MAP_v3.md`, `docs/TEST_RUN_CHECKLIST.md`, `shared_config.json`, `handoff_schema.json`, and every module under `Serp-compete/src/` (main, orchestrator, step_dag, ingestion, enrichment, api_clients, database, scoring_logic, semantic, eeat_scorer, cluster_detector, geo_profiler, analysis, comparison_features, serp_overlap, positioning, sov_analyzer, brand_demand, brand_utils, handoff_moz, gsc_performance, velocity_module, risk_radar, youtube_client, youtube_presence, reframe_engine, reporting). Skimmed: `third_party_crawlers.py`, `strike_mapper.py`, `infiltrator.py`, `competitor_mining.py` (all confirmed off the run path), the two test suites (grep for what they lock), and on the producer side `serp-discover/handoff_writer.py`, `moz_competitor.py`, `moz_client.py`, `ai_visibility_export.py` + schema. Real artefacts used as evidence: `competitor_handoff_couples_therapy_20260502_1634.json` (34 domains, 15 with a `www.` prefix) and `Serp-compete/strategic_briefing_run_11.md` (a real past report). The repo DB `living_systems_intel.db` is empty (created by the test baseline), so no real longitudinal rows were available. Probes (all under `docs/review_2026-11-04/probes/compete/`, PYTHONPATH=`Serp-compete`, external calls mocked): `probe_brand_www.py`, `probe_brand_demand.py`, `probe_reporting_crossjoin.py`, `probe_pa_zero_fragile.py`, `probe_cache_estimate_flip.py`, `probe_visibility_cliff.py`, `probe_gsc_block_sentinel.py`, `probe_feasibility_stale.py`, `probe_report_truncation.py`, `probe_semantic_terms.py`, `probe_dfs_abort.py`. Items already listed under TODO.md "Cold-sweep findings" / "SC-8.4" were not re-reported.

Counts: **S1 × 4, S2 × 8, S3 × 6** (CONFIRMED 15, PLAUSIBLE 3).

---

### C-C-01 · `www.` handoff domains derive brand `"www"` → wrong Branded-Demand, AI-SoV and YouTube rows for ~half the competitive set
- Severity: S1
- Verdict: CONFIRMED
- Where: `src/brand_utils.py:34` (`derive_brand_name`: `str(domain).split(".")[0]`); call sites `src/comparison_features.py:101,118,206` (C1 brands, C3 `brand_by_domain`, YouTube `brand_by_domain`); `src/youtube_presence.py:41` (`_stem` has the same `split(".")[0]`) used as the YouTube `search_term` at `:92`.
- Evidence: Tool 1 writes `"domain": urlparse(url).netloc.lower()` (`serp-discover/handoff_writer.py:124`) so `www.` is kept; 15 of 34 domains in the real handoff in the repo are `www.*`. Probe `probe_brand_www.py`: `www.jerichocounselling.com -> 'www'`, `www.averytherapy.com -> 'www'`, `www.psychologytoday.com -> 'www'`. Probe `probe_brand_demand.py` shows C3 sending the query set `['www', 'www reviews', 'www pricing']` for *each* www-domain and persisting identical volume/share rows for them (`www.jerichocounselling.com www 1020 33.33 volume_estimated`, `www.averytherapy.com www 1020 33.33 …`). `normalise_domain()` (the fix for the omit-list `www.` leak in LEARNINGS) exists in the same file but is not applied here.
- Failure scenario: any handoff produced by Tool 1 for a site whose canonical URL is `https://www.<brand>.com`. (a) Branded-Demand Benchmark: every such competitor is attributed the DataForSEO volume of the query `"www"` (and `"www reviews"` …), a huge, identical, meaningless number that dominates `branded_volume_share` and pushes the client's share toward 0% — rendered as fact in the briefing and the `Branded Demand` sheet, with no caveat (`volume_unavailable` only fires when *everything* is zero). (b) AI Share-of-Voice: `competitor_brand_set` contains `"www"`, so a mention of "Jericho Counselling" that is not also cited falls into `other` and is dropped from the per-engine "Mention share" line. (c) YouTube Presence: the search term is literally `"www"` and the identity scorer compares titles against stem/token `"www"`, so the row is recorded as `none_found` / `has_channel = 0` — a definitive negative for a competitor that may well have a channel (FEATURE_GUIDE promises `none_found` = "no channel").
- Fix: run the domain through `normalise_domain()` (strip `www.`, lower-case) at the start of `derive_brand_name` and in `youtube_presence._stem`; better, normalise once in `main.convert_handoff_to_targets` so every domain-keyed table is canonical. Tests: `test_brand_utils.py::test_www_prefix_stripped` (`www.jerichocounselling.com -> jericho`), `test_youtube_presence.py::test_search_term_not_www`, and a `test_brand_demand.py` case asserting two different `www.` domains never share a query set.
- Pattern: P7 (adversarial input), P3/P6 (contract between producer domain form and consumer)

### C-C-02 · Competitor Ranking Summary `total_keywords` is inflated by a `competitor_metrics × traffic_magnets` cross join (markdown and Excel)
- Severity: S1
- Verdict: CONFIRMED
- Where: `src/reporting.py:107-123`
- Evidence: the query joins `competitor_metrics m` (one row per ranked keyword, up to 10/domain) with `traffic_magnets tm ON m.run_id = tm.run_id AND m.domain = tm.domain` (up to 3 rows/domain, no URL condition) and then `SUM(CASE WHEN m.keyword IS NOT NULL … THEN 1 …) AS total_keywords`. Probe `probe_reporting_crossjoin.py` (1 domain, 10 keyword rows, 3 magnets): markdown row `| comp.com | 3 | 30 | 5.5 | Medical |` and the `Competitor Summary` sheet `total_keywords = 30`; true value 10. The real `strategic_briefing_run_11.md` shows exactly this signature: `total_keywords` is 30 for most domains, 20/10 for domains with 2/1 audited pages, 21 = 7×3, 27 = 9×3.
- Failure scenario: every run. A domain with 10 ranked keywords and 3 audited pages reports 30 keywords; a domain with 1 audited page reports the true count — so the column mis-ranks competitors by breadth (and `competitor_mining.get_top_domains` sorts by this column). `avg_pos` is numerically unaffected only because the replication factor is uniform per domain.
- Fix: compute keyword/position aggregates from `competitor_metrics` alone (`COUNT(DISTINCT m.keyword)`) and join a pre-aggregated per-domain subquery of `traffic_magnets` (`SELECT domain, MAX(medical_score)… GROUP BY domain`). Test: seed 10 metric rows + 3 magnets and assert `total_keywords == 10` in both the markdown and the sheet (a behaviour test, not a source grep — cf. TODO's note on `test_coverage_is_persisted…`).
- Pattern: P7 (looks-right-but-wrong number), P2

### C-C-03 · A missing / failed Moz PA is stored as `0` and then treated as a measured authority drop ("Fragile Magnet", twice) and as "not high-authority"
- Severity: S1
- Verdict: CONFIRMED (probe) — the Moz-failure trigger itself is live in production per C-C-04
- Where: `src/main.py:401-412` (`except … print warning`; `avg_pa = … else 0`; `if avg_pa > 50`), `:453` (`pa = moz_metrics_map.get(url, 0)`), `:454` → `database.save_competitor_history` (`drift = pa - prev_pa`), `:496-504` → `velocity.save_market_snapshot(da=pa)`; consumers `database.get_feasibility_drift` (`drift < -2`), `velocity_module.get_market_alerts` (`da_drift < 0`), both rendered by `reporting.py:87-104`.
- Evidence: probe `probe_pa_zero_fragile.py` — run 1 PA 35, run 2 Moz raised: `get_feasibility_drift → [{'url': …, 'pa': 0.0, 'drift': -35.0, 'alert': 'Fragile Magnet'}]` and `get_market_alerts → [{'type': 'Fragile Magnet', … 'da_drift': -35, 'advice': 'Strike this page now.'}]`. No `NULL` is ever written: `competitor_history.pa` and `market_history.da` cannot express "unknown".
- Failure scenario: Moz 401/429/5xx (or a URL Moz has no record for) on one run → every page of every affected domain appears under *🚩 Expert Alerts: Fragile Magnets* and *⚡ Market Velocity Alerts* with "Page Authority drifted by -35 … publish now". The next working run reports the mirror image (+35). In the same run `avg_pa` becomes 0 so the "PA > 50" skip is silently disabled and `competitors.avg_da` is never written (feasibility / positioning DA lost) — the report never states that PA was unavailable. The console warning is the only trace (P25-class).
- Fix: store `NULL` when PA is unknown; skip drift when either side is NULL; make the high-authority filter and `save_competitor_summary` skip (and say "unmeasured") on an empty map; print and persist an "N of M URLs had PA" count. Tests: `test_new_logic.py` second-run case with `pa=None` asserting no drift alert; a `main`-level test with `MozClient.get_url_metrics` raising asserting no `Fragile Magnet` and no `competitors` row.
- Pattern: P1 (transient → permanent negative), P2, P6

### C-C-04 · `MozClient.get_url_metrics` reads a response field (`url`) the Moz API does not return, and calls an endpoint the sister tool documents as legacy
- Severity: S1
- Verdict: PLAUSIBLE (cannot hit the live API from here)
- Where: `src/api_clients.py:177,183` (`https://api.moz.com/v2/url_metrics`), `src/main.py:404` (`moz_metrics_map[res.get('url')] = …`)
- Evidence: Moz's url-metrics objects identify the target as `page` (scheme-less, e.g. `"page": "moz.com/"`), not `url`; serp-discover's own fixture, "a trimmed but faithful subset of the real site_metrics object", models it as `"page": url.removeprefix("https://")` (`serp-discover/test_moz_client.py:46`), and `serp-discover/moz_client.py:16` says the legacy endpoint was `lsapi.seomoz.com/v2/url_metrics`, now replaced by JSON-RPC `api.moz.com/jsonrpc`. Compete's unit test (`test_api_clients.py:39`) mocks `{"url": …}` and therefore locks the wrong shape. Consistent with the real `strategic_briefing_run_11.md`, in which `mapquest.com`, `m.yelp.com`, `healthlinkbc.ca`, `foundrybc.ca` all survived the "avg PA > 50 is skipped" filter.
- Failure scenario: either the endpoint is gone (non-200 → `raise` → C-C-03's `pa = 0` path on every run) or it answers with `page` keys → `moz_metrics_map == {None: <PA of the last result>}`, so `avg_pa` is a single arbitrary URL's PA, every per-URL `pa` is 0, EEAT gets `domain_authority=None`, and `competitors.avg_da` is one page's PA. In both cases the "high-authority filter" documented in FEATURE_GUIDE §2.2 does not work.
- Fix: match on `page` (and normalise both sides scheme-less) or, better, reuse discover's `moz_client` shape; add a fixture-driven test copied from discover's real response; log "Moz returned N metrics for M URLs" (P2). Confirm the endpoint on the next live run (TEST_RUN_CHECKLIST §1 has no Moz line — add one).
- Pattern: P22 (shape assumed, not checked), P5, P6

### C-C-05 · `VelocityTracker.get_market_alerts` is not run-scoped: a URL that left the competitive set is re-alerted "Strike this page now" on every later run
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/velocity_module.py:85-105` (`SELECT DISTINCT url, keyword, domain FROM market_history` — no run/date filter; `calculate_velocity` compares the last two rows ever), consumed by `main.py:583` → `reporting.py:96-104`.
- Evidence: probe `probe_pa_zero_fragile.py`, run 3 (URL absent from the run): `run3 velocity alerts (NOT run-scoped, stale): [{'type': 'Fragile Magnet', 'domain': 'comp.com', … 'da_drift': -35}]` while the run-scoped `get_feasibility_drift` correctly returns `[]`.
- Failure scenario: a competitor skipped this run (omitted, PA-filtered, DFS 429, dropped from the handoff) keeps appearing under *⚡ Market Velocity Alerts* with its last recorded drop, indefinitely; the section grows monotonically with the table. Secondary: `market_history.rank` is `rank_absolute` and can be NULL → `prev[0] - curr[0]` raises `TypeError` inside `get_market_alerts`, which `run_audit` does not guard, aborting the run *after* all paid API work and before the report is written.
- Fix: snapshot with a `run_id` column (table is created by `VelocityTracker`, so add the ALTER beside the CREATE — the class TODO.md warns about) and compare only rows of `run_id` vs the latest earlier run per (url, keyword); null-guard rank/da. Test: dirty-state test (P8) with three runs where the URL is absent from the third.
- Pattern: P8, P1

### C-C-06 · `visibility_cliff` is computed on a ≤3-row sample, so one lost keyword / one failed scrape / a same-day re-run is a "visibility cliff"
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/main.py:459-504` (snapshot only for the first `max_audit_pages_per_domain` URLs, and only after `scrape_content` did not error), `src/database.py:760-772` (`SUM(rank <= 10) … GROUP BY DATE(timestamp)`, all runs of a day merged), `src/risk_radar.py:29-49`.
- Evidence: probe `probe_visibility_cliff.py`: `[3,3,2] → {'visibility_cliff', 'medium', drop 33.3%}`, `[2,2,1] → 'high' 50%`; two identical runs on day 1 + one on day 2 → series `[6.0, 3.0]` → `'high', drop 50%`. The series maximum per domain per run is `max_audit_pages_per_domain` (3) because `save_market_snapshot` sits inside the processed-URL branch; a page that returns `extraction_status == "error"` hits `continue` before the snapshot.
- Failure scenario: a competitor whose third audited page timed out this run, or whose one page slipped from rank 10 to 11, is reported under *Reputation-Risk Radar → Competitor risk signals* as a `visibility_cliff` ("a moment to strike"); the owner re-running twice in one day (the documented cache use-case) makes *every* competitor a `high` cliff the next day. The parasite/volatility signals are unaffected.
- Fix: build the series from `competitor_metrics` (all ranked keywords, one row per run) keyed by `run_id`, not by date; skip the detector when the per-run sample is below a config minimum (`risk_signals.cliff_min_sample`); record a snapshot for an errored scrape as `rank = NULL` rather than omitting it. Tests: adversarial P7 case "one of three rows missing is not a cliff"; P8 case "two runs same day".
- Pattern: P7, P1, P8, P4

### C-C-07 · `LIMIT 30` / `LIMIT 20` in reporting silently truncate the EEAT, GEO and Traffic-Magnet sections *and* their Excel sheets, and the Systemic-Vacuum list is a subset of the truncated set
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/reporting.py:159-166` (`eeat_scores … ORDER BY url LIMIT 30`), `:214-224` (`geo_profiles … LIMIT 30`), `:193-198` (`traffic_magnets … ORDER BY est_traffic DESC LIMIT 20`), `:205` (vacuums from `df_magnets`), `:489-498` (same frames written to Excel).
- Evidence: probe `probe_report_truncation.py` (15 competitors × 3 pages): `EEAT Scores rows in Excel: 30 | in DB: 45`, `GEO Extractability … 30 | 45`, `Traffic Magnets … 20 | 45`, and only domains `a…j` appear (ORDER BY url is alphabetical), `vacuums listed in MD: 20 of 45 Surface-Level magnets`. No "N of M" anywhere.
- Failure scenario: the real handoff has 34 domains; a run audits ~100 pages. The *EEAT Competitive Analysis* and *GEO* sections and sheets show the alphabetically-first ~10 competitors and omit the rest; *Traffic Magnets* shows 20 rows chosen by `est_traffic DESC` with heavy ties (all DFS `etv` 0 is common) → an arbitrary subset; *⚡ Systemic Vacuums* ("write these first") is therefore an arbitrary subset too. FEATURE_GUIDE §8.2 says each sheet is "the tabular form of the matching briefing section" — the sheet, which should be the full export, is truncated identically.
- Fix: keep a display cap for markdown but write the full frame to Excel; print "showing N of M" in the markdown header; sort EEAT/GEO by a meaningful key (tier, then url). Test: 45 rows → sheet has 45; markdown header carries "of 45".
- Pattern: P2

### C-C-08 · On a cache hit, the tier counts fed to `tag_competitor_position` are a "rough estimate" that flips `market_position` between run 1 and run 2 with identical content
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/main.py:508-509` (`scores['systems_score'] / 0.5 if < 2.0 else 0`, `/ 2.0 if >= 2.0 else 0`), consumer `database.tag_competitor_position` (`systems_t3 > 0 → "Direct Systemic"`, `systems_t2 > 10 → "Generalist"`), rendered in *Competitor Ranking Summary* (`market_position`, `recommended_strategy`).
- Evidence: probe `probe_cache_estimate_flip.py`: `t2=4,t3=0 (score 2.0)` → run 1 `Unknown`, run 2 (cached) `Direct Systemic`; `t2=12,t3=0 (score 6.0)` → run 1 `Generalist`, run 2 `Direct Systemic`. Any page with weighted systems score ≥ 2.0 and no Tier-3 term is re-labelled as having Tier-3 depth on the cached run.
- Failure scenario: run on Monday (fresh) → "Generalist — target their lack of Tier 3 depth"; re-run Wednesday (cache) → "Direct Systemic — use Functional Facts…" for the same unchanged page. The `competitor_metadata` row is domain-keyed (`ON CONFLICT … UPDATE`), so the wrong label also overwrites the right one.
- Fix: persist `t2_count`/`t3_count` in `semantic_audits` (ALTER + CREATE) and return them from `was_audited_recently`; delete the estimate. Test: P8 second-run test asserting `market_position` equal across fresh and cached runs for the same scores.
- Pattern: P8, P22 (return shape of `was_audited_recently` lacks the fields the caller needs)

### C-C-09 · `gsc_performance.analyze_gaps` still checks for the pre-`ScrapedPage` `"BLOCK"` sentinel, so a 429/timeout on the client's *own* page is cached as a 0/0 semantic audit for 7 days
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/gsc_performance.py:333-338` (`if content and content != "BLOCK":` … `save_semantic_audit(page, 0, 0, run_id=0)`); the equivalent bug in `main.py:476-484` was fixed ("never a 'BLOCK'/'' string, as the pre-ScrapedPage code assumed") but this call site was not.
- Evidence: probe `probe_gsc_block_sentinel.py` with `extraction_status="blocked"`: `semantic_audits rows after a BLOCKED own-page scrape: [('https://livingsystems.ca/anxiety', 0, 0, 0)]`; `was_audited_recently → {'medical_score': 0, 'systems_score': 0, …}`.
- Failure scenario: the client's site rate-limits the scraper once → each of its top-20 pages is recorded as "no systems language"; the *Clinical Mismatches* check (`systems_score > 5`) is suppressed for a week (false negative, "no mismatches") and the console says "⚡ Using cached local audit". Also a transient-as-permanent write with `run_id = 0`.
- Fix: branch on `content.extraction_status` exactly as `main.py` does and do not persist blocked/error pages. Test: mocked `scrape_content` returning a blocked page → no `semantic_audits` row.
- Pattern: P22, P1

### C-C-10 · *Competitor Feasibility* lists every domain ever stored in `competitors`, not this run's
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/database.py:885-896` (`get_competitor_das`: `SELECT domain, avg_da FROM competitors` — no run scope), called from `src/comparison_features.py:51` and persisted per run by `save_competitor_feasibility`; rendered at `reporting.py:287-301` and the `Feasibility` sheet. Contrast `get_positioning_inputs` (`:849-854`), which correctly restricts DA to domains audited this run.
- Evidence: probe `probe_feasibility_stale.py`: a domain audited only in an earlier run is persisted for the new run — `[('old-run-only.com', 60, 0), ('current.com', 30, 1)]` — while `get_positioning_inputs` returns only `current.com`.
- Failure scenario: after a few runs with changing handoffs, the feasibility table (✅/❌ per competitor) names competitors that are not in this run's handoff at all, with DA values of unknown age (the `competitors` row is overwritten in place, `last_crawled_at` not rendered).
- Fix: intersect with `competitor_keywords`/`run_domains` in `run_comparison_features` (or add a `run_id` filter via `competitor_metrics`). Test: P8 dirty-state test as in the probe.
- Pattern: P8, P6

### C-C-11 · Branded-Demand: a provider failure for *one* brand is persisted as `branded_search_volume = 0`, `estimation_basis = volume_estimated`
- Severity: S2
- Verdict: CONFIRMED
- Where: `src/brand_demand.py:84-92` (`vols = volume_provider(queries) or {}` → `volume[domain] = 0`), `:95-96` (`volume_unavailable = total == 0 and len(volume) > 0` — all-or-nothing), `src/api_clients.py:59-92` (`get_search_volume` returns `{}` after three failed attempts, and also on a 200 with an empty `result`).
- Evidence: probe `probe_brand_demand.py` with the provider returning `{}` for one brand: `clearcounselling.ca clear 0 0.0 volume_estimated` beside `… 1020 33.33 volume_estimated`.
- Failure scenario: a 429 on the third of twenty per-brand calls → that competitor is reported as having zero branded demand and 0.00% share (a "shrinking brand" in FEATURE_GUIDE's reading); the client's own row can get the same treatment. Only a total outage triggers the "source returned nothing" caveat.
- Fix: make `get_search_volume` return `None` (not `{}`) on failure, and let `compute_branded_demand` write `branded_search_volume = NULL`, `estimation_basis = "volume_unavailable"` per domain; carry "N of M brands measured" into the section. Test: one-of-three provider failure → that row NULL and basis unavailable; share computed over measured rows only.
- Pattern: P1, P2

### C-C-12 · `DataForSEOClient.get_relevant_pages` has no retry and no exception handling; a non-200 drops the competitor with no report trace, a raised `RequestException` aborts the run after `create_run`
- Severity: S2
- Verdict: CONFIRMED (trace) / abort path PLAUSIBLE under realistic network conditions
- Where: `src/api_clients.py:17-57` (`requests.post` bare; `!= 200 → return []`), `src/main.py:393-395` (no `try`; `if not pages: continue`), `:523` (`competitor_keywords[domain]` set only after pages arrive), `src/reporting.py:147-152` ("Missing Data Alert" compares `expected_competitors` — which is exactly the set of domains that *had* pages — to the same set, so it can never fire for a dropped domain).
- Evidence: probe `probe_dfs_abort.py`: `get_relevant_pages call at main.py line 393 | enclosing try blocks: 0`, `retry loop … False | exception handling: False`. `get_search_volume` in the same file *is* hardened (timeout + 3 attempts + backoff), so the class was not applied to its sibling (LEARNINGS checklist item 1).
- Failure scenario: (a) DataForSEO 429/5xx on domain 17 of 34 → domain 17 is absent from every section with no "N of M competitors audited" line; the console line is the only trace. (b) `ConnectionError`/`ReadTimeout` → traceback, no report, an orphan `runs` row; the next run's `get_volatility_alerts` silently compares against that empty run and reports nothing. `pre_flight_check`'s `requests.get(...)` at `main.py:247` has no timeout at all.
- Fix: harden `get_relevant_pages`/`get_url_metrics`/`scrape_content` like `get_search_volume` (timeout + retry + backoff, distinguish 429 from 4xx); collect `skipped_domains` with a reason in `run_audit` and pass it to the report ("Audited N of M handoff domains; skipped: …"); add a timeout to the pre-flight call. Test: a `main`-level test with `get_relevant_pages` returning `[]` for one domain asserting the report names it.
- Pattern: P5, P2, P1

### C-C-13 · The handoff's `client_brand_names` is dropped and `client.brand_names` never exists in config, so the client's branded-demand query is the bare stem `livingsystems`
- Severity: S3
- Verdict: CONFIRMED
- Where: `src/main.py:60-75` (`convert_handoff_to_targets` discards `client_brand_names`), `src/comparison_features.py:119-121` (`shared_config["client"]["brand_names"]` — not a key in `shared_config.json`, which has `client.name`).
- Evidence: the real handoff carries `client_brand_names: ['Living Systems']`; `brand_by_domain['livingsystems.ca'] == 'livingsystems'` (probe `probe_brand_demand.py`), so C3 measures volume for `livingsystems`, `livingsystems reviews`, … rather than `living systems counselling`.
- Failure scenario: the ⭐ client row in *Branded-Demand Benchmark* under-reports the client's own brand pull relative to competitors whose stems happen to be their real brand word.
- Fix: thread `client_brand_names` from the handoff (fallback `client.name`) into `run_comparison_features`; document the key in `shared_config.json`. Test: handoff with `client_brand_names` → the client's query set starts with that string.
- Pattern: P21 (built field with no consumer), P4

### C-C-14 · Documented config keys with no reader: `handoff.supported_versions/minimum_version/legacy_fallback_enabled`, `gsc_settings.date_range_days/position_target_max`, `technical.score_normaliser`, `penalty_thresholds.pseudo_systems_threshold`, `step_dag.*`, `orchestrator.step_timeout_seconds/log_level`
- Severity: S3
- Verdict: CONFIRMED
- Where: `shared_config.json:834-885`; grep of `Serp-compete/src` finds no reader for any of these (`src/gsc_performance.py:70` hard-codes `days=90`; `src/step_dag.py` is imported only by its test; `handoff_schema.json` versions are `1.0`/`1.1`).
- Evidence: `README.md:125` and `docs/USER_MANUAL.md:323` tell the owner that `handoff.supported_versions` (`2.0`, `2.1`) is "Tool 1 handoff formats accepted" — no version check exists, and the real versions are `1.0`/`1.1`, so editing it (or receiving a `2.0` handoff) changes nothing.
- Failure scenario: the owner "tunes" `score_normaliser` or `date_range_days` and sees no effect; a future Tool 1 bump to `schema_version: 2.0` is neither accepted nor rejected by version, only by `additionalProperties: false`.
- Fix: either wire the keys (read `date_range_days` in `fetch_performance_data`; enforce `supported_versions` in `get_latest_market_data`) or delete them and the doc lines. Test: `test_config_integrity.py` assertion that every top-level config key is referenced by at least one `src` module (P21 for config).
- Pattern: P4, P21

### C-C-15 · Scoring: `tag_competitor_position` thresholds are hard-coded, and the configured Tier-2 term `self-regulation` can never match
- Severity: S3
- Verdict: CONFIRMED
- Where: `src/database.py:965-971` (`traffic > 1000 and medical_score > 15`, `systems_t2 > 10`), `src/semantic.py:365-385` (single-token match via spaCy tokens; phrase match only `if " " in phrase`).
- Evidence: probe `probe_semantic_terms.py`: `'Self-regulation and self-regulation again.' → t2=0` (spaCy splits the hyphenated term into `self`, `-`, `regulation`); `'differentiation of self' → t2=1 t3=1` (the same text is counted in two tiers — intended or not, it is undocumented).
- Failure scenario: a competitor page built around "self-regulation" scores 0 on systems language and becomes a *Systemic Vacuum* (and a gpt-4o reframe target). The position thresholds cannot be tuned without editing Python, contrary to `CLAUDE.md` ("editorial content … belongs in config").
- Fix: match hyphenated terms via the phrase path (`if " " in phrase or "-" in phrase`) or regex with word boundaries over the raw text (as `eeat_scorer._count_tier_mentions` already does); move the three thresholds to `technical.position_thresholds`. Tests: adversarial P7 vocabulary test; config-parity test.
- Pattern: P7, P4

### C-C-16 · Orchestrator: the handoff the user *selects* is only honoured when "Copy handoff" is ticked, and the "Reports Directory" setting is never used by the writer
- Severity: S3
- Verdict: CONFIRMED (trace)
- Where: `src/orchestrator.py:184-197` (copy is optional), `main.py:46-51` (`find_latest_handoff_file` = newest mtime in `PROJECT_ROOT`, ignores the selection), `orchestrator.py:99-110` (saves `orchestrator.reports_dir`), `reporting.py:479-480` (writes to CWD = `Serp-compete/`), `orchestrator.py:117-154` (browses `reports_dir`).
- Evidence: with the checkbox cleared, `cmd = ["python3", "src/main.py"]` receives no path and `main.py` audits whichever `competitor_handoff_*.json` in the repo root is newest; the Streamlit log says "Running: … in Serp-compete" with no mention of which file was used. The `reports_dir` value is written to `shared_config.json` but nothing in `src/reporting.py` reads it.
- Failure scenario: owner picks an older handoff to compare, unticks the copy box → the report silently describes the newest file; owner sets a reports directory → new reports keep landing in `Serp-compete/` while "Previous Reports" looks elsewhere. (The "report reads a different database" class in TODO.md is verified fixed: `ReportGenerator`, `VelocityTracker` and `GSCManager` all resolve the DB relative to `shared_config.json`.)
- Fix: pass the selected path to `main.py` (`--handoff`) and have `get_latest_market_data` print the file it used into the report header; have `ReportGenerator` take an output dir from `orchestrator.reports_dir`. Test: P6 test that the report header names the handoff file.
- Pattern: P6, P21

### C-C-17 · SERP-overlap self-presence relies on one 5000-row GSC page over a 90-day average, compared against a same-day DataForSEO `rank_absolute` snapshot
- Severity: S3
- Verdict: PLAUSIBLE
- Where: `src/gsc_performance.py:77-86` (`rowLimit: 5000`, no `startRow` pagination; `days=90`), `src/main.py:439` (`rank_absolute`), `src/serp_overlap.py:129-141` (`self_present = raw_self <= top_n` vs `comp_top = {p <= top_n}`).
- Evidence: per-keyword absence is treated as a "real False" (module docstring) whenever the map is non-empty, so any query past row 5000 (GSC returns by clicks desc; zero-click long-tail is cut) reads as `exclusive_competitor` ("rivals rank, you're absent"), the top action queue. `rank_absolute` counts non-organic SERP elements while GSC `position` is a 90-day average over a different element model; the symmetric `<= 10` test is therefore applied to two different scales.
- Failure scenario: a site with >5000 query×page rows in 90 days gets false "you're absent" entries; a competitor organically #8 below three SERP features (`rank_absolute` 11) is counted as not in the top-N → `exclusive_self`.
- Fix: paginate with `startRow` until a short page; use `rank_group` (organic rank) for the top-N test and keep `rank_absolute` in evidence; state the window/scale mismatch in the section caveat. Test: a mocked GSC returning 5000 + 1 rows → the 5001st query present in the map.
- Pattern: P2, P6

### C-C-18 · Scraper: the homepage pre-visit and the page fetch have no retry; a transient failure consumes one of the domain's 3 audit slots and the page vanishes from the run (feeding C-C-06)
- Severity: S3
- Verdict: CONFIRMED (trace)
- Where: `src/semantic.py:72-77` (`session.get(base_url, timeout=10)` inside the same `try` as the page fetch → any homepage error returns `extraction_status="error"` for the page), `src/main.py:459-460,482-484` (`processed_urls.add(url)` *before* the fetch; `error → continue`).
- Evidence: a `ReadTimeout` on the competitor's *homepage* marks the target page unreadable even if the target would have loaded; the slot is spent, no `traffic_magnets`/`market_history` row is written, and no per-domain "audited N of 3 pages" reaches the report.
- Failure scenario: a slow competitor site → fewer audited pages, lower visibility series (C-C-06 cliff), and a smaller Traffic-Magnet pool, none of it visible in the artefact.
- Fix: make the homepage warm-up best-effort (own `try`), retry the page once with backoff, and record per-domain fetch coverage into the report. Test: homepage raising, page 200 → `extraction_status == "complete"`.
- Pattern: P5, P2

---

## Checked and found sound
- Handoff contract: `handoff_schema.json` is byte-identical in both repos; `moz` block optional, `moz.domains` keyed in the same `netloc.lower()` form as `targets[].domain`, so `restrict_to_run`/`anchor_coverage` scoping is consistent; `schema_version` 1.0/1.1 both validate.
- AI-visibility export: `sov_analyzer.compute_sov` reads exactly the keys `ai_visibility_export_schema.json` guarantees (`engines`, `brand_mentions{engine,brand,mention_count,questions_total,is_client}`, `ai_citations{engine,domain,brand,is_client,cite_count}`, `answer_sentiment{engine,brand,polarity}`); `find_av_export` honours the in-file `source_run_ts`/`data_available` selection contract and the `output/` location the exporter writes to; citation domains are compared `www.`-stripped on both sides.
- `anchor_coverage` / `anchor_texts_by_domain` / `detect_anchor_spam` transient-vs-terminal buckets, `collected_at` precedence, and the "unrecorded ≠ clean" caveat path in `reporting.py`.
- `yt_channel_presence` second-run idempotence (DELETE + INSERT per run), `has_channel` NULL for `error`, quota-budget stop marked `error` not `none_found`; `YouTubeDataClient` has timeout + retry + transient/terminal split.
- ALTER-beside-CREATE repairs for `sov_daily.cited_gap`, `yt_channel_presence.uploads_recent`, `anchor_coverage.reason`; `get_anchor_coverage` narrow `OperationalError` handling.
- `carry_forward_profile` allowlist, `run_id != ?` exclusion, and `finalize_domain_cluster` gate (fresh only when no page was cache-served); enrichment counters surfaced on the console.
- `database.load_db_path`, `VelocityTracker`, `GSCManager` all resolve the SQLite file relative to `shared_config.json` — the "report reads a different database" bug is fixed (fallback names differ only when `shared_config.json` is absent).
- `calculate_weighted_score` thresholds (`tier_1_max`, multiplier, weights) are read from config; label and score are the same object in markdown and Excel (same DataFrame); `INTEGER`-affinity columns preserve fractional `systems_score`.
- `serp_overlap` run-level `self_unknown` (empty GSC map → unknown, never absent), keyword case/whitespace normalisation on all join keys, `rollup_by_cell` partition property; `positioning` renormalises over present authority components and never silently lands in `middle`.
- `reporting.py` renders NULL EEAT scores as `—` (not `0` or `nan`), `has_channel` NULL as `?`, and `volume_unavailable` with the caveat.
- `semantic_audits` 7-day cache compares UTC `CURRENT_TIMESTAMP` with UTC `datetime('now', '-7 days')`.
- `competitor_mining.py`, `third_party_crawlers.py`, `strike_mapper.py`, `infiltrator.py`, `ingestion.py`, `step_dag.py` are not on the `run_audit` path (P21 dead capability, no data-path risk); their hard-coded paths affect only standalone invocation.

## Not examined
- Live behaviour of DataForSEO, Moz, OpenAI, YouTube and GSC endpoints (all mocked); the Streamlit UI at runtime.
- EEAT / GEO heuristic *weights* as editorial choices (only the arithmetic and None-handling were checked).
- `reframe_engine` prompt quality; OpenAI SDK's built-in retry/timeout was assumed (no explicit `timeout=` is set — a P5 nit, errors are surfaced as the reframe text).
- Excel formatting beyond row counts; markdown escaping of third-party text (already tracked in TODO.md).
- The `.claude/worktrees/...` copy of the source (older snapshot, not the reviewed tree).
