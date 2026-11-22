# Configuration reference — config.yml keys and rule files

**`config.yml`** — all operational settings:
- `serpapi.*` — API params (engine, location, pagination, retries, modes)
  - `serpapi.timeout_seconds` (default `60`) — how long one SerpAPI call may take before it is abandoned and retried (`retry_max_attempts`). Used by `serp_audit.py` and by the pivot fetches in `run_feasibility.py`. A missing, zero or non-numeric value falls back to 60 with a warning; there is no way to switch the timeout off. Without it the client library waits 16.7 hours.
  - `serpapi.retry_max_attempts` (default `3`) / `serpapi.retry_backoff_seconds` (default `1.0`) — the SerpAPI loop's own retry budget: the total number of tries for one SERP fetch, and the base delay before the first retry, which doubles with each attempt (plus up to 0.2s of jitter). **Read and validated by `http_retry` alongside the `http_retry` block** (review chunk Y7), so a value that is not a number, a boolean, or a value of zero or less is reported and the documented default used — until Y7 these two were read at `serp_audit` import with a bare `int()` / `float()`, so junk aborted the run with a traceback before anything was fetched and a negative backoff reached `time.sleep` after the first paid call, while the three keys beside them warned and carried on (P4/P32). The budget is deliberately one attempt longer than `http_retry.attempts`: a SERP fetch is a paid call against a single vendor and the run cannot continue without it, while a DA lookup has a second provider behind it. `serp_audit` reads it at call time through `http_retry.serpapi_retry_attempts()` / `serpapi_retry_backoff()`, never as a module constant bound at import, so a config applied after import reaches the fetch loop.
  - `serpapi.resume_max_age_hours` (default `24`) — how long the stored SerpAPI responses of an unfinished run may be reused by a resumed run (`serp_checkpoint.py`). `0` means never reuse. A negative or non-numeric value falls back to 24 with a warning.
  - `serpapi.google_max_pages` (default `3`) / `serpapi.num` / `serpapi.google_max_results` — pagination ceilings. Google serves roughly 10 organic rows per page whatever `num` asks for, so three pages reach about the **top 30**, not the top 300: `num: 100` and `google_max_results: 300` are never the binding limit, `google_max_pages` is. Raise `google_max_pages` to go deeper, and expect one SerpAPI call per page per keyword. `serpapi.num` has a second job: it is how a run written before `Results_Requested` existed judges whether its `Total_Results` figure is Google's index estimate or merely the size of the page it asked for. Runs from 2026-11-19 record their own request and do not depend on it.
  - `serpapi.location` — the market Google is asked about. Use SerpAPI's own `canonical_name` for the place (`https://serpapi.com/locations.json?q=<city>`), e.g. `North Vancouver,British Columbia,Canada`. It must name the same place as `feasibility.non_profit_location`, which is the market the feasibility verdicts and neighbourhood pivots assume; `config_validators.validate_config_yml` warns when the two disagree, because a run that searches one city and scores another produces a competitive set for the wrong place with nothing saying so (the 2026-11-14 run did exactly that). Both settings are comma-separated place fields, and the check compares every field both of them name, so `North Vancouver,Washington,United States` does not pass against a British Columbia market, and `North Vancouver, British Columbia` does not false-fire against `North Vancouver,British Columbia,Canada`. Where `non_profit_location` names only a city, only the city can be compared. A warning rather than an error: measuring a neighbouring market on purpose is legitimate. When `serpapi.location` is absent entirely, `run_feasibility.DEFAULT_LOCATION` is the single fallback, and `serp_audit.py` and `probe_ai_visibility.py` use the same value.
  - Result links are unwrapped before any consumer sees them. Google serves them as `https://www.google.com/goto?url=<opaque>`; `link_recovery.recover_response` replaces each with the destination **host**, recovered from `displayed_link`, a reference's `source_icon` or `source`, or the parent row's host. Because only the host is recoverable, such rows carry `Is_Destination_Page = false` and every page-level figure (`Word_Count`, `Content_Type`, schema/FAQ/author signals, `Page_Authority`) reads `Not Measured`; domain-level figures, including the Domain Authority behind feasibility, are unaffected. `enrichment.max_urls_per_keyword` therefore fetches HTML only for rows whose own URL survived. See docs/methodology.md, "Link recovery".
  - Ranks are absolute across pages. SerpAPI restarts `position` at 1 on each page; `_merge_google_pages` renumbers it to the merged position, keeping the raw value as `page_position`. So any config threshold expressed in ranks (`enrichment.max_urls_per_keyword`, the top-10 filters) counts down the real SERP (finding D-C-01, review of 2026-11-04).
