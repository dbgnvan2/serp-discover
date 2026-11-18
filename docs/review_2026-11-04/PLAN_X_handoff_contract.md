# Chunk X — Handoff and export contract

Spec: `docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md` §3 Chunk X
Tier: **Full** (`~/.claude/standards/effort-budget.md`) — the handoff is the only
data path between the two tools, and a wrong host form there silently changes
which competitors are measured.

## Reproduced

1. **Two forms of one host in one file.** `moz_competitor.competitor_domains`
   derived competitor hosts with its own lower-casing and kept a leading `www.`,
   while `handoff_writer` published `targets[].domain` through
   `domain_utils.normalize_domain`. A SERP carrying `https://WWW.JaneApp.com/b`
   published `janeapp.com` as a target and `www.janeapp.com` as a `moz.domains`
   key, so the consumer's join on the Moz block missed.
2. **The config form decided who was measured.** The client test and the
   `omit_from_audit` test both compared raw strings. A `www.livingsystems.ca` in
   `config.yml` stopped excluding the client's own pages from the Moz row budget,
   and an omit entry written in the other form was ignored.
3. **`client_domain` was published raw** — `client_domain or ""` — so the field
   did not match the form of the targets in the same file.
4. **Neither report stated the other tool's GSC pull.** compete's note asserted
   serp-discover pulls "90 days, all devices, global", which stopped being true
   at discover's chunk D5 (`gsc.country`, `gsc.device`). compete itself filtered
   country but not device, so its CTRs averaged desktop and mobile while the
   DataForSEO snapshot it sits beside is a desktop snapshot.

## As built

**serp-discover**

- `moz_competitor.competitor_domains` canonicalises the client, every omit
  entry and every SERP host through `normalize_domain`, and excludes the client
  by exact host or true subdomain (`domain == client or
  domain.endswith("." + client)`) instead of by substring.
- `handoff_writer` publishes the canonical `client_domain`.
- `docs/handoff_contract.md` → version 2.1: owner decision 4 is settled as
  **the producer canonicalises every host it publishes; the consumer keeps
  normalising on read**, because handoff files already on disk carry the old
  form. A new section states each tool's GSC window, country and device.
- `tests/test_handoff_contract.py` (new) — the producer's half of the contract,
  calling the real `moz_competitor` and `handoff_writer`.

**serp-compete**

- `gsc_performance.GSC_DEVICES` + a `gsc_settings.device` filter (default
  `desktop`, `all`/`none`/`any` turns it off, an unknown value warns and is
  ignored), built into one `dimensionFilterGroups` entry beside the country
  filter.
- `reporting.gsc_pull_note` prints the device the pull used, says "desktop and
  mobile clicks averaged together" when unfiltered, and no longer states
  serp-discover's filters as fact (P6) — it says that tool states its own.
- `shared_config.json` gains `gsc_settings.device: "desktop"`.
- `README.md`, `docs/USER_MANUAL.md`, `docs/handoff_contract.md` updated to 2.1.

## Verification

- serp-discover: `python3 -m pytest test_*.py tests/ -q` → **1950 passed, 68
  skipped, exit 0**.
- serp-compete: `python3 -m pytest tests/ -q` → **795 passed, exit 0**.
- **Mutations: 9 of 9 fail a guard, none vacuous.** X1 moz keys keep `www`;
  X2 client test back to a substring; X3 omit list compared raw; X4
  `client_domain` published raw; X5 contract doc loses the GSC table; X6 compete
  stops filtering the device; X7 compete prints every device as comparable; X8
  compete asserts the other tool's pull again; X9 compete's device default
  becomes unfiltered.
  X6 initially failed nothing: the guard matched `inspect.getsource` text that
  survived inside the dead branch. It was replaced with a behavioural guard that
  builds the real request against a recording service and asserts the device
  filter is in it — the guard was strengthened, the mutation was not dropped.
- Effort: ~200 lines production, ~250 lines tests (1.25x), ~90 lines plan prose
  (0.45x of production — over the 0.3x ceiling because the contract settles an
  owner decision that had to be written down; the contract/manual/methodology
  changes are required by working rule 13 and are not counted as plan prose).

