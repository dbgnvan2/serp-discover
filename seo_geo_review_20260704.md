# SEO / GEO Review & Recommendations — 2026-07-04

Scope: full-repo review of `serp-discover` (Tool 1) against (a) the Neil Patel
"Keywords are dead" transcript (micro-moments / AI-citation / GEO themes) and
(b) an independent SEO/AI-search expert assessment. Covers both **feature
recommendations** and **code review findings**.

Three ID families are used so items can be referenced in future specs:

- **T.x** — features derived from the transcript
- **G.x** — independent GEO/SEO expert recommendations
- **C.x** — code review findings (bugs, hygiene, convention violations)

---

## Part 0 — Where the tool already stands (credit where due)

Before adding anything, it matters that several of the transcript's headline
claims are **already implemented** here — in some cases better than the video
prescribes:

| Transcript theme | Status in this tool |
|---|---|
| "Understand the moment, not the keyword" (micro-moments: know/go/do/buy) | **Covered.** The 5-bucket SERP intent taxonomy (`intent_verdict.py`, `intent_mapping.yml`) maps almost 1:1 — want-to-know→informational, want-to-go→local, want-to-buy→transactional, comparison→commercial_investigation — and is computed deterministically per keyword with mixed-intent detection and a backdoor strategy hint. |
| "Same keyword, different emotional moment" (pain / budget / doubt moments) | **Covered, arguably ahead of the video.** The four Bowen traps in `strategic_patterns.yml` (Medical Model / Fusion / Resource / Blame-Reactivity) are exactly an emotional-moment classifier for this niche, with pre-written reframes. |
| AI Overviews are the new surface | **Partially covered.** AIO presence, full text, and **cited sources** are captured per keyword (`serp_audit.py:830-876`), including token-followup fetches, a client-cited flag, and a dedicated report section ("Section 4: AI Overview / GEO Opportunity Analysis", `prompts/main_report/system.md:318`). |
| Zero-click / rankings ≠ clicks | **Aware but unmeasured.** The tool reads AIO presence but has no click data (see G.4). |
| FAQ sections from question clusters | **Not covered** — the single biggest transcript-aligned gap (see T.1). |
| 75% of AI citations come from third-party surfaces | **Data exists, analysis missing** (see T.3). |

Architectural strength worth preserving through any of the changes below: the
**deterministic-verdict → LLM-synthesis → validator** design
(`intent_verdict.py` / `brief_validation.py` / `test_validation_consistency.py`).
Every new GEO field added to `keyword_profiles` must get a matching validator
rule, per the existing canary-test convention.

---

## Part 1 — Transcript-derived feature recommendations (T.x)

### T.1 — PAA → FAQ brief section with answer-first formatting guidance (HIGH)

Transcript: *"Turn your top 10 [question clusters] into clean FAQ sections on
your main pages and you'll move your citation rate more than months of
technical SEO."* Also: lead with the answer; write the question as a heading
in the words a person would use.

The tool already captures and intent-tags every PAA question
(`serp_audit.py:1446-1447`), and even builds a `bowen_reframe_faqs` payload
key (`brief_prompts.py:160`) — **but no prompt ever references it** (see C.2),
and the brief contains zero guidance on FAQ blocks, question-shaped H2s,
answer-first paragraphs, or FAQPage JSON-LD.

