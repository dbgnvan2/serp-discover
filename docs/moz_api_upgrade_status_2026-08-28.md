# Moz API upgrade — closing status report

Spec: `moz_api_upgrade_spec_v1.md` · Implemented 2026-08-27/28 · Branch `fix/gui-model-robustness`

Every acceptance criterion below is `done`, `partial`, or `not done` with a reason.
Commit hashes are the change that satisfied the criterion.

## T.0 — JSON-RPC client + quota probe (`36902b6`)

| Criterion | Status | Evidence |
|---|---|---|
| `moz_call` round-trips a mocked JSON-RPC response | done | `test_moz_jsonrpc.py::TestMozCall::test_t0_returns_the_result_object` |
| Missing token raises the same `RuntimeError` discipline as `MozClient` | done | `test_t0_missing_token_raises_runtimeerror` |
| `quota_lookup` parsed by a unit test from a mocked response | done | `test_moz_jsonrpc.py::TestQuotaLookup` — fixture is a real captured body |
| No real network call in tests | done | every test mocks `moz_jsonrpc.requests.post` |
| `CLAUDE.md` env-var note corrected | done | `CLAUDE.md`; same stale claim also fixed in `docs/feasibility.md` |

**Live result:** `MOZ_TOKEN` authenticates on `api.moz.com/jsonrpc`. Quota **3,000 rows/month**
(Starter Medium confirmed, not assumed). `quota.lookup` itself bills nothing.

**Spec correction:** `quota.lookup` returns no "remaining" field. It reports `allotted` and `used`;
remaining is derived. A parser written against the assumed `rows_remaining` key was wrong and was
corrected against a captured real response before the commit.

## T.1 — Site metrics: Spam Score + link counts (`485c3c7`, `5b30cf5`)

| Criterion | Status | Evidence |
|---|---|---|
| `get_moz_metrics` returns da/pa/spam_score/link_counts; da/pa callers unaffected | done | `test_moz_client.py::TestSiteMetricsContract` |
| `moz_cache` gains both columns via idempotent `ALTER TABLE` | done | `TestCacheMigration`, incl. legacy-table upgrade preserving rows |
| Moz stays fallback DA; `avg_serp_da` unchanged | done | DA/PA identical across old and new endpoints on the same targets |

**Three pre-existing defects found and fixed** (the contract T.1 had to define was broken):

1. `serp_audit`'s DA writeback was dead — it looked up by input URL while the client keyed by
   scheme-stripped URL, so `Competitor_DA`, `Page_Authority` and `save_url_moz_metrics()` never fired.
2. `run_feasibility` + DataForSEO produced `avg_serp_da: None` on **every** keyword —
   `split('/')[0]` yields `"https:"` for every DataForSEO key. Latent (no DataForSEO credentials
   configured) but live the moment they are added, and D-3 makes DataForSEO primary.
3. `lstrip('www.')` strips characters, not a prefix: `worldbank.org` → `orldbank.org`.

**Also fixed at the user's instruction:** `serp_audit` gated its entire Moz block on `MOZ_ACCESS_ID`
/ `MOZ_SECRET_KEY`, names this project never used, so the enrichment had never run from the audit
path. Now gated on `MOZ_TOKEN`, with rows-billed reporting.

**Folded-in P5 fix:** `_scrub_secrets` redacted only `SERPAPI_KEY` while Moz exceptions were logged
through it; it now scrubs every credential value.

## T.2 — Keyword metrics (`49f96c9`)

| Criterion | Status | Evidence |
|---|---|---|
| `data_available: false` per keyword, never a fabricated zero | done | `test_moz_keywords.py::TestAbsentData` |
| `keyword.moz` block reaches brief prompts via the `keyword_profiles.*` path | done | `TestBriefWiring`; `prompts/main_report/system.md` |
| `keyword_metrics.enabled` default true + per-run cap | done | `config.yml`; `TestSpendControls` |
| Every new prompt field validated or in `KNOWN_UNVALIDATED` with a reason | done | `test_validation_consistency.py` |

**Spec correction — the quota budget is wrong by 4×.** A successful fetch bills **4 rows, not 1**,
and there is **no `.multiple` variant** (`Action not found: DataKeywordMetricsFetchMultiple`). 50
keywords is ~200 rows, not 50.

**Absent data is HTTP 404 / JSON-RPC -32655** — terminal but legitimate, not an outage. Real for this
client: "bowen family systems therapy" has no Moz record at all.

## T.3 — Search-intent cross-check (`c58d154`)

| Criterion | Status | Evidence |
|---|---|---|
| Moz scores stored beside the repo verdict; divergence reported, never auto-overridden | done | `test_moz_intent.py::TestCrosscheck`; `serp_intent` proven byte-identical whether Moz agrees or not |
| No `intent_mapping.yml` rule changed | done | verified `git diff` against the T.2 baseline is empty |
| Absent-data flag per keyword | done | `test_t3_absent_data_flag_per_keyword` |

The vocabularies differ (Moz has four labels; this repo also emits `commercial_investigation`,
`local`, `uncategorised`), so an editorial mapping in `config.yml` translates before comparing.
`agrees` is `null`, never `false`, when comparison is impossible.

