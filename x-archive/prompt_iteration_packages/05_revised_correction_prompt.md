# Revised Correction Prompt

## user_template.md

```md
SURGICAL REVISION — preserve valid content, fix only what failed.

A previous draft failed evidence validation. The rejected claims
are listed below. Your job is to produce a corrected version of
the full document with minimal changes.

## Rules

1. PRESERVE VALID SECTIONS. If a section contains no rejected
   claims, copy it unchanged. Do not rephrase, reorganize, or
   "improve" sections that passed validation.

2. FOR EACH REJECTED CLAIM, choose exactly one of these repairs:
   a) DELETE the sentence or paragraph containing the claim if
      no verified evidence supports it.
   b) NARROW the claim to what the evidence actually shows. For
      example, change "appears across multiple clusters" to
      "appears for one keyword" if that is what the data confirms.
   c) SOFTEN the claim with uncertainty language if partial
      evidence exists but the original statement overstated it.
      For example, change "strongly supported" to "limited
      evidence in organic snippets only."

3. DO NOT INVENT NEW EVIDENCE to replace a rejected claim. If the
   claim was rejected because evidence is absent, the fix is
   deletion or acknowledgment of absence — not fabrication of
   alternative support.

4. DO NOT ADD NEW SECTIONS, recommendations, or analysis that
   did not exist in the original draft. The correction pass fixes
   errors; it does not expand scope.

5. RETURN THE FULL CORRECTED DOCUMENT, not notes about corrections.

## Rejected Claims

{{VALIDATION_ISSUES}}

## Revision Checklist

Before returning the document, verify:
- Every rejected claim has been deleted, narrowed, or softened
- No new unsupported claims have been introduced
- Sections not implicated by rejected claims are unchanged
- The document is complete (all original sections present)
```

---

## Rationale

### 1. "Surgical revision" framing replaces generic "revise" instruction
The current prompt says "Revise it so every claim matches the verified evidence exactly." This is an open invitation to rewrite the entire document, which is what the LLM does — it regenerates from scratch, introducing new errors in sections that were originally correct. The new prompt's opening line ("preserve valid content, fix only what failed") and Rule 1 ("copy it unchanged") make preservation the default behavior and changes the exception.

### 2. Three explicit repair options replace the binary keep/delete
The current prompt says "Delete unsupported claims if you cannot restate them with verified evidence." This creates a binary: delete or find new evidence. Finding new evidence is exactly the fabrication behavior we want to prevent. The new prompt offers three graduated options — delete, narrow, or soften — and explicitly prohibits inventing replacement evidence (Rule 3). This gives the LLM a middle path between deletion and fabrication that the current prompt doesn't provide.

For the specific "toxic" failure: the rejected report's Section 6 correctly stated "The Blame/Reactivity Trap - NOT SUPPORTED: Zero trigger occurrences." The fabrication was elsewhere — a cross-cutting toxic opportunity claim, probably in Section 5 or 7. The correction should delete that specific claim while preserving the accurate Section 6 assessment. The current prompt risks the LLM rewriting Section 6 as well during its broad revision pass.

### 3. No-expansion rule prevents scope creep on retries
The current prompt doesn't prevent the LLM from adding new content during correction. A common failure pattern: the LLM deletes the rejected claim, then fills the gap with a new paragraph that introduces a different unsupported claim. Rule 4 ("do not add new sections, recommendations, or analysis") closes this path. The correction pass is subtractive or narrowing, never additive.

### 4. Revision checklist acts as a self-check gate
The four-item checklist at the end forces the LLM to verify its own output before returning it. This is a lightweight technique that reduces the chance of the corrected document failing validation a second time. It's not a guarantee, but it adds a verification step that the current prompt lacks entirely.

---

## Token Efficiency Note

The current correction prompt triggers near-complete regeneration of the document because it provides no instruction to preserve valid sections. For an 8-section report of ~4,000 words, this means the retry outputs ~4,000 words even when only 1-2 sentences need to change. The revised prompt's preservation-first approach means the LLM copies 7+ sections verbatim and only generates new text for the specific sentences implicated by the rejected claims. In practice this won't reduce output tokens dramatically (the LLM still returns the full document), but it reduces the cognitive work the LLM does per section, which reduces the probability of introducing new errors during the rewrite. The primary token savings come from avoiding a third retry: if the surgical correction passes validation on the first attempt, you save the cost of an entire additional API call (~50K input tokens + 4K output tokens at current payload sizes).
