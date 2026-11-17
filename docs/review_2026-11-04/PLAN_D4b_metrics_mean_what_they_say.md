# D4b — the metrics mean what they say

*Chunk D4b of `REVIEW_WORKPLAN_2026-11-04.md`. D4 was split three ways: D4a
(report claims, pushed as `0ce79e7`), **D4b** (metric semantics, this plan),
D4c (brief + validator + outputs).*

**Findings:** D-M-11, D-M-12, D-M-13, D-M-19 — four numbers or labels whose
name does not describe what they are computed from.

---

## Reproduced before building

### D-M-11 — `mixed_intent_strategy`

`brief_data_extraction.py:_compute_strategic_flags` picks `compete_on_dominant`
when the dominant intent is in `client_intent_presence` — the set of intents
the client **already ranks for**. Two consequences, both reproduced:

```
informational 6 / local 4, preferred=[informational, local],
client ranks nowhere                                  -> backdoor
same, but the client already ranks for informational  -> compete_on_dominant
```

The docstring defines `backdoor` as "dominant intent is uncompetable, but a
non-dominant intent appears in `client.preferred_intents`". Here the dominant
intent is the one the client serves, and it is called a backdoor. A client with
no rankings yet — the case this tool exists for — can never get
`compete_on_dominant`, because the set is empty.

Ties are resolved by `max()` over a dict, so by insertion order, which is SERP
row order:

```
insertion order ('local', 'informational') -> dominant=local,          strategy=backdoor
insertion order ('informational', 'local') -> dominant=informational,  strategy=avoid
```

The same 5/5 SERP gets two different strategies depending on which result
Google returned first.

### D-M-12 — "market too small"

```
total_results=    0: action=skip   | Only 0 total results. Market too small…
total_results=  199: action=skip   | Only 199 total results. Market too small…
total_results=  200: action=enter  | 200 total results. …
```

Two faults. `total_results` is Google's *result-count estimate* for the query —
it measures how many pages exist, not how many people search, so it is not a
demand figure and "market too small" does not follow from it. And
`_safe_int(r.get("Total_Results"), 0)` makes a missing estimate a zero, so a
keyword whose count Google did not return is told its market is too small —
the D3 fault class (unmeasured read as a measured low).

### D-M-13 — commodity homogeneity and entity concentration

```
10 titles, pattern_counts={'other': 10}  -> serp_homogeneity 1.0 ("perfectly uniform")
                                            dominant_pattern None
```

`title_patterns.build` excludes `other` when choosing `dominant_pattern` but
keeps it in `pattern_counts`, and `serp_homogeneity` takes `max()` over those
counts. A SERP where **no** title matched any shape scores as maximally
homogeneous. Same class again: nothing measured, rendered as the top of the
scale.

Entity concentration has a different problem — its denominator is not a SERP:

```
reference run, 'family of origin work': n=21 entity-typed rows
  ranks present: [1,1,1,2,2,2,…,10,10]
```

`entity_by_kw` sums every organic row carrying that `Source_Keyword`, with no
de-duplication by rank, so a "top entity-type share" is computed over 21–29
rows for a ten-result page, while the intent verdict for the same keyword is
computed over the label-A top-10. Two shares of the same SERP that cannot both
be shares of it.

### D-M-19 — the pivot gate and its explanation

```
pivot text for a Low Feasibility keyword:
"The city-wide market for 'North Vancouver' is currently dominated by
 high-authority directories (Avg DA: 70)…"
```

The sentence is printed whatever the SERP holds — `generate_hyper_local_pivot`
never reads `entity_distribution`. A page of ten low-authority clinics with a
Low Feasibility verdict is reported as directory-dominated.

The gate is `is_service_like`, a token-list guess from the keyword string
(`query_variants.is_service_like`). The run has already classified the SERP's
intent from the results themselves; the gate ignores that verdict.

---

## Criteria

- **D4.6** `mixed_intent_strategy` is defined against `client.preferred_intents`
  (what the client *can* serve), with the client's existing presence used only
  to break what remains. `compete_on_dominant` requires the dominant intent to
  be preferred; `backdoor` requires it **not** to be. A tie in
  `intent_distribution` is reported as a tie, not resolved by dict order.
