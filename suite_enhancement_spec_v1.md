# Enhancement Specification — Closing the Audit Gaps (Three-Tool Suite) v1

## Status of this document

Implementation spec for the **Do**-ranked enhancements in
`three_tool_audit_review_20260721.md` (the coverage review of serp-discover,
serp-compete, and TalkingToad against Neil Patel's 17-step SEO audit).

**Acceptance criteria** subsections are binding. **Implementation notes** are
guidance. Where this document and the review disagree, this document wins;
where this document and a repo's own `CLAUDE.md` disagree, the repo's rules win.

### Scope decision (stated assumption)

"The missing pieces" is read as the review's four not-green audit rows plus the
suite-level items that were marked **Do**. In scope: **TT-1, TT-2, TT-3, SC-1,
X-1, X-2, X-3, X-4**, and **TT-4** as an optional stretch. Out of scope: the
review's Declines (**TT-5** cross-web plagiarism, **SC-2** competitor CWV) and
**SD-1** (serp-discover's G.3/G.4 are already specified in
`seo_geo_deferred_spec_v1.md` — ship those from that spec, not this one).

This spec spans three repos. It is a **cross-tool** contract; per-repo commits
implementing an item MUST carry a `Spec: suite_enhancement_spec_v1.md#<item>`
reference, following each repo's existing traceability convention.

### Confidence caveat (binding on the author of the code)

Several required changes below reference internal structures I have verified only
at the docs/catalogue level, not by reading source. Each such point is marked
*(verify in code)*. If the named module, table, or field does not exist as
described, **stop and report** before improvising — the base has drifted from the
docs and the acceptance criteria may need revision.

### Decisions applied — 2026-07-21 (owner)

These supersede the original gate defaults below. The self-contained per-repo
stubs (`suite_enhancement_spec_TALKINGTOAD_v1.md`,
`suite_enhancement_spec_SERPDISCOVER_v1.md`,
`suite_enhancement_spec_SERPCOMPETE_v1.md`) reflect them and are the current
build source of truth.

- **Apps stay independent** — no forced shared client profile across the three
  tools (not all users run all three). **X-1 (orchestration + shared profile) is
  dropped** as a shared feature; keep only as an optional personal runner if ever
  wanted. **G-D / G-E are void.**
- **X-2 (AI-citation loop)** becomes **optional / deferred**, off by default —
  only relevant to owners running both TalkingToad and serp-discover. **G-F**
  (the `AI_CITED_PAGE` source) remains an open code-check.
- **TT-1 (CWV):** source = PageSpeed Insights (**G-A** resolved); page set =
  **the site's primary navigation-menu pages** (not full-site, not traffic top-N;
  **G-B** resolved to nav-menu sampling with the cap kept as a safety limit);
  owner supplies `PSI_API_KEY`.
- **TT-2 (cannibalization):** thresholds confirmed — **G-C** resolved (≥2 own
  URLs, ≥10 impressions).
- **Build now = Phase 1 only:** TT-3, TT-2, SC-1, X-4. TT-1 later; TT-4 optional;
  X-2/X-3 deferred.
- **TalkingToad — DECISION B (2026-07-21): hold all new-code work** (TT-3, TT-2,
  TT-1, TT-4) until the in-flight R3→R5 scoring refactor lands, so codes are born
  into the final derived-scoring schema. Only **X-4** shipped (docs). Implementation
  intel captured in `suite_enhancement_spec_TALKINGTOAD_v1.md`. serp-compete (SC-1)
  and the other repos' Phase-1 items are unaffected.

---

## Reading before changing

Per repo, before touching code:

- **TalkingToad** — `CLAUDE.md`; `docs/functional-specification.md`;
  `docs/thresholds.md`; the issue-catalogue generation contract in
  `docs/issue-codes.md` header (edit `api/crawler/issue_checker.py`
  `_CATALOGUE` / `_ISSUE_SCORING` / `_AI_READINESS_CONFIDENCE`, then re-run
  `scripts/generate_issue_codes_doc.py`); `PLAN-V4.0.md` (the explainer
  standard — binding for any new code); the GSC integration and
  `scoring_model_version` conventions.
