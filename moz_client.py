"""
moz_client.py
~~~~~~~~~~~~~
Moz site-metrics client with SQLite caching.

Purpose: fetch Domain Authority, Page Authority, Spam Score and link counts
         for lists of URLs, cached locally.
Spec:    moz_api_upgrade_spec_v1.md#T.1
Tests:   test_moz_client.py

Fetches metrics via the Moz Data API method ``data.site.metrics.fetch.multiple``
(JSON-RPC over ``https://api.moz.com/jsonrpc``, transport in
:mod:`moz_jsonrpc`) and caches results locally to avoid redundant API calls —
DA changes slowly, so monthly granularity is sufficient.

Replaces the legacy Links-API v2 ``lsapi.seomoz.com/v2/url_metrics`` endpoint.
DA and PA values are unchanged by the move (verified against both endpoints on
2026-08-28); ``spam_score`` and ``link_counts`` are new additive fields.

Usage
-----
::

    from moz_client import MozClient

    client = MozClient()                      # reads env vars
    metrics = client.get_moz_metrics([
        "https://www.psychologytoday.com/ca",
        "https://livingsystems.ca/",
    ])
    # {"https://www.psychologytoday.com/ca":
    #     {"da": 93, "pa": 64, "spam_score": 3,
    #      "link_counts": {...}, "fetched_at": "..."},
    #  "https://livingsystems.ca/":
    #     {"da": 24, "pa": 31, "spam_score": 1,
    #      "link_counts": {...}, "fetched_at": "..."}}

Return-key contract
-------------------
Results are keyed by **the caller's input URL, verbatim** — the same contract
:class:`dataforseo_client.DataForSEOClient` already uses, so the two providers
are interchangeable at every call site.

The Moz API makes this exact: each result echoes the target as
``site_query.original_site_query.query``.

This corrects a real defect. The legacy path keyed results by the *response's*
scheme-stripped URL (``"livingsystems.ca/"`` for an input of
``"https://livingsystems.ca/"``), so ``serp_audit.py``'s
``if url in moz_results`` lookup never matched and ``Competitor_DA``,
``Page_Authority`` and ``save_url_moz_metrics()`` silently never fired
(learnings P2/P22).

Cache keys are normalised (scheme stripped) rather than raw input URLs, so
rows written by the legacy client remain valid after this upgrade.

Environment variables
---------------------
MOZ_TOKEN   Moz API token (required) — generated in the Moz API dashboard.

Read at instantiation time.  A ``RuntimeError`` is raised if absent so the
calling pipeline can set ``MOZ_AVAILABLE = False`` and degrade gracefully
rather than fail silently mid-run.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Iterator

from moz_jsonrpc import MozRpcError, moz_call

logger = logging.getLogger(__name__)

# Python 3.11+ exposes datetime.UTC; earlier versions need timezone.utc
try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Moz Data API method for batched site metrics.
SITE_METRICS_METHOD = "data.site.metrics.fetch.multiple"

#: Maximum targets per Moz API request.
MOZ_BATCH_SIZE: int = 50

#: Request timeout in seconds.
REQUEST_TIMEOUT: int = 30

#: SQLite table used for caching.
CACHE_TABLE = "moz_cache"

#: Query scope. The API accepts ``domain``, ``subdomain``, ``subfolder`` and
#: ``url``; ``url`` reproduces the legacy page-level PA behaviour.
DEFAULT_SITE_SCOPE = "url"

#: Fallback link-count fields. ``config.yml`` ``moz.site_metrics``
#: ``link_count_fields`` is the editorial source of record — this constant only
#: applies when a caller passes nothing.
DEFAULT_LINK_COUNT_FIELDS: tuple[str, ...] = (
    "root_domains_to_root_domain",
    "external_pages_to_root_domain",
    "nofollow_root_domains_to_root_domain",
    "root_domains_to_page",
    "external_pages_to_page",
    "pages_to_page",
)


def _cache_key(url: str) -> str:
    """Return the scheme-stripped cache key for *url*.

    Matches the key format the legacy client wrote, so rows cached before this
    upgrade still hit rather than forcing a full refetch.
    """
    for scheme in ("https://", "http://"):
        if url.startswith(scheme):
            return url[len(scheme):]
    return url


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MozClient:
    """Moz Data API site-metrics client with a local SQLite cache.

    Parameters
    ----------
    db_path:
        Path to the SQLite database used for caching.  Defaults to
        ``"serp_data.db"`` (same DB as the rest of the pipeline).
    cache_ttl_days:
        Number of days before a cached result is considered stale.
        Defaults to 30.  DA changes slowly so frequent refreshes are wasteful.
    scope:
        Moz site-query scope. See :data:`DEFAULT_SITE_SCOPE`.
    batch_size:
        Targets per API request.
    link_count_fields:
        Which ``site_metrics`` link-count fields to keep. Editorial — supplied
        from ``config.yml`` ``moz.site_metrics.link_count_fields``.

    Raises
    ------
    RuntimeError
        If the ``MOZ_TOKEN`` environment variable is not set.  Callers should
        catch this and set a ``MOZ_AVAILABLE`` flag.
    """

    def __init__(
        self,
        db_path: str = "serp_data.db",
        cache_ttl_days: int = 30,
        scope: str = DEFAULT_SITE_SCOPE,
        batch_size: int = MOZ_BATCH_SIZE,
        link_count_fields: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        token = os.getenv("MOZ_TOKEN")
        if not token:
            raise RuntimeError(
                "Moz credentials not found. Set MOZ_TOKEN in your .env file "
                "(generate a token in the Moz API dashboard)."
            )
        self._auth_header = {"x-moz-token": token}
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._scope = scope or DEFAULT_SITE_SCOPE
        self._batch_size = batch_size or MOZ_BATCH_SIZE
        self._link_count_fields = tuple(
            link_count_fields if link_count_fields else DEFAULT_LINK_COUNT_FIELDS
        )
        self._init_cache_table()

    @classmethod
    def from_config(cls, config: dict, db_path: str = "serp_data.db") -> "MozClient":
        """Build a client from the ``moz:`` block of a loaded config.

        Purpose: keep the config→argument mapping in one place so every front
                 end passes the same settings (learnings P25).
        Spec:    moz_api_upgrade_spec_v1.md#T.1
        Tests:   test_moz_site_metrics_wiring.py::TestFromConfigMapping
        """
        moz_cfg = config.get("moz", {}) or {}
        site_cfg = moz_cfg.get("site_metrics", {}) or {}
        return cls(
            db_path=db_path,
            cache_ttl_days=int(moz_cfg.get("cache_ttl_days", 30)),
            scope=site_cfg.get("scope") or DEFAULT_SITE_SCOPE,
            batch_size=int(site_cfg.get("batch_size") or MOZ_BATCH_SIZE),
            link_count_fields=site_cfg.get("link_count_fields"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_moz_metrics(self, url_list: list[str]) -> dict[str, dict]:
        """Return site metrics for each URL in *url_list*.

        Results are served from the local cache when available and not
        expired.  Uncached or expired URLs are fetched from the Moz API in
        batches of up to :attr:`_batch_size`.

        Parameters
        ----------
        url_list:
            List of URLs to look up.  Duplicates are silently deduplicated.

        Returns
        -------
        dict mapping **each input URL** to
        ``{"da": int, "pa": int, "spam_score": int | None,
        "link_counts": dict, "fetched_at": str}``.

        URLs that could not be fetched (HTTP error, timeout, no Moz record)
        are omitted from the result rather than raising, so a partial batch
        failure doesn't abort the pipeline. Omissions are logged with a count
        (learnings P2 — a silent drop is indistinguishable from "found
        nothing").
        """
        if not url_list:
            return {}

        unique_urls = list(dict.fromkeys(url_list))  # deduplicate, preserve order
        cached, to_fetch = self._cache_lookup(unique_urls)

        fresh: dict[str, dict] = {}
        if to_fetch:
            for batch in self._batches(to_fetch, self._batch_size):
                fresh.update(self._fetch_batch(batch))
            if fresh:
                self._cache_store(fresh)

        return {**cached, **fresh}

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_batch(self, urls: list[str]) -> dict[str, dict]:
        """Fetch one batch of targets via ``data.site.metrics.fetch.multiple``.

        Returns ``{input_url: metrics}``.  On failure returns an empty dict
        and logs a warning — the exception text from :mod:`moz_jsonrpc` is
        already token-redacted.
        """
        site_queries = [{"query": url, "scope": self._scope} for url in urls]
        try:
            result = moz_call(
                SITE_METRICS_METHOD,
                {"site_queries": site_queries},
                timeout=REQUEST_TIMEOUT,
            )
        except (MozRpcError, RuntimeError) as exc:
            logger.warning(
                "Moz site metrics failed for batch of %d URLs: %s", len(urls), exc
            )
            return {}

        errors = result.get("errors_by_site") or []
        if errors:
            logger.warning(
                "Moz returned errors for %d of %d targets: %s",
                len(errors), len(urls), str(errors)[:300],
            )

        results: dict[str, dict] = {}
        fetched_at = datetime.now(_UTC).isoformat()
        for entry in result.get("results_by_site") or []:
            site_query = entry.get("site_query") or {}
            original = (site_query.get("original_site_query") or {}).get("query")
            target = original or site_query.get("query")
            metrics = entry.get("site_metrics") or {}
            if not target or not metrics:
                continue
            results[target] = self._parse_site_metrics(metrics, fetched_at)

        missing = [u for u in urls if u not in results]
        if missing:
            logger.warning(
                "Moz site metrics: %d of %d targets returned no metrics (first: %s)",
                len(missing), len(urls), missing[0],
            )
        return results

    def _parse_site_metrics(self, metrics: dict, fetched_at: str) -> dict:
        """Map one Moz ``site_metrics`` object to this client's return shape.

        ``da``/``pa`` keep the legacy ``or 0`` coercion so feasibility scoring
        is unchanged by this upgrade (spec decision gate D-3). ``spam_score``
        is ``None`` when Moz has no value — never a fabricated 0, which would
        read as "clean site" (spec design principle 3).
        """
        spam = metrics.get("spam_score")
        return {
            "da": int(metrics.get("domain_authority") or 0),
            "pa": int(metrics.get("page_authority") or 0),
            "spam_score": (
                int(spam) if isinstance(spam, (int, float))
                and not isinstance(spam, bool) else None
            ),
            "link_counts": {
                field: metrics[field]
                for field in self._link_count_fields
                if metrics.get(field) is not None
            },
            "fetched_at": fetched_at,
        }

    # ------------------------------------------------------------------
    # Internal: cache
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        """Create the moz_cache table, and migrate it for the T.1 columns.

        The ALTER TABLE calls are idempotent — guarded on the live column
        list — mirroring the CREATE TABLE IF NOT EXISTS discipline so a
        database written by the legacy client upgrades in place.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    url               TEXT PRIMARY KEY,
                    domain_authority  INTEGER,
                    page_authority    INTEGER,
                    fetched_at        TEXT
                )
            """)
            existing = {
                row[1] for row in
                conn.execute(f"PRAGMA table_info({CACHE_TABLE})").fetchall()
            }
            for column, ddl in (
                ("spam_score", "INTEGER"),
                ("link_counts", "TEXT"),
            ):
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE {CACHE_TABLE} ADD COLUMN {column} {ddl}"
                    )
            conn.commit()

    def _cache_lookup(self, urls: list[str]) -> tuple[dict[str, dict], list[str]]:
        """Split *urls* into (cached_results, urls_needing_fetch).

        A cached entry is considered fresh if its ``fetched_at`` timestamp is
        within :attr:`_cache_ttl` of now. Cached results are returned keyed by
        the caller's input URL, not by the normalised cache key.
        """
        cached: dict[str, dict] = {}
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()

        key_to_urls: dict[str, list[str]] = {}
        for url in urls:
            key_to_urls.setdefault(_cache_key(url), []).append(url)
        keys = list(key_to_urls)

        # Batch the IN(...) query — SQLite caps bound variables (999 in
        # older builds), and large runs can exceed it (seo_geo_review C.7).
        rows = []
        with sqlite3.connect(self._db_path) as conn:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT url, domain_authority, page_authority, fetched_at, "
                    f"spam_score, link_counts "
                    f"FROM {CACHE_TABLE} WHERE url IN ({placeholders})",
                    chunk,
                ).fetchall())

        for key, da, pa, fetched_at, spam_score, link_counts in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            entry = {
                "da": da,
                "pa": pa,
                "spam_score": spam_score,
                "link_counts": _decode_link_counts(link_counts),
                "fetched_at": fetched_at,
            }
            for url in key_to_urls.get(key, []):
                cached[url] = entry

        to_fetch = [u for u in urls if u not in cached]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        """Upsert *results* into the cache table under normalised keys."""
        rows = [
            (
                _cache_key(url),
                v["da"],
                v["pa"],
                v["fetched_at"],
                v.get("spam_score"),
                json.dumps(v.get("link_counts") or {}),
            )
            for url, v in results.items()
        ]
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(url, domain_authority, page_authority, fetched_at, "
                f"spam_score, link_counts) VALUES (?,?,?,?,?,?)",
                rows,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Internal: utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _batches(items: list, size: int = MOZ_BATCH_SIZE) -> Iterator[list]:
        """Yield successive *size*-length chunks from *items*."""
        for i in range(0, len(items), size):
            yield items[i: i + size]


def _decode_link_counts(raw) -> dict:
    """Decode a cached ``link_counts`` JSON blob, tolerating legacy NULLs.

    Rows written before the T.1 migration have no value here; an empty dict is
    the honest answer for them, and the TTL refetch fills it in.
    """
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable link_counts blob in %s — treating as empty", CACHE_TABLE)
        return {}
    return decoded if isinstance(decoded, dict) else {}
