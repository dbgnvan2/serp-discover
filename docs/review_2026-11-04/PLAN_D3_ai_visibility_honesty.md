# Chunk D3 — AI-visibility honesty

Findings: **D-C-05 / D-M-03** (S1), **D-C-11** (S2), **D-M-18**, **D-M-14**,
**D-M-04**, **D-M-25**. Source: `REVIEW_WORKPLAN_2026-11-04.md`, chunk D3.

The common fault: an engine that was never asked, a call that failed, and a
page that does not exist all arrive downstream as a measured zero. The AI
Visibility Index then ranks the engine the tool could not reach as the best
opportunity, and the report states it.

Two pushes: **D3a** the engine-level honesty (D-C-05/D-M-03, D-C-11),
**D3b** the four narrower findings (D-M-18, D-M-14, D-M-04, D-M-25).

## Reproduced before building (the workplan requires it)

Run 2026-11-17, all five listed probes exit 0 and show the fault:

- `probes/discover/probe_06_aivi_skipped_engine.py` — `openai` answered no
  questions. It is persisted as `('openai', 0.0, 0.0)` in
  `ai_visibility_index`, enters `all_engine_avg` (50.0, dragging gemini's
  100 down by half) and is ranked **first** in the prioritisation.
- `probes/discover/probe_10_empty_answer_counted_as_not_mentioned.py` — a
  blocked Gemini call returns `{"answer_text": "", "source_urls": []}` and is
  recorded as `{'mentioned': False, 'cited': False}`: a failure stored as a
  measured absence.
- `probes/discover_method/p05_gazetteer.py` — the gazetteer's 40 entries
  include `Indeed`, `LinkedIn`, `Job Bank`, `Pathways` and `Government of
  British Columbia`; "Indeed" matches the sample answer and takes a
  leaderboard rank beside a real competitor. Two brands tie at rank 1 and the
  tie is broken alphabetically.
- `probes/discover_method/p06_aivi_skipped_engine.py` — the same AIVI row
  reaches the rendered report, and `rank_divergence.ranks` carries `null` for
  the two engines that were not measured.
- `probes/discover_method/p08_profile_questions.py` — 27 generated questions
  across three personas truncate to 20, and all 20 are `prospective_client`:
  `clinician_trainee` and `referrer` are dropped whole.

Two findings had no probe; both reproduce (recorded here, probes to be added
as `probe_13` / `probe_14`):

- **D-M-04** — `foundational_score.compute_structure` scores **66.67** for a
  client with no page in any enriched top-10. The score is computed from
  `schema_signals.schema_type_counts`, which counts every top-10 page, so the
  client's "foundational structure readiness" is its competitors' markup.
- **D-M-25** — three rate-limited sentiment calls produce three stored
  `neutral` rows and a Sentiment axis of **0.0**: "no answer says anything
  positive about the client", when nothing was classified at all.

## Acceptance criteria

### D-C-05 / D-M-03 — an engine that was not asked has no score (D3a)

- **D3.1** `run_report_enrichment` computes and persists per-engine metrics
  only for engines that produced at least one answered row. An engine with
  zero answers gets **no** `ai_visibility_index` row, no leaderboard row and
  no citation row.
- **D3.2** Such an engine is excluded from `all_engine_average`, which states
  its own n ("average over 2 of 4 engines"). The report names each unmeasured
  engine and why ("skipped — no API key", "0 of 20 answered").
- **D3.3** `engine_transfer.compute_transfer` is given only measured engines,
  and reports `measurable: False` with a reason when fewer than two remain.
  `jaccard` returns `None` for two empty sets rather than 1.0; pairs with no
  citations on either side are excluded from `avg_jaccard`, which states the
  number of pairs it averaged.
- **D3.4** `engine_recommendations.prioritize_engines` excludes an engine with
  no AIVI instead of scoring it maximum opportunity, and returns it in a
  separate `not_measured` list the report prints.

### D-C-11 — a failed call is not an absence (D3a)

- **D3.5** `run_engine_probes` no longer drops a raised call. It records the
  row with `status: "failed"` and the error, and writes **no** mention/cite
  verdict for it.
