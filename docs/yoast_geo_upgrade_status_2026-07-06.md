# Yoast GEO Upgrade — Phase A status (2026-07-06)

Spec: `yoast_geo_upgrade_spec_v1.md`. Phase A only (Y.1 → Y.4 → Y.13). Decision
gates use the spec's recommended defaults (Y-D1 = augment; Y-D5 = shared
per-client `client_profiles.yml`). All external/API calls in tests are mocked
or unused; the feature makes **no** network call (deterministic template
filling). Baseline suite before Phase A: 741 passed, 94 skipped, 1 error
(pre-existing tkinter collection error in `test_serp_launcher.py`, environment
lacks tkinter). After Phase A: **781 passed, 94 skipped, 1 (same) error.**

## Acceptance criteria → tests

### Y.1 — Client profile → persona-segmented question generation
Files: `client_profiles.yml` (new), `profile_questions.py` (new),
`tests/test_profile_questions.py` (new); docs + CLAUDE.md editorial list.

| Criterion | Coverage |
|---|---|
| Y.1.1 loader keyed by slug; missing/malformed warns → `{}` | `test_profile_questions.py::TestLoader` (4 tests) |
| Y.1.2 deterministic `{question,persona,city,intent}`; synthetic 2p/2t/2c count | `TestSyntheticCount` (3 tests) |
| Y.1.2a seed_questions verbatim; `{city}` in a seed is literal | `TestLivingSystemsDefault::test_seed_questions_verbatim_and_unmodified`, `::test_seed_with_city_placeholder_is_literal` |
| Y.1.2b local tier → cities + near-me + de-localised; informational never city-suffixed | `TestLivingSystemsDefault::test_local_transactional_expands_cities_nearme_delocalised`, `::test_informational_tier_never_city_suffixed` |
| Y.1.3 graceful degradation (no templates / empty secondary_cities / missing service) | `TestGracefulDegradation` (4 tests) |
| Y.1.4 editorial-listed in CLAUDE.md; every field in config_reference.md | CLAUDE.md editorial list + `docs/config_reference.md` `client_profiles.yml` block |
| Y.1.5 USER_MANUAL WHAT + WHY | `docs/USER_MANUAL.md` "Client profiles and persona-segmented questions" |

### Y.4 — Persona axis for situational templates
Files: `serp_vocab.yml` (restructured), `query_variants.py`
(`flatten_situational_templates` + `{service}` in `situational_template_probes`),
callers `serp_audit.py` / `probe_ai_visibility.py`,
`tests/test_persona_templates.py` (new); updated `tests/test_situational_probes.py`,
`tests/test_serp_vocab.py`; docs + CLAUDE.md.

| Criterion | Coverage |
|---|---|
| Y.4.1 no profile expands all blocks; superset of old flat list | `test_persona_templates.py::TestFlattenBackwardCompat` (4 tests) + `test_situational_probes.py` (legacy tests still green) |
| Y.4.2 fills persona templates incl. optional `{service}`, omitted cleanly | `TestServicePlaceholder` (4 tests) |
| Y.4.3 profile listing only clinician expands only clinician | `TestPersonaSelection` (3 tests) |
| Y.4.4 documented in config_reference.md + methodology.md; editorial-listed | `docs/config_reference.md`, `docs/methodology.md` (two `situational_templates` refs), CLAUDE.md |

### Y.13 — Client profile & funnel editor (ConfigManager tab)
Files: `config_manager.py` (`ClientProfileTab` + data-layer functions + tab
registration), `tests/test_client_profile_tab.py` (new), updated
`tests/test_config_manager.py` (tab count 8→9, init-order check, import); docs.

