# SERP Tools Upgrade — CLI Handoff

You are continuing implementation of `serp_tools_upgrade_spec_v2.md`. Phase 1 and most of Phase 2 are landed and pushed to GitHub. Pick up where the previous session left off.

## Quick orientation

- **Repo:** `/Users/davemini2/ProjectsLocal/serp-discover` — Tool 1 (the SERP intent / discover tool). Remote: `https://github.com/dbgnvan2/serp-discover`.
- **Sister repo:** `/Users/davemini2/ProjectsLocal/serp-compete` — Tool 2. Remote: `https://github.com/dbgnvan2/serp-compete`.
- **Spec:** `/Users/davemini2/ProjectsLocal/serp-compete/serp_tools_upgrade_spec_v2.md` (large file — load only when you need details on a specific gap).
- **Plan file:** `/Users/davemini2/.claude/plans/snoopy-soaring-tower.md` (long; revised mid-implementation — treat as reference, not gospel).
- **Project guide:** `serp-discover/CLAUDE.md` documents the new modules, fields, and the "push after each set of work" convention.

## Verify clean baseline

Before adding code:

```bash
cd /Users/davemini2/ProjectsLocal/serp-discover
source venv/bin/activate
python -m pytest test_*.py -q
# Expected: 298 passed, 5 skipped
git status --short    # working tree should be clean of intentional changes
git log --oneline -1  # last commit: "Add SERP intent verdict, title patterns, mixed-intent strategy (spec v2 Phase 1+2)"
```

## What is DONE (do not redo)

### Phase 1 — pre-computed deterministic fields (Gaps 1+2)
- `intent_mapping.yml` — rule table mapping `(content_type, entity_type, local_pack, domain_role)` → SERP intent. Domain judgment lives here. **Do not edit casually.**
- `intent_verdict.py` — loads the YAML, exposes `compute_serp_intent(rows, has_local_pack, client_domain, known_brand_domains, mapping, thresholds)`. 5 intent buckets + `uncategorised` fallback. Confidence = classified_count / total_count.
- `title_patterns.py` — regex shape extraction from top-10 titles. 8 patterns with priority ordering. `dominant_pattern` is set only when ≥4 of 10 match (and is never `"other"`).
- `test_intent_verdict.py` (45 tests), `test_title_patterns.py` (62 tests).

### Phase 2 (most of it)
- `generate_content_brief.py::extract_analysis_data_from_json` populates `serp_intent`, `title_patterns`, and `mixed_intent_strategy` on every keyword profile.
- `_compute_strategic_flags` computes `mixed_intent_strategy` (`compete_on_dominant` / `backdoor` / `avoid` / `null`) from `serp_intent.is_mixed`, the client's existing intent presence, and `client.preferred_intents` from `config.yml`.
- `validate_llm_report` enforces:
  - **HARD-FAIL** on `serp_intent.primary_intent` or `is_mixed` contradictions (issues containing `"but keyword_profiles shows"` are hard-failed by `has_hard_validation_failures`).
  - **SOFT-FAIL** (1 retry) on `title_patterns.dominant_pattern` and `mixed_intent_strategy` contradictions (partitioned to notes by `partition_validation_issues` via the substrings `"contradicts keyword_profiles.title_patterns"` and `"contradicts keyword_profiles.mixed_intent_strategy"`).
- `prompts/main_report/system.md` documents the new fields and adds Rules 12A/12B requiring the LLM to honour them.
- `config.yml` has new optional blocks: `serp_intent.thresholds`, `known_brands`, `client.preferred_intents`. All read with `.get()` defaults so older configs still load.
- 10 new validation tests in `test_generate_content_brief.py` (4 `mixed_intent_strategy` + 6 contradiction tests).

## What is REMAINING (in order)

### Phase 2 finishes (do these first; both unblock Phase 3)

**Gap 3 — Handoff schema & generation**

Create the contract Tool 2 will consume.

1. Create `handoff_schema.json` at `serp-discover/` root. JSON Schema (draft-07). Top-level fields per spec §Gap 3:
   - `schema_version` (string), `source_run_id`, `source_run_timestamp`, `client_domain`, `client_brand_names` (array), `targets` (array), `exclusions` (object).
   - Each `targets[]` item: `url`, `domain`, `rank`, `entity_type`, `content_type`, `title`, `source_keyword`, `primary_keyword_for_url`.
   - Set `additionalProperties: false` at the root and on each object so future drift is visible.

2. Wire generation into `serp_audit.py`. After the audit completes (after `keyword_profiles` are built but before LLM runs), build the handoff dict and write it next to the main JSON output as `competitor_handoff_<topic>_<timestamp>.json`. Validate against `handoff_schema.json` using `jsonschema` before writing — abort on validation failure with a clear log line.

