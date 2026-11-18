# Chunk Y1 — one definition each

Adjacent-issue batch, taken from the "Adjacent issues found, not fixed" lists
the earlier chunks' cold reviews left behind (global rule 10). Every item in
this chunk is the same fault: one rule with several implementations, so the
answer depended on which copy a path happened to call.

Effort tier: **Full** (`~/.claude/standards/effort-budget.md`) — the changes
touch the data path, the DB keys, the brief's validated numbers and the
cross-tool handoff. One guard per finding fixed.

## Reproduced

1. **`m.` was not an alias.** `normalize_domain` stripped `www.` only, so
   `m.psychologytoday.com` and `psychologytoday.com` were two competitors.
   Both can hold a top-10 slot on one SERP, and the DA mean, the Moz row
   budget and the handoff's target list all counted the site twice.
2. **Eight local copies of the host rule.** `citation_table.domain_of`,
   `brand_mentions._domain_stub`, `dataforseo_client` (the payload `target`
   and `_extract_domain`), `feasibility.domain_of`,
   `run_feasibility._extract_domain` and `probe_ai_visibility._domain_from_url`
   each re-implemented it, variously with and without the port, the userinfo
   and the prefix. Adding `m.` to one of them would have deepened the
   disagreement rather than ending it.
3. **The two DB columns that are joined on kept the raw host.**
   `storage.save_serp_result` wrote `serp_results.domain` and
   `save_domain_features` wrote `domain_features.domain` from whatever the
   caller passed. The entity-type join is on those columns, so
   `www.x.ca` in one and `x.ca` in the other was a miss.
4. **Two demand predicates.** `brief_validation` and `brief_data_extraction`
   each held their own "is this keyword's volume measured, and is it too
   small to invest in" pair. The validator checked the brief against one and
   the brief was written from the other.
5. **The title-pattern thresholds were Python defaults nothing passed** —
   `top_n=10`, `dominant_threshold=4` — while `thresholds_provenance` listed
   `title_patterns` as a tunable family, so the report's provenance line named
   numbers no config held (P4).
6. **The feasibility summary printed its own icons.** `run_feasibility`'s
   `## Summary` block carried a dict literal, so "Not measured" was `⚠️` there
   and `❓` wherever `feasibility_messages.yml` was read — one state, two
   glyphs, in one run's outputs.
7. **A parity rule pinned to one spelling.** `_play_assignment_phrase` matched
   the play label literally, so `prioritise`/`prioritize` decided whether the
   check ran at all.
8. **compete compared the client's host raw** in `anchor_texts_by_domain`, so
   a handoff file carrying the pre-chunk-X `www.` spelling lost the client's
   own anchors to a richer competitor sample filed under the same site.
9. **compete never read `client_domain`.** Tool 1 publishes it; nothing on the
   consumer side looked, so a handoff produced for one client could be audited
   against another client's `shared_config` with no warning anywhere.

## As built

- `domain_utils`: `ALIAS_PREFIXES = ("www.", "m.")`, stripped repeatedly to a
  fixed point, and only while a `.` remains in the rest — `m.ca` and `www.ca`
  are registrable domains whose first label happens to be an alias word, and
  stripping it would leave a bare public suffix, which is not a host. The list
  is technical, not editorial, so it lives beside the rule rather than in
  `config.yml`.
- The eight copies now delegate. No module strips a prefix by hand; a guard
  greps for the by-hand forms across the repo.
- `storage` canonicalises on write in both paths; an unreadable host writes no
  `domain_features` row and warns, rather than writing a row under `""` that
  the join would silently attach to nothing (P2).
- `keyword_demand.py`: one leaf module (`measured_volume`, `any_measured`,
  `assessment`, `too_small`); both callers are now thin aliases of it.
- `config.yml` gains `title_patterns.top_n` / `dominant_threshold`;
  `title_patterns.resolve_thresholds` reads them and degrades to the documented
  default with a warning on a non-positive or unparseable value (P1 — a bad
  config value is not a reason to abort a run, and not a reason to use it).
  The value is threaded through `brief_rendering` →
  `extract_analysis_data_from_json` rather than read twice.
- `run_feasibility`'s summary calls `feasibility.status_label`.
- `_play_assignment_phrase` builds its pattern with `[sz]` at each `s`/`z`.
- compete: `brand_utils.normalise_domain` mirrors the discover rule exactly,
  same constant name and values; `handoff_moz` compares the client host in the
  canonical form; `remember_client_domain` / `validated_client_domain` /
  `client_domain_mismatch` read what Tool 1 publishes and `run_audit` prints
  the disagreement. A handoff that does not say is silence, not a mismatch.

## Verification

- `tests/test_y1_one_definition_each.py` — 18 tests, five classes: one host
  rule, the DB keys one site per row, one demand predicate, the editorial
  values live in config, the parity rule survives a spelling.
- `Serp-compete/tests/test_handoff_contract.py` — 6 further tests for findings
  8 and 9.
- Mutation gate: 16 mutations, each reverting one production change. All 16
  fail a guard. Two were vacuous on the first pass and the **guards** were
  strengthened, not the mutations dropped: the title-threshold guard now runs
  the real extractor and reads `dominant_pattern` out of the profile, and the
  icon guard asserts over the rendered markdown (`run_feasibility` also names
  the helper in a local `_icon`, so the source grep passed with the literals
  restored).
- Full suites by exit code: discover 1971 passed / 68 skipped, exit 0; compete
  809 passed, exit 0.

