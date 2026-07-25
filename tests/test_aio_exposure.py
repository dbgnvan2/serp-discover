"""Tests for AI Overview zero-click exposure (D1 / AV.1).

Spec:  discover-spec.md#D1
Plan:  d1_aio_exposure_plan.md
Module: aio_exposure.py

Acceptance criteria AV.1.1–AV.1.12 (report-copy AV.1.4b + section-present AV.1.11b
live in test_markdown_rendering.py). Scoring + adversarial + dirty-state tests are
written first per the P10 fix→test rule.
"""
import json

import aio_exposure
from aio_exposure import (
    build_aio_exposure_report,
    compute_aio_exposure,
    ctr_base,
    est_ctr_loss,
    get_aio_exposure_for_run,
    get_aio_exposure_trend,
    render_aio_exposure_section,
    resolve_exposure_config,
    run_ts_from_filename,
    save_aio_exposure,
)

# A hermetic config mirroring the config.yml aio_exposure block.
CFG = {
    "aio_exposure": {
        "aio_ctr_multiplier": 0.60,
        "citation_credit": 0.5,
        "history_runs": 5,
        "ctr_curve": {1: 0.28, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
                      6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.015},
    }
}


def _profile(has_ai_overview=False, client_rank=None, client_aio_cited=False,
             aio_top_sources=None):
    return {
        "has_ai_overview": has_ai_overview,
        "client_rank": client_rank,
        "client_aio_cited": client_aio_cited,
        "aio_top_sources": aio_top_sources or [],
    }


# --- AV.1.1 / AV.1.2 — the scoring core (highest-impact, tested first) --------

def test_av1_1_client_cited_reduces_loss():
    """AV.1.1 — AIO lists the client → client_cited=1, loss ×(1-citation_credit)."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=1,
                               client_aio_cited=True,
                               aio_top_sources=[("livingsystems.ca", 2)])}
    rows, _ = compute_aio_exposure(profiles, CFG)
    row = rows[0]
    assert row["client_cited"] == 1
    # full loss for pos 1 would be 0.28*0.60 = 0.168; cited halves it → 0.084
    assert row["est_ctr_loss"] == 0.084


def test_av1_2_not_cited_full_multiplier():
    """AV.1.2 — AIO not listing the client → client_cited=0, full multiplier."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=1,
                               client_aio_cited=False,
                               aio_top_sources=[("competitor.com", 3)])}
    rows, _ = compute_aio_exposure(profiles, CFG)
    row = rows[0]
    assert row["client_cited"] == 0
    assert row["est_ctr_loss"] == 0.168  # 0.28 * 0.60, no citation credit


def test_av1_2b_no_aio_zero_loss():
    """No AIO → est_ctr_loss is 0 regardless of rank."""
    profiles = {"kw": _profile(has_ai_overview=False, client_rank=1)}
    rows, _ = compute_aio_exposure(profiles, CFG)
    assert rows[0]["aio_present"] == 0
    assert rows[0]["est_ctr_loss"] == 0.0


# --- AV.1.3 — rollup ----------------------------------------------------------

def test_av1_3_coverage_pct_rollup():
    """AV.1.3 — aio_coverage_pct = AIO-present / total; cited_share over AIO kws."""
    profiles = {
        "a": _profile(has_ai_overview=True, client_rank=2, client_aio_cited=True),
        "b": _profile(has_ai_overview=True, client_rank=3, client_aio_cited=False),
        "c": _profile(has_ai_overview=False, client_rank=5),
        "d": _profile(has_ai_overview=False),
    }
    _, rollup = compute_aio_exposure(profiles, CFG)
    assert rollup["total_keywords"] == 4
    assert rollup["aio_present_count"] == 2
    assert rollup["aio_coverage_pct"] == 50.0            # 2 of 4
    assert rollup["client_cited_count"] == 1
    assert rollup["cited_share"] == 50.0                  # 1 of 2 AIO kws