| Criterion | Coverage |
|---|---|
| Y.13.1 load→edit→save round-trip; client A edit leaves B byte-for-byte | `test_client_profile_tab.py::TestSaveRoundTrip` (2 tests) |
| Y.13.2 source-inspection init-order test (no tkinter) | `test_config_manager.py::TestTabInitializationOrder::test_tab_classes_have_instance_variables` (ClientProfileTab added) |
| Y.13.3 preview returns Y.1 questions, no network/API call | `test_client_profile_tab.py::TestPreviewNoNetwork` (4 tests) |
| Y.13.4 malformed input rejected inline, nothing written | `test_client_profile_tab.py::TestValidation` (6 tests) |
| Y.13.5 only widget-interaction tests skip when tkinter absent | tkinter-gated tests in `test_config_manager.py` carry `@pytest.mark.skipif`; data-layer tests do not require tkinter |
| Y.13.6 gui_steps.md + USER_MANUAL.md document the tab | `docs/gui_steps.md` "Configuration Manager tabs", `docs/USER_MANUAL.md` editing-in-Settings paragraph |

## Deviations / notes

- **Multi-client selector.** The multi-client docs describe a `clients/`
  directory selector, but `config_manager.py` does not implement one in code
  today (tabs read the current working directory). Per Y-D5 (shared
  `client_profiles.yml` keyed by client slug) the tab's "selected client" is a
  slug dropdown built from the file's keys — self-contained and testable, and
  consistent with "operates on the currently selected client" without
  introducing a second client concept.
- **Registries.** `client_profiles.yml` is intentionally NOT added to
  `VALIDATORS_BY_FILE` / `HELP_BY_FILE` (which the registry tests enumerate for
  the 8 raw-file tabs). The tab validates via `validate_client_profiles` /
  `validate_client_block` instead, so those tests stay green.
- **Not in Phase A:** Y.5 wiring (profile questions into the probe) is
  explicitly deferred to Phase B; methodology.md notes this.

## Commit status

Commits could not be created from the execution sandbox: git object writes
into `.git/objects` succeed but the sandbox blocks unlinking git's temp/lock
files (`.git/index.lock`, `tmp_obj_*`), so `git commit` aborts. All work is on
the working tree and the suite is green. Recommended local commits (run from a
normal terminal), one per item, staging only the listed files:

- Y.1: `client_profiles.yml profile_questions.py tests/test_profile_questions.py`
  + docs (`CLAUDE.md docs/config_reference.md docs/USER_MANUAL.md
  docs/spec_coverage.md`) — trailer `Spec: yoast_geo_upgrade_spec_v1.md#Y.1`
- Y.4: `serp_vocab.yml query_variants.py serp_audit.py probe_ai_visibility.py
  tests/test_persona_templates.py tests/test_situational_probes.py
  tests/test_serp_vocab.py` + docs (`CLAUDE.md docs/config_reference.md
  docs/methodology.md`) — trailer `Spec: yoast_geo_upgrade_spec_v1.md#Y.4`
- Y.13: `config_manager.py tests/test_client_profile_tab.py
  tests/test_config_manager.py docs/gui_steps.md docs/USER_MANUAL.md
  docs/config_reference.md docs/yoast_geo_upgrade_status_2026-07-06.md` —
  trailer `Spec: yoast_geo_upgrade_spec_v1.md#Y.13`

Do **not** `git add .` — `config.yml` and `domain_override_candidates.md` carry
pre-existing local drift that must stay local.

---

# Phase B status (2026-07-06) — Y.5

Phase B only (Y.5). Decision gate Y-D4 = hard `ai_visibility.max_total_calls`
ceiling (default 60), user-approved. Y-D1 (augment) carried from Phase A. All
external/API calls in tests are mocked; the feature makes **no** live call.
Baseline before Phase B: 781 passed, 94 skipped, 1 error (pre-existing tkinter
collection error in `test_serp_launcher.py`). After Phase B: **794 passed, 94
skipped, 1 (same) error.**

## Acceptance criteria → tests

### Y.5 — Profile questions in the probe + cross-engine share of voice
Files: `probe_ai_visibility.py` (precedence + `persona`/`source` columns +
idempotent migration + `max_total_calls` ceiling + share-of-voice section),
`config.yml` (`ai_visibility.max_total_calls`, `client_slug`),
`tests/test_ai_visibility_y5.py` (new); updated `tests/test_ai_visibility.py`
(source-label vocab, profile-neutralised `_MainRunMixin`); docs.

