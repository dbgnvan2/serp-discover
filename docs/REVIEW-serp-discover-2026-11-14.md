# Review: serp-discover — 2026-11-14

**Scope.** The areas the 2026-11-04 review (`docs/review_2026-11-04/`) excluded: GUI, test quality,
architecture, security, external-call hardening, multi-client readiness, docs drift, repo hygiene,
and missing features. Data-path correctness and SEO methodology were not re-reviewed; a sample of
the old findings was re-checked. Report only — no code was changed.

**Method.** Nine read-only reviewers over explicit file slices, two web-research agents, and one
challenge pass that tried to refute the 18 highest-severity findings (11 confirmed, 7 narrowed,
0 refuted). Items marked **[run]** I verified myself by running a command. Everything else is
static reading; no GUI was launched and no paid API was called.

## Verdict

The analysis code is careful and the editorial-config discipline is real. The weak points are at
the edges: the Configuration Manager can lose or blank config files on "Save All"; the pipeline
reports success when it failed; and paid runs have no timeout, no checkpoint and no resume. The
tool is single-client in code — the multi-client docs describe a mechanism that was never built,
and the shared database has no client or topic key. The Nov 4 findings are all still open (10 of 10
sampled), and the test suite is not green today. Fix the config-save and exit-code problems first;
they cost little and remove the ways the tool can damage its own inputs.

## Coverage

| Area | Correctness | Security / ext. calls | Structure | Tests |
|---|---|---|---|---|
| GUI (`serp-me.py`, `config_manager.py`, validators, `yaml_io`) | covered | partial | partial (config_manager grep only) | covered |
| API clients (Moz, DataForSEO, GSC, Bing, enricher, storage, feasibility) | prior review only | covered | partial | sampled |
| SERP audit, AI probes, brief/LLM | prior review only | covered | partial | partial |
| Report generation (`generate_insight_report`, `brief_data_extraction`, scoring modules) | prior review only | not reviewed | partial | sampled |
| Multi-client (configs, prompts, DB keys) | covered (one question) | — | covered | — |
| Docs | — | — | covered (USER_MANUAL ~40% read) | — |

Not reviewed: `keyword_enrich.py` (untracked), `scripts/`, `x-archive/`, `clinical_dictionary.json`,
live API behaviour, CVE status of dependencies, sibling repo serp-compete. Tests: 8 of 81 files read
fully, 12 in part, 61 by grep.

## Findings

No finding kept "blocker" after the challenge pass. Majors are ordered by what I would fix first.

### Major — the tool can damage its own configuration

**M1. Configuration Manager "Save All" is lossy.** (verified) One root cause: every tab rebuilds its
file from widgets and Save All writes all nine files whether or not they changed.
- `config_manager.py:1683-1691, 1794-1822` — a top-level list in `config.yml` is saved as `{}`.
  `known_brands: []` is harmless today; a populated list would be erased.
- `config_manager.py:1193-1196, 1440-1443` — the pattern Edit dialogs keep only name and count.
  Edits to triggers, reframes and keywords in `strategic_patterns.yml` and
  `brief_pattern_routing.yml` are discarded while the row shows "✓ Complete".
- `config_manager.py:1005-1013` — all 17 `rationale:` entries in `intent_mapping.yml` are dropped.
  No code reads them, so the loss is documentation, not behaviour.
- `config_manager.py:239-241`, `yaml_io.py:87-102` — a file that fails to parse loads as `{}` (error
  goes to `print`, invisible in the GUI); Save All then overwrites it. Applies to `config.yml`,
  `domain_overrides.yml`, `brief_pattern_routing.yml`, `client_profiles.yml`.
- `config_manager.py:2517-2561` — Save All ignores the validation result, writes files one at a
  time (partial save on failure), and Close destroys the window even when the save failed.
- `config_manager.py:2410-2424` — non-modal, no mtime check: an open manager window reverts
  overrides approved or paths written by the launcher in the meantime.

Fix: keep the loaded dict as the model, overwrite only keys that have a widget, save only dirty
tabs, refuse to save a tab that failed to load, validate before any write.

