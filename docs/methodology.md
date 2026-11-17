# Tool 1 Methodology

How SERP Intelligence Tool 1 produces its outputs.

---

## Part 1 — SERP data collection and intent classification

**Input:** keyword CSV file, named by the `SERP_INPUT_CSV` environment variable (set by the launcher) or else `files.input_csv` in `config.yml`.

**Fetch:** `serp_audit.py` calls SerpAPI for each keyword, retrieving organic results, People Also Ask (PAA) questions, and local pack entries. A query that returns no usable data is counted, named in the log, and recorded in the output JSON as `fetch_summary` (`planned`, `fetched`, `failed`, plus `pivot_failed` for pivot-keyword fetches); the analysis covers only the fetched queries. A run in which no query returns data, or in which an output file cannot be written, exits non-zero. Each SerpAPI response is saved under `raw/<run_id>/calls/` as it arrives. A run started with `SERP_RESUME_RUN_ID` reuses the stored responses of that earlier run when the request parameters are identical and the response is no older than `serpapi.resume_max_age_hours`; its results therefore mix fetch times, and `fetch_summary` records `resumed_from` and `reused_calls`. Rows built from a reused response carry the time of the resumed run, not the original fetch time. A stored response whose token follow-ups (AI Overview, related questions) were not completed is fetched again rather than reused.

**Rank semantics (pagination).** SerpAPI restarts `position` at 1 on every
paginated page, so page 2 of a three-page fetch reports positions 1..10 for
results that sit at 11..20 on the SERP. `_merge_google_pages` therefore
renumbers `position` to the merged, absolute position as it concatenates the
pages, counting only the rows it keeps after de-duplicating by link. The
merged sequence is a contiguous 1..N and `max(Rank) == len(rows)` for each
keyword. Every row keeps the raw per-page value as `page_position` and the
0-based page it came from as `page_index`. The `Rank` column in the JSON,
the workbook and `serp_results.rank` is this absolute position, so every
"top 10" filter downstream (enrichment, the brief's top-10 domain map and
`serp_intent` denominator, `client_rank`, the feasibility URL set, the
handoff targets, `metrics.py`, `aio_exposure.py`) means the real top 10.
Maps pagination needs no renumbering: the local-pack `Rank` is the index
into the merged `local_results` list, which is already absolute.

Because the merged sequence is contiguous, a row that follows a dropped
duplicate sits one place better than its true SERP position — and overlapping
`start`/`num` windows do return the same URL twice. The merge therefore records
how many rows it dropped as `pagination_duplicates_dropped` and logs it, so a
shifted merge is not indistinguishable from a clean one; `page_index` and
`page_position` keep the un-renumbered position recoverable on every row.

**Link recovery (Google redirect wrappers).** Since late 2026 Google serves
result links as `https://www.google.com/goto?url=CAES…`, where the `url`
parameter is an opaque Google payload rather than the destination; the older
`/url?…` form does the same. SerpAPI passes the wrapper through verbatim, so
every stage that works from a URL would read `www.google.com` as the result's
domain: entity and content classification, Domain Authority lookup,
client-rank detection, handoff targets and AI-Overview citation attribution.
All 81 organic links and all 65 AI-Overview citations of the 2026-11-14 run
were wrappers.

`link_recovery.recover_response` therefore rewrites every wrapped link in a
SerpAPI response, immediately after the response is stored and before any
consumer sees it, on the fresh-fetch and the resume path alike. The response
exactly as SerpAPI sent it survives in the per-call files under
`raw/<run_id>/calls/`, which the checkpoint writes before recovery runs; the
merged `raw/<run_id>/*_response.json` archive is written *after* it, and
carries a `_post_processing` key saying so, because a file named "raw" that
holds processed links would be read as the pipeline's input.
What Google still sends in the clear is the
**host**, not the page: `displayed_link` on an organic result or ad, the `url`
parameter of `source_icon` on an AI-Overview reference, `source` where it is a
hostname, and — for a sitelink, which carries only a title — the host already
recovered for the row it sits inside. A recovered link is therefore the site
root, and every recovered row is marked `link_is_destination_page: false`
(the `Is_Destination_Page` column).

That mark decides which figures a run may publish for the row. Anything
domain-level is still measured: the entity classification and the Domain
Authority that feeds feasibility. Anything page-level is not, and reads
`Not Measured` rather than the front page's value — `Content_Type`,
`Word_Count`, the schema/FAQ/author signals, and `Page_Authority`; the HTML
fetch is skipped rather than pointed at the homepage. A row whose host cannot
be recovered from any field carries no URL at all instead of Google's, and the
count is logged: as an error when it is an organic result, which is a lost
measurement, and as a warning otherwise.

A run written before this change stored the wrappers, and three readers go
back over stored output. `run_feasibility.py` drops such URLs when it reads an
older run's output, rather than scoring Google as the competitor.
`generate_domain_override_candidates.normalize_domain` returns no domain for a
wrapper, so google.com cannot enter the override review queue, and the
candidate pass reports how many rows it had to exclude.
`refresh_analysis_outputs` leaves a row's existing `Entity_Type` in place when
it has no usable domain, rather than overwriting it with `N/A` — which would
turn an unknown into a measured negative. Each of the three reports its count.

A blanked link reaches one more verdict. A situational probe decides
`Client_Cited` by looking for the client's domain among the AI-Overview
citations, and a citation whose host could not be recovered cannot answer the
question either way. Those are counted on the probe row as
`Citations_Unresolved` and carried into the brief data as
`citations_unresolved`, so `Client_Cited: false` beside a non-zero count reads
as "not established" rather than "not cited"; the count is also logged.

One consequence reaches the handoff. Two ranked pages on one site now arrive
as the same site root, so they collapse into a single target for Tool 2, which
will audit that site's front page rather than the page that ranked. The
collapse is counted and logged; the handoff record itself does not yet carry
the distinction, which needs a `schema_version` change agreed with Tool 2.

Three Google pages reach about the top 30, not the top 300: Google serves
roughly 10 organic rows per page regardless of `serpapi.num`, so with
`google_max_pages: 3` the `serpapi.num: 100` and
`serpapi.google_max_results: 300` ceilings are never the binding limit (see
`docs/config_reference.md`). `enrichment.max_urls_per_keyword` now means
what it says — the top N of the real SERP — so a run enriches N pages per
keyword rather than roughly N per page.

*Outputs written before 2026-11-16 carry the old per-page `Rank`: their
`client_rank`, feasibility figures and handoff ranks are wrong and need a
re-run. Finding D-C-01 / D-M-01, review of 2026-11-04.*

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

### Section 1 — Content plan ordering

`generate_insight_report.py` renders **1. What To Write** as one numbered option
per analysed keyword. Order comes from `_content_plan_order()`, which calls the
same `_rank_keywords()` helper the Executive Summary uses and then pins the
Executive Summary's chosen keyword to the front.

The pin is load-bearing, not belt-and-braces. `_get_best_opportunity_keyword()`
ranks only keywords present in the feasibility table; the content plan lists
every keyword in `keyword_profiles`. When every feasibility status scores zero
(all "Not Measured", or some keywords absent from the table entirely) the two
rankings tie on every numeric component and break the tie alphabetically over
*different sets*, so they can select different keywords. Pinning makes the
agreement structural rather than incidental.

Each option's "What the page must do" line renders `recommended_play.strategy_text`
plus, where present, the play's own `note`. When `recommended_play.data_available.feasibility`
is false while Section 5c reports High or Moderate feasibility, the report prints
an explicit disagreement notice: the play was routed without the DA data Section
5c measured, so its ranking claim is unverified.

*Spec: report_content_direction_spec.md#CD.1. Implemented 2026-08-28.*

A play whose `data_available.feasibility` is false renders
`strategy_text_unknown_feasibility` from `play_routing.yml` instead of the
play's normal text. `extraction_play` and `local_pivot_play` are both reachable
on `feasibility: unknown` while their normal text asserts a "high DA gap" — a
direction stated beside a note saying the DA data was never obtained.
`brief_validation.py` HARD-fails a brief that restates the claim in the LLM's
own words, against the editorial `validation.da_gap_claim_phrases` list.

*Spec: review_2026-11-04 D4.2 / D4.3 (D-M-07). Implemented 2026-11-17.*


### Section 1b — SERP feature counts

Features are counted per keyword (`Local Map Pack — 1 of 2 keywords`) rather than
unioned under a "Dominant" label. The union carries no frequency weighting, so it
could not establish dominance at any keyword count. `"Standard Organic"` is
`serp_audit.py`'s fallback string for "none of the seven detected features
present" and is reported as that null result, never listed as a feature.

