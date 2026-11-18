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

import atexit
import logging
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime

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


#: Cleanup failures this process has seen, keyed by `(what, db_path)`.
#:
#: Chunk Y11 stopped a failing `rollback()` or `close()` replacing the
#: exception that caused it, which was right — a failing cleanup is a second
#: fact, not the diagnosis — but the second fact then only reached stderr. The
#: GUI operator reads the workbook, and one `logger.exception` per occurrence
#: is not the same statement as "this happened 437 times", which is what a
#: repeating failed `close()` inside a loop is: one leaked file descriptor
#: each (P2, review chunk Y13).
_CLEANUP_FAILURES: dict = {}
#: The tally is read and written from the GUI's worker thread as well as its
#: Tk thread, so `dict[key] = dict.get(key) + 1` could lose a count and a
#: `dict(...)` copy could raise `RuntimeError: dictionary changed size during
#: iteration` — a diagnostic aborting the run it was diagnosing (the cold
#: review of this chunk, P2/P40).
_CLEANUP_LOCK = threading.Lock()
_CLEANUP_REPORTED = False

#: The step names `_safely` records, so the consequence can be chosen by what
#: actually failed rather than by a literal repeated in three modules (P32).
ROLL_BACK = "roll back"
CLOSE = "close"


def cleanup_failures() -> dict:
    """A copy of this process's cleanup tally, `{(what, db_path): count}`."""
    with _CLEANUP_LOCK:
        return dict(_CLEANUP_FAILURES)


def cleanup_failure_count() -> int:
    """How many cleanup steps have failed in this process."""
    with _CLEANUP_LOCK:
        return sum(_CLEANUP_FAILURES.values())


def reset_cleanup_failures() -> None:
    """Start a fresh tally, and let it be reported again.

    The audit calls this where its run begins. It is not called by every entry
    point, because they are separate processes: `run_pipeline` and the GUI
    launch each step with `subprocess`, so a step starts with an empty tally
    anyway. `refresh_analysis_outputs` is the one step the GUI runs in its own
    process, and it reports at exit like any other (the cold review of this
    chunk corrected a docs claim that every entry point resets).
    """
    global _CLEANUP_REPORTED
    with _CLEANUP_LOCK:
        _CLEANUP_FAILURES.clear()
        _CLEANUP_REPORTED = False


#: The fallback copy of the editorial wording, for a `serp_vocab.yml` that
#: cannot be read. It is verbatim equal to the file's text — the first version
#: stopped at "its figures stand" and so dropped the diagnosis in the one
#: situation the fallback exists for (the cold review of this chunk, P32). A
#: test asserts the two are identical.
_CLEANUP_DEFAULTS = {
    "warning": ("{failures} database cleanup step(s) failed during this run "
                "({detail}). {consequence} A cleanup that keeps failing "
                "usually means the database file or its directory has become "
                "unwritable, and each failed close holds a file handle open "
                "until the process exits"),
    "consequence_committed": ("The run's own writes were committed and its "
                              "figures stand."),
    "consequence_rolled_back": (
        "At least one of them was a failed rollback, which means a block "
        "raised and abandoned its transaction: what that step was writing is "
        "incomplete, and the earlier steps' committed figures stand."),
    "detail_item": "{count} x {what}",
    "paths": ". The database(s) involved: {paths}",
    "after_output": ("{further} further database cleanup step(s) failed after "
                     "this run's output was written, so the row in it counts "
                     "only the {counted} that came before"),
}


def _cleanup_vocab() -> dict:
    """The editorial `db_cleanup` block, or `{}` if it cannot be read.

    `pattern_matching` is imported here rather than at module scope: this
    module is what every other one opens the database through, and it does not
    load YAML to do that. The handler is narrow — `pattern_matching` raises
    `KeyError` at import when `serp_vocab.yml` loses a top-level key, which is
    the intended degrade — and says so at debug level, so a silent revert to
    the Python copy is traceable (the cold review of this chunk, P40).
    """
    try:
        from pattern_matching import SERP_VOCAB
        block = SERP_VOCAB.get("db_cleanup") or {}
        return block if isinstance(block, dict) else {}
    except (ImportError, KeyError, AttributeError, TypeError):
        logger.debug("serp_vocab.yml db_cleanup could not be read; using the "
                     "built-in wording.", exc_info=True)
        return {}


def _format(template: str, fallback: str, **values) -> str:
    """*template* filled in, or *fallback* if the editorial text is broken."""
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError, TypeError):
        return fallback.format(**values)


