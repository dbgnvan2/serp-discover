# Task: Move Verification Calculations from LLM to Extraction Code

## Principle

The current extraction code sends raw data to the LLM and relies on
it to count, cross-reference, and verify. The LLM has repeatedly
fabricated evidence when doing this — citing PAA questions that don't
exist, claiming terms appear "frequently" when they appear once,
and attributing signals to the wrong data source.

The fix: **every verifiable fact the LLM might cite should be
pre-computed in the extraction code and sent as a verified assertion,
not as raw data the LLM must process.**

The LLM's job becomes interpretation of pre-verified facts, not
verification of raw data.

## Working Files

- Extraction code + system prompt + user prompt: `serp_analysis_prompt_v3.md`
- Test spreadsheet: `/mnt/user-data/uploads/market_analysis_v2.xlsx`
- Client domain: `livingsystems.ca`
- Client name patterns: `['Living Systems']`

## What to Change

Review each data block in the extraction code. For each one, ask:
"Is this sending raw records for the LLM to count/search/cross-reference,
or is it sending pre-computed results?" If it's raw records, redesign
it to send computed results instead.

Below are the specific transformations needed, organized by data block.
After implementing all changes, update the system prompt's data
dictionary to match the new output structure, and remove any
instructions that tell the LLM to count or cross-reference things
that are now pre-computed.

---

### 1. PAA Questions: Pre-Compute Cross-Cluster Analysis

**Current problem:** The extraction sends a flat list of deduplicated
PAA questions with their source_keywords. The LLM is supposed to
identify which questions span multiple clusters and which are
single-cluster. It has failed at this twice — inflating single-cluster
questions into "cross-cutting opportunities" and fabricating questions
that don't exist.

**What to compute:**

```
paa_analysis: {
    cross_cluster: [
        // Questions appearing for 2+ source_keywords, sorted by
        // number of keywords descending, then by combined total_results
        {
            question: "What are the 5 stages of estrangement?",
            source_keywords: ["estrangement", "estrangement from adult children", "estrangement grief"],
            cluster_count: 3,
            combined_total_results: 287100,  // sum of total_results for those keywords
            category: "General",
        },
        ...
    ],
    single_cluster: [
        // Questions appearing for only 1 source_keyword
        {
            question: "What causes reunification to fail?",
            source_keywords: ["reunification counselling BC"],
            cluster_count: 1,
            combined_total_results: 94,
            category: "General",
        },
        ...
    ],
    summary: {
        total_unique_questions: 42,
        cross_cluster_count: 8,
        single_cluster_count: 34,
    }
}
```

**What to stop sending:** The raw `paa_questions` list with full
snippets. The LLM doesn't need the answer snippets — it needs to
know which questions exist, how broadly they appear, and at what
market scale. The question text itself is the content signal;
the snippet is noise.

---

### 2. Tool-Generated Recommendations: Pre-Verify Trigger Evidence

**Current problem:** The extraction sends trigger words found and
the LLM is supposed to verify where they appear. It consistently
claims triggers appear "in PAA questions" when they only appear in
organic snippets.

**What to compute:** For each recommendation, search every data
source separately and report exact counts:

```
tool_recommendations_verified: [
    {
        pattern_name: "The Fusion Trap",
        trigger_words_searched_for: ["connection", "bond", ...],
        triggers_found: {
            in_paa_questions: {},         // word: count
            in_organic_titles: {"connection": 15, "communication": 14, "bond": 3},
            in_organic_snippets: {"connection": 8, ...},
            in_aio_text: {"connection": 2, ...},
            in_autocomplete: {},
            in_related_searches: {},
        },
        content_angle: "Why trying to get 'closer' might be pushing your partner away.",
        status_quo_message: "...",
        reframe: "...",
        verdict_inputs: {
            // Pre-computed flags the LLM can use for evaluation
            any_paa_evidence: false,
            any_autocomplete_evidence: false,
            total_trigger_occurrences: 42,
            primary_evidence_source: "organic_titles_and_snippets",
        }
    },
    ...
]
```

**What to stop sending:** The raw `tool_generated_recommendations`
with just triggers_actually_found as a comma-separated string. That
format gives no information about WHERE the triggers were found.

---

### 3. Client Position: Pre-Compute Vulnerability Assessment

**Current problem:** The extraction sends raw client appearances
with rank_delta values. The LLM is supposed to assess whether the
client's position is stable, improving, or declining. It has
misinterpreted N/A (no prior data) as "stable" and failed to flag
a -3 rank drop as urgent.

