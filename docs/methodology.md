# Tool 1 Methodology

How SERP Intelligence Tool 1 produces its outputs.

---

## Part 1 — SERP data collection and intent classification

**Input:** keyword CSV file.

**Fetch:** `serp_audit.py` calls SerpAPI for each keyword, retrieving organic results, People Also Ask (PAA) questions, and local pack entries.

**Intent verdict:** `intent_verdict.py` applies rules from `intent_mapping.yml` (first-match-wins) to assign a `primary_intent`, `is_mixed` flag, confidence score, and distribution to each keyword.

**PAA classification:** `intent_classifier.py` tags each PAA question as `External Locus` (medical-model framing), `Systemic` (Bowen Family Systems Theory framing), or `General` (neither). Trigger vocabularies live in `intent_classifier_triggers.yml`.

**Title patterns:** `title_patterns.py` extracts the dominant shape pattern (how_to, what_is, listicle_numeric, etc.) from the top-10 organic titles for each keyword.

**Strategic patterns:** `serp_audit.py` loads Bowen pattern definitions from `strategic_patterns.yml` and matches trigger words (word-boundary, case-insensitive) against the SERP ngram corpus. Matched patterns become `strategic_recommendations` in the output JSON.

**Output:** `market_analysis_{topic}_{datetime}.json` — the data contract for Part 2.

### Cross-tool shared config

Both `serp_audit.py` (stop words, client DA/domain/location, omitted-domains path) and `feasibility.py` (gap thresholds, score normaliser) read the optional out-of-repo `shared_config.json` through one module, `shared_config.py`. It owns path resolution (default `../shared_config.json`, overridable via the `SERP_SHARED_CONFIG` env var), malformed-file handling (one warning naming the file, then in-repo defaults), and logs which keys were consumed. Precedence: shared config > `config.yml` > `serp_vocab.yml` / code defaults. Schema in `docs/config_reference.md` ("Shared config"). Tool 2 reads the same file, so its authority must not be removed.

*Spec: seo_geo_deferred_spec_v1.md#C.9. Implemented 2026-07-04.*

---

## Part 2 — Report generation

**Input:** `market_analysis_*.json`.

### Section 4 — Pattern keyword selection

Each Section 4 Bowen pattern block shows a *SERP intent context* line anchoring the pattern to the most relevant keyword in the run. The keyword is selected by `_get_most_relevant_keyword()` in `generate_insight_report.py` using a three-component scoring formula:

```
score(keyword, pattern) =
    (PAA questions for keyword tagged with pattern's Relevant_Intent_Class) × 3
  + (pattern's keyword_hints matching keyword source text) × 2
  + (pattern's trigger words appearing in Title+Snippet of keyword's organic results) × 1
```

**Component weights and rationale:**

| Component | Weight | Signal | Source |
|---|---|---|---|
| PAA intent class match | 3 | What searchers are framing (searcher intent) | `paa_questions[].Intent_Tag` + `strategic_patterns.yml[].Relevant_Intent_Class` |
| Keyword hint match | 2 | Source keyword text alignment | `brief_pattern_routing.yml[].keyword_hints` |
| Trigger text in organic titles | 1 | What page authors wrote (noisier signal) | `organic_results[].Title` + `Snippet` |

PAA evidence (weight 3) is intentionally the strongest signal because it reveals searcher framing, not page-author framing. Trigger words appearing in competitor titles are retained as a tiebreaker but cannot override PAA evidence.

**Relevant_Intent_Class by pattern:**

| Pattern | Relevant_Intent_Class |
|---|---|
| The Medical Model Trap | `External Locus` |
| The Fusion Trap | *(none — PAA component = 0)* |
| The Resource Trap | *(none — PAA component = 0)* |
| The Blame/Reactivity Trap | `External Locus` |

Patterns without a `Relevant_Intent_Class` field in `strategic_patterns.yml` score 0 on the PAA component and select their keyword via keyword_hints + trigger text only.

**Alphabetical tiebreaker:** When multiple keywords score equally, the keyword that sorts first alphabetically is selected (deterministic).

**Null result:** If all keywords score 0 across all three components, `_get_most_relevant_keyword()` returns `None` and the intent context line renders as: *"SERP intent context: no keyword in this run has triggers for this pattern."*

*Spec: serp_tool1_improvements_spec.md#I.3. Implemented 2026-05-01.*

---

## Part 3 — Content brief generation

**Input:** `market_analysis_*.json` + `strategic_recommendations`.