3. New config block in `config.yml`:
   ```yaml
   audit_targets:
     n: 10                  # top N organic URLs across all keywords
     omit_from_audit: []    # domains never sent to Tool 2
   ```
   Read with `.get()` defaults.

4. Tests in a new file `test_handoff_schema.py` (or extend `test_serp_audit.py` if you prefer):
   - Valid handoff dict passes schema validation.
   - Missing required field → schema validation rejects.
   - Client URLs and `omit_from_audit` domains excluded from `targets[]`, counted in `exclusions`.

5. Sync `handoff_schema.json` to `serp-compete/` repo root (manual `cp`). Both copies should be byte-identical until we centralise.

**Gap 5 — Validation consistency check**

Add `test_validation_consistency.py` that scans `prompts/main_report/system.md` and `prompts/main_report/user_template.md` for `keyword_profiles.<field>` references and checks that each has a corresponding rule in `validate_llm_report`. Heuristic — flag fields with no `re.search` mention. Goal: catch the case where someone adds a new field to `keyword_profiles` but forgets the validator. Pass after current state.

### Phase 3 — Tool 2 work (in `/Users/davemini2/ProjectsLocal/serp-compete/`)

Read the spec for full detail. Order:

1. **Gap 1 — Handoff ingestion.** `src/main.py::get_latest_market_data()` (NOT `src/ingestion.py` — that file only has `validate_domain` / `read_key_domains`). Look for `competitor_handoff_*.json` first, validate against the synced `handoff_schema.json`, hard-fail on mismatch. Fall back to `manual_targets.json` (current shape) only if no handoff exists. Manual fallback degrades Section A gracefully — does NOT require schema upgrade. (Confirmed earlier: Option A on the manual_targets question.)

2. **Gap 2 — `ScrapedPage` dataclass + `semantic.py::scrape_content` refactor.** Return structured data instead of a string. **Backward-compat for vocabulary scoring (Option A, confirmed):** preserve the exact "headers + first 500 words" string as the input to scoring. Either store it on `ScrapedPage` as a derived field or reconstruct at the scoring call site. Existing tier counts must not shift on fixture pages.

3. **Gap 3 — `eeat_scorer.py`.** Heuristic E-E-A-T signals from `ScrapedPage`. Score 0–1 per category. Confidence high/medium/low based on how many sub-scores were computable. Caveat string included verbatim in output.

4. **Gap 4 — `cluster_detector.py`.** Build directed graph of internal links across scraped pages of one domain. `insufficient_data` (<3 pages), `isolated`, `linked`, `clustered` (≥1 hub, where hub = in-degree ≥ threshold). Threshold from `shared_config.json::cluster_thresholds`.

5. **Gap 5 — Strategic briefing structure.** Section A = deterministic per-competitor audit (one LLM call per page for one-line commentary). Section B = Bowen reframe blueprints, soft-fail if no specific structural/EEAT signal referenced.

## Conventions

1. **Push after each set of work** (CLAUDE.md rule). After modules + tests pass for one gap, commit with a focused message and push. Stage explicitly — never `git add .` (the repos accumulate untracked drafts/output that should stay local). Run `git status --short` first.

2. **Bypass permissions are configured in the user-level settings** (`~/.claude/settings.json` has `"defaultMode": "bypassPermissions"`). The CLI session should pick it up at start. If you find yourself prompted, run `cat ~/.claude/settings.json` to confirm the setting is intact, then mention to the user that something stripped it.

3. **Test convention:** every new module needs a `test_<module>.py` at repo root. Run `python -m pytest test_*.py -q` after each landing. Baseline is 298 passed / 5 skipped on serp-discover.

4. **Smoke-test integration changes** against a real `output/market_analysis_*.json` before declaring a gap done. Pattern: load the JSON, run the function under test, assert new fields populate without errors.

5. **The intent_mapping.yml encodes domain judgment.** Edit it cautiously and only with the user's explicit approval if the change isn't a pure bug fix. The same is true for `client.preferred_intents` and `known_brands` in `config.yml`.

## First action when you start

```bash
cd /Users/davemini2/ProjectsLocal/serp-discover
source venv/bin/activate
python -m pytest test_*.py -q
```

Confirm 298 passed / 5 skipped, then say so before doing anything else. If the count differs, stop and investigate before adding code.

## Side task on the radar (do not start without ask)

Improve `classifiers.py` rule coverage. Current `Content_Type` and `Entity_Type` classifiers tag many real URLs as `N/A`, which means most keywords land at `confidence: low` in `serp_intent`. This is honest behaviour but limits the LLM signal. A separate session has been spawned for this — don't duplicate.