**What to compute:**

```
client_position: {
    organic: [
        {
            source_keyword: "family cutoff counselling Vancouver",
            query_label: "A",
            rank: 4,
            rank_delta: -3,
            stability: "declining",  // "new" if N/A, "stable" if 0, "improving" if positive, "declining" if negative
            title: "Can cutting off family be good therapy?",
            link: "https://livingsystems.ca/can-cutting-off-family-be-good-therapy/",
            competitors_above: [
                // Sources ranking better than client for this keyword
                {rank: 1, source: "CounsellingBC", entity_type: "directory"},
                {rank: 1, source: "Head and Heart Counselling", entity_type: "counselling"},
                {rank: 1, source: "Family Services of the North Shore", entity_type: "nonprofit"},
                {rank: 2, source: "Blue Sky Wellness Clinic", entity_type: "counselling"},
                {rank: 2, source: "Latitude Counselling", entity_type: "counselling"},
                {rank: 2, source: "Lotus Therapy & Counselling Centre", entity_type: "counselling"},
                {rank: 3, source: "Alison Bell & Associates", entity_type: "counselling"},
                {rank: 3, source: "Restored Hope Counselling Services", entity_type: "counselling"},
                {rank: 3, source: "lavendercounselling.com", entity_type: "counselling"},
            ]
        }
    ],
    aio_citations: [
        {
            source_keyword: "family cutoff counselling Vancouver",
            query_label: "A",
            title: "Can cutting off family be good therapy?",
            also_mentioned_in_aio_text: true,
            aio_text_excerpt: "Living Systems: Provides systemic therapy that addresses whether cutting off contact is a necessary..."
        }
    ],
    aio_text_mentions: [
        {
            source_keyword: "family cutoff counselling Vancouver",
            query_label: "A",
            excerpt: "Living Systems: Provides systemic therapy that addresses...",
        }
    ],
    local_pack: [],
    language_pattern_mentions: [
        {phrase: "living systems", count: 1},
        {phrase: "scenarios living systems", count: 1},
        {phrase: "living systems provides", count: 1},
    ],
    summary: {
        total_organic_appearances: 1,    // count unique source_keyword+label combos
        total_aio_citations: 1,
        total_aio_text_mentions: 1,
        total_local_pack: 0,
        keywords_with_any_visibility: ["family cutoff counselling Vancouver"],
        keywords_with_zero_visibility: ["estrangement", "estrangement from adult children", "estrangement grief", "reunification therapy near me", "reunification counselling BC"],
        has_declining_positions: true,
        worst_delta: -3,
    }
}
```

**Important:** Filter out false positives from language pattern
matching. "living through" and "living loss" are NOT references to
Living Systems — they're phrases like "Living Through Loss Counselling
Society" and "living loss disenfranchised grief." Only include
patterns where the match is genuinely the client organization.
Use `client_name_patterns` for this, not the domain fragment alone.
Require at least 2 consecutive words from the pattern to match
(i.e., "living systems" matches but "living" alone does not).

Also filter the organic results: "Living Through Loss Counselling
Society of BC" is NOT Living Systems Counselling. The client
detection must match on URL domain (`livingsystems.ca`), not on
source name containing "living."

---

### 4. Keyword Cluster Profiles: Pre-Build Cluster Summaries

**Current problem:** The extraction sends entity distributions,
organic results, AIO citations, PAA questions, autocomplete, and
related searches as separate data blocks, all keyed by
source_keyword. The LLM is supposed to cross-reference all of
these to build cluster profiles. This is where it makes mistakes
— it looks at one data source, makes a claim, but doesn't
cross-check against the others.

**What to compute:** One unified profile per root keyword:

```
keyword_profiles: {
    "estrangement": {
        total_results: 215000,
        serp_modules: ["ai_overview:2", "related_questions:5", "organic_results:6", "discussions_and_forums:14"],
        has_ai_overview: true,
        has_local_pack: false,
        has_discussions_forums: true,
        entity_distribution: {counselling: 6, legal: 9, nonprofit: 2, ...},
        entity_dominant_type: "legal",
        top5_organic: [
            {rank: 1, source: "Fulton & Company LLP", entity_type: "N/A"},
            {rank: 1, source: "Restored Hope Counselling Services", entity_type: "counselling"},
            ...
        ],
        aio_citation_count: 15,
        aio_top_sources: [["MacLean Family Law", 4], ["Psychology Today", 3]],
        paa_questions: [
            "When should you stop reaching out to an estranged child?",
            "How long does the average family estrangement last?",
            ...
        ],
        paa_count: 8,
        autocomplete_top10: ["estrangement meaning", "estrangement synonym", ...],
        related_searches: ["Family estrangement grief vancouver..."],
        local_pack_count: 0,
        client_visible: false,
        client_rank: null,
        client_rank_delta: null,
        client_aio_cited: false,
    },
    "family cutoff counselling Vancouver": {
        total_results: 689000,
        ...
        client_visible: true,
        client_rank: 4,
        client_rank_delta: -3,
        client_aio_cited: true,
    },
    ...
}
```

This gives the LLM one place to look per keyword with everything
pre-joined. No cross-referencing needed.

---

### 5. AIO Text: Send Excerpts Not Full Text

**Current problem:** AIO text is ~32K chars across all queries.
Most of it is generic information the LLM doesn't need. What the
LLM needs is: what framing/language the AIO uses, what sources
it names, and whether the client is mentioned.

**What to compute:** Extract structured signals from each AIO text:

```
aio_analysis: {
    "estrangement": {
        has_aio: true,
        aio_length_chars: 1847,
        sources_named_in_text: ["MacLean Family Law", "Reconnect Families", ...],
        client_mentioned: false,
        client_excerpt: null,
        key_phrases: ["parental alienation", "WESA", "disinheritance", ...],
        // Or just a truncated excerpt of the first 300 chars for framing
        opening_excerpt: "Family estrangement in Vancouver and British Columbia is addressed through specialized legal, therapeutic..."
    },
    "family cutoff counselling Vancouver": {
        has_aio: true,
        client_mentioned: true,
        client_excerpt: "Living Systems: Provides systemic therapy that addresses whether cutting off contact is a necessary...",
        opening_excerpt: "In Vancouver, specialized counselling for family cutoff...",
        ...
    },
}
```

**What to stop sending:** The full `ai_overview_text` field (up to
2000 chars per query). Replace with the structured extraction above.
If the LLM needs specific language from the AIO, the opening excerpt
and key phrases provide that. If it needs to know about the client,
client_excerpt provides it directly.

**Implementation note:** The `key_phrases` extraction can be simple.
Take the existing `top_bigrams` and `top_trigrams` from the
SERP_Language_Patterns sheet, but filter to only those phrases
that appear in that specific query's AIO text. This is deterministic,
not LLM-dependent.

Alternatively, if phrase extraction is too complex, just send the
opening 300-500 chars of AIO text as `opening_excerpt`. This is
where Google states its framing, and it's enough for the LLM to
assess the AIO's approach without having to parse 2000 chars of
detail.

---

### 6. Organic Results: Send Profiles Not Records

**Current problem:** `organic_results_by_keyword` sends ~25-30
full result records per keyword (rank, title, source, entity_type,
content_type, snippet). That's ~168 records with ~200-char snippets.
The LLM needs to know who ranks and what type they are, not the
full snippet text.

**What to compute:** This is already partially addressed by
`keyword_profiles` (item 4 above) which includes `top5_organic`.
For the full competitive picture, add a per-keyword competitive
summary:

```
competitive_landscape: {
    "estrangement": {
        total_organic_results: 27,
        entity_breakdown: {legal: 9, counselling: 6, N/A: 7, nonprofit: 2, ...},
        top_sources: [
            {source: "MacLean Family Law", appearances: 3, entity_type: "legal", best_rank: 4},
            {source: "estrangedfamilytherapy.com", appearances: 2, entity_type: "counselling", best_rank: 2},
            ...
        ],
        content_type_breakdown: {news: 5, guide: 4, other: 12, ...},
    },
    ...
}
```

**What to stop sending:** The full `organic_results_by_keyword`
with all 168 records and their snippets. Replace with the
competitive landscape summaries above.

Keep `source_frequency_top30` as a global view, but it's now
supplementary to the per-keyword breakdowns.

---

### 7. Autocomplete and Related Searches: Keep As-Is But Add Counts

These are already relatively compact (93 autocomplete suggestions,
116 related searches) and the LLM needs the actual text to
identify keyword expansion opportunities. However, add summary
counts so the LLM can cite them accurately:

