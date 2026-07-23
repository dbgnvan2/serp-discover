#!/usr/bin/env python3
"""ai_visibility_export.py — export AI-visibility outputs for serp-compete.

Spec: discover AV-EXPORT (the D5 export sub-item; serp-compete/compete-spec.md#C1
dependency — must land before Compete's AI Share-of-Voice feature).

Purpose:
    Serialize this repo's already-computed ``brand_mentions`` + ``ai_citations``
    rows for the latest probe run into a single, schema-validated JSON file that
    serp-compete consumes (it computes competitor *share* on top). Mirrors the
    existing ``handoff_writer.build_competitor_handoff`` → ``output/*.json``
    pattern so the two tools stay decoupled: Compete reads a versioned file, not
    this repo's SQLite.

Design (honours the "extend, don't rebuild" + "no fabricated data" rules):
    * **Pure reader.** It reads the rows the probe run already wrote — it never
      re-probes, re-detects, or re-computes ``is_client`` / brand attribution.
      The stored values (from ``probe_ai_visibility.run_report_enrichment``) are
      the authority; this module only serializes them.
    * **Absent-safe.** The five AI-visibility tables are created lazily and may
      not exist yet. When ``brand_mentions``/``ai_citations`` are missing or hold
      no rows, the export is written with ``data_available: false`` and empty
      arrays — never a crash, never a fabricated row (principle 3 /
      ``learnings.md`` P2).
    * **Lightweight.** Intentionally does NOT import ``citation_table`` /
      ``brand_mentions`` (which pull the entity classifier) — it only needs the
      table names + column order, which are pinned here and checked against the
      source constants by ``tests/test_ai_visibility_export.py`` so they can't
      silently drift.

Consumer selection contract (serp-compete C1): when several export files
co-exist in a directory, select the newest one whose ``data_available`` is true,
comparing the in-file ``source_run_ts`` — NOT the filename. As a safety net the
no-data stub is named ``..._00000000.json`` so it sorts *before* any real,
year-prefixed timestamp and can never shadow a real export by a naive filename
sort.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3

import jsonschema

try:
    from datetime import UTC as _UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _tz
    _UTC = _tz.utc

logger = logging.getLogger(__name__)

EXPORT_SCHEMA_VERSION = "1.0"

# Table names are the stable Y.7/Y.8 contract. Pinned here (not imported) to keep
# this reader free of the classifier import chain; a parity test in
# tests/test_ai_visibility_export.py asserts these equal the source constants
# (brand_mentions.BRAND_MENTIONS_TABLE / citation_table.CITATIONS_TABLE).
_BRAND_MENTIONS_TABLE = "brand_mentions"
_CITATIONS_TABLE = "ai_citations"

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "ai_visibility_export_schema.json")
_SCHEMA = None
if os.path.exists(_SCHEMA_PATH):
    with open(_SCHEMA_PATH) as _f:
        _SCHEMA = json.load(_f)


# ---------------------------------------------------------------------------
# Read helpers (no table creation — a pure reader must not mutate the DB)
# ---------------------------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _latest_run_ts(conn: sqlite3.Connection) -> str | None:
    """Newest ``run_ts`` across whichever AI-visibility tables exist, else None."""
    candidates: list[str] = []
    for table in (_BRAND_MENTIONS_TABLE, _CITATIONS_TABLE):
        if not _table_exists(conn, table):
            continue
        row = conn.execute(f"SELECT MAX(run_ts) FROM {table}").fetchone()
        if row and row[0]:
            candidates.append(row[0])
    return max(candidates) if candidates else None


def _read_brand_mentions(conn: sqlite3.Connection, run_ts: str) -> list[dict]:
    if not _table_exists(conn, _BRAND_MENTIONS_TABLE):
        return []
    rows = conn.execute(
        f"""SELECT engine, brand, mention_count, questions_total, is_client, source
            FROM {_BRAND_MENTIONS_TABLE}
            WHERE run_ts = ?
            ORDER BY engine ASC, mention_count DESC, brand ASC""",
        (run_ts,),
    ).fetchall()
    return [
        {
            "engine": engine,
            "brand": brand,
            "mention_count": int(mention_count or 0),
            "questions_total": int(questions_total or 0),
            "is_client": bool(is_client),
            "source": source,
        }
        for engine, brand, mention_count, questions_total, is_client, source in rows
    ]


def _read_ai_citations(conn: sqlite3.Connection, run_ts: str) -> list[dict]:
    if not _table_exists(conn, _CITATIONS_TABLE):
        return []
    rows = conn.execute(
        f"""SELECT engine, url, domain, category, brand, is_client, cite_count
            FROM {_CITATIONS_TABLE}
            WHERE run_ts = ?
            ORDER BY engine ASC, cite_count DESC, url ASC""",
        (run_ts,),
    ).fetchall()
    return [
        {
            "engine": engine,
            "url": url,
            "domain": domain,
            "category": category,
            "brand": brand,  # may be NULL → serialized as JSON null (never faked)
            "is_client": bool(is_client),
            "cite_count": int(cite_count or 0),
        }
        for engine, url, domain, category, brand, is_client, cite_count in rows
    ]


# ---------------------------------------------------------------------------
# Build + write
# ---------------------------------------------------------------------------

def _empty_export(client_name: str | None, source_run_ts: str | None = None) -> dict:
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "source_run_ts": source_run_ts,
        "client_name": client_name,
        "engines": [],
        "data_available": False,
        "brand_mentions": [],
        "ai_citations": [],
    }


def build_ai_visibility_export(db_path: str, run_ts: str | None = None,
                               client_name: str | None = None) -> dict | None:
    """Build the AI-visibility export dict from stored rows for one run.

    Reads ``brand_mentions`` + ``ai_citations`` for *run_ts* (the latest run if
    omitted). Returns a schema-valid dict; ``data_available`` is False (with empty
    arrays) when no rows exist. Returns None only on a schema-validation failure
    (a bug to fix — the writer then writes nothing), mirroring
    ``handoff_writer.build_competitor_handoff``.

    Pure reader: no probing, no re-detection, no table creation.
    """
    if not os.path.exists(db_path):
        export = _empty_export(client_name)
        return _validated(export)

    with sqlite3.connect(db_path) as conn:
        resolved_run_ts = run_ts or _latest_run_ts(conn)
        if resolved_run_ts is None:
            return _validated(_empty_export(client_name))
        brand_mentions = _read_brand_mentions(conn, resolved_run_ts)
        ai_citations = _read_ai_citations(conn, resolved_run_ts)

    if not brand_mentions and not ai_citations:
        # run_ts existed in a table but produced no mentions/citations, OR was a
        # caller-supplied run with none — honest empty, source_run_ts retained.
        return _validated(_empty_export(client_name, source_run_ts=resolved_run_ts))

    engines = sorted({r["engine"] for r in brand_mentions} |
                     {r["engine"] for r in ai_citations})
    export = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "source_run_ts": resolved_run_ts,
        "client_name": client_name,
        "engines": engines,
        "data_available": True,
        "brand_mentions": brand_mentions,
        "ai_citations": ai_citations,
    }
    return _validated(export)


def _validated(export: dict) -> dict | None:
    if _SCHEMA is None:
        return export
    try:
        jsonschema.validate(instance=export, schema=_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.error("AI-visibility export schema validation FAILED: %s", exc.message)
        return None
    return export


def _ts_token(source_run_ts: str | None) -> str:
    """Filename timestamp token from an ISO run_ts (digits).

    The no-data case returns ``"00000000"``, which sorts BEFORE any real
    timestamp (real run_ts start with a year, ``"2026…"``), so a stale
    ``data_available:false`` stub can never shadow a real export if a consumer
    naively picks the lexically-greatest filename. Consumers should instead
    select by the in-file ``source_run_ts`` / ``data_available`` (see module docs).
    A lone stub also self-overwrites (same filename) rather than accumulating.
    """
    if not source_run_ts:
        return "00000000"
    return re.sub(r"[^0-9]", "", source_run_ts)[:12] or "00000000"


def write_ai_visibility_export(export: dict | None, out_dir: str = "output",
                               client_slug: str = "client") -> str | None:
    """Write *export* to ``<out_dir>/ai_visibility_export_<slug>_<ts>.json``.

    Returns the path, or None when *export* is None (schema failure upstream).
    Creates *out_dir* if needed (mirrors where competitor_handoff_*.json lands).
    """
    if export is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    ts = _ts_token(export.get("source_run_ts"))
    fname = f"ai_visibility_export_{client_slug}_{ts}.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    return path


def export_latest(db_path: str, out_dir: str = "output", client_slug: str = "client",
                  client_name: str | None = None, run_ts: str | None = None) -> str | None:
    """Convenience: build the latest export and write it. Returns the path or None."""
    export = build_ai_visibility_export(db_path, run_ts=run_ts, client_name=client_name)
    return write_ai_visibility_export(export, out_dir=out_dir, client_slug=client_slug)
