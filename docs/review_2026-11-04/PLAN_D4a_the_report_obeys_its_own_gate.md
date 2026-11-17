# Chunk D4a — the report obeys its own gate

**Chunk:** D4 (Report and brief logic), first of three pushes.
**Findings:** D-M-06 (High), D-M-07 (High), D-C-14 (S2), D-C-18 (S3).
**Probes:** `probes/discover/probe_08_evidence_block_dead.py`,
`probes/discover_method/p07_feasibility_intent_rank_edges.py`.

## The common fault

The report states a conclusion the same report contradicts a few lines later.
Not a data fault this time — the data is right in each case — a **render and
routing** fault: the headline recommendation ignores the gate the action
column applies, a strategy line asserts a measurement whose own note says it
is unavailable, an evidence block reads keys its producer never writes, and a
section prints the word `unknown` for two values the metric never returns.

Each one is a claim stated more confidently than the thing behind it.

## Why D4 is three pushes, not two

The workplan calls D4 L and suggests two pushes (report logic / brief +
validator). Fifteen findings across eight modules is too wide for one review
pass, so the report-logic half is split by what the fix touches:

- **D4a (this)** — the report's own claims: the best-opportunity pick, the
  play strategy text, the pattern evidence block, the volatility keys.
- **D4b** — metric semantics: mixed-intent strategy (D-M-11), "market too
  small" (D-M-12), commodity homogeneity (D-M-13), the hyper-local pivot
  gate and its text (D-M-19).
- **D4c** — brief, validator and outputs: D-C-06, D-C-07, D-C-09, D-C-12,
  D-C-13, D-C-15, D-M-27.

## Reproduced before building

Run on `599a744`, against `tests/fixtures/market_analysis_reference_run.json`:

- `p07` — `_get_best_opportunity_keyword` picks **kwA**, "navigational
  intent, high feasibility", while the action column for that same keyword
  prints **⛔ Mismatched intent**; kwB (informational, a preferred intent,
  Moderate feasibility) is passed over. The single thing the report tells the
  reader to do first is the one keyword it also tells them not to pursue.
- `p07` — `compute_recommended_play` with `feasibility: unknown` renders
  "Ranking is unlikely (**high DA gap**) but AI-Overview citation is
  winnable", with `note: feasibility/DA data unavailable`. The strategy
  asserts the measurement its own note says was never taken.
- `probe_08` — the RC.4.1 "Why this pattern fired" block reads
  `org_result["title"]` and `["domain"]`; `serp_audit` writes `Title`,
  `Link` and `Source`. `render with producer keys: False`, `same data with
  lower-case keys: True`. The block has never rendered on real data.
- `metrics.get_volatility_metrics` returns no `keywords_current` /
  `keywords_previous`, so §6 prints "This run: unknown / Previous run:
  unknown" for exactly the runs where the sentence promises the two lists.

## Acceptance criteria

- **D4.1** `_get_best_opportunity_keyword` applies the same mandatory intent
  gate as `_get_keyword_action`: a keyword whose SERP intent is not one the
  client serves is never named the best opportunity. When no keyword passes
  both gates the section says so, naming which gate stopped it, instead of
  recommending one that fails its own action test.
- **D4.2** No play's strategy text asserts a DA gap, or any other
  feasibility-derived direction, when `data_available["feasibility"]` is
  false. The alternative wording is editorial and lives in `play_routing.yml`
  (`strategy_text_unknown_feasibility`), never in Python; a play without the
  variant falls back to its normal text, so a missing key cannot abort a
  report.
- **D4.3** `brief_validation` fails a brief that states a DA-gap direction
  for a keyword whose `recommended_play.data_available.feasibility` is false.
- **D4.4** The RC.4.1 evidence block reads the producer's own keys (`Title`,
  and the domain from `Link`), and a test plants a trigger word in a `Title`
  rather than asserting the block's absence.
- **D4.5** `metrics.get_volatility_metrics` returns `keywords_current` and
  `keywords_previous` as sorted lists; §6 renders them, and never prints
  `unknown` for a value the metric does return.

---

## As built (2026-11-17)

| Criterion | Where | Guard |
|---|---|---|
| D4.1 best opportunity passes the intent gate | `generate_insight_report.py::_get_best_opportunity_keyword` | `tests/test_d4a_report_obeys_its_gate.py::TestTheBestOpportunityPassesTheIntentGate` |
| D4.2 no play claims a gap nothing measured | `play_routing.py::compute_recommended_play`, `play_routing.yml` `strategy_text_unknown_feasibility` | `TestNoPlayClaimsAGapNothingMeasured` |
| D4.3 the validator catches the claim coming back | `brief_validation.py`, `play_routing.yml` `validation.da_gap_claim_phrases` | `TestTheValidatorCatchesTheClaimComingBack` |
| D4.4 the evidence block reads the producer's keys | `generate_insight_report.py` RC.4.1 block | `TestTheEvidenceBlockReadsTheProducersKeys` + the four rewritten `tests/test_report_clarity.py::TestRC4PatternEvidence` tests |
| D4.5 volatility returns the keys the report prints | `metrics.py::get_volatility_metrics`, `generate_insight_report.py::_render_volatility_keyword_sets` | `TestVolatilityReturnsTheKeysTheReportPrints` |

### The tests that let D-C-14 survive

