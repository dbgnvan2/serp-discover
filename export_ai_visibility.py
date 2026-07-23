#!/usr/bin/env python3
"""export_ai_visibility.py — CLI to export AI-visibility data for serp-compete.

Spec: discover AV-EXPORT (serp-compete/compete-spec.md#C1 dependency).

Reads the already-stored ``brand_mentions`` / ``ai_citations`` tables (no
re-probe, no cost) and writes ``output/ai_visibility_export_<slug>_<ts>.json``
for serp-compete to consume. Run any time after a probe run:

    python3 export_ai_visibility.py --db serp_data.db --out output

When no AI-visibility data exists yet, it writes a ``data_available: false`` stub
(so the downstream consumer degrades gracefully) and reports it.
"""
from __future__ import annotations

import argparse
import os
import sys

from ai_visibility_export import build_ai_visibility_export, write_ai_visibility_export

DEFAULT_CLIENT_SLUG = "client"


def _read_client_identity(config_path: str) -> tuple[str, str | None]:
    """Return (client_slug, client_name) from config.yml, with safe fallbacks.

    client_slug names the export file (matches ai_visibility.client_slug);
    client_name is informational in the payload — the authoritative client flag
    is the per-row ``is_client`` already stored in the tables.
    """
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as exc:  # missing/malformed config must not block the export
        print(f"AV export: could not read {config_path} ({exc}); using defaults.",
              file=sys.stderr)
        return DEFAULT_CLIENT_SLUG, None
    av = config.get("ai_visibility", {}) or {}
    analysis = config.get("analysis_report", {}) or {}
    slug = str(av.get("client_slug", DEFAULT_CLIENT_SLUG)) or DEFAULT_CLIENT_SLUG
    name = analysis.get("client_name")
    return slug, name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export AI-visibility data (brand_mentions/ai_citations) for serp-compete.")
    parser.add_argument("--db", default="serp_data.db", help="SQLite database path")
    parser.add_argument("--out", default="output", help="Output directory")
    parser.add_argument("--config", default="config.yml", help="Config path (for client slug/name)")
    args = parser.parse_args(argv)

    # Distinguish a missing DB (possible --db typo) from a genuinely empty one —
    # both yield an empty export, but only the latter is benign (P6).
    if not os.path.exists(args.db):
        print(f"AV export: ⚠️ database not found at '{args.db}'. Writing an empty "
              f"export; if this path is a typo, re-run with the correct --db.",
              file=sys.stderr)

    client_slug, client_name = _read_client_identity(args.config)
    export = build_ai_visibility_export(args.db, client_name=client_name)
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
        print(f"AV export: no AI-visibility data in {args.db} yet — wrote "
              f"data_available:false stub → {path}")
    print(f"AI_VISIBILITY_EXPORT_OUT={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
