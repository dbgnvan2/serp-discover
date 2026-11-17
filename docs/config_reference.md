# Configuration reference — config.yml keys and rule files

**`config.yml`** — all operational settings:
- `serpapi.*` — API params (engine, location, pagination, retries, modes)
  - `serpapi.timeout_seconds` (default `60`) — how long one SerpAPI call may take before it is abandoned and retried (`retry_max_attempts`). Used by `serp_audit.py` and by the pivot fetches in `run_feasibility.py`. A missing, zero or non-numeric value falls back to 60 with a warning; there is no way to switch the timeout off. Without it the client library waits 16.7 hours.
  - `serpapi.resume_max_age_hours` (default `24`) — how long the stored SerpAPI responses of an unfinished run may be reused by a resumed run (`serp_checkpoint.py`). `0` means never reuse. A negative or non-numeric value falls back to 24 with a warning.
  - `serpapi.google_max_pages` (default `3`) / `serpapi.num` / `serpapi.google_max_results` — pagination ceilings. Google serves roughly 10 organic rows per page whatever `num` asks for, so three pages reach about the **top 30**, not the top 300: `num: 100` and `google_max_results: 300` are never the binding limit, `google_max_pages` is. Raise `google_max_pages` to go deeper, and expect one SerpAPI call per page per keyword.
  - `serpapi.location` — the market Google is asked about. Use SerpAPI's own `canonical_name` for the place (`https://serpapi.com/locations.json?q=<city>`), e.g. `North Vancouver,British Columbia,Canada`. It must name the same place as `feasibility.non_profit_location`, which is the market the feasibility verdicts and neighbourhood pivots assume; `config_validators.validate_config_yml` warns when the two disagree, because a run that searches one city and scores another produces a competitive set for the wrong place with nothing saying so (the 2026-11-14 run did exactly that). Both settings are comma-separated place fields, and the check compares every field both of them name, so `North Vancouver,Washington,United States` does not pass against a British Columbia market, and `North Vancouver, British Columbia` does not false-fire against `North Vancouver,British Columbia,Canada`. Where `non_profit_location` names only a city, only the city can be compared. A warning rather than an error: measuring a neighbouring market on purpose is legitimate. When `serpapi.location` is absent entirely, `run_feasibility.DEFAULT_LOCATION` is the single fallback, and `serp_audit.py` and `probe_ai_visibility.py` use the same value.
  - Result links are unwrapped before any consumer sees them. Google serves them as `https://www.google.com/goto?url=<opaque>`; `link_recovery.recover_response` replaces each with the destination **host**, recovered from `displayed_link`, a reference's `source_icon` or `source`, or the parent row's host. Because only the host is recoverable, such rows carry `Is_Destination_Page = false` and every page-level figure (`Word_Count`, `Content_Type`, schema/FAQ/author signals, `Page_Authority`) reads `Not Measured`; domain-level figures, including the Domain Authority behind feasibility, are unaffected. `enrichment.max_urls_per_keyword` therefore fetches HTML only for rows whose own URL survived. See docs/methodology.md, "Link recovery".
  - Ranks are absolute across pages. SerpAPI restarts `position` at 1 on each page; `_merge_google_pages` renumbers it to the merged position, keeping the raw value as `page_position`. So any config threshold expressed in ranks (`enrichment.max_urls_per_keyword`, the top-10 filters) counts down the real SERP (finding D-C-01, review of 2026-11-04).
- `files.*` — input/output file paths. `input_csv`, `output_json`, `output_xlsx` and `output_md` are written by `serp_audit.py` at the end of a run that wrote all its outputs (`pipeline_status.finish_run`); a run that is cancelled, or stopped or failed before the audit finishes, leaves them unchanged (a failure in a later `run_pipeline.py` step does not undo them). The launcher does not write them: it passes the keyword file to the run as the `SERP_INPUT_CSV` environment variable, which takes precedence over `files.input_csv`. Output names are always new and timestamped; names already in `config.yml` are never reused.
- `enrichment.max_urls_per_keyword` (default `5`) — how many of each keyword's organic results have their HTML fetched and classified. Since ranks became absolute (D-C-01) this is N pages per keyword; before the fix the same value admitted roughly N rows per fetched page (~14 at three pages). Every domain is still entity-classified whether or not its page is fetched.
- `enrichment.*` — URL enrichment settings (`eeat_scan_chars` — how many leading body-text characters are scanned for author credentials and review markers, default 8000; see seo_geo_deferred G.3)
- `app.*` — API mode flags (`balanced_mode`, `deep_research_mode`)
- `moz.cache_ttl_days` — DA cache lifetime in days (default 30)
- `moz.negative_cache_ttl_days` — how long a cached **absence** stays good
  (default 7). A cache row whose DA is NULL records that the provider was
  asked and holds no figure; that stops being true as soon as the provider
  crawls the domain, so it is re-asked sooner than a measurement is
  refreshed. Clamped to `cache_ttl_days`. Applies to both DA providers.
