# Yoast-Inspired GEO Upgrade Specification — v1

## Status of this document

This is the implementation spec for a set of AI-GEO features derived from a
competitive review of Yoast's "AI brand analysis" flow (profile-seeded
question generation + multi-engine visibility probing). It **builds on**
`seo_geo_deferred_spec_v1.md#G.1` (the existing `probe_ai_visibility.py`
Claude+Gemini probe) and `#T.5` (the situational conversational probes in
`query_variants.py` / `serp_vocab.yml`). Those are the base; nothing here
re-specifies them.

The goal is stated by the user: make the tool **maximally effective** at
measuring and improving how Living Systems (and future clients) surface in
AI answer engines and local search. Every item below is additive — no
existing capability (keyword-seeded SERP audit, PAA/PASF, DA feasibility,
briefs, schema recommendations) is removed or weakened.

**Revision note:** items Y.6–Y.9 were added after examining a real Yoast
ChatGPT "Brand Analysis Report" for this client (see "What the sample
report revealed" below). They specify the *output* structures Yoast
produces that the current tool does not — the composite index, the
competitor leaderboard, the categorized citation table, and per-brand
sentiment. Y.1–Y.5 remain the *input/engine* upgrades.

## What the sample report revealed (Yoast ChatGPT, 2026-07-05)

The uploaded `brand-analysis_..._chatgpt_july-5-2026.pdf` ran 5
persona-style queries through ChatGPT and reported:

1. **AI Visibility Index (AIVI): a single 0–100 score** on a four-axis
   radar — **Mentions, Ranking, Citations, Sentiment** — with each axis
   also shown as a headline card (Mentions 0/5, Competitor Ranking "—",
   Citations 0, Positive Sentiment 0%). The client scored **0/100**: not
   mentioned or cited in any of the five answers.
2. **Per-query mention list** — each query tagged found / "Not found"
   ("0 of 5 queries mentioned the brand").
3. **Competitor ranking leaderboard** — **24 brands** the answers *did*
   mention, ranked by mention count (each 1/5 here). These are extracted
   **named entities** (e.g. "Vancouver Coastal Health", "Bowen Center for
   the Study of the Family", "Psychology Today"), not merely cited
   domains — several ranked brands were named without being linked.
4. **Citations table** — **27 source URLs** the AI used, each with
   `domain`, a **Category** (values observed: `Publisher`, `Other`), and
   the **brand** each citation supports; brand-owned citations flagged.
   URLs carried `?utm_source=openai`, confirming they are ChatGPT's live
   retrieved sources.
5. **Sentiment** — % positive for the **brand** and for the **top
   competitor**, plus extracted **positive/negative keyword** chips
   (e.g. competitor positives "integrated supports for youth and
   families", "public (no-cost) mental health assessment"; negative
   "some services may require a physician referral").

Takeaway for our tool: our probe already detects mention/citation, but it
produces neither a composite score, a full mention-based competitor
leaderboard, a categorized+attributed citation table, nor sentiment. Those
are the four Y.6–Y.9 additions. Note our repo **already has** a content/
entity classifier (`classifiers.py`, `classification_rules.json`,
`url_pattern_rules.yml`, `domain_overrides.yml`) and a `known_brands`
list — Y.7 and Y.8 reuse these rather than adding parallel logic.

**Acceptance criteria** subsections are binding. **Implementation notes**
are guidance. Where this document and any older doc disagree about these
new items, this document wins.

## Reading before changing

1. Read `seo_geo_deferred_spec_v1.md` items **G.1** and **T.5** in full —
   this spec extends both the probe engine registry and the situational
   template mechanism.
2. Read `docs/methodology.md` (the contract doc — every item below that
   changes a file it references must update it in the same change) and the
   CLAUDE.md rules on editorial content. For Y.13 (the Settings editor)
   also read `~/.claude/standards/ui-regression.md`, `docs/gui_steps.md`,
   the multi-client architecture docs (`docs/MULTI_CLIENT_ARCHITECTURE.md`,
   `docs/CONFIG_MANAGER_MULTI_CLIENT.md`), and the CLAUDE.md GUI
   initialization-testing rule (source-inspection tests for tab init
   order).
3. Confirm the current state exists, or **stop and report drift**:
   `probe_ai_visibility.py` with `VALID_ENGINES`, `resolve_engines`,
   `build_probes`, and the `ClaudeProbe`/`GeminiProbe` classes exposing
   `ask(question) -> {answer_text, source_urls, model_id}`;
   `query_variants.py:situational_template_probes`;
   `serp_vocab.yml:situational_templates`; the `ai_visibility:` block in
   `config.yml`; and the `known_brands` / `client` config keys.

## Empirical basis: does optimization transfer across engines?

A separate cross-engine analysis (2026) informs the engine design below.
Its **directional finding is high confidence** because it reproduces
across independent panels and vendors; the **exact percentages are low
confidence** (most figures come from GEO vendors with a commercial
interest, and the retrieval backends shift over time). Treat the direction
as binding design rationale and the numbers as indicative only.

1. **Citation-level visibility mostly does NOT transfer between engines.**
   Reported pairwise domain overlap is ~11–18% (Jaccard ~0.18 across five
   engines; ~11% of domains cited by both ChatGPT and Perplexity; up to
   615× brand citation-volume variance between platforms). Implication:
   the tool must **report every metric per engine, never only aggregated**,
   and must not imply that a win on one engine is a win on all. Y.6–Y.9
   already persist per-engine rows; this section makes per-engine
   reporting a hard requirement, and adds Y.11 to *measure* transfer for
   the specific client rather than assume it.
2. **The engines retrieve from different backends with different source
   biases** (as reported 2026, subject to change): ChatGPT — own +
   Bing-derived index, encyclopedic/consensus-heavy, few citations
   (~3.7); Perplexity — proprietary + Bing hybrid, Reddit-heavy,
   freshness-sensitive, many citations (~8–21); Gemini/Google AI Overviews
   — Google's index, highest overlap with Google organic; Claude — Brave
   Search (as reported), favors structured/depth content, conservative.
   Implication: platform-specific recommendations must differ by engine
   (Y.10), driven by an editorial `engine_profiles.yml`, not hardcoded.
3. **A foundational layer DOES transfer to all engines** and is the
   highest-ROI work: (a) technical accessibility (AI crawler can fetch/
   parse; not JS-gated), (b) clean extractable structure (headings, direct
   factual statements, schema), and (c) off-site authority — with
   brand-mention frequency across trusted third-party sources reported to
   predict AI citation ~3× more strongly than backlinks. Implication: the
   tool should score this transferable layer **separately** from per-engine
   outcomes (Y.12), and flag it as the first priority. The repo already
   owns most of the inputs (`keyword_profiles.extractability`,
   `schema_signals`, `strategic_flags.geo_alerts`, and Y.7 brand mentions).
4. **Prioritization is audience-dependent, not universal.** For a site
   whose audience arrives via Google organic (typical of a local
   nonprofit like livingsystems.ca), Google AI Overviews is usually the
   highest-impact AI surface because existing SEO partly carries over;
   ChatGPT leads on raw reach; Perplexity punches above its usage weight
   for *referral clicks*. Implication: engine enablement is a **toggle
   with documented recommended defaults** (Y-D9), and the tool emits a
   prioritization recommendation (Y.10) rather than a fixed ranking.

## Design principles (inherited from `seo_geo_deferred_spec_v1.md`, binding)

1. **Deterministic Python computes; the LLM writes.** New metrics are
   pre-computed and stored, never derived by an LLM at read time.
2. **Editorial content lives in YAML/JSON.** Personas, question templates,
   and profile fields go in config files, listed in CLAUDE.md's editorial
   surface list. No editorial content in `.py`.
3. **Absent data is stated, not faked.** A run with no client profile, or
   an engine with a missing API key, is reported as "not measured," never
   as a zero presented as a measurement.
4. **Paid calls are gated.** Every new engine spends API quota; all are
   subject to the existing `ai_visibility` cost guard (`--yes` /
   `assume_yes`), and the plan line states `questions × engines` before
   any call. A missing API key skips that engine with a logged warning,
   never an abort (mirrors the Gemini contract).
5. **Trend over point values.** New engines write per-engine rows to the
   existing `ai_visibility_probes` SQLite table; single-run values remain
   labeled as snapshots.
6. **Model ids are never hardcoded.** Every engine reads its model id from
   `config.yml`, as `claude_model` / `gemini_model` already do.

## Decision gates — TO CONFIRM before implementation

These mirror the "Decision gates" convention of the base spec. Recommended
defaults are given; the user confirms or overrides before Phase B/C spend.

| Gate | Item(s) | Question | Recommended default |
|---|---|---|---|
| Y-D1 | Y.1 | Do profile-seeded questions **replace** keyword-seeded probe questions, or **augment** them? | **Augment.** Profile questions become the highest-priority source in the existing precedence chain (profile → T.5 → PAA 6+ → templates), capped by `max_questions`. Keyword flow is untouched. |
| Y-D2 | Y.2 | Add the **OpenAI/ChatGPT** engine? Requires `OPENAI_API_KEY` and the web-search-enabled endpoint. | **Yes**, default present in `engines` only if key set; skipped-with-warning otherwise. |
| Y-D3 | Y.3 | Add the **Perplexity** engine? Requires `PERPLEXITY_API_KEY` (Sonar models return citations). | **Yes**, same key-gated skip behavior. |
| Y-D9 | Y.2, Y.3, Y.10 | Which engines are **ON by default** for this client? Optimization does not transfer across engines, so this is a real choice, not a formality. | For a Google-organic local nonprofit (livingsystems.ca): **Gemini + ChatGPT ON** (highest audience reach + Google-organic carryover); **Perplexity optional-ON** (strong referral-click value); **Claude optional-OFF** (lowest reach for a small local site). All four remain fully supported and individually toggleable via `ai_visibility.engines`; these are defaults, not restrictions. |
| Y-D4 | all | Budget: engines now number up to four. Keep `max_questions: 20` per engine? | **Yes**, but add a hard `ai_visibility.max_total_calls` ceiling (default 60) that the cost guard enforces across `questions × engines`. |
| Y-D5 | Y.1 | Where do persona definitions live — one shared `personas:` list, or per-client? | **Shared editorial list** in a new `client_profiles.yml`, one profile block per client (multi-client architecture already exists). |
| Y-D6 | Y.6 | The AIVI composite weighting across the four axes (Mentions, Ranking, Citations, Sentiment). Yoast's exact weights are unknown. | **Equal 25% each to start**, weights in `config.yml` (`aivi.weights`), methodology documented so the score is defensible and tunable. Never hardcode. |
| Y-D7 | Y.7, Y.9 | Brand-entity extraction and sentiment are **LLM/NLP derivations**, in tension with principle 1 ("LLM never derives numbers"). Accept an LLM extraction step? | **Yes, reconciled as follows:** the LLM extracts entities/sentiment *labels* from each answer once (treated as a measured input, like an API response, stored verbatim); **Python computes all counts, ranks, and percentages** from those stored labels. A gazetteer pass (`known_brands` + analysis-JSON competitors) runs first; the LLM only fills unknowns. This keeps numbers deterministic and auditable. |
| Y-D8 | Y.9 | Sentiment is a paid LLM call per answer. Budget? | **Reuse the answer already fetched** — one extra classification call per *answer*, capped by `max_total_calls`; OFF by default (`sentiment.enabled: false`) until the user opts in. |

**Do not begin Phase C (paid engines) until Y-D2/Y-D3/Y-D4 are resolved.
Do not begin Y.7/Y.9 until the principle-1 reconciliation (Y-D7) is
confirmed.**

## Definition of done (whole spec)

1. Full suite green: `python3 -m pytest test_*.py tests/ -q` (no new
   failures, no newly skipped business-logic tests). All external API
   calls mocked.
2. `docs/methodology.md`, `docs/USER_MANUAL.md`, and
   `docs/config_reference.md` updated per item, same commit.
3. Every new editorial surface (`client_profiles.yml`, persona/question
   templates in `serp_vocab.yml`) is added to CLAUDE.md's editorial list.
4. Each commit carries `Spec: yoast_geo_upgrade_spec_v1.md#<item>`.
5. A closing status report `docs/yoast_geo_upgrade_status_<date>.md` maps
   every acceptance criterion to a commit hash or an explicit "not done +
   reason."

## Suggested sequencing

1. **Phase A (no new credentials, no spend):** Y.1 → Y.4 → Y.13. Profile
   model, persona-segmented question generation, the persona axis for
   situational templates, then the Settings tab (Y.13) that makes Y.1
   per-client editable in the GUI. Y.13 comes last in Phase A because it
   edits Y.1's file and previews Y.1's generator.
2. **Phase B (wiring, no new engines):** Y.5. Feed profile questions into
   the existing probe precedence chain and add the cross-engine
   share-of-voice section to the report.
3. **Phase C (new paid engines, gates Y-D2/Y-D3/Y-D4):** Y.2 (OpenAI) then
   Y.3 (Perplexity). Each reuses the `AiEngineProbe` protocol; no changes
   to detection logic.
4. **Phase D (report enrichment, gates Y-D6/Y-D7/Y-D8):** Y.7 (competitor
   leaderboard) → Y.8 (citation table) → Y.9 (sentiment) → Y.6 (AIVI
   composite, last because it consumes all four axes). Y.6–Y.9 are read
   -side: they add stored metrics + report sections, no new engine calls
   except Y.9's opt-in sentiment classification.
5. **Phase E (engine strategy, gates Y-D9):** Y.12 (foundational-signal
   score — pure aggregation of existing signals, do first) → Y.10 (engine
   profiles + platform recommendations, editorial) → Y.11 (cross-engine
   transfer metric, needs ≥2 engines of history). Phase E answers "which
   platforms should this client optimize for, and does a win on one carry
   to others?"

---

# Y.1 — Client profile → persona-segmented question generation

## Problem

The tool can only probe questions derived from a **keyword CSV**
(T.5 situational templates fill `{base}/{topic}/{city}` from root
keywords; `probe_ai_visibility.py` falls back to PAA questions or the
static `situational_templates`). Real AI-assistant users do not type
keywords — they ask natural questions shaped by *who they are* and *what
they need*. Yoast's flow starts from a structured **profile** (brand,
service description, location, city) and generates such questions with no
keyword list at all, spanning **distinct audience personas** (a
family seeking affordable counselling, a clinician seeking training, a
referrer/conference-goer). The current tool has no profile entry point and
no persona axis, so it cannot see the questions those personas actually
ask — nor whether the client appears in the answers.

## Required change

1. New editorial file `client_profiles.yml` (per Y-D5), one block per
   **client** (keyed by client slug, e.g. `living_systems`) — distinct
   from the **topic** slug that names output files (from the keyword-CSV
   filename). One client profile serves all that client's topics.
   Fields, all editorial:
   - `brand_name`, `domain`, `location` (region), `primary_city`,
     `secondary_cities` (list, optional — Yoast's "1 city option to go
     local"), `service_description` (one paragraph), and `personas`
     (list). Each persona has a `label`, a short `needs` phrase, an
     optional `intent` hint, an optional `seed_questions` list (literal
     questions probed **verbatim**, no templating — this is where the
     client's real, hand-authored queries live), and optional
     `templates` (persona/intent-keyed patterns expanded per city, per
     Y.4). Both sources merge and de-duplicate.
   - **Funnel/intent tiers are explicit, per-client, and configurable.**
     Each persona declares questions under named intent tiers forming an
     ordered funnel. `informational` (top-of-funnel) and
     `local_transactional` (booking-intent) are the defaults, but the tier
     list is **open and per-client** — a client may add tiers (e.g.
     `consideration`) via Settings (Y.13). Tiers flagged `local: true`
     expand across `[primary_city] + secondary_cities` **and** a "near me"
     variant, keeping a de-localised copy for the AI-answer probe (reuse
     `query_variants.delocalise_keyword`); non-local tiers are probed
     as-is. This captures the difference, surfaced during review, between
     top-of-funnel concept queries and booking-intent local queries — the
     client had been probing only the former.
   - **Per-client by construction.** Everything above is keyed by client
     slug so each website/client has its own profile, personas, cities,
     and funnel tiers. The file is the store; **Settings (Y.13) is the
     editor** — the GUI reads and writes this file, no YAML hand-editing
     required.
   - A default **Living Systems** profile is provided, grounded in the
     client's actual usage (see illustrative block below), with **four**
     personas: prospective client (informational + local/transactional),
     clinician/trainee, and referrer.

   **Illustrative default (`client_profiles.yml`, editorial — final
   wording is the user's to tune):**

   **Client vs topic — do not conflate.** The key is the **client** slug
   (`living_systems`), of which there is exactly one for this deployment.
   It is NOT the **topic** slug that names outputs — the topic derives from
   the keyword-CSV filename (e.g. `keywords_leila.csv` → topic `leila`,
   named after the staff member who supplied that query set, not a
   separate client). One client profile serves all of that client's topics/
   keyword sets; `client_profiles.yml` is keyed by client, output files
   keep their existing `{topic}_{timestamp}` naming unchanged.

   ```yaml
   living_systems:                     # CLIENT slug — one block per client (not per topic)
     brand_name: Living Systems Counselling and Training
     domain: livingsystems.ca
     location: North Shore / Metro Vancouver, BC
     primary_city: North Vancouver
     secondary_cities: [West Vancouver, Vancouver]
     service_description: >
       A Bowen Family Systems Theory nonprofit offering counselling for
       individuals, couples and families, plus clinical training in
       family systems theory.
     personas:
       - label: prospective_client
         needs: understand their patterns and find local counselling
         intents:
           informational:               # top-of-funnel, non-local — the client's real CSV
             seed_questions:
               - why do I act differently around my family
               - how childhood affects adult relationships
               - repeating relationship patterns
               - how does birth order affect personality
               - family of origin issues
               - how to stop repeating my parents' patterns
           local_transactional:         # booking-intent — the missing tier
             templates:
               - "relationship counselling {city}"
               - "relationship counselling near me"
               - "couples counselling {city}"
               - "family therapist {city}"
               - "marriage counselling near me"
       - label: clinician_trainee
         needs: training and supervision in family systems theory
         seed_questions:
           - Bowen Family Systems Theory training programs
           - family systems therapy training for clinicians
           - clinical supervision family systems {city}
       - label: referrer
         needs: refer a family/patient for systemic counselling
         seed_questions:
           - where to refer a family for counselling in {city}
           - family counselling services for GP referral {city}
   ```
2. New module `profile_questions.py` (pure functions; pattern:
   `query_variants.py` — no I/O, config bound by the caller). It generates
   natural-language questions by filling **persona-aware templates** (see
   Y.4) with profile fields. Output: a list of
   `{question, persona, city}` dicts. Deterministic given inputs
   (templates ordered, no randomness) so tests are stable.
3. Question generation is **local-aware**: each persona's templates are
   expanded once per `[primary_city] + secondary_cities`, de-duplicated,
   and de-localised variants included where the template supports it
   (reuse `query_variants.delocalise_keyword`).
4. No new dependency. No network. No LLM call — this is deterministic
   template filling, consistent with principle 1.

## Acceptance criteria

- Y.1.1 `load_client_profiles()` parses `client_profiles.yml`, returns a
  dict keyed by slug; a missing or malformed file warns and returns `{}`
  (no crash), and the caller reports "no profile — profile questions
  skipped."
- Y.1.2 `profile_questions.generate(profile)` returns deterministic
  `{question, persona, city, intent}` dicts; a profile with N personas, M
  templates each, and C cities yields the expected de-duplicated count
  (unit test with a synthetic 2-persona / 2-template / 2-city profile).
- Y.1.2a `seed_questions` are emitted **verbatim** (no templating, no city
  suffixing) with their persona/intent tags; a template containing `{city}`
  inside a `seed_questions` list is treated as literal and NOT expanded
  (seeds are literal; only `templates` expand).
- Y.1.2b `local_transactional` templates expand across
  `[primary_city] + secondary_cities` **and** produce a "near me" variant
  and a de-localised copy; the informational tier is never city-suffixed
  (test asserts "relationship counselling North Vancouver",
  "relationship counselling West Vancouver", "relationship counselling
  near me", and a de-localised "relationship counselling" all appear,
  while a concept seed like "family of origin issues" appears once,
  unmodified).
- Y.1.3 Personas with no templates, empty `secondary_cities`, and missing
  `service_description` all degrade gracefully (produce fewer questions,
  never raise).
- Y.1.4 `client_profiles.yml` and its persona/template surfaces are listed
  in CLAUDE.md's editorial-content list; `docs/config_reference.md`
  documents every field.
- Y.1.5 `docs/USER_MANUAL.md` explains WHAT (profile → persona questions)
  and WHY (AI users ask persona-shaped natural questions, not keywords;
  personas surface audiences a keyword list misses, e.g. clinicians and
  referrers, not just therapy-seekers).

---

# Y.4 — Persona axis for situational templates (editorial)

## Problem

`serp_vocab.yml:situational_templates` is a flat list written from a
single implicit persona (the therapy-seeker: "my partner refuses…", "my
family keeps having the same fight…"). Yoast's output demonstrates that
the highest-value questions span multiple personas. A flat list cannot
express "these questions are for clinicians" vs "these are for referrers,"
so coverage is structurally capped at one audience.

## Required change

1. Restructure `situational_templates` from a flat list into a
   **persona-keyed map**: `situational_templates: {persona_label:
   [templates...]}`. Preserve every existing template under a
   `therapy_seeker` (or equivalent) key so current behavior is unchanged.
   Add at least two more persona blocks (clinician/trainee, referrer)
   with 3+ templates each.
2. Update `query_variants.situational_template_probes` and its caller to
   accept the persona-keyed structure. When a client profile (Y.1) is
   present, only that profile's declared personas are expanded; when
   absent, **all** persona blocks are used (backward-compatible default),
   so existing keyword-only runs still produce probes.
3. Placeholders unchanged (`{base}`, `{topic}`, `{city}`) plus optional
   `{service}` (from `service_description`) for profile-driven fills.
4. This is editorial content per CLAUDE.md — templates and persona labels
   are added to YAML only; no classification logic moves into Python.

## Acceptance criteria

- Y.4.1 The persona-keyed loader is backward compatible: a run with **no**
  profile expands all persona blocks and produces a superset of the
  previous flat-list output (test asserts every old template still
  appears).
- Y.4.2 `situational_template_probes` fills persona templates correctly,
  including the new `{service}` placeholder when supplied and omitting it
  cleanly when absent.
- Y.4.3 A profile listing only `clinician` expands only clinician
  templates (test).
- Y.4.4 The persona structure is documented in
  `docs/config_reference.md` and listed in CLAUDE.md's editorial list;
  `docs/methodology.md` updated because `serp_vocab.yml` is referenced
  there.

---

# Y.5 — Wire profile questions into the probe + cross-engine share-of-voice

## Problem

Y.1 generates profile questions but nothing consumes them, and the current
`ai_visibility_<topic>.md` report answers "does the client appear?" only —
it does not answer "**relative to whom?**" across engines, which is the
question a client actually pays to have answered ("how does my brand show
up in AI, and who beats me?"). The probe already detects
`competitors_cited`; that signal is under-reported.

## Required change

1. Extend the probe's question-source precedence in
   `probe_ai_visibility.py` to: **profile questions (Y.1) → T.5
   situational probes → PAA 6+ words → static templates**, capped by
   `max_questions` and the new `max_total_calls` ceiling (Y-D4). Each
   stored row records its `persona` (nullable) and `source`
   (`profile|situational|paa|template`) — add these columns to
   `ai_visibility_probes` via an idempotent migration in `storage.py`
   conventions; old rows read back with `NULL` (principle 3).
2. Add a **cross-engine share-of-voice** section to the report:
   per-engine, the client mention/citation rate alongside the top
   competitor domains cited (from the existing `competitors_cited`
   detection and `known_brands`), plus a per-persona breakdown of client
   mention rate. All values carry the run count and the snapshot caveat.
3. No detection-logic change — reuse the existing `mentioned` / `cited` /
   `competitors_cited` functions unchanged.

## Acceptance criteria

- Y.5.1 With a profile present and mocked engines, profile questions are
  probed first and their rows carry `persona` and `source='profile'`
  (test). With no profile, behavior equals the current G.1 precedence
  (regression test).
- Y.5.2 The `max_total_calls` ceiling is enforced: the cost guard prints
  `questions × engines` and the applied ceiling, and exits without calls
  when over budget unless `--yes` (test asserts zero calls).
- Y.5.3 The report renders the per-engine share-of-voice table and the
  per-persona breakdown with zero history and with history; competitor
  domains appear when cited; caveat paragraph always present.
- Y.5.4 Column migration is idempotent; a pre-existing DB without the new
  columns is upgraded once and old rows read back as `NULL` (test).
- Y.5.5 `docs/USER_MANUAL.md` explains WHAT (share of voice across engines
  + per persona) and WHY (visibility is comparative; knowing which
  competitors AI cites instead of the client is the actionable signal).

---

# Y.2 — OpenAI / ChatGPT probe engine

## Problem

The probe covers Claude and Gemini only. ChatGPT is the highest-traffic
consumer AI-answer surface; a GEO tool that cannot measure it is blind to
the engine most of the client's prospects actually use.

## Required change

1. Add `"openai"` to `VALID_ENGINES` and a `ChatGPTProbe` class
   implementing the existing `ask(question) -> {answer_text, source_urls,
   model_id}` protocol, following the `ClaudeProbe` construction pattern.
   Use OpenAI's **web-search-enabled** endpoint so answers reflect live
   retrieval, and return any citation/source URLs the response exposes for
   the `cited` detection. Model id from `ai_visibility.openai_model`
   (never hardcoded); API key from `OPENAI_API_KEY`.
2. Key-gated skip: a missing `OPENAI_API_KEY` skips the engine with a
   logged warning and completes the others (mirrors Gemini).
3. Prefer REST via `requests` + `http_retry` over adding a new SDK if the
   REST surface suffices; if an SDK is required, pin it in
   `requirements.txt`.
4. **Verify the current API surface before coding** — the exact
   web-search endpoint/model names and the shape of returned citations
   must be confirmed against OpenAI's live docs; if web-search + citations
   are not available on the account's tier, implement the engine but
   default it OFF and document the limitation (do not fake citations).

## Acceptance criteria

- Y.2.1 All calls mocked; detection verified for mentioned-only, cited,
  neither, and competitor-cited answers on `ChatGPTProbe` output.
- Y.2.2 `--engines openai` runs only `ChatGPTProbe`; missing
  `OPENAI_API_KEY` skips it with a warning and still completes other
  engines (mocked tests).
- Y.2.3 Rows written with `engine='openai'` and the configured model id;
  per-engine trend query returns openai runs in order.
- Y.2.4 `config.yml` gains `openai_model` and (if needed) endpoint keys;
  `docs/config_reference.md` and `docs/USER_MANUAL.md` document the engine
  and any tier limitation found in the verification step.

---

# Y.3 — Perplexity probe engine

## Problem

Perplexity is a citation-first AI search engine and a growing referral
surface; unlike some engines it returns explicit source citations, making
it a high-signal target for the `cited` metric.

## Required change

1. Add `"perplexity"` to `VALID_ENGINES` and a `PerplexityProbe` class
   implementing the same `ask()` protocol. Use a Sonar (or current
   search-grounded) model that returns citations; map those citations into
   `source_urls` for the existing `cited` detection. Model id from
   `ai_visibility.perplexity_model`; API key from `PERPLEXITY_API_KEY`.
2. Key-gated skip identical to the other optional engines.
3. REST via `requests` + `http_retry` preferred (Perplexity exposes an
   OpenAI-compatible chat endpoint); pin any new dependency.
4. **Verify the current API surface before coding** (model names and the
   citation field in the response) against Perplexity's live docs.

## Acceptance criteria

- Y.3.1 All calls mocked; detection verified for mentioned-only, cited,
  neither, and competitor-cited answers on `PerplexityProbe` output,
  including the citation-URL mapping.
- Y.3.2 `--engines perplexity` runs only `PerplexityProbe`; missing
  `PERPLEXITY_API_KEY` skips it with a warning; others complete.
- Y.3.3 Rows written with `engine='perplexity'` and the configured model
  id; per-engine trend query returns perplexity runs in order.
- Y.3.4 `config.yml` gains `perplexity_model`; docs updated as in Y.2.4.

---

# Y.6 — AI Visibility Index (AIVI): composite 0–100 score

## Problem

The tool reports raw mention/citation rates but no single, trendable
headline number a client can track. Yoast's report leads with an **AIVI
0–100** on a four-axis radar (Mentions, Ranking, Citations, Sentiment) — a
score that makes "are we getting more visible?" answerable at a glance and
comparable across engines and months.

## Required change

1. New module `aivi.py` (pure functions) computing a 0–100 score per
   engine, and an all-engine average, from four normalized 0–100 axes:
   - **Mentions** = share of probed questions where the client was
     mentioned.
   - **Ranking** = client's position on the Y.7 competitor leaderboard,
     normalized (rank 1 → 100, unranked → 0).
   - **Citations** = client-owned citations as a share of total citations
     for the client's questions (from Y.8).
   - **Sentiment** = client % positive (from Y.9); when sentiment is OFF,
     this axis is reported as `n/a` and **excluded from the weighted mean**
     (weights renormalized), never counted as 0 (principle 3).
2. Weights from `config.yml` `aivi.weights` (default equal, per Y-D6).
   Python computes the score; the number is never LLM-derived.
3. Persist per-engine AIVI and axis values to a new SQLite table
   `ai_visibility_index` (`run_ts, engine, aivi, mentions_axis,
   ranking_axis, citations_axis, sentiment_axis, weights_json`) so the
   score is trendable (principle 5).
4. Report: headline AIVI per engine with the four axis values, the
   prior-run delta, and the snapshot caveat. A text radar-equivalent
   (four labeled axis values) suffices; no chart dependency required.

## Acceptance criteria

- Y.6.1 Score is deterministic given axis inputs; unit tests cover
  all-zero (→ 0), all-max (→ 100), and a mixed vector against a
  hand-computed value.
- Y.6.2 Sentiment OFF → sentiment axis `n/a`, weights renormalized over
  the remaining three, score still 0–100 (test).
- Y.6.3 Weights read from config; changing weights changes the score;
  missing/malformed weights fall back to equal with a warning.
- Y.6.4 Table written idempotently with UTC `run_ts` + `engine`; trend
  query returns runs in order; report shows prior-run delta.
- Y.6.5 `docs/USER_MANUAL.md` documents each axis, the weighting, and WHY
  a composite is a snapshot to be read as a trend; `docs/methodology.md`
  updated (new metric).

---

# Y.7 — Competitor mention leaderboard (brand-entity extraction)

## Problem

Our probe detects competitors only when their **domain is cited**
(`competitors_cited`). Yoast's leaderboard ranked **24 brands by how often
they were *named* in answer text**, many without any link. Answer-text
brand naming is the dominant signal in AI answers and we currently miss it
entirely — so we cannot tell a client which rivals the AI recommends
instead of them.

## Required change

1. New module `brand_mentions.py` extracting named brand/organization
   entities from each answer's text, two-pass (per Y-D7):
   - **Gazetteer pass (deterministic):** match `known_brands` + the top
     competitor names/domains from the latest analysis JSON,
     case-insensitively.
   - **LLM pass (gated, fills unknowns):** one call per answer asks the
     model to list organization names present in the text; results are
     stored verbatim as a measured input. Reuses `brief_llm.py` client
     conventions; model id from config; OFF by default
     (`brand_mentions.llm_extraction: false`) — gazetteer-only still
     produces a leaderboard from known brands.
2. New brands the LLM surfaces that are not in `known_brands` are written
   to a review file `brand_mentions_candidates_<topic>_<ts>.md` (pattern:
   `domain_override_candidates.md`) for the user to promote into
   `known_brands` — no silent taxonomy growth.
3. Python aggregates mention counts across all probed questions into a
   ranked leaderboard, with the client's own rank computed and passed to
   Y.6's Ranking axis. Persist to `brand_mentions` SQLite table
   (`run_ts, engine, brand, mention_count, questions_total, is_client,
   source` where source ∈ `gazetteer|llm`).
4. Report: the ranked leaderboard (brand, mentions X/N, engine), the
   client's rank called out explicitly (or "not mentioned").

## Acceptance criteria

- Y.7.1 Gazetteer extraction is deterministic and case-insensitive; a
  synthetic answer naming three known brands yields the right counts
  (test, no LLM).
- Y.7.2 LLM pass mocked: extracted names merged with gazetteer,
  de-duplicated (case/whitespace-normalized), unknowns written to the
  candidates file; `llm_extraction: false` skips it entirely.
- Y.7.3 Leaderboard ranking, client-rank computation, and the "not
  mentioned" case are unit-tested; ties broken deterministically.
- Y.7.4 Table idempotent, per-engine, UTC ts; trend query ordered.
- Y.7.5 `brand_mentions_candidates` file listed with the other candidate
  review files; `docs/USER_MANUAL.md` explains WHAT/WHY; `known_brands`
  promotion path documented in `docs/config_reference.md`.

---

# Y.8 — Categorized, brand-attributed citation table

## Problem

We store `source_urls` per answer but do nothing with them beyond the
binary client-`cited` check. Yoast's citation table lists **every** source
(27 here) with a **Category** (`Publisher`, `Other`, …) and the **brand**
each supports — turning citations into an actionable map of *which sources
the AI trusts for this topic* (a content-partnership and outreach target
list). We already own the classifier to categorize URLs.

## Required change

1. New module `citation_table.py` that, per probed answer, records every
   source URL with: `domain`; a **category** from the **existing**
   content/entity classifier (`classifiers.py` + `classification_rules.json`
   + `url_pattern_rules.yml` + `domain_overrides.yml`) — do **not** add a
   parallel category list; extend the existing editorial files if a needed
   category (e.g. `directory`, `publisher`) is missing; and an attributed
   **brand** (gazetteer/domain match against `known_brands` + leaderboard
   brands; `null` when unknown). Client-owned citations flagged
   `is_client`.
2. De-duplicate identical URLs across questions; keep a count of how many
   answers cited each. Strip nothing — retain tracking params as returned
   (they identify the surfacing engine, e.g. `utm_source=openai`).
3. Persist to `ai_citations` SQLite table (`run_ts, engine, url, domain,
   category, brand, is_client, cite_count`). Feeds Y.6's Citations axis.
4. Report: a citations table (#, URL, domain, category, brand), client
   citations flagged, plus a one-line "top cited domains for this topic"
   summary as the outreach shortlist.

## Acceptance criteria

- Y.8.1 Category is sourced from the existing classifier (test asserts a
  known publisher domain and a known directory domain get the expected
  labels via the current editorial files; any newly added category label
  lives in the existing YAML/JSON, not Python).
- Y.8.2 Brand attribution matches gazetteer/domain; unknown → `null`;
  client URLs flagged `is_client` (test).
- Y.8.3 URL de-dup with `cite_count`; tracking params preserved (test).
- Y.8.4 Table idempotent, per-engine, UTC ts.
- Y.8.5 Any category label added to the editorial files is reflected in
  CLAUDE.md's editorial list; `docs/methodology.md` updated (uses the
  classifier contract); `docs/USER_MANUAL.md` explains the outreach use.

---

# Y.9 — Per-brand sentiment + aspect-keyword extraction

## Problem

Yoast reports **% positive sentiment** for the client and the top
competitor, with extracted **positive/negative keyword** chips that tell
the client *what the AI praises or flags*. We have no sentiment signal at
all. For a nonprofit whose reputation is the product, "what does the AI say
*about* us, not just whether it names us" is high-value.

## Required change

1. New module `answer_sentiment.py` (gated; `sentiment.enabled: false` by
   default, Y-D8). For each answer that mentions the client or the top
   competitor, one LLM classification call returns, as a **measured
   input** stored verbatim: a polarity label (positive/neutral/negative)
   and short positive/negative aspect phrases. Reuses `brief_llm.py`
   conventions; model id from config; subject to `max_total_calls`.
2. **Python computes** % positive per brand from the stored labels
   (principle 1 preserved via Y-D7). Aspect phrases are editorial output,
   surfaced verbatim, never numeric.
3. Persist to `answer_sentiment` SQLite table (`run_ts, engine, brand,
   polarity, positive_aspects_json, negative_aspects_json, answer_excerpt`).
   Feeds Y.6's Sentiment axis.
4. Report (only when enabled): client % positive and top-competitor %
   positive, each with positive/negative keyword chips, the run count,
   and the snapshot caveat. When disabled, the section states "sentiment
   not measured" (principle 3) and Y.6 excludes the axis.

## Acceptance criteria

- Y.9.1 Disabled by default: a run with `sentiment.enabled: false` makes
  zero sentiment calls, the report section reads "not measured," and Y.6
  renormalizes weights (test).
- Y.9.2 Enabled + mocked LLM: % positive computed by Python from stored
  labels (test with a hand-counted set); polarity for negative/neutral/
  positive answers classified into the right buckets.
- Y.9.3 Aspect phrases stored and rendered verbatim; empty-aspect answers
  handled without error.
- Y.9.4 Sentiment calls counted against `max_total_calls`; the cost guard
  reports them (test).
- Y.9.5 `docs/USER_MANUAL.md` explains WHAT (per-brand sentiment + aspect
  keywords) and WHY (reputation signal), and the accuracy caveat that LLM
  sentiment is an estimate read as a trend; `docs/methodology.md` updated.

---

# Y.10 — Engine source-bias profiles + platform-specific recommendations

## Problem

Because citation optimization does not transfer (see Empirical basis), a
single set of recommendations is wrong for a multi-engine world: ChatGPT
rewards encyclopedic/consensus content and cites few sources; Perplexity
rewards fresh, forum-and-community-referenced content and cites many;
Gemini mirrors Google's index; Claude favors well-structured depth. The
tool currently emits engine-agnostic advice, so it cannot tell the client
*what to do differently for each surface they choose to target*.

## Required change

1. New editorial file `engine_profiles.yml`, one block per engine
   (`chatgpt`, `perplexity`, `gemini`, `claude`, extensible), each with:
   `retrieval_backend`, `source_bias` (short phrases), `avg_citations`
   (indicative, dated), `recommended_content_moves` (editorial list),
   and a `confidence` note that these shift over time. All content
   editorial — no engine advice in `.py`.
2. New module `engine_recommendations.py` (pure) that, given the enabled
   engines and the client's per-engine results (AIVI, leaderboard rank,
   citation categories from Y.6–Y.8), emits per-engine recommended moves
   by joining results to `engine_profiles.yml`. Deterministic; no LLM.
3. Emit a **platform-prioritization recommendation**: rank the enabled
   engines for this client by a documented, config-weighted blend of
   (a) current gap (low AIVI = high opportunity), (b) engine reach tier,
   and (c) referral-click tier — with the audience-source caveat stated
   in prose (Google-organic audiences → Google AI surfaces first). This
   is guidance, explicitly labeled indicative.
4. Report: a per-engine "what to change here" section + the prioritization
   list, each carrying the "backends shift; re-measure" caveat.

## Acceptance criteria

- Y.10.1 Recommendations are sourced from `engine_profiles.yml` (test:
  editing a profile changes the output; no advice string is hardcoded in
  Python).
- Y.10.2 Prioritization blend is deterministic and config-weighted; a
  synthetic client with a low-AIVI/high-reach engine ranks it first
  (unit test against hand-computed order).
- Y.10.3 Only enabled engines appear; a disabled engine produces no
  recommendation.
- Y.10.4 `engine_profiles.yml` is listed in CLAUDE.md's editorial list;
  `docs/USER_MANUAL.md` explains WHY per-engine advice differs (low cross
  -engine transfer) and states the vendor/temporal confidence caveat;
  `docs/methodology.md` updated.

---

# Y.11 — Cross-engine transfer / overlap metric

## Problem

The user's core question — "if I'm good on one AI, am I good across all?"
— is empirically answerable **for this specific client** from data the
tool already collects across engines, rather than assumed from industry
averages. Nothing currently computes it.

## Required change

1. New module `engine_transfer.py` (pure) computing, from ≥2 engines of
   the same run:
   - **Client visibility transfer:** on which enabled engines the client
     is mentioned/cited, and a simple transfer statement ("mentioned on
     2 of 3 engines").
   - **Citation-source overlap:** pairwise Jaccard similarity of the
     cited-domain sets per engine (from Y.8), plus the count of domains
     cited by all engines vs by exactly one — the client's own version of
     the industry overlap finding.
   - **Leaderboard-rank divergence:** the client's Y.7 rank per engine and
     the spread.
2. Persist to `engine_transfer` SQLite table so overlap is trendable.
3. Report: a short "Transfer" section stating how much this client's AI
   visibility overlaps across engines, with the explicit interpretation —
   high overlap ⇒ foundational work suffices; low overlap ⇒ per-engine
   targeting needed. Requires ≥2 enabled engines; with one engine it
   states "transfer not measurable (single engine)."

## Acceptance criteria

- Y.11.1 Jaccard and all-vs-one counts computed deterministically from
  synthetic per-engine citation sets (unit test vs hand-computed values);
  identical sets → 1.0, disjoint → 0.0.
- Y.11.2 Client mention/cite transfer statement correct for 0, some, and
  all engines (test).
- Y.11.3 Single-engine run degrades to "not measurable," no crash.
- Y.11.4 Table idempotent, UTC ts, trendable.
- Y.11.5 `docs/USER_MANUAL.md` explains WHAT (this client's actual cross
  -engine overlap) and WHY it answers the "optimize once?" question
  directly, with the caveat that a single run is a snapshot.

---

# Y.12 — Foundational (transferable) GEO readiness score

## Problem

The highest-ROI GEO work is the layer that lifts the client on *every*
engine — crawlability, extractable structure/schema, and off-site brand
authority — yet the tool has no single view of it. AIVI (Y.6) measures the
*outcome* (a lagging indicator that varies per engine); this measures the
transferable *inputs* the client controls (a leading indicator that does
not). Separating them tells the client "fix these foundations first, they
pay off everywhere," which the empirical evidence identifies as the
correct first move.

## Required change

1. New module `foundational_score.py` (pure) aggregating **existing**
   signals into a 0–100 readiness score across three sub-scores:
   - **Accessibility/extractability** from `keyword_profiles.extractability`
     and any existing crawl/JS-gating flags.
   - **Structure/schema** from `keyword_profiles.schema_signals` /
     `schema_recommendations.yml` coverage.
   - **Off-site authority** from Y.7 brand-mention counts across trusted
     third-party sources (the signal reported to predict citation ~3×
     better than backlinks).
   No new external calls; reuse collected data. Weights in `config.yml`
   (`foundational.weights`), documented.
2. This score is **engine-agnostic** by construction and is presented as
   the first, cross-platform priority — visually and narratively ahead of
   the per-engine AIVI in the report.
3. Persist to `foundational_score` SQLite table for trending. Each sub
   -score lists its top 2–3 concrete gaps (pulled from the existing
   `strategic_flags.geo_alerts` / schema recommendations), so the score is
   actionable, not just a number.

## Acceptance criteria

- Y.12.1 Score deterministic from its inputs; all-zero → 0, all-max →
  100, mixed vector matches hand computation (test).
- Y.12.2 Missing sub-score inputs are reported `n/a` and excluded from the
  weighted mean (renormalized), never counted as 0 (principle 3).
- Y.12.3 Each sub-score surfaces concrete gaps from existing flag sources
  (test asserts gaps come from `geo_alerts`/schema recs, not new strings).
- Y.12.4 Weights from config; table idempotent and trendable.
- Y.12.5 `docs/USER_MANUAL.md` explains WHAT (transferable readiness) and
  WHY it is the first priority (it is the only layer that lifts all
  engines at once); `docs/methodology.md` updated.

---

# Y.13 — Client profile & funnel editor in Settings (ConfigManager tab)

## Problem

`client_profiles.yml` (Y.1) is the store, but this is a **multi-client**
tool and the whole point is that a non-developer sets each website's
personas and funnel queries **per client, in the GUI** — not by editing
YAML. There is currently no Settings surface for any of the Y.1 fields, so
without this item the profile feature is developer-only and the "top-of
-funnel vs progression queries set in Settings" requirement is unmet.

## Required change

1. New `ConfigManager` tab **"Client Profile & Queries"** (pattern:
   existing ConfigManager tabs; follow the CLAUDE.md init-order rule —
   instance variables initialized BEFORE `super().__init__()` where the
   existing tabs require it). The tab operates **on the currently selected
   client** (reuse the existing multi-client selector; do not add a second
   client concept).
2. Editable fields, all persisted to that client's block in
   `client_profiles.yml` via a single save path (no partial writes):
   `brand_name`, `domain`, `location`, `primary_city`, `secondary_cities`;
   and a **personas editor** — add/remove personas, and per persona
   add/remove **funnel/intent tiers** (name + `local` flag) with their
   `seed_questions` (free text, one per line, probed verbatim) and
   `templates` (with `{city}` hint). Top-of-funnel and progression tiers
   are ordinary tiers the user names and orders here.
3. A **"Preview generated questions"** action calls
   `profile_questions.generate` (Y.1) for the selected client and shows
   the expanded list (with persona/tier/city tags) so the user sees
   exactly what will be probed before spending on a run — no API calls,
   generation only.
4. Save is atomic and validated (round-trips through Y.1's loader;
   malformed input is rejected with an inline message, never written).
   The GUI never loses unrelated clients' blocks on save.

## Acceptance criteria

- Y.13.1 **Business-logic tests (no tkinter):** the tab's load→edit→save
  round-trip on `client_profiles.yml` is tested at the data layer —
  editing client A's personas leaves client B's block byte-for-byte intact
  (per CLAUDE.md: business logic must not require the GUI framework).
- Y.13.2 **Source-inspection init-order test** (no tkinter, per CLAUDE.md
  `test_config_manager.py` convention): the new tab class initializes its
  instance variables before `super().__init__()`, matching the existing
  tab pattern.
- Y.13.3 The preview action returns Y.1's generated questions for the
  selected client without any network/API call (mocked test).
- Y.13.4 Malformed input (e.g. empty persona label, duplicate tier name)
  is rejected with an inline error and nothing is written (test).
- Y.13.5 Actual widget-interaction tests are the only ones allowed to skip
  when tkinter is unavailable, and are marked accordingly (per CLAUDE.md).
- Y.13.6 `docs/gui_steps.md` and `docs/USER_MANUAL.md` document the tab —
  WHAT (set each client's personas and funnel queries) and WHY (queries
  are the app's job to manage per client; top-of-funnel and progression
  tiers are configured here, not in a CSV) — and `ui-regression.md`
  checklist is satisfied.

---

## Out of scope (explicitly not in this spec)

- Replacing the keyword-CSV entry point. The SERP audit, PAA/PASF, DA
  feasibility, briefs, and schema recommendations are unchanged — this
  spec adds a parallel profile/GEO axis, it does not remove the SEO one.
- Automated content publishing or on-page edits. The tool remains
  measurement + recommendation.
- Any engine whose API cannot return an answer body (mention detection is
  impossible without answer text); such engines are not added.

## Net effect when complete

The tool gains every genuinely additive capability the Yoast report
demonstrates:

- **Inputs/engines (Y.1–Y.5):** profile-seeded, persona-segmented question
  generation feeding the trend-tracked probe across **Claude, Gemini,
  ChatGPT, and Perplexity**, with cross-engine, per-persona share of voice.
  All **per-client and editable in Settings (Y.13)** — each website has its
  own personas and named funnel tiers (top-of-funnel + progression), with a
  no-cost preview of the exact questions before any paid run.
- **Outputs/report (Y.6–Y.9):** a single **AI Visibility Index (0–100)** on
  four axes, a **mention-based competitor leaderboard** (via brand-entity
  extraction, not just cited domains), a **categorized + brand-attributed
  citation table** (reusing the existing classifier, doubling as an
  outreach target list), and **per-brand sentiment with aspect keywords**.
- **Engine strategy (Y.10–Y.12):** a **foundational readiness score** (the
  transferable, do-first layer), **per-engine recommendations + a platform
  -prioritization list** (because optimization does not transfer), and a
  **cross-engine transfer metric** that answers "am I good on one AI ⇒
  good on all?" from the client's own data instead of industry averages.

All of it is trend-stored in SQLite and gated on cost. It keeps everything
Yoast lacks — DA feasibility scoring, PAA/PASF harvesting, content briefs,
schema recommendations — so the result is a strict superset of both tools,
not a copy of either.

The one principled tension to resolve with the user before building
Y.7/Y.9 is Y-D7: brand extraction and sentiment require an LLM derivation
step. The spec reconciles this by treating the LLM output as a measured,
stored input while Python computes every count, rank, and percentage — but
the user should confirm they accept that framing, since it is the one
place this spec bends the "LLM never derives" principle.
