# D2c — one host, one answer; an error page is not content

Third and last push of review chunk D2. Three findings, one sentence each:

- **D-C-08** (S2) — `www.havencollective.ca` is classified `N/A` although
  `domain_overrides.yml` carries `havencollective.ca`. The pipeline looks the
  host up verbatim; the refresh path and the override-candidate report strip
  `www.` first, so the three disagree.
- **D-C-20** (S3) — `url_enricher.fetch_url` returns the body of a 403, 429 or
  5xx, and the enrichment loop's only gate is `if fetch_res:`, so a Cloudflare
  challenge page is classified, counted and scored as the ranked page.
- **D-C-21** (S3) — `Has_Main_AI_Overview` is set from the un-located fallback
  probe as well as the located SERP, so a keyword whose Vancouver SERP has no
  AI Overview is reported as having one.

## Reproduced before building (the workplan requires it)

- D-C-08: `classify("www." + d) != classify(d)` for **35 of the 121** current
  overrides (`bccsu.ca`, `bcmhsus.ca`, `boomerangcc.ca`, …).
- D-C-20: `fetch_url` on a mocked 403 returns `status_code 403` with a 100-byte
  challenge body, and `extract_features` reports `word_count_est: 6`,
  `author_present: False` from it.
- D-C-21: with only `google_ai_overview_probe` present,
  `parse_data` returns `Has_Main_AI_Overview: True` and no `AI_Overview_Mode`.

## Acceptance criteria

### D-C-08 — one host, one answer

- **D2c.1** A new `domain_utils.normalize_domain(url_or_domain)` is the one
  definition: it accepts a URL or a bare host, takes the netloc, drops any
  port, lower-cases, and removes a leading `www.` with `removeprefix` — never
  `replace("www.", "")`, which strips the sequence anywhere in the string, and
  never `lstrip("www.")`, which strips the *character set*.
- **D2c.2** `EntityClassifier` normalises both sides: the override keys when
  the file is loaded, and the host before lookup and before pattern matching.
  `classify("www.x.ca", …) == classify("x.ca", …)` for **every** override in
  `domain_overrides.yml`, asserted over the real file.
- **D2c.3** The other producers on the override/classification path call the
  shared helper rather than their own copy:
  `generate_domain_override_candidates.normalize_domain`,
  `refresh_analysis_outputs.classify_domain_for_row`, and
  `brief_data_extraction._extract_domain` (line 149), which used
  `.replace("www.", "")`.
- **D2c.4** The candidate report no longer proposes a domain an override
  already covers under a `www.` host.

### D-C-20 — an error page is not content

- **D2c.5** The enrichment loop enriches only on a fetch that returned a
  status below 400. A `>= 400` response is recorded, not parsed: no
  `Content_Type`, `Word_Count`, schema, extractability, freshness or E-E-A-T
  value is taken from the body.
- **D2c.6** Every organic row carries `Fetch_Status`, so the reader can tell
  the four outcomes apart: enriched, blocked (the status), unreachable (the
  fetch raised), and not attempted (rank beyond the cap, or a recovered link
  that is not the destination page). The words are editorial and live in
  `serp_vocab.yml`, not in Python literals.
- **D2c.7** The status still reaches SQLite via `save_url_features`, so a
  blocked page is a record, not a hole.
- **D2c.8** "N of M pages blocked" reaches a reader, not only the log: a
  `parsing_warnings` row, which is the project's channel for what the run
  could not read (P2).
- **D2c.9** Domain-level classification is unaffected — it never used the body.

### D-C-21 — the located SERP and the un-located probe are different questions

- **D2c.10** `parse_data` derives which source supplied the overview and
  records it as `AI_Overview_Mode` on the overview row:
  `direct_in_main` | `token_followup` | `fallback_without_location` |
  `not_present`.
- **D2c.11** `Has_Main_AI_Overview` is True only for an overview on the
  **located** SERP. An overview that only the un-located probe returned sets
  the separate `Has_Unlocated_AI_Overview`, and `AI_Overview` text is still
  published — labelled by the mode, never silently promoted.
- **D2c.12** A `parsing_warnings` row says the overview came from the
  un-located probe, naming what it does and does not evidence.
- **D2c.13** The brief payload carries `has_ai_overview_unlocated` beside
  `has_ai_overview`, so `aio_exposure`, `commodity_score` and play routing
  charge CTR loss and route extraction plays on the located SERP only.
- **D2c.14** Both modes are tested: an overview in the main response, and one
  only the fallback returned.

## Adjacent issues found, not fixed

- `url_enricher.fetch_url` calls `requests.head` / `requests.get` directly,
  with a timeout but no retry or backoff, while the repo has a shared
  `http_retry` module (P5 — harden external calls as a class). Out of scope
  here: it changes fetch *volume*, which belongs with D-C-06/D-C-13 in D4.
- Six more ad-hoc `removeprefix("www.")` normalisers remain outside the
  override/classification path (`probe_ai_visibility.py` ×4,
  `dataforseo_client.py` ×2, `run_feasibility.py`, `feasibility.py`,
  `citation_table.py` ×2, `brand_mentions.py`). They are correct, merely
  duplicated; migrating them all would be a sweeping diff across modules this
  chunk does not touch.
- `refresh_analysis_outputs` re-classifies organic rows only, so the keyword
  profiles, AIO-citation entities, handoff and markdown report keep the
  pre-override verdicts. That is D-C-09, its own finding.

## Verification

