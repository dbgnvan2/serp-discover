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
from urllib.parse import urlparse

from classifiers import EntityClassifier
from domain_utils import normalize_domain
import db_connect

logger = logging.getLogger(__name__)

CITATIONS_TABLE = "ai_citations"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def domain_of(url: str) -> str:
    """Lower-cased host, ``www.`` stripped. Never raises.

    Delegates to ``domain_utils.normalize_domain`` — one definition of which
    host is which, so this module cannot disagree with the override lookup or
    the handoff about the same URL (review chunk Y1).
    """
    try:
        return normalize_domain(url)
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
    client = normalize_domain(client_domain)

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
    return unattributed_citations(table)[0][:limit]


def unattributed_citations(table: list[dict]) -> tuple[
        list[tuple[str, int]], int, int]:
    """``(domain counts, citations with no readable host, total citations)``.

    A URL the parser could not read a host from is skipped — it cannot be an
    outreach target — but the count is returned so the section can say so.
    Dropping it silently built the shortlist over fewer citations than the
    table above it lists (P2, review chunk Y3).
    """
    counts: dict[str, int] = {}
    dropped = 0
    total = 0
    for row in table:
        cites = int(row.get("cite_count") or 0)
        total += cites
        dom = row["domain"]
        if dom:
            counts[dom] = counts.get(dom, 0) + cites
        else:
            dropped += cites
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered, dropped, total


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
    with db_connect.connection(db_path) as conn:
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
    with db_connect.connection(db_path) as conn:
        # Idempotent per (run_ts, engine): replace this engine's rows for the run so
        # a re-save appends no duplicates (P8, matching aio_exposure/commodity).
        conn.execute(f"DELETE FROM {CITATIONS_TABLE} WHERE run_ts = ? AND engine = ?",
                     (run_ts, engine))
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
    with db_connect.connection(db_path) as conn:
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


def unattributed_brands(table: list[dict],
                        categories: list[str] | None = None
                        ) -> tuple[int, int, int]:
    """``(citations from a known brand, citations from none, total)``.

    Counted by cite count, not by row: a brand the gazetteer does not know is
    the thing the reader is meant to add to `known_brands`, and the table's
    per-row "—" could not tell "this engine cites nobody we track" from "we
    track everybody it cites" (P2/P9, review chunk Y5).

    With *categories*, only rows in those classifier categories are counted.
    A directory or a publisher has no brand by design, so the whole-table
    figure is large on every run; the figure for the categories where a rival
    would sit is the one worth acting on (cold review of chunk Y5).
    """
    attributed = 0
    unattributed = 0
    for row in table or []:
        if categories is not None and row.get("category") not in categories:
            continue
        count = int(row.get("cite_count") or 0)
        if row.get("brand"):
            attributed += count
        else:
            unattributed += count
    return attributed, unattributed, attributed + unattributed


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

def render_citation_section(engine: str, table: list[dict],
                            top_n: int = 40,
                            brand_relevant_categories: list[str] | None = None
                            ) -> list[str]:
    """Render the citations table for one engine + the outreach shortline.

    *brand_relevant_categories* is the editorial list from `config.yml`
    (`ai_visibility.brand_relevant_categories`) — the classifier categories in
    which a citation carrying no brand is a rival the gazetteer is missing.
    """
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
    if len(table) > top_n:
        # P2 — the table is truncated, so the reader is told by how much
        # rather than reading the top 40 as the whole citation set.
        out.append("")
        out.append(f"*Showing the {top_n} most-cited of {len(table)} "
                   f"distinct cited URLs.*")
    _ordered, _dropped, _total = unattributed_citations(table)
    shortlist = top_cited_domains(table)
    if _dropped:
        # Outside the shortlist block: when NOTHING could be attributed there
        # is no shortlist, and that is the case this count exists for (cold
        # review of chunk Y3).
        out.append("")
        out.append(
            f"*{_dropped} of {_total} citation(s) carry no readable host and "
            f"are not in the outreach shortlist"
            + ("—so this engine's answers produced no outreach target at all.*"
               if not _ordered else ".*"))
    _attributed, _unattributed, _brand_total = unattributed_brands(table)
    if _unattributed:
        out.append("")
        _tail = ("so none of this engine's citations is attributed to a brand "
                 "this run tracks"
                 if not _attributed else
                 # Not "in the table above": above `top_n` cited URLs the
                 # table is truncated, and some of the counted citations are
                 # in the rows it just said it was hiding.
                 "and carry no brand in this engine's citations")
        _focus = ""
        if brand_relevant_categories:
            _, _rival_unattributed, _rival_total = unattributed_brands(
                table, list(brand_relevant_categories))
            # A directory or a publisher carries no brand by design, so the
            # whole-table figure is high on every run and says nothing. The
            # figure for the categories a rival would sit in is the one to act
            # on, and it is printed even at zero, because zero is the answer
            # (P2, cold review of chunk Y5).
            _focus = (
                f" {_rival_unattributed} of the {_rival_total} citation(s) in "
                f"the categories a rival would sit in "
                f"({', '.join(brand_relevant_categories)}) carry no brand — "
                f"those are the ones to act on.")
        out.append(
            f"*{_unattributed} of {_brand_total} citation(s) are from a brand "
            f"not in `known_brands`, {_tail}.{_focus} Add the ones that matter "
            f"to `config.yml known_brands` (see "
            f"`brand_mentions_candidates_*.md`) so the next run attributes "
            f"them.*")
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
