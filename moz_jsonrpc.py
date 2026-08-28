"""
moz_jsonrpc.py
~~~~~~~~~~~~~~
JSON-RPC 2.0 transport for the Moz Data API (``https://api.moz.com/jsonrpc``).

Purpose: single, hardened entry point for every Moz Data API method call.
Spec:    moz_api_upgrade_spec_v1.md#T.0
Tests:   test_moz_jsonrpc.py

This module is **transport only** — envelope construction, auth, retry,
error classification and secret redaction. It performs no caching, no
scoring and no interpretation of business payloads; those belong to the
per-method modules built on top of it (T.1+).

The legacy Links-API client (``moz_client.MozClient``, ``lsapi.seomoz.com``)
is untouched by this module and keeps working until T.1 replaces it.

Request envelope (from the Moz API docs, binding)::

    {"jsonrpc": "2.0",
     "id": "<uuid-v4, >= 24 chars>",
     "method": "<method>",
     "params": {"data": {...}}}

Environment variables
---------------------
MOZ_TOKEN   Moz API token (required). Read at call time. Absent raises
            ``RuntimeError`` — the same discipline as ``MozClient`` — so a
            caller can set ``MOZ_AVAILABLE = False`` and degrade rather than
            fail silently mid-run.

Failure contract
----------------
Every failure raises :class:`MozRpcError`. Nothing returns ``{}`` on error:
"Moz has no record for this target" and "the call failed" must stay
distinguishable so callers can record ``data_available: false`` honestly
rather than fabricating a zero (external-api E4, learnings P2/P14).

All exception text is passed through :func:`_redact` before it escapes, so a
token echoed back inside an API error body cannot reach a log line
(security S1, external-api E7).
"""

from __future__ import annotations

import logging
import os
import re
import uuid

import requests

from http_retry import post_with_transient_retry as _post_with_transient_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Moz Data API JSON-RPC endpoint (HTTPS only — security S6).
MOZ_JSONRPC_ENDPOINT = "https://api.moz.com/jsonrpc"

#: Request timeout in seconds (external-api E1 — a named value, not a literal
#: at the call site).
REQUEST_TIMEOUT: int = 30

#: JSON-RPC protocol version required by the Moz Data API.
JSONRPC_VERSION = "2.0"

#: ``quota.lookup`` path for the monthly data-row allowance.
QUOTA_PATH_DATA_ROWS = "api.limits.data.rows"

#: Characters of an error response body kept for diagnosis (external-api E7).
ERROR_BODY_SNIPPET_CHARS = 300

#: Credential query-param names that must never reach a log line. Mirrors the
#: rule already applied to SerpAPI URLs in ``run_feasibility._scrub_secrets``.
_CREDENTIAL_PARAM_RE = re.compile(
    r"(?i)\b(api_key|apikey|key|token|secret|password|passwd|login)=([^&\s]+)"
)

#: ``quota.lookup`` reports consumption, not a remaining figure: the real
#: response carries ``allotted`` and ``used`` under ``result.quota``, and
#: remaining has to be derived. Confirmed against a live call on 2026-08-27 —
#: see the captured body in ``test_moz_jsonrpc.QUOTA_RESULT_FIXTURE``.
_QUOTA_KEY = "quota"
_QUOTA_ALLOTTED_KEY = "allotted"
_QUOTA_USED_KEY = "used"


class MozRpcError(RuntimeError):
    """A Moz Data API call failed (network, HTTP, protocol, or JSON-RPC error).

    The message is already redacted — it is safe to log directly.
    """


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

def _redact(text: object) -> str:
    """Return ``str(text)`` with the Moz token and credential params removed.

    An API error body can echo the token that was sent, and ``requests``
    exceptions carry the full request context — logging either naively leaks
    the credential (security S1, external-api E7, learnings P5).
    """
    s = str(text)
    token = os.environ.get("MOZ_TOKEN", "")
    if token:
        s = s.replace(token, "REDACTED")
    return _CREDENTIAL_PARAM_RE.sub(r"\1=REDACTED", s)


def _auth_header() -> dict[str, str]:
    """Build the Moz auth header, raising if ``MOZ_TOKEN`` is unset.

    Raises
    ------
    RuntimeError
        If ``MOZ_TOKEN`` is absent — same discipline and wording as
        ``MozClient.__init__`` so callers can handle both identically.
    """
    token = os.getenv("MOZ_TOKEN")
    if not token:
        raise RuntimeError(
            "Moz credentials not found. Set MOZ_TOKEN in your .env file "
            "(generate a token in the Moz API dashboard)."
        )
    return {"x-moz-token": token, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def build_envelope(method: str, data: dict) -> dict:
    """Return the JSON-RPC 2.0 request envelope for *method* with *data*.

    The ``id`` is a UUID-v4 string (36 chars), satisfying the Moz docs'
    ">= 24 characters" requirement.
    """
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": str(uuid.uuid4()),
        "method": method,
        "params": {"data": data},
    }