- **serp-discover** — `CLAUDE.md`; `methodology.md` (contract doc — update in the
  same change as any file it references); `seo_geo_deferred_spec_v1.md`
  (design principles, canary-test convention); `probe_ai_visibility.py`,
  `gsc_client.py`, `storage.py`, `shared_config.py`.
- **serp-compete** — `README.md`; `shared_config.json` (the config authority);
  `docs/SPEC_COVERAGE_REPORT_v3.md`; the v3 EEAT / page-structure extraction /
  handoff-ingestion modules.

---

## Design principles (inherited, binding)

Carried verbatim from `seo_geo_deferred_spec_v1.md` and TalkingToad's standards:

1. **Deterministic code computes; the LLM writes.** Every new metric is
   pre-computed and passed as data. No LLM derives a number that code can compute.
2. **Editorial content lives in YAML/JSON.** Thresholds, token lists, templates,
   and category labels go in config files, never hardcoded in source.
3. **Absent data is stated, not faked.** Every new data block carries a
   `data_available` (or equivalent) flag. Old artifacts without the new fields
   flow through without crashing and without fabricated zeros presented as
   measurements.
4. **Paid / external calls are gated.** Anything spending an API quota or hitting
   a new external service is **off by default**, capped in config, and the run
   log states how many external calls it made.
5. **Trend over point values.** Anything whose value drifts over time (AI-engine
   behaviour, CWV, citations) stores history and reports change; single-run
   numbers are labelled snapshots.
6. **(TalkingToad) Every new issue code ships a full V4 explainer.** Per
   `PLAN-V4.0.md`: `definition`, `impact`, `fix`, `confidence` tier
   (Established / Reasonable proxy / Heuristic), **plus** `good_vs_bad` and
   `how_it_can_mislead`. A code without the "how it can mislead" + evidence-tier
   field is incomplete and fails the help-parity test.

---

## Decision gates — RESOLVE before the gated items start

| Gate | Item(s) | Question | Proposed default (used if unanswered) |
|---|---|---|---|
| G-A | TT-1 | CWV data source: PageSpeed Insights API (lab + CrUX when present) vs CrUX-only vs a headless-Lighthouse container | **PSI API** — one key, free tier, no browser to host |
| G-B | TT-1 | Per-run page budget for CWV (each page = 1 PSI call, rate-limited) | **10 pages/run**: home + top service pages + top-GSC-traffic pages |
| G-C | TT-2 | Cannibalization definition | **≥2 own URLs** with impressions for one query in the GSC window, min **10 impressions** on the query |
| G-D | X-1 | Orchestration surface: standalone CLI runner vs a button in an existing GUI; and where the merged report is written | **Standalone CLI runner** (`run_suite_audit.py`) writing a dated combined report; GUI button later |
| G-E | X-1 | Canonical client-profile home | **Extend `shared_config.json`** (already read by serp-compete and, via `shared_config.py`, by serp-discover) — do not invent a new file |
| G-F | X-2 | `AI_CITED_PAGE` data source + export shape in TalkingToad | *(verify in code)* — resolve during TT read before wiring |

Gates G-A/G-B block **TT-1** only. G-C blocks **TT-2** only. G-D/G-E block
**X-1**. G-F blocks **X-2**. No other item is blocked.

---

## Execution model & sequencing

Free-first, dependency-ordered. Items within a phase are independent unless noted.

- **Phase 1 — free, no new dependency (do now):** TT-3, TT-2 (after G-C), SC-1,
  X-4. These need no new API and no new credential.
