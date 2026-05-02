# Spec v2 pre-computed fields and LLM validation policy

## Pre-Computed Fields (per keyword_profile)

`brief_data_extraction.py::extract_analysis_data_from_json()` populates these on every keyword profile so the LLM consumes deterministic verdicts instead of re-inferring them:

- **`serp_intent`**: `{primary_intent, is_mixed, confidence (high/medium/low), intent_distribution, evidence}` — driven by `intent_mapping.yml`. Confidence falls when classifiers tag many URLs as N/A.
- **`title_patterns`**: `{pattern_counts, dominant_pattern, examples, total_titles}` — `dominant_pattern` is set only when one pattern reaches ≥4 of 10 (and is never `"other"`).
- **`mixed_intent_strategy`**: `compete_on_dominant` / `backdoor` / `avoid` / `null`. Computed only when `serp_intent.is_mixed = True`. Driven by `client.preferred_intents` in `config.yml` and the client's existing intent presence (intents the client already ranks for).

`brief_validation.py::validate_llm_report()` enforces these as HARD-FAIL (intent + is_mixed contradictions) or SOFT-FAIL with 1 retry (dominant_pattern + mixed_intent_strategy contradictions).

## LLM Validation Strategy

`brief_validation.py` validates LLM outputs before writing:
1. Hard-fail (abort): AI Overview count mismatch vs. extracted data; `serp_intent.primary_intent` or `is_mixed` contradictions; `dominant_pattern` contradictions
2. Soft-fail (1 retry): `serp_intent.confidence` upgrade (LLM claims higher confidence than computed); `mixed_intent_strategy` contradictions → appended as interpretation notes
3. Failed validations written to `*.validation.md` for inspection

See `docs/validator_rules_20260501.md` for the full field-by-field rule list with severity, detection location, and test pointers.

`test_validation_consistency.py` (spec v2 Gap 5) is a canary that scans the prompt files for `keyword_profiles.<field>` references and asserts each has a corresponding mention in `validate_llm_report`. Run it after adding new pre-computed fields to catch missed validators early.
