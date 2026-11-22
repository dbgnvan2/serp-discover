# Moz API Upgrade — Implementation Spec v1

## App context (read first)

This repo, **serp-discover**, is **Tool 1** of the SERP Intelligence suite for
Living Systems Counselling (livingsystems.ca). The suite is:

- **serp-discover** (this repo) — Tool 1: SerpAPI SERP audit → market analysis
  + `competitor_handoff_<topic>_<timestamp>.json`.
- **serp-compete** — Tool 2: consumes that handoff and deep-audits the top
  competitor pages.

All Moz code lives in **serp-discover** (`moz_client.py`, `run_feasibility.py`,
`feasibility.py`, `foundational_score.py`, `handoff_writer.py`). **This spec is
scoped to serp-discover only.** Changes to serp-compete are out of scope, but
T.4 adds fields to the handoff, which is a cross-tool contract — see the
"Cross-tool contract" section.

## The one-line change

Replace the DA/PA-only Moz integration (legacy `lsapi.seomoz.com/v2/url_metrics`)
with the full **Moz Data API** (JSON-RPC 2.0 over `https://api.moz.com/jsonrpc`,
`x-moz-token` header). The account is the **"Starter Medium" API plan** — *not*
Moz Pro. Everything in this spec is API-only: **no CSV export, no Moz Pro UI,
no manual steps.**

## Available methods (all programmatic — no CSV)

| Serp-discover needs | Moz Data API method |
|---|---|
| Keyword difficulty + volume + organic CTR + priority | `data.keyword.metrics.fetch` |
| Search-intent scores (informational/navigational/commercial/transactional) | `data.keyword.search.intent.fetch` |
| Related/expanded keywords | `data.keyword.suggestions.list` |
| DA/PA + **Spam Score** + link counts | `data.site.metrics.fetch` / `.fetch.multiple` |
| What a competitor domain ranks for (top 50, with position/difficulty/volume) | `data.site.ranking.keyword.list` |
| Anchor-text distribution | `data.site.anchor.text.list` |
| Brand Authority™ | `data.site.metrics.brand_authority.fetch` |
| Sites linking to 2+ targets (competitor link gap) | `data.site.link.intersect.fetch` |
| Recently gained/lost links (60-day momentum) | `data.site.linking.domain.filter.recently_gained` / `.recently_lost` |
| Remaining quota | `quota.lookup` |

Method names above are transcribed from the public Moz API docs (2026-08-27).
**Confirm each method's exact params against the live docs before hardcoding**
(`https://moz.com/api/docs`, left-nav methods) — the base may have drifted.
Request shape (from the docs, binding):

```json
{"jsonrpc":"2.0","id":"<uuid-v4, ≥24 chars>","method":"<method>","params":{"data":{...}}}
```

## Decision gates — RESOLVED 2026-08-27

These are decided; do **not** re-ask the user. Implement the "decision" as the
default (all reversible via `config.yml` flags).

| Gate | Decision (binding) |
|---|---|
| D-1 — token + quota | `MOZ_TOKEN` is assumed valid on `api.moz.com/jsonrpc`. T.0 runs `quota.lookup` at runtime and records the real `rows_per_month` in `config.yml`. Starter Medium ≈ 3,000 rows/mo (verify; do not hardcode). |
| D-2 — default-on scope | `keyword.metrics` + `search.intent` are **ON** by default. All `site.*`/link methods are **OFF** by default (`config.yml` flags). |
| D-3 — DA source of record | **DataForSEO stays primary**; Moz remains fallback. Moz adds Spam Score + link counts as *additive* fields — no scoring change to `avg_serp_da`. **Partly reversed 2026-11-16 — see below.** |

### D-3, partly reversed by review chunk D2 (2026-11-16)

