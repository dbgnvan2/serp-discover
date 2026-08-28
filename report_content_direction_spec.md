# Report Content Direction — spec + implementation plan (v1)

**Status:** implemented 2026-08-28. All CD.1-CD.6 criteria done; see
`docs/spec_coverage.md` rows CD.1.1-CD.6.3 and the status report below.
**Date:** 2026-08-28
**Prefix:** `CD` (Content Direction)

## Problem

`market_analysis_*.md` reads as an analyst's data dump. Two concrete complaints from
the 2026-08-26 `family_of_origin_work` run:

1. **Undefined jargon.** "Dominant SERP Features: Local Map Pack, Standard Organic"
   means nothing to the reader. Neither do PAA, AIO, DA gap, extraction play,
   commodity score, SERP homogeneity, or backdoor strategy. None is defined anywhere
   in the report.
2. **Data without direction.** Sections 2 and 3 present questions and phrases but
   never say what to *do* with them when writing a page.
3. **Section 3 emits broken phrases.** `get_ngrams` (`pattern_matching.py:62`) strips
   stop words *before* joining words into n-grams, so "family of origin" renders as
   `family origin` and "The Family Institute at Greater Vancouver" yields the
   non-phrase `family greater`. On a 2-keyword run the list is the search term
   restated nine ways — it does not deliver the "Medical Model vs. Systemic"
   narrative analysis its heading promises.

## Goal

Reframe the report around **"here is the content you should create"**, with each
analytical section stating how its data should shape the writing, and every piece of
jargon defined in the report itself.

## Decisions taken (user, 2026-08-28)

- **Option unit:** one content option per analysed keyword, ranked. No padding to a
  fixed count — a 2-keyword run yields 2 options.
- **Existing sections:** kept in place, each gaining a writing directive. No
  restructure of sections 2–6, so the RC.1–RC.6 suite and `docs/methodology.md`
  stay valid.

## Scope

**In:** `market_analysis_*.md` (the markdown report from `generate_insight_report.py`).
**Out:** the `.xlsx` workbook, the `.docx` exports, and `generate_content_brief.py`'s
separate per-keyword briefs. The xlsx carries the same undefined jargon in its column
headers; deferred by the user to a later plan (2026-08-28).

---

## Acceptance criteria

### CD.1 — "What To Write" content plan section

The report gains `## 1. What To Write` immediately after the Executive Summary.
Current `## 1. Market Overview` becomes `## 1b. Market Overview`, following the
report's existing `5b/5c/5d` suffix convention. Sections 2–6 keep their numbers.

One `### Option N — <keyword>` block per analysed keyword, ordered by the **existing**
`_rank_keywords()` helper (`generate_insight_report.py:101`) so the plan's order can
never contradict the Executive Summary's "best opportunity" claim.

Each option block carries, all derived from data already in the JSON:

| Field | Source |
|---|---|
| Page type | recommended play + primary intent (local → service page; informational → guide) |
| Why this one | feasibility status + DA gap + AIO exposure |
| Target search | the keyword |
| What the page must do | play's `strategy_text` from `play_routing.yml` |
| Questions to use as headings | PAA questions filtered to that keyword |
| Terms to use | CD.3 display phrases + Bowen reframe vocabulary |
| Success looks like | play's success metric from `play_routing.yml` |

| ID | Criterion | Test |
|---|---|---|
| CD.1.1 | `## 1. What To Write` renders, positioned after §0 and before §1b | `tests/test_report_content_direction.py::test_cd1_1_content_plan_section_placement` |
| CD.1.2 | Exactly one option block per analysed keyword — exact count, not a floor | `::test_cd1_2_exact_one_option_per_keyword` |
| CD.1.3 | Option order matches `_rank_keywords()`; Option 1's keyword == Exec Summary's best keyword | `::test_cd1_3_option_order_matches_exec_summary` |
| CD.1.4 | Each option renders all seven fields | `::test_cd1_4_option_carries_all_fields` |
| CD.1.5 | Fewer than 3 keywords produces fewer than 3 options with no invented filler | `::test_cd1_5_no_padding_below_three` |
| CD.1.6 | A keyword with no PAA data renders an honest "no questions captured" line, not an empty heading | `::test_cd1_6_missing_paa_stated_not_blank` |

**CD.1.3 is the highest-regression-risk criterion and gets its test written first**
(P10): two independent rankings in one report that disagree would be worse than the
current state.

### CD.2 — Writing directives on existing sections

Each analytical section gains a short directive telling the reader how the data
shapes the writing. Directive text is editorial and lives in a new
**`report_writing_directives.yml`**, never in Python (project rule: editorial content
in config files).

| Section | Directive substance |
|---|---|
| §2 Anxiety Loop | make each question an H2; answer it in the first 2–3 sentences under that heading |
| §3 Status Quo | terms to use for topical match; framings to avoid |
| §4 Strategic Recs | use the content angle as the page's opening hook |
| §5 SERP Composition | what the competitor mix means for page format |
| §5c Feasibility | rank target vs. citation target — what changes in the writing |
| §5e Commodity | how hard this page must work to not be replaceable by one AI paragraph |

