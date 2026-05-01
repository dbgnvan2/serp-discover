# Prompt Iteration Package: Correction Prompt

## Objective

Rewrite the correction prompt so failed drafts are repaired surgically instead of being broadly regenerated. The retry should preserve valid content and only remove or restate unsupported claims.

## Current Prompt File

- [`prompts/correction/user_template.md`](/Users/davemini2/ProjectsLocal/serp/prompts/correction/user_template.md)

## Current Prompt Text

```md
SURGICAL REVISION — preserve valid content, fix only what failed.

A previous draft failed evidence validation. The rejected claims
are listed below. Your job is to produce a corrected version of
the full document with minimal changes.

## Rules

1. PRESERVE VALID SECTIONS. If a section contains no rejected
   claims, copy it unchanged. Do not rephrase, reorganize, or
   "improve" sections that passed validation.

2. FOR EACH REJECTED CLAIM, choose exactly one of these repairs:
   a) DELETE the sentence or paragraph containing the claim if
      no verified evidence supports it.
   b) NARROW the claim to what the evidence actually shows. For
      example, change "appears across multiple clusters" to
      "appears for one keyword" if that is what the data confirms.
   c) SOFTEN the claim with uncertainty language if partial
      evidence exists but the original statement overstated it.
      For example, change "strongly supported" to "limited
      evidence in organic snippets only."

3. DO NOT INVENT NEW EVIDENCE to replace a rejected claim. If the
   claim was rejected because evidence is absent, the fix is
   deletion or acknowledgment of absence — not fabrication of
   alternative support.

4. DO NOT ADD NEW SECTIONS, recommendations, or analysis that
   did not exist in the original draft. The correction pass fixes
   errors; it does not expand scope.

5. RETURN THE FULL CORRECTED DOCUMENT, not notes about corrections.

## Rejected Claims

{{VALIDATION_ISSUES}}

## Revision Checklist

Before returning the document, verify:
- Every rejected claim has been deleted, narrowed, or softened
- No new unsupported claims have been introduced
- Sections not implicated by rejected claims are unchanged
- The document is complete (all original sections present)
```

## Shared Evidence Bundle

Use these files with this package if your chatbot tool supports multiple attachments:

- [`extracted_payload_summary_estrangement_20260311_1733.json`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/extracted_payload_summary_estrangement_20260311_1733.json)
- [`extracted_payload_estrangement_20260311_1733.json`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/extracted_payload_estrangement_20260311_1733.json)
- [`failed_main_report_draft_20260311_1737.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/failed_main_report_draft_20260311_1737.md)
- [`reference_main_report_20260311_1554.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/reference_main_report_20260311_1554.md)
- [`reference_advisory_20260311_1554.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples/reference_advisory_20260311_1554.md)

Use the summary JSON first. Only inspect the full extracted payload if you need field-level detail.


## Failure Example

This is a real rejected first-pass draft from the current pipeline. The validator blocked it because it invented a cross-cutting `toxic` opportunity.

```markdown
# Content Opportunity Report Validation Issues

## Rejected Claims

- Report claims a cross-cutting 'toxic' opportunity, but verified PAA/autocomplete evidence is absent.

## Rejected Draft

# SERP Market Intelligence Report: Living Systems Counselling
**Family Estrangement & Reunification Services | North Vancouver, BC**

## Section 1: Data Summary

This analysis examined 6 queries across 6 root keywords geolocated to North Vancouver, BC, collected on March 11, 2026. The search covered estrangement-related terms including "estrangement," "estrangement from adult children," "estrangement grief," "family cutoff counselling Vancouver," "reunification counselling BC," and "reunification therapy near me." The dataset contains 168 total organic results with 129 entity-classified entries. AI Overviews appeared on all 6 queries, generating 88 total citations across 64 unique sources.

No significant data quality issues were detected. The "reunification counselling BC" keyword returned only 91 total results, indicating a very narrow market that may not justify dedicated content investment.

## Section 2: Keyword Cluster Analysis

The keywords cluster into three distinct behavioral groups based on SERP composition and total results scale:

**Legal-Dominant Cluster: General Estrangement (231,000 results)**
The broad "estrangement" keyword triggers a SERP dominated by legal entities (12 of 24 classified results), with law firms like MacLean Family Law, Pathway Legal Family Lawyers, and Clark Wilson LLP securing top positions. The AI Overview cites primarily legal sources and discusses parental alienation from a court perspective. PAA questions focus on contact strategies and duration timelines. This represents the largest market but poses the highest competitive barrier for a counselling organization.

**Counselling-Focused Cluster: Adult Child Estrangement (16,400 results) and Estrangement Grief (31,700 results)**
These keywords show counselling entities dominating (6 of 20 and 7 of 17 classified results respectively). Sources like estrangedfamilytherapy.com and Restored Hope Counselling Services rank prominently. The "estrangement grief" SERP uniquely includes nonprofit and government resources like the British Columbia Bereavement Helpline and gov.bc.ca. Both SERPs include discussions_and_forums modules, indicating active user-generated content. These markets offer more realistic entry opportunities for Living Systems Counselling.

**Service-Delivery Cluster: Reunification Services (15,300 and 91 results)**
"Reunification therapy near me" generates local pack results with 23 businesses averaging 4.78 stars, dominated by family counsellors. The SERP focuses on service delivery rather than information. "Reunification counselling BC" returns only 91 results with specialized providers like Bright Star Counselling and Susan Gamache's REACH program. This micro-niche may be too small for dedicated content investment despite lower competition.

Competitor ads appeared for none of these keywords, suggesting limited commercial competition in this geographic market.

## Section 3: Client Position Assessment

Living Systems Counselling appears organically for only 1 of 6 tracked keywords. The organization ranks #7 for "family cutoff counselling Vancouver" with the article "Can cutting off family be good therapy?" This position shows declining stability, dropping 3 positions from rank #4. This represents a critical vulnerability since 100% of the client's organic visibility depends on this single ranking.

The client receives zero AI Overview citations across all queries and is not mentioned in any AI Overview body text. No local pack presence was detected, and no language pattern mentions of Bowen theory terminology appear in the competitive landscape.

Google's current understanding of the client appears limited to this single content piece addressing family cutoff from a therapeutic perspective. The declining rank trend indicates this content is losing relevance or authority compared to competitors like Willow Tree Counselling, Blue Sky Wellness Clinic, and CounsellingBC, which consistently rank above the client.

## Section 4: AI Overview / GEO Opportunity Analysis

AI Overviews appear at position 2 across all queries, making them highly visible to searchers. Citation patterns reveal clear opportunities: Psychology Today leads with 7 citations, followed by MacLean Family Law and Reconnect Families (5 each). The client's absence from all 88 citations represents a significant missed opportunity for visibility.

AI Overview language varies by cluster. Legal-focused queries emphasize "parental alienation" and court processes. Counselling-focused queries discuss "disenfranchised grief" and therapeutic approaches. The "family cutoff counselling Vancouver" AIO specifically mentions local resources but cites YouTube, Willow Tree Counselling, and Psychology Today instead of specialized family systems providers.

The most accessible AIO citation opportunity appears in the counselling-focused cluster, where existing citations include therapeutic sources like estrangedfamilytherapy.com and Clearheart Counselling. The client's Bowen theory expertise could differentiate from the general counselling approaches currently cited.

## Section 5: Content Gap Analysis

Two significant gaps emerge from PAA and autocomplete analysis:

**Cross-Cluster Question Gap**: "How do I reach out to an estranged adult child?" appears in both estrangement clusters (247,400 combined results). Current SERP results focus on communication tactics without addressing the underlying emotional system dynamics that Bowen theory explains. This represents the strongest cross-cutting opportunity.

**Differentiation of Self Gap**: Despite "differentiation of self" being central to Bowen theory, it appears 0 times in market language analysis. Current content emphasizes "connection," "communication," and "reconnect" (27 total mentions) without addressing the anxiety-driven pursuit that often deepens cutoffs. This gap aligns perfectly with Living Systems' theoretical framework.

**Grief Framework Gap**: "Estrangement grief" autocomplete shows high interest in support groups, stages of grief, and "disenfranchised grief," but current SERPs primarily list service directories rather than explaining grief through a family systems lens. The client could address how emotional cutoff creates ambiguous loss that traditional grief models don't adequately address.

## Section 6: Evaluation of Tool-Generated Recommendations

**The Medical Model Trap** - SUPPORTED: Data shows 32 trigger occurrences across organic results and AIO text, with "clinical" (10), "registered" (8), and "mental health" (5) heavily present. The content angle addressing diagnostic language as potentially unhelpful aligns with Bowen theory's systems perspective versus individual pathology.

**The Fusion Trap** - STRONGLY SUPPORTED: Evidence includes 27 trigger occurrences with "reach out" appearing in 2 PAA questions and "reconnect" appearing 9 times across organic and AIO content. The cross-cluster PAA question "How do I reach out to an estranged adult child?" directly validates this content angle. This recommendation has the strongest data support.

**The Resource Trap** - PARTIALLY SUPPORTED: While 25 trigger occurrences appear including "free" (15 total) and "covered" (1 PAA question), this pattern may reflect genuine affordability barriers in BC rather than anxiety-driven symptom relief seeking. The data shows legitimate interest in "How to get therapy covered in BC?" suggesting practical rather than avoidant intent.

**The Blame/Reactivity Trap** - NOT SUPPORTED: Zero trigger occurrences found across all data sources. Terms like "narcissist," "toxic," and "abusive" do not appear in PAAs, autocomplete, or related searches. This recommendation lacks data foundation and should not be prioritized.

## Section 7: Prioritized Content Recommendations

**1. DEFEND: "Can cutting off family be good therapy?" (family cutoff counselling Vancouver)**
**Priority: Immediate**
Update existing content to prevent further rank decline from position #7. The 3-position drop threatens the client's only organic visibility. Add local optimization signals, update with recent case studies, and strengthen the Bowen theory framework explanation to differentiate from generic counselling approaches ranking above.

**2. ENTER: "Understanding Estrangement Grief Through Family Systems" (estrangement grief)**
**Priority: High**
Target the 31,700-result market dominated by counselling entities. Address the gap around ambiguous loss and disenfranchised grief using Bowen's emotional system concepts. Current results focus on traditional grief stages; differentiate by explaining how cutoff creates ongoing systemic impact across generations.

**3. ENTER: "When Adult Children Cut Contact: A Systems Perspective" (estrangement from adult children)**
**Priority: High**
Target the cross-cluster PAA question "How do I reach out to an estranged adult child?" (247,400 combined results). Address how anxiety-driven pursuit often deepens reactivity. Current results emphasize communication tactics; offer systems thinking about differentiation of self instead.

**4. ENTER: "Family Reunification: Beyond Forced Connection" (reunification therapy near me)**
**Priority: Medium**
Target the 15,300-result market with local pack presence. Current content focuses on service logistics; differentiate by addressing what makes reunification sustainable versus forced. Target PAA questions about therapy expectations and goals using Bowen's concepts of emotional cutoff resolution.

**5. ENTER CAUTIOUSLY: "Legal vs. Therapeutic Approaches to Estrangement" (estrangement)**
**Priority: Low**
The 231,000-result market is legal-entity dominated, requiring careful positioning. Create content that complements rather than competes with legal advice, focusing on the emotional system work that supports whatever legal outcomes occur. Avoid direct legal territory while addressing the therapeutic aspects legal sources don't cover.

## Section 8: Keyword Expansion Recommendations

Based on autocomplete and related searches analysis, investigate these additional keywords in future SERP analysis:

**"estrangement meaning" and "estrangement synonym"** - High autocomplete relevance (1,250 and 602) suggests definitional searches where Bowen theory could provide unique perspective beyond dictionary definitions.

**"parental alienation Vancouver"** - Appears in related searches for estrangement, indicating local legal-therapeutic intersection where systems perspective could add value without competing directly with legal services.

**"grief support groups Vancouver"** - Related search for estrangement grief with 8 related terms, suggesting group intervention opportunities that align with Living Systems' existing programming.

**"stages of grief family estrangement"** - Multiple autocomplete variations suggest interest in grief progression models that Bowen's multigenerational perspective could reframe.

**"family scapegoat estrangement grief"** - Specific autocomplete term indicating interest in family role dynamics that directly align with Bowen theory concepts of family projection and sibling position.

These expansions should be researched after defending existing visibility and establishing positions in the prioritized clusters above.
```


## Problems To Solve

1. The correction prompt is short and safe, but may still encourage too much regeneration.
2. It does not explicitly tell the model to preserve already-valid sections.
3. It does not distinguish between deleting unsupported claims and restating them more cautiously.

## Instructions For The AI Tool

1. Rewrite the correction prompt so it behaves like a surgical revision request.
2. Require the model to preserve all valid sections and only change text implicated by the rejected claims.
3. Tell the model to prefer narrowing or softening a claim over inventing new supporting evidence.
4. Keep the prompt compact. Token efficiency still matters on retries.
5. Preserve the `{{VALIDATION_ISSUES}}` placeholder exactly unless you provide a compelling compatibility reason to change it.

## Required Output From The AI Tool

Return:
1. a revised correction `user_template.md`
2. a short rationale for the revisions
3. a one-paragraph note on how the new version reduces retry-token waste