| Criterion | Coverage |
|---|---|
| Y.5.1 profile questions probed first, rows tagged `persona`+`source='profile'`; **no profile ⇒ current G.1 precedence (regression)** | `test_ai_visibility_y5.py::TestProfilePrecedence` (3 tests: `test_profile_questions_probed_first_and_tagged`, `test_no_profile_equals_g1_precedence`, `test_profile_rows_stored_with_persona_and_source`) + `TestProfileWiredIntoMain::test_profile_questions_used_and_persona_stored` |
| Y.5.2 `max_total_calls` ceiling: guard prints `questions × engines` + ceiling; **zero calls when over budget unless `--yes`** | `TestMaxTotalCalls::test_over_budget_plan_states_ceiling_and_makes_zero_calls`, `::test_over_budget_with_yes_stays_within_ceiling` |
| Y.5.3 share-of-voice + per-persona render with zero history and with history; competitor domains appear when cited; **caveat always present** | `TestShareOfVoiceReport` (4 tests) |
| Y.5.4 idempotent column migration; pre-existing DB without columns upgraded once; old rows read back `NULL` | `TestColumnMigration` (3 tests) |
| Y.5.5 USER_MANUAL WHAT (share of voice + per persona) + WHY (visibility is comparative); config_reference documents `max_total_calls`/`client_slug` + new columns; methodology.md updated | `docs/USER_MANUAL.md` "AI-engine visibility probe" section, `docs/config_reference.md` `ai_visibility.*`, `docs/methodology.md` "AI-engine mention probing" |

## Deviations / notes

- **Detection unchanged.** Y.5 reuses `detect_visibility`
  (`mentioned`/`cited`/`competitors_cited`) verbatim; no detection logic moved.
  The share-of-voice section is a pure read-side aggregation over stored rows.
- **Source-label vocab.** The stored `source` values are the spec's exact set
  `profile|situational|paa|template`; the pre-Y.5 in-memory label
  `situational_probe` was renamed to `situational` to match, and the two
  affected assertions in `test_ai_visibility.py::TestQuestionSources` were
  updated (no behavioural change).
- **`_MainRunMixin` neutralised.** The pre-Y.5 end-to-end tests assert the G.1
  precedence, so they now patch `load_client_profiles` to `{}` — this *is* the
  Y.5.1 "no profile ⇒ G.1 behaviour" contract exercised through `main()`.
- **Ceiling behaviour.** When `questions × engines` exceeds `max_total_calls`
  the question set is truncated to `max_total_calls // engines` so the ceiling
  is never breached; over-budget without `--yes` still makes zero calls (cost
  guard runs after truncation, before probe construction).

## Commit status

Same sandbox git limitation as Phase A (`.git/index.lock` cannot be removed).
All work is on the working tree; suite green. Recommended local commit (one),
staging only these files:

- Y.5: `probe_ai_visibility.py config.yml tests/test_ai_visibility_y5.py
  tests/test_ai_visibility.py` + docs (`docs/USER_MANUAL.md
  docs/config_reference.md docs/methodology.md docs/spec_coverage.md
  docs/yoast_geo_upgrade_status_2026-07-06.md`) — trailer
  `Spec: yoast_geo_upgrade_spec_v1.md#Y.5`

Do **not** `git add .` — `config.yml` carries pre-existing local drift; stage
it explicitly (only the `ai_visibility.max_total_calls` / `client_slug`
additions here) or split those two keys into their own hunk.

---

# Phase C status (2026-07-06) — Y.2 (OpenAI/ChatGPT) + Y.3 (Perplexity)

Phase C only (Y.2 → Y.3). Decision gates **Y-D2** (add OpenAI, web-search
endpoint), **Y-D3** (add Perplexity, Sonar w/ citations), **Y-D9** (default
engines gemini + openai + perplexity ON, claude available-but-not-default) —
all user-approved recommended defaults. Every engine still runs only if its
API key is present; a missing key skips it with a logged warning, never an
abort (identical to the Gemini contract). All external/API calls in tests are
mocked; the feature makes **no** live call — no live probe was issued to
OpenAI or Perplexity during implementation.

Baseline before Phase C: 794 passed, 94 skipped, 1 error (pre-existing tkinter
collection error in `test_serp_launcher.py`). After Phase C: **823 passed, 94
skipped, 1 (same) error** (+29 new tests).

