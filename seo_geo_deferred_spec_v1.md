# Deferred Items Specification: SEO/GEO Upgrades — v1

## Status of this document

This is the implementation spec for the items deferred in
`seo_geo_review_20260704.md` (see its "Implementation status" note):
**T.5, G.1, G.3, G.4, G.5, G.6, and C.9**. The already-implemented items
(C.1–C.8, C.10, T.1–T.4, T.6, G.2) are NOT re-specified here; their code and
conventions are the base this spec builds on.

**Acceptance criteria** subsections are binding. **Implementation notes**
are guidance. Where this document and the review doc disagree, this
document wins.

## Reading before changing

1. Read `seo_geo_review_20260704.md` Parts 1–2 for the rationale behind
   each item.
2. Read `docs/methodology.md` (the contract doc — every item below that
   changes a file it references must update it in the same change) and the
   CLAUDE.md rules on editorial content and validator canaries.
3. Confirm the current state: `serp_vocab.yml` (editorial vocab),
   `schema_recommendations.yml`, `http_retry.py`,
   `keyword_profiles.{schema_signals, aio_divergence, extractability}`,
   `strategic_flags.geo_alerts`, and `config.yml geo:` all exist. If any
   is missing, stop and report — the base has drifted.

## Design principles (inherited, binding)

1. **Deterministic Python computes; the LLM writes.** Every new metric is
   pre-computed and passed as data. The LLM never derives numbers.
2. **Editorial content lives in YAML/JSON.** Trigger lists, templates,
   credential vocabularies, and threshold labels go in config files.
   When a new prompt reference to `keyword_profiles.<field>` is added,
   either add a validator rule in `validate_llm_report` or add the field
   to `KNOWN_UNVALIDATED` in `test_validation_consistency.py` with a
   reason — the canary test enforces this.
3. **Absent data is stated, not faked.** Every new data block carries a
   `data_available` (or equivalent) flag; old analysis JSONs without the
   new fields must flow through extraction without crashing and without
   fabricated zeros presented as measurements.
4. **Paid calls are gated.** Anything that spends SerpAPI, Anthropic, or
   DataForSEO quota is off by default or capped in `config.yml`, and the
   run log states how many paid calls the feature consumed.
5. **Trend over point values.** AI-engine behavior swings between model
   versions. Probing features store history in SQLite and report change
   over time; single-run numbers are labeled as snapshots.

## Decisions required from the user (gates)

| Gate | Item(s) | Decision needed | Default if unstated |
|---|---|---|---|
| D-1 | T.5 | Max extra SerpAPI calls per run for situational probes | 6 per run (2 per priority keyword, top 3 keywords) |
| D-2 | G.1 | Which AI engines to probe in Phase 1; monthly probe budget | Claude only (existing `ANTHROPIC_API_KEY`), ≤ 20 questions/run, ≤ 2 runs/month |
| D-3 | G.4 | GSC auth method: OAuth client (interactive) vs service account added to the Search Console property | Service account (headless-friendly) |
| D-4 | G.5 | Enable Bing check at all? | Implemented but `enabled: false` in config |
| D-5 | C.9 | Is `../shared_config.json` still consumed by Tool 2 / other tools? | Assume yes → formalize, do not remove |

Implementation may proceed item-by-item without all gates resolved; each
item states which gate blocks it. Do not silently pick a non-default.

## Definition of done (whole spec)

1. Each item's acceptance criteria pass with `python3 -m pytest test_*.py
   tests/ -q` fully green (no new failures, no newly skipped
   business-logic tests).
2. `docs/methodology.md`, `docs/USER_MANUAL.md`, and
   `docs/config_reference.md` updated per item, same commit.
3. Every new editorial surface is listed in CLAUDE.md's editorial-content
   list.
4. Each commit carries `Spec: seo_geo_deferred_spec_v1.md#<item>`.
5. A closing status report `docs/seo_geo_deferred_status_<date>.md` maps
   every acceptance criterion to a commit hash or an explicit "not done +
   reason".

## Suggested sequencing

1. **Phase A (no new credentials):** C.9 → G.6 → G.3 (pure code/config +
   enrichment additions; G.6 and G.3 extend the same enrichment path).