**M2. Run button can start a second concurrent pipeline.** (verified) `serp-me.py:495, 943-946` —
`on_select` re-enables Run on any list click during a run; no running flag or process guard. This
is the house rule on background-process buttons. Related: no Stop button, no timeout, closing the
window orphans the child which keeps spending credits (`serp-me.py:948-965`).

**M3. Keyword files and `config.yml` are written before the run is validated.**
`serp-me.py:728-776, 741-745` — a cancelled or failed run leaves `files.output_*` pointing at files
that do not exist, and typing new keywords can silently overwrite an existing `keywords_<slug>.csv`.

### Major — failures reported as success

**M4. `serp_audit.py` exits 0 on every failure path.** (verified; found by two reviewers)
`serp_audit.py:1362-1377, 1456, 1975, 2115`, `run_pipeline.py:46-50, 77` — missing key or CSV is a
bare `return`; a keyword whose fetch failed is skipped with no count; output write errors are only
logged. `run_pipeline` then validates the *previous* run's files and prints "Finished Successfully".
Fix: non-zero exit on fatal paths and write errors; print "N of M keywords fetched".

**M5. LLM output is never checked for truncation.** (verified) `brief_llm.py:51-68` — no
`stop_reason` check, so a report cut at `max_tokens` or an empty response is validated and written.
`probe_ai_visibility.py:237-495` has the same gap for all four engines: an empty or safety-blocked
answer is stored as "client not mentioned", and there is no "answered N of M" total.
`answer_sentiment.py:81-106` stores a failed call as "neutral".

**M6. Per-keyword HARD validation fails open.** (verified, narrowed) `brief_validation.py:175-262` —
checks `continue` when the keyword heading regex does not match and nothing counts sections found.
The prompt prescribes the matching format, so this bites only when the model deviates.

**M7. GSC transient failure cached as "no data" for the TTL.** (verified; same as D-C-02)
`gsc_client.py:175-178, 209-223`. GSC is off by default.

### Major — paid runs are fragile

**M8. No working timeout on any SerpAPI call.** (verified) `serp_audit.py:354` — the legacy
`google-search-results` client defaults to `timeout=60000` seconds. One stalled connection hangs the
run for hours and the retry loop never fires. One-line fix.

**M9. No checkpoint or resume; raw responses overwrite each other.** **[run]**
`serp_audit.py:494-500, 1442-1711` — results live in memory until the final write, the keyword loop
has no per-keyword `try`, and `raw/<run_id>/google_response.json` has no keyword in its name, so
only the last keyword's raw data survives. A crash on keyword N loses everything already paid for.
`probe_ai_visibility.py:1478-1488` likewise saves only after every engine finishes.

**M10. SerpAPI key can be written to the log on a connection error.** (verified for connection-class
errors) `serp_audit.py:376-382` logs `{e}` unscrubbed; the key travels as a GET parameter.
`run_feasibility.py:135` already scrubs — share that function. `raw/` is gitignored, so exposure is
local.

**M11. `market_analysis_*.json` has no schema or version, and one consumer contract is broken.**
**[run]** Three readers (`serp_audit.py:1179`, `serp-me.py:563`, `query_variants.py:296`) read
`strategic_flags.content_priorities`; the writer never emits it (0 of 8 output files contain the
key). The "AI query alternatives" option and situational-probe priority mode therefore never do
anything. Three writers rewrite the file in place non-atomically.

**M12. GUI item 2 (Review Domain Overrides) acts on the last-run topic, not the selected one.**
`serp-me.py:1022, 1066, 1545` use `load_config_paths()`; items 3 and 4 use the selected keyword
file. With two topics on disk, the review can rewrite the other topic's JSON and XLSX.

**M13. Retired model ID is still a default.** `brief_llm.py:22`, `config.yml:197, 203` use
`claude-sonnet-4-20250514`, which `report_models.py:9` records as returning 404. A CLI
`--advisory-briefing` run fails after the main report is paid for. `SUPPORTED_REPORT_MODELS` is a
second, unused static list. No entry point pre-checks its model before paid calls start.

### Major — multi-client (you said: a few clients, run by you)

