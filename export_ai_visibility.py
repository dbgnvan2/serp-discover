#!/usr/bin/env python3
"""export_ai_visibility.py — CLI to export AI-visibility data for serp-compete.

Spec: discover AV-EXPORT (serp-compete/compete-spec.md#C1 dependency).

Reads the already-stored ``brand_mentions`` / ``ai_citations`` tables (no
re-probe, no cost) and writes ``output/ai_visibility_export_<slug>_<ts>.json``
for serp-compete to consume. Run any time after a probe run:

    python3 export_ai_visibility.py --out output

When no AI-visibility data exists yet, it writes a ``data_available: false`` stub
(so the downstream consumer degrades gracefully) and reports it.
"""
from __future__ import annotations

import argparse
import os
import sys

import db_connect
import process_config
from ai_visibility_export import (
    build_ai_visibility_export, write_ai_visibility_export)

DEFAULT_CLIENT_SLUG = "client"


def _load_config(config_path: str | None = None) -> dict:
    """config.yml, with this process's policies applied.

    This script read the config for the client slug alone and applied no
    policy, so the configured database path and lock wait never reached it
    (review chunk Y12). A missing or malformed config must not block the
    export, so the failure is reported and the defaults are reset.
    """
    config_path = process_config.config_path(config_path)
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as exc:
        print(f"AV export: could not read {config_path} ({exc}); using defaults.",
              file=sys.stderr)
        process_config.apply(None)
        return {}
    process_config.apply(config)
    return config


def _read_client_identity(config: dict) -> tuple[str, str | None]:
    """Return (client_slug, client_name) from a loaded config, with fallbacks.

    client_slug names the export file (matches ai_visibility.client_slug);
    client_name is informational in the payload — the authoritative client flag
    is the per-row ``is_client`` already stored in the tables.
    """
    av = config.get("ai_visibility", {}) or {}
    analysis = config.get("analysis_report", {}) or {}
    slug = str(av.get("client_slug", DEFAULT_CLIENT_SLUG)) or DEFAULT_CLIENT_SLUG
    name = analysis.get("client_name")
    return slug, name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export AI-visibility data (brand_mentions/ai_citations) for serp-compete.")
    parser.add_argument("--db", default=None,
                        help="SQLite database path (default: the configured "
                             "database.path)")
    parser.add_argument("--out", default="output", help="Output directory")
    parser.add_argument("--config", default=None, help="Config path (for client slug/name)")
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    # After the loader, so `database.path` is in force (review chunk Y12).
    db_path = args.db if args.db else db_connect.database_path()

    # Distinguish a missing DB (possible --db typo) from a genuinely empty one —
    # both yield an empty export, but only the latter is benign (P6).
    if not os.path.exists(db_path):
        print(f"AV export: ⚠️ database not found at '{db_path}'. Writing an empty "
              f"export; if this path is a typo, re-run with the correct --db.",
              file=sys.stderr)

    client_slug, client_name = _read_client_identity(config)
    export = build_ai_visibility_export(db_path, client_name=client_name)
    if export is None:
        print("AV export: schema validation failed — nothing written.", file=sys.stderr)
        return 1

    path = write_ai_visibility_export(export, out_dir=args.out, client_slug=client_slug)
    if export.get("data_available"):
        n_bm = len(export.get("brand_mentions", []))
        n_cit = len(export.get("ai_citations", []))
        print(f"AV export written: {path} "
              f"({n_bm} brand-mention rows, {n_cit} citation rows, "
              f"engines={export.get('engines')}).")
    else:
        print(f"AV export: no AI-visibility data in {db_path} yet — wrote "
              f"data_available:false stub → {path}")
    print(f"AI_VISIBILITY_EXPORT_OUT={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
