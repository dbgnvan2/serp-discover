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
        key_cols=("Run_ID", "Source_Keyword"),
        normalize_text_cols=("Search_Query_Used",),
        required_cols=("Run_ID", "Search_Query_Used", "Total_Results"),
    ),
    SheetSpec(
        sheet_name="Organic_Results",
        json_key="organic_results",
        key_cols=("Run_ID", "Source_Keyword", "Rank", "Link"),
        normalize_text_cols=("Title", "Snippet", "Source",
                             "Content_Type", "Entity_Type", "Word_Count", "Rank_Delta"),
        required_cols=("Run_ID", "Rank", "Title", "Link",
                       "Snippet", "Content_Type", "Entity_Type", "Word_Count", "Rank_Delta"),
    ),
    SheetSpec(
        sheet_name="PAA_Questions",
        json_key="paa_questions",
        key_cols=("Run_ID", "Source_Keyword", "Rank", "Question"),
        normalize_text_cols=("Question", "Snippet"),
        required_cols=("Run_ID", "Rank", "Question"),
    ),
    SheetSpec(
        sheet_name="Related_Searches",
        json_key="related_searches",
        key_cols=("Run_ID", "Source_Keyword", "Type", "Term"),
        normalize_text_cols=("Term",),
        required_cols=("Run_ID", "Type", "Term"),
    ),
    SheetSpec(
        sheet_name="Derived_Expansions",
        json_key="derived_expansions",
        key_cols=("Run_ID", "Source_Keyword", "Type", "Term"),
        normalize_text_cols=("Term",),
        required_cols=("Run_ID", "Type", "Term"),
    ),
    SheetSpec(
        sheet_name="Competitors_Ads",
        json_key="competitors_ads",
        key_cols=("Run_ID", "Source_Keyword", "Type", "Name", "Link"),
        normalize_text_cols=("Name", "Snippet"),
        required_cols=("Run_ID", "Type", "Name"),
    ),
    SheetSpec(
        sheet_name="Local_Pack_and_Maps",
        json_key="local_pack_and_maps",
        key_cols=("Run_ID", "Source_Keyword", "Source", "Rank", "Name"),
        normalize_text_cols=("Name", "Category", "Address"),
        required_cols=("Run_ID", "Source", "Rank", "Name"),
    ),
    SheetSpec(
        sheet_name="AI_Overview_Citations",
        json_key="ai_overview_citations",
        key_cols=("Run_ID", "Source_Keyword", "Link"),
        normalize_text_cols=("Title", "Source"),
        required_cols=("Run_ID", "Link"),
    ),
    SheetSpec(
        sheet_name="SERP_Modules",
        json_key="serp_modules",
        key_cols=("Run_ID", "Source_Keyword", "Module"),
        normalize_text_cols=("Module",),
        required_cols=("Run_ID", "Module"),
    ),
    SheetSpec(
        sheet_name="Rich_Features",
        json_key="rich_features",
        key_cols=("Run_ID", "Source_Keyword", "Feature", "Details"),
        normalize_text_cols=("Feature", "Details"),
        required_cols=("Run_ID", "Feature"),
    ),
    SheetSpec(
        sheet_name="Parsing_Warnings",
        json_key="parsing_warnings",
        key_cols=("Run_ID", "Source_Keyword", "Module", "Message"),
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


def index_records(records: List[Dict[str, Any]], key_cols: Tuple[str, ...], text_cols: Tuple[str, ...]):
    """``(index, counts)`` for one record set.

    ``counts`` maps every key to how many rows carried it. The index keeps the
    last of them, as it always has — which is why the counts are needed: of a
    repeated key only the survivor is field-compared, so the rest pass the
    gate unchecked while row counts and key sets still agree. Some sheets
    repeat a key legitimately (the same related search harvested twice for one
    keyword, with no field that tells the two rows apart), so a repeat is
    reported as a gap in coverage and only a DIFFERENCE in the repeat counts
    between the two files is a disagreement (cold review of the
    field-comparison fix, finding 5).
    """
    idx: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    counts: Dict[Tuple[Any, ...], int] = {}
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
            # A duplicate key overwrites, which it has always done. What is
            # new is that the field comparison now rests on this index: of a
            # duplicate pair only the survivor is compared, so the other row
            # passes the gate unchecked while counts and key sets still
            # agree. Counted and reported rather than dropped (P2, cold
            # review of the field-comparison fix, finding 5).
            pass  # the index keeps the last; `counts` records the rest
        counts[key] = counts.get(key, 0) + 1
        idx[key] = rr
    return idx, counts

#: What a cell may differ by and still be the same number. A workbook stores
#: every number as a float, so an integer written as 9 is read back as 9.0 and
#: a ratio written as 0.1 can come back a few bits away from it.
NUMERIC_TOLERANCE = 1e-9


def values_agree(a: Any, b: Any) -> bool:
    """Whether two cells hold the same value across the Excel round trip.

    Not `==`: the workbook is a lossy carrier. Both sides are collapsed to
    `None` for every form of absence, numbers compare within
    `NUMERIC_TOLERANCE` (a sheet stores 9 as 9.0), a number compares equal to
    its own decimal spelling (a column of mixed types reads back as text),
    and text compares after `norm_text`'s line-ending and whitespace
    collapse.
    """
    a = blank_to_none(a)
    b = blank_to_none(b)
    if a is None or b is None:
        return a is None and b is None
    a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_num and b_num:
        if pd.isna(a) or pd.isna(b):
            return bool(pd.isna(a) and pd.isna(b))
        return abs(float(a) - float(b)) <= NUMERIC_TOLERANCE * max(
            1.0, abs(float(a)), abs(float(b)))
    if a_num != b_num:
        number, text = (a, b) if a_num else (b, a)
        if not isinstance(text, str):
            return False
        try:
            return abs(float(number) - float(text.strip())) <= (
                NUMERIC_TOLERANCE * max(1.0, abs(float(number))))
        except ValueError:
            return False
    if isinstance(a, str) and isinstance(b, str):
        return norm_text(a) == norm_text(b)
    return bool(a == b)


def compared_columns(spec: SheetSpec, left: Dict[str, Any],
                     right: Dict[str, Any]):
    """`(compared, not_compared, missing_declared)` for one sheet's rows.

    The declared contract — `required_cols` plus `normalize_text_cols`, minus
    the key, which matching the row already proved — is what is compared.
    Anything else the two files carry is returned as NOT compared and said so
    in the report, rather than being counted as checked (P2).
    """
    present = set(left) | set(right)
    declared = (set(spec.required_cols) | set(spec.normalize_text_cols)
                ) - set(spec.key_cols)
    compared = tuple(sorted(declared & present))
    return (compared,
            tuple(sorted(present - declared - set(spec.key_cols))),
            # A declared column neither file carries any more fell out of
            # `compared` and never entered `not_compared`, so the gate
            # reported full coverage of a contract column that no longer
            # exists (P3, cold review of this fix, finding 3).
            tuple(sorted(declared - present)))


def field_mismatches(spec: SheetSpec,
                     x_idx: Dict[Tuple[Any, ...], Dict[str, Any]],
                     j_idx: Dict[Tuple[Any, ...], Dict[str, Any]],
                     ) -> Dict[str, Any]:
    """What the field comparison found, and what it covered.

    Returns ``{"mismatches", "rows_compared", "not_compared",
    "missing_declared"}``.

    Until 2026-11-19 this did not exist: the step compared row counts and key
    tuples only, `normalize_text_cols` was computed into a record that was
    then discarded and `required_cols` was never read at all, so a workbook
    whose `Title`, `Snippet`, `Word_Count` or `Content_Type` disagreed with
    the JSON passed a gate the pipeline labels "Data Validation" (P33 —
    complete along one axis, presented as a full cross-check).
    """
    mismatches: List[Dict[str, Any]] = []
    # Accumulated across every row, not overwritten by the last one: a column
    # only some rows carry was reported as unchecked or not depending on which
    # key happened to sort last (cold review of this fix, finding 4).
    not_compared: set = set()
    missing_declared: set = set()
    shared = sorted(x_idx.keys() & j_idx.keys(), key=repr)
    for key in shared:
        x_row, j_row = x_idx[key], j_idx[key]
        cols, uncompared, missing = compared_columns(spec, x_row, j_row)
        not_compared.update(uncompared)
        missing_declared.update(missing)
        for col in cols:
            if not values_agree(x_row.get(col), j_row.get(col)):
                mismatches.append({"key": str(key), "column": col,
                                   "xlsx": repr(x_row.get(col)),
                                   "json": repr(j_row.get(col))})
    return {"mismatches": mismatches,
            # How many rows this comparison actually ran over. Without it an
            # empty mismatch list reads the same whether every row agreed or
            # no row was compared at all.
            "rows_compared": len(shared),
            "not_compared": tuple(sorted(not_compared)),
            "missing_declared": tuple(sorted(missing_declared))}


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

        # `columns_not_compared` names, per sheet, the columns present in the
        # files that no spec declares — what this gate does NOT check, stated
        # rather than left for a reader to infer from the absence of a
        # complaint.
        diff: Dict[str, Any] = {"matches": True, "errors": [],
                                "sheet_diffs": {},
                                "columns_not_compared": {},
                                # How many rows the field comparison ran over
                                # per sheet. An empty mismatch list otherwise
                                # reads the same whether every row agreed or
                                # no row was compared at all.
                                "rows_field_compared": {},
                                # Rows a repeated key hid from the field
                                # comparison: the index keeps one row per key.
                                "rows_not_individually_compared": {}}

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
                x_idx, x_counts = index_records(
                    xlsx_recs, spec.key_cols, spec.normalize_text_cols)
                j_idx, j_counts = index_records(
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

            # 5. Compare the rows both files hold, field by field.
            found = field_mismatches(spec, x_idx, j_idx)
            diff["columns_not_compared"][spec.sheet_name] = list(
                found["not_compared"])
            diff["rows_field_compared"][spec.sheet_name] = found[
                "rows_compared"]
            if found["mismatches"]:
                diff["matches"] = False
                entry = diff["sheet_diffs"].setdefault(spec.sheet_name, {})
                entry["field_mismatch_count"] = len(found["mismatches"])
                entry["field_mismatch_sample"] = found["mismatches"][:10]
            if found["missing_declared"]:
                # A column this sheet's spec declares that NEITHER file
                # carries. The spec is the contract; a contract column that
                # has silently stopped being written is a failure of the gate
                # the spec exists for, not a detail of one row.
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})[
                    "declared_columns_missing"] = list(
                        found["missing_declared"])
            # A key carried by more than one row: only the survivor was
            # field-compared. Reported as coverage, because several sheets
            # repeat a key legitimately; a DIFFERENCE in how often a key
            # repeats is a real disagreement and fails.
            repeated = sorted((set(x_counts) | set(j_counts)), key=repr)
            uncompared_rows = sum(
                max(x_counts.get(k, 0), j_counts.get(k, 0)) - 1
                for k in repeated
                if max(x_counts.get(k, 0), j_counts.get(k, 0)) > 1)
            if uncompared_rows:
                diff["rows_not_individually_compared"][
                    spec.sheet_name] = uncompared_rows
            differing = [k for k in repeated
                         if k in x_counts and k in j_counts
                         and x_counts[k] != j_counts[k]]
            if differing:
                diff["matches"] = False
                diff["sheet_diffs"].setdefault(spec.sheet_name, {})[
                    "duplicate_count_mismatch"] = [
                        {"key": str(k), "xlsx": x_counts[k],
                         "json": j_counts[k]} for k in differing[:10]]

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
