#!/usr/bin/env python3
"""citation_table.py — categorized, brand-attributed AI citation table.

Spec: yoast_geo_upgrade_spec_v1.md#Y.8.

The probe stores ``source_urls`` per answer but does nothing with them beyond
the binary client-``cited`` check. Yoast's report lists EVERY source with a
**Category** and the **brand** each supports — turning citations into an
actionable map of which sources the AI trusts for this topic (a
content-partnership / outreach target list).

This module, per probed answer, records every source URL with:

  * ``domain`` (lower-cased, ``www.`` stripped);
  * a **category** from the EXISTING content/entity classifier
    (``classifiers.EntityClassifier`` + ``classification_rules.json`` +
    ``domain_overrides.yml``) — NOT a parallel category list. A ``publisher``
    label was added to the existing editorial files when it was missing;
  * an attributed **brand** (gazetteer/domain match against ``known_brands`` +
    the Y.7 leaderboard brands; ``None`` when unknown);
  * an ``is_client`` flag for client-owned citations.

Identical URLs are de-duplicated across questions with a ``cite_count``.
Tracking params are RETAINED as returned (e.g. ``?utm_source=openai``) — they
identify the surfacing engine and must not be stripped (Spec Y.8.3).

Persistence: an ``ai_citations`` SQLite table (``run_ts, engine, url, domain,
category, brand, is_client, cite_count``). Feeds Y.6's Citations axis.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from urllib.parse import urlparse

from classifiers import EntityClassifier

logger = logging.getLogger(__name__)

CITATIONS_TABLE = "ai_citations"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def domain_of(url: str) -> str:
    """Lower-cased registrable-ish domain, ``www.`` stripped. Never raises."""
    try:
        raw = str(url or "").strip()
        parsed = urlparse(raw if "//" in raw else "//" + raw)
        return (parsed.netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _matches_domain(domain: str, target: str) -> bool:
    return bool(domain) and (domain == target or domain.endswith("." + target))


class _Categorizer:
    """Thin cache around the existing EntityClassifier for domain→category.

    Uses ``classify(domain, None)`` (soup-less, domain-level) so the category is
    sourced entirely from the existing editorial files — no parallel list.
    """

    def __init__(self, classifier: EntityClassifier | None = None) -> None:
        self._classifier = classifier or EntityClassifier()
        self._cache: dict[str, str] = {}

    def category(self, domain: str) -> str:
        if domain in self._cache:
            return self._cache[domain]
        try:
            label, _conf, _ev = self._classifier.classify(domain, None)
        except Exception as exc:
            logger.warning("citation_table: classifier failed on %r: %s", domain, exc)
            label = "N/A"
        # The classifier's soup-less "not determined" sentinel is normalised to
        # the Yoast-style "other" bucket for the citation table.
        if label in (None, "", "N/A"):
            label = "other"
        self._cache[domain] = label
        return label


def attribute_brand(domain: str, brand_domains: dict[str, str],
                    brand_names: list[str]) -> str | None:
    """Attribute a citation domain to a brand.

    ``brand_domains`` maps a lower-cased domain (or bare label) to a display
    brand name; ``brand_names`` are additional gazetteer brands whose stub may
    appear in the domain. Returns the brand display name, or ``None`` when
    unknown (Spec Y.8.2 — unknown → null, never fabricated).
    """
    if not domain:
        return None
    for known_domain, display in brand_domains.items():
        kd = _norm(known_domain)
        if "." in kd:
            if _matches_domain(domain, kd):
                return display
        elif kd and kd in domain:
            return display
    # Fall back to a bare-name stub match (e.g. "theravive" in the domain).
    stub = domain.split(".")[0]
    for name in brand_names:
        if _norm(name) and _norm(name).replace(" ", "") == stub:
            return name
    return None


def build_citation_table(answers: list[dict], client_domain: str,
                         brand_domains: dict[str, str] | None = None,
                         brand_names: list[str] | None = None,
                         classifier: EntityClassifier | None = None) -> list[dict]:
    """Build the de-duplicated citation table for one engine's answers.

    ``answers`` is a list of ``{source_urls: [...]}`` dicts. Returns a list of
    ``{url, domain, category, brand, is_client, cite_count}`` dicts, ordered by
    ``cite_count`` desc then URL. Identical URLs are merged with a count; the
    URL string (including tracking params) is preserved verbatim (Y.8.3).
    """
    categorizer = _Categorizer(classifier)
    brand_domains = brand_domains or {}
    brand_names = brand_names or []
    client = (client_domain or "").lower().removeprefix("www.")

    order: list[str] = []
    records: dict[str, dict] = {}
    for ans in answers or []:
        for url in ans.get("source_urls") or []:
            url = str(url)
            if url not in records:
                domain = domain_of(url)
                is_client = bool(client and _matches_domain(domain, client))
                brand = attribute_brand(domain, brand_domains, brand_names)
                if is_client and not brand:
                    brand = brand_domains.get(client) or "client"
                records[url] = {
                    "url": url,             # verbatim — tracking params retained
                    "domain": domain,
                    "category": categorizer.category(domain),
                    "brand": brand,
                    "is_client": is_client,
                    "cite_count": 0,
                }
                order.append(url)
            records[url]["cite_count"] += 1

    table = [records[u] for u in order]
    table.sort(key=lambda r: (-r["cite_count"], r["url"]))
    return table


def top_cited_domains(table: list[dict], limit: int = 5) -> list[tuple[str, int]]:
    """Aggregate cite counts by domain → the outreach shortlist (Spec Y.8.4)."""
    counts: dict[str, int] = {}
    for row in table:
        dom = row["domain"]
        if dom:
            counts[dom] = counts.get(dom, 0) + row["cite_count"]
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def citations_axis(table: list[dict]) -> float:
    """Client-owned citations as a share of total citations → 0–100 (Y.6).

    Uses ``cite_count`` weighting so a heavily re-cited client URL counts more.
    Empty table → 0.0 (no citations to own).
    Spec: yoast_geo_upgrade_spec_v1.md#Y.6 (Citations axis).
    """
    total = sum(r["cite_count"] for r in table)
    if total <= 0:
        return 0.0
    client = sum(r["cite_count"] for r in table if r["is_client"])
    return round(100.0 * client / total, 2)


# ---------------------------------------------------------------------------
# Persistence (probe_ai_visibility.py conventions)
# ---------------------------------------------------------------------------

def init_citations_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {CITATIONS_TABLE} (
            run_ts     TEXT,
            engine     TEXT,
            url        TEXT,
            domain     TEXT,
            category   TEXT,
            brand      TEXT,
            is_client  INTEGER,
            cite_count INTEGER
        )''')
        conn.commit()


def save_citations(db_path: str, run_ts: str, engine: str,
                   table: list[dict]) -> None:
    init_citations_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"""INSERT INTO {CITATIONS_TABLE}
                (run_ts, engine, url, domain, category, brand, is_client,
                 cite_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, engine, r["url"], r["domain"], r["category"],
                 r["brand"], int(bool(r["is_client"])), int(r["cite_count"]))
                for r in table
            ],
        )
        conn.commit()


