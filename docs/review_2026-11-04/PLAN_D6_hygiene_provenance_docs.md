# Chunk D6 — Hygiene, provenance, docs

Workplan rows: **D-C-16, D-C-17, D-M-09, D-M-10, D-M-21, D-M-22, D-M-23,
D-M-24, D-M-26**, plus the docs lag noted in the correctness review's "sound"
list (CLAUDE.md and README call a `title_patterns` contradiction SOFT; the
validator treats it as HARD).

Effort tier: **Full** — `feasibility.py`, `intent_verdict.py` and
`pattern_matching.py` are scoring code whose numbers reach every report.

---

## Reproduced before building

Each finding was re-checked against the code as it stands, because five review
chunks have landed since the review was written.

1. **D-M-09.** `compute_feasibility` returns `avg_serp_da`, `gap`, `da_count`
   and `da_missing`. There is no minimum and no entity split, so a SERP of
   `[92] + [18]*9` reports mean 25.4 / gap −9.6 / "High Feasibility" and one of
   `[85]*5 + [12]*5` reports mean 48.5 / gap +13.5 / "Moderate Feasibility",
   although five DA-12 pages demonstrably hold slots on the second SERP. The
   fact that low-DA clinics occupy half the page is the evidence of rankability
   and it is invisible. Confirmed.
2. **D-M-24.** `feasibility.py:630`:
   `score = round(max(0.0, 1.0 - gap / SCORE_NORMALISER), 2)`. No upper clamp,
   docstring says "0.0 (worst) … 1.0 (best)". A gap of −15 gives 1.5.
   Confirmed.
3. **D-M-10 / D-C-17.** `_bucket_confidence(classified_count, organic_count)`
   is counts only (≥8 high, ≥5 medium). `config.yml`
   `serp_intent.thresholds.confidence_high` / `confidence_medium` are
   validated by `config_validators.py` and editable in the GUI, and
   `grep` finds no reader: `compute_serp_intent` reads only `primary_share`,
   `fallback_share`, `fallback_runner_up_max`. So the figure rises when
   `max_urls_per_keyword` is raised, with no change in any SERP, and tuning
   either knob changes nothing. Confirmed.
4. **D-M-21.** Every threshold named in the finding is still either a code
   constant or a config value whose comment says "default" or "industry
   reference". None names a study, a calibration or a decision record, and no
   report says "editorial, uncalibrated". Confirmed.
5. **D-M-22.** `methodology.md` at the repo root is still dated 2026-05-01 and
   still says the trigger vocabularies are "effectively hardcoded … the next
   file to externalise" (`intent_classifier_triggers.yml` has existed since
   I.2) and that two generators "weren't in the upload". CLAUDE.md names
   `docs/methodology.md` as the contract, so the root file is a second,
   contradicting answer. `intent_mapping.yml:44` still says "The local pack
   contributes its own `local` count from map-pack URLs", which the code never
   does. Confirmed.
6. **D-M-23.** **Already fixed.** `glossary.yml` now reads "The average Domain
   Authority of the sites currently ranking, minus yours", which matches
   `feasibility.py` (`gap = avg_serp_da − client_da`) and the columns block.
   Closed with a guard rather than re-fixed.
7. **D-C-16.** **Already fixed** (`abcc2aa`): `test_moz_competitor.py:933`
   builds its stale anchor as `now − 5 days`. Verified, not re-fixed.
8. **D-M-26.** `strategic_patterns.yml` still lists `registered`,
   `mental health`, `treatment` (Medical Model) and `close`, `communication`
   (Fusion) — the file's own rule at its head forbids "common words that appear
   everywhere in the topic domain". `analyze_strategic_opportunities` fires on
   any whole-word hit anywhere in the joined n-gram phrases and reports up to
   five trigger names with no count and no share. Confirmed.
9. **Docs lag.** `brief_validation.py` puts a
   `contradicts keyword_profiles.title_patterns` issue in `hard_patterns` and
   lets it fall through to `blocking`. `CLAUDE.md:279` lists it under
   "SOFT-fail (1 retry)" and `README.md:273` says it soft-fails, while
   `README.md:255` says HARD. Confirmed, and the two README sentences
   contradict each other.

---

## Criteria

- **D6.1** A feasibility row reports the minimum competitor DA and the minimum
  non-directory competitor DA beside the mean, with the count the figures rest
  on. Where no entity type could be resolved the non-directory figure is
  `None`, not the overall minimum and not zero.
- **D6.2** `feasibility_score` stays inside its documented 0–1 range.
- **D6.3** What the report calls "confidence" for a SERP intent is named as
  what it is — how many of the ranking URLs were classified — and a separate
  certainty is derived from the winning intent's share and read from
  `serp_intent.thresholds.confidence_high` / `confidence_medium`, so neither
  knob is dead. No key under `serp_intent.thresholds` is without a reader.
- **D6.4** Every threshold family that decides a verdict label states where it
  came from, and the report says "editorial, uncalibrated" once rather than
  implying a derivation.
