#!/usr/bin/env python3
"""
validate_xlsx_vs_json.py

Usage:
  python validate_xlsx_vs_json.py --xlsx market_analysis_v2.xlsx --json market_analysis_v2.json --out diff_report.json

Exit codes:
  0 = match
  1 = mismatch
  2 = error (schema/config)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

# ----------------------------
# Config
# ----------------------------


@dataclass(frozen=True)
class SheetSpec:
    sheet_name: str
    json_key: str
    key_cols: Tuple[str, ...]
    normalize_text_cols: Tuple[str, ...] = ()
    required_cols: Tuple[str, ...] = ()


SPECS: List[SheetSpec] = [
    SheetSpec(
        sheet_name="Overview",
        json_key="overview",
        key_cols=("Run_ID",),
        normalize_text_cols=("Search_Query_Used",),
        required_cols=("Run_ID", "Search_Query_Used", "Total_Results"),
    ),
    SheetSpec(
        sheet_name="Organic_Results",
        json_key="organic_results",
        key_cols=("Run_ID", "Rank", "Link"),
        normalize_text_cols=("Title", "Snippet", "Source",
                             "Content_Type", "Entity_Type", "Word_Count", "Rank_Delta"),
        required_cols=("Run_ID", "Rank", "Title", "Link",
                       "Snippet", "Content_Type", "Entity_Type", "Word_Count", "Rank_Delta"),
    ),
    SheetSpec(
        sheet_name="PAA_Questions",
        json_key="paa_questions",
        key_cols=("Run_ID", "Rank", "Question"),
        normalize_text_cols=("Question", "Snippet"),
        required_cols=("Run_ID", "Rank", "Question"),
    ),
    SheetSpec(
        sheet_name="Related_Searches",
        json_key="related_searches",
        key_cols=("Run_ID", "Type", "Term"),
        normalize_text_cols=("Term",),
        required_cols=("Run_ID", "Type", "Term"),
    ),
    SheetSpec(
        sheet_name="Derived_Expansions",
        json_key="derived_expansions",
        key_cols=("Run_ID", "Type", "Term"),
        normalize_text_cols=("Term",),
        required_cols=("Run_ID", "Type", "Term"),
    ),
    SheetSpec(
        sheet_name="Competitors_Ads",
        json_key="competitors_ads",
        key_cols=("Run_ID", "Type", "Name", "Link"),
        normalize_text_cols=("Name", "Snippet"),
        required_cols=("Run_ID", "Type", "Name"),
    ),
    SheetSpec(
        sheet_name="Local_Pack_and_Maps",
        json_key="local_pack_and_maps",
        key_cols=("Run_ID", "Source", "Rank", "Name"),
        normalize_text_cols=("Name", "Category", "Address"),
        required_cols=("Run_ID", "Source", "Rank", "Name"),
    ),
    SheetSpec(
        sheet_name="AI_Overview_Citations",
        json_key="ai_overview_citations",
        key_cols=("Run_ID", "Link"),
        normalize_text_cols=("Title", "Source"),
        required_cols=("Run_ID", "Link"),
    ),
    SheetSpec(
        sheet_name="SERP_Modules",
        json_key="serp_modules",
        key_cols=("Run_ID", "Module"),
        normalize_text_cols=("Module",),
        required_cols=("Run_ID", "Module"),
    ),
    SheetSpec(
        sheet_name="Rich_Features",
        json_key="rich_features",
        key_cols=("Run_ID", "Feature", "Details"),
        normalize_text_cols=("Feature", "Details"),
        required_cols=("Run_ID", "Feature"),
    ),
    SheetSpec(
        sheet_name="Parsing_Warnings",
        json_key="parsing_warnings",
        key_cols=("Run_ID", "Module", "Message"),
        normalize_text_cols=("Message",),
        required_cols=("Run_ID", "Module", "Message"),
    ),
    SheetSpec(
        sheet_name="AIO_Logs",
        json_key="aio_logs",
        key_cols=("Run_ID", "Keyword"),
        normalize_text_cols=("error",),
        required_cols=("Run_ID", "Keyword", "has_ai_overview"),
    ),
    SheetSpec(
        sheet_name="Autocomplete_Suggestions",
        json_key="autocomplete_suggestions",
        key_cols=("Run_ID", "Source_Keyword", "Rank"),
        normalize_text_cols=("Suggestion", "Type"),
        required_cols=("Run_ID", "Source_Keyword", "Rank", "Suggestion"),
    ),
    # Global aggregate
    SheetSpec(
        sheet_name="SERP_Language_Patterns",
        json_key="serp_language_patterns",
        key_cols=("Type", "Phrase"),
        normalize_text_cols=("Phrase",),
        required_cols=("Type", "Phrase", "Count"),
    ),
    SheetSpec(
        sheet_name="Strategic_Recommendations",
        json_key="strategic_recommendations",
        key_cols=("Pattern_Name",),
        normalize_text_cols=("Status_Quo_Message", "Bowen_Bridge_Reframe"),
        required_cols=("Pattern_Name", "Status_Quo_Message",
                       "Bowen_Bridge_Reframe"),
    ),
]

# ----------------------------
# Helpers
# ----------------------------


def blank_to_none(x: Any) -> Any:
    """`None` for every way a cell can be empty, on either side.

    One absence, one representation. A blank cell and a written empty string
    are indistinguishable once a workbook has been saved, and the JSON side
    writes `null` where the sheet side writes nothing, so a key of `""` and a
    key of `None` are the same key and must compare equal.

    This is the second half of the fix for the 2026-11-18 live-run failure.
    The first half stopped a stated `"N/A"` being read as a blank; the empty
    string was left normalised on the workbook side only, which reproduced
    the identical both-sides-missing signature for a key cell that is `""` in
    the JSON and blank in the sheet — `Rich_Features.Details` is written as
    `primary_results[key].get("title")` and yields `""` for a Knowledge Panel
    with no title. Found by the cold review of that fix; applied here, in the
    one place both record sets pass through.
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, str) and x.strip() == "":
        return None
    return x


