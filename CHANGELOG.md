# Changelog

All notable changes to the SERP Intelligence Tool (Tool 1, `serp-discover`).

The version is written in `_version.py` and nowhere else. The newest entry
here must name the same version — a test fails the build otherwise, so the
number and the record of what changed in it move together. `serp-compete`
(Tool 2) carries the same version deliberately: the two exchange a
`competitor_handoff_*.json` and a review that changes one side of that
contract changes both.

## [Unreleased]

### Fixed

- A keyword that says where it wants the service was refused its
  neighbourhood pivot. The gate read the SERP's classified intent alone, so
  `family of origin therapist near me` was refused as
  `commercial_investigation` and the report told the owner that proximity
  substitutes for authority "only when the searcher wants a service in a
  place" — about a query that says near me. The keyword text is now checked
  first against the editorial `local_intent.markers` list in
  `serp_vocab.yml`; a marker permits the pivot whatever the SERP classified
  as and never refuses one, and `gate_source` names the marker that decided.
  "near me" also had two homes — `profile_questions` held its own copy while
  the gate knew nothing about it — and `local_intent.near_me_phrase` is now
  the only one.

- The AI-visibility engines could not see keys the machine already had.
  Each of the four read an environment variable while content-brief
  generation read the shared key registry (`~/.config/llm/keys.json`), so on
  a machine whose keys live in the registry the brief was written and all
  four engines skipped with "KEY is not set". The probe now fills any key
  the environment does not carry from the registry, mapped per engine by the
  new editorial `ai_visibility.key_registry_providers`. The environment still
  wins, no key value reaches a log or a record, and an engine with no key
  anywhere is still skipped and reported as not measured rather than zeroed.
  This also covers a run that inherits no shell export — a GUI launched from
  Finder, or a scheduled run.

## [1.5.0] — 2026-11-19

The first numbered release. The minor digit carries the 2026-11-04
correctness review: 87 indexed findings across both tools, closed in chunks
X, D2–D6 and Y1–Y17 plus five follow-up chunks after the first live runs.
Everything below was found by review or by a real run, never by supposition.

### Three findings that invalidated figures in every earlier report

- **Ranks were page-relative.** SerpAPI restarts `position` at 1 on each
  paginated page and the audit stored it verbatim, so a "top 10" was roughly
  the first three or four results of each of three pages. Every figure built
  on rank was affected: the intent verdict, title patterns, entity mix, the
  feasibility mean, `client_rank`, AI-Overview CTR loss, rank-history deltas,
  and the `rank` the handoff passes to Tool 2. One 2026-08-26 brief told the
  owner they ranked #7 for what was a third-page result.
- **"No data" was coerced to zero, then averaged, cached and alerted on.** A
  null Domain Authority became DA 0; a keyword with no scored competitor
  became "Low Feasibility"; a skipped AI engine became AIVI 0 and was ranked
  the top priority; a GSC 503 cached every query as zero clicks for the TTL.
  Absence is now a state of its own everywhere in the data layer, not only in
  the rendering layer.
- **Tool 2 audited a universe the handoff never named.** It grouped the
  handoff's targets by domain and then discarded them, auditing each domain's
  own top-10 instead. Run 11's "traffic magnets" included an airport medical
  clinic in St John's and a Vancouver street address.

### Absence is stated, never implied

- Every "not measured" state now has words of its own in a vocabulary file:
  fetch outcomes, GSC outcomes, the AI-visibility family, feasibility status
  labels and the per-keyword "why there is no verdict" sentences. States that
  had shared a label because the wording was duplicated in Python — an engine
  never asked versus one whose every call failed, a GSC property that
  answered nothing versus a fetch that never ran — are now distinct.
- A retryable failure gets a retryable state. Failing every network attempt
  and never making a request are two outcomes, not one.
- Counts say "N of M" and name what was excluded, rather than reporting the
  remainder as the whole.
- `total_results` is withheld unless it exceeds the results the run asked
  for. Google has largely stopped publishing its index estimate and returns
  the fetched page's own count — 98 to 100 for all ten queries of the
  2026-11-19 run — so the brief had been quoting a page size as each
  keyword's market scale. The run now records `Results_Requested` so the
  check never depends on a config file that may have changed since.
- Report §0 states how many ranked results were classified and what stopped
  the rest, from the keywords' own evidence over the same top-10 window.

### Intent classification

- A known directory, government or publisher host settles the intent when
  the page's own type could not be established. Gated on the page's type,
  not on whether it was fetched: gating on the fetch classified one site two
  ways. A usable content type always beats the host; `counselling` and
  `media` are excluded by design. Host-inferred rows are counted separately
  and never raise the coverage bucket.
- Google serves roughly half of all organic results as encrypted
  `google.com/goto?url=…` links and SerpAPI passes them through verbatim —
  52 of 100 on the verdict window. Host inference is what keeps coverage
  usable despite a ceiling no configuration removes.
- A job board is off topic, not unmeasured. A keyword whose SERP is ten
  employment listings now reports `🚫 Off-topic SERP` rather than
  `❓ Intent unknown`, which had been indistinguishable from a measurement
  failure. The type is given no intent at all: filing an employment SERP
  under `commercial_investigation` would put it beside the therapist
  directories.
- News sites are `publisher`, not `media`, which had grouped them with
  social and retail hosts.

### Editorial content left Python

Trigger words, classification rules, routing tables, report wording and
every "not measured" phrase now live in YAML or JSON. Tool 2 had no
editorial text file at all and gained one. Thresholds that were magic
constants — timeouts, retry policy, the database path and its lock timeout,
intent and demand thresholds, GSC bands — became config keys, and
`config.yml` gained `thresholds_provenance`, one line per threshold family
saying where its numbers came from. A family left blank prints as
"editorial, uncalibrated", because every band in this tool is a judgement
somebody made and a reader could not tell those from measurements.

### Added

- `_version.py`, `CHANGELOG.md`, and the version stamped into the GUI title
  and the market report's header, so a report says which build produced it.
- A glossary rendered from `glossary.yml` covering only the terms a run
  actually used, with a standing guard against unglossed jargon.
- Moz Data API integration beyond Domain Authority: keyword metrics,
  site metrics, and an intent cross-check against this repo's own labels.
- `client_profiles.yml` and persona-segmented AI-visibility questions.
- Per-engine source-bias profiles and platform prioritisation.
- A candidate-review file for brand names the LLM surfaced, so the
  gazetteer never grows silently.

### Known gaps at this release

These are configuration, not defects, and the reports say so rather than
printing a zero:

- Feasibility and demand produce nothing: the Moz row allowance for the
  period is spent and DataForSEO is not configured.
- All four AI-visibility engines skip: none of their API keys is in `.env`.
- GSC analysis is off in `config.yml` and has no credentials path.