## API-shape verification (before coding)

Confirmed against each vendor's current (2026-07) docs via web search (no live
API calls):

- **OpenAI (Y.2):** the **Responses API** (`POST /v1/responses`) exposes web
  search via the `web_search` tool. Inline citations are `url_citation`
  annotation objects (each carrying `url` + `title`) on the `output_text`
  content of the assistant `message` item; the full consulted-source list is
  available on the `web_search_call` item's `action.sources`. `ChatGPTProbe`
  parses both, plus a flat `output_text` convenience field as a fallback.
- **Perplexity (Y.3):** the **OpenAI-compatible** `POST /chat/completions`
  endpoint with a **Sonar** model returns the answer in
  `choices[0].message.content`, a top-level `search_results` array (objects
  with `title`/`url`), and a `citations` array (URL strings). `PerplexityProbe`
  maps `search_results` URLs first, then merges the flat `citations` list
  (de-duplicated) into `source_urls`.

**Limitation noted (not faked):** citation availability can vary by account
tier and by model. Endpoints, tool names, and model ids are all
config-parameterised (`openai_endpoint`/`openai_web_search_tool`/`openai_model`,
`perplexity_endpoint`/`perplexity_model`) so the parser tracks the live surface
without a code change; on a tier that returns no citations the probe still
measures `mentioned` correctly and the citation-based `cited` reads as absent,
never fabricated. No new SDK was added — both probes use `requests` +
`http_retry`, so `requirements.txt` is unchanged.

## Acceptance criteria → tests

### Y.2 — OpenAI / ChatGPT probe engine
Files: `probe_ai_visibility.py` (`"openai"` in `VALID_ENGINES`, `ChatGPTProbe`,
`build_probes` branch, `DEFAULT_OPENAI_*` constants), `config.yml`
(`ai_visibility.openai_model`/`openai_endpoint`/`openai_web_search_tool`, new
default engine list), `tests/test_ai_visibility_y2_y3.py` (new).

| Criterion | Coverage |
|---|---|
| Y.2.1 all calls mocked; detection mentioned-only / cited / neither / competitor-cited on `ChatGPTProbe` output | `TestChatGPTProbeParsing` (4) + `TestChatGPTDetection` (4) |
| Y.2.2 `--engines openai` runs only `ChatGPTProbe`; missing `OPENAI_API_KEY` skips w/ warning, others complete | `TestMainSingleNewEngine::test_engines_openai_runs_only_chatgpt`, `::test_missing_openai_key_skips_but_run_completes_with_message`, `::test_missing_perplexity_key_skips_openai_completes`; `TestBuildProbesNewEngines::test_missing_openai_key_skips_with_warning_others_complete`; `TestResolveNewEngines` |
| Y.2.3 rows written `engine='openai'` + configured model id; per-engine trend ordered | `TestNewEnginePersistence` (2); `TestMainSingleNewEngine::test_engines_openai_runs_only_chatgpt` (report shows `| openai | gpt-4o |`) |
| Y.2.4 `config.yml` gains `openai_model` (+ endpoint keys); docs document engine + tier limitation | `TestDocs`; `docs/config_reference.md`, `docs/USER_MANUAL.md`, `docs/methodology.md` |

### Y.3 — Perplexity probe engine
Files: `probe_ai_visibility.py` (`"perplexity"` in `VALID_ENGINES`,
`PerplexityProbe`, `build_probes` branch, `DEFAULT_PERPLEXITY_*` constants),
`config.yml` (`ai_visibility.perplexity_model`/`perplexity_endpoint`),
`tests/test_ai_visibility_y2_y3.py`.

