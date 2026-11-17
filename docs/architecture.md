# Architecture — module map, data flow, and prompt templates

```
keywords.csv
    └─► serp_audit.py (fetch + parse + enrich)
            ├─► raw/{run_id}/                    raw JSON from SerpAPI
            ├─► market_analysis_*.json           aggregated data
            ├─► market_analysis_*.xlsx           Excel workbook
            ├─► market_analysis_*.md             markdown summary
            ├─► competitor_handoff_*.json        validated handoff for Tool 2 (Gap 3)
            └─► serp_data.db                     SQLite history

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
| `gsc_client.py` | GSC Search Analytics client — service-account auth (gate D-3), http_retry semantics, 7-day SQLite `gsc_cache`; returns a `GscStats` carrying what the fetch did and did not reach, and caches an absence only when the fetch completed (D2b); status wording in `gsc_messages.yml`; only imported by `run_gsc_analysis.py`, never by the pipeline |
| `classifiers.py` | Rule-based content & entity type classifiers |
| `intent_classifier.py` | Tags PAA questions as External Locus / Systemic / General |
| `intent_verdict.py` | Spec v2 — computes per-keyword SERP intent verdict from intent_mapping.yml rules (primary_intent, is_mixed, confidence, distribution) |
| `title_patterns.py` | Spec v2 — extracts shape patterns (how_to, what_is, listicle_numeric, vs_comparison, best_of, brand_only, question, other) from top-10 titles with dominance threshold |
| `feasibility.py` | DA gap scoring (`compute_feasibility`) + pivot suggestions (`generate_hyper_local_pivot`) + the one definition of the feasibility input set (`url_window` / `usable_url` / `competitor_da_window`), of the client's own DA (`with_client_url` / `resolve_client_da`), of a provider batch's coverage (`batch_coverage`, used by both DA clients) and of the row index (`index_feasibility_by_keyword`), shared by both producers (D-C-19, D-M-05). `NOT_MEASURED` is the status key every consumer branches on. Status labels, coverage phrases and the no-verdict sentences are read from `feasibility_messages.yml` (`load_messages`) |
| `dataforseo_client.py` | DataForSEO bulk_ranks API client with 30-day SQLite cache |
| `moz_client.py` | Moz Links API v2 client with 30-day SQLite cache (fallback) |
| `storage.py` | SQLite persistence layer. `save_feasibility_from_row` persists a feasibility assessment from the dict `compute_feasibility` produced, so a field added to the row cannot be dropped on the way to the database (review chunk D2) |
| `metrics.py` | Volatility & entity dominance calculations; baselines against the previous **completed** run, primary-query rows only (D-C-22) |
| `url_enricher.py` | URL fetching & feature extraction |
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