2. **Phase B (SerpAPI spend, gate D-1/D-4):** T.5, then G.5 (both are
   SerpAPI query features; G.5 reuses T.5's probe-run plumbing).
3. **Phase C (new integrations, gates D-2/D-3):** G.1, then G.4.

---

# C.9 — Formalize the `shared_config.json` contract

## Problem

`serp_audit.py:64` and `feasibility.py:29` both resolve
`os.path.join(os.path.dirname(__file__), "..", "shared_config.json")` — a
file OUTSIDE the repo. When present it silently overrides stop words,
client DA, domain, and feasibility thresholds; when absent everything
falls back with no trace. The path logic is duplicated, and nothing in the
repo documents the file's schema. Behavior depends on deploy layout.

## Required change

1. Create one module, `shared_config.py`, owning: the path resolution
   (env var `SERP_SHARED_CONFIG` overrides the `../shared_config.json`
   default), loading, JSON-error handling (warn + `{}`), and a single
   `load_shared_config()` used by both consumers. One INFO log line states
   whether the file was found and which keys were consumed.
2. Both `serp_audit.py` and `feasibility.py` import from it; the duplicate
   path constants are deleted.
3. Document the schema (keys: `stop_words`, `client.{da,domain,location}`,
   `technical.{feasibility_threshold,moderate_feasibility_max_gap,score_normaliser}`,
   `filtering.omitted_domains_path`) in `docs/config_reference.md` with an
   explicit precedence statement: shared_config > config.yml >
   serp_vocab.yml defaults (stop words) / code defaults (thresholds).

Do NOT remove the file's authority (gate D-5 default assumes Tool 2 also
reads it).

## Acceptance criteria

- C.9.1 `grep -rn "shared_config.json" *.py` shows the path constructed in
  exactly one module.
- C.9.2 `SERP_SHARED_CONFIG=/tmp/x.json` redirects loading (unit test with
  a temp file: overridden threshold visibly changes `_gap_to_status`).
- C.9.3 A malformed shared config logs one warning naming the file and
  falls back to defaults (test asserts the log record).
- C.9.4 With no file present, `serp_audit` and `feasibility` import and
  behave identically to today (existing tests stay green).
- C.9.5 `docs/config_reference.md` documents the schema and precedence.

---

# G.6 — Content freshness / decay tracking

## Problem

AI answer surfaces and Google both prefer fresh YMYL content. The tool
captures no page dates, so the brief cannot say "the top-10 for this
keyword is young/stale" or "the client's page is aging out."

## Required change

1. `url_enricher.extract_features` extracts a best-effort
   `published_time` and `modified_time` (ISO strings or None) from, in
   priority order: `article:published_time` / `article:modified_time`
   meta, JSON-LD `datePublished` / `dateModified` (reuse the existing
   JSON-LD walk), `<time datetime=…>` (first occurrence). No NLP date
   guessing from body text.
2. `serp_audit` copies both onto enriched organic rows
   (`Published_Time`, `Modified_Time`).
3. `brief_data_extraction` adds `keyword_profiles.freshness`:
   `data_available`, `pages` ({rank, source, published_time,
   modified_time, age_days — computed against the run's `Created_At`,
   NOT wall-clock, so re-extraction of an old JSON is stable}),
   `median_age_days` (dated pages only), `dated_page_count`,
   `client_page` (or None).
4. Prompt: Section 2 per-keyword profiles may state the median age and
   the client page's age when `data_available`; add `freshness` to the
   canary allowlist (evidence anchor) OR add a validator rule that the
   report may not state a median age different from the pre-computed one
   (preferred: allowlist; ages are descriptive).

## Implementation notes

- Dates are frequently absent (service pages rarely carry them). That is
  itself signal: report `dated_page_count` honestly; do not treat undated
  as age 0.
- Parse with `datetime.fromisoformat` after trimming trailing `Z`;
  unparseable strings → None (count as undated), never raise.

## Acceptance criteria

- G.6.1 Enricher unit tests: meta-tag page, JSON-LD page, `<time>` page,
  and no-date page each produce the expected fields.
- G.6.2 `age_days` is computed against run `Created_At` (test: fixed
  fixture dates give exact expected integers, independent of today).
- G.6.3 Old analysis JSONs (no date columns) yield
  `freshness.data_available == false` and extraction does not crash.
- G.6.4 Payload passthrough test (`keyword_profiles.freshness` reaches
  `build_main_report_payload` output).
- G.6.5 Canary test green (allowlist entry or validator rule present).

---

# G.3 — E-E-A-T author-signal detection

## Problem

