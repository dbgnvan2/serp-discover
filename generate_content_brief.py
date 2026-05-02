#!/usr/bin/env python3
"""
generate_content_brief.py

Modes:
1) Improved content opportunity report (default for launcher list mode):
   python generate_content_brief.py --json market_analysis_v2.json --list

2) Legacy single brief mode:
   python generate_content_brief.py --json market_analysis_v2.json --out brief.md --index 0
"""
import argparse
import json
import os
import sys
import yaml

from brief_data_extraction import (
    DEFAULT_CLIENT_CONTEXT,
    load_yaml_config, load_client_context_from_config,
    _extract_domain, _safe_int, _top_sources_for_keyword, _normalize_text,
    _classify_entity_distribution, _entity_label_reason_text,
    _client_match_patterns, _contains_phrase, _extract_excerpt,
    _parse_trigger_words, _count_terms_in_texts, _compute_strategic_flags,
    _classify_paa_intent, _build_feasibility_summary,
    extract_analysis_data_from_json,
)
from brief_validation import (
    validate_extraction, validate_llm_report, validate_advisory_briefing,
    _mixed_keyword_dominance_profiles, _label_requires_mixed, _label_requires_plurality,
    has_hard_validation_failures, partition_validation_issues,
)
from brief_prompts import (
    MAIN_REPORT_PROMPT_DEFAULT, ADVISORY_PROMPT_DEFAULT, CORRECTION_PROMPT_DEFAULT,
    _extract_code_block_after_heading, _read_prompt_file,
    load_prompt_blocks, load_single_prompt, build_user_prompt,
    build_main_report_payload, build_correction_message, append_interpretation_notes,
)
from brief_llm import (
    MAIN_REPORT_DEFAULT_MODEL, ADVISORY_DEFAULT_MODEL, SUPPORTED_REPORT_MODELS,
    run_llm_report,
)
from brief_rendering import (
    write_validation_artifact, _infer_intent_text, _score_keyword_opportunity,
    generate_local_report, generate_serp_intent_section, score_paa_for_brief,
    get_relevant_paa, get_relevant_competitors, _dedupe_question_records,
    list_recommendations, generate_brief,
)

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


def progress(message):
    print(message, flush=True)


def load_data(json_path):
    try:
        progress(f"[2/7] Loading analysis JSON from {json_path}...")
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate prompt-informed content opportunities report or a legacy content brief."
    )
    parser.add_argument("--json", required=True, help="Path to market_analysis_v2.json")
    parser.add_argument("--out", help="Legacy single-brief output markdown path")
    parser.add_argument("--index", type=int, default=0, help="Legacy brief recommendation index")
    parser.add_argument("--list", action="store_true", help="Generate improved opportunity report")
    parser.add_argument("--report-out", default="content_opportunities_report.md",
                        help="Output markdown path for improved report mode")
    parser.add_argument("--prompt-spec", default=MAIN_REPORT_PROMPT_DEFAULT,
                        help="Main report prompt directory (system.md + user_template.md) or legacy combined markdown spec")
    parser.add_argument("--advisory-prompt-dir", default=ADVISORY_PROMPT_DEFAULT,
                        help="Advisory prompt directory containing system.md and user_template.md")
    parser.add_argument("--correction-prompt", default=CORRECTION_PROMPT_DEFAULT,
                        help="Correction prompt template file used for LLM revision retries")
    parser.add_argument("--use-llm", action="store_true",
                        help="Use Anthropic API with prompt spec (fails if LLM path is unavailable)")
    parser.add_argument("--config", default="config.yml",
                        help="Path to YAML config (reads analysis_report client context)")
    parser.add_argument("--llm-model", default=MAIN_REPORT_DEFAULT_MODEL)
    parser.add_argument("--llm-max-tokens", type=int, default=16000)
    parser.add_argument("--allow-unverified-report", action="store_true",
                        help="Write the LLM report even if evidence validation flags unsupported claims")
    parser.add_argument("--advisory-briefing", action="store_true",
                        help="Run a second LLM pass to produce a strategic advisory briefing")
    parser.add_argument("--advisory-out", default="advisory_briefing.md",
                        help="Output path for the advisory briefing")
    parser.add_argument("--advisory-model", default=ADVISORY_DEFAULT_MODEL,
                        help="Model for advisory pass (defaults to --llm-model)")
    args = parser.parse_args()

    data = load_data(args.json)

    if args.list:
        list_recommendations(data, args)
        return

    if not args.out:
        print("Error: --out is required unless --list is used.")
        sys.exit(1)

    brief_content = generate_brief(data, args.index)
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(brief_content)
        print(f"Content Brief generated: {args.out}")
    except Exception as e:
        print(f"Error writing brief: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
