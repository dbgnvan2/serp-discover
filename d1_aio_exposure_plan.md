# D1 — AI Overview & Zero-Click Exposure — Implementation Plan

**Feature:** `discover-spec.md` **D1** · proposed spec-ID namespace **AV.1** (per
`RECONCILIATION_CHANGES.md` — Discover uses `AV.x`).
**Status:** PLAN — no implementation code written yet. Awaiting approval.
**Spec:** `discover-spec.md#D1`. **This plan file:** `d1_aio_exposure_plan.md`.

> Per the workflow rules: this is the *planning* step. Nothing below is built yet.
> On approval, implementation proceeds in the order in §7, tests-first per §6.

---

## 1. What D1 adds (one sentence)

A **modeled, market-side estimate** of the click impact of AI Overviews per
tracked keyword — a new `## 5c. AI Overview Exposure` report section, a persisted
`ai_aio_exposure` table for trend, and a run-level rollup — built entirely from
signals already on `keyword_profiles` (no new SERP fetch, no LLM call).

## 2. Verified reuse (checked in code — the spec's "verify in code" caveat)

| Spec claim | Verified location | Note |
|---|---|---|
| AIO presence flag | `brief_data_extraction.py:1667` `has_ai_overview` | → `aio_present` |
| Client organic rank | `brief_data_extraction.py:1682` `client_rank` (None if unranked) | → `organic_position` |
| Client cited in AIO | `brief_data_extraction.py:1684` `client_aio_cited` | **direct** `client_cited` signal (see D-1) |
| Divergence block | `brief_data_extraction.py:1688` `aio_divergence` (`_build_aio_divergence` @798) | cross-check |
| AIO cited sources | `brief_data_extraction.py:1675` `aio_top_sources` (domain,count) | → `cited_urls_json` (domains — see D-7) |
| Registrable-domain match | `brief_data_extraction.py:70` `_is_client_domain` | reuse verbatim |
| Table/persist/render template | `citation_table.py` (init/save/get @186–233, render @240) | copy the shape |
| Weights + fallback + `weights_json` | `aivi.py:49` `resolve_weights`, persist @154 | copy the pattern |
| Report entry (pure) | `generate_insight_report.py:401` `generate_report(data)`; 5b @648/@910 | render here |
| Production run of the report | `serp-me.py:1044` → `generate_insight_report.py --json --out` | wire persistence in `main()` @982 |
| DB | `storage.py:26` `SerpStorage(db_path="serp_data.db")` | same DB file |

