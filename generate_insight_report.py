#!/usr/bin/env python3
"""
generate_insight_report.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates a Markdown summary report from the SERP analysis JSON.

Sections
--------
0. Executive Summary
1. What To Write  ← NEW (CD.1) — the ranked content plan
1b. Market Overview
2. The 'Anxiety Loop' (PAA Analysis)
3. The Words Competitors Use  ← retitled (CD.6.3)
4. Strategic Recommendations (The Bridge)
5. SERP Composition (Entity + Content Dominance)
5b. Per-Keyword SERP Intent  ← NEW (M1.A)
5c. Keyword Feasibility & Pivot Recommendations
5d. AI Overview Exposure  ← NEW (D1 / AV.1)
5e. Query Commodity / AI-Absorption Risk
5f. Demand vs Clicks
6. Market Volatility
A. Glossary  ← NEW (CD.4)

Sections 2-5f each carry a "**When you write:**" directive sourced from
report_writing_directives.yml (CD.2). Glossary definitions live in glossary.yml
(CD.4). Both are editorial content — edit the YAML, not this module.

Usage
-----
::

    python generate_insight_report.py --json market_analysis_v2.json --out report.md
"""
import argparse
import functools
import json
import logging
import os
import re
import sys
from datetime import datetime

import yaml

import pattern_matching
import db_connect
import process_config
from play_rendering import format_play_cell, format_play_line, load_play_vocab

import aio_exposure
import brief_validation
import feasibility
from feasibility import index_feasibility_by_keyword
import commodity_score
import demand_dashboard
import enrichment
import intent_verdict
import thresholds_provenance
from domain_utils import normalize_domain

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_PATTERN_INTENT_CLASS_CACHE: dict | None = None
_KEYWORD_HINTS_CACHE: dict | None = None


def _load_pattern_intent_classes() -> dict:
    """Return mapping of pattern_name → Relevant_Intent_Class (or None)."""
    global _PATTERN_INTENT_CLASS_CACHE
    if _PATTERN_INTENT_CLASS_CACHE is not None:
        return _PATTERN_INTENT_CLASS_CACHE
    path = os.path.join(_REPO_ROOT, "strategic_patterns.yml")
    with open(path, encoding="utf-8") as f:
        patterns = yaml.safe_load(f) or []
    _PATTERN_INTENT_CLASS_CACHE = {
        p["Pattern_Name"]: p.get("Relevant_Intent_Class")
        for p in patterns if isinstance(p, dict) and "Pattern_Name" in p
    }
    return _PATTERN_INTENT_CLASS_CACHE


def _load_keyword_hints() -> dict:
    """Return mapping of pattern_name → keyword_hints list from brief_pattern_routing.yml."""
    global _KEYWORD_HINTS_CACHE
    if _KEYWORD_HINTS_CACHE is not None:
        return _KEYWORD_HINTS_CACHE
    path = os.path.join(_REPO_ROOT, "brief_pattern_routing.yml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _KEYWORD_HINTS_CACHE = {
        entry["pattern_name"]: list(entry.get("keyword_hints") or [])
        for entry in raw.get("patterns", [])
        if isinstance(entry, dict) and "pattern_name" in entry
    }
    return _KEYWORD_HINTS_CACHE

try:
    import metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False


def load_data(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)


#: One read, one policy application, however many thresholds the report asks
#: for. `_report_number` reaches this on the per-keyword narrative path, so
#: before the cold review of chunk Y11 the file was re-parsed and both
#: policies re-applied once per keyword — and every config warning was
#: re-emitted with it, so one typo produced N identical lines and the reader
#: could not tell one problem from N (P2/P25). Keyed by the path, so a caller
#: that points `_REPO_ROOT` somewhere else reads that file rather than a
#: cached answer about a different one.
_CONFIG_CACHE = {}


#: What section 5c says when `feasibility_messages.yml` cannot supply the
#: words. The same shape as `db_connect.FALLBACK_*`: a built-in wording for
#: the one sentence that is said from a place where the editorial file may
#: itself be the broken thing. Before this existed, an unreadable file left
#: the section empty, and an empty section reads as "nothing to report"
#: rather than "Domain Authority was never fetched" (cold review of the
#: 2026-11-18 live-run fix). It names no Moz plan figure and no allowance —
#: `tests/test_moz_plan_figure_is_not_hardcoded.py` would fail if it did.
FALLBACK_NO_FEASIBILITY = (
    "**⚠️ Feasibility data unavailable for this run.** No Domain Authority "
    "was measured. Set `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD` or "
    "`MOZ_TOKEN` in `.env` and run `run_feasibility.py` against this run's "
    "`market_analysis_*.json`. (The wording file "
    "`feasibility_messages.yml` could not be read, so this built-in wording "
    "was used.)"
)


def _load_config():
    """config.yml, with this process's policies applied (or reset). Read once.

    The report makes no outbound call, but it opens the database, and the
    SQLite lock wait is process-wide state like the retry policy
    (`process_config`). This loader was the one of the six that set no policy
    at all, so a report rendered in the GUI's process ran on whatever the
    last loader happened to leave behind, or on the import defaults while
    `config.yml` said otherwise (P5/P25, review chunk Y11).
    """
    path = os.path.join(_REPO_ROOT, "config.yml")
    if path in _CONFIG_CACHE:
        return _CONFIG_CACHE[path]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        config = {}
    except Exception as exc:
        # A YAML typo used to leave the report running on every default with
        # nothing said anywhere: the thresholds, the retry budget and the lock
        # wait all silently built-in (P2, cold review of chunk Y11).
        logging.error(
            "Could not read %s (%s). The report runs on the built-in "
            "defaults for every threshold, the retry policy and the database "
            "lock wait.", path, exc)
        config = {}
    process_config.apply(config or None)
    _CONFIG_CACHE[path] = config
    return config


_DA_GAP_NOISE_FLOOR_DEFAULT = 2.0
# Phrase-display thresholds. Below min_count a phrase is not "recurring"; limit
# caps the rendered list. Both are report presentation choices, so they are
# config, not literals buried in three call sites (P4).
_PHRASE_MIN_COUNT_DEFAULT = 2
_PHRASE_LIMIT_DEFAULT = 10


def _report_number(key: str, default):
    """Read config.yml `report.<key>` as a number, degrading to `default`.

    Purpose: Keep an editorial typo in config.yml from aborting a run.
    Spec:    report_content_direction_spec.md#CD.11
    Tests:   tests/test_report_content_direction.py::test_cd11_*

    This was a module-level `float(...)` at import. config.yml is user-edited and
    serp_audit imports this module at top level, so `report: {da_gap_noise_floor: ""}`
    raised before a single SerpAPI call, with a traceback naming neither the key
    nor the file. Every other config read here degrades; this one now does too.
    """
    raw = (_load_config().get("report") or {}).get(key, default)
    try:
        value = type(default)(raw)
        # int(3.7) is 3, silently. The string "3.7" raises and warns, so the
        # more plausible typo was the quiet one. Warn on any lossy coercion.
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) \
                and float(value) != float(raw):
            logging.warning(
                "config.yml report.%s is %r but this setting is a whole number "
                "— using %r.", key, raw, value)
    except (TypeError, ValueError):
        logging.warning(
            "config.yml report.%s is %r, which is not a number — using %r.",
            key, raw, default)
        return default
    if value < 0:
        logging.warning(
            "config.yml report.%s is %r, which is negative — using %r.",
            key, raw, default)
        return default
    return value


def _da_gap_noise_floor() -> float:
    """DA points below which a gap reads as "level" rather than a winner."""
    return _report_number("da_gap_noise_floor", _DA_GAP_NOISE_FLOOR_DEFAULT)


def _phrase_min_count() -> int:
    return _report_number("phrase_min_count", _PHRASE_MIN_COUNT_DEFAULT)


def _phrase_limit() -> int:
    return _report_number("phrase_limit", _PHRASE_LIMIT_DEFAULT)


def _analysed_keywords(data: dict) -> list:
    """The keyword list a run actually analysed, for keyword-echo suppression.

    Purpose: Give producer and consumer ONE echo vocabulary.
    Spec:    report_content_direction_spec.md#CD.11
    Tests:   tests/test_report_content_direction.py::test_cd11_3*

    serp_audit suppresses echo against the CSV keyword list; the report used
    keyword_profiles.keys(). Any keyword that failed to produce a profile was
    absent from the consumer's set, so a re-render could print phrases the
    producer had suppressed — under a caption promising they were excluded (P19).
    serp_audit now persists `analysed_keywords`; profile keys remain the fallback
    for JSONs written before it did.
    """
    stored = data.get("analysed_keywords")
    if isinstance(stored, list) and stored:
        return [str(k) for k in stored if str(k).strip()]
    return list((data.get("keyword_profiles") or {}).keys())


_DIRECTIVES_CACHE: dict | None = None
_GLOSSARY_CACHE: list | None = None


def _load_directives() -> dict:
    """Load report_writing_directives.yml.

    Purpose: Supply the editorial "when you write" lines and page-type labels.
    Spec:    report_content_direction_spec.md#CD.2
    Tests:   tests/test_report_content_direction.py::test_cd2_2_directive_text_sourced_from_yaml
             tests/test_report_content_direction.py::test_cd2_3_missing_yaml_degrades_safely

    A missing or malformed file returns {} so the report renders without
    directives. Guidance text disappearing is a cosmetic loss; the report failing
    to write at all would cost the run its content briefs, so this degrades rather
    than raises.
    """
    global _DIRECTIVES_CACHE
    if _DIRECTIVES_CACHE is not None:
        return _DIRECTIVES_CACHE
    path = os.path.join(_REPO_ROOT, "report_writing_directives.yml")
    try:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"expected a mapping, got {type(loaded).__name__}")
        _DIRECTIVES_CACHE = loaded
    except Exception as exc:
        logging.warning(
            "report_writing_directives.yml unavailable (%s) — sections will "
            "render without writing directives.", exc)
        _DIRECTIVES_CACHE = {}
    return _DIRECTIVES_CACHE


def _directive(key: str) -> list:
    """Return the '**When you write:**' line for a section, or [] if absent."""
    text = (_load_directives().get("directives") or {}).get(key)
    if not text or not str(text).strip():
        return []
    return ["", f"**When you write:** {str(text).strip()}", ""]


_PATTERN_EXAMPLE_CACHE: dict | None = None


def _pattern_examples() -> dict:
    """Pattern_Name -> Content_Angle_Example, from strategic_patterns.yml.

    Purpose: Supply §4's worked examples.
    Spec:    report_content_direction_spec.md#CD.7
    Tests:   tests/test_report_examples.py::test_cd7_4_pattern_example_rendered

    Read from the YAML rather than only from the run's stored
    strategic_recommendations, so a report re-rendered from a JSON written before
    an example was authored still shows it. Editorial text should come from the
    current editorial file, not a frozen copy.
    """
    global _PATTERN_EXAMPLE_CACHE
    if _PATTERN_EXAMPLE_CACHE is not None:
        return _PATTERN_EXAMPLE_CACHE
    path = os.path.join(_REPO_ROOT, "strategic_patterns.yml")
    try:
        with open(path, encoding="utf-8") as f:
            patterns = yaml.safe_load(f) or []
        _PATTERN_EXAMPLE_CACHE = {
            entry["Pattern_Name"]: entry.get("Content_Angle_Example")
            for entry in patterns
            if isinstance(entry, dict) and entry.get("Pattern_Name")
        }
    except Exception as exc:
        logging.warning("strategic_patterns.yml unreadable for examples (%s).", exc)
        _PATTERN_EXAMPLE_CACHE = {}
    return _PATTERN_EXAMPLE_CACHE


def fill_example(template: str, values: dict) -> str:
    """Fill an example template, dropping sentences whose data is missing.

    Purpose: Render worked examples without empty slots or "None" in the prose.
    Spec:    report_content_direction_spec.md#CD.7
    Tests:   tests/test_report_examples.py::test_cd7_*

    An example is editorial prose with {placeholders}. Where a placeholder has no
    value for this run — no PAA question captured, no competitor phrase survived
    — the whole sentence containing it is dropped rather than rendered with a
    blank or the word "None". Half a sentence about nothing is worse than one
    fewer sentence, and a literal "None" in advice reads as a bug (P14: never let
    a missing value flow into displayed text).

    Returns "" when nothing survives, so callers can skip the example entirely.
    """
    if not template:
        return ""
    text = " ".join(str(template).split())

    # Split on sentence ends, keeping the terminator with its sentence.
    sentences = re.findall(r'[^.!?]*[.!?]+["\')\]]*|[^.!?]+$', text)
    kept = []
    for sentence in sentences:
        needed = re.findall(r'\{(\w+)\}', sentence)
        if any(not str(values.get(name) or "").strip() for name in needed):
            continue
        try:
            kept.append(sentence.format(**values))
        except (KeyError, IndexError):
            # An unknown placeholder is an editorial typo in the YAML, not a
            # reason to lose the report: drop that sentence and carry on.
            logging.warning("Example sentence has an unknown placeholder: %r",
                            sentence.strip())
    return " ".join(part.strip() for part in kept).strip()


