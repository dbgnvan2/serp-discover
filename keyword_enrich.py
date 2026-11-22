#!/usr/bin/env python3
"""keyword_enrich.py — enrich a GSC-mined phrase CSV into a Google Ads keyword
shortlist using Moz (volume/difficulty/intent) + SerpAPI (autocomplete).

The bridge step between ~/gsc's serp_candidates.py (which mines Search Console
phrases into a CSV) and the Google Ads ad groups. Run from the serp-discover
venv so the Moz modules are available:

    ./venv/bin/python keyword_enrich.py --csv <phrases.csv> --out <dir>

Input CSV: one phrase per line (serp_candidates.csv format).
Outputs, in --out: enriched.json (full payload) + shortlist.md (human digest).

The script only classifies and expands — it never edits Google Ads.

It reads `config.yml` like every other entry point: the database is
`database.path`, the Moz locale, per-run caps and on/off switches are
`moz.keyword_metrics` / `moz.search_intent`, and SerpAPI goes through
`serp_fetch` with the configured timeout and retry policy. The grading and
grouping words are `serp_vocab.yml` `ads_shortlist`. Before this the script
named its own database, spent Moz rows with no cap and with
`moz.search_intent.enabled: false`, and filed a failed autocomplete call as a
phrase with no suggestions.

Spec: docs/USER_MANUAL.md#google-ads-keyword-shortlist-keyword_enrichpy
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

import pattern_matching  # noqa: E402
import process_config  # noqa: E402
import serp_fetch  # noqa: E402
import timeouts  # noqa: E402

#: A signal switched off in config.yml: asked for nothing, spent nothing.
STATUS_NOT_ENABLED = "not_enabled"
#: Autocomplete never called — no SERPAPI_KEY.
STATUS_NOT_ATTEMPTED = "not_attempted"


def load_config(path: str | None = None) -> dict:
    """config.yml as a dict, with this process's policies applied.

    `process_config.apply` sets the database path, the retry policy and the
    lock timeout, which is what makes `db_connect.database_path()` and
    `serp_fetch` honour the config here.
    """
    path = process_config.config_path(path)
    if not os.path.exists(path):
        process_config.apply(None)
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    process_config.apply(cfg)
    return cfg


def load_shortlist_vocab(vocab: dict | None = None) -> dict:
    """`serp_vocab.yml` `ads_shortlist`, or ValueError naming what is missing.

    No Python fallback copy: a second copy of the grading words is how the
    two drift, and a shortlist graded by words nobody can see is worse than
    no shortlist.
    """
    vocab = pattern_matching.SERP_VOCAB if vocab is None else vocab
    block = (vocab or {}).get("ads_shortlist")
    if not isinstance(block, dict):
        raise ValueError("serp_vocab.yml has no ads_shortlist block")
    intents = block.get("ad_grade_intents")
    groups = block.get("ad_groups")
    default = block.get("default_group")
    if not isinstance(intents, list) or not intents:
        raise ValueError("serp_vocab.yml ads_shortlist.ad_grade_intents is empty")
    if not isinstance(groups, list) or not all(
            isinstance(g, dict) and g.get("group") and g.get("triggers") for g in groups):
        raise ValueError("serp_vocab.yml ads_shortlist.ad_groups needs group + triggers per entry")
    if not default:
        raise ValueError("serp_vocab.yml ads_shortlist.default_group is empty")
    return {
        "ad_grade_intents": {str(i).lower() for i in intents},
        "ad_groups": [(str(g["group"]), [str(t).lower() for t in g["triggers"]])
                      for g in groups],
        "default_group": str(default),
    }


def read_phrases(csv_path: str) -> list[str]:
    phrases: list[str] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        # serp_candidates.csv is one phrase per line (no header); tolerate a
        # header by skipping the first line if it looks like a column name.
        first = True
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            val = row[0].strip()
            if first and val.lower() in {"keyword", "phrase", "query"}:
                first = False
                continue
            first = False
            if val.lower() not in {p.lower() for p in phrases}:
                phrases.append(val)
    return phrases


def classify_intent(intent_block: dict, vocab: dict) -> str:
    """`ad-grade`, `not ad-grade`, `no primary intent` or `unknown`.

    Never a Moz label Moz did not give: a navigational phrase used to read
    "informational", and so did a measured block with no primary intent.
    """
    if not intent_block.get("data_available"):
        return "unknown"
    primaries = [p.lower() for p in (intent_block.get("primary_intents") or [])]
    if not primaries:
        return "no primary intent"
    if any(p in vocab["ad_grade_intents"] for p in primaries):
        return "ad-grade"
    return "not ad-grade"


def ad_group(phrase: str, vocab: dict) -> str:
    p = phrase.lower()
    for group, triggers in vocab["ad_groups"]:
        if any(t in p for t in triggers):
            return group
    return vocab["default_group"]


def fetch_moz_signal(client_cls, cfg: dict, phrases: list[str],
                     db_path: str | None = None) -> dict[str, dict]:
    """One Moz signal for every phrase, or a `not_enabled` block per phrase.

    `from_config` carries the configured locale, per-run cap and row cost, so
    the 25-keyword testing cap applies here as it does in a run. The cap and
    the quota guard inside the client mark every phrase they skip.
    """
    from moz_keywords import absent
    moz_cfg = cfg.get("moz", {}) or {}
    sig_cfg = moz_cfg.get(client_cls.CONFIG_KEY, {}) or {}
    if not moz_cfg.get("enabled", True) or not sig_cfg.get("enabled", True):
        reason = f"moz.{client_cls.CONFIG_KEY}.enabled is false in config.yml"
        return {p: absent(STATUS_NOT_ENABLED, reason) for p in phrases}
    return client_cls.from_config(cfg, db_path=db_path).fetch(phrases)


def expand_autocomplete(phrases: list[str], cfg: dict,
                        client=None, available=None) -> dict[str, dict]:
    """Google Autocomplete per phrase as ``{"status", "suggestions"}``.

    ``status`` is `serp_fetch`'s word for the outcome, so a call that failed
    reads as failed and an answer with no suggestions reads as an answer.
    Both were ``[]`` before, which the shortlist rendered as nothing to say.
    """
    key = os.environ.get("SERPAPI_KEY", "")
    if not key:
        return {p: {"status": STATUS_NOT_ATTEMPTED, "suggestions": []} for p in phrases}
    serp_cfg = cfg.get("serpapi", {}) or {}
    timeout = timeouts.serpapi_timeout(cfg)
    out: dict[str, dict] = {}
    for p in phrases:
        params = {"engine": "google_autocomplete", "q": p,
                  "gl": serp_cfg.get("gl", "ca"), "hl": serp_cfg.get("hl", "en"),
                  "api_key": key}
        results, status = serp_fetch.fetch_with_status(
            params, timeout_seconds=timeout, client=client, available=available)
        suggestions = []
        for s in (results or {}).get("suggestions", []) or []:
            val = s.get("value") if isinstance(s, dict) else s
            if val:
                suggestions.append(val)
        out[p] = {"status": status, "suggestions": suggestions}
    return out


def _counts(blocks: dict[str, dict]) -> str:
    """'3 of 5 measured; 2 skipped_quota' — the shortlist says what it lacks."""
    c = Counter(b.get("status", "unknown") for b in blocks.values())
    ok = sum(1 for b in blocks.values() if b.get("data_available"))
    rest = "; ".join(f"{n} {s}" for s, n in sorted(c.items()) if s != "ok")
    return f"{ok} of {len(blocks)} measured" + (f"; {rest}" if rest else "")


def _cell(value, block: dict) -> str:
    if value is not None:
        return str(value)
    return f"— ({block.get('status', 'unknown')})"


def main() -> int:
    load_dotenv(os.path.join(REPO, ".env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default=None,
                    help="override config.yml database.path for this run")
    ap.add_argument("--config", default=None, help="config.yml to read")
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        vocab = load_shortlist_vocab()
    except ValueError as e:
        print(f"cannot grade phrases: {e}", file=sys.stderr)
        return 2

    from moz_jsonrpc import quota_status
    from moz_keywords import MozIntentClient, MozKeywordClient

    phrases = read_phrases(args.csv)
    if not phrases:
        print("no phrases found in CSV", file=sys.stderr)
        return 1

    try:
        quota_before = quota_status()["remaining"]
    except Exception as e:
        quota_before = f"unreadable: {e}"

    metrics = fetch_moz_signal(MozKeywordClient, cfg, phrases, args.db)
    intents = fetch_moz_signal(MozIntentClient, cfg, phrases, args.db)

    # Autocomplete-expand only the ad-grade phrases (cheaper + on-topic).
    ad_grade = [p for p in phrases
                if classify_intent(intents.get(p, {}), vocab) == "ad-grade"]
    autocomplete = expand_autocomplete(ad_grade, cfg)

    try:
        quota_after = quota_status()["remaining"]
    except Exception as e:
        quota_after = f"unreadable: {e}"

    os.makedirs(args.out, exist_ok=True)
    rows = []
    for p in phrases:
        m = metrics.get(p, {})
        i = intents.get(p, {})
        rows.append({
            "phrase": p,
            "volume": m.get("volume"),
            "difficulty": m.get("difficulty"),
            "metrics_status": m.get("status"),
            "intent": i.get("primary_intents"),
            "intent_status": i.get("status"),
            "verdict": classify_intent(i, vocab),
            "ad_group": ad_group(p, vocab),
        })

    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_csv": args.csv,
        "quota_remaining_before": quota_before,
        "quota_remaining_after": quota_after,
        "metrics_coverage": _counts(metrics),
        "intent_coverage": _counts(intents),
        "rows": rows,
        "autocomplete": autocomplete,
    }
    with open(os.path.join(args.out, "enriched.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    md = render_shortlist(payload)
    with open(os.path.join(args.out, "shortlist.md"), "w", encoding="utf-8") as f:
        f.write(md)

    print(md)
    return 0


def render_shortlist(p: dict) -> str:
    lines = ["# Google Ads keyword shortlist", "",
             f"Generated {p['generated_at'][:16]} from `{p['source_csv']}`",
             f"Moz quota: {p['quota_remaining_before']} → {p['quota_remaining_after']} rows remaining",
             f"Volume/difficulty: {p.get('metrics_coverage', '—')}",
             f"Intent: {p.get('intent_coverage', '—')}", ""]
    lines.append("## Vetted phrases")
    lines.append("| Phrase | Volume | Difficulty | Intent | Verdict | Ad group |")
    lines.append("|---|---|---|---|---|---|")
    for r in p["rows"]:
        m = {"status": r.get("metrics_status")}
        vol = _cell(r["volume"], m)
        diff = _cell(r["difficulty"], m)
        intent = (", ".join(r["intent"]) if r["intent"]
                  else f"— ({r.get('intent_status') or 'unknown'})")
        lines.append(f"| {r['phrase']} | {vol} | {diff} | {intent} | {r['verdict']} | {r['ad_group']} |")
    lines.append("")
    lines.append("## Autocomplete expansions (ad-grade only)")
    if not p.get("autocomplete"):
        # Said, not omitted: with search intent off nothing is ad-grade, and
        # a missing section read the same as "no phrase qualified".
        lines.append(f"\nNot run: 0 of {len(p['rows'])} phrases graded ad-grade "
                     f"(intent: {p.get('intent_coverage', '—')}).")
    else:
        failed = []
        for phrase, entry in p["autocomplete"].items():
            if entry["status"] != serp_fetch.STATUS_OK:
                failed.append(f"{phrase} ({entry['status']})")
            elif entry["suggestions"]:
                lines.append(f"\n**{phrase}**")
                for s in entry["suggestions"]:
                    lines.append(f"- {s}")
            else:
                lines.append(f"\n**{phrase}** — Google returned no suggestions")
        if failed:
            lines.append(f"\nNot fetched ({len(failed)} of {len(p['autocomplete'])}): "
                         + "; ".join(failed))
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