| Criterion | Coverage |
|---|---|
| Y.3.1 all calls mocked; detection four shapes incl. citation-URL mapping | `TestPerplexityProbeParsing` (4, incl. `test_flat_citations_list_merged_and_deduped`) + `TestPerplexityDetection` (4, incl. `test_cited_via_citation_mapping`, `test_competitor_cited_via_citation_mapping`) |
| Y.3.2 `--engines perplexity` runs only `PerplexityProbe`; missing `PERPLEXITY_API_KEY` skips; others complete | `TestMainSingleNewEngine::test_engines_perplexity_runs_only_perplexity`, `::test_missing_perplexity_key_skips_openai_completes`; `TestBuildProbesNewEngines::test_missing_perplexity_key_skips_with_warning_others_complete` |
| Y.3.3 rows written `engine='perplexity'` + configured model id; per-engine trend ordered | `TestNewEnginePersistence` (2); `TestMainSingleNewEngine::test_engines_perplexity_runs_only_perplexity` (report shows `| perplexity | sonar |`) |
| Y.3.4 `config.yml` gains `perplexity_model`; docs updated as in Y.2.4 | `TestDocs`; `docs/config_reference.md`, `docs/USER_MANUAL.md`, `docs/methodology.md` |

## Deviations / notes

- **Detection unchanged.** Y.2/Y.3 add only engine probes; `detect_visibility`
  (`mentioned`/`cited`/`competitors_cited`) is reused verbatim, as required.
- **Default engine list changed (Y-D9).** `DEFAULT_ENGINES` and
  `config.yml ai_visibility.engines` are now `[gemini, openai, perplexity]`.
  Three existing assertions in `test_ai_visibility.py` that hard-coded the old
  `[claude, gemini]` default were updated (config block, `resolve_engines(None,
  {})`, and the new-key presence checks). The `_MainRunMixin`-based tests pass
  explicit `engines` in their config, so they were unaffected.
- **No new dependency.** Both probes use REST via `requests` + `http_retry`
  (the Gemini pattern), so `requirements.txt` is unchanged.

## Commit status

Same sandbox git limitation as Phases A/B — git is blocked; all work is on the
working tree, suite green. Recommended local commit (one), staging only these
files:

- Y.2/Y.3: `probe_ai_visibility.py config.yml
  tests/test_ai_visibility_y2_y3.py tests/test_ai_visibility.py` + docs
  (`docs/USER_MANUAL.md docs/config_reference.md docs/methodology.md
  docs/spec_coverage.md docs/yoast_geo_upgrade_status_2026-07-06.md`) — trailer
  `Spec: yoast_geo_upgrade_spec_v1.md#Y.2 #Y.3`

Do **not** `git add .` — stage `config.yml` explicitly (only the
`ai_visibility` engine-list + openai/perplexity key additions).

---

# Phase D status (2026-07-06) — Y.7 → Y.8 → Y.9 → Y.6 (report enrichment)

Spec: `yoast_geo_upgrade_spec_v1.md`. Phase D only, implemented in that order
(leaderboard → citations → sentiment → AIVI-last, because AIVI consumes the
other three axes). Decision gates use the spec's user-approved recommended
defaults: **Y-D6** AIVI axis weights equal 25% each in `config.yml aivi.weights`
(never hardcoded); **Y-D7** brand-entity extraction (Y.7) and sentiment (Y.9)
may use an LLM but the LLM output is a MEASURED INPUT stored verbatim while
Python computes every count/rank/percentage — a deterministic gazetteer pass
runs first and the LLM is OFF by default; **Y-D8** sentiment OFF by default
(`sentiment.enabled: false`), reuses the already-fetched answer, capped by
`max_total_calls`. All LLM/API calls in tests are mocked; brand-LLM and
sentiment default OFF so a normal run makes **zero** new calls.

Baseline suite before Phase D: **823 passed, 94 skipped, 1 error**
(pre-existing tkinter collection error in `test_serp_launcher.py`). After
Phase D: **872 passed, 94 skipped, 1 (same) error** (+49 tests).

## Acceptance criteria → tests

### Y.7 — Competitor mention leaderboard (brand-entity extraction)
Files: `brand_mentions.py` (new), `tests/test_brand_mentions.py` (new),
`probe_ai_visibility.py` (`run_report_enrichment` wiring + report section),
`config.yml` (`brand_mentions.llm_extraction`/`llm_model`); docs + CLAUDE.md.