**M14. Multi-client support is documented but not implemented.** Seven documents
(`docs/CONFIG_MANAGER_MULTI_CLIENT.md`, `docs/MULTI_CLIENT_ARCHITECTURE.md`,
`docs/CONFIG_GENERALIZED_FOR_ANY_BUSINESS.md`, `CLIENTS_SETUP.md`, `IMPLEMENTATION_SUMMARY.md`,
`DELIVERY_SUMMARY.md`, `TECHNICAL_CHANGES.md`) describe a client picker, a `clients/` directory, a
`--client` flag and `SERP_CLIENT`. None exists in code. `MULTI_CLIENT_ARCHITECTURE.md` includes an
`rm -f *.yml *.json` recipe that would delete live config if run in the repo root. The only real
piece is `client_profiles.yml`, which affects AI-probe questions only.

**M15. The database has no client or topic key.** (verified) `ai_visibility_probes`,
`ai_visibility_index`, `brand_mentions`, `ai_aio_exposure` trend queries filter by engine or nothing
(`probe_ai_visibility.py:796-799`, `aio_exposure.py:319-326`). A second client's runs would appear
in the first client's trend tables. This already affects one client: runs on different keyword sets
share the same trend. `runs` (`storage.py:36-40`) stores no topic either; the effect there is
narrower — an interleaved other-topic run hides same-topic history (`metrics.py:43-48`).

**M16. A missing config key falls back to Living Systems.** `brief_data_extraction.py:75-97` —
absent `analysis_report.client_domain` gives the brief "livingsystems.ca", the Bowen framework text
and Bowen `framework_terms`, with no error. `ai_visibility.geo_context` is the literal "I'm in North
Vancouver, BC." and overrides the client location. `handoff_writer.py:63, 126` treats an empty
client domain as matching every URL, producing a handoff with zero targets.

**M17. Counselling/Bowen logic cannot be turned off.** An empty `strategic_patterns.yml` raises;
with zero matches a hardcoded "General Differentiation" Bowen record is emitted
(`pattern_matching.py:80, 436-443`). The LLM system prompts name the client's sector, BC therapy
directories and "the Bowen reframe" as literals (`prompts/main_report/system.md`,
`prompts/advisory/system.md`). Entity classification knows only counselling and legal providers
(`classifiers.py:151-202`), and `serp_vocab.yml` sends therapy-specific situational templates as
paid queries for any keyword.

### Major — tests

**T1. The suite fails today.** **[run]** `1 failed, 1399 passed, 66 skipped`.
`test_moz_competitor.py::TestCollectionFreshness::test_cached_block_reports_when_it_was_collected_not_now`
hardcodes a cache timestamp of 2026-08-01 and expects a cache hit; it began failing when that date
passed the cache TTL. CI last ran 2026-08-29 (green then).

**T2. All 66 skips are missing-fixture skips, not tkinter skips.** **[run]** They depend on two
gitignored files in `output/` that exist on no checkout, so the M1/RC report-clarity tests, the
brief-baseline regressions and the only "e2e" test run nowhere. `CLAUDE.md` says the 66 are GUI
tests; that is wrong. Fix: commit trimmed fixtures and fail instead of skip.

**T3. Highest-risk paths have no behavioural test.** `serp_audit.main()` (~840 lines) is never
called by a test; the HARD/SOFT retry policy in `list_recommendations` is checked only by `hasattr`;
SerpAPI retry/fail-fast logic is always patched out; `SerpStorage` and `UrlEnricher.fetch_url` have
no tests; the cross-tool handoff-schema test reads an absolute `/Users/davemini2/...` path and skips
in CI.

### Minor

- **Tests assert live `config.yml` values** (`test_moz_competitor.py:333`, `test_ai_visibility.py:61-75`
  and others) — changing a setting in the GUI breaks the suite. About 25 "Tab" tests in
  `tests/test_config_manager.py` never touch `config_manager` and three are vacuous (`assert True`).
  CI has no skip-count check, coverage or lint.
