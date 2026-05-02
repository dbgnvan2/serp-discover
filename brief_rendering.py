"""brief_rendering.py — report/brief rendering for content brief pipeline.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import json
import os
import re
from collections import Counter
from datetime import datetime
import yaml

from brief_data_extraction import (
    _safe_int, extract_analysis_data_from_json,
    load_yaml_config, load_client_context_from_config,
)
from brief_validation import (
    validate_extraction, validate_llm_report,
    partition_validation_issues, has_hard_validation_failures,
    validate_advisory_briefing,
)
from brief_prompts import (
    load_prompt_blocks, build_user_prompt, build_correction_message,
    build_main_report_payload, append_interpretation_notes,
)
from brief_llm import run_llm_report


def progress(message):
    print(message, flush=True)


_BRIEF_ROUTING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brief_pattern_routing.yml")
_BRIEF_ROUTING_CACHE: dict | None = None

_ROUTING_PATTERN_KEYS = {"paa_themes", "paa_categories", "keyword_hints"}


def load_brief_pattern_routing(path: str | None = None) -> dict:
    """Load and validate brief_pattern_routing.yml.

    Purpose: Provide editorial PAA/keyword/intent-slot routing to content brief generators.
    Spec:    serp_tool1_improvements_spec.md#I.1
    Tests:   tests/test_brief_routing.py::test_i12_yaml_matches_previous_constants
    """
    global _BRIEF_ROUTING_CACHE
    if _BRIEF_ROUTING_CACHE is not None and path is None:
        return _BRIEF_ROUTING_CACHE

    fpath = path or _BRIEF_ROUTING_PATH
    with open(fpath, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if "patterns" not in raw or not isinstance(raw["patterns"], list):
        raise ValueError(f"{fpath}: 'patterns' must be a non-empty list")
    if "intent_slot_descriptions" not in raw or not isinstance(raw["intent_slot_descriptions"], dict):
        raise ValueError(f"{fpath}: 'intent_slot_descriptions' must be a dict")

    # Load strategic pattern names for cross-validation
    _sp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategic_patterns.yml")
    with open(_sp_path, encoding="utf-8") as f:
        sp = yaml.safe_load(f) or []
    valid_pattern_names = {p["Pattern_Name"] for p in sp if isinstance(p, dict)}

    paa_themes: dict = {}
    paa_categories: dict = {}
    keyword_hints: dict = {}

    for entry in raw["patterns"]:
        name = entry.get("pattern_name", "").strip()
        if not name:
            raise ValueError(f"{fpath}: each pattern entry must have a non-empty 'pattern_name'")
        if name not in valid_pattern_names:
            raise ValueError(
                f"{fpath}: pattern_name {name!r} not found in strategic_patterns.yml. "
                f"Valid names: {sorted(valid_pattern_names)}"
            )
        missing = _ROUTING_PATTERN_KEYS - set(entry.keys())
        if missing:
            raise ValueError(f"{fpath} entry {name!r}: missing required keys: {sorted(missing)}")
        paa_themes[name] = list(entry["paa_themes"] or [])
        paa_categories[name] = set(entry["paa_categories"] or [])
        keyword_hints[name] = list(entry["keyword_hints"] or [])

    result = {
        "paa_themes": paa_themes,
        "paa_categories": paa_categories,
        "keyword_hints": keyword_hints,
        "intent_slot_descriptions": dict(raw["intent_slot_descriptions"]),
    }
    if path is None:
        _BRIEF_ROUTING_CACHE = result
    return result

def _infer_intent_text(keyword, paa_questions, related_terms):
    text = " ".join(
        [keyword.lower()] + [q.lower() for q in paa_questions] + [t.lower() for t in related_terms]
    )
    if any(x in text for x in ["law", "lawyer", "custody", "will", "inheritance", "court"]):
        return "Legal-dominant intent"
    if any(x in text for x in ["cost", "price", "fees", "insurance", "free"]):
        return "Cost/access intent"
    if any(x in text for x in ["therap", "counsell", "counsel"]):
        return "Therapeutic service intent"
    if any(x in text for x in ["what is", "meaning", "definition", "stages"]):
        return "Informational/educational intent"
    return "Mixed informational and support intent"


def _score_keyword_opportunity(extracted_data, source_keyword):
    client_org = [
        r for r in extracted_data.get("client_position", {}).get("organic", [])
        if r.get("source_keyword") == source_keyword
    ]
    client_aio = [
        r for r in extracted_data.get("client_position", {}).get("aio_citations", [])
        if r.get("source_keyword") == source_keyword
    ]
    client_local = [
        r for r in extracted_data.get("client_position", {}).get("local_pack", [])
        if r.get("source_keyword") == source_keyword
    ]
    profile = extracted_data.get("keyword_profiles", {}).get(source_keyword, {})
    aio_count = profile.get("aio_citation_count", 0)
    organic_rows = profile.get("top5_organic", [])
    low_competition = len({r.get("source") for r in organic_rows[:10] if r.get("source")}) <= 5
    has_top10_client = any(_safe_int(r.get("rank"), 999) <= 10 for r in client_org)
    has_position = bool(client_org or client_aio or client_local)

    score = 0
    if has_position:
        score += 4
    if has_top10_client:
        score += 3
    score += min(aio_count, 3)
    if low_competition:
        score += 2
    if len(organic_rows) >= 20:
        score += 1
    return score


def generate_local_report(extracted_data, context, warnings):
    now = datetime.now().strftime("%Y-%m-%d")
    root_keywords = extracted_data.get("root_keywords", [])
    queries = extracted_data.get("queries", [])
    organic_summary = extracted_data.get("organic_summary", {})

    kw_scores = [
        (kw, _score_keyword_opportunity(extracted_data, kw))
        for kw in root_keywords
    ]
    kw_scores.sort(key=lambda x: x[1], reverse=True)

    lines = []
    lines.append("# Content Opportunity Report")
    lines.append(f"Date: {now}")
    lines.append(f"Run ID: {extracted_data.get('metadata', {}).get('run_id', 'unknown')}")
    lines.append("")
    lines.append("## Section 1: Data Summary")
    lines.append(
        f"This run analyzed {len(root_keywords)} root keywords and {len(queries)} total queries. "
        f"The dataset includes {organic_summary.get('total_rows', 0)} organic rows and "
        f"{extracted_data.get('aio_total_citations', 0)} AI Overview citations."
    )
    if warnings:
        lines.append(
            "Data quality caveats were detected: " + "; ".join(warnings) + ". "
            "Interpret entity distributions and recommendation confidence accordingly."
        )
    else:
        lines.append("No major extraction warnings were detected.")

    lines.append("")
    lines.append("## Section 2: Keyword Cluster Analysis")
    for kw, score in kw_scores:
        profile = extracted_data.get("keyword_profiles", {}).get(kw, {})
        landscape = extracted_data.get("competitive_landscape", {}).get(kw, {})
        top_sources = landscape.get("top_sources", [])
        top_sources_text = ", ".join(f"{s['source']} ({s['appearances']})" for s in top_sources[:3]) or "No dominant source pattern"
        paa_q = profile.get("paa_questions", [])[:5]
        related = profile.get("related_searches", [])[:5]
        intent = _infer_intent_text(kw, paa_q, related)
        modules_text = ", ".join(profile.get("serp_modules", [])[:6]) or "No module data"
        lines.append(
            f"For '{kw}', opportunity score is {score}. Dominant sources include {top_sources_text}. "
            f"Likely intent: {intent}. Common SERP modules: {modules_text}."
        )

    lines.append("")
    lines.append("## Section 3: Client Position Assessment")
    client_summary = extracted_data.get("client_position", {}).get("summary", {})
    lines.append(
        f"Client organic appearances: {client_summary.get('total_organic_appearances', 0)}. "
        f"Client AIO citations: {client_summary.get('total_aio_citations', 0)}. "
        f"Client local pack appearances: {client_summary.get('total_local_pack', 0)}. "
        f"Client AIO text mentions: {client_summary.get('total_aio_text_mentions', 0)}."
    )
    rank_deltas = extracted_data.get("rank_deltas_top20", [])
    if rank_deltas:
        biggest = rank_deltas[0]
        lines.append(
            f"Top rank movement sample: keyword '{biggest.get('source_keyword')}', "
            f"title '{biggest.get('title')}', delta {biggest.get('delta')}."
        )
    else:
        lines.append("No significant rank-delta history is available yet.")

    lines.append("")
    lines.append("## Section 4: AI Overview / GEO Opportunity Analysis")
    queries_with_aio = [q for q in queries if q.get("has_ai_overview")]
    lines.append(
        f"{len(queries_with_aio)} of {len(queries)} queries triggered AI Overview. "
        f"Top cited sources: {', '.join(s for s, _ in extracted_data.get('aio_citations_top25', [])[:5]) or 'none'}."
    )
    lines.append(
        "Best near-term GEO gains should target source-keywords where AI Overview appears and "
        "the client already has either organic presence or at least one citation foothold."
    )

    lines.append("")
    lines.append("## Section 5: Content Gap Analysis")
    cross_cutting = extracted_data.get("paa_analysis", {}).get("cross_cluster", [])[:8]
    if cross_cutting:
        lines.append(
            "Cross-cutting PAA gaps (appearing across multiple root keywords) indicate high-leverage content themes: "
            + "; ".join(p.get("question") for p in cross_cutting) + "."
        )
    else:
        lines.append("No strong cross-keyword PAA overlap was detected in this run.")

    # Spec Fix 4: deterministic Per-Keyword SERP Intent section
    kw_profiles = extracted_data.get("keyword_profiles", {})
    serp_intent_section = generate_serp_intent_section(kw_profiles)
    if serp_intent_section:
        lines.append("")
        lines.append(serp_intent_section)

    lines.append("")
    lines.append("## Section 6: Evaluation of Tool-Generated Recommendations")
    tool_recs = extracted_data.get("tool_recommendations_verified", [])
    if not tool_recs:
        lines.append("No tool-generated recommendations were present.")
    else:
        for rec in tool_recs:
            verdict = rec.get("verdict_inputs", {})
            support = "supported" if verdict.get("total_trigger_occurrences", 0) > 0 else "weakly supported"
            lines.append(
                f"'{rec.get('pattern_name')}' is {support}. Trigger evidence source: {verdict.get('primary_evidence_source', 'none')}. "
                f"Angle: {rec.get('content_angle')}."
            )

    lines.append("")
    lines.append("## Section 7: Prioritized Content Recommendations")
    for kw, score in kw_scores[:7]:
        top_sources = extracted_data.get("competitive_landscape", {}).get(kw, {}).get("top_sources", [])
        dominant = ", ".join(s["source"] for s in top_sources[:2]) or "mixed sources"
        lines.append(
            f"Priority keyword cluster '{kw}' (score {score}): create one focused page that directly answers the "
            f"highest-scoring PAA questions for this cluster, framed using {context['framework_description']}. "
            f"Rationale: current SERP is dominated by {dominant}, and this cluster has measurable visibility runway. "
            "Success criteria: new AI Overview citations and organic rank gains in label-A queries. "
            "Avoid broad, generic content that does not match the observed intent profile."
        )

    lines.append("")
    lines.append("## Section 8: Keyword Expansion Recommendations")
    for kw in root_keywords[:]:
        ac = extracted_data.get("autocomplete_by_keyword", {}).get(kw, [])[:3]
        rel = extracted_data.get("related_searches_by_keyword", {}).get(kw, [])[:3]
        if not ac and not rel:
            continue
        ac_text = ", ".join((x.get("suggestion") or "") for x in ac if x.get("suggestion"))
        rel_text = ", ".join(rel)
        lines.append(
            f"For '{kw}', test expansion terms from autocomplete ({ac_text or 'none'}) and related searches "
            f"({rel_text or 'none'}). These terms should be queued for the next run when they sharpen intent "
            "segmentation (legal vs therapeutic vs cost-access)."
        )

    return "\n".join(lines).strip()


def generate_serp_intent_section(keyword_profiles: dict) -> str:
    """Build a deterministic 'Per-Keyword SERP Intent' section from keyword_profiles.

    Spec Fix 4: injected into every report so intent data is always visible
    without opening the JSON. Returns an empty string if there are no profiles.
    """
    if not keyword_profiles:
        return ""

    lines = ["## Per-Keyword SERP Intent", ""]
    mixed_notes = []  # collect mixed-intent notes for Section 4 callouts

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
        local_pack = ev.get("local_pack_present", False)
        mixed_comps = si.get("mixed_components") or []
        dominant_pattern = tp.get("dominant_pattern")

        lines.append(f"### {kw}")
        lines.append("")

        if primary is None:
            lines.append(
                f"- **Primary intent:** insufficient data "
                f"— only {classified_n} of {organic_n} URLs could be classified"
            )
        else:
            lines.append(f"- **Primary intent:** {primary}  *(confidence: {confidence})*")

        # Distribution line — only include buckets with count > 0
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
            mixed_notes.append((kw, mixed_comps, mis))

        if dominant_pattern:
            lines.append(f"- **Title patterns:** {dominant_pattern} dominant")
        else:
            lines.append("- **Title patterns:** no dominant pattern detected")

        if local_pack:
            lines.append("- **Local pack present:** yes")

        lines.append("")

    # Mixed-intent strategic callouts
    if mixed_notes:
        lines.append("---")
        lines.append("")
        lines.append("### ⚖️ Mixed-Intent Strategic Notes")
        lines.append("")
        for kw, comps, strategy in mixed_notes:
            comp_str = " + ".join(comps) if comps else "multiple intents"
            lines.append(
                f"The keyword **{kw}** shows mixed search intent ({comp_str}). "
                f"Recommended approach: **{strategy}**."
            )
            lines.append("")
            if strategy == "compete_on_dominant":
                lines.append(
                    "- *compete_on_dominant*: Match the dominant intent format directly."
                )
            elif strategy == "backdoor":
                lines.append(
                    "- *backdoor*: Produce content matching a non-dominant but "
                    "client-aligned intent. Likely to outrank head-on competitors via differentiation."
                )
            elif strategy == "avoid":
                lines.append(
                    "- *avoid*: No good fit for the client's content capabilities."
                )
            lines.append("")

    return "\n".join(lines).strip()


def score_paa_for_brief(question_text, theme_words):
    q_lower = str(question_text or "").lower()
    return sum(1 for word in theme_words if word in q_lower)


def get_relevant_paa(paa_questions, pattern_name, max_results=5):
    _routing = load_brief_pattern_routing()
    theme_words = _routing["paa_themes"].get(pattern_name, [])
    category_hints = _routing["paa_categories"].get(pattern_name, set())
    keyword_hints = _routing["keyword_hints"].get(pattern_name, [])
    if not theme_words and not category_hints and not keyword_hints:
        return _dedupe_question_records(paa_questions)[:max_results]

    scored = []
    for idx, q in enumerate(_dedupe_question_records(paa_questions)):
        question = q.get("Question", "")
        category = q.get("Category")
        source_keyword = str(q.get("Source_Keyword", "")).lower()
        theme_score = score_paa_for_brief(question, theme_words)
        category_score = 1 if category in category_hints else 0
        keyword_score = sum(1 for hint in keyword_hints if hint in source_keyword)
        score = (theme_score * 3) + (category_score * 2) + keyword_score
        scored.append((q, score, idx))

    scored.sort(key=lambda item: (-item[1], item[2]))
    matched = [q for q, score, _idx in scored if score > 0][:max_results]

    if len(matched) < max_results:
        matched_texts = {q.get("Question") for q in matched}
        category_fill = [
            q for q, _score, _idx in scored
            if q.get("Category") in category_hints
            and q.get("Question") not in matched_texts
        ]
        matched.extend(category_fill[:max_results - len(matched)])

    if len(matched) < max_results:
        matched_texts = {q.get("Question") for q in matched}
        remaining = [
            q for q, _score, _idx in scored
            if q.get("Question") not in matched_texts
        ]
        matched.extend(remaining[:max_results - len(matched)])

    return matched[:max_results]


def get_relevant_competitors(organic_results, pattern_name, max_results=3):
    theme_words = load_brief_pattern_routing()["paa_themes"].get(pattern_name, [])
    seen_titles = set()
    scored = []
    for idx, row in enumerate(organic_results):
        title = row.get("Title", "")
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        combined = f"{title} {row.get('Snippet', '')}".lower()
        score = sum(1 for word in theme_words if word in combined)
        rank = _safe_int(row.get("Rank"), 999)
        scored.append((title, score, rank, idx))

    scored.sort(key=lambda item: (-item[1], item[2], item[3]))
    top = [title for title, score, _rank, _idx in scored if score > 0][:max_results]
    if len(top) < max_results:
        remaining = [
            title for title, _score, _rank, _idx in scored
            if title not in top
        ]
        top.extend(remaining[:max_results - len(top)])
    return top[:max_results]


def _dedupe_question_records(paa_questions):
    out = []
    seen = set()
    for q in paa_questions:
        question = q.get("Question")
        key = str(question or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def list_recommendations(data, args):
    config = load_yaml_config(args.config)
    progress("[3/7] Resolving client context from YAML...")
    context = load_client_context_from_config(config)

    progress("[4/7] Extracting report data from market_analysis JSON...")
    # Spec v2: read optional known_brands and serp_intent.thresholds with .get()
    # defaults so existing config files without these blocks keep working.
    known_brands = config.get("known_brands", []) if isinstance(config, dict) else []
    serp_intent_cfg = config.get("serp_intent", {}) if isinstance(config, dict) else {}
    intent_thresholds = serp_intent_cfg.get("thresholds")
    client_cfg = config.get("client", {}) if isinstance(config, dict) else {}
    preferred_intents = client_cfg.get("preferred_intents", [])
    extracted = extract_analysis_data_from_json(
        data,
        client_domain=context["client_domain"],
        client_name_patterns=context["client_name_patterns"],
        framework_terms=context.get("framework_terms"),
        known_brands=known_brands,
        serp_intent_thresholds=intent_thresholds,
        preferred_intents=preferred_intents,
    )
    warnings = validate_extraction(extracted)
    progress(
        f"      Extracted {len(extracted.get('root_keywords', []))} root keywords, "
        f"{len(extracted.get('queries', []))} queries, "
        f"{extracted.get('aio_total_citations', 0)} AIO citations."
    )
    extracted_size = len(json.dumps(extracted, separators=(",", ":"), default=str))
    progress(f"      Extracted data object size: {extracted_size} chars.")

    if args.use_llm:
        if not ANTHROPIC_AVAILABLE:
            print("Error: anthropic package is not installed.")
            sys.exit(2)
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("Error: ANTHROPIC_API_KEY is not set.")
            sys.exit(2)

        system_prompt, user_template = load_prompt_blocks(
            args.prompt_spec,
            progress_label="[5/7]",
            progress_name="main report prompt",
        )
        if not (system_prompt and user_template):
            print(f"Error: Prompt blocks could not be loaded from {args.prompt_spec}")
            sys.exit(2)
        try:
            progress("[6/7] Building LLM prompt payload...")
            prompt_payload = build_main_report_payload(extracted)
            prompt_payload_size = len(json.dumps(prompt_payload, separators=(",", ":"), default=str))
            progress(f"      Main report prompt payload size: {prompt_payload_size} chars.")
            user_prompt = build_user_prompt(user_template, context, extracted, warnings)
            report = run_llm_report(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=args.llm_model,
                max_tokens=args.llm_max_tokens,
            )
            validation_issues = validate_llm_report(report, extracted)
            blocking_issues, note_issues = partition_validation_issues(validation_issues)
            if validation_issues and not args.allow_unverified_report:
                if not blocking_issues and note_issues:
                    progress("[note] LLM draft produced recoverable interpretation warnings. Writing report with notes.")
                    report = append_interpretation_notes(report, note_issues)
                    validation_issues = []
                elif has_hard_validation_failures(blocking_issues):
                    progress("[fail-fast] Initial LLM draft failed hard factual validation. Skipping retry.")
                else:
                    progress("[retry] Initial LLM draft failed evidence validation. Requesting one corrected revision...")
                    correction_msg = build_correction_message(
                        blocking_issues,
                        template_path=args.correction_prompt,
                    )
                    report = run_llm_report(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=args.llm_model,
                        max_tokens=args.llm_max_tokens,
                        prior_response=report,
                        correction_message=correction_msg,
                    )
                    validation_issues = validate_llm_report(report, extracted)
                    blocking_issues, note_issues = partition_validation_issues(validation_issues)
                    if not blocking_issues and note_issues:
                        progress("[note] Corrected draft still has interpretation warnings. Writing report with notes.")
                        report = append_interpretation_notes(report, note_issues)
                        validation_issues = []
                if validation_issues:
                    artifact_path = write_validation_artifact(
                        args.report_out,
                        "Content Opportunity Report Validation Issues",
                        validation_issues,
                        report,
                    )
                    print("Error: LLM report failed evidence validation.")
                    for issue in validation_issues:
                        print(f"- {issue}")
                    print(f"- Validation artifact written to {artifact_path}")
                    sys.exit(2)
            progress("[done] LLM response received. Writing report to disk...")
        except Exception as e:
            print(f"Error: LLM report generation failed: {e}")
            sys.exit(2)
    else:
        progress("[6/7] Generating local heuristic report...")
        report = generate_local_report(extracted, context, warnings)
        progress("[done] Local report generated. Writing report to disk...")

    # Spec Fix 4: prepend deterministic SERP intent section before saving.
    # This ensures the section is always present regardless of LLM compliance.
    kw_profiles = extracted.get("keyword_profiles", {})
    serp_intent_section = generate_serp_intent_section(kw_profiles)
    if serp_intent_section:
        report = serp_intent_section + "\n\n---\n\n" + report

    with open(args.report_out, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    if args.advisory_briefing:
        if not args.use_llm:
            print("Warning: --advisory-briefing requires --use-llm. Skipping.")
        elif not ANTHROPIC_AVAILABLE or not os.getenv("ANTHROPIC_API_KEY"):
            print("Error: Advisory briefing requires anthropic package and API key.")
            sys.exit(2)
        else:
            progress("[advisory] Running second-pass strategic briefing...")
            advisory_model = args.advisory_model or args.llm_model
            advisory_system_prompt, advisory_user_template = load_prompt_blocks(
                args.advisory_prompt_dir,
                progress_label="[advisory]",
                progress_name="advisory prompt",
            )
            if not (advisory_system_prompt and advisory_user_template):
                print(f"Error: Advisory prompt files could not be loaded from {args.advisory_prompt_dir}")
                sys.exit(2)
            advisory_user = advisory_user_template.format(
                client_name=context["client_name"],
                client_domain=context["client_domain"],
                org_type=context["org_type"],
                location=context["location"],
                framework_description=context["framework_description"],
                content_focus=context["content_focus"],
                additional_context=context["additional_context"],
                strategic_flags_json=json.dumps(
                    extracted["strategic_flags"],
                    separators=(",", ":"),
                    default=str,
                ),
                market_report_text=report,
            )
            advisory_report = run_llm_report(
                system_prompt=advisory_system_prompt,
                user_prompt=advisory_user,
                model=advisory_model,
                max_tokens=4000,
            )
            advisory_issues = validate_advisory_briefing(advisory_report, extracted)
            if advisory_issues:
                correction_msg = build_correction_message(
                    advisory_issues,
                    template_path=args.correction_prompt,
                )
                advisory_report = run_llm_report(
                    system_prompt=advisory_system_prompt,
                    user_prompt=advisory_user,
                    model=advisory_model,
                    max_tokens=4000,
                    prior_response=advisory_report,
                    correction_message=correction_msg,
                )
                advisory_issues = validate_advisory_briefing(advisory_report, extracted)
                if advisory_issues:
                    artifact_path = write_validation_artifact(
                        args.advisory_out,
                        "Advisory Briefing Validation Issues",
                        advisory_issues,
                        advisory_report,
                    )
                    print("Error: Advisory briefing failed validation.")
                    for issue in advisory_issues:
                        print(f"- {issue}")
                    print(f"- Validation artifact written to {artifact_path}")
                    sys.exit(2)
            with open(args.advisory_out, "w", encoding="utf-8") as f:
                f.write(advisory_report + "\n")
            progress(f"[done] Advisory briefing written to {args.advisory_out}")

    print("\nContent Opportunity Report generated.\n")
    print(f"Output: {args.report_out}")
    print(f"Run ID: {extracted.get('metadata', {}).get('run_id', 'unknown')}")
    print(f"Root keywords: {len(extracted.get('root_keywords', []))}")
    print(f"Queries: {len(extracted.get('queries', []))}")
    print(f"AIO citations: {extracted.get('aio_total_citations', 0)}")
    print(f"Client organic appearances: {extracted.get('client_position', {}).get('summary', {}).get('total_organic_appearances', 0)}")
    print(f"Client AIO citations: {extracted.get('client_position', {}).get('summary', {}).get('total_aio_citations', 0)}")
    print(f"Report mode: {'LLM (' + args.llm_model + ')' if args.use_llm else 'heuristic'}")

    if warnings:
        print("\nData warnings:")
        for w in warnings:
            print(f"- {w}")


def generate_brief(data, rec_index=0):
    # Legacy brief generator retained for direct --out usage.
    recs = data.get("strategic_recommendations", [])
    if not recs:
        return "No strategic recommendations found in the dataset."

    if rec_index >= len(recs):
        print(f"Index {rec_index} out of range. Using 0.")
        rec_index = 0

    rec = recs[rec_index]
    paa = data.get("paa_questions", [])
    organic = data.get("organic_results", [])
    relevant_paa_records = get_relevant_paa(
        paa, rec.get("Pattern_Name"), max_results=5
    )
    relevant_paa = [q.get("Question") for q in relevant_paa_records]
    top_competitors = get_relevant_competitors(
        organic, rec.get("Pattern_Name"), max_results=3
    )

    # M1.C — SERP Intent Context: find most relevant keyword from PAA source keywords
    src_keywords = [r.get("Source_Keyword", "") for r in relevant_paa_records if r.get("Source_Keyword")]
    most_relevant_kw = Counter(src_keywords).most_common(1)[0][0] if src_keywords else ""
    kw_profiles = data.get("keyword_profiles", {})
    kp = kw_profiles.get(most_relevant_kw, {}) if most_relevant_kw else {}
    si = kp.get("serp_intent") or {}
    tp = kp.get("title_patterns") or {}
    _primary = si.get("primary_intent")
    _confidence = si.get("confidence", "low")
    _is_mixed = si.get("is_mixed", False)
    _dp = tp.get("dominant_pattern")
    _slots = load_brief_pattern_routing()["intent_slot_descriptions"]
    _slot = _slots.get(_primary, "undetermined") if _primary else "undetermined"

    lines = []
    lines.append(f"# Content Brief: {rec.get('Content_Angle')}")
    lines.append(f"**Strategy:** {rec.get('Pattern_Name')}")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d')}\n")

    # 1a. SERP Intent Context (M1.C)
    lines.append("## 1a. SERP Intent Context")
    lines.append("")
    if most_relevant_kw:
        lines.append(f"For the most relevant keyword (*{most_relevant_kw}*):")
        _primary_display = _primary if _primary is not None else "insufficient data"
        lines.append(f"- Intent: {_primary_display} *(confidence: {_confidence})*")
        lines.append(f"- Title pattern: {_dp if _dp else 'no dominant pattern'}")
        lines.append(f"- Mixed: {'yes' if _is_mixed else 'no'}")
        lines.append("")
        lines.append(f"This brief targets the **{_slot}** intent slot.")
    else:
        lines.append("No directly mapped keyword for this brief.")
    lines.append("")

    lines.append("## 1. The Core Conflict (The Hook)")
    lines.append(f"**The Status Quo (Bad Advice):** \"{rec.get('Status_Quo_Message')}\"")
    lines.append(f"**The Bowen Reframe (The Solution):** \"{rec.get('Bowen_Bridge_Reframe')}\"")
    lines.append(
        f"**Target Audience Pain Point:** They are searching for *{rec.get('Detected_Triggers')}* and feeling anxious/stuck."
    )
    lines.append("\n## 2. User Intent & Anxiety (PAA)")
    lines.append("Address these specific questions to validate the reader's experience:")
    for q in relevant_paa:
        lines.append(f"- {q}")
    lines.append("\n## 3. The Competition (What to Differentiate Against)")
    for t in top_competitors:
        lines.append(f"- *{t}*")
    return "\n".join(lines)


def write_validation_artifact(output_path, title, validation_issues, draft_text):
    base, _ext = os.path.splitext(output_path)
    artifact_path = base + ".validation.md"
    lines = [
        f"# {title}",
        "",
        "## Rejected Claims",
        "",
    ]
    lines.extend(f"- {issue}" for issue in validation_issues)
    lines.extend([
        "",
        "## Rejected Draft",
        "",
        draft_text.strip(),
        "",
    ])
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return artifact_path


