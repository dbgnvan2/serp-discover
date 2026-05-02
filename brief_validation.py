"""brief_validation.py — LLM output validation for content brief pipeline.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import re

from brief_data_extraction import _normalize_text


def _mixed_keyword_dominance_profiles(extracted_data):
    profiles = []
    for keyword, profile in (extracted_data.get("keyword_profiles", {}) or {}).items():
        distribution = profile.get("entity_distribution", {}) or {}
        ranked = sorted(
            [(entity, count) for entity, count in distribution.items() if count],
            key=lambda item: item[1],
            reverse=True,
        )
        if len(ranked) < 2:
            continue
        (top_entity, top_count), (_second_entity, second_count) = ranked[:2]
        classified_total = sum(count for _entity, count in ranked)
        if classified_total <= 0:
            continue
        top_share = top_count / classified_total
        if second_count >= 3 and top_share <= 0.60:
            profiles.append((keyword, top_entity, top_count, second_count, top_share))
    return profiles


def _label_requires_mixed(entity_label):
    return str(entity_label or "").startswith("mixed_")


def _label_requires_plurality(entity_label):
    return str(entity_label or "").endswith("_plurality")


def validate_llm_report(report_text, extracted_data):
    issues = []
    report_l = _normalize_text(report_text)
    query_count = len(extracted_data.get("queries", []))
    keyword_profiles = extracted_data.get("keyword_profiles", {}) or {}
    queries_with_aio = sum(
        1 for profile in keyword_profiles.values()
        if profile.get("has_ai_overview")
    ) or sum(1 for q in extracted_data.get("queries", []) if q.get("has_ai_overview"))

    speculative_patterns = [
        r"indicating (?:technical|content|data|system)\w*",
        r"suggesting (?:a |that |some )?(?:bug|issue|problem|filter)",
        r"possibly due to",
        r"likely (?:because|due|caused)",
        r"technical issues? or content filtering",
        r"content filtering",
    ]
    for pattern in speculative_patterns:
        if re.search(pattern, report_l):
            issues.append(
                f"Report contains speculative causal language matching pattern: {pattern}"
            )
            break

    paa_cross_questions = {
        _normalize_text(item.get("question"))
        for item in extracted_data.get("paa_analysis", {}).get("cross_cluster", [])
    }
    if "cross-cutting" in report_l and "toxic" in report_l:
        toxic_cross_cluster = any("toxic" in question for question in paa_cross_questions)
        toxic_autocomplete = bool(extracted_data.get("autocomplete_summary", {}).get("trigger_word_hits", {}).get("toxic", []))
        if not toxic_cross_cluster and not toxic_autocomplete:
            issues.append(
                "Report claims a cross-cutting 'toxic' opportunity, but verified PAA/autocomplete evidence is absent."
            )

    for rec in extracted_data.get("tool_recommendations_verified", []):
        pattern_name = rec.get("pattern_name", "")
        verdict = rec.get("verdict_inputs", {})
        total_hits = verdict.get("total_trigger_occurrences", 0)
        if not pattern_name:
            continue
        section_match = re.search(
            rf"\*\*{re.escape(pattern_name)}\*\*:\s*([A-Z ]+)\.",
            report_text,
            flags=re.IGNORECASE,
        )
        if total_hits == 0 and section_match:
            label = section_match.group(1).strip().upper()
            if label in {"SUPPORTED", "PARTIALLY SUPPORTED"}:
                issues.append(
                    f"Report marks '{pattern_name}' as {label}, but verified trigger evidence count is zero."
                )
            paragraph_match = re.search(
                rf"(\*\*{re.escape(pattern_name)}\*\*:[^\n]*(?:\n(?!\*\*).*)*)",
                report_text,
                flags=re.IGNORECASE,
            )
            paragraph_text = paragraph_match.group(1) if paragraph_match else ""
            if re.search(
                r"(appear frequently|multiple autocomplete suggestions include|trigger[s]? found|heavy presence)",
                paragraph_text,
                flags=re.IGNORECASE,
            ):
                issues.append(
                    f"Report cites specific trigger evidence for '{pattern_name}' despite zero verified trigger evidence."
                )

    toxic_hits = extracted_data.get("autocomplete_summary", {}).get("trigger_word_hits", {}).get("toxic", [])
    if not toxic_hits and "high search volume term from autocomplete data" in report_l and "toxic" in report_l:
        issues.append(
            "Report cites 'toxic' as a high-volume autocomplete term, but autocomplete_summary shows no toxic hits."
        )

    aio_all_patterns = [
        rf"ai overviews appear for all {query_count} queries",
        rf"ai overviews appear across all {query_count} queries",
        rf"all {query_count} queries trigger ai overviews",
    ]
    if query_count and queries_with_aio != query_count:
        for pattern in aio_all_patterns:
            if re.search(pattern, report_l):
                issues.append(
                    f"Report claims AI Overviews appear for all {query_count} queries, but verified data shows {queries_with_aio} of {query_count}."
                )
                break
    aio_count_match = re.search(
        r"(\d+)\s+of\s+(\d+)\s+quer(?:y|ies)\s+(?:feature|have|show|trigger)",
        report_text,
        flags=re.IGNORECASE,
    )
    if aio_count_match:
        reported_with_aio = int(aio_count_match.group(1))
        reported_total = int(aio_count_match.group(2))
        if query_count and reported_total == query_count and reported_with_aio != queries_with_aio:
            issues.append(
                f"Report says {reported_with_aio} of {reported_total} queries have AI Overviews, but keyword_profiles shows {queries_with_aio} of {query_count}."
            )

    if re.search(r"data collection issue|potential data collection issue|suggesting .*data collection issue", report_l):
        issues.append(
            "Report speculates about a data collection issue without verified extraction evidence."
        )

    if re.search(r"monthly searches|monthly search volume", report_l):
        issues.append(
            "Report describes total_results as monthly search volume, which is not supported by the extracted data."
        )

    estrangement_profile = extracted_data.get("keyword_profiles", {}).get("estrangement", {})
    entity_distribution = estrangement_profile.get("entity_distribution", {}) or {}
    counselling_count = entity_distribution.get("counselling", 0)
    legal_count = entity_distribution.get("legal", 0)
    if counselling_count >= 3 and legal_count >= 3:
        if "estrangement" in report_l and re.search(r"counselling-dominat|counselling services dominat", report_l):
            issues.append(
                "Report labels the broad estrangement landscape as counselling-dominant despite a mixed legal and counselling entity distribution."
            )

    for keyword, top_entity, top_count, second_count, top_share in _mixed_keyword_dominance_profiles(extracted_data):
        section_match = re.search(
            rf"\*\*{re.escape(keyword)} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)",
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            continue
        section_text = section_match.group(1)
        if re.search(rf"\b{re.escape(top_entity)} (?:entities )?(?:heavily )?dominat", section_text, flags=re.IGNORECASE):
            issues.append(
                f"Report labels '{keyword}' as {top_entity}-dominant, but the classified entity mix is too close ({top_count} vs {second_count}; {top_share:.0%} share) and should be described as mixed or contested."
            )

    for keyword, profile in keyword_profiles.items():
        entity_label = profile.get("entity_label")
        if not entity_label:
            continue
        section_match = re.search(
            rf"\*\*{re.escape(keyword)} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)",
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            continue
        section_l = _normalize_text(section_match.group(1))
        if _label_requires_mixed(entity_label) and re.search(r"\bdominat(?:e|ed|es|ing)\b", section_l):
            issues.append(
                f"Report contradicts keyword_profiles.entity_label for '{keyword}': {entity_label} should be described as mixed or contested, not dominant."
            )
        if _label_requires_plurality(entity_label) and re.search(r"\bdominat(?:e|ed|es|ing)\b", section_l):
            issues.append(
                f"Report contradicts keyword_profiles.entity_label for '{keyword}': {entity_label} should be described as a plurality, not dominant."
            )

    # ── Spec v2 Gap 1: SERP intent verdict contradiction (HARD-FAIL) ─────────
    # ── Spec v2 Gap 2: title_patterns.dominant_pattern contradiction (SOFT) ──
    # Strong-claim phrases per intent. We only flag when the report makes an
    # explicit "this SERP is primarily X" type of claim — not casual mentions.
    INTENT_CLAIM_PHRASES = {
        "informational": [
            r"primarily informational",
            r"informational[- ]intent serp",
            r"informational intent dominates",
            r"primary intent[: ]\s*informational",
        ],
        "transactional": [
            r"primarily transactional",
            r"transactional[- ]intent serp",
            r"transactional intent dominates",
            r"primary intent[: ]\s*transactional",
            r"purchase[- ]intent serp",
        ],
        "commercial_investigation": [
            r"primarily commercial[- ]investigation",
            r"commercial investigation intent dominates",
            r"primary intent[: ]\s*commercial",
            r"investigative[- ]intent serp",
        ],
        "navigational": [
            r"primarily navigational",
            r"navigational[- ]intent serp",
            r"primary intent[: ]\s*navigational",
            r"branded serp",
        ],
        "local": [
            r"primarily local[- ]intent",
            r"local[- ]intent serp",
            r"primary intent[: ]\s*local",
        ],
    }
    PATTERN_CLAIM_PHRASES = {
        "how_to": [r"how[- ]to (?:guides? )?dominat", r"dominated by how[- ]to"],
        "what_is": [r"what[- ]is (?:guides? )?dominat", r"dominated by what[- ]is"],
        "best_of": [r"best[- ]of dominat", r"dominated by best[- ]of"],
        "vs_comparison": [r"vs\.? comparison.{0,20}dominat", r"dominated by vs"],
        "listicle_numeric": [r"listicles? dominat", r"dominated by listicles?", r"listicle[- ]dominated"],
        "brand_only": [r"brand[- ]only.{0,20}dominat", r"dominated by brand"],
        "question": [r"questions? dominat", r"dominated by questions?"],
    }

    for keyword, profile in keyword_profiles.items():
        section_match = re.search(
            rf"\*\*{re.escape(keyword)} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)",
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            continue
        section_l = _normalize_text(section_match.group(1))

        # ── serp_intent contradictions ──
        si = profile.get("serp_intent") or {}
        primary = si.get("primary_intent")
        is_mixed = si.get("is_mixed", False)
        confidence = si.get("confidence", "low")
        # Only enforce on confident, single-intent verdicts. Low confidence and
        # mixed verdicts permit the LLM more interpretive latitude.
        if primary and primary not in ("uncategorised",) and confidence != "low" and not is_mixed:
            for claimed_intent, phrases in INTENT_CLAIM_PHRASES.items():
                if claimed_intent == primary:
                    continue
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report claims '{keyword}' is {claimed_intent} intent, "
                            f"but keyword_profiles shows serp_intent.primary_intent='{primary}' "
                            f"(confidence={confidence}, is_mixed=False)."
                        )
                        break

        # is_mixed contradiction (separate hard-fail)
        if confidence != "low":
            if is_mixed and re.search(r"single[- ]intent serp|uniform intent|cleanly (?:informational|transactional|navigational)", section_l):
                issues.append(
                    f"Report describes '{keyword}' as single-intent, "
                    f"but keyword_profiles shows serp_intent.is_mixed=True."
                )
            if not is_mixed and re.search(r"mixed[- ]intent serp|mixed intent", section_l):
                issues.append(
                    f"Report describes '{keyword}' as mixed-intent, "
                    f"but keyword_profiles shows serp_intent.is_mixed=False."
                )

        # ── Spec v2 Gap 4: mixed_intent_strategy contradictions ──
        mixed_strategy = profile.get("mixed_intent_strategy")
        si_is_mixed = (profile.get("serp_intent") or {}).get("is_mixed", False)
        # HARD-FAIL: invoking mixed-intent framing on a non-mixed keyword.
        if not si_is_mixed:
            if re.search(r"backdoor (?:strategy|opportunity|approach|angle|content)|compete on (?:the )?dominant intent", section_l):
                issues.append(
                    f"Report invokes mixed-intent strategy language for '{keyword}', "
                    f"but keyword_profiles shows serp_intent.is_mixed=False "
                    f"(no mixed_intent_strategy applies)."
                )
        else:
            # SOFT-FAIL: contradicts the computed strategy.
            STRATEGY_PHRASES = {
                "compete_on_dominant": [r"backdoor", r"avoid this keyword|skip this keyword"],
                "backdoor": [r"compete on (?:the )?dominant", r"avoid this keyword|skip this keyword"],
                "avoid": [r"backdoor", r"compete on (?:the )?dominant"],
            }
            if mixed_strategy and mixed_strategy in STRATEGY_PHRASES:
                for contradicting in STRATEGY_PHRASES[mixed_strategy]:
                    if re.search(contradicting, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.mixed_intent_strategy "
                            f"for '{keyword}': computed='{mixed_strategy}', report uses "
                            f"different framing."
                        )
                        break

        # ── title_patterns.dominant_pattern contradictions (SOFT-FAIL) ──
        tp = profile.get("title_patterns") or {}
        dominant = tp.get("dominant_pattern")
        if dominant:
            for claimed_pattern, phrases in PATTERN_CLAIM_PHRASES.items():
                if claimed_pattern == dominant:
                    continue
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.title_patterns for '{keyword}': "
                            f"claims {claimed_pattern} dominance, but dominant_pattern='{dominant}'."
                        )
                        break
        else:
            # If dominant_pattern is null, the LLM should not assert one.
            for claimed_pattern, phrases in PATTERN_CLAIM_PHRASES.items():
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.title_patterns for '{keyword}': "
                            f"claims {claimed_pattern} dominance, but no pattern reached the dominance threshold."
                        )
                        break

        # ── confidence upgrade contradiction (SOFT-FAIL) ─────────────────────
        # LLM may downplay confidence but not upgrade it.
        HIGH_CONFIDENCE_PHRASES = [
            r"confidence[:\s]+high",
            r"high[- ]confidence",
            r"highly confident",
        ]
        MEDIUM_CONFIDENCE_PHRASES = [
            r"confidence[:\s]+medium",
            r"medium[- ]confidence",
        ]
        if confidence == "low":
            for phrase in HIGH_CONFIDENCE_PHRASES + MEDIUM_CONFIDENCE_PHRASES:
                if re.search(phrase, section_l):
                    issues.append(
                        f"Report upgrades confidence for '{keyword}' above computed level, "
                        f"but keyword_profiles.serp_intent.confidence='{confidence}'."
                    )
                    break
        elif confidence == "medium":
            for phrase in HIGH_CONFIDENCE_PHRASES:
                if re.search(phrase, section_l):
                    issues.append(
                        f"Report upgrades confidence for '{keyword}' to 'high', "
                        f"but keyword_profiles.serp_intent.confidence='{confidence}'."
                    )
                    break

    return issues


def validate_extraction(data):
    warnings = []
    if not data.get("root_keywords"):
        warnings.append("No root keywords extracted.")

    for kw in data.get("root_keywords", []):
        if kw not in data.get("keyword_profiles", {}):
            warnings.append(f"No keyword profile built for root keyword: {kw}")

    client_summary = data.get("client_position", {}).get("summary", {})
    if client_summary.get("total_organic_appearances", 0) == 0 and client_summary.get("total_aio_citations", 0) == 0 and client_summary.get("total_aio_text_mentions", 0) == 0 and client_summary.get("total_local_pack", 0) == 0:
        warnings.append("Client was not detected in organic, AIO citations, AIO text, or local pack.")

    queries_with_aio = sum(1 for q in data.get("queries", []) if q.get("has_ai_overview"))
    total_queries = len(data.get("queries", []))
    if total_queries > 0 and queries_with_aio == 0:
        warnings.append("No queries triggered AI Overviews.")

    if data.get("paa_analysis", {}).get("summary", {}).get("total_unique_questions", 0) < 5:
        warnings.append("Very low PAA coverage (<5 questions).")

    summary = data.get("organic_summary", {})
    total = summary.get("total_rows", 0)
    unclassified = summary.get("entity_unclassified_count", 0)
    if total > 0 and (unclassified / total) > 0.4:
        warnings.append(
            f"High unclassified entity share: {unclassified}/{total} ({unclassified/total:.0%})."
        )
    return warnings


def validate_advisory_briefing(report_text, extracted_data):
    issues = []
    report_l = _normalize_text(report_text)
    strategic_flags = extracted_data.get("strategic_flags", {})
    priorities = strategic_flags.get("content_priorities", [])
    first_priority = priorities[0] if priorities else {}
    skip_keywords = {item.get("keyword") for item in priorities if item.get("action") == "skip"}

    if strategic_flags.get("defensive_urgency") == "high":
        headline = report_text.split("## Action 1", 1)[0]
        first_block = report_text.split("## Action 1", 1)[1] if "## Action 1" in report_text else report_text
        first_block = first_block.split("## Action 2", 1)[0]
        expected_keyword = _normalize_text(first_priority.get("keyword"))
        if expected_keyword and expected_keyword not in _normalize_text(headline + "\n" + first_block):
            issues.append(
                f"Advisory briefing does not make the top defensive keyword '{first_priority.get('keyword')}' the first action."
            )

    for kw in skip_keywords:
        if kw and _normalize_text(kw) in report_l and "stop thinking about" not in report_l:
            issues.append(
                f"Advisory briefing references skip keyword '{kw}' outside the stop-thinking section."
            )

    overconfident_patterns = [
        r"you'?ll lose your rank #\d+ position entirely",
        r"will lose .*ai overview citation",
        r"will disappear entirely",
    ]
    for pattern in overconfident_patterns:
        if re.search(pattern, report_l):
            issues.append(
                "Advisory briefing uses unsupported certainty language where the data supports risk, not certainty."
            )
            break

    if re.search(r"monthly searches|monthly search volume", report_l):
        issues.append(
            "Advisory briefing describes total_results as monthly search volume, which is not supported by the extracted data."
        )

    estrangement_profile = extracted_data.get("keyword_profiles", {}).get("estrangement", {})
    entity_distribution = estrangement_profile.get("entity_distribution", {}) or {}
    counselling_count = entity_distribution.get("counselling", 0)
    legal_count = entity_distribution.get("legal", 0)
    if counselling_count >= 3 and legal_count >= 3:
        if "estrangement" in report_l and re.search(r"counselling practices dominat|counselling services dominat", report_l):
            issues.append(
                "Advisory briefing overstates broad estrangement as counselling-dominant despite mixed legal and counselling signals."
            )

    if re.search(r"eliminate your digital presence entirely|complete loss of (?:your )?digital presence", report_l):
        issues.append(
            "Advisory briefing overstates the consequence scope beyond measured search visibility."
        )

    return issues


def has_hard_validation_failures(validation_issues):
    hard_patterns = [
        "queries have ai overviews",
        "claims ai overviews appear for all",
        "cites 'toxic' as a high-volume autocomplete term",
        "cross-cutting 'toxic' opportunity",
        "marks '",
    ]
    for issue in validation_issues:
        normalized = _normalize_text(issue)
        if "despite zero verified trigger evidence" in normalized:
            return True
        if "but keyword_profiles shows" in normalized:
            return True
        if "contradicts keyword_profiles.title_patterns" in normalized:
            return True
        if "but verified data shows" in normalized:
            return True
        if any(pattern in normalized for pattern in hard_patterns):
            return True
    return False


def partition_validation_issues(validation_issues):
    blocking = []
    notes = []
    for issue in validation_issues:
        normalized = _normalize_text(issue)
        if "contradicts keyword_profiles.entity_label" in normalized:
            notes.append(issue)
        elif "contradicts keyword_profiles.mixed_intent_strategy" in normalized:
            notes.append(issue)
        elif "keyword_profiles.serp_intent.confidence" in normalized:
            notes.append(issue)
        # title_patterns.dominant_pattern contradiction is a HARD-FAIL (Fix 7).
        # Falls through to blocking.append below.
        else:
            blocking.append(issue)
    return blocking, notes




def validate_extraction(data):
    warnings = []
    if not data.get("root_keywords"):
        warnings.append("No root keywords extracted.")

    for kw in data.get("root_keywords", []):
        if kw not in data.get("keyword_profiles", {}):
            warnings.append(f"No keyword profile built for root keyword: {kw}")

    client_summary = data.get("client_position", {}).get("summary", {})
    if client_summary.get("total_organic_appearances", 0) == 0 and client_summary.get("total_aio_citations", 0) == 0 and client_summary.get("total_aio_text_mentions", 0) == 0 and client_summary.get("total_local_pack", 0) == 0:
        warnings.append("Client was not detected in organic, AIO citations, AIO text, or local pack.")

    queries_with_aio = sum(1 for q in data.get("queries", []) if q.get("has_ai_overview"))
    total_queries = len(data.get("queries", []))
    if total_queries > 0 and queries_with_aio == 0:
        warnings.append("No queries triggered AI Overviews.")

    if data.get("paa_analysis", {}).get("summary", {}).get("total_unique_questions", 0) < 5:
        warnings.append("Very low PAA coverage (<5 questions).")

    summary = data.get("organic_summary", {})
    total = summary.get("total_rows", 0)
    unclassified = summary.get("entity_unclassified_count", 0)
    if total > 0 and (unclassified / total) > 0.4:
        warnings.append(
            f"High unclassified entity share: {unclassified}/{total} ({unclassified/total:.0%})."
        )
    return warnings

