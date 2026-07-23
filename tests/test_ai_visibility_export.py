"""Tests for ai_visibility_export.py — the AV-EXPORT sub-item (serp-compete C1 dep).

Spec: discover AV-EXPORT. Verifies AV-EXPORT.1–4:
  .1 serializes brand_mentions + ai_citations for the latest run_ts, schema-valid.
  .2 absent/empty AI-visibility tables → data_available:false, clean, no table creation.
  .3 export reuses stored rows only — no network I/O.
  .4 is_client / brand attribution byte-match the source tables (no re-detection).
"""
import json
import os
import socket
import sqlite3

import jsonschema
import pytest

import ai_visibility_export as ave
from ai_visibility_export import (
    build_ai_visibility_export, write_ai_visibility_export,
)
from brand_mentions import save_brand_mentions, BRAND_MENTIONS_TABLE
from citation_table import save_citations, CITATIONS_TABLE

_SCHEMA = json.load(open(os.path.join(os.path.dirname(ave.__file__),
                                      "ai_visibility_export_schema.json")))


def _seed(db_path, run_ts="2026-07-22T10:00:00+00:00"):
    """Insert a realistic two-engine fixture via the REAL save functions."""
    save_brand_mentions(db_path, run_ts, "gemini", {
        "questions_total": 4,
        "rows": [
            {"brand": "Living Systems", "mention_count": 3, "is_client": True, "source": "gazetteer"},
            {"brand": "Theravive", "mention_count": 2, "is_client": False, "source": "gazetteer"},
        ],
    })
    save_brand_mentions(db_path, run_ts, "openai", {
        "questions_total": 4,
        "rows": [
            {"brand": "Psychology Today", "mention_count": 5, "is_client": False, "source": "gazetteer"},
        ],
    })
    save_citations(db_path, run_ts, "gemini", [
        {"url": "https://livingsystems.ca/couples?utm_source=gemini", "domain": "livingsystems.ca",
         "category": "practitioner", "brand": "Living Systems", "is_client": True, "cite_count": 2},
        {"url": "https://theravive.com/x", "domain": "theravive.com",
         "category": "directory", "brand": None, "is_client": False, "cite_count": 1},
    ])
    return run_ts


# ── AV-EXPORT.1 ───────────────────────────────────────────────────────────────

def test_avexport_1_shape_and_schema(tmp_path):
    db = str(tmp_path / "serp_data.db")
    run_ts = _seed(db)
    export = build_ai_visibility_export(db, client_name="Living Systems Counselling")

    assert export is not None
    jsonschema.validate(instance=export, schema=_SCHEMA)  # schema-valid
    assert export["data_available"] is True
    assert export["source_run_ts"] == run_ts
    assert export["engines"] == ["gemini", "openai"]
    assert len(export["brand_mentions"]) == 3
    assert len(export["ai_citations"]) == 2
    # round-trip through the writer re-validates on reload
    path = write_ai_visibility_export(export, out_dir=str(tmp_path / "output"),
                                      client_slug="living_systems")
    assert os.path.exists(path)
    jsonschema.validate(instance=json.load(open(path)), schema=_SCHEMA)


# ── AV-EXPORT.2 ───────────────────────────────────────────────────────────────

def test_avexport_2_absent_db_file_data_unavailable(tmp_path):
    export = build_ai_visibility_export(str(tmp_path / "missing.db"),
                                        client_name="LSC")
    assert export is not None
    jsonschema.validate(instance=export, schema=_SCHEMA)
    assert export["data_available"] is False
    assert export["source_run_ts"] is None
    assert export["brand_mentions"] == [] and export["ai_citations"] == []