*Spec: report_content_direction_spec.md#CD.6.1, #CD.6.2. Implemented 2026-08-28.*

### Section 3 — Display phrases

Section 3 shows phrases from `pattern_matching.get_display_phrases()`, which is
**separate from** `get_ngrams()`. `get_ngrams()` deletes stop words before joining
words into n-grams — correct for the Bowen trigger matcher and the word cloud,
which want a dense haystack, but it produces non-phrases for a reader ("family of
origin" → "family origin"; "Family Institute at Greater Vancouver" → "family
greater", which nobody wrote).

`get_display_ngrams()` spans the raw word sequence instead, so every phrase is a
contiguous quote from the source, then drops spans that begin or end on a stop
word — from **`display_stop_words`**, a separate generic-English list, never
`stop_words`. That distinction is load-bearing: `stop_words` is a domain noise
list containing the market's own nouns (`counselling`, `therapy`, `clinic`,
`vancouver`, `bc`) so that `get_ngrams` strips them and Bowen triggers stand out.
Used as a phrase boundary it makes this section unable to emit `family
counselling` or `couples therapy`, the vocabulary it exists to show. Both lists
are validated at load time to contain only strings, because YAML 1.1 parses a
bare `on`/`off`/`yes`/`no` as a boolean and would silently drop that word. `get_display_phrases()` counts those and removes keyword echo — any phrase
that is a contiguous sub-span of an analysed keyword, which is a fact about the
query rather than about competitors.

Both passes read the same text via `pattern_matching.collect_snippet_texts()`,
which `serp_audit.py` and `generate_insight_report.py` share so the producer and
consumer cannot drift on which fields hold competitor text. Snippet sources:
organic/featured/AI-Overview snippets, paid-ad copy, related searches, derived
expansions, autocomplete. `serp_audit.py` writes the result to the
`serp_display_phrases` JSON key; the report recomputes it when reading a JSON
written before that key existed.

Where every repeated phrase was keyword echo, Section 3 states that no distinct
vocabulary was found rather than rendering a padded list. "No competitor text was
captured" and "text was captured but nothing distinct survived" are separate
messages.

*Spec: report_content_direction_spec.md#CD.3, #CD.6.3. Implemented 2026-08-28.*

### Writing directives and glossary

Sections 1b–5e render a "When you write:" directive from
`report_writing_directives.yml`, which also holds the content plan's page-type
labels. The report ends with **A. Glossary**, built from `glossary.yml` and
filtered to the terms the rendered body actually used — matched on whole words so
prose containing the letters does not count as a use.

Both files are editorial content. A missing or malformed file degrades to
rendering without directives or without the glossary; it never aborts the report,
because `serp_audit` wraps the report write in a swallowing try and a raise here
would cost the run its content briefs.

`tests/test_report_content_direction.py::TestCD5JargonGuard` fails the build when
a guarded term appears in the report body with no glossary entry.

The same `glossary.yml` serves two further surfaces (CD.9/CD.10): a **Glossary
sheet** in the `.xlsx`, built from its `columns:` block, and the standalone
`docs/glossary.md`, regenerated with
`python3 generate_insight_report.py --glossary-out docs/glossary.md` and checked
by a test that fails when it goes stale. Workbook headers are deliberately **not**
renamed — the JSON and the workbook share one field vocabulary that
`validate_xlsx_vs_json.py` checks column by column. The workbook's "Help" sheet
text also lives in `glossary.yml`, under `sheet_guidance`.

None of this involves an LLM: the glossary is a dictionary lookup and costs
nothing to render at any surface.

*Spec: report_content_direction_spec.md#CD.2, #CD.4, #CD.5. Implemented 2026-08-28.*

### Worked examples (sections 4 and 5)

Each piece of generic advice is followed by a "**Here's an example:**" line
filling an editorial template with this run's own keyword, People Also Ask
question and competitor vocabulary. Templates: `mixed_intent_strategies` and
`examples` in `report_writing_directives.yml`; `Content_Angle_Example` per
pattern in `strategic_patterns.yml`.

`fill_example()` drops any sentence whose placeholder has no value for the run,
so an example never renders a blank slot or the word "None". A template with an
unknown placeholder loses that sentence and logs a warning rather than raising.

Section 5's examples skip labels listed under `unwritable_content_types` — the
classifier's catch-all buckets. This is load-bearing: in the 2026-08-26 run
`other` is the *largest* content type (51.1%) and `N/A` the second-largest entity
type, so a naive maximum would have told the reader to "write more 'other'".

*Spec: report_content_direction_spec.md#CD.7. Implemented 2026-08-28.*

### The single best opportunity passes both gates

`_get_best_opportunity_keyword` sorted on feasibility and treated intent as a
tie-break, so Section 0 could name the keyword its own action column marked
"⛔ Mismatched intent" two lines below. It now applies both gates
`_get_keyword_action` applies, and when nothing passes it separates "intent
this client does not serve" (widen `client.preferred_intents`) from "no intent
verdict at all" (re-run with more enrichment).

Section 6 renders the keyword sets of a non-comparable volatility run from
`keywords_current` / `keywords_previous`; it printed "unknown" for two keys
`metrics.get_volatility_metrics` never returned.

The Section-4 "Why this pattern fired" block quotes up to three competitor
titles containing a pattern trigger. It read `title` / `domain`; `serp_audit.py`
writes `Title` / `Link` / `Source`, so it never rendered on real data. It is
still omitted when no title matches — a trigger found in a snippet or PAA
question has no title to quote.

*Spec: review_2026-11-04 D4.1 / D4.4 / D4.5 (D-M-06, D-C-14, D-C-18).
Implemented 2026-11-17.*

### Recommended-play ordering (why feasibility must be re-applied)

`recommended_play` depends on Domain Authority, and DA does not always exist when
the play is first computed. `serp_audit.py` builds `keyword_profiles` while
writing the audit JSON; `run_feasibility.py` computes DA in a separate pass
afterwards. Before CD.8 that second pass wrote `keyword_feasibility` back into
the JSON without revisiting the plays, so the file held real DA data alongside
verdicts routed against none — the 2026-08-26 run carried "Ranking is unlikely
(high DA gap)" directly above a measured High Feasibility and a gap of −14.

`brief_data_extraction.attach_recommended_plays()` is the single definition of
routing the plays. Both producers call it, and `run_feasibility.py` logs how many
verdicts changed. **Any new pass that adds or revises `keyword_feasibility` must
call it too**, or the plays it leaves behind will be stale in the same way.

*Spec: report_content_direction_spec.md#CD.8. Implemented 2026-08-28.*

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

### What `entity_distribution` counts

`keyword_profiles[kw].entity_distribution` counts the **label-A** organic rows
for the keyword — the same row set the SERP intent verdict uses. It counted
every query label, so a "top entity-type share" could be computed over the
primary SERP plus its alternative-query and probe rows while the intent verdict
printed beside it came from the label-A top 10: two shares of one SERP that
cannot both be shares of it (D-M-13 / D4.9).

An identical result written twice (same rank, same link) is counted once and
the drop recorded in `entity_distribution_duplicate_rows`. A rank held by two
*different* results is a genuine second fetch; the snapshot carries no field
saying which fetch a row came from, so the rows cannot be split, and
`entity_distribution_single_serp` is set false instead — the share is reported
with its real denominator and is not a top-10 share.

Every share now states its denominator. `entity_distribution_rows` is that
denominator and `entity_distribution_rank_repeats` counts rows whose rank was
already seen — more than one fetch present for the keyword, so the rows are not
one page's worth. A non-zero repeat count is logged at WARNING rather than left
for the reader to infer (P2). The reference-run fixture has 21 label-A rows with
19 repeated ranks for one keyword, which is how this was found.

### Feasibility scoring and hyper-local pivot gating

The intents a pivot applies to are editorial and live in
`config.yml feasibility.pivotable_intents` (default `local`, `transactional`).
A refusal names the intent that decided it: the status read
`"No pivot — informational"` whatever the verdict was, so a SERP measured
`commercial_investigation` or `navigational` was reported as informational.
Consumers test the prefix through `feasibility.is_no_pivot`, never by equality
against one phrasing.

`feasibility.py` scores each keyword by the Domain Authority gap (avg competitor DA − client DA) into High / Moderate / Low Feasibility (thresholds in `docs/feasibility.md`). For **Low Feasibility** keywords `generate_hyper_local_pivot` may suggest a neighbourhood variant — but only when the keyword is **service-intent**. Whether a keyword is service-like is decided by the shared `query_variants.is_service_like` predicate, which matches the editorial `service_like_tokens` list in `serp_vocab.yml` against the de-localised keyword. Informational keywords (e.g. "how does birth order affect personality") get **no** pivot and **no** neighbourhood variants: a geographic variant is meaningless for them, and their play is content extractability, not proximity (the report flags them for the extraction play instead).