| ID | Criterion | Test |
|---|---|---|
| CD.2.1 | Every section in the table above renders its directive | `::test_cd2_1_directive_present_each_section` |
| CD.2.2 | Directive text is read from YAML — editing the YAML changes the output (behavioural, not a source grep) | `::test_cd2_2_directive_text_sourced_from_yaml` |
| CD.2.3 | A missing/malformed YAML file degrades to the section rendering without a directive, never an exception that aborts the report | `::test_cd2_3_missing_yaml_degrades_safely` |

### CD.3 — Readable phrases in §3

New `get_display_phrases()` in `pattern_matching.py`. **`get_ngrams` is left
unchanged** — it feeds `analyze_strategic_opportunities()`
(`pattern_matching.py:186`), which word-boundary-matches Bowen triggers over the
joined phrase string, and the word-cloud. Changing a function with three consumers to
fix one consumer's display is how P12/P22 regressions happen.

`get_display_phrases()`:
- keeps stop words *inside* a phrase (`family of origin` stays intact), trimming only
  phrases that start or end on a stop word
- suppresses phrases that are the analysed keyword or a sub-span of it
- when fewer than 3 distinct phrases survive, emits an honest "not enough distinct
  competitor language at this keyword count" line rather than padding the list

`serp_audit.py` writes the result to a new JSON key `serp_display_phrases`, alongside
the untouched `serp_language_patterns`.

| ID | Criterion | Test |
|---|---|---|
| CD.3.1 | Internal stop words preserved: "family of origin work" yields `family of origin`, never `family origin` | `::test_cd3_1_internal_stopwords_preserved` |
| CD.3.2 | Phrases spanning a deleted connector are not emitted: "Family Institute at Greater Vancouver" never yields `family greater` | `::test_cd3_2_no_cross_connector_phrases` |
| CD.3.3 | Keyword-echo phrases suppressed against the analysed keyword list | `::test_cd3_3_keyword_echo_suppressed` |
| CD.3.4 | Thin input renders the honest message, and §3 contains no phrase list | `::test_cd3_4_thin_input_states_insufficient_data` |
| CD.3.5 | **Regression guard:** `get_ngrams` output and `analyze_strategic_opportunities` trigger detection are byte-identical to today on a real fixture | `::test_cd3_5_get_ngrams_and_triggers_unchanged` |
| CD.3.6 | `serp_display_phrases` present in the JSON and consumed by §3 | `::test_cd3_6_display_phrases_wired_to_report` |

CD.3.5 uses the real `market_analysis_family_of_origin_work_20260826_2004.json` as
its fixture, not a synthetic one (P19: verify against a real artifact).

### CD.4 — Glossary

New `## A. Glossary` appendix at report end. Terms live in a new **`glossary.yml`**
(editorial content in config). Initial term list:

SERP · SERP feature · Local Map Pack · Standard Organic · PAA (People Also Ask) ·
AI Overview / AIO · Domain Authority (DA) · DA gap · organic position · CTR ·
search intent (informational / local / transactional / mixed) · rank play ·
extraction play · GEO · commodity score · SERP homogeneity · answer similarity ·
entity dominance · title pattern · backdoor strategy · FAQPage markup · volatility ·
cited-share · CTR loss

**Only terms that actually appear in the rendered report are defined**, so the
glossary never explains a concept absent from this run.

| ID | Criterion | Test |
|---|---|---|
| CD.4.1 | `## A. Glossary` renders at report end | `::test_cd4_1_glossary_section_present` |
| CD.4.2 | Every glossary term appearing in the report body has a definition | `::test_cd4_2_every_rendered_term_defined` |
| CD.4.3 | Terms absent from the report body are omitted from the glossary | `::test_cd4_3_absent_terms_omitted` |
| CD.4.4 | Definitions are read from `glossary.yml` (behavioural: edit YAML → output changes) | `::test_cd4_4_definitions_sourced_from_yaml` |

### CD.5 — Jargon guard

A standing test that fails when a new undefined abbreviation or term of art enters
the report. Asserts **exact membership** of a known-term set, not a count floor
(P29): a jargon term found in the report body that is neither in `glossary.yml` nor
on an explicit allowlist fails the test.

| ID | Criterion | Test |
|---|---|---|
| CD.5.1 | Report body contains no jargon term lacking a glossary entry | `tests/test_report_content_direction.py::test_cd5_1_no_undefined_jargon` |
| CD.5.2 | The guard's term set is exact-membership, and fails if `glossary.yml` loses an entry still used in the body | `::test_cd5_2_guard_catches_removed_definition` |

### CD.6 — Honest section-1 and section-3 labelling

Approved 2026-08-28 from the "adjacent issues" list (items 1, 2, 4). Item 3, the
xlsx headers, is deferred to a later plan.

