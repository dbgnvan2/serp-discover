"""D2 / AV.2 — Branded vs Non-Branded Demand (GSC).

Spec: discover-spec.md#D2. Plan: d2_d5_implementation_plan.md (AV.2).
Per-run grain (D-D2a). Classification + bands + divide-by-zero + dirty-state
reclassification (D2.1) + idempotent per-run persistence.
"""
import sqlite3

import gsc_demand as gd
from gsc_demand import (
    compute_demand, get_demand_trend, is_branded, render_demand_section,
    resolve_bands, run_ts_from_filename, save_demand,
)

PATTERNS_CFG = {"analysis_report": {"client_name_patterns": ["Living Systems"]}}


def _row(query, clicks=0, impressions=0, found=True):
    return {"query": query, "query_label": "A", "clicks": clicks,
            "impressions": impressions, "ctr": 0.0, "position": 5.0, "found": found}


# --- classification -----------------------------------------------------------

def test_is_branded_substring_case_insensitive():
    assert is_branded("living systems counselling", ["Living Systems"])
    assert is_branded("LIVING SYSTEMS north van", ["Living Systems"])
    assert not is_branded("couples therapy vancouver", ["Living Systems"])
    assert is_branded("livingsystems near me", ["livingsystems"])   # single-word brand
    assert not is_branded("", ["Living Systems"])


def test_is_branded_negative_override():
    # a generic phrase that contains the brand token but isn't name-seeking
    assert not is_branded("systems thinking course", ["Systems"],
                          negatives=["systems thinking"])
    assert is_branded("living systems", ["Systems"], negatives=["systems thinking"])


def test_classify_only_found_rows():
    rows = [_row("living systems", found=True), _row("living systems", found=False)]
    _, _score = compute_demand(rows, PATTERNS_CFG)
    assert rows[0]["is_branded"] is True
    assert rows[1]["is_branded"] is False       # no GSC data → not counted branded


# --- rollup + bands -----------------------------------------------------------

def test_compute_demand_share_and_band_top():
    rows = [_row("living systems help", clicks=30, impressions=100),
            _row("couples therapy", clicks=70, impressions=900)]
    _, score = compute_demand(rows, PATTERNS_CFG)
    assert score["branded_clicks"] == 30 and score["nonbranded_clicks"] == 70
    assert score["branded_click_share"] == 0.3
    assert score["benchmark_band"] == "top"        # >= 0.10
    assert score["matched_patterns"] == ["Living Systems"]
    assert score["branded_query_count"] == 1 and score["tracked_query_count"] == 2


def test_bands_below_avg_and_avg():
    below = compute_demand([_row("living systems", clicks=1),
                            _row("therapy", clicks=99)], PATTERNS_CFG)[1]
    assert below["branded_click_share"] == 0.01 and below["benchmark_band"] == "below_avg"
    avg = compute_demand([_row("living systems", clicks=5),
                          _row("therapy", clicks=95)], PATTERNS_CFG)[1]
    assert avg["benchmark_band"] == "avg"          # 0.05 in [0.024, 0.10)


def test_no_clicks_is_not_a_verdict():
    """P2 — no clicks → data_available False, band None (not a fake 'below average')."""
    _, score = compute_demand([_row("living systems", clicks=0),
                               _row("therapy", clicks=0)], PATTERNS_CFG)
    assert score["branded_click_share"] == 0.0     # no divide-by-zero
    assert score["data_available"] is False
    assert score["benchmark_band"] is None


def test_av2_render_insufficient_when_no_clicks():
    _, score = compute_demand([_row("living systems", clicks=0, impressions=40)], PATTERNS_CFG)
    body = "\n".join(render_demand_section(score))
    assert "Insufficient GSC data" in body
    assert "below average" not in body.lower()     # no confident negative on no data


def test_av2_insufficient_data_not_persisted(tmp_path):
    """P2 — a no-clicks run must not inject a spurious 0% point into the trend, but
    the per-query rows still persist for audit."""
    db = str(tmp_path / "serp_data.db")
    rows = [_row("living systems", clicks=0, impressions=50)]
    _, score = compute_demand(rows, PATTERNS_CFG)
    save_demand(db, "prop", "20260101_0000", rows, score)
    assert get_demand_trend(db, "prop") == []      # no score point
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM gsc_demand_run WHERE run_ts=?",
                         ("20260101_0000",)).fetchone()[0]
    assert n == 1                                   # run rows kept (audit)


