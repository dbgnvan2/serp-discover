# Task: Fix Remaining Report Errors (3 Issues)

## Context

The prompt revisions from packages 01–05 are working. Per-keyword
Section 2 structure is followed, trap framework is confined to
Section 6, strategic flags drive Section 7, no fabricated PAA
questions, autocomplete citations are verified as real.

Three factual errors persist. Two are prompt issues (the model
makes a judgment call the rules should have prevented). One is a
code issue (the extraction doesn't give the model enough
information to avoid the error).

---

## Fix 1: AIO Count Override (Prompt Fix)

### Problem

The report says "5 of 6 queries feature AI Overviews" when the
pre-computed data shows `has_ai_overview=True` for all 6. The
model decided "reunification therapy near me" doesn't really have
an AIO because the text is 3 characters and citations are 0, and
quietly downgraded the count.

This violates Rule 6 (use pre-computed fields exactly) and Rule 8
(state absence, don't interpret it).

### Fix

Add this worked example to the system prompt under Rule 8 or as
a new Rule 11:

```
RULE 11: DO NOT OVERRIDE PRE-COMPUTED FLAGS.
If a pre-computed field (has_ai_overview, has_local_pack,
stability, etc.) shows a value that seems inconsistent with
other data, state both facts. Do not silently adjust counts
based on your interpretation of the underlying data.

Example: if has_ai_overview=True for a keyword but
aio_citation_count=0 and aio_length_chars=3, say:
"AI Overview is technically present but contains minimal
content (3 characters) and generated 0 citations."
Do NOT say "5 of 6 queries feature AI Overviews" when the
data shows 6 of 6.

Example: if has_local_pack=True but local_pack_count=2, say:
"Local pack is present with 2 businesses listed."
Do NOT say "no meaningful local pack presence."
```

### Verification

Run the report and check Section 4. It should say "6 of 6"
(matching the pre-computed flags) with a qualification about the
minimal reunification therapy AIO, not "5 of 6."

---

## Fix 2: Speculative Causal Explanations (Prompt Fix)

### Problem

The report says "AI Overview present but with 0 citations,
indicating technical issues or content filtering." The data
shows a factual state (AIO present, 0 citations). The causal
explanation is fabricated — nothing in the data supports
"technical issues or content filtering."

This violates Rule 8 (absent evidence stated, not invented).

### Fix

Add this to Rule 8 in the system prompt:

```
When two pre-computed values appear contradictory (e.g.,
has_ai_overview=True but aio_citation_count=0), state both
values as facts. Do not speculate about the cause. Phrases
like "indicating technical issues," "suggesting content
filtering," "possibly due to," or "likely because" are not
permitted when explaining data anomalies. State what the data
shows and move on.

Example — WRONG: "AI Overview present but with 0 citations,
indicating technical issues or content filtering."
Example — RIGHT: "AI Overview is present but returned 0
citations for this keyword."
```

### Verification

Run the report and search for "indicating," "suggesting,"
"possibly," "likely because" in the context of data anomalies.
None should appear. The reunification therapy near me entry in
Section 2 should state the two facts (AIO present, 0 citations)
without explanation.

---

## Fix 3: Entity Mix Mislabeling (Prompt + Code Fix)

### Problem

The report says "estrangement from adult children" shows
"counselling dominance with 6 entities" when the actual mix is
counselling: 6, media: 6, legal: 4, directory: 3 (20 classified).
Counselling and media are tied at 30% each — calling this
"dominance" is wrong.

The system prompt has Rule 9 (60% threshold for "dominated") but
Sonnet doesn't reliably apply abstract percentage thresholds.

### Prompt Fix

Replace the current Rule 9 text with a version that includes a
worked example:

```
RULE 9: ENTITY LABELING THRESHOLDS.
When describing a keyword's entity mix, apply these labels:
- "dominated by [type]": that type exceeds 60% of classified
  entities (e.g., 13 of 20 classified = 65% → "dominated")
- "[type] leads" or "[type] plurality": that type is the
  single highest count but below 60% (e.g., 8 of 20 = 40%)
- "mixed" or "contested": two or more types are tied or
  within 2 entities of each other

Example: counselling 6, media 6, legal 4, directory 3 out of
20 classified → "mixed, with counselling and media tied at 6
each and legal at 4." NOT "counselling dominance."

Example: counselling 17, directory 3, nonprofit 2 out of 24
classified → "dominated by counselling entities (17 of 24,
71%)."

Example: legal 12, counselling 5 out of 24 classified →
"legal plurality (12 of 24, 50%) with counselling secondary
at 5." NOT "dominated by legal" (50% is below the 60%
threshold).
```

### Code Fix

The extraction code's `keyword_profiles` currently sets
`entity_dominant_type` to the top entity from
`entity_by_kw[kw].most_common(1)` but sets it to `None` when
... unclear conditions apply (it's `None` for all 6 keywords in
the current data).

Make `entity_dominant_type` deterministic and useful. In
`extract_analysis_data_from_json()`, change the logic to:

```python
# After computing entity_by_kw[kw]:
classified_total = sum(entity_by_kw.get(kw, Counter()).values())
if classified_total > 0:
    top_entity, top_count = entity_by_kw[kw].most_common(1)[0]
    second_count = entity_by_kw[kw].most_common(2)[1][1] if len(entity_by_kw[kw]) > 1 else 0
    top_pct = top_count / classified_total

    if top_pct >= 0.60:
        entity_label = f"dominated_by_{top_entity}"
    elif top_count > second_count:
        entity_label = f"{top_entity}_plurality"
    else:
        # Tied or very close
        tied = [et for et, c in entity_by_kw[kw].most_common() if c == top_count]
        entity_label = f"mixed_{'_'.join(sorted(tied))}"
else:
    entity_label = "unclassified"
```

Add `entity_label` to the keyword_profiles dict:

```python
keyword_profiles[kw] = {
    # ... existing fields ...
    "entity_dominant_type": dominant[0][0] if dominant else None,
    "entity_label": entity_label,  # NEW: pre-computed label
    # ...
}
```

Update the system prompt data dictionary to describe this field:

```
- entity_label: pre-computed entity mix classification. One of:
  "dominated_by_[type]" (>60% of classified),
  "[type]_plurality" (highest but <60%),
  "mixed_[type1]_[type2]" (tied top types),
  "unclassified" (no classified entities).
  Use this label directly in Section 2 per-keyword profiles.
```

Add to the system prompt's Rule 9:

```
Use entity_label from keyword_profiles as the starting point
for entity descriptions. You may expand on it (e.g., add the
counts) but do not contradict it.
```

### Verification

After the code change, run the extraction and check:

```python
for kw, profile in extracted['keyword_profiles'].items():
    print(f"{kw}: {profile['entity_label']}")
```

Expected output (approximately):
```
estrangement: legal_plurality
estrangement from adult children: mixed_counselling_media
estrangement grief: counselling_plurality
family cutoff counselling Vancouver: dominated_by_counselling
reunification counselling BC: counselling_plurality
reunification therapy near me: counselling_plurality
```

Then run the LLM report and check Section 2:
- "estrangement from adult children" should NOT say "counselling
  dominance" — it should say "mixed" or "counselling and media
  tied"
- "family cutoff counselling Vancouver" SHOULD say "dominated by
  counselling" (17/24 = 71%)
- "estrangement" should say "legal plurality" not "legal
  dominated" (12/24 = 50%)

---

## Fix 4 (Optional): Strengthen Validation for These Patterns

If you want the validator to catch these errors automatically,
add these checks to `validate_llm_report()`:

```python
# Check for speculative causal language about data anomalies
speculative_patterns = [
    r'indicating (technical|content|data|system)',
    r'suggesting (a |that |some )(bug|issue|problem|filter)',
    r'possibly due to',
    r'likely (because|due|caused)',
]
for pattern in speculative_patterns:
    if re.search(pattern, report_lower):
        issues.append(
            f"Report contains speculative causal language "
            f"matching pattern: {pattern}"
        )

# Check AIO count against pre-computed flags
aio_count_in_data = sum(
    1 for kw, profile in extracted.get("keyword_profiles", {}).items()
    if profile.get("has_ai_overview")
)
# Look for "N of 6 queries" pattern in report
aio_count_match = re.search(
    r'(\d+)\s+of\s+\d+\s+quer(?:y|ies)\s+'
    r'(?:feature|have|show|trigger)',
    report_text, re.IGNORECASE
)
if aio_count_match:
    reported_count = int(aio_count_match.group(1))
    if reported_count != aio_count_in_data:
        issues.append(
            f"Report says {reported_count} queries have AIO "
            f"but keyword_profiles shows {aio_count_in_data}."
        )
```

These are lightweight checks that would catch both errors seen in
the current report. They don't replace the prompt fixes — they
provide a safety net for when the model doesn't follow the rules.

---

## Summary of Changes

| Fix | Type | What Changes | Effort |
|---|---|---|---|
| 1: AIO count | Prompt | Add Rule 11 with worked example | Small |
| 2: Speculation | Prompt | Extend Rule 8 with prohibition + examples | Small |
| 3: Entity mix | Prompt + Code | Worked examples in Rule 9, new `entity_label` field in extraction | Medium |
| 4: Validation | Code | Two new checks in `validate_llm_report()` | Small |

Apply fixes 1–3 first and re-run the report. If the errors
persist after the prompt + code changes, add fix 4 as a validator
safety net.
