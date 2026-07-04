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