"No scoring change to `avg_serp_da`" was read as "leave the existing
coercion alone", and the existing coercion was
`int(metrics.get("domain_authority") or 0)`. That turned a domain Moz holds
no authority for into a measured DA of 0. Since
`gap = avg_serp_da - client_da`, those zeros dragged the competitor mean
down, shrank the gap and flipped verdicts toward feasible — the tool
recommended chasing keywords held by DA-90 directories because the domains
nobody scored counted as having no authority.

What changed (`moz_client._parse_site_metrics`, `feasibility.py`):

- An absent `domain_authority` / `page_authority` is now `None`, not `0`, the
  same treatment `spam_score` always had. A real 0 from Moz is still kept.
- `avg_serp_da` is the mean of the **measured** domains only; the unmeasured
  ones are counted and reported (`da_count` / `da_missing`) rather than
  averaged in.
- Fewer than `feasibility.MIN_DA_FOR_VERDICT` measured domains yields
  `"Not Measured"`, not a verdict.

What still holds from D-3: DataForSEO stays primary, Moz stays fallback, and
Spam Score and link counts remain additive. The thresholds in
`config.yml → feasibility` are untouched.

Spec: `docs/review_2026-11-04/PLAN_D2_null_is_not_zero.md` (D2a.3)
Tests: `tests/test_d2_null_is_not_zero.py::TestMoz`

## Reading before changing

1. Read this repo's `CLAUDE.md` (global standards + "Always do this") and the
   `~/.claude/standards/` files it names — `external-api.md` (HTTP calls),
   `learnings.md` (P1–P10), `security.md` (secret redaction), and
   `file-maintainability.md` — before writing any fetch/scoring code.
2. Read `moz_client.py` (existing client + cache pattern), `run_feasibility.py`
   (DA client selection + the token-redaction rule), `feasibility.py`,
   `foundational_score.py`, `intent_classifier.py` + `intent_mapping.yml`,
   `query_variants.py`, `handoff_writer.py`, `http_retry.py`
   (`post_with_transient_retry`), and `handoff_schema.json`.
3. Confirm the base hasn't drifted: the files above must exist and match their
   described roles before starting. If not, stop and report.

## Design principles (binding)

1. **Deterministic Python computes; the LLM writes.** Every Moz metric is
   pre-computed and passed as data. The LLM never derives numbers.
2. **Editorial content lives in YAML/JSON.** Threshold labels, method lists,
   and caps go in `config.yml` (`moz:` section), not Python.
3. **Absent data is stated, not faked.** Failed/empty calls yield
   `data_available: false`; never fabricate zeros (Moz has no record for many
   low-volume/local keywords).
4. **Paid calls are gated.** New methods are off by default or capped; the run
   log states rows consumed (the API reports quota per response — surface it).
5. **Cache everything.** Reuse the `moz_cache` SQLite table + TTL pattern
   (`cache_ttl_days`, default 30) for every method; never re-fetch within TTL.
6. **No new credentials.** Reuse `MOZ_TOKEN`. No new `.env` keys.

## Implementation tasks

Each task = feature module + tests + doc updates. Commit per task with
`Spec: moz_api_upgrade_spec_v1.md#<task>`.

### T.0 — JSON-RPC client + quota probe

Add `moz_jsonrpc.py` (keep the legacy `url_metrics` path in `moz_client.py`
working until T.1 lands). Export:

- `moz_call(method: str, data: dict) -> dict` — POST to `api.moz.com/jsonrpc`
  with the envelope above; reuse `http_retry.post_with_transient_retry`;
  **redact `MOZ_TOKEN` from any logged exception** (same rule already in
  `run_feasibility.py`).
- `quota_lookup() -> int` — remaining rows.

Also update the stale `CLAUDE.md` env-var note: `MOZ_TOKEN` is *not*
"free tier: 50 rows/month" — it is the **Starter Medium** API plan; correct the
note and say the real quota is read at runtime via `quota.lookup`.

**Acceptance criteria:**
- `moz_call` round-trips a mocked JSON-RPC response; missing token raises the
  same `RuntimeError` discipline as `MozClient`.
