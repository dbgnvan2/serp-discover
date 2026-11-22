# Feasibility scoring — DA thresholds, providers, and pivot logic

Gap = avg competitor DA − client DA. Thresholds:

| Gap | Status | Meaning |
|-----|--------|---------|
| ≤ 5 | ✅ High Feasibility | Rankable with content alone |
| 6–15 | ⚠️ Moderate Feasibility | Requires local backlink building |
| > 15 | 🔴 Low Feasibility | Dominated by high-authority sites — pivot to neighbourhood variant |
| — | ⚠️ Not measured | Too few ranking domains carried a DA record, or the client's own DA was never measured. No verdict, no pivot. |

**These three bands are editorial, not derived.** ≤ 5 / 6–15 / > 15 and the
0–30 score normaliser are judgements somebody made about what is realistic for
a local nonprofit. No study produced them and nobody has yet checked them
against whether the keywords the tool called High Feasibility were ones the
client went on to rank for. The gap is a measurement; the band is an opinion
about the measurement, and the report says so (review finding D-M-21 — record
a source under `thresholds_provenance.feasibility` in `config.yml` and the
report prints it instead). The calibration that would settle it is available:
compare each keyword's gap against whether the client's rank improved over
successive runs.

**`feasibility_score` is clamped to 0–1.** It is `1 − gap / 30`, and a negative
gap — the client stronger than the mean — used to put it above its own
maximum (1.47 and 1.5 in real runs, D-M-24). The magnitude lives in the gap;
the score is a normalised position inside a stated range, so it stays inside
it.

**The mean is not the whole answer, and the row says what it is missing.**
A mean over a top 10 answers "how strong is this page on average". The
question a DA-35 nonprofit is asking is "does anything my size hold a slot
here", and one directory moves the mean far enough to hide the answer: a SERP
of one DA-92 listing site plus nine DA-18 clinics means 25.4 and reads easy,
while five DA-85 sites plus five DA-12 clinics means 48.5 and reads hard,
although the second page demonstrably has room (D-M-09). Every row therefore
also carries:

| Field | Meaning |
|-------|---------|
| `min_competitor_da` | the weakest Domain Authority holding a top-10 slot |
| `min_non_directory_da` | the weakest that is not a directory, or `None` when no competitor's entity type was resolved |
| `non_directory_count` | measured competitors known not to be directories |
| `entities_known` | measured competitors whose entity type was resolved at all |

`da_count` is the `n` these figures and the mean rest on. Which entity types
count as a directory is editorial and lives in
`config.yml feasibility.directory_entity_types` (default `directory`).
`min_non_directory_da` being `None` means the split was **not measured** — it
never means "no directory ranks here"; `entities_known` is how a reader tells
those apart, and the report prints a different sentence for each.

Partial classification is the normal outcome, not an edge case: a non-enriched
rank is classified domain-only and returns `N/A` for any domain matching no
pattern. So where `entities_known` is between 1 and `da_count`, every figure
resting on the entity types is reported over the competitors whose type was
resolved and the remainder is named — "of the 1 of 10 scored competitors whose
type could be resolved…", and the table cell carries a `?` after the second
figure (`12 (40?)`). Quoting it over the window would assert a classification
nobody made, and with one classified competitor the "weakest non-directory"
figure can be the *strongest* page on the SERP.

All five fields travel with the row through both producers
(`feasibility.MINIMA_FIELDS` names the set once), into the JSON, the workbook
and the `keyword_feasibility` table. Re-listing them at each call site is what
left the coverage fields out of the database in review chunk D2 (finding F9).

**Which DAs the average is taken over.** `feasibility.competitor_da_window`
is the one definition, used by both producers. The window is the first
`TOP_N_FOR_FEASIBILITY` (10) URLs **of the SERP in absolute rank order**, and
the client's own domain is then dropped from that window — so a keyword where
the client ranks 4th is scored against the 9 competitors in its true top 10,
not against 10 competitors drawn from further down the page. A URL with no DA
record is omitted from the average rather than counted as a DA of 0.

**The denominator is published with the mean.** Every feasibility row carries
`da_count` (ranking domains with a DA record) and `da_missing` (those without),
in the JSON, the workbook, both reports and the `keyword_feasibility` table
(alongside `da_provider` and `client_da_source`; rows written before review
chunk D2 hold NULL there, which means "not recorded", never 0 of 0),
and both reports print the pair beside the average as a `DA Coverage` column:
`7/10 (3 unscored)`. A mean of three domains and a mean of ten read identically
otherwise. Below `feasibility.MIN_DA_FOR_VERDICT` measured domains the mean,
gap and score are still reported but the **status is withheld** as "Not
Measured" — four domains out of ten is not a verdict about a SERP. The
minimum is `technical.min_da_for_verdict` in config (default 5), not a
literal. *Findings D-C-03 / D-M-08, review chunk D2.*

What a withheld verdict suppresses downstream, so that no reader is handed a
conclusion the row refuses to draw:

- No geographic pivot and no paid Maps fetch (`generate_hyper_local_pivot`
  returns "Stay the course" with no recommendation either way; it used to
  answer an unmeasured keyword with "Current keyword is feasible"). The
  pipeline's own queue asks for the `Low Feasibility` verdict before it adds a
  pivot fetch job, independently of what the pivot function suggested, because
  the job costs a SerpAPI call (`pivot_pass.decide_pivots`, review chunk Y6).
- No directional Domain Authority sentence in the content plan — §1 states
  the coverage instead of saying which site is stronger.
- No "best opportunity" recommendation: §0 ranks only keywords that have a
  verdict, and says why when none does.
- No play routed from the gap (`play_routing` maps the status to `unknown`).
- A row in §5c and in the brief payload regardless, with its coverage and a
  one-line reason under **Not measured — why**. Surfaced, never dropped.

**A zero is a measurement; an absence is not.** A domain the provider holds no
authority for comes back as `None`, never `0`. Because
`gap = avg_serp_da − client_da`, counting absences as zeros dragged the
competitor mean down, which *shrank* the gap and flipped verdicts toward
feasible: the tool recommended chasing keywords held by DA-90 directories
because the domains nobody scored counted as having no authority. A real `0`
from a provider is still kept. The cache keeps absences too — the row's
presence says the provider was asked, the NULL says there is no figure — but
an absence expires on `moz.negative_cache_ttl_days` (default 7) rather than
the 30-day measurement TTL, because it stops being true as soon as the
provider crawls the domain. *Findings D-C-04 / D-M-02, review chunk D2.*

**The window is sliced before the blanks are dropped.** The window is the top
`TOP_N_FOR_FEASIBILITY` rows *of the SERP*. Dropping unusable rows first slid
ranks 11, 12 … into a set every output calls "the top 10" and threw the real
denominator away, so a 6-of-10 window published "mean of all 6 ranking
domains". `feasibility.url_window` takes the slice, counts the positions it
could not resolve, and hands both to `competitor_da_window`; the client's own
domain is then excluded from that window. `feasibility.usable_url` is the one
definition of a position with no URL (empty or `"N/A"`).

All four passes use it: the primary and the pivot pass in each producer. The
two pivot passes used to average every measured DA, which counted the client
as its own competitor whenever it ranked in the pivot SERP — pulling
`avg_serp_da` toward `client_da` and making the pivot read as more feasible
than it is, in exactly the number that justifies recommending it.

**An empty set is "Not Measured", never "Low Feasibility".** When no
competitor DA could be measured for a keyword, `compute_feasibility` returns
that status with every number `None`. It used to return "Low Feasibility",
which `generate_hyper_local_pivot` then turned into a pivot recommendation and
a paid Maps fetch — a published verdict from zero measurements. The
in-pipeline pass also writes that row rather than skipping the keyword, which
used to drop it out of report section 5b with no record that it was ever
attempted.

Two producers write `keyword_feasibility` from the same SERP — the in-pipeline
pass in `serp_audit.py` and the standalone `run_feasibility.py` — and they used
to build that set differently (page order with the client included, vs rank
order with the client excluded), so `market_analysis_*.md` and
`feasibility_*.md` reported different Avg Comp DA for the same keyword. The
in-pipeline pass now also computes a verdict for the primary query (`A`) only:
an AI-alternative phrasing (`A.1` / `A.2`) is a different SERP, and its row
used to overwrite the real keyword's verdict in report sections 0, 1 and 5c
while the play router kept the `A` row. Every consumer indexes the rows with
`feasibility.index_feasibility_by_keyword` (first-wins, pivot rows excluded).
*Finding D-C-19, review of 2026-11-04.*

**DA providers** (tried in order):
1. **DataForSEO** (`DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`) — `POST /v3/backlinks/bulk_ranks/live`, up to 1000 domains/call, pay-per-use
2. **Moz** (`MOZ_TOKEN`) — Moz Data API `data.site.metrics.fetch.multiple` over
   `https://api.moz.com/jsonrpc`, up to `moz.site_metrics.batch_size` targets/call (default 50).
   The account is the Starter Medium API plan; the monthly row allowance is read at runtime via
   `quota.lookup` and recorded as `moz.rows_per_month` in `config.yml` (3,000 rows/month as of
   2026-08-27, 1 row per target). Alongside DA/PA this returns **Spam Score** and **link counts**
   (`moz.site_metrics.link_count_fields`), stored as additive fields — they do not affect
   `avg_serp_da` scoring. Both DA providers key their results by the caller's input URL

Both cache results in SQLite (`da_cache` and `moz_cache` tables) for 30 days. Re-running within the cache window costs nothing.

**The two providers' numbers are not the same number.** DataForSEO's backlink
`rank` and Moz's `domain_authority` are both 0–100 and are both called "DA" in
this codebase, but they are different vendors' models: the worked example in
`feasibility.compute_feasibility` puts this client at **19** on DataForSEO
against the **35** recorded in `config.yml`. Subtracting one from the other
measured the difference between two vendors, not the client's gap.