def test_avexport_2_present_db_no_av_tables_no_creation(tmp_path):
    db = str(tmp_path / "serp_data.db")
    with sqlite3.connect(db) as conn:  # DB exists but only an unrelated table
        conn.execute("CREATE TABLE runs (id INTEGER)")
        conn.commit()
    export = build_ai_visibility_export(db)
    assert export["data_available"] is False
    # a pure reader must NOT create the AI-visibility tables as a side effect
    with sqlite3.connect(db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert BRAND_MENTIONS_TABLE not in names
    assert CITATIONS_TABLE not in names


def test_avexport_2_run_ts_present_but_no_rows(tmp_path):
    """A caller-supplied run with no mentions/citations → honest empty, ts retained."""
    db = str(tmp_path / "serp_data.db")
    _seed(db, run_ts="2026-07-01T00:00:00+00:00")
    export = build_ai_visibility_export(db, run_ts="2099-01-01T00:00:00+00:00")
    assert export["data_available"] is False
    assert export["source_run_ts"] == "2099-01-01T00:00:00+00:00"


# ── AV-EXPORT.3 ───────────────────────────────────────────────────────────────

def test_avexport_3_no_network_io(tmp_path, monkeypatch):
    db = str(tmp_path / "serp_data.db")
    _seed(db)

    def _boom(*a, **k):  # any socket construction during the build fails the test
        raise AssertionError("export attempted network I/O")

    monkeypatch.setattr(socket, "socket", _boom)
    export = build_ai_visibility_export(db)  # pure sqlite read — must succeed offline
    assert export["data_available"] is True
    assert len(export["brand_mentions"]) == 3


# ── AV-EXPORT.4 ───────────────────────────────────────────────────────────────

def test_avexport_4_is_client_and_brand_parity(tmp_path):
    db = str(tmp_path / "serp_data.db")
    run_ts = _seed(db)
    export = build_ai_visibility_export(db)

    # is_client bools must equal the stored INTEGER flags, not be re-derived.
    with sqlite3.connect(db) as conn:
        bm = {b: bool(ic) for b, ic in conn.execute(
            f"SELECT brand, is_client FROM {BRAND_MENTIONS_TABLE} WHERE run_ts=?",
            (run_ts,))}
        cites = {u: (br, bool(ic)) for u, br, ic in conn.execute(
            f"SELECT url, brand, is_client FROM {CITATIONS_TABLE} WHERE run_ts=?",
            (run_ts,))}
    for row in export["brand_mentions"]:
        assert row["is_client"] == bm[row["brand"]]
    for row in export["ai_citations"]:
        stored_brand, stored_is_client = cites[row["url"]]
        assert row["is_client"] == stored_is_client
        assert row["brand"] == stored_brand  # NULL stays null — never fabricated
    # the theravive citation had a NULL brand
    theravive = next(r for r in export["ai_citations"] if r["domain"] == "theravive.com")
    assert theravive["brand"] is None


# ── contract & behaviour guards ──────────────────────────────────────────────

def test_avexport_table_name_parity_with_source():
    """The pinned table names must not drift from the source-of-truth constants."""
    assert ave._BRAND_MENTIONS_TABLE == BRAND_MENTIONS_TABLE
    assert ave._CITATIONS_TABLE == CITATIONS_TABLE


def test_avexport_latest_run_ts_selected(tmp_path):
    db = str(tmp_path / "serp_data.db")
    _seed(db, run_ts="2026-06-01T00:00:00+00:00")   # older
    _seed(db, run_ts="2026-07-22T10:00:00+00:00")   # newer
    export = build_ai_visibility_export(db)
    assert export["source_run_ts"] == "2026-07-22T10:00:00+00:00"
    # only the newest run's rows are exported (not both runs merged)
    assert len(export["brand_mentions"]) == 3


def test_avexport_write_creates_missing_out_dir(tmp_path):
    db = str(tmp_path / "serp_data.db")
    _seed(db)
    export = build_ai_visibility_export(db)
    out_dir = str(tmp_path / "nested" / "output")  # does not exist yet
    path = write_ai_visibility_export(export, out_dir=out_dir, client_slug="living_systems")
    assert os.path.exists(path)
    assert "ai_visibility_export_living_systems_" in os.path.basename(path)


def test_avexport_read_columns_exist_in_live_tables(tmp_path):
    """Column contract (P19): every column the export reads exists in the real
    table — catches a source column rename/removal directly, not just the name."""
    db = str(tmp_path / "serp_data.db")
    _seed(db)
    reads = {
        BRAND_MENTIONS_TABLE: {"engine", "brand", "mention_count",
                               "questions_total", "is_client", "source"},
        CITATIONS_TABLE: {"engine", "url", "domain", "category", "brand",
                          "is_client", "cite_count"},
    }
    with sqlite3.connect(db) as conn:
        for table, needed in reads.items():
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            assert needed <= cols, f"{table} missing {needed - cols}"


def test_avexport_empty_stub_filename_sorts_before_real(tmp_path):
    """Finding 1: a data_available:false stub must never shadow a real export by a
    naive filename sort — its token sorts before any year-prefixed timestamp."""
    out = str(tmp_path / "o")
    empty = write_ai_visibility_export(
        build_ai_visibility_export(str(tmp_path / "missing.db")),
        out_dir=out, client_slug="lsc")
    db = str(tmp_path / "serp_data.db")
    _seed(db)
    real = write_ai_visibility_export(
        build_ai_visibility_export(db), out_dir=out, client_slug="lsc")
    assert os.path.basename(empty) < os.path.basename(real)
    # a consumer taking the lexically-greatest filename gets the REAL export
    assert max(os.path.basename(empty), os.path.basename(real)) == os.path.basename(real)


# ── main() hook guard (P15: an export failure must never abort a paid run) ────

def test_hook_guard_never_aborts_run(monkeypatch):
    import probe_ai_visibility as pav
    import ai_visibility_export

    def _boom(*a, **k):
        raise RuntimeError("export blew up")

    monkeypatch.setattr(ai_visibility_export, "export_latest", _boom)
    # the guard swallows the failure and returns None instead of propagating
    assert pav._safe_write_av_export("x.db", "output", "slug", None, None) is None


def test_hook_guard_success_returns_path(tmp_path):
    import probe_ai_visibility as pav
    db = str(tmp_path / "serp_data.db")
    _seed(db)
    path = pav._safe_write_av_export(db, str(tmp_path / "out"), "living_systems", "LSC", None)
    assert path and os.path.exists(path)
    jsonschema.validate(instance=json.load(open(path)), schema=_SCHEMA)
