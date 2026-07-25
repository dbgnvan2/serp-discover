#!/usr/bin/env python3
"""engine_transfer.py — cross-engine transfer / overlap metric.

Spec: yoast_geo_upgrade_spec_v1.md#Y.11 (decision gate Y-D9).

The user's core question — "if I'm good on one AI, am I good across all?" — is
empirically answerable FOR THIS SPECIFIC CLIENT from the data the tool already
collects across engines, rather than assumed from industry averages. This module
computes it, purely (design principle 1 — no LLM), from ≥2 enabled engines of the
same run:

  * **Client visibility transfer** — on which enabled engines the client is
    mentioned / cited, plus a plain statement ("mentioned on 2 of 3 engines").
  * **Citation-source overlap** — pairwise Jaccard similarity of the cited-domain
    sets per engine (from the Y.8 citation table), plus the count of domains
    cited by ALL engines vs by EXACTLY ONE — the client's own version of the
    industry ~0.18 overlap finding.
  * **Leaderboard-rank divergence** — the client's Y.7 rank per engine and the
    spread (max − min).

Persistence: an ``engine_transfer`` SQLite table so overlap is trendable
(principle 5). All timestamps UTC.

A single-engine run degrades to "transfer not measurable (single engine)" —
no crash (Spec Y.11.3).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from itertools import combinations

logger = logging.getLogger(__name__)

TRANSFER_TABLE = "engine_transfer"


def jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity of two sets: |A∩B| / |A∪B|.

    Two empty sets → 1.0 (identical, by convention: nothing differs). Identical
    non-empty sets → 1.0; disjoint sets → 0.0 (Spec Y.11.1). Deterministic.
    """
    union = set_a | set_b
    if not union:
        return 1.0
    return round(len(set_a & set_b) / len(union), 4)


def _cited_domains(table: list[dict]) -> set[str]:
    """The set of distinct cited domains from a Y.8 citation table."""
    return {r["domain"] for r in (table or []) if r.get("domain")}