- `http_retry.*` — the retry policy for every outbound HTTP call that goes through `http_retry` (the DA providers, the page fetches, the AI-visibility engines, the GSC pull). `attempts` (default `2`) is the total number of tries, not the number of extra ones — `1` means no retry at all; `backoff_seconds` (default `1.0`) is multiplied by the attempt number between tries, so it grows linearly (1x, 2x, 3x) and does **not** double, unlike the SerpAPI loop's; `max_retry_after_seconds` (default `30.0`) caps how long a server's `Retry-After` header may make the tool wait. The GUI offers a floor of 1 (0.1 for a seconds value) for every key the loader refuses at zero or less, so a value the loader would replace cannot be saved from the window where it is edited — it offered 0 for all of them until review chunk Y8, and the refusal went to a log the GUI operator never reads (P2). Every entry point that loads the config applies the policy once at startup, through `process_config.apply` (`serp_audit.py`, `run_feasibility.py`, `run_gsc_analysis.py`, `probe_ai_visibility.py`, `refresh_analysis_outputs.py`, `report_llm.py` and `generate_insight_report.py` — the last of these applied nothing until review chunk Y11), so one setting reaches every call site. A section that is present and is not a block of settings, a section mangled to empty, a value that is not a positive number, and a boolean are each reported and the documented default used — `http_retry` was read as `cfg.get(...) or {}` until the cold review of chunk Y7, so an indentation typo that made the block `0` or empty was replaced by the defaults with nothing in the log while the same mistake under `serpapi` warned — 0 attempts would make every transient failure terminal (P1), and a report cannot tell a configured 0 from a typo. SerpAPI's own retry has been configurable since the start (`serpapi.retry_max_attempts`), so until review chunk Y4 one of the tool's two retry policies could be tuned and the other could not (P4/P25); since Y7 both blocks are read by the same function (`http_retry.BUDGET_SOURCES`), so a validation rule added to one reaches the other. **The three timeout classes (review chunk Y5).** `http_retry.timeout_seconds` (default `30`) is how long one API call may take — DataForSEO, Moz, Google Search Console. The other two waits are different lengths on purpose and stay in the sections that own the work: `enrichment.timeout_seconds` (default `10`) for one ranked competitor page, shorter because every row of the top 10 is fetched, and `ai_visibility.timeout_seconds` (default `60`) for one engine answer, longer because the models search the web before answering. All three are read by `http_retry.resolve_retry_policy` through `timeouts.seconds_from_config`, so a non-positive, non-numeric or boolean value is reported and the default used; a timeout cannot be switched off. Each was a per-module Python constant repeated across four clients, so the same run waited the same 30 seconds for a Moz lookup and for an LLM with web search (P4/P25). Callers take the value from `http_retry.request_timeout()` / `page_fetch_timeout()` / `llm_timeout()` at call time rather than as a default argument, which binds at import and would never see the configured value.
- `database.lock_timeout_seconds` (default `5.0`) — how long a writer waits for another writer's SQLite lock before the write fails with `database is locked`. It was `sqlite3.connect`'s own default of 5, passed by nobody and choosable by nobody, until review chunk Y11: the GUI runs `refresh_analysis_outputs` in the same process as a run, the AI probe writes the same file, and the only lever that fixes `database is locked` was the one argument the code never named (P4). Shipped at 5.0, so naming it changed no behaviour. Read through `timeouts.seconds_from_config`, so a non-positive, non-numeric or boolean value is reported and the default used; a wait cannot be switched off. `db_connect.connection` passes it with `setdefault`, so a call site with a reason to wait less may name its own. **Every loader applies every policy through one function.** `process_config.apply(cfg)` sets both the outbound retry/timeout policy and the lock wait, and each of the six loaders of `config.yml` calls it. Five of them called `http_retry.apply_retry_policy` directly — a list the cold review of chunk Y4 had to extend once already — and `generate_insight_report._load_config` applied nothing at all although it opens the database, so a report rendered in the GUI's process ran on whatever the previous loader left behind (P5/P25).
- `database.path` (default `serp_data.db`) — where the SQLite history database lives. It was the bare literal `"serp_data.db"` at 24 sites in 17 modules with no config key at all, and every one of those literals was relative to the current working directory, so a reader started from anywhere but the repo root pointed SQLite at a path that did not exist and SQLite created a new empty file beside the caller: a missing history reported as an empty one (P4/P16/P2, review chunk Y12). `db_connect` now owns the name — one literal, in one module — and every call site asks `db_connect.database_path()` at call time rather than taking it as a default argument, which binds at `def` time before any config is read. A relative path resolves against the repo root, where `config.yml` lives, never against the cwd; an absolute path is used as given; `~` is expanded; a blank or non-string value is reported and the default used. `process_config.apply` sets it beside the lock wait, so the one function every loader of `config.yml` already called carries it too — and chunk Y12 gave `export_history.py`, `verify_enrichment.py` and `export_ai_visibility.py` a loader, since the first two read no config at all and the third read it for the client slug alone. The four `--db` command-line options default to `None` and are resolved after the loader, so the configured path is what they fall back to. The Configuration Manager shows the field with help text explaining that pointing it at a file that does not exist yet means an empty history. `db_connect.connection` says so once per database when it is creating the file rather than opening one, because a typo and an unmounted volume both otherwise arrive as "no history yet" (P1/P2). **Where `config.yml` itself is read from.** `process_config.config_path()` — the file beside the repo, not the one in the caller's working directory. Eight loaders defaulted to the bare `"config.yml"` and the GUI launched `serp_audit.py` with `cwd=os.getcwd()`, so starting the tool from any other directory found no config, reset every policy to its default and abandoned a configured `database.path` for the built-in one, which on an installation that had ever run before exists and reads as a real, stale history. A path passed on the command line is still resolved against the working directory, which is what a person typing `--config` means.
- **Values the Configuration Manager refuses at zero.** Thirteen settings may not be zero or negative, because the loader that reads each of them reports the value and uses its built-in default instead: the five retry-budget keys (`http_retry.attempts`, `http_retry.backoff_seconds`, `http_retry.max_retry_after_seconds`, `serpapi.retry_max_attempts`, `serpapi.retry_backoff_seconds`), the three timeouts (`http_retry.timeout_seconds`, `enrichment.timeout_seconds`, `ai_visibility.timeout_seconds`) `serpapi.timeout_seconds`, `database.lock_timeout_seconds` and the brief's own three (`report_llm.timeout_seconds`, `report_llm.main_max_tokens`, `report_llm.advisory_max_tokens`, which were in no table at all, so the GUI saved a typed 0 for a fourth timeout class after chunk Y8 had fixed the other nine). Save All refuses such a value with `<section>.<field>: must be greater than zero` and the field keeps the value it was loaded with. Until review chunk Y8 it saved: the Spinbox floor binds the spin arrows only, and the loader's report went to a log the GUI operator never reads (P2). The list is not written by hand — `config_tab_models.positive_only_fields()` reads it off `http_retry.BUDGET_SOURCES`, `http_retry.TIMEOUT_SOURCES`, `timeouts.GOVERNED_FIELDS`, `db_connect.LOCK_TIMEOUT_SOURCE` and `report_llm.GOVERNED_FIELDS` — each loader names the keys it refuses, and a new one belongs in its loader's own tuple rather than appended to the set — so a key added to a loader is refused in the GUI without a second edit (P32).
- `files.*` — input/output file paths. `input_csv`, `output_json`, `output_xlsx` and `output_md` are written by `serp_audit.py` at the end of a run that wrote all its outputs (`pipeline_status.finish_run`); a run that is cancelled, or stopped or failed before the audit finishes, leaves them unchanged (a failure in a later `run_pipeline.py` step does not undo them). The launcher does not write them: it passes the keyword file to the run as the `SERP_INPUT_CSV` environment variable, which takes precedence over `files.input_csv`. Output names are always new and timestamped; names already in `config.yml` are never reused. `files.keyword_csv_header_tokens` is what a header row's first cell may be called, lowercased before comparison (default: keyword, keywords, term, terms, query, queries, phrase, phrases, search term, search_term). Editorial, because whoever maintains the keyword files decides what the column is named. A keyword CSV may or may not have a header — six of this repo's seven have none, and `keywords_family-of-origin-seo-phrases.csv` is headed `keyword,intent,why_it_matters` — so the word "keyword" was being searched as a keyword: a paid call, a row in every output sheet and a keyword in the market report that no human typed. Only the first row is tested, so a keyword further down that happens to match a token is still searched, and a skipped header is logged (added 2026-11-18, found while checking that file before a live run). The key is an optional override: the shipped default list lives in `keyword_input.DEFAULT_HEADER_TOKENS`, so a `config.yml` without it behaves the same.
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
- `moz.keyword_metrics.*` — Moz keyword metrics (volume / difficulty / organic CTR / priority), **on by default** (spec gate D-2). `enabled`; `engine` / `locale` / `device` — all three are required by the API and all three change the answer, so all three are part of the cache key (`en-CA` matches the client's market); `max_keywords` — per-run cap (default 50); `rows_per_call` — rows Moz bills per successful fetch (**4**, measured live 2026-08-28, not 1). There is no batch variant for this method, so it is one API call per keyword: 50 keywords is ~200 rows. Runs also stop before exceeding the live remaining quota and log which keywords were skipped; `min_volume_for_investment` — **editorial** (default 20): the monthly search volume below which a keyword is called too small to invest in. This is a demand threshold and is read from the Moz volume figure only. It replaced a test on Google's `Total_Results` estimate, which counts indexed pages rather than searchers and is absent on many SERPs — a missing estimate read as `0` made every such keyword "market too small" (D-M-12 / D4.7)
- `moz.brand_authority.enabled` — Moz Brand Authority (0-100) per competitor domain. **Enabled** at the user's instruction (the spec's default was `false`). 1 row per domain. Rides on the competitor fetch, so `moz.competitor.enabled` must also be true. Also fetches the **client's own** score into the handoff's `moz.client` entry (uncached — 1 row per run — so the competitor scores have a reference point). The real method is `data.site.metrics.brand.authority.fetch`; the spec's `...metrics.brand_authority.fetch` does not exist on this API
- `moz.link_momentum.*` — **off by default, and deliberately not what the spec described.** Moz exposes no recently-gained / recently-lost filter and no time window at all on this plan (allowed filters: `external, follow, nofollow, deleted, not_deleted`). What this reports is linking domains **lost at some point** vs **currently live** — named `lost` / `live`, with an explicit `window: none` field, so it cannot be read as 60-day momentum. Costs 2 pages per domain; `limit` (default 10) is the spend control
- `moz.competitor.*` — Moz competitor signals added to the Tool 2 handoff (`data.site.ranking.keyword.list` + `data.site.anchor.text.list`). **Enabled** here at the user's instruction (the spec's default was `false`). `scope` / `locale` are part of the cache key and change the answer — bowencenter.org returns ranking keywords in `en-US` but none in `en-CA`. `max_competitors` (default 3), `ranking_keyword_limit` (50), `anchor_text_limit` (25). `client_anchor_texts` (default **true**) additionally fetches the **client's own** anchor text into the handoff's `moz.client.anchor_texts`; the client is excluded from the competitor list by design, so without it Tool 2's own-site spam check has no data and negative SEO aimed at the client is invisible. Costs one extra anchor page. **1 row per object returned.** The limits are sent as the API's own page controls (`page.limit` for ranking keywords, `offset.limit` for anchor text) so they genuinely reduce the bill — a bare `limit` is ignored and would return, and charge for, a full page regardless. Neither method is paginated to exhaustion; the result declares `truncated: true` when a full page came back
- `moz.search_intent.*` — Moz search-intent scores, used to **cross-check** the repo's own `intent_mapping.yml` classifier and never to replace it. **OFF by default**: it is a second opinion on a call the repo already makes. 1 row per keyword (measured live 2026-08-28, unlike `keyword_metrics` at 4). `repo_to_moz_intent` is **editorial**: Moz has four intent labels while this repo also emits `commercial_investigation`, `local` and `uncategorised`, so a repo verdict is mapped onto Moz's vocabulary before the two are compared. A `null` entry means "not comparable", which is reported as such rather than as a disagreement
- `moz.site_metrics.scope` — Moz site-query scope: `domain`, `subdomain`, `subfolder` or `url` (default `url`, which reproduces the page-level Page Authority the legacy endpoint returned)
- `moz.site_metrics.batch_size` — targets per `data.site.metrics.fetch.multiple` request (default 50)
- `moz.site_metrics.link_count_fields` — **editorial**: which of Moz's link-count fields are kept on each result and cached. Every kept field costs nothing extra (they arrive in the same response); the list controls what downstream code and the cache see
- `moz.rows_per_month` — the account's monthly data-row allowance, read from the live `quota.lookup` rather than hardcoded from the plan tier (3,000 on the Starter Medium plan, probed 2026-08-27). The API reports `allotted` and `used`; rows remaining is derived from the two by `moz_jsonrpc.parse_quota`
- `feasibility.*` — DA gap thresholds, client DA, neighbourhoods, pivot settings
  - `serpapi.maps_zoom` — **editorial**: the zoom level sent with a Maps query that pins its location by name. SerpAPI REQUIRES `z` (or `m`) whenever `location` is set and answers `400 Missing \`z\` or \`m\` parameter` without it, which is why every pivot local-pack check failed until 2026-11-21 — the audit passed `z=14` as a literal and the standalone feasibility pass passed nothing. 14 is roughly a town; lower is a region, higher is a few blocks.
  - `feasibility.pivotable_intents` — **editorial**: the SERP intents for which a neighbourhood pivot is meaningful (default `local`, `transactional`). Proximity substitutes for domain authority only when the searcher wants a service in a place, so a keyword whose measured intent is not on this list gets no pivot and no neighbourhood variants — and the refusal now names the intent that decided it rather than calling every refusal "informational". Must use `intent_mapping.yml`'s vocabulary. A keyword carrying a `local_intent.markers` phrase from `serp_vocab.yml` ("near me") is pivotable whatever its measured intent, so this list governs only the keywords that do not say where they want the service (2026-11-21). A missing, empty or malformed value falls back to the default with a warning (D-M-19 / D4.10 cold review)