- **D3.6** An empty `answer_text` with no source URLs is a failed call, not
  `mentioned=False`. `detect_visibility` is not asked for a verdict on it.
- **D3.7** Per engine the run stores `questions_planned`, `answered` and
  `failed`; the report renders "answered N of M (K failed)" and every rate is
  computed over `answered`, never over `planned`.

### D-M-18 — the per-engine cap does not drop whole personas (D3b)

- **D3.8** City variants of one question are de-duplicated before the cap
  applies, and the truncation samples round-robin across personas so every
  persona that generated a question is asked at least one.
- **D3.9** The plan line prints "N of M generated questions asked" and names
  any persona that still ended with none.

### D-M-14 — the gazetteer and the ranking axis (D3b)

- **D3.10** `build_gazetteer` drops a harvested source that is a single
  generic token. The stop list is editorial and lives in `config.yml`
  (`ai_visibility.generic_source_stoplist`), never in Python; a harvested
  source otherwise needs two or more tokens or a domain match.
- **D3.11** `build_leaderboard` uses competition ranking — equal mention
  counts share a rank — and the leaderboard carries `tied_with` so the report
  can say "tied with 3 others" instead of implying a winner.
- **D3.12** `detect_visibility` takes `negative_terms` (editorial, in
  `config.yml ai_visibility.negative_terms`, e.g. "living systems theory") and
  matches client patterns on a word boundary, as `gsc_demand.is_branded`
  already does.

### D-M-04 — the structure score is the client's own (D3b)

- **D3.13** `_build_schema_signals` carries the client's own row as
  `client_page` (as `extractability` already does).
  `foundational_score.compute_structure` reads only that and returns `None`
  when the client is in no enriched top-10. `docs/USER_MANUAL.md:1331-1334` is
  corrected to say whose markup the sub-score measures.

### D-M-25 — a failed classification is not neutral (D3b)

- **D3.14** A failed or unparseable classification stores `polarity: None`
  with `status: "failed"`, is excluded from `percent_positive` and the
  Sentiment axis, and the report prints "n classified of m attempted". The
  axis is `None` — not measured — when nothing was classified.

## Editorial content moved to config (CLAUDE.md)

`ai_visibility.generic_source_stoplist` and `ai_visibility.negative_terms` are
word lists a non-developer will want to edit, so they go in `config.yml` beside
`known_brands`, and are documented in `docs/config_reference.md`.

## Adjacent issues found, not fixed

- `_brand_domain_map` (`probe_ai_visibility.py:880`) strips `www.` by hand
  instead of calling `domain_utils.normalize_domain`; `_domain_from_url`
  (`:623`) does the same. Both are correct today, but they are two more copies
  of the definition D2c consolidated. Flagged for D6 hygiene.
- `answer_sentiment.classify_answer` has no timeout/retry of its own; it
  inherits whatever `brief_llm.run_llm_report` does. Worth checking against
  P5 in D6 rather than widening this chunk.
- The top-competitor pick (`probe_ai_visibility.py:983`) is
  `max(sorted(combined), key=…)`, an alphabetical tie-break like D-M-14's.
  Same class of fault, outside D3's findings.

## Verification

- The five existing probes flip: each asserts the fixed behaviour after
  printing the fault. Two new probes (`probe_13` foundational structure,
  `probe_14` sentiment failure) for the findings that had none.
- `tests/test_d3_ai_visibility_honesty.py`: an engine with no rows writes no
  AIVI row; half the questions raising carries the failure count; an empty
  answer produces no `mentioned=0` row; the gazetteer excludes "Indeed"; a
  four-way tie gives a shared rank; the structure score is `None` when the
  client is absent; a failed sentiment call leaves the axis `None`.
- Full suite by exit code (discover and serp-compete, each in its own venv).
- The reference-run report regenerated and diffed; every changed number
  explained by the chunk.
- Docs in the same push: `docs/methodology.md`, `docs/USER_MANUAL.md`,
  `docs/config_reference.md`, `glossary.yml` if a term changes, and the
  workplan index.