## Docs

`docs/config_reference.md` (the new `title_patterns` block),
`docs/methodology.md` (the host-form paragraph — the `m.` alias, the fixed
point, the public-suffix guard, and the two DB columns),
`serp-compete/docs/handoff_contract.md` (the shared prefix list and the
`client_domain` check).

## Cold review (learning-qa, tier Full)

Nine findings: six medium, three low, no high. Every medium is fixed, and two
lows were fixed because the change itself introduced them. What it found:

1. **The icon fix had not reached its own goal.** `feasibility_messages.yml`
   held `icon: ❓` and `label: "⚠️ Not measured"` for one state, and `⚠️` is
   also "Moderate Feasibility"'s icon — so two states shared a glyph while one
   state had two. The summary printed the icon and the table twenty lines down
   printed the label. The config now carries one glyph per state, a guard
   asserts the label starts with the icon, and another asserts no two statuses
   share a glyph.
2. **The summary's words were still a Python literal** with a special case for
   one status. It renders `status_label(status)` now.
3. **`dominant_threshold > top_n` was accepted** and made `dominant_pattern`
   permanently `None` — which the brief and the report read as a fact about
   the SERP. Both keys now fall back to the documented defaults with a
   warning.
4. **compete mirrored the prefix list, not the rule.** Its `normalise_domain`
   kept the scheme, the path, the port and the userinfo, so `https://m.x.ca/p`
   was `x.ca` on the producer's side and the whole string on the consumer's.
   The only guard grepped the sibling repo's source for the constant, so it
   could never have caught that. Both sides are now checked against
   `tests/host_canonical_cases.json`, byte-identical in both repos the way
   `handoff_schema.json` is, with a test on each side asserting that.
5. **A ninth copy of the rule sat in `handoff_moz`'s `ImportError` fallback**,
   stripping `www.` only. Under it the client compare, the mismatch check and
   every anchor key reverted to the pre-Y1 rule with nothing able to tell
   (P45). The fallback is gone; the import either works or fails.
6. **The client-mismatch caveat existed only on stdout**, and sat behind the
   no-targets abort — which is a likely consequence of the very mismatch it
   was checking for. It now goes into the report header through
   `reporting.client_mismatch_line`, and the check runs before the abort.
7. **One side of two host compares was canonicalised and the other was not**,
   which is worse than canonicalising neither: a `known_brands` or competitor
   entry typed `www.psychologytoday.com` could no longer match any citation,
   and the count was short with nothing saying so. Both sides now go through
   `normalize_domain`, and an unreadable entry is counted in a warning (P2).
8. **The DB write path changed form with no migration.** Rows from earlier
   runs hold the raw netloc, and `visualize_volatility` pivots that column
   across runs — a competitor present throughout would have shown its
   `www.x.ca` series stopping at the change and an `x.ca` series starting, in
   a chart, reading as one competitor leaving and another arriving. Opening a
   database now runs a one-off canonicalising pass over both columns:
   idempotent, logged as "N of M hosts", and on a `domain_features` collision
   it keeps the canonical row's entity type. `docs/database.md` records it.
9. **Three documents still stated the threshold as fixed behaviour** —
   `README.md` twice and `docs/spec_v2_fields.md` — which would have become
   false the first time anyone edited the new keys (rule 13).

Also fixed, both low but both introduced by this change: the P2 warning in
`save_domain_features` printed the `""` it had just produced instead of the
value that failed, and `save_serp_result` wrote an empty host with no warning
at all; and `keyword_demand.assessment` raised `AttributeError` on a truthy
non-dict `moz` block where the two predicates it replaced returned "not
measured".

Dropped: the remaining low — new `""` returns from the host rule are more
correct but uncounted in `citation_table.build_citation_table`'s outreach
shortlist, and `test_no_module_strips_the_prefix_by_hand` matches literals
rather than walking the AST. Logged below.

The mutation gate grew from 16 to 27 mutations as the fixes landed; all 27
fail a guard. Two of the original 16 were vacuous and the **guards** were
strengthened. Final suites: discover 1979 passed / 68 skipped, exit 0;
compete 814 passed, exit 0.

## Adjacent issues found, not fixed

- `http_retry` returns two different shapes depending on the failure; its
  callers branch on both. Own chunk.
- `_fetch_all_rows` treats a short page as end-of-data.
- `run_gsc_analysis` wraps `save_demand` in a bare `except`.
- `compute_sponge_effect.MIN_BUCKET_SIZE` is a Python constant (P4).
- `url_enricher.fetch_url` and `answer_sentiment.classify_answer` have no
  timeout/retry (P5).
- The top-competitor tie-break is alphabetical.
- `get_volatility_metrics` returns NaN with no `comparability_warning`, so
  report §6 is silently empty.
- `compute_foundational_score` returns `0.0` when every sub-score is `None`.
- `citation_table.build_citation_table` keeps a row whose host is unreadable
  and `top_cited_domains` then skips it, so an unattributable citation leaves
  the outreach shortlist with no "N of M" line.
- `test_no_module_strips_the_prefix_by_hand` matches three double-quoted
  literals; `removeprefix('www.')` in single quotes, or a fresh
  `urlparse(...).netloc` copy, would pass. An AST walk would not.
- `serp_audit.py:1517` derives a host as `urlparse(url).netloc` before passing
  it to `storage`, which now canonicalises it. Harmless as it stands, and a
  tenth place the rule is written out.
