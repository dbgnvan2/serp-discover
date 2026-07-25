# Serp Discover — Build Spec (AI-Era Visibility & Demand)

**For:** Claude Code implementation in the existing `serp-discover` repo. **Backend:** Python.
**Assumed data access (per product owner):** SerpAPI SERP data, Google Search Console (GSC) API, LLM APIs (OpenAI, Gemini, Anthropic/Claude, Perplexity). Infrastructure is out of scope — this document specifies *functionality and logic only*.

> **Reconciliation note (2026-07-22).** This spec was revised against the real repo. The original draft assumed a generic web-app stack (REST endpoints, SQLAlchemy ORM, Pydantic response models, a `scoring_config` table, background job workers). **None of that exists here.** serp-discover is a **Python CLI + tkinter GUI batch tool** that reads `keywords_*.csv`, fetches/parses SERPs, and writes `market_analysis_*.{json,xlsx,md}` plus enrichment reports, persisting history to a raw `sqlite3` database `serp_data.db`. All invented model/module/endpoint names below have been replaced with the repo's real ones, and each feature carries a build-status marker (`already-exists` / `partially-exists` / `new`). See `RECONCILIATION_CHANGES.md` for the full diff against the draft.

---

## Repo conventions this spec must follow

- **No web layer, no ORM.** Persistence is raw `sqlite3` via `storage.py` (`class SerpStorage`, core tables) and per-feature modules that open their own connection and `CREATE TABLE IF NOT EXISTS`. Migrations are `ALTER TABLE … ADD COLUMN` wrapped in `try/except sqlite3.OperationalError`. **Do not introduce SQLAlchemy or a migration framework.** Add new tables the same way the AI-visibility modules already do (`aivi.py`, `brand_mentions.py`, `citation_table.py`, `answer_sentiment.py`, `engine_transfer.py`, `foundational_score.py`, `probe_ai_visibility.py`).
- **Config is YAML, not a DB table.** Operational settings and all scoring weights/thresholds live in `config.yml`, loaded with `yaml.safe_load`, edited through the `config_manager.py` tkinter GUI, validated by `config_validators.py`. Cross-tool client identity/thresholds come from the out-of-repo `shared_config.json` via `shared_config.py`. **There is no `scoring_config` table and no `config_version` field today.** Where the draft said "store in `scoring_config`, stamp `config_version`", this means: **add a `config.yml` key group** (follow `aivi.weights` / `foundational.weights` / `engine_prioritization.weights` precedent — equal-default, malformed→fallback+warning, documented in `docs/methodology.md`). If per-run reproducibility stamping is wanted, follow the existing `weights_json` column pattern (`ai_visibility_index.weights_json`, `foundational_score.weights_json`) rather than inventing a global `config_version`.
- **Editorial content goes in config files, not Python.** Trigger words, category labels, routing rules, vocab tiers belong in the existing YAML/JSON surface (`intent_mapping.yml`, `play_routing.yml`, `strategic_patterns.yml`, `serp_vocab.yml`, `classification_rules.json`, `client_profiles.yml`, `engine_profiles.yml`, `domain_overrides.yml`). New editorial knobs go there too.
- **Spec-ID system.** Commits/docstrings carry a `Spec:` reference. This repo uses namespaced IDs per initiative — e.g. `Y.1–Y.13` + decision gates `Y-D2…Y-D9` (`yoast_geo_upgrade_spec_v1.md`), `C.x`/`T.x`/`G.x` (`seo_geo_deferred_spec_v1.md`, `seo_geo_review_*`), `I.x`, `RC.x`, `v2.G1.x` (`serp_tools_upgrade_spec_v2.md`). **Give the features in this spec their own namespace** (proposed below: `AV.x` for AI-Visibility/demand). Spec files live in the **repo root**; status/coverage docs live in `docs/` (`docs/spec_coverage.md` is the master matrix — regenerate after any spec-driven change). `docs/methodology.md` is a contract: update it in the same change as any file it references.
- **Tests & venv.** `source venv/bin/activate`, then `python3 -m pytest test_*.py tests/ -q`. Business-logic tests must not require tkinter (source-inspection tests catch GUI init-order bugs). All external calls are mocked; tests need no API keys. Add a canary entry to `test_validation_consistency.py` if any new pre-computed `keyword_profiles.<field>` is introduced.
- **Provenance today is partial, not uniform.** Existing rows carry `run_ts` (all AI-visibility tables, UTC), `fetched_at` (`url_features`, `gsc_cache`), `computed_at` (`keyword_feasibility`), and `weights_json` where a weighted score is stored. There is **no** repo-wide `source/fetched_at/computed_at/config_version` quadruple. Where this spec says "stamp provenance", extend the existing per-table pattern; don't retrofit a universal schema.
- **Themed statistics are reference framings.** Any copy referencing the "~60% CTR drop", "2.4% vs 10% branded share", the barbell, or "site-reputation abuse" must render as an industry reference point, not a measured fact about livingsystems.ca. Store such constants in `config.yml` (not code) and label them in the report text.

