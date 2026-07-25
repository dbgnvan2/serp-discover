# D2–D5 — Consolidated Implementation Plan (AV.2–AV.5)

**Features:** `discover-spec.md` D2–D5 · namespace **AV.2–AV.5**.
**Status:** PLAN — no implementation code yet. Awaiting approval + the ⚑ decisions.
**Grounding:** verified in code by four scouts (file:line throughout). Several spec
assumptions **did not survive contact with the real code** — flagged below.

> Plan-before-code step. On approval I build in the order in §2, tests-first, each
> feature → `learning-qa` review → commit (the D1 loop).

---

## 1. Reality check (what the grounding changed)

| Feature | Spec status | Buildable **now**? | The catch |
|---|---|---|---|
| **D5** own-brand monitor | already-exists | ✅ **Yes, fully** | 2 tiny extensions; full answer text already on the row, just not persisted |
| **D4** commodity risk | partially-exists | ✅ **Yes, deterministic core** | `answer_similarity` needs snippet text (recoverable); LLM probe stays OFF; `engine_transfer` is **not** a usable term on the report run |
| **D2** branded demand | partially-exists | ⚠️ **Yes, with a grain decision** | GSC fetch has **no `date` dimension** → the spec's per-**day** grain + "provisional" flag aren't achievable without new fetch work |
| **D3** demand-vs-clicks | new | 🔴 **Snapshot only** | `search_volume` **exists nowhere in the repo**; the `divergence_flag` trend needs daily storage that doesn't exist; depends on D2 |

**Headline:** D4 and D5 are cleanly buildable. D2 needs one grain decision. **D3 as
specced is mostly not buildable** — no `search_volume` input, no daily time-series —
so it reduces to a point-in-time snapshot plus a deferred trend.

## 2. Recommended build order (dependency + risk)

1. **D5** (smallest, self-contained, zero deps) →
2. **D4** (self-contained on the report path, deterministic) →
3. **D2** (needs the grain decision; unblocks D3) →
4. **D3** (depends on D2 + a `search_volume` decision; snapshot now, trend deferred).

I recommend **building D5 + D4 first** (unblocked, high-confidence) while you settle
the D2/D3 data decisions.

---

## 3. Decisions needed (⚑ — these change what I build)

- **⚑ D-D2a — GSC demand grain.** The client fetches `dimensions:["query"]` only
  (`gsc_client.py:195`); `gsc_cache` is per-query-per-**window**, no daily rows. So
  the spec's `gsc_demand_daily(date, …)` and "mark recent days provisional" are not
  achievable as-written. **Recommend (a):** grain = **per-run** (`run_ts`), trend
  across successive runs (the repo's raw-sqlite second-run model); rename the table
  `gsc_demand_run`. Honest, no new fetch. **Alt (b):** add a `dimensions:["date","query"]`
  fetch to `gsc_client` — real new client work, breaks the spec's "reuse only" premise;
  defer as its own item.
- **⚑ D-D2b — Demand denominator.** `get_query_stats` returns only the **collected
  analysis queries**, not the full property. **Recommend:** compute
  `branded_click_share` over the tracked-query set for v1 and **label it as such**
  ("share across tracked queries," not "total site demand"); full-property demand is a
  later enhancement (read the full `_fetch_all_rows` set).
- **⚑ D-D4a — `answer_similarity` method.** No snippet text on `keyword_profiles`
  (discarded at `brief_data_extraction.py:1215`) and no embedding lib in-repo.
  **Recommend:** recover `Snippet` from `data["organic_results"]`
  (`generate_insight_report.py:870` precedent) and compute a **deterministic**
  token-set Jaccard / `difflib` similarity over title+snippet — satisfies the
  "reproducible given the same snapshot" criterion. **Not** embeddings (new dep,
  breaks reproducibility).
- **⚑ D-D4b — LLM "one-paragraph" probe.** The gated-LLM + call-budget machinery
  lives **only** on the probe path; `generate_report` is deterministic/no-LLM.
  **Recommend:** ship the **3-term deterministic composite** (answer_similarity,
  serp_homogeneity, aio_present), renormalized via the `aivi` None-axis pattern, with
  `one_paragraph_answerable` **OFF/`None` by default** (config-gated future term, no
  LLM plumbing added to the report path now). Matches the spec's "OFF by default."
- **⚑ D-D5a — `raw_answer` storage.** Full LLM `answer_text` already exists on the
  probe row (`probe_ai_visibility.py:816`); today it's truncated to a 400-char excerpt
  at persist. **Recommend:** store it behind `ai_visibility.store_raw_answer: false`
  (default off) with a length cap — unbounded verbatim LLM output is a size/PII risk.
- **⚑ D-D3 — scope.** With no `search_volume` and no daily grain, **recommend:** build
  D3's **point-in-time snapshot only** (a "Demand vs Clicks" section from D1
  `aio_coverage_pct` + GSC-cache clicks/impressions, using **GSC impressions as the
  volume proxy** for a normalized visibility line), and **defer the `divergence_flag`
  trend** to a follow-up once D2's per-run demand series exists and a real
  `search_volume` source is chosen. **Alt:** defer D3 entirely until then.

