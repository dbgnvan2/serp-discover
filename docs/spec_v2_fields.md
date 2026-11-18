# Spec v2 pre-computed fields and LLM validation policy

## Pre-Computed Fields (per keyword_profile)

`brief_data_extraction.py::extract_analysis_data_from_json()` populates these on every keyword profile so the LLM consumes deterministic verdicts instead of re-inferring them:

- **`serp_intent`**: `{primary_intent, is_mixed, confidence (high/medium/low), intent_distribution, evidence}` — driven by `intent_mapping.yml`. Confidence falls when classifiers tag many URLs as N/A.
- **`title_patterns`**: `{pattern_counts, dominant_pattern, examples, total_titles}` — `dominant_pattern` is set only when one pattern reaches `title_patterns.dominant_threshold` of the `title_patterns.top_n` titles read (`config.yml`; 4 of 10 by default, and `total_titles` records how many were actually read), and is never `"other"`. The HARD validator rule on this field checks the model's claim against whatever those keys are set to, so tuning them changes what the brief may say (review chunk Y1).
- **`mixed_intent_strategy`**: `compete_on_dominant` / `backdoor` / `avoid` / `null`. Computed only when `serp_intent.is_mixed = True`. Driven by `client.preferred_intents` in `config.yml` — what the client **can** serve. `compete_on_dominant` when a dominant intent is preferred; `backdoor` when the dominant intent is not preferred but a non-dominant one is; `avoid` otherwise. The client's existing intent presence (intents they already rank for) only picks which of several equally dominant preferred intents to lead with (D-M-11 / D4.6: the gate used to be presence itself, so a dominant intent the client served was labelled a backdoor and a client with no rankings could never compete on anything).
- **`entity_distribution_rows`** / **`entity_distribution_rank_repeats`** / **`entity_distribution_duplicate_rows`** / **`entity_distribution_single_serp`**: the denominator of the entity share and what it is made of. An identical result (same rank, same link) is counted once and the drop recorded; a rank held by two *different* results means more than one fetch is present, and `entity_distribution_single_serp` is then false — the share is reported with its real denominator rather than passing as a top-10 share. The snapshot carries no field saying which fetch a row came from, so the rows cannot be split (D4.9).
- **`mixed_intent_dominant`** / **`mixed_intent_dominant_tied`** / **`mixed_intent_lead`**: the dominant intent(s) as a sorted list, whether they tie, and which one to lead with. A tie used to be resolved by `max()` over a dict — i.e. by SERP row order — so the same 5/5 page produced two different strategies (D4.6).

`brief_validation.py::validate_llm_report()` enforces these as HARD-FAIL (intent + is_mixed contradictions) or SOFT-FAIL with 1 retry (dominant_pattern + mixed_intent_strategy contradictions).

## LLM Validation Strategy

`brief_validation.py` validates LLM outputs before writing:
1. Hard-fail (abort): AI Overview count mismatch vs. extracted data; `serp_intent.primary_intent` or `is_mixed` contradictions; `dominant_pattern` contradictions
2. Soft-fail (1 retry): `serp_intent.confidence` upgrade (LLM claims higher confidence than computed); `mixed_intent_strategy` contradictions → appended as interpretation notes
3. Failed validations written to `*.validation.md` for inspection

See `docs/validator_rules_20260501.md` for the full field-by-field rule list with severity, detection location, and test pointers.

`test_validation_consistency.py` (spec v2 Gap 5) is a canary that scans the prompt files for `keyword_profiles.<field>` references and asserts each has a corresponding mention in `validate_llm_report`. Run it after adding new pre-computed fields to catch missed validators early.