def _example_block(template: str, values: dict) -> list:
    """Render a filled example as its own '**Here\'s an example:**' block."""
    filled = fill_example(template, values)
    if not filled:
        return []
    return ["", f"**Here's an example:** {filled}", ""]


def _example_values(data: dict, keyword: str | None) -> dict:
    """Placeholder values for `keyword`, drawn from this run's own data."""
    profiles = data.get("keyword_profiles") or {}
    profile = (profiles.get(keyword) or {}) if keyword else {}
    serp_intent = profile.get("serp_intent") or {}

    questions = [q for q in (profile.get("paa_questions") or []) if str(q).strip()]
    phrases = [row.get("Phrase")
               for row in _display_phrases_for_keyword(data, keyword)
               if row.get("Phrase")] if keyword else []
    components = serp_intent.get("mixed_components") or []

    return {
        "keyword": keyword or "",
        "question": questions[0] if questions else "",
        "term": phrases[0] if phrases else "",
        "components": " + ".join(components) if components else "",
    }


def _examples_config() -> dict:
    return _load_directives().get("examples") or {}


def _unwritable_content_types() -> set:
    """Content-type labels that name a classifier bucket, not a writable format.

    Spec: report_content_direction_spec.md#CD.7.5
    """
    raw = _load_directives().get("unwritable_content_types") or []
    return {str(v).strip().lower() for v in raw if str(v).strip()}


def _mixed_intent_strategies() -> dict:
    """Editorial descriptions + examples for each mixed-intent strategy.

    Lives in report_writing_directives.yml, not in a Python dict — it is an
    editorial judgement about how to play a split results page (CD.7).
    """
    return _load_directives().get("mixed_intent_strategies") or {}


def _with_directive(lines: list, key: str) -> list:
    """Insert a section's writing directive just under its heading.

    Purpose: Attach CD.2 directives to sections rendered by other modules
             (aio_exposure, commodity_score) without importing report config there.
    Spec:    report_content_direction_spec.md#CD.2.1
    Tests:   tests/test_report_content_direction.py::test_cd2_1_directive_present_each_section

    Returns `lines` unchanged when there is no directive or no heading to anchor
    to, so a section can never lose its content to a failed insertion.
    """
    directive = _directive(key)
    if not directive or not lines:
        return lines
    for idx, line in enumerate(lines):
        if str(line).lstrip().startswith("## "):
            return lines[:idx + 1] + [""] + directive + lines[idx + 1:]
    return lines


def _page_type_label(play_id: str | None, is_local: bool) -> str:
    """Map a play verdict to a plain-English page type (CD.1)."""
    page_types = _load_directives().get("page_types") or {}
    entry = page_types.get(play_id or "unknown") or page_types.get("unknown") or {}
    if not isinstance(entry, dict):
        return "Page type undetermined"
    variant = "local" if is_local else "default"
    return entry.get(variant) or entry.get("default") or "Page type undetermined"


def _load_glossary() -> list:
    """Load glossary.yml as a list of term entries.

    Purpose: Supply plain-English definitions for the report's jargon.
    Spec:    report_content_direction_spec.md#CD.4
    Tests:   tests/test_report_content_direction.py::test_cd4_4_definitions_sourced_from_yaml

    Degrades to [] on a missing or malformed file, for the same reason as
    _load_directives: no glossary is better than no report.
    """
    global _GLOSSARY_CACHE
    if _GLOSSARY_CACHE is not None:
        return _GLOSSARY_CACHE
    path = os.path.join(_REPO_ROOT, "glossary.yml")
    try:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        entries = loaded.get("terms") or []
        _GLOSSARY_CACHE = [
            e for e in entries
            if isinstance(e, dict) and e.get("term") and e.get("definition")
        ]
    except Exception as exc:
        logging.warning("glossary.yml unavailable (%s) — no glossary rendered.", exc)
        _GLOSSARY_CACHE = []
    return _GLOSSARY_CACHE


def _load_glossary_columns() -> list:
    """Column-name definitions for the workbook, from glossary.yml (CD.9)."""
    path = os.path.join(_REPO_ROOT, "glossary.yml")
    try:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        return [
            e for e in (loaded.get("columns") or [])
            if isinstance(e, dict) and e.get("column") and e.get("definition")
        ]
    except Exception as exc:
        logging.warning("glossary.yml columns unavailable (%s).", exc)
        return []


def load_sheet_guidance() -> list:
    """Workbook "Help" sheet rows, from glossary.yml `sheet_guidance` (CD.9).

    Tests: tests/test_glossary_surfaces.py::test_cd9_7_sheet_guidance_from_yaml
    """
    path = os.path.join(_REPO_ROOT, "glossary.yml")
    try:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        return [e for e in (loaded.get("sheet_guidance") or [])
                if isinstance(e, dict) and e.get("Tab")]
    except Exception as exc:
        logging.warning("glossary.yml sheet_guidance unavailable (%s).", exc)
        return []


def build_glossary_rows() -> list:
    """Rows for the workbook's "Glossary" sheet.

    Purpose: Carry the meaning of the workbook's machine field names with the
             file, so the .xlsx is readable away from the Markdown report.
    Spec:    report_content_direction_spec.md#CD.9
    Tests:   tests/test_glossary_surfaces.py::test_cd9_*

    Headers are deliberately NOT renamed. The JSON and the workbook share one
    field vocabulary that validate_xlsx_vs_json.py checks column by column, so
    renaming would break that contract and every formula a user has built on it.
    A definitions sheet adds the meaning without moving the data.

    Returns rows of {Item, Where, Meaning} covering both the workbook's columns
    and the report's terms of art, so one sheet answers both kinds of question.
    """
    rows = []
    for entry in _load_glossary_columns():
        rows.append({
            "Item": str(entry["column"]),
            "Where": f"Column — {entry.get('sheet', '')}".rstrip(" —"),
            "Meaning": " ".join(str(entry["definition"]).split()),
        })
    for entry in _load_glossary():
        rows.append({
            "Item": str(entry["term"]),
            "Where": "Term",
            "Meaning": " ".join(str(entry["definition"]).split()),
        })
    return rows


def build_glossary_document() -> str:
    """The full glossary as a standalone Markdown document (CD.10).

    Every term and column, unconditionally — unlike the in-report glossary, which
    is filtered to the terms that run actually used.
    """
    out = [
        "# Glossary",
        "",
        "Plain-English definitions for the SERP Intelligence tool's reports and "
        "workbook.",
        "",
        "Generated from `glossary.yml`. Edit that file, not this one — regenerate "
        "with:",
        "",
        "```bash",
        "python3 generate_insight_report.py --glossary-out docs/glossary.md",
        "```",
        "",
        "## Terms used in the report",
        "",
    ]
    for entry in sorted(_load_glossary(), key=lambda e: e["term"].lower()):
        out.append(f"**{entry['term']}** — "
                   f"{' '.join(str(entry['definition']).split())}")
        out.append("")

    columns = _load_glossary_columns()
    if columns:
        out += ["## Columns in the .xlsx workbook", "",
                "| Column | Sheet | Meaning |", "|---|---|---|"]
        for entry in columns:
            meaning = " ".join(str(entry["definition"]).split()).replace("|", "\\|")
            out.append(f"| `{entry['column']}` | {entry.get('sheet', '')} "
                       f"| {meaning} |")
        out.append("")
    return "\n".join(out)


def glossary_term_aliases(entry: dict) -> list:
    """Every spelling that counts as 'this term appears in the report'."""
    aliases = entry.get("aliases") or [entry["term"]]
    return [str(a) for a in aliases if str(a).strip()]


def term_appears_in(text: str, entry: dict) -> bool:
    """Whole-word, case-insensitive test for a glossary term in report text.

    Substring matching would fire on prose that merely contains the letters (P19's
    corollary), so every alias is anchored to word boundaries.
    """
    for alias in glossary_term_aliases(entry):
        if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text, re.IGNORECASE):
            return True
    return False


def _render_glossary(body_text: str) -> list:
    """Render the glossary appendix for terms actually used in this report.

    Purpose: Define every term of art the reader just met, and nothing else.
    Spec:    report_content_direction_spec.md#CD.4
    Tests:   tests/test_report_content_direction.py::test_cd4_*

    `body_text` is the report rendered so far, deliberately excluding this
    section — otherwise every term would define itself into existence.
    """
    entries = _load_glossary()
    used = [e for e in entries if term_appears_in(body_text, e)]
    if not used:
        return []

    out = ["## A. Glossary", ""]
    out.append(
        "Every term of art used above, in plain English. Terms that did not come "
        "up in this run are not listed.\n")
    for entry in sorted(used, key=lambda e: e["term"].lower()):
        definition = " ".join(str(entry["definition"]).split())
        out.append(f"**{entry['term']}** — {definition}\n")
    # D-M-21: the glossary says what each label means; this says where the
    # numbers behind the labels came from. A reader could not otherwise tell a
    # figure somebody measured from a figure somebody chose.
    out.extend(thresholds_provenance.lines(_load_config()))
    return out


def _no_phrases_message(stats: dict) -> str:
    """Explain an empty phrase list by what actually happened.

    Purpose: Never state a cause the numbers do not support.
    Spec:    report_content_direction_spec.md#CD.11
    Tests:   tests/test_report_content_direction.py::test_cd11_2*
    """
    texts = stats.get("texts", 0)
    candidates = stats.get("candidates", 0)
    repeated = stats.get("met_min_count", 0)
    echoed = stats.get("echo_suppressed", 0)
    minimum = stats.get("min_count", 2)

    if stats.get("stored"):
        return ("*The run recorded no competitor vocabulary for this keyword "
                "set.*")
    if not texts:
        return "*No competitor text was captured in this run.*"
    if not candidates:
        return (f"*No readable phrases could be formed from the {texts} pieces "
                "of competitor text captured. This usually means the snippets "
                "were very short or mostly punctuation.*")
    if not repeated:
        return (f"*No phrase appeared at least {minimum} times across the "
                f"{texts} pieces of competitor text captured "
                f"({candidates} distinct phrases were each seen fewer than "
                f"{minimum} times), so there is no recurring vocabulary to "
                "report. Analyse more keywords to build a usable list.*")
    if echoed and echoed == repeated:
        return (f"*No distinct competitor vocabulary found. All {echoed} "
                "phrases repeated often enough to count were restatements of "
                "the search terms themselves, which says nothing about how "
                "competitors write. Analyse more keywords, or a wider set of "
                "related terms, to get a usable vocabulary list.*")
    return ("*No distinct competitor vocabulary survived filtering for this "
            "keyword set.*")


def _display_phrases_for_keyword(data: dict, keyword: str) -> list:
    """Readable competitor phrases drawn from ONE keyword's own results.

    Purpose: Give each content option its own vocabulary.
    Spec:    report_content_direction_spec.md#CD.1.4
    Tests:   tests/test_report_content_direction.py::test_cd1_7_terms_are_per_keyword

    The stored serp_display_phrases key is run-wide, so it is deliberately not
    used here — repeating one global list under every option would read as
    per-keyword advice while being nothing of the kind.
    """
    texts = pattern_matching.collect_snippet_texts(
        overview=data.get("overview") or [],
        competitors=data.get("competitors_ads") or [],
        expansion=(data.get("related_searches") or [])
                  + (data.get("derived_expansions") or []),
        autocomplete=data.get("autocomplete_suggestions") or [],
        keyword=keyword,
    )
    if not texts:
        return []
    return pattern_matching.get_display_phrases(
        texts, keywords=_analysed_keywords(data),
        min_count=_phrase_min_count(), limit=_phrase_limit())


def _display_phrases_for_report(data: dict) -> list:
    """Readable competitor phrases, from the JSON or recomputed from it.

    Purpose: Feed §3 and the content plan with phrases a person can read.
    Spec:    report_content_direction_spec.md#CD.3.6
    Tests:   tests/test_report_content_direction.py::test_cd3_6_display_phrases_wired_to_report

    Prefers the `serp_display_phrases` key serp_audit now writes. Falls back to
    recomputing from the same snippet fields via the shared collector, so a report
    re-rendered from a JSON written before CD.3 still shows readable phrases
    instead of an empty section.
    """
    return _display_phrases_with_source(data)[0]


def _display_phrases_with_source(data: dict) -> tuple:
    """(phrases, stats) for the whole run.

    `stats` is what lets §3 say WHY a list is empty rather than guessing. "No
    competitor text was captured", "nothing repeated at all" and "everything
    repeated was the search term" are three different findings; reporting one as
    another states a confident wrong cause (P14).
    """
    texts = pattern_matching.collect_snippet_texts(
        overview=data.get("overview") or [],
        competitors=data.get("competitors_ads") or [],
        expansion=(data.get("related_searches") or [])
                  + (data.get("derived_expansions") or []),
        autocomplete=data.get("autocomplete_suggestions") or [],
    )
    stats = {"texts": len(texts), "candidates": 0, "met_min_count": 0,
             "echo_suppressed": 0, "kept": 0,
             "min_count": _phrase_min_count(), "stored": False}

    # Key PRESENCE, not truthiness: an explicitly-stored empty list means the
    # producer ran and honestly found nothing, which is a different fact from
    # "this JSON predates the key". Treating them alike sent an honest empty
    # result back through a recompute (P2).
    if "serp_display_phrases" in data:
        stored = data.get("serp_display_phrases")
        if isinstance(stored, list):
            stats.update({"stored": True, "kept": len(stored)})
            return stored, stats

    if not texts:
        return [], stats
    return pattern_matching.get_display_phrases(
        texts,
        keywords=_analysed_keywords(data),
        min_count=_phrase_min_count(),
        limit=_phrase_limit(),
        stats=stats,
    ), stats


