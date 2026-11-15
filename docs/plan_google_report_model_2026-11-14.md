# Plan: let the report and brief writer use a Google model (Gemini 4 Hydrogen) by default

**Status:** proposed 2026-11-14. Not approved. No code written.
**Tier (effort-budget):** Full — the paid LLM call path. Tests for the change, one cold
`learning-qa` pass over the diff before pushing.
**Branch:** current (`fix/gui-model-robustness`), two commits, pushed one at a time.

## What the code does now

- `brief_llm.run_llm_report` is the one function that writes the main report and the advisory
  briefing. It builds `anthropic.Anthropic` with `ANTHROPIC_API_KEY` and nothing else. It is
  called four times in `brief_rendering.py` (first try and correction retry, for each report).
- The default model IDs are literals in Python: `brief_llm.py:20,22` and `serp-me.py:78,79`.
  The two files disagree on the advisory default, and `brief_llm.py:22` names
  `claude-sonnet-4-20250514`, which was not on the live list on 2026-08-06.
- `brief_rendering.py:603,690` and the launcher note at `serp-me.py:242` check for or name
  `ANTHROPIC_API_KEY` only.
- The launcher's two model dropdowns come from `report_models.get_report_model_options`, which
  asks the shared registry (`~/.config/llm/keys.json`) for the live list and keeps only IDs
  starting with `claude`.
- The call has no check that the answer was cut off at `max_tokens`.

## Checked before planning

- The shared registry already has two Google providers on Google's OpenAI-compatible endpoint
  (`https://generativelanguage.googleapis.com/v1beta/openai`, dialect `openai`).
- Live model list on the `gemini-rag` key, 2026-11-14: 64 models, including
  `models/gemini-4-hydrogen`. That is the ID this plan assumes "Hydrogen" means.
- The `gemini-1` key is rejected by Google ("Please pass a valid API key"). Not part of this
  change, but that entry does not work today.
- No provider is mapped to `serp-discover` under `apps`, so it resolves to the registry default
  (`anthropic`).
- Not checked: whether the chat endpoint wants `gemini-4-hydrogen` or `models/gemini-4-hydrogen`,
  and how Hydrogen counts reasoning tokens against `max_tokens`. Both are settled by G8.

## Approach

The provider comes from the shared registry, in the order `llm-integration.md` L6 sets: this
repo's `config.yml`, then the registry's `apps` map, then the registry default. `run_llm_report`
looks at the provider's dialect: `anthropic` keeps today's SDK call; `openai` sends a
`/chat/completions` request with `requests`, with the timeout and retry the other HTTP calls
use. Any OpenAI-dialect provider then works, not only Google. Model IDs move out of Python into
`config.yml`.

## Chunk P — provider and model from config (`brief_llm.py`, `brief_rendering.py`, `config.yml`)

