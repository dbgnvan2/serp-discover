# Task: Fix Three Bugs and Regenerate Prompt Spec

## Files to Modify

- `generate_content_brief.py` — extraction code and report generation
- `serp_analysis_prompt_v3.md` — system prompt and data dictionary sent to the LLM

## Test Data

- JSON input: `market_analysis_v2.json`
- Client domain: `livingsystems.ca`
- Client name patterns: `['Living Systems']`
- Config: `config.yml`

After each fix, run the extraction and verify the change:

```bash
python generate_content_brief.py --json market_analysis_v2.json --list --config config.yml
```

---

## Fix 1: Trigger Word Parsing Bug (CRITICAL)

### Problem

`_parse_trigger_words()` on line 177 assumes input is a comma-separated
string. But when reading from the JSON file, the `Triggers` field is
already a Python list (e.g., `['clinical', 'registered', 'diagnosis']`).

Calling `str()` on a list produces `"['clinical', 'registered', ...]"`
and splitting on commas yields garbage tokens like `"['clinical'"` with
brackets and quotes embedded. These mangled tokens match nothing.

### Impact

All four `tool_recommendations_verified` entries show:
- `total_trigger_occurrences: 0`
- `primary_evidence_source: "none"`
- All six `triggers_found` sub-dicts are empty

The correct values (verified by running matching directly against the
JSON with properly parsed triggers) are:
- Medical Model Trap: 32 total occurrences
- Fusion Trap: 16 total occurrences  
- Resource Trap: 14 total occurrences
- Blame/Reactivity Trap: 4 total occurrences

This also breaks `autocomplete_summary.trigger_word_hits` because
`all_trigger_words` (line 538) is populated from the same mangled
tokens.

### Fix

Change `_parse_trigger_words` to handle both list and string input:

```python
def _parse_trigger_words(trigger_text):
    if isinstance(trigger_text, list):
        return [str(t).strip().lower() for t in trigger_text if str(t).strip()]
    return [part.strip().lower() for part in str(trigger_text or "").split(",") if part.strip()]
```

### Verification

After fix, run extraction and check:

```python
for rec in extracted['tool_recommendations_verified']:
    total = rec['verdict_inputs']['total_trigger_occurrences']
    primary = rec['verdict_inputs']['primary_evidence_source']
    print(f"{rec['pattern_name']}: {total} occurrences, source: {primary}")
```

Expected output (approximately):
```
The Medical Model Trap: 32 occurrences, source: in_organic_snippets
The Fusion Trap: 16 occurrences, source: in_organic_snippets
The Resource Trap: 14 occurrences, source: in_organic_snippets
The Blame/Reactivity Trap: 4 occurrences, source: in_aio_text
```

None of the totals should be zero. `autocomplete_summary.trigger_word_hits`
should show at least `"free": ["free reunification therapy near me"]`
instead of all empty lists.

---

## Fix 2: Local Pack Confirmed/Absent Misclassification

### Problem

`serp_local_pack_confirmed` (line 470-473) is set based on whether the
`Local_Pack_and_Maps` sheet has data for a keyword. This data comes from
a separate Google Maps API fetch that runs for all keywords regardless of
whether a local pack actually appears on the SERP page.

The SERP_Modules sheet shows `local_results` and `local_map` modules
only for "family cutoff counselling Vancouver" and "reunification therapy
near me". But the current code marks all 6 keywords as "confirmed"
because all 6 have some Maps data.

This causes `has_local_pack` in keyword_profiles to be `True` for
keywords like "estrangement" where no local pack appears on the actual
Google results page.

### Fix

After building `modules_by_kw`, cross-reference to determine which
keywords have a local pack visible on the SERP. Change the local pack
summary construction to:

```python
# Determine which keywords show local pack on the actual SERP page
serp_has_local = set()
for kw in root_keywords:
    for mod in modules_by_kw.get(kw, []):
        if mod.get("module") in ("local_results", "local_map", "local_pack"):
            serp_has_local.add(kw)
            break

for kw in root_keywords:
    rows = local_rows_by_kw.get(kw, [])
    if rows:
        # ... existing summary building code ...
        local_pack_summary[kw] = {
            "total_businesses": len(rows),
            "top_categories": category_counter.most_common(5),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "client_present": client_present,
            "on_serp": kw in serp_has_local,  # NEW: distinguishes Maps data from SERP visibility
        }
    # ... rest of loop ...

local_pack_summary["serp_local_pack_confirmed"] = sorted(serp_has_local)
local_pack_summary["serp_local_pack_absent"] = sorted(kw for kw in root_keywords if kw not in serp_has_local)
```