def cleanup_failure_warning() -> str | None:
    """The reader-facing sentence for this process's tally, or None.

    The words are editorial and live in `serp_vocab.yml` under `db_cleanup`,
    like `fetch_status` beside them: an operator has to act on a repeating
    cleanup failure, so the wording is theirs to refine (P4).
    """
    failures = cleanup_failures()
    if not failures:
        return None
    vocab = _cleanup_vocab()

    def _template(key):
        return str(vocab.get(key) or _CLEANUP_DEFAULTS[key])

    # Steps, not paths, for the count: one database failing to close three
    # times and three failing once each are the same number of leaked
    # handles. The paths are named separately, because the operator's next
    # action is to check a file and since chunk Y12 the path is configurable
    # (the cold review of this chunk).
    by_step: dict = {}
    for (what, _db_path), count in failures.items():
        by_step[what] = by_step.get(what, 0) + count
    detail_item = _template("detail_item")
    detail = ", ".join(
        _format(detail_item, _CLEANUP_DEFAULTS["detail_item"],
                count=count, what=what)
        for what, count in sorted(by_step.items()))
    consequence = _template("consequence_rolled_back" if ROLL_BACK in by_step
                            else "consequence_committed")
    text = _format(_template("warning"), _CLEANUP_DEFAULTS["warning"],
                   failures=sum(by_step.values()), detail=detail,
                   consequence=consequence)
    paths = sorted({path for _what, path in failures})
    if len(paths) > 1:
        text += _format(_template("paths"), _CLEANUP_DEFAULTS["paths"],
                        paths=", ".join(paths))
    return text


def cleanup_failures_after(counted: int) -> str | None:
    """The sentence for failures that arrived after an output was written.

    A run's workbook cannot be amended once it is on disk, and the run keeps
    writing to the database after it: the report's trend reads and the write
    that marks the run complete both come later, and "the database file has
    become unwritable" is as likely to begin late as early. The audit calls
    this with the count its row carried, so a late failure is stated rather
    than counted into a dict nobody reads again (the cold review of this
    chunk, P2).
    """
    further = cleanup_failure_count() - counted
    if further <= 0:
        return None
    return _format(str(_cleanup_vocab().get("after_output")
                       or _CLEANUP_DEFAULTS["after_output"]),
                   _CLEANUP_DEFAULTS["after_output"],
                   further=further, counted=counted)


def cleanup_warning_row(run_id) -> dict | None:
    """The audit's `parsing_warnings` row for the tally, or None.

    The row shape lives here, beside the tally, so it can be asserted against
    the workbook contract (`validate_xlsx_vs_json.SPECS`) without running the
    audit: `Run_ID`, `Module` and `Message` are the columns that validation
    requires of every row on that sheet.
    """
    warning = cleanup_failure_warning()
    if not warning:
        return None
    return {"Run_ID": run_id, "Created_At": datetime.now().isoformat(),
            "Module": __name__, "Field": "cleanup", "Message": warning}


def report_cleanup_failures(printer=None, counted: int = None) -> str | None:
    """Print the tally once, wherever a run ends, and return what was printed.

    Fifteen modules open the database through this one, and each pipeline step
    is its own process; only the audit renders the sentence into an artefact.
    This is the floor for the rest, and for the audit's own abort paths:
    registered at exit, so a step that writes no reader-facing output, and a
    run that ends early, still say it happened instead of leaving it in the
    log (P5/P2, the cold review of this chunk). *counted* is how many the
    caller's own output already carried; any that arrived after it are stated
    separately, because that output cannot be amended.
    """
    global _CLEANUP_REPORTED
    warning = cleanup_failure_warning()
    _CLEANUP_REPORTED = True
    if not warning:
        return None
    say = printer or (lambda line: print(line, file=sys.stderr))
    say(f"{warning}.")
    if counted is not None:
        late = cleanup_failures_after(counted)
        if late:
            say(f"{late}.")
    return warning


def _report_cleanup_failures_at_exit() -> None:
    """Say it on the way out if nothing else did."""
    if _CLEANUP_FAILURES and not _CLEANUP_REPORTED:
        report_cleanup_failures()


atexit.register(_report_cleanup_failures_at_exit)


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
        # The counting is itself inside the handler, so it must not escape and
        # replace the caller's exception — the defect chunk Y11 removed.
        seen = "an uncounted"
        try:
            key = (what, str(db_path))
            with _CLEANUP_LOCK:
                _CLEANUP_FAILURES[key] = _CLEANUP_FAILURES.get(key, 0) + 1
                seen = _CLEANUP_FAILURES[key]
        except Exception:
            pass
        logger.exception(
            "Could not %s the connection to %s (%s time(s) in this run). The "
            "original outcome of the block stands; this is a failure of the "
            "cleanup, not of the work.",
            what, db_path, seen)


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
        _safely(conn.rollback, ROLL_BACK, db_path)
        raise
    finally:
        _safely(conn.close, CLOSE, db_path)
