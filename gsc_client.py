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
  a ``GscStats`` carrying the measured rows plus the coverage of the fetch
  that produced them (which queries GSC answered absent, and which the
  fetch never reached). Paginated with the shared ``http_retry``
  transient-retry semantics.
- 7-day SQLite cache (``gsc_cache`` table) following the DA-client cache
  pattern including batched IN(...) lookups (500 bound variables per
  query, seo_geo_review C.7). An absence is cached with ``found = 0``
  ONLY when the fetch reported itself complete; a query the fetch did not
  reach is cached as nothing at all, so the next run asks again
  (review chunk D2b, finding D-C-02).

Environment variables
---------------------
GSC_CREDENTIALS_PATH   Path to the service-account JSON key (optional —
                       required only when no token_provider is injected).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import quote

import requests
import yaml

from http_retry import post_with_transient_retry as _post_with_transient_retry
import db_connect

logger = logging.getLogger(__name__)

# D5.7 — the country/device restriction lives in gsc_filters so the read-side
# dashboard can resolve it without importing this module (pipeline isolation,
# G.4.4). Re-exported here because callers and tests reference them by this name.
from gsc_filters import (  # noqa: E402
    COUNTRY_ALPHA2_TO_ALPHA3,
    GSC_DEVICES,
    cache_filter_key,
    filters_text,
    resolve_query_filters,
)

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

#: How many pages one fetch may request before it gives up and reports the
#: rows as INCOMPLETE. At ROW_LIMIT rows a page this is 5,000,000 queries, far
#: past any real property; it exists so that an API which never serves an
#: empty page cannot loop forever.
MAX_PAGES: int = 200

#: Documented default only. The live value is editorial, in `config.yml`
#: under `http_retry.timeout_seconds`, and reaches this call through
#: `http_retry` itself — one setting, every call site (P4/P25, review chunk
#: Y5). Kept so a direct caller that builds its own request still has a
#: timeout.
REQUEST_TIMEOUT: int = 30

CACHE_TABLE = "gsc_cache"

#: What is known about one query: GSC answered with figures, GSC answered and
#: holds no row, or the fetch never reached it. Keys, not wording — the words
#: come from `gsc_messages.yml`. The last two were one state before D-C-02.
STATUS_MEASURED = "measured"
STATUS_MEASURED_ABSENT = "measured_absent"
STATUS_NOT_REACHED = "not_reached"


#: Where the status labels, table cells and report lines live. Editorial, so
#: config rather than literals: three Python copies of a status word are how
#: "no GSC data" came to mean both "GSC says none" and "we never asked"
#: (CLAUDE.md editorial rule, as `feasibility_messages.yml`).
MESSAGES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "gsc_messages.yml")

_MESSAGES_CACHE = None


def load_messages() -> dict:
    """Read ``gsc_messages.yml``, or ``{}`` when it cannot be read.

    Missing or malformed degrades to the bare status key; the words are
    presentation and must never cost a run. Cached after the first read.
    """
    global _MESSAGES_CACHE
    if _MESSAGES_CACHE is not None:
        return _MESSAGES_CACHE
    data = {}
    try:
        with open(MESSAGES_FILE, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "gsc_messages.yml could not be read (%s); GSC statuses will "
            "render as plain keys.", exc)
    _MESSAGES_CACHE = data
    return data


def status_text(status: str, key: str = "label") -> str:
    """The configured *key* ("label" / "cell" / "coverage") for *status*."""
    entry = (load_messages().get("statuses") or {}).get(status) or {}
    value = entry.get(key)
    return str(value) if value else str(status or "")


def line(name: str, fallback: str, **values) -> str:
    """A configured report/log line, formatted, falling back rather than raising.

    A placeholder added to ``gsc_messages.yml`` must not be able to abort a
    report.
    """
    template = (load_messages().get("lines") or {}).get(name)
    if not template:
        return fallback.format(**values) if values else fallback
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        logger.warning(
            "gsc_messages.yml: %r could not be rendered (%s); using the "
            "built-in wording.", name, exc)
        return fallback.format(**values) if values else fallback