## Cold review (`learning-qa`, tier Full)

12 findings: 0 high, 8 medium, 4 low. All eight medium fixed, the four low
dropped, one medium dropped as a false positive. Each fix carries its own
mutation (X10-X17 above; 17 of 17 mutations now fail a guard).

Fixed:

1. `moz_competitor.build_handoff_block` published `client_domain.lower()` — the
   one host chunk X had left non-canonical, while both repos' contracts asserted
   the producer canonicalises every host it publishes (P6).
2. The new contract test built its own `moz` block, so finding 1 was green
   8/8. It now drives the real `build_handoff_block` with the Moz calls stubbed
   and asserts over `moz.client.domain` and `moz.domains` as a run writes them.
3. `brand_authority_for` / `anchor_texts_for` were called with the raw config
   value, so the paid Moz calls were billed under a cache key
   (`domain, scope, locale`) no other path reads (P5). `test_moz_competitor.py`
   had pinned that spelling; the assertion was repointed, not deleted.
4. compete: an unrecognised `gsc_settings.device` pulled every device and the
   report printed it exactly as a deliberate `device: all` — a typo read as a
   decision (P1). It now says the value GSC rejected and that the figures are
   not comparable.
5. compete: `mobile` or `tablet` printed "mobile only" and no caveat, which is
   the one case certainly not comparable with a desktop SERP snapshot (P6).
6. compete: "the country filter matches the DataForSEO snapshot" was printed
   for any non-empty country, so `usa` claimed comparability with a Canada
   snapshot. The DataForSEO market moved out of four `api_clients.py` literals
   into `shared_config.json` `dataforseo_snapshot`, and the note now compares
   the two sides instead of asserting they match (P4/P6).
7. compete: only `generate_summary` carried the pull note. `gsc_strike_list.md`
   and `gsc_strategic_gap.md` print positions, impressions and CTR from the same
   narrowed pull, and their empty state is also what a failed pull prints
   (P1/P9). Both now state the pull, and the empty case says so.
8. compete: `from src.gsc_performance import GSC_DEVICES` at module scope pulled
   google-auth, googleapiclient, spacy and openai into every report render. The
   import is now inside `gsc_pull_note`.

Dropped:

- **False positive (medium).** "discover sends a lower-case device expression
  while compete uppercases it." `gsc_filters.resolve_query_filters` maps through
  the same `GSC_DEVICES` table before `gsc_client` is constructed
  (`run_gsc_analysis.py:773`), so discover already sends `DESKTOP`. The
  reviewer read `gsc_client` alone.
- Three low findings: an unreadable `omit_from_audit` entry is dropped without a
  count; `moz_competitor` holds a second copy of the client-host test
  (`handoff_writer._is_client_host`); the contract's GSC table describes
  discover's pull while `gsc.enabled` is false.

## Adjacent issues found, not fixed

- `serp_audit.py:1517` writes `urlparse(url).netloc` (raw case, `www.` kept)
  into `serp_results.domain`, so the DB record of a SERP row carries a host form
  the handoff no longer uses. Latent: no consumer groups by that column.
- compete's `handoff_moz.py:257` compares `domain != client["domain"]`
  un-normalised while `:397` normalises.
- Nothing in compete reads the handoff's `client_domain`; it takes the client
  host from its own `shared_config.client.domain`. The two tools' agreement on
  the client host rests on two config values nothing reconciles.
- The existing `moz_competitor_cache` row is `www.google.com`; after this change
  it is a miss and is refetched as `google.com` (one billed row). `google.com`
  reaching the competitor list at all looks unintended.
- `normalize_domain` keeps a leading `m.` and other host prefixes, so a mobile
  subdomain of a competitor is still counted as a separate competitor.
- compete's `gsc_settings.country` is passed through as typed (`can`) while
  discover maps `ca` → `CAN`; the two configs name the same country differently
  and nothing checks they agree.