def moz_call(
    method: str,
    data: dict,
    *,
    timeout: int = REQUEST_TIMEOUT,
    post=None,
) -> dict:
    """Call a Moz Data API *method* and return its ``result`` object.

    Purpose: hardened single call path for every Moz Data API method.
    Spec:    moz_api_upgrade_spec_v1.md#T.0
    Tests:   test_moz_jsonrpc.py::TestMozCall

    Parameters
    ----------
    method:
        Moz Data API method name, e.g. ``"data.site.metrics.fetch"``.
    data:
        The object placed at ``params.data`` in the envelope.
    timeout:
        Per-request timeout in seconds (external-api E1).
    post:
        Injectable ``requests.post`` replacement, for tests.

    Returns
    -------
    dict
        The ``result`` object from the JSON-RPC response. Callers read the
        per-response quota report from here as well as their own payload.

    Raises
    ------
    RuntimeError
        ``MOZ_TOKEN`` is not set.
    MozRpcError
        Any network, HTTP, JSON, or JSON-RPC-level failure. Never returns an
        empty dict for a failure — see the module "Failure contract" note.
    """
    headers = _auth_header()
    envelope = build_envelope(method, data)
    poster = post if post is not None else requests.post

    response = _post_with_transient_retry(
        "Moz API",
        MOZ_JSONRPC_ENDPOINT,
        headers=headers,
        json_payload=envelope,
        batch_desc=f"method {method}",
        timeout=timeout,
        post=poster,
    )

    if response is None:
        raise MozRpcError(
            f"Moz API request failed at the network layer for method {method!r} "
            "after retries"
        )

    # Status before .json() — an error page is often HTML (external-api E2).
    if not response.ok:
        raise MozRpcError(
            f"Moz API HTTP {response.status_code} for method {method!r}: "
            f"{_redact(_body_snippet(response))}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise MozRpcError(
            f"Moz API returned non-JSON for method {method!r}: {_redact(exc)}"
        ) from None

    if not isinstance(payload, dict):
        raise MozRpcError(
            f"Moz API returned a non-object JSON body for method {method!r}"
        )

    error = payload.get("error")
    if error:
        raise MozRpcError(
            f"Moz API error for method {method!r}: {_redact(error)}"
        )

    result = payload.get("result")
    if not isinstance(result, dict):
        raise MozRpcError(
            f"Moz API response for method {method!r} carried no 'result' object"
        )
    return result


def _body_snippet(response) -> str:
    """Return a short, log-safe excerpt of a response body (external-api E7)."""
    try:
        return str(response.json())[:ERROR_BODY_SNIPPET_CHARS]
    except (ValueError, AttributeError):
        try:
            return str(response.text)[:ERROR_BODY_SNIPPET_CHARS]
        except AttributeError:
            return "<unreadable body>"


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

def _require_int(obj: dict, key: str) -> int:
    """Return ``obj[key]`` as an int, raising if absent or not a number.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, so a
    ``True`` flag would otherwise be read as the number 1.
    """
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MozRpcError(
            f"Moz quota.lookup response has no usable {key!r} figure "
            f"(got {type(value).__name__}; keys present: {sorted(obj)})"
        )
    return int(value)


def parse_quota(result: dict) -> dict:
    """Parse a ``quota.lookup`` result into a quota status dict.

    Purpose: derive rows remaining, which the API does not report directly.
    Spec:    moz_api_upgrade_spec_v1.md#T.0
    Tests:   test_moz_jsonrpc.py::TestQuotaLookup

    Returns ``{"path", "allotted", "used", "remaining", "overage"}``.
    ``remaining`` is ``allotted - used``, floored at 0; ``overage`` carries
    the API's own flag so an over-consumed account is still visible after
    the floor.

    Raises ``MozRpcError`` when the figures are absent. An unreadable quota
    must never degrade to ``0``: a fabricated zero reads as "quota
    exhausted" and would silently disable every downstream Moz call
    (spec design principle 3, learnings P1/P2).
    """
    quota = result.get(_QUOTA_KEY)
    if not isinstance(quota, dict):
        raise MozRpcError(
            "Moz quota.lookup response carried no 'quota' object "
            f"(keys seen: {sorted(result)})"
        )
    allotted = _require_int(quota, _QUOTA_ALLOTTED_KEY)
    used = _require_int(quota, _QUOTA_USED_KEY)
    return {
        "path": quota.get("path"),
        "allotted": allotted,
        "used": used,
        "remaining": max(0, allotted - used),
        "overage": bool(quota.get("overage", False)),
    }


def quota_status(
    *,
    path: str = QUOTA_PATH_DATA_ROWS,
    post=None,
) -> dict:
    """Return the full parsed quota status for *path*.

    Purpose: give the run log the rows-consumed figures the spec's quota
             budget requires before a method is allowed to spend.
    Spec:    moz_api_upgrade_spec_v1.md#T.0
    Tests:   test_moz_jsonrpc.py::TestQuotaLookup
    """
    return parse_quota(moz_call("quota.lookup", {"path": path}, post=post))


def quota_lookup(
    *,
    path: str = QUOTA_PATH_DATA_ROWS,
    post=None,
) -> int:
    """Return the number of Moz data rows remaining for the account.

    Purpose: read the real row allowance at runtime instead of hardcoding a
             plan figure (spec decision gate D-1).
    Spec:    moz_api_upgrade_spec_v1.md#T.0
    Tests:   test_moz_jsonrpc.py::TestQuotaLookup

    Raises
    ------
    RuntimeError
        ``MOZ_TOKEN`` is not set.
    MozRpcError
        The call failed, or the response carried no quota figures.
    """
    return quota_status(path=path, post=post)["remaining"]