## As built — D3a (D3.1-D3.7)

All seven D3a criteria are met. Decisions worth recording:

- **A failed call is a row, not a gap.** `status` / `failure_reason` columns
  arrive by the same idempotent `ALTER TABLE` migration as `persona` /
  `source`. A pre-D3a row carries no status and reads as answered, which is
  what it was — those rows were only ever written on a successful call.
  `mentioned` / `cited` are NULL on a failed row, not 0; `_verdict()` in
  `save_probe_rows` is what keeps the 0 out.
- **The trend keeps a run where everything failed**, with `answered` 0 and no
  rate, rather than dropping it from history (P2). It gains `attempted` and
  `failed` beside `questions`, and the rates are over `questions` (answered).
- **The AIVI trend still covers every enabled engine**, not just the measured
  ones, so a gap in an engine's history reads as a gap rather than as the
  engine never having existed.
- **`jaccard` now returns `None` for two empty sets.** Only a pair where
  *neither* side cited anything is incomparable — "a cited x.ca, c cited
  nothing" is a real overlap of zero, and the guard test pins that
  distinction. `avg_jaccard` is `None` when no pair is comparable and states
  `pairs_compared` otherwise.
- **`prioritize_engines` skips an engine with no AIVI** rather than scoring it
  1.0 opportunity. The engines it could not rank come back from the new
  `unmeasured_engines()` and are rendered under "Not ranked — not measured".
  Returning them inside the same list would have meant sorting on `None`.
- Three existing tests encoded the old behaviour and were updated, not
  deleted: `test_engine_transfer.py::test_both_empty_is_one` →
  `test_both_empty_is_not_measurable`;
  `test_engine_recommendations.py::test_missing_aivi_is_max_opportunity` →
  `test_missing_aivi_is_not_ranked`; and one `prioritize_engines(..., {})`
  call in `TestEnabledOnly` now passes an AIVI, since an engine with none is
  no longer ranked.

## Cold review of the D3a diff — findings fixed

A cold `learning-qa` pass over `probe_ai_visibility.py` / `engine_transfer.py`
/ `engine_recommendations.py` returned 6 findings, 2 high. Its verdict: the
data layer of D3a was sound, the render layer had not caught up with it —
F1, F2 and F3 were all the same class D3a set out to close (a negative stated
about something that was never measured), surviving in the rendered report.
All six are fixed, each with a guard in
`tests/test_d3_ai_visibility_honesty.py::TestTheRenderedReportSaysWhatWasNotMeasured`.

| # | Finding | Fix |
|---|---------|-----|
| F1 (high, P2/P9) | `all_engine_avg_n` / `engines_measured` / `engines_unmeasured` were added to the returned dict but had **no production consumer** — `render_aivi_section` still took the old three arguments, so a mean over 1 of 2 engines printed identically to a mean over 2 and the unmeasured engine was absent from the section | `aivi.render_aivi_section` takes `engines_measured` / `engines_enabled` / `engines_unmeasured`; prints "over N of M enabled engine(s)" and names each unmeasured engine with its reason |
| F2 (high, P1/P6) | `_enrichment_sections` receives the full engine list while leaderboards/citations are built only for measured engines, so an unmeasured engine fell to the renderers' empty branch: "No brands were named in this engine's answers this run" — false for an engine whose every call returned 429 | `_not_measured_block` renders "not measured — <reason>. No answers were returned this run, so no brand could be named in them." A *measured* engine with no brands still reports that honestly |
| F3 (med-high, P1) | `compute_transfer` gated on `len(engines) < 2` over the **measured** list and returned "single engine", rendered as "Enable at least two engines" — telling the user to change configuration when 3 of 4 engines had been rate-limited, the opposite of the action required | `compute_transfer(..., engines_enabled=, engines_unmeasured=)` separates one engine *enabled* (enable another) from one engine *measured* ("only 1 of 4 enabled engines returned an answer … re-run") |
| F4 (medium, P4 / CLAUDE.md editorial rule) | one state ("no measurement") was rendered four ways across three modules at first write — the same drift `feasibility_messages.yml` and `gsc_messages.yml` already exist to stop | new `ai_visibility_messages.yml` + `ai_visibility_messages.py` loader (the `gsc_client` pattern), read by all four renderers; documented in `docs/config_reference.md` and listed in `CLAUDE.md` |
| F5 (low-med, P9) | `planned` fell back to the cross-engine row total and was stored as *every* engine's plan (2 engines × 5 questions → `planned: 10` each) | `engine_call_counts(questions_planned=None)` sets `planned: None`; a denominator nobody measured is not presented as one |
| F6 (low, P2) | `get_engine_trend`'s numerator `SUM(COALESCE(mentioned, 0))` had no status filter while the denominator did, so an answered row with a NULL verdict would be summed as a measured False | both verdict sums are now `CASE WHEN <col> THEN 1 ELSE 0 END`, over the same rows as the denominator |

