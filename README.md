# serp

## Overview

A Market Intelligence Tool designed to support the "Bridge Strategy" for a non-profit counselling agency. It maps "Problem-Aware" queries to "Solution-Aware" content using SERP data.

## Installation

**Prerequisites:**

- Python 3.8+
- A valid SerpApi Key

1. Create a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set your API Key:
   ```bash
   export SERPAPI_KEY="your_api_key_here"
   ```

## Running the Tool

To execute the full pipeline (Audit -> Validation -> Verification):

```bash
python run_pipeline.py
```

To launch the GUI with the pinned Python 3.12 interpreter:

```bash
./run_serp_launcher.sh
```

In the GUI, keyword input is now file-based:

- select an existing `keywords.csv` or `keywords_*.csv` file from the dropdown, or
- enter `New Keywords (comma separated)` to create a new keyword file, or
- do both to merge new keywords into an existing file

The launcher now:

- auto-creates keyword files named from the first keyword
- updates `config.yml` to point `files.input_csv` at the selected file
- auto-names outputs to match the keyword-file slug
- never overwrites prior outputs; each run gets a timestamp suffix
- keeps SerpApi cache enabled by default (`serpapi.no_cache: false`)
- limits `A.1/A.2` AI-likely query alternatives to high-priority keywords from the latest analysis
- runs related-question AI follow-up only when `Deep Research Mode` is enabled
- exposes three API usage modes in the launcher:
  - `Low API Mode`
  - `Balanced Mode`
  - `Deep Research Mode`

Example:

```bash
keywords_estrangement.csv
market_analysis_estrangement_20260311_1415.xlsx
market_analysis_estrangement_20260311_1415.json
market_analysis_estrangement_20260311_1415.md
content_opportunities_estrangement_20260311_1415.md
advisory_briefing_estrangement_20260311_1415.md
```

## Content Opportunities Report

`List Content Opportunities` now generates a richer report using the
topic-matched JSON from the selected keyword file and writes:

```bash
content_opportunities_<topic>.md
advisory_briefing_<topic>.md
```

It uses the prompt spec in `serp_analysis_prompt_v3.md` with Anthropic and
loads client context from `config.yml` under `analysis_report`.

Required for launcher mode:

- `ANTHROPIC_API_KEY` env var
- `anthropic` Python package

For lower SerpApi usage in routine runs:

### Low API Mode

- cheapest monitoring mode
- 1 Google page
- 1 Maps page
- no A.1 / A.2
- no related-question AI follow-up

### Balanced Mode

- recommended default for real analysis
- 3 Google pages
- 1 Maps page
- keeps main AI Overview collection
- keeps AI fallback without location
- no related-question AI follow-up
- A.1 / A.2 only for `defend` / `strengthen` keywords when enabled

### Deep Research Mode

- highest-cost exploratory mode
- use for monthly or quarterly strategic research
- allows related-question AI exploration

Recommended routine setting:

- `Balanced Mode` on
- `Deep Research Mode` off
- `Low API Mode` off
- `Run 2 AI-likely alternatives` off unless you specifically want A.1 / A.2 on top-priority terms

The audit log now prints a running `SerpApi Call Count` and a final
`Total SerpApi Calls` summary for each run.

If LLM access is unavailable, `List Content Opportunities` fails (no fallback).
If the LLM returns a report that contradicts the pre-verified extraction
facts, the script now fails evidence validation instead of writing the
report. When validation fails after retry, the script writes a companion
artifact next to the intended output, such as:

```bash
content_opportunities_report.validation.md
advisory_briefing.validation.md
```

These files list the rejected claims and include the rejected draft text.
You can bypass first-pass report validation only with:

```bash
python generate_content_brief.py --json market_analysis_v2.json --list --use-llm --allow-unverified-report
```

## Domain Override Review

The full pipeline now also generates:

```bash
domain_override_candidates.md
```

This report lists recurring domains that are not already in
`domain_overrides.yml` and may be worth adding after review. You can
also generate it directly with:

```bash
python generate_domain_override_candidates.py --json market_analysis_v2.json --overrides domain_overrides.yml --out domain_override_candidates.md
```

By default it suppresses low-confidence unclassified domains and focuses
on domains that are more likely to benefit from an override.

In the GUI, `6. Review Domain Override Candidates` now opens an in-app
checklist. High-confidence items are pre-checked, lower-confidence items
are left unchecked, and `Approve Checked` writes only the selected domains
into `domain_overrides.yml`. You can also choose the category for the
selected domain before approval. The current entity categories are:
`counselling`, `legal`, `directory`, `nonprofit`, `government`,
`media`, `professional_association`, and `education`.

When `Run Full Pipeline` finishes successfully in the GUI, the app now
auto-opens this review window if candidates exist. After you approve
checked domains, the app refreshes the current JSON/XLSX analysis files
locally so `List Content Opportunities` uses the updated entity labels
without requiring another SERP fetch.

CLI equivalent:

```bash
python apply_domain_override_candidates.py --json market_analysis_v2.json --overrides domain_overrides.yml
python refresh_analysis_outputs.py --json market_analysis_v2.json --xlsx market_analysis_v2.xlsx --overrides domain_overrides.yml
```

## Utilities

**Visualize Volatility:** Plot rank history for a keyword.

```bash
python visualize_volatility.py --list
python visualize_volatility.py --keyword "Free counselling North Vancouver"
```

**Export History:** Dump SQLite database to CSVs.

```bash
python export_history.py
```

## Testing

To run the regression tests:

```bash
python -m unittest test_enrichment.py
python -m unittest test_serp_audit.py
python -m unittest test_generate_content_brief.py
python -m unittest test_generate_domain_override_candidates.py
python -m unittest test_apply_domain_override_candidates.py
python -m unittest test_refresh_analysis_outputs.py
```
