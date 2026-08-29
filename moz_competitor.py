"""
moz_competitor.py
~~~~~~~~~~~~~~~~~
Per-competitor Moz signals: ranking keywords and anchor-text distribution.

Purpose: enrich the competitor handoff with what each competitor domain
         actually ranks for and how the web links to it.
Spec:    moz_api_upgrade_spec_v1.md#T.4
Tests:   test_moz_competitor.py

Two methods per domain, both confirmed live on 2026-08-28:

- ``data.site.ranking.keyword.list`` — ``{"target_query": {query, scope,
  locale}}``. Note ``locale`` sits **inside** ``target_query`` here, unlike
  the keyword methods where it sits in ``serp_query``; the API rejects the
  call otherwise. Returns ``ranking_keywords`` with keyword, ranking_page,
  rank_position, difficulty and volume.
- ``data.site.anchor.text.list`` — ``{"site_query": {query, scope}}``.
  Returns ``anchor_texts`` with text, external_root_domains, external_pages.

Both bill 1 row per object returned, so cost scales with how much the
competitor actually has: a domain ranking for 2 keywords costs 2 rows, while
anchor text returns a full page (25 by default) and costs 25.

Paging
------
Both methods paginate and neither is exhausted here. Taking the top page is
deliberate — the handoff wants a competitor's strongest signals, not its
complete index, and exhausting anchor text alone would multiply the row cost
without changing any decision. What that leaves behind is logged rather than
passed over in silence (learnings P9/E6): the result records
``truncated: true`` when a full page came back, so a consumer can tell "this
is the top 25" from "this is all there is".
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta

from moz_jsonrpc import MozRpcError, moz_call
from moz_keywords import (
    NO_RECORD_CODE,
    NO_RECORD_STATUS,
    STATUS_ERROR,
    STATUS_NO_RECORD,
    STATUS_OK,
    STATUS_SKIPPED_CAP,
    STATUS_SKIPPED_QUOTA,
    _CACHEABLE,
    absent,
    row_budget,
)

logger = logging.getLogger(__name__)

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

RANKING_KEYWORDS_METHOD = "data.site.ranking.keyword.list"
ANCHOR_TEXT_METHOD = "data.site.anchor.text.list"

CACHE_TABLE = "moz_competitor_cache"

DEFAULT_SCOPE = "domain"
DEFAULT_LOCALE = "en-CA"
DEFAULT_MAX_COMPETITORS = 3
DEFAULT_RANKING_KEYWORD_LIMIT = 50
DEFAULT_ANCHOR_TEXT_LIMIT = 25

#: Rows billed per object returned, measured live 2026-08-28.
ROWS_PER_OBJECT = 1

RANKING_KEYWORD_FIELDS = (
    "keyword", "ranking_page", "rank_position", "difficulty", "volume",
)
ANCHOR_TEXT_FIELDS = ("text", "external_root_domains", "external_pages")


class MozCompetitorClient:
    """Fetches and caches per-domain competitor signals.

    Parameters
    ----------
    db_path, cache_ttl_days:
        Cache location and lifetime, matching the other Moz clients.
    scope, locale:
        Moz query context. Part of the cache key — both change the answer.
    max_competitors:
        Per-run domain cap.
    ranking_keyword_limit, anchor_text_limit:
        How many objects to keep per method. Each kept object costs a row.
    """

    def __init__(
        self,
        db_path: str = "serp_data.db",
        cache_ttl_days: int = 30,
        scope: str = DEFAULT_SCOPE,
        locale: str = DEFAULT_LOCALE,
        max_competitors: int = DEFAULT_MAX_COMPETITORS,
        ranking_keyword_limit: int = DEFAULT_RANKING_KEYWORD_LIMIT,
        anchor_text_limit: int = DEFAULT_ANCHOR_TEXT_LIMIT,
    ) -> None:
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._scope = scope or DEFAULT_SCOPE
        self._locale = locale or DEFAULT_LOCALE
        self._max_competitors = int(max_competitors)
        self._ranking_keyword_limit = int(ranking_keyword_limit)
        self._anchor_text_limit = int(anchor_text_limit)
        self.rows_consumed = 0
        self._init_cache_table()

    @classmethod
    def from_config(cls, config: dict, db_path: str = "serp_data.db") -> "MozCompetitorClient":
        """Build a client from the ``moz.competitor`` block of a config.

        Purpose: one config→argument mapping shared by every front end (P25).
        Spec:    moz_api_upgrade_spec_v1.md#T.4
        Tests:   test_moz_competitor.py::TestFromConfig
        """
        moz_cfg = config.get("moz", {}) or {}
        comp_cfg = moz_cfg.get("competitor", {}) or {}
        return cls(
            db_path=db_path,
            cache_ttl_days=int(moz_cfg.get("cache_ttl_days", 30)),
            scope=comp_cfg.get("scope") or DEFAULT_SCOPE,
            locale=comp_cfg.get("locale") or DEFAULT_LOCALE,
            max_competitors=int(
                comp_cfg.get("max_competitors") or DEFAULT_MAX_COMPETITORS),
            ranking_keyword_limit=int(
                comp_cfg.get("ranking_keyword_limit")
                or DEFAULT_RANKING_KEYWORD_LIMIT),
            anchor_text_limit=int(
                comp_cfg.get("anchor_text_limit") or DEFAULT_ANCHOR_TEXT_LIMIT),
        )

    @staticmethod
    def is_enabled(config: dict) -> bool:
        """Whether competitor enrichment is switched on for this config."""
        moz_cfg = (config.get("moz", {}) if isinstance(config, dict) else {}) or {}
        comp_cfg = moz_cfg.get("competitor", {}) or {}
        return bool(moz_cfg.get("enabled", True) and comp_cfg.get("enabled", False))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, domains: list[str]) -> dict[str, dict]:
        """Return a signal block for every domain in *domains*.

        Every input domain appears in the result — a domain that could not be
        fetched carries an explicit absent block rather than being dropped, so
        "no entry" can never be misread as "no backlinks" (learnings P2).
        """
        if not domains:
            return {}

        unique = list(dict.fromkeys(d.lower() for d in domains if d))
        results: dict[str, dict] = {}

        cached, to_fetch = self._cache_lookup(unique)
        results.update(cached)

        if len(to_fetch) > self._max_competitors:
            skipped = to_fetch[self._max_competitors:]
            to_fetch = to_fetch[:self._max_competitors]
            logger.warning(
                "Moz competitor: cap %d reached — %d of %d uncached domain(s) "
                "skipped (%s)",
                self._max_competitors, len(skipped),
                len(skipped) + len(to_fetch), ", ".join(skipped),
            )
            for domain in skipped:
                results[domain] = absent(
                    STATUS_SKIPPED_CAP,
                    f"per-run cap of {self._max_competitors} competitors reached",
                )

        # Worst case per domain: a full page from each method.
        per_domain = (self._ranking_keyword_limit + self._anchor_text_limit) \
            * ROWS_PER_OBJECT
        budget = row_budget(len(to_fetch) * per_domain, "competitor") \
            if to_fetch else None

        fresh: dict[str, dict] = {}
        for index, domain in enumerate(to_fetch):
            if budget is not None and budget < per_domain:
                remaining = to_fetch[index:]
                logger.warning(
                    "Moz competitor: quota exhausted — %d domain(s) skipped "
                    "rather than overspending (%s)",
                    len(remaining), ", ".join(remaining),
                )
                for skipped_domain in remaining:
                    results[skipped_domain] = absent(
                        STATUS_SKIPPED_QUOTA,
                        "monthly row quota would be exceeded",
                    )
                break
            block, billed = self._fetch_one(domain)
            fresh[domain] = block
            self.rows_consumed += billed
            if budget is not None:
                budget -= billed

        if fresh:
            self._cache_store(fresh)
            logger.info(
                "Moz competitor: %d domain(s) fetched, %d row(s) billed this "
                "session", len(fresh), self.rows_consumed,
            )
        results.update(fresh)
        return results

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_one(self, domain: str) -> tuple[dict, int]:
        """Fetch both signals for *domain*. Returns ``(block, rows_billed)``.

        A failure on one method does not discard the other: each carries its
        own status, so a domain with anchor text but no ranking data reports
        exactly that.
        """
        ranking, ranking_rows = self._fetch_ranking_keywords(domain)
        anchors, anchor_rows = self._fetch_anchor_text(domain)

        available = bool(ranking.get("items")) or bool(anchors.get("items"))
        if not available:
            statuses = {ranking.get("status"), anchors.get("status")}
            status = STATUS_ERROR if STATUS_ERROR in statuses else STATUS_NO_RECORD
            block = absent(status, "no ranking keywords or anchor text returned")
            block["ranking_keywords"] = ranking
            block["anchor_texts"] = anchors
            return block, ranking_rows + anchor_rows

        return {
            "data_available": True,
            "status": STATUS_OK,
            "ranking_keywords": ranking,
            "anchor_texts": anchors,
        }, ranking_rows + anchor_rows

    def _fetch_ranking_keywords(self, domain: str) -> tuple[dict, int]:
        """Keywords *domain* ranks for. `locale` belongs inside target_query."""
        data = {
            "target_query": {
                "query": domain,
                "scope": self._scope,
                "locale": self._locale,
            },
            "limit": self._ranking_keyword_limit,
        }
        result, status = self._call(RANKING_KEYWORDS_METHOD, data, domain)
        if result is None:
            return self._page_block([], [], status), 0

        raw = result.get("ranking_keywords") or []
        items = [
            {field: entry.get(field) for field in RANKING_KEYWORD_FIELDS}
            for entry in raw if isinstance(entry, dict)
        ][:self._ranking_keyword_limit]
        return self._page_block(items, raw, status), len(raw) * ROWS_PER_OBJECT

    def _fetch_anchor_text(self, domain: str) -> tuple[dict, int]:
        """Anchor-text distribution pointing at *domain*."""
        data = {"site_query": {"query": domain, "scope": self._scope}}
        result, status = self._call(ANCHOR_TEXT_METHOD, data, domain)
        if result is None:
            return self._page_block([], [], status), 0

        raw = result.get("anchor_texts") or []
        items = [
            {field: entry.get(field) for field in ANCHOR_TEXT_FIELDS}
            for entry in raw if isinstance(entry, dict)
        ][:self._anchor_text_limit]
        return self._page_block(items, raw, status), len(raw) * ROWS_PER_OBJECT

    @staticmethod
    def _page_block(items: list, raw: list, status: str) -> dict:
        """Wrap items with an honest note about what the page left behind.

        ``truncated`` distinguishes "this is the top N" from "this is all
        there is" — a caller reading a capped list as complete would
        understate a competitor (learnings P9).
        """
        return {
            "status": status,
            "items": items,
            "returned": len(items),
            "truncated": len(items) < len(raw),
        }

    def _call(self, method: str, data: dict, domain: str):
        """Call *method*, classifying absence apart from failure.

        Returns ``(result | None, status)``.
        """
        try:
            return moz_call(method, data), STATUS_OK
        except MozRpcError as exc:
            if exc.status == NO_RECORD_STATUS or exc.code == NO_RECORD_CODE:
                logger.info("Moz has no %s data for %r", method, domain)
                return None, STATUS_NO_RECORD
            logger.warning("Moz %s failed for %r: %s", method, domain, exc)
            return None, STATUS_ERROR
        except RuntimeError as exc:
            logger.warning("Moz %s unavailable for %r: %s", method, domain, exc)
            return None, STATUS_ERROR

    # ------------------------------------------------------------------
    # Internal: cache
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    domain           TEXT NOT NULL,
                    scope            TEXT NOT NULL,
                    locale           TEXT NOT NULL,
                    status           TEXT,
                    ranking_keywords TEXT,
                    anchor_texts     TEXT,
                    fetched_at       TEXT,
                    PRIMARY KEY (domain, scope, locale)
                )
            """)
            conn.commit()

    def _cache_lookup(self, domains: list[str]) -> tuple[dict[str, dict], list[str]]:
        cached: dict[str, dict] = {}
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()

        rows = []
        with sqlite3.connect(self._db_path) as conn:
            for start in range(0, len(domains), 500):
                chunk = domains[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT domain, status, ranking_keywords, anchor_texts, "
                    f"fetched_at FROM {CACHE_TABLE} "
                    f"WHERE scope=? AND locale=? AND domain IN ({placeholders})",
                    [self._scope, self._locale, *chunk],
                ).fetchall())

        for domain, status, ranking, anchors, fetched_at in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            if status == STATUS_NO_RECORD:
                cached[domain] = absent(
                    STATUS_NO_RECORD, "Moz holds no competitor data for this domain")
                continue
            if status != STATUS_OK:
                continue  # never serve a cached failure
            cached[domain] = {
                "data_available": True,
                "status": STATUS_OK,
                "ranking_keywords": _decode(ranking),
                "anchor_texts": _decode(anchors),
            }

        to_fetch = [d for d in domains if d not in cached]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        fetched_at = datetime.now(_UTC).isoformat()
        rows = [
            (
                domain, self._scope, self._locale, block.get("status"),
                json.dumps(block.get("ranking_keywords") or {}),
                json.dumps(block.get("anchor_texts") or {}),
                fetched_at,
            )
            for domain, block in results.items()
            if block.get("status") in _CACHEABLE
        ]
        if not rows:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(domain, scope, locale, status, ranking_keywords, "
                f"anchor_texts, fetched_at) VALUES (?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()


def _decode(raw) -> dict:
    """Decode a cached JSON blob, degrading to an empty block."""
    if not raw:
        return {"status": STATUS_NO_RECORD, "items": [],
                "returned": 0, "truncated": False}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable blob in %s — treating as empty", CACHE_TABLE)
        decoded = None
    if not isinstance(decoded, dict):
        return {"status": STATUS_NO_RECORD, "items": [],
                "returned": 0, "truncated": False}
    return decoded


def competitor_domains(all_organic, client_domain, omit_from_audit=None) -> list[str]:
    """Return the competitor domains present in *all_organic*, in rank order.

    Purpose: reuse the audit's existing domain resolution rather than
             introducing a second competitor list that can drift from it.
    Spec:    moz_api_upgrade_spec_v1.md#T.4
    Tests:   test_moz_competitor.py::TestDomainResolution

    Applies the same exclusions the handoff itself applies — the client's own
    domain and the configured omit list — and skips "S"-label situational
    probe rows, which never feed the handoff.
    """
    from urllib.parse import urlparse

    client = (client_domain or "").lower()
    omit = {d.lower() for d in (omit_from_audit or [])}
    domains, seen = [], set()
    for item in all_organic or []:
        if item.get("Query_Label") == "S":
            continue
        url = item.get("Link") or item.get("url", "")
        if not url or url == "N/A":
            continue
        domain = urlparse(url).netloc.lower()
        if not domain or domain in seen:
            continue
        if domain == client or (client and client in domain):
            continue
        if domain in omit:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def build_handoff_block(config, all_organic, client_domain,
                        omit_from_audit=None, db_path="serp_data.db"):
    """Build the optional ``moz`` block for the competitor handoff.

    Purpose: give serp_audit one call to make, and keep the enable/resolve/
             fetch decision in the module that owns it.
    Spec:    moz_api_upgrade_spec_v1.md#T.4
    Tests:   test_moz_competitor.py::TestHandoffBlock

    Returns ``None`` when disabled or when nothing could be fetched, in which
    case the handoff stays a byte-identical v1.0 document that Tool 2 accepts
    unchanged.
    """
    if not MozCompetitorClient.is_enabled(config):
        return None
    domains = competitor_domains(all_organic, client_domain, omit_from_audit)
    if not domains:
        return None
    try:
        client = MozCompetitorClient.from_config(config, db_path=db_path)
        results = client.fetch(domains)
    except Exception as exc:  # an optional signal must never abort the run
        logger.warning("Moz competitor signals unavailable: %s", exc)
        return None
    if not results:
        return None
    return {
        "generated_at": datetime.now(_UTC).isoformat(),
        "locale": client._locale,
        "scope": client._scope,
        "domains": results,
    }