- `moz.enabled` — master switch for the Moz Data API (`api.moz.com/jsonrpc`); default `true`. Per-method flags gate spend independently (see moz_api_upgrade_spec_v1.md T.0)
- `moz.keyword_metrics.*` — Moz keyword metrics (volume / difficulty / organic CTR / priority), **on by default** (spec gate D-2). `enabled`; `engine` / `locale` / `device` — all three are required by the API and all three change the answer, so all three are part of the cache key (`en-CA` matches the client's market); `max_keywords` — per-run cap (default 50); `rows_per_call` — rows Moz bills per successful fetch (**4**, measured live 2026-08-28, not 1). There is no batch variant for this method, so it is one API call per keyword: 50 keywords is ~200 rows. Runs also stop before exceeding the live remaining quota and log which keywords were skipped
- `moz.brand_authority.enabled` — Moz Brand Authority (0-100) per competitor domain. **Enabled** at the user's instruction (the spec's default was `false`). 1 row per domain. Rides on the competitor fetch, so `moz.competitor.enabled` must also be true. Also fetches the **client's own** score into the handoff's `moz.client` entry (uncached — 1 row per run — so the competitor scores have a reference point). The real method is `data.site.metrics.brand.authority.fetch`; the spec's `...metrics.brand_authority.fetch` does not exist on this API
- `moz.link_momentum.*` — **off by default, and deliberately not what the spec described.** Moz exposes no recently-gained / recently-lost filter and no time window at all on this plan (allowed filters: `external, follow, nofollow, deleted, not_deleted`). What this reports is linking domains **lost at some point** vs **currently live** — named `lost` / `live`, with an explicit `window: none` field, so it cannot be read as 60-day momentum. Costs 2 pages per domain; `limit` (default 10) is the spend control
- `moz.competitor.*` — Moz competitor signals added to the Tool 2 handoff (`data.site.ranking.keyword.list` + `data.site.anchor.text.list`). **Enabled** here at the user's instruction (the spec's default was `false`). `scope` / `locale` are part of the cache key and change the answer — bowencenter.org returns ranking keywords in `en-US` but none in `en-CA`. `max_competitors` (default 3), `ranking_keyword_limit` (50), `anchor_text_limit` (25). `client_anchor_texts` (default **true**) additionally fetches the **client's own** anchor text into the handoff's `moz.client.anchor_texts`; the client is excluded from the competitor list by design, so without it Tool 2's own-site spam check has no data and negative SEO aimed at the client is invisible. Costs one extra anchor page. **1 row per object returned.** The limits are sent as the API's own page controls (`page.limit` for ranking keywords, `offset.limit` for anchor text) so they genuinely reduce the bill — a bare `limit` is ignored and would return, and charge for, a full page regardless. Neither method is paginated to exhaustion; the result declares `truncated: true` when a full page came back
- `moz.search_intent.*` — Moz search-intent scores, used to **cross-check** the repo's own `intent_mapping.yml` classifier and never to replace it. **OFF by default**: it is a second opinion on a call the repo already makes. 1 row per keyword (measured live 2026-08-28, unlike `keyword_metrics` at 4). `repo_to_moz_intent` is **editorial**: Moz has four intent labels while this repo also emits `commercial_investigation`, `local` and `uncategorised`, so a repo verdict is mapped onto Moz's vocabulary before the two are compared. A `null` entry means "not comparable", which is reported as such rather than as a disagreement
- `moz.site_metrics.scope` — Moz site-query scope: `domain`, `subdomain`, `subfolder` or `url` (default `url`, which reproduces the page-level Page Authority the legacy endpoint returned)
- `moz.site_metrics.batch_size` — targets per `data.site.metrics.fetch.multiple` request (default 50)
- `moz.site_metrics.link_count_fields` — **editorial**: which of Moz's link-count fields are kept on each result and cached. Every kept field costs nothing extra (they arrive in the same response); the list controls what downstream code and the cache see
- `moz.rows_per_month` — the account's monthly data-row allowance, read from the live `quota.lookup` rather than hardcoded from the plan tier (3,000 on the Starter Medium plan, probed 2026-08-27). The API reports `allotted` and `used`; rows remaining is derived from the two by `moz_jsonrpc.parse_quota`
- `feasibility.*` — DA gap thresholds, client DA, neighbourhoods, pivot settings
- `audit_targets.n` — top-N organic URLs per keyword exported to competitor handoff (default 10)
- `audit_targets.omit_from_audit` — domains excluded from the handoff (never sent to Tool 2)
- `client.preferred_intents` — intents the client can produce content for; drives `mixed_intent_strategy`
- `analysis_report.*` — client context injected into LLM prompts
- `report_llm.*` — which LLM writes the Content Opportunity report and the advisory briefing (`report_llm.py`, `brief_llm.py`). `provider` is an entry name in the shared key file `~/.config/llm/keys.json`; empty means the key file's `apps` map for `serp-discover`, then its default provider. `main_model` / `advisory_model` are that provider's model IDs (an empty `advisory_model` uses `main_model`; `--llm-model` / `--advisory-model` override both). `timeout_seconds` (default `600`) is the limit for one call; zero or a non-number falls back to the default. `main_max_tokens` (default `16000`) and `advisory_max_tokens` (default `4000`) are the output-token limits; a model that reasons before answering spends part of the limit on reasoning (Hydrogen needed about 19,000 and 10,000 tokens on a 9-keyword run, so `config.yml` sets `64000` and `16000`), and an answer that hits the limit fails the run. `--llm-max-tokens` overrides the main limit. `model_include` (ID prefixes) and `model_exclude` (substrings) decide which of the provider's live models the launcher dropdowns offer. A provider that cannot be loaded, or a call that fails, stops the step; there is no fallback to another provider. `brand_mentions.llm_model` and `sentiment.llm_model` are sent to this same provider
- `report_thresholds.entity_dominance.*` — thresholds for interpreting SERP entity type dominance in reports (see RC.6)
- `geo.outreach_entity_types` — entity types treated as brand-placement (outreach) surfaces in the AI Overview citation analysis, as opposed to competitor counselling sites (see seo_geo_review T.3)
- `situational_probes.*` — "S"-label conversational query probes (see seo_geo_deferred T.5). **Paid feature, off by default.** `enabled` (default `false`; Deep Research mode turns it on, Low API mode always turns it off), `max_probes_per_run` (default 6 — the hard per-run SerpAPI call cap, decision gate D-1), `probes_per_keyword` (default 2), `keywords` (`priority` = probe in strategic_flags order from the last analysis JSON; `all` = keyword CSV order). Probe query templates are editorial and live in `serp_vocab.yml situational_templates`.
- `ai_visibility.*` — AI-engine mention probing (`probe_ai_visibility.py`; see seo_geo_deferred G.1, decision gate D-2). **Paid feature, cost-guarded:** the script makes zero API calls unless run with `--yes` or `assume_yes: true`. Keys: `engines` (default `[gemini, openai, perplexity]` per gate Y-D9 — which assistants to probe; Claude is available-but-not-default and can be added; `--engines` overrides per run. Valid engines: `claude`, `gemini`, `openai`, `perplexity`), `claude_model` / `gemini_model` / `openai_model` / `perplexity_model` (model ids — never hardcoded in Python; `openai_model` default `gpt-4o`, `perplexity_model` default `sonar`), `claude_web_search_tool` (Anthropic web-search tool type matching the chosen Claude model), `openai_endpoint` (default `https://api.openai.com/v1/responses` — the web-search-enabled Responses API) and `openai_web_search_tool` (default `web_search`), `perplexity_endpoint` (default `https://api.perplexity.ai/chat/completions` — the OpenAI-compatible Sonar endpoint that returns citations), `max_questions` (default 20 — cap **per engine**; total calls = questions × engines), `max_total_calls` (default 60 — **hard ceiling on total paid calls across questions × engines**, decision gate Y-D4; the cost guard prints `questions × engines` and this ceiling, and when the plan exceeds it the question set is truncated so the ceiling is never breached — and no calls are made at all unless `--yes`/`assume_yes`), `client_slug` (default `living_systems` — which block in `client_profiles.yml` seeds the highest-priority profile questions per Y.5; a missing slug/profile skips profile questions and the probe falls back to keyword-derived questions), `assume_yes` (default `false`), `history_runs` (default 5 — how many prior runs the trend table shows), `geo_context` (sentence prefixed to every question so answers are location-realistic). Each optional engine is key-gated and skipped-with-warning (never an abort) when its key is absent: Gemini needs `GEMINI_API_KEY`, OpenAI/ChatGPT needs `OPENAI_API_KEY` (Y.2), Perplexity needs `PERPLEXITY_API_KEY` (Y.3). **Tier note (Y.2/Y.3):** the OpenAI web-search citations and Perplexity Sonar citations are confirmed against the vendors' 2026-07 live docs (OpenAI `url_citation` annotations + `web_search_call` sources on the Responses API; Perplexity top-level `search_results`/`citations`), but citation availability can vary by account tier/model — endpoints, tool names, and model ids are all config-parameterised so no code change is needed to track the current surface, and a run on a tier that returns no citations still measures `mentioned` correctly (citation-based `cited` simply reads as absent, never faked).
  - **`ai_visibility_probes` SQLite columns (Y.5):** each probe row now records `persona` (the client-profile persona that seeded the question, `NULL` for keyword-derived rows) and `source` (`profile` | `situational` | `paa` | `template` — which precedence tier produced the question). These columns are added by an idempotent `ALTER TABLE … ADD COLUMN` migration (storage.py convention); a database created before Y.5 is upgraded once on next use and its old rows read back as `NULL` (never fabricated values).
