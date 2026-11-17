# Competitor Handoff Contract

**File:** `competitor_handoff_<topic>_<timestamp>.json`  
**Schema:** `handoff_schema.json` (JSON Schema draft-07)  
**Version:** 1.0

This document describes the contract between Tool 1 (`serp-discover`) and Tool 2 (`serp-compete`). The handoff file is the stable, validated interface between the two tools.

---

## Purpose

Tool 1 audits SERPs and identifies which competitor URLs rank for each keyword. Tool 2 audits those competitor pages in depth (vocabulary analysis, EEAT scoring, cluster detection). The handoff file tells Tool 2 exactly which URLs to audit and why.

---

## File location and naming

Produced on every full pipeline run alongside the other output files:

```
output/competitor_handoff_<topic>_<YYYYMMDD_HHMM>.json
```

The `<topic>` slug is derived from the input keyword CSV filename (same as `market_analysis_*.json`).

---

## Schema

### Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | ✅ | `"2.0"`, or `"2.1"` when the optional `moz` block is present. `1.0`/`1.1` are the same shape with per-page ranks — see "schema_version 2.0" below |
| `source_run_id` | string | ✅ | Unique ID of the Tool 1 run that produced this file |
| `source_run_timestamp` | string | ✅ | ISO 8601 UTC timestamp of the run |
| `client_domain` | string | ✅ | The client's primary domain (e.g. `livingsystems.ca`) |
| `client_brand_names` | array of strings | ✅ | Brand name patterns for the client |
| `targets` | array of target objects | ✅ | Competitor URLs for Tool 2 to audit (may be empty) |
| `exclusions` | object | ✅ | Counts of URLs excluded from `targets` |

### Target object fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✅ | Full URL of the competitor page |
| `domain` | string | ✅ | Hostname extracted from the URL |
| `rank` | integer | ✅ | Absolute organic position on the SERP (1 = first result overall). Per-page under `schema_version` 1.0/1.1 |
| `entity_type` | string | ✅ | Entity classification (counselling, directory, media, etc.) |
| `content_type` | string | ✅ | Content type (service, guide, directory, news, pdf, other) |
| `title` | string | ✅ | Page title from the SERP result |
| `source_keyword` | string | ✅ | The root keyword for which this URL ranked |
| `primary_keyword_for_url` | string | ✅ | The keyword for which this URL had its best (lowest) rank |

### Exclusions object fields

| Field | Type | Description |
|-------|------|-------------|
| `client_urls_excluded` | integer | URLs on the client domain that were excluded |
| `omit_list_excluded` | integer | URLs excluded because their domain is in `omit_from_audit` |
| `omit_list_used` | array of strings | The domains that were in the omit list for this run |

---

## Selection logic

For each keyword:

1. Take the top N organic results (default N=10, set by `config.yml → audit_targets.n`).
2. Exclude URLs whose domain matches the client domain.
3. Exclude URLs whose domain is in `config.yml → audit_targets.omit_from_audit`.
4. Add each remaining URL to `targets` with `source_keyword` set.

If the same URL ranks for multiple keywords, it appears in `targets` multiple times (once per `source_keyword`). This is intentional — Tool 2 uses `source_keyword` to understand why each target matters.

### The canonical host form (review chunk D2c / finding D-C-08)

Every host in this document is written in one form: lowercase, no port, no
credentials, and no leading `www.` (`domain_utils.normalize_domain`). That is
what `targets[].domain` carries, and it is also the key of the optional `moz`
block's `domains` map.

The same normalisation is applied to both sides of every comparison that
produces the file, so one site gets one answer regardless of how it was
written:

- the client domain from `config.yml`, so `client_domain: www.livingsystems.ca`
  excludes `livingsystems.ca` and vice versa;
- each entry of `audit_targets.omit_from_audit`, so an entry written with
  `www.` still excludes the bare host;
- each ranked URL's host.

The client test is equality or a dot-suffix match (`blog.livingsystems.ca` is
the client), **not** a substring match — the substring form silently dropped
any competitor whose host merely contained the client's
(`notlivingsystems.ca`).

Tool 2 normalises hosts at ingest too (`src/brand_utils.py`,
`src/handoff_moz.py`), so the two tools agree on the key without either side
having to guess.

---

## `source_keyword` vs `primary_keyword_for_url`

These two fields are semantically different and will often diverge.

