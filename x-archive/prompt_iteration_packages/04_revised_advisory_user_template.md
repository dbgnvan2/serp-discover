# Revised Advisory User Template

## user_template.md

```md
## Task

Produce the advisory briefing specified in your system instructions.
Read the inputs below in this order:

1. Strategic flags — these are binding constraints, not suggestions.
   They determine which action is first, which keywords are skip,
   and whether defense takes priority over expansion.
2. Client context — background for assessing fit and framing
   recommendations in the client's language.
3. Market intelligence report — the verified analysis that your
   briefing interprets. Do not repeat it; reference findings by
   keyword name.

## Strategic Flags (binding constraints)

These were computed deterministically from the SERP data. They are
not hypotheses. Use them as given.

- If defensive_urgency = "high", Action 1 must defend the
  declining position.
- content_priorities ordering determines your action sequence.
- Keywords with action = "skip" appear only in "What to Stop
  Thinking About."
- total_results values are indexed page counts, not monthly
  search volume.

<strategic_flags>
{strategic_flags_json}
</strategic_flags>

## Client Context (background — not evidence)

Organization: {client_name}
Website: {client_domain}
Type: {org_type}
Location: {location}
Framework: {framework_description}
Content focus: {content_focus}
Constraints: {additional_context}

Use this to assess whether the client can realistically execute
each recommendation and to frame actions in language that connects
to their work. Do not treat client context as SERP evidence.

## Market Intelligence Report (verified analysis)

This is the first-pass report produced from pre-verified SERP data.
Every number in it has been checked against the raw data. Use it
as your analytical foundation but do not repeat its contents —
the reader has already seen it.

<market_report>
{market_report_text}
</market_report>

Produce the advisory briefing now. Follow the four-part structure
(data → why it matters → what to do → consequence of inaction)
for each of exactly 3 actions.
```

---

## Rationale

### 1. Strategic flags moved ahead of client context and report
The current template places client context first, then strategic flags, then the report. This ordering lets the LLM absorb the client's framework description and start generating ideas before encountering the constraints that should shape those ideas. The new template puts strategic flags first with an explicit "binding constraints" label. The LLM reads "defensive_urgency = high, Action 1 must defend" before it reads about Bowen Theory or sees the report's content gap analysis. This directly addresses Problem 3 from the package: strategic flags should override interesting but lower-priority ideas.

### 2. Constraint summary added before the JSON block
The current template wraps strategic flags in XML tags with no interpretive guidance. The LLM has to parse the JSON and figure out what matters. The new template adds four bullet points before the JSON that state the operational rules in plain language: defend first when urgency is high, follow the priority ordering, skip means skip, total_results isn't search volume. This is not duplicating the system prompt — the system prompt says *how* to write each action; these bullets say *which* actions to write based on this specific data.

### 3. Client context explicitly labeled "not evidence"
Same principle as the pass-1 user template revision. The framework description ("Bowen Family Systems Theory... differentiation of self, emotional cutoff...") was being used to generate content gap narratives rather than to assess execution fit. The new label ("Use this to assess whether the client can realistically execute each recommendation") constrains the context to its proper role.

### 4. Report framing tightened
The current template says "verified, from first-pass analysis." The new template adds "Every number in it has been checked against the raw data" and "do not repeat its contents — the reader has already seen it." The first statement gives the LLM permission to trust the report's numbers without re-deriving them. The second reinforces the system prompt's rule against report repetition — a problem in the reference advisory where whole paragraphs restated pass-1 findings.

### 5. Closing instruction restates the structural constraint
The current template ends with "produce the advisory briefing as specified in your instructions." The new template ends with "Follow the four-part structure (data → why it matters → what to do → consequence of inaction) for each of exactly 3 actions." This is a single-sentence reminder that reinforces the system prompt's most important structural requirement at the point where the LLM begins generating output. It's not duplicating the system prompt — it's a checkpoint.

---

## Placeholder Changes

None. All existing `str.format()` placeholders are preserved:
- `{client_name}`, `{client_domain}`, `{org_type}`, `{location}`
- `{framework_description}`, `{content_focus}`, `{additional_context}`
- `{strategic_flags_json}`, `{market_report_text}`

The single-brace `{}` format is unchanged. The `<strategic_flags>` and `<market_report>` XML wrappers are unchanged. The template remains compatible with the existing `ADVISORY_USER_TEMPLATE.format(...)` call in `generate_content_brief.py`.
