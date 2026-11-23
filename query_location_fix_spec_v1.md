# Query location fix — spec and plan v1

Status: plan, awaiting approval (2026-11-22).

## Problem

`app.force_local_intent: true` makes `serp_audit.fetch_serp_data` send every
keyword that does not already name a place as
`"<keyword> North Vancouver,British Columbia,Canada"`
([serp_audit.py:449](serp_audit.py)). It also sends the location as the
`location` parameter, which is the documented way to geolocate a search.

Evidence:
- All 10 keywords of the 2026-11-19 run went to Google with the location in
  the text (read from each row's `Google_URL`). This includes
  `family of origin therapist near me`, which already asks for local results.
- A paired live check on 2026-11-22 ("golden child syndrome", same `location`,
  `gl`, `hl` and device) shared 1 of 10 top-result sites with the plain query.
  The appended version returned North Shore social-service pages and related
  searches about "Family services North Vancouver". The plain version returned
  topic results and related searches about the condition.
- 15 of 17 related searches in the 2026-11-19 run were about Canada itself.
- Every row records `Executed_Query = keyword`, so the records state that the
  plain keyword was measured (P6).

The same flag also turns on a Google Maps fetch for every keyword
([serp_audit.py:658](serp_audit.py)), and `bing_check.py:108` appends the
location the same way. The GUI help text in `config_manager.py:349` describes
the flag as "Always label local pack results as 'local' intent", which is not
what it does.

## Decision to confirm

The flag does two jobs. The plan splits it into two settings:

| New key | Default | What it does |
|---|---|---|
| `app.append_location_to_query` | `false` | Adds the location to the search text. Off: Google gets the keyword as typed, geolocated by the `location` parameter, which is what a North Vancouver searcher sees. |
| `app.always_fetch_maps` | `true` | Fetches Google Maps for every keyword, not only when a local pack appears. Keeps today's Maps behaviour. |

`app.force_local_intent` is removed. If a config still carries it, the run
logs one warning naming the two new keys and ignores it. It does not guess
which of the two the user meant.

## Acceptance criteria

| ID | Criterion | Test |
|---|---|---|
| QL.1 | With `append_location_to_query: false`, the primary Google request's `q` is the keyword unchanged, and `location` is still sent. | `test_serp_audit.py::TestQueryLocation::test_plain_query_keeps_location_param` |
| QL.2 | With `append_location_to_query: true`, a keyword that names no place gets the location appended; one that names the place (`names_place`) or carries a `local_intent.markers` phrase ("near me") does not. | `…::test_append_skips_place_and_near_me` |
| QL.3 | The Maps fetch runs when a local pack is present or `always_fetch_maps` is true, and is independent of `append_location_to_query`. Maps `q` follows the same rule as QL.1/QL.2. | `…::test_maps_gate_is_its_own_setting` |
| QL.4 | `bing_check.run_bing_checks` uses the same query builder as Google, so the two engines cannot disagree on what was sent. | `tests/test_bing_check.py::test_bing_uses_shared_query_builder` |
| QL.5 | Every row carries `Sent_Query`, the exact `q` sent. `Executed_Query` keeps its current meaning (the logical keyword), because the brief's word counts and the GSC join read it. | `test_serp_audit.py::TestQueryLocation::test_sent_query_recorded`; `validate_xlsx_vs_json.py` passes on a fixture run |
| QL.6 | A config carrying `force_local_intent` logs one warning naming the two new keys and changes no behaviour. | `…::test_old_key_warns_and_is_ignored` |
| QL.7 | `Sent_Query` has a plain-English entry in `glossary.yml columns:`. | existing `TestCD5JargonGuard` / column-glossary test |
| QL.8 | The GUI help text describes both new keys correctly. | `tests/test_config_manager.py` help-text test (new assertion) |

## Implementation order

1. One helper, `query_variants.build_query_term(keyword, location, city, append)`,
   holding the QL.2 rule. Tests for QL.2 first.
2. `serp_audit`: read the two keys, call the helper for Google and Maps, split
   the Maps gate, record `Sent_Query`, warn on the old key (QL.1, QL.3, QL.5, QL.6).
3. `bing_check`: call the same helper (QL.4).
4. `config.yml`, `config_manager.py` help text, `glossary.yml` (QL.7, QL.8).
5. Docs: `docs/config_reference.md` (both keys), `docs/USER_MANUAL.md` (what
   the search text is and why), `docs/methodology.md` if it describes query
   construction. Full suite, cold learning-qa pass (tier: data-path code).

## Data format change

`Sent_Query` is a new column in the market-analysis JSON and xlsx. Nothing is
renamed or removed. serp-compete reads `competitor_handoff_*.json`, which this
change does not touch.

## Risks

- **Runs before and after the fix measure different searches.** Rankings,
  competitors and feasibility from 2026-11-19 and earlier describe the
  location-appended search. Anything that compares runs (rank history in the
  SQLite database, run-over-run deltas) will show a change that is the fix,
  not the market. Build step 2 checks which comparisons key on the query text
  and, where one does, the report says the earlier run used a different query.
- Topic keywords will now show national sites (Cleveland Clinic, Thriveworks)
  as competitors. That is what local searchers see, and it will lower
  feasibility scores for those keywords.

## Adjacent issues found, not fixed

- `bing_check.py:108` tests the city with a bare substring, the fault
  `names_place` was written to fix. QL.4 removes it by sharing the helper.
- The 2026-11-19 run outputs stay as they are; a new run is needed for
  corrected figures (one SerpAPI search per keyword, plus Maps).
