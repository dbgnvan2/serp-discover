"""D5 / AV.5 — Own-Brand AI Visibility Monitor extensions.

Spec: discover-spec.md#D5. Plan: d2_d5_implementation_plan.md (AV.5).
AV.5.1 raw_answer retention (gated, capped); AV.5.2 own-brand negative-sentiment
alert (gated on sentiment.enabled). The C1 export sub-item was already shipped
(ai_visibility_export.py) and is not re-tested here.
"""
import sqlite3

import answer_sentiment as sm
import probe_ai_visibility as pav


def _probe_row(answer_text="full answer text about Living Systems", **over):
    row = {
        "run_ts": "20260725_0900", "engine": "openai", "model": "gpt-4o",
        "question": "who offers family systems therapy?", "mentioned": 1, "cited": 0,
        "competitors_cited": [], "answer_excerpt": answer_text[:400],
        "persona": "seeker", "source": "profile", "answer_text": answer_text,
    }
    row.update(over)
    return row


def _read_raw(db):
    with sqlite3.connect(db) as conn:
        return [r[0] for r in conn.execute(f"SELECT raw_answer FROM {pav.PROBE_TABLE}")]


# --- AV.5.1 — raw_answer retention -------------------------------------------

def test_av5_1_migration_adds_raw_answer_column(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.init_probe_table(db)
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({pav.PROBE_TABLE})")]
    assert "raw_answer" in cols


def test_av5_1_old_db_migrates_in_place(tmp_path):
    """P8 — a pre-D5 DB (no raw_answer column) migrates on first init, old rows NULL."""
    db = str(tmp_path / "serp_data.db")
    with sqlite3.connect(db) as conn:
        conn.execute(f"""CREATE TABLE {pav.PROBE_TABLE} (
            run_ts TEXT, engine TEXT, model TEXT, question TEXT, mentioned INTEGER,
            cited INTEGER, competitor_domains_json TEXT, answer_excerpt TEXT,
            persona TEXT, source TEXT)""")
        conn.execute(f"INSERT INTO {pav.PROBE_TABLE} (run_ts, engine) VALUES ('old','openai')")
    pav.init_probe_table(db)                       # must ALTER-add raw_answer
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({pav.PROBE_TABLE})")]
        assert "raw_answer" in cols
        assert conn.execute(
            f"SELECT raw_answer FROM {pav.PROBE_TABLE} WHERE run_ts='old'").fetchone()[0] is None


def test_av5_1_store_off_by_default_leaves_null(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row()])        # default store_raw_answer=False
    assert _read_raw(db) == [None]


def test_av5_1_store_on_persists_full_answer(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row(answer_text="a much longer full answer")],
                        store_raw_answer=True)
    assert _read_raw(db) == ["a much longer full answer"]


def test_av5_1_cap_enforced_with_truncation_marker(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row(answer_text="x" * 5000)],
                        store_raw_answer=True, raw_answer_max_chars=100)
    stored = _read_raw(db)[0]
    assert len(stored) == 100                 # hard cap incl. the marker
    assert stored.startswith("x")
    assert stored.endswith("[truncated]")     # P9: clip is signalled, not silent


def test_av5_1_short_answer_not_marked(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row(answer_text="brief")],
                        store_raw_answer=True, raw_answer_max_chars=100)
    assert _read_raw(db) == ["brief"]         # under cap → verbatim, no marker


def test_av5_1_malformed_cap_falls_back_no_crash(tmp_path):
    """P2 — a non-numeric raw_answer_max_chars must not crash persistence (which
    runs after the paid probes); it falls back to the default."""
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row(answer_text="short answer")],
                        store_raw_answer=True, raw_answer_max_chars="not-a-number")
    assert _read_raw(db) == ["short answer"]   # coerced to default, stored, no crash


def test_av5_1_excerpt_still_capped_at_400(tmp_path):
    db = str(tmp_path / "serp_data.db")
    pav.save_probe_rows(db, [_probe_row(answer_text="y" * 1000, answer_excerpt="y" * 1000)],
                        store_raw_answer=True)
    with sqlite3.connect(db) as conn:
        excerpt = conn.execute(f"SELECT answer_excerpt FROM {pav.PROBE_TABLE}").fetchone()[0]
    assert len(excerpt) == 400


# --- AV.5.2 — own-brand negative-sentiment alert ------------------------------

def _sent_row(brand, polarity, engine="openai", neg=None, pos=None):
    return {"brand": brand, "polarity": polarity, "engine": engine,
            "positive_aspects": pos or [], "negative_aspects": neg or []}


def test_av5_2_alert_fires_on_client_negative():
    rows = [
        _sent_row("Living Systems", "negative", neg=["dismissive", "long waitlist"]),
        _sent_row("Living Systems", "positive", pos=["warm"]),
        _sent_row("Rival Co", "negative", neg=["expensive"]),   # competitor — ignored
    ]
    out = "\n".join(sm.render_negative_sentiment_alert(rows, True, "Living Systems"))
    assert "Negative sentiment alert" in out
    assert "1 of 2 answer(s)" in out          # 1 negative of 2 client answers
    assert "dismissive" in out and "long waitlist" in out
    assert "Rival Co" not in out              # competitor negatives excluded


def test_av5_2_no_alert_when_no_client_negative():
    rows = [_sent_row("Living Systems", "positive"), _sent_row("Living Systems", "neutral")]
    assert sm.render_negative_sentiment_alert(rows, True, "Living Systems") == []


def test_av5_2_no_alert_when_disabled():
    """Gate: sentiment OFF → no alert, even if negative rows exist (never fabricate)."""
    rows = [_sent_row("Living Systems", "negative", neg=["bad"])]
    assert sm.render_negative_sentiment_alert(rows, False, "Living Systems") == []


def test_av5_2_no_alert_without_client_brand():
    rows = [_sent_row("Living Systems", "negative", neg=["bad"])]
    assert sm.render_negative_sentiment_alert(rows, True, "") == []
