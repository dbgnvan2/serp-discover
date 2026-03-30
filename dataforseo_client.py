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
import sqlite3
from base64 import b64encode
from datetime import datetime, timedelta
from typing import Iterator
from urllib.parse import urlparse

import requests

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

REQUEST_TIMEOUT: int = 30

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

    Raises
    ------
    RuntimeError
        If ``DATAFORSEO_LOGIN`` or ``DATAFORSEO_PASSWORD`` env vars are absent.
    """

    def __init__(self, db_path: str = "serp_data.db", cache_ttl_days: int = 30) -> None:
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
        dict mapping each input URL to ``{"da": int, "pa": int, "fetched_at": str}``.
        URLs whose domain could not be resolved or fetched are omitted.
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
        try:
            response = requests.post(
                DFS_ENDPOINT,
                headers={**self._auth_header, "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
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
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("DataForSEO request failed for batch of %d domains: %s", len(domains), exc)
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
                    domain = item.get("target", "").lstrip("www.")
                    if not domain:
                        continue
                    rank = int(item.get("rank") or 0)
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
        with sqlite3.connect(self._db_path) as conn:
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
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()
        placeholders = ",".join("?" * len(domains))
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                f"SELECT domain, domain_authority, page_authority, fetched_at "
                f"FROM {CACHE_TABLE} WHERE domain IN ({placeholders})",
                domains,
            ).fetchall()
        fresh = set()
        for domain, da, pa, fetched_at in rows:
            if fetched_at and fetched_at >= cutoff:
                cached[domain] = {"da": da, "pa": pa, "fetched_at": fetched_at}
                fresh.add(domain)
        to_fetch = [d for d in domains if d not in fresh]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        rows = [
            (domain, v["da"], v["pa"], v["fetched_at"])
            for domain, v in results.items()
        ]
        with sqlite3.connect(self._db_path) as conn:
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
        try:
            return urlparse(url).netloc.lower().lstrip("www.")
        except Exception:
            return ""

    @staticmethod
    def _batches(items: list, size: int = DFS_BATCH_SIZE) -> Iterator[list]:
        for i in range(0, len(items), size):
            yield items[i: i + size]