- **D6.5** One methodology document. The root reading guide is marked as a
  dated snapshot and points at the contract; `intent_mapping.yml` no longer
  claims the local pack contributes a count the code never adds.
- **D6.6** The glossary's DA-gap direction matches `feasibility.py`, with a
  guard so it cannot reverse again.
- **D6.7** A fired Bowen pattern reports how many of the corpus's pages carry
  its triggers, and each trigger's own hit count. Triggers that violate the
  file's own rule are gone. The section says it is trigger-word presence, not
  framing analysis.
- **D6.8** The `title_patterns` severity is stated the same way in the code,
  CLAUDE.md and README.

## As built

| Criterion | Where | What changed |
|---|---|---|
| D6.1 | `feasibility.py`, `feasibility_messages.yml`, `run_feasibility.py`, `serp_audit.py` | `competitor_minima()` returns `min_competitor_da`, `max_competitor_da`, `min_non_directory_da`, `non_directory_count`, `entities_known` beside the mean. `min_non_directory_da is None` means *no competitor's entity type was resolved*, never "no directory ranks here"; `entities_known` says which it is, and a competitor whose type is unknown is never counted as a non-directory page. Which types count as a directory is editorial config (`feasibility.directory_entity_types`). `DAWindow` carries the entity types it was given; `competitor_da_window` takes an `entity_for_url` callable and swallows classifier errors as `None`. `minima_cell()` / `minima_phrase()` take their words from `feasibility_messages.yml`. |
| D6.2 | `feasibility.py` | `feasibility_score` is clamped to 0.0–1.0, which `docs/feasibility.md` had always claimed. |
| D6.3 | `intent_verdict.py`, `generate_insight_report.py`, `brief_rendering.py` | `confidence` has always been classification coverage, so it is published under that name too (`classification_coverage`, same value). `intent_certainty` / `primary_intent_share` are new: the leading intent's share of the **classified** URLs, bucketed against `serp_intent.thresholds.confidence_high` / `confidence_medium` — two config keys that had no reader before this chunk. Nothing classified gives `not_measured`, not "low". Section 0 prints Coverage and Certainty in separate columns; ranking reads certainty and falls back to coverage. |
| D6.4 | `pattern_matching.py`, `serp_audit.py`, `generate_insight_report.py`, `strategic_patterns.yml` | Each fired pattern reports, per trigger word, how many of the scanned pages carry it (`Trigger_Hits`, `Pages_With_Trigger`, `Pages_Scanned`) — all `None` when the caller gave no corpus, printed as "not quantified this run". Section 4 states that it measures trigger-word presence, not framing. Four triggers that violated the file's own rule (`registered`, `mental health`, `close`, `communication`) were removed. |
| D6.5 | `thresholds_provenance.py` (new), `config.yml`, `generate_insight_report.py` | Nine threshold families each state where their numbers came from in the report's §A appendix. A family with nothing recorded prints "editorial, uncalibrated — no source or date is recorded for this one", which is the honest status of every band in the tool today. A malformed block warns and degrades; it never aborts a report. |
| D6.6 | `methodology.md`, `intent_mapping.yml`, `glossary.yml`, `docs/glossary.md` | The root reading guide carries a banner naming itself a dated snapshot, pointing at `docs/methodology.md` as the contract, and listing its known stale passages. `intent_mapping.yml`'s header no longer claims a `local` count the code never adds. The glossary states the feasibility and commodity bands are editorial. |
| D6.7 | `CLAUDE.md`, `README.md` | A `title_patterns.dominant_pattern` contradiction is a HARD failure, which is what the validator has always done; both docs said retryable. |
| D6.8 | `tests/test_moz_competitor.py` | The collection-freshness test anchors on a computed date, not a literal that expires. |

Docs updated in the same change: `docs/feasibility.md`, `docs/methodology.md`, `docs/config_reference.md`, `docs/architecture.md`, `docs/USER_MANUAL.md`, `docs/glossary.md` (regenerated), `CLAUDE.md`, `README.md`, `methodology.md`, `glossary.yml`, `config_manager.py` help text.

## Verification

- **Suite**: `python3 -m pytest test_*.py tests/ -q` → **1933 passed, 68 skipped, 10 subtests, exit 0**.
- **Guards**: 35 in `tests/test_d6_hygiene_provenance_docs.py`, one class per finding fixed.
- **Mutation check**: 42 mutations (M1–M42), one or more per criterion and one per cold-review fix. Every one fails at least one guard, and each fails guards covering its own criterion. Four were vacuous on the first pass and the guards were strengthened rather than the mutations dropped: an unknown entity counted as non-directory (no partial-classification case existed), the certainty share taken over the organic count instead of the classified count (the fixture had no uncategorised rows, so both denominators agreed), the corpus never reaching the matcher from `serp_audit.py` (no guard on that call site), and the root reading guide losing its banner (the guard matched words the shortened banner still contained).
- **Reference report**: regenerated from `output/market_analysis_leila_20260807_0954.json` before and after. The diff is 104 lines and contains only the intended changes: section 0's Confidence column split into Coverage and Certainty, "confidence" reworded to "classification coverage" wherever it meant coverage, section 4's new measurement caveat and per-pattern presence line, the commodity-score editorial caveat, and the new provenance appendix. On this archived run `intent certainty` and the trigger counts print as not measured, which is correct — the JSON predates both fields, and a field nobody recorded is not a zero.
- **Effort** (tier Full): production 821 lines changed or added (631 in tracked modules + the 190-line `thresholds_provenance.py`), plus 127 lines of editorial config; tests 574 (0.70x, ceiling 2x); explanatory prose 250 (0.30x, at the ceiling) plus this review record and the workplan rows.

