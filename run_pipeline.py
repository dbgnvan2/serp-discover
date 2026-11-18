#!/usr/bin/env python3
"""
run_pipeline.py
GUI item 1 (Run Full Pipeline). Orchestrates four sub-steps, logged as
Step 1.1-1.4 so they don't collide with the GUI's own item numbers 1-4:
  1.1 Run Audit (Fetch + Enrich + Store)
  1.2 Validate Output (XLSX vs JSON)
  1.3 Verify DB Enrichment
  1.4 Generate Domain Override Review Candidates
"""
import db_connect
import subprocess
import sys
import os
import yaml

import pipeline_status
import process_config


def run_command(cmd, description, allow_codes=()):
    """Run one step. Returns its exit code; exits the pipeline on a failure.

    ``allow_codes`` are non-zero codes this step may return without ending the
    pipeline — the audit's ``EXIT_PARTIAL``, which means its outputs are on
    disk but cover fewer keywords than were asked for. The code is returned so
    the caller can carry it into the pipeline's own exit code rather than
    printing a clean success (D4.14 / D-C-13).
    """
    print(f"\n--- {description} ---")
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode in allow_codes:
        print(f"⚠️  {description} Completed with warnings. "
              f"(Exit Code: {result.returncode})")
        return result.returncode
    if result.returncode != 0:
        print(f"❌ {description} Failed! (Exit Code: {result.returncode})")
        sys.exit(result.returncode)
    print(f"✅ {description} Completed.")
    return result.returncode


def main():
    # Load Config
    config = {}
    if os.path.exists("config.yml"):
        with open("config.yml", "r") as f:
            config = yaml.safe_load(f) or {}
    # This process now reads one of the policies it sets — the closing
    # summary names the database — so it applies them like every other
    # loader. It was exempt on the grounds that it opens no database and
    # makes no call, which stopped being true when the summary stopped
    # printing a literal (the cold review of chunk Y12).
    process_config.apply(config)
    files_cfg = config.get("files", {})

    # 1. Run SERP Audit
    audit_code = run_command([sys.executable, "serp_audit.py"],
                             "Step 1.1: SERP Audit & Enrichment",
                             allow_codes=(pipeline_status.EXIT_PARTIAL,))

    # Re-read config: serp_audit.py writes the actual output paths on completion.
    if os.path.exists("config.yml"):
        with open("config.yml", "r") as f:
            config = yaml.safe_load(f) or {}
    files_cfg = config.get("files", {})

    # 2. Validate Data Consistency
    xlsx_file = files_cfg.get("output_xlsx", "market_analysis_v2.xlsx")
    json_file = files_cfg.get("output_json", "market_analysis_v2.json")
    diff_file = "diff_report.json"

    # B4: the audit exited 0, so its outputs must exist. Missing files are a
    # failed run, not a step to skip.
    missing = pipeline_status.absent_files([xlsx_file, json_file])
    if missing:
        print(f"❌ Audit output files not found: {', '.join(missing)}")
        sys.exit(pipeline_status.EXIT_FAILED)
    run_command([
        sys.executable, "validate_xlsx_vs_json.py",
        "--xlsx", xlsx_file,
        "--json", json_file,
        "--out", diff_file
    ], "Step 1.2: Data Validation")

    # 3. Verify Database Enrichment
    run_command([sys.executable, "verify_enrichment.py"],
                "Step 1.3: DB Enrichment Verification")

    # 4. Generate Domain Override Review Candidates
    run_command([
        sys.executable, "generate_domain_override_candidates.py",
        "--json", json_file,
        "--overrides", files_cfg.get("domain_overrides", "domain_overrides.yml"),
        "--out", "domain_override_candidates.md",
    ], "Step 1.4: Domain Override Candidate Report")

    # Markdown report shares the JSON stem (same topic + timestamp).
    md_file = json_file[:-5] + ".md" if json_file.endswith(".json") else "market_analysis.md"
    if audit_code == pipeline_status.EXIT_PARTIAL:
        print("\n⚠️  Full Pipeline (item 1) Finished — partial run: one or more "
              "keywords produced no SERP data and are absent from every output.")
    else:
        print("\n🎉 Full Pipeline (item 1) Finished Successfully!")
    print(f"   - Report: {md_file}")
    print(f"   - Excel:  {xlsx_file}")
    print(f"   - JSON:   {json_file}")
    print(f"   - DB:     {db_connect.database_path()}")
    print(f"   - Override Candidates: domain_override_candidates.md")
    return audit_code


if __name__ == "__main__":
    sys.exit(main())
