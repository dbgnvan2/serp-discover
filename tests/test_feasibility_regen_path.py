"""Regression test for the item-3 -> report auto-regeneration target path.

Purpose: After Run Feasibility Analysis, the GUI regenerates the MARKET ANALYSIS
         report. It must write to the market_analysis .md that matches the JSON
         it just updated (same stem), NOT output_names["report_out"] — which is
         the content_opportunities file. The old code used report_out, so the
         user's market_analysis .md stayed stale ("feasibility data is missing")
         and a bogus content_opportunities_<ts>.md was created instead.
Spec:    feasibility regen fix (2026-08-07)
Tests:   tests/test_feasibility_regen_path.py

AST/source-inspection (no tkinter): inspect the auto-regenerate method body.
"""

import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERP_ME_PATH = os.path.join(REPO_ROOT, "serp-me.py")

METHOD = "auto_regenerate_market_analysis_after_feasibility"


def _method_node_and_source():
    with open(SERP_ME_PATH, "r", encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src, filename=SERP_ME_PATH)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == METHOD:
            return node, ast.get_source_segment(src, node)
    raise AssertionError(f"{METHOD} not found in serp-me.py")


NODE, SOURCE = _method_node_and_source()

# String constants that appear in actual CODE (comments are not in the AST).
_STRING_CONSTS = {
    n.value for n in ast.walk(NODE)
    if isinstance(n, ast.Constant) and isinstance(n.value, str)
}


def test_regen_does_not_target_report_out():
    """The regen must NOT write the market-analysis report to report_out (content_opportunities)."""
    assert "report_out" not in _STRING_CONSTS, (
        "auto-regenerate still uses the 'report_out' key; that is the "
        "content_opportunities file, not the market_analysis .md."
    )


def test_regen_derives_md_from_input_json():
    """The regen derives the .md target from the JSON it updated (same stem)."""
    assert ".json" in SOURCE and '".md"' in SOURCE, SOURCE
    # It must pass the derived md path (md_out) to generate_insight_report --out.
    assert "md_out" in SOURCE


def test_regen_calls_generate_insight_report():
    """Sanity: the method still invokes the insight-report generator."""
    assert "generate_insight_report.py" in SOURCE
