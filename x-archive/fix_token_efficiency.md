# Coding Agent Instructions: Fix Token Efficiency in generate_content_brief.py

## Context

`generate_content_brief.py` makes Anthropic API calls for a market intelligence report.
Three token-efficiency problems were found in code review. Fix all three. Do not change
any behaviour outside the scope of each fix. Do not change any other files.

---

## Fix 1 — Retry prompt doubles the full user prompt (HIGH PRIORITY)

### Problem

`build_validation_retry_prompt` prepends `original_user_prompt` to the correction
instructions before sending the retry call. This means the retry sends the entire
data payload **twice** — once as `original_user_prompt`, once again embedded inside
`retry_prompt`. This doubles input token cost on every validation failure.

Both the main report retry (lines ~1484–1490) and the advisory retry (lines ~1548–1554)
have this problem.

### Fix

Change `run_llm_report` to accept an optional `prior_response: str | None = None`
parameter. When `prior_response` is provided, build a three-turn conversation:

```
user:      original_user_prompt
assistant: prior_response        ← the rejected first draft
user:      correction_instructions_only  ← short, no data payload
```

Change `build_validation_retry_prompt` so it returns **only** the correction
instructions (no longer prepends `original_user_prompt`). Rename it to
`build_correction_message` to reflect its new, narrower purpose.

Update every call site to pass `prior_response=report` (or `prior_response=advisory_report`)
into the retry call.

#### Exact changes required

**`run_llm_report` signature — change from:**
```python
def run_llm_report(system_prompt, user_prompt, model, max_tokens):
```
**to:**
```python
def run_llm_report(system_prompt, user_prompt, model, max_tokens, prior_response=None):
```

**`run_llm_report` body — change the `messages` list from:**
```python
messages=[{"role": "user", "content": user_prompt}],
```
**to:**
```python
messages=(
    [
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": prior_response},
        {"role": "user", "content": "IMPORTANT REVISION INSTRUCTIONS:\n"
         "A previous draft failed deterministic evidence validation. "
         "You must revise the report so every claim matches the pre-computed evidence exactly.\n"
         "Return the full corrected document, not notes about the correction."},
    ]
    if prior_response is not None
    else [{"role": "user", "content": user_prompt}]
),
```

Wait — the correction rules text lives inside `build_validation_retry_prompt`.
Keep them there. The refactor is:

1. `build_validation_retry_prompt(original_user_prompt, validation_issues)` →
   rename to `build_correction_message(validation_issues)` and remove the
   `f"{original_user_prompt}\n\n"` prefix. Return only the correction header +
   rules + issues list (as it currently does, minus the original prompt prefix).

2. `run_llm_report` builds the `messages` list:
   - If `prior_response is None`: `[{"role": "user", "content": user_prompt}]`
   - If `prior_response` is set:
     ```python
     [
         {"role": "user",      "content": user_prompt},
         {"role": "assistant", "content": prior_response},
         {"role": "user",      "content": correction_message},
     ]
     ```
     where `correction_message` is passed as a new parameter
     `correction_message: str | None = None`.

   Final signature:
   ```python
   def run_llm_report(system_prompt, user_prompt, model, max_tokens,
                      prior_response=None, correction_message=None):
   ```

3. **Main report retry call site (~line 1484)** — change from:
   ```python
   retry_prompt = build_validation_retry_prompt(user_prompt, validation_issues)
   report = run_llm_report(
       system_prompt=system_prompt,
       user_prompt=retry_prompt,
       model=args.llm_model,
       max_tokens=args.llm_max_tokens,
   )
   ```
   **to:**
   ```python
   correction_msg = build_correction_message(validation_issues)
   report = run_llm_report(
       system_prompt=system_prompt,
       user_prompt=user_prompt,
       model=args.llm_model,
       max_tokens=args.llm_max_tokens,
       prior_response=report,
       correction_message=correction_msg,
   )
   ```

4. **Advisory retry call site (~line 1548)** — same pattern:
   ```python
   correction_msg = build_correction_message(advisory_issues)
   advisory_report = run_llm_report(
       system_prompt=ADVISORY_SYSTEM_PROMPT,
       user_prompt=advisory_user,
       model=advisory_model,
       max_tokens=4000,
       prior_response=advisory_report,
       correction_message=correction_msg,
   )
   ```

