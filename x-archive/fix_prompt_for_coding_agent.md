# Task: Fix SERP Analysis Prompt to Prevent Known Report Errors

## Context

The file `serp_analysis_prompt_v3.md` contains a system prompt, data
extraction code, and user prompt template used to generate SERP market
intelligence reports via the Anthropic API. A test run of this pipeline
produced a report with specific, documented errors. Your job is to
modify `serp_analysis_prompt_v3.md` to prevent these errors in future
runs.

The errors fall into two categories:
1. **System prompt gaps** — the LLM isn't told something it needs to know
2. **Missing or misleading data** — the extraction code omits signals
   the LLM needs, or the data dictionary misdescribes what's there

Do NOT rewrite the file from scratch. Make targeted edits to fix
each issue. After each edit, verify the change doesn't break the
extraction code by running it against the spreadsheet at
`/mnt/user-data/uploads/market_analysis_v2.xlsx` with client_domain
`livingsystems.ca` and client_name_patterns `['Living Systems']`.

## Issue 1: Hallucinated PAA Quotes

**Problem:** The report quoted a PAA question ("Why is it the Estranged
Parents never seem to have a clue?") that does not exist in the dataset.
The LLM fabricated it to support an argument.

**Fix:** Add a rule to the system prompt's analytical principles section
(or create a new "Evidence Rules" subsection after the principles) that
states: Every PAA question referenced in the report must appear verbatim
in the paa_questions data. Do not paraphrase, combine, or invent
questions. If a content gap exists but no PAA question directly supports
it, state that the gap is inferred from other signals (autocomplete,
related searches, AIO text) rather than citing a non-existent question.

## Issue 2: Inflated Frequency Claims

**Problem:** The report said "Multiple PAA questions ask 'What is the
cut off in family therapy?'" when this question appears exactly once for
one keyword. It also said Fusion Trap triggers "appear frequently in PAA
questions" when zero PAA questions contain any of those trigger words.

**Fix:** Add a rule: When claiming a question or term appears "multiple
times," "frequently," or "across clusters," cite the specific count
and the specific source_keywords it appears for. The paa_questions data
includes a source_keywords array for each question — use it. Do not
describe something as appearing "multiple times" if it appears once.
Do not claim a term appears in PAA questions if it only appears in
organic result titles/snippets.

## Issue 3: N/A Rank Delta Misinterpreted as Stability

**Problem:** The report said Living Systems' positions "show zero rank
delta, indicating stable positioning." The actual rank_delta value is
null/None (extracted from the spreadsheet's 'N/A' string). The LLM
treated missing data as evidence of stability.

**Fix:** Update the data dictionary entry for rank_deltas to clarify:
"A null/None rank_delta means no prior SERP snapshot exists for
comparison — this is NOT the same as zero change. Zero means the
position was measured before and did not move. Null means the keyword
is new to the tracking set and stability cannot be assessed. Do not
describe null rank_delta positions as 'stable.'"

Also update the client_organic_appearances data dictionary entry to
include the same caveat, since those entries carry rank_delta values.

## Issue 4: Local Pack SERP Module vs Maps Data Confusion

**Problem:** The report claimed local packs appeared on the SERP for
"reunification counselling BC" but the SERP_Modules data only shows
local_results/local_map modules for "family cutoff counselling
Vancouver" and "reunification therapy near me." The Local_Pack_and_Maps
sheet has data for "reunification counselling BC" because it comes from
a separate Google Maps API fetch, not from what appears on the SERP page.

**Fix:** Update the data dictionary to distinguish these two data
sources. The serp_modules_by_keyword entry should note: "These modules
reflect what actually appears on the Google SERP page." The
local_pack_by_keyword entry should note: "This data comes from Google
Maps queries and may include businesses that do NOT appear in the SERP
local pack module. Cross-reference with serp_modules_by_keyword to
confirm which keywords actually show local pack results on the SERP."

## Issue 5: Missing Search Volume Context

**Problem:** The report treats all six keyword clusters as comparable
opportunities without noting that "reunification counselling BC" returned
97 total results versus 690,000 for "family cutoff counselling Vancouver"
— a 7,000x difference. The total_results field is already in the queries
data but the system prompt doesn't instruct the LLM to use it.

**Fix:** In the data dictionary under the queries entry, add: "The
total_results field is Google's estimated result count for each query.
While not a precise search volume metric, large differences between
keywords (e.g., 97 vs 690,000) indicate meaningful differences in
market size and should inform prioritization."

Also add to the Keyword Cluster Analysis section description in the
report structure: "Note the relative scale of each cluster using
total_results as a proxy for search volume. Flag any clusters where
total_results is very low (under 1,000) as potentially too small
to justify dedicated content investment."

## Issue 6: Missing Discussion of Directory Platforms

**Problem:** Psychology Today appears 22 times in organic results and
17 times in AIO citations — the most visible single entity — but the
report treats it only as a citation source without noting it functions
as a therapist directory. This is strategically relevant because the
client could get listed there.

**Fix:** Add to the system prompt principles or report structure: "When
analyzing source frequency, distinguish between direct competitors
(organizations offering similar services), directories/aggregators
(platforms that list practitioners, such as Psychology Today,
CounsellingBC, TherapyTribe), and informational sources (news, guides,
government). Directory platforms represent a different kind of
opportunity — the client may benefit from being listed on them rather
than competing against them for organic rankings."

## Issue 7: Missing Competitor Ads and Forum Signals

**Problem:** The report doesn't mention competitor ads (already extracted
in the data) or the discussions_and_forums SERP module (present for all
root keywords), both of which are strategically relevant.

**Fix:** Add to the Section 2 (Keyword Cluster Analysis) description:
"Note any competitor_ads activity and what it signals about commercial
intent. Note whether discussions_and_forums modules appear, as these
indicate Google is surfacing user-generated content (e.g., Reddit) and
may represent both competitive threats and distribution opportunities."

## Issue 8: Local Pack Count Underestimate

**Problem:** The report says "up to 55 local businesses listed" when the
actual data shows 134 for "reunification therapy near me" and 115 for
"family cutoff counselling Vancouver." The LLM miscounted.

**Fix:** Add an extraction-level summary. In the extraction code, after
building local_pack_by_keyword, add a local_pack_summary that counts
entries per keyword:

```python
data['local_pack_summary'] = {
    kw: len(entries) for kw, entries in local_by_kw.items()
}
```

Add this to the data dictionary: "local_pack_summary: count of local
businesses returned per root keyword. Use these exact counts rather
than estimating from the raw data."

## Verification

After making all changes:

1. Run the extraction code against the test spreadsheet and confirm
   it still produces valid output with all expected keys.
2. Confirm the system prompt contains all new rules and data dictionary
   entries.
3. Confirm no existing functionality was broken (all original data
   blocks still extract correctly).
4. Print the final compact JSON size to confirm it hasn't grown
   unreasonably (baseline: ~167K chars).
