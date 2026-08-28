# SERP Intelligence Tool

## Global standards

Read the relevant file from `~/.claude/standards/` before starting work:

| Standard | When |
|---|---|
| `learnings.md` | Any data-path, fetch, scoring, or report code — P1–P10 checklist |
| `external-api.md` | Any call to SerpAPI, DataForSEO, Moz, Anthropic, or other HTTP endpoints |
| `llm-integration.md` | Any change to prompt building, LLM validation logic, or model selection |
| `security.md` | Secrets in `.env`, input validation, HTTPS |
| `file-maintainability.md` | Any new module or significant refactor |
| `ui-regression.md` | Any change to the tkinter GUI |



Market intelligence tool for Living Systems Counselling (livingsystems.ca),
a Bowen Family Systems Theory nonprofit in North Vancouver, BC. Scrapes
Google SERPs via SerpAPI, generates content briefs via Anthropic API, scores
keyword feasibility via Domain Authority gap analysis.

## Always do this

- **Activate venv first**: `source venv/bin/activate` before any Python
  command. Tests and scripts will fail in confusing ways without it.
- **Run tests with**: `python3 -m pytest test_*.py tests/ -q`
  (currently 476 passing, 27 skipped). Note: skipped tests are GUI tests requiring
  tkinter (not available in venv, but run when tkinter is available).
- **Never `git add .`** — the repo accumulates output and draft files that
  must stay local. Only commit files intentionally changed for the current
  chunk.
- **Push after each logical chunk** of work (feature module + tests,
  validation rule + tests, doc update). Don't accumulate sweeping diffs.
- **Document new functionality in `docs/USER_MANUAL.md`**: When adding new
  features or modifying user-facing behavior, update the manual to explain
  WHAT the feature does and WHY it matters. Use clear examples. Example: when
  implementing report ranking (feasibility > intent > confidence), explain
  each metric (Domain Authority gap, SERP intent classification), why each
  factor matters for keyword prioritization, and how they interact. Users
  should understand not just the feature, but the reasoning behind it.
- **Separate business logic tests from UI tests**: Business logic (data loading,
  validation, structure) should NOT require GUI frameworks. Only skip tests that
  actually need widget interaction. This prevents hidden bugs from going untested.
  Example: Don't skip "test that validates loaded data" just because treeview
  rendering isn't available — that test has nothing to do with the UI.
  
  **GUI Initialization Testing**: When adding new Tkinter tabs to ConfigManager,
  use source code inspection tests (no tkinter required) to catch initialization
  order bugs (e.g., initializing attributes AFTER super().__init__() call).
  See `tests/test_config_manager.py::TestTabInitializationOrder::test_tab_classes_have_instance_variables`.
  This catches patterns that would otherwise silently pass in venv but fail at runtime.

## Required env vars (in `.env`)

- `SERPAPI_KEY` — required for SERP fetching.
- `ANTHROPIC_API_KEY` — required for content brief generation.
- `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` — primary DA provider
  (pay-per-use).
- `MOZ_TOKEN` — fallback DA provider, and the credential for the full Moz
  Data API (`api.moz.com/jsonrpc`). The account is the **Starter Medium**
  API plan, *not* the free tier. The real row allowance is read at runtime
  via `quota.lookup` (`moz_jsonrpc.quota_lookup`) and recorded in
  `config.yml` as `moz.rows_per_month` — never hardcode a plan figure.
- `GEMINI_API_KEY` — **optional**; enables the Gemini engine in
  `probe_ai_visibility.py` (G.1). Missing key = engine skipped with a
  warning, never an abort.
- `GSC_CREDENTIALS_PATH` — **optional**; path to the Google Search Console
  service-account JSON key used by `run_gsc_analysis.py` (G.4).

Tests do not require API keys — all external calls are mocked.

## Output naming

`market_analysis_{topic}_{YYYYMMDD_HHMM}.{json,xlsx,md}` plus
`competitor_handoff_{topic}_{YYYYMMDD_HHMM}.json`.

Topic slug derives from the keyword CSV filename (lowercase, spaces →
underscores). The GUI auto-updates `config.yml` with the latest paths.

## Configuration files

- `config.yml` — operational settings. See `docs/config_reference.md` for
  the full key list.
- `domain_overrides.yml` — manual entity-type overrides
  (e.g. `psychologytoday.com: directory`).
- `intent_mapping.yml` — SERP intent rule table (spec v2). First-match-wins,
  top of file = highest priority. Edit this file to refine intent rules; do
  not push exceptions into Python.
- `clinical_dictionary.json` — Bowen vs medical-model vocabulary tiers.
- `strategic_patterns.yml` — Bowen pattern definitions (triggers, reframes, content angles). Add patterns here; no Python required.

## Editorial content lives in config files

Trigger words, classification rules, mapping tables, vocabulary lists,
brief routing rules, and any other content that requires editorial judgment
to refine belongs in YAML or JSON, not in Python source.

When adding a new editorial knob (a new trigger list, a new mapping table,
a new routing rule), check whether similar editorial content already exists
elsewhere in the codebase. If so, externalise the older content in the same
change. Do not leave old hardcoded content in place while new content moves to
YAML — this produces a codebase where similar things live in different places
and reviewers can't find the editorial surface.

Test for "is this editorial content?": if a non-developer reading the file
might reasonably want to change a value (a trigger word, a category label,
a routing rule), it's editorial. If only a developer would touch it (a
class structure, a function signature, an algorithm), it's code.