**All D1 inputs already exist on `keyword_profiles`.** No re-parse, no new field
on `keyword_profiles` (so `test_validation_consistency.py` canary is **not**
triggered — confirmed the spec's "don't add a `keyword_profiles.<field>`" path).

## 3. Design decisions (⚑ = needs owner approval before build)

- **D-1 ⚑ `client_cited` source.** The spec reconstructs a formula
  (`not client_ranks_but_not_cited AND has_aio_citations AND client_in_top10-or-cited`).
  The repo already computes the ground-truth field `client_aio_cited`
  (`= client domain is among the AIO's cited sources`, `brief_data_extraction.py:1684`).
  **Plan: use `client_aio_cited` directly** (a P6/P11 "verify against ground truth"
  improvement over the reconstructed proxy). It satisfies the acceptance criteria
  ("AIO lists the client → client_cited=true") exactly. Divergence block used only
  as a consistency cross-check. *Deviation from the spec's literal formula — approve.*
- **D-2 ⚑ `generate_report` signature.** Add **optional** params:
  `generate_report(data, db_path=None, run_ts=None)`. Rendering of the 5c section
  always runs from `data["keyword_profiles"]` (like 5b). **Persistence + trend only
  when `db_path`+`run_ts` are supplied** (i.e. from `main()`), so the existing pure
  test contract `generate_report(data)` is unchanged. Backward-compatible.
- **D-3 ⚑ No new GUI step.** The 5c section rides the **existing** market-analysis
  report step (`serp-me.py:1044`). `main()` derives `run_ts` from the `--json`
  filename (`market_analysis_{topic}_{YYYYMMDD_HHMM}.json`) and defaults
  `db=serp_data.db` → persistence activates with **zero `serp-me.py` change**.
  (Alternative: add explicit `--run-ts`/`--db` args + pass them from the GUI. More
  surface, more P13 guard-scope risk. Recommend the zero-change path.) *Approve.*
- **D-4 Unranked-but-cited modeling.** `ctr_base(None) = 0.0` (you cannot lose
  organic CTR on a position you do not hold). So an unranked-but-cited keyword is
  recorded with `organic_position=NULL`, `client_cited=true`, `est_ctr_loss=0.0`.
  This is a *good* outcome (cited without ranking), correctly modeled as no loss.
- **D-5 Reference constants (themed-statistic rule).** `aio_ctr_multiplier`
  (default `0.60`, the industry "~60% AIO CTR drop" reference), `citation_credit`
  (default `0.5`), and the organic `ctr_curve` all live in `config.yml`, labelled
  **"estimated / industry reference"** in the report — never presented as measured
  livingsystems.ca CTR (cross-cutting requirement).
- **D-6 `source` column** = `"google"` (SERP provider), mirroring the AI tables'
  per-engine `source`/`engine` column, so a future non-Google SERP source is additive.
- **D-7 `cited_urls_json`.** `keyword_profiles` carries cited **domains**
  (`aio_top_sources`), not full URLs, at profile level. Store the cited-domain list
  (honest to available data). Column keeps the spec name; note documents the nuance.

## 4. Data model — new table (built like `citation_table.CITATIONS_TABLE`)

```
ai_aio_exposure (
  run_ts           TEXT,     -- run identity (from the market_analysis_* timestamp)
  keyword          TEXT,
  source           TEXT,     -- "google" (D-6)
  aio_present      INTEGER,  -- has_ai_overview
  client_cited     INTEGER,  -- client_aio_cited (D-1)
  cited_urls_json  TEXT,     -- JSON list of cited domains (D-7); [] when none
  organic_position INTEGER,  -- client_rank; NULL if unranked (D-4)
  est_ctr_loss     REAL,     -- heuristic (§5)
  weights_json     TEXT      -- {aio_ctr_multiplier, citation_credit, ctr_curve} used
)
```
Own `sqlite3.connect`, `CREATE TABLE IF NOT EXISTS`, UTC `run_ts` — no new column
on any existing table, no `keyword_profiles` field.

## 5. Core logic (new module `aio_exposure.py`; heuristic; constants from config)

```
resolve_exposure_config(cfg) -> {aio_ctr_multiplier, citation_credit, ctr_curve}
    # mirror aivi.resolve_weights: missing/malformed -> documented defaults + warning

ctr_base(position, curve) -> float          # curve[pos]; position None or > max -> 0.0

est_ctr_loss(position, aio_present, client_cited, cfg):
    if not aio_present: return 0.0
    loss = ctr_base(position, cfg.ctr_curve) * cfg.aio_ctr_multiplier
    if client_cited: loss *= (1 - cfg.citation_credit)
    return round(loss, 4)

compute_aio_exposure(keyword_profiles, cfg) -> (rows, rollup)
    rows: one per keyword (fields = §4, minus run_ts)
    rollup: {aio_coverage_pct = aio_present_kw / total_kw,
             cited_share      = client_cited_kw / max(aio_present_kw,1)}
```
Persistence + trend (copy `citation_table` + `aivi.get_aivi_trend` shapes):
`init_aio_exposure_table`, `save_aio_exposure(db, run_ts, rows)`,
`get_aio_exposure_for_run(db, run_ts)`, `get_aio_exposure_trend(db, limit)`
(per-run rollup series, `history_runs` from config).
Render: `render_aio_exposure_section(rows, rollup, trend=None) -> list[str]`
— `## 5c. AI Overview Exposure`, sortable table `keyword | organic position |
AIO present | client cited? | est. CTR loss`, **default sort = highest
`est_ctr_loss` where `client_cited=false` first**, estimates labelled, rollup +
optional trend delta line.

## 6. Acceptance criteria → test map (write scoring tests FIRST — P10)

New test file `tests/test_aio_exposure.py` unless noted. Every test name carries
its AV id.

| ID | Criterion (spec) | Test |
|---|---|---|
| **AV.1.1** | AIO lists client → `client_cited=true`, loss ×`(1-citation_credit)` | `test_av1_1_client_cited_reduces_loss` |
| **AV.1.2** | AIO not listing client → `client_cited=false`, full multiplier | `test_av1_2_not_cited_full_multiplier` |
| **AV.1.3** | `aio_coverage_pct` = AIO-present / total tracked | `test_av1_3_coverage_pct_rollup` |
| **AV.1.4** | estimates labelled; `0.60`/`0.5`/curve from config not literals | `test_av1_4_constants_from_config` (override cfg → score changes) + `test_markdown_rendering.py::test_av1_4_report_labels_estimates` |
| **AV.1.5** | AIO present, empty citations → `aio_present=1, cited_urls=[]`, full mult | `test_av1_5_aio_present_empty_citations` |
| **AV.1.6** | client unranked but cited → `organic_position=NULL`, `client_cited=true`, loss 0 | `test_av1_6_unranked_but_cited` |
| **AV.1.7** | registrable-domain match (not URL-exact); look-alike domain excluded | `test_av1_7_registrable_domain_match` |
| **AV.1.8** (P7) | identical kw: cited variant scores **lower** risk; at-risk queue ranks non-cited above cited | `test_av1_8_adversarial_cited_scores_lower` |
| **AV.1.9** (P8) | dirty-state: pre-seed a prior `run_ts`; rerun → section shows only new run, trend includes prior, no double-count | `test_av1_9_dirty_state_trend` |
| **AV.1.10** | reproducible: same snapshot + `weights_json` → identical rows (no wall-clock/random) | `test_av1_10_reproducible` |
| **AV.1.11** (P21) | section present in report from a `data` dict (removing the call fails); `main()` persists rows on a fixture json | `test_markdown_rendering.py::test_av1_11_section_present` + `test_av1_11_main_persists_rows` |
| **AV.1.12** | docs contract: `methodology.md` documents AIO exposure | `test_av1_12_methodology_documents_aio_exposure` |

**Highest-impact first (P10):** AV.1.1 / AV.1.2 / AV.1.8 (the `est_ctr_loss`
heuristic + `client_cited` mapping) — the scoring, most likely to regress.

**Not code-testable (human review):** whether the *reference numbers* themselves
(`0.60`, `0.5`, the `ctr_curve` values) are the right editorial values. Tests can
only prove they are **sourced from config**, not that a value is "correct."
Proposed: owner signs off on the curve/defaults as reference points in `config.yml`.

## 7. Implementation order & dependencies

1. `aio_exposure.py` compute + `ctr_base` + `resolve_exposure_config` + rollup (pure).
   → tests AV.1.1,1.2,1.3,1.5,1.6,1.7,1.8,1.10.
2. `config.yml` `aio_exposure:` block (after `aivi:`) + optional light type-check in
   `validate_config_yml`. → AV.1.4 (config half).
3. Persistence: `init/save/get/trend` (mirror `citation_table`). → table exists.
4. Render `render_aio_exposure_section` + wire into `generate_report` after 5b
   (`generate_insight_report.py:648`). → AV.1.11 (section) + AV.1.4 (label half).
5. `main()` (@982): optional `db_path`/`run_ts` (run_ts parsed from `--json`),
   persist + fetch trend, pass to `generate_report`. → AV.1.9 dirty-state, AV.1.11 persist.
6. Docs: `docs/methodology.md` (new subsection, Part 2), `docs/USER_MANUAL.md`
   (what/why: AIO interception, est-CTR-loss, "estimated"), `docs/spec_coverage.md`
   (AV.1 row). → AV.1.12.
7. Full suite green (`python3 -m pytest test_*.py tests/ -q`).

Dependency chain: 1 → 3 → 5 (persist/trend); 1 → 4 (render); 4 → 5 (main passes data).

## 8. Adjacent issues found, not fixed (rule #10 — flagged, not swept)

- **config.yml comment-stripping regression** (already surfaced separately) — the
  working-tree `config.yml` lost `gsc:`/`geo:` comments; likely `config_manager.py`
  save path. Not part of D1; do not commit that file with D1.
- **`validate_config_yml` doesn't reject unknown top-level keys** (`config_validators.py:409`).
  Benign for D1 (new block won't be rejected); noted, not changed beyond adding an
  optional type-check for `aio_exposure`.
- **`serp-me.py:1048` `--out` uses `report_out`** (`content_opportunities_*.md`) while
  `output_md` is `market_analysis_*.md` — possible output-name confusion in the GUI
  step. Not D1's concern; flagged for a separate look.

## 9. Docs to update in the same change (contract)

`docs/methodology.md` (Part 2 subsection), `docs/USER_MANUAL.md` (feature +
reasoning), `docs/spec_coverage.md` (AV.1 entry). No `docs/gui_steps.md` change
(no new step — D-3). Commits carry `Spec: discover-spec.md#D1`.

## 10. Out of scope for D1

D2–D5. GSC-based first-party CTR (that's D2/`compute_sponge_effect`, already built).
No new SERP fetch, no LLM call, no `keyword_profiles` field, no new GUI step.
