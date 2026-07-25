# serp-discover — Suite Enhancement Spec (v1, self-contained)

Origin: split from the cross-tool master `suite_enhancement_spec_v1.md` (**in this
repo**), derived from `three_tool_audit_review_20260721.md` (also here).
**This file is self-contained** — serp-discover's items are inlined below. The
master remains the cross-tool reference and holds the full item set.

Commits MUST carry `Spec: suite_enhancement_spec_v1.md#<item>`.

## Decisions applied (2026-07-21, from the owner)

- **Apps stay independent** — no forced shared client profile across all three
  tools. The **X-1** orchestration/shared-profile item is **dropped as a shared
  feature** (optional personal runner only, if ever wanted).
- **Phase 1 for this repo is just the X-4 doc note.** serp-discover's larger items
  are either deferred (X-2, X-3) or already specified elsewhere (SD-1).

## Read first (this repo)

`CLAUDE.md`; `methodology.md` (contract doc — update in the same change as any file
it references); `seo_geo_deferred_spec_v1.md`; `probe_ai_visibility.py`,
`gsc_client.py`, `storage.py`, `config.yml`, `brief_data_extraction.py`.

---

## X-4 — Backlink-exclusion note  · Phase 1 · docs only

Add a short **"Out of scope: backlink graph analysis"** note to `methodology.md`
(extend the existing "What the tool does NOT do" section): the suite uses Domain
Authority as the sole authority proxy; full backlink/toxic-link/disavow analysis
needs a paid link-graph provider and is judged low-ROI for one nonprofit; revisit
only if scale or budget changes.

**Acceptance criteria.** X-4.1 The note exists in `methodology.md`, wording
consistent across the three repos. No code/test change.

---

## X-2 — Close the AI-citation loop (ingest side)  · deferred, optional

Because apps stay independent, this is an **optional** bridge for owners who run
both TalkingToad and serp-discover; **not Phase 1**.

**If built later.**
1. serp-discover ingests TalkingToad's client-citation export (optional input path
   in `config.yml`; `data_available: false` when absent — no crash, no fabricated
   citations).
2. Use it in citation-surface / GEO analysis and to target "ranks-but-not-cited"
   alerts at the exact URLs TalkingToad marks high-value-but-uncited.
3. HARD rule: ingested citations are **evidence** the LLM may not contradict — add
   a validator/canary entry if it becomes a `keyword_profiles.<field>`
   (`test_validation_consistency.py` convention).

**Open code-check (#7):** the `AI_CITED_PAGE` data source + export shape live on
the TalkingToad side and are currently unknown — resolve before wiring.

**Acceptance criteria (when built).**
- X-2.2 Ingests the export when present; `data_available: false` (no crash) when
  absent — both paths tested.
- X-2.3 A "ranks-but-not-cited" alert is emitted for a URL that ranks in the
  analysis JSON and appears in TalkingToad's high-value-uncited list.
- X-2.4 Canary/validator convention satisfied if a new keyword-profile field is
  added.

---

## X-3 — Scheduled audit cadence  · deferred

**If built later.** Provide ready-to-use schedule definitions (docs) for a
quarterly full run and a monthly light run (TalkingToad re-crawl + serp-discover
AI-visibility probe), framed as change-over-time; cadence/label values in config,
not hardcoded; no bundled scheduler.

**Acceptance criteria (when built).** X-3.1 Docs contain copy-pasteable
quarterly/monthly schedule commands. X-3.2 Cadence/label values config-driven.

> Note: X-3 originally leaned on X-1's combined runner. With X-1 dropped, X-3 (if
> wanted) schedules each tool's existing entry points independently.

---

## Not in this spec — already specified elsewhere

- **SD-1**: the review's EEAT (G.3) and GSC (G.4) items are already fully specified
  in `seo_geo_deferred_spec_v1.md`. **Ship those from that spec.** No duplicate
  scope here.

## Out of scope (this repo)

- **X-1** shared client profile / suite orchestration — dropped as a shared
  feature per the keep-apps-independent decision; keep only as an optional personal
  runner if ever wanted.
