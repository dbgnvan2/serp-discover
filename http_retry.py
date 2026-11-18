"""http_retry.py — shared transient-error retry for DA provider clients.

Spec: seo_geo_review_20260704.md C.6 — previously one transient network
failure silently dropped a whole batch of Domain Authority data, skewing
feasibility averages downstream.
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 30.0

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
    attempts=RETRY_ATTEMPTS,
    backoff=RETRY_BACKOFF_SECONDS,
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
    attempts=RETRY_ATTEMPTS,
    backoff=RETRY_BACKOFF_SECONDS,
    post=None,
):
    """POST with retry on network errors and transient HTTP statuses.

    Returns the final :class:`requests.Response` (possibly non-ok for
    non-transient statuses — the caller handles those), or ``None`` when
    every attempt failed at the network layer. Honors a numeric
    ``Retry-After`` header on transient statuses, capped at
    :data:`MAX_RETRY_AFTER_SECONDS`.
    """
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
