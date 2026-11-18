# D4c — the brief is checked, and what is written is whole

Review chunk D4c of `REVIEW_WORKPLAN_2026-11-04.md`: the brief, its validator
and the outputs. Seven findings were scheduled; two turned out to be already fixed.

## Reproduced before building

### D-C-06 — already fixed, not re-fixed

`serp_audit._resolve_output_names` takes one argument and always builds a fresh
timestamp; its docstring states that names in `config.yml` belong to an earlier
run and are never reused. Fixed by `0864d58` (14 Nov), after the review was
written (4 Nov), and guarded by
`test_serp_audit.py::test_audit_output_names_are_always_fresh`. The workplan row
is flipped with that commit named; no code change here.

### D-C-07 — the play-parity HARD rule cannot fire

Probe: pre-computed play `rank_play`; the brief states
`Recommended play: **Extraction play**` in Section 7.

```
issues: []            hard failures: False
```

The same statement inside the Section-2 keyword block, still as the bare label:
`issues: [] hard: False`. Only the exact configured label, parenthetical
included, is caught:

```
canonical-in-block: ["Report assigns a different play to 'family of origin
work' (Extraction play (GEO)), but ke…"]   hard: True
```

So the rule fires only on a phrasing the model does not use, in a section it
does not use.

### D-C-09 — the refresh re-classifies rows and nothing else

`refresh_analysis_outputs.py` contains no reference to `keyword_profiles`,
`extract_analysis_data_from_json`, `ai_overview_citations`, `generate_report`
or `recommended_play`. `refresh_json` writes `row["Entity_Type"]` and dumps the
file. README Step 4 says it "re-classifies URLs and rewrites reports".

### D-C-12 — `generate_insight_report.main` writes no briefs

`"Content Briefs" in main: False`, `"generate_brief" in main: False`, while
`serp_audit` writes the report *plus* `# Content Briefs` and the per-pattern
blocks into the same `.md`. Every GUI run that regenerates after feasibility,
and every documented `--out` invocation, drops them.

### D-C-13 — a keyword that produced no SERP data vanishes

Probe on the reference run with one keyword added to `analysed_keywords` and no
rows for it:

```
mentions the missing keyword: False
any N-of-M fetch line:       False
validate_extraction:         no warning about it
```

`root_keywords` derive from the overview rows, so the one check that would
notice cannot see the keyword at all.

### D-C-15 — already fixed, not re-fixed

My first probe said `run_llm_report` never reads `stop_reason`. The probe was
wrong: it searched that function's source for the literal `stop_reason`, and
the function uses the local name `reason`. `brief_llm` carries
`COMPLETE_REASONS` / `TRUNCATED_REASONS` / `REFUSED_REASONS` per dialect and
raises `ReportLLMError` on a truncation, a refusal, empty text, **and** any
reason not known to mean "finished", so nothing is written. Fixed by `c742f68`
(14 Nov), after the review was written, and guarded by
`tests/test_brief_llm_providers.py::test_g4_truncated_answer_is_a_failure`.
The workplan row is flipped with that commit named; no code change here.

### D-M-27 — the validator cannot check the numbers most likely to be wrong

`client_rank` and `avg_serp_da` appear nowhere in `brief_validation.py`. The
keyword-specific `estrangement` rule is there and is dead weight for any other
keyword set. Found while reading: `validate_extraction` is defined **twice**,
byte-identically (lines 443 and 582); the second shadows the first, so an edit
to the first has no effect.

---

## Criteria

- **D4.11** The play-parity HARD rule sees a play statement anywhere in the
  brief, attributed to the keyword it names, and matches the label with the
  parenthetical suffix optional.
- **D4.12** After an override changes a row's entity type, the refresh rebuilds
  what depends on it — `keyword_profiles`, and with them the AIO-citation
  analysis — and reports how many profiles changed. What it cannot rebuild it
  says it has not. (The citation rows themselves carry no `Entity_Type`:
  `ai_overview_citations` holds `Title`/`Link`/`Source` only, and the entity
  classification of a citation is derived inside the profiles. Rebuilding the
  profiles is therefore the whole of re-classifying the citations.)
