#!/usr/bin/env python3
"""
generate_insight_report.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates a Markdown summary report from the SERP analysis JSON.

Sections
--------
1. Market Overview
2. The 'Anxiety Loop' (PAA Analysis)
3. The 'Status Quo' (Competitor Language)
4. Strategic Recommendations (The Bridge)
5. SERP Composition (Entity + Content Dominance)
5b. Per-Keyword SERP Intent  ← NEW (M1.A)
5c. Keyword Feasibility & Pivot Recommendations
6. Market Volatility

Usage
-----
::

    python generate_insight_report.py --json market_analysis_v2.json --out report.md
"""
import argparse
import json
import os
import sys
from datetime import datetime

import yaml

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

    # RC.1.2 — Content brief priority (placeholder; will be filled by RC.8)
    report.append("*Content brief prioritization will be added by RC.8.*\n")

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
        return list(enumerate((rec.get("Pattern_Name", ""), None, None) for rec in strategic_recs))

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


def generate_report(data):
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
    report.extend(_render_executive_summary(data, best_kw, best_reason))

    # 1. Overview & Opportunity
    report.append("## 1. Market Overview")
    if overview:
        report.append(f"- **Keywords Analyzed:** {len(overview)}")

        # Top SERP Features
        features = [o.get("SERP_Features")
                    for o in overview if o.get("SERP_Features")]
        if features:
            unique_features = sorted(
                list(set(", ".join(features).split(", "))))
            report.append(
                f"- **Dominant SERP Features:** {', '.join(unique_features)}")
    report.append("\n")

    # 2. The "Anxiety Loop" (PAA Analysis)
    report.append("## 2. The 'Anxiety Loop' (User Intent)")
    report.append(
        "What users are frantically searching for (Problem-Awareness).")

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

        # General top questions if no categories matched
        if not (commercial or distress or reactivity):
            for q in deduped_paa[:5]:
                report.append(f"- {q['Question']}")
    else:
        report.append("_No PAA data found._")
    report.append("\n")

    # 3. The "Status Quo" (Competitor Language)
    report.append("## 3. The 'Status Quo' (Competitor Language)")
    report.append(
        "The dominant narrative in the market (Medical Model vs. Systemic).")

    # Handle key rename compatibility (serp_language_patterns vs bad_advice_patterns)
    patterns = data.get("serp_language_patterns") or data.get(
        "bad_advice_patterns", [])

    if patterns:
        report.append("\n### Top Recurring Phrases")
        # Filter for Bigrams/Trigrams and sort by count
        top_patterns = sorted(
            patterns, key=lambda x: x["Count"], reverse=True)[:10]
        for p in top_patterns:
            report.append(f"- **{p['Phrase']}** ({p['Count']} occurrences)")
    else:
        report.append("_No language patterns found._")
    report.append("\n")

    # 4. Strategic Bridge
    report.append("## 4. Strategic Recommendations (The Bridge)")
    report.append("How to differentiate using Bowen Theory.")

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
            report.append(f"- **Status Quo:** {rec.get('Status_Quo_Message')}")
            report.append(
                f"- **The Reframe:** {rec.get('Bowen_Bridge_Reframe')}")
            report.append(f"- **Content Angle:** *{rec.get('Content_Angle')}*")
            if rec.get("Detected_Triggers") and rec.get("Detected_Triggers") != "N/A":
                report.append(
                    f"- *Triggers found:* {rec.get('Detected_Triggers')}")
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

    feasibility_rows = data.get("keyword_feasibility", [])
    if feasibility_rows:
        report.append(
            "Domain Authority gap analysis for each keyword. "
            "Low Feasibility keywords include a hyper-local pivot suggestion "
            "where geographic relevance can substitute for domain strength.\n"
        )

        # Split primary and pivot rows
        primary_rows = [r for r in feasibility_rows if r.get("Query_Label") != "P"]
        pivot_rows   = {r.get("Source_Keyword", r.get("Keyword")): r
                        for r in feasibility_rows if r.get("Query_Label") == "P"}

        # Table header
        report.append("| Keyword | Client DA | Avg Comp DA | Gap | Status | Recommended Pivot |")
        report.append("|---------|-----------|-------------|-----|--------|-------------------|")

        STATUS_ICONS = {
            "High Feasibility":     "✅ High",
            "Moderate Feasibility": "⚠️ Moderate",
            "Low Feasibility":      "🔴 Low",
        }

        for row in primary_rows:
            kw       = row.get("Keyword") or row.get("original_keyword", "—")
            client_da = row.get("client_da", "—")
            avg_da   = row.get("avg_serp_da")
            gap      = row.get("gap")
            status   = STATUS_ICONS.get(row.get("feasibility_status", ""), row.get("feasibility_status", "—"))
            avg_da_str = f"{avg_da:.0f}" if avg_da is not None else "—"
            gap_str    = f"{gap:+.0f}" if gap is not None else "—"

            pivot_cell = "*(stay the course)*"
            if row.get("pivot_status") == "Pivoting to Hyper-Local":
                suggested = row.get("suggested_keyword", "")
                # Check if we have a pivot result with local pack data
                pivot_result = pivot_rows.get(kw)
                if pivot_result:
                    pack = pivot_result.get("Client_In_Local_Pack")
                    pack_str = " ✓ in local pack" if pack else " ✗ not in local pack"
                    pivot_feas = pivot_result.get("feasibility_status", "")
                    p_icon = STATUS_ICONS.get(pivot_feas, pivot_feas)
                    pivot_cell = f"**{suggested}** — {p_icon}{pack_str}"
                else:
                    pivot_cell = f"**{suggested}**"

            report.append(f"| {kw} | {client_da} | {avg_da_str} | {gap_str} | {status} | {pivot_cell} |")

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

        lines.append("")

    return lines


def main():
    parser = argparse.ArgumentParser(
        description="Generate Marketing Insights Report")
    parser.add_argument("--json", required=True,
                        help="Path to serp_norm.json or market_analysis_v2.json")
    parser.add_argument("--out", required=True,
                        help="Output Markdown file path")
    args = parser.parse_args()

    data = load_data(args.json)
    report_content = generate_report(data)

    try:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"Report generated: {args.out}")
    except Exception as e:
        print(f"Error writing report: {e}")


if __name__ == "__main__":
    main()