class GscStats(NamedTuple):
    """One ``get_query_stats`` answer, with what it does and does not cover.

    The coverage travels with the figures (as :class:`feasibility.DAWindow`,
    D2a): a caller recomputing it from ``len(stats)`` cannot tell an empty
    answer from an outage. *complete* is False when any page of the fetch
    failed; *measured_absent* / *not_reached* are the queries GSC answered
    "nothing" for and the ones the fetch never reached.
    """

    stats: dict
    complete: bool
    asked: list
    measured_absent: list
    not_reached: list
    #: Every query row for the property, keyed by lowercased query, when this
    #: call pulled them and the pull covered the whole property. ``None``
    #: whenever that is not true — a cache-only answer, or an incomplete
    #: fetch — so a caller cannot mistake a partial view for the property
    #: total (D5.4 / finding D-M-16).
    property_rows: dict | None = None

    def status_for(self, query: str) -> str:
        """``STATUS_MEASURED`` | ``STATUS_MEASURED_ABSENT`` | ``STATUS_NOT_REACHED``.

        A query never asked for reports ``STATUS_NOT_REACHED``: only measured
        absence is a claim about the client, and a lookup miss must not
        produce one (D2b.4).
        """
        q = (query or "").strip().lower()
        if q in self.stats:
            return STATUS_MEASURED
        if q in set(self.measured_absent):
            return STATUS_MEASURED_ABSENT
        return STATUS_NOT_REACHED