Therapy is YMYL. Both Google and AI engines weight visible author
credentials on health content. The tool cannot currently say "8 of 10
ranking pages carry credentialed bylines; the client's page has none."

## Required change

1. New editorial section in `serp_vocab.yml`: `eeat_signals`, containing
   `credential_tokens` (e.g. RCC, CCC, MSW, RSW, PhD, PsyD, RP, RCT,
   "registered clinical counsellor", "marriage and family therapist") and
   `review_markers` ("medically reviewed", "clinically reviewed",
   "reviewed by"). Word-boundary matching for short tokens (an "RP" inside
   another word must not fire), substring for multi-word phrases —
   mirror `intent_classifier.py`'s matching approach.
2. `url_enricher.extract_features` adds: `author_present` (bool — JSON-LD
   `author`/`Person`, `rel=author`, or a `class`/`itemprop` author byline
   node), `credential_hits` (distinct credential tokens found in the first
   N chars of body text or in JSON-LD author fields; N configurable,
   default 8000), `review_marker_present` (bool).
3. Flow onto organic rows → `keyword_profiles.eeat_signals`:
   `data_available`, `pages` ({rank, source, author_present,
   credential_hits, review_marker_present}), `credentialed_page_count`,
   `client_page`.
4. Prompt: Section 5b and Section 7 may state whether credentialed
   authorship is table-stakes on that SERP (e.g. "7 of 8 enriched pages
   show credentials; the client page shows none"). Canary: allowlist
   `eeat_signals` as an evidence anchor.

## Acceptance criteria

- G.3.1 `serp_vocab.yml` gains `eeat_signals` and the loader requires it
  (missing key → ValueError, updated required-keys test).
- G.3.2 Matching tests: "Jane Doe, RCC" fires; "harp" does not fire "RP";
  "registered clinical counsellor" fires as a phrase.
- G.3.3 Enricher tests for a JSON-LD-author page, a byline-only page, and
  a no-author page.
- G.3.4 Old JSONs → `data_available == false`, no crash; payload
  passthrough test; canary green.
- G.3.5 CLAUDE.md editorial list already covers `serp_vocab.yml` — no new
  entry needed, but `docs/config_reference.md`'s serp_vocab description
  mentions the new section.

---

# T.5 — Situational (conversational) query probes

## Problem

Six-plus-word situation-style queries trigger AI answers ~3× more often
than short keywords, and they are how people phrase problems to AI
assistants. The tool's generated variants stop at `A.1`
(informational) and `A.2` (cost). There is no measurement of AIO trigger
rate by query length on the client's actual market.

## Required change

1. New query label **"S"** (situational), generated per root keyword.
   Sources, in priority order, capped by config:
   a. The keyword's own PAA questions of 6+ words (verbatim — they are
      already conversational), preferring External Locus ones.
   b. Editorial templates: new `situational_templates` section in
      `serp_vocab.yml`, `{base}`/`{topic}`/`{city}` placeholders, e.g.
      "my partner refuses to try {base} what can I do".
2. Config block:
   ```yaml
   situational_probes:
     enabled: false          # off by default (paid calls)
     max_probes_per_run: 6   # gate D-1
     probes_per_keyword: 2
     keywords: priority      # priority = strategic_flags order | all
   ```
   Deep Research mode may enable it; Low API mode never runs probes.
3. Each probe is a normal SerpAPI fetch (single page, no enrichment, no
   maps call) recorded with `Query_Label: "S"`. Probe results feed ONLY
   the AIO-rate analysis and `ai_overview_citations`; they must NOT enter
   organic ranking metrics, intent verdicts, volatility, or the handoff
   file (assert this — the "A"-label filters already exist; add "S" to
   any label allowlists that need it).
4. New analysis block `aio_trigger_analysis` (extraction):
   `by_word_count_bucket` ({"1-3", "4-5", "6+"} → {queries, aio_present,
   rate}) computed across ALL queries in the run including probes, and
   `probe_results` ({query, source_keyword, word_count, has_aio,
   client_cited}). Prompt: Section 4 states the measured trigger rate by
   length bucket and any probe where the client was cited; canary
   allowlist or n/a (not a `keyword_profiles.` field).
5. Run log prints: "Situational probes: N SerpAPI calls (cap M)".

## Acceptance criteria

- T.5.1 With `enabled: false` (default), zero extra SerpAPI calls occur
  (test: mock fetch, assert call count unchanged).
