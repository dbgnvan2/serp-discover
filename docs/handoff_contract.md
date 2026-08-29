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
| `schema_version` | string | ✅ | Always `"1.0"` |
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
| `rank` | integer | ✅ | Organic rank position on the SERP |
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


## schema_version 1.1 — the optional `moz` block (moz_api_upgrade_spec_v1.md T.4)

`schema_version` is `"1.1"` **only when** the optional top-level `moz` block is present; a run
with `moz.competitor.enabled: false` still emits a byte-identical `"1.0"` document.

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
      ranking_keywords: {status, items[], returned, truncated}
      anchor_texts:     {status, items[], returned, truncated}
```

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