D-M-19 / D4.10 changed which signal decides that. `is_service_like` is a token guess from the keyword *string*; by the time the pivot runs the SERP itself has been classified, so `generate_hyper_local_pivot` takes `serp_intent` and gates on the measured verdict (`feasibility.PIVOTABLE_INTENTS` — `local` or `transactional`, or a mixed SERP with one of them among its components). The token guess is the fallback for a keyword with no verdict, and the returned `gate_source` says which basis decided. Both branches of `run_feasibility` use the same gate; the unmeasured branch used to build neighbourhood variants from the guess alone.

The pivot explanation also used to assert that the city-wide market "is currently dominated by high-authority directories" whatever the page held, so ten low-authority clinics with a Low Feasibility verdict were reported as directory-dominated. `_market_composition_clause` now describes the keyword's own `entity_distribution` — naming the leader and its count, saying "led jointly by" for a tie, and making no composition claim at all when there is no distribution to describe.

When `feasibility.pivot_serp_fetch` is on, a secondary SerpAPI Maps/organic fetch validates each pivot. That fetch is treated honestly: a **failed** validation fetch is recorded as *could not measure* (local pack `None`, pivot status **Not Measured**), never as a real "not in local pack" or a false "Low Feasibility". Any request URL written to a log is scrubbed of the SerpAPI key first.

Both producers of `keyword_feasibility` — the in-pipeline pass in
`serp_audit.py` and the standalone `run_feasibility.py` — take the DA average
over the same set: `feasibility.competitor_da_window`, the true top 10 by
absolute rank with the client's own domain dropped. The in-pipeline pass
computes a verdict for the primary query only, and every consumer indexes the
rows with `feasibility.index_feasibility_by_keyword`. See
`docs/feasibility.md`, "Which DAs the average is taken over" (finding D-C-19).

**A value that was never measured is never written down as a zero.** A domain
the DA provider holds no authority for is `None`, not `0`: counting absences
as zeros dragged the competitor mean down, shrank the gap and flipped verdicts
toward feasible. Each row publishes the coverage its mean rests on
(`da_count` / `da_missing`, rendered as a `DA Coverage` column), and fewer than
`feasibility.MIN_DA_FOR_VERDICT` measured domains withholds the status as "Not
measured" rather than scoring four domains out of ten. The client's own DA is
fetched in the same batch as the competitors and tagged with its provenance
(`client_da_source`, `da_provider`), because DataForSEO's backlink rank and
Moz's Domain Authority are both 0–100 and are not the same number. The status
labels and the no-verdict sentences are editorial and live in
`feasibility_messages.yml`; `technical.min_da_for_verdict` sets the minimum.
The window is the top N rows of the SERP, sliced before the unusable ones are
dropped, so a position link recovery could not resolve is a hole in the
coverage rather than a slot backfilled from rank 11
(`feasibility.url_window` / `usable_url`). Absences are cached — the row says
the provider was asked, the NULL says there is no figure — but expire on
`moz.negative_cache_ttl_days` rather than the 30-day measurement TTL, and
both providers log how many of their answered records carry a figure
(`feasibility.batch_coverage`), because the record count is not the
measurement count. The coverage and the provenance are persisted with the row
by `storage.save_feasibility_from_row`, so rank history carries them too. A
withheld verdict suppresses the pivot recommendation, the directional DA
sentence, the best-opportunity pick and the play routing — never the row
itself. See `docs/feasibility.md` (findings D-C-03, D-C-04, D-M-02, D-M-05,
D-M-08; review chunk D2).

**Rank history.** Deltas (`metrics.py`) are measured against the previous run
that wrote all of its outputs, over primary-query rows only; an aborted run
and an AI-alternative query can no longer act as a baseline. See
`docs/database.md`, "Rank history: which rows are comparable" (finding
D-C-22).

*Spec: seo_geo_review_20260704.md (chip B). Implemented 2026-07-04.*

### Recommended Play (feasibility + market-analysis reports)

Each keyword carries a pre-computed `keyword_profiles[kw].recommended_play` verdict —
`{play, label, strategy_text, evidence, data_available, confidence, note}` — computed
by `play_routing.py::compute_recommended_play` (foundation chip A) from the keyword's
feasibility, `serp_intent`, `has_ai_overview`, `aio_divergence`, service-like tokens,
and local-pack signals, using the ordered decision table in `play_routing.yml`
(first-match-wins). It expresses the single strategic move under the **two-score,
rank-vs-citation** model (a keyword's Google rank and its AI-Overview citation are
separate scores; T.4). The play is one of `rank_play` (winnable DA gap → chase the
ranking), `extraction_play` (rank out of reach + AIO present → restructure
answer-first to be cited), `reformat_play` (client already ranks top-10 but is not
AIO-cited → reformat that existing page first; wins over extraction), `local_pivot_play`
(service keyword → hyper-local variant), or `deprioritize`. When a routing input was
missing the verdict carries a `note` and `confidence: low` (honesty, never faked).

Consumers (chip C) render it through the shared `play_rendering.py` helpers, which
read labels + success metrics from chip A's `plays:` map (single source of truth):
`run_feasibility.py` adds a **Recommended Play** column to `feasibility_*.md` (the new
home for non-service guidance, replacing the pivot suggestion those keywords no longer
receive), and `generate_insight_report.py` adds a per-keyword play line to
`market_analysis_*.md` (Sections 5b and 5c). When the verdict carries a `note` the
cell states "inputs missing: …" rather than implying full grounding.

The content-brief prompt documents the field and Section 7 must **state and follow**
each keyword's play, choosing the success metric by play (rank → rank improvement;
extraction/reformat → AIO citation gain). `brief_validation.py::validate_llm_report`
enforces parity: a report that assigns a *different* play than the pre-computed one —
detected by anchoring on the canonical `Recommended play: <label>` statement, so
prose caveats don't false-positive — is a **hard** validation failure (no retry;
written to `*.validation.md`). The `test_validation_consistency.py` canary requires
the field to have a matching rule.

*Spec: seo_geo_review_20260704.md T.4. Implemented 2026-07-04.*

### AI Overview Exposure (Section 5d — D1 / AV.1)

`generate_insight_report.py` renders a **5d. AI Overview Exposure** table
(`aio_exposure.py`) estimating, per keyword, how much organic click-through the
Google AI Overview (AIO) is likely intercepting — the market-side complement to
the GSC sponge effect (`run_gsc_analysis.py`, which is first-party). It is pure
read-side assembly from fields already on `keyword_profiles` (no new SERP fetch,
no LLM call): `has_ai_overview` (AIO present), `client_rank` (organic position,
NULL when unranked), `client_aio_cited` (the AIO cites a client URL — the
registrable-domain match computed upstream via `_is_client_domain`), and
`aio_top_sources` (the cited domains).

`has_ai_overview` means an AI Overview on the **located** SERP — the one this
run asked for. In Balanced mode (`serpapi.ai_fallback_without_location`) a
keyword whose located SERP has no overview is retried without the location; an
overview only that probe returns is recorded as `Has_Unlocated_AI_Overview`
with `AI_Overview_Mode: fallback_without_location` on the overview row, and
reaches the brief payload as `has_ai_overview_unlocated`. It is evidence that
Google has an overview for those words, not that a searcher in this market
sees one, so no CTR loss is charged for it and extraction/reformat plays do
not route on it (review chunk D2c, finding D-C-21). `AI_Overview_Mode` carries
all four cases: `direct_in_main`, `token_followup`,
`fallback_without_location`, `not_present`.

The per-keyword estimate is a **heuristic**, not a measurement:
`est_ctr_loss = ctr_base(position) × aio_ctr_multiplier`, reduced by
`citation_credit` when the client is cited inside the AIO; `0` when there is no
AIO or the client is unranked (no organic CTR to lose). Every constant — the
organic `ctr_curve`, the `aio_ctr_multiplier` (default `0.60`, the industry
"~60% AIO CTR interception" reference), and the `citation_credit` (default `0.5`)
— lives in `config.yml aio_exposure` and is resolved with a documented-default
fallback + warning (mirroring `aivi.weights`). These are **industry reference
points, not measured livingsystems.ca CTR**, and the report labels every value
"estimated". The table defaults to the highest-loss, **not-cited** keywords first
(the priority queue). A run-level rollup (`aio_coverage_pct`, `cited_share`) is
persisted to the `ai_aio_exposure` SQLite table under the run's timestamp and
trended over `aio_exposure.history_runs`; results drift run-to-run, so the report
shows the trend delta, not a single number.