def test_av1_3b_empty_profiles_no_divzero():
    rows, rollup = compute_aio_exposure({}, CFG)
    assert rows == []
    assert rollup["aio_coverage_pct"] == 0.0
    assert rollup["cited_share"] == 0.0


# --- AV.1.4 — constants come from config, not literals ------------------------

def test_av1_4_constants_from_config():
    """AV.1.4 — changing config changes the score (no hardcoded 0.60/0.5)."""
    base = {"kw": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=False)}
    default_row = compute_aio_exposure(base, CFG)[0][0]

    hot = {"aio_exposure": {**CFG["aio_exposure"], "aio_ctr_multiplier": 0.90}}
    hot_row = compute_aio_exposure(base, hot)[0][0]
    assert hot_row["est_ctr_loss"] == 0.252              # 0.28 * 0.90
    assert hot_row["est_ctr_loss"] != default_row["est_ctr_loss"]

    # citation_credit is also config-driven
    cited = {"kw": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=True)}
    stingy = {"aio_exposure": {**CFG["aio_exposure"], "citation_credit": 0.25}}
    row = compute_aio_exposure(cited, stingy)[0][0]
    assert row["est_ctr_loss"] == round(0.168 * 0.75, 4)  # 0.126


def test_av1_4b_malformed_config_falls_back_with_warning(caplog):
    """Malformed config → documented defaults + warning (mirrors aivi)."""
    import logging
    with caplog.at_level(logging.WARNING):
        resolved = resolve_exposure_config({"aio_exposure": {
            "aio_ctr_multiplier": "not-a-number",
            "citation_credit": 5,          # out of [0,1]
            "ctr_curve": "nope",
        }})
    assert resolved["aio_ctr_multiplier"] == aio_exposure.DEFAULT_AIO_CTR_MULTIPLIER
    assert resolved["citation_credit"] == aio_exposure.DEFAULT_CITATION_CREDIT
    assert resolved["ctr_curve"] == aio_exposure.DEFAULT_CTR_CURVE
    assert "aio_exposure" in caplog.text


# --- AV.1.5 / AV.1.6 — edge cases --------------------------------------------

def test_av1_5_aio_present_empty_citations():
    """AV.1.5 — AIO present but no citations → aio_present=1, cited_urls=[], full loss."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=2,
                               client_aio_cited=False, aio_top_sources=[])}
    rows, _ = compute_aio_exposure(profiles, CFG)
    row = rows[0]
    assert row["aio_present"] == 1
    assert json.loads(row["cited_urls_json"]) == []
    assert row["client_cited"] == 0
    assert row["est_ctr_loss"] == round(0.15 * 0.60, 4)   # pos 2, full multiplier


def test_av1_6_unranked_but_cited():
    """AV.1.6 — client unranked but cited → organic_position NULL, cited=1, loss 0."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=None,
                               client_aio_cited=True,
                               aio_top_sources=[("livingsystems.ca", 1)])}
    rows, _ = compute_aio_exposure(profiles, CFG)
    row = rows[0]
    assert row["organic_position"] is None
    assert row["client_cited"] == 1
    assert row["est_ctr_loss"] == 0.0        # ctr_base(None) = 0 (D-4)


def test_ctr_base_off_curve_and_none():
    curve = CFG["aio_exposure"]["ctr_curve"]
    assert ctr_base(None, curve) == 0.0
    assert ctr_base(99, curve) == 0.0        # beyond curve tail
    assert ctr_base(1, curve) == 0.28


# --- AV.1.7 — registrable-domain matching (inherited via client_aio_cited) ----

