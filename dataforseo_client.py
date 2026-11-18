"""
dataforseo_client.py
~~~~~~~~~~~~~~~~~~~~
DataForSEO Backlinks API client with SQLite caching.

Drop-in replacement for moz_client.MozClient — returns the same
``{url: {"da": int, "pa": int, "fetched_at": str}}`` dict so no
changes are needed in callers.

DataForSEO uses Domain Rank (0–100) as its DA-equivalent metric.
Since the API operates at the domain level, all URLs from the same
domain share one cached row.  Page Authority is not available from
this endpoint; ``pa`` mirrors ``da``.

Usage
-----
::

    from dataforseo_client import DataForSEOClient

    client = DataForSEOClient()
    metrics = client.get_domain_metrics([
        "https://psychologytoday.com/",
        "https://livingsystems.ca/",
    ])
    # {"https://psychologytoday.com/": {"da": 82, "pa": 82, ...},
    #  "https://livingsystems.ca/":    {"da": 19, "pa": 19, ...}}

Environment variables
---------------------
DATAFORSEO_LOGIN     Account email address (required)
DATAFORSEO_PASSWORD  API password from DataForSEO dashboard (required)

API reference
-------------
Endpoint : POST https://api.dataforseo.com/v3/backlinks/bulk_ranks/live
Auth     : HTTP Basic (login:password)
Batch    : up to 1000 domains per request (rank_scale: one_hundred → 0-100)
"""
from __future__ import annotations

import json
import logging
import os
from base64 import b64encode
from datetime import datetime, timedelta
from typing import Iterator
from urllib.parse import urlparse

import requests

from http_retry import post_with_transient_retry as _post_with_transient_retry

import feasibility
from domain_utils import normalize_domain
import db_connect

logger = logging.getLogger(__name__)

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DFS_ENDPOINT = "https://api.dataforseo.com/v3/backlinks/bulk_ranks/live"

#: Maximum domains per API request.
DFS_BATCH_SIZE: int = 1000

#: Documented default only. The live value is editorial, in `config.yml`
#: under `http_retry.timeout_seconds`, and reaches this call through
#: `http_retry` itself — one setting, every call site (P4/P25, review chunk
#: Y5). Kept so a direct caller that builds its own request still has a
#: timeout.
REQUEST_TIMEOUT: int = 30

# Fallback for how many days a cached absence (a row with no rank) stays good
# before it is asked again. The real value is `moz.negative_cache_ttl_days` in
# config.yml, passed in by the caller alongside cache_ttl_days — this client
# does not read config.yml itself (P4: the knob is in config, and there is one
# place that reads it).
DEFAULT_NEGATIVE_CACHE_TTL_DAYS = 7