*Spec: discover-spec.md#D1 (AV.1). Implemented 2026-07-24.*

### Query Commodity / AI-Absorption Risk (Section 5e — D4 / AV.4)

`generate_insight_report.py` renders a **5e. Query Commodity / AI-Absorption Risk**
table (`commodity_score.py`) scoring each keyword 0–100 by how easily a single AI
paragraph could replace the whole SERP. It is **deterministic** — no LLM on the report
path, so the score reproduces given the snapshot + `weights_json` — a blend of three
sub-scores: **answer_similarity** (mean pairwise token-set Jaccard over the top-N result
title+snippet texts, read from `data["organic_results"]` grouped by `Root_Keyword`,
degrading to `top5_organic` titles — higher = the results all say the same thing),
**serp_homogeneity** (top entity-type share from `entity_distribution` blended with
title-pattern dominance; D-M-13 / D4.8: the shape term excludes the `other`
catch-all from the dominant-shape candidates while keeping every title in the
denominator — it used to take `max()` over every bucket, so ten titles that
matched *no* shape scored 1.0, "perfectly uniform". When neither signal is
measurable the sub-score is `None`, floored to 0.0 and kept in the denominator
like `answer_similarity`, never renormalised away, and the keyword is flagged
`low_confidence`), and **aio_present** (`has_ai_overview` — an AIO already *is*
the absorption). Weights come from `config.yml commodity.weights` (documented-default
fallback + warning, mirroring `aivi.weights`); the optional `one_paragraph_answerable`
LLM term is **OFF by default** and its weight renormalises out (the `aivi` None-axis
mechanism). Bands low/medium/high; a keyword with < 3 results or < 2 comparable texts is
flagged `low_confidence`, as is one whose homogeneity could not be measured. The recommended action is routed through the existing
`recommended_play` (extraction_play / deprioritize), never a parallel string. Persisted
to `commodity_score` (idempotent per `run_ts`). The score is **indicative**, a heuristic
proxy — labelled as such and paired with the play routing, not treated as a verdict.

*Spec: discover-spec.md#D4 (AV.4). Implemented 2026-07-25.*

### Demand vs Clicks snapshot (Section 5f — D3 / AV.3)

`generate_insight_report.py` renders a **5f. Demand vs Clicks** snapshot
(`demand_dashboard.py`) that operationalizes *clicks ≠ demand*: D1's
`aio_coverage_pct` (how much AI-Overview interception the SERP shows) alongside the
client's own Search Console clicks/impressions, and an **estimated traffic at risk** =
GSC impressions × the modeled AIO CTR interception (`est_ctr_loss`) for AIO keywords
where the client is not cited (indicative). GSC clicks are read read-only from the
`gsc_cache` table (via `db_path`, joined by lower-cased keyword) — never by importing
the standalone `gsc_client`; when the table is absent or GSC is off, the section
degrades to an honest "connect GSC" note. **Scope (decision D-D3):** snapshot only. The
spec's `divergence_flag` (a trailing-window trend of visibility falling while brand
demand holds) is **deferred** — it needs a per-keyword `search_volume` source (none of
the current SERP providers supply one) and a daily GSC series (Search Console returns
per-query totals, no `date` dimension); building it on absent data would be a fabricated
signal. The branded-demand trend that *is* buildable lives in the D2 GSC analysis report.

*Spec: discover-spec.md#D3 (AV.3). Implemented 2026-07-25.*

---

## Part 3 — Content brief generation

**Input:** `market_analysis_*.json` + `strategic_recommendations`.

`generate_content_brief.py` selects relevant PAA questions and competitors for each pattern using routing rules from `brief_pattern_routing.yml` (`paa_themes`, `paa_categories`, `keyword_hints`). An LLM generates the main report and advisory briefing. The provider and both model IDs come from `report_llm` in `config.yml` (any Anthropic or OpenAI-dialect provider in the shared key file, including Google models); each LLM-written file ends with a line naming the model and provider that wrote it. Outputs are validated before writing; hard validation failures abort, soft failures retry once. The validation rules are the same for every model. An empty, refused or token-limit-truncated answer is a failure and nothing is written.

### FAQ / Answer-Extraction Plan (report Section 5b)

