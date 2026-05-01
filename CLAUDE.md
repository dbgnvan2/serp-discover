# SERP Intelligence Tool

Market intelligence tool for Living Systems Counselling (livingsystems.ca),
a Bowen Family Systems Theory nonprofit in North Vancouver, BC. Scrapes
Google SERPs via SerpAPI, generates content briefs via Anthropic API, scores
keyword feasibility via Domain Authority gap analysis.

## Always do this

- **Activate venv first**: `source venv/bin/activate` before any Python
  command. Tests and scripts will fail in confusing ways without it.
- **Run tests with**: `python3 -m pytest test_*.py -q`
  (expects 369 passing, 5 skipped, 0 errors).
- **Never `git add .`** — the repo accumulates output and draft files that
  must stay local. Only commit files intentionally changed for the current
  chunk.
- **Push after each logical chunk** of work (feature module + tests,
  validation rule + tests, doc update). Don't accumulate sweeping diffs.
- **Edit configuration, not Python.** Intent rules belong in
  `intent_mapping.yml`, entity overrides in `domain_overrides.yml`, client
  context in `config.yml`. Do not push exceptions or hardcoded values into
  `.py` files.

## Required env vars (in `.env`)

- `SERPAPI_KEY` — required for SERP fetching.
- `ANTHROPIC_API_KEY` — required for content brief generation.
- `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` — primary DA provider
  (pay-per-use).
- `MOZ_TOKEN` — fallback DA provider (free tier: 50 rows/month).

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

## Spec traceability for this project

This project uses spec IDs throughout. When working from a spec:

- The `serp_tools_upgrade_spec_v2.md` and follow-up fix specs live in
  the repo root (not `docs/specs/`).
- Code that implements a spec criterion includes a `Spec:` reference in
  its docstring per the user-level workflow rules.
- After any spec-driven change, regenerate `docs/spec_coverage.md` to
  reflect current implementation status.