Also update `has_local_pack` in keyword_profiles to use the SERP module
check instead of the Maps data check:

```python
"has_local_pack": kw in serp_has_local,
```

Note: `modules_by_kw` must be built BEFORE the local pack section. Check
that the code order in `extract_analysis_data_from_json` has the SERP
modules block before the local pack block. If not, reorder them.

### Verification

After fix:
```python
lps = extracted['local_pack_summary']
print(f"SERP confirmed: {lps['serp_local_pack_confirmed']}")
print(f"SERP absent: {lps['serp_local_pack_absent']}")
```

Expected:
```
SERP confirmed: ['family cutoff counselling Vancouver', 'reunification therapy near me']
SERP absent: ['estrangement', 'estrangement from adult children', 'estrangement grief', 'reunification counselling BC']
```

And in keyword_profiles:
```python
for kw, profile in extracted['keyword_profiles'].items():
    print(f"{kw}: has_local_pack={profile['has_local_pack']}")
```

Expected: only "family cutoff counselling Vancouver" and
"reunification therapy near me" show `True`.

---

## Fix 3: Regenerate Prompt Spec Data Dictionary

### Problem

`serp_analysis_prompt_v3.md` still describes the old extraction output.
The system prompt's "Data Structure Reference" section references keys
that no longer exist:

- `organic_results_by_keyword` → now `keyword_profiles` and `competitive_landscape`
- `client_organic_appearances` → now `client_position.organic`
- `client_aio_citations` → now `client_position.aio_citations`
- `client_local_pack_appearances` → now `client_position.local_pack`
- `paa_questions` → now `paa_analysis.cross_cluster` and `paa_analysis.single_cluster`

The LLM receives a system prompt describing one data structure and JSON
containing a different one.

### Fix

Rewrite the "Data Structure Reference" section in the system prompt
(inside the first code block after `### System Prompt`) to document the
actual keys produced by `extract_analysis_data_from_json()`. The keys
and their structure are:

```
metadata                      - run_id, created_at, google_url_sample
root_keywords                 - list of 6 root keyword strings
queries                       - list of 6 query dicts (source_keyword, query_label, total_results, has_ai_overview, etc.)
organic_summary               - total_rows, entity_classified_count, entity_unclassified_count
source_frequency_top30        - [["source", count], ...] across all queries
content_type_distribution     - [["type", count], ...]
rank_deltas_top20             - biggest rank changes, each with source_keyword, delta, source, title

paa_analysis                  - PRE-COMPUTED cross-cluster analysis:
  .cross_cluster              - questions appearing for 2+ keywords, with cluster_count and combined_total_results
  .single_cluster             - questions appearing for 1 keyword only, with combined_total_results
  .summary                    - total_unique_questions, cross_cluster_count, single_cluster_count

tool_recommendations_verified - PRE-VERIFIED trigger evidence for each tool recommendation:
  .triggers_found             - separate counts per data source (in_paa_questions, in_organic_titles, in_organic_snippets, in_aio_text, in_autocomplete, in_related_searches)
  .verdict_inputs             - any_paa_evidence, any_autocomplete_evidence, total_trigger_occurrences, primary_evidence_source

client_position               - PRE-COMPUTED client vulnerability assessment:
  .organic                    - each appearance with rank, rank_delta, stability ("new"/"stable"/"improving"/"declining"), competitors_above list
  .aio_citations              - each citation with also_mentioned_in_aio_text flag and excerpt
  .aio_text_mentions          - each AIO body text mention with excerpt
  .local_pack                 - client local pack appearances
  .language_pattern_mentions  - client name in SERP bigram/trigram patterns
  .summary                    - total counts, keywords_with_any_visibility, keywords_with_zero_visibility, has_declining_positions, worst_delta

keyword_profiles              - one unified profile per root keyword:
  .total_results, .serp_modules, .has_ai_overview, .has_local_pack, .has_discussions_forums
  .entity_distribution, .entity_dominant_type
  .top5_organic, .aio_citation_count, .aio_top_sources
  .paa_questions (list of question strings), .paa_count
  .autocomplete_top10, .related_searches
  .local_pack_count
  .client_visible, .client_rank, .client_rank_delta, .client_aio_cited

competitive_landscape         - per keyword: total_organic_results, entity_breakdown, top_sources (with appearances, best_rank, entity_type), content_type_breakdown

aio_analysis                  - per keyword: has_aio, sources_named_in_text, client_mentioned, client_excerpt, key_phrases, opening_excerpt
aio_citations_top25           - [["source", count], ...]
aio_total_citations           - int
aio_unique_sources            - int

autocomplete_by_keyword       - raw autocomplete suggestions per keyword
related_searches_by_keyword   - related search terms per keyword
autocomplete_summary          - total_suggestions, by_keyword counts, trigger_word_hits per trigger

local_pack_summary            - per keyword: total_businesses, top_categories, avg_rating, client_present, on_serp
                                also: serp_local_pack_confirmed, serp_local_pack_absent

market_language               - top_20_bigrams, top_10_trigrams, client_mentions, bowen_theory_terms (with explicit zero counts)
competitor_ads                - any Google Ads found
```

