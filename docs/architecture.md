# Architecture — module map, data flow, and prompt templates

```
keywords.csv
    └─► serp_audit.py (fetch + parse + enrich)
            ├─► serp_fetch.py                    one SerpAPI call: resume, retry budget, recovery
            ├─► pivot_pass.py                    pivot decision, on the measured SERP intent
            ├─► raw/{run_id}/                    raw JSON from SerpAPI
            ├─► market_analysis_*.json           aggregated data
            ├─► market_analysis_*.xlsx           Excel workbook
            ├─► market_analysis_*.md             markdown summary
            ├─► competitor_handoff_*.json        validated handoff for Tool 2 (Gap 3)
            └─► database.path                   SQLite history (serp_data.db)

market_analysis_*.json
    ├─► run_feasibility.py (DA gap analysis — standalone, runs any time)
    │       ├─► dataforseo_client.py       domain rank lookup (primary)
    │       ├─► moz_client.py             domain rank lookup (fallback)
    │       ├─► feasibility.py            gap scoring + pivot suggestions
    │       └─► feasibility_*.md          standalone feasibility report
    │
    └─► generate_content_brief.py (LLM via the provider in config.yml report_llm)
            ├─► content_opportunities_*.md
            └─► advisory_briefing_*.md
```

## Core Modules