- `audit_targets.n` — top-N organic URLs per keyword exported to competitor handoff (default 10)
- `audit_targets.omit_from_audit` — domains excluded from the handoff (never sent to Tool 2)
- `client.preferred_intents` — intents the client can produce content for; drives `mixed_intent_strategy`
- `analysis_report.*` — client context injected into LLM prompts
- `report_llm.*` — which LLM writes the Content Opportunity report and the advisory briefing (`report_llm.py`, `brief_llm.py`). `provider` is an entry name in the shared key file `~/.config/llm/keys.json`; empty means the key file's `apps` map for `serp-discover`, then its default provider. `main_model` / `advisory_model` are that provider's model IDs (an empty `advisory_model` uses `main_model`; `--llm-model` / `--advisory-model` override both). `timeout_seconds` (default `600`) is the limit for one call; zero or a non-number falls back to the default. `main_max_tokens` (default `16000`) and `advisory_max_tokens` (default `4000`) are the output-token limits; a model that reasons before answering spends part of the limit on reasoning (Hydrogen needed about 19,000 and 10,000 tokens on a 9-keyword run, so `config.yml` sets `64000` and `16000`), and an answer that hits the limit fails the run. `--llm-max-tokens` overrides the main limit. `model_include` (ID prefixes) and `model_exclude` (substrings) decide which of the provider's live models the launcher dropdowns offer. A provider that cannot be loaded, or a call that fails, stops the step; there is no fallback to another provider. `brand_mentions.llm_model` and `sentiment.llm_model` are sent to this same provider
- `report_thresholds.entity_dominance.*` — thresholds for interpreting SERP entity type dominance in reports (see RC.6)
- `geo.outreach_entity_types` — entity types treated as brand-placement (outreach) surfaces in the AI Overview citation analysis, as opposed to competitor counselling sites (see seo_geo_review T.3)
- `situational_probes.*` — "S"-label conversational query probes (see seo_geo_deferred T.5). **Paid feature, off by default.** `enabled` (default `false`; Deep Research mode turns it on, Low API mode always turns it off), `max_probes_per_run` (default 6 — the hard per-run SerpAPI call cap, decision gate D-1), `probes_per_keyword` (default 2), `keywords` (`priority` = probe in strategic_flags order from the last analysis JSON; `all` = keyword CSV order). Probe query templates are editorial and live in `serp_vocab.yml situational_templates`.
- `ai_visibility.*` — AI-engine mention probing (`probe_ai_visibility.py`; see seo_geo_deferred G.1, decision gate D-2). **Paid feature, cost-guarded:** the script makes zero API calls unless run with `--yes` or `assume_yes: true`. Keys: `engines` (default `[gemini, openai, perplexity]` per gate Y-D9 — which assistants to probe; Claude is available-but-not-default and can be added; `--engines` overrides per run. Valid engines: `claude`, `gemini`, `openai`, `perplexity`), `claude_model` / `gemini_model` / `openai_model` / `perplexity_model` (model ids — never hardcoded in Python; `openai_model` default `gpt-4o`, `perplexity_model` default `sonar`), `claude_web_search_tool` (Anthropic web-search tool type matching the chosen Claude model), `openai_endpoint` (default `https://api.openai.com/v1/responses` — the web-search-enabled Responses API) and `openai_web_search_tool` (default `web_search`), `perplexity_endpoint` (default `https://api.perplexity.ai/chat/completions` — the OpenAI-compatible Sonar endpoint that returns citations), `max_questions` (default 20 — cap **per engine**; total calls = questions × engines), `max_total_calls` (default 60 — **hard ceiling on total paid calls across questions × engines**, decision gate Y-D4; the cost guard prints `questions × engines` and this ceiling, and when the plan exceeds it the question set is truncated so the ceiling is never breached — and no calls are made at all unless `--yes`/`assume_yes`), `client_slug` (default `living_systems` — which block in `client_profiles.yml` seeds the highest-priority profile questions per Y.5; a missing slug/profile skips profile questions and the probe falls back to keyword-derived questions), `assume_yes` (default `false`), `history_runs` (default 5 — how many prior runs the trend table shows), `geo_context` (sentence prefixed to every question so answers are location-realistic). Each optional engine is key-gated and skipped-with-warning (never an abort) when its key is absent: Gemini needs `GEMINI_API_KEY`, OpenAI/ChatGPT needs `OPENAI_API_KEY` (Y.2), Perplexity needs `PERPLEXITY_API_KEY` (Y.3). **Tier note (Y.2/Y.3):** the OpenAI web-search citations and Perplexity Sonar citations are confirmed against the vendors' 2026-07 live docs (OpenAI `url_citation` annotations + `web_search_call` sources on the Responses API; Perplexity top-level `search_results`/`citations`), but citation availability can vary by account tier/model — endpoints, tool names, and model ids are all config-parameterised so no code change is needed to track the current surface, and a run on a tier that returns no citations still measures `mentioned` correctly (citation-based `cited` simply reads as absent, never faked). **`timeout_seconds`** (default `60`) is how long one engine answer may take; it is far longer than `http_retry.timeout_seconds` because these models search the web before answering, and every engine reads it through `http_retry.llm_timeout()` — including the Claude engine, whose SDK client is built per request so the configured value reaches it rather than the SDK's own ten-minute default (review chunk Y5 and its cold review). **`brand_relevant_categories`** (default `[counselling, nonprofit]`) is editorial: the classifier categories in which a cited domain carrying no `known_brands` entry is a rival the gazetteer is missing. The citations section prints the count for these categories beside the whole-table count, because a directory or a publisher has no brand by design and the whole-table figure is high on every run.
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