So the client's own domain is fetched **in the same batch as the competitors**
(`feasibility.with_client_url`) and resolved from that batch
(`feasibility.resolve_client_da` / `client_da_from_batch`), in this precedence:

1. `--client-da` on the command line — an explicit operator override.
2. The active provider's live figure for the client's domain, which is what
   the gap uses. The run logs the value, the provider and the date.
3. `config.yml → feasibility.client_da`, a fallback that travels with
   `feasibility.client_da_source` — who measured it and when. Rows carry
   `client_da_source: "config fallback (dataforseo 2026-11-21, unverified
   against moz)"` and both reports print the cell as
   `32 (config, not measured by moz)` so the gap is not read as like-for-like.
   Where the fallback was measured by the provider now running, its scale
   holds and only its date is old, and the run says that rather than
   "unverified"; where a provider measures a **different** figure from the one
   named in the provenance, the run reports the fallback as STALE and prints
   the value to set. The fallback was `35` from nobody and no date while
   DataForSEO measured 32 (2026-11-21).

With no provider reachable the client DA is `None` and every keyword reads
"Not measured" — live competitors are never scored against a constant. Every
row also carries `da_provider`, so a trend never mixes two providers' values.
*Finding D-M-05, review chunk D2.*

**Where the words come from.** The status labels, icons, the per-keyword
"why there is no verdict" sentences and the coverage phrases are editorial and
live in `feasibility_messages.yml`, read by `feasibility.load_messages()`. A
missing or malformed file degrades to the bare status string; it never aborts a
report. There is one label per status: the old second label, "No DA Data",
is retired.

**Reading the "Weakest (non-dir)" cell.** `0 · non-dir 61 (7 of 10 typed)` means: the weakest page holding a top-10 slot scores 0, the weakest that is not a directory scores 61, and 7 of the 10 scored competitors had an entity type to judge by — so the non-directory figure stands over those 7, not the window. `0 · all directories` means every scored competitor is one, which is evidence of nothing either way about a site your size. `0 · non-dir not measured` means no page carried a type this run, a different fact again. The words are editorial (`feasibility_messages.yml minima_cell`); the cell used to render `0 (0?)` and say none of this.

**Pivot logic:** Low Feasibility keywords get a neighbourhood variant suggestion (e.g. "Couples Counselling" → "Couples Counselling Lonsdale"). If `feasibility.pivot_serp_fetch: true`, a secondary SerpAPI Maps call checks whether the client appears in the local 3-pack for the pivot keyword.

**Pivots are gated on service intent.** A neighbourhood variant only makes sense for **service-intent** keywords, where physical proximity can substitute for domain authority. Informational keywords (e.g. "how does birth order affect personality") get **no** pivot and **no** neighbourhood variants — nobody searches an informational question with a neighbourhood, and ranking is not the game for them. Service intent is determined by the shared `query_variants.is_service_like` predicate reading the editorial `service_like_tokens` list in `serp_vocab.yml`.

**A keyword that states local intent in its own words always pivots.** The gate checks the keyword text against the editorial `local_intent.markers` list in `serp_vocab.yml` ("near me", "nearby", "in my area"...) BEFORE it reads the measured intent, and a match permits the pivot whatever the SERP classified as. `family of origin therapist near me` was refused a pivot as `commercial_investigation` until 2026-11-21. A marker never refuses a pivot, so keywords carrying none are unaffected.

**The neighbourhood replaces the marker, it does not sit beside it.** The variant is built on `feasibility.pivot_base_keyword`, the keyword with its TRAILING marker removed, so the pivot reads `family of origin therapist West Vancouver` rather than `family of origin therapist near me West Vancouver` — a phrase nobody searches, and one SerpAPI's Maps engine refused. A marker in the middle of a keyword cannot be removed without changing what is left, so it is kept and `stripped_local_marker` is empty. Both are reported on the pivot: `pivot_base_keyword` and `stripped_local_marker`.

**The pivot's local-pack check needs a zoom.** SerpAPI requires `z` (or `m`) on any Maps query that pins its location by NAME and answers `400 Missing \`z\` or \`m\` parameter` without it. The audit passed `z=14`; the standalone feasibility pass passed none, so every pivot local-pack check failed and the pivot row read "local pack not measured (validation fetch failed)". The zoom is now `config.yml serpapi.maps_zoom` (default 14) and both callers read it. It was invisible until the gate fix of 2026-11-21 produced a pivot to check. Informational Low-Feasibility keywords are reported separately; their play is content extractability, not geography.

**Fetch-failure honesty.** The local-pack signal distinguishes three states: *measured — in local pack* (✓), *measured — genuinely absent* (✗), and *could not measure* (the validation SerpAPI fetch failed). A failed fetch is **never** rendered as "✗ not in local pack" — that would present a transient error as a real negative. When the pivot validation SERP fetch fails entirely, the pivot row is marked **Not Measured** rather than a false "Low Feasibility".