## Cold review

`learning-qa`, cold, over the production diff (tier Full: this chunk changes
what the report states as measured). 11 findings — 2 high, 5 medium or
medium-high, 4 low. Nine fixed, two dropped as low with no reader affected.

**Fixed**

1. **High (P1/P6)** — a partly classified window was reported as a fully
   classified one. Both renderers branched on `entities_known` being truthy and
   then quoted every figure over `da_count`, so one classified competitor out
   of ten produced "Every one of the 10 scored competitors is a directory", and
   in the mirror case offered DA 90 — the *strongest* page on the SERP — as the
   weakest non-directory competitor "over 10 scored competitors". Partial
   classification is the normal outcome, since a non-enriched rank is
   classified domain-only and returns `N/A` for any unmatched domain. Two new
   states in `feasibility_messages.yml` (`with_non_directory_partial`,
   `all_classified_directory`) name how many types were resolved and how many
   were not; the table cell carries a `?` after the second figure.
2. **High (P2/P5)** — the standalone producer and the database dropped all five
   new fields. `serp_audit.py` splats the assessment into its row, but
   `run_feasibility.py` re-lists fields and `storage.save_feasibility_from_row`
   re-lists columns, so in that path every measured minimum rendered as "—",
   which the new table header documents as "no competitor was scored", and the
   §5c sentence never printed. This is finding F9 from review chunk D2
   recurring in the same file whose docstring describes it.
   `feasibility.MINIMA_FIELDS` now names the set once, both rows copy it, and
   five migrated columns persist it.
3. **Medium-high (P4/P6)** — the provenance appendix hardcoded in Python the
   threshold figures it exists to account for. Tune `commodity.bands` and the
   section explaining where the numbers came from would print the old ones.
   The labels now name the config keys and the lines print their live values,
   read from the config the report was generated with; a key this config does
   not set says the code default applies, and the title-pattern threshold is
   stated as the code constant it still is.
4. **Medium (P1/P2)** — `Pages_Scanned` / `Pages_With_Trigger` were not pages.
   The corpus is `collect_snippet_texts` — snippets, ad copy, related searches,
   autocomplete, several entries per result — so the denominator was inflated
   by non-pages and the share systematically understated, while the report, the
   methodology doc and CLAUDE.md all called it a page count. Renamed
   `Snippets_Scanned` / `Snippets_With_Trigger`, and every sentence now says
   "SERP text blocks".
5. **Medium (P1)** — the fire test and the count used different haystacks.
   Triggers fired against the n-gram phrases, which have stop words and short
   words stripped; the counts ran over the raw text. So "reach out" could be
   listed as detected and counted 0 in the same line. Both now run over the
   same text.
6. **Medium (P7)** — the new ranking key rewarded thin coverage. Certainty is
   the leading intent's share of the *classified* URLs, so one classified URL
   scores 1.0 and outranked a well-covered 6/4 split. `_intent_rank_word` now
   reads certainty only where the coverage behind it is medium or better.
7. **Medium** — `primary_intent_share` was not the primary intent's share: it
   is computed even when the verdict is `mixed` or withheld for too little
   classification, and the cell printed it beside the intent word. Renamed
   `leading_intent_share`, and the cell says "leading intent".
8. **Low-medium (P2)** — a classifier raising on every URL was silent, so every
   SERP would read "directory split not measured" with nothing saying why. The
   failures are counted and the first is named in a warning.
9. **Low-medium (P4)** — the §5c sentence always named the default
   `directory`, even where `feasibility.directory_entity_types` was widened.
   The report now passes the resolved list it computed with.

**Adjacent issues found, not fixed** (rule 10)

- `feasibility.competitor_minima` strips `None` DAs before zipping them with
  the entity list. No current caller can hit it — `DAWindow` never appends a
  `None` DA — but a future caller with a sparse list would get entity types
  attached to the wrong competitors. Low; zip-then-filter is the fix.
- The `feasibility_score` clamp changes the meaning of a persisted column:
  pre-D6 rows hold values above 1.0 and new rows saturate at 1.0, so a
  run-over-run comparison of that column mixes two scales with nothing marking
  where it changed. Low; the clamp itself is right.
- `title_patterns.DOMINANT_THRESHOLD` is still a Python constant while every
  other threshold family it sits beside is config. The provenance line now says
  so rather than hiding it. **Fixed in chunk Y1** — `title_patterns.top_n` /
  `dominant_threshold` are config keys and the provenance line names them.
