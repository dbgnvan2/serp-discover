"""brief_prompts.py — prompt loading and construction for content brief pipeline.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import os
import re
import yaml

def progress(message):
    print(message, flush=True)


MAIN_REPORT_PROMPT_DEFAULT = os.path.join("prompts", "main_report")

ADVISORY_PROMPT_DEFAULT = os.path.join("prompts", "advisory")

CORRECTION_PROMPT_DEFAULT = os.path.join("prompts", "correction", "user_template.md")


def _extract_code_block_after_heading(markdown_text, heading_text):
    # Finds the first fenced code block after the given heading, allowing
    # explanatory text between the heading and the block.
    idx = markdown_text.find(heading_text)
    if idx == -1:
        return None
    tail = markdown_text[idx + len(heading_text):]
    match = re.search(r"```(?:[a-zA-Z0-9_]*)\n(.*?)\n```", tail, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _read_prompt_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_prompt_blocks(prompt_source, progress_label="[5/7]", progress_name="prompt spec"):
    if not os.path.exists(prompt_source):
        return None, None
    progress(f"{progress_label} Loading {progress_name} from {prompt_source}...")
    if os.path.isdir(prompt_source):
        system_prompt = _read_prompt_file(os.path.join(prompt_source, "system.md"))
        user_template = _read_prompt_file(os.path.join(prompt_source, "user_template.md"))
        return system_prompt, user_template

    with open(prompt_source, "r", encoding="utf-8") as f:
        text = f.read()
    system_prompt = _extract_code_block_after_heading(text, "### System Prompt")
    user_template = _extract_code_block_after_heading(text, "### User Prompt Template")
    return system_prompt, user_template


def load_single_prompt(prompt_path, progress_label=None, progress_name="prompt template"):
    if progress_label:
        progress(f"{progress_label} Loading {progress_name} from {prompt_path}...")
    return _read_prompt_file(prompt_path)


def build_user_prompt(template, context, extracted_data, warnings):
    additional_context = context["additional_context"]
    if warnings:
        additional_context += "\n\nData extraction warnings:\n" + "\n".join(f"- {w}" for w in warnings)

    prompt_payload = build_main_report_payload(extracted_data)
    user_prompt = template
    replacements = {
        "{{CLIENT_NAME}}": context["client_name"],
        "{{CLIENT_DOMAIN}}": context["client_domain"],
        "{{ORG_TYPE}}": context["org_type"],
        "{{LOCATION}}": context["location"],
        "{{FRAMEWORK_DESCRIPTION}}": context["framework_description"],
        "{{CONTENT_FOCUS}}": context["content_focus"],
        "{{ADDITIONAL_CONTEXT}}": additional_context or "None provided.",
        "{{QUERY_COUNT}}": str(len(extracted_data.get("queries", []))),
        "{{ROOT_KEYWORD_COUNT}}": str(len(extracted_data.get("root_keywords", []))),
        "{{GEO_LOCATION}}": context["location"],
        "{{COLLECTION_DATE}}": extracted_data.get("metadata", {}).get("created_at", "unknown"),
        "{{EXTRACTED_DATA_JSON}}": json.dumps(prompt_payload, separators=(",", ":"), default=str),
    }
    for k, v in replacements.items():
        user_prompt = user_prompt.replace(k, v)
    return user_prompt


def build_main_report_payload(extracted_data):
    keyword_profiles = {}
    for keyword, profile in (extracted_data.get("keyword_profiles", {}) or {}).items():
        keyword_profiles[keyword] = {
            "total_results": profile.get("total_results"),
            "serp_modules": profile.get("serp_modules", [])[:8],
            "has_ai_overview": profile.get("has_ai_overview"),
            "has_local_pack": profile.get("has_local_pack"),
            "has_discussions_forums": profile.get("has_discussions_forums"),
            "entity_distribution": profile.get("entity_distribution", {}),
            "entity_dominant_type": profile.get("entity_dominant_type"),
            "entity_label": profile.get("entity_label"),
            "top5_organic": [
                {
                    "rank": row.get("rank"),
                    "title": row.get("title"),
                    "source": row.get("source"),
                    "entity_type": row.get("entity_type"),
                    "content_type": row.get("content_type"),
                }
                for row in profile.get("top5_organic", [])[:5]
            ],
            "aio_citation_count": profile.get("aio_citation_count"),
            "aio_top_sources": profile.get("aio_top_sources", [])[:5],
            "paa_questions": profile.get("paa_questions", [])[:8],
            "paa_count": profile.get("paa_count"),
            "autocomplete_top10": profile.get("autocomplete_top10", [])[:10],
            "related_searches": profile.get("related_searches", [])[:8],
            "local_pack_count": profile.get("local_pack_count"),
            "client_visible": profile.get("client_visible"),
            "client_rank": profile.get("client_rank"),
            "client_rank_delta": profile.get("client_rank_delta"),
            "client_aio_cited": profile.get("client_aio_cited"),
        }

    competitive_landscape = {}
    for keyword, landscape in (extracted_data.get("competitive_landscape", {}) or {}).items():
        competitive_landscape[keyword] = {
            "total_organic_results": landscape.get("total_organic_results"),
            "entity_breakdown": landscape.get("entity_breakdown", {}),
            "top_sources": landscape.get("top_sources", [])[:5],
            "content_type_breakdown": landscape.get("content_type_breakdown", {}),
        }

    payload = {
        "metadata": {
            "run_id": extracted_data.get("metadata", {}).get("run_id"),
            "created_at": extracted_data.get("metadata", {}).get("created_at"),
        },
        "root_keywords": extracted_data.get("root_keywords", []),
        "queries": [
            {
                "source_keyword": item.get("source_keyword"),
                "query_label": item.get("query_label"),
                "total_results": item.get("total_results"),
                "serp_features": item.get("serp_features", []),
                "has_ai_overview": item.get("has_ai_overview"),
                "client_mentioned_in_aio_text": item.get("client_mentioned_in_aio_text"),
            }
            for item in extracted_data.get("queries", [])
        ],
        "organic_summary": extracted_data.get("organic_summary", {}),
        "client_position": extracted_data.get("client_position", {}),
        "strategic_flags": extracted_data.get("strategic_flags", {}),
        "keyword_profiles": keyword_profiles,
        "competitive_landscape": competitive_landscape,
        "aio_analysis": extracted_data.get("aio_analysis", {}),
        "aio_citations_top25": extracted_data.get("aio_citations_top25", [])[:25],
        "aio_total_citations": extracted_data.get("aio_total_citations"),
        "aio_unique_sources": extracted_data.get("aio_unique_sources"),
        "paa_analysis": extracted_data.get("paa_analysis", {}),
        "bowen_reframe_faqs": (extracted_data.get("paa_by_intent") or {}).get("Systemic", [])[:10],
        "feasibility_summary": extracted_data.get("feasibility_summary"),
        "tool_recommendations_verified": extracted_data.get("tool_recommendations_verified", []),
        "autocomplete_by_keyword": {
            keyword: rows[:10]
            for keyword, rows in (extracted_data.get("autocomplete_by_keyword", {}) or {}).items()
        },
        "related_searches_by_keyword": {
            keyword: rows[:10]
            for keyword, rows in (extracted_data.get("related_searches_by_keyword", {}) or {}).items()
        },
        "autocomplete_summary": extracted_data.get("autocomplete_summary", {}),
        "local_pack_summary": extracted_data.get("local_pack_summary", {}),
        "market_language": extracted_data.get("market_language", {}),
        "competitor_ads": extracted_data.get("competitor_ads", []),
    }
    return payload


def build_correction_message(validation_issues, template_path=CORRECTION_PROMPT_DEFAULT):
    template = load_single_prompt(template_path)
    if not template:
        raise RuntimeError(f"Correction prompt template could not be loaded from {template_path}")
    issues_text = "\n".join(f"- {issue}" for issue in validation_issues)
    return template.replace("{{VALIDATION_ISSUES}}", issues_text)


def append_interpretation_notes(report_text, note_issues):
    if not note_issues:
        return report_text

    note_lines = []
    seen = set()
    for issue in note_issues:
        match = re.search(
            r"for '([^']+)': ([^ ]+) should be described as ([^.]+)\.",
            issue,
            flags=re.IGNORECASE,
        )
        if match:
            keyword = match.group(1)
            entity_label = match.group(2)
            guidance = match.group(3)
            line = (
                f"For '{keyword}', the pre-computed entity label is `{entity_label}`. "
                f"Treat this SERP as {guidance} and interpret any single-category dominance wording cautiously."
            )
        else:
            line = issue
        if line not in seen:
            seen.add(line)
            note_lines.append(f"- {line}")

    section = "\n\n## Data Interpretation Notes\n" + "\n".join(note_lines) + "\n"
    if "## Data Interpretation Notes" in report_text:
        return report_text
    return report_text.rstrip() + section