- **`source_keyword`**: the keyword for which this particular target entry was selected. A URL that ranks for 3 keywords appears 3 times in `targets`, each with a different `source_keyword`.
- **`primary_keyword_for_url`**: the keyword for which this URL had its **best** (lowest numeric) rank across all keywords in the run. This is the same for all entries with the same URL, regardless of which `source_keyword` generated them.

**When they diverge:** A URL included because it ranks #8 for keyword A may have its best rank (#2) for keyword B. Its `source_keyword` is A, but `primary_keyword_for_url` is B.

**Fixture evidence** (run `20260501_0832`, 46 targets total — 4 cases where the fields differ):

| URL (truncated) | `source_keyword` | `primary_keyword_for_url` |
|-----------------|-----------------|--------------------------|
| `https://counselling-vancouver.com/` | "How much is couples therapy in Vancouver?" | "success rate of couples therapy?" |
| `https://www.psychologytoday.com/ca/therapists/bc/v…` | "How much is couples therapy in Vancouver?" | "What type of therapist is best for couples therapy?" |
| `https://www.nofearcounselling.com/why-consider-cou…` | "success rate of couples therapy?" | "how does couples counselling work" |
| `https://wellbeingscounselling.ca/psychotherapy/ser…` | "success rate of couples therapy?" | "how does couples counselling work" |

**Tool 2 guidance:** Use `source_keyword` to understand *why this entry is in the audit queue* (i.e., this URL was competitive for this keyword). Use `primary_keyword_for_url` to understand *where this page is most authoritative* and to avoid auditing the same URL twice with different context (de-duplicate by URL, keeping the entry with the lowest `rank` or the `primary_keyword_for_url` entry).

---

## How Tool 2 consumes this file

Tool 2's `get_latest_market_data()` reads this file to populate its audit queue. It uses:

- `targets[*].url` — the page to fetch and audit
- `targets[*].source_keyword` — for context on why the page matters
- `targets[*].entity_type` and `targets[*].content_type` — for initial scoring context
- `client_domain` — to exclude the client from competitor comparisons
- `exclusions` — for audit traceability

---

## Validation

Tool 1 validates the handoff against `handoff_schema.json` before writing. If validation fails:
- The handoff file is **not written**
- The schema violation is logged with the specific failing field
- The other output files (`market_analysis_*.json`, `*.xlsx`, `*.md`) are **not deleted**

If organic results are empty (no SERP data collected), no handoff file is written.

---

## Configuration

```yaml
# config.yml
audit_targets:
  n: 10                  # Number of top organic URLs per keyword
  omit_from_audit: []    # Domains to exclude from the handoff
```


## schema_version 2.0 — `rank` is absolute (review chunk D1 / finding D-C-01)

Under 1.0 and 1.1, `targets[].rank` carried SerpAPI's per-page `position`. SerpAPI restarts
that at 1 on every paginated page, so a three-page Tool 1 run emitted ranks running
1..9, 1..10, 1..10 and **three different targets each claimed rank 1** — Tool 2 could not
tell a genuine #1 from a page-3 row, and any `rank <= 10` filter on its side admitted about
three rows per rank.

Since 2026-11-16 Tool 1 renumbers the merged pages, so `rank` is the absolute position on
the SERP. The document's *shape* is unchanged: nothing was added, removed or renamed, and
only the meaning of one field moved. The version is bumped anyway because Tool 2 enforces
`handoff.supported_versions` and keys its rank-column warning off
`handoff.absolute_rank_versions`; the bump is how it learns these ranks can be trusted.

**Tool 2 side (`serp-compete/shared_config.json`):** `"2.0"` and `"2.1"` must be listed in
both `handoff.supported_versions` and `handoff.absolute_rank_versions`. Until they are in
`supported_versions`, Tool 2 hard-fails a 2.x handoff (`main._unsupported_handoff_version`);
until they are in `absolute_rank_versions`, it keeps printing the rank-column warning on
data that no longer needs it.

De-duplicating "by the lowest `rank`" is now meaningful across the whole SERP rather than
within a page.

## schema_version 2.1 — the optional `moz` block (moz_api_upgrade_spec_v1.md T.4)

`schema_version` is `"2.1"` **only when** the optional top-level `moz` block is present; a run
with `moz.competitor.enabled: false` emits the smaller `"2.0"` document. (These were `"1.1"`
and `"1.0"` before the rank change above.)

