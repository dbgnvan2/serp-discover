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

#: T.5. The spec named `data.site.metrics.brand_authority.fetch` and
#: `data.site.linking.domain.filter.recently_gained` / `.recently_lost`.
#: Neither exists: the API CamelCases each dot-segment, so it answered
#: "Action not found: DataSiteMetricsBrand_authorityFetch". The real names
#: were found by probing (invalid method names cost no rows).
BRAND_AUTHORITY_METHOD = "data.site.metrics.brand.authority.fetch"
LINKING_DOMAIN_METHOD = "data.site.linking.domain.list"

#: Allowed `options.filters` values, from the API's own error message:
#: external, follow, nofollow, deleted, not_deleted. There is **no**
#: recently-gained/recently-lost filter and no time window of any kind, so
#: the spec's "60-day momentum" cannot be computed from this endpoint. What
#: is available is lost-at-some-point vs currently-live, which is what this
#: module reports — under names that say so.
LOST_LINK_FILTERS = ("external", "deleted")
LIVE_LINK_FILTERS = ("external", "not_deleted")

DEFAULT_LINK_MOMENTUM_LIMIT = 10

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
        brand_authority: bool = False,
        client_anchor_texts: bool = False,
        link_momentum: bool = False,
        link_momentum_limit: int = DEFAULT_LINK_MOMENTUM_LIMIT,
    ) -> None:
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._scope = scope or DEFAULT_SCOPE
        self._locale = locale or DEFAULT_LOCALE
        self._max_competitors = int(max_competitors)
        self._ranking_keyword_limit = int(ranking_keyword_limit)
        self._anchor_text_limit = int(anchor_text_limit)
        self._brand_authority = bool(brand_authority)
        self._client_anchor_texts = bool(client_anchor_texts)
        self._link_momentum = bool(link_momentum)
        self._link_momentum_limit = int(link_momentum_limit)
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
            brand_authority=bool(
                (moz_cfg.get("brand_authority", {}) or {}).get("enabled", False)),
            client_anchor_texts=bool(
                comp_cfg.get("client_anchor_texts", False)),
            link_momentum=bool(
                (moz_cfg.get("link_momentum", {}) or {}).get("enabled", False)),
            link_momentum_limit=int(
                (moz_cfg.get("link_momentum", {}) or {}).get("limit")
                or DEFAULT_LINK_MOMENTUM_LIMIT),
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
        if self._brand_authority:
            per_domain += 1
        if self._link_momentum:
            per_domain += 2 * self._link_momentum_limit * ROWS_PER_OBJECT
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
        brand, brand_rows = self._fetch_brand_authority(domain)
        momentum, momentum_rows = self._fetch_link_momentum(domain)
        extra_rows = brand_rows + momentum_rows

        available = (bool(ranking.get("items")) or bool(anchors.get("items"))
                     or bool(brand.get("data_available")))
        if not available:
            statuses = {ranking.get("status"), anchors.get("status")}
            status = STATUS_ERROR if STATUS_ERROR in statuses else STATUS_NO_RECORD
            block = absent(status, "no ranking keywords or anchor text returned")
            block["ranking_keywords"] = ranking
            block["anchor_texts"] = anchors
            block["brand_authority"] = brand
            block["link_momentum"] = momentum
            return block, ranking_rows + anchor_rows + extra_rows

        return {
            "data_available": True,
            "status": STATUS_OK,
            "ranking_keywords": ranking,
            "anchor_texts": anchors,
            "brand_authority": brand,
            "link_momentum": momentum,
        }, ranking_rows + anchor_rows + extra_rows

    def _fetch_ranking_keywords(self, domain: str) -> tuple[dict, int]:
        """Keywords *domain* ranks for. `locale` belongs inside target_query."""
        # `page.limit` is what constrains the response — and therefore the
        # bill. A bare top-level `limit` is ignored: the call still returns a
        # full page and still costs a row per object, so the cap would trim
        # the list after paying for all of it (learnings P9).
        data = {
            "target_query": {
                "query": domain,
                "scope": self._scope,
                "locale": self._locale,
            },
            "page": {"limit": self._ranking_keyword_limit},
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
        # This method pages via `offset.limit`, not `page.limit` — see the
        # note in _fetch_ranking_keywords about caps that do not cap the cost.
        data = {
            "site_query": {"query": domain, "scope": self._scope},
            "offset": {"limit": self._anchor_text_limit},
        }
        result, status = self._call(ANCHOR_TEXT_METHOD, data, domain)
        if result is None:
            return self._page_block([], [], status), 0

        raw = result.get("anchor_texts") or []
        items = [
            {field: entry.get(field) for field in ANCHOR_TEXT_FIELDS}
            for entry in raw if isinstance(entry, dict)
        ][:self._anchor_text_limit]
        return self._page_block(items, raw, status), len(raw) * ROWS_PER_OBJECT

    def anchor_texts_for(self, domain: str) -> dict:
        """Fetch the anchor-text distribution for one domain — the client's own.

        Purpose: let Tool 2's anchor-spam detector see the client's own inbound
                 anchors, which is the case that would surface negative SEO
                 aimed at the client.
        Spec:    moz_api_upgrade_spec_v1.md#T.4
        Tests:   test_moz_competitor.py::TestClientAnchorTexts

        The client is deliberately absent from ``moz.domains`` — the handoff
        excludes it by design — so its anchors travel in the ``moz.client``
        entry instead. Without this the own-site branch of Tool 2's detector
        could never fire: the capability was tested and documented but had no
        data path (learnings P21).

        Uncached, like :meth:`brand_authority_for`: one domain per run.
        """
        if not domain:
            return {"status": "not_fetched", "data_available": False,
                    "items": [], "returned": 0, "truncated": False}
        block, rows = self._fetch_anchor_text(domain.lower())
        self.rows_consumed += rows
        return block

    def brand_authority_for(self, domain: str) -> dict:
        """Fetch Brand Authority for one domain — typically the client's own.

        Purpose: give the handoff the client's own Brand Authority next to its
                 competitors', so the score has a reference point.
        Spec:    moz_api_upgrade_spec_v1.md#T.5
        Tests:   test_moz_competitor.py::TestClientBrandAuthority

        Deliberately uncached. One row per run is cheaper than a fourth cache
        table and its own staleness rules, and at roughly one run a week that
        is ~4 rows a month. Returns the same absent-safe block shape as the
        competitor path, so a missing score is never a 0.
        """
        if not domain:
            return {"status": "not_fetched", "data_available": False}
        block, rows = self._fetch_brand_authority(domain.lower())
        self.rows_consumed += rows
        return block

    def _fetch_brand_authority(self, domain: str) -> tuple[dict, int]:
        """Moz Brand Authority for *domain* (T.5). One row per call.

        Off unless ``moz.brand_authority.enabled``. Absent-safe: a domain Moz
        has no score for reports ``data_available: False`` and carries no
        score field, never a 0 — Brand Authority is a 0-100 scale on which 0
        is a real and damning value, so a fabricated one would be a
        substantive false claim (spec design principle 3).
        """
        if not self._brand_authority:
            return {"status": "disabled", "data_available": False}, 0

        data = {"site_query": {"query": domain, "scope": self._scope}}
        result, status = self._call(BRAND_AUTHORITY_METHOD, data, domain)
        if result is None:
            return {"status": status, "data_available": False}, 0

        score = (result.get("site_metrics") or {}).get("brand_authority_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return {
                "status": STATUS_NO_RECORD, "data_available": False,
                "reason": "Moz returned no brand authority score",
            }, ROWS_PER_OBJECT
        return {
            "status": STATUS_OK, "data_available": True, "score": score,
        }, ROWS_PER_OBJECT

    def _fetch_link_momentum(self, domain: str) -> tuple[dict, int]:
        """Lost vs currently-live linking domains for *domain* (T.5).

        Off unless ``moz.link_momentum.enabled``.

        **This is not the 60-day gained/lost momentum the spec described.**
        That does not exist on this API: ``data.site.linking.domain.list``
        accepts only ``external, follow, nofollow, deleted, not_deleted``
        (the API's own error message enumerates them), and there is no time
        window on any of them. What is reported here is "lost at some point"
        against "currently live", which is the nearest real signal — named
        `lost` and `live` rather than `gained`/`recently_*` so it cannot be
        read as something it is not.
        """
        if not self._link_momentum:
            return {"status": "disabled", "data_available": False}, 0

        blocks, rows = {}, 0
        for key, filters in (("lost", LOST_LINK_FILTERS),
                             ("live", LIVE_LINK_FILTERS)):
            data = {
                "site_query": {"query": domain, "scope": self._scope},
                "offset": {"limit": self._link_momentum_limit},
                "options": {"filters": list(filters)},
            }
            result, status = self._call(LINKING_DOMAIN_METHOD, data, domain)
            if result is None:
                blocks[key] = self._page_block([], [], status)
                continue
            raw = result.get("linking_domains") or []
            items = [
                {
                    "root_domain": (entry.get("site_metrics") or {}).get("root_domain"),
                    "domain_authority": (entry.get("site_metrics") or {}).get(
                        "domain_authority"),
                }
                for entry in raw if isinstance(entry, dict)
            ][:self._link_momentum_limit]
            blocks[key] = self._page_block(items, raw, status)
            rows += len(raw) * ROWS_PER_OBJECT

        available = any(b.get("items") for b in blocks.values())
        return {
            "status": STATUS_OK if available else STATUS_NO_RECORD,
            "data_available": available,
            "window": "none — Moz exposes no time-filtered link data on this plan",
            **blocks,
        }, rows

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
            # Idempotent migration for the T.5 columns, mirroring the
            # CREATE TABLE IF NOT EXISTS discipline used elsewhere.
            existing = {
                row[1] for row in
                conn.execute(f"PRAGMA table_info({CACHE_TABLE})").fetchall()
            }
            for column in ("brand_authority", "link_momentum"):
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE {CACHE_TABLE} ADD COLUMN {column} TEXT")
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
                    f"fetched_at, brand_authority, link_momentum "
                    f"FROM {CACHE_TABLE} "
                    f"WHERE scope=? AND locale=? AND domain IN ({placeholders})",
                    [self._scope, self._locale, *chunk],
                ).fetchall())

        for (domain, status, ranking, anchors, fetched_at,
             brand, momentum) in rows:
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
                "brand_authority": _decode_signal(brand),
                "link_momentum": _decode_signal(momentum),
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
                json.dumps(block.get("brand_authority") or {}),
                json.dumps(block.get("link_momentum") or {}),
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
                f"anchor_texts, fetched_at, brand_authority, link_momentum) "
                f"VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()


