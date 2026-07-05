# Configuration reference — config.yml keys and rule files

**`config.yml`** — all operational settings:
- `serpapi.*` — API params (engine, location, pagination, retries, modes)
- `files.*` — input/output file paths (auto-updated by GUI after each run)
- `enrichment.*` — URL enrichment settings (`eeat_scan_chars` — how many leading body-text characters are scanned for author credentials and review markers, default 8000; see seo_geo_deferred G.3)
- `app.*` — API mode flags (`balanced_mode`, `deep_research_mode`)
- `moz.cache_ttl_days` — DA cache lifetime in days (default 30)
- `feasibility.*` — DA gap thresholds, client DA, neighbourhoods, pivot settings
- `audit_targets.n` — top-N organic URLs per keyword exported to competitor handoff (default 10)
- `audit_targets.omit_from_audit` — domains excluded from the handoff (never sent to Tool 2)
- `client.preferred_intents` — intents the client can produce content for; drives `mixed_intent_strategy`
- `analysis_report.*` — client context injected into LLM prompts
- `report_thresholds.entity_dominance.*` — thresholds for interpreting SERP entity type dominance in reports (see RC.6)
- `geo.outreach_entity_types` — entity types treated as brand-placement (outreach) surfaces in the AI Overview citation analysis, as opposed to competitor counselling sites (see seo_geo_review T.3)
- `situational_probes.*` — "S"-label conversational query probes (see seo_geo_deferred T.5). **Paid feature, off by default.** `enabled` (default `false`; Deep Research mode turns it on, Low API mode always turns it off), `max_probes_per_run` (default 6 — the hard per-run SerpAPI call cap, decision gate D-1), `probes_per_keyword` (default 2), `keywords` (`priority` = probe in strategic_flags order from the last analysis JSON; `all` = keyword CSV order). Probe query templates are editorial and live in `serp_vocab.yml situational_templates`.
- `ai_visibility.*` — AI-engine mention probing (`probe_ai_visibility.py`; see seo_geo_deferred G.1, decision gate D-2). **Paid feature, cost-guarded:** the script makes zero API calls unless run with `--yes` or `assume_yes: true`. Keys: `engines` (default `[claude, gemini]` — which assistants to probe; `--engines` overrides per run), `claude_model` / `gemini_model` (model ids — never hardcoded in Python), `claude_web_search_tool` (Anthropic web-search tool type matching the chosen Claude model), `max_questions` (default 20 — cap **per engine**; total calls = questions × engines), `assume_yes` (default `false`), `history_runs` (default 5 — how many prior runs the trend table shows), `geo_context` (sentence prefixed to every question so answers are location-realistic). Gemini requires the optional `GEMINI_API_KEY` env var; when missing the engine is skipped with a warning.
- `bing_check.*` — Bing secondary-index visibility check (see seo_geo_deferred G.5). **Paid feature, off by default** (decision gate D-4): `enabled` (default `false`), `num` (default 20 — Bing results requested per keyword). When enabled, one SerpAPI `engine=bing` call per root keyword records the client's Bing rank next to its Google rank (ChatGPT search grounds substantially on Bing).
- `gsc.*` — Google Search Console integration (`run_gsc_analysis.py`; see seo_geo_deferred G.4, decision gate D-3). Free first-party data, but `enabled` defaults to `false` until the service-account grant is in place (`GSC_CREDENTIALS_PATH` env var + the service-account email added to the Search Console property — setup steps in `docs/USER_MANUAL.md`). Keys: `property` (default `sc-domain:livingsystems.ca`), `lookback_days` (default 90 — the Search Analytics window), `cache_ttl_days` (default 7 — SQLite `gsc_cache` lifetime), `feed_strategic_flags` (default `false` — when true, the content brief attaches the latest `gsc_analysis_*` sidecar to the LLM payload as `gsc_summary`; the prompt treats those numbers as client-private).

**`domain_overrides.yml`** — manual entity type overrides (e.g., `psychologytoday.com: directory`).

**`intent_mapping.yml`** (spec v2) — rule table mapping `(content_type, entity_type, local_pack, domain_role)` → SERP intent (informational / commercial_investigation / transactional / navigational / local / uncategorised). First-match-wins, top of file = highest priority. Edit this file to refine intent assignments — don't push exceptions into Python.

