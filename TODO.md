# TODO

Deferred and adjacent items surfaced during work, with enough context to act later.

## Model-list / GUI (from fix/gui-model-robustness, 2026-08-06)

- **Async model-list fetch at GUI startup.** `serp-me.py.__init__` calls
  `report_models.get_report_model_options()`, which does a synchronous HTTP GET
  (Anthropic `/v1/models` via `global-api-config` `llm_providers.list_models`).
  It has a 3s timeout ceiling and offline fails fast, but a degraded-but-connected
  network (captive portal, DNS stall) can block window construction up to ~3s.
  Deferred fix: fetch after the window is shown (`root.after(...)` or a background
  thread) and repopulate the combobox `values` on completion. (learning-qa sweep
  finding #3, MEDIUM — mitigated by the 3s ceiling, not eliminated.)

- **Source the Anthropic API key via `global-api-config` too.** `brief_llm.py`
  reads only `os.getenv("ANTHROPIC_API_KEY")`; the repo `.env` has no Anthropic
  key (it resolves from the process env / `~/.config/llm/keys.json`). Resolving
  the key through `llm_providers` would make key handling consistent with the
  model-list path and remove the hidden dependency on the ambient env.

- **Promote the model list / defaults fully to config.** `REPORT_MODEL_OPTIONS`
  and `MAIN/ADVISORY_DEFAULT_MODEL` are still Python constants (now used only as
  the offline fallback + preferred default). Consider moving them to `config.yml`
  so a non-developer can adjust the fallback set and preferred default.