- T.5.2 Probe generation test: PAA-sourced probes come verbatim from that
  keyword's 6+-word questions; template probes fill placeholders; total
  respects both caps.
- T.5.3 Probe rows carry `Query_Label == "S"` and are absent from
  `competitor_handoff_*.json`, `keyword_profiles.serp_intent` inputs, and
  volatility (tests per surface).
- T.5.4 `aio_trigger_analysis` computes correct bucket rates on a fixture
  with known word counts and AIO flags.
- T.5.5 `serp_vocab.yml` gains `situational_templates` (loader-required,
  parity-tested), documented in USER_MANUAL with the WHY (23% vs 77%
  claim, tested on the client's own market).

---

# G.5 — Secondary index check: Bing

## Problem

ChatGPT search grounds substantially on Bing. The client's Bing standing
is unknown and unmeasured; a Google-only view can miss an entire AI
referral surface.

## Required change

1. Config:
   ```yaml
   bing_check:
     enabled: false   # gate D-4
     num: 20
   ```
2. When enabled, one SerpAPI `engine=bing` call per ROOT keyword (label
   "A" query text; no pagination, no enrichment, reuse the existing retry
   wrapper). Store raw response under `raw/{run_id}/bing_{kw}.json`
   (raw/ is gitignored).
3. New extraction block `bing_visibility` per keyword: `checked` (bool),
   `client_rank` (int or None), `client_url`, `top3_domains`, plus a
   run-level summary {keywords_checked, client_visible_count}. Domain
   matching reuses `_domain_from_link` / `_is_client_domain`.
4. Report: one Section 4 paragraph comparing Google vs Bing client rank
   per keyword ("visible on Google at #4, absent from Bing top-20" or
   vice versa). If `checked` is false everywhere, the report says the
   check was disabled — never guesses.

## Implementation notes

- Bing SERP JSON differs from Google's (`organic_results` shape is
  similar but verify `position` and `link` fields against a captured
  fixture before writing the parser; commit the fixture under
  `tests/fixtures/`).
- Do not classify or enrich Bing results; this is a visibility check,
  not a second market analysis.

## Acceptance criteria

- G.5.1 Disabled by default: zero Bing calls (mock-based test).
- G.5.2 Parser test against a committed Bing fixture: client rank found;
  client absent → `client_rank None` with `checked true`.
- G.5.3 One call per root keyword when enabled (call-count test), routed
  through the standard retry path.
- G.5.4 Report prompt references the block only descriptively; canary
  unaffected (top-level key) — verify canary stays green.

---

# G.1 — AI-engine mention probing (phased)

## Problem

The tool measures Google's AI Overview only. Whether Claude/other
assistants mention or cite Living Systems when asked realistic
therapy-seeker questions is unmeasured — and per the review's own
evidence, this swings between model versions, so it must be tracked as a
trend, not a snapshot.

## Required change — Phase 1 (Claude only, gate D-2)

1. New standalone script `probe_ai_visibility.py` (pattern:
   `run_feasibility.py` — runs any time, reads config, no pipeline
   coupling):
   - Question set: the run's situational probes (T.5 output) when
     available, else PAA questions 6+ words, else `situational_templates`;
     capped by `ai_visibility.max_questions` (default 20).
   - For each question, one Anthropic API call **with the web search tool
     enabled**, geo-context prefixed ("I'm in North Vancouver, BC…").
     Reuse `brief_llm.py`'s client-construction conventions; model id from
     config (`ai_visibility.model`), never hardcoded.
   - Detection: `mentioned` (client name patterns from
     `analysis_report.client_name_patterns`, case-insensitive),
     `cited` (client domain in any returned source URL),
     `competitors_cited` (domains matched against `known_brands` +
     top competitor domains from the latest analysis JSON).
2. Persistence: new SQLite table `ai_visibility_probes`
   (`run_ts, engine, model, question, mentioned, cited,
   competitor_domains_json, answer_excerpt`), written via `storage.py`
   conventions (parameterized, UTC timestamps).
3. Report `ai_visibility_<topic>_<ts>.md`: this run's mention/citation
   rate, the same rate for the previous N runs (trend table), engines/
   model ids used, and a mandatory caveat paragraph that single-run
   values are snapshots. Output name follows the gitignored report globs.
4. Cost guard: the script prints estimated call count and exits without
   calling unless `--yes` or `ai_visibility.assume_yes: true`.

## Required change — Phase 2 (only after Phase 1 has ≥2 runs of data)

