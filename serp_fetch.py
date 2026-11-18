"""serp_fetch.py — one SerpAPI call: resume, retry budget, post-response work.

The loop used to live in `serp_audit` and caught every exception the same way,
so a fault in `serp_checkpoint.save` or `link_recovery.recover_response` — both
of which run *after* a response has been paid for — was logged as a fetch
error, retried with up to two more paid calls that would fail the same way, and
then filed beside genuine network failures (P1 in reverse, P40). It is a module
of its own because `serp_audit` is at its 2200-line ceiling and this is the
piece with its own failure taxonomy.

Spec: docs/review_2026-11-04/PLAN_Y8_a_bug_is_not_a_dead_network.md
"""
from __future__ import annotations

import json
import logging
import random
import time

import requests

import http_retry
import link_recovery
import serp_checkpoint
from run_feasibility import _scrub_secrets  # requests errors carry api_key in the URL

try:
    from serpapi import GoogleSearch
    SERPAPI_AVAILABLE = True
except ImportError:
    GoogleSearch = None
    SERPAPI_AVAILABLE = False

try:
    from serpapi.serp_api_client_exception import SerpApiClientException
except ImportError:          # older client, or the package absent entirely
    class SerpApiClientException(Exception):
        """Stand-in so the retry tuple below is always a tuple of types."""

    if SERPAPI_AVAILABLE:
        # The client is installed but does not expose the exception where we
        # look for it, so every error it raises itself now falls into the
        # not-retried branch. Silence here would narrow the retry policy
        # without saying so (P2, cold review of chunk Y8).
        logging.getLogger(__name__).warning(
            "The installed SerpAPI client does not expose "
            "serp_api_client_exception.SerpApiClientException, so an error "
            "raised by the client itself is treated as a fault in this tool "
            "and is not retried. Check the client version.")


#: The failures a retry can fix, caught by name: the request never completed
#: (`requests` raises), the client itself reported a transport problem, or the
#: body was not the JSON it claimed to be. Everything else is a fault in this
#: process, and every attempt costs a paid SerpAPI call, so it is not retried
#: (P40, review chunk Y8). `OSError` covers the socket-level errors that reach
#: us unwrapped; `ConnectionError` and `TimeoutError` are its subclasses and
#: are named for the reader.
SERPAPI_TRANSPORT_ERRORS = (
    requests.RequestException,
    SerpApiClientException,
    json.JSONDecodeError,
    OSError,
)

#: What one `fetch` ended as. Returning a bare `None` for six different
#: outcomes left the new taxonomy in the log file: the run summary recorded
#: "no SERP data returned" for a fault in the tool and a dead host alike, and
#: a resumed run re-paid a call per keyword to fail the same way — the cost the
#: no-retry decision exists to avoid (P2/P9, cold review of chunk Y8).
STATUS_OK = "ok"
STATUS_CLIENT_ABSENT = "client_absent"
STATUS_API_ERROR_SETTLED = "api_error_settled"
STATUS_API_ERROR_PERSISTED = "api_error_persisted"
STATUS_TRANSPORT_FAILED = "transport_failed"
STATUS_INTERNAL_ERROR = "internal_error"
STATUS_NO_BUDGET = "no_retry_budget"

#: The words the run summary and the log use for each outcome. Editorial, and
#: one home for them.
STATUS_TEXT = {
    STATUS_OK: "SERP data returned",
    STATUS_CLIENT_ABSENT: "the SerpAPI client library is not installed",
    STATUS_API_ERROR_SETTLED: "SerpAPI refused the request (settled, not retried)",
    STATUS_API_ERROR_PERSISTED: "SerpAPI returned an error on every attempt",
    STATUS_TRANSPORT_FAILED: "every attempt failed at the network layer",
    STATUS_INTERNAL_ERROR: "a fault in this tool, not the network (not retried)",
    STATUS_NO_BUDGET: "the configured retry budget was not a positive number",
}


def status_text(status: str) -> str:
    """The sentence for one outcome, for a log line or a run summary."""
    return STATUS_TEXT.get(status, status)


#: Paid calls this process has made. Read through `call_count()`.
CALL_COUNT = 0


def call_count() -> int:
    """How many paid SerpAPI calls this process has made."""
    return CALL_COUNT


def fetch(params, *, timeout_seconds, client=None, available=None):
    """`fetch_with_status` for the callers that only need the response."""
    results, _status = fetch_with_status(
        params, timeout_seconds=timeout_seconds, client=client,
        available=available)
    return results