**`url_pattern_rules.yml`** — URL-path fallback rules for pages the HTML enricher couldn't classify. Edit to improve classification rates without touching Python.

**`serp_vocab.yml`** — editorial SERP-audit vocabulary: n-gram stop words, PAA category triggers (Commercial/Distress/Reactivity), service-like tokens, the AI-alternative query templates, the `situational_templates` section (situation-style probe query templates with `{base}`/`{topic}`/`{city}` placeholders — keep each 6+ words; see seo_geo_deferred T.5), and the `eeat_signals` section (E-E-A-T author-signal vocab: `credential_tokens` — professional designations like RCC/MSW/"registered clinical counsellor" that mark a byline as credentialed, and `review_markers` — "medically reviewed"-style phrases; see seo_geo_deferred G.3). Note: the shared config's `stop_words` (out-of-repo, see "Shared config" below) still overrides the stop-word list when present.

**`strategic_patterns.yml`** — Bowen theory strategic pattern definitions. Each entry has `Pattern_Name`, `Triggers` (list), `Status_Quo_Message`, `Bowen_Bridge_Reframe`, and `Content_Angle`. A pattern fires when any trigger word appears as a whole word in the run's SERP ngram corpus. Add new patterns by appending entries; no Python changes required.

**`play_routing.yml`** — the **Recommended Play** taxonomy (rank-vs-citation two-score model; seo_geo_review T.4). Vocabulary block consumed by the report renderers and the brief validator: `play_labels` (machine token → human label, e.g. `extraction_play: "Extraction Play"`), `play_success_metric` (token → success metric surfaced in the brief's Section 7), and `play_claim_phrases` (token → extra regexes counted as the brief *asserting* a play, used only for contradiction detection). Edit the labels/metrics here — do not hardcode the play taxonomy in Python. The **routing rules** that decide which play each keyword receives live under `routing:` in the same file (owned by the recommended_play producer). Chip C reads only the vocabulary block; a missing/broken file degrades gracefully to an empty vocab (the play columns render `—`).

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
    "score_normaliser": 30.0
  },
  "filtering": {
    "omitted_domains_path": "omitted_domains.txt"
  }
}
```

| Key | Consumed by | Overrides |
|-----|-------------|-----------|
| `stop_words` | `serp_audit.py` n-gram corpus | `serp_vocab.yml stop_words` |
| `client.da` | feasibility scoring | `config.yml feasibility.client_da` |
| `client.domain` | client visibility detection | `config.yml analysis_report.client_domain` |
| `client.location` | hyper-local pivot text | `config.yml feasibility.non_profit_location` |
| `technical.feasibility_threshold` | `feasibility.py` High/Moderate cut | code default 5 |
| `technical.moderate_feasibility_max_gap` | `feasibility.py` Moderate/Low cut | code default 15 |
| `technical.score_normaliser` | `feasibility.py` score scaling | code default 30.0 |
| `filtering.omitted_domains_path` | domain exclusion list (path relative to the shared config's directory) | code default `omitted_domains.txt` |

**Precedence:** shared config > `config.yml` > `serp_vocab.yml` defaults (stop words) / code defaults (thresholds). Do not remove the file's authority — Tool 2 reads the same file (decision gate D-5).

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
| Config Settings | `config.yml` | Edit operational settings (API keys, file paths, thresholds, client preferences). |
| Domain Overrides | `domain_overrides.yml` | View/edit/add/delete domain → entity-type manual overrides. |
| Classification Rules | `classification_rules.json` | View/edit entity-type list and entity-type descriptions. Double-click descriptions to edit. |
| URL Pattern Rules | `url_pattern_rules.yml` | View/edit/add/delete URL fallback patterns (regex → content type). |

**Features:**
- **Validation before save:** All files validated for schema errors and cross-file constraints. Errors shown with field-level detail.
- **Backup and restore:** Save automatically backs up current files before writing. If save fails, original files restored.
- **Help on every field:** Click `?` button next to any field to see contextual help explaining what it means and why it matters.
- **CRUD operations:** Add new entries, edit existing ones, delete, and reorder (for order-sensitive files like intent_mapping.yml).
- **Discard changes:** Cancel button lets you abandon edits and return to saved state.

For detailed help, see `docs/config_manager_phase5_completion_20260502.md`.