def _content_plan_order(keyword_profiles: dict, keyword_feasibility: list,
                        preferred_intents: list, best_kw: str | None) -> list:
    """Keyword order for the content plan, guaranteed to agree with §0.

    Purpose: Order the numbered content options.
    Spec:    report_content_direction_spec.md#CD.1.3
    Tests:   tests/test_report_content_direction.py::test_cd1_3_option_order_matches_exec_summary

    Uses the same _rank_keywords helper the Executive Summary uses, then pins the
    Executive Summary's chosen keyword to the front. The pin matters: §0 ranks only
    keywords that HAVE feasibility data, while the plan lists every keyword, and
    when every feasibility status is "Not Measured" the two subsets can tie and
    break alphabetically in different directions. A report that recommends one
    keyword in §0 and a different Option 1 in §1 would be worse than no plan, so
    agreement is enforced by construction rather than left to coincide.
    """
    ranked = _rank_keywords(keyword_profiles, keyword_feasibility, preferred_intents)
    order = [row[0] for row in ranked]
    if best_kw and best_kw in order:
        order.remove(best_kw)
        order.insert(0, best_kw)
    return order


def _as_float(value):
    """Coerce a feasibility number, or None if it cannot be one.

    Purpose: One coercion for DA figures that arrive from JSON as strings.
    Spec:    report_content_direction_spec.md#CD.11.5
    Tests:   tests/test_report_content_direction.py::test_cd11_5*

    These come from an on-disk JSON whose producers have varied, so a value that
    "is not None" is not necessarily a number. Formatting one with :+.0f raises
    ValueError, and §5c is NOT wrapped in _safe_section, so it takes the whole
    report down rather than degrading one section.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trigger_presence(rec: dict) -> str:
    """Trigger names with how many text blocks carry each, and the denominator.

    The denominator is the SERP text the audit collected — snippets, ad copy,
    related searches — not the ranking pages themselves, so the wording says
    "SERP text blocks". Calling them pages would state a page-level
    measurement nobody took (D6 cold review).

    "not quantified this run" is the honest answer when no corpus reached the
    matcher — it is not "0", which would say the triggers were looked for and
    found nowhere (P1/P2, D-M-26).
    """
    names = rec.get("Detected_Triggers") or ""
    hits = rec.get("Trigger_Hits")
    scanned = rec.get("Snippets_Scanned")
    if not isinstance(hits, dict) or not scanned:
        return f"{names} — trigger-word presence not quantified this run"
    parts = []
    for name in [n.strip() for n in names.split(",") if n.strip()]:
        count = hits.get(name)
        parts.append(f"{name} ({count} of {scanned} SERP text blocks)"
                     if count is not None else name)
    blocks = rec.get("Snippets_With_Trigger")
    tail = ""
    if blocks is not None:
        share = blocks / scanned if scanned else 0
        tail = (f" — {blocks} of {scanned} scanned SERP text blocks carry at "
                f"least one ({share:.0%})")
    return ", ".join(parts) + tail


def _intent_rank_word(serp_intent: dict, coverage) -> str:
    """Which word the intent ranking key reads: certainty, or coverage.

    Certainty is the leading intent's share of the *classified* URLs, so one
    classified URL scores 1.0 — maximal certainty from almost nothing read.
    Ranking on it alone put a keyword nobody could classify above a
    well-covered 6/4 split (D6 cold review). Certainty orders the list only
    where the coverage behind it is medium or better; otherwise the coverage
    word orders, which is what happened before D6.3. Both figures are printed
    either way, but the order is itself a published recommendation.

    A row written before D6.3 has no certainty and falls back for the same
    reason: its order was never a statement about certainty.
    """
    certainty = (serp_intent or {}).get("intent_certainty")
    if certainty and certainty != "not_measured" and coverage in ("high", "medium"):
        return certainty
    return coverage


def _certainty_cell(serp_intent: dict) -> str:
    """The intent certainty for a table cell, with the share it rests on.

    A row written before D6.3 carries no certainty. It is "—" (not recorded),
    never "low": the run did not measure it. ``not_measured`` means nothing on
    the page was classified, so there is no share to read.
    """
    si = serp_intent or {}
    certainty = si.get("intent_certainty")
    if not certainty:
        return "—"
    if certainty == "not_measured":
        return "not measured"
    share = si.get("leading_intent_share")
    try:
        # "leading intent", not the primary intent: on a mixed SERP, or one
        # where the verdict was withheld, this share belongs to whichever
        # intent led, not to the word printed beside it.
        return f"{certainty} (leading intent {float(share):.0%} of classified)"
    except (TypeError, ValueError):
        return str(certainty)


def _why_this_keyword(feas_record: dict, profile: dict) -> str:
    """Plain-English reason this keyword sits where it does in the plan (CD.1)."""
    bits = []
    status = feas_record.get("feasibility_status")
    client_da = feas_record.get("client_da")
    avg_da = feas_record.get("avg_serp_da")
    gap = feas_record.get("gap")

    if status and client_da is not None and avg_da is not None and gap is not None:
        # Coerce ONCE, via the shared helper. The first branch used float(gap)
        # and the second compared the raw value, so a gap arriving as a numeric
        # string passed the first test and raised on the second — collapsing the
        # whole content plan to "Section unavailable this run".
        gap_value = _as_float(gap)
        avg_da_value = _as_float(avg_da)
    else:
        avg_da_value = None

    # Append and fall through — never return here. An early return exited the
    # WHOLE function, so an unparseable avg_serp_da silently dropped the
    # AI-Overview and map-pack sentences below, making a merely-unusable value
    # produce LESS information than a missing one (None still fell through).
    if not (status and client_da is not None and avg_da is not None
            and gap is not None and avg_da_value is not None):
        bits.append(f"{status}." if status else
                    "No Domain Authority comparison was available for this keyword.")
    elif status == feasibility.NOT_MEASURED:
        # There is a mean and a gap here, but not enough of the window was
        # scored for them to carry a verdict. Printing "they are stronger
        # than you" off two of ten domains states as fact what the status
        # line next to it refuses to conclude (P2/P6, finding F7). State the
        # coverage; withhold the direction.
        bits.append(
            f"{status} — {feasibility.coverage_phrase(feas_record.get('da_count'), feas_record.get('da_missing'))}, "
            "too little of this result page to call the Domain Authority "
            "comparison either way.")
    else:
        coverage = feasibility.coverage_phrase(feas_record.get("da_count"),
                                               feas_record.get("da_missing"))
        against = (f"your site scores {client_da} against an average of "
                   f"{round(avg_da_value, 1)} for the sites currently ranking "
                   f"({coverage})")
        # Domain Authority is a third-party estimate on a 0-100 scale, so a gap of
        # a point or two is noise. Calling a direction on it would contradict the
        # feasibility status for no reason a reader could act on.
        if gap_value is None:
            strength = against
        elif abs(gap_value) < _da_gap_noise_floor():
            strength = f"{against} — effectively level"
        elif gap_value < 0:
            strength = f"{against}, so you are the stronger site here"
        else:
            strength = f"{against}, so they are stronger than you"
        bits.append(f"{status} — {strength}.")
        # The mean is the wrong statistic for "can a site my size rank here"
        # (D-M-09): a single directory drags it either way. The minima say
        # what the mean cannot, and they travel with it rather than replacing
        # it.
        # The computation used the config list, so the prose must name the
        # same one — otherwise a widened `feasibility.directory_entity_types`
        # is described as "directory" alone (D6 cold review).
        minima = feasibility.minima_phrase(
            feas_record,
            directory_types=feasibility.resolve_directory_entity_types(
                _load_config()))
        if minima:
            bits.append(minima)

    if profile.get("has_ai_overview"):
        if profile.get("client_aio_cited"):
            bits.append("Google's AI Overview appears and already cites you.")
        else:
            bits.append(
                "Google's AI Overview appears for this search and does not cite you.")

    if profile.get("has_local_pack"):
        bits.append(
            "A map pack sits above the ordinary results, so those results start "
            "lower down the page.")

    return " ".join(bits)


def _render_content_plan(data: dict, order: list) -> list:
    """Render §1, the ranked list of pages to write.

    Purpose: Turn the analysis into "here is the content you should create".
    Spec:    report_content_direction_spec.md#CD.1
    Tests:   tests/test_report_content_direction.py::test_cd1_*
    """
    profiles = data.get("keyword_profiles") or {}
    feas_map = index_feasibility_by_keyword(data.get("keyword_feasibility"))
    vocab = load_play_vocab()

    out = ["## 1. What To Write", ""]

    if not order:
        out.append(
            "*No keywords were analysed in this run, so there is nothing to "
            "recommend writing.*\n")
        return out

    out.append(
        f"{len(order)} search{'es' if len(order) != 1 else ''} were analysed, so "
        f"there {'are' if len(order) != 1 else 'is'} {len(order)} "
        f"page{'s' if len(order) != 1 else ''} to consider below, best first. "
        "Each block says what kind of page to write and what has to be in it. "
        "The sections after this one are the evidence behind these calls.\n")

    for position, keyword in enumerate(order, start=1):
        profile = profiles.get(keyword) or {}
        feas_record = feas_map.get(keyword) or {}
        serp_intent = profile.get("serp_intent") or {}
        play_obj = profile.get("recommended_play") or {}
        play_id = play_obj.get("play")

        is_local = bool(
            profile.get("has_local_pack")
            or serp_intent.get("primary_intent") == "local"
            or "local" in (serp_intent.get("mixed_components") or [])
        )

        out.append(f"### Option {position} — {keyword}")
        out.append("")
        out.append(f"- **Page type:** {_page_type_label(play_id, is_local)}")
        out.append(
            f"- **Why this one:** {_why_this_keyword(feas_record, profile)}")
        out.append(f"- **Target search:** `{keyword}`")

        strategy = play_obj.get("strategy_text")
        if strategy:
            out.append(f"- **What the page must do:** "
                       f"{' '.join(str(strategy).split())}")
            # The play verdict carries its own honesty note when it was routed
            # without some of its inputs. Dropping that note here would present a
            # low-confidence verdict as settled fact (P2/P14), which matters most
            # in exactly the case below: a play routed without DA data can assert
            # "high DA gap" while §5c reports High Feasibility from the DA data
            # the router never saw. Surface both, and name the disagreement.
            note = play_obj.get("note")
            if note:
                out.append(f"    - *Caveat: {' '.join(str(note).split())}.*")
            feasibility_missing = not (
                (play_obj.get("data_available") or {}).get("feasibility", True))
            status = feas_record.get("feasibility_status") or ""
            if feasibility_missing and ("High" in status or "Moderate" in status):
                out.append(
                    f"    - *These two disagree: this verdict was decided "
                    f"without Domain Authority data, while Section 5c measured "
                    f"\"{status}\" for this keyword. **Page type** and "
                    f"**Success looks like** above are derived from the same "
                    f"unverified verdict, so treat all three as provisional and "
                    f"trust Section 5c on feasibility. Re-running the "
                    f"feasibility step on this run's JSON re-routes the verdict "
                    f"against the measured data.*")
        else:
            out.append(
                "- **What the page must do:** No play verdict was produced for "
                "this keyword, so there is no pre-computed instruction here. "
                "Section 5b shows what was and was not measured.")

        questions = [q for q in (profile.get("paa_questions") or []) if str(q).strip()]
        if questions:
            out.append("- **Questions to use as headings:**")
            for question in questions[:5]:
                out.append(f"    - {question}")
        else:
            out.append(
                "- **Questions to use as headings:** None captured for this "
                "search — Google showed no People Also Ask box. Use the questions "
                "in Section 2 from the other searches, or your own client "
                "questions.")

        phrases = [row.get("Phrase")
                   for row in _display_phrases_for_keyword(data, keyword)
                   if row.get("Phrase")]
        if phrases:
            out.append("- **Terms to work in:** "
                       + ", ".join(f"`{p}`" for p in phrases[:6]))
        else:
            out.append(
                "- **Terms to work in:** No distinct competitor vocabulary was "
                "found for this search — every repeated phrase was a restatement "
                "of the search term. See Section 3.")

        metric = (vocab.get("play_success_metric") or {}).get(play_id)
        if metric:
            out.append(f"- **Success looks like:** {metric}")
        else:
            out.append(
                "- **Success looks like:** Not determined — no play verdict for "
                "this keyword.")

        out.append("")
        out.append(
            "*Section 4 carries the argument this page should make. Use its "
            "content angle as the opening, not as a closing thought.*")
        out.append("")

    return out


def _rank_keywords(keyword_profiles: dict, keyword_feasibility: list, preferred_intents: list):
    """
    Purpose: Rank keywords by feasibility > intent alignment > intent certainty.
    Spec:    report_clarity_spec.md#RC.1.1
    Tests:   tests/test_report_clarity.py::test_rc1_*

    Returns list of (keyword, rank_score, feasibility_status, intent, confidence).
    Higher rank_score = higher priority.
    """
    feasibility_map = index_feasibility_by_keyword(keyword_feasibility)

    ranked = []
    for kw, profile in keyword_profiles.items():
        feas_record = feasibility_map.get(kw, {})
        feas_status = feas_record.get("feasibility_status", "")

        intent = profile.get("serp_intent", {}).get("primary_intent", "")
        confidence = profile.get("serp_intent", {}).get("confidence", "")
        is_mixed = profile.get("serp_intent", {}).get("is_mixed", False)

        # Feasibility ranking. "Not Measured" gets its own position below the
        # three verdicts, and a keyword with no row at all sits below that.
        # They used to share 0, which said an unmeasured keyword is a worse
        # bet than one measured as hard — a claim from no data (finding F7).
        # Last here means "cannot be ranked on Domain Authority", not
        # "ranked worst": §5c states why for each one, and
        # _get_best_opportunity_keyword will not recommend one at all.
        feas_rank = (
            4 if "High" in feas_status
            else 3 if "Moderate" in feas_status
            else 2 if "Low" in feas_status
            else 1 if feas_status == feasibility.NOT_MEASURED
            else 0
        )

        # Intent match (preferred=1, not preferred=0)
        # For mixed intent, check if any component matches preferred intents
        if is_mixed:
            components = profile.get("serp_intent", {}).get("mixed_components", [])
            intent_match = 1 if any(c in preferred_intents for c in components) else 0
        else:
            intent_match = 1 if intent in preferred_intents else 0

        # Third ranking key: how clearly one intent leads (D6.3). It used to
        # be `confidence`, which is the count of classified URLs — so the
        # order moved when the operator enriched more pages and not when any
        # SERP changed (D-M-10). A row written before D6.3 has no certainty;
        # it falls back to the old key rather than dropping to last, because
        # its order was never a statement about certainty either way.
        rank_word = _intent_rank_word(profile.get("serp_intent"), confidence)
        conf_rank = (
            3 if rank_word == "high"
            else 2 if rank_word == "medium"
            # "not_measured" and "low" are both below medium, and they are not
            # the same: nothing classified is not a weak lead. Ordering cannot
            # express the difference, so the tables print it.
            else 1
        )

        # Combined score: (feas, intent_match, conf, alphabetical as tiebreaker)
        score = (feas_rank, intent_match, conf_rank, kw)
        ranked.append((kw, score, feas_status, intent, confidence, intent_match))

    # Sort by score (descending on numeric parts, ascending on kw for tie-break)
    ranked.sort(key=lambda x: (-x[1][0], -x[1][1], -x[1][2], x[1][3]))
    return ranked


_NO_LINK_SENTINELS = {"", "n/a", "na", "none", "null", "-"}


def _evidence_domain(org_result: dict) -> str:
    """
    Purpose: Name the host behind an organic row for the Section-4 evidence.
    Spec:    review_2026-11-04 D4.4 cold review, finding 1

    `serp_audit.py` writes `"Link": item.get("link") or "N/A"` — the key is
    never empty, so `normalize_domain` was handed the literal "N/A" and
    returned "n" (urlparse reads `//N/A` as netloc `N`). The `Source`
    fallback was dead code for exactly the rows it was written for. The
    producer's sentinel is part of its contract and is treated as absent.
    """
    link = str(org_result.get("Link") or "").strip()
    if link.lower() in _NO_LINK_SENTINELS:
        link = ""
    return normalize_domain(link) or str(org_result.get("Source") or "unknown")


def _collect_pattern_evidence(organic_results: list, keyword: str,
                              triggers: list, cap: int = 3):
    """
    Purpose: Quote up to `cap` SERP results whose text carries a trigger.
    Spec:    review_2026-11-04 D4.4 cold review, findings 1 and 2

    Returns (evidence, selected_on_text_we_cannot_quote).

    `_get_most_relevant_keyword` scores triggers over Title + Snippet, so a
    pattern could be selected purely on snippet text and then render no
    evidence at all — the original symptom, surviving silently. This searches
    the same two fields the selector did and says which one carried the hit.
    """
    evidence = []
    saw_any_trigger = False
    for row in organic_results:
        if row.get("Root_Keyword") != keyword:
            continue
        title = str(row.get("Title") or "")
        snippet = str(row.get("Snippet") or "")
        in_title = any(t in title.lower() for t in triggers)
        in_snippet = any(t in snippet.lower() for t in triggers)
        if not (in_title or in_snippet):
            continue
        saw_any_trigger = True
        if len(evidence) >= cap:
            continue
        if in_title:
            evidence.append((title, _evidence_domain(row), "title"))
        else:
            evidence.append((snippet, _evidence_domain(row), "snippet"))
    return evidence, (saw_any_trigger and not evidence)


def _render_volatility_keyword_sets(vol: dict) -> str:
    """
    Purpose: Render the two keyword sets a non-comparable volatility run used.
    Spec:    review_2026-11-04 D4.5 (D-C-18)

    Section 6 printed "This run: unknown" for two keys
    `metrics.get_volatility_metrics` never returned. The metric now returns
    both sorted lists; this renders them as a readable line, and says
    "not recorded" only when the key really is absent (a result from an
    older metrics build), never when the set is merely empty.
    """
    def _line(value):
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value) or "none"
        if value in (None, ""):
            return "not recorded"
        return str(value)

    return (
        f"- **This run:** {_line(vol.get('keywords_current'))}\n"
        f"- **Previous run:** {_line(vol.get('keywords_previous'))}\n"
    )


def _get_best_opportunity_keyword(keyword_profiles: dict, keyword_feasibility: list, preferred_intents: list):
    """
    Purpose: Determine the single best keyword to pursue.
    Spec:    report_clarity_spec.md#RC.1.1
    Tests:   tests/test_report_clarity.py::test_rc1_best_opportunity_statement_present

    Returns tuple: (keyword_name, reason) or (None, reason_why_not).

    Two gates, both mandatory and both the ones the Section-0 action column
    applies: the keyword needs a feasibility VERDICT (not "Not Measured"),
    and its SERP intent must be one the client serves. A keyword failing
    either is not the best opportunity, however well it scores on the other
    (D-M-06 / D4.1).
    """
    if not keyword_profiles:
        return None, "No keywords to analyze."

    # Filter to keywords with a feasibility VERDICT. A "Not Measured" row is
    # a record that the keyword was attempted, not a verdict, and naming one
    # as the single best opportunity recommends a keyword on evidence the
    # report itself says it does not have (finding F7).
    feas_map = index_feasibility_by_keyword(keyword_feasibility)
    keywords_with_feas = [
        kw for kw in keyword_profiles
        if kw in feas_map
        and feas_map[kw].get("feasibility_status") != feasibility.NOT_MEASURED
    ]

    if not keywords_with_feas:
        attempted = [kw for kw in keyword_profiles if kw in feas_map]
        if attempted:
            return None, (
                "could not be determined: no keyword has enough Domain "
                "Authority coverage for a feasibility verdict. Section 5c "
                "states why for each one.")
        # No feasibility row at all — the pass did not run.
        return None, "feasibility data is missing. Run with DA credentials to enable ranking. See Section 5c."

    # Rank only keywords with feasibility data
    profiles_subset = {kw: keyword_profiles[kw] for kw in keywords_with_feas}
    ranked = _rank_keywords(profiles_subset, keyword_feasibility, preferred_intents)

    if not ranked:
        return None, "could not be determined."

    # D-M-06: intent is a MANDATORY gate, not a tie-break. `_rank_keywords`
    # sorts feasibility first, so a high-feasibility keyword whose SERP intent
    # the client does not serve outranked every preferred-intent keyword and
    # was named the single best opportunity — while the action column two
    # lines below printed "⛔ Mismatched intent" for that same keyword. The
    # report told the reader to start with the one keyword it also told them
    # not to pursue. The best opportunity now passes BOTH gates, the same two
    # `_get_keyword_action` applies. Spec: D4.1.
    eligible = [row for row in ranked if row[5] and row[3]]
    if not eligible:
        # P2: say which gate stopped them, and how many. "No intent verdict"
        # and "an intent this client does not serve" are different facts and
        # need different actions — re-run with more enrichment versus widen
        # `preferred_intents`.
        mismatched = sorted(row[0] for row in ranked if row[3] and not row[5])
        unclassified = sorted(row[0] for row in ranked if not row[3])
        parts = []
        if mismatched:
            parts.append(
                f"{len(mismatched)} keyword(s) have a SERP intent this client "
                "does not serve (`client.preferred_intents`)")
        if unclassified:
            parts.append(
                f"{len(unclassified)} keyword(s) have no SERP intent verdict "
                "at all (too few classified results)")
        return None, (
            "could not be determined: no keyword passes both the intent gate "
            "and the feasibility gate — "
            + "; ".join(parts) + ". Section 1 lists each keyword's intent.")

    best_kw, _, feas_status, intent, _, _ = eligible[0]
    reason = f"{intent} intent, {feas_status.lower()}"
    return best_kw, reason


@functools.lru_cache(maxsize=1)
def _off_topic_min_share() -> float:
    """intent_mapping.yml's off-topic share, read once per report run."""
    return intent_verdict.off_topic_min_share()