| Criterion | Coverage |
|---|---|
| Y.7.1 gazetteer deterministic + case-insensitive, no LLM | `TestGazetteer::test_gazetteer_deterministic_case_insensitive`, `::test_gazetteer_word_boundary` |
| Y.7.2 LLM pass mocked, merged/de-duped, unknowns→candidates; `llm_extraction:false` skips | `TestLLMPass` (4); `TestCandidatesFile`; `test_probe_enrichment.py::test_leaderboard_gazetteer_only_and_persisted`, `::test_brand_llm_surfaces_candidates_file` |
| Y.7.3 ranking, client-rank, "not mentioned", deterministic ties | `TestRankingAndClientRank` (3) |
| Y.7.4 table idempotent, per-engine, UTC ts, trend ordered | `TestPersistence::test_table_idempotent_per_engine_trend` |
| Y.7.5 candidates file listed; USER_MANUAL WHAT/WHY; promotion path in config_reference | `TestCandidatesFile`; CLAUDE.md editorial + candidate-review entry; `docs/USER_MANUAL.md`; `docs/config_reference.md` `known_brands` promotion note |

### Y.8 — Categorized, brand-attributed citation table
Files: `citation_table.py` (new), `tests/test_citation_table.py` (new),
`classification_rules.json` (+`publisher` entity type + `publisher_domains`),
`classifiers.py` (publisher branch), `probe_ai_visibility.py` wiring; docs.

| Criterion | Coverage |
|---|---|
| Y.8.1 category from EXISTING classifier (publisher + directory) | `TestCategoryFromExistingClassifier` (2) — `wikipedia.org`→`publisher`, `psychologytoday.com`→`directory` via the classifier |
| Y.8.2 brand attribution gazetteer/domain; unknown→null; client flagged | `TestBrandAttribution` (2) |
| Y.8.3 URL de-dup with cite_count; tracking params preserved | `TestDedupAndTrackingParams::test_dedup_cite_count_and_tracking_params_preserved` |
| Y.8.4 table idempotent, per-engine, UTC ts | `TestPersistence::test_table_idempotent_per_engine` |
| Y.8.5 added category label in editorial files; methodology + USER_MANUAL updated | CLAUDE.md editorial `classification_rules.json` note; `docs/methodology.md`; `docs/USER_MANUAL.md` outreach use |

### Y.9 — Per-brand sentiment + aspect-keyword extraction
Files: `answer_sentiment.py` (new), `tests/test_answer_sentiment.py` (new),
`probe_ai_visibility.py` wiring, `config.yml` (`sentiment.enabled`/`llm_model`);
docs.

| Criterion | Coverage |
|---|---|
| Y.9.1 disabled by default → zero calls, "not measured", Y.6 renormalises | `TestGating` (3); `test_probe_enrichment.py::test_sentiment_disabled_zero_calls_and_axis_na` |
| Y.9.2 enabled+mocked → Python computes % positive; polarity bucketed | `TestClassificationAndPercent` (3) |
| Y.9.3 aspect phrases verbatim; empty handled | `TestAspectsVerbatim` (2) |
| Y.9.4 calls counted against budget | `TestBudget::test_call_budget_enforced`; `test_probe_enrichment.py::test_sentiment_enabled_counts_calls` |
| Y.9.5 USER_MANUAL WHAT/WHY + accuracy caveat; methodology updated | `docs/USER_MANUAL.md` sentiment subsection (caveat); `docs/methodology.md` |

### Y.6 — AI Visibility Index (AIVI) composite
Files: `aivi.py` (new), `tests/test_aivi.py` (new), `probe_ai_visibility.py`
wiring + AIVI-first report section, `config.yml` (`aivi.weights`); docs.

| Criterion | Coverage |
|---|---|
| Y.6.1 deterministic; all-zero→0, all-max→100, mixed hand-computed | `TestComputeAivi` (4) |
| Y.6.2 sentiment OFF → axis n/a, weights renormalised, still 0–100 | `TestSentimentNa` (2); `test_probe_enrichment.py::test_sentiment_disabled_zero_calls_and_axis_na` |
| Y.6.3 weights from config; changing changes score; malformed→equal+warn | `TestWeights` (3) |
| Y.6.4 table idempotent, UTC ts+engine, trend ordered, prior-run delta | `TestPersistence::test_table_idempotent_trend_and_delta` |
| Y.6.5 USER_MANUAL each axis + weighting + trend rationale; methodology updated | `docs/USER_MANUAL.md` AIVI subsection; `docs/methodology.md` |