---

## 4. Per-feature plans

### AV.5 — Own-Brand AI Visibility (extend only) · smallest

**Verified:** full `answer_text` is on the probe row (`probe_ai_visibility.py:816`) but
`save_probe_rows` persists only `answer_excerpt[:400]` (`:740`); `_PROBE_MIGRATION_COLUMNS`
(`:698`) uses the ALTER-in-`try` pattern. `answer_sentiment` table has a `polarity`
label ∈ {positive,neutral,negative} (`answer_sentiment.py:39,201`); rendered by
`render_sentiment_section` (`:244`), wired at `probe_ai_visibility.py:1201`; gated by
`sentiment.enabled` (default off). C1 export **already shipped** (`ai_visibility_export.py`).

**Build:**
- **AV.5.1 raw_answer** — add `("raw_answer","TEXT")` to `_PROBE_MIGRATION_COLUMNS`;
  persist `row.get("answer_text")` in `save_probe_rows`, gated by
  `ai_visibility.store_raw_answer` (default false) + a length cap (D-D5a). Old rows read
  NULL (principle 3).
- **AV.5.2 negative-sentiment alert** — a helper beside `render_sentiment_section` that,
  **only when `sentiment.enabled`**, filters `sent_rows` for `polarity=="negative"` and
  emits an alert block; prints "not measured" when off (never fabricate). Surfaces in the
  existing `## Sentiment` section.

**Tests** (`tests/test_ai_visibility_extensions.py` or extend existing): AV.5.1 migration
+ gated persist (on→stored, off→NULL, cap enforced); AV.5.2 alert fires on a negative row,
silent/"not measured" when disabled (P8 gate invariant), no fabrication on zero rows.

### AV.4 — Query Commodity / AI-Absorption Risk · new `commodity_score.py`

**Verified reuse:** `keyword_profiles[kw]` has `has_ai_overview` (`:1667`),
`entity_distribution`/`entity_dominant_type` (`:1670`), `title_patterns` (`:1686`),
`recommended_play` (`:1785`), `top5_organic` titles (`:1673`). `aio_exposure.py` is the
structural template. **Corrections to the spec:** `get_entity_dominance` is **run-level**
(`metrics.py:118`) — use per-keyword `entity_distribution` + `title_patterns` variance
instead; `engine_transfer` is **probe-only** and **not a composite term** — do not wire it.

**Data model** `commodity_score(run_ts, keyword, answer_similarity, serp_homogeneity,
aio_present, one_paragraph_answerable, commodity_score, risk_band, weights_json)` — built
like `ai_aio_exposure`.

**Core logic** (mirrors `aio_exposure` + `aivi`): `answer_similarity` = deterministic
title+snippet similarity (D-D4a); `serp_homogeneity` from entity_distribution
concentration + title-pattern dominance; `aio_present` from the profile. Composite via
`aivi.resolve_weights`/`compute_aivi` with `commodity.weights` (default 0.4/0.3/0.2/0.1,
`one_paragraph_answerable=None` off → renormalize over 3). Bands <40/40–70/>70. `<3`
results or `<2` texts → `low_confidence`. Action routed through existing
`recommended_play` (extraction_play/deprioritize), not a parallel string.

**Wiring (P21):** `build_commodity_report(keyword_profiles, data, config, db_path, run_ts)`
called in `generate_report` right after the D1 block (`generate_insight_report.py:758`);
runs on the real `serp_audit.py:2124` path. Snippet recovery reads `data["organic_results"]`.