- `quota_lookup` parsed by a unit test from a mocked response.
- No real network call in tests.

### T.1 — Site metrics upgrade (Spam Score + link counts)

Replace the `url_metrics` payload handling with `data.site.metrics.fetch` /
`.fetch.multiple`; extend the parsed result to `da`, `pa`, `spam_score`,
`link_counts`.

**Acceptance criteria:**
- `get_moz_metrics` returns all four fields per URL; callers reading only
  `da`/`pa` are unaffected (backward-compatible).
- `moz_cache` gains `spam_score` + `link_counts` columns via an idempotent
  `ALTER TABLE` migration (mirror the existing `CREATE TABLE IF NOT EXISTS`
  discipline).
- `run_feasibility.py` still treats Moz as fallback DA; the new fields are
  additive, per D-3. `avg_serp_da` itself **did** change in review chunk D2:
  it is now the mean of the measured domains only. See the D-3 note above.

### T.2 — Keyword metrics (volume + difficulty + organic CTR + priority)

New `moz_keywords.py` calling `data.keyword.metrics.fetch` per target keyword,
cached per keyword. Feeds feasibility/foundational scoring.

**Acceptance criteria:**
- `data_available: false` per keyword when Moz has no record — never a
  fabricated zero.
- New pre-computed signal block (e.g. `keyword.moz = {volume, difficulty,
  organic_ctr, priority}`) passed as data into brief prompts via the same path
  as `keyword_profiles.*`.
- `config.yml` `moz:` gains `keyword_metrics.enabled` (default **true** per
  D-2) and a per-run keyword cap.
- Every new prompt field is validated in `validate_llm_report` **or** added to
  `KNOWN_UNVALIDATED` in `test_validation_consistency.py` with a reason (the
  canary test enforces this).

### T.3 — Search-intent cross-check (does not replace intent rules)

Call `data.keyword.search.intent.fetch` per target keyword; store the four
intent scores. Use them to **cross-check** the `intent_mapping.yml` classifier;
do **not** replace it.

**Acceptance criteria:**
- Moz intent scores are stored and surfaced alongside the repo's own verdict;
  divergence is reported, never auto-overridden.
- No `intent_mapping.yml` rule is changed by this task.
- Absent-data flag per keyword.

### T.4 — Competitor ranking keywords + anchor text (cross-tool)

`data.site.ranking.keyword.list` and `data.site.anchor.text.list` for the
competitor domains per campaign. Results enrich the competitor handoff.

**Acceptance criteria:**
- Results flow into `handoff_writer.py` as a new `moz` block per competitor,
  **additive and absent-safe**.
- `config.yml` gains `moz.competitor.enabled` (default **false**) +
  `max_competitors`.
- Reuses the existing domain→competitor resolution; no new competitor list.

**Cross-tool contract (binding):** `handoff_schema.json` is draft-07 with
`additionalProperties: false`. Adding a `moz` field therefore requires a
`schema_version` bump and an updated `handoff_schema.json` (new optional
properties only — nothing new in `required`). serp-compete is **not** changed
in this spec, so the new fields must be **optional and ignored-safe** on its
side. Verify serp-compete tolerates the version bump (read its
`compete-spec.md` / `handoff_schema.json` consumer) and note any follow-up in
the closing status report.

### T.5 — Brand Authority + link momentum (stretch, off by default)

`data.site.metrics.brand_authority.fetch` and
`data.site.linking.domain.filter.recently_gained` / `.recently_lost`.

**Acceptance criteria:**
- Stored as additive, absent-safe fields; `config.yml` flags default **false**;
  capped.
- Documented in `docs/USER_MANUAL.md` as optional signals.

## Quota budget (verified at T.0: 3,000 rows/mo on 2026-08-27, **750** on 2026-11-21)

Rule of thumb (Moz docs): **1 row ≈ 1 object in the response**; some list
methods are "weighted" (consume >1 row/object — confirm per method). With the
30-day cache, one run:

| Method | Objects | Est. rows/run |
|---|---|---|
| Site metrics (50 URLs incl. competitors) | 50 | 50 |
| Keyword metrics (50 keywords) | 50 | 50 |
| Search intent (50 keywords) | 50 | 50 |
| Ranking keywords (3 competitors × ~100) | 300 | ≤300 (weighted — confirm) |
| Anchor text (3 domains) | ~30 | ~30 |
| Brand Authority (1 + 3 competitors) | 4 | 4 |

≈ **~500 rows/run** at ~1 run/week — within the 3,000/mo measured on
2026-08-27 **iff cache TTLs hold**, but the 2026-11-21 probe read 750, which
the same estimate exhausts in one and a half runs. The budget below is the
method shape, not a standing allowance: re-probe `quota.lookup` before
planning a run.
The run log must print rows consumed per method; when `rows_per_month` would be
exceeded, skip and log which method was skipped — never silently over-spend.

## Caching & gating (binding)

- Reuse `moz_cache` with a `method` column (or one table per method family) so
  keyword metrics, intent, and site metrics cache independently under the same
  TTL discipline.
- `config.yml` `moz:` gains `rows_per_month`, a master `enabled` switch, and
  per-method `enabled` + caps. Defaults per D-2.

## Editorial content

Any threshold label or method list lives in `config.yml` (`moz:`), per design
principle 2. Add any new editorial surface to this repo's `CLAUDE.md`
editorial-content list in the same change.

## Tests

- All external Moz calls mocked (CLAUDE.md: "Tests do not require API keys").
- Coverage: JSON-RPC envelope shape, token redaction on error, quota
  accounting, cache hit/miss per method, absent-data flag, and the canary
  (`test_validation_consistency.py`) staying green for any new prompt field.

## Definition of done (whole spec)

1. `python3 -m pytest test_*.py tests/ -q` fully green (no new failures, no
   newly skipped business-logic tests).
2. `docs/methodology.md`, `docs/USER_MANUAL.md`, and
   `docs/config_reference.md` updated per task, same commit.
3. Every new editorial surface listed in `CLAUDE.md`'s editorial-content list.
4. Each commit carries `Spec: moz_api_upgrade_spec_v1.md#<task>`.
5. A closing status report `docs/moz_api_upgrade_status_<date>.md` maps every
   acceptance criterion to a commit hash or "not done + reason".

## Execution model & sequencing

Implement sequentially **T.0 → T.1 → T.2 → T.3 → T.4 → T.5**. After each task:
keep the full suite green, commit per task, push. **Stop for approval at two
points:**

1. After **T.0** — report the real `quota.lookup` result and whether
   `MOZ_TOKEN` authenticates on `api.moz.com/jsonrpc`, before T.2 spends quota.
2. After **T.3** — before T.4 (the cross-tool handoff change).

## Handoff to Claude Code

Paste the block below into Claude Code from this repo's root:

```
Implement moz_api_upgrade_spec_v1.md, one task at a time in order
T.0 → T.1 → T.2 → T.3 → T.4 → T.5.

Follow this repo's CLAUDE.md (global standards + "Always do this"):
- source venv/bin/activate before any Python command
- run `python3 -m pytest test_*.py tests/ -q` before and after each change
- never `git add .` — commit only the files changed for the current task
- commit per task with "Spec: moz_api_upgrade_spec_v1.md#<task>", push after
  each task
- tests must not call real APIs — mock all Moz/HTTP calls
- read the ~/.claude/standards/ files the CLAUDE.md names before writing
  fetch/scoring code

Plan first: read the spec, then write out your plan for T.0 and STOP for my
approval before writing code. After T.0, run quota.lookup, report the actual
row quota + whether MOZ_TOKEN authenticates on api.moz.com/jsonrpc, and STOP
again before T.2 spends any quota. After T.3, STOP before T.4 (cross-tool
handoff change).
```
