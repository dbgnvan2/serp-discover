"""
CD.9 / CD.10 — the glossary reaches every surface that carries the jargon.

Spec: report_content_direction_spec.md#CD.9, #CD.10

CD.4 defined the report's terms of art inside the report. Two surfaces still
carried undefined jargon:

  CD.9  the .xlsx workbook, whose headers are machine field names (avg_serp_da,
        Params_Hash, Rank_Delta). Headers are NOT renamed — the JSON and the
        workbook share one field vocabulary that validate_xlsx_vs_json.py checks
        column by column, and renaming would break that contract and any user
        formulas. A "Glossary" sheet carries the meaning instead.

  CD.10 a standalone glossary document, so the definitions can be read and
        shared without opening a run's report.

This is the P25 shape: a capability wired at one surface is not wired at the
others. Every test here is mutation-checked.
"""

import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import generate_insight_report as gir
from test_report_content_direction import _reset_gir_caches  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clear_caches():
    _reset_gir_caches()
    yield
    _reset_gir_caches()


class TestCD9WorkbookGlossary:

    def test_cd9_1_rows_cover_columns_and_terms(self):
        """CD.9.1 — one sheet answers both kinds of question."""
        rows = gir.build_glossary_rows()
        wheres = {r["Where"] for r in rows}
        assert any(w.startswith("Column") for w in wheres)
        assert "Term" in wheres

    def test_cd9_1b_row_count_is_exact(self):
        """CD.9.1 — every YAML entry becomes a row. Exact, not a floor (P29).

        A floor would not notice the column block being dropped entirely.
        """
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "glossary.yml"), encoding="utf-8"))
        expected = len(raw["columns"]) + len(raw["terms"])
        assert len(gir.build_glossary_rows()) == expected

    def test_cd9_2_jargon_columns_are_defined(self):
        """CD.9.2 — the specific headers a reader cannot guess are covered.

        Membership of known-hard cases rather than a count (P29): these are the
        columns that prompted the change.
        """
        defined = " | ".join(r["Item"] for r in gir.build_glossary_rows())
        for column in ["avg_serp_da", "client_da", "gap", "Params_Hash",
                       "Rank_Delta", "Query_Label", "Entity_Type",
                       "Content_Type", "SERP_Features", "feasibility_score"]:
            assert column in defined, f"{column} has no glossary entry"

    def test_cd9_3_every_row_has_a_meaning(self):
        """CD.9 — no row ships with a blank definition."""
        for row in gir.build_glossary_rows():
            assert str(row["Meaning"]).strip(), row["Item"]

    def test_cd9_3b_newlines_flattened_for_the_cell(self, monkeypatch):
        """CD.9 — a multi-line definition is flattened into one cell.

        Today's glossary.yml uses folded (>-) scalars, so nothing in it contains
        a newline and the flattening is never exercised by the real data. A
        literal block scalar (|) would, and an embedded newline breaks the
        spreadsheet cell — so drive the builder with one deliberately.
        """
        monkeypatch.setattr(gir, "_load_glossary_columns", lambda: [
            {"column": "test_col", "sheet": "X",
             "definition": "First line.\nSecond line."}])
        monkeypatch.setattr(gir, "_load_glossary", lambda: [])
        row = gir.build_glossary_rows()[0]
        assert "\n" not in row["Meaning"], (
            "a multi-line definition reached the cell unflattened")
        assert row["Meaning"] == "First line. Second line."

    def test_cd9_4_sheet_written_to_workbook(self, tmp_path):
        """CD.9.3 — the sheet actually reaches a written .xlsx.

        build_glossary_rows() working in isolation says nothing about whether
        serp_audit writes it (P21/P25). This writes a real workbook through the
        same pandas path and reads the sheet back.
        """
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        out = tmp_path / "wb.xlsx"
        rows = gir.build_glossary_rows()
        assert rows, "no glossary rows to write"
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pd.DataFrame([{"a": 1}]).to_excel(
                writer, sheet_name="Overview", index=False)
            pd.DataFrame(rows).to_excel(
                writer, sheet_name="Glossary", index=False)

        book = pd.read_excel(out, sheet_name=None)
        assert "Glossary" in book
        sheet = book["Glossary"]
        assert list(sheet.columns) == ["Item", "Where", "Meaning"]
        assert len(sheet) == len(rows)
        assert "avg_serp_da" in set(sheet["Item"])

    def test_cd9_5_serp_audit_calls_the_builder(self):
        """CD.9.3 — serp_audit actually calls the builder when writing the book.

        Asserting that serp_audit can *reach* gir.build_glossary_rows is trivially
        true of any module that imports it and proves nothing — it stays green
        with the call site deleted. There is no way to observe the call without
        running a full paid audit, so this walks the AST for the call site
        itself, which is the sanctioned form of a "is this wired?" check: a
        parsed call node, not a substring that a comment could satisfy.
        """
        import ast
        source = open(os.path.join(REPO_ROOT, "serp_audit.py"),
                      encoding="utf-8").read()
        called = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called.add(func.attr)
                elif isinstance(func, ast.Name):
                    called.add(func.id)
        assert "build_glossary_rows" in called, (
            "serp_audit.py has no call to build_glossary_rows — the workbook "
            "will ship without its Glossary sheet")

    def test_cd9_7_sheet_guidance_from_yaml(self):
        """CD.9 — the workbook's Help text is editorial config, not a Python
        literal, and serp_audit reads it from there."""
        import serp_audit
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "glossary.yml"), encoding="utf-8"))
        assert raw.get("sheet_guidance"), "sheet_guidance missing from glossary.yml"
        rows = serp_audit.build_help_rows()
        assert len(rows) == len(raw["sheet_guidance"])
        for row in rows:
            for field in ("Tab", "Trigger", "Likely_Query_Type", "Why_Empty"):
                assert str(row.get(field) or "").strip(), f"{row.get('Tab')}: {field}"

    def test_cd9_7b_sheet_guidance_follows_the_yaml(self, monkeypatch, tmp_path):
        """CD.9 — behavioural: change the YAML, the Help sheet changes."""
        sentinel = "SENTINEL-HELP-ROW-5d2e"
        (tmp_path / "glossary.yml").write_text(yaml.safe_dump({
            "sheet_guidance": [{"Tab": sentinel, "Trigger": "t",
                                "Likely_Query_Type": "q", "Why_Empty": "w"}],
            "terms": [], "columns": [],
        }), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        import serp_audit
        assert serp_audit.build_help_rows()[0]["Tab"] == sentinel

    def test_cd9_6_headers_are_not_renamed(self):
        """CD.9 — the workbook/JSON field contract is untouched.

        The fix adds a sheet; it must not rename columns, because
        validate_xlsx_vs_json.py compares them by name.
        """
        import validate_xlsx_vs_json as v
        specs = {s.sheet_name: s for s in v.SPECS}
        assert "Glossary" not in specs, (
            "the Glossary sheet must not be added to the JSON parity contract — "
            "it has no JSON counterpart and would fail every run")
        feas_cols = set(specs["Overview"].required_cols)
        assert "Run_ID" in feas_cols, "Overview's field names changed"


class TestCD10StandaloneGlossary:

    def test_cd10_1_document_contains_every_term(self):
        """CD.10.1 — the standalone doc is unfiltered, unlike the in-report one."""
        doc = gir.build_glossary_document()
        for entry in gir._load_glossary():
            assert f"**{entry['term']}**" in doc, entry["term"]

    def test_cd10_2_document_contains_column_table(self):
        doc = gir.build_glossary_document()
        assert "## Columns in the .xlsx workbook" in doc
        assert "`avg_serp_da`" in doc

    def test_cd10_3_pipes_escaped_in_table(self, monkeypatch):
        """CD.10 — a definition containing '|' must not break the table.

        No definition in glossary.yml contains a pipe today, so the real data
        cannot exercise this. Inject one: unescaped, it would split the row into
        extra columns and corrupt the whole table below it.
        """
        monkeypatch.setattr(gir, "_load_glossary_columns", lambda: [
            {"column": "piped", "sheet": "X",
             "definition": "Either A | or B, your choice."}])
        monkeypatch.setattr(gir, "_load_glossary", lambda: [])
        doc = gir.build_glossary_document()
        row = next(l for l in doc.split("\n") if l.startswith("| `piped`"))
        assert "\\|" in row, "the pipe inside the definition was not escaped"
        # Exactly 4 unescaped delimiters = a well-formed 3-column row.
        assert row.count("|") - row.count("\\|") == 4, row

    def test_cd10_3b_real_table_rows_are_well_formed(self):
        """CD.10 — and every row actually shipped is well-formed."""
        doc = gir.build_glossary_document()
        rows = [l for l in doc.split("\n") if l.startswith("| `")]
        assert rows, "no column rows in the document"
        for row in rows:
            assert row.count("|") - row.count("\\|") == 4, row

    def test_cd10_4_checked_in_doc_is_current(self):
        """CD.10.2 — docs/glossary.md matches what the builder produces now.

        A generated file checked into the repo goes stale silently; this fails
        the build when glossary.yml moves on without a regenerate.
        """
        path = os.path.join(REPO_ROOT, "docs", "glossary.md")
        assert os.path.exists(path), (
            "docs/glossary.md missing — regenerate with "
            "python3 generate_insight_report.py --glossary-out docs/glossary.md")
        on_disk = open(path, encoding="utf-8").read()
        assert on_disk == gir.build_glossary_document(), (
            "docs/glossary.md is stale — regenerate with "
            "python3 generate_insight_report.py --glossary-out docs/glossary.md")

    def test_cd10_5_cli_writes_without_a_run(self, tmp_path, monkeypatch):
        """CD.10.3 — --glossary-out needs no --json.

        The glossary is editorial content, not run output: producing it must not
        require a market_analysis JSON.
        """
        out = tmp_path / "g.md"
        monkeypatch.setattr(
            sys, "argv",
            ["generate_insight_report.py", "--glossary-out", str(out)])
        gir.main()
        assert out.exists()
        assert "# Glossary" in out.read_text(encoding="utf-8")

    def test_cd10_6_missing_json_still_errors_for_a_report(self, monkeypatch, capsys):
        """CD.10.3 — making --json optional must not let a report run without it.

        Pinned to argparse's own exit (code 2) and its message. Asserting merely
        "exited non-zero" passed with the guard deleted, because load_data(None)
        failed later and exited 1 anyway — a different failure, much further in,
        with a confusing message.
        """
        monkeypatch.setattr(sys, "argv", ["generate_insight_report.py"])
        with pytest.raises(SystemExit) as exc:
            gir.main()
        assert exc.value.code == 2, (
            "expected an argument-parsing error, not a downstream failure")
        assert "--json and --out are required" in capsys.readouterr().err