- **D4.7** No "market too small" conclusion is drawn from `total_results`. A
  missing result-count estimate is distinguishable from a measured zero and
  yields no demand conclusion. Where a demand figure exists (`moz.volume`), it
  is the one that may carry such a conclusion.
- **D4.8** `serp_homogeneity` excludes `other` from the dominant-shape
  candidates while keeping every title in the denominator, and returns `None`
  (not 1.0) when no title matched any shape, so the composite does not score an
  unmeasured SERP as uniform. Corrected during the build: `compute_commodity`
  does **not** renormalise an unmeasured sub-score — it floors it to 0.0 and
  keeps it in the denominator, the module's existing P7 treatment of
  `answer_similarity`. The `None` is kept on the row and sets `low_confidence`.
- **D4.9** Entity concentration is computed over the same row set as the intent
  verdict — label-A, one row per rank — and the row count travels with it.
- **D4.10** The pivot gate reads the measured `serp_intent.primary_intent`, and
  the pivot explanation states what the SERP's `entity_distribution` actually
  shows, or omits the clause.

---

## As built

| Criterion | Where | Guard |
|---|---|---|
| D4.6 | `brief_data_extraction._compute_strategic_flags` — dominant intents computed from non-zero shares, `sorted()` so a tie is order-independent; strategy chosen against `client.preferred_intents`; new profile fields `mixed_intent_dominant`, `mixed_intent_dominant_tied`, `mixed_intent_lead` | `TestMixedIntentIsDefinedByWhatTheClientServes` ×2 |
| D4.7 | new `brief_data_extraction._demand_too_small` (Moz volume vs `moz.keyword_metrics.min_volume_for_investment`, default 20); `total_results_measured` map recorded beside the int count; config key threaded through `serp_audit.py` and `brief_rendering.py` | `TestOnlyADemandFigureConcludesAboutDemand` ×2 |
| D4.8 | `commodity_score.serp_homogeneity` → `float | None`; `_NON_SHAPE_PATTERNS = ("other",)` excluded from the numerator, kept in the denominator; `None` floored to 0.0 in `subscores` and kept on the row; `low_conf` now includes `hom is None` | `TestUnclassifiedIsNotUniform` ×2 |
| D4.9 | entity counting scoped to `label == "A"`; `entity_distribution_rows` + `entity_distribution_rank_repeats` recorded; WARNING logged when repeats > 0 (P2) | `TestEntityShareIsAShareOfOneSerp` ×2 |
| D4.10 | new `feasibility._pivot_gate` (mixed_components → primary_intent → the token guess, returning `gate_source`) and `_market_composition_clause`; `run_feasibility.py` gates **both** branches on the verdict and passes `serp_intent` + `entity_distribution` | `TestThePivotReadsWhatWasMeasured` ×2 |

Every guard mutation-verified: eight separate reverts of the production code,
each failing at least one guard, the clean tree passing all ten.

**Effort (tier Full).** Code+config 310 lines changed. Tests 10 guards /
201 lines + 93 lines of correction to two existing files — 0.95x, under the
2x line ceiling; 10 guards against a fix-batch ceiling of one per finding (4).
13 guards were written and cut: what remains is two per criterion because each
criterion has two independently revertible mechanisms (the decision and its
tie-break; the new threshold and the removal of the old one; the numerator
exclusion and the floor; the row scoping and the repeat count; the gate and the
clause). Prose 63 lines — 0.20x.

**Two existing tests encoded the faults** and were corrected, not deleted:
`test_generate_content_brief.py::test_mixed_intent_strategy_compete_on_dominant`
asked for "compete" from a client with `preferred_intents=[]` and used a 0.5/0.5
distribution, so it was asserting the dict-order tie-break; two
`tests/test_commodity_score.py` cases asserted `no signal → 0.0`, and its
fixtures passed `pattern_counts` bare rather than under the key the code reads,
so the shape term was never exercised at all.

**Reference-run effect.** 6 lines differ from the D4a baseline:
`serp_homogeneity` 0.83→0.65 and 0.78→0.57, `commodity_score` 55.5→49.7 and
53.2→45.9. Both bands unchanged at `medium`.

### Adjacent issues found, not fixed (rule 10)