### Verification

After the fix, `build_correction_message(issues)` must NOT contain
the original data payload. Assert in a test that calling
`build_correction_message(["issue one"])` returns a string shorter than 500
characters (it should be ~200 characters of rules + the issue list).

---

## Fix 2 — Add prompt caching to the system prompt (HIGH PRIORITY)

### Problem

`run_llm_report` passes `system=system_prompt` as a plain string. The system prompt
is loaded from `serp_analysis_prompt_v3.md` (~56 KB, ~14 000 tokens). It is
completely static between calls. No `cache_control` is set, so the full token
cost is charged on every call including retries.

Anthropic's prompt caching charges ~10 % of normal input token price on cache hits.
Applying it to this prompt saves ~90 % of system-prompt input cost on retries and
on repeat runs within the 5-minute cache TTL.

### Fix

In `run_llm_report`, change the `system` argument from a plain string to a list
with `cache_control`:

**Change from:**
```python
response = client.messages.create(
    model=model,
    max_tokens=max_tokens,
    system=system_prompt,
    messages=...,
)
```

**Change to:**
```python
response = client.messages.create(
    model=model,
    max_tokens=max_tokens,
    system=[
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ],
    messages=...,
)
```

Apply the same change to the advisory call. `ADVISORY_SYSTEM_PROMPT` is a
module-level constant (~2 KB) and is also sent on every advisory + advisory-retry
call, so it benefits from caching too.

`ADVISORY_SYSTEM_PROMPT` is passed inline as `system_prompt` to `run_llm_report`,
so the single change to `run_llm_report` covers both cases automatically — no
separate change needed for the advisory path.

### Verification

After the fix, the `system` value passed to `client.messages.create` must be a
`list`, not a `str`. Add an assertion or a unit test that calls `run_llm_report`
with a mocked `client.messages.create` and checks that
`call_args.kwargs["system"]` is a `list` with one element containing `"cache_control"`.

---

## Fix 3 — Compact JSON for advisory strategic_flags (LOW PRIORITY)

### Problem

The advisory user prompt serializes `strategic_flags` with `indent=2`:

```python
strategic_flags_json=json.dumps(
    extracted["strategic_flags"],
    indent=2,
    default=str,
),
```

Pretty-printed indentation adds whitespace tokens with no information value.
`strategic_flags` is a flat-ish dict, typically 300–600 tokens indented vs
~100 tokens compact.

### Fix

Change `indent=2` to `separators=(",", ":")` (remove indent, use compact separators),
consistent with how `{{EXTRACTED_DATA_JSON}}` is serialized in `build_user_prompt`.

**Change from:**
```python
strategic_flags_json=json.dumps(
    extracted["strategic_flags"],
    indent=2,
    default=str,
),
```

**Change to:**
```python
strategic_flags_json=json.dumps(
    extracted["strategic_flags"],
    separators=(",", ":"),
    default=str,
),
```

### Verification

The advisory user prompt must not contain any two-space indented JSON lines.
Assert that `"  " not in advisory_user` holds for a representative
`strategic_flags` dict.

---

## Do Not Change

- Any function in `serp_audit.py`, `classifiers.py`, `metrics.py`, `storage.py`,
  `url_enricher.py`, or any file other than `generate_content_brief.py`.
- The `validate_llm_report`, `validate_advisory_briefing`, or
  `extract_analysis_data_from_json` functions.
- The `--llm-max-tokens` default (16000). This is left to the operator to tune.
- CLI argument names or behaviour visible to the user.
- The heuristic (non-LLM) report path.

## Acceptance Criteria

1. `build_correction_message(issues)` returns a string with no data payload.
2. `run_llm_report` retry path sends a 3-message conversation, not a single
   doubled message.
3. `client.messages.create` always receives `system` as a `list` with
   `cache_control` set.
4. Advisory `strategic_flags` JSON uses compact separators.
5. All existing tests in `test_serp_audit.py` continue to pass.
6. The script runs end-to-end with `--use-llm` and produces the same report
   structure as before (content will vary due to model non-determinism, but
   all output sections must be present).