- `aivi.*` — **AI Visibility Index composite (Y.6).** `aivi.weights` sets the weighting across the four normalised axes (`mentions`, `ranking`, `citations`, `sentiment`; default equal `0.25` each per decision gate Y-D6). Weights are normalised to sum to 1; a missing block, a non-numeric weight, or weights summing to zero all fall back to equal 25% each **with a logged warning** (never a hardcoded score). The composite is computed by Python (design principle 1), persisted per engine to the `ai_visibility_index` SQLite table (`run_ts, engine, aivi, mentions_axis, ranking_axis, citations_axis, sentiment_axis, weights_json`; UTC `run_ts`, idempotent, trendable), and reported as a headline AIVI per engine + an all-engine average + prior-run delta. An **unmeasured axis** (e.g. sentiment when `sentiment.enabled: false`) is shown `n/a` and **excluded** from the weighted mean (weights renormalise over the present axes) — it is never counted as 0 (principle 3).
- `brand_mentions.*` — **competitor mention leaderboard (Y.7).** `llm_extraction` (default `false`, decision gate Y-D7) gates the optional LLM pass that fills unknown brands; the **deterministic gazetteer pass** (from `known_brands` + the top competitor names harvested from the latest `market_analysis_*.json`) always runs, so a leaderboard is produced even with the LLM off. `llm_model` is the model id for the gated pass (never hardcoded). When the LLM surfaces brands not already in `known_brands`, they are written to `brand_mentions_candidates_<topic>_<ts>.md` (a candidate-review file, pattern of `domain_override_candidates.md`) for the user to **promote into `known_brands`** — no silent taxonomy growth. Python computes every mention count and the client's rank; the LLM only contributes labels (Y-D7). Persisted per engine to the `brand_mentions` SQLite table (`run_ts, engine, brand, mention_count, questions_total, is_client, source` where `source ∈ gazetteer|llm`; UTC ts, idempotent, trendable).
- `known_brands` — **editorial** list of competitor brand names and/or domains. Seeds the Y.7 gazetteer (name matching in answer text) and the Y.8 citation brand attribution (domain entries map a cited domain to a brand). **Promotion path:** review `brand_mentions_candidates_*.md` after an LLM-extraction run and add real competitors here so future runs count them deterministically.
- `sentiment.*` — **per-brand sentiment (Y.9).** `enabled` (default `false`, decision gate Y-D8): OFF by default — a disabled run makes **zero** sentiment calls, the report reads "sentiment not measured", and AIVI excludes the Sentiment axis (principle 3). When enabled, one LLM classification runs per answer that mentions the client or top competitor (subject to `ai_visibility.max_total_calls`), returning a polarity label + verbatim positive/negative aspect phrases stored as a **measured input**; Python computes `% positive` (Y-D7). `llm_model` is the model id (never hardcoded). Persisted to the `answer_sentiment` SQLite table (`run_ts, engine, brand, polarity, positive_aspects_json, negative_aspects_json, answer_excerpt`).
  - **`ai_citations` SQLite table (Y.8):** every source URL each engine returned, recorded once with a `cite_count` (identical URLs de-duplicated; **tracking params retained verbatim**, e.g. `?utm_source=openai`, since they identify the surfacing engine), a `domain`, a `category` **sourced from the existing content/entity classifier** (`classifiers.py` + `classification_rules.json` + `domain_overrides.yml` — not a parallel list; the `publisher` category was added to those editorial files), an attributed `brand` (gazetteer/domain match; `NULL` when unknown), and an `is_client` flag. Feeds AIVI's Citations axis and the "top cited domains for this topic" outreach shortlist. UTC ts, per engine, idempotent.
