#!/usr/bin/env python3
"""
Refresh local analysis outputs after domain overrides change, without
refetching SERP data.
"""
import argparse
import json
import os

import openpyxl
import yaml

import brief_data_extraction
from classifiers import EntityClassifier
from generate_domain_override_candidates import (
    collect_candidates,
    load_overrides,
    normalize_domain,
    render_markdown,
)


def load_config(config_path="config.yml"):
    """config.yml as a dict, or {} when it is absent."""
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config_paths(config_path="config.yml"):
    config = load_config(config_path)
    files_cfg = config.get("files", {})
    return {
        "json": files_cfg.get("output_json", "market_analysis_v2.json"),
        "xlsx": files_cfg.get("output_xlsx", "market_analysis_v2.xlsx"),
        "overrides": files_cfg.get("domain_overrides", "domain_overrides.yml"),
        "candidates_report": "domain_override_candidates.md",
    }


def classify_domain_for_row(classifier, row):
    """The entity type for one row, or its existing one when it has no domain.

    ``normalize_domain`` returns "" for a Google redirect wrapper, which is
    what runs written before link recovery stored in ``Link``. Keeping the
    row's existing type is honest; classifying the wrapper would file it as
    google.com.
    """
    domain = normalize_domain(row.get("Link") or row.get("Source"))
    if not domain:
        return row.get("Entity_Type", "N/A")
    entity_type, _confidence, _evidence = classifier.classify(domain, None)
    return entity_type or "N/A"


def refresh_json(json_path, classifier):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    changed = 0
    unclassifiable = 0
    rows = data.get("organic_results", [])
    for row in rows:
        if not normalize_domain(row.get("Link") or row.get("Source")):
            # Not counted as updated: the row keeps the type it had, and
            # calling it updated made the JSON figure mean something different
            # from the workbook figure over the same data (P5/P6, cold review
            # of chunk Y3).
            unclassifiable += 1
            continue
        new_type = classify_domain_for_row(classifier, row)
        old_type = row.get("Entity_Type", "N/A")
        row["Entity_Type"] = new_type
        updated += 1
        if old_type != new_type:
            changed += 1

    if unclassifiable:
        # P2 — a reclassification that silently skipped rows would look clean.
        print(f"  {unclassifiable} of {len(rows)} organic row(s) carry no "
              f"usable domain (a Google redirect wrapper or a blank link) and "
              f"keep their existing Entity_Type.")

    # No write here. This pass classifies; `refresh_analysis_outputs` writes
    # once, through `_write_json_atomically`. The direct `json.dump` that used
    # to be here truncated the live file first — the exact window that helper
    # exists to close — and the caller then wrote the same data again
    # (review chunk Y3).
    return data, updated, changed


def refresh_xlsx(xlsx_path, classifier):
    if not os.path.exists(xlsx_path):
        print(f"  no workbook at {xlsx_path}, so no workbook row was "
              f"re-classified.")
        return 0, 0

    wb = openpyxl.load_workbook(xlsx_path)
    if "Organic_Results" not in wb.sheetnames:
        print(f"  {xlsx_path} has no Organic_Results sheet, so no workbook "
              f"row was re-classified.")
        return 0, 0

    ws = wb["Organic_Results"]
    headers = {cell.value: idx + 1 for idx, cell in enumerate(ws[1])}
    link_col = headers.get("Link")
    source_col = headers.get("Source")
    entity_col = headers.get("Entity_Type")
    if not link_col or not source_col or not entity_col:
        # "0 rows updated" reads as "nothing needed changing"; the workbook
        # was never read (P2, cold review of chunk Y3).
        print(f"  {xlsx_path} Organic_Results is missing one of the Link / "
              f"Source / Entity_Type columns, so no workbook row was "
              f"re-classified.")
        return 0, 0

    updated = 0
    changed = 0
    skipped = 0
    for row_idx in range(2, ws.max_row + 1):
        link = ws.cell(row=row_idx, column=link_col).value
        source = ws.cell(row=row_idx, column=source_col).value
        old_type = ws.cell(row=row_idx, column=entity_col).value or "N/A"
        domain = normalize_domain(link or source)
        if not domain:
            # No domain to classify; overwriting with "N/A" would turn an
            # unknown into a measured negative (P1). Counted as skipped, not
            # updated: nothing was written to this row, and calling it updated
            # overstated what the refresh did (P6, review chunk Y3).
            skipped += 1
            continue
        new_type, _confidence, _evidence = classifier.classify(domain, None)
        new_type = new_type or "N/A"
        ws.cell(row=row_idx, column=entity_col).value = new_type
        updated += 1
        if old_type != new_type:
            changed += 1

    wb.save(xlsx_path)
    if skipped:
        # The same line the JSON pass prints, so the two sides of one refresh
        # account for their rows the same way (P2).
        print(f"  {skipped} of {skipped + updated} workbook row(s) carry no "
              f"usable domain and keep their existing Entity_Type.")
    return updated, changed


# What a refresh cannot rebuild: every output that needs the SERP data itself,
# not just the rows already on disk. Printed so a refresh is not mistaken for
# a re-run (P2).
NOT_REBUILT = (
    "the Markdown report (market_analysis_*.md) — it is written by the audit "
    "and is not regenerated here; re-render it with "
    "`python3 generate_insight_report.py --json <json> --out <md>`",
    "keyword_feasibility — Domain Authority comes from a paid API call, so a "
    "refresh leaves the DA figures of the run that fetched them",
)


