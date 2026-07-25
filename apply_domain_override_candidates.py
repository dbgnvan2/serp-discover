#!/usr/bin/env python3
"""
Apply current high-confidence domain override candidates into domain_overrides.yml.
"""
import argparse

import yaml

from yaml_io import save_yaml_preserving_comments
from classifiers import EntityClassifier
from generate_domain_override_candidates import (
    collect_candidates,
    load_json,
    load_overrides,
    normalize_domain,
    split_candidates,
)


def merge_overrides(existing_overrides, high_confidence_candidates):
    merged = {normalize_domain(domain): entity_type for domain, entity_type in (existing_overrides or {}).items()}
    added = []
    skipped = []

    for item in high_confidence_candidates:
        domain = normalize_domain(item["domain"])
        suggested_type = item.get("selected_type") or item["suggested_type"]
        existing_type = merged.get(domain)
        if existing_type:
            skipped.append((domain, existing_type, "already_present"))
            continue
        merged[domain] = suggested_type
        added.append((domain, suggested_type))

    return merged, added, skipped


def write_overrides(path, overrides):
    # Comment-preserving write (ruamel round-trip) — safe_dump stripped
    # domain_overrides.yml's header comments whenever candidates were applied.
    save_yaml_preserving_comments(path, dict(sorted(overrides.items())))


def main():
    parser = argparse.ArgumentParser(
        description="Approve and apply high-confidence domain override candidates."
    )
    parser.add_argument("--json", default="market_analysis_v2.json")
    parser.add_argument("--overrides", default="domain_overrides.yml")
    parser.add_argument("--min-rows", type=int, default=4)
    parser.add_argument("--min-keywords", type=int, default=2)
    args = parser.parse_args()

    print(f"[1/5] Loading analysis JSON from {args.json}...", flush=True)
    data = load_json(args.json)
    print(f"[2/5] Loading existing overrides from {args.overrides}...", flush=True)
    existing_overrides = load_overrides(args.overrides)
    print("[3/5] Building candidate list...", flush=True)
    classifier = EntityClassifier(override_file=args.overrides)
    candidates = collect_candidates(
        data,
        existing_overrides,
        classifier,
        min_rows=args.min_rows,
        min_keywords=args.min_keywords,
    )
    high_confidence, _needs_judgment = split_candidates(candidates)
    print(f"[4/5] Applying {len(high_confidence)} high-confidence candidates...", flush=True)
    merged_overrides, added, skipped = merge_overrides(existing_overrides, high_confidence)
    print(f"[5/5] Writing updated overrides to {args.overrides}...", flush=True)
    write_overrides(args.overrides, merged_overrides)

    print("")
    print(f"High-confidence candidates reviewed: {len(high_confidence)}")
    print(f"Overrides added: {len(added)}")
    for domain, entity_type in added:
        print(f"  + {domain}: {entity_type}")
    if skipped:
        print(f"Skipped existing overrides: {len(skipped)}")
        for domain, entity_type, reason in skipped:
            print(f"  = {domain}: {entity_type} ({reason})")


if __name__ == "__main__":
    main()