**`serp_vocab.yml`** — editorial SERP-audit vocabulary: n-gram stop words, PAA category triggers (Commercial/Distress/Reactivity), service-like tokens, the AI-alternative query templates, the `situational_templates` section (situation-style probe query templates — keep each 6+ words; see seo_geo_deferred T.5). As of yoast_geo_upgrade Y.4 this section is a **persona-keyed map** `{persona_label: [templates...]}` (the original flat list is preserved verbatim under `therapy_seeker`, with `clinician_trainee` and `referrer` blocks added). When a client profile (Y.1) is present only that profile's declared personas expand; with no profile all persona blocks expand (backward-compatible). Placeholders: `{base}`/`{topic}`/`{city}` plus the optional `{service}` (client `service_description`, omitted cleanly when absent). Flattened for consumers via `query_variants.flatten_situational_templates`), the `fetch_status` section (review chunk D2c: the words a row's `Fetch_Status` can carry — `enriched`, `blocked` (takes `{status}`), `unreachable`, `not_attempted`, `not_destination_page`, `no_url`, `enrichment_disabled` — plus `blocked_warning`, the "N of M pages were not read" line written to Parsing_Warnings; the ONLY home for these words. The machine-readable state lives beside them in the row's `Fetch_State` column, which is what consumers filter on, so re-wording a status here never changes a count), the `classification_coverage` section (added 2026-11-19: the §0 line saying how many ranked results were classified and, from the rows' own `Fetch_Status` words, what stopped the rest — `line`, `reason_item` and `none_classified`, the separate wording for a run where nothing was classified at all), and the `eeat_signals` section (E-E-A-T author-signal vocab: `credential_tokens` — professional designations like RCC/MSW/"registered clinical counsellor" that mark a byline as credentialed, and `review_markers` — "medically reviewed"-style phrases; see seo_geo_deferred G.3). Note: the shared config's `stop_words` (out-of-repo, see "Shared config" below) still overrides the stop-word list when present.

