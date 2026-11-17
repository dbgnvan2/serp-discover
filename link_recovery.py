"""link_recovery.py — recover a destination URL from a Google redirect wrapper.

Since late 2026 Google serves organic and AI-Overview links as
``https://www.google.com/goto?url=CAES…`` (and the older
``/url?…&url=CAES…``), where the ``url`` parameter is an opaque Google blob
rather than the destination. SerpAPI passes that through verbatim, so every
stage of this pipeline that works from a URL silently reads ``www.google.com``
as the result's domain: entity and content classification, Domain Authority
lookup, client-rank detection, handoff targets and AI-Overview citation
attribution.

What is recoverable is the **host**, which Google still sends in the clear
beside the wrapper:

* organic results — ``displayed_link`` ("https://www.yellowpages.ca › …"),
* AI-Overview references — the ``url`` parameter of ``source_icon``
  (``…/faviconV2?url=https://www.psychologytoday.com``),
* either — ``source``, when it is a hostname rather than a brand name.

So a recovered link is the site root, **not the ranked page**. Every recovered
row is marked ``link_is_destination_page: False`` so a caller that needs the
page itself (HTML enrichment: word count, schema, author signals) can skip it
instead of fetching the homepage and filing its features as the ranked page's.
A row whose host cannot be recovered gets an empty ``link``: unknown, not
"google.com" (P1 — unknown is not a terminal value).

Pure functions plus one counter, so the recovery can be tested without a fetch.

Spec: review_2026-11-04, follow-up to the 2026-11-14 reading
Tests: tests/test_link_recovery.py
"""

from __future__ import annotations

import logging
import re

from urllib.parse import parse_qs, urlparse

# Google serves its wrappers from whichever ccTLD answered the search, so the
# host is matched by shape rather than by a list: "google" followed only by
# short suffix labels. ``www.google.com``, ``www.google.co.uk`` and
# ``google.com.au`` count; ``mygoogle.example`` and ``google.example.com``
# (someone else's subdomain) do not. A real public-suffix list would be
# exact; the length bound is what distinguishes a suffix from a hostname here.
_GOOGLE_HOST = re.compile(r"(?:^|\.)google(?:\.[a-z]{2,3}){1,2}$")

# ``/goto`` is the 2026 organic wrapper, ``/url`` the long-standing one and
# ``/aclk`` the ad-click wrapper; the walker visits ad rows too.
_REDIRECT_PATHS = ("/goto", "/url", "/aclk")

# The marker of an opaque Google payload where a destination URL used to be.
_OPAQUE_PREFIX = "CAES"

#: Row keys this module adds. Kept together so callers can copy them forward.
ANNOTATIONS = ("original_link", "link_recovered_from", "link_is_destination_page")


def is_google_redirect(url) -> bool:
    """True when ``url`` is a Google redirect wrapper rather than a destination."""
    text = str(url or "")
    if not text:
        return False
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower().split(":")[0]
    if not _GOOGLE_HOST.search(host):
        return False
    if parsed.path.rstrip("/") not in _REDIRECT_PATHS:
        return False
    # A wrapper whose url= is a real URL is still usable — see recover_link.
    return True


def _target_param(url) -> str:
    """The destination query parameter of a redirect wrapper.

    ``/goto`` and the newer ``/url`` use ``url=``; the long-standing ``/url``
    form uses ``q=`` and sends the destination **page** in the clear, which is
    worth more than the host-only recovery below, so both names are read.
    """
    query = parse_qs(urlparse(str(url or "")).query)
    for name in ("url", "q"):
        values = query.get(name) or []
        if values and values[0]:
            return values[0]
    return ""


def _host_url(text) -> str:
    """``scheme://host`` for ``text``, or "" when it holds no host.

    Accepts a bare host ("www.example.ca"), since ``displayed_link`` and
    ``source`` both appear in that form.
    """
    candidate = str(text or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate if "//" in candidate else "//" + candidate)
    host = (parsed.netloc or "").strip().lower()
    # A hostname has a dot, no whitespace, and is not a brand name like
    # "The Best Vancouver".
    if not host or "." not in host or " " in host:
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}"


