# Specification: Report Clarity and Decisiveness

**Spec ID prefix:** RC  
**Date:** 2026-05-05  
**Status:** Draft — awaiting implementation

---

## Purpose of this document

The current `generate_insight_report.py` output is descriptive but not
decisive. A user reading the report cannot answer the two questions that
motivated the run: *which keyword should I act on first, and what exactly
should I produce?* This spec closes that gap.

Problems identified from inspection of `market_analysis_leila_20260504_2020.md`
and `generate_insight_report.py`:

1. **No priority ranking.** All keywords are presented equally. There is no
   statement of which keyword represents the best opportunity.

2. **Section 5c (Feasibility) is absent.** The feasibility table is the
   primary mechanism for ranking keywords by attainability, but it did not
   appear in the output because DA data was not fetched. The report renders
   silently without it rather than explaining why.

3. **"Total Search Volume (Proxy)" is misleading.** The figure is Google's
   estimated result count (`num_results`), not a search volume metric. It has
   no predictive value and should not be presented as a volume proxy.

4. **Section 2 (Anxiety Loop) is not prioritised.** PAA questions are
   rendered as a flat list when some are more directly relevant to the client's
   offering than others. Categories are computed but underused.

5. **Strategic recommendations (Section 4) are pattern-matched templates.**
   Each recommendation block fires from trigger word presence, then outputs
   pre-written boilerplate regardless of which specific keyword and which
   specific competitors triggered it. The reader cannot tell what is data-driven
   and what is editorial template.

6. **Content briefs are not ranked or sequenced.** Four briefs are emitted
   without any statement of which to write first or why.

7. **Section 6 (Volatility) renders a meaningless result without flagging it.**
   When the current run uses a different keyword set than the previous run, the
   volatility score is `nan` and the comparison is noted in a warning but the
   section header still implies useful data exists.

8. **Section 5 entity/content dominance has no actionable interpretation.**
   The percentages are presented without telling the reader what they mean for
   strategy.

---

## Design principles

These supplement and do not replace the design principles in
`serp_tools_upgrade_spec_v2.md`.

**RC-P1. Every section must answer a question.** Each section in the report
must open with a single sentence stating what question it answers and what the
reader should do with the answer.

**RC-P2. The report's first output must be its most important output.**
The first substantive section after the metadata header must be a ranked
action list. All descriptive sections follow.

**RC-P3. Absent data must be named, not silently omitted.** If a section
cannot be populated (feasibility data missing, volatility not comparable),
the section still appears with a one-line explanation of why it is empty and
what the reader must do to populate it.

**RC-P4. Template content must be distinguished from data-derived content.**
Wherever a fixed editorial string (a Bowen reframe, a content angle) is
emitted, the output must make visible what data caused it to fire (which
keyword, which trigger words, which competitor titles). A reader should be
able to verify the recommendation by tracing it back to the raw SERP data.

**RC-P5. Improvements are additive.** Existing JSON schema keys are not
removed. New keys are added alongside. All existing tests continue to pass.

---

## Spec items

Each item is a self-contained unit of work. Items within a section have no
ordering dependency unless stated.

---

### RC.1 — Executive Summary section (new Section 0)

**Problem addressed:** Issues 1, 6.

**Required change:**

Add a new section at the top of the report (before Section 1), rendered as
`## 0. Executive Summary`, containing:

**RC.1.1 — Best opportunity statement.**

A single sentence in the format:

> **Best keyword opportunity:** `<keyword>` — `<one-sentence reason>`.

The keyword selected is the one with the best combined score across:
- Feasibility status (High > Moderate > Low; null = unranked)
- SERP intent alignment with `client.preferred_intents` (matched = preferred)
- Confidence level of the intent verdict (high > medium > low)

Tie-breaking: alphabetical. This is deterministic Python logic, not LLM
inference.

When feasibility data is absent for all keywords, the statement reads:

> **Best keyword opportunity:** cannot be determined — feasibility data is
> missing. Run with DA credentials to enable ranking. See Section 5c.

When feasibility data is absent for some but not all keywords, only keywords
with feasibility data are eligible for the best opportunity statement. Keywords
without DA data are noted as unranked.

**RC.1.2 — Content brief priority.**

A sentence in the format:

> **Write first:** `<content angle from best-matching brief>` (`<pattern name>`).

