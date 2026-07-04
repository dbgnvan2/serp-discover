# Closing status report — `seo_geo_deferred_spec_v1.md` (2026-07-04)

Definition-of-done item 5: every acceptance criterion of the whole spec
mapped to its implementing commit and its test(s). All work is on branch
`claude/repo-seo-geo-review-sas8m6`.

**Verification basis (not taken on faith):** the full suite was re-run at
close of Phase C — `python3 -m pytest test_*.py tests/ -q` →
**729 passed, 28 skipped** (skips are the pre-existing tkinter GUI tests),
and every test file named below was confirmed to exist and to reference
its criterion IDs. Decision gates D-1…D-5 were implemented as resolved in
the spec; no silent deviations.

| Phase | Item | Commit |
|-------|------|--------|
| A | C.9 shared_config contract | `650d8a7bf43786ed2dacd9d9c2c15e5eb472c307` |
| A | G.6 content freshness | `9e087cc17b22f2d102b7b9fa34a4acbb6d912ecf` |
| A | G.3 E-E-A-T author signals | `5415cb32512589ec0c937309ec484830cd194bf5` |
| B | T.5 situational probes | `020715995e819bde6807cea8ce980fd3126416a2` |
| B | G.5 Bing check | `e3e7bbba8fd66d8ba4f143c2622879d6a1a514fe` |
| C | G.1 AI-engine probing | `9c76bf46a6b70e601f5a4bf71b6a6c3c6265e3e7` |
| C | G.4 GSC integration | `105027c13ff7a2d0654ee494e38476b5d5ea0fd5` |

---

## C.9 — shared_config.json contract (commit `650d8a7`)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| C.9.1 path constructed in exactly one module | **Done** | `shared_config.py`; `tests/test_shared_config.py::TestSinglePathOwner::test_literal_appears_in_exactly_one_module` |
| C.9.2 `SERP_SHARED_CONFIG` redirects loading; overridden threshold changes `_gap_to_status` | **Done** | `tests/test_shared_config.py::TestEnvOverride` (incl. `test_overridden_threshold_changes_gap_to_status`) |
| C.9.3 malformed file → one warning naming the file, defaults | **Done** | `tests/test_shared_config.py::TestMalformedConfig` (asserts the log record) |
| C.9.4 no file present → identical behavior, existing tests green | **Done** | `tests/test_shared_config.py::TestAbsentAndPresentFile`; full suite green at the C.9 commit and since |
| C.9.5 schema + precedence documented | **Done** | `docs/config_reference.md` § "Shared config (`shared_config.json`, out-of-repo)" — key table + explicit precedence statement (shared_config > config.yml > serp_vocab.yml / code defaults); gate D-5 authority preserved |

## G.6 — Content freshness / decay tracking (commit `9e087cc`)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| G.6.1 enricher extracts dates from meta / JSON-LD / `<time>` / no-date pages | **Done** | `tests/test_freshness.py::TestEnricherDateExtraction` |
| G.6.2 `age_days` anchored to run `Created_At` (exact integers, independent of today) | **Done** | `tests/test_freshness.py::TestBuildFreshness` (fixed fixture dates) |
| G.6.3 old JSONs → `data_available == false`, no crash | **Done** | `tests/test_freshness.py::TestOldJsonCompatibility` |
| G.6.4 payload passthrough (`keyword_profiles.freshness` reaches the payload) | **Done** | `tests/test_freshness.py::TestPayloadPassthrough` |
| G.6.5 canary green (allowlist entry) | **Done** | `freshness` in `KNOWN_UNVALIDATED` (`test_validation_consistency.py`) with reason; canary suite green |

## G.3 — E-E-A-T author-signal detection (commit `5415cb3`)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| G.3.1 `serp_vocab.yml eeat_signals` loader-required (missing key → ValueError) | **Done** | `tests/test_eeat_signals.py::TestVocabSection`; `pattern_matching.load_serp_vocab` required-keys set |
| G.3.2 word-boundary matching ("Jane Doe, RCC" fires; "harp" does not fire "RP"; phrases fire as substrings) | **Done** | `tests/test_eeat_signals.py::TestCredentialMatching` |
| G.3.3 enricher tests: JSON-LD-author, byline-only, no-author pages | **Done** | `tests/test_eeat_signals.py::TestEnricherAuthorSignals` |
| G.3.4 old JSONs → `data_available == false`; payload passthrough; canary green | **Done** | `tests/test_eeat_signals.py::TestOldJsonAndPayload`; `eeat_signals` in `KNOWN_UNVALIDATED` |
| G.3.5 config_reference serp_vocab description mentions the new section | **Done** | `docs/config_reference.md` serp_vocab bullet names `eeat_signals` (credential_tokens + review_markers); no new CLAUDE.md entry needed (serp_vocab.yml already listed) |