The payload gives the LLM two intent-bucketed PAA lists: `bowen_reframe_faqs` (External Locus questions — the reframe candidates) and `aligned_demand_faqs` (Systemic questions — demand already in the client's vocabulary). For each priority keyword the report recommends up to 3 verbatim PAA questions as literal page headings with answer-first formatting guidance, plus a structured-data line built from `keyword_profiles.schema_signals` (schema.org types and FAQPage presence observed on the enriched top-10 pages). Markup recommendations are restricted to the editorial table in `schema_recommendations.yml`.

*Spec: seo_geo_review_20260704.md T.1 / G.2 / C.2. Implemented 2026-07-04.*

### AI Overview citation surfaces and rank-vs-citation divergence (report Section 4)

Every AI Overview citation domain is entity-classified (same rules as organic results) and aggregated into `aio_citation_surfaces`: the citation mix by entity type, the third-party domains cited, and `outreach_candidates` — placement surfaces (directories, media, associations; the list of qualifying entity types is `config.yml geo.outreach_entity_types`). Per keyword, `keyword_profiles.aio_divergence` compares AIO-cited domains against the organic top-10: domains cited without ranking, rankers the AIO ignores, and the `client_ranks_but_not_cited` alert, which also surfaces as `strategic_flags.geo_alerts`. Discussion/forum threads Google surfaces are captured per-thread (title, link, forum, date) and passed as `forum_threads_by_keyword`.

*Spec: seo_geo_review_20260704.md T.3 / T.4 / T.6. Implemented 2026-07-04.*

### Answer-extractability audit (report Section 5b evidence)

**Which pages are read.** `enrichment.enrich_row` decides, per organic row, whether the ranked page was read at all, and records the outcome in `Fetch_Status`: enriched, blocked (with the HTTP status), unreachable (the fetch raised), not fetched (rank beyond `technical.max_urls_to_enrich`), or not the ranked page (a recovered link resolves to the site root). A response at or above 400 is **recorded and not parsed** — a Cloudflare challenge page's six words are not the ranked page's word count, and its missing byline is not the page's missing byline. The status still reaches SQLite via `save_url_features`, so a blocked page is a record rather than a hole, and "N of M pages returned an error status" reaches the Parsing_Warnings sheet. The outcome words are editorial and live in `serp_vocab.yml` (`fetch_status`). Every page-level measurement below is therefore over the pages that were read, and the rest read `Not Measured`, never zero. The machine-readable state is the row's `Fetch_State`; `Fetch_Status` is only its wording, so editing the vocabulary never moves a count. `brief_data_extraction._build_fetch_coverage` carries that per-keyword count into each of the four enriched-page signal blocks (`schema_signals`, `extractability`, `freshness`, `eeat_signals`) as `fetch_coverage`, so the brief reads every one of those figures against the number of pages actually read; when such a block is empty, its `reason` says whether the pages were blocked or the capture never ran.

**Which host is which.** `domain_utils.normalize_domain` is the single definition used by `classifiers.EntityClassifier` (on the override keys at load and on the host before lookup), `refresh_analysis_outputs`, `generate_domain_override_candidates`, `brief_data_extraction` and `handoff_writer` (the client domain, every `omit_from_audit` entry and each target's host): netloc, lower-cased, no port, no leading `www.`. `www.x.ca` and `x.ca` are the same site and get the same entity type, so an override the user approves in Step 6 is applied on the next run whichever spelling Google returns. The competitor handoff's `targets[].domain` carries that canonical form, and the client test there is equality or a dot-suffix match, not a substring one (`notlivingsystems.ca` is a competitor).

During enrichment, `url_enricher.py` measures how liftable each ranking page's answers are: the number of question-shaped H2/H3 headings (question detection reuses the `title_patterns.py` regexes), the body-text length before the first H2 (a long intro buries the answer), and FAQ presence. `brief_data_extraction._build_extractability` compares those signals on AIO-cited vs uncited pages per keyword (`keyword_profiles.extractability`) and locates the client's own page, so Section 5b formatting advice is grounded in measured differences rather than generic best practice.

*Spec: seo_geo_review_20260704.md T.2. Implemented 2026-07-04.*

### Content freshness / decay tracking (report Section 2 evidence)

During enrichment, `url_enricher.py` extracts a best-effort `published_time` and `modified_time` per page — from `article:published_time` / `article:modified_time` meta tags, then JSON-LD `datePublished` / `dateModified`, then the first `<time datetime=…>` element (published only); no NLP date guessing from body text. `serp_audit.py` copies both onto enriched organic rows (`Published_Time`, `Modified_Time`), and `brief_data_extraction._build_freshness` computes `keyword_profiles.freshness`: per-page `age_days` anchored to the run's `Created_At` (not wall-clock, so re-extracting an old analysis JSON is stable), `median_age_days` over dated pages only, `dated_page_count`, and the client's page when present. Undated pages are reported as undated, never as age 0. Section 2 may state the median age and the client page's age when `data_available` is true.

*Spec: seo_geo_deferred_spec_v1.md#G.6. Implemented 2026-07-04.*

### Situational query probes and AIO trigger rate by query length (report Section 4)

When `config.yml situational_probes.enabled` is true (or Deep Research mode is on — Low API mode always disables it), `serp_audit.py` runs a probe pass after the main keyword loop: up to `max_probes_per_run` (default 6, decision gate D-1) extra single-page SerpAPI fetches of **"S"-label** situation-style queries, `probes_per_keyword` (default 2) per root keyword. Keywords are probed in `strategic_flags.content_priorities` order from the most recent analysis JSON (`keywords: priority`; `all` keeps CSV order). Probe queries come from, in priority order: the keyword's own 6+-word PAA questions verbatim (External Locus first — they are already conversational), then the editorial `situational_templates` in `serp_vocab.yml`. As of yoast_geo_upgrade Y.4 that section is a **persona-keyed map** (`{persona_label: [templates...]}`); the SERP audit has no client profile, so `query_variants.flatten_situational_templates` expands **all** persona blocks (a backward-compatible superset of the previous flat list). Placeholders: `{base}`/`{topic}`/`{city}` plus the optional `{service}` (client `service_description`, omitted cleanly when absent). Generation and execution live in `query_variants.py` (which also owns the A.1/A.2 alternative and autocomplete-variant generation, extracted from `serp_audit.py`); the run log prints "Situational probes: N SerpAPI calls (cap M)".

Probe results feed exactly two surfaces: the probe rows land in the analysis JSON's `situational_probes` list, and probe AIO citations join `ai_overview_citations` labeled "S". They never enter organic ranking metrics, `serp_intent` inputs, volatility (no SQLite writes), or the competitor handoff (`handoff_writer.py` filters label "S" defensively). `brief_data_extraction._build_aio_trigger_analysis` then computes the top-level `aio_trigger_analysis` block: the AI Overview trigger rate per query word-count bucket ("1-3", "4-5", "6+") across ALL queries in the run including probes, plus per-probe results (query, word count, has_aio, client_cited). Report Section 4 states the measured rates and any probe where the client was cited — testing the transcript's 23%-vs-77% trigger-rate-by-length claim on the client's own market instead of assuming it.

*Spec: seo_geo_deferred_spec_v1.md#T.5. Implemented 2026-07-04.*

### Bing secondary-index check (report Section 4)

When `config.yml bing_check.enabled` is true (default OFF — decision gate D-4), `serp_audit.py` makes exactly one SerpAPI `engine=bing` call per root keyword after the main loop (`bing_check.run_bing_checks`, bound to the standard `_fetch_serp_api` retry wrapper). The query text mirrors the label-"A" Google query (forced-local suffix included) so ranks are comparable; `bing_check.num` (default 20) sets the result count requested. Raw responses are stored under `raw/{run_id}/bing_{kw}.json` (gitignored); Bing results are not enriched or classified — this is a visibility check, not a second market analysis. The run log states the paid call count.

`bing_check.parse_bing_visibility` reads Bing's `organic_results` (position/link/title — shape pinned by `tests/fixtures/bing_serp_sample.json`) into per-keyword rows (client rank/URL via the same `_domain_from_link`/`_is_client_domain` matching as the Google analysis, plus the top-3 Bing domains), which land in the analysis JSON's `bing_visibility` list. `brief_data_extraction._build_bing_visibility` summarises them into the top-level `bing_visibility` block: `by_keyword` records (`checked`, `client_rank` — null with `checked: true` means measured absence, `client_url`, `top3_domains`) and a run summary (`keywords_checked`, `client_visible_count`). Report Section 4 closes with a Google-vs-Bing client-rank comparison per checked keyword; when nothing was checked the report states the check was disabled — it never guesses Bing standing. Rationale: ChatGPT search grounds substantially on Bing, so a Google-only view can miss an entire AI referral surface.

*Spec: seo_geo_deferred_spec_v1.md#G.5. Implemented 2026-07-04.*

### AI-engine mention probing (standalone `probe_ai_visibility.py`)

`probe_ai_visibility.py` is a standalone script (run_feasibility.py pattern — reads config plus the latest `market_analysis_*.json`, runs any time, never imported by the pipeline) that asks AI assistants realistic therapy-seeker questions and measures whether the client appears. Engines are provider-pluggable behind one protocol (`ask(question) → {answer_text, source_urls, model_id}`): **ClaudeProbe** (Anthropic API with the web search tool enabled; model id from `config.yml ai_visibility.claude_model`), **GeminiProbe** (Gemini REST via `requests` + the shared `http_retry` wrapper with Google Search grounding; model id from `ai_visibility.gemini_model`), **ChatGPTProbe** (OpenAI web-search-enabled Responses API via `requests` + `http_retry`; model id from `ai_visibility.openai_model`, endpoint/tool from `openai_endpoint`/`openai_web_search_tool`; source URLs read from the message's `url_citation` annotations plus the `web_search_call` sources — Y.2) and **PerplexityProbe** (Perplexity Sonar via the OpenAI-compatible `chat/completions` endpoint, `requests` + `http_retry`; model id from `ai_visibility.perplexity_model`, endpoint from `perplexity_endpoint`; citations mapped from the response's `search_results`/`citations` into `source_urls` — Y.3). Each optional engine is key-gated (`GEMINI_API_KEY` / `OPENAI_API_KEY` / `PERPLEXITY_API_KEY`) — a missing key skips that engine with a logged warning, never an abort (decision gate D-2, gates Y-D2/Y-D3/Y-D9). The valid engine set is `claude`, `gemini`, `openai`, `perplexity`; the engine list is `ai_visibility.engines` (default `[gemini, openai, perplexity]` per gate Y-D9 for this Google-organic local nonprofit, Claude available-but-not-default), overridable per run with `--engines`. Detection is unchanged across all four engines and reported strictly per engine, because citation overlap between engines is empirically low — a win on one does not transfer to the others.

Questions come from, in priority order (Y.5 precedence): the client's **profile-seeded persona questions** (`profile_questions.generate` on the `ai_visibility.client_slug` block of `client_profiles.yml`, Y.1), else the run's T.5 `situational_probes` (verbatim), else 6+-word PAA questions, else the editorial `situational_templates` in `serp_vocab.yml` (persona-keyed as of Y.4; with no client profile the probe flattens all persona blocks via `query_variants.flatten_situational_templates`) — capped at `ai_visibility.max_questions` (default 20) **per engine**. Profile questions are *augmentative* (gate Y-D1): when a profile is present its questions lead the chain; when absent the chain collapses to the pre-Y.5 (G.1) order exactly. Every question is prefixed with the geo context (`ai_visibility.geo_context`, default "I'm in North Vancouver, BC."). Detection is engine-agnostic and deterministic and is **unchanged by Y.5**: `mentioned` (any `analysis_report.client_name_patterns` string in the answer text, case-insensitive), `cited` (client domain in any returned source URL), `competitors_cited` (source domains matched against `known_brands` plus the most frequent top-10 organic competitor domains from the analysis JSON). Paid calls are gated: the script prints the planned spend (questions × engines) **and the hard `ai_visibility.max_total_calls` ceiling** (default 60, gate Y-D4); when the plan exceeds the ceiling the question set is truncated so the ceiling is never breached, and nothing is called at all unless `--yes` or `ai_visibility.assume_yes` is set.

Results persist per question in the SQLite table `ai_visibility_probes` (`run_ts` in UTC, `engine`, `model`, `question`, `mentioned`, `cited`, `competitor_domains_json`, `answer_excerpt`, plus `persona` and `source` as of Y.5) so trends are per-engine. The `persona`/`source` columns are added by an idempotent `ALTER TABLE … ADD COLUMN` migration (storage.py convention); a pre-Y.5 database is upgraded once and its old rows read back as `NULL`. The **full** answer text is retained (in a `raw_answer` column added by the same migration) only when `ai_visibility.store_raw_answer` is enabled (D5/AV.5.1 — OFF by default because full answers are unbounded and may carry PII), capped at `ai_visibility.raw_answer_max_chars`; otherwise only the 400-char `answer_excerpt` is kept. The report `ai_visibility_<topic>_<ts>.md` (gitignored) shows this run's mention/citation rate per engine, the per-engine trend over the previous `ai_visibility.history_runs` runs with the model ids used, a **cross-engine share-of-voice** section (per-engine client mention/citation rate alongside the top competitor domains cited, plus a per-persona breakdown of the client mention rate — every value carrying its run count), and a mandatory caveat that single-run values are snapshots — AI answers swing between model versions, which is exactly why the feature stores history instead of reporting a point value.


**What counts as measured (review chunk D3a — findings D-C-05, D-C-11, D-M-03).** A probe call can produce no answer two ways: it raises (network, quota, auth) or it returns HTTP 200 with neither text nor sources (a safety block, a truncated response). Both are recorded as a row with `status = failed` and the reason, carrying **no** mention/cite verdict — `mentioned` and `cited` are NULL, not 0. A raised call used to be dropped, so the question left the denominator; an empty answer used to be stored as `mentioned = False`, a failure filed as a measured absence. Every rate is computed over the answers, and the per-engine table reads "answered N of M (K failed)" so a half-blocked engine cannot read as a fully-measured one. An engine that answered **nothing** was not measured: it gets no `ai_visibility_index` row, no leaderboard or citation row, no place in `all_engine_average` (which states its own n), no place in the cross-engine transfer, and no priority score. It is named instead, with why — "skipped — GEMINI_API_KEY not set", "0 of 20 calls returned an answer". Scoring it 0 ranked the engine the tool could not reach as the client's biggest opportunity. Its AIVI *trend* is still shown, so a gap in history reads as a gap and not as a disappearance. The `status` and `failure_reason` columns arrive by the same idempotent `ALTER TABLE` migration as `persona`/`source`; a pre-D3a row carries no status and reads as answered, which is what it was. The report states the same thing the data does (cold-review F1–F3): the all-engine AIVI mean prints the engines it is over ("over 1 of 4 enabled") with the unmeasured ones named beneath it; an unmeasured engine's leaderboard and citation headings read "not measured — <reason>" rather than falling to "no brands were named" / "no sources were returned", which would be a measured negative about an engine that produced nothing for a brand to be named in; and the transfer section distinguishes **one engine enabled** (a configuration state — enable another) from **one engine measured** (a gap in this run — re-run), since telling the user to enable more engines when three of four were rate-limited is the opposite of the action required. All of this wording lives in `ai_visibility_messages.yml`, not in Python.

**The narrower cases (review chunk D3b — findings D-M-18, D-M-14, D-M-04, D-M-25).** Four more places where something unmeasured arrived as a measured value. (1) `profile_questions.generate` emits every question of persona 1 before persona 2, and both caps — `max_questions` in `build_question_set` and the `max_total_calls` truncation — took a prefix, so a 27-question plan over three personas asked 20 questions that were all the first persona's and the other two personas' rows read as "no data". `profile_questions.interleave_by_persona` round-robins first, so a cap costs every persona a question; the plan line prints "Asking N of M generated questions" and names any persona the cap still left with none. (2) `brand_mentions.build_gazetteer` harvested competitor `Source` labels verbatim, including bare generic words — "Indeed" matched "Indeed, there are many options" and took a leaderboard rank beside a real practice. A harvested name is now kept only when it has two or more tokens, or is a single token matching its own row's domain; `config.yml ai_visibility.generic_source_stoplist` is the editorial override, and `known_brands` is never filtered. (3) `build_leaderboard` ranked by list position, so equal mention counts were separated by the alphabetical sort and a tie read as a loss; it now uses competition ranking (1, 2, 2, 4) and every row carries `tied_with`, with `client_tied_with` beside `client_rank`. `detect_visibility` matches client patterns on a word boundary and takes `config.yml ai_visibility.negative_terms`, so "living systems theory" — the subject this client teaches about — is no longer a mention of the practice (mirroring `gsc_demand.is_branded`, which already did both). (4) `foundational_score.compute_structure` read `schema_signals.schema_type_counts`, an aggregate over the whole enriched top-10, so a client absent from every top-10 scored 66.67 on its COMPETITORS' markup; `_build_schema_signals` now carries the client's own row as `client_page` (as `_build_extractability` already did) and the sub-score reads only that, returning `None` when the client has no enriched page. Every `row_profile` carries its `domain` for that, not only the extractability-enriched ones. (5) `answer_sentiment.classify_answer` returned polarity "neutral" for a raised call, an empty response, a non-JSON response and an unrecognised label, so three rate-limited calls became three measured neutral verdicts and a Sentiment axis of 0.0; a failed classification now carries `polarity: None` with `status: "failed"` and the reason, is excluded from `percent_positive`, the Sentiment axis and the negative-sentiment alert, and the report states "n classified of m attempted". `status`/`failure_reason` reach `answer_sentiment` by the same idempotent `ALTER TABLE` migration; a pre-D3b row carries no status and reads as classified, which is what it was.

**One matcher, one tie-break, one status (review chunk D3b, cold review).** The first pass at the above fixed each defect at one call site and left its siblings carrying it, which moved the error to the axis next door rather than removing it. `brand_match.matches_patterns` is now the only place a brand name is matched against answer text — word boundary plus the editorial `ai_visibility.negative_terms`, vetoed **per match rather than per answer** (an AI answer explains the theory in one paragraph and names the practice in the next, so a whole-answer veto dropped the real mention; `gsc_demand.is_branded` vetoes the whole string because a GSC query is a handful of words, not a document) — and `detect_visibility`, `brand_mentions.gazetteer_pass` and `answer_sentiment.answer_mentions_brand` all call it, so the client's rank, its authority sub-score and which answers buy a paid sentiment call carry the same veto as its `mentioned` flag. The single-token gazetteer rule tests the harvested name against **every label of its row's host** (`ca.indeed.com` → `indeed`), not `host.split(".")[0]`, which discarded one-word brands on any subdomained host and shrank the competitor field in the client's favour; the dropped counts are logged (P2). `client_ranking_axis` takes `client_tied_with` and scores a tie as the mid-point of the places the tied brands occupy, instead of giving a client tied at rank 1 a perfect 100 beside prose reading "not ahead of them"; the top-competitor pick resolves its tie explicitly and the Sentiment section names the tie. An exhausted sentiment budget records each unasked (answer, brand) pair with `status: "skipped_budget"` and no polarity, so the report says the budget ran out rather than that no answer portrayed the brand (P1 — that is a retryable state). `compute_structure` returns a *reason* beside `None`, because "no page in any enriched top-10" and "no schema contexts configured" are two facts that both rendered as a bare `n/a`; the schema recommendations are still reported as gaps when the client is unmeasured, since they are advice rather than a measurement. `foundational_score.DEFINITION_VERSION` is stored per run and the trend suppresses Δ across a definition change, so the sub-score's new meaning is not printed as a readiness gain. `ai_visibility_export._read_answer_sentiment` exports classified rows only: a NULL polarity would reach serp-compete against a schema that requires a string. All new wording lives in `ai_visibility_messages.yml`.
*Spec: seo_geo_deferred_spec_v1.md#G.1 (base); yoast_geo_upgrade_spec_v1.md#Y.5 (profile-first precedence, persona/source columns, cross-engine share of voice, max_total_calls ceiling); #Y.2 (OpenAI/ChatGPT engine) and #Y.3 (Perplexity engine). Implemented 2026-07-04; Y.5 2026-07-06; Y.2/Y.3 2026-07-06.*

### AI-visibility report enrichment: AIVI, leaderboard, citations, sentiment (Phase D, Y.6–Y.9)

These four read-side metrics are computed from the answers the probe already fetched — **no new engine calls** except Y.9's opt-in sentiment classification. They live in dedicated pure modules and are orchestrated by `probe_ai_visibility.run_report_enrichment`, which persists per-engine rows and returns the report sections. The one principled tension (an LLM extraction step, in tension with "deterministic Python computes; the LLM writes") is reconciled per decision gate Y-D7: **the LLM output is treated as a measured input, stored verbatim; Python computes every count, rank, and percentage.** A deterministic gazetteer pass runs first and both LLM steps are OFF by default.

- **Competitor mention leaderboard (`brand_mentions.py`, Y.7).** Yoast's report ranked brands by how often the AI *named* them in answer text — many without any link — which our domain-based `competitors_cited` detection misses entirely. Two passes: a deterministic, case-insensitive, whole-word **gazetteer** match (from `known_brands` + the recurring competitor `Source` labels in the latest `market_analysis_*.json`), then a **gated LLM pass** (`brand_mentions.llm_extraction`, default off) that lists organisation names to fill unknowns. LLM-surfaced brands not already in `known_brands` are written to `brand_mentions_candidates_<topic>_<ts>.md` for manual promotion (same candidate-review pattern as `domain_override_candidates.md` from `generate_domain_override_candidates.py`). Python aggregates a mention-count leaderboard (ties broken alphabetically — deterministic) and computes the client's own rank (or "not mentioned"). Persisted per engine to `brand_mentions`. The client's normalised rank (rank 1 → 100, unranked → 0) is AIVI's Ranking axis.
- **Categorized, brand-attributed citation table (`citation_table.py`, Y.8).** Every source URL is recorded once with a `cite_count` (identical URLs de-duplicated; **tracking params retained verbatim** — `?utm_source=openai` identifies the surfacing engine and must not be stripped), a domain, a **category from the existing content/entity classifier** (`classifiers.EntityClassifier.classify(domain, None)` over `classification_rules.json` + `domain_overrides.yml` — deliberately *not* a parallel category list; the `publisher` entity type + `publisher_domains` list were added to those editorial files, and the classifier's soup-less "not determined" sentinel maps to the Yoast-style `other` bucket), an attributed brand (gazetteer/domain match; `null` when unknown), and an `is_client` flag. Persisted to `ai_citations`. Client-owned citations as a share of the total (cite-count-weighted) are AIVI's Citations axis; a "top cited domains for this topic" shortline doubles as an outreach target list.
- **Per-brand sentiment + aspect keywords (`answer_sentiment.py`, Y.9).** OFF by default (`sentiment.enabled: false`, gate Y-D8): a disabled run makes **zero** sentiment calls, the report states "sentiment not measured", and AIVI excludes the axis (principle 3). When enabled, one LLM classification per answer that mentions the client or top competitor returns a polarity label + verbatim positive/negative aspect phrases (stored as a measured input); **Python computes `% positive`**. Each call counts against `ai_visibility.max_total_calls`. Persisted to `answer_sentiment`. The client's `% positive` is AIVI's Sentiment axis (or `None` → n/a when disabled/unmeasured). When sentiment is enabled, an own-brand **negative-sentiment alert** (D5/AV.5.2) surfaces in the report whenever the client is portrayed negatively in one or more answers this run — reporting the count, the engines, and the recurring verbatim negative aspect phrases — and stays silent (never fabricated) when sentiment is off or no negative client answer was measured.
- **AI Visibility Index (`aivi.py`, Y.6).** A single 0–100 headline per engine (plus an all-engine average), computed by Python from the four normalised axes above using `config.yml aivi.weights` (default equal 25% each, gate Y-D6; malformed/missing weights fall back to equal with a warning — never a hardcoded score). An unmeasured axis is excluded and the remaining weights renormalise, so an absent axis is never counted as 0. Persisted per engine to `ai_visibility_index` (UTC `run_ts`, trendable); the report shows the headline, the four axis values (`n/a` where excluded), the prior-run delta, and the snapshot caveat — a text/4-value radar equivalent, no chart dependency. Because citation overlap between engines is empirically low, AIVI is reported strictly per engine — a high score on one engine is not a high score on all.

*Spec: yoast_geo_upgrade_spec_v1.md#Y.6 / #Y.7 / #Y.8 / #Y.9 (decision gates Y-D6/Y-D7/Y-D8). Read-side enrichment of `probe_ai_visibility.py`; reuses the existing classifier for Y.8 categories. Implemented 2026-07-06.*

### Engine strategy: foundational score, per-engine recommendations, cross-engine transfer (Phase E, Y.10–Y.12)

Phase E answers "which platforms should this client optimise for, and does a win on one carry to the others?" Its design rationale is the cross-engine empirical finding (spec "Empirical basis"): **citation-level visibility mostly does NOT transfer between engines** (reported pairwise domain overlap ~0.18), the engines retrieve from **different backends with different source biases**, and a **foundational layer DOES transfer** and is the highest-ROI work. All three metrics are pure read-side aggregations of signals already collected (no new engine calls), orchestrated in `run_report_enrichment` after the Phase D metrics.

- **Foundational (transferable) GEO readiness (`foundational_score.py`, Y.12).** A single 0–100, **engine-agnostic by construction**, measuring the *inputs* the client controls (a leading indicator that transfers) rather than the per-engine *outcome* AIVI measures (a lagging indicator that does not). Three sub-scores from **existing** data: **accessibility** from `keyword_profiles[*].extractability` (question-shaped headings, answer-at-top intro length, FAQ block on the client's own ranking pages), **structure** from `keyword_profiles[*].schema_signals` coverage vs the `schema_recommendations.yml` contexts the client could mark up, and **authority** from the Y.7 leaderboard (the client's off-site mention frequency vs the leader — the "brand mentions across third-party sources" signal reported ~3× more predictive of citation than backlinks). Weights from `config.yml foundational.weights` (default equal thirds; malformed → equal + warning). A sub-score with no captured inputs is `n/a` and **excluded** from the weighted mean (renormalised), never 0. Each sub-score lists its top 2–3 concrete gaps pulled **from existing sources** — `strategic_flags.geo_alerts` details, `schema_recommendations.yml` labels for missing types, and rival brand names from the leaderboard — so the number is actionable and no new gap strings are invented. Persisted to `foundational_score`; reported **first**, ahead of per-engine AIVI, as the cross-platform priority.
- **Engine source-bias profiles + per-engine recommendations (`engine_recommendations.py` + `engine_profiles.yml`, Y.10).** Because optimisation does not transfer, one set of recommendations is wrong for a multi-engine world. The editorial `engine_profiles.yml` holds one block per engine (chatgpt/`openai`, perplexity, gemini, claude) — `retrieval_backend`, `source_bias`, indicative+dated `avg_citations`, `reach_tier`/`referral_click_tier`, and the `recommended_content_moves` list. `engine_recommendations.py` (pure, no LLM) joins the client's per-engine results (AIVI, leaderboard rank, citation categories) to that file to emit per-engine "what to change here" — **nothing is hardcoded in Python**; editing a profile changes the output. It also emits a **platform-prioritisation** ranking of the enabled engines by a documented, config-weighted blend of opportunity (low AIVI), reach tier, and referral-click tier (`engine_prioritization.weights`), with the audience-source caveat in prose and the whole ranking labelled **indicative**. Only enabled engines with a profile **and an AIVI** appear: an engine with no measurement used to be scored maximum opportunity and so came out top of the ranking (D-C-05 / D-M-03). Those are listed separately as "not ranked — not measured", with why. **Vendor/temporal confidence caveat (binding):** directional findings are high confidence, the figures are indicative and shift over time — re-measure.
- **Cross-engine transfer / overlap (`engine_transfer.py`, Y.11).** Answers the user's core question — "if I'm good on one AI, am I good across all?" — **for this specific client** from its own data, not industry averages. From ≥2 enabled engines of one run: (a) client visibility transfer ("mentioned on N of M engines"), (b) citation-source overlap = pairwise **Jaccard** of the cited-domain sets per engine (from Y.8; identical→1.0, disjoint→0.0, and **None — not comparable** when neither engine cited anything, since the old 1.0 convention rendered two silent engines as perfect agreement: review chunk D3a / D-M-03) plus counts of domains cited by all vs exactly one engine, and (c) leaderboard-rank divergence (the client's Y.7 rank per engine + spread). The average is over the comparable pairs only and states how many those were; with no comparable pair it reads "not measurable", which is not a finding of low overlap. The interpretation is explicit: high overlap ⇒ foundational work suffices; low overlap ⇒ per-engine targeting needed. Persisted to `engine_transfer`. A **single-engine run** — or a run where only one engine was measured (D3a) — degrades to "transfer not measurable (single engine)" without crashing.

*Spec: yoast_geo_upgrade_spec_v1.md#Y.12 / #Y.10 / #Y.11 (decision gate Y-D9). Pure read-side aggregation in `probe_ai_visibility.run_report_enrichment`; `engine_profiles.yml` is a new editorial surface. Implemented 2026-07-06.*

### AI-visibility export for serp-compete (AV-EXPORT)

serp-compete's Competitive AI Share-of-Voice feature (Tool 2, `compete-spec.md#C1`) is **comparative**: it needs this repo's already-computed `brand_mentions` and `ai_citations` rows but must not fork the probe runner (the "apps stay independent" decision). `ai_visibility_export.py` serializes the latest run's `brand_mentions` (`brand, mention_count, questions_total, is_client, source`), `ai_citations` (`url, domain, category, brand, is_client, cite_count`), and `answer_sentiment` (`engine, brand, polarity` — so Compete can compute per-competitor sentiment from that competitor's own rows only, its SC-3.4) — grouped by engine — into one schema-validated JSON (`ai_visibility_export_schema.json`), mirroring the `handoff_writer.build_competitor_handoff` → `output/*.json` contract. It is a **pure reader**: it reuses the stored detector output verbatim (no re-probe, no re-detection, no table creation), and when the AI-visibility tables are absent or empty it writes `data_available: false` (no crash, no fabricated rows — principle 3). A live `probe_ai_visibility.py --yes` run refreshes the export automatically (a guarded post-run hook that can never abort the paid run); `export_ai_visibility.py --db serp_data.db --out output` regenerates it on demand from stored rows.

*Spec: discover AV-EXPORT (serp-compete C1 dependency). Pure read-side export of the Y.7/Y.8 tables; no new engine calls. Tests: `tests/test_ai_visibility_export.py` (AV-EXPORT.1–4).*

### Google Search Console sponge-effect analysis (standalone `run_gsc_analysis.py`)

`run_gsc_analysis.py` is a standalone script (run_feasibility.py pattern; the main pipeline never imports it or `gsc_client.py` — G.4.4) that joins the client's first-party Search Console data onto the run's queries. `gsc_client.GscClient` authenticates headlessly with a service account (gate D-3: JSON key path from the optional `GSC_CREDENTIALS_PATH` env var; the service-account email must be granted on the Search Console property), pulls query-dimension Search Analytics rows through the shared `http_retry` wrapper (paginated 25 000-row pulls), and caches results for `gsc.cache_ttl_days` (default 7) in the SQLite `gsc_cache` table — DA-client cache pattern including batched IN(...) lookups (500 bound variables per chunk, C.7). Queries GSC has no row for are cached as measured absence (`found = 0`) and omitted from results — never reported as fabricated zeros. A fetch that did **not** complete (network failure, non-OK status, non-JSON body, or a failure part-way through pagination) caches nothing for the queries it could not resolve, so the next run asks again: `get_query_stats` returns a `GscStats` carrying `complete`, `measured_absent` and `not_reached`, every report row carries a `gsc_status` of `measured` / `measured_absent` / `not_reached` (words in `gsc_messages.yml`), and the report, the sidecar (`fetch_complete`, `queries_not_reached`), the brief payload and the branded-demand trend all distinguish "GSC answered nothing" from "the fetch failed". A partial fetch writes no branded-share trend point, because the share would be computed over a truncated denominator (review chunk D2b, finding D-C-02).

The query set is the run's root keywords plus their A.1/A.2 informational variants, the "S"-label situational probes, and the top PAA phrasings, each carrying `has_ai_overview` joined from the analysis JSON (PAA phrasings: unknown, never guessed). Two deterministic computations follow: the **sponge comparison** — median CTR at comparable position (bands 1–3 / 4–10 / 11–20) for AIO-present vs AIO-absent queries, reported per band only when both buckets hold ≥3 queries, otherwise stated as insufficient data — and **reformat_candidates** — queries ranking in the top 10 whose CTR sits below the no-AIO median for their band, cross-referenced against `strategic_flags.geo_alerts` so pages the AI Overview already ignores (T.4) sort first. Outputs: `gsc_analysis_<topic>_<ts>.md` plus a JSON sidecar (both gitignored). When `config.yml gsc.feed_strategic_flags` is true, `brief_data_extraction._build_gsc_summary` attaches the latest sidecar to the LLM payload as `gsc_summary` — with the HARD prompt rule that GSC numbers are the client's private data, quotable only in client-position contexts, never as market-level claims.

*Spec: seo_geo_deferred_spec_v1.md#G.4. Implemented 2026-07-04.*

### Branded vs Non-Branded Demand (D2 / AV.2)

`run_gsc_analysis.py` also classifies the run's GSC queries as **branded**
(name-seeking) vs **non-branded** and trends the branded click share
(`gsc_demand.py`) — the demand signal that predicts survival when generic clicks
fall to AI answers. Classification reuses `analysis_report.client_name_patterns`
(the `detect_visibility` substring form — single-word brands included — plus an
optional `gsc_demand.negative_terms` override), recomputed every run so a pattern
edit reclassifies (never gated by the 7-day GSC cache). `branded_click_share =
branded_clicks / total_clicks` over the run's **tracked** queries (labelled as
such, not the full property), banded against `config.yml gsc_demand.bands`
(industry reference points below-avg < 2.4% / top ≥ 10%, labelled reference, not a
target). Because the current GSC client fetches per-query only (no `date`
dimension), the series is keyed by **run** (`run_ts`, parsed from the source
filename) and trends across successive runs (decision D-D2a; true per-day grain +
provisional-day flagging are deferred to a future dated fetch). Persisted to
`gsc_demand_run` + `gsc_demand_score` (idempotent per `property`+`run_ts`), a new
"Branded vs Non-Branded Demand" section in `gsc_analysis_<topic>_<ts>.md`, and a
`demand` block in the sidecar. GSC's 2–3 day lag makes the latest run provisional.

*Spec: discover-spec.md#D2 (AV.2). Implemented 2026-07-25.*

### E-E-A-T author-signal detection (report Sections 5b/7 evidence)

During enrichment, `url_enricher.py` detects author signals on each ranking page: `author_present` (JSON-LD `author`/`Person`, a `rel=author` link, or a class/itemprop byline node), `credential_hits` (distinct professional-designation tokens found in the first `enrichment.eeat_scan_chars` characters of body text or in JSON-LD author fields), and `review_marker_present` ("medically reviewed"-style phrases). The credential and review vocabularies are editorial and live in `serp_vocab.yml` (`eeat_signals` section, loader-required); matching mirrors `intent_classifier.py` — word boundaries for single tokens (so "RP" never fires inside "harp"), substring for multi-word phrases, case-insensitive. `brief_data_extraction._build_eeat_signals` summarises the signals per keyword (`keyword_profiles.eeat_signals`: pages, `credentialed_page_count`, `client_page`) so Sections 5b and 7 can state whether credentialed authorship is table-stakes on that SERP and whether the client's page carries a credentialed byline.

*Spec: seo_geo_deferred_spec_v1.md#G.3. Implemented 2026-07-04.*

---

## Out of scope

**Backlink / off-site authority analysis.** Tool 1 uses the **Domain Authority gap** between the client and the ranking competitors as its authority signal for keyword feasibility (`feasibility.py`, with DA/PA sourced per domain from DataForSEO and Moz as fallback); it does **not** analyse backlink profiles. The Moz path additionally records **Spam Score** and a configurable set of aggregate **link counts** (`moz.site_metrics.link_count_fields`) per URL — these are stored as additive context and are *not* inputs to feasibility scoring; they are counts from Moz's index, not a backlink graph, and do not change the boundary stated here. Separately, per-keyword Moz metrics (volume, difficulty, organic CTR, priority) are fetched via `moz_keywords.py` and passed to the brief as `keyword_profiles.moz`. Keywords Moz holds no record for are marked `data_available: false` and carry no metric fields at all, so an absent figure can never be read as a zero; the prompt instructs the model to make no demand claim for those keywords. Moz search-intent scores are available as an optional cross-check on the `intent_mapping.yml` classifier (`moz.search_intent`, off by default): the repo's rule-based verdict remains authoritative and Moz's reading is reported alongside it, with disagreement surfaced as an open question and never auto-resolved. Per-competitor Moz signals (ranking keywords, anchor-text distribution, and optionally brand authority and lost-vs-live linking domains) are attached to the Tool 2 handoff as an optional top-level `moz` block (`moz.competitor`); they are handoff payload only and are not inputs to any score computed here. Each of the four signals is fetched, cached and expired **independently** (`moz_competitor_cache`, per-signal `<signal>_at` timestamps): a sub-call that failed is not cached, so the next run asks for that signal alone rather than serving its empty `items: []` as a fact about the competitor for the 30-day TTL, and every sub-block carries its own `fetched_at` plus an explicit `data_available` and `reason` so a consumer can tell "Moz holds none" from "the call failed" (review chunk D2b, finding D-C-10). This narrows the "no backlink analysis" boundary stated above only in the sense that anchor-text *aggregates* are now passed through — no backlink graph is built, traversed, or scored. Backlink discovery, toxic-link identification, and referring-domain diversity are deliberately out of scope. Across the tool suite, Domain Authority (and Moz Page Authority) serve as the single authority proxy; a full backlink graph requires a paid third-party link-index provider (Ahrefs, Majestic, or DataForSEO backlinks) and is judged low-ROI for a single nonprofit. This is a deliberate boundary, not an omission — revisit only if scale or budget changes.

*Spec: suite_enhancement_spec_v1.md#X-4.*