```
moz:
  generated_at: ISO-8601
  locale: en-CA          # the Moz query context these signals were fetched under
  scope: domain
  client:                # optional; present when brand_authority and/or
                         # competitor.client_anchor_texts is on
    domain: <client domain>
    brand_authority: {status, data_available, score}
    anchor_texts:    {status, items[], returned, truncated}
  domains:
    <competitor domain>:
      data_available: bool
      status: ok | no_record | error | skipped_run_cap | skipped_quota
      complete: bool             # false when an enabled signal is missing
      signals_missing: [<signal>, ...]
      fetched_at: ISO-8601       # the OLDEST signal below; see "per signal"
      signals_fetched_at: {<signal>: ISO-8601}
      ranking_keywords: {status, data_available, reason, items[], returned,
                         truncated, fetched_at}
      anchor_texts:     {status, data_available, reason, items[], returned,
                         truncated, fetched_at}
      brand_authority:  {status, data_available, score?, fetched_at}
      link_momentum:    {status, data_available, window, lost{...}, live{...},
                         fetched_at}
```

**Each signal is fetched, cached and dated on its own** (review chunk D2b,
finding D-C-10). A sub-call that failed is never cached, so what a consumer
reads is either a real measurement or an explicit failure — never a 30-day-old
cached error standing in for one, and never an empty `items: []` that has to
be guessed at:

- `status` on a sub-block is `ok` / `no_record` / `error` / `disabled` /
  `not_fetched`. `data_available` and `reason` are present on **every**
  sub-block, with `reason` empty when there is nothing to say, so a consumer
  never reads `None` where a sibling block has a string.
- `error` means the Moz call failed. It is **not** a statement about the
  domain, and Tool 1 will ask again on the next run — so repeated `errored`
  readings across runs are repeated real outages, not one stale cached one.
- `disabled` means the signal is switched off in this run's config;
  `not_fetched` means it was not asked for (a per-run cap or the row quota).
- `complete` is false, and `signals_missing` names them, when an **enabled**
  signal was not *obtained* — where obtained means a real reading or a
  measured absence (`ok` / `no_record`). A failed call, a cap or quota skip,
  and a signal not asked for are all gaps. A block can carry real ranking keywords beside a
  failed anchor-text call, so `data_available: true` at the top level means
  "something was measured", not "everything was". Read `complete` before
  treating a signal's `items: []` as a finding about the domain. A missing
  page signal still carries `items: []`, `returned: 0` and `truncated: false`
  beside its status, so the shape never varies by outcome.
- Each sub-block's `fetched_at` is when **that** signal was collected. The
  domain's top-level `fetched_at` is the **oldest** of them: the block as a
  whole is only as current as its stalest part. `signals_fetched_at` gives
  them all. A ranking-keywords block from 27 days ago beside an anchor-text
  block from today must not both read as today.

**The block is top-level, never inside a target.** Both repos' schemas set
`additionalProperties: false` on each target, and serp-compete's `Serp-compete/src/main.py`
calls `sys.exit(1)` on any validation error — so a new field is *not* silently ignored
downstream, it is fatal. Adding a per-target field would break Tool 2 outright.

**Both copies of `handoff_schema.json` must stay in sync.** serp-compete validates against its
own copy, so the v1.1 schema was synced there in the same change (the established workflow —
its previous commit is "Sync handoff_schema.json from serp-discover"). serp-compete's code is
otherwise unchanged: it ignores the block, and its full suite (158 tests) passes with the new
schema. `test_moz_competitor.py::TestHandoffContract` validates a generated v1.1 handoff
against **Tool 2's real schema file on disk**, so the two drifting apart fails a test here.

The `client` entry carries the client's own signals. Brand Authority gives the competitor
scores a reference point rather than being absolute numbers with nothing to compare against
(livingsystems.ca scores 1; psychologytoday.com scores 73). Its `anchor_texts` exist so Tool 2 can run its
anchor-spam check against the client's own inbound links — the case that reveals a
**negative-SEO campaign aimed at the client**, which is otherwise invisible. The client is
**not** added to `domains` — the handoff excludes the client by design, and Tool 2 tags a
hit on it `is_own_site` rather than filing it as competitor intel.

**Follow-up for serp-compete (not done in this spec):** nothing consumes the block yet.
`convert_handoff_to_targets` drops it, which is correct and safe. Using the anchor-text and
ranking-keyword data in Tool 2's audit is a separate piece of work.
