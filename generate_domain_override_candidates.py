#!/usr/bin/env python3
"""
Generate a reviewable list of recurring domains that may deserve entries
in domain_overrides.yml.
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from urllib.parse import urlparse

import yaml

import domain_utils
import link_recovery
from classifiers import EntityClassifier


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_overrides(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def normalize_domain(url_or_domain):
    """The bare domain for a stored link, or "" when there is none.

    Runs written before link recovery stored Google's redirect wrapper in
    ``Link``, whose netloc is ``www.google.com``. Classifying that would put
    google.com into the override queue and onto the rows as a competitor
    (P1 — unknown is not a terminal value), so a wrapper has no domain here.
    One definition: refresh_analysis_outputs imports this function, and the
    host normalisation itself is ``domain_utils.normalize_domain`` — the same
    one ``EntityClassifier`` applies, so the report and the pipeline cannot
    disagree about which host an override covers (D2c.3, finding D-C-08).
    """
    if link_recovery.is_google_redirect(url_or_domain):
        return ""
    return domain_utils.normalize_domain(url_or_domain)


def collect_candidates(data, overrides, classifier, min_rows=3, min_keywords=2):
    rows = data.get("organic_results", [])
    grouped = defaultdict(list)
    override_domains = {normalize_domain(d) for d in overrides.keys()}

    wrapped = 0
    for row in rows:
        if link_recovery.is_google_redirect(row.get("Link")):
            wrapped += 1
            continue
        domain = normalize_domain(row.get("Link") or row.get("Source"))
        if not domain or domain in override_domains:
            continue
        grouped[domain].append(row)

    if wrapped:
        # P2 — say what was excluded rather than returning a shorter list.
        print(f"  {wrapped} of {len(rows)} organic row(s) still hold a Google "
              f"redirect wrapper in Link and have no domain to classify; "
              f"re-run the audit to recover them.")

    candidates = []
    for domain, domain_rows in grouped.items():
        source_keywords = sorted({r.get("Source_Keyword") for r in domain_rows if r.get("Source_Keyword")})
        if len(domain_rows) < min_rows and len(source_keywords) < min_keywords:
            continue

        suggested_type, confidence, evidence = classifier.classify(domain, None)
        # Unknown domains can stay out of the review queue unless they recur
        # heavily enough to warrant a manual decision.
        if suggested_type == "N/A" and confidence == 0.0:
            if len(source_keywords) < 4 and len(domain_rows) < 10:
                continue
        rank_values = []
        for row in domain_rows:
            try:
                rank_values.append(int(row.get("Rank")))
            except (TypeError, ValueError):
                pass

        titles = []
        for row in domain_rows:
            title = row.get("Title")
            if title and title not in titles:
                titles.append(title)
            if len(titles) == 3:
                break

        current_types = Counter(
            r.get("Entity_Type") for r in domain_rows
            if r.get("Entity_Type") not in (None, "", "N/A")
        )
        candidates.append({
            "domain": domain,
            "suggested_type": suggested_type,
            "confidence": confidence,
            "evidence": evidence,
            "organic_rows": len(domain_rows),
            "source_keywords": source_keywords,
            "source_keyword_count": len(source_keywords),
            "best_rank": min(rank_values) if rank_values else None,
            "current_entity_types": dict(current_types),
            "sample_titles": titles,
        })

    candidates.sort(
        key=lambda item: (
            -item["source_keyword_count"],
            -item["organic_rows"],
            item["best_rank"] if item["best_rank"] is not None else 999,
            item["domain"],
        )
    )
    return candidates


def split_candidates(candidates):
    high_confidence = []
    needs_judgment = []

    for item in candidates:
        if item["confidence"] >= 0.9 or (
            item["suggested_type"] in {
                "government", "directory", "media",
                "nonprofit", "education", "professional_association"
            }
            and item["confidence"] >= 0.6
        ):
            high_confidence.append(item)
        else:
            needs_judgment.append(item)

    return high_confidence, needs_judgment


def render_markdown(candidates, json_path, overrides_path, min_rows, min_keywords):
    high_confidence, needs_judgment = split_candidates(candidates)

    lines = []
    lines.append("# Domain Override Review Candidates")
    lines.append("")
    lines.append(f"Source analysis JSON: `{json_path}`")
    lines.append(f"Existing overrides: `{overrides_path}`")
    lines.append(
        f"Included when a domain appears in at least `{min_rows}` organic rows or across "
        f"`{min_keywords}` source keywords."
    )
    lines.append("")

    if not candidates:
        lines.append("No new override candidates met the current threshold.")
        return "\n".join(lines) + "\n"

    if high_confidence:
        lines.append("## High-confidence Additions")
        lines.append("")
        lines.append("| Domain | Suggested Type | Rows | Root Keywords | Best Rank | Sample Titles |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for item in high_confidence:
            sample_titles = "; ".join(item["sample_titles"])
            lines.append(
                f"| `{item['domain']}` | `{item['suggested_type']}` | {item['organic_rows']} | "
                f"{item['source_keyword_count']} | {item['best_rank'] or '-'} | {sample_titles} |"
            )
        lines.append("")

    if needs_judgment:
        lines.append("## Needs Human Judgment")
        lines.append("")
        lines.append("| Domain | Suggested Type | Rows | Root Keywords | Best Rank | Sample Titles |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for item in needs_judgment:
            sample_titles = "; ".join(item["sample_titles"])
            lines.append(
                f"| `{item['domain']}` | `{item['suggested_type']}` | {item['organic_rows']} | "
                f"{item['source_keyword_count']} | {item['best_rank'] or '-'} | {sample_titles} |"
            )
        lines.append("")

    lines.append("")
    lines.append("## Review Notes")
    for item in candidates:
        lines.append(
            f"`{item['domain']}` appears in {item['organic_rows']} rows across "
            f"{item['source_keyword_count']} root keywords. Suggested override: "
            f"`{item['suggested_type']}` (confidence {item['confidence']:.1f}). "
            f"Keywords: {', '.join(item['source_keywords'])}. "
            f"Evidence: {', '.join(item['evidence']) if item['evidence'] else 'none'}."
        )

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Generate a review list of domains worth considering for domain_overrides.yml."
    )
    parser.add_argument("--json", default="market_analysis_v2.json")
    parser.add_argument("--overrides", default="domain_overrides.yml")
    parser.add_argument("--out", default="domain_override_candidates.md")
    parser.add_argument("--min-rows", type=int, default=4)
    parser.add_argument("--min-keywords", type=int, default=2)
    args = parser.parse_args()

    print(f"[1/4] Loading analysis JSON from {args.json}...", flush=True)
    data = load_json(args.json)
    print(f"[2/4] Loading existing overrides from {args.overrides}...", flush=True)
    overrides = load_overrides(args.overrides)
    print("[3/4] Building candidate list...", flush=True)
    classifier = EntityClassifier(override_file=args.overrides)
    candidates = collect_candidates(
        data,
        overrides,
        classifier,
        min_rows=args.min_rows,
        min_keywords=args.min_keywords,
    )
    print(f"[4/4] Writing review report to {args.out}...", flush=True)
    report = render_markdown(candidates, args.json, args.overrides, args.min_rows, args.min_keywords)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)

    print("")
    print(f"Domain override candidate report generated: {args.out}")
    print(f"Candidates found: {len(candidates)}")


if __name__ == "__main__":
    main()
