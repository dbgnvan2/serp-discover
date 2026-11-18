"""http_retry.py — shared transient-error retry for DA provider clients.

Spec: seo_geo_review_20260704.md C.6 — previously one transient network
failure silently dropped a whole batch of Domain Authority data, skewing
feasibility averages downstream.
"""
import logging
import time
from types import MappingProxyType

import requests

from timeouts import seconds_from_config

logger = logging.getLogger(__name__)

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Documented defaults. The live values are editorial, in `config.yml` under
#: `http_retry`; SerpAPI's own retry has been configurable since the
#: start (`serpapi.retry_max_attempts`), so one of the tool's two retry
#: policies could be tuned and the other could not (P4/P25, review chunk Y4).
#: Frozen, so the fallback is always the documented default and never a value
#: a previous `apply_retry_policy` left behind — the module constants below
#: are rebound, so reading them as the fallback made the policy compound.
#: Three timeout classes, because one number cannot serve all three: a DA or
#: GSC API answers in about a second, a ranked page may be slow and there are
#: dozens of them per run, and an LLM with web search routinely takes tens of
#: seconds. Each was a per-module Python constant until review chunk Y5, while
#: the retry budget beside them became editorial in Y4 — one outbound policy
#: that could be tuned in halves (P4/P25).
#:
#: Two of the three already had a config home and keep it (Y1 — one definition
#: each): the ranked-page wait is `enrichment.timeout_seconds`, which
#: `serp_audit` has always passed to `UrlEnricher`, and the probe's LLM wait is
#: `ai_visibility.timeout_seconds` beside the engine list it belongs to. Only
#: the generic API wait, which had no home at all, is an `http_retry` key.
DEFAULT_RETRY_POLICY = MappingProxyType({
    "attempts": 2,
    "backoff": 1.0,
    "max_retry_after": 30.0,
    "timeout": 30.0,
    "page_fetch_timeout": 10.0,
    "llm_timeout": 60.0,
})

RETRY_ATTEMPTS = DEFAULT_RETRY_POLICY["attempts"]
RETRY_BACKOFF_SECONDS = DEFAULT_RETRY_POLICY["backoff"]
MAX_RETRY_AFTER_SECONDS = DEFAULT_RETRY_POLICY["max_retry_after"]
REQUEST_TIMEOUT_SECONDS = DEFAULT_RETRY_POLICY["timeout"]
PAGE_FETCH_TIMEOUT_SECONDS = DEFAULT_RETRY_POLICY["page_fetch_timeout"]
LLM_TIMEOUT_SECONDS = DEFAULT_RETRY_POLICY["llm_timeout"]


def request_timeout() -> float:
    """The API-call timeout this process is configured with.

    A function, not a constant read at import: `apply_retry_policy` rebinds
    the module globals, and a caller that captured the value in a default
    argument would never see the configured one (the Y4 trap).
    """
    return REQUEST_TIMEOUT_SECONDS


def page_fetch_timeout() -> float:
    """The ranked-page fetch timeout this process is configured with."""
    return PAGE_FETCH_TIMEOUT_SECONDS


def llm_timeout() -> float:
    """The LLM-answer timeout this process is configured with."""
    return LLM_TIMEOUT_SECONDS


#: Where each timeout class is configured: policy key -> (config section,
#: key in it). Read by `resolve_retry_policy`, so there is one table rather
#: than a `cfg.get(...)` at each call site.
TIMEOUT_SOURCES = MappingProxyType({
    "timeout": ("http_retry", "timeout_seconds"),
    "page_fetch_timeout": ("enrichment", "timeout_seconds"),
    "llm_timeout": ("ai_visibility", "timeout_seconds"),
})


def resolve_retry_policy(cfg: dict | None = None) -> dict:
    """The outbound policy: retry budget plus the three timeout classes.

    `config.yml`, not the shared config: this is one tool's own outbound
    policy, and `technical.*` is the cross-tool namespace. The retry budget
    comes from `http_retry`; each timeout comes from the section named in
    `TIMEOUT_SOURCES`.

    A value that is not a positive number is reported and the documented
    default used: 0 attempts would make every transient failure terminal, 0
    seconds would fail every call, and a report cannot tell a configured 0
    from a typo.
    """
    cfg = cfg or {}
    block = cfg.get("http_retry") or {}
    out = dict(DEFAULT_RETRY_POLICY)
    for key, (section_name, cfg_key) in TIMEOUT_SOURCES.items():
        section = cfg.get(section_name)
        if not isinstance(section, dict) or cfg_key not in section:
            continue
        if section[cfg_key] is None:
            # `seconds_from_config` reads `None` as "key absent" and returns
            # the default without a warning, which is right for an absent key
            # and wrong for `timeout_seconds:` written with nothing after it —
            # a typo the reader would never hear about (P2, cold review of
            # chunk Y5).
            logger.warning(
                "config.yml %s.%s is empty; using the documented default %s.",
                section_name, cfg_key, out[key])
            continue
        # `timeouts.seconds_from_config` is this repo's own rule for "a
        # positive number of seconds, else the default with a warning", and it
        # rejects booleans. Reimplementing it here is how two validators come
        # to disagree (P32).
        out[key] = seconds_from_config(
            section[cfg_key], out[key], f"{section_name}.{cfg_key}")
    if not isinstance(block, dict):
        logger.warning(
            "config.yml http_retry is %r, not a block of settings; using the "
            "documented retry defaults.", block)
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
    global REQUEST_TIMEOUT_SECONDS, PAGE_FETCH_TIMEOUT_SECONDS
    global LLM_TIMEOUT_SECONDS
    policy = resolve_retry_policy(cfg)
    RETRY_ATTEMPTS = policy["attempts"]
    RETRY_BACKOFF_SECONDS = policy["backoff"]
    MAX_RETRY_AFTER_SECONDS = policy["max_retry_after"]
    REQUEST_TIMEOUT_SECONDS = policy["timeout"]
    PAGE_FETCH_TIMEOUT_SECONDS = policy["page_fetch_timeout"]
    LLM_TIMEOUT_SECONDS = policy["llm_timeout"]
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
    timeout=None,
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
    timeout = REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
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
    timeout=None,
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
    timeout = REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
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
