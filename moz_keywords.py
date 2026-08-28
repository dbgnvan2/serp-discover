"""
moz_keywords.py
~~~~~~~~~~~~~~~
Moz keyword metrics (volume, difficulty, organic CTR, priority) with caching.

Purpose: fetch per-keyword demand and competition metrics from the Moz Data
         API and hand them to the brief as pre-computed data.
Spec:    moz_api_upgrade_spec_v1.md#T.2
Tests:   test_moz_keywords.py

Calls ``data.keyword.metrics.fetch``, one call per keyword — Moz has no
``.multiple`` variant for this method (``Action not found:
DataKeywordMetricsFetchMultiple``, confirmed live 2026-08-28).

Request shape (confirmed live; all four ``serp_query`` fields are required and
the API rejects the call naming any that is missing)::

    {"serp_query": {"keyword": "...", "engine": "google",
                    "locale": "en-CA", "device": "desktop"}}

Absent data
-----------
Moz answers "I hold no metrics for this keyword" with **HTTP 404 /
JSON-RPC -32655**, which is a terminal but perfectly legitimate answer — many
low-volume and local keywords have no record. It is reported as
``status="no_record"`` with ``data_available: False`` and **never** as zeros:
a fabricated ``volume: 0`` would read as "nobody searches this", which is a
different and much stronger claim than "Moz doesn't know" (spec design
principle 3, learnings P1/P2/P14).

A genuine failure (5xx, timeout, bad credentials) is ``status="error"`` and is
**not cached**, so a later run retries it. A ``no_record`` verdict *is* cached
— it is Moz's real answer, not a transient block.

Quota
-----
A successful fetch bills **4 rows**, not 1 — measured against the live quota,
where the spec's budget table assumed one row per keyword. 50 keywords is
therefore ~200 rows, not 50. Failed and no-record calls bill nothing.

Runs are bounded twice: ``moz.keyword_metrics.max_keywords`` caps keywords per
run, and the remaining live quota is checked before spending, so the run
stops and says which keywords it skipped rather than silently overspending.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from moz_jsonrpc import MozRpcError, moz_call, quota_status

logger = logging.getLogger(__name__)

try:
    from datetime import UTC as _UTC
except ImportError:
    from datetime import timezone as _tz
    _UTC = _tz.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KEYWORD_METRICS_METHOD = "data.keyword.metrics.fetch"

CACHE_TABLE = "moz_keyword_cache"

#: Rows billed per successful fetch, measured live on 2026-08-28. Configurable
#: because it is Moz's pricing, not our logic, and it can change.
DEFAULT_ROWS_PER_CALL = 4

#: Keywords per run. Editorial/operational — config.yml is the source of record.
DEFAULT_MAX_KEYWORDS = 50

DEFAULT_ENGINE = "google"
DEFAULT_LOCALE = "en-CA"
DEFAULT_DEVICE = "desktop"

#: Moz's "no data for this target" answer. Not an outage — see module docstring.
NO_RECORD_STATUS = 404
NO_RECORD_CODE = -32655

#: The metric fields carried through to the brief.
METRIC_FIELDS = ("volume", "difficulty", "organic_ctr", "priority")

STATUS_OK = "ok"
STATUS_NO_RECORD = "no_record"
STATUS_ERROR = "error"
STATUS_SKIPPED_CAP = "skipped_run_cap"
STATUS_SKIPPED_QUOTA = "skipped_quota"

#: Statuses safe to cache. An error must not be, or one bad afternoon becomes
#: a month of "no data" (learnings P1).
_CACHEABLE = frozenset({STATUS_OK, STATUS_NO_RECORD})


def absent(status: str = STATUS_ERROR, reason: str | None = None) -> dict:
    """Return the absent-data block for one keyword.

    Every metric is omitted rather than zeroed, so a consumer cannot read a
    fabricated number (spec design principle 3).
    """
    block = {"data_available": False, "status": status}
    if reason:
        block["reason"] = reason
    return block


class MozKeywordClient:
    """Fetches and caches Moz keyword metrics.

    Parameters
    ----------
    db_path, cache_ttl_days:
        Cache location and lifetime, matching :class:`moz_client.MozClient`.
    engine, locale, device:
        The Moz ``serp_query`` context. All three are required by the API and
        all three change the answer, so all three are part of the cache key.
    max_keywords:
        Per-run keyword cap.
    rows_per_call:
        Rows Moz bills per successful fetch, used for the quota guard.
    """

    def __init__(
        self,
        db_path: str = "serp_data.db",
        cache_ttl_days: int = 30,
        engine: str = DEFAULT_ENGINE,
        locale: str = DEFAULT_LOCALE,
        device: str = DEFAULT_DEVICE,
        max_keywords: int = DEFAULT_MAX_KEYWORDS,
        rows_per_call: int = DEFAULT_ROWS_PER_CALL,
    ) -> None:
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._engine = engine or DEFAULT_ENGINE
        self._locale = locale or DEFAULT_LOCALE
        self._device = device or DEFAULT_DEVICE
        self._max_keywords = int(max_keywords)
        self._rows_per_call = int(rows_per_call)
        self.rows_consumed = 0
        self._init_cache_table()

    @classmethod
    def from_config(cls, config: dict, db_path: str = "serp_data.db") -> "MozKeywordClient":
        """Build a client from the ``moz:`` block of a loaded config.

        Purpose: one config→argument mapping shared by every front end (P25).
        Spec:    moz_api_upgrade_spec_v1.md#T.2
        Tests:   test_moz_keywords.py::TestFromConfig
        """
        moz_cfg = config.get("moz", {}) or {}
        kw_cfg = moz_cfg.get("keyword_metrics", {}) or {}
        return cls(
            db_path=db_path,
            cache_ttl_days=int(moz_cfg.get("cache_ttl_days", 30)),
            engine=kw_cfg.get("engine") or DEFAULT_ENGINE,
            locale=kw_cfg.get("locale") or DEFAULT_LOCALE,
            device=kw_cfg.get("device") or DEFAULT_DEVICE,
            max_keywords=int(kw_cfg.get("max_keywords") or DEFAULT_MAX_KEYWORDS),
            rows_per_call=int(kw_cfg.get("rows_per_call") or DEFAULT_ROWS_PER_CALL),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, keywords: list[str]) -> dict[str, dict]:
        """Return a metrics block for every keyword in *keywords*.

        Every input keyword is present in the result — a keyword that could
        not be fetched gets an explicit absent block rather than being
        dropped, so a consumer can never mistake "missing from the dict" for
        "no demand" (learnings P2).
        """
        if not keywords:
            return {}

        unique = list(dict.fromkeys(keywords))
        results: dict[str, dict] = {}

        cached, to_fetch = self._cache_lookup(unique)
        results.update(cached)

        if len(to_fetch) > self._max_keywords:
            skipped = to_fetch[self._max_keywords:]
            to_fetch = to_fetch[:self._max_keywords]
            logger.warning(
                "Moz keyword metrics: run cap %d reached — %d of %d uncached "
                "keyword(s) skipped (first: %s)",
                self._max_keywords, len(skipped), len(skipped) + len(to_fetch),
                skipped[0],
            )
            for kw in skipped:
                results[kw] = absent(
                    STATUS_SKIPPED_CAP,
                    f"per-run cap of {self._max_keywords} keywords reached",
                )

        budget = self._row_budget(len(to_fetch))
        fresh: dict[str, dict] = {}
        for index, keyword in enumerate(to_fetch):
            if budget is not None and budget < self._rows_per_call:
                remaining = to_fetch[index:]
                logger.warning(
                    "Moz keyword metrics: quota exhausted — %d keyword(s) "
                    "skipped rather than overspending (first: %s)",
                    len(remaining), remaining[0],
                )
                for kw in remaining:
                    results[kw] = absent(
                        STATUS_SKIPPED_QUOTA, "monthly row quota would be exceeded"
                    )
                break
            block = self._fetch_one(keyword)
            fresh[keyword] = block
            if block.get("status") == STATUS_OK:
                self.rows_consumed += self._rows_per_call
                if budget is not None:
                    budget -= self._rows_per_call

        if fresh:
            self._cache_store(fresh)
            logger.info(
                "Moz keyword metrics: %d fetched (%d with data), %d row(s) "
                "billed this session",
                len(fresh),
                sum(1 for b in fresh.values() if b.get("data_available")),
                self.rows_consumed,
            )
        results.update(fresh)
        return results

    # ------------------------------------------------------------------
    # Internal: API
    # ------------------------------------------------------------------

    def _row_budget(self, planned_calls: int) -> int | None:
        """Return rows available to spend, or ``None`` when it can't be read.

        An unreadable quota must not be treated as zero — that would disable
        the feature on a transient hiccup (P1). It falls through to "spend and
        let the API refuse", which is the pre-existing behaviour.
        """
        if not planned_calls:
            return None
        try:
            status = quota_status()
        except (MozRpcError, RuntimeError) as exc:
            logger.warning(
                "Moz keyword metrics: could not read quota (%s) — proceeding "
                "without a local budget guard", exc
            )
            return None
        needed = planned_calls * self._rows_per_call
        logger.info(
            "Moz keyword metrics: %d keyword(s) to fetch, ~%d row(s) needed, "
            "%d remaining of %d",
            planned_calls, needed, status["remaining"], status["allotted"],
        )
        return status["remaining"]

    def _fetch_one(self, keyword: str) -> dict:
        """Fetch one keyword, classifying absence apart from failure."""
        serp_query = {
            "keyword": keyword,
            "engine": self._engine,
            "locale": self._locale,
            "device": self._device,
        }
        try:
            result = moz_call(KEYWORD_METRICS_METHOD, {"serp_query": serp_query})
        except MozRpcError as exc:
            if exc.status == NO_RECORD_STATUS or exc.code == NO_RECORD_CODE:
                logger.info("Moz has no keyword metrics for %r", keyword)
                return absent(STATUS_NO_RECORD, "Moz holds no metrics for this keyword")
            logger.warning("Moz keyword metrics failed for %r: %s", keyword, exc)
            return absent(STATUS_ERROR, "Moz API call failed")
        except RuntimeError as exc:
            logger.warning("Moz keyword metrics unavailable for %r: %s", keyword, exc)
            return absent(STATUS_ERROR, "Moz credentials unavailable")

        metrics = result.get("keyword_metrics")
        if not isinstance(metrics, dict):
            logger.warning(
                "Moz keyword metrics response for %r carried no metrics object", keyword
            )
            return absent(STATUS_ERROR, "response carried no keyword_metrics object")

        block = {"data_available": True, "status": STATUS_OK}
        for field in METRIC_FIELDS:
            value = metrics.get(field)
            # Omit rather than zero: a missing field is unknown, not zero.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            block[field] = value
        if not any(field in block for field in METRIC_FIELDS):
            return absent(STATUS_NO_RECORD, "Moz returned no usable metric values")
        return block

    # ------------------------------------------------------------------
    # Internal: cache
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    keyword      TEXT NOT NULL,
                    engine       TEXT NOT NULL,
                    locale       TEXT NOT NULL,
                    device       TEXT NOT NULL,
                    status       TEXT,
                    volume       INTEGER,
                    difficulty   INTEGER,
                    organic_ctr  INTEGER,
                    priority     INTEGER,
                    fetched_at   TEXT,
                    PRIMARY KEY (keyword, engine, locale, device)
                )
            """)
            conn.commit()

    def _cache_lookup(self, keywords: list[str]) -> tuple[dict[str, dict], list[str]]:
        cached: dict[str, dict] = {}
        cutoff = (datetime.now(_UTC) - self._cache_ttl).isoformat()

        rows = []
        with sqlite3.connect(self._db_path) as conn:
            for start in range(0, len(keywords), 500):
                chunk = keywords[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(
                    f"SELECT keyword, status, volume, difficulty, organic_ctr, "
                    f"priority, fetched_at FROM {CACHE_TABLE} "
                    f"WHERE engine=? AND locale=? AND device=? "
                    f"AND keyword IN ({placeholders})",
                    [self._engine, self._locale, self._device, *chunk],
                ).fetchall())

        for keyword, status, *metrics, fetched_at in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            if status == STATUS_NO_RECORD:
                cached[keyword] = absent(
                    STATUS_NO_RECORD, "Moz holds no metrics for this keyword"
                )
                continue
            if status != STATUS_OK:
                continue  # never serve a cached failure
            block = {"data_available": True, "status": STATUS_OK}
            for field, value in zip(METRIC_FIELDS, metrics):
                if value is not None:
                    block[field] = value
            cached[keyword] = block

        to_fetch = [kw for kw in keywords if kw not in cached]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        fetched_at = datetime.now(_UTC).isoformat()
        rows = [
            (
                keyword, self._engine, self._locale, self._device,
                block.get("status"),
                *[block.get(field) for field in METRIC_FIELDS],
                fetched_at,
            )
            for keyword, block in results.items()
            if block.get("status") in _CACHEABLE
        ]
        if not rows:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                f"(keyword, engine, locale, device, status, volume, difficulty, "
                f"organic_ctr, priority, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
