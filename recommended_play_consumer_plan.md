# Chip C — "Recommended Play" consumer: implementation plan

**Spec parent:** `seo_geo_review_20260704.md` (T.4 rank-vs-citation "two separate
scores" + the hyper-local pivot mechanism it critiques).
**Chip role:** CONSUMER (C of 3). Renders + enforces the pre-computed
`keyword_profiles[kw].recommended_play` verdict that **chip A** produces. The LLM
only *narrates* the verdict; it may never contradict it.
**Status of dependency:** chip A is **NOT merged** anywhere (no `play_routing.yml`,
no `recommended_play` field on `main`, the three sibling `claude/*` worktrees, or
`wip-multi-client-config`). This plan is written against the **assumed schema**
below and must be confirmed before code lands.

---

## 0. Assumed chip-A schema (CONFIRM before wiring)

`brief_data_extraction.py:1629` (`keyword_profiles[kw] = {...}`) gains one field:

```python
"recommended_play": {
    "play": str,            # machine token: "rank_play" | "extraction_play"
                            #   | "local_pivot_play" | "avoid_play" (chip A owns the set)
    "label": str,           # human label rendered in reports, e.g. "Rank Play"
    "strategy_text": str,   # one-line strategy sentence
    "evidence": list[str],  # supporting signals (DA gap, aio_divergence, AIO presence…)
    "data_available": bool, # honesty flag — False when inputs were missing;
                            #   consumers render an honest "inputs missing" note, never fake
}
```

**Persistence path (verified):** the field rides the existing pipeline to disk with
no extra plumbing — `serp_audit.py:1967-1985` calls
`extract_analysis_data_from_json` and writes `full_data["keyword_profiles"]` into
`market_analysis_*.json`. Therefore all three consumer sites already receive it:
`run_feasibility.py:530` (loads that JSON), `generate_insight_report.py`
(loads that JSON), and the brief pipeline (rebuilds profiles in-memory via the same
extractor).

**Consumer discipline:** chip C reads `label` / `strategy_text` / `evidence` /
`data_available` **verbatim** and does **not** hardcode the play taxonomy. The play
vocabulary (tokens, labels, and claim phrases used for validation) is loaded from
**`play_routing.yml`** (chip A's config) so the editorial surface stays in YAML,
per the project's editorial-content rule.

**Reconciliation notes vs the chip-C brief:**
- The brief named `generate_content_brief.py` for validation; the function actually
  lives in **`brief_validation.py::validate_llm_report`** and is re-exported through
  `generate_content_brief` (`generate_content_brief.py:29`), so the canary's
  `inspect.getsource(generate_content_brief.validate_llm_report)` still resolves.
  Rule is edited in `brief_validation.py`.
- `*.validation.md` is written by `brief_rendering.py::write_validation_artifact`
  (unchanged — kept as the failure path).

---

## 1. Acceptance criteria → tests (spec IDs verbatim in code + test names)

| ID | Criterion | Verifying test |
|----|-----------|----------------|
| **RP-C.1** | `feasibility_*.md` renders a **Recommended Play** column. For a **non-service informational** keyword whose play is `extraction_play`, the cell shows the play label + one-line `strategy_text` + evidence — **not** a hyper-local pivot. When `data_available` is False the cell states inputs were missing, never fabricates. | `test_feasibility.py::test_rpc1_recommended_play_column_extraction_not_pivot`, `::test_rpc1_recommended_play_honest_when_data_missing` |
| **RP-C.2** | `market_analysis_*.md` renders a per-keyword **play line** in both the SERP-intent section (5b) and the feasibility section (5c). | `tests/test_report_clarity.py::test_rpc2_play_line_in_intent_section`, `::test_rpc2_play_line_in_feasibility_section` |
| **RP-C.3** | The main-report prompt (`prompts/main_report/system.md`) documents `keyword_profiles.recommended_play`, and **Section 7** instructs the report to STATE and FOLLOW each keyword's play — `rank_play` → ranking success metric, `extraction_play` → "AIO citation" success metric. | `test_generate_content_brief.py::test_rpc3_prompt_documents_recommended_play`, `::test_rpc3_section7_states_and_follows_play` |
| **RP-C.4** | `validate_llm_report` adds a rule: if the report assigns a **different** play than the pre-computed one for a keyword, it fails. A play mismatch is mechanically checkable → **HARD** fail (no retry); artifact written to `*.validation.md`. | `test_generate_content_brief.py::test_rpc4_play_mismatch_is_hard_fail`, `::test_rpc4_matching_play_passes` |
| **RP-C.5** | Canary parity: `keyword_profiles.recommended_play` referenced in the prompt has a matching mention in `validate_llm_report`; `test_validation_consistency.py` passes with the new field registered (rule, not KNOWN_UNVALIDATED allowlist). | `test_validation_consistency.py::test_all_prompt_fields_covered_by_validator` (existing, must stay green) + new `::test_recommended_play_covered` |
| **RP-C.6** | Payload passthrough: `build_main_report_payload` includes `recommended_play` so the LLM can actually narrate it. | `test_generate_content_brief.py::test_rpc6_payload_includes_recommended_play` |
| **RP-C.7** | Docs updated **in the same commits**: `docs/methodology.md`, `docs/USER_MANUAL.md` (WHAT the play is + WHY the two-score rank-vs-citation model matters, birth-order example), `docs/config_reference.md` (`play_routing.yml` consumer keys), regenerated `docs/spec_coverage.md`. | Doc-presence assertions: `tests/test_report_clarity.py::test_rpc7_docs_document_recommended_play` (greps the three docs for required anchors) |

---

## 2. Implementation order (dependencies first)

**Chunk 1 — validation core + canary (RP-C.4, RP-C.5, RP-C.6).** Highest-stakes /
most-likely-to-regress (P10), so its tests are written FIRST.
1. `brief_prompts.py::build_main_report_payload` (~line 126): add
   `"recommended_play": profile.get("recommended_play")` to the per-keyword payload. *(RP-C.6)*
2. `play_routing.yml` **consumer contract**: add (or read, if chip A already ships it)
   a `play_labels` / `play_claim_phrases` block the validator can load. Coordinate
   with chip A — if chip A already defines the taxonomy, consume it; do not fork.
3. `brief_validation.py`: add `PLAY_CLAIM_PHRASES` loaded from `play_routing.yml`
   and a rule in `validate_llm_report` — per keyword, if the report section asserts a
   play label ≠ the pre-computed `recommended_play["label"]`/`["play"]`, append an
   issue whose text contains the literal `recommended_play` (satisfies the canary) and
   the HARD marker (see §3). *(RP-C.4)* Mirror `INTENT_CLAIM_PHRASES` structure.
4. `prompts/main_report/system.md`: add a `keyword_profiles.recommended_play`
   documentation block near the other pre-computed fields (~line 46-87). *(RP-C.5 wiring)*
5. Write chunk-1 tests. Run full suite. Commit when green.

**Chunk 2 — feasibility report column (RP-C.1).**
6. `run_feasibility.py`: header (`:413`) gains a `Recommended Play` column; row loop
   (`:416-437`) joins `data["keyword_profiles"][kw]["recommended_play"]` and renders
   `label — strategy_text` (+ compact evidence), with an honest "inputs missing" cell
   when `data_available` is False. The pivot column is left to chip B (empty/— for
   non-service). A small pure helper `format_play_cell(play_obj)` holds the logic so it
   is unit-testable without file I/O.
7. Tests + suite + commit.

**Chunk 3 — market_analysis play lines (RP-C.2).**
8. `generate_insight_report.py`: `_render_serp_intent_section` (`:912-950`) gains a
   `- **Recommended play:** …` line; the feasibility table (`:667-699`) gains the same
   `Recommended Play` column via the shared `format_play_cell` helper.
9. Tests + suite + commit.

**Chunk 4 — Section 7 STATE-and-FOLLOW + docs (RP-C.3, RP-C.7).**
10. `prompts/main_report/system.md` Section 7 (`:553-570`): add instruction to state
    each non-skip keyword's `recommended_play.label` and choose the success metric by
    play (`rank_play`→rank improvement; `extraction_play`→AIO citation gain). Keep
    within the existing "What success looks like" bullet to avoid contradicting the
    pre-computed verdict.
11. Docs (RP-C.7): `docs/methodology.md`, `docs/USER_MANUAL.md`,
    `docs/config_reference.md`, regenerate `docs/spec_coverage.md`.
12. Tests + suite + commit.

---

## 3. HARD/SOFT severity design (mechanically grounded)

Control flow (`brief_rendering.py:543-583`): `validate_llm_report` → issues →
`partition_validation_issues` (soft = "notes") → if only notes, write with notes; elif
`has_hard_validation_failures(blocking)`, **fail-fast no retry**; else **one retry**.

The chip-C brief says a play mismatch is mechanically checkable → treat as **HARD**.
Realization:
- The issue string is phrased `"...but keyword_profiles.recommended_play shows
  play='<label>'..."` — it will **not** match any `partition_validation_issues` note
  pattern, so it stays in `blocking`.
- Add one line to `has_hard_validation_failures` (`brief_validation.py:457`):
  `if "but keyword_profiles.recommended_play shows" in normalized: return True` —
  parallel to the existing intent HARD detector. → no retry, artifact written, `exit(2)`.

---

## 4. Adversarial / dirty-state / honesty test obligations (from ~/.claude rules)

- **P7 adversarial (RP-C.4):** a report that *looks* authoritative but assigns
  `Rank Play` to a keyword whose pre-computed play is `extraction_play` must FAIL.
- **Honesty (RP-C.1):** `data_available=False` → the report cell states inputs were
  missing; assert no fabricated label/strategy is emitted (never fill from title/memory).
- **P6 verify-against-artifact:** the validator compares the LLM's stated play to the
  pre-computed field that actually exists in the payload, not a remembered value.

---

## 5. Open items to CONFIRM (blocking)

1. **Chip-A schema.** Field shape + play token/label set above — confirm, or point me
   at chip A's landed output so I follow it verbatim and note the reconciliation.
2. **`play_routing.yml` ownership of the validation vocabulary.** Does chip A's YAML
   expose play labels/claim phrases the validator can load, or should chip C add a
   consumer block? (Preference: chip A owns it; chip C reads it.)
3. **Proceed now vs wait.** Build the tolerant consumer now against the assumed schema
   (with a temporary local `recommended_play` fixture in tests so the suite is green
   before chip A lands), or block until chip A merges?

*No implementation code will be written until these are confirmed.*