def recover_link(row, parent_host=""):
    """``(url, recovered_from)`` for one SerpAPI result row.

    ``recovered_from`` is "" when ``row``'s link needed no recovery, and the
    url is "" when the host could not be recovered from any field. The
    recovered url is the site root; see the module docstring.

    ``parent_host`` is the host already recovered for the row this one sits
    inside. A sitelink under an organic result or an ad carries only a title
    and a wrapper, and by construction belongs to that result's site, so the
    parent's host is a fact about it rather than a guess.
    """
    if not isinstance(row, dict):
        return "", ""
    link = row.get("link") or ""
    if not is_google_redirect(link):
        return link, ""

    # The wrapper sometimes still carries a real URL rather than a blob.
    target = _target_param(link)
    if target and not target.startswith(_OPAQUE_PREFIX):
        host = _host_url(target)
        if host and not is_google_redirect(target):
            return target, "url_param"

    # displayed_link: "https://www.yellowpages.ca › Counselling+Services › N..."
    displayed = str(row.get("displayed_link") or "").split("›")[0]
    host = _host_url(displayed)
    if host:
        return host, "displayed_link"

    # source_icon: ".../faviconV2?url=https://www.psychologytoday.com&..."
    host = _host_url(_target_param(row.get("source_icon")))
    if host:
        return host, "source_icon"

    # source is a hostname on some rows and a brand name on others.
    host = _host_url(row.get("source"))
    if host:
        return host, "source"

    # Inheriting a Google host would hand back exactly what this module
    # exists to remove, labelled as recovered. Google's own result pages
    # (related_searches, knowledge panels) are such hosts, and the walker
    # passes every node's host down (P6).
    if parent_host and not _GOOGLE_HOST.search(urlparse(parent_host).netloc):
        return parent_host, "parent"

    return "", ""


def recover_row(row, parent_host="") -> str:
    """Rewrite ``row["link"]`` in place. Returns "", "recovered" or "lost"."""
    if not isinstance(row, dict) or not is_google_redirect(row.get("link")):
        return ""
    url, recovered_from = recover_link(row, parent_host=parent_host)
    row["original_link"] = row.get("link")
    row["link"] = url
    row["link_recovered_from"] = recovered_from
    row["link_is_destination_page"] = bool(url) and recovered_from == "url_param"
    return "recovered" if url else "lost"


def link_status(row):
    """``destination``, ``site_root`` or ``unrecovered`` for one result row.

    ``link_is_destination_page`` alone conflates two different things: a link
    recovered to the site root, where the competitor is known and only the
    page is not, and a link that could not be recovered at all, where nothing
    about the result was measured. Reporting the second as the first is the
    hidden non-measurement this module exists to stop (P1/P14).
    """
    if not isinstance(row, dict) or not row.get("original_link"):
        return "destination"
    return "site_root" if row.get("link") else "unrecovered"


def _walk(node, visit, parent_host=""):
    """Depth-first over every dict in a SerpAPI response.

    ``visit`` returns the host it settled on for a node, which is passed down
    to that node's descendants as their ``parent_host``.
    """
    if isinstance(node, dict):
        parent_host = visit(node, parent_host) or parent_host
        for value in node.values():
            _walk(value, visit, parent_host)
    elif isinstance(node, list):
        for value in node:
            _walk(value, visit, parent_host)


def recover_response(response):
    """Recover every wrapped link in one SerpAPI response, in place.

    Returns ``{"wrapped", "recovered", "lost", "lost_organic"}``. A ``lost``
    row keeps the wrapper in ``original_link`` and carries an empty ``link``:
    no URL at all, rather than one whose domain reads ``google.com`` (P1).

    Every dict holding a link is visited, not a named list of them. Against
    the 2026-11-14 run, enumerating the containers missed four of them: ads,
    ad sitelinks, organic sitelinks, and the inline ``snippet_links`` of
    AI-Overview text blocks.
    """
    counts = {"wrapped": 0, "recovered": 0, "lost": 0, "lost_organic": 0}
    if not isinstance(response, dict):
        return counts

    def visit(node, parent_host):
        outcome = recover_row(node, parent_host=parent_host)
        if outcome:
            counts["wrapped"] += 1
            counts[outcome] += 1
        host = _host_url(node.get("link"))
        return "" if _GOOGLE_HOST.search(urlparse(host).netloc) else host

    _walk(response, visit)

    counts["lost_organic"] = sum(
        1 for row in response.get("organic_results") or []
        if isinstance(row, dict) and row.get("original_link") and not row.get("link"))

    if counts["wrapped"]:
        logging.info(
            "Link recovery: %d of %d wrapped Google links resolved to a host, "
            "%d unrecoverable. A recovered link is a site root, not the ranked "
            "page, so page-level enrichment skips it.",
            counts["recovered"], counts["wrapped"], counts["lost"])
    if counts["lost_organic"]:
        # An organic row with no URL is a lost measurement: no domain, no
        # Domain Authority, no client-rank check for that position.
        logging.error(
            "Link recovery: %d organic result(s) carried no host in any field "
            "and have no URL; they are excluded from domain, authority and "
            "rank analysis.", counts["lost_organic"])
    elif counts["lost"]:
        logging.warning(
            "Link recovery: %d wrapped link(s) outside the organic results "
            "carried no host in any field and have no URL.", counts["lost"])
    return counts