- `foundational.*` — **foundational (transferable) GEO readiness score (Y.12).** `foundational.weights` sets the weighting across the three sub-scores (`accessibility`, `structure`, `authority`; default equal thirds). Weights normalise to sum 1; a missing block, non-numeric/negative weight, or zero sum falls back to equal thirds **with a logged warning**. The score is engine-agnostic by construction and computed by Python from **existing** data only (no new external calls): accessibility from `keyword_profiles[*].extractability`, structure from `keyword_profiles[*].schema_signals` coverage vs `schema_recommendations.yml`, authority from the Y.7 brand-mention leaderboard. A sub-score whose inputs are entirely absent is `n/a` and **excluded** from the weighted mean (renormalised) — never counted as 0 (principle 3). Each sub-score surfaces its top 2–3 concrete gaps **from existing sources** (`strategic_flags.geo_alerts` details, `schema_recommendations.yml` labels, rival leaderboard brands) — no new gap strings are invented. Persisted to the `foundational_score` SQLite table (`run_ts, score, accessibility, structure, authority, weights_json`; UTC ts, idempotent, trendable) and reported **first**, ahead of per-engine AIVI, as the cross-platform priority.
- `engine_prioritization.*` — **platform-prioritisation blend (Y.10).** `engine_prioritization.weights` sets the blend across three normalised 0–1 signals (`opportunity` = low-AIVI opportunity, `reach` = engine reach tier, `referral` = referral-click tier; defaults `0.5 / 0.3 / 0.2`). Weights normalise to sum 1; malformed/missing/zero-sum falls back to the defaults with a warning. `engine_recommendations.py` ranks the **enabled** engines by this blend; the ranking is **indicative guidance, not a fixed ranking** — prioritisation is audience-dependent (a Google-organic audience favours Google AI surfaces first). The reach/referral tiers and every per-engine "what to change here" move come from the editorial `engine_profiles.yml`, joined deterministically (no LLM, nothing hardcoded in Python).
  - **`engine_transfer` SQLite table (Y.11):** per-run cross-engine transfer metrics computed from ≥2 enabled engines (`run_ts, engine_count, mentioned_count, cited_count, avg_jaccard, cited_by_all, cited_by_exactly_one, rank_spread, detail_json`; UTC ts, idempotent, trendable). Overlap is the pairwise Jaccard of cited-domain sets per engine (from Y.8) plus counts of domains cited by all vs exactly one engine. A **single-engine run** records the run with everything but `engine_count` NULL and reports "transfer not measurable (single engine)".
- `launcher.*` — how the GUI launcher (`serp-me.py`) controls the scripts it starts. `stop_grace_seconds` (default `5`): after Stop, how long the run is given to end before it is forced. `max_run_minutes` (default `0` = no limit): a run lasting longer is ended and labelled `TIMED OUT`; leave at 0 unless you know how long your longest mode takes, because a cap that is too low ends a paid run part-way. `regenerate_timeout_seconds` (default `300`): limit on the automatic report regeneration after a feasibility run. `process_check_timeout_seconds` (default `5`): limit on the check for an already-running pipeline. Bad values fall back to these defaults.
- `bing_check.*` — Bing secondary-index visibility check (see seo_geo_deferred G.5). **Paid feature, off by default** (decision gate D-4): `enabled` (default `false`), `num` (default 20 — Bing results requested per keyword). When enabled, one SerpAPI `engine=bing` call per root keyword records the client's Bing rank next to its Google rank (ChatGPT search grounds substantially on Bing).
- `gsc.*` — Google Search Console integration (`run_gsc_analysis.py`; see seo_geo_deferred G.4, decision gate D-3). Free first-party data, but `enabled` defaults to `false` until the service-account grant is in place (`GSC_CREDENTIALS_PATH` env var + the service-account email added to the Search Console property — setup steps in `docs/USER_MANUAL.md`). Keys: `property` (default `sc-domain:livingsystems.ca`), `lookback_days` (default 90 — the Search Analytics window), `cache_ttl_days` (default 7 — SQLite `gsc_cache` lifetime), `feed_strategic_flags` (default `false` — when true, the content brief attaches the latest `gsc_analysis_*` sidecar to the LLM payload as `gsc_summary`; the prompt treats those numbers as client-private).

