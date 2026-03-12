# SERP Market Intelligence: API Prompt & Data Extraction Spec (v2)

## Overview

This document contains:

1. **Data Extraction Spec** — Python code to compress the raw spreadsheet
   (~1.9M chars) into a structured JSON summary (~165K chars compact)
2. **The API Prompt** — System prompt + user prompt template for the
   LLM analysis call
3. **Implementation Notes** — API call configuration, token budgets,
   scaling strategies
4. **Iteration Guide** — How to use previous analyses in subsequent runs

The raw spreadsheet is too large for a single API context window. The
extraction layer does counting, grouping, and deduplication. The LLM
does interpretation, gap analysis, and strategic recommendations.

---

## Part 1: Data Extraction Functions

### Key Concepts

The spreadsheet uses two keyword fields that are easy to confuse:

- **`Source_Keyword`** — The root keyword you entered (e.g., "estrangement").
  This is the clustering key. All queries derived from the same root share
  this value.
- **`Root_Keyword`** — The full executed query text (e.g., "what are the
  best options for estrangement? Vancouver, British Columbia, Canada").
  This is NOT suitable for grouping.

The **`Query_Label`** field indicates query type:
- **A** = Root local query (the keyword + geo-location)
- **A.1** = AI-generated informational variant (e.g., "how to choose...")
- **A.2** = AI-generated cost variant (e.g., "how much does ... cost...")

The extraction code below uses `Source_Keyword` for all clustering.

### Code

```python
import openpyxl
import json
from collections import Counter, defaultdict
from urllib.parse import urlparse


def _extract_domain(url: str) -> str:
    """Extract readable domain from URL."""
    if not url:
        return ''
    try:
        parsed = urlparse(str(url))
        return parsed.netloc.replace('www.', '')
    except Exception:
        return str(url)[:60]


def _safe_int(val, default=0):
    """Safely convert a value to int, handling 'N/A' strings and None."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str) and val not in ('N/A', '', 'None'):
        try:
            return int(val)
        except ValueError:
            pass
    return default


def extract_analysis_data(
    xlsx_path: str,
    client_domain: str,
    client_name_patterns: list[str] | None = None,
) -> dict:
    """
    Extract and summarize SERP data for LLM analysis.

    Args:
        xlsx_path: Path to the market_analysis spreadsheet.
        client_domain: The client's domain (e.g., 'livingsystems.ca')
                       used to flag client appearances in URLs.
        client_name_patterns: Additional strings to search for in AI
                              Overview body text (e.g., ['Living Systems']).
                              The domain is always checked automatically.

    Returns:
        dict ready to serialize as JSON for the API prompt.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    data = {}
    client_domain_lower = client_domain.lower()

    # Build list of patterns for AIO text matching.
    # URLs use the domain; AIO body text uses the org name.
    _aio_text_patterns = [client_domain_lower]
    if client_name_patterns:
        _aio_text_patterns.extend(p.lower() for p in client_name_patterns)

    # ─────────────────────────────────────────────
    # BLOCK 0: Run Metadata
    # Purpose: Collection date, geo-location, run identity
    # ─────────────────────────────────────────────
    ws = wb['Overview']
    first_row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))
    data['metadata'] = {
        'run_id': first_row[1],
        'created_at': str(first_row[2]) if first_row[2] else 'unknown',
        'google_url_sample': first_row[3],  # contains UULE geo param
    }

    # ─────────────────────────────────────────────
    # BLOCK 1: Query Map
    # Purpose: Shows what was searched and basic SERP shape per query.
    # Also extracts the set of unique root keywords (Source_Keyword).
    # ─────────────────────────────────────────────
    # Overview columns:
    #  [0] Root_Keyword (full query text)
    #  [2] Created_At
    #  [5] Search_Query_Used
    #  [6] Total_Results
    #  [7] SERP_Features
    #  [11] Has_Main_AI_Overview
    #  [12] AI_Overview (full text)
    #  [16] Rank_1_Title  [17] Rank_1_Link
    #  [20] Rank_2_Title  [21] Rank_2_Link
    #  [24] Rank_3_Title  [25] Rank_3_Link
    #  [29] Source_Keyword (root keyword)
    #  [30] Query_Label (A, A.1, A.2)
    #  [31] Executed_Query
    queries = []
    root_keywords = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[29]
        root_keywords.add(source_kw)

        # Detect client mentions in AI Overview text.
        # AIO text uses organization name, not domain.
        aio_text = str(row[12]) if row[12] else ''
        aio_text_lower = aio_text.lower()
        client_in_aio_text = any(
            p in aio_text_lower for p in _aio_text_patterns
        )

        q = {
            'source_keyword': source_kw,
            'query_label': row[30],
            'executed_query': row[31],
            'total_results': row[6],
            'serp_features': row[7],
            'has_ai_overview': row[11],
            'ai_overview_text': aio_text[:2000] if aio_text else None,
            'client_mentioned_in_aio_text': client_in_aio_text,
            'rank_1': {
                'title': row[16],
                'source': _extract_domain(row[17]),
                'link': row[17]
            },
            'rank_2': {
                'title': row[20],
                'source': _extract_domain(row[21]),
                'link': row[21]
            },
            'rank_3': {
                'title': row[24],
                'source': _extract_domain(row[25]),
                'link': row[25]
            },
        }
        queries.append(q)

    data['queries'] = queries
    data['root_keywords'] = sorted(root_keywords)

    # ─────────────────────────────────────────────
    # BLOCK 2: Organic Results (condensed)
    # Purpose: Who ranks, for what, entity/content type distribution.
    # Grouped by Source_Keyword (root keyword), not Root_Keyword (query).
    # ─────────────────────────────────────────────
    # Organic_Results columns:
    #  [0] Root_Keyword   [5] Rank        [6] Title
    #  [7] Link           [8] Snippet     [9] Source
    #  [10] Content_Type  [11] Entity_Type
    #  [13] Rank_Delta    [14] Source_Keyword
    #  [15] Query_Label   [16] Executed_Query
    ws = wb['Organic_Results']

    organic_by_kw = defaultdict(list)       # All results for label-A queries
    source_counter = Counter()               # Global source frequency
    entity_by_kw = defaultdict(Counter)      # Entity type per root keyword
    entity_na_count = 0                      # Track unclassified results
    content_counter = Counter()              # Content type (global)
    client_organic = []                      # Client organic appearances
    rank_deltas = []                         # Non-zero rank changes
    total_organic_rows = 0                   # Total rows processed

    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[14]      # Source_Keyword — the clustering key
        label = row[15]
        rank = row[5]
        title = row[6]
        link = row[7]
        snippet = row[8]
        source = row[9]
        content_type = row[10]
        entity_type = row[11]
        rank_delta = _safe_int(row[13], default=None)

        total_organic_rows += 1
        source_counter[source] += 1

        if entity_type and entity_type != 'N/A':
            entity_by_kw[source_kw][entity_type] += 1
        else:
            entity_na_count += 1

        if content_type and content_type != 'N/A':
            content_counter[content_type] += 1

        # All results for root queries (label A).
        # The SERP data typically contains multiple results per rank
        # position (e.g., 2-3 URLs at rank 1), so this produces ~25-30
        # entries per keyword, not 10.
        if label == 'A':
            organic_by_kw[source_kw].append({
                'rank': rank,
                'title': title,
                'source': source,
                'entity_type': entity_type,
                'content_type': content_type,
                'snippet': str(snippet)[:200] if snippet else None
            })

        # Client appearances (all queries, all labels)
        if link and client_domain_lower in str(link).lower():
            client_organic.append({
                'source_keyword': source_kw,
                'query_label': label,
                'rank': rank,
                'title': title,
                'link': link,
                'rank_delta': rank_delta
            })

        # Rank deltas (non-zero only)
        if rank_delta is not None and rank_delta != 0:
            rank_deltas.append({
                'source_keyword': source_kw,
                'query_label': label,
                'rank': rank,
                'delta': rank_delta,
                'source': source,
                'title': title
            })

    data['organic_results_by_keyword'] = {
        kw: sorted(results, key=lambda x: x['rank'])
        for kw, results in organic_by_kw.items()
    }
    data['source_frequency_top30'] = source_counter.most_common(30)
    data['entity_distribution_by_keyword'] = {
        kw: dict(counts) for kw, counts in entity_by_kw.items()
    }
    data['content_type_distribution'] = content_counter.most_common(10)
    data['client_organic_appearances'] = client_organic
    data['rank_deltas_top20'] = sorted(
        rank_deltas, key=lambda x: -abs(x['delta'])
    )[:20]
    data['organic_summary'] = {
        'total_rows': total_organic_rows,
        'entity_classified_count': total_organic_rows - entity_na_count,
        'entity_unclassified_count': entity_na_count,
    }

    # ─────────────────────────────────────────────
    # BLOCK 3: AI Overview Citations
    # Purpose: Who Google's AI cites — the GEO target list.
    # Grouped by Source_Keyword.
    # ─────────────────────────────────────────────
    # AI_Overview_Citations columns:
    #  [0] Root_Keyword  [5] Title    [6] Link
    #  [7] Source        [8] Source_Keyword
    #  [9] Query_Label   [10] Executed_Query
    ws = wb['AI_Overview_Citations']
    aio_source_counter = Counter()
    aio_by_kw = defaultdict(Counter)
    client_aio_citations = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        source = row[7]
        source_kw = row[8]
        link = row[6]
        title = row[5]
        query_label = row[9]

        aio_source_counter[source] += 1
        aio_by_kw[source_kw][source] += 1

        if link and client_domain_lower in str(link).lower():
            client_aio_citations.append({
                'source_keyword': source_kw,
                'query_label': query_label,
                'title': title,
                'link': link
            })

    data['aio_citations_top25'] = aio_source_counter.most_common(25)
    data['aio_citations_by_keyword'] = {
        kw: counts.most_common(5) for kw, counts in aio_by_kw.items()
    }
    data['aio_total_citations'] = sum(aio_source_counter.values())
    data['aio_unique_sources'] = len(aio_source_counter)
    data['client_aio_citations'] = client_aio_citations

    # ─────────────────────────────────────────────
    # BLOCK 4: PAA Questions (deduplicated)
    # Purpose: What people actually ask — content targeting.
    # Keywords list uses Source_Keyword for clustering.
    # ─────────────────────────────────────────────
    # PAA_Questions columns:
    #  [0] Root_Keyword  [6] Score     [7] Category
    #  [8] Is_AI_Generated  [9] Question  [10] Snippet
    #  [12] Source_Keyword  [13] Query_Label
    ws = wb['PAA_Questions']
    paa_unique = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        question = row[9]
        category = row[7]
        score = row[6]
        source_kw = row[12]

        if question not in paa_unique:
            paa_unique[question] = {
                'category': category,
                'score': score,
                'source_keywords': [],
                'snippet': str(row[10])[:200] if row[10] else None
            }
        # Only add each root keyword once per question
        if source_kw not in paa_unique[question]['source_keywords']:
            paa_unique[question]['source_keywords'].append(source_kw)

    data['paa_questions'] = [
        {'question': q, **info}
        for q, info in sorted(
            paa_unique.items(),
            key=lambda x: (-x[1]['score'], -len(x[1]['source_keywords']))
        )
    ]

    # ─────────────────────────────────────────────
    # BLOCK 5: Autocomplete Suggestions
    # Purpose: Long-tail keyword discovery, audience intent signals.
    # Already keyed by Source_Keyword in the spreadsheet.
    # ─────────────────────────────────────────────
    # Autocomplete_Suggestions columns:
    #  [1] Source_Keyword  [2] Query_Label  [3] Executed_Query
    #  [4] Rank  [5] Suggestion  [6] Relevance  [7] Type
    ws = wb['Autocomplete_Suggestions']
    autocomplete_by_kw = defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[1]
        suggestion = row[5]
        relevance = row[6]
        autocomplete_by_kw[source_kw].append({
            'suggestion': suggestion,
            'relevance': relevance
        })
    data['autocomplete_by_keyword'] = dict(autocomplete_by_kw)

    # ─────────────────────────────────────────────
    # BLOCK 6: Related Searches (grouped by Source_Keyword)
    # Purpose: What Google thinks is related — expansion opportunities.
    # ─────────────────────────────────────────────
    # Related_Searches columns:
    #  [0] Root_Keyword  [6] Term  [8] Source_Keyword  [9] Query_Label
    ws = wb['Related_Searches']
    related_by_kw = defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[8]
        term = row[6]
        if term and term not in related_by_kw[source_kw]:
            related_by_kw[source_kw].append(term)
    data['related_searches_by_keyword'] = dict(related_by_kw)

    # ─────────────────────────────────────────────
    # BLOCK 7: SERP Language Patterns (top N bigrams and trigrams)
    # Purpose: Dominant vocabulary in the market.
    # ─────────────────────────────────────────────
    # SERP_Language_Patterns columns:
    #  [0] Type  [1] Phrase  [2] Count
    ws = wb['SERP_Language_Patterns']
    bigrams = []
    trigrams = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        typ = row[0]
        phrase = row[1]
        count = row[2]
        if typ == 'Bigram':
            bigrams.append({'phrase': phrase, 'count': count})
        elif typ == 'Trigram':
            trigrams.append({'phrase': phrase, 'count': count})

    data['top_bigrams'] = sorted(bigrams, key=lambda x: -x['count'])[:50]
    data['top_trigrams'] = sorted(trigrams, key=lambda x: -x['count'])[:30]

    # Check if client name appears in language patterns.
    # Uses both domain fragment and name patterns since SERP text
    # may use either form (e.g., "livingsystems" vs "living systems").
    _lang_patterns = [client_domain_lower.split('.')[0]]
    _lang_patterns.extend(p.lower() for p in (client_name_patterns or []))
    client_lang_mentions = []
    for item in bigrams + trigrams:
        phrase_lower = str(item['phrase']).lower()
        if any(p in phrase_lower for p in _lang_patterns):
            client_lang_mentions.append(item)
    data['client_language_pattern_mentions'] = client_lang_mentions

    # ─────────────────────────────────────────────
    # BLOCK 8: Local Pack (label-A queries only, grouped by Source_Keyword)
    # Purpose: Local competitive landscape.
    # ─────────────────────────────────────────────
    # Local_Pack_and_Maps columns:
    #  [0] Root_Keyword  [6] Rank  [7] Name  [8] Category
    #  [9] Rating  [10] Reviews  [13] Website
    #  [15] Source_Keyword  [16] Query_Label
    ws = wb['Local_Pack_and_Maps']
    local_by_kw = defaultdict(list)
    client_local_pack = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[15]
        label = row[16]
        if label != 'A':
            continue
        name = row[7]
        category = row[8]
        rating = row[9]
        reviews = row[10]
        website = row[13]

        entry = {
            'rank': row[6],
            'name': name,
            'category': category,
            'rating': rating,
            'reviews': reviews
        }
        local_by_kw[source_kw].append(entry)

        # Check for client in local pack
        if website and client_domain_lower in str(website).lower():
            client_local_pack.append({
                'source_keyword': source_kw,
                **entry
            })

    data['local_pack_by_keyword'] = dict(local_by_kw)
    data['local_pack_summary'] = {
        kw: len(entries) for kw, entries in local_by_kw.items()
    }
    data['client_local_pack_appearances'] = client_local_pack

    # ─────────────────────────────────────────────
    # BLOCK 9: SERP Module Order (label-A queries only)
    # Purpose: What SERP features appear and where.
    # Filtered to root queries (label A) to avoid redundancy —
    # variant queries (A.1, A.2) often have similar module layouts
    # but the root query best represents the primary SERP experience.
    # ─────────────────────────────────────────────
    # SERP_Modules columns:
    #  [0] Root_Keyword  [5] Module  [6] Order  [7] Present
    #  [9] Source_Keyword  [10] Query_Label
    ws = wb['SERP_Modules']
    modules_by_kw = defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_kw = row[9]
        label = row[10]
        module = row[5]
        order = row[6]
        present = row[7]

        # Only root queries, only present modules
        if label == 'A' and present:
            modules_by_kw[source_kw].append({
                'module': module,
                'order': order
            })

    data['serp_modules_by_keyword'] = {
        kw: sorted(mods, key=lambda x: x['order'])
        for kw, mods in modules_by_kw.items()
    }

    # ─────────────────────────────────────────────
    # BLOCK 10: Tool-Generated Strategic Recommendations
    # Purpose: Pre-generated recommendations to be EVALUATED, not
    # blindly trusted. These come from a hard-coded pattern-matching
    # system that scans for trigger words in the SERP data. The
    # patterns and trigger words are pre-defined, not derived from
    # the current data.
    # ─────────────────────────────────────────────
    ws = wb['Strategic_Recommendations']
    recs = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        recs.append({
            'pattern_name': row[0],
            'trigger_words_searched_for': row[1],
            'status_quo_message': row[2],
            'reframe': row[3],
            'content_angle': row[4],
            'triggers_actually_found': row[5]
        })
    data['tool_generated_recommendations'] = recs

    # ─────────────────────────────────────────────
    # BLOCK 11: Competitor Ads (if any)
    # Purpose: Signals paid competition in the keyword space.
    # ─────────────────────────────────────────────
    ws = wb['Competitors_Ads']
    ads = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        ads.append({
            'keyword': row[0],
            'advertiser': row[7],
            'position': row[9],
            'link': row[10]
        })
    data['competitor_ads'] = ads

    # ─────────────────────────────────────────────
    # Intentionally skipped sheets:
    # - Derived_Expansions: usually empty
    # - Rich_Features: rarely populated for local-intent queries
    # - Parsing_Warnings: diagnostic data, not analytical
    # - AIO_Logs: latency/timing data, not analytical
    # - Help: documentation for the spreadsheet tool
    # ─────────────────────────────────────────────

    wb.close()
    return data
```

### Output Size Estimate

With 6 root keywords × 3 variants each (18 queries), the extracted JSON
is approximately 165,000 characters compact (210,000 with indent=2). The
three largest contributors are AI Overview text (~32K), organic snippets
(~25K), and PAA snippets (~24K). This fits in a single API call using
Sonnet's 200K context window. For larger keyword sets, see "Compression
Strategies" in Part 3.

---

---

## Prompt Files

Prompt assets now live in:

- `prompts/main_report/system.md`
- `prompts/main_report/user_template.md`
- `prompts/advisory/system.md`
- `prompts/advisory/user_template.md`
- `prompts/correction/user_template.md`

For legacy reference, the combined prompt and extraction document remains in `serp_analysis_prompt_v3.md`.

## Part 3: Implementation Notes

### Populating the User Prompt

For Living Systems, the template variables would be:

```python
client_context = {
    "CLIENT_NAME": "Living Systems Counselling",
    "CLIENT_DOMAIN": "livingsystems.ca",
    "CLIENT_NAME_PATTERNS": ["Living Systems"],  # for AIO text matching
    "ORG_TYPE": "Small nonprofit counselling organization, established 1971",
    "LOCATION": "North Vancouver, BC, Canada",
    "FRAMEWORK_DESCRIPTION": (
        "Bowen Family Systems Theory. Core concepts include: differentiation "
        "of self, emotional cutoff, triangles, nuclear family emotional "
        "process, multigenerational transmission process, and societal "
        "emotional process. The approach emphasizes understanding emotional "
        "systems rather than diagnosing pathology. Key differentiator: views "
        "symptoms like estrangement, anxiety, and conflict as products of "
        "the relationship system, not individual dysfunction."
    ),
    "CONTENT_FOCUS": (
        "Counselling services (individual, couple, family), Bowen Theory "
        "training programs, professional conferences, and educational "
        "content about family emotional systems."
    ),
    "ADDITIONAL_CONTEXT": (
        "The organization serves two audiences: (1) local counselling "
        "clients in Greater Vancouver seeking therapy, and (2) a broader "
        "professional/educational audience interested in Bowen Theory "
        "training and concepts. Budget is limited. The organization does "
        "NOT offer court-mandated reunification programs or government-"
        "contracted family preservation services."
    ),
}
```

### API Call Configuration

```python
import json
import anthropic


def run_analysis(
    xlsx_path: str,
    client_context: dict,
    system_prompt: str,
    user_prompt_template: str,
) -> str:
    """
    Full pipeline: extract data from spreadsheet and run LLM analysis.
    """
    # Step 1: Extract data from spreadsheet
    extracted_data = extract_analysis_data(
        xlsx_path=xlsx_path,
        client_domain=client_context['CLIENT_DOMAIN'],
        client_name_patterns=client_context.get('CLIENT_NAME_PATTERNS'),
    )

    # Step 2: Validate extraction
    warnings = validate_extraction(extracted_data)
    additional_context = client_context.get('ADDITIONAL_CONTEXT', '')
    if warnings:
        additional_context += (
            '\n\nData extraction warnings:\n'
            + '\n'.join(f'- {w}' for w in warnings)
        )

    # Step 3: Build the user prompt
    root_kw_count = len(extracted_data.get('root_keywords', []))
    user_prompt = user_prompt_template.replace(
        '{{CLIENT_NAME}}', client_context['CLIENT_NAME']
    ).replace(
        '{{CLIENT_DOMAIN}}', client_context['CLIENT_DOMAIN']
    ).replace(
        '{{ORG_TYPE}}', client_context['ORG_TYPE']
    ).replace(
        '{{LOCATION}}', client_context['LOCATION']
    ).replace(
        '{{FRAMEWORK_DESCRIPTION}}', client_context['FRAMEWORK_DESCRIPTION']
    ).replace(
        '{{CONTENT_FOCUS}}', client_context['CONTENT_FOCUS']
    ).replace(
        '{{ADDITIONAL_CONTEXT}}', additional_context or 'None provided.'
    ).replace(
        '{{QUERY_COUNT}}', str(len(extracted_data['queries']))
    ).replace(
        '{{ROOT_KEYWORD_COUNT}}', str(root_kw_count)
    ).replace(
        '{{GEO_LOCATION}}', client_context['LOCATION']
    ).replace(
        '{{COLLECTION_DATE}}',
        extracted_data.get('metadata', {}).get('created_at', 'unknown')
    ).replace(
        '{{EXTRACTED_DATA_JSON}}',
        json.dumps(extracted_data, separators=(',', ':'), default=str)
    )

    # Step 4: Call the API
    client = anthropic.Anthropic()
    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=16000,
        system=system_prompt,
        messages=[{'role': 'user', 'content': user_prompt}]
    )

    return response.content[0].text


# Usage:
# report = run_analysis(
#     xlsx_path='market_analysis_v2.xlsx',
#     client_context=client_context,     # dict defined above
#     system_prompt=SYSTEM_PROMPT,       # string from Part 2
#     user_prompt_template=USER_PROMPT,  # string from Part 2
# )
```

### Key Implementation Details

**JSON serialization:** Use `separators=(',', ':')` instead of
`indent=2`. Indentation adds ~20% more characters (measured: ~43K chars
on 18 queries) for zero analytical benefit. The LLM parses compact
JSON without issue.

**Template substitution:** The example above uses simple `.replace()`
calls. If you prefer, use `str.format()` or Jinja2, but be aware that
`str.format()` will choke on the literal `{` and `}` characters inside
the JSON. `.replace()` with `{{PLACEHOLDER}}` double-brace syntax
avoids this.

**Model choice:** Sonnet is adequate for this task and substantially
cheaper. Opus would produce marginally better analysis of the tool-
generated recommendations (Section 6) but the cost difference is
significant for routine runs.

### Token Budget Estimates

| Component | Approximate Characters | Approximate Tokens |
|---|---|---|
| System prompt (with data dictionary) | ~8,000 | ~2,500 |
| Client context | ~1,500 | ~500 |
| Extracted data JSON (18 queries, compact) | ~165,000 | ~45,000 |
| Output (full report) | ~25,000 | ~8,000–14,000 |
| **Total** | | **~56,000–62,000** |

The largest data contributors are AI Overview text (~32K chars),
organic result snippets (~25K chars), and PAA snippets (~24K chars).
To reduce input size, see "Compression Strategies" below.

This fits within Sonnet's 200K context window with margin.
For Haiku, which has a smaller effective context, apply at least
strategies 1 and 4 below.

### Compression Strategies for Larger Keyword Sets

At 18 queries the compact JSON is ~165K chars. Scaling to 30+ root
keywords (90+ queries) would exceed 400K. Apply these in order:

1. **Truncate AI Overview text** — reduce from 2000 to 500 chars per
   query. Saves ~24K for 18 queries. The LLM still gets the opening
   framing; AIO citations (a separate data block) carry the source data.
2. **Remove organic snippets** — set snippet to None in the extraction.
   Title + source + entity_type is sufficient for competitive analysis.
   Saves ~25K for 18 queries.
3. **Trim PAA snippets** — reduce from 200 to 80 chars, or remove
   entirely (the question text is the primary signal). Saves ~18K.
4. **Collapse variant queries** — for A.1/A.2 queries, omit the full
   query entry from the queries list and include only their AIO citation
   data (the root query A is more representative of SERP composition).
5. **Aggregate language patterns** — top 30 bigrams, top 15 trigrams.
6. **Split into multiple calls** — run one analysis per keyword cluster,
   then a synthesis call that takes all cluster analyses as input.

### What This Prompt Does NOT Do

This prompt produces a strategic analysis report. It does NOT generate:

- Content briefs or blog outlines
- Blog post drafts
- SEO metadata or title tags
- Schema markup

If you want improved content briefs, make a second API call that takes
the analysis report as input and generates briefs. Keep analysis and
generation as separate steps. Combining them in one call produces the
generic template problem visible in the current tool output — the LLM
optimizes for generating plausible-looking briefs rather than doing
rigorous analysis.

---

## Part 4: Iteration and Calibration

### Comparing Runs

When your tool collects new SERP data (e.g., monthly), include the
previous analysis summary as additional context in the user prompt:

```
## Previous Analysis Summary (from {{PREVIOUS_DATE}})

{{PREVIOUS_ANALYSIS_KEY_FINDINGS}}

## Changes Since Last Run

- New keywords added: {{NEW_KEYWORDS}}
- Keywords removed: {{REMOVED_KEYWORDS}}
- Content published since last run: {{NEW_CONTENT_URLS}}
- Known external changes: {{KNOWN_CHANGES}}
```

This lets the LLM identify trends, assess whether previous
recommendations had visible effect (if the client acted on them),
and adjust priorities accordingly.

### Calibration Feedback Loop

After reviewing the LLM output and deciding what to act on, record:

- Which recommendations you accepted and why
- Which you rejected and why
- What the LLM missed that you spotted manually

Feed this back as additional context in future runs. Over 3-4 cycles
this calibrates the analysis toward your actual decision-making criteria
and domain knowledge.

### Validating Extraction Output

Before sending the extracted data to the API, run a basic sanity check:

```python
def validate_extraction(data: dict) -> list[str]:
    """Return a list of warnings about the extracted data."""
    warnings = []

    # Check that root keywords are present
    if not data.get('root_keywords'):
        warnings.append('No root keywords extracted.')

    # Check that organic results exist for each root keyword
    for kw in data.get('root_keywords', []):
        if kw not in data.get('organic_results_by_keyword', {}):
            warnings.append(f'No organic results for root keyword: {kw}')

    # Check for empty client appearances (URL-based detection)
    url_client = (
        len(data.get('client_organic_appearances', []))
        + len(data.get('client_aio_citations', []))
        + len(data.get('client_local_pack_appearances', []))
    )
    # Check for AIO text mentions (name-based detection)
    aio_text_mentions = sum(
        1 for q in data.get('queries', [])
        if q.get('client_mentioned_in_aio_text')
    )
    if url_client == 0 and aio_text_mentions == 0:
        warnings.append(
            'Client not found anywhere in the data (neither domain '
            'in URLs nor name in AI Overview text). Verify '
            'client_domain and client_name_patterns are correct.'
        )

    # Check AIO coverage
    queries_with_aio = sum(
        1 for q in data.get('queries', []) if q.get('has_ai_overview')
    )
    total_queries = len(data.get('queries', []))
    if total_queries > 0 and queries_with_aio == 0:
        warnings.append('No queries triggered AI Overviews.')

    # Check for suspiciously low PAA count
    paa_count = len(data.get('paa_questions', []))
    if paa_count < 5:
        warnings.append(
            f'Only {paa_count} unique PAA questions found. '
            f'Data may be incomplete.'
        )

    # Check entity classification coverage
    summary = data.get('organic_summary', {})
    total = summary.get('total_rows', 0)
    unclassified = summary.get('entity_unclassified_count', 0)
    if total > 0 and unclassified / total > 0.4:
        warnings.append(
            f'{unclassified}/{total} organic results '
            f'({unclassified/total:.0%}) have unclassified entity '
            f'type. Entity distribution data is based on the '
            f'classified minority only.'
        )

    return warnings
```

Append any warnings to the ADDITIONAL_CONTEXT section of the user
prompt so the LLM can account for data limitations in its analysis.
