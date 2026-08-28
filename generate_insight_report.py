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
import json
import logging
import os
import re
import sys
from datetime import datetime

import yaml

import pattern_matching
from play_rendering import format_play_cell, format_play_line, load_play_vocab

import aio_exposure
import commodity_score
import demand_dashboard

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


def _load_config():
    """Load config.yml to get preferred_intents and report thresholds."""
    path = os.path.join(_REPO_ROOT, "config.yml")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# Domain Authority points below which a gap is treated as "level" rather than a
# direction. DA is a 0-100 third-party estimate; a point or two is not a finding.
# Overridable via config.yml report.da_gap_noise_floor.
_DA_GAP_NOISE_FLOOR = float(
    (_load_config().get("report") or {}).get("da_gap_noise_floor", 2.0))

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
    return out


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
        texts, keywords=list((data.get("keyword_profiles") or {}).keys()))


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
    """(phrases, had_source_text) for the whole run.

    The second element is what lets §3 distinguish "no competitor text was
    captured" from "text was captured but every repeated phrase was the search
    term". Collapsing those two into one empty list would make a failed run look
    like a analysed-but-unremarkable one (P2).
    """
    texts = pattern_matching.collect_snippet_texts(
        overview=data.get("overview") or [],
        competitors=data.get("competitors_ads") or [],
        expansion=(data.get("related_searches") or [])
                  + (data.get("derived_expansions") or []),
        autocomplete=data.get("autocomplete_suggestions") or [],
    )
    had_text = bool(texts) or bool(data.get("serp_language_patterns")
                                   or data.get("bad_advice_patterns"))

    stored = data.get("serp_display_phrases")
    if isinstance(stored, list) and stored:
        return stored, True
    if not texts:
        return [], had_text
    return pattern_matching.get_display_phrases(
        texts, keywords=list((data.get("keyword_profiles") or {}).keys())), had_text


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


def _why_this_keyword(feas_record: dict, profile: dict, aio_row: dict | None) -> str:
    """Plain-English reason this keyword sits where it does in the plan (CD.1)."""
    bits = []
    status = feas_record.get("feasibility_status")
    client_da = feas_record.get("client_da")
    avg_da = feas_record.get("avg_serp_da")
    gap = feas_record.get("gap")

    if status and client_da is not None and avg_da is not None and gap is not None:
        against = (f"your site scores {client_da} against an average of "
                   f"{round(float(avg_da), 1)} for the sites currently ranking")
        # Domain Authority is a third-party estimate on a 0-100 scale, so a gap of
        # a point or two is noise. Calling a direction on it would contradict the
        # feasibility status for no reason a reader could act on.
        if abs(float(gap)) < _DA_GAP_NOISE_FLOOR:
            strength = f"{against} — effectively level"
        elif gap < 0:
            strength = f"{against}, so you are the stronger site here"
        else:
            strength = f"{against}, so they are stronger than you"
        bits.append(f"{status} — {strength}.")
    elif status:
        bits.append(f"{status}.")
    else:
        bits.append("No Domain Authority comparison was available for this keyword.")

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


