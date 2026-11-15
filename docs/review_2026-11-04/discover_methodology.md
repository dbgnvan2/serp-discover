# SerpDiscover — methodology-validity review

**Scope & method.** Reviewed the serp-discover copy at `/Users/davemini2/ProjectsLocal/serp-discover` (no files modified) against the question: does each printed metric, threshold and verdict measure what the report and its contract docs (`docs/methodology.md`, `docs/USER_MANUAL.md`, `glossary.yml`, `report_writing_directives.yml`, `play_routing.yml`, `intent_mapping.yml`, `strategic_patterns.yml`, `engine_profiles.yml`, `config.yml`) say it measures, at the sample sizes the tool actually runs at (2–20 keywords, "top-10" organic, 3 Google pages, ~20 AI-probe questions per engine, one DA provider)? I read every module behind a printed number (`feasibility.py`, `run_feasibility.py`, `intent_verdict.py`, `title_patterns.py`, `brief_data_extraction.py`, `play_routing.py`, `aio_exposure.py`, `commodity_score.py`, `demand_dashboard.py`, `probe_ai_visibility.py`, `brand_mentions.py`, `citation_table.py`, `aivi.py`, `foundational_score.py`, `engine_transfer.py`, `engine_recommendations.py`, `answer_sentiment.py`, `run_gsc_analysis.py`, `gsc_demand.py`, `gsc_client.py`, `metrics.py`, `handoff_writer.py`, `generate_insight_report.py`, `brief_validation.py`, `pattern_matching.py`) and the SerpAPI merge path in `serp_audit.py`. Where behaviour is quantitative I ran probes against the committed reference run (`tests/fixtures/market_analysis_reference_run.json`, a trimmed real run from 2026-08-26) and against synthetic edge inputs; probes live in `docs/review_2026-11-04/probes/discover_method/p01…p10` and their output is quoted below. Classes: **WRONG** (number does not mean what the report says), **UNLABELLED HEURISTIC** (defensible but presented as more certain than warranted), **UNDOCUMENTED PROVENANCE** (threshold/weight with no stated source), **DOC–CODE DRIFT**. Items already in `TODO.md` or `three_tool_audit_review_20260721.md` are not re-reported; none of the findings below are tracked there (the TODO's "Section 4 stale-play caveat" is a different, narrower case than D-M-07). Judged against the owner's "state absence, don't fake it" principle.

Headline: the tool's honesty scaffolding (data_available flags, "not measured" states, n/a-excluded axes, Moz null = not comparable) is real and mostly works. The problems are upstream of it — one data-shape bug that silently corrupts every "top-10" metric, several null→0 coercions that the scaffolding does not see, and a handful of composites whose inputs are not what their labels say.

---

### D-M-01 · "Top-10 organic" is not the top 10: SerpAPI per-page positions are stored as absolute ranks, so every rank-based metric mixes pages 1–3
- Class: WRONG
- Impact: High (changes intent verdicts, feasibility means, client rank, reformat/geo alerts, the serp-compete handoff)
- Verdict: CONFIRMED (fixture + probe)
- Where: `serp_audit.py:941` (`"Rank": item.get("position", "N/A")`), `serp_audit.py:400-425` (`_merge_google_pages` concatenates pages, keeps each page's own `position`), `serp_audit.py:1547` (`if rank_val <= MAX_URLS_TO_ENRICH`), `brief_data_extraction.py:1698` (`kw_rows = sorted(..., key=rank)`) → `:1736` (`organic_rows=kw_rows[:10]`), `:1368` (`if rank <= 10` → `organic_top10_domains_by_kw`), `run_feasibility.py:240-241`, `handoff_writer.py:116`, `metrics.py:137` (`s.rank <= 10`), `config.yml:6-8` (`num: 100`, `google_max_pages: 3`)
- Evidence: `p03_page_evidence.py` on the reference run, keyword "family of origin counselling", one `Run_ID`, one `Google_URL`, `google_pages_fetched: 3`, label-A ranks in storage order: `[1,2,3,4,5,6,7,8,9, 1,2,3,4,5,6,7,8,9,10, 2,3,4,5,6,7,8,9]`. Nothing in `serp_audit.py` adds the page offset (`start`). Consequences measured in `p09_handoff_rank_mix.py`: `run_feasibility._get_organic_urls_by_keyword` selects merged positions `[1, 10, 2, 11, 20, 3, 12, 21, 4, 13]` as "top 10"; the competitor handoff for the same keyword lists `rank=1 https://www.newtides.ca/...` which is merged position 10 (page 2, #1) and `rank=2 https://movingforward.help/` which is merged position 20 (page 3). In `keyword_profiles`, `livingsystems.ca` is recorded as `client_rank: 7` (`p01`), but that row is page 3 position 7 (`p02`, third block). Because `rank_val <= 5` is tested per row, ~14 pages per keyword are HTML-enriched (fixture: 14 rows with content types per keyword), not 5.
- Why it matters: the intent verdict, title patterns, `top5_organic`, `entity_distribution`, `client_rank` (and therefore `aio_exposure.est_ctr_loss`, `client_ranks_but_not_cited` → `reformat_play`/`geo_alerts`, "defend/strengthen" flags), the feasibility mean, volatility deltas (a URL moving from page-1 #9 to page-2 #1 reads as +8 "improved"), and the URLs serp-compete audits are all computed on a set that is roughly "the first 3–4 results of each of three pages". The 2026-08-28 content brief told the owner "livingsystems.ca ranks #6" on that basis.
- Fix: compute absolute rank at merge time — `absolute = page_start + position` (use the `start` parsed from `serpapi_pagination` for each fetched page, or `10*(page_index) + position`); store it as `Rank` and keep the raw per-page position in a separate field. Re-run the fixture and re-check every `[:10]`/`<= 10` consumer. Also note that `num: 100` is no longer honoured by Google (pages are ~10), so "3 pages" means top ~30, not 300; `google_max_results: 300` is stale.

### D-M-02 · A domain the DA provider cannot score enters the feasibility mean as DA 0, pulling the gap down and inflating feasibility
- Class: WRONG
- Impact: High (flips Low → High Feasibility; drives rank_play vs extraction_play and the pivot spend)
- Verdict: CONFIRMED (code trace + arithmetic probe)
- Where: `dataforseo_client.py:206-209` (`rank = int(item.get("rank") or 0)` → `"da": rank`), `moz_client.py:327-335` ("``da``/``pa`` keep the legacy ``or 0`` coercion so feasibility scoring is unchanged" → `"da": int(metrics.get("domain_authority") or 0)`), `serp_audit.py:1625-1628` and `:1752` (`if v.get("da") is not None` — never excludes 0), `run_feasibility.py:331-335` (no filter at all)
- Evidence: `p07`: 7 competitors with DA `[60,55,50,48,52,58,61]` → `avg 54.9, gap +19.9, Low Feasibility`; the same 7 plus three unscored domains coerced to 0 → `avg 38.4, gap +3.4, High Feasibility`. The Moz comment states the coercion is deliberate so "feasibility scoring is unchanged", i.e. it was already the behaviour when DataForSEO was primary. Neither provider path distinguishes "no record" from "DA 0", and no row records how many URLs contributed to the mean.
- Why it matters: new/small clinic domains are exactly the ones a backlink index may not hold; every such miss makes the SERP look weaker than it is. The report then says "your site scores 35 against an average of 38 for the sites currently ranking" and routes to `rank_play`.
- Fix: return `None` (not 0) for an absent `rank`/`domain_authority`; exclude `None` from `competitor_das`; carry `da_count` / `da_missing` on the feasibility row and print "mean of N of 10 ranking domains (M unscored)" in §5c and `feasibility_*.md`; if `da_count < 5`, status "Not Measured", not a verdict.

### D-M-03 · Engines that never ran are scored AIVI 0, persisted, averaged, ranked #1 priority and counted in "mentioned on 1 of 3 engines"
- Class: WRONG
- Impact: High (the prioritisation table and all-engine AIVI headline are driven by fabricated zeros)
- Verdict: CONFIRMED (probe)
- Where: `probe_ai_visibility.py:1504` (`run_report_enrichment(rows, engines, …)` passes the *configured* list, not `probes.keys()` minus `skipped`), `:1000-1016` (`for engine in engines: … mentions_axis = … if total else 0.0` → `compute_aivi` → `save_aivi`), `engine_transfer.py:39-47` (two empty sets → Jaccard 1.0 "by convention"), `engine_recommendations.py:164` (`opportunity = 1.0 if aivi_val is None …`, and AIVI 0.0 is not None), `config.yml:engines` default `[gemini, openai, perplexity]`
- Evidence: `p06_aivi_skipped_engine.py` — gemini answered 2 questions, openai/perplexity passed as skipped (no key). Output: `openai AIVI: 0.0 axes {mentions 0, ranking 0, citations 0}`, `perplexity AIVI: 0.0`, `all_engine_avg: 13.0` (gemini alone is 38.9); `ai_visibility_index` table now holds `('openai', 0.0, 0.0)` and `('perplexity', 0.0, 0.0)` for that `run_ts`; rendered report: "**All-engine average AIVI: 13.0/100**", Platform prioritisation `| 1 | ChatGPT | 0.900 | 1.00 |`, Cross-engine transfer "mentioned on 1 of 3 engines", "openai vs perplexity: 1.00", "Average pairwise Jaccard … 0.33", "**Interpretation:** Moderate cross-engine citation overlap: foundational work helps everywhere…". The per-engine table correctly prints "skipped — OPENAI_API_KEY not set" two sections earlier, so the same report contradicts itself.
- Why it matters: with the default engine list and only one key present, every run writes two fake zero rows into the trend table; the next run's "Δ prior" for that engine will compare against 0; the prioritisation tells the owner to work on ChatGPT first because it was never measured. This is the exact "0 mentions vs engine not run" confusion the brief asked about, and the stored rows are exported to serp-compete (`ai_visibility_export.py` reads `brand_mentions`/`ai_citations`, which are empty for the skipped engines, so the export is honest; the AIVI/transfer tables are not).
- Fix: pass `list(probes.keys())` (engines that produced rows) to `run_report_enrichment`, `generate_report`'s transfer/prioritisation and the trend lookups; never persist an AIVI row for an engine with zero answers; in `engine_transfer.jaccard`, return `None` for two empty sets and exclude the pair; in `prioritize_engines`, skip engines with no measurement rather than treating them as maximum opportunity; print "n answered of m asked" per engine (failed questions are dropped at `:837-839`, so the denominator is answered, not asked).

### D-M-04 · Foundational "structure / schema" sub-score measures competitors' schema, not the client's
- Class: WRONG (and DOC–CODE DRIFT)
- Impact: High (the "do-first, watch it climb" score cannot respond to anything the client does)
- Verdict: CONFIRMED (exact trace)
- Where: `foundational_score.py:159-200` (`compute_structure` reads `keyword_profiles[*].schema_signals.schema_type_counts`), `brief_data_extraction.py:511-551` (`_build_schema_signals(kw_rows)` counts `schema_types` over all top-10 rows), `docs/USER_MANUAL.md:1331-1334` ("structure / schema (the schema.org markup the client's own pages carry vs what the topic warrants)"), `docs/methodology.md` Phase E ("measuring the *inputs* the client controls")
- Evidence: `schema_type_counts` is a `Counter` over every enriched top-10 row regardless of domain; `compute_structure` scores `covered recommended types / total recommended types` against that union. In `p06` the reference run (client present on one keyword at page-3) yields "Structure / schema: 67" and gaps "Add FAQPage markup", "Add ProfessionalService markup" — these are types *no competitor* carried, not types the client lacks. The accessibility sub-score correctly filters to `ext.client_page`; structure does not.
- Why it matters: the owner is told to "fix these foundations before chasing any single engine" and that the score is "stored each run so you can watch it climb". Adding FAQPage schema to livingsystems.ca changes nothing unless the client ranks top-10 for a tracked keyword; a competitor adding it raises the client's "readiness".
- Fix: compute structure from the client's own enriched rows only (`row.domain == client_domain`, same filter as `_client_extractability_pages`), and return `None` ("n/a — client page not in any enriched top-10") when there are none. State in the manual that the sub-score is only measurable when the client ranks; if a client-site crawl is wanted, that is TalkingToad's data, not this tool's.

### D-M-05 · `client_da` is a fixed config constant (35) compared against live provider numbers that may be on a different scale
- Class: UNDOCUMENTED PROVENANCE (bordering on WRONG when the provider is DataForSEO)
- Impact: High (every gap and every feasibility verdict is offset by whatever 35 is wrong by)
- Verdict: CONFIRMED (trace)
- Where: `config.yml:306` (`client_da: 35`), `run_feasibility.py:257` (`client_da = client_da_override or feasibility_cfg.get("client_da", 35)`), `:334` (client domain explicitly *excluded* from the provider lookup), `serp_audit.py:150` (default 0 when absent), `dataforseo_client.py:26-27` (example output `"livingsystems.ca": {"da": 19}`), `docs/CONFIGURATION_GUIDE.md:338` ("`35` (estimated or from SEMrush/Moz)"), `docs/USER_MANUAL.md:675` ("Living Systems DA (fixed)")
- Evidence: the provider is called for the ranking URLs in the same run but never for the client domain; DataForSEO's bulk_ranks "rank" (`rank_scale: one_hundred`, a DataForSEO Domain Rank) is written into the same `da` field as Moz's Domain Authority, and the code's own example gives livingsystems.ca 19 on DataForSEO while config says 35. No doc states which provider 35 came from or when. `docs/feasibility.md` says only "Both DA providers key their results by the caller's input URL".
- Why it matters: with DataForSEO primary, a gap of "+3" may really be "+19"; the Moz fallback silently changes scale mid-history (cached `da_cache` vs `moz_cache` rows never mix in one run, but runs on different days do). "Within about two points, treat it as level" (glossary) is meaningless if the baseline is off by 16.
- Fix: look up the client domain through the active provider in the same batch and use that as `client_da` (log provider + fetch date; keep the config value only as an override); tag each feasibility row with `da_provider`; never compare across providers in the trend; state in `docs/feasibility.md` that DataForSEO rank and Moz DA are different models and are not interchangeable.

### D-M-06 · Section 0 "best opportunity" ignores the intent gate the manual calls mandatory
- Class: DOC–CODE DRIFT
- Impact: High (the one keyword the report tells the owner to pursue first can be one the same table marks ⛔)
- Verdict: CONFIRMED (probe)
- Where: `generate_insight_report.py:897-950` (`_rank_keywords`: sort key `(feas_rank, intent_match, conf_rank, kw)`), `:953-985` (`_get_best_opportunity_keyword` takes `ranked[0]`), `:1010` (`_get_keyword_action` returns "⛔ Mismatched intent" first), `docs/USER_MANUAL.md:633-635` ("Example 3 … → **Pursue B only.** A is off-limits because the intent doesn't match, regardless of feasibility")
- Evidence: `p07`: kwA = High Feasibility + navigational, kwB = Moderate + informational, preferred = [informational, transactional, local] → `best opportunity: kwA | navigational intent, high feasibility`; action table: `kwA: ⛔ Mismatched intent`, `kwB: ⚠️ Pursue with effort`. `_content_plan_order` then pins kwA to the front of "1. What To Write" (methodology §1).
- Why it matters: the executive summary and content plan lead with a keyword the manual says is off-limits.
- Fix: filter `intent_match == 0` keywords out of `_rank_keywords` candidates for the best-opportunity pick (or make intent the first sort key), and update `docs/USER_MANUAL.md` §"Keyword Prioritization" to match whichever is chosen.

### D-M-07 · Extraction-play text asserts "high DA gap" for keywords whose DA was never measured
- Class: WRONG (label)
- Impact: High (the strategy sentence is quoted verbatim into the LLM brief and §1 "What the page must do")
- Verdict: CONFIRMED (fixture)
- Where: `play_routing.yml` rules 5–6 (`feasibility: [low, unknown]`), `plays.extraction_play.strategy_text` ("Ranking is unlikely (high DA gap) but AI-Overview citation is winnable…"), `play_routing.py:238-244` (note appended separately), header comment "feasibility 'unknown' is grouped with 'low'"
- Evidence: `p01` on the reference run: both keywords carry `recommended_play.play = extraction_play`, `strategy_text = "Ranking is unlikely (high DA gap)…"`, `inputs_used.feasibility = "unknown"`, `data_available.feasibility = False`, note "feasibility/DA data unavailable — routed on intent + AI-Overview only". `p07` reproduces it synthetically. The same JSON's `keyword_feasibility` rows show `gap −14.2, High Feasibility` (the CD.8 stale-play case the methodology documents) — but the unknown-feasibility wording is wrong even when the plays are fresh.
- Why it matters: "Ranking is unlikely (high DA gap)" is a factual claim; the note says the fact was not measured. A reader of §1 sees the claim; the note is rendered as "inputs missing: …" only in some surfaces.
- Fix: give the play a second `strategy_text_unknown_feasibility` (or template the clause) so that `feasibility == unknown` renders "DA not measured; routed on intent + AI Overview — citation play" and never "high DA gap". Validator rule: a report may not state a DA gap direction for a keyword with `data_available.feasibility == false`.

### D-M-08 · A keyword whose ranking domains all lack DA (while the provider returned data for other keywords) is verdicted "Low Feasibility", gets a neighbourhood pivot and triggers paid validation fetches
- Class: WRONG
- Impact: High (fabricated verdict + SerpAPI spend)
- Verdict: CONFIRMED (code trace + probe)
- Where: `feasibility.py:86-93` (`if not competitor_das: return {... "feasibility_status": "Low Feasibility"}` with every number `None`), `run_feasibility.py:308-321` (the "No DA Data" branch keys on the run-wide `da_data_available = bool(da_metrics)`, not per keyword), `:357-361` (pivot job queued whenever status is Low and keyword is service-like)
- Evidence: `p07`: `compute_feasibility(35, [])` → `{'avg_serp_da': None, 'gap': None, 'feasibility_status': 'Low Feasibility'}`. In `run_feasibility_analysis`, a keyword with zero scored domains in a run where any other keyword was scored reaches `compute_feasibility` with `[]`, so the row prints `| — | — | 🔴 Low |`, `generate_hyper_local_pivot` returns "Pivoting to Hyper-Local" with the text "currently dominated by high-authority directories (Avg DA: unknown)", and a Maps + organic SerpAPI fetch is spent validating it. (The in-pipeline path in `serp_audit.py:1629` instead drops the keyword from the table entirely, so the two producers disagree.)
- Why it matters: the docstring says the empty case is "so callers don't have to special-case missing data" — i.e. the fake verdict is by design. It contradicts the tool's own "Not Measured" convention used two branches later for pivots.
- Fix: return `feasibility_status: "No DA Data"` from `compute_feasibility` for an empty list; gate pivot jobs on `feas["gap"] is not None`.

### D-M-09 · The feasibility statistic (unweighted mean DA over "top-10") answers "how strong is the SERP on average", not "can a DA-35 site rank here"; no count, spread or entity breakdown is shown
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (arithmetic probe)
- Where: `feasibility.py:95-98`, `run_feasibility.py:331-335` (directories such as psychologytoday.com are included; the client's own URL is excluded here but *not* in `serp_audit.py:1625`), `docs/feasibility.md` ("Gap = avg competitor DA − client DA"), `generate_insight_report.py:741-756` ("your site scores 35 against an average of X for the sites currently ranking")
- Evidence: `p07`: `[92] + [18]*9` → mean 25.4, gap −9.6, "High Feasibility"; `[85]*5 + [12]*5` → mean 48.5, gap +13.5, "Moderate Feasibility — requires local backlink building" even though five DA-12 pages demonstrably rank on that SERP. The mean is dominated by directory DA; the fact that low-DA clinics occupy half the page is the actual evidence of rankability and is invisible.
- Why it matters: for a local nonprofit the actionable statistic is "lowest DA holding a top-10 slot among non-directory, non-client pages" (or the DA of positions 6–10); the mean over-weights Psychology Today and HealthLink. The report presents the mean as the measurement with no `n`, no min/max, no entity split.
- Fix: keep the mean but add `min_competitor_da`, `n_scored`, and `min_non_directory_da` (entity_type from the same rows) to the row and to §5c; consider defining the gap against the median or the lowest-ranking DA in positions 6–10 and state in `docs/feasibility.md` that the thresholds (≤5 / 6–15 / >15) are editorial, not derived (see D-M-21).

### D-M-10 · Intent "confidence" is a count of classified URLs, which is capped by the enrichment budget, and the manual equates it with intent clarity
- Class: DOC–CODE DRIFT + UNLABELLED HEURISTIC
- Impact: Medium (confidence is the third ranking key in §0 and a prompt field)
- Verdict: CONFIRMED (fixture + probe)
- Where: `intent_verdict.py:137-147` (`_bucket_confidence`: ≥8 classified = high, ≥5 = medium, count-based only), `config.yml:26` (`max_urls_per_keyword: 5` — only those rows get HTML content types; ranks 6–10 stay `N/A` unless `url_pattern_rules.yml` matches), `config.yml:296-297` (`confidence_high: 0.8`, `confidence_medium: 0.5` — read by `config_validators.py:464` and described in the GUI at `config_manager.py:199` as "Threshold for marking intent as 'high confidence' (0.0-1.0)", but never consumed by `intent_verdict.py`), `docs/USER_MANUAL.md:613-615` ("Confidence — How sure are we about the intent? … <5 = low (mixed intent)"), `:940` ("Confidence: High (clear intent) / Medium (some ambiguity) / Low (mixed intent)")
- Evidence: `p07`: 10/10 classified split 6 informational / 4 transactional → `informational, is_mixed False, confidence high`; passing `confidence_high: 0.99` through `thresholds=` changes nothing (`confidence: high`). Reference run: 7 and 5 classified of 10 → "medium" on both keywords, with the classifiable rows being predominantly the HTML-enriched ones. Primary intent can be declared from 2 of 10 URLs (5 classified, 2/5 = 40% with runner-up ≤20%).
- Why it matters: a user raising `max_urls_per_keyword` to 10 would see "confidence" rise across the board with no change in SERPs; a 6/4 split is reported as high confidence; the GUI exposes two dead knobs. Mixed-ness and confidence are independent in the code but conflated in the manual.
- Fix: rename the field in the report to "classification coverage: 7 of 10" (it already prints that in §5b) and derive a separate margin-based certainty (top share − second share) if a "confidence" word is wanted; delete or wire `confidence_high/medium`; correct the manual's three statements. Make the URL-pattern fallback apply to ranks 1–5 too or state that ranks 6–10 are classified by URL shape only.

### D-M-11 · Mixed-intent strategy says "backdoor" even when the dominant intent is one the client prefers, and breaks ties by dict order
- Class: WRONG
- Impact: Medium (strategy label is rendered in §4/§5b and enforced on the LLM by the validator)
- Verdict: CONFIRMED (fixture + probe)
- Where: `brief_data_extraction.py:405-425` (`dominant = max(distribution, key=distribution.get)`; `compete_on_dominant` only if dominant ∈ `client_intent_presence`, which is built solely from keywords where the client is *already visible* with a non-mixed verdict; else `backdoor` if any non-dominant intent ∈ `preferred_intents`), `report_writing_directives.yml:77-86` (backdoor = "dominant intent is uncompetable … You cannot outrank the local half with an article")
- Evidence: `p10`: distribution `{informational 4, transactional 3, local 1}`, client not visible, preferred = [informational, transactional, local] → `backdoor` (the dominant intent *is* preferred; nothing was checked about competability). Reference run `family of origin counselling`: `informational 3 / local 3 / transactional 1` → `dominant = informational` purely because it is first in dict order; `p10` with `local` first → dominant `local`; either way `backdoor`.
- Why it matters: with 2–20 keywords and the client visible on ~1, `client_intent_presence` is almost always empty, so `compete_on_dominant` is effectively unreachable and nearly every mixed SERP reads "backdoor" — the report then tells the writer to avoid the half of the SERP they should be writing for.
- Fix: `compete_on_dominant` if dominant ∈ `preferred_intents` (client capability, which is what the directive text describes), `backdoor` if dominant ∉ preferred but a non-dominant one is, `avoid` otherwise; on a tie report "tied: informational/local" rather than picking one; drop the "that space belongs to Google Business Profiles" sentence unless `local` is actually the dominant component.

### D-M-12 · "Market too small" is decided from Google's `total_results` estimate (< 200), which measures index size, not demand
- Class: WRONG (label) + UNDOCUMENTED PROVENANCE
- Impact: Medium (routes a keyword to `skip` in `strategic_flags.content_priorities`)
- Verdict: CONFIRMED (probe)
- Where: `brief_data_extraction.py:385-389` (`elif total_results < 200: action = "skip"; reason = "Only {n} total results. Market too small to justify dedicated content investment."`), `prompts/main_report/system.md:386` and `prompts/advisory/system.md:60` (both correctly say total_results ≠ search volume)
- Evidence: `p10`: `total_results=150` → `skip | Only 150 total results. Market too small…`. The 2026-08-28 content brief carried this through: "Total indexed results are only 120, meaning the addressable market for this exact query is small". The prompt forbids the LLM from calling it volume, but the deterministic layer already turned it into a market-size verdict; the validator only catches the words "monthly searches".
- Why it matters: Google's "About N results" for a localised long-tail query is an index-coverage estimate that fluctuates by orders of magnitude and says nothing about searches; low competition on a long-tail query is, if anything, an opportunity. The one real demand source in the repo (`keyword_profiles.moz.volume`, en-CA) is not used here.
- Fix: remove the `skip` rule or re-key it on `moz.volume` when `moz.data_available` is true (with "demand not measured" otherwise); reword the reason to "few indexed pages — competition is thin; demand not measured".

### D-M-13 · Commodity "SERP homogeneity" treats unclassifiable titles as a homogeneous shape and uses entity counts from all three pages
- Class: WRONG
- Impact: Medium (adds ~15–25 points to every keyword in a run where titles don't match the regexes)
- Verdict: CONFIRMED (probe on fixture)
- Where: `commodity_score.py:147-165` (`tp_conc = max(counts.values()) / tp_total` — `other` included; `ent_conc` from `entity_distribution`), `brief_data_extraction.py:1307-1309` (`entity_by_kw` counts every label-A row, 23 per keyword in the fixture, not top-10), `title_patterns.py:171-175` (title module itself refuses to call `other` dominant: "4+ unclassifiable titles is NOT a meaningful SERP-shape signal")
- Evidence: `p04`: both reference keywords have `pattern_counts.other = 10/10`; `serp_homogeneity = 0.826` and `0.783` of which the title component is `1.0`; entity-only concentration is 0.65/0.57 over 23 rows. Resulting scores 55.5 / 53.2 ("medium") with answer similarity only 0.13 / 0.11.
- Why it matters: the "differentiate-or-lose queue" ordering is driven mostly by a term that says "we could not classify the titles". The caveat text describes answer similarity as lexical but not this.
- Fix: exclude `other` from `tp_conc` (return the title component as `None` when no pattern is classifiable, and let `_composite` renormalise as it does for the LLM term); compute entity concentration over the top-10 rows used for the intent verdict; add the sub-score inputs' `n` to the table.

### D-M-14 · Brand-mention gazetteer matches ordinary English words, and the AIVI Ranking axis is decided alphabetically on ties
- Class: WRONG
- Impact: Medium (leaderboard, Ranking axis, foundational authority gaps)
- Verdict: CONFIRMED (probe)
- Where: `brand_mentions.py:85-120` (`build_gazetteer` harvests every organic `Source` label — "Indeed", "Pathways", "First Session", "Job Bank", "LinkedIn"…), `:127-139` (`gazetteer_pass`: `\bIndeed\b` with `re.IGNORECASE`), `:268-287` (`rows.sort(key=(-mention_count, name))` → `client_rank`), `:306-318` (`client_ranking_axis` linear in rank), `config.yml:298` (`known_brands: []`), `analysis_report.client_name_patterns: ["Living Systems"]`
- Evidence: `p05`: gazetteer from the reference run (40 entries) includes `'Indeed'`; the sentence "Indeed, there are many options…" yields a brand mention for Indeed. `p06`: four brands each mentioned once → ranks by name: Family Services…(1), Indeed(2), Living Systems(3), Theravive(4) → `Ranking axis 33.33` for a four-way tie, and the foundational gaps list "Build third-party authority: AI names 'Indeed' in the client's place". `gsc_demand.is_branded` docstring already admits "Living Systems" matches "living systems theory" (the same word-boundary matcher is used for AI-answer `mentioned`).
- Why it matters: at 20 questions per engine one false hit moves the mentions axis by 5 points and can swap the client's leaderboard rank; the authority gap list names a job board as a rival.
- Fix: stop-list single-token generic sources (or require ≥2 tokens / a domain match) in `build_gazetteer`; use competition ranking (ties share a rank: 1,1,1,1 → axis 100) or report "tied with N"; add `negative_terms`-style exclusions ("living systems theory") to `detect_visibility` as `gsc_demand` already has.

### D-M-15 · The GSC "sponge" delta is a cross-sectional comparison of different queries, and "reformat candidates" are, by construction, the below-median half of the client's own queries
- Class: UNLABELLED HEURISTIC (sponge) / WRONG (candidates)
- Impact: Medium
- Verdict: CONFIRMED (code trace)
- Where: `run_gsc_analysis.py:166-212` (`compute_sponge_effect`: median CTR of AIO queries vs non-AIO queries per position band, `MIN_BUCKET_SIZE = 3`, no impression weighting), `:236-271` (`find_reformat_candidates`: any top-10 query with `ctr < no_aio_median_ctr`, AIO or not), `:304-307` (report: "A lower AIO-median at the same position band *is* the sponge effect"), `gsc_client.py:186-200` (90-day, all-device, all-country totals), `collect_queries` (`has_ai_overview` from one desktop Vancouver fetch)
- Evidence: queries that trigger AIOs are systematically informational; informational queries have lower CTR at the same position whether or not an AIO exists, so the band delta conflates intent with AIO presence. With `MIN_BUCKET_SIZE = 3` and no impression weight, three queries with 20 impressions each decide the band. For candidates, `ctr < median(no-AIO CTRs)` flags roughly half of the no-AIO queries as "starving CTR … reformat for answer extraction" regardless of any AIO.
- Why it matters: the report sends the owner to reformat pages whose only property is being below the median of their own peers; the "sponge" number is presented as causal.
- Fix: label the sponge table "association, not effect; confounded by intent"; require impressions ≥ a floor and weight by impressions; for candidates, require `has_ai_overview is True` *and* CTR below the no-AIO median by more than a stated margin, or compare the same query across runs (before/after AIO appeared) which the per-run storage already allows. Filter the GSC pull by `country = can` and `device = DESKTOP` to match the SERP fetch, and say the window.

### D-M-16 · Branded click share is computed over the tracked keyword set but benchmarked against whole-property industry bands; the whole-property data is fetched and discarded
- Class: WRONG
- Impact: Medium
- Verdict: CONFIRMED (code trace)
- Where: `gsc_demand.py:124-170` (`branded`/`nonbranded` over `rows` = tracked queries), `:270-275` (rendered "— **below average** vs the industry reference band"), `gsc_client.py:186-244` (`_fetch_all_rows` pulls every query in the property, then `get_query_stats` keeps only the tracked ones), `config.yml:286-287` (`below_avg: 0.024`, `top: 0.1` — "INDUSTRY REFERENCE points", no source)
- Evidence: the tracked set is the keyword CSV + variants + PAA phrasings; a brand query ("living systems counselling") is in it only if it was in the CSV, so the branded share over tracked queries is structurally near 0 and the band verdict is "below average" by construction. The report's own caveat ("over the run's tracked queries, not the full property") concedes the denominator differs from the benchmark's, but the comparison is still printed.
- Why it matters: this is the metric the methodology calls "the demand signal that predicts survival when generic clicks fall to AI answers". As built it cannot move with real brand demand.
- Fix: compute branded share over the full `_fetch_all_rows` result (already in memory; cache it as a property-level row), keep the tracked-query view as a secondary line, and cite the source of 2.4% / 10% or drop the band.

### D-M-17 · "Estimated traffic at risk" multiplies GSC impressions by an industry CTR curve even though GSC supplies the client's actual CTR; the estimate can exceed the clicks the client actually gets
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (arithmetic probe)
- Where: `demand_dashboard.py:96` (`intercepted = impressions × est_ctr_loss`), `aio_exposure.py:170-182` (`ctr_base(position) × 0.6`, position = `client_rank` from the SERP — see D-M-01), `config.yml:237-250`
- Evidence: `p10`: client at rank 1 with an AIO, not cited: `est_ctr_loss = 0.168`; 1000 impressions → "~168 clicks/period at risk" while the GSC row for that query says 60 clicks (CTR 6%). The section prints the GSC clicks on the line above, so the reader sees 60 actual and 168 "at risk".
- Why it matters: the number is labelled "indicative" but is still the headline of §5f; it is not bounded by observed clicks and ignores the measured CTR/position sitting in the same row.
- Fix: `at_risk = min(actual_clicks, impressions × ctr_loss)` at minimum; better, use GSC's own `position` and `ctr` for the query (`loss = clicks × aio_ctr_multiplier`) and reserve the curve for keywords with no GSC row; print the 90-day window explicitly.

### D-M-18 · The 20-question cap silently drops entire personas, so the "per-persona" breakdown and the mention rate describe one persona's city-expanded templates
- Class: UNLABELLED HEURISTIC
- Impact: Medium (for the AI-visibility trend's meaning)
- Verdict: CONFIRMED (probe)
- Where: `probe_ai_visibility.py:1431-1441` (`questions = questions[:allowed]`, allowed = `max_total_calls // len(engines)` = 60/3 = 20), `build_question_set` (profile questions first, in persona file order), `client_profiles.yml` (`prospective_client` has 22 generated questions, `clinician_trainee` 3, `referrer` 2), `profile_questions.generate` (local templates expanded per city + "near me" + de-localised)
- Evidence: `p08`: 27 profile questions generated (22 / 3 / 2 by persona; 16 of 27 are `local_transactional` city expansions); kept at cap 20: `Counter({'prospective_client': 20})` — the other two personas never run. The report's "Client mention rate by persona" then shows one persona, and the trend table across runs is a trend on near-duplicate city variants.
- Why it matters: the methodology sells persona segmentation and a per-engine trend; at the default budget the sample is 20 questions of which most are "family counselling {city}" permutations, so a change of ±1 mention is ±5 points and all of it is one persona.
- Fix: sample proportionally or round-robin across personas when truncating; log and print "N of M generated questions asked; personas dropped: …"; de-duplicate city variants to one per template before capping.

### D-M-19 · Pivot explanation asserts "dominated by high-authority directories" unconditionally, and the service-intent gate is a token test that ignores the SERP intent verdict
- Class: WRONG (label) / UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe)
- Where: `feasibility.py:244-252` (hard-coded "currently dominated by high-authority directories (Avg DA: …) … over a national directory"), `query_variants.is_service_like:63-84` and `play_routing._is_service_like:146-153` (substring on `service_like_tokens`: counselling/therapy/therapist/…), `run_feasibility.py:303-305` (gate uses only the token test), `docs/feasibility.md` ("Pivots are gated on service intent")
- Evidence: `p07`: `generate_hyper_local_pivot("how does family therapy work", …, Low, is_service_like=True)` → "The city-wide market for 'North Vancouver' is currently dominated by high-authority directories (Avg DA: 70)…"; both predicates return `True` for "how does family therapy work" because it contains "therapy", so an informational question gets the geo pivot and a paid validation fetch, while the SERP intent verdict computed for the same keyword is never consulted.
- Why it matters: the entity mix is known (`entity_distribution`) and the SERP verdict is known; the text invents a directory-dominated market and the gate contradicts `docs/feasibility.md`'s "service-intent" claim.
- Fix: gate on `serp_intent.primary_intent in {local, transactional}` (or mixed with a local component) with the token test as fallback when the verdict is None; build the explanation from `entity_distribution` ("4 of 10 ranking pages are directories (avg DA 78)") or omit the clause.

### D-M-20 · AI Overview exposure constants (28/15/10… CTR curve, 0.60 interception, 0.5 citation credit) have no cited source and the rollup trend mixes runs with different keyword sets
- Class: UNDOCUMENTED PROVENANCE
- Impact: Medium
- Verdict: CONFIRMED (trace)
- Where: `config.yml:231-250` ("industry reference points" — no study, vendor or date), `aio_exposure.py:49-58`, `:286-310` (`get_aio_exposure_trend` groups by `run_ts` with no keyword-set comparability check, unlike `metrics.get_volatility_metrics`), `docs/methodology.md` §5d ("the industry '~60% AIO CTR interception' reference")
- Evidence: the heuristic is labelled "estimated" in the report (good), but "industry reference" is the whole provenance; `citation_credit: 0.5` is an assumption with no stated basis; the position curve is applied to a per-page `client_rank` (D-M-01). The trend's `aio_coverage_pct` across runs on `keywords_leila.csv` vs `keywords_family_of_origin_work.csv` is reported as a delta.
- Fix: name the source and date next to each constant in `config.yml` and the glossary ("CTR curve: <vendor study>, <year>, desktop US"), or mark them "owner's assumption"; in the trend, only compare runs whose keyword set matches (reuse the `comparability_warning` pattern from `metrics.py`).

### D-M-21 · Core thresholds and weights carry no stated derivation: DA gap 5/15 and score normaliser 30; intent 0.60/0.40/0.20 and the 8/5 counts; title dominance 4/10; commodity 0.4/0.3/0.2/0.1 and bands 40/70; AIVI 25% × 4; foundational thirds; prioritisation 0.5/0.3/0.2; demand bands 2.4%/10%; entity dominance 0.60 and `report_thresholds.entity_dominance`
- Class: UNDOCUMENTED PROVENANCE
- Impact: Medium (they decide every verdict label)
- Verdict: CONFIRMED (trace)
- Where: `feasibility.py:38-46`, `docs/config_reference.md:140-141` ("code default 5"), `intent_verdict.py:66-70`, `:137-147`, `title_patterns.py:93`, `commodity_score.py:47-55`, `config.yml` `aivi.weights` ("documented in docs/methodology.md so the score is defensible" — the doc records the value, not a reason), `foundational.weights`, `engine_prioritization.weights`, `gsc_demand.bands`, `brief_data_extraction.py:198`, `config.yml:report_thresholds`
- Evidence: every one is either a code constant or a config value whose comment says "default" or "industry reference"; none names a study, a calibration run, or an owner decision record. `docs/methodology.md` calls the AIVI equal weights "defensible" because they are tunable. The spec history (Y-D6, D-D4a) records that the owner approved them, which is a provenance of sorts — but the reports do not say "editorial weights, uncalibrated".
- Fix: add a one-line `source:` beside each threshold in `config.yml` ("editorial, owner 2026-07-06; not calibrated") and surface "editorial thresholds" once in the glossary entries for feasibility status, commodity band and AIVI; where a calibration is possible (feasibility: compare gap vs. whether the client actually ranks over successive runs), note it as future measurement.

### D-M-22 · Root `methodology.md` is a stale 2026-05-01 reading guide that contradicts the contract doc on several points
- Class: DOC–CODE DRIFT
- Impact: Low–Medium (it is the file a newcomer opens first; CLAUDE.md names `docs/methodology.md` as the contract)
- Verdict: CONFIRMED
- Where: `methodology.md:3` ("as it stands at 2026-05-01"), `:111-115` ("DA (currently 35)", thresholds), `:213-215` ("trigger vocabularies … are effectively hardcoded … This is the next file to externalise" — `intent_classifier_triggers.yml` has existed since I.2), `:302` ("`generate_content_brief.py` and `generate_insight_report.py` weren't in the upload"), `:236` (`local_pack_member_count` "isn't used in the verdict computation itself" — still true, and `intent_mapping.yml` header edge case 2 says "The local pack contributes its own `local` count from map-pack URLs", which the code never does)
- Fix: delete or retitle it `docs/reading_guide_2026-05-01.md` with a banner; correct the `intent_mapping.yml` edge-case-2 sentence (local-pack members are never counted as URLs).

### D-M-23 · Glossary defines DA gap with the formula reversed
- Class: DOC–CODE DRIFT
- Impact: Low (but it is printed in every report's §A)
- Verdict: CONFIRMED
- Where: `glossary.yml:256-261` ("Your Domain Authority minus the average of the sites currently ranking. A negative gap means you are stronger"), vs `feasibility.py:96` (`gap = avg_serp_da − client_da`) and `glossary.yml:151` columns block ("avg_serp_da minus client_da", correct)
- Fix: "The average Domain Authority of the sites currently ranking minus yours…".

### D-M-24 · `feasibility_score` exceeds its documented 0–1 range
- Class: WRONG (minor)
- Impact: Low (field is persisted to SQLite and the xlsx; not used for ranking)
- Verdict: CONFIRMED (fixture + probe)
- Where: `feasibility.py:98` (`max(0.0, 1.0 − gap/30)` — no upper clamp), docstring `:81` ("0.0 (worst) … 1.0 (best)")
- Evidence: reference run `feasibility_score: 1.47`; `p07` gap −15 → 1.5.
- Fix: `min(1.0, …)` or document the range as unbounded above.

### D-M-25 · A failed sentiment classification is stored as "neutral", a measured value
- Class: WRONG
- Impact: Low (sentiment is OFF by default)
- Verdict: CONFIRMED
- Where: `answer_sentiment.py:64-85` ("A malformed/failed response degrades to a neutral label with empty aspects"), `sentiment_axis` counts it in `% positive`'s denominator
- Fix: store `polarity: None` / `status: failed` and exclude from the axis; print "n classified of m attempted".

### D-M-26 · Bowen trap triggers include words that appear on essentially every counselling SERP, so the "pattern fired" verdict carries little information and the report does not quantify it
- Class: UNLABELLED HEURISTIC
- Impact: Low–Medium
- Verdict: PLAUSIBLE (trigger lists read; firing rate not measured here)
- Where: `strategic_patterns.yml:47-52` (Medical Model: `registered`, `mental health`, `treatment`), `:70-74` (Fusion: `connection`, `close`, `communication`), header `:15-22` (the file's own rule: "Bad triggers: common words that appear everywhere in the topic domain"), `pattern_matching.py:429-433` (fires on any whole-word hit; reports up to 5 detected triggers, no counts, no share of corpus)
- Evidence: "registered" is in every RCC byline on a BC counselling page; "connection"/"communication" are the vocabulary of every couples page. The root reading guide concedes over-firing; the report's §4 shows "Detected triggers" but not how many times or in what fraction of results, and the directive text treats a fired pattern as evidence the SERP "frames" the problem that way.
- Fix: print per-pattern hit counts and the share of ranking pages containing any trigger; drop/replace triggers that violate the file's own rule (`registered`, `mental health`, `close`, `communication`); label §4 "trigger-word presence, not framing analysis".

### D-M-27 · Validator coverage: the claims most likely to be wrong upstream are not checkable
- Class: UNLABELLED HEURISTIC
- Impact: Low–Medium
- Verdict: CONFIRMED (code read)
- Where: `brief_validation.py:54-400` (regex rules for AIO counts, intent/mixed/dominant-pattern parity, play parity, "toxic", one keyword-specific "estrangement" rule, "monthly searches")
- Evidence: there is no rule for DA figures, client rank, "market too small"/total_results, freshness ages or persona rates; the validator cannot see that `client_rank` or `avg_serp_da` were mis-measured (D-M-01/02), so the brief faithfully repeats them. The keyword-specific "estrangement" rule is dead weight for other keyword sets.
- Fix: add a rule that any numeric the model states for `client_rank`, `avg_serp_da`, `gap`, `total_results` must match the profile exactly, and a rule forbidding market-size language unless `moz.data_available`; remove the estrangement special case.

---

**Checked and found sound**
- Moz intent cross-check (`moz_keywords.crosscheck_intent`, `_build_moz_intent`): `agrees = None` for mixed/unmappable, rendered and prompted as "not comparable", never as disagreement.
- Moz keyword metrics: keywords with no Moz record carry `data_available: false` and no numeric fields; the prompt forbids demand claims for them.
- AIVI composite mechanics (`aivi.compute_aivi`): a `None` axis is excluded and weights renormalise; sentiment-off is rendered "n/a" (the failure is in which engines are fed in, D-M-03, not in the arithmetic).
- Commodity `low_confidence` demotion (< 3 texts can never be "high").
- Pivot validation fetch failure → "Not Measured" / local pack `None`, never a false negative (`run_feasibility.py:373-384`, `_local_pack_phrase`).
- GSC "no row" cached as measured absence, never a zero; sponge bands print "insufficient data" below n=3.
- Volatility comparability warning when keyword sets differ (`metrics.py:81-91`).
- §5b prints "distribution … over N of M classified URLs" and "insufficient data" when primary is None.
- Title-pattern `other` is never eligible as dominant; 4/10 is conservative at 6 classifiable titles (4/6).
- Play routing: all seven rules are reachable; `mixed_intent_strategy` is a declared-but-unused match field (no rule keys on it), which is harmless; rule ordering gives reformat > rank > local pivot > extraction as documented.
- `aio_trigger_analysis` prompt explicitly forbids importing the 23%/77% claim and states empty buckets as unmeasured.
- Glossary jargon guard test exists and the §A glossary is filtered to terms used.
- `ai_visibility_export.py` is a pure reader of stored rows and writes `data_available: false` when tables are empty (no fabrication; it does not export the AIVI table, so D-M-03's zeros do not reach serp-compete through it).

**Not examined**
- The tkinter GUI (`serp-me.py`, `config_manager.py`) beyond the dead `confidence_*` tooltips.
- `moz_competitor.py` handoff payload (ranking keywords / anchor text) — declared non-scoring.
- `bing_check.py`, `situational_probes` execution paths (OFF in config), `url_enricher.py` extraction accuracy (freshness/E-E-A-T/question-heading detection), `classifiers.py` content/entity rules themselves (the 51% `other` rate is acknowledged in `docs/classifier_residual_20260501.md`).
- Live SerpAPI/DataForSEO/Moz/engine responses — all conclusions about the rank shape rest on the committed reference run plus code reading; D-M-01 should be re-confirmed on one raw `raw/{run_id}/` response before the fix is written.
- The LLM prompts' wording beyond the fields the validator checks.
