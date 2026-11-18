"""db_connect.py — one way to open the SQLite database and close it again.

`with sqlite3.connect(path) as conn:` commits on a clean exit and rolls back
on an exception, but it never closes the connection: the handle is released
whenever the object happens to be collected. `with closing(sqlite3.connect(
path)) as conn:` is the opposite trap — it closes the handle and discards the
commit, because `closing` does not run the connection's own `__exit__`, so
every write inside the block is rolled back by the close.

This module does both, once, so no call site has to pair them (review chunk
Y9, the adjacent issue carried by chunks Y5 and Y6). Review chunk Y11 added
the two things the first version got wrong: a failing rollback or close no
longer replaces the exception that caused it, and the lock wait is a
configured number rather than sqlite3's undeclared default.

Spec: docs/review_2026-11-04/PLAN_Y9_a_handle_is_closed.md,
      docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md
Tests: tests/test_y9_a_handle_is_closed.py,
       tests/test_y11_a_rollback_is_not_the_diagnosis.py
"""

import logging
import sqlite3
from contextlib import contextmanager

from timeouts import seconds_from_config

logger = logging.getLogger(__name__)

#: sqlite3's own default for `connect(timeout=)`, named here because it was
#: being used without being chosen. It is how long a writer waits for another
#: writer's lock before raising `database is locked`.
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0

#: The longest wait that will be honoured. A contended write blocks the
#: thread that makes it, and the GUI calls `refresh_analysis_outputs` on the Tk
#: thread, so a slip of a decimal point (`5000` for `5.0`, or milliseconds for
#: seconds) would freeze the window for 83 minutes with nothing in the log
#: until the wait ended. Five minutes is longer than any lock this tool takes
#: and short enough to read as a hang rather than a crash. The sibling policy
#: bounds its wait for the same reason (`max_retry_after_seconds`); this one,
#: which can block the UI, had no bound at all (cold review of chunk Y11).
MAX_LOCK_TIMEOUT_SECONDS = 300.0

#: The configured wait. Rebound by `apply_lock_timeout`; read through
#: `lock_timeout()`, never as a default argument, which binds at import.
LOCK_TIMEOUT_SECONDS = DEFAULT_LOCK_TIMEOUT_SECONDS

#: Where the wait is configured. Named so a caller that needs to know which
#: settings are refused at zero reads the fact off the loader rather than
#: keeping a second list (P32) — `timeouts.GOVERNED_FIELDS` includes it.
LOCK_TIMEOUT_SOURCE = ("database", "lock_timeout_seconds")


def lock_timeout() -> float:
    """How long this process waits for another writer's lock, in seconds."""
    return LOCK_TIMEOUT_SECONDS


def apply_lock_timeout(cfg: dict | None) -> float:
    """Set this process's SQLite lock wait from *cfg*, and return it.

    Called once per process by `process_config.apply`, which every loader of
    `config.yml` routes through. A non-positive or non-numeric value is
    reported and the documented default used: zero would make every
    concurrent write fail at once, and `seconds_from_config` is this repo's
    one rule for reading a wait (P32).
    """
    global LOCK_TIMEOUT_SECONDS
    section_name, cfg_key = LOCK_TIMEOUT_SOURCE
    section = cfg.get(section_name) if isinstance(cfg, dict) else None
    if isinstance(cfg, dict) and section_name in cfg and not isinstance(section, dict):
        # The three shapes `http_retry` was fixed for in the cold review of
        # chunk Y7, and this missed in its own: a block mangled to a scalar or
        # to nothing at all. An indentation typo is enough, and the configured
        # wait was then discarded in silence (P2/P5, cold review of chunk Y11).
        logger.warning(
            "config.yml %s is %r, not a block of settings; using the "
            "documented default lock wait %s.",
            section_name, section, DEFAULT_LOCK_TIMEOUT_SECONDS)
    elif isinstance(section, dict) and not section:
        logger.warning(
            "config.yml %s is empty; using the documented default lock wait "
            "%s.", section_name, DEFAULT_LOCK_TIMEOUT_SECONDS)
    value = section.get(cfg_key) if isinstance(section, dict) else None
    if isinstance(section, dict) and cfg_key in section and value is None:
        # `seconds_from_config` reads `None` as "key absent" and returns the
        # default without a warning, which is right for an absent key and
        # wrong for `lock_timeout_seconds:` written with nothing after it (P2,
        # the same distinction `http_retry.resolve_retry_policy` makes).
        logger.warning(
            "config.yml %s.%s is empty; using the documented default %s.",
            section_name, cfg_key, DEFAULT_LOCK_TIMEOUT_SECONDS)
        value = None
    seconds = seconds_from_config(
        value, DEFAULT_LOCK_TIMEOUT_SECONDS, f"{section_name}.{cfg_key}")
    if seconds > MAX_LOCK_TIMEOUT_SECONDS:
        logger.warning(
            "config.yml %s.%s is %s seconds, which would block a contended "
            "write — and the GUI thread that made it — for that long. Waiting "
            "the maximum of %s instead.",
            section_name, cfg_key, seconds, MAX_LOCK_TIMEOUT_SECONDS)
        seconds = MAX_LOCK_TIMEOUT_SECONDS
    LOCK_TIMEOUT_SECONDS = seconds
    return LOCK_TIMEOUT_SECONDS


def _safely(cleanup, what: str, db_path) -> None:
    """Run one cleanup step so it cannot replace the caller's exception.

    A failing `rollback()` or `close()` is a second fact, not the diagnosis:
    raising from here turns the `IntegrityError` that says which write was
    wrong into an `OperationalError` from the cleanup, and on the clean path
    turns a committed, durable write into a reported failure (review chunk
    Y11). `Exception`, not `BaseException`, so a `KeyboardInterrupt` during
    cleanup still reaches the user.
    """
    try:
        cleanup()
    except Exception:
        logger.exception(
            "Could not %s the connection to %s. The original outcome of the "
            "block stands; this is a failure of the cleanup, not of the work.",
            what, db_path)


@contextmanager
def connection(db_path, **kwargs):
    """A connection to *db_path*: committed on success, always closed.

    An exception inside the block rolls the transaction back and is
    re-raised, which is what the plain `with sqlite3.connect(...)` form did.
    Keyword arguments are passed to `sqlite3.connect` unchanged; `timeout`
    defaults to the configured lock wait (`lock_timeout`), so a call site
    that names its own is still honoured.
    """
    kwargs.setdefault("timeout", lock_timeout())
    conn = sqlite3.connect(db_path, **kwargs)
    try:
        yield conn
        conn.commit()
    except BaseException:
        _safely(conn.rollback, "roll back", db_path)
        raise
    finally:
        _safely(conn.close, "close", db_path)