**`strategic_patterns.yml`** — Bowen theory strategic pattern definitions. Each entry has `Pattern_Name`, `Triggers` (list), `Status_Quo_Message`, `Bowen_Bridge_Reframe`, and `Content_Angle`. A pattern fires when any trigger word appears as a whole word in the run's SERP ngram corpus. Add new patterns by appending entries; no Python changes required.

**`play_routing.yml`** (seo_geo_review chip A) — the "Recommended Play" decision table. `play_routing.py` normalises each keyword's pre-computed signals into primitives; this file makes the call among five plays. First-match-wins, top of file = highest priority. Two top-level keys:

- `plays`: map of play-id → `{label, strategy_text, success_metric}`. The five plays are `rank_play` (High/Moderate feasibility → win by ranking), `extraction_play` (Low/unknown feasibility + informational/commercial or mixed intent + AI Overview → win by AIO citation), `reformat_play` (client already ranks top-10 but is not AIO-cited → reformat the existing page first), `local_pivot_play` (Low/unknown feasibility + service-like keyword + local/transactional intent → hyper-local pivot), and `deprioritize` (none of the above). `strategy_text` is a one-line string the report/LLM may quote. `success_metric` (added by the chip C consumer) is the metric the brief's Section 7 uses for that play (rank → ranking, extraction/reformat → AIO citation). Every play a rule references must be defined here.
- `rules`: ordered list of `{play, match}`. A rule matches when **every** key in its `match` block matches the keyword's normalised signal; any signal not named is treated as `any`. A match value may be a scalar, a list (signal ∈ list), or `any`. Matchable signals: `feasibility` (high/moderate/low/unknown), `primary_intent` (informational/commercial_investigation/transactional/navigational/local/mixed/unknown), `is_mixed`, `mixed_intent_strategy`, `has_ai_overview`, `client_ranks_but_not_cited` (the per-keyword source of `strategic_flags.geo_alerts`), `is_service_like` (keyword contains a `serp_vocab.yml` `service_like_tokens` entry), `has_local_pack`.

Each play may also carry `strategy_text_unknown_feasibility` — the wording used when
`data_available.feasibility` is false. `extraction_play` and `local_pivot_play` have one
because both are reachable on `feasibility: unknown` while their normal text asserts a
high DA gap (D4.2). A third top-level key, `validation.da_gap_claim_phrases`, is the list
of regexes `brief_validation.py` HARD-fails on when the LLM restates that claim for a
keyword whose DA was never measured (D4.3). Both are editorial: add or reword entries
here, not in Python.