class GscClient:
    """Thin Search Analytics API wrapper with a 7-day SQLite cache.

    Parameters
    ----------
    property_url:
        The Search Console property, e.g. ``"sc-domain:livingsystems.ca"``
        or ``"https://livingsystems.ca/"`` (config.yml ``gsc.property``).
    db_path:
        SQLite database path. Defaults to the configured database (``database.path``).
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

    def __init__(self, property_url: str, db_path: str | None = None,
                 cache_ttl_days: int = 7, credentials_path: str | None = None,
                 token_provider=None, filters: dict | None = None) -> None:
        # Resolved in the body, never as a default argument: that binds
        # at `def` time, before any config has been read (chunk Y12).
        db_path = db_connect.database_path() if db_path is None else db_path
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
        # What the pull is restricted to. Part of the cache key: rows pulled
        # for one country/device must never be served for another (D5.7).
        self._filters = {"country": (filters or {}).get("country"),
                         "device": (filters or {}).get("device")}
        self._init_cache_table()

    @property
    def filters(self) -> dict:
        """The country/device this client's pull is restricted to."""
        return dict(self._filters)

    def _filter_key(self) -> str:
        """The cache-key form of the filters (``""`` = unfiltered, pre-D5.7)."""
        return cache_filter_key(self._filters)

    def _dimension_filter_groups(self) -> list[dict]:
        groups = []
        if self._filters.get("country"):
            groups.append({"dimension": "country", "operator": "equals",
                           "expression": self._filters["country"]})
        if self._filters.get("device"):
            groups.append({"dimension": "device", "operator": "equals",
                           "expression": self._filters["device"]})
        return [{"filters": groups}] if groups else []

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
                        end_date: str) -> GscStats:
        """Return GSC stats for each query over [start_date, end_date].

        Matching is case-insensitive (GSC reports queries lowercased);
        the returned dict is keyed by the lowercased query. Queries with
        no impressions in the window are omitted — never reported as
        fabricated zeros.

        A query is reported as absent only when the fetch that would have
        found it **completed**. Otherwise it comes back under ``not_reached``
        and is not cached, so the next call asks again: caching it as an
        absence made a 503 indistinguishable from "no impressions for these
        queries" for the whole TTL (D-C-02).

        Returns
        -------
        :class:`GscStats` — the figures plus what the answer covers.
        """
        normalized = list(dict.fromkeys(
            q.strip().lower() for q in (queries or []) if q and q.strip()))
        if not normalized:
            return GscStats({}, True, [], [], [])

        cached, cached_absent, to_fetch = self._cache_lookup(
            normalized, start_date, end_date)
        complete = True
        not_reached: list[str] = []
        property_rows: dict | None = None

        if to_fetch:
            all_rows, complete = self._fetch_all_rows(start_date, end_date)
            # The property-wide view is only real when the pull finished: a
            # truncated page set is a sample, not the property (D5.4).
            property_rows = dict(all_rows) if complete else None
            found = {q: all_rows[q] for q in to_fetch if q in all_rows}
            missing = [q for q in to_fetch if q not in all_rows]
            if complete:
                # The fetch covered the property: an absent query has no row.
                self._cache_store(
                    {**found, **{q: None for q in missing}},
                    start_date, end_date)
                cached_absent.extend(missing)
            else:
                # Only what was seen may be cached: the rest were not
                # measured as absent, they were not reached.
                if found:
                    self._cache_store(found, start_date, end_date)
                not_reached = missing
                logger.warning(
                    "GSC fetch incomplete — %d of %d query/queries were not "
                    "reached and are NOT recorded as having no impressions. "
                    "Re-run; the next call will ask again.",
                    len(missing), len(to_fetch),
                )
            cached.update(found)

        return GscStats(
            stats=cached,
            complete=complete,
            asked=normalized,
            measured_absent=[q for q in cached_absent if q not in cached],
            not_reached=not_reached,
            property_rows=property_rows,
        )

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _fetch_all_rows(self, start_date: str,
                        end_date: str) -> tuple[dict[str, dict], bool]:
        """Pull every query row for the property, paginated.

        Returns ``(rows, complete)``. ``complete`` is True only when the loop
        ended because the API served an EMPTY page — that is, when the whole
        property was covered. Any network failure, non-OK status or
        unparseable body ends the loop with ``complete=False`` and the rows
        reached so far.

        The bool is the whole point of this signature. Returning the rows
        alone could not express "these, and there are more I could not
        reach", so the caller treated a first-page 503 as "the property has
        no rows" and cached every query as a measured absence for the TTL
        (D-C-02). A failure part-way through pagination is the same fault in
        miniature: pages 1-2 arrive, and every query on pages 3+ is recorded
        as having no impressions. A short page part-way through a set did
        exactly that until 2026-11-19; the loop ends on an empty page now.
        """
        url = GSC_ENDPOINT_TEMPLATE.format(site=quote(self._property, safe=""))
        results: dict[str, dict] = {}
        start_row = 0
        pages = 0
        while True:
            payload = {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": ["query"],
                "rowLimit": ROW_LIMIT,
                "startRow": start_row,
            }
            groups = self._dimension_filter_groups()
            if groups:
                payload["dimensionFilterGroups"] = groups
            headers = {
                "Authorization": f"Bearer {self._token_provider()}",
                "Content-Type": "application/json",
            }
            response = _post_with_transient_retry(
                "GSC", url, headers, payload,
                batch_desc=f"searchAnalytics rows {start_row}+",
                post=requests.post,
            )
            if response is None:
                logger.warning(
                    "GSC request failed at the network layer after retries "
                    "(rows %d+) — returning %d row(s) as INCOMPLETE.",
                    start_row, len(results))
                return results, False
            if not response.ok:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text[:300]
                logger.warning(
                    "GSC %d error at rows %d+: %s — returning %d row(s) as "
                    "INCOMPLETE.", response.status_code, start_row, body,
                    len(results))
                return results, False
            try:
                data = response.json()
            except ValueError as exc:
                logger.warning(
                    "GSC returned a non-JSON response at rows %d+: %s — "
                    "returning %d row(s) as INCOMPLETE.", start_row, exc,
                    len(results))
                return results, False

            rows = data.get("rows") or []
            before = len(results)
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
            if not rows:
                # An EMPTY page is the end of the data. A SHORT one is not:
                # GSC can serve fewer rows than asked for part-way through a
                # set under sampling, and treating that as the end recorded
                # every query after it as having no impressions, cached for
                # the TTL — the D-C-02 fault in miniature, which this
                # function's own docstring described and its loop then
                # committed. The cost of the distinction is one extra request
                # per fetch, the empty page that confirms the end.
                return results, True
            if len(rows) < ROW_LIMIT:
                logger.info(
                    "GSC served a short page at rows %d+ (%d of %d); "
                    "continuing, because a short page is not the end of the "
                    "data.", start_row, len(rows), ROW_LIMIT)
            if len(results) == before:
                # A page of rows that added no query this fetch had not
                # already seen. A backend ignoring `startRow` re-serves the
                # same page, and the only other stop is MAX_PAGES, so without
                # this the run spends 199 further 25k-row requests to learn
                # nothing. INCOMPLETE, not complete: the rows beyond this
                # point were never served, so they are not an absence (P1,
                # cold review of this fix, finding 6).
                logger.warning(
                    "GSC served %d row(s) at rows %d+ and none of them was a "
                    "query this fetch had not already seen; stopping with "
                    "%d row(s) as INCOMPLETE.",
                    len(rows), start_row, len(results))
                return results, False
            start_row += len(rows)
            pages += 1
            if pages >= MAX_PAGES:
                # Bounded, and INCOMPLETE rather than silently truncated: an
                # API that never serves an empty page would otherwise loop
                # until the process was killed.
                logger.warning(
                    "GSC paging stopped at %d pages (%d row(s)) without an "
                    "empty page — returning them as INCOMPLETE.",
                    pages, len(results))
                return results, False

    # ------------------------------------------------------------------
    # Internal: cache (DA-client pattern)
    # ------------------------------------------------------------------

    #: The cache's current column set. ``filters`` (D5.7) is part of the
    #: primary key: without it one configuration's ``INSERT OR REPLACE``
    #: evicted the other's row, so flipping `gsc.country` between 'all' and a
    #: country refetched the whole property every run (cold review 8).
    _CACHE_DDL = f"""
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
            filters      TEXT DEFAULT '',
            PRIMARY KEY (query, start_date, end_date, filters)
        )
    """

    _CACHE_COLUMNS = ("query", "start_date", "end_date", "clicks",
                      "impressions", "ctr", "position", "found", "fetched_at",
                      "filters")

    def _init_cache_table(self) -> None:
        """Create the cache, migrating a pre-D5.7 table in place.

        A table created before D5.7 has no ``filters`` column and a primary key
        of ``(query, start_date, end_date)``. SQLite cannot alter a primary
        key, so the old table is copied into the new shape (its rows carrying
        ``filters = ''``, which is what they are: unfiltered) and swapped. The
        copy happens once; afterwards the ``CREATE TABLE IF NOT EXISTS`` is a
        no-op.
        """
        with db_connect.connection(self._db_path) as conn:
            conn.execute(self._CACHE_DDL)
            columns = {row[1] for row in conn.execute(
                f"PRAGMA table_info({CACHE_TABLE})")}
            pk = [row[1] for row in conn.execute(
                f"PRAGMA table_info({CACHE_TABLE})") if row[5]]
            if "filters" not in columns or "filters" not in pk:
                logger.info(
                    "Migrating %s to the D5.7 shape (filters in the primary "
                    "key); existing rows are recorded as unfiltered.",
                    CACHE_TABLE)
                conn.execute(f"ALTER TABLE {CACHE_TABLE} RENAME TO _gsc_cache_old")
                conn.execute(self._CACHE_DDL)
                old_columns = {row[1] for row in conn.execute(
                    "PRAGMA table_info(_gsc_cache_old)")}
                carried = [c for c in self._CACHE_COLUMNS if c in old_columns]
                conn.execute(
                    f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                    f"({', '.join(carried)}) "
                    f"SELECT {', '.join(carried)} FROM _gsc_cache_old")
                conn.execute(
                    f"UPDATE {CACHE_TABLE} SET filters = '' WHERE filters IS NULL")
                conn.execute("DROP TABLE _gsc_cache_old")
            conn.commit()

    def _cache_lookup(self, queries: list[str], start_date: str,
                      end_date: str) -> tuple[dict[str, dict], list[str],
                                              list[str]]:
        """Split queries into (cached-found, cached-absent, needs_fetch).

        Fresh ``found = 0`` rows are cached-absent: excluded from the result
        and from the fetch list, so measured absence does not trigger a
        re-pull inside the TTL. They come back in their own list because the
        caller must tell "GSC answered nothing" (a finding about the client)
        from "never reached" (not one) — D-C-02.
        """
        if not queries:
            return {}, [], []
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()
        rows = []
        with db_connect.connection(self._db_path) as conn:
            # Batch the IN(...) query — SQLite caps bound variables
            # (999 in older builds; seo_geo_review C.7 pattern).
            # The chunk size lives in `db_connect`: SQLite caps bound
            # variables (999 in older builds) and the Moz caches batch for
            # the same reason (review chunk Y14).
            for start in range(0, len(queries), db_connect.CACHE_LOOKUP_CHUNK):
                chunk = queries[
                    start:start + db_connect.CACHE_LOOKUP_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT query, clicks, impressions, ctr, position, found, fetched_at "
                    f"FROM {CACHE_TABLE} "
                    f"WHERE start_date = ? AND end_date = ? "
                    f"AND COALESCE(filters, '') = ? AND query IN ({placeholders})",
                    [start_date, end_date, self._filter_key(), *chunk],
                ).fetchall())

        cached: dict[str, dict] = {}
        resolved: set[str] = set()
        absent: list[str] = []
        for query, clicks, impressions, ctr, position, found, fetched_at in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            resolved.add(query)
            if found:
                cached[query] = {
                    "clicks": clicks, "impressions": impressions,
                    "ctr": ctr, "position": position,
                }
            else:
                absent.append(query)
        to_fetch = [q for q in queries if q not in resolved]
        return cached, absent, to_fetch

    def _cache_store(self, fetched: dict[str, dict | None], start_date: str,
                     end_date: str) -> None:
        fetched_at = datetime.now(_UTC).isoformat()
        rows = []
        for query, stats in fetched.items():
            key = self._filter_key()
            if stats:
                rows.append((query, start_date, end_date, stats["clicks"],
                             stats["impressions"], stats["ctr"],
                             stats["position"], 1, fetched_at, key))
            else:
                rows.append((query, start_date, end_date,
                             None, None, None, None, 0, fetched_at, key))
        with db_connect.connection(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(query, start_date, end_date, clicks, impressions, ctr, "
                f"position, found, fetched_at, filters) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
