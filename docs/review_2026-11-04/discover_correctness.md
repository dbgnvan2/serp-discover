# serp-discover — correctness / data-path review

**Scope & method.** Read in full: `CLAUDE.md`, `README.md`, `TODO.md`, `RECONCILIATION_CHANGES.md`, `docs/architecture.md`, `docs/methodology.md`, `docs/config_reference.md`, `docs/handoff_contract.md`, `handoff_schema.json`, `config.yml`; and the code of `serp_audit.py`, `run_feasibility.py`, `feasibility.py`, `metrics.py`, `storage.py`, `dataforseo_client.py`, `moz_client.py`, `moz_jsonrpc.py`, `moz_keywords.py`, `moz_competitor.py`, `http_retry.py`, `handoff_writer.py`, `refresh_analysis_outputs.py`, `run_pipeline.py`, `intent_verdict.py`, `play_routing.py`, `brief_validation.py`, `brief_llm.py`, `generate_content_brief.py`, `gsc_client.py`, `run_gsc_analysis.py`, `demand_dashboard.py`, `aivi.py`, `yaml_io.py`, the relevant halves of `brief_data_extraction.py` (extraction loop, keyword_profiles, play attachment), `generate_insight_report.py` (ranking, content plan, §5/§5c/§6, pattern evidence), `probe_ai_visibility.py` (probes, run loop, enrichment, report, main), `brief_rendering.list_recommendations`, `aio_exposure.py` core. Skimmed: `classifiers.py`, `url_enricher.py`, `commodity_score.py`, `foundational_score.py`, `engine_transfer.py`, `brand_mentions.py`, `citation_table.py`, `gsc_demand.py`, `serp-me.py` (output naming + post-feasibility regenerate), `config_validators.py` (threshold keys), and the serp-compete consumer (`Serp-compete/src/main.py`, `handoff_moz.py`). Not read: `config_manager.py`, `pattern_matching.py`, `query_variants.py`, `title_patterns.py`, `intent_classifier.py`, `bing_check.py`, `answer_sentiment.py`, `engine_recommendations.py`, `profile_questions.py`, `brief_prompts.py`, `brief_rendering.py` renderers, `ai_visibility_export.py`.

Ten probe scripts live in `docs/review_2026-11-04/probes/discover/probe_01…10_*.py`; every CONFIRMED finding below names the probe whose output reproduces it. The real 2026-08-26 run (`tests/fixtures/market_analysis_reference_run.json`) and its LLM brief (`content_opportunities_family_of_origin_work_20260826_2031.md`) were used as live evidence wherever possible. Nothing below is listed in `TODO.md` or `RECONCILIATION_CHANGES.md`.

---