`generate_content_brief.py` selects relevant PAA questions and competitors for each pattern using routing rules from `brief_pattern_routing.yml` (`paa_themes`, `paa_categories`, `keyword_hints`). An LLM (Anthropic API) generates the main report and advisory briefing. Outputs are validated before writing; hard validation failures abort, soft failures retry once.

### FAQ / Answer-Extraction Plan (report Section 5b)

The payload gives the LLM two intent-bucketed PAA lists: `bowen_reframe_faqs` (External Locus questions — the reframe candidates) and `aligned_demand_faqs` (Systemic questions — demand already in the client's vocabulary). For each priority keyword the report recommends up to 3 verbatim PAA questions as literal page headings with answer-first formatting guidance, plus a structured-data line built from `keyword_profiles.schema_signals` (schema.org types and FAQPage presence observed on the enriched top-10 pages). Markup recommendations are restricted to the editorial table in `schema_recommendations.yml`.

*Spec: seo_geo_review_20260704.md T.1 / G.2 / C.2. Implemented 2026-07-04.*

### AI Overview citation surfaces and rank-vs-citation divergence (report Section 4)

Every AI Overview citation domain is entity-classified (same rules as organic results) and aggregated into `aio_citation_surfaces`: the citation mix by entity type, the third-party domains cited, and `outreach_candidates` — placement surfaces (directories, media, associations; the list of qualifying entity types is `config.yml geo.outreach_entity_types`). Per keyword, `keyword_profiles.aio_divergence` compares AIO-cited domains against the organic top-10: domains cited without ranking, rankers the AIO ignores, and the `client_ranks_but_not_cited` alert, which also surfaces as `strategic_flags.geo_alerts`. Discussion/forum threads Google surfaces are captured per-thread (title, link, forum, date) and passed as `forum_threads_by_keyword`.

*Spec: seo_geo_review_20260704.md T.3 / T.4 / T.6. Implemented 2026-07-04.*

### Answer-extractability audit (report Section 5b evidence)

During enrichment, `url_enricher.py` measures how liftable each ranking page's answers are: the number of question-shaped H2/H3 headings (question detection reuses the `title_patterns.py` regexes), the body-text length before the first H2 (a long intro buries the answer), and FAQ presence. `brief_data_extraction._build_extractability` compares those signals on AIO-cited vs uncited pages per keyword (`keyword_profiles.extractability`) and locates the client's own page, so Section 5b formatting advice is grounded in measured differences rather than generic best practice.

*Spec: seo_geo_review_20260704.md T.2. Implemented 2026-07-04.*

### Content freshness / decay tracking (report Section 2 evidence)

During enrichment, `url_enricher.py` extracts a best-effort `published_time` and `modified_time` per page — from `article:published_time` / `article:modified_time` meta tags, then JSON-LD `datePublished` / `dateModified`, then the first `<time datetime=…>` element (published only); no NLP date guessing from body text. `serp_audit.py` copies both onto enriched organic rows (`Published_Time`, `Modified_Time`), and `brief_data_extraction._build_freshness` computes `keyword_profiles.freshness`: per-page `age_days` anchored to the run's `Created_At` (not wall-clock, so re-extracting an old analysis JSON is stable), `median_age_days` over dated pages only, `dated_page_count`, and the client's page when present. Undated pages are reported as undated, never as age 0. Section 2 may state the median age and the client page's age when `data_available` is true.

*Spec: seo_geo_deferred_spec_v1.md#G.6. Implemented 2026-07-04.*

### E-E-A-T author-signal detection (report Sections 5b/7 evidence)

During enrichment, `url_enricher.py` detects author signals on each ranking page: `author_present` (JSON-LD `author`/`Person`, a `rel=author` link, or a class/itemprop byline node), `credential_hits` (distinct professional-designation tokens found in the first `enrichment.eeat_scan_chars` characters of body text or in JSON-LD author fields), and `review_marker_present` ("medically reviewed"-style phrases). The credential and review vocabularies are editorial and live in `serp_vocab.yml` (`eeat_signals` section, loader-required); matching mirrors `intent_classifier.py` — word boundaries for single tokens (so "RP" never fires inside "harp"), substring for multi-word phrases, case-insensitive. `brief_data_extraction._build_eeat_signals` summarises the signals per keyword (`keyword_profiles.eeat_signals`: pages, `credentialed_page_count`, `client_page`) so Sections 5b and 7 can state whether credentialed authorship is table-stakes on that SERP and whether the client's page carries a credentialed byline.

*Spec: seo_geo_deferred_spec_v1.md#G.3. Implemented 2026-07-04.*