- `probe_10_www_bypasses_overrides.py`, `probe_11_error_page_as_content.py`
  and `probe_12_unlocated_aio.py` print the fault, then the fix, and assert
  the fixed behaviour.
- `tests/test_d2c_one_host_one_answer.py`.
- Full suite by exit code; `docs/USER_MANUAL.md`, `docs/methodology.md`,
  `docs/config_reference.md`, `docs/architecture.md` and the workplan index
  updated in the same commit.

## As built

All 14 criteria are met. Deviations and decisions worth recording:

- **D2c.1** `normalize_domain` also rejects free text: a value with any
  whitespace in it ("not a url") is not a host and returns `""`. An existing
  test (`tests/test_citation_surfaces.py`) depended on that, rightly — a bare
  string with no dot is not a host either, but rejecting dotless labels would
  also reject `localhost`, so the rule is whitespace only.
- **D2c.5-D2c.9** fixing this in place would have pushed `serp_audit.py` past
  its 2200-line cap (`tests/test_serp_audit_split.py::TestI63MainModuleSize`),
  so the per-row enrichment moved to a new `enrichment.py` — which is where it
  belonged anyway. `serp_audit.py` went from 2184 to 2186 lines net of the AIO
  change; the module is still within 14 lines of its cap, which the next
  change to it will have to deal with.
- **D2c.6** `Fetch_Status` is new on every organic row. It is additive: no
  existing column was renamed, so the `validate_xlsx_vs_json.py` field
  contract is unchanged.
- **D2c.10/D2c.11** the mode is *derived in `parse_data`* from which source
  supplied the overview, rather than threaded through from `aio_log`. The
  parse then states what it actually used, which cannot drift from the fetch's
  own record of what it did.
- A source-inspection test in `tests/test_link_recovery_wiring.py` pinned the
  recovered-link gate by its text in `serp_audit.py`. The gate moved, so the
  test is now behavioural: it asserts that a non-destination row is never
  fetched and reads `Not Measured`.

### The cold review pass, and what it changed

A `learning-qa` pass over the uncommitted diff returned 10 findings, all
medium or higher, so all 10 were fixed before the commit (working process
step 5).

1. **`Not Measured` became a measured content type.** With `not_attempted`
   now on ranks 6-10 of every keyword, the content-type counter made it the
   market's plurality category. Skipped now, and `organic_summary` carries
   `content_type_measured_count` / `content_type_unmeasured_count` (P2).
2. **The un-located overview's citations were still consumed.** The criteria
   stopped `Has_Main_AI_Overview`, but the brief still read the probe's
   citations and text as the located SERP's — `has_ai_overview: False` while
   quoting the overview and counting the client as visible in it.
   `ai_citations` rows now carry `AI_Overview_Mode`; the consumer routes them
   into `aio_citations_excluded_unlocated`, blanks the derived text fields and
   sets `has_aio_unlocated`. `prompts/main_report/system.md` says what the
   flags mean.
3. **The four enriched-page signal blocks lost their denominator.**
   `schema_signals`, `extractability`, `freshness` and `eeat_signals` stopped
   counting blocked pages silently, and an empty block still said "the
   analysis JSON predates capture, or enrichment disabled" — a transient block
   reported as permanent absence (P1). Each now carries `fetch_coverage`
   (rows / read / unread / by_state) and, when empty, a `reason` naming which.
4. **The handoff was the host comparison D2c had not normalised.**
   `handoff_writer` compared a raw netloc against a raw client domain and omit
   list, and the client test was `client_domain_lower in domain` — a substring
   match that dropped any competitor whose host merely contained the client's
   (`notlivingsystems.ca`). All three go through `normalize_domain` now, and
   the client test is equality or a dot-suffix match. This settles workplan
   **decision 4**: Tool 1 writes the canonical host, which serp-compete
   already normalises to at ingest (`src/brand_utils.py`,
   `src/handoff_moz.py`). Recorded in `docs/handoff_contract.md`.
5. `client_domain` from `config.yml` was itself unnormalised, so
   `www.livingsystems.ca` there would have failed every client match silently.
6. `Fetch_State` added beside `Fetch_Status`: the state is machine-readable,
   the words editorial, so no consumer gates on text the user may re-word (P4).
7. The "N of M pages" warning fired on blocked only; now blocked or
   unreachable. `status_text` falls back to literal English rather than
   printing a state key into a cell.
8. `enrich_row` takes `domain=` instead of a key smuggled onto the row dict.
9. Rows with no URL read `No URL`; a run with enrichment off reads `Not
   Enriched (disabled)`. Both were silently `Not Measured`.
10. Normalised override keys can collide. `EntityClassifier` warns when two
    keys disagree on one host instead of letting file order pick, and drops a
    key normalising to nothing. The current file is clean: 121 keys, no
    collisions.

The pass also checked the extraction into `enrichment.py` line-by-line
against `git show HEAD:serp_audit.py` and found it faithful, with one
improvement: a `None` status code is treated as an error rather than raising.

### Documentation updated in this change

`docs/architecture.md` (both new modules), `docs/methodology.md` (which pages
are read, which host is which, and the located-vs-un-located overview),
`docs/USER_MANUAL.md` (the `Fetch_Status` table and what to do about each
outcome; the two-questions explanation for the AI Overview),
`docs/config_reference.md` (`serp_vocab.yml fetch_status`, plus `Fetch_State`
and the two extra statuses), `docs/handoff_contract.md` (the canonical host
form and the client test), `prompts/main_report/system.md` (the two AI
Overview flags and the excluded-citation block), `CLAUDE.md` (the
editorial-content list), and the workplan index.