**Client concept.** There is no `project_id` multi-tenant model. "The tracked domain" is the single **client** defined in `config.yml → analysis_report` (`client_domain: livingsystems.ca`, `client_name_patterns: ["Living Systems"]`) and `ai_visibility.client_slug` / `client_profiles.yml`. Domain matching uses the existing `_is_client_domain` helper (registrable-domain level). Read every "per project" rollup below as "per client run".

---

## D1 — AI Overview & Zero-Click Exposure Tracking · **partially-exists**

**Problem.** Rankings no longer predict clicks: an AI Overview (AIO) can intercept the click at position 1. Discover should tell the user, per keyword, whether an AIO is present, whether the client domain is *cited inside* it, and the estimated click impact.

**What already exists (reuse, don't rebuild).**
- SERP-feature parsing incl. AI Overview: `serp_audit.py` produces `Has_Main_AI_Overview` / `has_aio` and extracts `ai_overview_citations` from the SerpAPI payload (`brief_data_extraction.py:~1128`).
- **AIO citation-vs-rank divergence** is fully built: `brief_data_extraction.py::_build_aio_divergence()` computes per-keyword `has_aio_citations`, `cited_not_ranking_top10`, `ranking_top10_not_cited`, `client_in_top10`, and the headline flag **`client_ranks_but_not_cited`** (client ranks top-10 but the AIO cites others). Stored on `keyword_profiles[kw].aio_divergence`.
- First-party zero-click measurement exists in the GSC path: `run_gsc_analysis.py::compute_sponge_effect()` compares median CTR at a comparable position band for AIO-present vs AIO-absent queries.

**What is new.** A **modeled market-side CTR-loss estimate** (independent of GSC) and a project-level AIO exposure rollup with a trend series. The divergence flags exist; a numeric `est_ctr_loss` does not.

**Data model (extend the existing AI-visibility table family; new table).**
```
ai_aio_exposure   (run_ts, keyword, source,               -- follow ai_visibility_probes column style
                   aio_present INT,                        -- from Has_Main_AI_Overview / has_aio
                   client_cited INT,                       -- from aio_divergence.client_ranks_but_not_cited (inverted)
                   cited_urls_json TEXT,                   -- ai_overview_citations
                   organic_position INT,                   -- client rank, NULL if unranked
                   est_ctr_loss REAL,                      -- new heuristic (see logic)
                   weights_json TEXT)                      -- the CTR curve + multiplier config used
```
Create it exactly like `citation_table.CITATIONS_TABLE` (own `sqlite3.connect`, `CREATE TABLE IF NOT EXISTS`, UTC `run_ts`). Do **not** add a `keyword_profiles.aio_est_ctr_loss` field unless you also add its validator/canary in `test_validation_consistency.py`.

**Core logic.**
1. Read `aio_divergence` + `has_aio` off the existing `keyword_profiles` (no re-parse).
2. `client_cited = not aio_divergence.client_ranks_but_not_cited AND has_aio_citations AND client_in_top10-or-cited`.
3. Estimate click impact (heuristic; all constants in a new `config.yml → aio_exposure` block, following the `aivi.weights` precedent):
   - `ctr_base(position)` from a configurable organic CTR curve.
   - If `aio_present`: `est_ctr_loss = ctr_base(position) * aio_ctr_multiplier` (default `0.60` — the industry ~60% figure; **label as estimate in the report, store the constant in config**).
   - If `client_cited`: `est_ctr_loss *= (1 - citation_credit)` (default `0.5`).
4. Roll up per run: `aio_coverage_pct`, `cited_share`.

**Access surface (not REST — this repo renders reports + a GUI).**
- New **report section** in the market-analysis markdown via `generate_insight_report.py` (it already renders `## 5b. Per-Keyword SERP Intent`): add "AI Overview Exposure" with the sortable table (keyword, organic position, AIO present, cited?, est. CTR loss), default sort = highest `est_ctr_loss` where `client_cited=false`.
- Trend via the existing history mechanism (`get_engine_trend`-style query over `ai_aio_exposure.run_ts`, `history_runs` from config).
- Surface in the `serp-me.py` GUI as a step, consistent with `docs/gui_steps.md`.

**Acceptance criteria.**
- Snapshot whose AIO lists the client → `client_cited=true`, loss reduced by `citation_credit`.
- AIO not listing the client → `client_cited=false`, full `aio_ctr_multiplier`.
- `aio_coverage_pct` = AIO-present keywords / total tracked keywords for the run.
- Report copy marks estimates as "estimated"; the `0.60` / `0.5` constants come from `config.yml`, not literals in code.

**Edge cases.** AIO present but empty citation list → `aio_present=1, cited_urls_json=[]`. Client unranked but cited → `organic_position=NULL`, still report `client_cited`. Registrable-domain matching via `_is_client_domain` (not URL-exact).

---

## D2 — Branded vs Non-Branded Demand Score (GSC) · **partially-exists**

**Problem.** Clicks fall but *brand demand* predicts survival. Discover should surface how much of the client's search demand is name-seeking, and trend it.

**What already exists.** `gsc_client.py` (`class GscClient`, service-account auth, cache table `gsc_cache` with `fetched_at`, 7-day TTL, `http_retry` semantics) fetches clicks/impressions/ctr/position per query. `run_gsc_analysis.py` computes the zero-click **sponge effect** and **reformat candidates** (`find_reformat_candidates`, cross-referenced with `strategic_flags.geo_alerts`), writing `gsc_analysis_<topic>_<ts>.{md,json}` and an optional brief sidecar when `gsc.feed_strategic_flags`. GSC config lives under `config.yml → gsc` (`enabled`, `property: sc-domain:livingsystems.ca`, `lookback_days: 90`, `cache_ttl_days: 7`). It is **standalone**, never imported by the pipeline.

**What is new.** The **branded vs non-branded classification and share** itself. There is no `brand_terms` config key and no query segmentation today. The nearest brand-identity primitives are `analysis_report.client_name_patterns` (`["Living Systems"]`) and the empty `config.yml → known_brands` list — **reuse `client_name_patterns` as the brand-term seed; do not invent a parallel `brand_terms` model.**

**Data model (new table, colocated with GSC).**
```
gsc_demand_daily  (property, date, query, clicks, impressions, position,   -- mirrors gsc_cache grain
                   is_branded INT,                                          -- classified
                   source TEXT DEFAULT 'gsc', fetched_at TEXT)
gsc_demand_score  (property, date,
                   branded_clicks INT, nonbranded_clicks INT,
                   branded_impressions INT, nonbranded_impressions INT,
                   branded_click_share REAL,
                   benchmark_band TEXT,        -- below_avg | avg | top
                   weights_json TEXT)          -- band thresholds used
```
Add these in `run_gsc_analysis.py` (or a new `gsc_demand.py` that `run_gsc_analysis.py` imports), same raw-sqlite pattern.

**Core logic.**
1. Classify each GSC query as branded if any `client_name_patterns` entry matches (case-insensitive; allow a regex/negative-term override list added to `config.yml`). Cache per distinct query string.
2. `branded_click_share = branded_clicks / max(total_clicks, 1)`.
3. Benchmark bands (reference points, in a new `config.yml → gsc_demand.bands` block; **label in report as industry reference, not target**): `below_avg < 0.024`, `avg [0.024, 0.10)`, `top ≥ 0.10`.
4. Trend: expose a series so a falling clicks line vs a rising branded share is visible.

**Access surface.** Extend the `gsc_analysis_*.md/json` outputs with a "Branded vs Non-Branded Demand" section (headline share + band + dual series + which patterns matched). Respect GSC's 2–3 day lag: mark the most-recent days `provisional=true`, visually distinct.

**Acceptance criteria.**
- Editing `client_name_patterns` (or the branded override list) triggers reclassification for the affected range.
- `branded_click_share` for a day = branded clicks / total clicks from the same GSC pull.
- Provisional lagging days flagged.
- Band thresholds come from `config.yml`, not literals.

**Edge cases.** No branded queries → share `0`, band `below_avg`, no divide-by-zero. Generic-word brand → regex/negative-term override. Multiple properties → aggregate at client level with de-dup (single `property` today).

---

## D3 — Demand-vs-Clicks Dashboard · **new**

**Problem.** One view that operationalizes "clicks ≠ demand" — traffic falling while demand holds.

**What exists to draw on.** D1 (`ai_aio_exposure.est_ctr_loss`), D2 (`gsc_demand_score.branded_click_share`), GSC clicks/impressions (`gsc_cache`), and rank/visibility from `serp_results` + `keyword_feasibility`. Note: existing "visibility" greps are unrelated (`aivi.py` = AI-engine visibility; `bing_check.py` = Bing presence; `probe_ai_visibility.detect_visibility` = mention detection). There is **no GSC-click visibility index today** — this feature is new.

**Data model.** No new primary storage — a **read-model** assembled at report time (a function in `generate_insight_report.py` or a new `demand_dashboard.py`) aggregating: `total_clicks`, `total_impressions`, `avg_visibility`, `branded_click_share`, `aio_coverage_pct`, `est_traffic_at_risk`. If a materialized cache is wanted, add a `demand_dashboard_daily` table via the standard pattern.

**Core logic.**
- `visibility` = Σ over tracked keywords of `ctr_base(position) * search_volume`, normalized 0–100.
- `demand_index` = normalized branded impressions + branded clicks (name-seeking proxy).
- `divergence_flag` = true when, over the trailing window, `visibility`/clicks trend down while `demand_index` is flat-or-up beyond configurable slopes (constants in `config.yml`).

**Access surface.** A "Demand vs Clicks" section in the market-analysis report (two normalized lines + a callout when `divergence_flag` is set). Frontends that render charts should follow existing report conventions; no web dashboard framework is present.

**Acceptance criteria.** `divergence_flag` fires only when both slope conditions hold over the full window; unit-tested with synthetic series (down/up, down/down, up/up). Indicators recompute when D1/D2 update. Sparse data (<30 days) → suppress flag, show "insufficient history". Seasonal sites → optional YoY mode.

---

## D4 — Query Commodity / AI-Absorption Risk Score · **partially-exists**

**Problem.** If ~100 sites answer a question identically, an AI answer can replace them all with one paragraph. Score each tracked query by how commoditized its answer is.

**What already exists (assemble from these, don't start blank).**
- **`play_routing.py` + `play_routing.yml`** — the ordered, first-match-wins "Recommended Play" decision table routing each keyword to one of five plays: `rank_play`, `extraction_play`, `reformat_play`, `local_pivot_play`, `deprioritize`. Computed as `keyword_profiles[kw].recommended_play` in `brief_data_extraction.py`. **`extraction_play` and `deprioritize` are the commodity-adjacent verdicts** (route on feasibility, `serp_intent`, `has_ai_overview`, `aio_divergence.client_ranks_but_not_cited`, service tokens, `has_local_pack`).
- **`metrics.py::get_entity_dominance()`** — SERP homogeneity by entity type vs `report_thresholds.entity_dominance`.
- **`engine_transfer.py`** — cross-engine cited-domain **Jaccard overlap** (answer homogeneity across LLM engines); table `engine_transfer` (`avg_jaccard`, `cited_by_all`, …).
- SERP-intent verdicts (`intent_verdict.py`, `serp_intent.thresholds`) and title-shape patterns (`title_patterns.py`).

**What is new.** A single named **commodity/AI-absorption composite** and its optional "one-paragraph answerable" LLM probe.

**Data model (new table).**
```
commodity_score  (run_ts, keyword,
                  answer_similarity REAL,        -- 0..1 mean pairwise similarity of top-N snippets/summaries
                  serp_homogeneity REAL,         -- from entity-dominance / title-pattern variance
                  aio_present INT,               -- from D1
                  one_paragraph_answerable INT,  -- optional LLM probe, gated
                  commodity_score REAL,          -- 0..100 composite
                  risk_band TEXT,                -- low | medium | high
                  weights_json TEXT)
```

**Core logic (heuristic composite; weights in `config.yml → commodity.weights`, equal-default+fallback like `aivi.weights`).**
1. `answer_similarity`: embed top-N snippets/summaries; mean pairwise cosine. Degrade to title/snippet similarity if page text unavailable.
2. `serp_homogeneity`: reuse `get_entity_dominance()` + `title_patterns` variance.
3. `one_paragraph_answerable`: optional, gated by a cost flag mirroring `sentiment.enabled` / `brand_mentions.llm_extraction` (OFF by default; model id from config, never hardcoded); cache by query.
4. Composite `= 100 * (w1*answer_similarity + w2*serp_homogeneity + w3*aio_present + w4*one_paragraph_answerable)`, default `0.4/0.3/0.2/0.1`; bands `<40 low / 40–70 medium / >70 high`. When the LLM probe is off, renormalize the remaining three weights.

**Access surface.** Per-keyword risk badge + driver explanation in the report; a run-level "differentiate or lose" queue sorted by `commodity_score`. Recommended action per band should reuse/point at the existing play routing (`extraction_play` / `deprioritize`) rather than a parallel recommendation string.

**Acceptance criteria.** Two queries with identical top-N snippets score higher `answer_similarity` than a diverse one. LLM probe skipped when its flag is off; score still computes (renormalized). Reproducible given the same snapshot + `weights_json`. <3 ranking results → `low_confidence=true`.

---

## D5 — Own-Brand AI Visibility Monitor · **already-exists (do not rebuild — extend only)**

**Problem.** Track whether the LLMs (ChatGPT/OpenAI, Gemini, Claude, Perplexity) mention the client, cite its URLs, and with what sentiment — over time.

**This is the most-built feature in the repo. It is implemented end-to-end. A revised spec should describe the existing system and only propose incremental extensions, never a green-field build.**

**Real implementation (reuse these exact modules/tables/config).**
- **Probe runner:** `probe_ai_visibility.py` — `VALID_ENGINES = ("claude","gemini","openai","perplexity")`, `DEFAULT_ENGINES = ["gemini","openai","perplexity"]` (also `config.yml → ai_visibility.engines`). Probe classes `ClaudeProbe`, `GeminiProbe`, `ChatGPTProbe` (OpenAI Responses API + `web_search`), `PerplexityProbe` (Sonar). Each `ask(question)->dict`; missing API key → skip-with-warning, never abort. Models/endpoints from `config.yml → ai_visibility.*` (`openai_model: gpt-4o`, `perplexity_model: sonar`, `gemini_model`, `claude_model`). Standalone; **never imported by the pipeline** (gate D-2). Ceilings: `max_questions: 20`, `max_total_calls: 60`.
- **Question generation:** `profile_questions.py` + `client_profiles.yml` — persona-segmented from the client profile (`brand_name`, `domain`, `personas[*].{label, needs, seed_questions, templates}`, city-expanded). Precedence: profile → situational (`serp_vocab.situational_templates`) → PAA → template. Edited in the config_manager "Client Profile & Queries" tab.
- **Mention detection:** `brand_mentions.py` — deterministic gazetteer `build_gazetteer(known_brands, analysis_data)` (config `known_brands` + competitor Source labels harvested from the analysis JSON) + `probe_ai_visibility.detect_visibility`; `build_leaderboard()` → rows `{brand, mention_count, is_client, source}`; `client_ranking_axis()`. Gated LLM pass (`brand_mentions.llm_extraction: false`) writes unknown-brand candidates to `brand_mentions_candidates_<topic>_<ts>.md` (no silent taxonomy growth). Table **`brand_mentions`**.
- **Citation extraction:** `citation_table.py` — per-answer source URLs categorized by the existing classifier (`publisher` entity type in `classification_rules.json`), brand-attributed, `is_client` flag, de-duped with `cite_count`. Table **`ai_citations`**.
- **Sentiment:** `answer_sentiment.py` — gated (`sentiment.enabled: false`, Y-D8: disabled = zero calls, "not measured", AIVI excludes the axis); one LLM classification per client/top-competitor answer → polarity + verbatim aspect phrases. Table **`answer_sentiment`**. Model id from config.
- **Composite (AIVI):** `aivi.py` — 0–100 per engine + all-engine average from four normalised axes (Mentions, Ranking, Citations, Sentiment), weights from `config.yml → aivi.weights` (equal 25% default; malformed→equal+warn; sentiment-OFF axis n/a and renormalised). Table **`ai_visibility_index`** (per-axis values + `weights_json`). Documented in `docs/methodology.md`.
- **History/trend:** table **`ai_visibility_probes`** (`save_probe_rows`, `get_engine_trend`), `get_aivi_trend`, `history_runs: 5`. Columns incl. `persona`, `source` (Y.5 ALTERs).
- **Adjacent engine-strategy modules (already built):** `foundational_score.py` (table `foundational_score`, transferable GEO readiness, `config.yml → foundational.weights`), `engine_recommendations.py` + `engine_profiles.yml` (per-engine advice + prioritization blend, `config.yml → engine_prioritization.weights`), `engine_transfer.py` (table `engine_transfer`, cross-engine Jaccard).
- **Gating flags:** `ai_visibility.assume_yes`, `max_total_calls`, `brand_mentions.llm_extraction`, `sentiment.enabled`, per-engine API-key presence.

**Mapping the draft's invented schema to reality.** Draft `ai_probe` → real `ai_visibility_probes`. Draft `ai_probe_result` → split across `brand_mentions` (mention), `ai_citations` (citation), `answer_sentiment` (sentiment). Draft `ai_visibility_daily` → real `ai_visibility_index` (+ trend queries). Draft `prompt_templates` → `client_profiles.yml` personas + `profile_questions.py`. Draft "reuse D2 `brand_terms`" → real `build_gazetteer` over `known_brands` + `client_name_patterns`.

**Proposed extensions only (mark `new` sub-items).**
- Persist per-answer `raw_answer` for a full audit trail if not already retained beyond `answer_excerpt`.
- Optional negative-sentiment alerting off the existing `answer_sentiment` table.
- **Export mention/citation rows for serp-compete C1 (cross-tool obligation — added 2026-07-22).** The owner decided Compete's competitive AI share-of-voice (C1) will **consume** Discover's outputs rather than run its own probes. Discover must therefore expose the `brand_mentions` and `ai_citations` rows (with `is_client`, `engine`, `run_ts`) in a location Compete can read — either the existing analysis JSON or a small sidecar export keyed off the run. Follow the existing one-way handoff precedent (`handoff_writer.py` → `competitor_handoff_*.json`); the exact export shape is a small follow-up to pin down when C1 is built. No new probing — this is a read-side export of data D5 already stores.
- These are the only genuinely-new items in D5; everything else is `already-exists`.

**Access surface.** Reporting already emits per-engine cards + a probe log. Keep the "results vary run-to-run; show rolling average not single run" caveat that the existing report carries.

**Acceptance criteria (regression, not new build).** Brand-name-containing answer → `mentioned=true` + count. Sentiment computed only over brand-mention sentences (existing behavior; keep the adversarial test). Engine failures isolated. AIVI recomputes from `aivi.weights`.

---

## Boundary note (Discover vs Compete)

The draft's Discover/Compete split (**Discover = single-site**, **Compete = comparative**) **matches the real repos** and is retained. Confirmed facts:
- serp-discover is single-site (client-visibility) analysis. Its only competitor-facing code is (a) `handoff_writer.py::build_competitor_handoff()` → `competitor_handoff_{topic}_{ts}.json` (validated against `handoff_schema.json`), a **producer** that passes raw competitor targets to serp-compete — not a comparison; and (b) the `brand_mentions.py` leaderboard, which is **client-centric share-of-voice** (who gets mentioned in answers to the *client's* persona questions), single-site framed.
- Therefore D1–D5 correctly live in Discover. Compete's C1 (AI answer share-of-voice *vs named competitors*) is a genuine sibling. **Decided (2026-07-22): C1 consumes Discover's `brand_mentions`/`ai_citations` outputs** rather than duplicating `probe_ai_visibility.py` — see `compete-spec.md` C1 and the D5 export sub-item above. No Discover feature moved to Compete and vice-versa.

---

## Cross-cutting requirements (Discover)

- **Provenance:** extend the existing per-table pattern (`run_ts` on AI tables, `fetched_at`/`computed_at` where present, `weights_json` for weighted scores). Do not retrofit a universal `source/fetched_at/computed_at/config_version` schema; there is no `config_version` today.
- **Reproducibility:** re-running on the same stored snapshot + `weights_json` yields the same result (no wall-clock/randomness in scoring).
- **Config-driven thresholds:** all new bands/weights/multipliers in `config.yml` under their own key group (equal-default + malformed-fallback + `docs/methodology.md` entry), never literals in Python.
- **Test data:** ship synthetic SERP snapshots + GSC fixtures (AIO present/absent, cited/not-cited, branded/non-branded, sparse-history) under `tests/fixtures/`; mock all external calls.
- **Themed-statistic labeling:** the "~60% CTR drop", "2.4% vs 10% branded share" etc. are industry reference points in `config.yml`, labeled as such in report copy — not measured facts about livingsystems.ca.
- **Methodology contract:** update `docs/methodology.md` and regenerate `docs/spec_coverage.md` in the same change as any file they reference.
