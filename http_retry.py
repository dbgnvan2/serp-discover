"""http_retry.py — shared transient-error retry for DA provider clients.

Spec: seo_geo_review_20260704.md C.6 — previously one transient network
failure silently dropped a whole batch of Domain Authority data, skewing
feasibility averages downstream.
"""
import logging
import time
from types import MappingProxyType

import requests

logger = logging.getLogger(__name__)

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Documented defaults. The live values are editorial, in `config.yml` under
#: `http_retry`; SerpAPI's own retry has been configurable since the
#: start (`serpapi.retry_max_attempts`), so one of the tool's two retry
#: policies could be tuned and the other could not (P4/P25, review chunk Y4).
#: Frozen, so the fallback is always the documented default and never a value
#: a previous `apply_retry_policy` left behind — the module constants below
#: are rebound, so reading them as the fallback made the policy compound.
DEFAULT_RETRY_POLICY = MappingProxyType({
    "attempts": 2,
    "backoff": 1.0,
    "max_retry_after": 30.0,
})

RETRY_ATTEMPTS = DEFAULT_RETRY_POLICY["attempts"]
RETRY_BACKOFF_SECONDS = DEFAULT_RETRY_POLICY["backoff"]
MAX_RETRY_AFTER_SECONDS = DEFAULT_RETRY_POLICY["max_retry_after"]


def resolve_retry_policy(cfg: dict | None = None) -> dict:
    """``{attempts, backoff, max_retry_after}`` from config `http_retry`.

    `config.yml`, not the shared config: this is one tool's own outbound
    policy, and `technical.*` is the cross-tool namespace.

    A value that is not a positive number is reported and the documented
    default used: 0 attempts would make every transient failure terminal, and
    a report cannot tell a configured 0 from a typo.
    """
    block = (cfg or {}).get("http_retry") or {}
    out = dict(DEFAULT_RETRY_POLICY)
    if not isinstance(block, dict):
        logger.warning(
            "config.yml http_retry is %r, not a block of settings; using the "
            "documented defaults %r.", block, out)
        return out
    for key, cfg_key, cast in (("attempts", "attempts", int),
                               ("backoff", "backoff_seconds", float),
                               ("max_retry_after", "max_retry_after_seconds",
                                float)):
        if cfg_key not in block:
            continue
        raw = block[cfg_key]
        if isinstance(raw, bool):
            logger.warning(
                "config.yml http_retry.%s is %r, which is not a number; "
                "using the documented default %s.", cfg_key, raw, out[key])
            continue
        try:
            value = cast(raw)
        except (TypeError, ValueError):
            logger.warning(
                "config.yml http_retry.%s is %r, which is not a "
                "number; using the documented default %s.",
                cfg_key, raw, out[key])
            continue
        if value <= 0:
            logger.warning(
                "config.yml http_retry.%s is %r, which is %s as a retry "
                "policy; zero or less makes every transient failure terminal "
                "(P1). Using the documented default %s.",
                cfg_key, raw, value, out[key])
            continue
        out[key] = value
    return out


def apply_retry_policy(cfg: dict | None) -> dict:
    """Set this process's retry defaults from *cfg* and return the policy.

    The two helpers read the module constants as their default arguments, so
    one assignment here reaches every caller that does not pass its own —
    which is all of them (P25: one config→argument mapping, not one per call
    site).
    """
    global RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, MAX_RETRY_AFTER_SECONDS
    policy = resolve_retry_policy(cfg)
    RETRY_ATTEMPTS = policy["attempts"]
    RETRY_BACKOFF_SECONDS = policy["backoff"]
    MAX_RETRY_AFTER_SECONDS = policy["max_retry_after"]
    return policy

#: Request errors that will fail again however many times they are retried:
#: the URL cannot be turned into a request, or the server sends the client
#: round a loop. :func:`get_with_transient_retry` re-raises these instead of
#: retrying and then reporting them as "retryable", which is what it did for
#: every `RequestException` alike until the cold review of chunk Y2 — so a
#: malformed URL and a host that does not resolve were both reported to the
#: reader as pages that might read fine on the next run.
PERMANENT_REQUEST_ERRORS = (
    requests.exceptions.MissingSchema,
    requests.exceptions.InvalidSchema,
    requests.exceptions.InvalidURL,
    requests.exceptions.URLRequired,
    requests.exceptions.TooManyRedirects,
)