Four of the five RC.4 tests asserted only `"## 4." in report` or
`"**" in section4`. They passed whatever keys the evidence block read, which is
why a block that never rendered on real data stayed green from RC.4 until now.
They are replaced with tests that plant trigger words in a row's `Title` — the
key the producer writes — and assert the block, the quoted title, the
normalised domain, the three-title cap and the omission when no title matches.

### Verification

- Suite: **1868 passed, 68 skipped, 10 subtests, exit 0**.
- Effort (tier Full): 181 lines of code + config; tests 295 (1.62x, under the
  2x ceiling); prose 50 (0.27x, under 0.3x) excluding this record. Guard count
  is 12 new plus 4 rewritten against 4 findings, above the one-guard-per-finding
  ceiling for a fix batch: each finding has a fix branch and a
  did-not-over-reach branch, and the 4 RC.4 tests replace vacuous ones rather
  than adding to them. Kept because every one is mutation-verified below.
- Every guard was mutation-checked: reverting each of the
  five fixes in turn fails the guard for that criterion and no other.
- Reference run regenerates **byte-identical** (0 diff lines). That is honest,
  not a null fix: no title in `tests/fixtures/market_analysis_reference_run.json`
  contains any of that run's three trigger words (`clinical`, `registered`,
  `free`), the run's best-opportunity keyword already passed both gates, and
  its plays all had measured feasibility. The probes below exercise the paths
  the fixture does not.
- `p07` probe: best opportunity is now `kwB` (informational, moderate) with
  `kwA` still marked ⛔ Mismatched intent; the unknown-feasibility extraction
  play renders "No Domain Authority data was obtained…" in place of "Ranking
  is unlikely (high DA gap)".
- `probe_08`: the evidence block renders with producer keys and prints
  `psychologytoday.com` from `Link`.

### Adjacent issues found, not fixed (rule 10)

- `metrics.get_volatility_metrics` can return a NaN `volatility_score` with no
  `comparability_warning` when the keyword sets match but no URL overlaps, so
  Section 6 renders neither branch and the section is silently empty. Logged
  for D6.
- `_rank_keywords` still sorts feasibility first. The gate above makes the
  report correct, but the ordering within the eligible set remains
  feasibility-dominant; `docs/USER_MANUAL.md` describes that as intended.

---

## Cold review (learning-qa, P1–P45)

10 findings: 1 high, 4 medium, 5 low. Every medium-or-higher is fixed, plus
the three cheap lows. Finding 10 is dropped: a HARD-fail regex can match
inside a negation ("we cannot say *ranking is unlikely* without DA data"), but
no project message literal collides today, so it is residual risk — recorded
here, not guarded.

| # | Sev | What it was | Fix |
|---|---|---|---|
| 1 | High | `serp_audit.py` writes `"Link": … or "N/A"`, so `normalize_domain("N/A")` returned `"n"` — truthy, making the `Source` fallback dead code for exactly the rows it was written for | `_evidence_domain` treats the producer's sentinels as absent before normalising |
| 2 | Med | `_get_most_relevant_keyword` scores triggers over Title + Snippet; the evidence block searched `Title` only, so a pattern selected on snippet text still rendered no evidence, silently | `_collect_pattern_evidence` searches both, marks which carried the hit, and says so when nothing is quotable |
| 3 | Med | The action column's intent gate read `if intent and not intent_matches`, so a keyword with no verdict printed ✅ Pursue below a Section 0 saying no keyword passes the intent gate — a new instance of the contradiction this chunk removes | New `❓ Intent unknown` action, documented in `report_clarity_spec.md` and `README.md` |
| 4 | Med | `deprioritize` is the catch-all and so reachable on `feasibility: unknown`, asserting an absence over a signal nobody read; only two of the three claimants got a variant (P5) | `strategy_text_unknown_feasibility` for `deprioritize`: hold, do not deprioritise |
| 5 | Med | `load_play_vocab`'s bare `except Exception` now governs a HARD validation rule; an empty phrase list is a rule that never fires, cached for the process, logging nothing | Both the loader and `brief_validation` log when the list is empty or the file failed |
| 6 | Med-low | The YAML comment promised case-insensitive matching; `re.search` was called without `re.IGNORECASE`, so the first `"High DA Gap"` entry would never match | Patterns compiled once at load with `re.IGNORECASE`; a malformed one is reported at load |
| 7 | Low | `strategy_text_unknown_feasibility` had no type validation, so a YAML slip reached the brief as a Python repr | Validated as a non-empty string in `load_play_routing` |
| 8 | Low | `rp.get("data_available", {})` raises on a present-but-null key | `(rp.get("data_available") or {})` |
| 9 | Low-med | A guard asserted the YAML had `strategy_text` rather than exercising the fallback branch; no case used the `"N/A"` the producer writes, or a snippet-only trigger | That guard replaced; three data cases added |

### What the fixes changed in real output

The reference run now differs from the pre-D4a report by **16 lines, all
additions**: the Section-4 evidence block renders for both patterns, quoting
four competitor snippets with correctly resolved domains
(`susangamache.com`, `newtides.ca`, `lotuscounselling.com`,
`movingforward.help`). Finding 2 was the reason the D4.4 fix alone left the
reference run byte-identical — every trigger in that run is in a snippet, not
a title. Suite after the review fixes: **1873 passed, 68 skipped, exit 0**.
