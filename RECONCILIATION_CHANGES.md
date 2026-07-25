# Changes vs Draft — SERP Spec Reconciliation (2026-07-22)

Revised `discover-spec.md` and `compete-spec.md` against the real `serp-discover` and `serp-compete` code. This note lists what was renamed, dropped as already-built, re-assigned, or flagged. Evidence is cited by real filename/table/config key.

## Biggest correction: architecture framing (both specs)

The drafts assumed a **web-app stack** that does not exist in either repo:

| Draft assumption | Reality |
|---|---|
| REST API endpoints (`GET /projects/{id}/…`) | No web layer. serp-discover = CLI + **tkinter** GUI (`serp-me.py`, `config_manager.py`); serp-compete = CLI + **Streamlit** wrapper (`orchestrator.py`). Output is JSON/XLSX/MD reports. Endpoints → **report sections + GUI steps + module functions**. |
| SQLAlchemy ORM + Pydantic models | Raw `sqlite3`, hand-written SQL. `storage.py::SerpStorage` (discover), `src/database.py::DatabaseManager` (compete). `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE … ADD COLUMN` in `try/except OperationalError`. No Pydantic. |
| `scoring_config` table + `config_version` stamp | Weights/thresholds live in **YAML/JSON** (`config.yml`; `shared_config.json`). No `scoring_config` table, no `config_version` field anywhere. Reproducibility is done today via `weights_json` columns (`ai_visibility_index`, `foundational_score`). |
| Background job workers | Standalone scripts run manually / via `run_pipeline.py` and `run_audit.sh`; AI-visibility + GSC are explicitly *not* imported by the pipeline. |
| Multi-tenant `project_id` | Single **client** per repo (`analysis_report.client_domain` = livingsystems.ca; `shared_config.json → client`). |

Both specs now open with a "Repo conventions" section pinning these down, and every data model is expressed as a real sqlite table in the existing style.

## Spec-ID / workflow alignment

- Draft had no spec-ID scheme. Discover uses namespaced IDs (`Y.1–Y.13` + gates `Y-D2…Y-D9`, `C.x/T.x/G.x`, `I.x`, `RC.x`, `v2.G1.x`); spec files in repo root, status in `docs/spec_coverage.md`; `Spec:` docstring refs; `docs/methodology.md` is a contract. Compete uses `Spec: suite_enhancement_spec_v1.md#<item>` with IDs `SC-1/SC-2/X-1/X-4`.
- Revised specs propose their own IDs: **Discover `AV.x`**, **Compete `SC-3…SC-8`** (one per surviving feature), and require regenerating `docs/spec_coverage.md` (discover) / `docs/SPEC_COVERAGE_REPORT_v3.md` (compete).
- Test/venv conventions added: discover `python3 -m pytest test_*.py tests/ -q` (venv), business-logic tests must not need tkinter, `test_validation_consistency.py` canary for new `keyword_profiles.<field>`; compete `PYTHONPATH=. pytest tests/`. Compete security note: `client_secret_*.json` gitignore check, never `git add .`.

## Discover — per-feature status & renames

**D1 AI Overview / zero-click — `partially-exists` (was implied green-field).**
- Already built: `brief_data_extraction.py::_build_aio_divergence()` → `aio_divergence` with the headline `client_ranks_but_not_cited` flag; `Has_Main_AI_Overview`/`has_aio`; `ai_overview_citations`. First-party zero-click = `run_gsc_analysis.py::compute_sponge_effect()`.
- New only: a modeled market-side `est_ctr_loss` + rollup table. Draft `aio_exposure` table → real-style `ai_aio_exposure` (built like `citation_table.CITATIONS_TABLE`). Draft `serp_feature`/`serp_snapshot` tables dropped — SERP features already parsed in `serp_audit.py`. `tracked_domain` → `_is_client_domain` + `analysis_report.client_domain`.

**D2 branded demand (GSC) — `partially-exists`.**
- Already built: GSC client + analysis (`gsc_client.py::GscClient`, table `gsc_cache`; `run_gsc_analysis.py` sponge effect + reformat candidates; `config.yml → gsc`).
- New only: the branded/non-branded **classification** itself. Draft `brand_terms` table dropped → reuse `analysis_report.client_name_patterns` (`["Living Systems"]`) as the brand seed (+ a regex/negative override list). Draft `gsc_query_daily`/`demand_score_daily` → real-style `gsc_demand_daily`/`gsc_demand_score`.

**D3 demand-vs-clicks dashboard — `new`.**
- Confirmed nothing combines GSC clicks vs demand/visibility. Clarified that existing "visibility" symbols are unrelated (`aivi.py` AI-visibility, `bing_check.py`, `probe_ai_visibility.detect_visibility`). Reframed as a report **read-model** (`generate_insight_report.py` / new `demand_dashboard.py`), not a web dashboard.

**D4 commodity / AI-absorption — `partially-exists`.**
- Reuse targets named: `play_routing.py`+`play_routing.yml` (`extraction_play`/`deprioritize` are the commodity-adjacent verdicts; `keyword_profiles[kw].recommended_play`), `metrics.py::get_entity_dominance()`, `engine_transfer.py` Jaccard. New only: the named composite + optional gated LLM "one-paragraph" probe (gate modeled on `sentiment.enabled`).