def fetch_with_status(params, *, timeout_seconds, client=None,
                      available=None):
    """One SerpAPI call, with the resume lookup, the retry budget and the
    post-response work.

    Returns ``(results, status)``: the response, or ``None`` with one of the
    ``STATUS_*`` words saying which outcome it was. Six different outcomes
    returned a bare ``None``, so the run summary read "no SERP data returned"
    for a fault in this tool and for a dead host alike (cold review of this
    chunk).

    *client* and *available* default to this module's own client import; the
    pipeline passes its own so a caller that has replaced the client (a test,
    or a run with the library absent) is honoured.

    Spec: docs/review_2026-11-04/PLAN_Y8_a_bug_is_not_a_dead_network.md
    """
    global CALL_COUNT
    client = GoogleSearch if client is None else client
    if not (SERPAPI_AVAILABLE if available is None else available):
        logging.error(
            "SerpApi client library is not installed. Install dependencies with: pip install -r requirements.txt"
        )
        return None, STATUS_CLIENT_ABSENT

    # Redact API Key for logging
    log_params = params.copy()
    if "api_key" in log_params:
        log_params["api_key"] = "REDACTED"
    logging.info(f"API Call Parameters: {json.dumps(log_params, indent=2)}")
    stored = serp_checkpoint.lookup(params)  # resume: a call already paid for
    if stored is not None:
        # Recovered on the way out, not on the way in: the checkpoint keeps
        # SerpAPI's response as it arrived, so a resumed run and a fresh one
        # see the same recovered links.
        link_recovery.recover_response(stored)
        return stored, STATUS_OK
    max_attempts = http_retry.serpapi_retry_attempts()
    if max_attempts < 1:
        # `_read_budget` guarantees a positive budget, so this is reachable
        # only from a direct caller or a patch — and it was the one return
        # path that made no call and logged nothing (cold review of this
        # chunk).
        logging.error(
            "Retry budget is %r, so no SerpAPI call was attempted for '%s'.",
            max_attempts, params.get("q", "N/A"))
        return None, STATUS_NO_BUDGET
    results = None
    for attempt in range(1, max_attempts + 1):
        try:
            CALL_COUNT += 1
            logging.info(f"SerpApi Call Count: {CALL_COUNT}")
            search = client(dict(params))  # the client adds fields to what it is given
            search.timeout = timeout_seconds  # the constructor takes no timeout
            results = search.get_dict()
            # `default=str`: a value the encoder cannot serialise used to
            # raise from the logging statement itself, inside the `try`, and
            # a logging detail then discarded a paid response (cold review of
            # this chunk).
            logging.info(
                f"API Return Message: "
                f"{json.dumps(results, indent=2, default=str)}")
        except SERPAPI_TRANSPORT_ERRORS as e:
            # The failures retrying can fix: a timeout, a reset, a 5xx, a
            # truncated body. Named, not caught as a class, because the loop
            # spends a paid call on every attempt (review chunk Y8).
            results = None
            logging.error(
                f"Fetch error (attempt {attempt}) for query '{params.get('q', 'N/A')}': {_scrub_secrets(e)}"
            )
            if attempt == max_attempts:
                logging.critical(
                    f"CRITICAL ERROR fetching with params {params.get('q')}: {_scrub_secrets(e)}"
                )
                return None, STATUS_TRANSPORT_FAILED
        except Exception as e:
            # Anything else is a bug in this process, and retrying it spends
            # two more paid SerpAPI calls to be told the same thing. It used
            # to be logged as a fetch error, so a `TypeError` read in the log
            # and the run summary exactly like a dead host (P1 in reverse,
            # P40 — review chunk Y8).
            logging.exception(
                f"INTERNAL ERROR fetching '{params.get('q', 'N/A')}' "
                f"(attempt {attempt} of {max_attempts}, not retried — this is "
                f"a fault in the tool, not the network): {_scrub_secrets(e)}"
            )
            return None, STATUS_INTERNAL_ERROR
        else:
            if "error" in results:
                error_text = str(results["error"]).lower()
                # Quota/auth errors never succeed on retry — fail fast
                # instead of burning paid attempts (seo_geo_review C.6).
                # A bad parameter is settled, not transient: retrying it
                # spends the clock and the search allowance to be told the
                # same thing (P1 in reverse).
                non_retryable = (
                    "invalid api key", "unauthorized", "account",
                    "run out of searches", "out of searches", "plan limit",
                    "unsupported", "not supported", "invalid location",
                    "missing query", "invalid parameter", "unrecognized",
                )
                if any(marker in error_text for marker in non_retryable):
                    logging.error(
                        f"API Error (non-retryable, aborting): {results['error']}"
                    )
                    return None, STATUS_API_ERROR_SETTLED
                logging.error(f"API Error (attempt {attempt}): {results['error']}")
                results = None
                if attempt == max_attempts:
                    return None, STATUS_API_ERROR_PERSISTED
            else:
                break
        sleep_s = (http_retry.serpapi_retry_backoff() * (2 ** (attempt - 1))
                   + random.uniform(0, 0.2))
        time.sleep(sleep_s)
    if results is None:
        return None, STATUS_TRANSPORT_FAILED
    # Once, on the response that succeeded, and outside the retry loop: these
    # two run after a response has been paid for, so a fault in either used to
    # be retried with up to two more paid calls that would fail the same way
    # (review chunk Y8).
    #
    # They are two different events and are handled as two (cold review of
    # this chunk). `serp_checkpoint.save` documents its own contract — a
    # failed write must not fail a paid call — and swallows the write errors
    # it expects; anything that still reaches here is a fault in the
    # checkpoint code, and discarding a charged-for SERP over it would be the
    # same catch-all mistake this chunk removed. The response is returned, and
    # the log says the run is not resumable for this call.
    try:
        serp_checkpoint.save(params, results)  # raw, as SerpAPI sent it
    except Exception as e:
        logging.exception(
            f"INTERNAL ERROR storing the response for "
            f"'{params.get('q', 'N/A')}' — a fault in this tool, not the "
            f"network. The response is used; a resumed run will pay for this "
            f"call again: {_scrub_secrets(e)}"
        )
    # Link recovery is different: it rewrites the response in place, so a
    # fault part-way through leaves some links as Google wrappers, and a
    # wrapper reaching the parsers makes google.com the competitor (P1). The
    # response is dropped rather than half-recovered.
    try:
        link_recovery.recover_response(results)
    except Exception as e:
        logging.exception(
            f"INTERNAL ERROR recovering the links for "
            f"'{params.get('q', 'N/A')}' (not retried — this is a fault in "
            f"the tool, not the network). The response is dropped: some links "
            f"would still be Google wrappers: {_scrub_secrets(e)}"
        )
        return None, STATUS_INTERNAL_ERROR
    return results, STATUS_OK