- **Phase 2 — free integration (after Phase 1):** X-2 (after G-F), X-1 (after
  G-D/G-E; benefits from TT/SC changes already landed), X-3 (needs X-1's runner).
- **Phase 3 — external dependency (deliberate):** TT-1 (after G-A/G-B).
- **Optional stretch, any time:** TT-4.

---

## Definition of done (whole spec)

1. Each in-scope item's acceptance criteria pass with the owning repo's full test
   suite green (no new failures, no newly skipped business-logic tests).
2. Every new editorial surface (threshold, token list, template) is in YAML/JSON
   and listed in the owning repo's editorial-content register (`CLAUDE.md`).
3. Every new TalkingToad issue code carries a full V4 explainer and passes the
   catalogue↔help parity test; `docs/issue-codes.md` regenerated.
4. Docs updated in the same change: TalkingToad `functional-specification.md` +
   `thresholds.md` + `user-guide.md`; serp-discover `methodology.md` +
   `USER_MANUAL.md`; serp-compete `USER_MANUAL.md` + `SPEC_COVERAGE_REPORT`.
5. Each commit carries `Spec: suite_enhancement_spec_v1.md#<item>`.
6. A closing status report `suite_enhancement_status_<date>.md` maps every
   acceptance criterion to a commit hash or an explicit "not done + reason".

---

# Phase 1 — free, no new dependency

## TT-3 — Measured crawl-time response speed  *(Blog step 7)*

### Problem
TalkingToad reports page-speed only via proxies (`PAGE_SIZE_LARGE`,
`PAGE_TIMEOUT`, image weight). The crawler already fetches every page but does not
record how long the server took to respond, so there is no measured speed signal.

### Required change
1. During the existing crawl fetch, capture **time-to-first-byte / total response
   time** per URL (the crawler's HTTP client already has the timing; expose it).
   *(verify in code — the async fetch layer.)*
2. Persist `response_ms` on the page record and in the crawl DB
   (`talkingtoad.db`), so it can trend across runs (principle 5).
3. New issue code **`PERF_SLOW_RESPONSE`** (category: CRAWLABILITY or a new
   PERFORMANCE category — see TT-1). Severity from a config threshold in
   `docs/thresholds.md` / the thresholds config: default **warning ≥ 1500 ms**,
   info ≥ 800 ms. Confidence tier: **Reasonable proxy** (server latency is a real
   but partial component of perceived speed).
4. Full V4 explainer (principle 6), incl. `good_vs_bad` (a 300 ms vs a 2500 ms
   response) and `how_it_can_mislead` (a one-off slow response under load is not a
   chronic problem; TTFB ≠ full render — that's TT-1's job).

### Acceptance criteria
- TT-3.1 Every crawled page record carries a numeric `response_ms`; a fixture
  crawl asserts the field is populated and persisted.
- TT-3.2 `PERF_SLOW_RESPONSE` fires above the configured threshold and not below
  it (unit test at boundary values); threshold is read from config, not hardcoded.
- TT-3.3 The code appears in `_CATALOGUE` with a full V4 `issueHelp.js` entry;
  catalogue↔help parity test green; `docs/issue-codes.md` regenerated.
- TT-3.4 Old crawl rows without `response_ms` do not crash reporting
  (data_available handling).

## TT-2 — Keyword cannibalization via GSC  *(Blog step 4)*

### Problem
Two of the client's own pages competing for one query is invisible. TalkingToad
detects within-site title/meta duplicates but not query-level self-competition,
and it already holds GSC data that makes this a query, not a new integration.

### Required change
1. Using the existing GSC link, for each query in the GSC window, group the
   **client URLs** receiving impressions/clicks. *(verify in code — confirm the
   GSC layer exposes per-query page breakdowns; if it returns query-only
   aggregates, add a query×page fetch dimension.)*
2. New **site-scoped** issue code **`KEYWORD_CANNIBALIZATION`** (a single
   site-level deduction per the R5 scope model, not one per page). Fires per
   gate **G-C**: ≥2 own URLs for one query, query ≥ min-impressions. Payload
   lists the competing URLs, their impressions/clicks/avg position, and which URL
   GSC favours (highest clicks/position).
3. Recommendation text: consolidate into one canonical page + 301 the weaker
   URL(s); reference the winning URL by name. Confidence tier: **Reasonable
   proxy** (GSC impression overlap strongly indicates but does not prove intent
   overlap).
4. Thresholds (`min_urls`, `min_impressions`, GSC lookback) in config, not code.
5. Full V4 explainer, incl. `how_it_can_mislead`: legitimately distinct pages
   (a service page and a blog post) can share a query without true cannibalization
   — the flag is a prompt to review, not a verdict.

### Acceptance criteria
- TT-2.1 On a synthetic GSC fixture with one query mapped to two client URLs above
  threshold, the code fires once, site-scoped, naming both URLs and the favoured
  one.
- TT-2.2 A query mapped to a single URL, or below min-impressions, does not fire.
- TT-2.3 With GSC not connected, the check is silently skipped and the report
  states the check requires a GSC connection (never guesses).
- TT-2.4 Thresholds are config-driven (test overrides them and sees behaviour
  change); catalogue↔help parity green; docs regenerated.

## SC-1 — Competitor GEO / extractability comparison  *(Adjacent; extends steps 11, 17)*

### Problem
serp-compete scores competitor pages for *language* (medical vs. systems) and
EEAT, but not for the **structural** reasons AI engines cite them. It already
fetches and extracts competitor page structure (v3), so the signals are within
reach.

### Required change
1. On the competitor pages serp-compete already scrapes, compute a compact
   **extractability/GEO profile** per page: schema types present (esp. FAQPage /
   Article / Organization / Person), author byline + credential presence,
   FAQ-answers-in-HTML, answer-first structure (lead paragraph under H2), and
   question-shaped headings. Reuse TalkingToad's AI-readiness heuristics — prefer
   a **shared, ported checker module** over a divergent second implementation
   *(verify: whether TalkingToad's checker can be imported or must be re-expressed;
   if re-expressed, the token/threshold lists live in `shared_config.json`,
   principle 2).*
2. Attach the profile to each competitor page record and surface it in the
   **strategic briefing**: for every "traffic magnet", state *why* it is likely
   cited ("ranks #2, AI-cited; carries FAQPage schema + credentialed author +
   answer-first structure") and contrast with the client's equivalent page when
   known (from the handoff / shared profile).
3. Do not add competitor performance/CWV (that is SC-2, declined).

### Acceptance criteria
- SC-1.1 Each audited competitor page record gains a GEO-profile block with the
  listed fields; unit tests for a schema-rich page, a bare page, and a
  credentialed-author page.
- SC-1.2 The briefing renders at least one "why cited" structural rationale per
  traffic magnet when the data supports it, and says so honestly when it does not.
- SC-1.3 All editorial token/threshold lists used by the ported heuristics live in
  `shared_config.json`; no new hardcoded editorial content in Python.
- SC-1.4 Existing serp-compete suites stay green; new logic covered by the v3 test
  suite conventions.

## X-4 — Document the backlink-exclusion decision  *(Blog step 16)*

### Problem
Step 16 (backlink profile) is a real capability gap, deliberately not built (DA is
used as a single proxy across the suite). Left undocumented it reads as an
oversight rather than a choice.

### Required change
1. Add a short, explicit **"Out of scope: backlink graph analysis"** note to
   serp-discover `methodology.md` (extend the existing "What the tool does NOT do"
   section), serp-compete `README.md`, and TalkingToad `docs/overview.md`, stating:
   the suite uses DA as the sole authority proxy; full backlink/toxic-link/disavow
   analysis requires a paid link-graph provider and is judged low-ROI for a single
   nonprofit; revisit only if scale or budget changes.

### Acceptance criteria
- X-4.1 The note exists in all three named docs with consistent wording.
- X-4.2 No code change; no test change.

---

# Phase 2 — free integration

## X-2 — Close the AI-citation loop (TalkingToad ↔ serp-discover)  *(Adjacent)*

### Problem
TalkingToad observes which **client** pages AI engines actually cited
(`AI_CITED_PAGE`, `AI_HIGH_VALUE_UNCITED`); serp-discover probes AI engines about
the **market** and captures AIO citations. Each tool's blind spot is the other's
data, and they never meet.

### Required change
1. **Resolve G-F first:** confirm `AI_CITED_PAGE`'s data source and add/verify a
   stable **export** of TalkingToad's observed client-citation list (URL, engine
   if known, last-cited date) — e.g. a JSON sidecar written next to the crawl
   report, following TalkingToad's gitignored-output conventions.
2. serp-discover **ingests** that export (optional input path in `config.yml`,
   `data_available` when absent) and uses it in the citation-surface / GEO
   analysis: real observed client citations replace inferred ones, and the
   "ranks-but-not-cited" alert (review T.4) can target the exact URLs TalkingToad
   marks high-value-but-uncited.
3. HARD rule (principle 1): serp-discover treats the ingested list as **evidence
   data**, not as something the LLM may contradict — add a validator/canary entry
   if it becomes a `keyword_profiles.<field>`, per the existing convention.

### Acceptance criteria
- X-2.1 TalkingToad writes a schema-stable client-citation export; a fixture crawl
  asserts its shape.
- X-2.2 serp-discover ingests the export when present and sets `data_available`
  false (no crash, no fabricated citations) when absent — both paths tested.
- X-2.3 A "ranks-but-not-cited" alert is emitted for a URL that ranks in the
  analysis JSON and appears in TalkingToad's high-value-uncited list (integration
  fixture).
- X-2.4 Canary/validator convention satisfied if a new keyword-profile field is
  added.

## X-1 — One orchestrated audit + shared client profile  *(Adjacent; the blog's whole premise)*

### Problem
An audit is one process; the suite is three programs with a JSON handoff between
two of them and no link to the third. Running "the full audit" is manual glue.

### Required change
1. **Shared client profile (G-E):** make `shared_config.json` the single client
   profile all three tools read — name/domain/DA/location/known-brands. serp-compete
   already reads it; serp-discover's `shared_config.py` (C.9) formalises reading
   it; add TalkingToad as a reader for the client identity fields it needs. Do not
   duplicate these values into per-tool configs; per-tool configs keep only
   operational settings.
2. **Runner (G-D):** a standalone `run_suite_audit.py` that, given a topic/keyword
   set, sequences: serp-discover pipeline → `competitor_handoff` → serp-compete
   audit → TalkingToad crawl of the client domain, then stitches a single dated
   **combined executive report** (`suite_audit_<topic>_<ts>.md`) linking each
   tool's own outputs and surfacing the top findings from each. It orchestrates
   existing entry points; it does **not** re-implement any tool's logic.
3. Honest partial-failure behaviour: if one tool fails or is unconfigured
   (e.g. no GSC, no SerpAPI budget), the runner completes the others and the
   combined report states which stage was skipped and why — never a silent gap.

### Acceptance criteria
- X-1.1 All three tools read client identity from `shared_config.json`; a test
  changes one value there and observes it reflected in each tool's run context.
- X-1.2 `run_suite_audit.py` sequences the three stages against mocked tool entry
  points and writes one combined report referencing each stage's outputs.
- X-1.3 A mid-sequence stage failure is caught; the combined report is still
  written and names the skipped stage and reason (test with one stage forced to
  fail).
- X-1.4 No tool's own tests regress; the runner has its own test module.

## X-3 — Scheduled audit cadence  *(Blog: audit frequency)*

### Problem
The blog prescribes annual full audits, quarterly for fast-moving sites, and
mini-audits after changes. Nothing encodes this; runs are manual.

### Required change
1. Provide ready-to-use schedule definitions (documented in the suite
   `user-guide` / README) for: a **quarterly** full `run_suite_audit.py` and a
   **monthly** light run (TalkingToad re-crawl + serp-discover AI-visibility
   probe), all framed as change-over-time.
2. Do not hardcode a scheduler; document the cron/agent invocation and keep the
   cadence values in config so they are editable.

### Acceptance criteria
- X-3.1 The suite docs contain copy-pasteable quarterly-full and monthly-light
  schedule commands referencing the X-1 runner and the existing probe entry point.
- X-3.2 Cadence/label values are config-driven, not literals in source.

---

# Phase 3 — external dependency (deliberate)

## TT-1 — Core Web Vitals & measured performance  *(Blog steps 7, 8)*

### Problem
No performance category exists in TalkingToad's 152 codes. The blog's steps 7–8
(page speed, LCP/INP/CLS) are the clearest capability gap in the suite. Closing
them means adding an external measurement dependency — a deliberate architectural
step, gated per principle 4.

### Required change
1. **New PERFORMANCE category** in the catalogue, with codes
   `CWV_LCP_SLOW`, `CWV_CLS_HIGH`, `CWV_INP_SLOW` (INP proxied by TBT when only
   lab data is available), plus `PERF_TTFB_SLOW` if not already covered by TT-3.
2. **Data source (G-A):** PageSpeed Insights API. Config block
   `performance: {enabled: false, page_budget: 10, psi_api_key_env: PSI_API_KEY,
   thresholds: {...}}`. Off by default; capped at `page_budget` PSI calls per run;
   the run log prints "Performance: N PSI calls (cap M)".
3. **Page selection (G-B):** home + top service pages + top-GSC-traffic pages, up
   to `page_budget`. Selection logic in code, budget in config.
4. **Thresholds** per the blog and Google guidance, in config/`thresholds.md`:
   LCP good < 2.5 s / poor > 4 s; CLS good < 0.1 / poor > 0.25; INP good < 200 ms /
   poor > 500 ms. Confidence tier: **Established** (vendor-defined metrics) for the
   raw values; the *page-selection* and lab-vs-field caveat is the "how it can
   mislead" content.
5. **Trend (principle 5):** store CWV per URL per run in `talkingtoad.db`; report
   change since last run; label single-run values as snapshots.
6. Full V4 explainers for every new code, incl. `good_vs_bad` and
   `how_it_can_mislead` (lab data ≠ real-user field data; a single PSI sample is
   noisy; only measured pages are covered — state the sampled set, never imply
   full-site coverage, per principle 3).
7. Missing/invalid `PSI_API_KEY` → feature skipped with a logged warning, never an
   abort (mirror the Gemini-key pattern in serp-discover G.1).

### Acceptance criteria
- TT-1.1 With `performance.enabled: false` (default), **zero** PSI calls occur
  (mock-based call-count test).
- TT-1.2 With a mocked PSI client, LCP/CLS/INP parse into the code fields; each
  code fires above / not below its configured threshold at boundary values.
- TT-1.3 Page selection respects `page_budget` (test: 30 candidate pages, budget
  10 → exactly 10 PSI calls) and the run log states the call count and cap.
- TT-1.4 CWV history persists and a second run reports change vs the first
  (two-run fixture).
- TT-1.5 Missing `PSI_API_KEY` skips the feature with a warning and does not abort
  the crawl.
- TT-1.6 Old crawls without CWV data render with `data_available: false`; every
  new code has a full V4 explainer; catalogue↔help parity green; docs regenerated.

---

# Optional stretch

## TT-4 — Rendered mobile-usability signal  *(Blog step 9)*

### Problem
Mobile coverage stops at the static `MISSING_VIEWPORT_META` + `IMG_NO_SRCSET`.
TalkingToad already runs a render pass (`JS_RENDERED_CONTENT_DIFFERS`,
`RAW_HTML_JS_DEPENDENT`) that a usability check can piggyback on.

### Required change
1. On the existing render, at a mobile viewport width, detect horizontal overflow
   (content wider than viewport) and, optionally, tap-target proximity. New code
   `MOBILE_CONTENT_OVERFLOW`, confidence tier **Heuristic**, full V4 explainer.
2. Reuse the existing render; do **not** add a second headless-browser pass.

### Acceptance criteria
- TT-4.1 A fixture page with a fixed-width element wider than the mobile viewport
  fires the code; a responsive fixture does not.
- TT-4.2 No new render pass is introduced (reuses the existing one); parity/doc
  criteria as for all new codes.

---

## Out of scope (re-affirmed from the review)

- **TT-5** cross-web plagiarism (Copyscape-style) — declined: paid dependency,
  low value for one nonprofit; on-site duplication already covered.
- **SC-2** competitor Core Web Vitals — declined: PSI cost scales with
  competitor×page, poor ROI, rarely explanatory in this niche. Revisit only if
  TT-1 ships with spare quota.
- **Backlink graph analysis** — see **X-4**: documented as a deliberate exclusion,
  not built.