def _get_keyword_action(keyword: str, profile: dict, feas_record: dict, preferred_intents: list):
    """
    Purpose: Determine the action value for a keyword.
    Spec:    report_clarity_spec.md#RC.1.3
    Tests:   tests/test_report_clarity.py::test_rc1_action_*

    Returns one of: ✅ Pursue, ⚠️ Pursue with effort, 📊 Unranked,
    🔴 Pivot or skip, ⛔ Mismatched intent, 🚫 Off-topic SERP,
    ❓ Intent unknown.

    `🚫 Off-topic SERP` was added 2026-11-19. A keyword whose results are
    mostly job boards has no intent verdict, and reporting that as "Intent
    unknown" read as a measurement gap in the tool when it is a finding about
    the keyword: Google answered an employment search. Which entity types
    count and how much of the page they must hold are editorial, in
    intent_mapping.yml.

    `❓ Intent unknown` was added by the D4.1 cold review (finding 3). The
    intent gate read `if intent and not intent_matches`, so a keyword with no
    intent verdict skipped the gate and printed ✅ Pursue — directly below a
    Section 0 that had just said no keyword passes the intent gate. No verdict
    is not a pass, and it is not 📊 Unranked either, which means no DA.
    """
    serp_intent = profile.get("serp_intent", {})
    intent = serp_intent.get("primary_intent", "")
    feas_status = feas_record.get("feasibility_status", "")
    is_mixed = serp_intent.get("is_mixed", False)

    # Check intent match first (mandatory)
    # For mixed intent, check if any component matches preferred intents
    intent_matches = False
    if is_mixed:
        components = serp_intent.get("mixed_components", [])
        intent_matches = any(c in preferred_intents for c in components)
    else:
        intent_matches = intent in preferred_intents

    has_verdict = bool(intent) and (
        not is_mixed or bool(serp_intent.get("mixed_components")))
    if not has_verdict:
        # No verdict, but say WHY when the cause is the keyword rather than
        # the measurement: results outside this market cannot carry an intent
        # to classify, so a page mostly made of them is off topic, not unread.
        evidence = serp_intent.get("evidence", {}) or {}
        organic = evidence.get("organic_url_count") or 0
        off_topic = evidence.get("off_topic_organic_url_count") or 0
        if organic and off_topic / organic >= _off_topic_min_share():
            return "🚫 Off-topic SERP"
        return "❓ Intent unknown"

    if not intent_matches:
        return "⛔ Mismatched intent"

    # If no feasibility data
    if not feas_status:
        return "📊 Unranked"

    # Map feasibility status to action
    if "High" in feas_status:
        return "✅ Pursue"
    elif "Moderate" in feas_status:
        return "⚠️ Pursue with effort"
    elif "Low" in feas_status:
        return "🔴 Pivot or skip"
    else:
        return "📊 Unranked"


