# PAA intent classification — External Locus / Systemic / General tagging

`intent_classifier.py` tags every PAA question with:
- **External Locus** — Medical model language (diagnosis, treatment, disorder, patient…)
- **Systemic** — Bowen Theory language (differentiation, emotional cutoff, triangulation…)
- **General** — Neither

Tags written to `market_analysis_*.json` (`Intent_Tag`, `Intent_Confidence` fields). External Locus questions are passed to the LLM as `bowen_reframe_faqs` in the content brief payload — they are the prime candidates for a Bowen-framed reframe. Systemic questions are passed separately as `aligned_demand_faqs` (demand already framed in the client's vocabulary; no reframe needed). Before 2026-07-04 the wiring was inverted (Systemic questions fed `bowen_reframe_faqs`); fixed per seo_geo_review_20260704.md C.2.