def test_is_branded_word_boundary():
    assert not is_branded("bowenville real estate", ["Bowen"])   # no sub-word match
    assert is_branded("bowen family therapy", ["Bowen"])         # matches on boundary


def test_av2_generic_brand_collision_and_negative_lever():
    """P7 — a brand that is also a generic phrase ('Living Systems') mis-counts an
    un-negated generic query as branded; gsc_demand.negative_terms is the lever."""
    cfg = {"analysis_report": {"client_name_patterns": ["Living Systems"]}}
    _, score = compute_demand([_row("living systems theory", clicks=40),
                               _row("couples therapy", clicks=60)], cfg)
    assert score["branded_clicks"] == 40           # generic query (mis)counted branded
    cfg_neg = {**cfg, "gsc_demand": {"negative_terms": ["living systems theory"]}}
    _, score2 = compute_demand([_row("living systems theory", clicks=40),
                                _row("couples therapy", clicks=60)], cfg_neg)
    assert score2["branded_clicks"] == 0           # negative override excludes it


def test_resolve_bands_default_and_malformed():
    assert resolve_bands({"gsc_demand": {"bands": {"below_avg": 0.03, "top": 0.2}}}) \
        == {"below_avg": 0.03, "top": 0.2}
    assert resolve_bands({"gsc_demand": {"bands": {"below_avg": "x"}}}) == gd.DEFAULT_BANDS
    assert resolve_bands({"gsc_demand": {"bands": {"below_avg": 0.5, "top": 0.1}}}) \
        == gd.DEFAULT_BANDS                        # out of order → default


# --- D2.1 dirty-state: a client_name_patterns edit reclassifies ---------------

def test_d21_pattern_edit_reclassifies():
    rows_a = [_row("living systems help", clicks=30), _row("family therapy", clicks=70)]
    score_a = compute_demand(rows_a, {"analysis_report": {"client_name_patterns": ["Living Systems"]}})[1]
    assert score_a["branded_clicks"] == 30
    rows_b = [_row("living systems help", clicks=30), _row("family therapy", clicks=70)]
    score_b = compute_demand(rows_b, {"analysis_report": {"client_name_patterns": ["Family"]}})[1]
    assert score_b["branded_clicks"] == 70         # "family therapy" now branded


# --- persistence (idempotent per property+run_ts) -----------------------------

def test_save_idempotent_and_trend(tmp_path):
    db = str(tmp_path / "serp_data.db")
    rows1 = [_row("living systems", clicks=10), _row("therapy", clicks=90)]
    _, s1 = compute_demand(rows1, PATTERNS_CFG)
    save_demand(db, "prop", "20260101_0000", rows1, s1)
    # re-run same run_ts (e.g. patterns edited) — must REPLACE, not duplicate (P8/D2.1)
    rows2 = [_row("living systems", clicks=40), _row("therapy", clicks=60)]
    _, s2 = compute_demand(rows2, PATTERNS_CFG)
    save_demand(db, "prop", "20260101_0000", rows2, s2)
    with sqlite3.connect(db) as conn:
        n_run = conn.execute("SELECT COUNT(*) FROM gsc_demand_run WHERE run_ts=?",
                             ("20260101_0000",)).fetchone()[0]
        n_score = conn.execute("SELECT COUNT(*) FROM gsc_demand_score WHERE run_ts=?",
                               ("20260101_0000",)).fetchone()[0]
    assert n_run == 2 and n_score == 1             # 2 found rows, one score, no dup
    save_demand(db, "prop", "20260102_0000", rows2, s2)   # a second run
    trend = get_demand_trend(db, "prop")
    assert [t["run_ts"] for t in trend] == ["20260101_0000", "20260102_0000"]  # oldest→newest
    assert trend[0]["branded_click_share"] == s2["branded_click_share"]        # replaced value


# --- render + helpers ---------------------------------------------------------

def test_render_labels_reference_bands():
    _, score = compute_demand([_row("living systems", clicks=30),
                               _row("therapy", clicks=70)], PATTERNS_CFG)
    body = "\n".join(render_demand_section(score))
    assert "Branded vs Non-Branded Demand" in body
    assert "reference" in body.lower()             # bands framed as reference, not target
    assert "Living Systems" in body                # matched pattern surfaced


def test_run_ts_from_filename():
    assert run_ts_from_filename("market_analysis_leila_20260725_0900.json") == "20260725_0900"
    assert run_ts_from_filename("no_stamp.json") is None
