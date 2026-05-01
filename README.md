# SERP Intelligence Tool

Market intelligence for [Living Systems Counselling](https://livingsystems.ca) — a Bowen Family Systems Theory nonprofit in North Vancouver, BC.

The tool scrapes Google search results (SERPs) for a keyword set, enriches and classifies every competitor URL, scores how feasible it is for Living Systems to rank, and uses an Anthropic LLM to write a strategic content brief that maps what people are actually searching for to content Living Systems can realistically create.

---

## What it produces

For each keyword set you run, the tool writes:

| File | What it is |
|------|-----------|
| `output/market_analysis_<topic>_<timestamp>.json` | Full structured data — the source of truth for all downstream steps |
| `output/market_analysis_<topic>_<timestamp>.xlsx` | Same data in Excel, one sheet per data type |
| `output/market_analysis_<topic>_<timestamp>.md` | Markdown summary |
| `output/competitor_handoff_<topic>_<timestamp>.json` | Validated competitor list for Tool 2 (serp-compete) |
| `content_opportunities_<topic>_<timestamp>.md` | LLM content brief — which pages to create and why |
| `advisory_briefing_<topic>_<timestamp>.md` | Executive advisory — strategic framing and priorities |
| `feasibility_<topic>_<timestamp>.md` | Domain Authority gap analysis — how hard each keyword is to rank for |

---

## One-time setup

**Prerequisites:** Python 3.12+, a SerpAPI account, and an Anthropic API account.

```bash
cd /path/to/serp-discover
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file at the repo root:

```
SERPAPI_KEY=your_serpapi_key
ANTHROPIC_API_KEY=your_anthropic_key
DATAFORSEO_LOGIN=your_dataforseo_email
DATAFORSEO_PASSWORD=your_dataforseo_password
```

- **SerpAPI** — required for all SERP fetches
- **Anthropic** — required only for the content brief and advisory steps
- **DataForSEO** — required for Domain Authority feasibility scoring (pay-per-use, ~$0.002/domain, cached 30 days)

---

## Daily workflow — GUI launcher

The GUI is the recommended way to run everything:

```bash
source venv/bin/activate
python3 serp-me.py
```

The launcher walks through each step in order. After a pipeline run it automatically updates `config.yml` so all downstream steps find the right files.

### Steps in order

| Step | What it does |
|------|-------------|
| **1. Run Full Pipeline** | Fetches SERPs, classifies every URL, scores feasibility, writes JSON/XLSX/MD. This is the expensive step (SerpAPI calls). |
| **2. Fetch SERPs Only** | Fetches without running validation — useful for debugging. |
| **3. List Content Opportunities** | Calls Anthropic LLM to generate the content brief and advisory. Reads the JSON from Step 1. |
| **4. Refresh Analysis Outputs** | Re-classifies URLs and rewrites reports without re-fetching SERPs. Use after approving domain overrides. |
| **5. Export History** | Dumps the SQLite rank history to CSV files. |
| **6. Review Domain Overrides** | Opens a checklist of domains whose entity type (counselling, directory, legal, etc.) may need manual correction. Approve to update `domain_overrides.yml`. |
| **7. Feasibility Analysis** | Re-runs Domain Authority gap scoring from the existing JSON. Cached — free to run multiple times. |

### API usage modes

Set in the launcher before running Step 1:

| Mode | Pages fetched | AI follow-up | When to use |
|------|-------------|-------------|-------------|
| **Low API** | 1 Google, 1 Maps | No | Quick monitoring check |
| **Balanced** *(default)* | 3 Google, 1 Maps | Defend/Strengthen only | Regular analysis runs |
| **Deep Research** | Configurable | Yes (up to 5 calls) | Quarterly strategic research |

---

## Command-line equivalents

If you prefer the CLI or are running headlessly:

```bash
source venv/bin/activate

# Full pipeline
python3 run_pipeline.py

# Content brief only (after pipeline has run)
python3 generate_content_brief.py --json output/market_analysis_<topic>_<timestamp>.json --list

# Feasibility analysis only (free re-run — uses DA cache)
python3 run_feasibility.py --json output/market_analysis_<topic>_<timestamp>.json

# Re-classify without re-fetching
python3 refresh_analysis_outputs.py \
  --json output/market_analysis_<topic>_<timestamp>.json \
  --xlsx output/market_analysis_<topic>_<timestamp>.xlsx

# Export SQLite history to CSV
python3 export_history.py

# Plot rank volatility for a keyword
python3 visualize_volatility.py --keyword "couples counselling North Vancouver"
```

---

## Keyword files

Keywords are stored in CSV files, one keyword per row, no header. Name the file to match the topic:

```
keywords_couples_therapy.csv
keywords_estrangement.csv
keywords_Couple_Marriage_RelationshipLocal.csv
```

The output slug is derived from the filename (e.g. `keywords_couples_therapy.csv` → outputs named `market_analysis_couples_therapy_<timestamp>.*`).

---

## Configuration — `config.yml`

Key sections:

```yaml
serpapi:
  location: Vancouver, British Columbia, Canada
  google_max_pages: 3        # pages per keyword (Balanced mode)
  maps_max_pages: 3

files:
  input_csv: keywords_Couple_Marriage_RelationshipLocal.csv   # auto-updated by GUI

enrichment:
  max_urls_per_keyword: 5    # URLs fully fetched and analysed per keyword

feasibility:
  enabled: true
  client_da: 35              # Living Systems domain authority
  pivot_serp_fetch: true     # check local 3-pack for pivot keywords

audit_targets:
  n: 10                      # top-N competitor URLs sent to serp-compete (Tool 2)
  omit_from_audit: []        # domains to exclude from handoff

client:
  preferred_intents:         # intents Living Systems can produce content for
    - informational
    - transactional
    - local

analysis_report:
  client_name: Living Systems Counselling
  client_domain: livingsystems.ca
  location: North Vancouver, BC, Canada
  framework_description: Bowen Family Systems Theory ...
```

**`domain_overrides.yml`** — manual entity type corrections for specific domains (e.g. forcing `psychologytoday.com` to `directory`).

**`intent_mapping.yml`** — rule table mapping `(content_type, entity_type, local_pack, domain_role)` → SERP intent. Edit this to refine intent assignments; domain judgment lives here, not in Python.

---

## Feasibility scoring

Gap = average competitor Domain Authority − Living Systems DA (35).

| Gap | Status | What it means |
|-----|--------|---------------|
| ≤ 5 | ✅ High Feasibility | Rankable with content quality alone |
| 6–15 | ⚠️ Moderate Feasibility | Needs local backlink building |
| > 15 | 🔴 Low Feasibility | High-authority incumbents — pivot to neighbourhood variant |

Low-feasibility keywords get a neighbourhood pivot suggestion (e.g. "Couples Counselling" → "Couples Counselling Lonsdale"). DA results are cached in SQLite for 30 days — re-running feasibility within that window costs nothing.

---

## LLM models

The content brief uses two model calls:

| Pass | Default model | Purpose |
|------|-------------|---------|
| Main report | `claude-opus-4-6` | Full per-keyword analysis and recommendations |
| Advisory briefing | `claude-sonnet-4-20250514` | Executive framing |

You can override both in the GUI launcher or with `--llm-model` / `--advisory-model` CLI flags.

**Approximate LLM cost per run:** $0.08–$0.40 depending on model and keyword count.

---

## What's new in this version (v2)

This version adds deterministic pre-computed fields to every keyword profile, preventing the LLM from guessing at data the tool already knows:

| Field | Example value | Description |
|-------|--------------|-------------|
| `serp_intent.primary_intent` | `"informational"` | Intent verdict for the top-10 organic results. `null` when fewer than 5 URLs could be classified. `"mixed"` when no single intent clears the threshold. |
| `serp_intent.is_mixed` | `false` | `true` when `primary_intent == "mixed"`. |
| `serp_intent.confidence` | `"high"` | `high` (≥8 classified), `medium` (≥5), `low` (<5). Count-based, not ratio-based. |
| `serp_intent.intent_distribution` | `{"informational": 7, "transactional": 1}` | Integer counts per intent bucket among classified organic URLs. |
| `serp_intent.evidence.organic_url_count` | `10` | Top-10 organic URLs processed. |
| `serp_intent.mixed_components` | `["informational", "transactional"]` | Populated only when `is_mixed: true`. |
| `title_patterns.dominant_pattern` | `"how_to"` | Set when one pattern reaches ≥4 of 10 titles. `null` otherwise. Never `"other"`. |
| `mixed_intent_strategy` | `"backdoor"` | When `is_mixed: true`: `compete_on_dominant`, `backdoor`, or `avoid`. `null` otherwise. |

**Validator changes:** contradicting `primary_intent`, `is_mixed`, or `title_patterns.dominant_pattern` is a HARD failure (no retry). Contradicting `mixed_intent_strategy` is a SOFT failure (one retry).

**Rule files:**
- `intent_mapping.yml` — maps `(content_type, entity_type, local_pack, domain_role)` → SERP intent. Edit this file to refine intent assignments without touching Python.
- `url_pattern_rules.yml` — URL-path fallback rules for pages the HTML enricher couldn't classify. Edit to improve classification rates.

See `docs/intent_mapping_rationale.md` for the rationale behind each mapping decision.

---

## What the LLM receives (pre-computed fields)

To keep the LLM honest and reduce hallucination, the tool pre-computes deterministic verdicts before sending anything to the model:

- **`serp_intent`** — primary intent (informational / commercial_investigation / transactional / navigational / local / uncategorised), whether the SERP is mixed-intent, and confidence level. Driven by `intent_mapping.yml`.
- **`title_patterns`** — shape analysis of the top-10 organic titles (how_to, what_is, best_of, etc.). `dominant_pattern` is only set when one shape reaches ≥4 of 10 titles.
- **`mixed_intent_strategy`** — when the SERP is mixed-intent: `compete_on_dominant`, `backdoor`, or `avoid`. Driven by `client.preferred_intents` in `config.yml`.

The validator hard-fails if the LLM report contradicts `serp_intent.primary_intent` or `is_mixed`, and soft-fails (one retry) on `title_patterns.dominant_pattern` or `mixed_intent_strategy` contradictions. If validation fails after retry, a companion `.validation.md` file is written explaining the rejected claims.

---

## Competitor handoff (Tool 1 → Tool 2)

After every pipeline run, the tool writes:

```
output/competitor_handoff_<topic>_<timestamp>.json
```

This is the input file for **serp-compete** (Tool 2), which audits the top competitor pages in depth. The file is validated against `handoff_schema.json` (draft-07) before being written — if validation fails, no file is written and the error is logged. The `audit_targets` block in `config.yml` controls how many URLs are included and which domains to exclude.

See `docs/handoff_contract.md` for the full field-by-field schema contract between Tool 1 and Tool 2.

---

## Backwards compatibility

Runs produced before the v2 upgrade (pre-2026-05-01) do not contain the `serp_intent`, `title_patterns`, or `mixed_intent_strategy` fields. All three fields are nullable on read — the content brief generator skips validation for any keyword profile where they are absent. Re-running `generate_content_brief.py` against a pre-v2 JSON is safe; the new report sections will simply be empty.

---

## Domain override review

After a pipeline run the GUI auto-opens a domain override checklist if candidates exist. You can also run it manually:

```bash
python3 generate_domain_override_candidates.py \
  --json output/market_analysis_<topic>_<timestamp>.json \
  --overrides domain_overrides.yml \
  --out domain_override_candidates.md
```

After approving overrides, refresh the analysis without re-fetching:

```bash
python3 refresh_analysis_outputs.py \
  --json output/market_analysis_<topic>_<timestamp>.json \
  --xlsx output/market_analysis_<topic>_<timestamp>.xlsx
```

---

## Testing

```bash
source venv/bin/activate
python3 -m pytest test_*.py -q
# Expected: 369 passed, 5 skipped (tkinter tests skipped in headless environments)
```

All tests run without API keys — external calls are mocked.

---

## Output file naming

Files follow this convention:

```
market_analysis_<topic>_<YYYYMMDD_HHMM>.json
competitor_handoff_<topic>_<YYYYMMDD_HHMM>.json
content_opportunities_<topic>_<YYYYMMDD_HHMM>.md
advisory_briefing_<topic>_<YYYYMMDD_HHMM>.md
feasibility_<topic>_<YYYYMMDD_HHMM>.md
```

The `<topic>` slug comes from the keyword CSV filename. The GUI updates `config.yml` with the latest paths after each run so all downstream steps automatically find the right files.