def _render_executive_summary(data: dict, best_opportunity_kw: str, best_opportunity_reason: str):
    """
    Purpose: Render Section 0 (Executive Summary) with best opportunity, brief priority, and action table.
    Spec:    report_clarity_spec.md#RC.1
    Tests:   tests/test_report_clarity.py::test_rc1_executive_summary_section_placement

    Returns list of report lines.
    """
    config = _load_config()
    preferred_intents = config.get("client", {}).get("preferred_intents", ["informational"])

    keyword_profiles = data.get("keyword_profiles", {})
    keyword_feasibility = data.get("keyword_feasibility", [])
    feas_map = index_feasibility_by_keyword(keyword_feasibility)

    report = []
    report.append("## 0. Executive Summary\n")

    # RC.1.1 — Best opportunity statement
    if best_opportunity_kw:
        report.append(f"**Best keyword opportunity:** `{best_opportunity_kw}` — {best_opportunity_reason}.\n")
    else:
        report.append(f"**Best keyword opportunity:** cannot be determined — {best_opportunity_reason}\n")

    # Why the Intent column reads as it does, said once rather than left to
    # be inferred from ten "0 of 10 classified" lines further down (P2, found
    # by the first live run). Built from the organic rows' own Fetch_Status
    # words; empty when every ranked result was classified.
    coverage_line = enrichment.classification_coverage_line(keyword_profiles)
    if coverage_line:
        report.append(coverage_line + "\n")

    # RC.1.2 — Content brief priority. Wires the RC.8 ordering
    # (_order_briefs_by_opportunity) into the Executive Summary: the first
    # ordered brief is the "write first" recommendation. Spec:
    # report_clarity_spec.md#RC.1.2.
    strategic_recs = data.get("strategic_recommendations", [])
    ordered = _order_briefs_by_opportunity(data, strategic_recs, best_opportunity_kw)
    if ordered:
        first_idx = ordered[0][0]
        first_pattern = ordered[0][1] if len(ordered[0]) > 1 else ""
        first_kw = ordered[0][2] if len(ordered[0]) > 2 else None
        rec = strategic_recs[first_idx] if 0 <= first_idx < len(strategic_recs) else {}
        content_angle = (rec.get("Content_Angle") or first_pattern or "the top-priority brief").rstrip(". ")
        pattern_name = rec.get("Pattern_Name", first_pattern or "")
        line = f"**Write first:** {content_angle} (`{pattern_name}`)."
        if not (best_opportunity_kw and first_kw == best_opportunity_kw):
            # RC.1.2 fallback: no brief maps to the best opportunity keyword.
            line += " *(No brief maps to the best-opportunity keyword; using the top-ranked brief.)*"
        report.append(line + "\n")
    else:
        report.append("*No content briefs available to prioritize.*\n")

    # RC.1.3 — Keyword action table
    # "Coverage" and "Certainty" are two different facts and used to be one
    # column called Confidence (D-M-10): coverage is how many of the ten
    # ranking URLs were classified at all — a count capped by
    # enrichment.max_urls_per_keyword — and certainty is how large a share of
    # those agreed on the leading intent. A 6/4 split read as "high
    # confidence" because only the count was shown.
    report.append("| Keyword | Intent | Coverage | Certainty | Feasibility | Action |")
    report.append("|---------|--------|----------|-----------|-------------|--------|")

    # Build rows and sort by action group
    rows = []
    for kw, profile in sorted(keyword_profiles.items()):
        si = profile.get("serp_intent", {}) or {}
        intent = si.get("primary_intent", "—")
        confidence = si.get("classification_coverage") or si.get("confidence") or "—"
        certainty = _certainty_cell(si)
        feas_record = feas_map.get(kw, {})
        feas_status = feas_record.get("feasibility_status", "—")
        action = _get_keyword_action(kw, profile, feas_record, preferred_intents)

        # Sort priority: Pursue > Pursue with effort > Unranked >
        # Pivot or skip > Intent unknown > Mismatched intent >
        # Off-topic SERP (last: the keyword itself is the problem)
        action_priority = (
            0 if action.startswith("✅") else
            1 if action.startswith("⚠️") else
            2 if action.startswith("📊") else
            3 if action.startswith("🔴") else
            4 if action.startswith("❓") else
            5 if action.startswith("⛔") else
            6
        )
        rows.append((action_priority, kw, intent, confidence, certainty,
                     feas_status, action))

    # Sort by action group, then alphabetically
    rows.sort(key=lambda x: (x[0], x[1]))
    for _, kw, intent, confidence, certainty, feas_status, action in rows:
        report.append(f"| {kw} | {intent} | {confidence} | {certainty} "
                      f"| {feas_status} | {action} |")

    report.append("")
    return report


def _get_entity_dominance_interpretation(entity_dist: dict, config: dict):
    """
    Purpose: Generate interpretive sentence based on entity dominance percentages.
    Spec:    report_clarity_spec.md#RC.6
    Tests:   tests/test_report_clarity.py::test_rc6_interpretation_*
    """
    thresholds = config.get("report_thresholds", {}).get("entity_dominance", {})
    counselling_dir_threshold = thresholds.get("counselling_directory_combined", 0.4)
    education_threshold = thresholds.get("education", 0.15)
    government_threshold = thresholds.get("government", 0.20)

    # Calculate percentages
    counselling_pct = entity_dist.get("counselling", 0) / 100.0
    directory_pct = entity_dist.get("directory", 0) / 100.0
    education_pct = entity_dist.get("education", 0) / 100.0
    government_pct = entity_dist.get("government", 0) / 100.0

    # Check thresholds in priority order
    if (counselling_pct + directory_pct) > counselling_dir_threshold:
        return (
            "Competitors are primarily counselling providers and directories. For "
            "informational keywords, your competition is guide/article content, not "
            "service pages."
        )
    elif education_pct > education_threshold:
        return (
            "Educational institutions hold significant SERP share. Content must meet "
            "an academic evidence standard to compete."
        )
    elif government_pct > government_threshold:
        return (
            "Government sources dominate. These keywords may be difficult to rank for "
            "regardless of DA — consider whether the audience finding government results "
            "is the same audience you are targeting."
        )
    else:
        return (
            "No single entity type dominates. SERP is fragmented — differentiated "
            "content has room to enter."
        )


def _order_briefs_by_opportunity(data: dict, strategic_recs: list, best_opportunity_kw: str):
    """
    Purpose: Order content briefs for sequencing (RC.8).
    Spec:    report_clarity_spec.md#RC.8
    Tests:   tests/test_report_clarity.py::test_rc8_*

    Returns list of (index, pattern_name, most_relevant_keyword, rank_info) tuples,
    ordered by: best opportunity keyword first, then by feasibility/intent ranking.
    """
    if not strategic_recs or not data.get("keyword_profiles"):
        # Same 4-tuple contract as the normal return below
        # (idx, pattern_name, most_rel_kw, rank_score) — the old 2-tuple shape
        # here made callers that index [1]/[2]/[3] read a nested tuple and crash.
        return [
            (idx, rec.get("Pattern_Name", ""), None, (-1, 0, 0, ""))
            for idx, rec in enumerate(strategic_recs)
        ]

    config = _load_config()
    preferred_intents = config.get("client", {}).get("preferred_intents", ["informational"])
    keyword_profiles = data.get("keyword_profiles", {})
    keyword_feasibility = data.get("keyword_feasibility", [])
    organic_results = data.get("organic_results", [])
    paa_questions = data.get("paa_questions", [])

    feas_map = index_feasibility_by_keyword(keyword_feasibility)

    # Build brief metadata
    brief_metadata = []
    for idx, rec in enumerate(strategic_recs):
        pattern_name = rec.get("Pattern_Name", "")
        most_rel_kw = _get_most_relevant_keyword(rec, organic_results, keyword_profiles, paa_questions)

        if not most_rel_kw or most_rel_kw not in keyword_profiles:
            most_rel_kw = None

        # Get ranking info for this keyword
        if most_rel_kw:
            profile = keyword_profiles.get(most_rel_kw, {})
            feas_record = feas_map.get(most_rel_kw, {})
            intent = profile.get("serp_intent", {}).get("primary_intent", "")
            confidence = profile.get("serp_intent", {}).get("confidence", "")
            feas_status = feas_record.get("feasibility_status", "")

            # Feasibility ranking
            feas_rank = (
                3 if "High" in feas_status else
                2 if "Moderate" in feas_status else
                1 if "Low" in feas_status else 0
            )

            # Intent match
            is_mixed = profile.get("serp_intent", {}).get("is_mixed", False)
            if is_mixed:
                components = profile.get("serp_intent", {}).get("mixed_components", [])
                intent_match = 1 if any(c in preferred_intents for c in components) else 0
            else:
                intent_match = 1 if intent in preferred_intents else 0

            # Intent certainty, same key as _rank_keywords (D6.3): the brief
            # order and the keyword order have to agree, and ranking on the
            # classification count ordered both by enrichment budget.
            _rank_word = _intent_rank_word(
                profile.get("serp_intent"), confidence)
            conf_rank = (3 if _rank_word == "high"
                         else 2 if _rank_word == "medium" else 1)

            rank_score = (feas_rank, intent_match, conf_rank, most_rel_kw)
        else:
            rank_score = (-1, 0, 0, "")

        brief_metadata.append((idx, pattern_name, most_rel_kw, rank_score))

    # Sort: best opportunity keyword first, then by rank score (descending feas/intent/conf)
    def sort_key(item):
        idx, pattern_name, most_rel_kw, rank_score = item
        # First, sort by whether it matches best_opportunity_kw (True = higher priority)
        matches_best = 1 if most_rel_kw == best_opportunity_kw else 0
        # Then by rank score (descending)
        return (-matches_best, -rank_score[0], -rank_score[1], -rank_score[2], rank_score[3])

    brief_metadata.sort(key=sort_key)
    return brief_metadata


def _safe_section(name, builder):
    """Render one report section in isolation. A raise degrades to a placeholder
    line so a single malformed keyword can't abort the whole market_analysis_*.md
    write (which serp_audit wraps in a swallowing try) and lose the content briefs."""
    try:
        return builder()
    except Exception as exc:
        logging.error("Report section %r failed to render: %s", name, exc)
        return [f"## {name}", f"*Section unavailable this run — {exc}*", ""]