- **Retry helper** (`http_retry.py:14-17, 61-66`) — one retry after 1s, constants not in config, a
  negative `Retry-After` raises. Four GET call sites bypass it (`run_feasibility.py:178, 212`,
  `url_enricher.py:81, 99`).
- **`url_enricher.py:81-106`** — no size cap, no content-type check on GET, no host validation.
  Bounded by the top-5 limit and per-socket timeout.
- **Moz site-metrics cache key omits `scope`** (`moz_client.py:135-144`).
- **`probe_ai_visibility.py:143-151`** has its own `.env` parser that does not strip quotes; a quoted
  key works for the audit and 401s for the probe.
- **Sentiment budget is zero under shipped defaults** (60 − 20×3), so enabling it classifies nothing
  and the report gives the wrong reason (`answer_sentiment.py:141-145`).
- **Three seed questions in `client_profiles.yml:81-86` contain a literal `{city}`** and are sent
  verbatim as paid probes.
- **Third-party text in prompts** is labelled "pre-verified" with no untrusted-data rule
  (`prompts/main_report/user_template.md:43-50`).
- **Dependencies** — ranges with no lock file; `pytest` in runtime requirements; legacy SerpAPI client.
- **Full SerpAPI responses are pretty-printed at INFO** into the log and an unbounded Tk text widget
  (`serp_audit.py:349, 356`).
- **Duplicated helpers** — eight domain-extraction implementations with three behaviours; two
  `load_brief_pattern_routing` copies, and the tests cover the one production does not call.
- **Editorial content still in Python** — `brief_rendering.py:96-108`, `classifiers.py:92, 153-159`
  (`ubc.ca`, `sfu.ca`), `serp-me.py:564`, sentiment/brand system prompts, `brief_validation.py`
  phrase lists and rules hardcoded to "toxic" and "estrangement".
- **`enrichment.enable_domain_age`** (`config.yml:29`) is read by no code. `clinical_dictionary.json`
  is referenced by no Python file though `CLAUDE.md` lists it as live config.

### Docs drift (all confirmed against code)

- GUI step tables in `docs/gui_steps.md`, `README.md:66-72` and `USER_MANUAL.md` describe a 7-step
  list that no longer matches `serp-me.py:152-275`; every "run Step N" instruction is wrong.
- `USER_MANUAL.md:1644-1665` names tables that do not exist, the wrong entry-point filename, the
  wrong export path, and config keys `client.da` / `serpapi.language` (real: `feasibility.client_da`,
  `serpapi.hl`).
- `docs/database.md` lists 8 of ~22 tables; `docs/architecture.md` lists ~27 of ~62 modules;
  `docs/config_reference.md` omits six config blocks that code reads.
- `README.md` setup omits tkinter and five env vars; test counts disagree (README 518, CLAUDE.md
  1308, CI comment 1394, actual 1400).
- `docs/COMPETITIVE_POSITIONING.md` says there is no AI-visibility tracking or backlink data.
- `moz_api_upgrade_spec_v1.md` is untracked but cited as the governing spec.
- No documentation index exists. About 20 dated status/plan snapshots in `docs/` and the root are
  superseded and could move to `x-archive/`.

### Repo hygiene **[run]**

- **The GitHub repo is public.** History contains raw SerpAPI logs, six versions of `serp_data.db`,
  and client reports in `x-archive/`. I found no credentials (logged keys are `REDACTED`).
- **`.git` is 1.8 GB; packed content is ~450 KB.** 1.48 GiB of loose objects and 338 MB of temp
  garbage. `git gc --prune=now` should reclaim it.
- **The Nov 4 review is untracked** and the branch is 32 commits ahead of `main`.

## Systemic patterns

1. **Failure recorded as a measured negative.** M5, M7, zero-answer engines scored AIVI 0, sentiment
   "neutral", DataForSEO null→DA 0 (D-C-04). Each needs a "not measured" state and an N-of-M count.
2. **State passed between steps through `config.yml` and "newest file" globs.** M3, M4, M12, the GSC
   sidecar lookup. Pass explicit paths; stop writing last-run paths into shared config.