| Module | Role |
|--------|------|
| `serp_audit.py` | Main SERP engine — fetches, parses, enriches, tags PAA intent |
| `pattern_matching.py` | N-gram analysis and Bowen strategic pattern matching (extracted from `serp_audit.py` I.6) |
| `serp_fetch.py` | One SerpAPI call: the resume lookup, the retry budget, and the post-response checkpoint write and link recovery. A transport error is retried (`SERPAPI_TRANSPORT_ERRORS`, caught by name); anything else is a fault in this process, is logged as an internal error and is **not** retried, because every attempt costs a paid call. The loop used to sit in `serp_audit` and caught every exception the same way, so a fault in the checkpoint write or the link recovery — both of which run after a response has been paid for — was retried with two more paid calls and then filed beside genuine network failures (extracted from `serp_audit.py` by review chunk Y8) |
| `serp_pagination.py` | SerpAPI pagination: next-page `start` offset, and the page merge that renumbers `position` to the absolute SERP rank (extracted from `serp_audit.py` by review chunk D1) |
| `handoff_writer.py` | Builds and schema-validates the `competitor_handoff_*.json` handoff for Tool 2 (extracted from `serp_audit.py` I.6) |
| `generate_insight_report.py` | Renders `market_analysis_*.md` — Sections 1–6 including `## 5b. Per-Keyword SERP Intent`, Mixed-Intent Strategic Notes (Section 4), and per-pattern SERP intent context lines (C.2) |
| `generate_content_brief.py` | Entry point for the content brief pipeline — orchestrates sub-modules; contains `main()`, `progress()`, `load_data()`, `load_brief_pattern_routing()` |
| `brief_data_extraction.py` | Extracts structured data from `market_analysis_*.json`; `extract_analysis_data_from_json()` is the primary entry point (split from `generate_content_brief.py` I.5) |
| `brief_validation.py` | Validates LLM output against pre-computed verdicts; `validate_llm_report()` enforces HARD/SOFT-fail rules (split from `generate_content_brief.py` I.5) |
| `brief_prompts.py` | Loads and constructs prompt payloads; `load_prompt_blocks()`, `build_main_report_payload()`, etc. (split from `generate_content_brief.py` I.5) |
| `report_llm.py` | Reads `report_llm` from `config.yml` and resolves the provider (Anthropic or OpenAI dialect) from the shared key file; no model ID in Python |
| `brief_llm.py` | LLM call for either dialect; `run_llm_report()` handles multi-turn correction flow and fails on an empty, refused or truncated answer (split from `generate_content_brief.py` I.5) |
| `brief_rendering.py` | Renders content briefs and opportunity reports; `generate_brief()`, `list_recommendations()`, `generate_local_report()` (split from `generate_content_brief.py` I.5) |
| `run_feasibility.py` | Standalone DA feasibility analysis and pivot report |
| `probe_ai_visibility.py` | Standalone AI-engine mention probing (Claude + Gemini, gate D-2) — per-engine mention/citation trend in SQLite, cost-guarded; never imported by the pipeline (seo_geo_deferred G.1) |
| `run_gsc_analysis.py` | Standalone Google Search Console sponge-effect analysis — joins first-party CTR data onto the run's queries; writes `gsc_analysis_*.{md,json}` (seo_geo_deferred G.4) |
| `thresholds_provenance.py` | One answer for "where did this threshold come from". Reads the editorial `thresholds_provenance` block in `config.yml` and renders the report's "Where these thresholds come from" block; a family with no recorded source prints as editorial and uncalibrated rather than silently (D-M-21) |
| `gsc_filters.py` | Resolves the Search Console query filters (country, device) from `config.yml` and builds the `gsc_cache` filter key. Config reading only — no network, no heavy imports — so both `gsc_client` and the read-side `demand_dashboard` can import it without the read side pulling in the client (pipeline isolation, G.4.4) |
| `gsc_client.py` | GSC Search Analytics client — service-account auth (gate D-3), http_retry semantics, 7-day SQLite `gsc_cache`; returns a `GscStats` carrying what the fetch did and did not reach, and caches an absence only when the fetch completed (D2b); status wording in `gsc_messages.yml`; only imported by `run_gsc_analysis.py`, never by the pipeline |
| `classifiers.py` | Rule-based content & entity type classifiers |
| `intent_classifier.py` | Tags PAA questions as External Locus / Systemic / General |
| `intent_verdict.py` | Spec v2 — computes per-keyword SERP intent verdict from intent_mapping.yml rules (primary_intent, is_mixed, confidence, distribution) |
| `title_patterns.py` | Spec v2 — extracts shape patterns (how_to, what_is, listicle_numeric, vs_comparison, best_of, brand_only, question, other) from top-10 titles with dominance threshold |
| `pivot_pass.py` | The in-pipeline neighbourhood-pivot decision, run between `serp_audit`'s SERP fetch loop and its pivot fetch pass. `build_pivot_profiles` builds the keyword profiles through the shared `brief_data_extraction.build_keyword_profiles`; `decide_pivots` calls `feasibility.generate_hyper_local_pivot` with the measured `serp_intent` and `entity_distribution` and returns the feasibility rows and the pivot fetch jobs. The decision used to sit inside the fetch loop, where no profile existed yet, so the pipeline and `run_feasibility.py` could reach different pivots from the same SERP (review chunk Y6) |
| `feasibility.py` | DA gap scoring (`compute_feasibility`) + pivot suggestions (`generate_hyper_local_pivot`) + the one definition of the feasibility input set (`url_window` / `usable_url` / `competitor_da_window`), of the client's own DA (`with_client_url` / `resolve_client_da`), of a provider batch's coverage (`batch_coverage`, used by both DA clients) and of the row index (`index_feasibility_by_keyword`), shared by both producers (D-C-19, D-M-05). `NOT_MEASURED` is the status key every consumer branches on. Status labels, coverage phrases and the no-verdict sentences are read from `feasibility_messages.yml` (`load_messages`) |
| `dataforseo_client.py` | DataForSEO bulk_ranks API client with 30-day SQLite cache |
| `moz_client.py` | Moz Links API v2 client with 30-day SQLite cache (fallback) |
| `moz_keywords.py` | Per-keyword Moz signals. `_KeywordSignalClient` holds everything that must behave identically for every signal — the run cap, the quota guard, the "404 is not an error" rule, and (since review chunk Y14) the **cache**: the DDL, the chunked lookup and the store are built from the subclass's `CACHE_TABLE_NAME` + `CACHE_PAYLOAD_COLUMNS`, so the three rules a cache of this shape must obey — a row past its TTL is ignored, a cached failure is never served, a measured absence is served — exist once rather than once per signal. `MozKeywordClient` (volume / difficulty / organic CTR / priority) and `MozIntentClient` (search-intent scores) supply only `_block_from_cache` and `_payload_for_cache`, the two halves that genuinely differ |
| `storage.py` | SQLite persistence layer. `save_feasibility_from_row` persists a feasibility assessment from the dict `compute_feasibility` produced, so a field added to the row cannot be dropped on the way to the database (review chunk D2) |
| `db_connect.py` | The one way a module opens the SQLite database: `connection(db_path)` commits on a clean exit, rolls back on an exception, and closes the handle on every path. `with sqlite3.connect(...)` commits but never closes, and `with closing(sqlite3.connect(...))` closes but discards the commit; every production module goes through this helper instead of pairing them per site (review chunk Y9). A failing `rollback()` or `close()` is logged and does not replace the exception the block raised, and `timeout` — the wait for another writer's lock — comes from `config.yml database.lock_timeout_seconds` (review chunk Y11). It also owns the database's **name**: `database_path()` returns the configured `database.path`, resolved against the repo root rather than the current working directory, and it is the only module that contains the literal `"serp_data.db"` (review chunk Y12). A cleanup step that fails is **counted**, not only logged: `cleanup_failure_count()` / `cleanup_failure_warning()` / `cleanup_warning_row()` give the per-process tally, the sentence and the `parsing_warnings` row the audit writes, because a `close()` that fails inside a per-keyword loop fails every time and each one holds a file handle open until the process exits. The sentence claims "the figures stand" only for a failed `close`; a counted `roll back` means a transaction was abandoned. `report_cleanup_failures()` is the floor for the fourteen other consumers and for an abort — registered at exit, since only the audit writes an artefact (review chunk Y13 and its cold review). `CACHE_LOOKUP_CHUNK` lives here too: how many bound variables one `IN (...)` lookup may carry is a fact about SQLite rather than about Moz or about Search Console, and the **five** caches of that shape — the two keyword signals, the DA cache, the DataForSEO cache and the competitor cache — each carried their own copy of it, one explained and four bare literals. A standing guard (`tests/test_y14_one_cache_for_both_signals.py::TestTheCacheLivesInOnePlace`) walks every production module and fails on a chunked lookup that carries its own number, so the sixth cache cannot be missed (review chunk Y14 and its cold review) |
| `process_config.py` | The one function that sets this process's policies from a loaded `config.yml`: the outbound retry and timeout policy (`http_retry`) and the SQLite lock wait and the database path (`db_connect`). Nine loaders read `config.yml`; asking each of them to remember two policies is how the next one gets only one, so they all call `process_config.apply` (review chunks Y11, Y12). It also owns the **config path**: `process_config.config_path()` is `config.yml` beside the repo, so no loader defaults to the bare cwd-relative name — eight of them did, and the GUI launched `serp_audit.py` with `cwd=os.getcwd()`, so starting the tool from another directory found no config and reset every policy silently (the cold review of chunk Y12) |
| `metrics.py` | Volatility & entity dominance calculations; baselines against the previous **completed** run, primary-query rows only (D-C-22) |
| `url_enricher.py` | URL fetching & feature extraction |
| `enrichment.py` | One organic row's page-level enrichment, and the fetch-outcome gate: a response at or above 400 is recorded, not read (D2c / D-C-20) |
| `domain_utils.py` | `normalize_domain` — the one definition of "which host is this", shared by the classifier, the refresh path, the candidate report and the brief extractor (D2c / D-C-08) |
| `serp-me.py` | Tkinter GUI launcher |
| `run_pipeline.py` | Pipeline orchestration |
| `run_control.py` | Launcher process control (no tkinter): one run at a time, stop a run with its child processes, detect a pipeline started elsewhere |
| `serp_checkpoint.py` | Saves each SerpAPI response under `raw/<run_id>/calls/` as it arrives, records `run_state.json`, and serves stored responses to a resumed run (`SERP_RESUME_RUN_ID`) |
| `keyword_run_plan.py` | Launcher keyword-file handling (no tkinter): plan what a run will read and write, then write it only when the run starts |
| `timeouts.py` | Reads timeouts from `config.yml`; a bad value falls back to the default, never to "no timeout" |
| `pipeline_status.py` | Exit-code rules shared by the audit, the pipeline runner and the launcher: fetch summary, missing-output check, launcher status label |
| `config_tab_models.py` | Data side of the Configuration Manager tabs (no tkinter): load/save guards, save-only-changed-tabs, record models. `config_manager.py` holds the widgets |
| `handoff_schema.json` | Spec v2 Gap 3 — draft-07 JSON Schema for `competitor_handoff_*.json`; `additionalProperties: false` enforces contract |
| `strategic_patterns.yml` | Bowen strategic pattern definitions (Pattern_Name, Triggers, Status_Quo_Message, Bowen_Bridge_Reframe, Content_Angle). Add patterns here; no Python required. Loaded and validated at runtime by `pattern_matching._load_strategic_patterns`. |
| `test_validation_consistency.py` | Spec v2 Gap 5 — canary test scanning prompts for `keyword_profiles.<field>` references and asserting each has a validator rule |

## Prompt Templates

```
prompts/
├── main_report/system.md + user_template.md   → content_opportunities_*.md
├── advisory/system.md + user_template.md      → advisory_briefing_*.md
└── correction/user_template.md                → retry on validation failure
```