**D5 own-brand AI visibility — `already-exists` (was drafted as a full new build — the single biggest over-spec).**
- Entire system exists. Draft→real name map recorded in the spec: `ai_probe`→`ai_visibility_probes`; `ai_probe_result`→`brand_mentions`+`ai_citations`+`answer_sentiment`; `ai_visibility_daily`→`ai_visibility_index`; `prompt_templates`→`client_profiles.yml`+`profile_questions.py`; "reuse `brand_terms`"→`build_gazetteer(known_brands, analysis_data)`. Real modules: `probe_ai_visibility.py` (`ClaudeProbe/GeminiProbe/ChatGPTProbe/PerplexityProbe`), `aivi.py` (`config.yml → aivi.weights`), `brand_mentions.py`, `citation_table.py`, `answer_sentiment.py` (`sentiment.enabled`), `engine_recommendations.py`/`engine_profiles.yml`, `foundational_score.py`. Spec now says "extend only" and lists the few genuinely-new sub-items (raw-answer retention, negative-sentiment alerting).

## Compete — per-feature status & renames

**C1 AI answer share-of-voice — `new` here, but the runner lives in Discover.**
- serp-compete has **no** AI probing (only OpenAI gpt-4o in `reframe_engine.py` for Bowen reframes). Draft "reuse D5 runner" corrected to point at the real Discover modules and, per the "apps stay independent" decision, to **consume Discover's `brand_mentions`/`ai_citations` outputs** rather than fork `probe_ai_visibility.py`. Draft `competitor_set`/`competitor` tables dropped → real `competitors`/`competitor_metadata`.

**C2 barbell positioning — `partially-exists`.**
- Reuse: `tag_competitor_position()` labels (Volume Scaler / Direct Systemic / Generalist) in `competitor_metadata`; `EEATScorer`/`eeat_scores` (authority proxy); `ClusterDetector`/`cluster_results` (focus proxy). New only: combining them into a 2×2 quadrant table.

**C3 branded-demand benchmark — `new`.**
- No branded segmentation exists; `search_volume` used only generically (`infiltrator.py`, `competitor_mining.py`). Reuse `client_brand_names` (handoff) + `derive_brand_name()`. Own-site anchor = Discover D2 via handoff.

**C4 SERP overlap & differentiation gap — `partially-exists` (the tool's spine; scattered).**
- Documented three real implementations: `identify_strategic_openings()` "Systemic Vacuum" (**wired, live**), `analysis.py::AnalysisEngine.find_keyword_intersection`/`check_feasibility` (**built but never called in `run_audit()`** — wiring it in is part of the work), `competitor_mining.py` → `competitor_keyword_gap.md` (offline), `infiltrator.py` → `infil_report.md`. New only: a unified, wired who-ranks-where matrix with cell classification. Draft `serp_overlap` kept but sourced from real tables (`competitor_metrics`) + Discover D4 commodity.

**C5 off-platform attention — `new` (deferred).** Integration flag retained (only feature needing sources beyond the confirmed three). `third_party_crawlers.py` confirmed *not* a social tracker. Added the nonprofit-ROI caveat from `CLAUDE.md`.

**C6 reputation-risk radar — `partially-exists`.**
- Reuse: `get_volatility_alerts()`, `get_feasibility_drift()` (Fragile Magnet), `velocity_module.py` (`market_history`). New only: `visibility_cliff` + `parasite_subfolder`/`affiliate_arm` detection (reuse C2 cluster analysis for topical-mismatch). Clarified the only code "penalty" is the scoring penalty in `scoring_logic.py`, unrelated.

## Already-built, added as "do NOT re-propose" (Compete SC-1, shipped)

`GeoProfiler`/`geo_profiles`, `EEATScorer`/`eeat_scores`, `ClusterDetector`/`cluster_results`, the "Systemic Vacuum" core (`semantic.py`+`scoring_logic.py`+`identify_strategic_openings`), `ReframeEngine`, and the `enrichment.py` wiring/carry-forward plumbing. The revised spec frames the new comparative value as a **client-vs-competitor comparison layer** on top of these single-page engines, not the engines themselves.

## Boundary verdict (assumption confirmed)

The draft's split — **Discover = single-site**, **Compete = comparative** — **matches the real repos**; no feature was re-assigned across apps. Supporting facts:
- serp-discover's only competitor-facing code is the **handoff producer** (`handoff_writer.py::build_competitor_handoff` → `competitor_handoff_*.json`, `handoff_schema.json`) and the **client-centric** `brand_mentions` leaderboard (share-of-voice within the client's own probes) — neither is a competitor-vs-competitor comparison.
- serp-compete **ingests** that handoff (`main.py::get_latest_market_data` → `find_latest_handoff_file` → `jsonschema.validate` → `convert_handoff_to_targets`) and does the comparative work.
- The one cross-app dependency to make explicit: **C1 (SoV) and C3 (branded anchor) consume Discover outputs**; C1's probe runner is not duplicated in Compete.

## Owner decisions applied (2026-07-22)

- **C1 integration path — DECIDED: consume.** Compete reads Discover's `brand_mentions`/`ai_citations` outputs (new optional input path in `shared_config.json`, `data_available: false` when absent) and adds only the comparative share layer. The runner is not forked. The "port the runner" alternative is recorded as rejected-for-traceability in the spec.
- **C5 off-platform attention — DEFERRED (future todo).** Not built this pass; target interface retained under `SC-7` with an explicit status banner and revisit trigger (owner wants cross-platform tracking + provider budget approved). Blocker is data access beyond the three confirmed sources, not effort.

## Open items still outstanding

- No `config_version` exists in either repo; if per-run config stamping is required, adopt the existing `weights_json`-column pattern rather than a global stamp.
- C1 "consume" path assumes Discover exports its `brand_mentions`/`ai_citations` (or analysis JSON) in a location Compete can read; the exact export shape is a small follow-up to pin down when C1 is built.