**Tests** (`tests/test_commodity_score.py`): identical-snippet SERP scores higher
`answer_similarity` than a diverse one (P7 adversarial); LLM-off renormalization keeps
0–100; reproducible given snapshot+weights_json; `<3` results → low_confidence;
config-driven weights; P21 section-present + persistence (argv + dirty-state idempotent
save, per the D1 learnings).

### AV.2 — Branded vs Non-Branded Demand (GSC) · new `gsc_demand.py`

**Verified reuse:** `run_gsc_analysis.run_analysis` (`:408`) join loop (`:424-432`) is the
per-query row source; `client_name_patterns` at `config.yml:189` (list); reuse the
substring matcher `probe_ai_visibility.py:642-645` (**not** the ≥2-word
`_client_match_patterns`). Bands → new `config.yml gsc_demand` block after `:159` (no
validator change). Renders into `generate_report` (`:282`) + `build_sidecar` (`:369`).

**Data model** (grain per D-D2a): `gsc_demand_run(property, run_ts, query, clicks,
impressions, position, is_branded, source, fetched_at)` + `gsc_demand_score(property,
run_ts, branded_clicks, nonbranded_clicks, branded_impressions, nonbranded_impressions,
branded_click_share, benchmark_band, weights_json)`.

**Wiring (P21):** classification + both saves go **inside `run_analysis` after :432**,
before `generate_report`/`build_sidecar`; thread `db_path` into `run_analysis` (it has
none today — small signature change). New `gsc_demand.py` imported **only** by
`run_gsc_analysis` (the `tests/test_gsc.py:397` isolation guard forbids pipeline imports).
Classification recomputed every run + `INSERT OR REPLACE` (dirty-state; a
`client_name_patterns` edit must reclassify — key any cache by patterns-signature).

**Tests** (extend `tests/test_gsc.py`): branded/non-branded split on a fixture; share =
branded/total from the same pull; band from config not literals; no branded → share 0 /
below_avg / no div-by-zero; pattern edit reclassifies (P8); isolation guard still green.

### AV.3 — Demand-vs-Clicks (snapshot) · read-model in `generate_insight_report`

**Scope per D-D3: snapshot only; `divergence_flag` trend deferred.** Build a "Demand vs
Clicks" section from D1 `aio_coverage_pct` (`aio_exposure.compute_aio_exposure` rollup) +
GSC `gsc_cache` clicks/impressions (via `db_path`), with a normalized visibility line
using **GSC impressions as the volume proxy** (no `search_volume` exists — B1). Join
`keyword_profiles` (raw keys) to `gsc_cache.query` (lowercased) with normalization.
`est_traffic_at_risk` = D1 `est_ctr_loss` × GSC clicks per keyword. New names
`demand_vs_clicks`/`est_traffic_at_risk` (avoid `avg_visibility` — too near `aivi`).

**Deferred (documented, not silently dropped):** the `divergence_flag` trailing-window
slopes — needs D2's per-run demand series + a real `search_volume` source + daily/`run_ts`
history. Logged as a follow-up item, not built.

**Tests:** snapshot renders from D1 rollup + a GSC-cache fixture; `gsc.enabled:false`/empty
cache → honest "GSC not connected" (no fabricated zeros); join normalization; the deferred
trend is explicitly asserted absent (no half-built flag).

---

## 5. Cross-cutting (all four)

Config-driven constants with documented-default fallback+warning (`aivi.resolve_weights`
pattern); `weights_json` persisted for reproducibility; new tables built like
`ai_aio_exposure` with **idempotent same-run_ts save** (the D1 learning-qa fix);
`docs/methodology.md` + `docs/USER_MANUAL.md` + `docs/spec_coverage.md` updated per feature;
`learning-qa` pass before each commit; commits carry `Spec: discover-spec.md#D<n>`.

## 6. Out of scope / deferred (explicit, per no-silent-skipping)

- **True daily GSC grain + provisional-day flagging** (D2) — needs a dated GSC fetch.
- **Full-property demand denominator** (D2) — v1 is tracked-query scope.
- **`search_volume` source** (D3/D4) — no provider field wired today.
- **D3 `divergence_flag` trend** — blocked on the above.
- **D4 `one_paragraph_answerable` LLM term** — config-gated future extension.
- **D5 raw_answer** default OFF (opt-in).