The brief selected is the one whose `most_relevant_keyword` (computed by the
existing `_get_most_relevant_keyword` logic) matches the best opportunity
keyword from RC.1.1. When no brief maps to the best keyword, the first brief
in the list is used and the fallback is stated explicitly.

**RC.1.3 — Keyword action table.**

A compact table listing all keywords with their key metrics side by side:

| Keyword | Intent | Confidence | Feasibility | Action |
|---------|--------|------------|-------------|--------|
| ...     | ...    | ...        | ...         | ...    |

The `Action` column values are drawn from a fixed vocabulary:
- `✅ Pursue` — High Feasibility, intent matches `preferred_intents`
- `⚠️ Pursue with effort` — Moderate Feasibility, intent matches
- `🔴 Pivot or skip` — Low Feasibility
- `📊 Unranked` — Feasibility data absent
- `⛔ Mismatched intent` — intent does not appear in `preferred_intents`
  regardless of feasibility

The table appears in the order: Pursue → Pursue with effort → Unranked →
Pivot or skip → Mismatched intent. Within each group, alphabetical.

**Acceptance criteria:**

- `## 0. Executive Summary` appears before `## 1. Market Overview` in all
  rendered reports.
- When all keywords have High Feasibility and informational intent, the best
  opportunity statement names a keyword and does not read "cannot be
  determined."
- When all feasibility data is absent, the statement reads "cannot be
  determined" and contains "See Section 5c."
- The action table contains exactly one row per keyword in `keyword_profiles`.
- `Action` column values are restricted to the five vocabulary items above.
- Unit tests in `tests/test_report_clarity.py::test_rc1_executive_summary_*`
  cover: all data present, all feasibility absent, mixed (some keywords have
  DA data and some do not), mismatched intent.

---

### RC.2 — Fix misleading "Total Search Volume (Proxy)" label

**Problem addressed:** Issue 3.

**Required change:**

In `generate_insight_report.py::generate_report`, Section 1, replace the
`Total Search Volume (Proxy)` label and its value with:

> **Keywords analyzed:** `<n>` | **SERP result count (not search volume):**
> `<total_results:,>`

Add a footnote line immediately after:

> *Result count is Google's estimated index size for these queries, not a
> search frequency metric. It cannot be used to compare keyword popularity.*

Alternatively, if the value adds no information that is not already present
in Section 5b, remove the result count entirely and replace with:

> **Keywords analyzed:** `<n>`

The decision between the two options is left to the implementer. Either
satisfies this criterion provided the old label `Total Search Volume (Proxy)`
no longer appears anywhere in the rendered output.

**Acceptance criteria:**

- The string `Total Search Volume (Proxy)` does not appear in any rendered
  `.md` output.
- `tests/test_report_clarity.py::test_rc2_no_misleading_volume_label` asserts
  the string is absent.

---

### RC.3 — Section 2 PAA: categorised output with question-to-offer mapping

**Problem addressed:** Issue 4.

**Required change:**

**RC.3.1** — The section opening line changes from the current generic
description to a statement of what the reader should do:

> *These are the questions your audience is already asking. Use them as
> headings, FAQ items, or opening hooks in content targeting these keywords.*

**RC.3.2** — When PAA categories are present (Distress, Reactivity,
Commercial), the existing category subsections (`🚨 High Distress Signals`,
`🔥 Reactivity & Blame`, `💰 Resource/Cost Anxiety`) are rendered as now.
No change to categorisation logic.

**RC.3.3** — When no categories are present (the fallback flat list), instead
of rendering all questions without context, render:

> *No category signals detected. Questions are listed by frequency across
> keywords.*

Then list questions deduplicated and ordered by the number of distinct
keywords they appeared under (descending). This requires counting
`Source_Keyword` values per question in the PAA data — deterministic Python,
no LLM.

**RC.3.4** — After the question list, add a short block:

> **Most common question:** `<top PAA question>`  
> **Appears for:** `<comma-separated list of keywords it appeared under>`

This makes the connection between PAA data and specific keywords explicit.

**Acceptance criteria:**

- The phrase `"frantically searching for"` no longer appears in the output
  (it is editorialising about user emotional state without data support).
- When PAA data has no categories, questions are ordered by keyword frequency
  not insertion order.
- The "Most common question" block appears in Section 2 when ≥1 PAA question
  exists.
- `tests/test_report_clarity.py::test_rc3_paa_*` covers: categorised PAA,
  uncategorised PAA, empty PAA.

---