## T.4 — Competitor signals in the handoff (`dd59b0d`)

| Criterion | Status | Evidence |
|---|---|---|
| Results flow into `handoff_writer.py` as a `moz` block per competitor, additive and absent-safe | done | `test_moz_competitor.py::TestHandoffContract` |
| `moz.competitor.enabled` + `max_competitors` | done | enabled at the user's instruction; spec default was `false` |
| Reuses existing domain resolution; no new competitor list | done | `competitor_domains()`, `TestDomainResolution` |
| `schema_version` bump + updated `handoff_schema.json`, new optional properties only | done | v1.1; `moz` not in `required` |
| Verify serp-compete tolerates the version bump | **done — and it does not, unaided** | see below |

**The spec's cross-tool assumption does not hold.** It states the new fields must be "optional and
ignored-safe" on Tool 2's side. They cannot be: serp-compete validates against its own schema copy
and calls `sys.exit(1)` on any error (`Serp-compete/src/main.py:132`), with
`additionalProperties: false` at the root and per target. Demonstrated before fixing — a v1.1 handoff
failed Tool 2's real schema with `Additional properties are not allowed ('moz' was unexpected)`.

Resolved by keeping the block top-level, bumping `schema_version` only when it is present (so a
disabled run emits the byte-identical v1.0 document), and syncing `handoff_schema.json` into
serp-compete — the established workflow there. Tool 2's code is untouched and its full suite
(158 tests) passes.

## T.5 — Brand Authority + link momentum (this commit)

| Criterion | Status | Evidence |
|---|---|---|
| Stored as additive, absent-safe fields; capped | done | `test_moz_competitor.py::TestBrandAuthority`, `::TestLinkMomentum` |
| `config.yml` flags | **partial** | `link_momentum.enabled: false` per spec; `brand_authority.enabled: true` at the user's instruction |
| Documented in `docs/USER_MANUAL.md` as optional signals | done | `docs/USER_MANUAL.md` |
| Brand Authority | done | real method is `data.site.metrics.brand.authority.fetch`, 1 row |
| 60-day gained/lost link momentum | **not done — the capability does not exist** | see below |

**Neither method named in the spec exists.** `data.site.metrics.brand_authority.fetch` and
`data.site.linking.domain.filter.recently_gained` / `.recently_lost` all return
`Action not found` — the API CamelCases each dot-segment, so `brand_authority` cannot be one. The
real Brand Authority method was found by probing (invalid names cost no rows).

**There is no recently-gained / recently-lost data on this plan, and no time window at all.**
`data.site.linking.domain.list` accepts only `external, follow, nofollow, deleted, not_deleted` — the
API's own error message enumerates them. The 60-day momentum the spec describes cannot be computed
from this endpoint. What is implemented instead is *lost at some point* vs *currently live*, named
`lost` / `live` with an explicit `window: none` field so it cannot be read as something it is not.
This is off by default. If real momentum is needed, it requires a different data source.

**Defect found in T.4 and fixed here:** `ranking_keyword_limit` and `anchor_text_limit` truncated the
list *after* paying for a full page — a bare `limit` is ignored by the API. They are now sent as the
API's own page controls (`page.limit` and `offset.limit`) and genuinely reduce the bill: a live run
with caps 3+3 plus Brand Authority billed **7 rows**, where anchor text alone previously cost 25.

## Verification

- Suite: **1355 passed, 66 skipped, exit 0** (baseline before this work: 1088 passed, 66 skipped).
- Every test mutation-checked against the verbatim production line it names; ~90 mutations, all red.
- The mutation harness itself had a P16 bug (same-second, same-size writes let Python reuse a stale
  `.pyc`, so two mutations silently never loaded). Fixed with `PYTHONDONTWRITEBYTECODE` plus a
  `__pycache__` purge, and every earlier mutation re-verified under the fixed harness.
- Each task smoke-tested on the **real API** before its commit, not only against mocks.

## Quota

3,000 rows/month. The whole implementation, including all live probing, spent **~350 rows**.

Per-run cost at current settings: site metrics 1/URL · keyword metrics 4/keyword ·
search intent 1/keyword (off) · competitor ranking+anchor ≤ (`ranking_keyword_limit` +
`anchor_text_limit`) per domain · Brand Authority 1/domain · link momentum 2 pages/domain (off).
Every paid signal checks live remaining quota before spending and stops, naming what it skipped.

## Follow-ups (not done, deliberately)

1. **serp-compete's `handoff_schema.json` change is uncommitted.** Made and verified in that repo,
   left uncommitted pending the user's decision, since committing there was not requested.
2. **Nothing in Tool 2 consumes the `moz` block yet.** `convert_handoff_to_targets` drops it, which
   is correct and safe. Using the data in Tool 2's audit is separate work.
3. **Client-domain Brand Authority.** The spec's budget line implies client + competitors; only
   competitor domains are fetched, because adding a `client` key to the handoff `moz` block would
   require a second cross-tool schema sync while decision (1) is open.
4. **`docs/spec_coverage.md`** regenerated separately per `CLAUDE.md`.