- **D4.13** The `# Content Briefs` assembly has one home, and both the pipeline
  and `generate_insight_report --out` produce it.
- **D4.14** A keyword that produced no SERP data is named in the report with its
  N-of-M count, `validate_extraction` warns about it, and the audit's exit code
  reflects it.

  The exit code is a new `pipeline_status.EXIT_PARTIAL` (2), not `EXIT_FAILED`.
  `finish_run` renames every output `<name>.failed` and leaves `config.yml`
  alone on `EXIT_FAILED`, so returning it for one failed keyword out of N would
  discard a run whose outputs are correct for the keywords that did return.
  `EXIT_PARTIAL` keeps and records the outputs, is not `EXIT_OK` so
  `storage.mark_run_completed` does not stamp the run (a partial keyword set
  must not become the baseline a later run's rank deltas are measured
  against — the gate added for D-C-22 already tests for `EXIT_OK`), and
  `run_pipeline` continues through the remaining steps, says the run was
  partial instead of printing a clean success, and returns 2 itself. The label
  is scoped to `serp_audit.py` in `exit_label`, because
  `validate_xlsx_vs_json.py` already returns 2 to mean its comparison raised.
- **D4.16** The numerics the brief restates (`client_rank`, `avg_serp_da`,
  `gap`, `total_results`) are checked against the profile; market-size language
  requires a demand figure; the keyword-specific rule and the duplicate
  `validate_extraction` are gone.

---

## As built

### D4.11 — the play-parity rule fires where the brief writes

`brief_validation._keyword_regions(report_text, keyword)` returns every stretch
of the report attributed to one keyword: the Section-2 profile block
(`**<kw> (intent)**` up to the next block) and any markdown heading naming the
keyword, down to the next heading of the same or a higher level.
`_play_assignment_phrase` strips the label's parenthetical before matching and
makes it optional, so the configured `Extraction play (GEO)` is caught when the
brief writes `Extraction play`. `_check_play_parity(issues, keyword, profile,
regions)` runs the comparison over every region.

### D4.16 — the numbers are checked, and the validator has one definition

`brief_validation_rules.yml` (new, editorial) holds `numeric_claims` —
`client_rank`, `total_results`, `avg_serp_da`, `gap`, each with `label`,
`tolerance` and one-capture-group `patterns` — and `market_size_phrases`.
`load_validation_rules` caches it, validates the capture-group count, and warns
and degrades rather than aborting. `_check_numeric_claims` compares each claim
found in the keyword's own regions against the measured value; a field that was
not measured is skipped. `avg_serp_da` and `gap` come from the keyword's
primary `keyword_feasibility` row — `Query_Label == "P"` rows measure the pivot
keyword and are skipped.

The rank patterns are anchored on the word "client". A keyword's own section
also states competitor ranks ("havynbc.ca ranks #1"), and a bare `ranks #N`
would have read those as claims about the client. The issue message does not
contain any of `has_hard_validation_failures`' phrases, so a numeric
disagreement is SOFT — one retry against the correction prompt — which is the
right weight for a figure found by pattern match.

The market-size rule is now gated on `_any_demand_measured(keyword_profiles)`
rather than banning the wording outright: with a measured volume the sentence is
a true statement. The keyword-specific `estrangement` rule is gone from both
`validate_llm_report` and `validate_advisory_briefing`. The second,
byte-identical definition of `validate_extraction` is gone; one remains.

### D4.13 — one home for the briefs

`generate_insight_report.build_content_briefs_section(data, preferred_intents=None)`
holds the assembly. `generate_insight_report.main` appends it, and `serp_audit`
calls it in place of its own 45-line inline block. Against the reference run the
whole report diff versus HEAD is the 117 lines of this section appearing — the
`--out` re-render now produces what the pipeline does.

### D4.14 — a keyword with no SERP data

