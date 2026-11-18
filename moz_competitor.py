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
from datetime import datetime, timedelta

from domain_utils import normalize_domain
from moz_jsonrpc import MozRpcError, moz_call
import db_connect
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

#: The four signals a competitor block is made of, each fetched, cached and
#: reported on its own. One failed sub-call used to freeze all four for 30
#: days — the top-level status was `ok` whenever ANY sub-call returned data,
#: and the cache gated on that — so its empty `items: []` read as a fact
#: about the competitor (D-C-10 / D2b.9-D2b.13).
SIGNAL_RANKING = "ranking_keywords"
SIGNAL_ANCHORS = "anchor_texts"
SIGNAL_BRAND = "brand_authority"
SIGNAL_MOMENTUM = "link_momentum"
SIGNALS = (SIGNAL_RANKING, SIGNAL_ANCHORS, SIGNAL_BRAND, SIGNAL_MOMENTUM)

#: Per-signal `fetched_at` cache column. A ranking-keywords block collected
#: 27 days ago must not read as same-day because an anchor-text block was
#: refreshed today (P6, D2b.13).
_SIGNAL_AT = {signal: f"{signal}_at" for signal in SIGNALS}

#: A signal we have not got, and why — never a bare empty list (D2b.14).
STATUS_NOT_FETCHED = "not_fetched"
STATUS_DISABLED = "disabled"


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

        # Per signal, not per domain: a domain with three fresh signals and
        # one that failed last run needs one call, not four (D2b.11/D2b.12).
        cached, needed = self._cache_lookup(unique)
        to_fetch = [d for d in unique if needed.get(d)]
        for domain in unique:
            if not needed.get(domain):
                results[domain] = self._assemble(cached.get(domain, {}))

        if len(to_fetch) > self._max_competitors:
            skipped = to_fetch[self._max_competitors:]
            to_fetch = to_fetch[:self._max_competitors]
            logger.warning(
                "Moz competitor: cap %d reached — %d of %d domain(s) needing a "
                "fetch skipped (%s)",
                self._max_competitors, len(skipped),
                len(skipped) + len(to_fetch), ", ".join(skipped),
            )
            for domain in skipped:
                # What is cached is still served; only the rest is skipped.
                results[domain] = self._assemble(
                    cached.get(domain, {}), STATUS_SKIPPED_CAP,
                    f"per-run cap of {self._max_competitors} competitors reached")

        costs = {d: sum(self._signal_cost(sig) for sig in needed[d])
                 for d in to_fetch}
        budget = row_budget(sum(costs.values()), "competitor") if to_fetch else None

        fresh: dict[str, dict] = {}
        for index, domain in enumerate(to_fetch):
            if budget is not None and budget < costs[domain]:
                remaining = to_fetch[index:]
                logger.warning(
                    "Moz competitor: quota exhausted — %d domain(s) skipped "
                    "rather than overspending (%s)",
                    len(remaining), ", ".join(remaining),
                )
                for skipped_domain in remaining:
                    results[skipped_domain] = self._assemble(
                        cached.get(skipped_domain, {}), STATUS_SKIPPED_QUOTA,
                        "monthly row quota would be exceeded")
                break
            blocks, billed = self._fetch_one(domain, needed[domain])
            fresh[domain] = blocks
            results[domain] = self._assemble({**cached.get(domain, {}), **blocks})
            self.rows_consumed += billed
            if budget is not None:
                budget -= billed

        if fresh:
            self._cache_store(fresh)
            logger.info(
                "Moz competitor: %d domain(s) fetched (%s), %d row(s) billed "
                "this session", len(fresh),
                ", ".join(f"{d}: {'+'.join(needed[d])}" for d in fresh),
                self.rows_consumed,
            )
        return results

    # ------------------------------------------------------------------
    # Internal: signals
    # ------------------------------------------------------------------

    def enabled_signals(self) -> tuple[str, ...]:
        """The signals this configuration asks for. The others are not gaps.

        A signal switched off by config is not a partial block (D2b.9) and
        must not trigger a refetch every run.
        """
        signals = [SIGNAL_RANKING, SIGNAL_ANCHORS]
        if self._brand_authority:
            signals.append(SIGNAL_BRAND)
        if self._link_momentum:
            signals.append(SIGNAL_MOMENTUM)
        return tuple(signals)

    def _signal_cost(self, signal: str) -> int:
        """Worst-case rows one signal bills: a full page from each method."""
        if signal == SIGNAL_RANKING:
            return self._ranking_keyword_limit * ROWS_PER_OBJECT
        if signal == SIGNAL_ANCHORS:
            return self._anchor_text_limit * ROWS_PER_OBJECT
        if signal == SIGNAL_BRAND:
            return ROWS_PER_OBJECT
        if signal == SIGNAL_MOMENTUM:
            return 2 * self._link_momentum_limit * ROWS_PER_OBJECT
        return 0

    def _assemble(self, blocks: dict[str, dict],
                  missing_status: str | None = None, reason: str = "") -> dict:
        """One competitor block from its signals, however they were obtained.

        One definition for the fully cached, partially refetched and skipped
        paths alike. ``fetched_at`` is the OLDEST signal's: the block is only
        as current as its stalest part (P6, D2b.13). ``signals_missing``
        names every enabled signal not in hand, so a block with real ranking
        keywords and a skipped anchor fetch cannot present itself as complete
        just because `data_available` is true of one of its parts (P2).
        """
        out: dict[str, dict] = {}
        for signal in self.enabled_signals():
            if signal in blocks:
                out[signal] = blocks[signal]
                continue
            stub = {
                "status": missing_status or STATUS_NOT_FETCHED,
                "data_available": False,
                "reason": reason or "not fetched on this run",
            }
            if signal in (SIGNAL_RANKING, SIGNAL_ANCHORS):
                # The page shape, so a consumer reading `.get("items", [])`
                # finds the same keys it finds on a real block and the empty
                # list arrives with its explanation attached (P19).
                stub.update(items=[], returned=0, truncated=False)
            out[signal] = stub
        for signal in SIGNALS:
            # Switched off reports that rather than vanishing: a consumer
            # must tell "off" from "failed".
            out.setdefault(signal, {"status": STATUS_DISABLED,
                                    "data_available": False})

        ranking, anchors = out[SIGNAL_RANKING], out[SIGNAL_ANCHORS]
        available = (bool(ranking.get("items")) or bool(anchors.get("items"))
                     or bool(out[SIGNAL_BRAND].get("data_available")))
        stamps = sorted(
            b["fetched_at"] for b in out.values()
            if isinstance(b, dict) and b.get("fetched_at"))

        if not available and missing_status in (STATUS_SKIPPED_CAP,
                                                STATUS_SKIPPED_QUOTA):
            # Empty because we deliberately did not ask: the cap or the
            # quota, not the domain. "no_record" here would be this chunk's
            # own fault one level up (P1 — a skip is not a terminal absence).
            block = absent(missing_status, reason)
        elif not available:
            statuses = {ranking.get("status"), anchors.get("status")}
            status = STATUS_ERROR if STATUS_ERROR in statuses else STATUS_NO_RECORD
            block = absent(status, "no ranking keywords or anchor text returned")
        else:
            block = {"data_available": True, "status": STATUS_OK}
        block.update(out)
        # "Obtained" is the same test the cache uses: a real reading or a
        # measured absence. Anything else — a failed call, a skip, a signal
        # not asked for — is a gap, and a gap is named rather than left for
        # the consumer to infer from an empty list.
        missing_signals = [signal for signal in self.enabled_signals()
                           if out[signal].get("status") not in _CACHEABLE]
        block["complete"] = not missing_signals
        block["signals_missing"] = missing_signals
        if missing_signals and block.get("status") == STATUS_OK:
            block["reason"] = (
                "partial: " + ", ".join(missing_signals) + " not obtained")
        if stamps:
            block["fetched_at"] = stamps[0]
            block["signals_fetched_at"] = {
                signal: sub.get("fetched_at")
                for signal, sub in out.items() if isinstance(sub, dict)
            }
        return block

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_one(self, domain: str,
                   signals: tuple | list | None = None) -> tuple[dict, int]:
        """Fetch *signals* for *domain*. Returns ``({signal: block}, rows)``.

        Only the signals asked for — on a partial cache hit, the one that
        failed last run, not all four (D2b.12). Each block carries its own
        status and ``fetched_at``. Assembly is :meth:`_assemble`'s job.
        """
        fetchers = {
            SIGNAL_RANKING: self._fetch_ranking_keywords,
            SIGNAL_ANCHORS: self._fetch_anchor_text,
            SIGNAL_BRAND: self._fetch_brand_authority,
            SIGNAL_MOMENTUM: self._fetch_link_momentum,
        }
        wanted = tuple(signals) if signals is not None else self.enabled_signals()
        blocks: dict[str, dict] = {}
        billed = 0
        for signal in wanted:
            fetcher = fetchers.get(signal)
            if fetcher is None:
                continue
            block, rows = fetcher(domain)
            # Stamped at collection, so a block refreshed today cannot make
            # a 27-day-old sibling look current.
            block["fetched_at"] = datetime.now(_UTC).isoformat()
            blocks[signal] = block
            billed += rows
        return blocks, billed

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
            return {"status": STATUS_NOT_FETCHED, "data_available": False,
                    "items": [], "returned": 0, "truncated": False,
                    "reason": "no domain given"}
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
            return {"status": STATUS_NOT_FETCHED, "data_available": False}
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
            return {"status": STATUS_DISABLED, "data_available": False}, 0

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
            return {"status": STATUS_DISABLED, "data_available": False}, 0

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
        # This signal is two calls. If EITHER failed the signal is not an
        # answer, however much the other returned: a cacheable `ok` here
        # would freeze the failed half for the whole TTL and serve its
        # `items: []` as a fact about the domain — D-C-10 one level down.
        if any(b.get("status") == STATUS_ERROR for b in blocks.values()):
            rollup = STATUS_ERROR
        elif available:
            rollup = STATUS_OK
        else:
            rollup = STATUS_NO_RECORD
        return {
            "status": rollup,
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

        ``data_available`` and ``reason`` travel beside the items so
        ``items: []`` cannot be read as "this competitor has none": the list
        alone is identical for "Moz holds nothing" and "the call 503'd"
        (D2b.14).
        """
        if status == STATUS_ERROR:
            reason = ("the Moz call failed — this is not a measurement of the "
                      "domain, and the next run will ask again")
        elif status == STATUS_NO_RECORD and not items:
            reason = "Moz holds no data for this domain"
        else:
            reason = ""
        # `reason` is present on every block, empty when there is nothing to
        # say: one producer, one shape, so a consumer never reads None where
        # a sibling block has a string (learnings P19).
        return {
            "status": status,
            "data_available": bool(items),
            "items": items,
            "returned": len(items),
            "truncated": len(items) < len(raw),
            "reason": reason,
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
        with db_connect.connection(self._db_path) as conn:
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
            # D2b.10/D2b.13 — a per-signal fetched_at, so a signal can be
            # refreshed, expire or be absent on its own. NULL on an existing
            # database reads as "not recorded", so rows frozen by the old
            # whole-domain cache clear themselves on the next run.
            for column in _SIGNAL_AT.values():
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE {CACHE_TABLE} ADD COLUMN {column} TEXT")
            conn.commit()

    def _cache_lookup(self, domains: list[str]) -> tuple[dict[str, dict[str, dict]],
                                                          dict[str, list[str]]]:
        """Split each domain's signals into (fresh-cached, still-needed).

        Returns ``({domain: {signal: block}}, {domain: [signals to fetch]})``.
        Signals whose own ``fetched_at`` is inside the TTL are served; the
        rest are asked for. A failed signal is never cached, so it has no
        timestamp and is needed again next run (D-C-10 / D2b.11).
        """
        cached: dict[str, dict[str, dict]] = {}
        needed: dict[str, list[str]] = {}
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()
        wanted = self.enabled_signals()

        columns = ["domain"]
        for signal in SIGNALS:
            columns.extend([signal, _SIGNAL_AT[signal]])
        select = ", ".join(columns)

        rows = []
        with db_connect.connection(self._db_path) as conn:
            for start in range(0, len(domains), 500):
                chunk = domains[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT {select} FROM {CACHE_TABLE} "
                    f"WHERE scope=? AND locale=? AND domain IN ({placeholders})",
                    [self._scope, self._locale, *chunk],
                ).fetchall())

        by_domain = {row[0]: row[1:] for row in rows}
        for domain in domains:
            row = by_domain.get(domain)
            fresh: dict[str, dict] = {}
            if row is not None:
                for index, signal in enumerate(SIGNALS):
                    blob, stamp = row[index * 2], row[index * 2 + 1]
                    if not blob or not stamp or stamp < cutoff:
                        continue
                    decoded = (_decode(blob) if signal in
                               (SIGNAL_RANKING, SIGNAL_ANCHORS)
                               else _decode_signal(blob))
                    if decoded.get("status") not in _CACHEABLE:
                        # Belt and braces: a failure must not be served even
                        # if an older build managed to write one.
                        continue
                    # When this signal was collected, not when the handoff was
                    # assembled — a cached signal can be nearly TTL-old (P6).
                    decoded["fetched_at"] = stamp
                    fresh[signal] = decoded
            if fresh:
                cached[domain] = fresh
            missing = [signal for signal in wanted if signal not in fresh]
            if missing:
                needed[domain] = missing
        return cached, needed

    def _cache_store(self, fetched: dict[str, dict[str, dict]]) -> None:
        """Write the signals that answered, leaving the ones that failed unset.

        Column-wise, so a partial refetch does not blank the signals it did
        not ask for. A non-cacheable status is skipped entirely — no blob, no
        timestamp, so the next run asks again (D2b.9/D2b.10).
        """
        with db_connect.connection(self._db_path) as conn:
            for domain, blocks in fetched.items():
                storable = {
                    signal: block for signal, block in blocks.items()
                    if signal in SIGNALS and block.get("status") in _CACHEABLE
                }
                if not storable:
                    continue
                assignments, values = [], []
                for signal, block in storable.items():
                    assignments.append(f"{signal}=?")
                    assignments.append(f"{_SIGNAL_AT[signal]}=?")
                    values.append(json.dumps(block))
                    values.append(block.get("fetched_at")
                                  or datetime.now(_UTC).isoformat())
                # The row must exist before the column-wise update; `status`
                # and the legacy whole-row `fetched_at` are kept for
                # diagnostics only — nothing reads them to decide freshness.
                conn.execute(
                    f"INSERT OR IGNORE INTO {CACHE_TABLE} "
                    f"(domain, scope, locale) VALUES (?,?,?)",
                    (domain, self._scope, self._locale),
                )
                conn.execute(
                    f"UPDATE {CACHE_TABLE} SET {', '.join(assignments)}, "
                    f"status=?, fetched_at=? "
                    f"WHERE domain=? AND scope=? AND locale=?",
                    [*values, STATUS_OK, datetime.now(_UTC).isoformat(),
                     domain, self._scope, self._locale],
                )
            conn.commit()


def _decode_signal(raw) -> dict:
    """Decode a cached T.5 sub-block, degrading to an honest absent block."""
    if not raw:
        return {"status": STATUS_NOT_FETCHED, "data_available": False}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable T.5 blob in %s — treating as absent", CACHE_TABLE)
        decoded = None
    if not isinstance(decoded, dict):
        return {"status": STATUS_NOT_FETCHED, "data_available": False}
    return decoded


def _decode(raw) -> dict:
    """Decode a cached JSON blob, degrading to "not recorded".

    The fallback is deliberately NOT ``no_record``: that is in
    ``_CACHEABLE``, so an unreadable blob would be served as a measured
    absence and would block its own refetch for the rest of the TTL
    (D-C-10 again, via the decode path).
    """
    if not raw:
        return {"status": STATUS_NOT_FETCHED, "data_available": False,
                "items": [], "returned": 0, "truncated": False,
                "reason": "nothing recorded for this signal"}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable blob in %s — treating as not recorded",
                       CACHE_TABLE)
        decoded = None
    if not isinstance(decoded, dict):
        return {"status": STATUS_NOT_FETCHED, "data_available": False,
                "items": [], "returned": 0, "truncated": False,
                "reason": "the cached blob could not be read"}
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
    # Review chunk X: one host, one answer, on both sides of the handoff.
    # This function lower-cased the netloc and kept `www.`, so the handoff's
    # `moz.domains` keys were the `www.` form while `targets[].domain` next to
    # them was canonical — the same file disagreeing with itself. Worse, the
    # two exclusions depended on the form the config happened to use: the
    # client test was the substring test D-C-08 removed elsewhere (a bare
    # `livingsystems.ca` dropped `notlivingsystems.ca` as "the client"), and
    # the omit list only matched a host written in the same form. Which
    # competitors are measured, and which the Moz row budget is spent on, then
    # turned on a `www.` somebody typed in `config.yml`.
    client = normalize_domain(client_domain)
    omit = {normalize_domain(d) for d in (omit_from_audit or []) if d}
    domains, seen = [], set()
    for item in all_organic or []:
        if item.get("Query_Label") == "S":
            continue
        url = item.get("Link") or item.get("url", "")
        if not url or url == "N/A":
            continue
        domain = normalize_domain(url)
        if not domain or domain in seen:
            continue
        if client and (domain == client or domain.endswith("." + client)):
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
    # Every host this block publishes — the `domains` keys, the `client` entry,
    # and the host the paid Moz calls are billed under — is the one canonical
    # form (review chunk X, owner decision 4). The cache PK is
    # (domain, scope, locale), so a `www.` from `config.yml` would query and
    # bill the client's own site under a key no other path uses (P5).
    client_domain = normalize_domain(client_domain) if client_domain else ""
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
        # Assembly time, NOT collection time — per-domain `fetched_at` carries
        # that, because a cached domain can be far older than this timestamp.
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
        client_entry["fetched_at"] = datetime.now(_UTC).isoformat()
    if client_entry:
        block["client"] = {"domain": client_domain, **client_entry}
    return block
