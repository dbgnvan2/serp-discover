"""serp_checkpoint.py — keep every paid SerpAPI response, and reuse it on resume.

Each successful response the audit fetches (everything that goes through
serp_audit._fetch_serp_api) is written to its own file the moment it arrives,
so a crash, a Stop or a failed run no longer loses what was paid for. A resumed
run re-runs the audit and takes any call it already has from the earlier run's
folder instead of calling SerpAPI again.

Layout:  raw/<run_id>/run_state.json
         raw/<run_id>/calls/<seq>_<engine>_<query-slug>_<hash>.json

Spec: docs/plan_checkpoint_resume_and_m3_2026-11-14.md (C1-C8)
Tests: tests/test_serp_checkpoint.py
"""

import copy
import hashlib
import json
import logging
import os
import re
import time

RAW_DIR = "raw"
RESUME_ENV = "SERP_RESUME_RUN_ID"
DEFAULT_RESUME_MAX_AGE_HOURS = 24.0
SECRET_PARAMS = ("api_key",)

# INCOMPLETE: outputs were written (exit 0) but some queries failed. Every
# status except COMPLETE is offered for resume.
RUNNING, COMPLETE, INCOMPLETE, FAILED = "running", "complete", "incomplete", "failed"

# Request parameters that carry a short-lived token taken from an earlier response.
TOKEN_PARAMS = ("page_token", "next_page_token")


class CheckpointError(Exception):
    """A resume was asked for and cannot be honoured."""


def resume_max_age_hours(config):
    """``serpapi.resume_max_age_hours`` from config.yml. 0 means never reuse."""
    section = config.get("serpapi") if isinstance(config, dict) else None
    value = section.get("resume_max_age_hours") if isinstance(section, dict) else None
    if value is None:
        return DEFAULT_RESUME_MAX_AGE_HOURS
    try:
        if isinstance(value, bool):
            raise ValueError("boolean")
        hours = float(value)
        if not 0 <= hours < float("inf"):
            raise ValueError("negative")
        return hours
    except (TypeError, ValueError):
        logging.warning(f"config serpapi.resume_max_age_hours={value!r} is not a number of hours; "
                        f"using {DEFAULT_RESUME_MAX_AGE_HOURS:g}.")
        return DEFAULT_RESUME_MAX_AGE_HOURS


def _public_params(params):
    return {k: v for k, v in params.items() if k not in SECRET_PARAMS}