def generate_report(data, db_path=None, run_ts=None):
    report = []

    # Extract Metadata
    overview = data.get("overview", [])
    run_id = overview[0].get("Run_ID", "Unknown") if overview else "Unknown"
    date = overview[0].get("Created_At", datetime.now(
    ).isoformat()) if overview else datetime.now().isoformat()

    report.append(f"# Market Intelligence Report")
    report.append(f"**Run ID:** {run_id} | **Date:** {date}\n")

    # 0. Executive Summary (RC.1)
    config = _load_config()
    preferred_intents = config.get("client", {}).get("preferred_intents", ["informational"])
    keyword_feasibility = data.get("keyword_feasibility", [])
    best_kw, best_reason = _get_best_opportunity_keyword(
        data.get("keyword_profiles", {}),
        keyword_feasibility,
        preferred_intents
    )
    # Isolate the Exec Summary too: a raise here (e.g. a malformed brief) must
    # not abort the whole market_analysis_*.md write in serp_audit's swallowing try.
    report.extend(_safe_section(
        "0. Executive Summary",
        lambda: _render_executive_summary(data, best_kw, best_reason),
    ))

    # 1. What To Write (CD.1) — the content plan, before the evidence behind it.
    plan_order = _content_plan_order(
        data.get("keyword_profiles", {}),
        keyword_feasibility,
        preferred_intents,
        best_kw,
    )
    report.extend(_safe_section(
        "1. What To Write",
        lambda: _render_content_plan(data, plan_order),
    ))
    # Section 5's worked examples speak about the keyword the reader was just
    # told to write first, so the two sections stay about the same page.
    _plan_top_keyword = plan_order[0] if plan_order else None

    # 1b. Overview & Opportunity
    report.append("## 1b. Market Overview")
    if overview:
        # D-C-13 / D4.14: a keyword whose SERP fetch failed has no overview row,
        # so `len(overview)` alone said "7 keywords analysed" for a run of 8 and
        # named neither the total nor the one that produced nothing (P2).
        #
        # Both numbers are counted in keywords. `overview` holds one row per
        # QUERY JOB — `expand_keywords_for_ai` adds A.1/A.2 alternative rows for
        # priority keywords — so counting its rows reported 13 for a run of 8.
        _missing = brief_validation.missing_serp_keywords(data)
        _answered = len({(r.get("Source_Keyword") or r.get("Keyword"))
                         for r in overview
                         if (r.get("Source_Keyword") or r.get("Keyword"))}) or len(overview)
        _asked_list = [str(k) for k in (data.get("analysed_keywords") or [])
                       if str(k).strip()]
        report.append(f"- **Keywords Analyzed:** {_answered}"
                      + (f" of {len(_asked_list)}" if _asked_list else ""))
        if _missing:
            report.append(
                "- **No SERP data returned for:** "
                + ", ".join(f"`{k}`" for k in _missing)
                + " — every figure below excludes "
                + ("them." if len(_missing) > 1 else "it."))
        elif not _asked_list:
            # A run written before `analysed_keywords` was recorded. Saying
            # nothing would assert completeness this file cannot support (P35).
            report.append(
                "- **Coverage:** this run did not record the keyword list it was "
                "asked for, so whether any keyword produced no SERP data cannot "
                "be established from it.")

        # CD.6.1 — count how many keywords showed each feature instead of
        # unioning them under a "Dominant" label the data does not support: the
        # union is not frequency-weighted, so it cannot establish dominance.
        # CD.6.2 — "Standard Organic" is serp_audit's fallback string for "none of
        # the seven detected features present", not a feature. It is reported as
        # the null result it is, never listed alongside real features.
        feature_counts = {}
        plain_keyword_count = 0
        measured_keyword_count = 0
        for row in overview:
            raw = row.get("SERP_Features")
            if not raw:
                continue
            measured_keyword_count += 1
            names = [n.strip() for n in str(raw).split(",") if n.strip()]
            real_features = [n for n in names if n != "Standard Organic"]
            if not real_features:
                plain_keyword_count += 1
                continue
            for name in real_features:
                feature_counts[name] = feature_counts.get(name, 0) + 1

        if measured_keyword_count:
            total = measured_keyword_count
            report.append(
                "- **Search page features found** *(what Google showed besides "
                "the plain list of links)*:")
            if feature_counts:
                for name, count in sorted(
                        feature_counts.items(), key=lambda kv: (-kv[1], kv[0])):
                    report.append(
                        f"    - {name} — {count} of {total} "
                        f"keyword{'s' if total != 1 else ''}")
            if plain_keyword_count:
                report.append(
                    f"    - No extra features — {plain_keyword_count} of {total} "
                    f"keyword{'s' if total != 1 else ''} returned nothing but the "
                    "plain list of links")
    report.extend(_directive("section_1b"))
    report.append("\n")

    # 2. The "Anxiety Loop" (PAA Analysis) (RC.3 — PAA improvements)
    report.append("## 2. The 'Anxiety Loop' (User Intent)")
    report.append(
        "These are the questions your audience is already asking. Use them as "
        "headings, FAQ items, or opening hooks in content targeting these keywords.")
    report.extend(_directive("section_2"))

    paa = data.get("paa_questions", [])
    if paa:
        seen_questions = set()
        deduped_paa = []
        for item in paa:
            question = str(item.get("Question", "")).strip()
            key = question.lower()
            if not question or key in seen_questions:
                continue
            seen_questions.add(key)
            deduped_paa.append(item)

        # Group by category if available
        commercial = [q["Question"]
                      for q in deduped_paa if q.get("Category") == "Commercial"]
        distress = [q["Question"]
                    for q in deduped_paa if q.get("Category") == "Distress"]
        reactivity = [q["Question"]
                      for q in deduped_paa if q.get("Category") == "Reactivity"]

        if distress or reactivity or commercial:
            # RC.3.2 — Categorized PAA (no change to existing logic)
            if distress:
                report.append("\n### 🚨 High Distress Signals")
                for q in distress[:5]:
                    report.append(f"- {q}")

            if reactivity:
                report.append("\n### 🔥 Reactivity & Blame")
                for q in reactivity[:5]:
                    report.append(f"- {q}")

            if commercial:
                report.append("\n### 💰 Resource/Cost Anxiety")
                for q in commercial[:5]:
                    report.append(f"- {q}")
        else:
            # RC.3.3 & RC.3.4 — Uncategorized PAA with frequency ordering
            report.append("\n*No category signals detected. Questions are listed by frequency across keywords.*\n")

            # Count how many distinct keywords each question appears under
            q_keyword_counts = {}
            for item in deduped_paa:
                q = item.get("Question", "")
                source_kw = item.get("Source_Keyword", "")
                if q and source_kw:
                    if q not in q_keyword_counts:
                        q_keyword_counts[q] = set()
                    q_keyword_counts[q].add(source_kw)

            # Sort by number of distinct keywords (descending), then alphabetically
            sorted_questions = sorted(
                q_keyword_counts.items(),
                key=lambda x: (-len(x[1]), x[0])
            )

            for q, keywords in sorted_questions[:5]:
                report.append(f"- {q}")

            # RC.3.4 — Most common question block
            if sorted_questions:
                most_common_q, most_common_kws = sorted_questions[0]
                kw_list = ", ".join(sorted(most_common_kws))
                report.append(f"\n**Most common question:** `{most_common_q}`")
                report.append(f"**Appears for:** {kw_list}")
    else:
        report.append("_No PAA data found._")
    report.append("\n")

    # 3. Competitor Language
    # CD.6.3 — the old heading ("The 'Status Quo'") and its subtitle ("The dominant
    # narrative in the market (Medical Model vs. Systemic)") promised the narrative
    # contrast that Section 4 actually performs. This section produces a term list.
    # It is now titled and introduced as one, and points at Section 4 for the rest.
    report.append("## 3. The Words Competitors Use")
    report.append(
        "The vocabulary already on this results page. Matching it makes your page "
        "recognisably about the topic; it does not make it different. Section 4 is "
        "where the Medical Model vs. Systemic contrast is drawn.")
    report.extend(_directive("section_3"))

    # CD.3 — readable phrases. serp_language_patterns is still produced and still
    # feeds the Bowen trigger matcher, but its phrases have their stop words
    # stripped before joining ("family of origin" → "family origin"), so they are
    # not fit to show a reader.
    display_phrases, phrase_stats = _display_phrases_with_source(data)

    if display_phrases:
        report.append("\n### Most repeated phrases")
        report.append(
            "*Counted across the snippets, ads, related searches and autocomplete "
            "Google displayed — not the full text of competitor pages. Phrases "
            "that just restate your search term are excluded.*\n")
        for row in display_phrases:
            report.append(f"- **{row['Phrase']}** ({row['Count']} occurrences)")
    else:
        # Zero-from-non-empty is a real finding, not a failure to report (P19) —
        # but WHICH finding matters. "Nothing was captured", "nothing repeated"
        # and "everything repeated was the search term" are three different
        # causes, and the earlier code asserted the third for all of them, which
        # is a confident wrong cause presented as an insight (P14).
        report.append("\n" + _no_phrases_message(phrase_stats))
    report.append("\n")

    # 4. Strategic Bridge
    report.append("## 4. Strategic Recommendations (The Bridge)")
    report.append("How to differentiate using Bowen Theory.")
    # D6.7 / D-M-26: a pattern fires on a whole-word trigger hit in the
    # ranking pages' text. That is trigger-word presence, which is what the
    # counts below report — it is not an analysis of how those pages frame
    # the problem, and a pattern that fired on one page of twenty is not
    # evidence the market thinks that way.
    report.append("")
    report.append(
        "*What this section measures: trigger-word presence in the SERP text "
        "this run collected — the snippets, ad copy and related searches, not "
        "the body text of the ranking pages — and not framing analysis. Each "
        "pattern below reports how many of those text blocks carry its "
        "trigger words, so a pattern that fired in one block of forty can be "
        "read as such.*")
    report.extend(_directive("section_4"))

    # M1.B — Mixed-Intent Strategic Note callouts above Bowen pattern blocks
    _kw_profiles = data.get("keyword_profiles", {})
    # CD.7 — descriptions and their worked examples are editorial content and live
    # in report_writing_directives.yml, not in a dict here.
    _strategies = _mixed_intent_strategies()
    _STRATEGY_DESCRIPTIONS = {
        key: " ".join(str((entry or {}).get("description") or "").split())
        for key, entry in _strategies.items()
    }
    _mixed_kws = [
        (kw, p)
        for kw, p in _kw_profiles.items()
        if p.get("mixed_intent_strategy") is not None
    ]
    for _kw, _p in _mixed_kws:
        _strategy = _p["mixed_intent_strategy"]
        _comps = (_p.get("serp_intent") or {}).get("mixed_components") or []
        _comp_str = " + ".join(_comps) if _comps else "multiple intents"
        _desc = _STRATEGY_DESCRIPTIONS.get(_strategy, "")
        report.append(f"\n### ⚖️ Mixed-Intent Strategic Note: {_kw}")
        report.append("")
        report.append(
            f"This keyword shows mixed search intent ({_comp_str}). "
            f"Recommended approach: **{_strategy}**."
        )
        report.append("")
        # D4b cold review, finding 7: the tie and the lead were computed and
        # went no further than the JSON. A reader told to "compete on the
        # dominant intent" cannot act on it without knowing which one, and
        # must be told when two tied.
        _lead = _p.get("mixed_intent_lead")
        _dom = _p.get("mixed_intent_dominant") or []
        if _p.get("mixed_intent_dominant_tied") and len(_dom) > 1:
            report.append(
                f"Two intents lead this SERP equally ({' and '.join(_dom)}), so "
                f"the choice is not forced by the data"
                + (f" — this run writes for **{_lead}**." if _lead else ".")
            )
            report.append("")
        elif _lead:
            report.append(f"The dominant intent to write for is **{_lead}**.")
            report.append("")
        if _desc:
            report.append(_desc)
        # CD.7 — translate the generic strategy into this keyword's own data.
        report.extend(_example_block(
            (_strategies.get(_strategy) or {}).get("example"),
            _example_values(data, _kw)))

    _organic_results = data.get("organic_results", [])
    _paa_questions = data.get("paa_questions", [])
    recs = data.get("strategic_recommendations", [])
    if recs:
        for rec in recs:
            report.append(f"\n### 🌉 {rec.get('Pattern_Name', 'Opportunity')}")
            report.append("")
            report.append(_render_pattern_intent_context(rec, _organic_results, _kw_profiles, _paa_questions))
            report.append("")
            # RC.4.2 — Add (template) labels to distinguish editorial from data-driven
            report.append(f"- **Status Quo (template):** {rec.get('Status_Quo_Message')}")
            report.append(
                f"- **Bowen Reframe (template):** {rec.get('Bowen_Bridge_Reframe')}")
            report.append(f"- **Content Angle (template):** *{rec.get('Content_Angle')}*")

            # CD.7 — turn the angle into a concrete opening, using this run's own
            # keyword, question and competitor vocabulary.
            _pattern_kw = _get_most_relevant_keyword(
                rec, _organic_results, _kw_profiles, _paa_questions)
            _angle_example = (
                rec.get("Content_Angle_Example")
                or _pattern_examples().get(rec.get("Pattern_Name")))
            report.extend(_example_block(
                _angle_example, _example_values(data, _pattern_kw)))

            # RC.4.1 — Add evidence block if triggers found
            if rec.get("Detected_Triggers") and rec.get("Detected_Triggers") != "N/A":
                triggers_str = rec.get('Detected_Triggers')
                report.append(
                    f"- *Triggers found:* {_trigger_presence(rec)}")

                # Build evidence block from organic_results
                triggers = [t.strip().lower() for t in triggers_str.split(",") if t.strip()]
                most_rel_kw = _get_most_relevant_keyword(rec, _organic_results, _kw_profiles, _paa_questions)

                if triggers and most_rel_kw:
                    # Find organic results for this keyword that contain trigger words
                    # D-C-14 / D4.4: this read "title" and "domain";
                    # serp_audit writes "Title", "Link" and "Source", so the
                    # block never rendered on real data and every pattern in
                    # every report since has been stated with no evidence
                    # beside it. The keys are the producer's own.
                    evidence_titles, snippet_only = _collect_pattern_evidence(
                        _organic_results, most_rel_kw, triggers)

                    # RC.4.1 — Render evidence block if titles found
                    if evidence_titles:
                        report.append("\n> **Why this pattern fired:**")
                        report.append(f"> Trigger word(s) `{triggers_str}` appeared in SERP results for")
                        report.append(f"> **`{most_rel_kw}`**:")
                        for quote, domain, where in evidence_titles:
                            label = "" if where == "title" else " (snippet)"
                            report.append(
                                f"> - *\"{quote}\"*{label} — `{domain}`")
                        report.append("")
                    elif snippet_only:
                        # P2: the pattern was selected on text this block does
                        # not quote. Say so rather than printing the pattern
                        # with no evidence and no explanation (finding 2).
                        report.append(
                            f"\n> **Why this pattern fired:** trigger word(s) "
                            f"`{triggers_str}` appeared in the SERP text for "
                            f"**`{most_rel_kw}`**, but in no result whose "
                            f"title or snippet could be quoted.")
                        report.append("")
    else:
        report.append("_No strategic recommendations generated._")

    # 5. Advanced Metrics (Dominance) + 6. Volatility
    if METRICS_AVAILABLE:
        _overview = data.get("overview", [])
        _run_id = _overview[0].get("Run_ID") if _overview else None

        if _run_id:
            # Section 5 — SERP Composition
            dominance = metrics.get_entity_dominance(_run_id)
            _has_dominance = bool(dominance.get("entity_dominance")
                                  or dominance.get("content_dominance"))
            if not _has_dominance and dominance.get("msg"):
                # Say why instead of dropping the section silently: an absent
                # section 5 reads as "the SERP has no composition" rather than
                # "this run's rows are not comparable" (P2). Deliberately not
                # a "## 5." heading — a rendered section must carry its
                # writing directive (CD.2), and "match the format that is
                # winning" is not advice you can give with no data.
                report.append(
                    f"\n_Section 5 (SERP Composition) is not available for "
                    f"this run — {dominance['msg']}_")
            if _has_dominance:
                report.append("\n## 5. SERP Composition (Enriched Data)")
                report.extend(_directive("section_5"))

                ents = dominance.get("entity_dominance", {})
                if ents:
                    report.append("### Entity Dominance (Top 10)")
                    for k, v in sorted(ents.items(), key=lambda x: x[1], reverse=True):
                        report.append(f"- **{k}:** {v}%")

                    # RC.6 — Entity dominance interpretation
                    config = _load_config()
                    interpretation = _get_entity_dominance_interpretation(ents, config)
                    report.append(f"\n*{interpretation}*")

                    # CD.7 — the same point, in this run's numbers.
                    _named_ents = {
                        k: v for k, v in ents.items()
                        if str(k).strip().lower() not in _unwritable_content_types()
                    }
                    if _named_ents:
                        _top_entity, _top_pct = max(
                            _named_ents.items(), key=lambda kv: kv[1])
                        _vals = _example_values(data, _plan_top_keyword)
                        _vals.update({"entity": _top_entity, "pct": _top_pct})
                        report.extend(_example_block(
                            _examples_config().get("entity_dominance"), _vals))

                conts = dominance.get("content_dominance", {})
                if conts:
                    report.append("\n### Content Type Dominance (Top 10)")
                    for k, v in sorted(conts.items(), key=lambda x: x[1], reverse=True):
                        report.append(f"- **{k}:** {v}%")

                    # CD.7 — "other" is the classifier's unknown bucket, not a
                    # format anyone can write, so it must never become advice.
                    _named = {k: v for k, v in conts.items()
                              if str(k).strip().lower() not in _unwritable_content_types()}
                    if _named:
                        _top_type, _type_pct = max(_named.items(), key=lambda kv: kv[1])
                        _vals = _example_values(data, _plan_top_keyword)
                        _vals.update({"content_type": _top_type, "pct": _type_pct})
                        report.extend(_example_block(
                            _examples_config().get("content_type_dominance"), _vals))
                report.append("\n")

    # 5b. Per-Keyword SERP Intent (M1.A — always rendered when keyword_profiles present)
    _kw_profiles_for_5b = data.get("keyword_profiles", {})
    report.extend(_render_serp_intent_section(_kw_profiles_for_5b))

    # 5c. Keyword Feasibility & Pivot Recommendations (RC.5 — always render)
    report.append("## 5c. Keyword Feasibility & Pivot Recommendations\n")
    report.extend(_directive("section_5c"))

    feasibility_rows = data.get("keyword_feasibility", [])
    if feasibility_rows:
        report.append(
            "Domain Authority gap analysis for each keyword. The **Recommended Play** "
            "column carries the pre-computed verdict under the two-score, "
            "rank-vs-citation model (rank_play = ranking target; extraction_play = "
            "AI-Overview citation target). Service keywords out of ranking reach still "
            "show a hyper-local **Recommended Pivot**.\n"
        )

        # Split primary and pivot rows
        # One row per keyword: an AI-alternative A.1/A.2 row must not add a
        # second line for the same keyword (finding D-C-19).
        primary_rows = list(index_feasibility_by_keyword(feasibility_rows).values())
        pivot_rows   = {r.get("Source_Keyword", r.get("Keyword")): r
                        for r in feasibility_rows if r.get("Query_Label") == "P"}

        # Table header
        # "Weakest (non-dir)" is the rankability figure the mean hides
        # (D-M-09 / D6.1): the lowest DA holding a slot, and the lowest that
        # is not a directory. "—" means no competitor was scored; "n/m" means
        # no entity type was resolved, so the directory split is unmeasured
        # rather than empty.
        report.append("| Keyword | Client DA | Avg Comp DA | Weakest (non-dir) | DA Coverage | Gap | Status | Recommended Play | Recommended Pivot |")
        report.append("|---------|-----------|-------------|-------------------|-------------|-----|--------|------------------|-------------------|")

        # Labels are editorial and live in feasibility_messages.yml; this was
        # the fourth Python copy of the same map (review chunk D2a).

        def _local_pack_phrase(pack):
            # Honest rendering (B.2, same class as run_feasibility): None = the
            # validation fetch failed (could not measure) — never a false
            # "✗ not in local pack". 0 = measured-absent. Truthy = present.
            if pack is None:
                return " — local pack not measured (validation fetch failed)"
            return " ✓ in local pack" if pack else " ✗ not in local pack"

        # RP-C.2 — Recommended Play column joins on the pre-computed verdict.
        feas_kw_profiles = data.get("keyword_profiles", {}) or {}

        for row in primary_rows:
            kw       = row.get("Keyword") or row.get("original_keyword", "—")
            avg_da   = row.get("avg_serp_da")
            gap      = row.get("gap")
            status   = feasibility.status_label(row.get("feasibility_status", "")) or "—"
            # Coerce before formatting: these arrive from JSON and a string
            # here raises ValueError. §5c is NOT inside _safe_section, so that
            # takes the entire report down (same class as CD.11.5).
            avg_da_num = _as_float(avg_da)
            gap_num    = _as_float(gap)
            avg_da_str = f"{avg_da_num:.0f}" if avg_da_num is not None else "—"
            gap_str    = f"{gap_num:+.0f}" if gap_num is not None else "—"
            # The denominator travels with the mean (D2a.9, P2), and the
            # client's own DA says whether it was measured at all (D-M-05).
            coverage_str = feasibility.coverage_phrase(
                row.get("da_count"), row.get("da_missing"), short=True)
            client_da_str = feasibility.client_da_cell(
                row.get("client_da"), row.get("client_da_source", ""))

            play_cell = format_play_cell((feas_kw_profiles.get(kw) or {}).get("recommended_play"))

            pivot_cell = "*(stay the course)*"
            if feasibility.is_no_pivot(row.get("pivot_status")):
                # SEAM (chip C): the extraction-play recommendation renders here.
                refused = str(row["pivot_status"]).split("— ", 1)[-1]
                pivot_cell = f"*({refused} — extraction play)*"
            elif row.get("pivot_status") == "Pivoting to Hyper-Local":
                suggested = row.get("suggested_keyword", "")
                # Check if we have a pivot result with local pack data
                pivot_result = pivot_rows.get(kw)
                if pivot_result:
                    pack_str = _local_pack_phrase(pivot_result.get("Client_In_Local_Pack"))
                    pivot_feas = pivot_result.get("feasibility_status", "")
                    p_icon = feasibility.status_label(pivot_feas)
                    pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
                else:
                    pivot_cell = f"**{suggested}**"

            weakest_str = feasibility.minima_cell(row)
            report.append(f"| {kw} | {client_da_str} | {avg_da_str} | {weakest_str} "
                          f"| {coverage_str} | {gap_str} | {status} | {play_cell} "
                          f"| {pivot_cell} |")

        report.append("")

        # Why each unmeasured keyword has no verdict. The reason was computed
        # and stored on the row, and then rendered nowhere: the only consumer
        # of `strategy` was the Low Feasibility block below, which a
        # "Not Measured" row never enters (P21/P25, finding F3).
        unmeasured_rows = [r for r in primary_rows
                           if r.get("feasibility_status") == feasibility.NOT_MEASURED]
        if unmeasured_rows:
            report.append("### Not measured — why\n")
            for row in unmeasured_rows:
                kw = row.get("Keyword") or row.get("original_keyword", "")
                reason = (row.get("no_measurement_reason") or "").strip()
                coverage = feasibility.coverage_phrase(
                    row.get("da_count"), row.get("da_missing"))
                report.append(f"- **{kw}** — {reason or coverage}"
                              + (f" ({coverage})" if reason else ""))
            report.append("")

        # Pivot strategy explanations for Low Feasibility keywords
        low_feas = [r for r in primary_rows if r.get("feasibility_status") == "Low Feasibility"]
        if low_feas:
            report.append("### Pivot Strategy\n")
            report.append(
                "> **Why this works:** Geographic relevance is the equalizer for non-profits. "
                "A practitioner physically located in a neighbourhood can outrank a national "
                "directory for a user searching in that specific area, regardless of domain authority.\n"
            )
            for row in low_feas:
                strategy = row.get("strategy", "")
                if strategy and strategy != "Current keyword is feasible. No pivot required.":
                    kw = row.get("Keyword") or row.get("original_keyword", "")
                    report.append(f"**{kw}:** {strategy}\n")

        report.append("\n")
    else:
        # RC.5 — No feasibility data: say so, and say what fills it in.
        # The words live in feasibility_messages.yml `no_data_section`. They
        # were a literal here, and one of them was a Moz plan figure — both
        # wrong for this account and the one number CLAUDE.md says must never
        # be hardcoded, since the allowance is read from the account at
        # runtime. The old wording is recorded in feasibility_messages.yml,
        # not quoted here, because a guard forbids the figure in source.
        #
        # §5c is deliberately outside `_safe_section`, so this branch may not
        # raise and may not fall silent either. Both were true of the first
        # version of it, found by its cold review: a `no_data_section` written
        # as a plain string — the likeliest typo in a block whose whole
        # purpose is to be hand-edited — raised AttributeError and took down
        # the whole market report, and an unreadable file left the heading
        # with nothing under it, which reads as "nothing to report" rather
        # than "DA was never fetched". `FALLBACK_NO_FEASIBILITY` is the
        # built-in wording, the same shape as `db_connect.FALLBACK_*`, and it
        # says that it was used.
        _no_data = feasibility.load_messages().get("no_data_section")
        if not isinstance(_no_data, dict):
            _no_data = {}
        _lines = [str(_no_data[_key]).strip() for _key in _no_data
                  if isinstance(_no_data.get(_key), str)
                  and str(_no_data[_key]).strip()]
        if not _lines:
            logging.warning(
                "feasibility_messages.yml no_data_section is missing or "
                "unusable; section 5c used the built-in wording.")
            _lines = [FALLBACK_NO_FEASIBILITY]
        for _text in _lines:
            report.append(f"{_text}\n")

    # 5d / 5e / 5f — the three AI-era sections (D1 AIO exposure, D4 commodity risk,
    # D3 demand dashboard). Each is composed in ISOLATION via _safe_section: a raise
    # in one degrades to a placeholder while the siblings + the rest of the report
    # still render, so a single malformed keyword can't abort the whole
    # market_analysis_*.md write and lose the content briefs.
    _kp = data.get("keyword_profiles", {})
    report.extend(_safe_section(
        "5d. AI Overview Exposure",
        lambda: _with_directive(aio_exposure.build_aio_exposure_report(
            _kp, config, db_path=db_path, run_ts=run_ts), "section_5d")))
    report.extend(_safe_section(
        "5e. Query Commodity / AI-Absorption Risk",
        lambda: _with_directive(commodity_score.build_commodity_report(
            _kp, data, config, db_path=db_path, run_ts=run_ts), "section_5e")))
    report.extend(_safe_section(
        "5f. Demand vs Clicks",
        lambda: demand_dashboard.build_dashboard(_kp, config, db_path=db_path)))

    # Section 6 — Market Volatility (RC.7 — suppress or explain non-comparable runs)
    _overview = data.get("overview", [])
    _run_id = _overview[0].get("Run_ID") if _overview else None
    if not METRICS_AVAILABLE:
        # The section disappeared on these two gates too, which is the same
        # "the market did not move" misreading (cold review of chunk Y3).
        report.append("## 6. Market Volatility")
        report.append("**Not measured for this run:** the volatility metrics "
                      "module could not be imported in this environment "
                      "(pandas or matplotlib missing).")
        report.append("\n")
    elif not _run_id:
        report.append("## 6. Market Volatility")
        report.append("**Not measured for this run:** the overview rows carry "
                      "no Run_ID, so this run cannot be matched against the "
                      "run history.")
        report.append("\n")
    else:
        vol = metrics.get_volatility_metrics(_run_id)
        if vol and vol.get("status") != "success":
            # Every reason there is no volatility figure is printed. The
            # section used to render only on success, so a run with no
            # completed baseline, an unknown run id or a failed query
            # produced no section at all and the `msg` the metric built
            # for the reader reached nothing (P2, review chunk Y3).
            report.append("## 6. Market Volatility")
            report.append(
                f"**Not measured for this run:** "
                f"{vol.get('msg') or vol.get('status')}")
            if vol.get("comparability_warning"):
                report.append(
                    f"**Comparability Warning:** "
                    f"{vol['comparability_warning']}")
            if vol.get("keywords_current") or vol.get("keywords_previous"):
                report.append(_render_volatility_keyword_sets(vol))
            report.append("\n")
        elif vol and vol.get("status") == "success":
            report.append("## 6. Market Volatility")

            # The empty-merge case is `no_shared_urls` above, and the
            # ranks are dropna'd before the merge, so a success result
            # cannot carry a NaN score any more. The branch that used to
            # handle it could print the heading and a blank line when the
            # keyword sets matched but every URL moved — the bug this
            # chunk fixes (cold review of chunk Y3).
            vol_score = vol.get("volatility_score")
            if vol_score is not None:
                # Valid score: render as normal
                report.append(
                    f"**Volatility Score:** {vol_score} (Avg rank change)")
                report.append(
                    f"**Stable URLs:** {vol['stable_urls_count']} / {vol['total_compared']}")
                if vol.get("comparability_warning"):
                    report.append(f"**Comparability Warning:** {vol['comparability_warning']}")

                if vol.get('winners'):
                    report.append("\n### 🚀 Top Movers (Winners)")
                    for w in vol['winners']:
                        report.append(
                            f"- **{w['url']}** (+{w['rank_delta']} positions) for '{w['keyword_text']}'")

                if vol.get('losers'):
                    report.append("\n### 🔻 Top Movers (Losers)")
                    for l in vol['losers']:
                        report.append(
                            f"- **{l['url']}** ({l['rank_delta']} positions) for '{l['keyword_text']}'")
            report.append("\n")

    # A. Glossary (CD.4) — appended last so it can be built from the finished body:
    # only terms the reader actually met above get defined, and the glossary's own
    # headwords are excluded from the scan so nothing defines itself into the list.
    body_text = "\n".join(report)
    report.extend(_safe_section("A. Glossary", lambda: _render_glossary(body_text)))

    return "\n".join(report)