Also add this principle to the "Your Analytical Principles" section:

```
9. EVIDENCE DISCIPLINE. The data contains pre-verified facts computed
   deterministically from raw SERP data. Use these pre-computed values
   exactly as provided. Specifically:
   - PAA questions: Only reference questions that appear verbatim in
     paa_analysis.cross_cluster or paa_analysis.single_cluster. Never
     paraphrase, combine, or invent questions. If citing a cross-cluster
     question, state the exact cluster_count and combined_total_results.
   - Trigger verification: When evaluating tool recommendations, use the
     triggers_found sub-dicts to state exactly where evidence was found.
     Do not claim triggers appear "in PAA questions" if
     triggers_found.in_paa_questions is empty.
   - Client stability: Use the pre-computed stability field ("new",
     "stable", "improving", "declining"). Do not reinterpret rank_delta
     values. "new" means no prior data exists — it does NOT mean stable.
   - Local pack: Only state a local pack appears on the SERP if
     has_local_pack is true in keyword_profiles (this is verified against
     SERP modules). local_pack_summary may contain Maps data for keywords
     where no local pack appears on the actual search page.
   - Counts: Use exact numbers from the data. Do not round, estimate, or
     say "multiple" when the count is 1.
```

Also update the Section 3 description to add:

```
If any client positions show stability="declining", assess the risk
this poses and whether defensive action (updating/optimizing existing
content) should take priority over creating new content.
```

### Verification

After updating the prompt spec, confirm that:

1. Every key in the extraction output is documented in the data dictionary.
2. No old keys (organic_results_by_keyword, client_organic_appearances,
   etc.) are referenced anywhere in the system prompt.
3. The `load_prompt_blocks()` function in the Python script still
   correctly extracts the system prompt and user template from the
   updated markdown file.

Run a quick test:

```python
system_prompt, user_template = load_prompt_blocks("serp_analysis_prompt_v3.md")
assert system_prompt is not None, "System prompt extraction failed"
assert user_template is not None, "User template extraction failed"
assert "organic_results_by_keyword" not in system_prompt, "Old key still referenced"
assert "paa_analysis" in system_prompt, "New key missing"
assert "EVIDENCE DISCIPLINE" in system_prompt, "New principle missing"
print("Prompt spec validation passed")
```

---

## Fix 4 (Minor): LLM Max Tokens Default

Change line 1215:

```python
parser.add_argument("--llm-max-tokens", type=int, default=16000)
```

The current default of 12000 risks truncating the 8-section report.

---

## Final Validation

After all fixes, run the full extraction and confirm:

```python
import json
extracted = extract_analysis_data_from_json(data, 'livingsystems.ca', ['Living Systems'], ...)

# Trigger verification works
assert extracted['tool_recommendations_verified'][0]['verdict_inputs']['total_trigger_occurrences'] > 0, \
    "Medical Model Trap still shows zero triggers"

# Local pack correctly separated
lps = extracted['local_pack_summary']
assert 'estrangement' not in lps['serp_local_pack_confirmed'], \
    "estrangement should not have SERP local pack"
assert 'family cutoff counselling Vancouver' in lps['serp_local_pack_confirmed'], \
    "family cutoff should have SERP local pack"

# Keyword profiles match
for kw in ['estrangement', 'estrangement grief', 'estrangement from adult children']:
    assert extracted['keyword_profiles'][kw]['has_local_pack'] == False, \
        f"{kw} should not have local pack"

# Client position unchanged
assert extracted['client_position']['summary']['worst_delta'] == -3
assert extracted['client_position']['organic'][0]['stability'] == 'declining'

# Compact size still reasonable
size = len(json.dumps(extracted, separators=(',', ':'), default=str))
assert size < 70000, f"JSON too large: {size}"
print(f"All checks passed. JSON size: {size:,} chars")
```