Rule ordering is load-bearing: `reformat_play` must precede `extraction_play`, and `local_pivot_play` rules must always require `is_service_like: true`. `feasibility: unknown` is grouped with `low` for the Low-feasibility plays so a keyword whose DA data could not be fetched still routes on intent + AIO rather than being silently dropped — the resulting verdict carries an honesty note (`recommended_play.confidence` / `data_available` / `note`). Edit the table to refine routing — don't push exceptions into `play_routing.py`. A malformed file fails loudly (`ValueError`).

**`brief_validation_rules.yml`** (review_2026-11-04 D4.16) — what the brief validator checks a brief's numbers against, and the market-size wording that needs a demand figure. Two top-level keys:

- `numeric_claims`: map of field-id → `{label, tolerance, patterns}`. The five fields are `client_rank`, `total_results`, `volume` (the keyword's Moz monthly volume), `avg_serp_da` and `gap`. `label` is the words the issue message uses ("client rank"). `tolerance` is how far a stated figure may sit from the measured one before it is an issue — `0` for a rank, a wider band for a figure the model may round. `patterns` is a list of regexes, **one capture group each**, that find the claim in the brief's prose for that keyword. The rank patterns are anchored on the word "client": a keyword's section also states competitor ranks, and a bare `ranks #N` read those as claims about the client. A field that was never measured is not checked: there is no number to disagree with, and that case belongs to the gates that already cover it. `total_results` counts as never measured unless it exceeds the results the request asked for — Google has largely stopped publishing its index estimate, and what comes back is otherwise the fetched page's own result count (see `docs/methodology.md`, "`total_results` is a page count").
- `market_size_phrases`: the phrases that assert a market size ("monthly searches", "search volume of"). Inside a keyword's own section they require **that keyword** to carry a measured Moz volume; outside any keyword's section they require at least one keyword in the run to. Otherwise the brief is talking about demand nobody measured.

Both are editorial: add a field, widen a tolerance or add a phrasing here, not in Python. A missing or malformed file logs a warning and the numeric checks are skipped — it never aborts a run. A pattern with more or fewer than one capture group is reported and ignored.

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
   `client_da_source: "config fallback (<provenance>, unverified against
   <provider>)"` and rendered as `32 (config, not measured by moz)`.

With no provider reachable the client DA is `None`, every keyword reads "Not
measured", and nothing is scored against the constant.

`feasibility.client_da_source` — **editorial**: who measured the fallback and
when, e.g. `dataforseo 2026-11-21`. The fallback was `35` with no provenance
at all while DataForSEO measured 32, so a reader could not tell whether the
difference was staleness or two vendors' scales — and nothing asked for it to
be corrected. With the provenance recorded, a run that measures a different
figure **with the provider named there** reports the fallback as STALE and
prints the value to set; a run whose provider differs says the two scales are
not comparable. When the fallback is used, a same-provider figure is reported
as old but correctly scaled, and any other as unverified. `shared_config`'s
`client.da_source` wins over this key, as `client.da` does over `client_da`;
both are resolved by `feasibility.resolve_client_da_config`, so one precedence
serves the audit and the standalone pass (2026-11-21).

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
| `coverage_unknown` | a row from a run written before coverage was recorded — a third state, not "0 of 0" |
| `minima` | the sentence stating the weakest competitor holding a slot, and the weakest that is not a directory, beside the mean (D-M-09) |
| `no_data_section` | `heading` + `body`: what report section 5c says in place of a feasibility table when no DA was measured at all. Added 2026-11-18 after a live run found the words hardcoded in `generate_insight_report.py` with a Moz plan figure in them ("free tier, 50 rows/month") that is both wrong for this account and the one number `CLAUDE.md` forbids hardcoding — the allowance is read from the account at runtime. The block names no figure, and it names `run_feasibility.py`, because credentials alone do not fill the section in: `run_pipeline.py` runs steps 1.1-1.4 and feasibility is not one of them |

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

### `ai_visibility.key_registry_providers` (editorial)

Which shared-key-registry provider (`~/.config/llm/keys.json`) supplies each
engine's API key when the environment carries none:

```yaml
ai_visibility:
  key_registry_providers:
    ANTHROPIC_API_KEY: anthropic
    OPENAI_API_KEY: openai-serp
    GEMINI_API_KEY: gemini-serp
    PERPLEXITY_API_KEY: ""
```

**The environment always wins.** A key placed in `.env` for this tool is
never overridden by a registry default.

Editorial because the registry holds eleven providers and which of them this
tool may spend is the owner's decision, not the code's. A provider named here
must be one whose key authenticates against the engine's *own* endpoint: the
probes call Anthropic, Gemini, OpenAI and Perplexity direct and ignore a
registry `base_url`, so a proxy provider's key would authenticate nowhere.

Blank means no provider is configured for that engine, which is a different
fact from a provider that failed. Every engine variable is listed even when
blank, so "the registry holds no Perplexity key on this machine" is visible
beside the three that are filled. An engine with no key anywhere is skipped
and reported as not measured, never as a zero.

Before this map the four engines read environment variables only while
content-brief generation read the registry, so on a machine whose keys live
in the registry the brief was written and all four engines skipped with
"KEY is not set" — the key existed and the probe could not see it. The run
log now names where each key came from, and the reason for each that has
none ("N of M engine key(s) unavailable"). No key value reaches a log or a
record.

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

### `gsc` / `gsc_demand` / `aio_exposure` — the demand and exposure figures (review chunk D5)

| Key | What it sets |
|-----|--------------|
| `gsc.min_impressions` | the impressions a query needs before its CTR enters the sponge medians or the reformat shortlist (default 50). One click on three impressions is a 33% CTR and says nothing; the sponge rollup reports `queries_below_impression_floor` so the drop is visible. Editorial: a judgement about how much traffic this client's pages get (D-M-15) |
| `gsc.reformat_ctr_margin` | how far below the no-AIO median CTR a query must sit to be shortlisted (default 0.25 = 25% below). Below the median on its own shortlists half of any set. Editorial: a tighter margin shortlists more pages (D-M-15) |
| `gsc.min_bucket_size` | how many queries a position band needs in **both** buckets (AIO-present and AIO-absent) before the band reports a median at all (default 3); the no-AIO median alone still needs its own bucket to be this large. Below it the band states insufficient data. Editorial: a judgement about how many queries make a median worth reading. A value below 1 is reported and the default used — it would report a median over one query as a comparison (review chunk Y4) |
| `gsc.*` thresholds, where they are read | `run_gsc_analysis.run_analysis` applies this run's `gsc` block once (`apply_sponge_thresholds`) and `compute_sponge_effect` / `find_reformat_candidates` read that one mapping whenever an argument is omitted. Until review chunk Y7 the run resolved the block and also passed all five values explicitly, so the applied mapping had no production reader and the same config was resolved twice behind itself (P25). They are resolved from the config argument, not from process state, so a caller that passes a config without going through `_load_config` still gets its own numbers (P28) |
| `gsc.position_bands` | the position bands the sponge comparison groups queries into, as a list of `[low, high]` pairs (default `[[1,3],[4,10],[11,20]]`). Editorial: the bands decide which queries are treated as ranking comparably, and a client whose pages sit deeper wants different ones. A band that is not a numeric `[low, high]` pair, or whose low exceeds its high or falls below 1, can never hold a query, so the whole list is reported and the documented default used. So are bands that overlap (one query would enter two medians) or leave a gap (those queries enter none). Bands given out of order are used in order, and the rollup reports `queries_in_no_band` so what the bands themselves excluded is visible (review chunk Y4) |
| `gsc.reformat_max_position` | the deepest ranking position the reformat shortlist will consider (default 10). Editorial, and it has to agree with `gsc.position_bands`: it stayed a Python constant when the bands became config, so a client whose pages sit at 11-20 could widen the bands and get an always-empty shortlist with nothing saying why. When no band can hold a position within the cap, the run says so (cold review of chunk Y4) |
| `gsc.country` / `gsc.device` | which country and device the GSC pull is restricted to, so the clicks are measured over the same population as the SERP fetch. Absent → mirrors `serpapi.gl` / `serpapi.device`; `all` turns the filter off on purpose and the report prints a "Mixed populations" warning. `country` takes a 2- or 3-letter ISO-3166-1 code (`ca` → `can`), `device` one of desktop / mobile / tablet. An unmappable value is reported and the filter is left off, never guessed. Part of the `gsc_cache` key, so rows pulled under one filter are never served under another (D-M-20) |
| `gsc_demand.bands.source` | where the branded-share bands come from: a study and a date. Empty → the report states the two figures are the owner's working assumption, because no published source was ever recorded for them. Editorial (D-M-16) |
| `aio_exposure.sources.aio_ctr_multiplier` / `.citation_credit` / `.ctr_curve` | the same for the three modelled AI-Overview constants. "Industry reference point" named no study and no date, and third-party CTR figures move year to year, so each empty value prints as the owner's working assumption in the report caveat and the glossary. Editorial (D-M-20) |

### `thresholds_provenance` / `feasibility.directory_entity_types` / `serp_intent.thresholds` (review chunk D6)

| Key | What it sets |
|-----|--------------|
| `thresholds_provenance.<family>` | one line, in the owner's own words, saying where that threshold family came from — a study and a date, a decision record, or a calibration. Printed in the report's §A glossary appendix under "Where these thresholds come from". A family left blank or absent prints as "editorial, uncalibrated — no source or date is recorded for this one", which is the honest answer until somebody records one. Families: `feasibility`, `serp_intent`, `title_patterns`, `commodity`, `aivi`, `foundational`, `engine_prioritization`, `gsc_demand`, `entity_dominance` (they must match `thresholds_provenance.FAMILIES`; an unknown name is reported and not printed). Each printed line also names the config keys that hold that family's numbers and shows their live values (a key this config does not set says the code default applies); the figures are never copied into the module, so the section cannot print a number somebody has since tuned. Editorial (D-M-21) |
| `feasibility.directory_entity_types` | which entity types count as a directory when the report prints the weakest **non**-directory competitor beside the mean (default `directory`). A directory holding a top-10 slot says nothing about whether a DA-35 clinic can hold one, which is why the two minima are separate. Must use `classification_rules.json`'s `entity_types` vocabulary; malformed → the default plus a warning. Editorial (D-M-09) |
| `serp_intent.thresholds.confidence_high` / `confidence_medium` | the share of the **classified** ranking URLs the leading intent must hold for the verdict's certainty to read high / medium (0.8 / 0.5). Read by `intent_verdict._bucket_certainty`. These two keys were validated, documented and GUI-editable with no reader at all until this chunk, so tuning either changed nothing and warned about nothing; a test now fails if any key under the block loses its reader (D-C-17). Not the same figure as classification coverage, which counts how many URLs could be classified and rises with `enrichment.max_urls_per_keyword` (D-M-10) |

### `title_patterns` — the dominant-pattern thresholds (review chunk Y1)

| Key | What it sets |
|-----|--------------|
| `title_patterns.top_n` | how many of a keyword's ranking titles are read when the title-pattern profile is built (default 10). The profile's counts and its `brand_only` share are over this many titles, so widening it changes both |
| `title_patterns.dominant_threshold` | how many of those titles must share a pattern before it is reported as the SERP's dominant title pattern (default 4). The brief's `title_patterns.dominant_pattern` is HARD-validated against this, so the figure decides what the LLM may say about the SERP's shape |

Both were Python defaults on `compute_title_patterns` that nothing passed, while
`thresholds_provenance` listed `title_patterns` as a tunable family — the
provenance line named numbers no config held. A non-positive or unparseable
value warns and falls back to the documented default rather than aborting the
run.

---

## Configuration Manager GUI

**How to access:** Click "Edit Configuration" button in `serp-me.py` launcher.

The Configuration Manager edits every editorial file in the repo without opening a text editor. Nine files have a **form** — a widget per field, listed first below. The other ten are edited as **source**, listed after them (review chunk Y15).

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

### Source tabs (review chunk Y15)

Ten editorial files had no editor at all: the rule that editorial content belongs in YAML was followed, and the consequence it exists for — that somebody other than a developer can change it — was not delivered for them. Each now has a tab that edits the file's own text.

They are source rather than forms because they nest arbitrarily: `engine_profiles.yml` and `report_writing_directives.yml` are three and four levels deep with prose leaves, and a widget tree over arbitrary nesting is more GUI surface than the editorial benefit justifies. What a source tab adds over opening the file in a text editor:

- The file is **discoverable** in the window, with help text saying what it decides and what changing it changes.
- The **syntax is checked before anything is written**, so a YAML error is reported with its line instead of breaking the next run. A file that does not parse is never saved.
- The file's own **validator runs** if it has one.
- The file's own **loader runs** where one can tell a usable table from valid YAML that is not one. `play_routing.yml` and `brief_validation_rules.yml` are checked this way: a play table with no `rules` list, or a validation file that declares no `numeric_claims`, is refused with what its loader said. Valid YAML is not a valid rule table — deleting `rules:` used to save cleanly and kill the next run, and deleting `numeric_claims:` used to turn every numeric check off with nothing saying so.
- It joins **Save All**, **Discard Changes** and the unsaved-changes prompt, under the same all-or-nothing rule as every other tab.
- **Comments survive exactly**, including ones you add: the text is written as you wrote it rather than re-dumped from the parsed structure. An edit to a comment alone counts as a change.

| Tab | File | What it decides |
|-----|------|-----------------|
| Feasibility Wording | `feasibility_messages.yml` | Status labels and icons, the per-keyword "why there is no verdict" sentence, the coverage phrase beside every mean, how a Client DA cell states its provenance |
| Search Console Wording | `gsc_messages.yml` | The words for each of the three GSC fetch outcomes — measured, measured-and-absent, not-reached |
| AI Visibility Wording | `ai_visibility_messages.yml` | The words for every "not measured" state in the AI-visibility family, per engine, per sentiment brand and per foundational sub-score |
| SERP Vocabulary | `serp_vocab.yml` | Stop words, PAA triggers, service tokens, probe templates, E-E-A-T markers, `fetch_status`, `classification_coverage`, `db_cleanup` |
| Glossary | `glossary.yml` | The plain-English definition of every term of art the report prints, plus the .xlsx column meanings and sheet help |
| Recommended Plays | `play_routing.yml` | The ordered decision table mapping a keyword's signals to one of five plays, and each play's text |
| Engine Profiles | `engine_profiles.yml` | Per-engine source bias, citation counts, reach tiers, and the "what to change here" advice |
| Report Directives | `report_writing_directives.yml` | The "When you write:" line under each report section, page-type labels, mixed-intent strategies, unwritable content types |
| Brief Validation | `brief_validation_rules.yml` | What the validator checks the brief's numbers against, and the market-size wording that requires a measured volume |
| Schema Recommendations | `schema_recommendations.yml` | The schema.org markup the brief recommends, per page type and context |

**Adding a file:** a row in `config_tab_models.EDITORIAL_SOURCE_FILES` — file name, type, tab title, and optionally a `module:function` structural check — not a class. A standing guard (`tests/test_y15_every_editorial_file_has_an_editor.py`) lists the editorial YAML and JSON **git tracks at the repo root** and fails the build when one has neither a tab nor an entry in `NOT_EDITORIAL` giving the reason it is not editable — today `handoff_schema.json` and `ai_visibility_export_schema.json` (contracts between the two tools, where hand-editing one side is how they drift). The count of tabs is what went stale before; the guard reads the files. Tracked files, not everything at the root: a run's own output and a reader's scratch files sit there too, and listing the directory made an untracked `zz_scratch.yml` fail the suite.

**Saving:**
- **Only changed files are written.** "Save All" writes the tabs you edited and reports how many of the changed tabs were saved. Pressing it with no edits writes nothing.
- **Nothing is written unless everything can be.** Each changed file is validated first; if one is invalid, no file is written and the errors are listed. Each file is replaced atomically. There is no backup copy — use git to recover an earlier version.
- **Keys the tab does not show are kept.** A save applies your edits to the file as it was loaded, so entries with no field in the GUI (for example `known_brands` in `config.yml`, or `rationale` on an intent rule) are left as they were.
- **A file that could not be read is never overwritten by a form tab.** If a file has a syntax error when the manager opens, its tab shows a red notice and is skipped on save. Fix the file in a text editor, then press "Discard Changes" to reload.
- **A source tab can repair the file it could not read.** The ten source tabs above are the exception: the raw text loads even when it does not parse, so you can fix the syntax in the tab and save. The text is re-parsed first, so a still-broken repair is refused and the file on disk is untouched.
- **A file changed by something else is not overwritten.** If the launcher or a pipeline run wrote a file after the manager loaded it, saving that file is refused; press "Discard Changes" to reload and redo the edit.
- **A field that does not parse is an error.** A typo in a number or list field in Config Settings is reported by name instead of being saved as `0` or an empty list.
- **Closing:** the Close button and the window's close box both ask about unsaved changes. If "save before closing" fails, the window stays open with your edits.

**Other features:**
- **Help on every field:** Click `?` next to a field for what it means and why it matters.
- **CRUD operations:** Add, edit, delete, and reorder (for order-sensitive files like intent_mapping.yml).
- **Discard Changes:** reloads every tab from disk.

For detailed help, see `docs/config_manager_phase5_completion_20260502.md`.