def _get_most_relevant_keyword(
    rec: dict,
    organic_results: list,
    keyword_profiles: dict,
    paa_questions: list,
) -> str | None:
    """Three-component keyword relevance scoring for Section 4 pattern blocks.

    Purpose: Select the keyword most associated with a strategic recommendation pattern.
    Spec:    serp_tool1_improvements_spec.md#I.3
    Tests:   tests/test_most_relevant_keyword.py::test_i31_three_component_scoring

    score(keyword, pattern) =
        (PAA questions for kw tagged with pattern's Relevant_Intent_Class) * 3
      + (pattern's keyword_hints matching kw source text) * 2
      + (pattern's trigger words in Title+Snippet of kw's organic results) * 1

    The PAA component is 0 when no Relevant_Intent_Class is set for the pattern.
    Alphabetical tiebreaker when scores are equal.
    Returns None when all keywords score 0 or inputs are empty.
    """
    pattern_name = rec.get("Pattern_Name", "")
    triggers_raw = rec.get("Detected_Triggers") or ""
    triggers = [t.strip().lower() for t in triggers_raw.split(",") if t.strip()]

    relevant_intent_class = _load_pattern_intent_classes().get(pattern_name)
    keyword_hints = _load_keyword_hints().get(pattern_name, [])

    candidate_kws = {
        row.get("Root_Keyword", "")
        for row in organic_results
        if row.get("Root_Keyword") and row.get("Root_Keyword") in keyword_profiles
    }
    if not candidate_kws:
        return None

    kw_scores: dict[str, int] = {}
    for kw in candidate_kws:
        kw_lower = kw.lower()

        # Component 1: PAA intent class match (weight 3)
        paa_score = 0
        if relevant_intent_class:
            paa_score = sum(
                1 for q in paa_questions
                if q.get("Source_Keyword") == kw
                and q.get("Intent_Tag") == relevant_intent_class
            ) * 3

        # Component 2: keyword_hints match (weight 2)
        hint_score = sum(1 for h in keyword_hints if h in kw_lower) * 2

        # Component 3: trigger text in organic Title+Snippet (weight 1)
        trigger_score = 0
        for row in organic_results:
            if row.get("Root_Keyword") != kw:
                continue
            text = ((row.get("Title") or "") + " " + (row.get("Snippet") or "")).lower()
            trigger_score += sum(1 for t in triggers if t in text)

        kw_scores[kw] = paa_score + hint_score + trigger_score

    if not kw_scores or max(kw_scores.values()) == 0:
        return None
    return max(kw_scores, key=lambda k: (kw_scores[k], [-ord(c) for c in k]))