def call_key(params):
    """Identity of one SerpAPI call: every request parameter except the API key."""
    text = json.dumps(_public_params(params), sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text, limit=40):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit] or "none"


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class CallStore:
    """The stored responses of one run, plus an optional earlier run to reuse."""

    def __init__(self, run_id, resume_run_id=None, max_age_hours=DEFAULT_RESUME_MAX_AGE_HOURS,
                 raw_dir=RAW_DIR, now=time.time):
        self.run_id = run_id
        self.calls_dir = os.path.join(raw_dir, run_id, "calls")
        self.resume_run_id = resume_run_id or None
        self.reused = 0
        self.stale = 0
        self.refetched = 0          # stored, but not reused: see _chain_complete
        self.failed_queries = 0     # set by fetch_summary() near the end of the run
        self._followed_tokens = set()
        self._last_plain = -1
        self._seq = 0
        self._last_label = None
        self._now = now
        self._resume = {}
        if self.resume_run_id:
            self._load_resume(os.path.join(raw_dir, self.resume_run_id, "calls"), max_age_hours)

    def _load_resume(self, folder, max_age_hours):
        if not os.path.isdir(folder):
            raise CheckpointError(
                f"Cannot resume run {self.resume_run_id}: {folder} does not exist.")
        oldest_allowed = self._now() - max_age_hours * 3600
        unreadable = 0
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            try:
                record = _read_json(os.path.join(folder, name))
                key, saved_at = record["key"], float(record["saved_at"])
                record["response"]
            except (OSError, ValueError, KeyError, TypeError):
                unreadable += 1
                continue
            if saved_at < oldest_allowed:
                self.stale += 1
                continue
            params = record.get("params") or {}
            record["_order"] = order = len(self._resume)
            tokens = [params[k] for k in TOKEN_PARAMS if params.get(k)]
            self._followed_tokens.update(tokens)
            if not tokens:
                self._last_plain = order
            self._resume[key] = record
        if self.stale or unreadable:
            logging.warning(
                f"Resume from {self.resume_run_id}: ignored {self.stale} stored responses older "
                f"than {max_age_hours:g}h and {unreadable} unreadable files; those calls will be "
                "fetched again.")
        logging.info(f"Resume from {self.resume_run_id}: {len(self._resume)} stored responses "
                     "available.")

    def _path(self, params, key):
        self._seq += 1
        self._last_label = f"{self._seq:04d}_{_slug(params.get('q', ''))}"
        name = f"{self._seq:04d}_{_slug(params.get('engine', 'engine'), 30)}_" \
               f"{_slug(params.get('q', ''))}_{key[:8]}.json"
        return os.path.join(self.calls_dir, name)

    def _write(self, params, key, response, saved_at):
        os.makedirs(self.calls_dir, exist_ok=True)
        record = {"key": key, "saved_at": saved_at, "params": _public_params(params),
                  "response": response}
        text = json.dumps(record)
        for name in SECRET_PARAMS:               # belt and braces: no key inside a response
            secret = params.get(name)
            if secret and str(secret) in text:
                record = json.loads(text.replace(str(secret), "REDACTED"))
        _write_json_atomic(self._path(params, key), record)

    def lookup(self, params):
        """The stored response for this call from the run being resumed, or None.
        A hit is copied into this run's folder so this run can be resumed too."""
        record = self._resume.get(call_key(params))
        if record is None:
            return None
        if not self._chain_complete(record):
            self.refetched += 1
            logging.info(f"Stored response for '{params.get('q')}' not reused: its follow-up "
                         "calls were not finished, and their tokens expire. Fetching it again.")
            return None
        self.reused += 1
        logging.info(f"Served from run {self.resume_run_id} (no SerpAPI call): "
                     f"{params.get('engine')} '{params.get('q', '')}'")
        self._save_quietly(params, record["key"], record["response"], record["saved_at"])
        return copy.deepcopy(record["response"])

    def _chain_complete(self, record):
        """False when reusing this response would send an expired token.

        A SERP response can carry tokens for follow-up calls (AI Overview,
        related questions). The tokens are short-lived, so a stored response
        is only useful together with its stored follow-ups:
        - an AI Overview token must have its follow-up stored;
        - related-question tokens are followed only up to a configured count,
          so the test is that the earlier run went on to a later ordinary call.
        Follow-up responses themselves are always reused.
        """
        if any((record.get("params") or {}).get(k) for k in TOKEN_PARAMS):
            return True
        response = record["response"] if isinstance(record["response"], dict) else {}
        overview = response.get("ai_overview")
        token = overview.get("page_token") if isinstance(overview, dict) else None
        if token and token not in self._followed_tokens:
            return False
        related = response.get("related_questions") or []
        has_related_tokens = any(isinstance(i, dict) and i.get("next_page_token") for i in related)
        return not (has_related_tokens and record["_order"] >= self._last_plain)

    def save(self, params, response):
        """Store one successful response. A failed write must not fail a paid call."""
        self._save_quietly(params, call_key(params), response, self._now())

    def _save_quietly(self, params, key, response, saved_at):
        try:
            self._write(params, key, response, saved_at)
        except (OSError, TypeError, ValueError) as e:
            logging.error(f"Could not store SerpAPI response for '{params.get('q')}': {e}. "
                          "The run continues; this call cannot be reused by a resume.")

    def raw_file_label(self):
        """Prefix for the per-engine raw files, so they stop overwriting each other."""
        return self._last_label

    def summary(self):
        return {"resumed_from": self.resume_run_id, "reused_calls": self.reused}


def open_store(run_id, config, environ=os.environ, raw_dir=RAW_DIR):
    """The CallStore for this run, resuming ``SERP_RESUME_RUN_ID`` when it is set."""
    resume = (environ.get(RESUME_ENV) or "").strip() or None
    return CallStore(run_id, resume, resume_max_age_hours(config), raw_dir=raw_dir)


# --- the store of the run in progress (what serp_audit calls) ----------------

ACTIVE = None


def lookup(params):
    return ACTIVE.lookup(params) if ACTIVE else None


def save(params, response):
    if ACTIVE:
        ACTIVE.save(params, response)