**`domain_overrides.yml`** — manual entity type overrides (e.g., `psychologytoday.com: directory`).

**`intent_mapping.yml`** (spec v2) — rule table mapping `(content_type, entity_type, local_pack, domain_role)` → SERP intent (informational / commercial_investigation / transactional / navigational / local / uncategorised). First-match-wins, top of file = highest priority. Edit this file to refine intent assignments — don't push exceptions into Python.

**`url_pattern_rules.yml`** — URL-path fallback rules for pages the HTML enricher couldn't classify. Edit to improve classification rates without touching Python.

**`serp_vocab.yml`** — editorial SERP-audit vocabulary: n-gram stop words, PAA category triggers (Commercial/Distress/Reactivity), service-like tokens, the AI-alternative query templates, the `situational_templates` section (situation-style probe query templates — keep each 6+ words; see seo_geo_deferred T.5). As of yoast_geo_upgrade Y.4 this section is a **persona-keyed map** `{persona_label: [templates...]}` (the original flat list is preserved verbatim under `therapy_seeker`, with `clinician_trainee` and `referrer` blocks added). When a client profile (Y.1) is present only that profile's declared personas expand; with no profile all persona blocks expand (backward-compatible). Placeholders: `{base}`/`{topic}`/`{city}` plus the optional `{service}` (client `service_description`, omitted cleanly when absent). Flattened for consumers via `query_variants.flatten_situational_templates`), the `fetch_status` section (review chunk D2c: the words a row's `Fetch_Status` can carry — `enriched`, `blocked` (takes `{status}`), `unreachable`, `not_attempted`, `not_destination_page`, `no_url`, `enrichment_disabled` — plus `blocked_warning`, the "N of M pages were not read" line written to Parsing_Warnings; the ONLY home for these words. The machine-readable state lives beside them in the row's `Fetch_State` column, which is what consumers filter on, so re-wording a status here never changes a count), and the `eeat_signals` section (E-E-A-T author-signal vocab: `credential_tokens` — professional designations like RCC/MSW/"registered clinical counsellor" that mark a byline as credentialed, and `review_markers` — "medically reviewed"-style phrases; see seo_geo_deferred G.3). Note: the shared config's `stop_words` (out-of-repo, see "Shared config" below) still overrides the stop-word list when present.

**`strategic_patterns.yml`** — Bowen theory strategic pattern definitions. Each entry has `Pattern_Name`, `Triggers` (list), `Status_Quo_Message`, `Bowen_Bridge_Reframe`, and `Content_Angle`. A pattern fires when any trigger word appears as a whole word in the run's SERP ngram corpus. Add new patterns by appending entries; no Python changes required.

**`play_routing.yml`** (seo_geo_review chip A) — the "Recommended Play" decision table. `play_routing.py` normalises each keyword's pre-computed signals into primitives; this file makes the call among five plays. First-match-wins, top of file = highest priority. Two top-level keys:

- `plays`: map of play-id → `{label, strategy_text, success_metric}`. The five plays are `rank_play` (High/Moderate feasibility → win by ranking), `extraction_play` (Low/unknown feasibility + informational/commercial or mixed intent + AI Overview → win by AIO citation), `reformat_play` (client already ranks top-10 but is not AIO-cited → reformat the existing page first), `local_pivot_play` (Low/unknown feasibility + service-like keyword + local/transactional intent → hyper-local pivot), and `deprioritize` (none of the above). `strategy_text` is a one-line string the report/LLM may quote. `success_metric` (added by the chip C consumer) is the metric the brief's Section 7 uses for that play (rank → ranking, extraction/reformat → AIO citation). Every play a rule references must be defined here.
- `rules`: ordered list of `{play, match}`. A rule matches when **every** key in its `match` block matches the keyword's normalised signal; any signal not named is treated as `any`. A match value may be a scalar, a list (signal ∈ list), or `any`. Matchable signals: `feasibility` (high/moderate/low/unknown), `primary_intent` (informational/commercial_investigation/transactional/navigational/local/mixed/unknown), `is_mixed`, `mixed_intent_strategy`, `has_ai_overview`, `client_ranks_but_not_cited` (the per-keyword source of `strategic_flags.geo_alerts`), `is_service_like` (keyword contains a `serp_vocab.yml` `service_like_tokens` entry), `has_local_pack`.

Rule ordering is load-bearing: `reformat_play` must precede `extraction_play`, and `local_pivot_play` rules must always require `is_service_like: true`. `feasibility: unknown` is grouped with `low` for the Low-feasibility plays so a keyword whose DA data could not be fetched still routes on intent + AIO rather than being silently dropped — the resulting verdict carries an honesty note (`recommended_play.confidence` / `data_available` / `note`). Edit the table to refine routing — don't push exceptions into `play_routing.py`. A malformed file fails loudly (`ValueError`).

**Consumers (chip C):** the report renderers (`play_rendering.py` → feasibility_*.md / market_analysis_*.md) and the brief validator (`brief_validation.py`) read `plays` for labels and success metrics. The brief may only NARRATE the pre-computed play; parity is enforced by anchoring on the canonical `Recommended play: <label>` verdict statement (not loose prose), and a mismatch is a hard validation failure. A missing/broken file degrades the renderers gracefully (play columns show `—`).