def _render_pattern_intent_context(
    rec: dict, organic_results: list, keyword_profiles: dict, paa_questions: list
) -> str:
    """Return the SERP intent context italic line for a Section 4 pattern block.

    Purpose: Anchor each Bowen pattern recommendation to a per-keyword SERP intent verdict.
    Spec:    serp_tool1_improvements_spec.md#I.3 (supersedes cleanup_spec.md#C.2)
    Tests:   tests/test_most_relevant_keyword.py::test_i31_three_component_scoring

    Format: *SERP intent context (most relevant keyword: <kw>): <intent>,
    classification coverage <cov>[, certainty <cert>][, mixed: c1 + c2].*
    Null primary_intent: *SERP intent context (most relevant keyword: <kw>): primary intent insufficient data.*
    No keyword found: *SERP intent context: no keyword in this run has triggers for this pattern.*
    """
    most_relevant_kw = _get_most_relevant_keyword(rec, organic_results, keyword_profiles, paa_questions)
    if not most_relevant_kw:
        return "*SERP intent context: no keyword in this run has triggers for this pattern.*"

    kp = keyword_profiles.get(most_relevant_kw, {})
    si = kp.get("serp_intent") or {}
    primary = si.get("primary_intent")
    confidence = si.get("confidence", "low")
    is_mixed = si.get("is_mixed", False)
    mixed_comps = si.get("mixed_components") or []

    if primary is None:
        return (
            f"*SERP intent context (most relevant keyword: {most_relevant_kw}): "
            f"primary intent insufficient data.*"
        )

    mixed_segment = ""
    if is_mixed and mixed_comps:
        mixed_segment = f", mixed: {' + '.join(mixed_comps)}"

    # "confidence <word>" said coverage and read as certainty (D-M-10). Both
    # facts are printed, each named.
    certainty = si.get("intent_certainty")
    certainty_segment = f", certainty {certainty}" if certainty else ""
    return (
        f"*SERP intent context (most relevant keyword: {most_relevant_kw}): "
        f"{primary}, classification coverage {confidence}"
        f"{certainty_segment}{mixed_segment}.*"
    )


def _render_serp_intent_section(keyword_profiles: dict) -> list:
    """Return lines for ## 5b. Per-Keyword SERP Intent (M1.A of completion spec)."""
    if not keyword_profiles:
        return []

    lines = ["\n## 5b. Per-Keyword SERP Intent", ""]
    lines.extend(_directive("section_5b"))

    for kw, profile in keyword_profiles.items():
        si = profile.get("serp_intent") or {}
        tp = profile.get("title_patterns") or {}
        mis = profile.get("mixed_intent_strategy")
        primary = si.get("primary_intent")
        confidence = si.get("confidence", "low")
        is_mixed = si.get("is_mixed", False)
        dist = si.get("intent_distribution") or {}
        ev = si.get("evidence") or {}
        classified_n = ev.get("classified_organic_url_count", 0)
        organic_n = ev.get("organic_url_count", 0)
        mixed_comps = si.get("mixed_components") or []
        dominant_pattern = tp.get("dominant_pattern")
        local_pack = ev.get("local_pack_present", False)

        lines.append(f"### {kw}")
        lines.append("")

        if primary is None:
            lines.append(
                f"- **Primary intent:** insufficient data "
                f"— only {classified_n} of {organic_n} URLs could be classified"
            )
        else:
            # Two figures, two names (D6.3): coverage is how much of the page
            # was classified, certainty how much of that agreed.
            cert = _certainty_cell(si)
            lines.append(
                f"- **Primary intent:** {primary}  "
                f"*(classification coverage: {confidence}; "
                f"intent certainty: {cert})*")

        dist_parts = [
            f"{intent}: {count}"
            for intent, count in sorted(dist.items(), key=lambda x: -x[1])
            if count > 0
        ]
        if dist_parts:
            lines.append(
                f"- **Distribution:** {', '.join(dist_parts)} "
                f"over {classified_n} of {organic_n} classified URLs"
            )
        else:
            lines.append("- **Distribution:** no URLs classified")

        if is_mixed and mixed_comps:
            lines.append(f"- **Mixed-intent components:** {', '.join(mixed_comps)}")

        if mis is not None:
            lines.append(f"- **Strategy:** {mis}")

        if dominant_pattern:
            lines.append(f"- **Title patterns:** {dominant_pattern} dominant")
        else:
            lines.append("- **Title patterns:** no dominant pattern detected")

        if local_pack:
            lines.append("- **Local pack present:** yes")

        # RP-C.2 — per-keyword Recommended Play line (two-score rank-vs-citation
        # verdict). Rendered verbatim from the pre-computed field; honest note when
        # inputs were missing. Spec: seo_geo_review_20260704.md (T.4).
        play_body = format_play_line(profile.get("recommended_play"))
        if play_body:
            lines.append(f"- **Recommended play:** {play_body}")

        lines.append("")

    return lines


def build_content_briefs_section(data: dict, preferred_intents=None) -> list[str]:
    """The ``# Content Briefs`` block: sequencing note + the ordered briefs.

    Purpose: ONE home for the assembly. Spec: RC.8; review_2026-11-04 D4.13
             (D-C-12)
    Tests:   tests/test_d4c_the_brief_is_checked_and_whole.py

    It lived in `serp_audit.main` only, so `generate_insight_report --out` — the
    documented re-render, and what the GUI runs after feasibility — rewrote the
    same `.md` with the insight report alone and silently dropped every brief.
    Returns [] when the run has no strategic recommendations, which is the one
    case where there are no briefs to write.
    """
    recs = data.get("strategic_recommendations") or []
    if not recs:
        return []

    if preferred_intents is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.yml"), "r", encoding="utf-8") as fh:
                preferred_intents = ((yaml.safe_load(fh) or {}).get("client")
                                     or {}).get("preferred_intents")
        except Exception as exc:
            logging.warning("Could not read client.preferred_intents (%s): "
                            "ordering briefs on intent confidence alone.", exc)
            preferred_intents = None
    preferred_intents = preferred_intents or ["informational"]

    best_kw, _ = _get_best_opportunity_keyword(
        data.get("keyword_profiles", {}),
        data.get("keyword_feasibility", []),
        preferred_intents)
    ordered = _order_briefs_by_opportunity(data, recs, best_kw)

    out = ["# Content Briefs\n", "**Recommended writing order:**\n"]
    for n, (_idx, pattern_name, most_rel_kw, _rest) in enumerate(ordered, 1):
        out.append(f"{n}. `{pattern_name}` — targets `{most_rel_kw}`"
                   if most_rel_kw
                   else f"{n}. `{pattern_name}` — (no primary keyword match)")
    if not any(item[2] for item in ordered):
        out.append("\n*Without feasibility data, briefs are ordered by intent "
                   "confidence (high → medium → low) of their most relevant "
                   "keyword.*")
    else:
        out.append("\nWrite in this order to address the highest-opportunity "
                   "keyword first. Each brief below is self-contained.")
    out.append("")

    import generate_content_brief
    for n, (orig_idx, pattern_name, _kw, _rest) in enumerate(ordered, 1):
        out.append(f"## Brief {n}: {pattern_name}")
        out.append(generate_content_brief.generate_brief(data, rec_index=orig_idx))
        out.append("\n---\n")
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Generate Marketing Insights Report")
    parser.add_argument("--json", required=False,
                        help="Path to serp_norm.json or market_analysis_v2.json")
    parser.add_argument("--out", required=False,
                        help="Output Markdown file path")
    parser.add_argument("--glossary-out", default=None,
                        help="Write the standalone glossary (CD.10) to this path "
                             "and exit. Needs no --json: the glossary is built "
                             "from glossary.yml, not from a run.")
    parser.add_argument("--db", default=None,
                        help="SQLite DB for AI-Overview exposure trend (D1 / AV.1); "
                             "default: the configured database.path.")
    parser.add_argument("--run-ts", default=None,
                        help="Run timestamp YYYYMMDD_HHMM; default parsed from --json.")
    args = parser.parse_args()

    # CD.10 — the glossary is editorial content, not run output: it needs no JSON
    # and costs nothing to produce.
    if args.glossary_out:
        try:
            with open(args.glossary_out, "w", encoding="utf-8") as f:
                f.write(build_glossary_document())
            print(f"Glossary written: {args.glossary_out}")
        except Exception as exc:
            print(f"Error writing glossary: {exc}")
            sys.exit(1)
        return

    if not args.json or not args.out:
        parser.error("--json and --out are required unless --glossary-out is given")

    data = load_data(args.json)
    # D1: persist AIO exposure under the run's identity (parsed from the
    # market_analysis_* filename) so the trend is keyed to real runs, never a
    # wall-clock stamp. Unparseable → run_ts None → render-only (no persistence).
    run_ts = args.run_ts or aio_exposure.run_ts_from_filename(args.json)
    # The loader applies the policies, and it is cached, so the call
    # `generate_report` makes a moment later is free. `main` did not call it
    # at all: the first load on this path was inside `generate_report`,
    # *after* the line below had already read the import-time default, so a
    # configured `database.path` never reached the AIO-exposure write and the
    # trend split across two databases with nothing logged (P4/P16, the cold
    # review of chunk Y12).
    _load_config()
    db_path = args.db if args.db else db_connect.database_path()
    report_content = generate_report(data, db_path=db_path, run_ts=run_ts)
    # D4.13: the same .md the pipeline writes — report THEN briefs. Rendering
    # only the report here is what dropped every brief from the GUI's
    # post-feasibility regenerate.
    # A brief that cannot be rendered must not take the report with it: before
    # D4.13 this path always wrote the report, and an exception escaping here
    # would write nothing at all (degrade, don't abort).
    try:
        briefs = build_content_briefs_section(data)
    except Exception as exc:
        logging.warning("Content briefs could not be rendered (%s): the report "
                        "is written without them.", exc)
        briefs = ["# Content Briefs\n",
                  f"*The briefs could not be rendered for this run: {exc}. "
                  f"The report above is unaffected.*"]
    if briefs:
        report_content = "\n".join([report_content, "\n---\n"] + briefs)

    try:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"Report generated: {args.out}")
    except Exception as e:
        print(f"Error writing report: {e}")


if __name__ == "__main__":
    main()