Editorial content currently lives in:
- `intent_mapping.yml` — SERP intent rule table
- `strategic_patterns.yml` — Bowen patterns (triggers, status quo, reframes)
- `url_pattern_rules.yml` — URL pattern fallbacks for content classifier
- `domain_overrides.yml` — manual entity-type overrides
- `classification_rules.json` — content type and entity type pattern lists (includes the `publisher` entity type + `publisher_domains` list added for the yoast_geo_upgrade Y.8 citation table; the Y.8 citation category is sourced from this file via the existing classifier, never a parallel list)
- `clinical_dictionary.json` — Bowen vs medical vocabulary tiers
- `brief_pattern_routing.yml` — brief PAA / keyword / intent-slot routing (added I.1)
- `intent_classifier_triggers.yml` — PAA External Locus / Systemic vocabularies (added I.2)
- `schema_recommendations.yml` — schema.org markup recommendations for the brief (added seo_geo_review G.2)
- `serp_vocab.yml` — SERP audit vocabulary: stop words, PAA category triggers, service tokens, AI-alternative query templates (added seo_geo_review C.4); `eeat_signals` credential tokens and review markers (added seo_geo_deferred G.3); `situational_templates` probe query templates — persona-keyed map `{persona_label: [templates...]}` supporting an optional `{service}` placeholder (added seo_geo_deferred T.5; restructured to persona-keyed by yoast_geo_upgrade Y.4)
- `play_routing.yml` — "Recommended Play" decision table: ordered, first-match-wins rules mapping pre-computed keyword signals to one of five plays (rank / extraction / reformat / local_pivot / deprioritize), plus each play's label + strategy_text (added seo_geo_review chip A)
- `engine_profiles.yml` — per-engine (chatgpt/`openai`, perplexity, gemini, claude) source-bias profiles: `retrieval_backend`, `source_bias` phrases, indicative+dated `avg_citations`, `reach_tier`/`referral_click_tier`, and the editorial `recommended_content_moves` list joined by `engine_recommendations.py` to produce per-engine "what to change here" advice. This is the ONLY place engine advice lives — no engine advice is hardcoded in Python. Vendor/temporal confidence caveat is binding: directional findings are high confidence, the numbers are indicative and shift over time — re-measure (added yoast_geo_upgrade Y.10)
- `client_profiles.yml` — per-client profile blocks (keyed by client slug) driving persona-segmented AI-visibility question generation: `brand_name`, `domain`, `location`, `primary_city`, `secondary_cities`, `service_description`, and `personas` (each with `label`, `needs`, verbatim `seed_questions`, and per-city-expanding `templates` under open, per-client funnel/intent tiers). Edited in the GUI "Client Profile & Queries" tab (added yoast_geo_upgrade Y.1 / Y.13)
- `config.yml` `moz.site_metrics.link_count_fields` — which of Moz's link-count
  fields are kept on each site-metrics result and cached (added
  moz_api_upgrade_spec_v1.md T.1). `moz.site_metrics.scope` sets the query
  scope (domain / subdomain / subfolder / url)
- `config.yml` — operational settings, including the editorial `known_brands`
  list (competitor brand names / domains) used by the Y.7 gazetteer and Y.8
  citation brand attribution; `aivi.weights` (Y.6 composite weighting, default
  equal 25% each); `brand_mentions.llm_extraction` (Y.7 gated LLM pass, OFF by
  default); `sentiment.enabled` (Y.9 gated sentiment, OFF by default);
  `foundational.weights` (Y.12 foundational readiness sub-score weighting,
  default equal thirds); and `engine_prioritization.weights` (Y.10 platform
  -prioritisation blend weights: opportunity / reach / referral)
- `brand_mentions_candidates_<topic>_<ts>.md` — **candidate-review file** (like
  `domain_override_candidates.md`): LLM-surfaced brand names not yet in
  `known_brands`, written by Y.7 for the user to promote into `known_brands`.
  No silent taxonomy growth — new brands never enter the gazetteer automatically.

When in doubt, ask the user before adding new editorial content to a `.py` file.

## Reference documentation

For details, read these as needed (do not preload):

- `docs/architecture.md` — module map and data flow diagram.
- `docs/database.md` — SQLite schema and tables.
- `docs/api_modes.md` — Low API / Balanced / Deep Research modes.
- `docs/feasibility.md` — DA scoring thresholds and pivot logic.
- `docs/spec_v2_fields.md` — pre-computed `serp_intent`, `title_patterns`,
  `mixed_intent_strategy` fields and their validators.
- `docs/gui_steps.md` — `serp-me.py` GUI step reference.
- `docs/intent_classification.md` — PAA External Locus / Systemic / General
  tagging.
- `docs/config_reference.md` — `config.yml` keys.

## LLM validation policy

`generate_content_brief.py` validates LLM outputs before writing:

- **HARD-fail (abort)**: AI Overview count mismatch versus extracted data;
  `serp_intent.primary_intent` or `is_mixed` contradictions.
- **SOFT-fail (1 retry)**: wording issues, `title_patterns.dominant_pattern`
  contradictions, `mixed_intent_strategy` contradictions. Retry uses the
  correction prompt.
- Failed validations are written to `*.validation.md` for inspection.

`test_validation_consistency.py` is a canary that scans the prompt files
for `keyword_profiles.<field>` references and asserts each has a
corresponding rule in `validate_llm_report`. Run it after adding any new
pre-computed field to a keyword profile to catch missed validators early.

## Methodology doc is a contract

When modifying any file referenced in `docs/methodology.md`, update that doc
in the same change. The methodology doc is part of the contract, not a side
artifact — it must stay in sync with the code it describes.

## Spec traceability for this project

This project uses spec IDs throughout. When working from a spec:

- The `serp_tools_upgrade_spec_v2.md` and follow-up fix specs live in
  the repo root (not `docs/specs/`).
- Code that implements a spec criterion includes a `Spec:` reference in
  its docstring per the user-level workflow rules.
- After any spec-driven change, regenerate `docs/spec_coverage.md` to
  reflect current implementation status.
