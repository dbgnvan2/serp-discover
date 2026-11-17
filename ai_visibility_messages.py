"""The words a reader sees when an AI engine was not measured.

One home for the vocabulary of "we have no measurement for this engine", read
by ``probe_ai_visibility``, ``aivi``, ``engine_transfer`` and
``engine_recommendations``. The state itself is a constant in
``probe_ai_visibility`` (``STATUS_ANSWERED`` / ``STATUS_FAILED``); only the
wording lives here, as ``gsc_client``/``gsc_messages.yml`` and
``feasibility_messages.yml`` do.

Spec: D3a (cold-review finding F4) — four Python copies of one status word are
how an unmeasured state comes to carry four labels.
"""
import logging
import os

import yaml

logger = logging.getLogger(__name__)

MESSAGES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "ai_visibility_messages.yml")

_CACHE: dict | None = None


def load_messages() -> dict:
    """Read ``ai_visibility_messages.yml``, or ``{}`` when it cannot be read.

    Missing or malformed degrades to the caller's built-in wording; the words
    are presentation and must never cost a run. Cached after the first read.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data: dict = {}
    try:
        with open(MESSAGES_FILE, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "ai_visibility_messages.yml could not be read (%s); AI-visibility "
            "statuses will render as their built-in wording.", exc)
    _CACHE = data
    return data


def status_text(status: str, key: str = "label") -> str:
    """The configured *key* ("label" / "cell" / "coverage") for *status*."""
    entry = (load_messages().get("statuses") or {}).get(status) or {}
    value = entry.get(key)
    return str(value) if value else str(status or "")


def line(name: str, fallback: str, **values) -> str:
    """A configured report line, formatted, falling back rather than raising.

    A placeholder added to the YAML must not be able to abort a report.
    """
    template = (load_messages().get("lines") or {}).get(name)
    if not template:
        return fallback.format(**values) if values else fallback
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        logger.warning(
            "ai_visibility_messages.yml: %r could not be rendered (%s); using "
            "the built-in wording.", name, exc)
        return fallback.format(**values) if values else fallback