### D-C-01 · SerpAPI `position` restarts at 1 on every paginated page; the pipeline uses it verbatim as `Rank`, so every "top-10" / "client ranks #N" number is page-relative
- Severity: **S1**
- Verdict: **CONFIRMED** (real run data + probe)
- Where: `serp_audit.py:941` (`"Rank": item.get("position", "N/A")`), `serp_audit.py:401-450` (`_merge_google_pages` concatenates pages without offsetting), `serp_audit.py:1547` (enrich `rank_val <= MAX_URLS_TO_ENRICH`), `serp_audit.py:1530` (rank persisted to `serp_results`). Consumers: `brief_data_extraction.py:1368,1737,1781` (top-10 domain map, `serp_intent` input `kw_rows[:10]`, `client_rank`), `run_feasibility.py:225-242` (top-10 by sorted Rank), `handoff_writer.py` (`rank`, `primary_keyword_for_url`, top-N selection), `metrics.py:137` (`s.rank <= 10`), `aio_exposure.py:219` (CTR curve by `client_rank`), rank deltas (`metrics.get_rank_deltas`).
- Evidence: the reference run (3 Google pages per keyword) carries Rank sequences `[1..9, 1..10, 1..10]` and `[1..9, 1..10, 2..9]`. The client's row for *family of origin counselling* is list index 24 (third page) yet `keyword_profiles[kw].client_rank == 7`; its `competitors_above` has 17 entries. The 2026-08-26 LLM brief then states "The client already ranks #7 … Six competitors rank above: Theravive (#1), FSGV (#2)…" and sets the success metric to "rank improvement from #7". `run_feasibility`'s "top 10" for that keyword is rows 1-4 of page 1, 1-4 of page 2, 1-2 of page 3. `test_serp_audit.py:391-395` models page 2 as `position: 11`, which is not what SerpAPI returns. Probe: `probe_01_pagination_rank.py`.
- Failure scenario: any run with `google_max_pages > 1` (Balanced mode = 3). Client on page 3 → reported as top-10, `client_ranks_but_not_cited` can fire → `reformat_play`; `serp_intent` is computed over positions 1,10,20,2,11,21,3,12,22,4; feasibility averages DA over the same mixed set; `est_ctr_loss` uses the page-1 CTR for a page-3 page; SQLite rank history shows a URL moving from page-1 #9 to page-2 #1 as "+8 improvement"; handoff `rank`/`primary_keyword_for_url` are wrong for Tool 2.
- Fix: in `_merge_google_pages`, renumber: `item["position"] = offset + i` where `offset` = organic rows merged so far (or use the page's `start` param). Do the same for `_merge_maps_pages` if maps ranks are consumed. Add a test feeding two pages with `position 1..10` each and asserting merged positions `1..20`, plus a fixture-based test asserting `max(Rank) == len(rows)` per keyword in the reference JSON. Re-run feasibility/brief on existing JSONs after the fix — they are all affected.
- Pattern: P6, P7

### D-C-02 · GSC transient failure (5xx / expired token / 403) is cached as `found = 0` for every unfetched query and served as "no GSC data" for the cache TTL
- Severity: **S1**
- Verdict: **CONFIRMED** (probe)
- Where: `gsc_client.py:174-178` (`fetched = {q: all_rows.get(q) for q in to_fetch}; self._cache_store(fetched, …)`), `gsc_client.py:186-232` (`_fetch_all_rows` `break`s on `response is None` / `not response.ok` / non-JSON and returns the partial dict), `gsc_client.py:303-320` (`_cache_store` writes `found=0` for `None`).
- Evidence: `probe_04_gsc_failure_cached_absent.py` — after one 503: `cache rows: [('couples counselling', 0, None), ('family therapy', 0, None)]`; a retry while the API is healthy makes **0 POSTs** and returns `{}`; `run_gsc_analysis` renders "Queries with no GSC data: N (no impressions recorded — reported as absent, not as zero)". Pagination has the same hole: page 2 failing marks every page-2+ query absent.
- Failure scenario: service-account token refresh fails once, or Google returns 503 twice → the sponge table, reformat candidates, branded-demand share (`gsc_demand`, persisted per run_ts) and §5f "Demand vs Clicks" all report measured absence; `gsc_demand.save_demand` writes a 0-click trend point for the run.
- Fix: make `_fetch_all_rows` return `(rows, complete: bool)` or raise on any non-OK/network outcome; only call `_cache_store` for absences when `complete` is True; propagate a `fetch_failed` flag so `run_gsc_analysis` prints "GSC fetch failed — N queries not measured" instead of the absent line. Test: mock a 503, assert no `found=0` rows and that a second call re-posts.
- Pattern: P1, P2

### D-C-03 · `run_feasibility` decides DA availability per run, so a keyword with zero DA-covered competitors is scored "Low Feasibility", and partial coverage averages are presented without N-of-M
- Severity: **S1**
- Verdict: **CONFIRMED** (probe)
- Where: `run_feasibility.py:306` (`da_data_available = bool(da_metrics)`), `run_feasibility.py:335-339` (per-keyword `competitor_das` list), `run_feasibility.py:361` (`compute_feasibility(client_da, competitor_das)`), `feasibility.py:86-93` (empty list → `"Low Feasibility"` with all numbers `None`); pivot path `run_feasibility.py:416-432` (`pivot_das=[]` when the DA fetch for pivot URLs returned nothing → `compute_feasibility(…, [])` → "Low Feasibility" for the pivot).
- Evidence: `probe_02_feasibility_partial_da.py`: keyword whose only ranked domains were unknown to the provider → `status='Low Feasibility' avg_serp_da=None gap=None`; keyword with DA for 1 of 10 URLs → `avg_serp_da=90.0, gap=55.0, Low Feasibility` with no coverage count. `compute_feasibility(35, []) -> 'Low Feasibility'`.
- Failure scenario: one Moz batch 503s (50 URLs) or DataForSEO has no record for small local sites → those keywords show 🔴 Low in `feasibility_*.md` and §5c, `_rank_keywords` scores them 1, `play_routing` normalises "Low" to `low` with `confidence: high` (feasibility is "available"), so the content plan tells the user ranking is out of reach. The in-pipeline path (`serp_audit.py:1629 if competitor_das:`) already guards this; only the standalone path is wrong.
- Fix: in `run_feasibility_analysis`, if `competitor_das` is empty use the existing "No DA Data" row shape; add `da_covered_count`/`organic_count` to each row and render "avg of N of M" in both feasibility renderers; treat `pivot_das == []` as "Not Measured". Tests: a keyword with no covered domains must produce `feasibility_status == "No DA Data"`; a row must carry the coverage count.
- Pattern: P1, P2

### D-C-04 · DataForSEO `rank: null` (no data for the domain) becomes DA 0, is used in the average, and is cached for 30 days
- Severity: **S1**
- Verdict: **CONFIRMED** code path (probe); the API returning `null`/`0` for unknown domains is DataForSEO-documented behaviour I could not call live
- Where: `dataforseo_client.py:206` (`rank = int(item.get("rank") or 0)`), `:207-211` (stored as `da`/`pa`), `:256-267` (`_cache_store`).
- Evidence: `probe_03_dataforseo_null_rank.py`: `{'https://unknown-new-site.ca/b': {'da': 0, …}}` returned, `('unknown-new-site.ca', 0)` in `da_cache`, served from cache on the next client with 0 POSTs. `compute_feasibility(35, [70, 70, 0]) → Moderate (gap 11.7)` vs `[70, 70] → Low (gap 35)`.
- Failure scenario: a SERP with two authority sites and one brand-new clinic → the fabricated 0 drags the average down and flips Low → Moderate ("Pursue with effort") for a month. `moz_client._parse_site_metrics` has the same `or 0` coercion (`moz_client.py:334-335`) but documents it as deliberate (gate D-3); it is the same fabricated-zero shape.
- Fix: skip items whose `rank` is `None` (do not cache them, or cache a `found=0` sentinel that the consumer omits — like `gsc_client` intends to), log "N of M domains had no rank". Test: a `rank: null` item must be absent from the result and from `da_cache`.
- Pattern: P1, P14

### D-C-05 · AI-visibility enrichment computes and persists AIVI = 0 (and transfer/prioritisation inputs) for engines that were skipped or whose every call failed
- Severity: **S1**
- Verdict: **CONFIRMED** (probe)
- Where: `probe_ai_visibility.py:1002-1014` (loop over configured `engines`; `mentions_axis = … if total else 0.0`; `aivi_mod.save_aivi(...)` for each), `:1062-1073` (engine_transfer uses `any()` over an empty row list → `False`), `:1044-1059` (prioritisation gets `aivi: 0`). The main loop drops engines without rows only at the report table (`:1121-1128`).
- Evidence: `probe_06_aivi_skipped_engine.py` with `engines=["gemini","openai"]` and rows only for gemini: `AIVI openai: 0.0 axes={'mentions': 0.0, 'ranking': 0.0, 'citations': 0.0}`; `ai_visibility_index` now holds `('openai', 0.0, 0.0)`; `all_engine_avg: 50.0` (should be 100.0 from the one measured engine); prioritisation ranks `openai` first as the biggest "opportunity".
- Failure scenario: `OPENAI_API_KEY` unset (default engine list has three) → every run writes a permanent AIVI-0 trend point for openai; the "all-engine average" is halved/thirded; the Y.10 ranking tells the user to optimise for the engine that was never asked. The methodology doc's "an unmeasured axis is never counted as 0" is violated at engine granularity.
- Fix: iterate over `probes.keys()` (engines that ran) and additionally require `total > 0` before computing/persisting AIVI; pass `None` axes (→ excluded) for an engine with zero answers; exclude such engines from `all_engine_average`, `compute_transfer` and `prioritize_engines`, and say "not measured (0 answers / skipped)" in the report. Test: enrichment with an engine that has no rows must not write an `ai_visibility_index` row for it.
- Pattern: P1, P2, P6

### D-C-06 · A CLI re-run on the same keyword CSV reuses the previous run's timestamped output filenames and overwrites them
- Severity: **S2**
- Verdict: **CONFIRMED** (probe)
- Where: `serp_audit.py:93-115` (`_resolve_output_names`: `if configured_json and f"market_analysis_{slug}_" in configured_json: return configured paths`), `serp_audit.py:2182-2192` (writes the resolved paths back to `config.yml` at the end of every run, so the next CLI run matches again).
- Evidence: with the repo's current `config.yml`, `_resolve_output_names("keywords_family-of-origin-seo-phrases.csv", CONFIG)` returns `output/market_analysis_family-of-origin-seo-phrases_20260828_1433.{xlsx,json,md}` — the 28 Aug run's files — for a run started today. The handoff still gets a fresh `datetime.now()` stamp, so a `competitor_handoff_…_20261104_*.json` sits beside a `market_analysis_…_20260828_1433.json` that actually holds 4 Nov data. README documents `python3 run_pipeline.py` as the CLI path.
- Failure scenario: user runs `run_pipeline.py` twice on the same CSV → the first run's JSON/XLSX/MD are silently replaced (only `normalized/<run_id>.serp_norm.json` survives); `run_feasibility`/brief outputs already derived from the old JSON now disagree with it; the `ai_aio_exposure` run_ts (parsed from the filename) is reused so the trend gets one point instead of two.
- Fix: only reuse configured names when they do not already exist on disk (that is the GUI's pre-write case); otherwise generate a fresh timestamp. Test: configured path exists → fresh names returned.
- Pattern: P8

### D-C-07 · The recommended-play parity HARD-fail in the brief validator can never fire on a real brief
- Severity: **S2**
- Verdict: **CONFIRMED** (probe on the real 2026-08-26 brief)
- Where: `brief_validation.py:255-263` (per-keyword section = text between `**<kw> (…)**` and the next `\n\n**`), `:356-376` (play check runs only on that section), `:13-22` (`_play_assignment_phrase` built from the yml label, e.g. `extraction play \(geo\)`). Prompt (`prompts/main_report/system.md`) puts "Recommended play: <label>" in Section 7, outside the Section-2 keyword block.
- Evidence: `probe_07_validator_play_parity.py`: pre-computed play `rank_play`; the brief's Section-7 line flipped to `Recommended play: **Extraction play**` → `validate_llm_report` returns **no** play issue, `has_hard_validation_failures → False`; the scanned Section-2 block does not contain "recommended play". Control: the same statement placed inside the block is caught only when written exactly as `Extraction play (GEO)` — the bare `Extraction play` (what the 08-26 brief actually wrote for its play) is also missed.
- Failure scenario: the LLM assigns the opposite play in Section 7; the brief is written as validated. The same block-scoping limits the intent/is_mixed hard-fails to Section-2 prose only (Section 7 claims are unchecked) — by design maybe, but undocumented.
- Fix: scan for `recommended play[:\-\s]+<label>` across the whole report, grouped by the keyword heading in Section 7 (or require the canonical statement to name the keyword, e.g. `Recommended play (<kw>): <label>`), and match on the label with the parenthetical suffix optional. Test: flip the play in Section 7 of `tests/fixtures/brief_baseline_*.md` and assert a hard failure.
- Pattern: P21, P7

### D-C-08 · Domain overrides keyed by the bare domain are not applied when the SERP URL has `www.` (35 of the 121 current overrides)
- Severity: **S2**
- Verdict: **CONFIRMED** (real run data + probe)
- Where: `serp_audit.py:1529` (`domain = urlparse(url).netloc` — keeps `www.`), `:1543` / `:1556` (`entity_classifier.classify(domain, …)`), `classifiers.py:146-149` (`if domain in self.overrides`). `refresh_analysis_outputs.classify_domain_for_row` and `generate_domain_override_candidates.normalize_domain` strip `www.`, so the refresh path and the candidate report disagree with the pipeline.
- Evidence: in the reference run `www.havencollective.ca` is `Entity_Type: N/A` although `domain_overrides.yml` has `havencollective.ca: counselling`; 30 of 56 organic links carry `www.`; `classify('www.'+d)` differs from `classify(d)` for 35 overrides (`probe_09_refresh_leaves_profiles_stale.py`, tail).
- Failure scenario: user approves an override via Step 6 → next pipeline run still classifies the site `N/A` → `serp_intent` classified count drops (primary → `None`, "insufficient data"), entity dominance and handoff `entity_type` wrong; the candidate report keeps proposing the same domain.
- Fix: normalise in one place (`EntityClassifier.classify`: strip `www.` and lower-case before lookup, and apply the same to pattern matching); test that `classify("www.x.ca")` equals `classify("x.ca")` for every override.
- Pattern: P22, P8

### D-C-09 · `refresh_analysis_outputs.py` re-classifies organic rows only; `keyword_profiles`, AIO-citation entities, the handoff and the markdown report keep the pre-override verdicts
- Severity: **S2**
- Verdict: **CONFIRMED** (probe)
- Where: `refresh_analysis_outputs.py:44-60` (`refresh_json` touches `organic_results[*].Entity_Type` only), `:126-143`. README Step 4 says it "re-classifies URLs and rewrites reports".
- Evidence: `probe_09_refresh_leaves_profiles_stale.py`: 9 rows for *family of origin counselling* flip N/A→legal, yet `keyword_profiles[kw].entity_distribution` is byte-identical before/after and `serp_intent` stays `('mixed', 7 classified)`; no `.md` is rewritten.
- Failure scenario: after approving overrides the JSON contradicts itself; `generate_insight_report.py` (and the GUI's regenerate) read `keyword_profiles` from the JSON, so §0/§1/§5b still show the old intent, entity label and play; the brief (which re-extracts) disagrees with the market report.
- Fix: after re-classifying rows, rebuild `keyword_profiles` via `generate_content_brief.extract_analysis_data_from_json` (as `serp_audit` does), re-attach plays, re-classify `ai_overview_citations`, regenerate the `.md`, and log "N profiles changed". Test: an override that changes an entity must change `keyword_profiles[kw].entity_distribution`.
- Pattern: P8, P6

### D-C-10 · A Moz competitor block with one sub-call failed (5xx) is cached with status `ok` and the error sub-block is served for 30 days without retry
- Severity: **S2**
- Verdict: **CONFIRMED** (probe)
- Where: `moz_competitor.py:280-299` (`available` is true if *either* ranking or anchors has items → top-level `status: ok` even when the other is `error`), `:571-584` (`_cache_store` keys cacheability on the top-level status only), `:526-566` (`_cache_lookup` serves the stored sub-blocks verbatim). `brand_authority` has the same shape (`:388-413`).
- Evidence: `probe_05_moz_competitor_cache.py` (B): ranking OK, anchors 503 → `status=ok`, cached row `anchor_texts = {"status": "error", "items": []}`; a new client on a healthy API makes **0 calls** and serves `anchor_texts.status = error`.
- Failure scenario: one afternoon of 503s on `data.site.anchor.text.list` → the handoff carries `anchor_texts.status: error` for those competitors for a month; serp-compete's `anchor_coverage` counts them `errored` on every run and never sees anchors Tool 1 never retries. Inverse case: anchors OK, ranking 5xx → `ranking_keywords.items == []` served as if measured.
- Fix: cache a block only when every sub-call that was enabled has status `ok`/`no_record`; otherwise store nothing (or store only the OK sub-blocks and refetch the failed ones on the next run). Test: ranking OK + anchors 5xx → second `fetch` re-POSTs the anchor method.
- Pattern: P1

### D-C-11 · AI-visibility probe failures vanish from the denominators, and HTTP-200 empty answers (safety block / incomplete) are recorded as measured "not mentioned"
- Severity: **S2**
- Verdict: **CONFIRMED** (probe)
- Where: `probe_ai_visibility.py:834-838` (`except Exception: logger.warning(...); continue` — no row, no count), `:1130` / `:1294` / `:1004` (`total = len(engine_rows)`), `:796` (trend `COUNT(*)`); `GeminiProbe.ask` `:293-328` and `ChatGPTProbe.ask` `:364-422` return `answer_text: ""` with no error when `candidates`/`output` are empty.
- Evidence: `probe_10_empty_answer_counted_as_not_mentioned.py`: Gemini `{"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}` → `answer_text ''`, row recorded `mentioned=False cited=False`; OpenAI `status: incomplete` likewise. Code trace for the drop: an engine with 18 of 20 calls failing prints `| gemini | … | 2 | 1/2 (50%) |` and the trend table compares that 2-question run against 20-question runs with no failure count anywhere in the report or sidecar.
- Failure scenario: a 429 burst on one engine → inflated/deflated mention rate persisted as a trend point; a safety-blocked persona question → counted as "client not mentioned" and pulls AIVI's mentions axis down.
- Fix: count failures per engine (`failed`), render "answered N of M (K failed)" in the per-engine table and store `questions_planned`/`failed` per run; treat empty `answer_text` (no text, no sources) as a failed call, not a measured zero. Tests: a probe raising for half the questions must produce a report line with the failure count; an empty answer must not produce a `mentioned=0` row.
- Pattern: P2, P1

### D-C-12 · The GUI's post-feasibility auto-regenerate rewrites `market_analysis_*.md` with the insight report only, dropping the "# Content Briefs" section the pipeline wrote
- Severity: **S2**
- Verdict: **CONFIRMED** (code trace)
- Where: `serp-me.py:1093-1130` (`auto_regenerate_market_analysis_after_feasibility` runs `generate_insight_report.py --json … --out <same .md>`), `generate_insight_report.py:1985-1995` (`main` writes `generate_report(...)` only), vs `serp_audit.py:2119-2172` (pipeline writes `generate_report(...)` + `"# Content Briefs"` + ordered `generate_brief(...)` blocks into the same file).
- Failure scenario: every GUI run that includes Step 7 ends with a `market_analysis_*.md` missing the brief sequencing block and all per-pattern briefs; nothing says so. Any later `generate_insight_report.py --out` invocation (README) has the same effect.
- Fix: move the Content Briefs assembly into a function in `generate_insight_report` (or a shared `report_assembly` module) and call it from both `serp_audit.main` and `generate_insight_report.main`; test that `main()` output on the fixture contains `# Content Briefs` when `strategic_recommendations` is non-empty.
- Pattern: P22, P8

### D-C-13 · A keyword whose SERP fetch fails after retries disappears from every report with no "N of M keywords fetched" statement
- Severity: **S2**
- Verdict: **CONFIRMED** (code trace)
- Where: `serp_audit.py:556-558` (`fetch_serp_data` returns `{}` on primary failure), `:1456 if raw_data_dict:` (no overview/organic rows), `brief_data_extraction.py:1240` (`root_keywords` from overview rows), `generate_insight_report.py:1284` ("Keywords Analyzed: len(overview)"). Only `aio_logs` keeps an error row; `analysed_keywords` (CSV list) is used solely for echo suppression.
- Failure scenario: SerpAPI returns an error 3× for one of 8 keywords → the report says "7 keywords analysed", the brief has 7 profiles, `validate_extraction` cannot warn (the keyword is not a root keyword), §6 volatility prints "Only in previous run: <kw>" as the only hint.
- Fix: compare `analysed_keywords` with `keyword_profiles.keys()` in `generate_report`/`validate_extraction` and render "N of M keywords returned SERP data; failed: …"; exit non-zero from `serp_audit` if any primary fetch failed (run_pipeline already honours exit codes). Test: fixture with `analysed_keywords` ⊋ profile keys must render the failure line.
- Pattern: P2

### D-C-14 · Section 4 "Why this pattern fired" evidence block reads `title`/`domain` keys the producer never writes, so it never renders
- Severity: **S2**
- Verdict: **CONFIRMED** (probe)
- Where: `generate_insight_report.py:1513-1521` (`org_result.get("title", "")`, `org_result.get("domain", "")`) vs producer keys `Title`/`Link`/`Source` (`serp_audit.py:939-950`); the sibling `_get_most_relevant_keyword` (`:1827-1831`) correctly uses `Title`/`Snippet`.
- Evidence: `probe_08_evidence_block_dead.py`: with a trigger word placed in a real organic `Title`, the rendered report has no evidence block; the same data with lower-cased keys renders it. No committed `market_analysis`/`content_opportunities` file in the repo contains the block. `tests/test_report_clarity.py::TestRC4PatternEvidence` asserts only that section 4 exists.
- Failure scenario: RC.4.1's "competitor titles that contain pattern trigger words (up to 3 per pattern)" never appears; the user sees `Triggers found:` with no evidence.
- Fix: use `Title` and `_domain_from_link(Link)`; replace the vacuous RC.4 tests with one that plants a trigger in a `Title` and asserts the block.
- Pattern: P21, P22

### D-C-15 · LLM responses are never checked for `stop_reason == "max_tokens"`; a truncated brief is validated and written as complete
- Severity: **S2**
- Verdict: **PLAUSIBLE** (code reading; not reproduced against the API)
- Where: `brief_llm.py:52-63` (`run_llm_report` returns joined text only), `brief_rendering.py:621-668`, `generate_content_brief.py:148` (`--llm-max-tokens` default 16000). Existing briefs are 42-60 KB (`content_opportunities_leila_20260704_1444.md` 60,066 chars ≈ 15k tokens).
- Failure scenario: a 9-keyword run produces a 17k-token draft → cut mid-Section-7; the validator sees fewer claims (fewer contradictions), the file is written, the advisory pass is fed the truncated text as `market_report_text`.
- Fix: return `(text, stop_reason)` from `run_llm_report`; treat `max_tokens` as a hard failure (write the `.validation.md` artifact with the reason) or raise `max_tokens` and warn. Test with a stubbed response object whose `stop_reason="max_tokens"`.
- Pattern: P2, P5

### D-C-16 · `test_moz_competitor.py::TestCollectionFreshness::test_cached_block_reports_when_it_was_collected_not_now` is a time bomb, not a cache defect
- Severity: **S3**
- Verdict: **CONFIRMED** (probe)
- Where: `test_moz_competitor.py:907` (`stale = "2026-08-01T09:00:00+00:00"`), `moz_competitor.py:528,545` (`cutoff = now − cache_ttl_days(30)`; `fetched_at < cutoff → continue`).
- Evidence: `probe_05_moz_competitor_cache.py` (A): the hard-coded date is 95 days old today vs a 30-day TTL → the row is correctly treated as expired → 2 POSTs. The test passed until 2026-08-31. The production code is right: a 95-day-old block *should* be refetched.
- Fix: compute `stale = (datetime.now(UTC) - timedelta(days=5)).isoformat()` (inside the TTL, visibly not "now"), or freeze time with a patched `datetime`. Keep the assertion `block["fetched_at"] == stale`.
- Pattern: P8

### D-C-17 · `serp_intent.thresholds.confidence_high` / `confidence_medium` are validated, GUI-editable and documented, but nothing reads them
- Severity: **S3**
- Verdict: **CONFIRMED** (grep)
- Where: `config.yml` `serp_intent.thresholds` block; `config_validators.py:464` validates them; `intent_verdict.py:137-148` computes confidence from counts and `compute_serp_intent` reads only `primary_share`, `fallback_share`, `fallback_runner_up_max`. (`enrichment.enable_domain_age` likewise has no reader.)
- Failure scenario: a user tunes `confidence_high: 0.9` expecting stricter confidence; nothing changes and no warning is logged.
- Fix: either implement them (ratio-based confidence) or delete the keys from `config.yml`, the validator and the GUI tab; add a test that every key under `serp_intent.thresholds` is consumed by `intent_verdict`.
- Pattern: P4, P21

### D-C-18 · §6 volatility renders "This run: unknown / Previous run: unknown" because `get_volatility_metrics` never returns those keys
- Severity: **S3**
- Verdict: **CONFIRMED** (code trace)
- Where: `generate_insight_report.py:1737-1738` (`vol.get('keywords_current', 'unknown')`), `metrics.py:get_volatility_metrics` return dict (`status, volatility_score, stable_urls_count, total_compared, comparability_warning, winners, losers`).
- Failure scenario: any run whose keyword set differs from the previous one prints two "unknown" lines instead of the keyword lists the sentence promises.
- Fix: return `keywords_current`/`keywords_previous` (sorted lists) from `metrics.get_volatility_metrics`; assert on them in `test_metrics.py`.
- Pattern: P22

### D-C-19 · Two feasibility producers with different definitions write the same `keyword_feasibility` artifact
- Severity: **S3**
- Verdict: **CONFIRMED** (code trace)
- Where: in-pipeline `serp_audit.py:1604-1631` (first 10 organic links in page order, **client's own URL included**, one row per `Query_Label` incl. `A.1`/`A.2`), vs `run_feasibility.py:333-339` (sorted by Rank, client excluded). Consumers key by `Keyword` with last-wins dict comprehensions (`generate_insight_report.py:782-786, 906-910, 965-969`) while `brief_data_extraction.index_feasibility_by_keyword` keeps the first row.
- Failure scenario: Deep-Research runs with AI alternatives on produce `A.1`/`A.2` feasibility rows that overwrite the `A` row in §0/§1/§5c but not in play routing → the report's status and the play's `feasibility` input disagree for the same keyword. In every mode the pipeline-written `market_analysis_*.md` shows a different Avg Comp DA than the later `feasibility_*.md` for the same JSON.
- Fix: route the in-pipeline computation through the same helper as `run_feasibility` (exclude client, label-A only) and make all consumers use `index_feasibility_by_keyword`. Test: pipeline rows for a keyword must equal standalone rows for the same organic set.
- Pattern: P22, P5

### D-C-20 · `url_enricher.fetch_url` returns 403/429/5xx bodies as content; the pipeline classifies the error page
- Severity: **S3**
- Verdict: **PLAUSIBLE**
- Where: `url_enricher.py:99-107` (returns `status_code` + body for any status), `serp_audit.py:1549 if fetch_res:` (no status check), `:1569-1600` (Content_Type, Word_Count, extractability, freshness, E-E-A-T taken from the page).
- Failure scenario: Cloudflare challenge on psychologytoday.com → `Content_Type` from a "Just a moment…" page, `Intro_Text_Length`/`Question_Heading_Count` 0, `Author_Present` false → feeds `extractability`, `eeat_signals`, foundational accessibility. `status_code` reaches SQLite only.
- Fix: in the enrichment loop treat `status_code >= 400` as "not enriched" (leave `N/A`, record `Fetch_Status`), and count "N of M pages blocked" in the run log/report.
- Pattern: P2, P1

### D-C-21 · `Has_Main_AI_Overview` is set from the no-location fallback probe as well as the main SERP
- Severity: **S3**
- Verdict: **PLAUSIBLE** (code trace; the reference run did not hit the fallback)
- Where: `serp_audit.py:871-890` (`ai_candidate = google_ai_overview or google_ai_overview_probe or primary.ai_overview`; `metrics["Has_Main_AI_Overview"] = bool(ai_overview_data)`), with the comment "B. Don't overload Has_AI_Overview". `aio_log.ai_overview_mode == "fallback_without_location"` records the distinction, but `keyword_profiles.has_ai_overview`, `aio_exposure`, `commodity_score` and play routing read only the overview flag.
- Failure scenario: Balanced mode (`ai_fallback_without_location: true`): the Vancouver-located SERP has no AIO, the un-located one does → the report says "Google's AI Overview appears for this search", `est_ctr_loss` is charged, extraction/reformat plays route on it.
- Fix: carry `AI_Overview_Mode` onto the overview row and either exclude `fallback_without_location` from `has_ai_overview` or expose a separate `has_ai_overview_unlocated` flag; test both modes.
- Pattern: P6

### D-C-22 · Rank history is polluted by aborted runs and by alternative-query rows saved under the root keyword
- Severity: **S3**
- Verdict: **PLAUSIBLE**
- Where: `serp_audit.py:1391` (`storage.save_run(run_id, "N/A")` before any fetch → a `runs` row exists even if the run aborts on keyword 1), `metrics.py` (previous run = immediately preceding `run_date`, no completeness check); `serp_audit.py:1530-1533` (`save_serp_result(run_id, source_keyword, …)` for `A.1`/`A.2` jobs as well, so alt-query ranks are stored under the root keyword).
- Failure scenario: an aborted run yesterday → today's deltas compare against a 1-keyword run ("Only in previous run: …" for everything else); with AI alternatives on, `merge(on=[keyword_text, url])` produces cross-products for URLs ranking in both the root and alt query → wrong `rank_delta`, `winners/losers`.
- Fix: write the `runs` row (or a `completed` flag) only at the end; pick the previous *completed* run; store `query_label` in `serp_results` and filter `= 'A'` in `metrics`.
- Pattern: P8

---

## Checked and found sound
- `moz_keywords.py` / `moz_jsonrpc.py`: 404/-32655 vs 5xx separation, never-cache-an-error, quota guard returning `None` (not 0) on failure, `parse_quota` refusing to fabricate zero, redaction — all as documented. Cache keys include engine/locale/device.
- `moz_client.py` return-key contract (caller's URL verbatim), batched IN(...) lookups, link_counts decode; TTL comparisons are all UTC ISO strings on both sides (no naive/aware mix) in `moz_client`, `moz_keywords`, `moz_competitor`, `dataforseo_client`, `gsc_client`.
- `http_retry.py`: timeouts, two attempts, Retry-After honoured; SerpAPI retry fails fast on quota/auth errors.
- `intent_verdict.py`: thresholds, `primary_intent None` below 5 classified, count-based confidence, mixed components — correct given correct inputs (the inputs are what D-C-01 breaks).
- `play_routing.py`: `No DA Data`/`Not Measured` → `unknown` with `data_available.feasibility False` and a note; `attach_recommended_plays` is called by both producers; `run_feasibility` re-routes and logs the count.
- `brief_validation` hard-fail flow in `list_recommendations`: hard → no retry → artifact + exit 2; soft → one retry → artifact + exit 2 if still failing; `--allow-unverified-report` is the only (explicit) bypass. Note: CLAUDE.md/README say `title_patterns` contradictions are SOFT; `has_hard_validation_failures` (`brief_validation.py:515`) treats them as HARD ("Fix 7") — docs lag the code.
- `aivi.compute_aivi`, `foundational_score`, `commodity_score`, `engine_transfer`: every division is guarded; `None` axes are excluded and weights renormalised; weights fall back with a warning.
- `aio_exposure.save_aio_exposure` and the other persistence helpers are idempotent per `run_ts`; `demand_dashboard._latest_gsc` filters `found = 1` and degrades without raising.
- Handoff contract: the two `handoff_schema.json` copies are identical; `convert_handoff_to_targets` reads exactly the required target fields; the v1.1 `moz` block shape (`domains`, optional `client`, per-domain `fetched_at`, sub-block statuses) matches what `handoff_moz.anchor_texts_by_domain` / `anchor_coverage` consume. `competitor_domains()` applies the same client/omit exclusions as the handoff.
- `yaml_io.save_yaml_preserving_comments`: atomic replace, fresh ruamel instance per call, symlink-safe.
- `run_feasibility` pivot validation: failed Maps fetch → `Client_In_Local_Pack None` → "not measured", failed organic fetch → "Not Measured"; SerpAPI key scrubbed from logs.
- `generate_insight_report._rank_keywords` / `_get_best_opportunity_keyword` / `_content_plan_order` pin logic; `_as_float` coercions in §5c; `_safe_section` isolation.
- `gsc_demand.compute_demand`: zero-click share guarded; branded classification recomputed each run.
- Entity-dominance interpretation thresholds are read from `config.yml report_thresholds` as documented.

## Not examined
- `config_manager.py` (110 KB GUI) beyond the threshold-key validator; `serp-me.py` run-context plumbing other than output naming and the post-feasibility regenerate.
- `pattern_matching.py` (n-grams, display phrases, Bowen trigger matching), `query_variants.py`, `title_patterns.py`, `intent_classifier.py`, `bing_check.py`, `profile_questions.py`, `brief_prompts.py`, the brief renderers in `brief_rendering.py`, `answer_sentiment.py`, `brand_mentions.py` gazetteer/LLM extraction, `engine_recommendations.py`, `ai_visibility_export.py`, `validate_xlsx_vs_json.py`, `verify_enrichment.py`, `export_history.py`.
- Live behaviour of SerpAPI/DataForSEO/Moz/GSC/LLM endpoints (all probes use mocks; D-C-01 relies on the captured reference run, D-C-04 on the documented `rank: null` shape).
- The XLSX writer / Glossary sheet content and `validate_xlsx_vs_json.py` parity rules.