def test_av1_7_client_cited_follows_upstream_flag_not_url_exact():
    """AV.1.7 — client_cited reflects the upstream registrable-domain flag; cited
    domains are stored as domains (not exact URLs), so a subdomain form still
    attributes to the client without URL-exact matching."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=4,
                               client_aio_cited=True,
                               aio_top_sources=[("blog.livingsystems.ca", 1)])}
    rows, _ = compute_aio_exposure(profiles, CFG)
    row = rows[0]
    assert row["client_cited"] == 1
    assert json.loads(row["cited_urls_json"]) == ["blog.livingsystems.ca"]


# --- AV.1.8 — adversarial: cited scores LOWER risk; queue orders correctly -----

def test_av1_8_adversarial_cited_scores_lower_and_queue_order():
    """AV.1.8 (P7) — a client-cited keyword must score LOWER est_ctr_loss than an
    otherwise-identical non-cited one, and the at-risk queue (render order) must
    rank the non-cited keyword ABOVE the cited one."""
    profiles = {
        "cited_kw": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=True),
        "exposed_kw": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=False),
    }
    rows, rollup = compute_aio_exposure(profiles, CFG)
    by_kw = {r["keyword"]: r for r in rows}
    # A cited page is LESS at risk than an identical non-cited page.
    assert by_kw["cited_kw"]["est_ctr_loss"] < by_kw["exposed_kw"]["est_ctr_loss"]

    lines = render_aio_exposure_section(rows, rollup)
    body = "\n".join(lines)
    # non-cited (exposed) keyword appears before the cited one in the table
    assert body.index("exposed_kw") < body.index("cited_kw")


# --- AV.1.9 — dirty-state trend (P8) -----------------------------------------

def test_av1_9_dirty_state_trend(tmp_path):
    """AV.1.9 (P8) — a prior run persisted; a second run must not contaminate the
    current-run fetch, and the trend must include both runs oldest→newest."""
    db = str(tmp_path / "serp_data.db")
    prior = [{"keyword": "old", "source": "google", "aio_present": 1,
              "client_cited": 0, "cited_urls_json": "[]", "organic_position": 1,
              "est_ctr_loss": 0.168, "weights_json": "{}"}]
    save_aio_exposure(db, "20260101_0000", prior)

    profiles = {"new": _profile(has_ai_overview=True, client_rank=2, client_aio_cited=True)}
    lines = build_aio_exposure_report(profiles, CFG, db_path=db, run_ts="20260102_0000")

    current = get_aio_exposure_for_run(db, "20260102_0000")
    assert [r["keyword"] for r in current] == ["new"]     # only the new run's rows
    assert all(r["keyword"] != "old" for r in current)    # prior run not leaked

    trend = get_aio_exposure_trend(db, limit=5)
    assert [t["run_ts"] for t in trend] == ["20260101_0000", "20260102_0000"]  # oldest→newest
    assert "Δ prior run" in "\n".join(lines)              # delta rendered with ≥2 runs


# --- AV.1.10 — reproducibility ------------------------------------------------

def test_av1_10_reproducible():
    """AV.1.10 — identical snapshot + config → byte-identical rows + weights_json."""
    profiles = {
        "a": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=True),
        "b": _profile(has_ai_overview=True, client_rank=5, client_aio_cited=False),
    }
    rows1, roll1 = compute_aio_exposure(profiles, CFG)
    rows2, roll2 = compute_aio_exposure(profiles, CFG)
    assert rows1 == rows2
    assert roll1 == roll2
    # weights_json is a stable, sorted serialization
    assert rows1[0]["weights_json"] == rows2[0]["weights_json"]
    assert json.loads(rows1[0]["weights_json"])["aio_ctr_multiplier"] == 0.60


# --- AV.1.11 — wiring: build persists + renders the section -------------------

def test_av1_11_build_persists_and_renders(tmp_path):
    """AV.1.11 (P21) — build_aio_exposure_report with db+run_ts persists rows AND
    returns the rendered 5d section."""
    db = str(tmp_path / "serp_data.db")
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=1, client_aio_cited=False)}
    lines = build_aio_exposure_report(profiles, CFG, db_path=db, run_ts="20260103_0000")
    assert any("## 5d. AI Overview Exposure" in ln for ln in lines)
    persisted = get_aio_exposure_for_run(db, "20260103_0000")
    assert len(persisted) == 1
    assert persisted[0]["keyword"] == "kw"


def test_av1_11b_render_only_without_db():
    """Pure render path (no db/run_ts) still produces the section (test contract)."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=1)}
    lines = build_aio_exposure_report(profiles, CFG)
    assert any("## 5d. AI Overview Exposure" in ln for ln in lines)


