"""RC.1.2 write-first: contract + degraded-path regression tests.

Purpose: Guard the two ways RC.1.2 could break:
  1. _order_briefs_by_opportunity must return the SAME 4-tuple shape on both its
     normal and early-return paths (the early return used to yield a 2-tuple,
     which crashed the Exec Summary when a top brief had an empty Content_Angle).
  2. _render_executive_summary must not raise on a degraded run (strategic recs
     present, keyword_profiles empty, Content_Angle empty) — a raise there would
     abort the whole market_analysis_*.md write.
Spec:    report_clarity_spec.md#RC.1.2 / #RC.8 ; regen/sweep fixes (2026-08-07)
Tests:   tests/test_rc12_writefirst.py
"""

from generate_insight_report import (
    _order_briefs_by_opportunity,
    _render_executive_summary,
)


def test_order_briefs_returns_4tuples_on_early_return():
    """Early return (no keyword_profiles) must match the normal 4-tuple contract."""
    data = {"keyword_profiles": {}}  # forces the early-return branch
    recs = [{"Pattern_Name": "Reactivity"}, {"Pattern_Name": "Fusion"}]
    result = _order_briefs_by_opportunity(data, recs, best_opportunity_kw=None)
    assert result, "expected one entry per rec"
    for item in result:
        assert len(item) == 4, f"expected 4-tuple, got {item!r}"
        idx, pattern, kw, rank = item
        assert isinstance(idx, int)
        assert isinstance(pattern, str)  # NOT a nested tuple


def test_exec_summary_survives_degraded_input_with_empty_content_angle():
    """Degraded run (empty keyword_profiles + empty Content_Angle) must not crash."""
    data = {
        "strategic_recommendations": [{"Pattern_Name": "Reactivity", "Content_Angle": ""}],
        "keyword_profiles": {},
        "keyword_feasibility": [],
    }
    lines = _render_executive_summary(
        data, best_opportunity_kw=None, best_opportunity_reason="feasibility data is missing."
    )
    text = "\n".join(lines)
    assert "Write first:" in text  # falls back to the pattern name, no crash
    assert "will be added by RC.8" not in text


def test_exec_summary_no_briefs_states_it():
    """With no strategic recs, RC.1.2 says so rather than crashing or printing a stub."""
    data = {"strategic_recommendations": [], "keyword_profiles": {}, "keyword_feasibility": []}
    text = "\n".join(_render_executive_summary(data, None, "feasibility data is missing."))
    assert "No content briefs available" in text