**`client_profiles.yml`** (yoast_geo_upgrade Y.1) — per-client profiles for persona-segmented AI-visibility question generation. Keyed by **client slug** (e.g. `living_systems`) — one block per client, distinct from the **topic slug** that names output files (e.g. `leila` from `keywords_leila.csv`). One client profile serves all of that client's topics/keyword sets; output naming is unchanged. `profile_questions.load_client_profiles()` reads it; a missing or malformed file warns and returns `{}` (profile questions skipped, never a crash). The GUI "Client Profile & Queries" tab (Y.13) is the editor. Per-client fields:

- `brand_name` — the client's brand, probed verbatim in questions.
- `domain` — the client's website domain.
- `location` — human-readable region (free text).
- `primary_city` — the city local tiers expand for first.
- `secondary_cities` — additional cities local tiers expand across (optional list; empty degrades gracefully to primary-city-only).
- `service_description` — one paragraph; fills the optional `{service}` placeholder in templates.
- `personas` — list of audience personas. Each persona has: `label` (tagged on every generated question), `needs` (short phrase), optional `intent` hint, `seed_questions` (LITERAL questions probed **verbatim** — no templating, no city suffixing; a `{city}` inside a seed stays literal), `templates` (patterns expanded per city; **only** `templates` expand), and optional `intents` — a map of named funnel/intent **tiers**, each itself carrying `seed_questions` and/or `templates` plus an optional `local` flag. The tier list is **open and per-client**. A tier flagged `local: true` (booking-intent, e.g. `local_transactional`) expands its templates across `[primary_city] + secondary_cities` **plus** a "near me" variant **plus** a de-localised copy (reusing `query_variants.delocalise_keyword`); non-local tiers (e.g. `informational`) are probed as-is and never city-suffixed. Placeholders in templates: `{city}` and the optional `{service}`.

Generation is deterministic (templates ordered, no randomness), pure, and makes no network/LLM call — it is template filling, so a no-cost preview of the exact questions is available in Settings before any paid run.

**`glossary.yml`** (report_content_direction CD.4) — plain-English definitions for
every term of art the market report uses. Fields per entry: `term` (the glossary
heading), `aliases` (other spellings that count as a use of the term; defaults to
`[term]`, matched case-insensitively on whole words), `definition` (required), and
optional `guard` (default true — whether the CD.5 jargon guard fails the build when
this term appears in the report undefined). `generate_insight_report.py` renders
`## A. Glossary` with only the terms that run's report body actually used. A missing
or malformed file drops the glossary and warns; it never aborts the report.

**`report_writing_directives.yml`** (report_content_direction CD.1/CD.2) — two blocks:

- `directives` — the "**When you write:**" line rendered under each analytical
  report section. Keys: `section_1b`, `section_2`, `section_3`, `section_4`,
  `section_5`, `section_5b`, `section_5c`, `section_5d`, `section_5e`. A key with no
  matching section fails `test_cd2_1b_all_yaml_directives_are_reachable`, so editorial
  text cannot sit in the file unreachable by any reader (P25).
- `page_types` — page-type labels for the §1 content plan, keyed by play id
  (`rank_play`, `extraction_play`, `reformat_play`, `local_pivot_play`,
  `deprioritize`, `unknown`). Each has a `default` label and an optional `local`
  variant used when the search shows a map pack or local intent.

A missing or malformed file renders the report without directives rather than
raising.

### `config.yml` — `report` block (optional)

| Key | Default | Meaning |
|---|---|---|
| `report.da_gap_noise_floor` | `2.0` | Domain Authority points below which the §1 content plan calls a gap "effectively level" instead of naming a stronger side. DA is a 0–100 third-party estimate, so a gap of a point or two is noise; without this floor a 0.6-point gap would be reported as "they are stronger than you" directly under a "High Feasibility" status. |
| `report.phrase_min_count` | `2` | How many times a phrase must appear before report §3 calls it recurring. Below this it is not listed, and §3 says so. |
| `report.phrase_limit` | `10` | Maximum phrases listed in report §3. |

All three degrade with a warning if set to something that is not a non-negative number — a typo here must never abort a run, since `serp_audit` imports the report module at start-up.

---

## Shared config (`shared_config.json`, out-of-repo)

*Spec: seo_geo_deferred_spec_v1.md#C.9.*

One optional JSON file shared with Tool 2 (the competitor audit tool) so both tools agree on client identity, stop words, and feasibility thresholds. It lives **outside this repo** — by default one directory above it (`../shared_config.json`). The env var **`SERP_SHARED_CONFIG`** overrides that path (absolute path to the file). All loading goes through `shared_config.py` (`load_shared_config()`); a malformed file logs one warning naming the file and falls back to in-repo defaults; an absent file is logged at INFO and is not an error.

**Schema (all keys optional):**

```json
{
  "stop_words": ["the", "and", "..."],
  "client": {
    "da": 30,
    "domain": "livingsystems.ca",
    "location": "North Vancouver"
  },
  "technical": {
    "feasibility_threshold": 5,
    "moderate_feasibility_max_gap": 15,
    "score_normaliser": 30.0,
    "min_da_for_verdict": 5
  },
  "filtering": {
    "omitted_domains_path": "omitted_domains.txt"
  }
}
```