### RC.4 — Section 4: make pattern triggers and competitor evidence visible

**Problem addressed:** Issue 5.

**Required change:**

Each `### 🌉 <Pattern Name>` block in Section 4 currently shows the trigger
words that fired in a single line (`*Triggers found: ...*`). This is
insufficient because it does not show:

- Which specific keyword the trigger appeared in.
- Which competitor titles contained the trigger.

**RC.4.1 — Trigger evidence block.**

After the existing `*Triggers found:*` line, add a collapsible evidence block
(rendered as a Markdown blockquote since collapsible HTML is not reliable in
all renderers):

```
> **Why this pattern fired:**
> Trigger word(s) `<triggers>` appeared in SERP results for
> **`<most_relevant_keyword>`**:
> - *"<competitor title containing trigger>"* — `<domain>`
> - *"<competitor title containing trigger>"* — `<domain>`
```

Cap at 3 competitor title examples. If fewer than 1 title example can be
found, omit the evidence block rather than rendering an empty one.

The competitor titles and domains are already in `organic_results` in the JSON
payload. No new data fetch is required.

**RC.4.2 — Template vs. data language.**

The `Status Quo`, `The Reframe`, and `Content Angle` fields are editorial
templates from `strategic_patterns.yml`. Label them as such with a subtle
prefix so the reader knows these are pre-written, not LLM-generated from their
specific SERP data:

```
- **Status Quo (template):** You are sick/broken...
- **Bowen Reframe (template):** Shift from pathology...
- **Content Angle (template):** *Why turning relationship problems...*
```

This is a label change only — no changes to `strategic_patterns.yml` or the
logic that selects patterns.

**Acceptance criteria:**

- Every pattern block with `Detected_Triggers` present includes a `> **Why
  this pattern fired:**` blockquote.
- The blockquote contains at least 1 competitor title and domain.
- When no organic results contain the trigger text, the blockquote is omitted
  (not rendered empty).
- The labels `Status Quo (template):` and `Bowen Reframe (template):` and
  `Content Angle (template):` appear in the rendered output.
- `tests/test_report_clarity.py::test_rc4_pattern_evidence_block_*` covers:
  triggers present with matching organic results, triggers present with no
  matching organic results.

---

### RC.5 — Section 5c: always render, explain absence

**Problem addressed:** Issue 2.

**Required change:**

Section 5c (`## 5c. Keyword Feasibility & Pivot Recommendations`) is currently
guarded by `if feasibility_rows:` — it renders only when DA data is present.

Change to: **always render Section 5c.** When `feasibility_rows` is empty or
absent, render:

```markdown
## 5c. Keyword Feasibility & Pivot Recommendations

**⚠️ Feasibility data unavailable for this run.**

Domain Authority scoring requires at least one of:
- `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` in `.env` (pay-per-use, primary)
- `MOZ_TOKEN` in `.env` (free tier, 50 rows/month)

Without DA data, keyword ranking is based on intent alignment only (see
Section 0). Re-run with credentials to enable full feasibility scoring.
```

When partial data is present (some keywords have DA data, some do not), the
table renders with `—` in the `Client DA`, `Avg Comp DA`, and `Gap` columns
for keywords with missing data, and `📊 No DA data` in the `Status` column.

**Acceptance criteria:**

- `## 5c.` appears in all rendered reports regardless of whether
  `feasibility_rows` is populated.
- When feasibility_rows is empty, the section contains the credential
  instructions and the exact string `Re-run with credentials`.
- When feasibility_rows is partially populated, keywords with no DA data show
  `📊 No DA data` in the Status column.
- `tests/test_report_clarity.py::test_rc5_feasibility_always_rendered_*`
  covers: data present, data absent, data partial.

---

### RC.6 — Section 5 entity dominance: add interpretive sentence

**Problem addressed:** Issue 8.

**Required change:**

After the entity dominance percentages, add a one-line interpretation block
derived deterministically from the data:

If `counselling` + `directory` combined share > 40%:

> *Competitors are primarily counselling providers and directories. For
> informational keywords, your competition is guide/article content, not
> service pages.*

If `education` share > 15%:

> *Educational institutions hold significant SERP share. Content must meet
> an academic evidence standard to compete.*

If `government` share > 20%:

> *Government sources dominate. These keywords may be difficult to rank for
> regardless of DA — consider whether the audience finding government results
> is the same audience you are targeting.*

If none of the above thresholds are met:

> *No single entity type dominates. SERP is fragmented — differentiated
> content has room to enter.*

These thresholds are editorial. Move them to `config.yml` under a new
`report_thresholds.entity_dominance` key so they can be adjusted without
code changes.

**Acceptance criteria:**

- One and only one interpretive sentence appears after the entity dominance
  list in Section 5.
- The thresholds live in `config.yml::report_thresholds.entity_dominance`,
  not hard-coded in `generate_insight_report.py`.
- `tests/test_report_clarity.py::test_rc6_entity_dominance_interpretation_*`
  covers each threshold branch and the default.

---

### RC.7 — Section 6 volatility: suppress or explain non-comparable runs

**Problem addressed:** Issue 7.

**Required change:**

When `comparability_warning` is present in the volatility metrics, the section
currently renders the warning alongside the `nan` score. Change to:

If `volatility_score` is `nan` or `null` AND `comparability_warning` is
present, replace the entire section content with:

```markdown
## 6. Market Volatility

**Not applicable for this run.**

Volatility requires two runs with the same keyword set. This run used a
different keyword set than the previous run:

- **This run:** <keywords in current run only, comma-separated>
- **Previous run:** <keywords in previous run only, comma-separated>

Run again with the same keywords to establish a baseline for rank change
tracking.
```

If `volatility_score` is a valid number (not nan/null), render as currently,
including the comparability warning if present.

**Acceptance criteria:**

- When volatility_score is `nan`, the string `nan` does not appear in the
  rendered output.
- When volatility_score is `nan`, the section explains the incompatibility.
- When volatility_score is a valid number, the section renders the score and
  movers as now.
- `tests/test_report_clarity.py::test_rc7_volatility_*` covers: nan score,
  valid score, missing volatility data entirely.

---

### RC.8 — Content brief sequencing block

**Problem addressed:** Issue 6.

**Required change:**

Before the content brief list (currently `# Content Briefs`), add a brief
sequencing block:

```markdown
# Content Briefs

**Recommended writing order:**

1. `<Brief N title>` — targets `<keyword>` (best opportunity keyword from RC.1)
2. `<Brief N title>` — targets `<keyword>`
3. ...

Write in this order to address the highest-opportunity keyword first. Each
brief below is self-contained.
```

The ordering logic: the brief whose `most_relevant_keyword` matches the best
opportunity keyword from RC.1.1 is listed first. Remaining briefs are ordered
by the feasibility/intent ranking of their `most_relevant_keyword`. When two
briefs map to the same keyword, they are ordered alphabetically by pattern
name.

When feasibility data is absent, the sequencing block states:

> *Without feasibility data, briefs are ordered by intent confidence
> (high → medium → low) of their most relevant keyword.*

**Acceptance criteria:**

- `**Recommended writing order:**` appears before the first `## Brief` block.
- The number of items in the list equals the number of content briefs.
- `tests/test_report_clarity.py::test_rc8_brief_sequencing_*` covers:
  feasibility present, feasibility absent.

---

## Definition of done

This spec is complete when ALL of the following are true:

1. All RC.1 through RC.8 acceptance criteria are met.
2. `pytest` passes with zero failures. The existing test count (476 passing,
   27 skipped) does not decrease.
3. A rendered report from the `leila` run fixture contains:
   - `## 0. Executive Summary` as the first section.
   - The string `Total Search Volume (Proxy)` does not appear.
   - `## 5c.` appears with either a data table or the credential instructions.
   - Section 6 does not contain the string `nan`.
   - `**Recommended writing order:**` appears before the first brief.
4. `tests/test_report_clarity.py` exists with at least one test per RC item,
   all passing.
5. `config.yml` contains `report_thresholds.entity_dominance` keys.
6. `docs/spec_coverage.md` is updated with all RC.* criteria.

---

## What this spec does NOT change

- JSON schema. No new fields are added to `keyword_profiles` or any other
  JSON key. All changes are in rendering logic in `generate_insight_report.py`.
- `strategic_patterns.yml`, `brief_pattern_routing.yml`, or any other
  editorial YAML file.
- The content brief generation pipeline (`generate_content_brief.py`). Brief
  content is unchanged; only the sequencing block that precedes the briefs is
  new.
- The LLM prompt or validation logic.
- The feasibility scoring logic itself. Section 5c renders the same data as
  before when data is present; RC.5 only changes what renders when data is
  absent.