`brief_validation.missing_serp_keywords(data)` compares `analysed_keywords`
against the keywords with an overview row or a profile. Three consumers:
Section 1b prints `Keywords Analyzed: N of M` and names the excluded keywords;
`validate_extraction` warns per keyword; the audit passes them to
`pipeline_status.finish_run(..., incomplete_keywords=...)`, which returns the new
`EXIT_PARTIAL` (2). The exit-code reasoning is under Criteria above.

### D4.12 — the refresh rebuilds what it invalidates

`brief_data_extraction.build_keyword_profiles(data, config, client_domain=None)`
is the one builder; `serp_audit` and `refresh_analysis_outputs` both call it, so
a rebuild cannot be assembled from different settings than the run.
`refresh_analysis_outputs.rebuild_keyword_profiles` returns `(built, changed)`,
writes the JSON back, and on failure warns that the rows were re-classified
while the profiles still describe the previous taxonomy. `NOT_REBUILT` names the
Markdown report and `keyword_feasibility`; `main` prints both.

## Verification

- Full suite: 1891 passed, 68 skipped, 10 subtests passed, exit code 0.
- Five guards in `tests/test_d4c_the_brief_is_checked_and_whole.py`, one per
  criterion; the cold review's fixes were folded into the guard for the
  criterion they belong to rather than added as new tests. Ten mutations, each
  failing exactly its own guard and nothing else: the strict label phrase, the
  numeric tolerance test, the audit's call to the shared assembly, the
  `incomplete_keywords` branch, the profile rebuild, substring keyword
  matching, the extractor withholding `keyword_feasibility`, a run-wide demand
  gate, counting query jobs instead of keywords, and the brief assembly
  aborting the report.
- Not guarded, and said plainly: the GUI log line and message box that now
  carry the rebuild's outcome (finding 5). Driving the tkinter dialog for it
  would cost more than the line is worth; the fields it reads are returned by
  `refresh_analysis_outputs` and are guarded there.
- Reference report versus a `git stash`-based HEAD baseline on
  `output/market_analysis_couples_counselling_20261114_1554.json`: the only
  changes are the 117-line `# Content Briefs` section appearing (D4.13) and
  `Keywords Analyzed: 9` becoming `9 of 9`. No keyword is missing from that
  run, so no exclusion line appears.
- `refresh_analysis_outputs.py` run against a copy of that JSON:
  `Rebuilt keyword_profiles: 9 (changed: 9)`. The nine differ because the
  profiles on disk predate D4a/D4b — the rebuilt `recommended_play` no longer
  claims a DA gap for a keyword whose DA was never measured.
- Effort: code + config 737 added lines; tests 283 (0.38x, under the 2x
  ceiling); prose 429 (0.58x), over the 0.3x ceiling. Nothing was cut. 296 of
  those lines are this plan record, covering seven scheduled findings and the
  cold review's six — about 23 lines each — and the remaining 133 are
  `docs/methodology.md`, `docs/config_reference.md`, `README.md`,
  `docs/USER_MANUAL.md`, `docs/gui_steps.md` and `CLAUDE.md`, each of which the
  project requires to change with the behaviour it describes. Cutting to the
  ratio would mean deleting either the record of a finding or a document the
  rules make mandatory.

## Cold review (learning-qa, P1–P45) — six findings, all fixed

1. **HIGH — the widened region attribution matched keywords by substring.**
   `_keyword_regions` attributed a heading to every profile keyword contained
   in it. Real keyword files overlap (`couples counselling` and `couples
   counselling for trust issues` are in one CSV), so the longer keyword's
   section became the shorter one's, and both the play-parity rule and the D4.3
   DA-direction rule — both HARD, both fail-fast — aborted a report whose every
   statement was true. Before D4.11 the play rule read only the
   `**kw (intent)**` block, whose `(` anchor made the bleed impossible.
   Fixed: a heading is attributed to the longest profile keyword it names, and
   `_names_keyword` requires phrase boundaries rather than `in`.