def compute_transfer(engines: list[str], mention_by_engine: dict,
                     cited_by_engine: dict,
                     citation_tables: dict,
                     client_rank_by_engine: dict) -> dict:
    """Compute the cross-engine transfer metrics for one run.

    Args:
      engines: enabled engine names (order preserved for reporting).
      mention_by_engine: engine → bool (client mentioned in ≥1 answer).
      cited_by_engine: engine → bool (client cited in ≥1 answer).
      citation_tables: engine → Y.8 citation table (list of row dicts).
      client_rank_by_engine: engine → int | None (client's Y.7 leaderboard rank).

    Returns a dict with ``measurable`` False + a ``reason`` for a single-engine
    run (Spec Y.11.3); otherwise the full metric bundle::

        {
          "measurable": True,
          "engines": [...],
          "visibility": {
             "mentioned_engines": [...], "cited_engines": [...],
             "mention_transfer": "mentioned on N of M engines",
             "cite_transfer": "cited on N of M engines",
             "engine_count": M,
          },
          "overlap": {
             "pairwise_jaccard": {"a|b": float, ...},
             "avg_jaccard": float,
             "cited_by_all": int, "cited_by_exactly_one": int,
             "domains_all": [...], "domains_unique": [...],
          },
          "rank_divergence": {
             "ranks": {engine: rank|None}, "spread": int | None,
          },
          "interpretation": str,
        }

    Deterministic given inputs.
    """
    engines = list(engines or [])
    if len(engines) < 2:
        return {
            "measurable": False,
            "reason": "transfer not measurable (single engine)",
            "engines": engines,
        }

    mention_by_engine = mention_by_engine or {}
    cited_by_engine = cited_by_engine or {}
    citation_tables = citation_tables or {}
    client_rank_by_engine = client_rank_by_engine or {}

    engine_count = len(engines)

    # --- Client visibility transfer ---
    mentioned_engines = [e for e in engines if mention_by_engine.get(e)]
    cited_engines = [e for e in engines if cited_by_engine.get(e)]
    visibility = {
        "mentioned_engines": mentioned_engines,
        "cited_engines": cited_engines,
        "mention_transfer": f"mentioned on {len(mentioned_engines)} of {engine_count} engines",
        "cite_transfer": f"cited on {len(cited_engines)} of {engine_count} engines",
        "engine_count": engine_count,
    }

    # --- Citation-source overlap (pairwise Jaccard of cited-domain sets) ---
    domain_sets = {e: _cited_domains(citation_tables.get(e, [])) for e in engines}
    pairwise: dict[str, float] = {}
    jaccard_values: list[float] = []
    for a, b in combinations(engines, 2):
        j = jaccard(domain_sets[a], domain_sets[b])
        pairwise[f"{a}|{b}"] = j
        jaccard_values.append(j)
    avg_jaccard = round(sum(jaccard_values) / len(jaccard_values), 4) if jaccard_values else 0.0

    # Count domains cited by ALL vs EXACTLY ONE engine.
    domain_engine_count: dict[str, int] = {}
    for e in engines:
        for domain in domain_sets[e]:
            domain_engine_count[domain] = domain_engine_count.get(domain, 0) + 1
    cited_by_all = sorted(d for d, n in domain_engine_count.items() if n == engine_count)
    cited_by_one = sorted(d for d, n in domain_engine_count.items() if n == 1)
    overlap = {
        "pairwise_jaccard": pairwise,
        "avg_jaccard": avg_jaccard,
        "cited_by_all": len(cited_by_all),
        "cited_by_exactly_one": len(cited_by_one),
        "domains_all": cited_by_all,
        "domains_unique": cited_by_one,
    }

    # --- Leaderboard-rank divergence ---
    ranks = {e: client_rank_by_engine.get(e) for e in engines}
    present_ranks = [r for r in ranks.values() if r is not None]
    spread = (max(present_ranks) - min(present_ranks)) if len(present_ranks) >= 2 else None
    rank_divergence = {"ranks": ranks, "spread": spread}

    # --- Interpretation (high overlap ⇒ foundational suffices; low ⇒ per-engine) ---
    if avg_jaccard >= 0.5:
        interpretation = (
            "High cross-engine citation overlap: the engines largely draw on the "
            "same sources for this client, so foundational, transferable work "
            "(accessibility, structure/schema, off-site authority) is likely to "
            "lift the client on all of them at once."
        )
    elif avg_jaccard >= 0.2:
        interpretation = (
            "Moderate cross-engine citation overlap: foundational work helps "
            "everywhere, but some per-engine targeting is still needed because "
            "the engines diverge on which sources they cite."
        )
    else:
        interpretation = (
            "Low cross-engine citation overlap: the engines cite mostly different "
            "sources for this client, so a win on one does NOT carry to the "
            "others — per-engine targeting is required in addition to the "
            "foundational layer."
        )

    return {
        "measurable": True,
        "engines": engines,
        "visibility": visibility,
        "overlap": overlap,
        "rank_divergence": rank_divergence,
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def init_transfer_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {TRANSFER_TABLE} (
            run_ts               TEXT,
            engine_count         INTEGER,
            mentioned_count      INTEGER,
            cited_count          INTEGER,
            avg_jaccard          REAL,
            cited_by_all         INTEGER,
            cited_by_exactly_one INTEGER,
            rank_spread          INTEGER,
            detail_json          TEXT
        )''')
        conn.commit()


def save_transfer(db_path: str, run_ts: str, result: dict) -> None:
    """Persist one run's transfer metrics. Single-engine (non-measurable) runs
    are still recorded (engine_count, everything else NULL) so the trend is
    honest about when transfer could not be measured."""
    init_transfer_table(db_path)
    engines = result.get("engines", []) or []
    if not result.get("measurable"):
        row = (run_ts, len(engines), None, None, None, None, None, None,
               json.dumps({"measurable": False,
                           "reason": result.get("reason")}))
    else:
        vis = result.get("visibility", {})
        ov = result.get("overlap", {})
        rd = result.get("rank_divergence", {})
        row = (
            run_ts, vis.get("engine_count", len(engines)),
            len(vis.get("mentioned_engines", [])),
            len(vis.get("cited_engines", [])),
            ov.get("avg_jaccard"),
            ov.get("cited_by_all"),
            ov.get("cited_by_exactly_one"),
            rd.get("spread"),
            json.dumps({
                "pairwise_jaccard": ov.get("pairwise_jaccard", {}),
                "ranks": rd.get("ranks", {}),
                "interpretation": result.get("interpretation"),
            }),
        )
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {TRANSFER_TABLE} WHERE run_ts = ?",
                     (run_ts,))   # idempotent per run_ts — P8
        conn.execute(
            f"""INSERT INTO {TRANSFER_TABLE}
                (run_ts, engine_count, mentioned_count, cited_count, avg_jaccard,
                 cited_by_all, cited_by_exactly_one, rank_spread, detail_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        conn.commit()


def get_transfer_trend(db_path: str, limit: int = 5) -> list[dict]:
    """Per-run transfer metrics, oldest→newest (trendable, Spec Y.11.4)."""
    init_transfer_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, engine_count, mentioned_count, cited_count,
                       avg_jaccard, cited_by_all, cited_by_exactly_one, rank_spread
                FROM {TRANSFER_TABLE}
                ORDER BY run_ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    trend = [
        {"run_ts": rt, "engine_count": ec, "mentioned_count": mc,
         "cited_count": cc, "avg_jaccard": aj, "cited_by_all": ca,
         "cited_by_exactly_one": co, "rank_spread": rs}
        for rt, ec, mc, cc, aj, ca, co, rs in rows
    ]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

def render_transfer_section(result: dict) -> list[str]:
    """Render the "Transfer" section (Spec Y.11 report).

    States how much this client's AI visibility overlaps across engines, with the
    explicit interpretation (high overlap ⇒ foundational suffices; low ⇒
    per-engine targeting). A single-engine run states "not measurable".
    """
    out: list[str] = []
    out.append("## Cross-engine transfer — does a win on one AI carry to all?")
    if not result.get("measurable"):
        out.append(
            "*Transfer not measurable (single engine). Enable at least two "
            "engines to measure how much this client's AI visibility overlaps "
            "across them.*"
        )
        out.append("")
        return out

    vis = result.get("visibility", {})
    ov = result.get("overlap", {})
    rd = result.get("rank_divergence", {})

    out.append(
        "Measured from this run's ≥2 engines — this client's actual cross-engine "
        "overlap, not an industry average. A single run is a snapshot; read the "
        "trend."
    )
    out.append("")
    out.append("**Client visibility transfer:**")
    out.append(f"- {vis.get('mention_transfer', '—')}"
               + (f" ({', '.join(vis['mentioned_engines'])})" if vis.get("mentioned_engines") else ""))
    out.append(f"- {vis.get('cite_transfer', '—')}"
               + (f" ({', '.join(vis['cited_engines'])})" if vis.get("cited_engines") else ""))
    out.append("")

    out.append("**Citation-source overlap:**")
    out.append(f"- Average pairwise Jaccard of cited-domain sets: "
               f"{ov.get('avg_jaccard', 0):.2f}")
    pairwise = ov.get("pairwise_jaccard", {})
    for pair, value in pairwise.items():
        out.append(f"  - {pair.replace('|', ' vs ')}: {value:.2f}")
    out.append(f"- Domains cited by ALL engines: {ov.get('cited_by_all', 0)}")
    out.append(f"- Domains cited by exactly ONE engine: {ov.get('cited_by_exactly_one', 0)}")
    out.append("")

    ranks = rd.get("ranks", {})
    if ranks:
        rank_cells = ", ".join(
            f"{e}: {'#' + str(r) if r is not None else 'not ranked'}"
            for e, r in ranks.items())
        spread = rd.get("spread")
        spread_txt = f" (spread {spread})" if spread is not None else ""
        out.append(f"**Leaderboard-rank divergence:** {rank_cells}{spread_txt}.")
        out.append("")

    out.append(f"**Interpretation:** {result.get('interpretation', '')}")
    out.append("")
    return out