## Deviations / notes

- **`publisher` category (Y.8).** The Yoast-observed `Publisher` category was
  absent from the classifier, so a `publisher` entity type + a
  `publisher_domains` list were added to `classification_rules.json` and a
  branch to `classifiers.py:EntityClassifier` — the citation category is sourced
  from the existing classifier, never a parallel list. The classifier's
  soup-less "not determined" sentinel (`N/A`) maps to the Yoast-style `other`
  bucket for the citation table.
- **`known_brands` left empty.** It ships `[]`; the gazetteer still works from
  the analysis-JSON competitors. Populating it is an editorial (user) decision;
  the candidate-review file is the promotion path.
- **No new engine calls.** Y.6–Y.8 are pure read-side aggregation of the
  answers already fetched; only Y.9 (opt-in, OFF by default) can spend, and it
  is capped by `max_total_calls`. No new dependency.
- **Answer text retained in memory only.** `run_engine_probes` now carries
  `answer_text`/`source_urls` on the in-memory rows for the enrichment modules;
  the persisted `ai_visibility_probes` schema is unchanged (still stores the
  400-char `answer_excerpt`).

## Commit status

Git is blocked in this sandbox — all work is on the working tree, suite green
(872 passed). Recommended local commit (one), staging only these files:

- Y.7/Y.8/Y.9/Y.6: `brand_mentions.py citation_table.py answer_sentiment.py
  aivi.py probe_ai_visibility.py classifiers.py classification_rules.json
  config.yml tests/test_brand_mentions.py tests/test_citation_table.py
  tests/test_answer_sentiment.py tests/test_aivi.py tests/test_probe_enrichment.py`
  + docs (`CLAUDE.md docs/USER_MANUAL.md docs/config_reference.md
  docs/methodology.md docs/spec_coverage.md
  docs/yoast_geo_upgrade_status_2026-07-06.md`) — trailer
  `Spec: yoast_geo_upgrade_spec_v1.md#Y.7 #Y.8 #Y.9 #Y.6`

Do **not** `git add .` — stage `config.yml` explicitly (only the `aivi`,
`brand_mentions`, `sentiment` blocks were added).

---

## Phase E — engine strategy (Y.12 → Y.10 → Y.11), implemented 2026-07-06

Pure read-side aggregation of already-collected signals; **zero new engine
calls**. Wired into `probe_ai_visibility.run_report_enrichment` after the Phase
D metrics and rendered in `_enrichment_sections` (foundational FIRST, then AIVI
and the Phase D sections, then per-engine recommendations, then transfer).

### Y.12 — foundational (transferable) GEO readiness score (`foundational_score.py`)

| Criterion | Status | Evidence |
|---|---|---|
| Y.12.1 deterministic; all-zero→0, all-max→100, mixed=hand-computed | **Done** | `tests/test_foundational_score.py::TestSubscores` (`test_all_max_is_100`, `test_all_zero_is_0`, `test_mixed_hand_computed`, `test_deterministic`) |
| Y.12.2 missing inputs → n/a, excluded (renormalised), never 0 | **Done** | `TestNaRenormalization::test_missing_inputs_are_na_and_excluded`, `test_na_axis_excluded_not_zero` |
| Y.12.3 gaps from EXISTING geo_alerts / schema recs / leaderboard, not new strings | **Done** | `TestGapsFromExistingSources` (three tests) |
| Y.12.4 weights from config; table idempotent + trendable | **Done** | `TestWeightsAndPersistence` (four tests) |
| Y.12.5 USER_MANUAL WHAT/WHY; methodology updated | **Done** | `docs/USER_MANUAL.md` "Engine strategy" section; `docs/methodology.md` Phase E |
| Presented FIRST, ahead of per-engine AIVI | **Done** | `_enrichment_sections`; `tests/test_probe_enrichment.py::TestPhaseEWiring::test_foundational_and_transfer_persisted_and_rendered` asserts section order |