Provider-pluggable interface (`AiEngineProbe` protocol: `ask(question) →
{answer_text, source_urls}`), mirroring the DataForSEO/Moz dual-provider
pattern, so additional engines slot in behind config without touching the
analysis/reporting layer. Phase 2 engine choice is a new user gate — do
not implement speculatively.

## Acceptance criteria

- G.1.1 All API calls mocked in tests: detection logic verified for
  mentioned-only, cited, neither, and competitor-cited answers.
- G.1.2 Table created idempotently; rows written with UTC `run_ts`;
  trend query returns runs in order (test with two synthetic runs).
- G.1.3 No calls without explicit confirmation (test: default run with
  mocked client asserts zero API calls, exit message states the cap).
- G.1.4 Report renders with zero prior history (first run) and with
  history; caveat paragraph always present.
- G.1.5 `docs/USER_MANUAL.md` explains WHAT (mention/citation trend) and
  WHY (AI answers are a growing referral surface; volatility across model
  versions is why the trend view exists).

---

# G.4 — Google Search Console integration

## Problem

The tool sees rank but never clicks, so the zero-click/AIO "sponge"
effect on the client's own traffic is invisible. GSC is free, first-party
data for `livingsystems.ca`.

## Required change

1. New client module `gsc_client.py`:
   - Auth per gate D-3 (default: service account JSON, path from
     `GSC_CREDENTIALS_PATH` env var; the service account email must be
     added to the Search Console property — document this step in the
     USER_MANUAL).
   - One method:
     `get_query_stats(queries, start_date, end_date) → {query:
     {clicks, impressions, ctr, position}}` via the Search Analytics API
     (dimension `query`, filtered to the property), batched, with the
     existing `http_retry` semantics. New dependency
     `google-api-python-client` (pinned range) — or plain REST via
     `requests` with a google-auth token; prefer the lighter footprint.
   - 7-day SQLite cache (`gsc_cache` table) following the DA-client
     cache pattern, including the batched IN(...) lookups.
2. New standalone script `run_gsc_analysis.py` (like `run_feasibility.py`):
   reads the latest `market_analysis_*.json`, pulls GSC stats for the
   run's root keywords + their `A.1`/`A.2`/`S` variants + top PAA
   phrasings, and writes `gsc_analysis_<topic>_<ts>.md` plus a JSON
   sidecar containing:
   - per-query: clicks, impressions, CTR, avg position, `has_ai_overview`
     (joined from the analysis JSON);
   - the sponge comparison: median CTR at comparable position for
     AIO-present vs AIO-absent queries (only when both buckets have ≥3
     queries — otherwise state insufficient data);
   - `reformat_candidates`: queries where position is stable/good but
     CTR sits below the no-AIO median — cross-referenced against
     `strategic_flags.geo_alerts` when the keyword matches.
3. Feed-forward (optional, config-gated `gsc.feed_strategic_flags`):
   when the sidecar exists, `brief_data_extraction` may attach
   `gsc_summary` to the payload. HARD rule for the prompt: GSC numbers
   are the client's private data — quote them only in client-position
   contexts, never as market-level claims.
4. Config: `gsc: {enabled: false, property: "sc-domain:livingsystems.ca",
   lookback_days: 90}`; env var documented in CLAUDE.md's required-env
   list as optional.

## Acceptance criteria

- G.4.1 All HTTP mocked: auth header construction, batching, cache
  hit/miss, and the 999-variable batching on cache lookups (reuse test
  patterns from `test_dataforseo_client.py`).
- G.4.2 Sponge computation unit-tested on synthetic data (known medians,
  both buckets; and the <3-queries insufficient-data path).
- G.4.3 `reformat_candidates` intersects correctly with `geo_alerts` on a
  fixture where one keyword satisfies both.
- G.4.4 With `enabled: false` or no credentials, `run_gsc_analysis.py`
  exits with a clear message and zero API calls; the main pipeline is
  entirely unaffected (no import of gsc_client at pipeline import time).
- G.4.5 Outputs follow the gitignored naming globs; USER_MANUAL documents
  setup (service-account grant) and how to read the sponge table.

---

## Out of scope (re-affirmed)

- llms.txt generation — unchanged from the review: not worth tool code.
- Per-model citation chasing — G.1 measures trends; no per-engine
  optimization logic.
- Automated outreach/posting to Reddit or directories — the tool surfaces
  targets (T.3/T.6, shipped); humans do outreach.
