# Revised Main Report User Template

## user_template.md

```md
## Task

Produce the market intelligence report specified in your system
instructions. Work through the payload in this order:

1. Read strategic_flags first — these set the priority frame.
2. Read client_position — this establishes what to defend.
3. Read keyword_profiles one keyword at a time for Section 2.
4. Read paa_analysis and aio_analysis for Sections 4–5.
5. Read tool_recommendations_verified last, for Section 6 only.

Do not reorganize your analysis around the tool recommendations.
They are assessment targets, not the report's organizing structure.

## Client Context (background — not evidence)

Organization: {{CLIENT_NAME}}
Website: {{CLIENT_DOMAIN}}
Type: {{ORG_TYPE}}
Location: {{LOCATION}}
Theoretical framework: {{FRAMEWORK_DESCRIPTION}}
Content focus: {{CONTENT_FOCUS}}

This context describes the client's background and services. Use it
to assess fit between opportunities and the client's capabilities.
Do not treat it as SERP evidence — it tells you who the client is,
not what the data shows.

## Additional Context

{{ADDITIONAL_CONTEXT}}

Treat this as operational constraints (budget, audience scope,
service boundaries). If data extraction warnings appear here,
note them in Section 1 and adjust confidence accordingly.

## SERP Analysis Data

Pre-processed and pre-verified SERP data from {{QUERY_COUNT}}
queries across {{ROOT_KEYWORD_COUNT}} root keywords, geolocated
to {{GEO_LOCATION}}, collected on {{COLLECTION_DATE}}.

All counts, cross-references, stability classifications, and
priority orderings in this payload are deterministic — computed
by code, not estimated. Use them as given. If a field is empty
or zero, that is a verified absence, not missing data.

<serp_data>
{{EXTRACTED_DATA_JSON}}
</serp_data>
```


---

## Rationale for Structural Changes

### 1. Added explicit processing order
The current template says "Analyze this data and produce the market intelligence report" — a single instruction that lets the LLM start anywhere. In practice it starts with whatever is narratively interesting, which is usually the trap recommendations. The new template specifies a reading order: strategic flags → client position → keyword profiles → PAA/AIO → tool recommendations last. This mirrors the report section order and ensures the LLM has the priority frame and defensive context before encountering the recommendation hypotheses.

### 2. Separated client context from evidence
The current template places client context and SERP data in the same undifferentiated flow. The LLM has treated the framework description ("Bowen Family Systems Theory... differentiation of self, emotional cutoff, triangles...") as a source of analytical concepts to search for in the data, leading to claims like "differentiation of self appears 0 times — this gap aligns perfectly with Living Systems' framework." That's using the client context as an analytical lens rather than keeping it as background.

The new template explicitly labels client context as "background — not evidence" and the additional context as "operational constraints." The SERP data section explicitly states these are "pre-verified" and "deterministic — computed by code, not estimated."

### 3. Added the "do not reorganize around tool recommendations" instruction
This is the user-template counterpart to the system prompt's demotion of tool_recommendations_verified. The system prompt says they're appendix material; the user template says "read them last, for Section 6 only." Together these create two barriers against the recommendations becoming the narrative spine.

### 4. Added "verified absence" framing for empty fields
The previous template didn't address how to handle zeros and empty arrays. The LLM would encounter an empty paa_questions list for a keyword and either skip it silently or fill the gap with questions from other keywords. The new template states: "If a field is empty or zero, that is a verified absence, not missing data." This pairs with the system prompt's Rule 8 (absent evidence is stated, not invented).

### 5. Kept the template concise
The temptation was to add per-section instructions here, duplicating the system prompt. I avoided this — the user template's job is to frame the data and the task, not to re-specify the report structure. The processing order is the only structural guidance added, and it's five lines.

---

## Placeholder Changes

None. All existing placeholders are preserved exactly:
- `{{CLIENT_NAME}}`, `{{CLIENT_DOMAIN}}`, `{{ORG_TYPE}}`, `{{LOCATION}}`
- `{{FRAMEWORK_DESCRIPTION}}`, `{{CONTENT_FOCUS}}`, `{{ADDITIONAL_CONTEXT}}`
- `{{QUERY_COUNT}}`, `{{ROOT_KEYWORD_COUNT}}`, `{{GEO_LOCATION}}`, `{{COLLECTION_DATE}}`
- `{{EXTRACTED_DATA_JSON}}`

The double-brace `{{}}` format and `<serp_data>` XML wrapper are unchanged. The template remains compatible with the existing `build_user_prompt()` loader in `generate_content_brief.py`.
