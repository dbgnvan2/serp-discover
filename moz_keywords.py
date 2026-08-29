"""
moz_keywords.py
~~~~~~~~~~~~~~~
Per-keyword Moz signals — demand metrics and search intent — with caching.

Purpose: fetch per-keyword metrics and intent scores from the Moz Data API
         and hand them to the brief as pre-computed data.
Spec:    moz_api_upgrade_spec_v1.md#T.2, #T.3
Tests:   test_moz_keywords.py, test_moz_intent.py

Two signals share one fetch loop, because they share everything that matters:
the same required ``serp_query``, the same absent-data answer, the same cache
discipline and the same quota guard.

- :class:`MozKeywordClient` — ``data.keyword.metrics.fetch`` (T.2), 4 rows.
- :class:`MozIntentClient`  — ``data.keyword.search.intent.fetch`` (T.3), 1 row.

One call per keyword either way: Moz has no ``.multiple`` variant for these
methods (``Action not found: DataKeywordMetricsFetchMultiple``, confirmed live
2026-08-28).

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

import json
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


def row_budget(rows_needed: int, what: str = "Moz") -> int | None:
    """Return rows available to spend, or ``None`` when the quota can't be read.

    Purpose: one quota guard for every paid Moz signal, so hardening one does
             not leave its siblings unguarded (learnings P5).
    Spec:    moz_api_upgrade_spec_v1.md#T.2, #T.4
    Tests:   test_moz_keywords.py::TestSpendControls, test_moz_competitor.py

    An unreadable quota returns ``None``, not zero: treating a transient
    hiccup as "no budget" would silently disable the feature (P1). Callers
    then fall through to "spend and let the API refuse".
    """
    try:
        status = quota_status()
    except (MozRpcError, RuntimeError) as exc:
        logger.warning(
            "Moz %s: could not read quota (%s) — proceeding without a local "
            "budget guard", what, exc
        )
        return None
    logger.info(
        "Moz %s: ~%d row(s) needed, %d remaining of %d",
        what, rows_needed, status["remaining"], status["allotted"],
    )
    return status["remaining"]


class _KeywordSignalClient:
    """Shared fetch/cache/quota machinery for a per-keyword Moz signal.

    Subclasses supply the method name, the row price, and how to parse and
    cache their own payload. Everything that must behave identically across
    signals — the run cap, the quota guard, the 404-is-not-an-error rule, the
    never-cache-a-failure rule — lives here once, so a fix to one signal
    cannot silently miss the other (learnings P5).

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

    #: Moz Data API method this signal calls.
    METHOD: str = ""
    #: Rows billed per successful fetch, measured live.
    ROWS_PER_CALL: int = 1
    #: ``moz:`` sub-block holding this signal's settings.
    CONFIG_KEY: str = ""
    #: Human-readable name of what this signal holds, used in absent-data
    #: reasons so an intent block never reports "no metrics".
    SIGNAL_NAME: str = "data"

    def __init__(
        self,
        db_path: str = "serp_data.db",
        cache_ttl_days: int = 30,
        engine: str = DEFAULT_ENGINE,
        locale: str = DEFAULT_LOCALE,
        device: str = DEFAULT_DEVICE,
        max_keywords: int = DEFAULT_MAX_KEYWORDS,
        rows_per_call: int | None = None,
    ) -> None:
        self._db_path = db_path
        self._cache_ttl = timedelta(days=cache_ttl_days)
        self._engine = engine or DEFAULT_ENGINE
        self._locale = locale or DEFAULT_LOCALE
        self._device = device or DEFAULT_DEVICE
        self._max_keywords = int(max_keywords)
        self._rows_per_call = int(
            self.ROWS_PER_CALL if rows_per_call is None else rows_per_call
        )
        self.rows_consumed = 0
        self._init_cache_table()

    @classmethod
    def from_config(cls, config: dict, db_path: str = "serp_data.db"):
        """Build a client from the ``moz:`` block of a loaded config.

        Purpose: one config→argument mapping shared by every front end (P25).
        Spec:    moz_api_upgrade_spec_v1.md#T.2, #T.3
        Tests:   test_moz_keywords.py::TestFromConfig
        """
        moz_cfg = config.get("moz", {}) or {}
        kw_cfg = moz_cfg.get(cls.CONFIG_KEY, {}) or {}
        return cls(
            db_path=db_path,
            cache_ttl_days=int(moz_cfg.get("cache_ttl_days", 30)),
            engine=kw_cfg.get("engine") or DEFAULT_ENGINE,
            locale=kw_cfg.get("locale") or DEFAULT_LOCALE,
            device=kw_cfg.get("device") or DEFAULT_DEVICE,
            max_keywords=int(kw_cfg.get("max_keywords") or DEFAULT_MAX_KEYWORDS),
            rows_per_call=int(kw_cfg.get("rows_per_call") or cls.ROWS_PER_CALL),
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
        """Return rows available to spend, or ``None`` when it can't be read."""
        if not planned_calls:
            return None
        return row_budget(planned_calls * self._rows_per_call, self.SIGNAL_NAME)

    def _fetch_one(self, keyword: str) -> dict:
        """Fetch one keyword, classifying absence apart from failure."""
        serp_query = {
            "keyword": keyword,
            "engine": self._engine,
            "locale": self._locale,
            "device": self._device,
        }
        try:
            result = moz_call(self.METHOD, {"serp_query": serp_query})
        except MozRpcError as exc:
            if exc.status == NO_RECORD_STATUS or exc.code == NO_RECORD_CODE:
                logger.info("Moz has no keyword metrics for %r", keyword)
                return absent(
                    STATUS_NO_RECORD,
                    f"Moz holds no {self.SIGNAL_NAME} for this keyword",
                )
            logger.warning("Moz keyword metrics failed for %r: %s", keyword, exc)
            return absent(STATUS_ERROR, "Moz API call failed")
        except RuntimeError as exc:
            logger.warning("Moz keyword metrics unavailable for %r: %s", keyword, exc)
            return absent(STATUS_ERROR, "Moz credentials unavailable")

        return self._parse(result, keyword)

    def _parse(self, result: dict, keyword: str) -> dict:
        raise NotImplementedError



class MozKeywordClient(_KeywordSignalClient):
    """Moz keyword metrics: volume, difficulty, organic CTR, priority.

    Purpose: per-keyword demand and competition figures for the brief.
    Spec:    moz_api_upgrade_spec_v1.md#T.2
    Tests:   test_moz_keywords.py
    """

    METHOD = KEYWORD_METRICS_METHOD
    ROWS_PER_CALL = DEFAULT_ROWS_PER_CALL
    CONFIG_KEY = "keyword_metrics"
    SIGNAL_NAME = "keyword metrics"

    def _parse(self, result: dict, keyword: str) -> dict:
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
                    STATUS_NO_RECORD,
                    f"Moz holds no {self.SIGNAL_NAME} for this keyword",
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


# ---------------------------------------------------------------------------
# T.3 — search intent (a cross-check, never a replacement)
# ---------------------------------------------------------------------------

SEARCH_INTENT_METHOD = "data.keyword.search.intent.fetch"

INTENT_CACHE_TABLE = "moz_intent_cache"

#: Rows billed per successful intent fetch, measured live 2026-08-28. One,
#: where keyword metrics cost four — the prices differ per method.
INTENT_ROWS_PER_CALL = 1

#: Moz's four intent labels. This is Moz's vocabulary, not the repo's: the
#: repo's classifier also emits `commercial_investigation`, `local` and
#: `uncategorised`, which is why comparing the two needs a mapping and why
#: that mapping is editorial (config.yml `moz.search_intent`).
MOZ_INTENT_LABELS = ("informational", "navigational", "commercial", "transactional")

#: Fallback repo-intent → Moz-label mapping. config.yml
#: `moz.search_intent.repo_to_moz_intent` is the editorial source of record.
DEFAULT_REPO_TO_MOZ_INTENT = {
    "informational": "informational",
    "commercial_investigation": "commercial",
    "transactional": "transactional",
    "navigational": "navigational",
    # Moz has no "local" label; a local service query scores transactional
    # there ("family counselling north vancouver" → transactional, 0.45).
    "local": "transactional",
    "uncategorised": None,
}


class MozIntentClient(_KeywordSignalClient):
    """Moz search-intent scores for a keyword.

    Purpose: an independent second opinion on intent, to cross-check the
             repo's own rule-based classifier.
    Spec:    moz_api_upgrade_spec_v1.md#T.3
    Tests:   test_moz_intent.py

    This never replaces `intent_mapping.yml`. The repo's classifier stays the
    verdict; Moz's scores sit beside it and disagreement is *reported*, not
    resolved — an external model quietly overriding a rule table the user
    maintains would make the rules unfalsifiable.
    """

    METHOD = SEARCH_INTENT_METHOD
    ROWS_PER_CALL = INTENT_ROWS_PER_CALL
    CONFIG_KEY = "search_intent"
    SIGNAL_NAME = "intent scores"

    def _parse(self, result: dict, keyword: str) -> dict:
        intent = result.get("keyword_intent")
        if not isinstance(intent, dict):
            logger.warning(
                "Moz search intent response for %r carried no intent object", keyword
            )
            return absent(STATUS_ERROR, "response carried no keyword_intent object")

        scores = {}
        for entry in intent.get("all_intents") or []:
            if not isinstance(entry, dict):
                continue
            label, score = entry.get("label"), entry.get("score")
            if label in MOZ_INTENT_LABELS and isinstance(score, (int, float)) \
                    and not isinstance(score, bool):
                scores[label] = float(score)

        primaries = [
            label for label in (intent.get("primary_intents") or [])
            if label in MOZ_INTENT_LABELS
        ]
        if not scores and not primaries:
            return absent(STATUS_NO_RECORD, "Moz returned no usable intent scores")
        return {
            "data_available": True,
            "status": STATUS_OK,
            "primary_intents": primaries,
            "scores": scores,
        }

    # ------------------------------------------------------------------
    # Internal: cache
    # ------------------------------------------------------------------

    def _init_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {INTENT_CACHE_TABLE} (
                    keyword         TEXT NOT NULL,
                    engine          TEXT NOT NULL,
                    locale          TEXT NOT NULL,
                    device          TEXT NOT NULL,
                    status          TEXT,
                    primary_intents TEXT,
                    scores          TEXT,
                    fetched_at      TEXT,
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
                    f"SELECT keyword, status, primary_intents, scores, fetched_at "
                    f"FROM {INTENT_CACHE_TABLE} "
                    f"WHERE engine=? AND locale=? AND device=? "
                    f"AND keyword IN ({placeholders})",
                    [self._engine, self._locale, self._device, *chunk],
                ).fetchall())

        for keyword, status, primaries, scores, fetched_at in rows:
            if not fetched_at or fetched_at < cutoff:
                continue
            if status == STATUS_NO_RECORD:
                cached[keyword] = absent(
                    STATUS_NO_RECORD,
                    f"Moz holds no {self.SIGNAL_NAME} for this keyword",
                )
                continue
            if status != STATUS_OK:
                continue  # never serve a cached failure
            cached[keyword] = {
                "data_available": True,
                "status": STATUS_OK,
                "primary_intents": _decode_json(primaries, list),
                "scores": _decode_json(scores, dict),
            }

        to_fetch = [kw for kw in keywords if kw not in cached]
        return cached, to_fetch

    def _cache_store(self, results: dict[str, dict]) -> None:
        fetched_at = datetime.now(_UTC).isoformat()
        rows = [
            (
                keyword, self._engine, self._locale, self._device,
                block.get("status"),
                json.dumps(block.get("primary_intents") or []),
                json.dumps(block.get("scores") or {}),
                fetched_at,
            )
            for keyword, block in results.items()
            if block.get("status") in _CACHEABLE
        ]
        if not rows:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO {INTENT_CACHE_TABLE} "
                f"(keyword, engine, locale, device, status, primary_intents, "
                f"scores, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()