2. **HIGH — half of D4.16 could not fire on a real run.**
   `extract_analysis_data_from_json` did not return `keyword_feasibility`, and
   that dict is what `validate_llm_report` is always called with, so
   `_feasibility_by_keyword` was always empty and the `avg_serp_da` and `gap`
   rules matched nothing. They passed their guard only because the guard
   hand-built the key. Fixed: the extractor returns `feasibility_rows`, the
   guard now exercises the real extractor on
   `output/market_analysis_family-of-origin-seo-phrases_20260828_1433.json`,
   and the DA patterns were widened to accept "is" / "at" as well as "of" and
   ":" — the phrasing the model actually uses ("the average SERP Domain
   Authority is 80") matched none of the original patterns.
3. **MEDIUM — the demand gate was run-wide and the volume itself unchecked.**
   One keyword with a Moz volume licensed market-size language for all of them.
   Fixed: `_check_keyword_demand` evaluates the phrases inside each keyword's
   own regions against that keyword's `moz` block, and `numeric_claims` gained
   a `volume` entry so a restated figure is checked too. The run-wide rule
   stays for demand language that sits outside any keyword's section.
4. **MEDIUM — the N-of-M line reconciled two different units, and defaulted to
   complete.** `overview` holds one row per query job, not per keyword
   (`expand_keywords_for_ai` adds `A.1`/`A.2` rows for priority keywords), so
   the line would have read "13 of 14" for a run of 8. Fixed: the numerator is
   the distinct `Source_Keyword` count and the denominator is
   `len(analysed_keywords)`. A run written before that key existed now prints a
   coverage line saying the asked-for list was never recorded, rather than
   printing a bare count that reads as complete.
5. **MEDIUM — the rebuild's failure was invisible where users work, and the
   write was not atomic.** The GUI calls `refresh_analysis_outputs` in-process
   and logged only the row counts, so a failed profile rebuild read as a clean
   refresh; and `json.dump` onto the live file truncates it first, so a
   part-way failure left a file that does not parse beside a message asserting
   the rows were fine. Fixed: `_write_json_atomically` (temp file +
   `os.replace`), the dump moved out of the rebuild's `try` so the two failures
   carry different messages, and the GUI logs `profiles_built` /
   `profiles_changed` / `profiles_error` and says the Markdown report is not
   regenerated.
6. **MEDIUM-LOW — a brief that could not render took the report with it.**
   `build_content_briefs_section` ran outside `main`'s write guard, so an
   exception wrote nothing at all where the `--out` re-render had always
   produced the report. Fixed: the assembly is wrapped and degrades to a
   "briefs could not be rendered" marker.

Three low notes were reported and dropped per the review tier; they are in the
adjacent list below.

## Adjacent issues found, not fixed

- `validate_advisory_briefing` duplicates several of `validate_llm_report`'s
  checks by copy, including the market-size rule, and received neither the
  numeric checks nor the region widening. The advisory restates the same
  figures, so the hardening is applied to one sibling only.
- `load_validation_rules` wraps the file read and the pattern-normalising loop
  in one `except Exception`, and caches the result, so a bug in that loop would
  disable every numeric and demand check for the process behind one warning —
  and "no issues" would be indistinguishable from "checks off".
- `play_routing.yml` labels one play `Deprioritise`; the HARD parity phrase is
  built from the label, so a draft writing `Deprioritize` evades the rule.
  **Fixed in chunk Y1** — the phrase is matched with `[sz]` at each `s`/`z`.
- "Is demand measured" is now implemented in four places:
  `brief_data_extraction._demand_assessment` and `_demand_too_small`, and
  `brief_validation._keyword_volume` / `_any_demand_measured`. Duplicate
  predicates must agree and nothing makes them. **Fixed in chunk Y1** — one
  `keyword_demand` module; both callers alias it.
- `refresh_analysis_outputs.refresh_xlsx` counts a row with no domain as
  `updated` while changing nothing, so its "updated" figure is not the number
  of cells it wrote.
- `refresh_json` writes the JSON, then `refresh_analysis_outputs` writes it
  again after the rebuild. Two writes where one would do.