```
autocomplete_summary: {
    total_suggestions: 93,
    by_keyword: {
        "estrangement": 15,
        "estrangement from adult children": 15,
        ...
    },
    // Flag any trigger words from tool recommendations found here
    trigger_word_hits: {
        "free": ["free reunification therapy near me"],
        "toxic": [],  // explicitly empty — prevents fabrication
        ...
    }
}
```

Keep the raw `autocomplete_by_keyword` and
`related_searches_by_keyword` lists, but add the summary block.

---

### 8. Local Pack: Send Counts Not Records

**Current problem:** `local_pack_by_keyword` sends full records
for every local business. For "reunification therapy near me"
there can be 100+ entries. The LLM miscounted these in a previous
report.

**What to compute:**

```
local_pack_summary: {
    "family cutoff counselling Vancouver": {
        total_businesses: 115,
        top_categories: [["Counselor", 45], ["Family counselor", 22], ...],
        avg_rating: 4.3,
        client_present: false,
    },
    "reunification therapy near me": {
        total_businesses: 134,
        ...
    },
    // Only include keywords that actually show local_results in SERP modules
    serp_local_pack_confirmed: ["family cutoff counselling Vancouver", "reunification therapy near me"],
    serp_local_pack_absent: ["estrangement", "estrangement from adult children", "estrangement grief", "reunification counselling BC"],
}
```

**What to stop sending:** The full `local_pack_by_keyword` with
all individual business records. The LLM doesn't need to know
every business name — it needs the competitive density (count),
the category mix, and whether the client appears.

---

### 9. Language Patterns: Send Relevant Subset Only

**Current problem:** The extraction sends the top 50 bigrams and
30 trigrams. Most are not analytically useful for the report.

**What to compute:** Filter to patterns relevant to the analysis:

```
market_language: {
    top_20_bigrams: [...],   // reduced from 50
    top_10_trigrams: [...],  // reduced from 30
    client_mentions: [...],  // already computed, keep
    bowen_theory_terms: [    // terms related to client's framework
        {phrase: "family systems", count: N},
        {phrase: "differentiation", count: N},
        {phrase: "emotional cutoff", count: N},
        ...
    ],
    // If any of these are zero, the LLM knows the framework
    // language isn't present in competitor content
}
```

**Implementation note:** The `bowen_theory_terms` list should be
configurable via the client_context, not hardcoded. Add a
`FRAMEWORK_TERMS` key to client_context:

```python
"FRAMEWORK_TERMS": [
    "family systems", "bowen", "differentiation",
    "emotional cutoff", "triangles", "multigenerational",
    "nuclear family emotional", "societal emotional",
]
```

The extraction code searches all bigrams and trigrams for these
terms and reports counts. Zero counts are explicitly included —
they tell the LLM "this concept is absent from the competitive
landscape."

---

## After All Changes

### Update the System Prompt

The data dictionary in the system prompt must be rewritten to
match the new output structure. Remove all instructions that tell
the LLM to:
- Count how many times something appears
- Cross-reference between data blocks
- Determine where trigger words were found
- Assess whether positions are stable or declining
- Distinguish cross-cluster from single-cluster PAA questions

Replace with instructions that tell the LLM to:
- Interpret pre-computed cluster profiles
- Explain implications of pre-computed vulnerability assessments
- Recommend actions based on pre-verified evidence
- Connect findings to strategic decisions ("why this matters")

Add a new analytical principle:

```
EVIDENCE DISCIPLINE. The data you receive contains pre-verified
facts — counts, cross-references, and classifications computed
deterministically from the raw SERP data. Use these pre-computed
values exactly as provided. Do not estimate, round, or
approximate counts. Do not claim a term appears in a data source
unless the pre-computed trigger verification confirms it. If the
data does not contain evidence for a claim you want to make,
state that the evidence is absent rather than inferring it.
```

### Update the Token Budget

The pre-computed format should be substantially smaller than the
raw data format. Measure the new compact JSON size and update the
token budget estimates. Target: under 60K chars (down from ~167K).

### Validate

Run the updated extraction against the test spreadsheet and verify:
1. All pre-computed values match what manual inspection of the
   spreadsheet confirms.
2. The compact JSON size decreased.
3. The system prompt data dictionary matches every key in the output.
4. No raw record arrays are sent where a summary would suffice.
5. The LLM cannot cite a PAA question, trigger word source, rank
   delta interpretation, or local pack count that isn't explicitly
   stated in the pre-computed data.
