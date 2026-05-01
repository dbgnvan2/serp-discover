# Task: Add a Balanced API Mode Between Cheap Monitoring and Full Research

## Objective

The current repo now has:

- a low-cost monitoring mode
- a full research mode

What is missing is a **balanced mode** that restores the highest-value
evidence needed for good strategy decisions, while still using
substantially fewer SerpApi calls than the full run.

The balanced mode should improve:

- cluster reliability
- client visibility / decline detection
- content brief relevance
- AI Overview / citation confidence

without restoring all of the expensive exploratory behavior.

Do not remove the existing low mode or deep-research behavior. Add a
third operating mode cleanly.

---

## Problem Summary

The reduced-call run produced outputs that were usable for rough
monitoring but not reliable enough for strategic planning.

Observed weaknesses from the reduced mode:

1. Too few organic rows were captured
   - reduced run: about 58 organic rows
   - earlier fuller run: about 170 organic rows
   - this weakened cluster/entity conclusions

2. Client position assessment became weaker
   - report lost or softened decline/defensive signals
   - existing visibility became “one citation” rather than a properly
     contextualized position

3. Content briefs remained partially degraded
   - PAA and competitor matching improved from the original bug, but
     still lacked strong relevance in some briefs
   - thin input data is part of the reason

4. AI/GEO insight stayed somewhat usable, but source coverage dropped
   - enough for monitoring
   - not ideal for decision-making

The balanced mode should restore the missing evidence that matters most.

---

## Design Goal

Balanced mode should be:

- much cheaper than full mode
- materially better than low mode
- safe as the default mode for “real analysis” when the user is trying
  to decide what content to create next

It should preserve:

- AI Overview capture
- enough organic depth for meaningful entity and competitor analysis
- enough local pack / Maps depth for local-service terms
- enough related signals to support content-gap work

It should avoid:

- fully open-ended AI exploration on every query
- the highest-multiplier cost behavior across all keywords

---

## Files To Change

- `serp_audit.py`
- `serp-me.py`
- `config.yml`
- `README.md`
- relevant tests, primarily:
  - `test_serp_audit.py`

Do not make unrelated changes.

---

## Balanced Mode Specification

### New Mode

Add a new operating mode:

- env var: `SERP_BALANCED_MODE`
- config default under `app:`:
  ```yml
  balanced_mode: true
  ```

This should be separate from:

- `SERP_LOW_API_MODE`
- `SERP_DEEP_RESEARCH_MODE`

Priority rule:

1. If `LOW_API_MODE` is on, it wins and disables balanced/deep behavior.
2. Else if `DEEP_RESEARCH_MODE` is on, deep behavior applies.
3. Else if `BALANCED_MODE` is on, balanced behavior applies.
4. Else fall back to existing standard/full behavior.

### Balanced Mode Settings

Balanced mode should enforce:

- `GOOGLE_MAX_PAGES = 2`
- `MAPS_MAX_PAGES = 1`
- `AI_FALLBACK_WITHOUT_LOCATION = False`
- `RELATED_QUESTIONS_AI_FOLLOWUP = False`
- `RELATED_QUESTIONS_AI_MAX_CALLS = 0`
- `NO_CACHE_ENABLED = False`

Do **not** disable the main AI Overview capture path. If the main SERP
contains an AI Overview or a page token for one, keep that behavior.

### AI Query Alternatives in Balanced Mode

Keep the current priority-keyword gating for `A.1` / `A.2`, but only
allow alternatives for:

- keywords whose strategic action is `defend`
- keywords whose strategic action is `strengthen`

Do **not** run `A.1/A.2` for `enter_cautiously` in balanced mode.

That is intentionally stricter than the current policy.

Implementation guidance:

- keep the existing helper structure
- adjust the allowed action set dynamically when balanced mode is active

Expected balanced behavior:

- low mode: no A.1 / A.2
- balanced mode: A.1 / A.2 only for `defend` and `strengthen`
- standard/full mode: current broader priority gating can remain
- deep mode: same or broader than standard is fine

---

## Add Explicit Mode Logging

At startup, the audit log currently prints mode flags and page settings.
Extend this so the output clearly shows:

- `LOW_API_MODE`
- `BALANCED_MODE`
- `DEEP_RESEARCH_MODE`
- effective Google pages
- effective Maps pages
- whether related-question AI follow-up is active
- whether AI alternatives are active
- which strategic actions are allowed for A.1/A.2 in the current mode

This matters because the user is trying to trade off quality vs cost
and needs to see which mode actually ran.

---

## Launcher Changes

### Add a Balanced Mode Checkbox

In `serp-me.py`, add a new checkbox:

- label: `Balanced Mode`

Behavior:

- default on
- if `Low API Mode` is checked:
  - disable `Balanced Mode`
  - disable `Deep Research Mode`
  - disable AI alternatives toggle
- if `Deep Research Mode` is checked:
  - leave `Balanced Mode` visible, but only deep mode should apply in
    the backend
- if `Balanced Mode` is checked:
  - set env var `SERP_BALANCED_MODE=1`
  - otherwise `SERP_BALANCED_MODE=0`

The execution log should show:

- `SERP_BALANCED_MODE=...`

### Recommended Default GUI State

Recommended startup defaults:

- `Balanced Mode = on`
- `Low API Mode = off`
- `Deep Research Mode = off`
- `Run 2 AI-likely alternatives = off`

That gives the user a safe “good-enough analysis” default.

---

## Improve Brief Input Quality Under Balanced Mode

Do not redesign the brief generator here. The main issue is data
thinness, not the theme matching logic itself.

However, make sure the balanced mode restores enough data for better
brief quality by ensuring:

- Google organic collection uses 2 pages
- organic rows are still merged and deduped exactly as today
- brief generation continues to use the improved theme-based matching

No separate brief-format change is required in this task unless tests
show balanced mode still fails to surface relevant PAA for the Resource
or Fusion briefs.

---

## Config Changes

In `config.yml`, add:

```yml
app:
  force_local_intent: true
  balanced_mode: true
  deep_research_mode: false
  ai_query_priority_actions:
    - "defend"
    - "strengthen"
    - "enter_cautiously"
```

Do not remove the existing keys.

Balanced mode should read from config unless overridden by env var.

---

## Testing Requirements

Add or update tests in `test_serp_audit.py` for:

1. Balanced mode disables related-question AI follow-up
2. Balanced mode forces Google max pages to 2 and Maps max pages to 1
3. Balanced mode keeps AI Overview main-path behavior intact
4. Balanced mode limits A.1 / A.2 to `defend` / `strengthen`
5. Low mode still overrides balanced mode

Suggested test structure:

- use `patch.object(...)` for module-level flags
- verify `expand_keywords_for_ai(...)`
- verify `fetch_serp_data(...)` does not call `google_related_questions`
  when balanced mode is active

Also rerun:

- `test_generate_content_brief.py`

to ensure the brief path still works.

---

## README Updates

Update README to explain the three operating modes:

### Low API Mode

- cheapest monitoring
- 1 page
- no AI alternatives
- no related-question AI follow-up

### Balanced Mode

- recommended default for decision-making
- 2 Google pages
- 1 Maps page
- AI Overview retained
- no related-question AI follow-up
- A.1 / A.2 only for defend/strengthen keywords

### Deep Research Mode

- highest-cost exploratory mode
- use when doing monthly or quarterly strategy work

Also update the launcher section to mention the new checkbox.

---

## Acceptance Criteria

1. Balanced mode exists and is independently controllable.
2. Balanced mode preserves main AI Overview collection.
3. Balanced mode restores more organic depth than low mode.
4. Balanced mode disables related-question AI follow-up.
5. Balanced mode only allows A.1/A.2 for `defend` and `strengthen`.
6. Launcher exposes balanced mode and logs it.
7. Tests pass.
8. README describes when to use low vs balanced vs deep mode.

---

## Notes For Implementation

- Do not introduce a fourth concept beyond low / balanced / deep /
  existing standard behavior.
- Keep the cost-control logic explicit and easy to inspect in logs.
- Prefer deterministic policy over heuristics.
- The point of balanced mode is not “best possible research.” It is
  “good enough for strategy without burning credits.”
