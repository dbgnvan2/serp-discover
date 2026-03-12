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
