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

Review chunk Y1 adds ``m.`` to the prefixes stripped. ``m.example.com`` is the
same site as ``example.com`` by the same web convention that makes
``www.example.com`` one — and this tool keys entity-type overrides, Moz cache
rows, feasibility scores and the competitor handoff by this value, so a mobile
host counted as a separate competitor takes a top-10 slot twice. The list is
technical, not editorial: it is the set of hosts the web treats as aliases of
the apex, not a judgement about this client's market, which is why it lives
here beside the rule rather than in ``config.yml``.
"""
from urllib.parse import urlparse

__all__ = ["normalize_domain", "ALIAS_PREFIXES"]

#: Host prefixes that mean "the same site". Order matters only in that each is
#: tried once: ``www.m.example.com`` is not a form anybody serves.
ALIAS_PREFIXES = ("www.", "m.")


def normalize_domain(url_or_domain):
    """Return the comparable host for a URL or a bare domain.

    Lower-cased, without a leading ``www.`` or ``m.``, without a port, and
    without userinfo. Returns ``""`` for anything with no host in it.
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
    # Strip alias prefixes until none is left, so `www.m.example.com`,
    # `m.example.com` and `example.com` all get one answer — the invariant the
    # whole module exists for. A prefix is only stripped when something that
    # can still be a site is left: `m.ca` is a registrable domain whose first
    # label happens to be "m", and stripping it would leave a bare public
    # suffix, which is not a host.
    changed = True
    while changed:
        changed = False
        for prefix in ALIAS_PREFIXES:
            if netloc.startswith(prefix) and "." in netloc[len(prefix):]:
                netloc = netloc[len(prefix):]
                changed = True
                break
    return netloc