def get_citations_for_run(db_path: str, run_ts: str, engine: str) -> list[dict]:
    init_citations_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT url, domain, category, brand, is_client, cite_count
                FROM {CITATIONS_TABLE}
                WHERE run_ts = ? AND engine = ?
                ORDER BY cite_count DESC, url ASC""",
            (run_ts, engine),
        ).fetchall()
    return [
        {"url": u, "domain": d, "category": c, "brand": b,
         "is_client": bool(ic), "cite_count": cc}
        for u, d, c, b, ic, cc in rows
    ]


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

def render_citation_section(engine: str, table: list[dict],
                            top_n: int = 40) -> list[str]:
    """Render the citations table for one engine + the outreach shortline."""
    out: list[str] = []
    out.append(f"### {engine} — citations")
    if not table:
        out.append("*No sources were returned in this engine's answers this run.*")
        out.append("")
        return out
    out.append("| # | URL | Domain | Category | Brand | Cites |")
    out.append("|---|-----|--------|----------|-------|-------|")
    for index, row in enumerate(table[:top_n], start=1):
        brand = row["brand"] or "—"
        flag = " ✓client" if row["is_client"] else ""
        out.append(
            f"| {index} | {row['url']} | {row['domain']} | {row['category']} "
            f"| {brand}{flag} | {row['cite_count']} |"
        )
    shortlist = top_cited_domains(table)
    if shortlist:
        joined = ", ".join(f"{dom} ({n})" for dom, n in shortlist)
        out.append("")
        out.append(
            f"**Top cited domains for this topic (outreach shortlist):** {joined}. "
            "These are the sources this engine trusts for the topic — the "
            "content-partnership / outreach targets."
        )
    out.append("")
    return out