| ID | Criterion | Test (`tests/test_brief_llm_providers.py`) |
|---|---|---|
| G1 | New `config.yml` block `report_llm`: `provider` (a name in the registry; empty = use the registry's `apps` map, then its default), `main_model`, `advisory_model`, `timeout_seconds`. The four model-ID literals in `brief_llm.py` and `serp-me.py` are removed. | `test_g1_models_and_provider_come_from_config`; source check that no `claude-`/`gemini-` literal remains in the two files. |
| G2 | With an `openai`-dialect provider, the call goes to `<base_url>/chat/completions` with a Bearer key from the registry, the system prompt as a system message, and the correction retry as the same three-message exchange used today. Timeout from config; transient failures retried with backoff; the key never appears in a log or error. | `test_g2_openai_dialect_request_shape`, `test_g2_correction_retry_messages`, `test_g2_timeout_and_retry`, `test_g2_key_is_not_logged`. |
| G3 | With an `anthropic`-dialect provider the request is unchanged, including prompt caching. If the registry is missing, the Anthropic path still works from `ANTHROPIC_API_KEY` as it does now. | `test_g3_anthropic_request_unchanged`, `test_g3_env_key_fallback_without_registry`. |
| G4 | An empty answer, a refusal, or an answer cut off at the token limit (`finish_reason: length` / `stop_reason: max_tokens`) raises a named error for both dialects. The report file is not written and the run exits non-zero. | `test_g4_truncated_answer_is_a_failure` (both dialects), `test_g4_empty_answer_is_a_failure`. |
| G5 | A configured provider that is missing, has no key, or fails is an error that names the provider. There is no fallback to another provider or model. | `test_g5_unknown_provider_fails`, `test_g5_no_silent_fallback`. |
| G6 | The pre-run checks in `brief_rendering.py` test for the resolved provider's key, not `ANTHROPIC_API_KEY`. The run prints the provider name and model before each call, and the report records which model wrote it. | `test_g6_precheck_uses_resolved_provider`, `test_g6_model_is_recorded`. |

## Chunk D — launcher dropdowns (`report_models.py`, `serp-me.py`)

| ID | Criterion | Test (`tests/test_report_models.py`) |
|---|---|---|
| G7 | The dropdowns list the resolved provider's live models. Which IDs are offered is set in `config.yml` (`report_llm.model_include` prefixes, `model_exclude` substrings) so embedding, image, speech and robotics models are left out; a `models/` prefix is removed. Defaults are `report_llm.main_model` / `advisory_model` when live, else the first offered. Offline, the dropdown shows the two configured models. | `test_g7_google_models_are_listed_and_filtered`, `test_g7_defaults_come_from_config`, `test_g7_offline_fallback_is_the_configured_models`. |

UI contract (ui-regression): no control added, removed, renamed or moved. The note at
`serp-me.py:242` changes from "Requires Anthropic API" to name the configured provider.

## Decisions needed

1. **Which key.** Recommended: you add a new entry to `~/.config/llm/keys.json` (for example
   `gemini-serp`, same base URL as `gemini-rag`) holding the new key, and I set
   `report_llm.provider: gemini-serp`. This tool's usage then bills to its own key. The
   alternative is to reuse `gemini-rag`. I will not handle the key itself.
2. **One provider for both reports.** Recommended: main report and advisory briefing use the
   same provider, both defaulting to `gemini-4-hydrogen`. Going back to Claude is one config
   line. The alternative, a provider per report, needs a second setting and a second dropdown
   source.
3. **Real-run check (G8).** Recommended: after the build, one real brief on an existing
   analysis JSON with Hydrogen. It costs LLM tokens only, no SerpAPI credits. I will not run it
   without your yes.

## Risks

- **Validators were only ever run against Claude output.** The checks are text rules, so they
  apply to any model, but a different model may fail them more often. The SOFT-fail retry and
  HARD-fail abort stay as they are. G8 shows what happens.
- **Cost.** Prompt caching is sent on the Anthropic path only. On the Google path the system
  prompt is billed in full on each of up to four calls. I have no price for Hydrogen and will
  not quote one from memory.
- **Token limit.** If Hydrogen spends output tokens on reasoning, today's `max_tokens` may cut
  the report short. G4 turns that into a visible failure; the limit may then need raising in
  config.

## Order

P first, then D. D depends on the `report_llm` block from P.

## Documents updated in the same commits

- `docs/USER_MANUAL.md` — choosing the report model and provider; what a provider failure
  looks like.
- `docs/config_reference.md` — the `report_llm` block.
- `docs/methodology.md` — the report writer is no longer fixed to one vendor; the report names
  its model.
- `docs/architecture.md`, `README.md`, `CLAUDE.md` — the env-var and key sections (registry
  entry instead of, or as well as, `ANTHROPIC_API_KEY`); test count.

## Adjacent issues found, not fixed

- `brand_mentions.llm_model` and `sentiment.llm_model` in `config.yml` name
  `claude-sonnet-4-20250514` (both features are off by default).
- `ai_visibility.gemini_model` is `gemini-2.5-flash`; the probe reads `GEMINI_API_KEY` from
  `.env`, not the registry. The probe is a measurement of each engine, so it is left alone.
- `report_models._LIVE_FETCH_TIMEOUT` and `DEFAULT_REPORT_MODELS` are literals in Python.
- The `gemini-1` registry key is invalid.
- `.env` line 3 is malformed and breaks `python-dotenv`.
- `serp-compete` resolves its own provider (`openai-serp`); not touched.

## Not code-testable

- **G8:** one real brief with Hydrogen — the model-ID form the endpoint accepts, whether the
  report passes validation, whether it is cut off, and how long the call takes (for the
  timeout default).
- Whether the report Hydrogen writes is as good as the Claude one. That is your read of the
  two files side by side.
