# TODO

Deferred and adjacent items surfaced during work, with enough context to act later.

## Report content direction (CD, 2026-08-28) — sweep findings not fixed

Two `learning-qa` sweeps ran over the CD.1–CD.11 work. Everything of medium
severity or above was fixed in-session; these were graded below that and
deliberately left, per the "bound the fix loop" rule — each fix is new
unreviewed surface, so a cosmetic one buys none of the safety it costs.

- **`display_stop_words` omits some boilerplate connectives.** `all`, `about`,
  `more`, `out`, `up` are not in the list, so ordinary page furniture clears the
  span-boundary rule: `all rights reserved`, `learn more about`, `read more`
  can appear in report §3 as "competitor vocabulary". Not wrong exactly — they
  are genuine repeated phrases — but they are noise, not vocabulary. Worth a
  look after the next full run, where the phrase counts are ~40× the fixture's
  and the noise will be visible. Edit `serp_vocab.yml` `display_stop_words`;
  no Python change needed. (Sweep 2, finding 1, related.)

- **`_load_config()` is uncached and now read per keyword.**
  `generate_insight_report._report_number` opens `config.yml` on every call, and
  `_da_gap_noise_floor()` is called once per keyword inside `_why_this_keyword`
  plus twice per phrase pass. It was one read at import before CD.11 moved it
  behind a degrading helper (which was the right trade — the import-time read
  could abort a whole audit on a typo). Not a correctness bug; hoist into a
  module cache if a large keyword set ever makes it noticeable. (Sweep 2,
  finding 7, corollary.)

- **The CD guards assert against different inputs on different machines.**
  `REAL_JSON = FULL_RUN_JSON if os.path.exists(...) else FIXTURE_JSON` in
  `tests/test_report_content_direction.py`. The two artifacts are not identical
  — `generate_report` yields 23,815 chars from the full run and 23,807 from the
  committed trim — so a future assertion could pass locally and fail in CI, or
  vice versa. Nothing is vacuous today (the arrays the guards read are
  untrimmed), and the suite reports the same count both ways. Cleaner: make the
  fixture the single source and exercise the full run in a separate,
  explicitly-optional test. (Sweep 2, finding 3, corollary.)

- **Section 4's stale-play caveat narrates a contradiction the report could
  resolve.** When `recommended_play.data_available.feasibility` is false but
  `keyword_feasibility` carries a row for that keyword, everything needed to
  re-route the verdict is in the same dict. The report explains the
  disagreement instead. Deliberate: re-routing at render time would mutate a
  derived field inside a renderer without persisting it, and would make a third
  caller of `attach_recommended_plays`. Re-running the feasibility step fixes
  the artifact properly. Revisit if users keep hitting it on old JSONs.
  (Sweep 1, finding F3, alternative not taken.)

- **The `.xlsx` column headers are still machine field names.** CD.9 added a
  Glossary sheet rather than renaming them, because the JSON and workbook share
  one field vocabulary that `validate_xlsx_vs_json.py` checks column by column,
  and user formulas depend on the names. A friendly-header layer would need a
  rename map applied at write time only, with the parity check taught about it.
  Deferred by the user, 2026-08-28.

- **No repo-root `LEARNINGS.md`.** Both sweeps noted its absence. This repo
  routes generic failure patterns to `~/.claude/standards/learnings.md` and
  repo-specific lessons to `./CLAUDE.md`, so a third home was not created.
  Decide deliberately whether repo-specific lessons want their own file.

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
