# Tool 1 Methodology

How SERP Intelligence Tool 1 produces its outputs.

---

## Part 1 — SERP data collection and intent classification

**Input:** keyword CSV file.

**Fetch:** `serp_audit.py` calls SerpAPI for each keyword, retrieving organic results, People Also Ask (PAA) questions, and local pack entries.

**Intent verdict:** `intent_verdict.py` applies rules from `intent_mapping.yml` (first-match-wins) to assign a `primary_intent`, `is_mixed` flag, confidence score, and distribution to each keyword.

**PAA classification:** `intent_classifier.py` tags each PAA question as `External Locus` (medical-model framing), `Systemic` (Bowen Family Systems Theory framing), or `General` (neither). Trigger vocabularies live in `intent_classifier_triggers.yml`.

**Title patterns:** `title_patterns.py` extracts the dominant shape pattern (how_to, what_is, listicle_numeric, etc.) from the top-10 organic titles for each keyword.

**Strategic patterns:** `serp_audit.py` loads Bowen pattern definitions from `strategic_patterns.yml` and matches trigger words (word-boundary, case-insensitive) against the SERP ngram corpus. Matched patterns become `strategic_recommendations` in the output JSON.

**Output:** `market_analysis_{topic}_{datetime}.json` — the data contract for Part 2.

---

## Part 2 — Report generation

**Input:** `market_analysis_*.json`.

### Section 4 — Pattern keyword selection

Each Section 4 Bowen pattern block shows a *SERP intent context* line anchoring the pattern to the most relevant keyword in the run. The keyword is selected by `_get_most_relevant_keyword()` in `generate_insight_report.py` using a three-component scoring formula:

```
score(keyword, pattern) =
    (PAA questions for keyword tagged with pattern's Relevant_Intent_Class) × 3
  + (pattern's keyword_hints matching keyword source text) × 2
  + (pattern's trigger words appearing in Title+Snippet of keyword's organic results) × 1
```

**Component weights and rationale:**

| Component | Weight | Signal | Source |
|---|---|---|---|
| PAA intent class match | 3 | What searchers are framing (searcher intent) | `paa_questions[].Intent_Tag` + `strategic_patterns.yml[].Relevant_Intent_Class` |
| Keyword hint match | 2 | Source keyword text alignment | `brief_pattern_routing.yml[].keyword_hints` |
| Trigger text in organic titles | 1 | What page authors wrote (noisier signal) | `organic_results[].Title` + `Snippet` |

PAA evidence (weight 3) is intentionally the strongest signal because it reveals searcher framing, not page-author framing. Trigger words appearing in competitor titles are retained as a tiebreaker but cannot override PAA evidence.

**Relevant_Intent_Class by pattern:**

| Pattern | Relevant_Intent_Class |
|---|---|
| The Medical Model Trap | `External Locus` |
| The Fusion Trap | *(none — PAA component = 0)* |
| The Resource Trap | *(none — PAA component = 0)* |
| The Blame/Reactivity Trap | `External Locus` |

Patterns without a `Relevant_Intent_Class` field in `strategic_patterns.yml` score 0 on the PAA component and select their keyword via keyword_hints + trigger text only.

**Alphabetical tiebreaker:** When multiple keywords score equally, the keyword that sorts first alphabetically is selected (deterministic).

**Null result:** If all keywords score 0 across all three components, `_get_most_relevant_keyword()` returns `None` and the intent context line renders as: *"SERP intent context: no keyword in this run has triggers for this pattern."*

*Spec: serp_tool1_improvements_spec.md#I.3. Implemented 2026-05-01.*

---

## Part 3 — Content brief generation

**Input:** `market_analysis_*.json` + `strategic_recommendations`.

`generate_content_brief.py` selects relevant PAA questions and competitors for each pattern using routing rules from `brief_pattern_routing.yml` (`paa_themes`, `paa_categories`, `keyword_hints`). An LLM (Anthropic API) generates the main report and advisory briefing. Outputs are validated before writing; hard validation failures abort, soft failures retry once.
