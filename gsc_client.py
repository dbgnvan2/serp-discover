"""
gsc_client.py
~~~~~~~~~~~~~
Google Search Console (Search Analytics) client with SQLite caching.

Spec: seo_geo_deferred_spec_v1.md#G.4 (decision gate D-3: headless service
account — JSON key path from the optional ``GSC_CREDENTIALS_PATH`` env var;
the service-account email must be granted access on the Search Console
property, see docs/USER_MANUAL.md for the setup steps).

The main pipeline never imports this module (G.4.4) — only the standalone
``run_gsc_analysis.py`` does.

Design
------
- Auth: service-account JSON → OAuth2 access token via ``google-auth``
  (imported lazily, so tests — and installs without the dependency — can
  inject a ``token_provider`` instead; all HTTP is mocked in tests).
- One public method: ``get_query_stats(queries, start_date, end_date)`` →
  ``{query: {clicks, impressions, ctr, position}}`` via the Search
  Analytics API (dimension ``query``), paginated with the shared
  ``http_retry`` transient-retry semantics.
- 7-day SQLite cache (``gsc_cache`` table) following the DA-client cache
  pattern including batched IN(...) lookups (500 bound variables per
  query, seo_geo_review C.7). Queries that GSC returned no row for are
  cached with ``found = 0`` so absence is remembered (measured absence,
  not a fabricated zero — absent queries are simply omitted from the
  result, per the "absent data is stated, not faked" design principle).

Environment variables
---------------------
GSC_CREDENTIALS_PATH   Path to the service-account JSON key (optional —
                       required only when no token_provider is injected).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import quote

import requests

from http_retry import post_with_transient_retry as _post_with_transient_retry

logger = logging.getLogger(__name__)

try:
    from datetime import UTC as _UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _tz
    _UTC = _tz.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_ENDPOINT_TEMPLATE = (
    "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
)

#: Rows requested per Search Analytics page (API maximum).
ROW_LIMIT: int = 25000

REQUEST_TIMEOUT: int = 30

CACHE_TABLE = "gsc_cache"

#: Bound variables per cache IN(...) chunk (SQLite caps at 999 in older
#: builds — same batching as dataforseo_client, seo_geo_review C.7).
CACHE_LOOKUP_CHUNK: int = 500


class GscClient:
    """Thin Search Analytics API wrapper with a 7-day SQLite cache.

    Parameters
    ----------
    property_url:
        The Search Console property, e.g. ``"sc-domain:livingsystems.ca"``
        or ``"https://livingsystems.ca/"`` (config.yml ``gsc.property``).
    db_path:
        SQLite database path. Defaults to ``"serp_data.db"``.
    cache_ttl_days:
        Days before a cached row is stale. Defaults to 7 (spec G.4).
    credentials_path:
        Service-account JSON key path. Defaults to the
        ``GSC_CREDENTIALS_PATH`` env var.
    token_provider:
        Optional zero-arg callable returning a bearer token — injected by
        tests; when omitted, a google-auth service-account provider is
        built from ``credentials_path``.

    Raises
    ------
    RuntimeError
        If no token_provider is given and the credentials path is unset
        or missing.
    """

    def __init__(self, property_url: str, db_path: str = "serp_data.db",
                 cache_ttl_days: int = 7, credentials_path: str | None = None,
                 token_provider=None) -> None:
        if not property_url:
            raise RuntimeError("GSC property is not configured (config.yml gsc.property).")
        self._property = property_url
        if token_provider is None:
            path = (credentials_path or os.getenv("GSC_CREDENTIALS_PATH", "")).strip()
            if not path:
                raise RuntimeError(
                    "GSC credentials not found. Set GSC_CREDENTIALS_PATH in your "
                    ".env to the service-account JSON key path (gate D-3)."
                )
            if not os.path.exists(path):
                raise RuntimeError(f"GSC credentials file not found: {path}")
            token_provider = self._service_account_token_provider(path)
        self._token_provider = token_provider
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._init_cache_table()

    # ------------------------------------------------------------------
    # Auth (gate D-3: headless service account)
    # ------------------------------------------------------------------

    @staticmethod
    def _service_account_token_provider(credentials_path: str):
        """Build a token provider from a service-account JSON key.

        google-auth is imported lazily so the dependency is only required
        when real credentials are used (tests inject token_provider).
        """
        def _provider() -> str:
            try:
                from google.oauth2 import service_account
                from google.auth.transport.requests import Request as _GoogleAuthRequest
            except ImportError as exc:
                raise RuntimeError(
                    "google-auth is required for GSC service-account auth "
                    "(pip install google-auth — see requirements.txt)."
                ) from exc
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=[GSC_SCOPE])
            credentials.refresh(_GoogleAuthRequest())
            return credentials.token
        return _provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_query_stats(self, queries: list[str], start_date: str,
                        end_date: str) -> dict[str, dict]:
        """Return GSC stats for each query over [start_date, end_date].

        Matching is case-insensitive (GSC reports queries lowercased);
        the returned dict is keyed by the lowercased query. Queries with
        no impressions in the window are omitted — never reported as
        fabricated zeros.

        Returns
        -------
        dict mapping query → ``{"clicks", "impressions", "ctr", "position"}``.
        """
        normalized = list(dict.fromkeys(
            q.strip().lower() for q in (queries or []) if q and q.strip()))
        if not normalized:
            return {}

        cached, to_fetch = self._cache_lookup(normalized, start_date, end_date)

        if to_fetch:
            all_rows = self._fetch_all_rows(start_date, end_date)
            fetched = {q: all_rows.get(q) for q in to_fetch}
            self._cache_store(fetched, start_date, end_date)
            cached.update({q: stats for q, stats in fetched.items() if stats})

        return cached

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_all_rows(self, start_date: str, end_date: str) -> dict[str, dict]:
        """Pull every query row for the property, paginated (batched pulls)."""
        url = GSC_ENDPOINT_TEMPLATE.format(site=quote(self._property, safe=""))
        results: dict[str, dict] = {}
        start_row = 0
        while True:
            payload = {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": ["query"],
                "rowLimit": ROW_LIMIT,
                "startRow": start_row,
            }
            headers = {
                "Authorization": f"Bearer {self._token_provider()}",
                "Content-Type": "application/json",
            }
            response = _post_with_transient_retry(
                "GSC", url, headers, payload,
                batch_desc=f"searchAnalytics rows {start_row}+",
                timeout=REQUEST_TIMEOUT,
                post=requests.post,
            )
            if response is None:
                logger.warning("GSC request failed at the network layer — partial data.")
                break
            if not response.ok:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text[:300]
                logger.warning("GSC %d error: %s", response.status_code, body)
                break
            try:
                data = response.json()
            except ValueError as exc:
                logger.warning("GSC returned non-JSON response: %s", exc)
                break

            rows = data.get("rows") or []
            for row in rows:
                keys = row.get("keys") or []
                if not keys:
                    continue
                query = str(keys[0]).strip().lower()
                results[query] = {
                    "clicks": int(row.get("clicks") or 0),
                    "impressions": int(row.get("impressions") or 0),
                    "ctr": float(row.get("ctr") or 0.0),
                    "position": float(row.get("position") or 0.0),
                }
            if len(rows) < ROW_LIMIT:
                break
            start_row += len(rows)
        return results

    # ------------------------------------------------------------------
    # Internal: cache (DA-client pattern)
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    query        TEXT,
                    start_date   TEXT,
                    end_date     TEXT,
                    clicks       INTEGER,
                    impressions  INTEGER,
                    ctr          REAL,
                    position     REAL,
                    found        INTEGER,
                    fetched_at   TEXT,
                    PRIMARY KEY (query, start_date, end_date)
                )
            """)
            conn.commit()

    def _cache_lookup(self, queries: list[str], start_date: str,
                      end_date: str) -> tuple[dict[str, dict], list[str]]:
        """Split queries into (cached-found, needs_fetch).

        Fresh ``found = 0`` rows count as cached-absent: they are excluded
        from both the result and the fetch list, so measured absence does
        not trigger a re-pull inside the TTL.
        """
        if not queries:
            return {}, []
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()
        rows = []
        with sqlite3.connect(self._db_path) as conn:
            # Batch the IN(...) query — SQLite caps bound variables
            # (999 in older builds; seo_geo_review C.7 pattern).
            for start in range(0, len(queries), CACHE_LOOKUP_CHUNK):
                chunk = queries[start:start + CACHE_LOOKUP_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT query, clicks, impressions, ctr, position, found, fetched_at "
                    f"FROM {CACHE_TABLE} "
                    f"WHERE start_date = ? AND end_date = ? AND query IN ({placeholders})",
                    [start_date, end_date, *chunk],
                ).fetchall())

        cached: dict[str, dict] = {}
        resolved: set[str] = set()
        for query, clicks, impressions, ctr, position, found, fetched_at in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            resolved.add(query)
            if found:
                cached[query] = {
                    "clicks": clicks, "impressions": impressions,
                    "ctr": ctr, "position": position,
                }
        to_fetch = [q for q in queries if q not in resolved]
        return cached, to_fetch

    def _cache_store(self, fetched: dict[str, dict | None], start_date: str,
                     end_date: str) -> None:
        fetched_at = datetime.now(_UTC).isoformat()
        rows = []
        for query, stats in fetched.items():
            if stats:
                rows.append((query, start_date, end_date, stats["clicks"],
                             stats["impressions"], stats["ctr"],
                             stats["position"], 1, fetched_at))
            else:
                rows.append((query, start_date, end_date,
                             None, None, None, None, 0, fetched_at))
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(query, start_date, end_date, clicks, impressions, ctr, "
                f"position, found, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
