# PAA intent classification — External Locus / Systemic / General tagging

`intent_classifier.py` tags every PAA question with:
- **External Locus** — Medical model language (diagnosis, treatment, disorder, patient…)
- **Systemic** — Bowen Theory language (differentiation, emotional cutoff, triangulation…)
- **General** — Neither

Tags written to `market_analysis_*.json` (`Intent_Tag`, `Intent_Confidence` fields). External Locus questions are passed to the LLM as `bowen_reframe_faqs` in the content brief payload — they are the prime candidates for a Bowen-framed reframe. Systemic questions are passed separately as `aligned_demand_faqs` (demand already framed in the client's vocabulary; no reframe needed). Before 2026-07-04 the wiring was inverted (Systemic questions fed `bowen_reframe_faqs`); fixed per seo_geo_review_20260704.md C.2.


## Moz search-intent cross-check (moz_api_upgrade_spec_v1.md T.3)

`moz.search_intent` (off by default) fetches Moz's own intent scores per keyword and reports
them beside this tool's verdict as `keyword_profiles.moz_intent`. **The rules in
`intent_mapping.yml` remain the verdict** — Moz is a second opinion, and a disagreement is
surfaced, never resolved automatically. An external model silently overriding a rule table the
user maintains would make those rules unfalsifiable.

The vocabularies differ. Moz emits `informational`, `navigational`, `commercial` and
`transactional`; this repo also emits `commercial_investigation`, `local` and `uncategorised`.
`config.yml` `moz.search_intent.repo_to_moz_intent` maps a repo verdict onto Moz's vocabulary so
the two can be compared; it is editorial, and `local -> transactional` reflects what Moz actually
returns for local service queries ("family counselling north vancouver" scores transactional
0.45). A `null` mapping, a mixed-intent keyword, or absent Moz data all yield `agrees: null` —
**not comparable**, which is reported as such and never as a disagreement.