def norm_text(x: Any) -> Any:
    x = blank_to_none(x)
    if not isinstance(x, str):
        return x
    s = x.replace("\r\n", "\n").strip()
    # optional: collapse runs of whitespace
    s = " ".join(s.split())
    # A string of nothing but whitespace strips to "", which is the same
    # absence `blank_to_none` just handled — said once, both ways in.
    return s or None


#: How a sheet is read back. `keep_default_na=False` with an empty `na_values`
#: is not a preference: pandas' DEFAULT missing-value list contains the string
#: `"N/A"`, and `"N/A"` is this tool's own written-out marker for a value it
#: did not get — a SERP result with no link carries `Link: "N/A"`. Read with
#: the defaults, that cell comes back as `NaN`, the key tuple becomes
#: `(run_id, 9, nan)` on the workbook side and `(run_id, 9, "N/A")` on the
#: JSON side, and the validator reports the same row as missing from both
#: files. The pipeline then hard-fails at step 1.2 on any run where one result
#: has no link, which is most real runs. Found by the first live run after the
#: 2026-11-04 review (2026-11-18); no mocked test could have found it, because
#: the collision is between a real workbook and pandas' own defaults.
READ_OPTIONS = {"keep_default_na": False, "na_values": []}


def df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """The sheet's rows, with an empty cell as `None`.

    Read with `READ_OPTIONS`, a genuinely empty cell arrives as `""` rather
    than `NaN`, so it is mapped here instead: the JSON side writes `null` for
    the same absence, and a key of `""` would not match one of `None`. A
    stated marker such as `"N/A"` is left exactly as it is written — it is a
    value, not a blank.
    """
    out = df.where(pd.notnull(df), None).to_dict(orient="records")
    for row in out:
        for column, value in row.items():
            # `DataFrame.where` leaves NaN in place on an object column in
            # some pandas versions, which is how a float nan reached a key
            # tuple in the first place.
            row[column] = blank_to_none(value)
    return out


def index_records(records: List[Dict[str, Any]], key_cols: Tuple[str, ...], text_cols: Tuple[str, ...]) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    idx: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for r in records:
        rr = dict(r)
        for c in text_cols:
            if c in rr:
                rr[c] = norm_text(rr[c])

        # Construct key
        key_parts = []
        for k in key_cols:
            val = rr.get(k)
            # Normalize key text fields too if they are in text_cols
            if k in text_cols:
                val = norm_text(val)
            # Every key part, declared a text column or not: a key column that
            # is not in `normalize_text_cols` (`Rich_Features.Details` is one)
            # would otherwise keep `""` on the JSON side while the sheet side
            # read `None`, and the two rows would each report the other as
            # missing.
            key_parts.append(blank_to_none(val))

        key = tuple(key_parts)

        if key in idx:
            # Duplicate key found. In a real scenario, we might want to log this.
            # For now, we overwrite or raise. Let's raise to be strict.
            # Exception: Bad_Advice_Patterns might have duplicates if not aggregated correctly,
            # but the script aggregates them.
            # print(f"Warning: Duplicate key found for {key_cols}: {key}")
            pass
        idx[key] = rr
    return idx

# ----------------------------
# Main validation
# ----------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    xlsx_path = Path(args.xlsx)
    json_path = Path(args.json)
    out_path = Path(args.out)

    try:
        # Load JSON (Expects a flat dict of lists)
        json_data = json.loads(json_path.read_text(encoding="utf-8"))

        # Load Excel
        xl = pd.ExcelFile(xlsx_path)

        diff: Dict[str, Any] = {"matches": True,
                                "errors": [], "sheet_diffs": {}}

        for spec in SPECS:
            # 1. Check Sheet Existence
            if spec.sheet_name not in xl.sheet_names:
                diff["matches"] = False
                diff["sheet_diffs"][spec.sheet_name] = {
                    "missing_sheet_in_xlsx": True}
                continue

            # 2. Load Data
            sdf = xl.parse(spec.sheet_name, **READ_OPTIONS)
            xlsx_recs = df_to_records(sdf)
            json_recs = json_data.get(spec.json_key, [])

            # 3. Compare Counts
            if len(xlsx_recs) != len(json_recs):
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})["row_count"] = {
                    "xlsx": len(xlsx_recs),
                    "json": len(json_recs),
                }

            # 4. Index and Compare Keys
            try:
                x_idx = index_records(
                    xlsx_recs, spec.key_cols, spec.normalize_text_cols)
                j_idx = index_records(
                    json_recs, spec.key_cols, spec.normalize_text_cols)
            except Exception as e:
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})[
                    "indexing_error"] = str(e)
                continue

            missing_in_xlsx = [str(k) for k in j_idx.keys() if k not in x_idx]
            missing_in_json = [str(k) for k in x_idx.keys() if k not in j_idx]

            if missing_in_xlsx:
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})[
                    "missing_in_xlsx_sample"] = missing_in_xlsx[:10]
            if missing_in_json:
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})[
                    "missing_in_json_sample"] = missing_in_json[:10]

        out_path.write_text(json.dumps(
            diff, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if diff["matches"] else 1

    except Exception as e:
        err = {"matches": False, "errors": [str(e)]}
        out_path.write_text(json.dumps(
            err, indent=2, ensure_ascii=False), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