def test_run_ts_from_filename():
    assert run_ts_from_filename("output/market_analysis_leila_20260704_2113.json") == "20260704_2113"
    assert run_ts_from_filename("no_timestamp_here.json") is None
    assert run_ts_from_filename(None) is None


# --- learning-qa follow-ups: idempotency, robustness, real argv path ---------

def test_av1_9b_save_is_idempotent_same_run_ts(tmp_path):
    """P8 — re-saving the SAME run_ts REPLACES prior rows. The market report is
    regenerated for the same run (primary write + post-feasibility regenerate),
    so a bare INSERT would accumulate duplicate keyword rows."""
    db = str(tmp_path / "serp_data.db")
    profiles = {"a": _profile(has_ai_overview=True, client_rank=1),
                "b": _profile(has_ai_overview=False)}
    rows, _ = compute_aio_exposure(profiles, CFG)
    save_aio_exposure(db, "20260101_0000", rows)
    save_aio_exposure(db, "20260101_0000", rows)      # regenerate same run
    fetched = get_aio_exposure_for_run(db, "20260101_0000")
    assert len(fetched) == 2                           # not 4
    assert sorted(r["keyword"] for r in fetched) == ["a", "b"]


def test_malformed_aio_top_sources_does_not_crash():
    """P2 — a malformed aio_top_sources element is skipped, not raised, so one bad
    keyword cannot abort the whole market-analysis report write."""
    profiles = {"kw": _profile(has_ai_overview=True, client_rank=1,
                               client_aio_cited=False,
                               aio_top_sources=["bare", ("dom", 2), {"x": 1}, ()])}
    rows, _ = compute_aio_exposure(profiles, CFG)      # must not raise
    assert json.loads(rows[0]["cited_urls_json"]) == ["bare", "dom"]


def test_history_runs_clamp():
    """Minor — history_runs is clamped to >=1 (a negative → SQLite LIMIT -1 =
    unbounded; non-numeric → default)."""
    from aio_exposure import _resolve_history_runs
    assert _resolve_history_runs({"history_runs": 3}) == 3
    assert _resolve_history_runs({"history_runs": -1}) == aio_exposure.DEFAULT_HISTORY_RUNS
    assert _resolve_history_runs({"history_runs": 0}) == aio_exposure.DEFAULT_HISTORY_RUNS
    assert _resolve_history_runs({"history_runs": "x"}) == aio_exposure.DEFAULT_HISTORY_RUNS
    assert _resolve_history_runs(None) == aio_exposure.DEFAULT_HISTORY_RUNS


def test_av1_11c_main_argv_persists(tmp_path, monkeypatch):
    """P21 — the REAL argv → main() → persistence path: run_ts is parsed from the
    --json filename and rows land in --db (covers the wiring, not just the func)."""
    import sys
    import generate_insight_report as gir
    jf = tmp_path / "market_analysis_test_20260724_0900.json"
    jf.write_text(json.dumps({"keyword_profiles": {
        "kw": {"has_ai_overview": True, "client_rank": 1, "client_aio_cited": False}}}))
    out = tmp_path / "report.md"
    db = tmp_path / "serp_data.db"
    monkeypatch.setattr(sys, "argv", ["generate_insight_report.py",
                                      "--json", str(jf), "--out", str(out), "--db", str(db)])
    gir.main()
    assert out.exists()
    rows = get_aio_exposure_for_run(str(db), "20260724_0900")
    assert [r["keyword"] for r in rows] == ["kw"]


# --- AV.1.12 — docs contract --------------------------------------------------

def test_av1_12_methodology_documents_aio_exposure():
    """AV.1.12 — methodology.md documents the AIO-exposure metric."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "methodology.md"), encoding="utf-8") as fh:
        text = fh.read().lower()
    assert "ai overview exposure" in text
    assert "est_ctr_loss" in text or "ctr loss" in text
