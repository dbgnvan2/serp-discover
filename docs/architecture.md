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
    └─► generate_content_brief.py (LLM via Anthropic)
            ├─► content_opportunities_*.md
            └─► advisory_briefing_*.md
```

## Core Modules

| Module | Role |
|--------|------|
| `serp_audit.py` | Main SERP engine — fetches, parses, enriches, tags PAA intent |
| `pattern_matching.py` | N-gram analysis and Bowen strategic pattern matching (extracted from `serp_audit.py` I.6) |
| `handoff_writer.py` | Builds and schema-validates the `competitor_handoff_*.json` handoff for Tool 2 (extracted from `serp_audit.py` I.6) |
| `generate_insight_report.py` | Renders `market_analysis_*.md` — Sections 1–6 including `## 5b. Per-Keyword SERP Intent`, Mixed-Intent Strategic Notes (Section 4), and per-pattern SERP intent context lines (C.2) |
| `generate_content_brief.py` | Entry point for the content brief pipeline — orchestrates sub-modules; contains `main()`, `progress()`, `load_data()`, `load_brief_pattern_routing()` |
| `brief_data_extraction.py` | Extracts structured data from `market_analysis_*.json`; `extract_analysis_data_from_json()` is the primary entry point (split from `generate_content_brief.py` I.5) |
| `brief_validation.py` | Validates LLM output against pre-computed verdicts; `validate_llm_report()` enforces HARD/SOFT-fail rules (split from `generate_content_brief.py` I.5) |
| `brief_prompts.py` | Loads and constructs prompt payloads; `load_prompt_blocks()`, `build_main_report_payload()`, etc. (split from `generate_content_brief.py` I.5) |
| `brief_llm.py` | Anthropic API call wrapper; `run_llm_report()` handles multi-turn correction flow (split from `generate_content_brief.py` I.5) |
| `brief_rendering.py` | Renders content briefs and opportunity reports; `generate_brief()`, `list_recommendations()`, `generate_local_report()` (split from `generate_content_brief.py` I.5) |
| `run_feasibility.py` | Standalone DA feasibility analysis and pivot report |
| `classifiers.py` | Rule-based content & entity type classifiers |
| `intent_classifier.py` | Tags PAA questions as External Locus / Systemic / General |
| `intent_verdict.py` | Spec v2 — computes per-keyword SERP intent verdict from intent_mapping.yml rules (primary_intent, is_mixed, confidence, distribution) |
| `title_patterns.py` | Spec v2 — extracts shape patterns (how_to, what_is, listicle_numeric, vs_comparison, best_of, brand_only, question, other) from top-10 titles with dominance threshold |
| `feasibility.py` | DA gap scoring (`compute_feasibility`) + pivot suggestions (`generate_hyper_local_pivot`) |
| `dataforseo_client.py` | DataForSEO bulk_ranks API client with 30-day SQLite cache |
| `moz_client.py` | Moz Links API v2 client with 30-day SQLite cache (fallback) |
| `storage.py` | SQLite persistence layer |
| `metrics.py` | Volatility & entity dominance calculations |
| `url_enricher.py` | URL fetching & feature extraction |
| `serp-me.py` | Tkinter GUI launcher |
| `run_pipeline.py` | Pipeline orchestration |
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
