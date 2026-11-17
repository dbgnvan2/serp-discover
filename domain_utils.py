"""
domain_utils.py
~~~~~~~~~~~~~~~
One definition of "which host is this", shared by every module that keys
anything by domain.

Review chunk D2c, finding D-C-08: the pipeline looked a SERP host up in
``domain_overrides.yml`` verbatim while the refresh path and the
override-candidate report stripped ``www.`` first, so 35 of the 121 overrides
were applied by two of the three and ignored by the third. A host is one host;
it gets one answer.

Two wrong ways to strip the prefix, both of which have been in this repo:

- ``lstrip("www.")`` strips the *character set* ``{w, .}``, so
  ``"wellness.ca"`` becomes ``"ellness.ca"`` (seo_geo_review C.1).
- ``replace("www.", "")`` strips the sequence anywhere, so
  ``"findwww.example.com"`` loses a piece of its label.

``removeprefix`` is the only correct one.
"""
from urllib.parse import urlparse

__all__ = ["normalize_domain"]


def normalize_domain(url_or_domain):
    """Return the comparable host for a URL or a bare domain.

    Lower-cased, without a leading ``www.``, without a port, and without
    userinfo. Returns ``""`` for anything with no host in it.
    """
    raw = str(url_or_domain or "").strip()
    if not raw or any(ch.isspace() for ch in raw):
        # A host has no spaces in it. Free text ("not a url") is not a host,
        # and must not be returned as one.
        return ""
    if "//" in raw:
        netloc = urlparse(raw).netloc
    elif "/" in raw:
        netloc = urlparse("//" + raw).netloc
    else:
        netloc = raw
    netloc = netloc.lower()
    if "@" in netloc:                       # userinfo@host
        netloc = netloc.rsplit("@", 1)[-1]
    if netloc.startswith("["):              # IPv6 literal, keep the brackets
        host, _, _port = netloc.partition("]")
        netloc = host + "]"
    elif ":" in netloc:
        netloc = netloc.split(":", 1)[0]
    return netloc.removeprefix("www.")