3. **Rebuild-from-widgets saving.** All of M1.
4. **Tests that skip instead of fail.** T2, the handoff-schema test, the section-5 class skip.
5. **Client 1 as the default.** M16, M17 and the literals behind them.

## Prior review status

Sampled: every S1 in `discover_correctness.md` and five WRONG findings in
`discover_methodology.md`. **10 of 10 still open, 0 false positives**; cited line numbers still
match within a few lines. The 10 rows are 7 distinct defects. The largest: page-2 results keep
page-relative `Rank`, so consumers that take "top 10" get a mix of pages (D-C-01).

## Missing features worth considering

From web research (sources in the research notes; vendor statistics are indicative only). Ordered
by value against effort. You asked not to add for the sake of adding — the last list is what I
would leave out.

| # | What | Why | Effort |
|---|---|---|---|
| 1 | robots.txt check for AI search crawlers (OAI-SearchBot, PerplexityBot, Claude-SearchBot), reported separately from training crawlers | OpenAI documents that sites blocking OAI-SearchBot are not shown in ChatGPT search. The "accessibility" sub-score never checks this. One fetch per client. | S |
| 2 | "Changed since last run" section: position, local pack, AI Overview citation | Data is already in SQLite. Needs M15's topic key first. | S |
| 3 | GSC striking-distance queries (positions 8–20) and declining pages | GSC is already connected; this is the most actionable GSC output for a small site. | S |
| 4 | Repeat each AI probe N times and report appearance rate with n; drop the AIVI "ranking" axis | A 2026 SparkToro/Gumshoe study found single runs rarely repeat the same brand list and ordering almost never repeats. The tool uses n=1 per question and gives position 25% weight. Fewer questions × more repeats holds cost. | M |
| 5 | Keyword gap ("competitors rank, you don't") | `moz_competitor.py` already fetches competitor ranking keywords; only the diff is missing. Costs extra Moz rows for the client's own list. | S–M |
| 6 | Google AI Mode in the SERP pass | SerpAPI has a `google_ai_mode` engine; Google says AI Mode and AI Overviews can cite different links. | M |
| 7 | Google Business Profile comparison against local-pack competitors | Categories, review count and rating are levers a local client controls; partly captured already. | M |
| 8 | Lower the default schema weight in the foundational score | Google says no special schema is needed for AI features; an Ahrefs matched study found no citation lift. Schema is one third of the score today. Config change. | S |

Also worth a manual checklist line rather than code: Search Console's Generative AI performance
report and Bing Webmaster Tools' AI Performance report (API access for both unverified).

**Not worth adding:** llms.txt, markdown page variants, more schema types for AI citation, prompt
volume estimates, AI crawler log analytics, citation/NAP monitoring (buy it), a site crawler/audit,
daily AI sampling, draft scoring, a paid AI-visibility SaaS.

**Label fix, not a feature:** the report calls OpenAI API results "ChatGPT". A 2026 preprint found
the API recovered about 23% of the URLs the ChatGPT product cited. Label as "API proxy" and report
at domain level. `config.yml` `openai_model: gpt-4o` should also be checked against the live list.

## Refuted or narrowed in the challenge pass

None fully refuted. Narrowed: pattern-dialog loss (new StrategicPatterns entries fail validation
rather than save empty); empty-file overwrite (4 of 9 files, the rest are blocked by validators);
volatility cross-topic (empty merge and hidden history, not wrong deltas); GSC sidecar mix-up (off by
default); empty-domain match (only `handoff_writer`); unbounded fetch (top 5 per keyword);
`{city}` seeds (code behaves as documented; the data is wrong).

## Questions only you can answer

1. Is the repo meant to be public, given the client data in its history?
2. Multi-client isolation: a directory per client (own config, DB, output), or a client slug column
   in one DB and one config? M14–M16 are fixed differently depending on the answer.
3. Will the next clients be counselling practices or other industries? If counselling only, M17
   drops to minor.
4. Should the Nov 4 work plan be done before any of this? Several findings here (M4, M9, M11) touch
   the same code.
5. What do Moz and DataForSEO return on quota exhaustion? If it is a "not found" shape, it is being
   cached as a real negative for 30 days.
