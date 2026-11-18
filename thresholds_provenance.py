"""Where each verdict-deciding threshold came from.

Review finding D-M-21: every threshold that decides a label — the DA-gap
bands, the intent shares, the title-dominance counts, the commodity bands,
the AIVI weights, the foundational thirds, the engine-prioritisation blend,
the branded-demand bands, the entity-dominance share — is either a code
constant or a config value whose comment says "default" or "industry
reference". None names a study, a calibration run or a decision record, and
no report says "editorial, uncalibrated". A reader cannot tell a figure
somebody measured from a figure somebody chose.

This module is the one place that answers it. The text per family is
EDITORIAL and lives in ``config.yml`` under ``thresholds_provenance``; an
entry left empty means nobody has recorded one, which the report states as
the owner's working assumption rather than passing over in silence. That is
the same rule the AI-Overview constants follow (``aio_exposure.sources``,
review chunk D5).

Spec: docs/review_2026-11-04/PLAN_D6_hygiene_provenance_docs.md#D6.4
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The threshold families a report can state a provenance for, each with the
#: config keys that hold its numbers. The label names the family and the keys;
#: it never repeats the figures. A copy of the figures here is a copy that
#: goes stale the first time somebody tunes one, and a provenance section
#: printing the wrong numbers is worse than none (P4/P6, D6 cold review).
#: Keys are dotted paths into the config this module is given; a path that is
#: not in it prints as not set in this run's config.
FAMILIES = {
    "feasibility": (
        "Feasibility bands and the score normaliser",
        ("technical.feasibility_threshold",
         "technical.moderate_feasibility_max_gap",
         "technical.score_normaliser"),
    ),
    "serp_intent": (
        "SERP-intent shares and the classification-coverage counts",
        ("serp_intent.thresholds",),
    ),
    "title_patterns": (
        "Title-pattern dominance and how many titles are read",
        ("title_patterns.dominant_threshold", "title_patterns.top_n"),
    ),
    "commodity": (
        "Commodity score weights and bands",
        ("commodity.weights", "commodity.bands"),
    ),
    "aivi": (
        "AI-visibility composite weights",
        ("aivi.weights",),
    ),
    "foundational": (
        "Foundational readiness sub-score weights",
        ("foundational.weights",),
    ),
    "engine_prioritization": (
        "Platform-prioritisation blend",
        ("engine_prioritization.weights",),
    ),
    "gsc_demand": (
        "Branded-share benchmark bands",
        ("gsc_demand.bands",),
    ),
    "entity_dominance": (
        "Entity-dominance share and report thresholds",
        ("report_thresholds.entity_dominance",),
    ),
}

#: What the report says for a family with no recorded source. Not a silence:
#: "nobody wrote one down" is the finding, and the reader is entitled to it.
UNRECORDED = ("editorial, uncalibrated — no source or date is recorded for "
              "this one")

#: Sentinel: this config does not set the key at all, which is not the same as
#: setting it to None.
_ABSENT = object()


def resolve(cfg: dict | None) -> dict:
    """Return ``{family: provenance text}`` for every family in :data:`FAMILIES`.

    A family the config does not mention, or mentions with a blank value,
    gets :data:`UNRECORDED`. A non-string value is a config error, not a
    provenance: it is reported and treated as unrecorded.
    """
    block = (cfg or {}).get("thresholds_provenance")
    if block is not None and not isinstance(block, dict):
        logger.warning(
            "thresholds_provenance is not a mapping (%r); every threshold "
            "family will be reported as uncalibrated.", type(block).__name__)
        block = None
    block = block or {}
    for key in block:
        if key not in FAMILIES:
            logger.warning(
                "thresholds_provenance names an unknown family %r — it will "
                "not be printed. Known families: %s",
                key, ", ".join(sorted(FAMILIES)))
    out = {}
    for family in FAMILIES:
        raw = block.get(family)
        if isinstance(raw, str) and raw.strip():
            out[family] = raw.strip()
        else:
            if raw is not None and not isinstance(raw, str):
                logger.warning(
                    "thresholds_provenance.%s is not text (%r); reporting it "
                    "as uncalibrated.", family, raw)
            out[family] = UNRECORDED
    return out


def _lookup(cfg: dict | None, path: str):
    """Return the value at a dotted *path*, or :data:`_ABSENT`."""
    node = cfg or {}
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def _values(cfg: dict | None, keys) -> str:
    """Render ``key = value`` for each key, reading the live config.

    The figures are never copied into this module; they are read from the
    config the report was generated with, so the line cannot drift from the
    numbers that produced the labels the reader just saw. A key the config
    does not set — ``technical.*`` comes from the shared cross-tool config,
    not this one — says so rather than printing a guess.
    """
    parts = []
    shared = None
    for key in keys:
        value = _lookup(cfg, key)
        if value is _ABSENT:
            # `technical.*` lives in the shared cross-tool config, not this
            # one. Look there before saying a figure is unset, or the line
            # would report the tool's own live thresholds as missing.
            if shared is None:
                try:
                    from shared_config import load_shared_config
                    shared = load_shared_config() or {}
                except Exception as exc:          # pragma: no cover - defensive
                    logger.warning(
                        "could not read the shared config for threshold "
                        "provenance (%s); keys it holds will be reported as "
                        "unset.", exc)
                    shared = {}
            value = _lookup(shared, key)
            if value is not _ABSENT:
                parts.append(f"`{key}` = {value} (shared config)")
                continue
            parts.append(f"`{key}` not set — the code default applies")
        else:
            parts.append(f"`{key}` = {value}")
    return "; ".join(parts)


def lines(cfg: dict | None) -> list:
    """The report block: one line per family, each naming its own provenance."""
    resolved = resolve(cfg)
    # A bold lead-in, not a heading: this block lives INSIDE the glossary
    # appendix, and the report's own guard requires that no section follow the
    # glossary (tests/test_report_content_direction.py::TestCD4Glossary).
    out = [
        "**Where these thresholds come from**",
        "",
        "Every band and weight below decides a label you have just read. "
        "Where a line says *editorial, uncalibrated*, the figure is a "
        "judgement somebody made about this client's market — it is not "
        "derived from a study and it has not been checked against whether "
        "the predictions came true. Record a source and a date under "
        "`thresholds_provenance` in `config.yml` and this section prints it "
        "instead.",
        "",
    ]
    for family, (label, keys) in FAMILIES.items():
        values = _values(cfg, keys)
        where = f" ({values})" if values else ""
        out.append(f"- **{label}**{where} — {resolved[family]}")
    out.append("")
    return out