def _decode_json(raw, expected_type):
    """Decode a cached JSON blob, degrading to an empty container."""
    if not raw:
        return expected_type()
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Unreadable blob in %s — treating as empty", INTENT_CACHE_TABLE)
        return expected_type()
    return decoded if isinstance(decoded, expected_type) else expected_type()


def crosscheck_intent(repo_intent, moz_block, mapping=None) -> dict:
    """Compare the repo's intent verdict with Moz's, and report the result.

    Purpose: surface agreement or divergence without ever overriding the
             repo's own rule-based classification.
    Spec:    moz_api_upgrade_spec_v1.md#T.3
    Tests:   test_moz_intent.py::TestCrosscheck

    The two use different vocabularies — Moz has four labels, the repo also
    emits ``commercial_investigation``, ``local`` and ``uncategorised`` — so
    the repo verdict is mapped onto Moz's before comparing. That mapping is an
    editorial judgement and lives in config.yml.

    ``agrees`` is ``None``, never ``False``, whenever agreement cannot be
    determined (no Moz data, a mixed-intent keyword, an unmappable label).
    Reporting "they disagree" when the truth is "not comparable" would invent
    a conflict (learnings P1/P14).
    """
    block = dict(moz_block or {})
    mapping = mapping or DEFAULT_REPO_TO_MOZ_INTENT
    block["repo_intent"] = repo_intent

    if not block.get("data_available"):
        block["agrees"] = None
        block["divergence"] = None
        return block

    mapped = mapping.get(repo_intent) if repo_intent else None
    block["repo_intent_as_moz"] = mapped
    primaries = block.get("primary_intents") or []

    if not mapped or not primaries:
        block["agrees"] = None
        block["divergence"] = (
            "not comparable: no single mappable repo intent"
            if not mapped else
            "not comparable: Moz reported no primary intent"
        )
        return block

    block["agrees"] = mapped in primaries
    block["divergence"] = None if block["agrees"] else (
        f"repo says {repo_intent!r} (Moz vocabulary: {mapped!r}); "
        f"Moz says {', '.join(primaries)!r}"
    )
    return block