Logged for D6; none is in this change's blast radius.

1. `brief_validation._mixed_keyword_dominance_profiles` sorts the entity
   distribution `reverse=True`, so a tie at the top picks `top_entity` by dict
   order — the same class as D-M-11.
2. `compute_foundational_score` returns `score = 0.0` when all three sub-scores
   are `None`, and `render_foundational_section` would raise `TypeError` if the
   score were `None` — so the honest value cannot be returned yet.
3. `_brand_domain_map` / `_domain_from_url` hand-strip `www.` instead of calling
   `domain_utils.normalize_domain`.
4. `answer_sentiment.classify_answer` has no timeout/retry of its own (P5).
5. `get_volatility_metrics` yields a NaN `volatility_score` with no
   `comparability_warning` when the keyword sets match but no URLs overlap, so
   report §6 renders neither branch.
6. `serp_audit.py`'s in-pipeline pivot pass (~line 1605) runs before
   `keyword_profiles` is built (~1931), so that call still falls back to the
   token guess. `gate_source` records which gate decided. The rows the report
   uses come from `run_feasibility`, which passes both inputs.

### Cold review (learning-qa, pre-push)

7 findings — 3 high, 3 medium, 1 medium-low. All 7 fixed.

| # | Finding | Fix |
|---|---|---|
| 1 | `render_commodity_section` formatted the now-nullable `serp_homogeneity` unguarded, so `float(None)` raised inside `_safe_section` and **one** keyword with nothing to measure dropped the whole 5e table for every keyword. Reproduced. | `"—"` like `answer_similarity`, caveat updated, guard `TestANullSubScoreDoesNotDestroyTheSection` (mutation-verified) |
| 2 | The pivot refusal read `"No pivot — informational"` whatever decided it, so a SERP measured `commercial_investigation` or `navigational` was reported as informational — the fault class this chunk exists to remove. And `PIVOTABLE_INTENTS` was editorial content in Python. | `_refused_intent_phrase` names the intent and the basis; `NO_PIVOT_PREFIX` + `is_no_pivot` so the three consumers test the prefix, not one phrasing; the list moved to `config.yml feasibility.pivotable_intents` with `resolve_pivotable_intents` (default + warning), threaded into both pivot call sites (P5) |
| 3 | Label scoping is a **no-op on this project's real data** — all 9 snapshots are 100% label A. The real inflation is duplicate ranks inside label A; the change only warned about it. Measured. | Identical results (same rank, same link) counted once with the drop recorded; a rank held by two different results sets `entity_distribution_single_serp: False`; the share is no longer called a top-10 share anywhere. The guard now uses label `P`, which the pipeline actually writes, and covers both cases |
| 4 | `serp_audit` passes the volume floor but fetches no Moz metrics, so the demand rule was silently inert there and `opportunity_scale` could carry `enter` for a keyword the brief path calls `skip`, with no field distinguishing "measured and adequate" from "never assessed". | `_demand_assessment` returns (too_small, basis); `opportunity_scale` carries `demand_assessed` + `demand_basis` |
| 5 | `gate_source` was computed, documented as "so the caller can record it", and discarded; the unmeasured branch had no such key at all. | Both branches carry it; the row carries `pivot_gate_source` |
| 6 | `total_results_measured` was `is not None`, so `""` / `"N/A"` / `"unknown"` counted as measured while `_safe_int` turned them into 0 — "0 total results" could still print as a fact. | Derived from whether the int parse succeeded |
| 7 | The new tie fields reached JSON and nothing else, so a reader told to "compete on the dominant intent" was not told which one; `glossary.yml`'s "backdoor strategy" still used the old less-served-side framing. | §Mixed-Intent note names the lead and says when two tied; glossary entry rewritten against `client.preferred_intents` |

Two further existing tests encoded finding 2's fault (`test_feasibility.py::test_b1b…`,
`test_run_feasibility.py::test_b1c…`): both pass no SERP intent, so the refusal
is a keyword-text judgement, and they asserted it was called "informational".
Corrected to assert the basis is named.

Final: suite 1886 passed / 68 skipped / exit 0, `serp-compete` 952 passed.
11 guards. Code+config lines after the review fixes are reported in the commit.