| Key | Consumed by | Overrides |
|-----|-------------|-----------|
| `stop_words` | `serp_audit.py` n-gram corpus | `serp_vocab.yml stop_words` |
| `client.da` | feasibility scoring — a **fallback**, not the default: the client's own DA is looked up through the active provider first (see below) | `config.yml feasibility.client_da` |
| `client.domain` | client visibility detection | `config.yml analysis_report.client_domain` |
| `client.location` | hyper-local pivot text | `config.yml feasibility.non_profit_location` |
| `technical.feasibility_threshold` | `feasibility.py` High/Moderate cut | code default 5 |
| `technical.moderate_feasibility_max_gap` | `feasibility.py` Moderate/Low cut | code default 15 |
| `technical.score_normaliser` | `feasibility.py` score scaling | code default 30.0 |
| `technical.min_da_for_verdict` | `feasibility.py` — how many of the top-10 positions must carry a DA figure before a gap is published as a verdict. Below it the row reads `Not Measured`; the mean and the gap are still reported, with their coverage | code default 5 |
| `filtering.omitted_domains_path` | domain exclusion list (path relative to the shared config's directory) | code default `omitted_domains.txt` |

**Precedence:** shared config > `config.yml` > `serp_vocab.yml` defaults (stop words) / code defaults (thresholds). Do not remove the file's authority — Tool 2 reads the same file (decision gate D-5).

### The client's own DA is measured, not configured (review chunk D2, D-M-05)

`feasibility.client_da` / `client.da` is the **last** resort, because the two
DA providers' numbers are not interchangeable: DataForSEO's backlink rank and
Moz's Domain Authority are both 0–100 and are different vendors' models (this
client scores 19 on DataForSEO against the 35 in `config.yml`). The client's
domain is fetched in the same batch as its competitors and resolved in this
order:

1. `--client-da` on `run_feasibility.py` — an explicit operator override.
2. The active provider's live figure. The run logs the value, the provider and
   the date, and says it is not using the config value.
3. The config value, labelled on every row as
   `client_da_source: "config fallback (unmeasured, <provider>)"` and rendered
   as `35 (config, not measured by moz)`.

With no provider reachable the client DA is `None`, every keyword reads "Not
measured", and nothing is scored against the constant.

### `feasibility_messages.yml` — the feasibility vocabulary (editorial)

Status labels and icons, the per-keyword "why there is no verdict" sentences,
and the coverage phrases printed beside every mean. Four Python copies of the
status map are how one unmeasured state came to carry two labels in different
outputs; there is now one label per status, and `"No DA Data"` is retired.
Read by `feasibility.load_messages()`; a missing or malformed file degrades to
the bare status string and never aborts a report.

| Block | What it sets |
|-------|--------------|
| `statuses` | `icon` (bare glyph, console) + `label` (glyph + words, reports) per status. Keys must match the statuses `feasibility.py` returns — a test asserts they do, and a rename must not begin with "high", "moderate" or "low" or the play router will read it as a measured verdict |
| `no_measurement` | `no_provider` / `nothing_in_window` / `below_minimum`, with `{provider}` `{measured}` `{window}` `{minimum}` placeholders |
| `coverage` | the sentence form: "mean of 7 of 10 ranking domains (3 unscored)" |
| `coverage_short` | the same fact for the reports' `DA Coverage` column: "7/10 (3 unscored)" |
| `client_da` | how a `Client DA` cell states its own provenance |

Not editorial, and so still in `feasibility.py`: `MIN_DA_FOR_VERDICT` (5), the
number of measured ranking domains a verdict requires.

### `gsc_messages.yml` — the Search Console fetch-outcome vocabulary (editorial)

The words a reader sees for each GSC fetch outcome. A query Search Console
answered "no rows for this" and a query the fetch never reached are different
facts — one is about the client, one is about the fetch — and before review
chunk D2b they shared one label ("no GSC data") because the wording was Python
literals in three places. Read by `gsc_client.load_messages()`; a missing or
malformed file degrades to the bare status key and never aborts a report.

| Block | What it sets |
|-------|--------------|
| `statuses` | per status (`measured` / `measured_absent` / `not_reached`): `label`, `cell` (the per-query table cell) and `coverage` (the phrase beside a count). Keys must match the `gsc_client.STATUS_*` constants — a test asserts every state has all three |
| `lines` | the report and log sentences: `coverage_measured_absent`, `coverage_not_reached`, `fetch_complete`, `fetch_incomplete`, `partial_warning`, `band_short_of_rows`. `{...}` placeholders are filled by `run_gsc_analysis`; an unknown placeholder falls back to the built-in wording rather than raising |

### `ai_visibility.generic_source_stoplist` / `ai_visibility.negative_terms` (editorial)

Two word lists in `config.yml`, added by review chunk D3b (finding D-M-14).

| Key | What it does |
|-----|--------------|
| `ai_visibility.generic_source_stoplist` | harvested competitor `Source` labels that are ordinary words, not brands. The Y.7 gazetteer harvests brand names from the market-analysis JSON, and a bare generic token matched plain answer text — "Indeed" matched "Indeed, there are many options" and took a leaderboard rank beside a real practice. A harvested name is otherwise kept only when it has two or more tokens, or is a single token matching its own row's domain. `known_brands` is editorial and is never filtered |
| `ai_visibility.negative_terms` | phrases that contain a `client_name_pattern` but are not a mention of the client. Broad substring match, applied before the word-boundary pattern test. "Living Systems" is also the name of an academic subject this client teaches about, so an answer explaining living systems theory counted as the AI naming the practice. Mirrors `gsc_demand.negative_terms`, which does the same for Search Console queries |

---

### `ai_visibility_messages.yml` — the "not measured" vocabulary (editorial)

The words a reader sees when an AI answer engine produced no measurement. An
engine that was never asked (no API key), an engine whose every call failed
(rate-limited), and two engines that cited nothing are three different facts,
and none of them is a zero or a finding about the client. Added by review
chunk D3a (cold-review finding F4), because "we have no measurement" was being
rendered four different ways across `probe_ai_visibility.py`,
`engine_transfer.py` and `engine_recommendations.py` — the same drift
`feasibility_messages.yml` and `gsc_messages.yml` already exist to stop. Read
by `ai_visibility_messages.load_messages()`; a missing or malformed file
degrades to the built-in wording and never aborts a report.

| Block | What it sets |
|-------|--------------|
| `statuses` | per state (`answered` / `failed` / `not_measured` / `not_comparable`): `label`, `cell` (the table cell, e.g. the mention-rate cell for an engine with no answers) and `coverage` (the phrase beside a count). `answered` / `failed` must match the `probe_ai_visibility.STATUS_*` constants |
| `lines` | the report sentences: the `reason_*` short forms stored on each `engines_unmeasured` entry (`reason_skipped`, `reason_all_failed`, `reason_no_questions`, `reason_no_aivi`, `reason_no_profile`), the per-engine table note (`engine_note`, `engine_not_measured`), the AIVI headline and its coverage (`aivi_average`, `aivi_not_measured`), the leaderboard and citation not-measured blocks, the prioritisation's not-ranked note, and the transfer section's two distinct cases (`transfer_single_enabled` — a config change is needed — versus `transfer_single_measured` — a re-run is needed) plus the two Jaccard not-comparable phrases |
| `lines` (sentiment) | the three sentiment states, added by the D3b cold review: `sentiment_budget_exhausted` (the call budget ran out before any answer naming this brand was classified — a re-run with a larger `max_total_calls`, not an absence of mentions), `sentiment_all_failed`, `sentiment_not_portrayed`, and `sentiment_skipped_note`, the clause appended to a coverage phrase when some answers were never classified |
| `lines` (foundational) | `foundational_structure_no_client_page` and `foundational_structure_no_recs` — the two reasons the structure sub-score reads `n/a`, printed beneath the sub-score table via `foundational_subscore_reason`; and `foundational_delta_definition_changed`, printed instead of a Δ when the prior run's structure value was computed under an earlier `foundational_score.DEFINITION_VERSION` |

---

## Configuration Manager GUI

**How to access:** Click "Edit Configuration" button in `serp-me.py` launcher.

The Configuration Manager allows you to edit all 9 configuration files in a GUI without opening a text editor:

| Tab | File | What You Can Do |
|-----|------|-----------------|
| Intent Mapping | `intent_mapping.yml` | View/edit/add/delete/reorder SERP intent rules (first-match-wins). Double-click to edit rule details. |
| Strategic Patterns | `strategic_patterns.yml` | View/edit/add/delete pattern definitions (name, triggers, reframes, content angles). |
| Brief Pattern Routing | `brief_pattern_routing.yml` | View/edit/add/delete pattern routing (PAA themes, categories, keyword hints per pattern). |
| Intent Classifier Triggers | `intent_classifier_triggers.yml` | View/edit/add/delete medical and systemic trigger lists for intent classification. |
| Config Settings | `config.yml` | Edit operational settings (file paths, thresholds, client preferences). API keys live in `.env`, not here. |
| Domain Overrides | `domain_overrides.yml` | View/edit/add/delete domain → entity-type manual overrides. |
| Classification Rules | `classification_rules.json` | View/edit entity-type list and entity-type descriptions. Double-click descriptions to edit. |
| URL Pattern Rules | `url_pattern_rules.yml` | View/edit/add/delete URL fallback patterns (regex → content type). |
| Client Profile & Queries | `client_profiles.yml` | Edit the **selected client's** profile (brand, domain, location, cities) and its personas with named funnel/intent tiers (verbatim `seed_questions` + per-city `templates`). **Preview generated questions** runs `profile_questions.generate` with persona/tier/city tags — no API calls. Save is atomic, validated (round-trips through the Y.1 loader; rejects empty persona labels / bad tiers inline), and never disturbs other clients' blocks. (yoast_geo_upgrade Y.13) |

**Saving:**
- **Only changed files are written.** "Save All" writes the tabs you edited and reports "Saved N of 9". Pressing it with no edits writes nothing.
- **Nothing is written unless everything can be.** Each changed file is validated first; if one is invalid, no file is written and the errors are listed. Each file is replaced atomically. There is no backup copy — use git to recover an earlier version.
- **Keys the tab does not show are kept.** A save applies your edits to the file as it was loaded, so entries with no field in the GUI (for example `known_brands` in `config.yml`, or `rationale` on an intent rule) are left as they were.
- **A file that could not be read is never overwritten.** If a file has a syntax error when the manager opens, its tab shows a red notice and is skipped on save. Fix the file in a text editor, then press "Discard Changes" to reload.
- **A file changed by something else is not overwritten.** If the launcher or a pipeline run wrote a file after the manager loaded it, saving that file is refused; press "Discard Changes" to reload and redo the edit.
- **A field that does not parse is an error.** A typo in a number or list field in Config Settings is reported by name instead of being saved as `0` or an empty list.
- **Closing:** the Close button and the window's close box both ask about unsaved changes. If "save before closing" fails, the window stays open with your edits.

**Other features:**
- **Help on every field:** Click `?` next to a field for what it means and why it matters.
- **CRUD operations:** Add, edit, delete, and reorder (for order-sensitive files like intent_mapping.yml).
- **Discard Changes:** reloads every tab from disk.

For detailed help, see `docs/config_manager_phase5_completion_20260502.md`.
