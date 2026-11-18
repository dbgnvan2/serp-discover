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
import os
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


#: The database every module opens when its caller names none. It was the
#: literal `"serp_data.db"` at 24 sites in 17 modules, with no config key at
#: all — and every one of those literals was relative to the current working
#: directory, so a reader run from anywhere but the repo root created a new
#: empty database beside itself instead of reporting that the history was
#: missing (P4/P16, review chunk Y12).
DEFAULT_DATABASE_NAME = "serp_data.db"

#: Where the path is configured, and the directory a relative one resolves
#: against: the repo root, which is where `config.yml` lives. Tool 2 resolves
#: its own `technical.database_path` against its config file for the same
#: reason.
DATABASE_PATH_SOURCE = ("database", "path")
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

#: The resolved path. Rebound by `apply_database_path`; read through
#: `database_path()`, never as a default argument, which binds at import.
DATABASE_PATH = os.path.join(_REPO_ROOT, DEFAULT_DATABASE_NAME)


def database_path() -> str:
    """The database this process opens when the caller names none."""
    return DATABASE_PATH


def resolve_database_path(configured) -> str:
    """*configured* as an absolute path, or the documented default.

    A relative path resolves against the repo root rather than the current
    working directory: `"serp_data.db"` read from the config means the one
    database this tool keeps, not a new empty file in whatever directory the
    script was started from.
    """
    if configured is None:
        configured = DEFAULT_DATABASE_NAME
    elif not isinstance(configured, str) or not configured.strip():
        logger.warning(
            "config.yml %s.%s is %r, which is not a path; using %s.",
            DATABASE_PATH_SOURCE[0], DATABASE_PATH_SOURCE[1], configured,
            DEFAULT_DATABASE_NAME)
        configured = DEFAULT_DATABASE_NAME
    configured = os.path.expanduser(configured.strip())
    if os.path.isabs(configured):
        return configured
    return os.path.normpath(os.path.join(_REPO_ROOT, configured))


def apply_database_path(cfg: dict | None) -> str:
    """Set this process's database path from *cfg*, and return it.

    Called by `process_config.apply`, like the lock wait beside it, so the one
    function every loader of `config.yml` already calls carries this too.
    """
    global DATABASE_PATH
    section_name, cfg_key = DATABASE_PATH_SOURCE
    section = cfg.get(section_name) if isinstance(cfg, dict) else None
    configured = section.get(cfg_key) if isinstance(section, dict) else None
    DATABASE_PATH = resolve_database_path(configured)
    return DATABASE_PATH


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


#: Paths already reported as new, so the notice is one line per database per
#: process rather than one per connection.
_ANNOUNCED_NEW = set()


def _announce_if_new(db_path) -> None:
    """Say so when this is a database being created, not one being opened.

    `sqlite3.connect` creates whatever path it is handed. While the name was a
    literal that could not be wrong, this did not matter; now that
    `database.path` is editable, a typo or an unmounted volume produces a new
    empty history that every reader then reports as "no history yet" — a
    mistake and a transient condition both delivered as a fact about the
    client (P1/P2/P6, the cold review of chunk Y12).
    """
    try:
        if db_path in _ANNOUNCED_NEW or os.path.exists(db_path):
            return
        _ANNOUNCED_NEW.add(db_path)
        logger.warning(
            "Creating a new, empty SQLite database at %s. If this is not where "
            "the history should be, check config.yml %s.%s — nothing has been "
            "read from an existing database.",
            db_path, DATABASE_PATH_SOURCE[0], DATABASE_PATH_SOURCE[1])
    except (TypeError, ValueError, OSError):
        # A path-like this check cannot stat is `sqlite3.connect`'s problem to
        # report, not a reason to fail before it gets there.
        pass


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
    _announce_if_new(db_path)
    conn = sqlite3.connect(db_path, **kwargs)
    try:
        yield conn
        conn.commit()
    except BaseException:
        _safely(conn.rollback, "roll back", db_path)
        raise
    finally:
        _safely(conn.close, "close", db_path)