def _decode_signal(raw) -> dict:
    """Decode a cached T.5 sub-block, degrading to an honest absent block."""
    if not raw:
        return {"status": "not_fetched", "data_available": False}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable T.5 blob in %s — treating as absent", CACHE_TABLE)
        decoded = None
    if not isinstance(decoded, dict):
        return {"status": "not_fetched", "data_available": False}
    return decoded


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

    block = {
        "generated_at": datetime.now(_UTC).isoformat(),
        "locale": client._locale,
        "scope": client._scope,
        "domains": results,
    }
    # The client's own signals, so the competitor numbers have a reference
    # point and so Tool 2's own-site checks have data to run on. The client is
    # never added to `domains` — the handoff excludes it by design, and a
    # reference point is not a competitor entry.
    client_entry = {}
    if client_domain and client._brand_authority:
        client_entry["brand_authority"] = client.brand_authority_for(client_domain)
    if client_domain and client._client_anchor_texts:
        # Without this the client's anchors never leave Tool 1, so Tool 2's
        # own-site anchor-spam branch — the one that would reveal a negative-SEO
        # campaign aimed at the client — had no data path at all (P21).
        client_entry["anchor_texts"] = client.anchor_texts_for(client_domain)
    if client_entry:
        block["client"] = {"domain": client_domain.lower(), **client_entry}
    return block