Also applied from the review's readability note: the local `unmeasured_engines`
list in `run_report_enrichment` is renamed `unmeasured`, so it no longer
collides by name with `engine_recommendations.unmeasured_engines`.

Carried forward, not fixed here (the review's own cross-repo observation): the
AI-visibility export carries no failed/attempted count, so `serp-compete`
cannot tell a 5-question run from one where only 3 were answered. Logged for
the compete-side chunk rather than widened into this diff.

## As built — D3b (D3.8–D3.14)

| # | Criterion | Where |
|---|-----------|-------|
| D3.8 | The caps take a persona-fair slice | `profile_questions.interleave_by_persona` (new); applied in `probe_ai_visibility.build_question_set`'s profile loop and again before the `max_total_calls` slice in `main` |
| D3.9 | The plan line prints "Asking N of M generated questions" and names any persona left with none | `probe_ai_visibility.main` |
| D3.10 | A harvested source needs two tokens or its own domain; the stop list is editorial | `brand_mentions.build_gazetteer(generic_source_stoplist=)`, `config.yml ai_visibility.generic_source_stoplist` |
| D3.11 | Competition ranking; `tied_with` per row, `client_tied_with` beside `client_rank`; the report says "tied with N — not ahead of them" | `brand_mentions.build_leaderboard`, `render_leaderboard_section` |
| D3.12 | Word-boundary client matching + editorial `negative_terms` | `probe_ai_visibility.detect_visibility(negative_terms=)`, threaded through `run_engine_probes`; `config.yml ai_visibility.negative_terms` |
| D3.13 | The structure sub-score is the client's own markup, `None` when it has no enriched page | `brief_data_extraction._build_schema_signals(client_domain_lower)` carries `client_page`; `foundational_score.compute_structure` reads only it |
| D3.14 | A failed classification carries no polarity, is excluded from every percentage and from the axis, and the report says "n classified of m attempted" | `answer_sentiment`: `STATUS_CLASSIFIED`/`STATUS_FAILED`, `_failed_classification`, `classified_rows`, `percent_positive`, `render_sentiment_section`, `render_negative_sentiment_alert`, `save_sentiment` + migration |

On D3.8's "city variants de-duplicated before the cap applies": no new pass
was needed and none was added. `generate` already de-duplicates by
`(question, persona)` and `build_question_set._add` de-duplicates by
lower-cased query across every source, so a template without a `{city}`
placeholder expanded per city collapses to one question. Checked on the
shipped `living_systems` profile: 27 generated, 27 distinct, 27 after
`build_question_set`. City variants that differ by city name are different
questions, not duplicates.

Probes: `probe_13_structure_score_is_not_the_clients.py` and
`probe_14_failed_sentiment_is_neutral.py` are new (the two findings that had
none) and both now assert the fixed behaviour; `p05_gazetteer.py` and
`p08_profile_questions.py` were print-only and now assert. All four exit 0.

Tests: `tests/test_d3b_narrower_honesty.py` (24 tests, 6 classes).

Two existing tests encoded the old behaviour and were corrected, not deleted:

- `tests/test_brand_mentions.py::TestRankingAndClientRank::test_client_rank_and_ties`
  → `test_a_tie_shares_a_rank_and_says_so`. It asserted `client_rank == 3` for a
  client tied with one rival on one mention each — the alphabetical listing
  order was the rank.
- `tests/test_answer_sentiment.py::TestClassificationAndPercent::test_polarity_buckets`
  asserted an unrecognised polarity label fell back to "neutral". That fallback
  is finding D-M-25.

Six `tests/test_foundational_score.py` fixtures carried `schema_type_counts`
with no `client_page`, which is now "the client has no measured page" — each
fixture gained the client's own page carrying the types the test intends.

### Cold review of the D3b diff — 10 findings, 8 medium-or-higher, all fixed

The review's verdict: the chunk hardened one matcher and one tie-break and left
their siblings alone, so the leaderboard, authority and sentiment axes still
carried the bugs the diff described as fixed. Fixes, in the review's numbering:

| # | Sev | Fault | Fix |
|---|-----|-------|-----|
| 1 | HIGH | the single-token gazetteer rule compared the harvested name against `host.split(".")[0]`, so `ca.indeed.com` → `ca` and every one-word brand on a subdomained host was dropped — shrinking the competitor field in the client's favour, and contradicting its own docstring and config comment | `brand_mentions._domain_labels` tests every label of the host (public-suffix and hosting labels excluded); dropped counts logged (P2) |
| 2 | HIGH | `detect_visibility` got the word boundary and the negative terms; `gazetteer_pass` and `answer_sentiment.answer_mentions_brand` — the same patterns against the same answers — got neither, so the false positive still reached the client's rank, the authority sub-score and a paid sentiment call (P5) | new `brand_match.matches_patterns`, the one matcher all three call; `negative_terms` threaded through `build_leaderboard` and `collect_sentiment` |
| 3 | MED-HIGH | `ai_visibility_export._read_answer_sentiment` had no status filter, so a NULL polarity reached serp-compete against a schema requiring a string | the export selects classified rows only (a pre-D3b DB has no `status` column; every row in it was classified) |
| 4 | MED | an exhausted sentiment budget returned early recording nothing, so the report printed "no answer this run portrayed this brand" over answers that did (P1 — a spent budget is retryable) | each unasked (answer, brand) pair is recorded with `STATUS_SKIPPED_BUDGET` and no polarity; the section says the budget ran out |
| 5 | MED | the negative-terms veto was applied to the whole answer, so one paragraph about the subject erased a real mention in the next | the veto is per match span, not per document |
| 6 | MED | `compute_structure` returned a bare `None` for two different unmeasured states and dropped its gaps, so the client least visible in the SERPs got no structure advice at all; and the sub-score's definition change printed as a readiness Δ | returns `(score, gaps, reason)` with the reason rendered; recommendation gaps kept when unmeasured; `DEFINITION_VERSION` stored per run and Δ suppressed across the boundary |
| 7 | MED | `client_ranking_axis` still scored a shared rank 1 as 100, next to prose saying "not ahead of them" | takes `client_tied_with`; a tie scores the mid-point of the places the tied brands occupy |
| 8 | MED | `max(sorted(combined), ...)` picked the top competitor — the benchmark that buys sentiment calls — by alphabetical order on a tie | the tie is resolved explicitly, logged, and named in the Sentiment section |

Findings 9 and 10 were LOW (an unlogged malformed-profile skip; two mixed
populations in the plan line's denominator) and were dropped per the effort
budget. Finding 8 is the adjacent item this chunk had flagged for D6 — the
review raised it as a finding, so it was fixed here rather than deferred.

Adjacent, flagged not fixed (rule 10): `compute_foundational_score` sets
`score = 0.0` when all three sub-scores are `None`, which is "nothing was
measured" rendering as 0/100 — the exact pattern this chunk exists to remove,
and `structure = None` is now more frequent, so the all-`None` path is more
reachable. `render_foundational_section` would also raise `TypeError` if
`score` were ever `None`. Outside D3's findings; flagged for D6.
