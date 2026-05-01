# Prompt Iteration Package: Main Report User Template

## Objective

Rewrite the main report user template so it gives the model the right context with less ambiguity and less room for over-reading the payload.

## Current Prompt File

- [`prompts/main_report/user_template.md`](/Users/davemini2/ProjectsLocal/serp/prompts/main_report/user_template.md)

## Current Prompt Text

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

## Shared Evidence Bundle

Use these files with this package if your chatbot tool supports multiple attachments:

- [`extracted_payload_summary_estrangement_20260311_1733.json`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/extracted_payload_summary_estrangement_20260311_1733.json)
- [`extracted_payload_estrangement_20260311_1733.json`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/extracted_payload_estrangement_20260311_1733.json)
- [`failed_main_report_draft_20260311_1737.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/failed_main_report_draft_20260311_1737.md)
- [`reference_main_report_20260311_1554.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/reference_main_report_20260311_1554.md)
- [`reference_advisory_20260311_1554.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/reference_advisory_20260311_1554.md)

Use the summary JSON first. Only inspect the full extracted payload if you need field-level detail.


## Representative Data Summary

Use this fixed summary snapshot while iterating the prompt so prompt changes are evaluated against stable evidence.

```json
{
  "run_id": "20260311_173328",
  "root_keywords": [
    "estrangement",
    "estrangement from adult children",
    "estrangement grief",
    "family cutoff counselling Vancouver",
    "reunification counselling BC",
    "reunification therapy near me"
  ],
  "query_count": 6,
  "aio_total_citations": 88,
  "client_position_summary": {
    "total_organic_appearances": 1,
    "total_aio_citations": 0,
    "total_aio_text_mentions": 0,
    "total_local_pack": 0,
    "keywords_with_any_visibility": [
      "family cutoff counselling Vancouver"
    ],
    "keywords_with_zero_visibility": [
      "estrangement",
      "estrangement from adult children",
      "estrangement grief",
      "reunification counselling BC",
      "reunification therapy near me"
    ],
    "has_declining_positions": true,
    "worst_delta": -3
  },
  "strategic_flags": {
    "defensive_urgency": "high",
    "defensive_detail": "Client's content 'Can cutting off family be good therapy?' dropped 3 positions to rank #7 for 'family cutoff counselling Vancouver'. This page provides 0 of the client's AIO citations. If organic rank continues declining, AIO citation loss is probable.",
    "visibility_concentration": "critical",
    "concentration_detail": "Client visible for 1 of 6 tracked keywords ('family cutoff counselling Vancouver'). 100% of organic and AIO visibility depends on a single keyword cluster.",
    "opportunity_scale": {
      "estrangement": {
        "total_results": 231000,
        "client_rank": null,
        "client_trend": null,
        "action": "enter_cautiously",
        "reason": "Legal entities dominate this SERP. Entry requires differentiated content that avoids competing on legal topics directly."
      },
      "estrangement from adult children": {
        "total_results": 16400,
        "client_rank": null,
        "client_trend": null,
        "action": "enter",
        "reason": "16,400 total results. Client has no current visibility. Dominant entity type: counselling."
      },
      "estrangement grief": {
        "total_results": 31700,
        "client_rank": null,
        "client_trend": null,
        "action": "enter",
        "reason": "31,700 total results. Client has no current visibility. Dominant entity type: counselling."
      },
      "family cutoff counselling Vancouver": {
        "total_results": 686000,
        "client_rank": 7,
        "client_trend": "declining",
        "action": "defend",
        "reason": "Client ranks #7, declined 3 positions. Protect existing visibility before expanding elsewhere."
      },
      "reunification counselling BC": {
        "total_results": 91,
        "client_rank": null,
        "client_trend": null,
        "action": "skip",
        "reason": "Only 91 total results. Market too small to justify dedicated content investment."
      },
      "reunification therapy near me": {
        "total_results": 15300,
        "client_rank": null,
        "client_trend": null,
        "action": "enter",
        "reason": "15,300 total results. Client has no current visibility. Dominant entity type: counselling."
      }
    },
    "content_priorities": [
      {
        "action": "defend",
        "keyword": "family cutoff counselling Vancouver",
        "total_results": 686000,
        "reason": "Client ranks #7, declined 3 positions. Protect existing visibility before expanding elsewhere."
      },
      {
        "action": "enter",
        "keyword": "estrangement grief",
        "total_results": 31700,
        "reason": "31,700 total results. Client has no current visibility. Dominant entity type: counselling."
      },
      {
        "action": "enter",
        "keyword": "estrangement from adult children",
        "total_results": 16400,
        "reason": "16,400 total results. Client has no current visibility. Dominant entity type: counselling."
      },
      {
        "action": "enter",
        "keyword": "reunification therapy near me",
        "total_results": 15300,
        "reason": "15,300 total results. Client has no current visibility. Dominant entity type: counselling."
      },
      {
        "action": "enter_cautiously",
        "keyword": "estrangement",
        "total_results": 231000,
        "reason": "Legal entities dominate this SERP. Entry requires differentiated content that avoids competing on legal topics directly."
      },
      {
        "action": "skip",
        "keyword": "reunification counselling BC",
        "total_results": 91,
        "reason": "Only 91 total results. Market too small to justify dedicated content investment."
      }
    ],
    "top_cross_cluster_paa": {
      "question": "How do I reach out to an estranged adult child?",
      "cluster_count": 2,
      "combined_total_results": 247400
    }
  },
  "paa_cross_cluster": [
    {
      "question": "How do I reach out to an estranged adult child?",
      "source_keywords": [
        "estrangement",
        "estrangement from adult children"
      ],
      "cluster_count": 2,
      "combined_total_results": 247400,
      "category": "General"
    },
    {
      "question": "When should you stop reaching out to an estranged child?",
      "source_keywords": [
        "estrangement",
        "estrangement from adult children"
      ],
      "cluster_count": 2,
      "combined_total_results": 247400,
      "category": "General"
    },
    {
      "question": "What should I expect in reunification therapy?",
      "source_keywords": [
        "reunification counselling BC",
        "reunification therapy near me"
      ],
      "cluster_count": 2,
      "combined_total_results": 15391,
      "category": "General"
    }
  ],
  "keyword_profiles_excerpt": {
    "estrangement": {
      "total_results": 231000,
      "entity_distribution": {
        "counselling": 5,
        "legal": 12,
        "nonprofit": 2,
        "directory": 1,
        "professional_association": 1,
        "government": 2,
        "media": 1
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": false,
      "paa_questions": [
        "How do I reach out to an estranged adult child?",
        "How long does the average family estrangement last?",
        "When should you stop reaching out to an estranged child?",
        "When to go no-contact with a family member?"
      ],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "Family Estrangement Therapy in Victoria, Vancouver & Kelowna",
          "source": "estrangedfamilytherapy.com",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 1,
          "title": "Laws on Parental Alienation in BC",
          "source": "Pathway Legal Family Lawyers",
          "entity_type": "legal",
          "content_type": "guide"
        },
        {
          "rank": 2,
          "title": "Family Estrangement Counselling for Parents & Children",
          "source": "Restored Hope Counselling Services",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "British Columbia \u2013 CCMF",
          "source": "Men and Families",
          "entity_type": "nonprofit",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Court allows disinheritance of estranged children",
          "source": "Clark Wilson LLP",
          "entity_type": "legal",
          "content_type": "news"
        }
      ]
    },
    "estrangement from adult children": {
      "total_results": 16400,
      "entity_distribution": {
        "counselling": 6,
        "legal": 4,
        "directory": 3,
        "media": 6,
        "education": 1
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": false,
      "paa_questions": [
        "How do I reach out to an estranged adult child?",
        "How long does parent-child estrangement usually last?",
        "Should you leave inheritance to an estranged child?",
        "When should you stop reaching out to an estranged child?"
      ],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "Family Estrangement Therapy in Victoria, Vancouver & Kelowna",
          "source": "estrangedfamilytherapy.com",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 1,
          "title": "Family estrangements rise in Canada due to social, cultural ...",
          "source": "Canadian Affairs",
          "entity_type": "media",
          "content_type": "news"
        },
        {
          "rank": 1,
          "title": "Those of you who are estranged from your children, what ...",
          "source": "Reddit \u00b7 r/AskOldPeople",
          "entity_type": "media",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Family Estrangement Counselling for Parents & Children",
          "source": "Restored Hope Counselling Services",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Tina Gilbertson, LPC",
          "source": "LinkedIn \u00b7 Tina Gilbertson",
          "entity_type": "N/A",
          "content_type": "other"
        }
      ]
    },
    "estrangement grief": {
      "total_results": 31700,
      "entity_distribution": {
        "nonprofit": 3,
        "government": 2,
        "directory": 4,
        "counselling": 7,
        "media": 1
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": false,
      "paa_questions": [],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "British Columbia Bereavement Helpline - Homepage New",
          "source": "British Columbia Bereavement Helpline",
          "entity_type": "nonprofit",
          "content_type": "news"
        },
        {
          "rank": 1,
          "title": "Grieving in the Age of Estrangement and Division",
          "source": "The Tyee",
          "entity_type": "N/A",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "After a Death: Get Support When Someone Dies - Gov.bc.ca",
          "source": "gov.bc.ca",
          "entity_type": "government",
          "content_type": "guide"
        },
        {
          "rank": 2,
          "title": "Death of estranged parent : r/legaladvicecanada",
          "source": "Reddit \u00b7 r/legaladvicecanada",
          "entity_type": "media",
          "content_type": "other"
        },
        {
          "rank": 3,
          "title": "Professional Grief Counselling - Vancouver - Pathways",
          "source": "Pathways BC",
          "entity_type": "government",
          "content_type": "other"
        }
      ]
    },
    "family cutoff counselling Vancouver": {
      "total_results": 686000,
      "entity_distribution": {
        "counselling": 17,
        "directory": 3,
        "nonprofit": 2,
        "government": 2
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": true,
      "paa_questions": [],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "Reduced-Cost Counselling Options in Vancouver January ...",
          "source": "Willow Tree Counselling",
          "entity_type": "counselling",
          "content_type": "pdf"
        },
        {
          "rank": 1,
          "title": "Family & Parent Counselling Therapy in Vancouver, BC",
          "source": "wellspringcounselling.ca",
          "entity_type": "counselling",
          "content_type": "guide"
        },
        {
          "rank": 2,
          "title": "Family Counselling Vancouver",
          "source": "Blue Sky Wellness Clinic",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Trauma Counselling",
          "source": "Family Services of Greater Vancouver",
          "entity_type": "government",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "North Vancouver Counselling - Boomerang Centre",
          "source": "Boomerang Counselling Centre",
          "entity_type": "counselling",
          "content_type": "other"
        }
      ]
    },
    "reunification counselling BC": {
      "total_results": 91,
      "entity_distribution": {
        "counselling": 11,
        "nonprofit": 3,
        "legal": 1,
        "government": 6,
        "professional_association": 1,
        "directory": 1
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": false,
      "paa_questions": [
        "How to prove parental alienation in BC?",
        "What is the best therapy for parental alienation?",
        "What should I expect in reunification therapy?",
        "Who qualifies for the family reunification program?"
      ],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "Reunification Counselling Port Moody BC",
          "source": "Bright Star Counselling",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 1,
          "title": "REACH Reunification Program",
          "source": "Susan Gamache",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Vancouver Family Preservation & Reunification Services",
          "source": "Westcoast Family Centres",
          "entity_type": "nonprofit",
          "content_type": "guide"
        },
        {
          "rank": 2,
          "title": "Individual & Family Counselling",
          "source": "Success BC",
          "entity_type": "nonprofit",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "REACH REUNIFICATION PROGRAM - Updated March 2026",
          "source": "Yelp",
          "entity_type": "directory",
          "content_type": "other"
        }
      ]
    },
    "reunification therapy near me": {
      "total_results": 15300,
      "entity_distribution": {
        "legal": 2,
        "nonprofit": 2,
        "counselling": 10,
        "government": 4,
        "professional_association": 1,
        "directory": 2
      },
      "dominant_entity_type": null,
      "has_ai_overview": true,
      "has_local_pack": true,
      "paa_questions": [
        "How to get therapy covered in BC?",
        "What is a family reunification therapist?",
        "What is the most common goal of reunification family therapy?",
        "What should I expect in reunification therapy?"
      ],
      "autocomplete": [],
      "top5_organic": [
        {
          "rank": 1,
          "title": "Parent and Child Reunification Program | We ... - Vancouver",
          "source": "Reconnect Families",
          "entity_type": "legal",
          "content_type": "other"
        },
        {
          "rank": 1,
          "title": "Family Preservation and Reunification Counselling Services",
          "source": "HelpStartsHere",
          "entity_type": "government",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Vancouver Family Preservation & Reunification Services",
          "source": "Westcoast Family Centres",
          "entity_type": "nonprofit",
          "content_type": "guide"
        },
        {
          "rank": 2,
          "title": "Family Preservation & Reunification",
          "source": "Hollyburn Family Services",
          "entity_type": "counselling",
          "content_type": "other"
        },
        {
          "rank": 2,
          "title": "Family & Couples Therapy | Langley, BC",
          "source": "Dr. Ellie Bolgar",
          "entity_type": "legal",
          "content_type": "other"
        }
      ]
    }
  },
  "tool_recommendations_verified": [
    {
      "pattern_name": "The Medical Model Trap",
      "trigger_words_searched_for": [
        "clinical",
        "registered",
        "diagnosis",
        "disorder",
        "mental health",
        "patient",
        "treatment"
      ],
      "triggers_found": {
        "in_paa_questions": {},
        "in_organic_titles": {
          "clinical": 1,
          "registered": 1,
          "mental health": 1
        },
        "in_organic_snippets": {
          "clinical": 10,
          "registered": 8,
          "disorder": 1,
          "mental health": 2,
          "treatment": 3
        },
        "in_aio_text": {
          "mental health": 3
        },
        "in_autocomplete": {},
        "in_related_searches": {
          "mental health": 2
        }
      },
      "content_angle": "Why turning family estrangement into a diagnosis keeps you stuck.",
      "status_quo_message": "You are sick/broken and need an expert to fix you (External Locus of Control).",
      "reframe": "Shift from pathology to functioning. You don't need a diagnosis; you need a map of your emotional system.",
      "verdict_inputs": {
        "any_paa_evidence": false,
        "any_autocomplete_evidence": false,
        "total_trigger_occurrences": 32,
        "primary_evidence_source": "in_organic_snippets"
      }
    },
    {
      "pattern_name": "The Fusion Trap",
      "trigger_words_searched_for": [
        "connection",
        "bond",
        "close",
        "intimacy",
        "communication",
        "reconnect",
        "reach out"
      ],
      "triggers_found": {
        "in_paa_questions": {
          "reach out": 2
        },
        "in_organic_titles": {
          "reconnect": 3
        },
        "in_organic_snippets": {
          "connection": 4,
          "communication": 6,
          "reconnect": 1,
          "reach out": 1
        },
        "in_aio_text": {
          "connection": 1,
          "communication": 2,
          "reconnect": 5,
          "reach out": 1
        },
        "in_autocomplete": {},
        "in_related_searches": {
          "reconnect": 1
        }
      },
      "content_angle": "Why trying to force reconnection may deepen the cutoff.",
      "status_quo_message": "The goal is to force closeness, agreement, or reconnection as quickly as possible.",
      "reframe": "Sustainable contact requires differentiation. Anxiety-driven pursuit often increases reactivity and deepens cutoff.",
      "verdict_inputs": {
        "any_paa_evidence": true,
        "any_autocomplete_evidence": false,
        "total_trigger_occurrences": 27,
        "primary_evidence_source": "in_organic_snippets"
      }
    },
    {
      "pattern_name": "The Resource Trap",
      "trigger_words_searched_for": [
        "free",
        "low cost",
        "sliding scale",
        "cheap",
        "affordable",
        "covered",
        "insurance"
      ],
      "triggers_found": {
        "in_paa_questions": {
          "covered": 1
        },
        "in_organic_titles": {},
        "in_organic_snippets": {
          "free": 4,
          "low cost": 1,
          "affordable": 2
        },
        "in_aio_text": {
          "free": 9,
          "affordable": 1
        },
        "in_autocomplete": {
          "free": 1
        },
        "in_related_searches": {
          "free": 6
        }
      },
      "content_angle": "When short-term relief becomes a substitute for working the family pattern.",
      "status_quo_message": "High anxiety about resources/access. Seeking immediate symptom relief (venting).",
      "reframe": "Address the anxiety driving the search. Cheap relief often delays real structural change.",
      "verdict_inputs": {
        "any_paa_evidence": true,
        "any_autocomplete_evidence": true,
        "total_trigger_occurrences": 25,
        "primary_evidence_source": "in_aio_text"
      }
    },
    {
      "pattern_name": "The Blame/Reactivity Trap",
      "trigger_words_searched_for": [
        "narcissist",
        "toxic",
        "abusive",
        "mean",
        "angry",
        "hate",
        "deal with"
      ],
      "triggers_found": {
        "in_paa_questions": {},
        "in_organic_titles": {},
        "in_organic_snippets": {},
        "in_aio_text": {},
        "in_autocomplete": {},
        "in_related_searches": {}
      },
      "content_angle": "Stop diagnosing the other person and start observing your own reactivity.",
      "status_quo_message": "The problem is the other person (The Identified Patient).",
      "reframe": "Focus on self-regulation. You cannot change them, only your response to them.",
      "verdict_inputs": {
        "any_paa_evidence": false,
        "any_autocomplete_evidence": false,
        "total_trigger_occurrences": 0,
        "primary_evidence_source": "none"
      }
    }
  ]
}
```


## Template Constraints

- Keep these placeholders unless there is a clear reason to rename them:
  - `{CLIENT_NAME}`
  - `{CLIENT_DOMAIN}`
  - `{ORG_TYPE}`
  - `{LOCATION}`
  - `{FRAMEWORK_DESCRIPTION}`
  - `{CONTENT_FOCUS}`
  - `{ADDITIONAL_CONTEXT}`
  - `{QUERY_COUNT}`
  - `{ROOT_KEYWORD_COUNT}`
  - `{GEO_LOCATION}`
  - `{COLLECTION_DATE}`
  - `{EXTRACTED_DATA_JSON}`
- The template must remain compatible with the current loader in [`generate_content_brief.py`](/Users/davemini2/ProjectsLocal/serp/generate_content_brief.py).

## Problems To Solve

1. The current template passes the payload with minimal framing, which leaves too much interpretive freedom.
2. It does not explicitly tell the model how to prioritize sections of the payload.
3. It does not explicitly separate verified evidence from contextual client information.
4. It does not tell the model how to handle warnings or low-confidence signals.

## Instructions For The AI Tool

1. Rewrite the user template to better stage the model's work before it sees the extracted JSON.
2. Add concise guidance that tells the model to prioritize verified per-keyword data, strategic flags, client position, AIO analysis, and cross-cluster PAA evidence.
3. Make the role of `ADDITIONAL_CONTEXT` explicit: useful context, not evidence.
4. Keep the template concise. Do not turn it into a second system prompt.
5. Preserve placeholder compatibility unless renaming is absolutely necessary.

## Required Output From The AI Tool

Return:
1. a revised `user_template.md`
2. a short rationale for structural changes
3. any placeholder changes, if unavoidable, called out explicitly