**CD.6.1 — §1b feature list stops claiming dominance.** Today
`generate_insight_report.py:478` unions `SERP_Features` across every keyword and
labels the result "Dominant SERP Features". The union does not weight by frequency,
so "dominant" is unearned at any keyword count. Replaced with a per-feature count of
how many keywords showed it: `Local Map Pack — 1 of 2 keywords`.

**CD.6.2 — "Standard Organic" stops posing as a feature.** It is the fallback string
for "none of the seven detected features present" (`serp_audit.py:859`). In the
report it renders as a plain-English null result, not as a named feature in a list.

**CD.6.3 — §3's heading stops promising analysis it does not perform.** "The dominant
narrative in the market (Medical Model vs. Systemic)" describes §4's job. §3 is
retitled to what it delivers — the wording competitors actually use — and points to
§4 for the narrative contrast.

| ID | Criterion | Test |
|---|---|---|
| CD.6.1 | §1b renders per-feature keyword counts; the string "Dominant SERP Features" is absent | `::test_cd6_1_feature_counts_not_dominance_claim` |
| CD.6.2 | With no features on any keyword, §1b states the null result in plain English and never lists "Standard Organic" as a feature | `::test_cd6_2_standard_organic_rendered_as_null_result` |
| CD.6.3 | §3 heading and intro describe a term list; the "Medical Model vs. Systemic" promise appears only where §4 delivers it | `::test_cd6_3_section3_heading_matches_content` |

---

## Not code-testable — flagged

**"Is the report actually clearer to a non-expert reader?"** cannot be asserted in a
test. CD.5 is the closest code-testable proxy (no undefined jargon survives), but it
cannot judge whether a definition is *understandable* or whether the content options
are useful.

**Proposed human review:** after implementation I re-render the report from the
existing `market_analysis_family_of_origin_work_20260826_2004.json` — no API spend —
and you read the output. Sign-off on readability is yours, not a test's.

---

## Implementation order

| # | Step | Depends on | Risk |
|---|---|---|---|
| 1 | This spec doc, committed | — | — |
| 2 | `glossary.yml` + `report_writing_directives.yml` (editorial only, no code) | 1 | none |
| 3 | CD.1.3 test written first (ranking agreement), against current code — expected red | 1 | none |
| 4 | CD.3 `get_display_phrases` + CD.3.1–3.6 incl. the unchanged-`get_ngrams` guard | 2 | low — isolated new function |
| 5 | CD.4 glossary rendering + CD.5 jargon guard | 2 | low — additive appendix |
| 6 | CD.1 content plan section + section renumber to `1b` | 3, 4 | **highest** — new section, renumber |
| 7 | CD.2 directives + CD.6 honest labelling | 2, 6 | low |
| 8 | Docs: `USER_MANUAL.md`, `methodology.md`, `CLAUDE.md` editorial list, `docs/spec_coverage.md` | 6, 7 | — |
| 9 | Re-render report from existing JSON; human readability review | 8 | — |

## Files touched

**New:** `report_content_direction_spec.md` (this file) · `glossary.yml` ·
`report_writing_directives.yml` · `tests/test_report_content_direction.py`

**Modified:** `generate_insight_report.py` (new sections, directives, glossary) ·
`pattern_matching.py` (add `get_display_phrases`; `get_ngrams` untouched) ·
`serp_audit.py` (populate `serp_display_phrases`) · `docs/USER_MANUAL.md` ·
`docs/methodology.md` · `CLAUDE.md` (editorial-content list) · `docs/spec_coverage.md`

## Test discipline

- Every new test is **mutation-checked** (P27): delete or invert the line it names,
  run it, confirm red, restore — using the verbatim original line, not a paraphrase.
- CD.1.2 and CD.5 assert **exact counts / exact membership**, never `> N` (P29).
- CD.3.5 uses a **real on-disk artifact** as fixture (P19).
- CD.2.3 covers the malformed-config path so a bad YAML cannot abort the report.
- Full suite must stay green; success judged on **pytest exit code**, not a grep of
  the summary line (P24).

## Adjacent issues found, not fixed

Per the "old code is not someone else's problem" rule — flagged, not silently swept:

1. **§1 "Dominant SERP Features" is a set-union across all keywords**
   (`generate_insight_report.py:478`), rendered as if it described one page. On the
   2-keyword run it reads `Local Map Pack, Standard Organic`, which is really "one
   keyword had a map pack, the other had nothing". "Dominant" is unearned at any
   keyword count, since the union does not weight by frequency.
2. **"Standard Organic" is a null result rendered as a feature name**
   (`serp_audit.py:859`). It means "none of the seven detected features present".
3. **The xlsx workbook carries the same undefined jargon** in its column headers.
   Deferred by the user to a later plan (2026-08-28) — not addressed here.
4. **§3's heading promises analysis it does not perform.** "The dominant narrative in
   the market (Medical Model vs. Systemic)" describes what §4 actually does. Even
   with CD.3's phrase fix, §3 delivers a term list, not a narrative contrast.

**Resolution (2026-08-28):** items 1, 2 and 4 approved and folded in as **CD.6**.
Item 3 (xlsx headers) deferred to a later plan.