def get_with_transient_retry(
    api_name,
    url,
    headers,
    batch_desc,
    timeout=30,
    attempts=None,
    backoff=None,
    get=None,
    **kwargs,
):
    """GET with retry on network errors and transient HTTP statuses.

    The same policy as :func:`post_with_transient_retry`, and for the same
    reason (P5: a class of calls is hardened together, not one site at a
    time). ``url_enricher`` fetched every ranked page with a bare
    ``requests.get`` and one timeout, so a single connection reset filed a
    page as unreachable and its word count, schema, author signals and
    extractability as not measured for the whole run — while every other
    outbound call in the tool retried (review chunk Y2).

    Returns the final :class:`requests.Response` (possibly non-ok), or
    ``None`` when every attempt failed at the network layer. ``kwargs`` are
    passed through to the getter (``allow_redirects``, ``stream``, ...).
    """
    if get is None:
        get = requests.get
    # Resolved here, not as a default argument: a default is bound when the
    # function is defined, so `apply_retry_policy` rebinding the module
    # globals would never reach a caller that omits them (review chunk Y4).
    attempts = RETRY_ATTEMPTS if attempts is None else attempts
    backoff = RETRY_BACKOFF_SECONDS if backoff is None else backoff
    response = None
    for attempt in range(1, attempts + 1):
        try:
            response = get(url, headers=headers, timeout=timeout, **kwargs)
        except PERMANENT_REQUEST_ERRORS as exc:
            # Not transient: a URL that cannot be turned into a request, or a
            # redirect loop. Retrying spends `attempts × timeout` to reach the
            # same answer, and the caller needs to know it is permanent so it
            # does not tell a reader to try again (cold review of chunk Y2).
            logger.warning(
                "%s request cannot be made for %s: %s",
                api_name, batch_desc, exc,
            )
            raise
        except requests.RequestException as exc:
            logger.warning(
                "%s request failed (attempt %d) for %s: %s",
                api_name, attempt, batch_desc, exc,
            )
            response = None
            if attempt == attempts:
                return None
            time.sleep(backoff * attempt)
            continue
        if response.status_code in TRANSIENT_STATUSES and attempt < attempts:
            delay = backoff * attempt
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
                except ValueError:
                    pass
            logger.warning(
                "%s transient %d (attempt %d) for %s — retrying in %.1fs",
                api_name, response.status_code, attempt, batch_desc, delay,
            )
            time.sleep(delay)
            continue
        return response
    return response


def post_with_transient_retry(
    api_name,
    url,
    headers,
    json_payload,
    batch_desc,
    timeout=30,
    attempts=None,
    backoff=None,
    post=None,
):
    """POST with retry on network errors and transient HTTP statuses.

    Returns the final :class:`requests.Response` (possibly non-ok for
    non-transient statuses — the caller handles those), or ``None`` when
    every attempt failed at the network layer. Honors a numeric
    ``Retry-After`` header on transient statuses, capped at
    :data:`MAX_RETRY_AFTER_SECONDS`.
    """
    # See `get_with_transient_retry`: resolved here, not as a default.
    attempts = RETRY_ATTEMPTS if attempts is None else attempts
    backoff = RETRY_BACKOFF_SECONDS if backoff is None else backoff
    # Callers pass their own module's requests.post so existing test
    # patch targets (e.g. moz_client.requests.post) keep intercepting.
    if post is None:
        post = requests.post
    response = None
    for attempt in range(1, attempts + 1):
        try:
            response = post(
                url, headers=headers, json=json_payload, timeout=timeout
            )
        except requests.RequestException as exc:
            logger.warning(
                "%s request failed (attempt %d) for %s: %s",
                api_name, attempt, batch_desc, exc,
            )
            response = None
            if attempt == attempts:
                return None
            time.sleep(backoff * attempt)
            continue
        if response.status_code in TRANSIENT_STATUSES and attempt < attempts:
            delay = backoff * attempt
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
                except ValueError:
                    pass
            logger.warning(
                "%s transient %d (attempt %d) for %s — retrying in %.1fs",
                api_name, response.status_code, attempt, batch_desc, delay,
            )
            time.sleep(delay)
            continue
        return response
    return response