CACHE_TABLE = "da_cache"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DataForSEOClient:
    """Thin wrapper around the DataForSEO bulk_domain_metrics endpoint.

    Parameters
    ----------
    db_path:
        SQLite database path. Defaults to ``"serp_data.db"``.
    cache_ttl_days:
        Days before a cached result is considered stale. Defaults to 30.
    negative_cache_ttl_days:
        Days before a cached *absence* (a row with no rank) is re-asked.
        Defaults to ``moz.negative_cache_ttl_days`` in ``config.yml``, and is
        clamped to ``cache_ttl_days``.

    Raises
    ------
    RuntimeError
        If ``DATAFORSEO_LOGIN`` or ``DATAFORSEO_PASSWORD`` env vars are absent.
    """

    def __init__(self, db_path: str = "serp_data.db", cache_ttl_days: int = 30,
                 negative_cache_ttl_days: int | None = None) -> None:
        login = os.getenv("DATAFORSEO_LOGIN", "").strip()
        password = os.getenv("DATAFORSEO_PASSWORD", "").strip()
        if not login or not password:
            raise RuntimeError(
                "DataForSEO credentials not found. "
                "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in your .env file."
            )
        token = b64encode(f"{login}:{password}".encode()).decode()
        self._auth_header = {"Authorization": f"Basic {token}"}
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        # A cached absence expires sooner than a cached measurement: see
        # _cache_lookup. Never longer than the positive TTL.
        if negative_cache_ttl_days is None:
            negative_cache_ttl_days = DEFAULT_NEGATIVE_CACHE_TTL_DAYS
        self._negative_cache_ttl = timedelta(
            days=min(int(negative_cache_ttl_days), cache_ttl_days))
        self._init_cache_table()

    # ------------------------------------------------------------------
    # Public API — same interface as MozClient.get_moz_metrics()
    # ------------------------------------------------------------------

    def get_domain_metrics(self, url_list: list[str]) -> dict[str, dict]:
        """Return DA-equivalent metrics for each URL in *url_list*.

        Deduplicates by domain (all URLs from the same domain share one
        cached row).  Results are served from cache when fresh.

        Returns
        -------
        dict mapping each input URL to
        ``{"da": int | None, "pa": int | None, "fetched_at": str}``.
        URLs whose domain could not be resolved or fetched are omitted
        entirely; a domain DataForSEO *answered about* but holds no rank for
        is present with ``da: None``. The two are different facts — "we never
        asked" and "there is no figure" — and only the second may be cached.
        A consumer must omit a ``None`` from any average rather than read it
        as 0 (`feasibility.competitor_da_window` does).
        """
        if not url_list:
            return {}

        unique_urls = list(dict.fromkeys(url_list))
        url_to_domain = {url: self._extract_domain(url) for url in unique_urls}
        # Remove URLs with no parseable domain
        url_to_domain = {u: d for u, d in url_to_domain.items() if d}

        unique_domains = list(dict.fromkeys(url_to_domain.values()))

        cached_domains, domains_to_fetch = self._cache_lookup(unique_domains)

        fresh_domains: dict[str, dict] = {}
        if domains_to_fetch:
            for batch in self._batches(domains_to_fetch):
                batch_result = self._fetch_batch(batch)
                fresh_domains.update(batch_result)
            if fresh_domains:
                self._cache_store(fresh_domains)

        all_domain_data = {**cached_domains, **fresh_domains}

        # Map back from domain → each original URL
        result: dict[str, dict] = {}
        for url, domain in url_to_domain.items():
            if domain in all_domain_data:
                result[url] = all_domain_data[domain]

        # A domain DataForSEO answered about but holds no rank for is present
        # with da: None (review chunk D2). len(result) therefore counts
        # records, not measurements, so say how many carry a figure — a batch
        # that measured nothing otherwise looked like a successful fetch
        # (P2/P6).
        coverage = feasibility.batch_coverage(result, asked=unique_urls)
        logger.info(
            "DataForSEO: %d of %d URLs answered, %d carry a rank, %d have no "
            "rank record", coverage.records, coverage.asked,
            coverage.measured, coverage.unmeasured,
        )
        if coverage.records and not coverage.measured:
            logger.warning(
                "DataForSEO holds no rank for any of the %d domains answered "
                "— those domains are unmeasured, not DA 0", coverage.records,
            )

        return result

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_batch(self, domains: list[str]) -> dict[str, dict]:
        """POST a single batch of domains to DataForSEO.

        Returns ``{domain: {da, pa, fetched_at}}`` on success,
        or ``{}`` on any error.
        """
        payload = [{"targets": domains, "rank_scale": "one_hundred"}]
        response = _post_with_transient_retry(
            "DataForSEO",
            DFS_ENDPOINT,
            headers={**self._auth_header, "Content-Type": "application/json"},
            json_payload=payload,
            batch_desc=f"batch of {len(domains)} domains",
        )
        if response is None:
            return {}
        if not response.ok:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:300]
            logger.warning(
                "DataForSEO %d error for batch of %d domains: %s",
                response.status_code, len(domains), body,
            )
            return {}

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("DataForSEO returned non-JSON response: %s", exc)
            return {}

        results: dict[str, dict] = {}
        fetched_at = datetime.now(_UTC).isoformat()
        for task in data.get("tasks", []):
            if task.get("status_code") != 20000:
                logger.warning("DataForSEO task error: %s", task.get("status_message"))
                continue
            # Response structure: result[0].items[{target, rank}]
            for result_block in (task.get("result") or []):
                for item in (result_block.get("items") or []):
                    domain = normalize_domain(item.get("target", ""))
                    if not domain:
                        continue
                    # A domain DataForSEO has not crawled comes back with no
                    # rank, or with null. `int(... or 0)` turned that into a
                    # measured DA of 0, which dragged the competitor mean down
                    # and so shrank the gap, flipping verdicts toward feasible
                    # — the tool recommended chasing keywords held by DA-90
                    # directories (D-C-04/D-M-02). None is "not measured"; the
                    # domain still appears in the result, so the caller can
                    # tell it apart from one that was never asked about.
                    #
                    # Provenance: that DataForSEO encodes "no rank" as a
                    # missing or null `rank` (rather than, say, omitting the
                    # item) is unverified against a live response — no
                    # DATAFORSEO_LOGIN/PASSWORD was reachable when this was
                    # written (2026-11-16). The premise comes from the
                    # synthetic payload in
                    # docs/review_2026-11-04/probes/discover/probe_03_dataforseo_null_rank.py.
                    # The branch is safe either way: a numeric rank is kept,
                    # anything else becomes None, so a shape we have not seen
                    # degrades to "not measured" rather than to a fabricated
                    # 0. Confirm against a real response when credentials
                    # are available.
                    raw_rank = item.get("rank")
                    rank = (int(raw_rank)
                            if isinstance(raw_rank, (int, float))
                            and not isinstance(raw_rank, bool) else None)
                    results[domain] = {
                        "da": rank,
                        "pa": rank,   # DataForSEO bulk_ranks is domain-level only
                        "fetched_at": fetched_at,
                    }
        return results

    # ------------------------------------------------------------------
    # Internal: cache
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        with db_connect.connection(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    domain           TEXT PRIMARY KEY,
                    domain_authority INTEGER,
                    page_authority   INTEGER,
                    fetched_at       TEXT
                )
            """)
            conn.commit()

    def _cache_lookup(self, domains: list[str]) -> tuple[dict[str, dict], list[str]]:
        """Split domains into (cached, needs_fetch)."""
        if not domains:
            return {}, []
        cached: dict[str, dict] = {}
        now = datetime.now(_UTC)
        cutoff = (now - self._cache_ttl).isoformat()
        # A measured DA is a fact about a crawled domain; an absence is a fact
        # about what the provider had crawled *at the time of asking*, and it
        # stops being true as soon as the domain is crawled. Caching both for
        # 30 days left a keyword reading "Not Measured" for a month after the
        # figure existed, with no path back (P1 — a transient absence held as
        # a terminal one). Absences expire on the shorter TTL and are asked
        # again (review chunk D2, finding F6).
        negative_cutoff = (now - self._negative_cache_ttl).isoformat()
        # Batch the IN(...) query — SQLite caps bound variables (999 in
        # older builds), and large runs can exceed it (seo_geo_review C.7).
        rows = []
        with db_connect.connection(self._db_path) as conn:
            for start in range(0, len(domains), 500):
                chunk = domains[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT domain, domain_authority, page_authority, fetched_at "
                    f"FROM {CACHE_TABLE} WHERE domain IN ({placeholders})",
                    chunk,
                ).fetchall())
        fresh = set()
        for domain, da, pa, fetched_at in rows:
            if not fetched_at:
                continue
            limit = cutoff if da is not None else negative_cutoff
            if fetched_at >= limit:
                cached[domain] = {"da": da, "pa": pa, "fetched_at": fetched_at}
                fresh.add(domain)
        to_fetch = [d for d in domains if d not in fresh]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        """Persist one batch, including the absences.

        ``domain_authority`` is a nullable column and a ``None`` is stored as
        SQL NULL on purpose: it is the ``found=0`` sentinel. The row's presence
        says DataForSEO was asked and answered, so the domain is not refetched
        inside the TTL; the NULL says there is no figure, so no consumer may
        average it. Storing a 0 here instead would be indistinguishable from a
        real rank of 0 (D-C-04).
        """
        rows = [
            (domain, v["da"], v["pa"], v["fetched_at"])
            for domain, v in results.items()
        ]
        with db_connect.connection(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(domain, domain_authority, page_authority, fetched_at) VALUES (?,?,?,?)",
                rows,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Internal: utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_domain(url: str) -> str:
        """One definition of which host a URL is (review chunk Y1)."""
        try:
            return normalize_domain(url)
        except Exception:
            return ""

    @staticmethod
    def _batches(items: list, size: int = DFS_BATCH_SIZE) -> Iterator[list]:
        for i in range(0, len(items), size):
            yield items[i: i + size]
