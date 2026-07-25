"""D3 / AV.3 — Demand vs Clicks snapshot.

Spec: discover-spec.md#D3. Plan: d2_d5_implementation_plan.md (AV.3).
Snapshot only (trend deferred, D-D3). Reads D1 AIO coverage + gsc_cache clicks,
degrading honestly to "not connected" and never crashing on an absent table (P2).
"""
import sqlite3

from demand_dashboard import compute_dashboard, render_dashboard_section

CFG = {}   # aio_exposure uses its documented defaults (multiplier 0.60, default curve)


def _profiles():
    return {
        "anxiety therapy": {"has_ai_overview": True, "client_rank": 1,
                            "client_aio_cited": False, "aio_top_sources": []},
        "family systems": {"has_ai_overview": False, "client_rank": 3,
                           "client_aio_cited": False, "aio_top_sources": []},
    }


def _make_gsc_cache(db, rows):
    with sqlite3.connect(db) as conn:
        conn.execute('''CREATE TABLE gsc_cache (
            query TEXT, start_date TEXT, end_date TEXT, clicks INTEGER,
            impressions INTEGER, ctr REAL, position REAL, found INTEGER, fetched_at TEXT)''')
        conn.executemany(
            "INSERT INTO gsc_cache (query, clicks, impressions, found, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()


def test_no_db_not_connected():
    dash = compute_dashboard(_profiles(), CFG, db_path=None)
    assert dash["gsc_connected"] is False
    assert dash["aio_coverage_pct"] == 50.0          # 1 of 2 keywords shows an AIO
    body = "\n".join(render_dashboard_section(dash))
    assert "## 5f. Demand vs Clicks" in body
    assert "not connected" in body.lower()
    assert "Snapshot only" in body                   # deferral documented, not silent


def test_missing_gsc_table_no_crash(tmp_path):
    """P2 — a db without a gsc_cache table (GSC never run) degrades, never raises."""
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()
    dash = compute_dashboard(_profiles(), CFG, db_path=db)
    assert dash["gsc_connected"] is False


def test_connected_traffic_at_risk(tmp_path):
    db = str(tmp_path / "serp_data.db")
    _make_gsc_cache(db, [("anxiety therapy", 100, 1000, 1, "2026-07-25T00:00"),
                         ("family systems", 50, 500, 1, "2026-07-25T00:00")])
    dash = compute_dashboard(_profiles(), CFG, db_path=db)
    assert dash["gsc_connected"] is True
    assert dash["total_clicks"] == 150 and dash["total_impressions"] == 1500
    # anxiety therapy: AIO, not cited, est_ctr_loss 0.168 → 1000 × 0.168 = 168 at risk
    assert dash["est_traffic_at_risk"] == 168.0
    assert dash["keywords_at_risk"][0]["keyword"] == "anxiety therapy"
    body = "\n".join(render_dashboard_section(dash))
    assert "traffic at risk" in body.lower()


def test_case_insensitive_join(tmp_path):
    """gsc_cache.query is lower-cased; raw profile keys must still match."""
    db = str(tmp_path / "serp_data.db")
    _make_gsc_cache(db, [("anxiety therapy", 10, 100, 1, "t")])
    profiles = {"Anxiety Therapy": {"has_ai_overview": True, "client_rank": 2,
                                    "client_aio_cited": False, "aio_top_sources": []}}
    dash = compute_dashboard(profiles, CFG, db_path=db)
    assert dash["matched_query_count"] == 1


def test_cited_keyword_excluded_from_at_risk_total(tmp_path):
    """The est_traffic_at_risk TOTAL must be scoped to not-cited (matching the label
    + docs), not just the list — a cited keyword's halved loss must not inflate it."""
    db = str(tmp_path / "serp_data.db")
    _make_gsc_cache(db, [("cited kw", 100, 1000, 1, "t")])
    profiles = {"cited kw": {"has_ai_overview": True, "client_rank": 1,
                             "client_aio_cited": True, "aio_top_sources": []}}
    dash = compute_dashboard(profiles, CFG, db_path=db)
    assert dash["keywords_at_risk"] == []            # already cited → not "at risk"
    assert dash["est_traffic_at_risk"] == 0.0        # and excluded from the total


def test_latest_row_wins_dirty_state(tmp_path):
    """P8 — two gsc_cache rows for one query (an old + a newer fetch): the newer
    clicks/impressions win (SQLite single-MAX bare-column rule)."""
    db = str(tmp_path / "serp_data.db")
    _make_gsc_cache(db, [("anxiety therapy", 10, 100, 1, "2026-07-01T00:00"),
                         ("anxiety therapy", 999, 9990, 1, "2026-07-25T00:00")])
    profiles = {"anxiety therapy": {"has_ai_overview": True, "client_rank": 1,
                                    "client_aio_cited": False, "aio_top_sources": []}}
    dash = compute_dashboard(profiles, CFG, db_path=db)
    assert dash["total_clicks"] == 999 and dash["total_impressions"] == 9990


def test_corrupt_db_no_crash(tmp_path):
    """P2 — a corrupt / not-a-database file must degrade, not raise (would drop the
    whole market_analysis_*.md via serp_audit's swallowing try)."""
    db = tmp_path / "serp_data.db"
    db.write_bytes(b"this is not a sqlite database")
    dash = compute_dashboard(_profiles(), CFG, db_path=str(db))
    assert dash["gsc_connected"] is False            # degraded, no exception


def test_gsc_ran_but_no_matches(tmp_path):
    """Finding 4 — table present but no matching queries → 'GSC ran' wording, not
    'not connected' (don't tell the user to run something they already ran)."""
    db = str(tmp_path / "serp_data.db")
    _make_gsc_cache(db, [("unrelated query", 5, 50, 1, "t")])
    dash = compute_dashboard(_profiles(), CFG, db_path=db)
    assert dash["gsc_connected"] is False and dash["gsc_ran"] is True
    body = "\n".join(render_dashboard_section(dash))
    assert "GSC ran" in body and "not connected" not in body.lower()