def _write_json_atomically(path, data):
    """Write ``data`` to ``path`` via a temp file and ``os.replace``.

    A direct ``json.dump`` onto the live file truncates it first, so a failure
    part-way through leaves a file that does not parse while the warning
    printed beside it describes a file that does (P6).
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def rebuild_keyword_profiles(data, config):
    """Rebuild ``keyword_profiles`` from the re-classified rows.

    Spec: review_2026-11-04 D4.12 (D-C-09)

    The profiles are derived from ``organic_results`` — entity counts, the
    entity distribution, the AIO citation analysis. Re-classifying the rows
    and leaving the profiles alone left the report quoting the entity mix of
    the previous taxonomy. Returns ``(built, changed)``: how many profiles the
    rebuild produced, and how many differ from the ones on disk.

    The citation rows carry no entity type of their own — their classification
    is derived inside the profiles — so rebuilding the profiles re-classifies
    the AIO citation analysis with them.
    """
    before = data.get("keyword_profiles") or {}
    profiles = brief_data_extraction.build_keyword_profiles(data, config)
    changed = sum(1 for k, v in profiles.items() if before.get(k) != v)
    changed += sum(1 for k in before if k not in profiles)
    data["keyword_profiles"] = profiles
    return len(profiles), changed


def regenerate_candidate_report(data, json_path, overrides_path, out_path):
    overrides = load_overrides(overrides_path)
    classifier = EntityClassifier(override_file=overrides_path)
    candidates = collect_candidates(
        data,
        overrides,
        classifier,
        min_rows=4,
        min_keywords=2,
    )
    report = render_markdown(candidates, json_path, overrides_path, 4, 2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    return len(candidates)


def refresh_analysis_outputs(json_path, xlsx_path, overrides_path, candidates_report_path,
                             config=None):
    classifier = EntityClassifier(override_file=overrides_path)
    config = load_config() if config is None else config
    data, json_updated, json_changed = refresh_json(json_path, classifier)
    # D4.12: the profiles are derived from the rows that were just
    # re-classified, so they are rebuilt in the same pass and written back.
    profiles_built = profiles_changed = 0
    profiles_error = None
    try:
        profiles_built, profiles_changed = rebuild_keyword_profiles(data, config)
    except Exception as e:
        # The re-classified rows are already written; an honest warning beats
        # leaving stale profiles behind without saying so (P1/P2).
        profiles_error = (f"keyword_profiles could not be rebuilt ({e}). The "
                          f"organic rows were re-classified but the profiles "
                          f"in {json_path} still describe the previous "
                          f"taxonomy.")
        print(f"  WARNING: {profiles_error}")
        # The re-classified rows still have to reach disk: `refresh_json` no
        # longer writes, so this is the only write on this path.
        try:
            _write_json_atomically(json_path, data)
        except Exception as write_exc:
            profiles_error += (f" The re-classified rows could not be written "
                               f"either ({write_exc}): {json_path} is "
                               f"unchanged.")
            print(f"  WARNING: {json_path} could not be written: {write_exc}")
    else:
        try:
            _write_json_atomically(json_path, data)
        except Exception as e:
            # A distinct failure from the one above, and a distinct message:
            # the rebuild worked, the file on disk did not change.
            profiles_error = (f"keyword_profiles were rebuilt but {json_path} "
                              f"could not be written ({e}): the file still "
                              f"holds the profiles from before the rebuild.")
            print(f"  WARNING: {profiles_error}")
    xlsx_updated, xlsx_changed = refresh_xlsx(xlsx_path, classifier)
    candidate_count = regenerate_candidate_report(
        data,
        json_path,
        overrides_path,
        candidates_report_path,
    )
    return {
        "json_updated": json_updated,
        "json_changed": json_changed,
        "profiles_built": profiles_built,
        "profiles_changed": profiles_changed,
        "profiles_error": profiles_error,
        "xlsx_updated": xlsx_updated,
        "xlsx_changed": xlsx_changed,
        "candidate_count": candidate_count,
    }


def main():
    defaults = load_config_paths()
    parser = argparse.ArgumentParser(
        description="Refresh local analysis files after domain override updates."
    )
    parser.add_argument("--json", default=defaults["json"])
    parser.add_argument("--xlsx", default=defaults["xlsx"])
    parser.add_argument("--overrides", default=defaults["overrides"])
    parser.add_argument("--candidate-report", default=defaults["candidates_report"])
    args = parser.parse_args()

    result = refresh_analysis_outputs(
        json_path=args.json,
        xlsx_path=args.xlsx,
        overrides_path=args.overrides,
        candidates_report_path=args.candidate_report,
    )
    print(
        f"Refreshed JSON rows: {result['json_updated']} (changed: {result['json_changed']})"
    )
    print(
        f"Refreshed XLSX rows: {result['xlsx_updated']} (changed: {result['xlsx_changed']})"
    )
    if result["profiles_error"] is None:
        print(
            f"Rebuilt keyword_profiles: {result['profiles_built']} "
            f"(changed: {result['profiles_changed']})"
        )
    print(f"Regenerated candidate report. Remaining candidates: {result['candidate_count']}")
    print("Not rebuilt by a refresh:")
    for item in NOT_REBUILT:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