Recommendation — add a required brief section (e.g. "Section 5b: FAQ /
Answer-Extraction Plan") that, per priority keyword:

1. Lists the top PAA questions verbatim (validator-checkable against
   `paa_analysis`, consistent with RULE 4).
2. For External Locus questions, pairs each with its Bowen reframe angle
   (this is the fix for C.2 — the *medical-model* questions are the reframe
   candidates per `intent_classifier.py:8-12`).
3. Mandates formatting guidance in the recommendation: question as H2/H3 in
   natural language, answer in the first 1–2 sentences, then depth.
4. Emits a ready-to-paste FAQPage JSON-LD stub (see G.2).

This is the highest leverage/effort ratio in the whole review: the data
pipeline is done; it's a prompt + routing + validator change.

### T.2 — Answer-extractability score for enriched pages (HIGH)

Transcript: *"AI chunks the page and scans for one thing: can I lift a
complete, confident answer right out of this page? If the answer is buried in
paragraph 8, AI skips you."*

`url_enricher.py` already fetches ranking pages and extracts headings, word
count, schema types, and `faq_present`. Extend `extract_features` with an
**extractability score** per page:

- Are H2/H3s question-shaped? (reuse `title_patterns.py` regexes on headings
  — `question`, `how_to`, `what_is` patterns)
- Do question headings match/overlap captured PAA questions for that keyword?
- First-paragraph answer density: length of text before the first H2;
  presence of a direct-answer opener (short first paragraph after a question
  heading).
- FAQPage / QAPage schema present (already captured).

Then report per keyword: *average extractability of pages the AIO cites vs.
pages that merely rank* — and where the client's own page sits. This turns
"format for AI" from advice into a measured gap. New editorial knobs
(question-heading regexes if extended beyond title_patterns, score weights)
belong in YAML per the project convention.

### T.3 — Third-party citation surface report ("the 75%") (HIGH)

Transcript: *"Most of what AI cites isn't your page at all… Reddit, review
sites, roundups. That list is your outreach plan."*

The tool already has both halves of this and never joins them:
`ai_overview_citations` (domain + link per keyword) and `EntityClassifier`
(directory / media / counselling / nonprofit …). Add an aggregation:

- Classify every AIO-cited domain by entity type.
- Report the citation mix per keyword and overall: e.g. "AIO citations: 40%
  directory (psychologytoday.com ×6, counsellingbc.com ×3), 25% media, 10%
  forum…"
- Flag **outreach targets**: third-party surfaces cited on the client's
  priority keywords where the client has no presence (directory profile
  missing/thin, roundup lists that omit Living Systems).
- For a nonprofit counselling org the practical GEO targets are Psychology
  Today / CounsellingBC / TherapyTribe profile completeness, BC counselling
  roundups, and Reddit threads (r/vancouver, r/therapy) — the report should
  name the actual cited URLs so outreach is concrete.

Data exists; this is a metrics + report-section change, plus a brief prompt
addition ("Section 4b: Off-site citation surfaces / outreach targets").

### T.4 — Rank-vs-citation divergence analysis (MEDIUM)

Transcript: *"90% of pages AI cited rank 21 or lower… your Google rank and
your AI visibility are two separate scores."*

Join `organic_results` with `ai_overview_citations` per keyword and surface:

- **Cited-but-not-ranking** domains (in AIO citations, absent from top 10) —
  evidence that extraction-friendly content beats rank; also feeds T.3.
- **Ranking-but-not-cited** URLs — especially the client's own: "you rank #4
  for X but the AIO cites three competitors" is the single most actionable
  GEO alert this tool could emit, and both fields are already in
  `client_position`. Make it an explicit `strategic_flags`-adjacent flag so
  the advisory can prioritize it.

### T.5 — Conversational / situational query probes (MEDIUM)

Transcript: *"Six words or more triggers an AI answer 77% of the time…
nobody types keywords into ChatGPT, they describe the whole situation."*

Current query expansion is narrow: `A` (root+geo), `A.1` (informational),
`A.2` (cost). Add a third generated variant class — situation-style long
queries composed from PAA + autocomplete material (e.g. root "couples
counselling north vancouver" → "my partner refuses to go to couples
counselling what can I do"). Concretely:

- Source candidates from captured PAA questions and related searches (they
  are already near-conversational); optionally template a few per intent
  bucket. Templates are editorial → YAML file, not Python.
- Track and report **AIO trigger rate by query word-count** across the run,
  which directly tests the 23%-vs-77% claim on the client's own market.
- Budget note: each probe is a SerpAPI call; gate behind Deep Research mode
  or a per-run cap in `config.yml`.

### T.6 — Capture per-item detail from `discussions_and_forums` (LOW)

The module is captured but flattened to generic "Discussion/Forum" expansion
rows (`serp_audit.py:992-998`). Keep the individual thread titles, URLs and
forum names (subreddit etc.) so T.3's outreach list can say *which* Reddit
threads Google surfaces for each keyword, not just that forums appear.

---

## Part 2 — Independent GEO/SEO expert recommendations (G.x)

### G.1 — Direct AI-engine visibility probing (HIGH, phased)

The tool measures Google's AIO only. The transcript's own data says citation
behavior swings wildly between model versions (8%→56%→down for brand-site
citations), which is precisely why you measure **trend, not point values**.
A phased approach that fits a small nonprofit budget:

- **Phase 1 (cheap, uses the key you already have):** a probe script that
  asks Claude (web-search-enabled) N situation-style questions from the T.5
  set and records whether "Living Systems" / livingsystems.ca is mentioned or
  cited, storing results in `serp_data.db` per run for trend lines. This
  reuses the existing Anthropic client (`brief_llm.py`) and SQLite layer.
- **Phase 2 (optional):** add other engines behind the same interface
  (SerpAPI exposes some AI-engine endpoints; direct APIs for others). Keep it
  provider-pluggable like the DataForSEO/Moz pair.
- Report as a new section: AI-engine mention rate over time, alongside AIO
  citation data. Do **not** treat single-run numbers as signal; the report
  language should say so (this matches the existing RULE 8 honesty ethos).

### G.2 — Schema/JSON-LD recommendations in the brief output (HIGH)

The enricher *reads* competitors' `schema_types` (`url_enricher.py:97-107`)
but the brief never recommends markup. For a YMYL therapy site the high-value
types are: `FAQPage` (pairs with T.1), `LocalBusiness`/`ProfessionalService`
(NAP + geo for the local pack), `Organization`, `Person` (practitioner
credentials), and `MedicalWebPage`/`Article` with `reviewedBy` where
appropriate. Add:

- A schema-gap line per priority keyword: "pages cited by the AIO for this
  keyword carry [FAQPage, MedicalWebPage]; client page has [none]" — the data
  is already captured per enriched URL.
- Brief guidance (prompt-level) that Section 7 recommendations name the
  schema types to add. Which types are recommended per content type is an
  editorial mapping → YAML, not Python.

### G.3 — E-E-A-T / YMYL author-signal detection (MEDIUM)

Therapy is YMYL: both Google's systems and AI engines weight author expertise
heavily for health queries. Extend enrichment to detect byline/credential
signals on ranking pages (author name present, credential strings — RCC,
MSW, PhD, "reviewed by" — `Person`/`author` in JSON-LD) and report the share
of top-10 pages carrying them per keyword. Brief output should then say
whether credentialed authorship is table-stakes on that SERP. Credential
token list is editorial → YAML.

### G.4 — Google Search Console integration (MEDIUM)

The tool sees rank but not clicks, so the transcript's core economics (top
spot CTR falling >60% under AIO; 57%+ zero-click) are invisible to it. GSC's
API is free and first-party for the client's own domain:

- Pull impressions/clicks/CTR per query for client pages in the keyword set.
- Correlate: keywords with `has_ai_overview=true` vs CTR at same rank —
  a direct measurement of the "sponge effect" on the client's own traffic.
- Feed `strategic_flags`: a page whose rank is stable but whose CTR fell
  after AIO appeared is a "reformat for extraction" candidate (T.2), not a
  "write new content" candidate.

### G.5 — Secondary index check: Bing (LOW)

ChatGPT search grounds substantially on Bing's index. SerpAPI supports
`engine=bing`; an optional low-frequency check of whether the client ranks
on Bing for the same keyword set closes a blind spot for a large AI-referral
surface at trivial cost. Gate behind a config flag; default off.

### G.6 — Content freshness / decay tracking (LOW)

The enricher can capture `article:published_time` / `dateModified` where
present; storage already keeps run history. Report the age profile of the
top 10 per keyword (AI engines and Google both favor fresh YMYL content) and
flag client pages that are aging relative to the SERP median.

### G.7 — Explicitly not recommended (for the record)

- **llms.txt** — adoption/consumption by major engines remains unproven;
  fine for the client to add on the website side, but not worth tool code.
- **Chasing per-model citation quirks** — the transcript's own 8%→56%→down
  story is the argument: build extraction-friendly pages (T.1/T.2) and
  measure trends (G.1), don't optimize for one engine's current behavior.

### Suggested sequencing

1. **Now:** C.1 bug fix, C.2 rewire, C.3 hygiene (small, protective).
2. **Next chunk:** T.1 + G.2 (FAQ section + schema recs — prompt/YAML work,
   biggest client-visible win).
3. **Then:** T.3 + T.4 + T.6 (citation-surface analysis — data already
   captured, pure aggregation/reporting).
4. **Then:** T.2 (extractability scoring — enricher work).
5. **Later:** T.5 + G.1 (probes; new API spend), G.3, G.4, G.5, G.6.

---

## Part 3 — Code review findings (C.x)

### C.1 — BUG: `lstrip("www.")` corrupts domains starting with w/. (HIGH)

`dataforseo_client.py:202`, `dataforseo_client.py:270`,
`run_feasibility.py:91`. `str.lstrip("www.")` strips a **character set**
`{w, .}`, not the prefix string: `wellspringcounselling.ca` →
`ellspringcounselling.ca`, `wix.com` → `ix.com`. Any competitor domain
beginning with "w" gets a wrong cache key and a wrong/missing DA lookup —
silently skewing the feasibility scores that drive keyword prioritization
(and `wellspringcounselling.ca` is a named competitor in this niche). Fix:
`re.sub(r"^www\.", "", host)` or `host.removeprefix("www.")`, plus a
regression test.

### C.2 — BUG/design conflict: `bowen_reframe_faqs` mis-wired and unused (HIGH)

`brief_prompts.py:160` populates `bowen_reframe_faqs` from the **Systemic**
PAA bucket, but the design intent (`intent_classifier.py:8-12`) is that
**External Locus** (medical-model) questions are the reframe candidates —
those are the ones you answer in Bowen framing to differentiate. And no
prompt file references the key at all, so the payload is dead weight either
way. Fix together with T.1: feed External Locus questions (Systemic ones can
be listed separately as "already-aligned demand"), reference the key in the
main-report prompt, and add a validator rule per the
`test_validation_consistency.py` canary convention. Update
`docs/intent_classification.md:8`, which currently documents the buggy
behavior as intended.

### C.3 — Repo hygiene: data, DB, and client outputs committed (HIGH)

Tracked in git despite the CLAUDE.md rule that output/draft files stay
local: `serp_data.db` (mutable binary, churns every run), the entire `raw/`
tree (scraped SERP responses **containing third-party business PII** — names,
phones, addresses), `output/*.{json,md}`, `exports/*.csv`,
`diff_report.json`, root-level `advisory_briefing_*`/`content_opportunities_*`
reports, and client keyword CSVs. `.gitignore` covers only `*.xlsx`, `*.png`,
`normalized/`, `venv/`, `.env` — and `normalized/` files added before the
ignore rule are still tracked. Fix: expand `.gitignore` (`*.db`, `raw/`,
`output/`, `exports/`, `diff_report.json`, report-name globs), then
`git rm --cached` the tracked offenders in one hygiene commit.

### C.4 — Convention violation: hardcoded editorial content in Python (MEDIUM)

Direct violations of the project's own "editorial content lives in config
files" rule:

- `serp_audit.py:916-920` — PAA `trigger_map` ("Commercial", "Distress",
  "Reactivity" trigger words) hardcoded.
- `serp_audit.py:155-161` and `pattern_matching.py:16-22` — two divergent
  copies of a domain-vocabulary `STOP_WORDS` list (vancouver, counselling…).
- `serp_audit.py:1169-1182` — `service_like_tokens` and AI-alternative
  phrase templates.

Externalize to YAML (one file or extend `intent_classifier_triggers.yml` /
a new `serp_audit_vocab.yml`), delete the duplicates, and per CLAUDE.md do it
in the same change as the next editorial-knob addition (T.1/T.5 both add
editorial YAML — natural moment).

### C.5 — Unpinned dependencies (MEDIUM)

`requirements.txt` pins nothing; `anthropic` and `pandas` in particular ship
breaking changes. Also `textblob`/`wordcloud`/`matplotlib` are listed as hard
requirements but treated as optional in code (`serp_audit.py:42-52`). Pin
with `>=,<` ranges (or a constraints file) and split optional extras.

### C.6 — Retry semantics inconsistent across API clients (MEDIUM)

`serp_audit.py:322-346` retries **every** error response identically —
including non-retryable ones (bad key, exhausted quota), wasting paid calls —
and has no 429/`Retry-After` handling. Meanwhile `moz_client.py:160-186` and
`dataforseo_client.py:165-185` never retry: one transient failure silently
drops a whole DA batch (returns `{}`), which then reads as "No DA Data" or
skews averages downstream. Unify: retry only transient statuses, honor
Retry-After, and add one retry round to the DA clients.

### C.7 — SQLite `IN (…)` cache lookups can exceed the 999-variable limit (LOW)

`moz_client.py:228`, `dataforseo_client.py:235` — `_cache_lookup` passes all
URLs/domains as placeholders in one query; >999 raises `OperationalError`.
Batch the lookup like `_fetch_batch` already does. Related: connections are
opened per call with no `timeout=`/WAL while `serp_audit.py` writes the same
DB in-process — add `timeout=` and consider WAL mode.

### C.8 — Silent broad excepts hide config errors (LOW)

`feasibility.py:42-44` (`except Exception: pass` → silently uses default
thresholds on malformed `shared_config.json`), `serp_audit.py:1201`,
`serp_audit.py:1884` (keyword_profiles build failure logged at warning,
output silently missing a documented field), bare `except:` at
`config_manager.py:1798-1815`. At minimum log at warning with the exception;
for the thresholds case, a wrong threshold silently changes every
feasibility verdict.

### C.9 — Out-of-repo `shared_config.json` path, duplicated (LOW)

`serp_audit.py:64` and `feasibility.py:29` both resolve
`../shared_config.json` (outside the repo). Behavior depends on deploy
layout and falls back silently. Move the shared values into `config.yml` (or
document the external contract), and de-duplicate the resolution logic.

### C.10 — Minor: interface + time-handling inconsistencies (LOW)

`compute_feasibility` returns `feasibility_status`/`avg_serp_da` while
`generate_hyper_local_pivot` expects `status`/`avg_competitor_da`
(`feasibility.py:99-105` vs `:170-171`) — every caller must remap; align the
keys. `datetime.utcnow()` at `serp_audit.py:1907` is deprecated; storage
uses naive local time while DA caches use UTC — standardize on
`datetime.now(timezone.utc)`.

---

## Part 4 — One-page priority summary

| # | Item | Type | Effort | Impact |
|---|------|------|--------|--------|
| C.1 | Fix `lstrip("www.")` domain corruption | Bug | XS | Feasibility scores correct for w-domains |
| C.2 | Rewire + use `bowen_reframe_faqs` (External Locus) | Bug | S | Unlocks the tool's core reframe play in briefs |
| C.3 | Untrack DB/raw/outputs; expand .gitignore | Hygiene | S | Stops PII + binary churn in git history |
| T.1 | FAQ / answer-first brief section (+G.2 schema stubs) | Feature | M | The transcript's #1 tactic; pipeline already exists |
| T.3 | Third-party citation surface / outreach report | Feature | M | Addresses the "75% off-site" GEO reality |
| T.4 | Rank-vs-citation divergence flags | Feature | S | "Ranks but not cited" is the key GEO alert |
| T.2 | Answer-extractability scoring in enricher | Feature | M | Measures what AI actually selects for |
| C.4 | Externalize hardcoded editorial vocab | Convention | S | Restores the project's own editorial contract |
| T.5 | Situational long-query probes + AIO-rate-by-length | Feature | M | Tests the 23%/77% claim on this market |
| G.1 | AI-engine mention probing (Claude first, trend-based) | Feature | M | True GEO measurement beyond Google AIO |
| G.4 | GSC integration (sponge-effect measurement) | Feature | M | Connects rank to actual clicks |
| G.3/G.5/G.6 | E-E-A-T signals / Bing check / freshness | Feature | S–M | YMYL and secondary-surface coverage |
| C.5–C.10 | Pinning, retries, SQLite limits, excepts, paths | Hardening | S | Reliability of paid-API pipeline |