def _render_content_plan(data: dict, order: list, preferred_intents: list) -> list:
    """Render §1, the ranked list of pages to write.

    Purpose: Turn the analysis into "here is the content you should create".
    Spec:    report_content_direction_spec.md#CD.1
    Tests:   tests/test_report_content_direction.py::test_cd1_*
    """
    profiles = data.get("keyword_profiles") or {}
    feas_map = {
        r.get("Keyword"): r
        for r in (data.get("keyword_feasibility") or [])
        if r.get("Query_Label") != "P"
    }
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
            f"- **Why this one:** {_why_this_keyword(feas_record, profile, None)}")
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
                    f"    - *These two disagree: this verdict was decided without "
                    f"Domain Authority data, while Section 5c measured "
                    f"\"{status}\" for this keyword. Treat the ranking half of "
                    f"the advice above as unverified and trust Section 5c on "
                    f"feasibility.*")
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
    Purpose: Rank keywords by feasibility > intent alignment > confidence.
    Spec:    report_clarity_spec.md#RC.1.1
    Tests:   tests/test_report_clarity.py::test_rc1_*

    Returns list of (keyword, rank_score, feasibility_status, intent, confidence).
    Higher rank_score = higher priority.
    """
    feasibility_map = {
        r.get("Keyword"): r
        for r in keyword_feasibility
        if r.get("Query_Label") != "P"  # Exclude pivot keywords
    }

    ranked = []
    for kw, profile in keyword_profiles.items():
        feas_record = feasibility_map.get(kw, {})
        feas_status = feas_record.get("feasibility_status", "")

        intent = profile.get("serp_intent", {}).get("primary_intent", "")
        confidence = profile.get("serp_intent", {}).get("confidence", "")
        is_mixed = profile.get("serp_intent", {}).get("is_mixed", False)

        # Feasibility ranking (High=3, Moderate=2, Low=1, None=0)
        feas_rank = (
            3 if "High" in feas_status
            else 2 if "Moderate" in feas_status
            else 1 if "Low" in feas_status
            else 0
        )

        # Intent match (preferred=1, not preferred=0)
        # For mixed intent, check if any component matches preferred intents
        if is_mixed:
            components = profile.get("serp_intent", {}).get("mixed_components", [])
            intent_match = 1 if any(c in preferred_intents for c in components) else 0
        else:
            intent_match = 1 if intent in preferred_intents else 0

        # Confidence ranking (high=3, medium=2, low=1)
        conf_rank = (
            3 if confidence == "high"
            else 2 if confidence == "medium"
            else 1
        )

        # Combined score: (feas, intent_match, conf, alphabetical as tiebreaker)
        score = (feas_rank, intent_match, conf_rank, kw)
        ranked.append((kw, score, feas_status, intent, confidence, intent_match))

    # Sort by score (descending on numeric parts, ascending on kw for tie-break)
    ranked.sort(key=lambda x: (-x[1][0], -x[1][1], -x[1][2], x[1][3]))
    return ranked


def _get_best_opportunity_keyword(keyword_profiles: dict, keyword_feasibility: list, preferred_intents: list):
    """
    Purpose: Determine the single best keyword to pursue.
    Spec:    report_clarity_spec.md#RC.1.1
    Tests:   tests/test_report_clarity.py::test_rc1_best_opportunity_statement_present

    Returns tuple: (keyword_name, reason) or (None, reason_why_not).
    """
    if not keyword_profiles:
        return None, "No keywords to analyze."

    # Filter to keywords with feasibility data
    feas_map = {
        r.get("Keyword"): r
        for r in keyword_feasibility
        if r.get("Query_Label") != "P"
    }
    keywords_with_feas = [kw for kw in keyword_profiles if kw in feas_map]

    if not keywords_with_feas:
        # All keywords lack feasibility data
        return None, "feasibility data is missing. Run with DA credentials to enable ranking. See Section 5c."

    # Rank only keywords with feasibility data
    profiles_subset = {kw: keyword_profiles[kw] for kw in keywords_with_feas}
    ranked = _rank_keywords(profiles_subset, keyword_feasibility, preferred_intents)

    if not ranked:
        return None, "could not be determined."

    best_kw, _, feas_status, intent, _, _ = ranked[0]
    reason = f"{intent} intent, {feas_status.lower()}"
    return best_kw, reason


def _get_keyword_action(keyword: str, profile: dict, feas_record: dict, preferred_intents: list):
    """
    Purpose: Determine the action value for a keyword.
    Spec:    report_clarity_spec.md#RC.1.3
    Tests:   tests/test_report_clarity.py::test_rc1_action_*

    Returns one of: ✅ Pursue, ⚠️ Pursue with effort, 📊 Unranked, 🔴 Pivot or skip, ⛔ Mismatched intent
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

    if intent and not intent_matches:
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
    feas_map = {r.get("Keyword"): r for r in keyword_feasibility if r.get("Query_Label") != "P"}

    report = []
    report.append("## 0. Executive Summary\n")

    # RC.1.1 — Best opportunity statement
    if best_opportunity_kw:
        report.append(f"**Best keyword opportunity:** `{best_opportunity_kw}` — {best_opportunity_reason}.\n")
    else:
        report.append(f"**Best keyword opportunity:** cannot be determined — {best_opportunity_reason}\n")

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
    report.append("| Keyword | Intent | Confidence | Feasibility | Action |")
    report.append("|---------|--------|------------|-------------|--------|")

    # Build rows and sort by action group
    rows = []
    for kw, profile in sorted(keyword_profiles.items()):
        intent = profile.get("serp_intent", {}).get("primary_intent", "—")
        confidence = profile.get("serp_intent", {}).get("confidence", "—")
        feas_record = feas_map.get(kw, {})
        feas_status = feas_record.get("feasibility_status", "—")
        action = _get_keyword_action(kw, profile, feas_record, preferred_intents)

        # Sort priority: Pursue > Pursue with effort > Unranked > Pivot or skip > Mismatched intent
        action_priority = (
            0 if action.startswith("✅") else
            1 if action.startswith("⚠️") else
            2 if action.startswith("📊") else
            3 if action.startswith("🔴") else
            4
        )
        rows.append((action_priority, kw, intent, confidence, feas_status, action))

    # Sort by action group, then alphabetically
    rows.sort(key=lambda x: (x[0], x[1]))
    for _, kw, intent, confidence, feas_status, action in rows:
        report.append(f"| {kw} | {intent} | {confidence} | {feas_status} | {action} |")

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

    feas_map = {r.get("Keyword"): r for r in keyword_feasibility if r.get("Query_Label") != "P"}

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

            # Confidence ranking
            conf_rank = 3 if confidence == "high" else 2 if confidence == "medium" else 1

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
        lambda: _render_content_plan(data, plan_order, preferred_intents),
    ))

    # 1b. Overview & Opportunity
    report.append("## 1b. Market Overview")
    if overview:
        report.append(f"- **Keywords Analyzed:** {len(overview)}")

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
    display_phrases, had_source_text = _display_phrases_with_source(data)

    if display_phrases:
        report.append("\n### Most repeated phrases")
        report.append(
            "*Counted across the snippets, ads, related searches and autocomplete "
            "Google displayed — not the full text of competitor pages. Phrases "
            "that just restate your search term are excluded.*\n")
        for row in display_phrases:
            report.append(f"- **{row['Phrase']}** ({row['Count']} occurrences)")
    elif had_source_text:
        # Zero-from-non-empty is a real finding here, not a failure to report: on a
        # small keyword set nearly every repeated phrase IS the search term. Say
        # that plainly rather than padding the list back out with echoes (P19).
        report.append(
            "\n*No distinct competitor vocabulary found. Every phrase repeated "
            "often enough to count was a restatement of the search terms "
            "themselves, which says nothing about how competitors write. Analyse "
            "more keywords, or a wider set of related terms, to get a usable "
            "vocabulary list.*")
    else:
        report.append("\n*No competitor text was captured in this run.*")
    report.append("\n")

    # 4. Strategic Bridge
    report.append("## 4. Strategic Recommendations (The Bridge)")
    report.append("How to differentiate using Bowen Theory.")
    report.extend(_directive("section_4"))

    # M1.B — Mixed-Intent Strategic Note callouts above Bowen pattern blocks
    _kw_profiles = data.get("keyword_profiles", {})
    _STRATEGY_DESCRIPTIONS = {
        "compete_on_dominant": (
            "Match the dominant intent format directly. The client's existing "
            "content posture aligns with the most-represented intent in this SERP."
        ),
        "backdoor": (
            "Produce content matching a non-dominant but client-aligned intent. "
            "Likely to outrank head-on competitors via differentiation."
        ),
        "avoid": "No good fit for the client's content capabilities. Skip this keyword.",
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
        if _desc:
            report.append(_desc)

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

            # RC.4.1 — Add evidence block if triggers found
            if rec.get("Detected_Triggers") and rec.get("Detected_Triggers") != "N/A":
                triggers_str = rec.get('Detected_Triggers')
                report.append(f"- *Triggers found:* {triggers_str}")

                # Build evidence block from organic_results
                triggers = [t.strip().lower() for t in triggers_str.split(",") if t.strip()]
                most_rel_kw = _get_most_relevant_keyword(rec, _organic_results, _kw_profiles, _paa_questions)

                if triggers and most_rel_kw:
                    # Find organic results for this keyword that contain trigger words
                    evidence_titles = []
                    for org_result in _organic_results:
                        if org_result.get("Root_Keyword") != most_rel_kw:
                            continue
                        title = org_result.get("title", "").lower()
                        domain = org_result.get("domain", "")
                        if any(trigger in title for trigger in triggers):
                            evidence_titles.append((org_result.get("title", ""), domain))
                            if len(evidence_titles) >= 3:
                                break

                    # RC.4.1 — Render evidence block if titles found
                    if evidence_titles:
                        report.append("\n> **Why this pattern fired:**")
                        report.append(f"> Trigger word(s) `{triggers_str}` appeared in SERP results for")
                        report.append(f"> **`{most_rel_kw}`**:")
                        for title, domain in evidence_titles:
                            report.append(f"> - *\"{title}\"* — `{domain}`")
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
            if dominance:
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

                conts = dominance.get("content_dominance", {})
                if conts:
                    report.append("\n### Content Type Dominance (Top 10)")
                    for k, v in sorted(conts.items(), key=lambda x: x[1], reverse=True):
                        report.append(f"- **{k}:** {v}%")
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
        primary_rows = [r for r in feasibility_rows if r.get("Query_Label") != "P"]
        pivot_rows   = {r.get("Source_Keyword", r.get("Keyword")): r
                        for r in feasibility_rows if r.get("Query_Label") == "P"}

        # Table header
        report.append("| Keyword | Client DA | Avg Comp DA | Gap | Status | Recommended Play | Recommended Pivot |")
        report.append("|---------|-----------|-------------|-----|--------|------------------|-------------------|")

        STATUS_ICONS = {
            "High Feasibility":     "✅ High",
            "Moderate Feasibility": "⚠️ Moderate",
            "Low Feasibility":      "🔴 Low",
            "Not Measured":         "⚠️ Not measured",
        }

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
            client_da = row.get("client_da", "—")
            avg_da   = row.get("avg_serp_da")
            gap      = row.get("gap")
            status   = STATUS_ICONS.get(row.get("feasibility_status", ""), row.get("feasibility_status", "—"))
            avg_da_str = f"{avg_da:.0f}" if avg_da is not None else "—"
            gap_str    = f"{gap:+.0f}" if gap is not None else "—"

            play_cell = format_play_cell((feas_kw_profiles.get(kw) or {}).get("recommended_play"))

            pivot_cell = "*(stay the course)*"
            if row.get("pivot_status") == "No pivot — informational":
                # SEAM (chip C): the extraction-play recommendation renders here.
                pivot_cell = "*(informational — extraction play)*"
            elif row.get("pivot_status") == "Pivoting to Hyper-Local":
                suggested = row.get("suggested_keyword", "")
                # Check if we have a pivot result with local pack data
                pivot_result = pivot_rows.get(kw)
                if pivot_result:
                    pack_str = _local_pack_phrase(pivot_result.get("Client_In_Local_Pack"))
                    pivot_feas = pivot_result.get("feasibility_status", "")
                    p_icon = STATUS_ICONS.get(pivot_feas, pivot_feas)
                    pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
                else:
                    pivot_cell = f"**{suggested}**"

            report.append(f"| {kw} | {client_da} | {avg_da_str} | {gap_str} | {status} | {play_cell} | {pivot_cell} |")

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
        # RC.5 — No feasibility data: show credential instructions
        report.append("**⚠️ Feasibility data unavailable for this run.**\n")
        report.append(
            "Domain Authority scoring requires at least one of:\n"
            "- `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` in `.env` (pay-per-use, primary)\n"
            "- `MOZ_TOKEN` in `.env` (free tier, 50 rows/month)\n\n"
            "Without DA data, keyword ranking is based on intent alignment only (see Section 0). "
            "Re-run with credentials to enable full feasibility scoring.\n"
        )

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
    if METRICS_AVAILABLE:
        _overview = data.get("overview", [])
        _run_id = _overview[0].get("Run_ID") if _overview else None
        if _run_id:
            vol = metrics.get_volatility_metrics(_run_id)
            if vol and vol.get("status") == "success":
                report.append("## 6. Market Volatility")

                # RC.7 — Handle nan or null volatility scores
                vol_score = vol.get("volatility_score")
                is_nan = (
                    vol_score is None or
                    str(vol_score).lower() == "nan" or
                    (isinstance(vol_score, float) and vol_score != vol_score)  # NaN check
                )

                if is_nan and vol.get("comparability_warning"):
                    report.append("**Not applicable for this run.**\n")
                    report.append(
                        "Volatility requires two runs with the same keyword set. "
                        "This run used a different keyword set than the previous run:\n"
                    )
                    report.append(f"- **This run:** {vol.get('keywords_current', 'unknown')}")
                    report.append(f"- **Previous run:** {vol.get('keywords_previous', 'unknown')}\n")
                    report.append(
                        "Run again with the same keywords to establish a baseline for rank change tracking."
                    )
                elif not is_nan and vol_score is not None:
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

    Format: *SERP intent context (most relevant keyword: <kw>): <intent>, confidence <conf>[, mixed: c1 + c2].*
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

    return (
        f"*SERP intent context (most relevant keyword: {most_relevant_kw}): "
        f"{primary}, confidence {confidence}{mixed_segment}.*"
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
            lines.append(f"- **Primary intent:** {primary}  *(confidence: {confidence})*")

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


def main():
    parser = argparse.ArgumentParser(
        description="Generate Marketing Insights Report")
    parser.add_argument("--json", required=True,
                        help="Path to serp_norm.json or market_analysis_v2.json")
    parser.add_argument("--out", required=True,
                        help="Output Markdown file path")
    parser.add_argument("--db", default="serp_data.db",
                        help="SQLite DB for AI-Overview exposure trend (D1 / AV.1).")
    parser.add_argument("--run-ts", default=None,
                        help="Run timestamp YYYYMMDD_HHMM; default parsed from --json.")
    args = parser.parse_args()

    data = load_data(args.json)
    # D1: persist AIO exposure under the run's identity (parsed from the
    # market_analysis_* filename) so the trend is keyed to real runs, never a
    # wall-clock stamp. Unparseable → run_ts None → render-only (no persistence).
    run_ts = args.run_ts or aio_exposure.run_ts_from_filename(args.json)
    report_content = generate_report(data, db_path=args.db, run_ts=run_ts)

    try:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"Report generated: {args.out}")
    except Exception as e:
        print(f"Error writing report: {e}")


if __name__ == "__main__":
    main()