### Y.10 — engine profiles + per-engine recommendations (`engine_profiles.yml` + `engine_recommendations.py`)

| Criterion | Status | Evidence |
|---|---|---|
| Y.10.1 sourced from engine_profiles.yml; editing profile changes output; no advice hardcoded | **Done** | `tests/test_engine_recommendations.py::TestSourcedFromYaml` (`test_moves_come_from_yaml_editing_changes_output`, `test_no_advice_string_hardcoded_in_module`) |
| Y.10.2 prioritisation deterministic + config-weighted; hand-computed order | **Done** | `TestPrioritization::test_low_aivi_high_reach_ranks_first`, `test_deterministic` |
| Y.10.3 only enabled engines appear; disabled → no rec | **Done** | `TestEnabledOnly` (two tests) |
| Y.10.4 engine_profiles.yml in CLAUDE.md editorial list; USER_MANUAL WHY + confidence caveat; methodology updated | **Done** | `CLAUDE.md` editorial list; `docs/USER_MANUAL.md`; `docs/methodology.md`; caveat rendered (`TestRepoProfilesLoad::test_report_section_carries_caveat`) |

### Y.11 — cross-engine transfer / overlap metric (`engine_transfer.py`)

| Criterion | Status | Evidence |
|---|---|---|
| Y.11.1 Jaccard + all-vs-one deterministic; identical→1.0, disjoint→0.0 | **Done** | `tests/test_engine_transfer.py::TestJaccard`, `TestOverlapCounts` |
| Y.11.2 mention/cite transfer statement for 0/some/all engines | **Done** | `TestVisibilityTransfer` (three tests) |
| Y.11.3 single-engine → "not measurable", no crash | **Done** | `TestSingleEngine` (two tests) |
| Y.11.4 table idempotent, UTC ts, trendable | **Done** | `TestPersistence::test_table_idempotent_and_trendable` |
| Y.11.5 USER_MANUAL WHAT/WHY + single-run caveat; methodology updated | **Done** | `docs/USER_MANUAL.md`; `docs/methodology.md` |

### Notes / deviations

- **`engine_profiles.yml` is a new editorial surface** — added to CLAUDE.md's
  editorial-content list with the binding vendor/temporal confidence caveat.
  The OpenAI engine's block key is `openai` (surfaced as ChatGPT) to match the
  probe's `VALID_ENGINES`.
- **Foundational score consumes existing data only** — `keyword_profiles`
  extractability/schema_signals + `strategic_flags.geo_alerts` (from the latest
  market-analysis extraction) and the Y.7 leaderboards; `schema_recommendations`
  loaded via the existing `brief_prompts.load_schema_recommendations`. No new
  external calls, no new dependency. An analysis JSON that predates
  keyword_profiles capture flows through with each sub-score `n/a` (never a
  fabricated zero).
- **Config additions** (`config.yml`): `foundational.weights` (equal thirds) and
  `engine_prioritization.weights` (opportunity/reach/referral 0.5/0.3/0.2). New
  SQLite tables `foundational_score` and `engine_transfer` (idempotent, trendable).

## Phase E commit status

Git blocked in this sandbox — work is on the working tree, full suite green
(954 passed / 94 skipped / 1 pre-existing tkinter error in
`test_serp_launcher.py`, unchanged). Recommended local commit (one), staging
ONLY these files:

- New modules + editorial: `foundational_score.py engine_recommendations.py
  engine_transfer.py engine_profiles.yml`
- Wiring: `probe_ai_visibility.py config.yml`
- Tests: `tests/test_foundational_score.py tests/test_engine_recommendations.py
  tests/test_engine_transfer.py tests/test_probe_enrichment.py`
- Docs: `CLAUDE.md docs/USER_MANUAL.md docs/config_reference.md
  docs/methodology.md docs/spec_coverage.md
  docs/yoast_geo_upgrade_status_2026-07-06.md`

Trailer: `Spec: yoast_geo_upgrade_spec_v1.md#Y.12 #Y.10 #Y.11`

Do **not** `git add .` — stage `config.yml` explicitly (only the `foundational`
and `engine_prioritization` blocks were added).