def raw_file_prefix():
    """"0007_some-query_" during a tracked run, "" otherwise."""
    label = ACTIVE.raw_file_label() if ACTIVE else None
    return f"{label}_" if label else ""


def summary():
    return ACTIVE.summary() if ACTIVE else {"resumed_from": None, "reused_calls": 0}


def fetch_summary(run_summary):
    """The audit's fetch summary plus the resume counts. Also notes how many
    queries failed, so a run that exits 0 with failures stays resumable."""
    if ACTIVE:
        ACTIVE.failed_queries = (len(run_summary.get("failed") or [])
                                 + len(run_summary.get("pivot_failed") or []))
    return {**run_summary, **summary()}


def calls_line(new_calls):
    """The end-of-run count line. Keeps the old wording when nothing was reused."""
    reused = summary()["reused_calls"]
    if not reused:
        return f"--- Total SerpApi Calls: {new_calls} ---"
    return f"--- Reused {reused} stored responses; made {new_calls} new SerpAPI calls ---"


# --- run state ---------------------------------------------------------------

def write_run_state(run_id, status, raw_dir=RAW_DIR, **fields):
    folder = os.path.join(raw_dir, run_id)
    path = os.path.join(folder, "run_state.json")
    state = {}
    try:
        state = _read_json(path)
    except (OSError, ValueError):
        pass
    state.update(fields)
    state.update({"run_id": run_id, "status": status, "updated_at": time.time()})
    try:
        os.makedirs(folder, exist_ok=True)
        _write_json_atomic(path, state)
    except OSError as e:
        logging.warning(f"Could not write {path}: {e}")


def tracked_run(run_id, input_csv, config, run, raw_dir=RAW_DIR, environ=os.environ):
    """Run ``run(run_id)`` (returns an exit code) with its call store open and
    its state recorded on disk.

    A run that is killed stays "running" on disk, which the launcher reads as
    "did not finish". A resume that cannot be honoured fails the run before
    any call is made, rather than quietly paying for everything again.
    """
    global ACTIVE
    write_run_state(run_id, RUNNING, raw_dir=raw_dir,
                    input_csv=os.path.basename(input_csv or ""), started_at=time.time())
    status = FAILED
    try:
        try:
            ACTIVE = open_store(run_id, config, environ=environ, raw_dir=raw_dir)
        except CheckpointError as e:
            logging.error(str(e))
            return 1
        code = run(run_id)
        if code != 0:
            status = FAILED
        else:
            status = INCOMPLETE if ACTIVE.failed_queries else COMPLETE
        return code
    finally:
        fields = summary()
        if ACTIVE:
            fields["failed_queries"] = ACTIVE.failed_queries
        ACTIVE = None
        write_run_state(run_id, status, raw_dir=raw_dir, **fields)


def find_resumable_run(input_csv, max_age_hours, raw_dir=RAW_DIR, now=time.time):
    """The newest run for this keyword file, if it did not finish and can be reused.

    Returns ``{"run_id", "stored_calls", "age_minutes"}`` or None. Only the
    newest run for the file is considered: if that one completed, there is
    nothing to resume.
    """
    wanted = os.path.basename(input_csv or "")
    if not wanted or max_age_hours <= 0 or not os.path.isdir(raw_dir):
        return None
    newest = None
    for run_id in os.listdir(raw_dir):
        try:
            state = _read_json(os.path.join(raw_dir, run_id, "run_state.json"))
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict) or state.get("input_csv") != wanted:
            continue
        started = float(state.get("started_at") or 0)
        if newest is None or started > newest[0]:
            newest = (started, run_id, state)
    if newest is None or newest[2].get("status") == COMPLETE:
        return None
    calls_dir = os.path.join(raw_dir, newest[1], "calls")
    oldest_allowed = now() - max_age_hours * 3600
    fresh = []
    for name in os.listdir(calls_dir) if os.path.isdir(calls_dir) else []:
        try:
            saved_at = float(_read_json(os.path.join(calls_dir, name))["saved_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if saved_at >= oldest_allowed:
            fresh.append(saved_at)
    if not fresh:
        return None
    return {"run_id": newest[1], "stored_calls": len(fresh),
            "age_minutes": int((now() - min(fresh)) // 60)}