## T.5 — Situational query probes (commit `0207159`, gate D-1)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| T.5.1 `enabled: false` default → zero extra SerpAPI calls | **Done** | `tests/test_situational_probes.py::TestDisabledByDefault` (mocked fetch, call count unchanged; Low API mode never runs probes) |
| T.5.2 PAA-sourced probes verbatim (6+ words, External Locus first); template placeholders; both caps respected | **Done** | `tests/test_situational_probes.py::TestProbeGeneration` |
| T.5.3 probe rows carry `Query_Label == "S"` and are absent from handoff, `serp_intent` inputs, and volatility | **Done** | `tests/test_situational_probes.py::TestSurfaceExclusion` (per-surface tests) + `TestProbeRun` |
| T.5.4 `aio_trigger_analysis` bucket rates correct on a fixture | **Done** | `tests/test_situational_probes.py::TestAioTriggerAnalysis` |
| T.5.5 `situational_templates` loader-required + USER_MANUAL WHY (23% vs 77%, tested on the client's own market) | **Done** | `tests/test_situational_probes.py::TestVocabSection`; `docs/USER_MANUAL.md` § "The situational query probes and AI-answer trigger rate" |

## G.5 — Bing secondary-index check (commit `e3e7bbb`, gate D-4)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| G.5.1 disabled by default: zero Bing calls | **Done** | `tests/test_bing_check.py::TestDisabledByDefault` (config default + mock-based zero-call test) |
| G.5.2 parser vs committed fixture: client rank found; absent → `client_rank None` with `checked true` | **Done** | `tests/test_bing_check.py::TestParser` against `tests/fixtures/bing_serp_sample.json` |
| G.5.3 one call per root keyword when enabled, standard retry path | **Done** | `tests/test_bing_check.py::TestRunChecks` (call-count + `_fetch_serp_api` routing) |
| G.5.4 prompt references the block descriptively; canary green | **Done** | `tests/test_bing_check.py::TestExtraction`; `keyword_profiles.client_rank` allowlisted in `KNOWN_UNVALIDATED` with reason; canary suite green |

## G.1 — AI-engine mention probing (commit `9c76bf4`, gate D-2)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| G.1.1 all API calls mocked; detection for mentioned-only / cited / neither / competitor-cited | **Done** | `tests/test_ai_visibility.py::TestDetection` + `TestProbeParsing` (mocked Anthropic client and Gemini REST) |
| G.1.2 idempotent table; UTC `run_ts` + `engine` rows; ordered per-engine trend across two synthetic runs on both engines | **Done** | `tests/test_ai_visibility.py::TestPersistence` |
| G.1.3 no calls without confirmation; exit message states questions × engines | **Done** | `tests/test_ai_visibility.py::TestCostGuard` ("2 questions x 2 engines = 4 paid API calls") |
| G.1.4 `--engines claude` runs only ClaudeProbe; missing `GEMINI_API_KEY` skips Gemini with a warning while Claude completes; unknown engine errors listing valid options | **Done** | `tests/test_ai_visibility.py::TestEngineSelection` |
| G.1.5 report renders with zero history and with history; per-engine rates; caveat always present | **Done** | `tests/test_ai_visibility.py::TestReport` (incl. `test_caveat_paragraph_always_present`); output name matches the gitignored `ai_visibility_*` glob |
| G.1.6 USER_MANUAL WHAT + WHY (growing referral surface; model-version volatility is why the trend view exists; how to choose engines) | **Done** | `docs/USER_MANUAL.md` § "The AI-engine visibility probe" |

## G.4 — Google Search Console integration (commit `105027c`, gate D-3)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| G.4.1 all HTTP mocked: bearer-auth header construction, request batching (pagination), cache hit/miss, bound-variable batching on cache lookups | **Done** | `tests/test_gsc.py::TestGscClientAuthAndBatching` + `TestGscClientCache` (incl. `test_cache_lookup_batches_bound_variables`, 1200 queries through 500-var IN(...) chunks — test_dataforseo_client patterns) |
| G.4.2 sponge computation on synthetic data (known medians, both buckets; <3-queries insufficient-data path) | **Done** | `tests/test_gsc.py::TestSpongeComputation` |
| G.4.3 `reformat_candidates` intersects with `strategic_flags.geo_alerts` on a fixture where one keyword satisfies both | **Done** | `tests/test_gsc.py::TestReformatCandidates::test_intersection_with_geo_alerts` |
| G.4.4 disabled / no credentials → clear message, zero API calls; pipeline unaffected (no gsc_client import at pipeline import time) | **Done** | `tests/test_gsc.py::TestDisabledAndIsolation` (message + zero-call tests, sys.modules import-isolation test, source-level import scan) |
| G.4.5 outputs follow gitignored globs; USER_MANUAL documents the service-account grant and how to read the sponge table | **Done** | `tests/test_gsc.py::TestEndToEndRun::test_output_base_matches_gitignored_glob` (`gsc_analysis_*` in `.gitignore`); `docs/USER_MANUAL.md` § "The Search Console sponge analysis" (setup steps 1–3 + sponge-table reading guide) |

---

## Whole-spec definition of done

1. **Suite fully green** — 729 passed, 28 skipped (GUI/tkinter only, pre-existing), no newly skipped business-logic tests.
2. **Docs per item, same commit** — each of the seven item commits updates `docs/methodology.md`, `docs/USER_MANUAL.md`, and `docs/config_reference.md` in the same commit as the code.
3. **Editorial surfaces listed in CLAUDE.md** — the spec's phases added editorial content only to `serp_vocab.yml` (`eeat_signals`, `situational_templates`), which was already on CLAUDE.md's editorial list; no new editorial file was created. G.1/G.4 knobs are operational and live in `config.yml` (documented in `docs/config_reference.md`).
4. **Spec traceability** — every item commit ends with `Spec: seo_geo_deferred_spec_v1.md#<item>`.
5. **This report** — every acceptance criterion above maps to a commit hash and test; **nothing is unmet** (no "not done" entries).

## Out of scope (re-affirmed, unchanged)

llms.txt generation, per-model citation chasing beyond the G.1 trend view,
and automated outreach/posting remain out of scope per the spec.
