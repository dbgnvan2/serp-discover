"""brief_data_extraction.py — data extraction helpers for content brief generation.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse
import yaml

from intent_verdict import compute_serp_intent, load_mapping as load_intent_mapping
from title_patterns import compute_title_patterns
from classifiers import classify_url_from_patterns


def progress(message):
    print(message, flush=True)

DEFAULT_CLIENT_CONTEXT = {
    "client_name": "Living Systems Counselling",
    "client_domain": "livingsystems.ca",
    "client_name_patterns": ["Living Systems"],
    "org_type": "Small nonprofit counselling organization",
    "location": "North Vancouver, BC, Canada",
    "framework_description": (
        "Bowen Family Systems Theory. Differentiation of self, emotional cutoff, "
        "triangles, and multigenerational family patterns."
    ),
    "content_focus": (
        "Counselling services and educational content grounded in Bowen Family Systems Theory."
    ),
    "additional_context": (
        "Prioritize practical recommendations a small nonprofit can execute. "
        "Avoid audiences outside counselling scope."
    ),
    "framework_terms": [
        "family systems", "bowen", "differentiation",
        "emotional cutoff", "triangles", "multigenerational",
        "nuclear family emotional", "societal emotional",
    ],
}

def load_yaml_config(config_path):
    if not os.path.exists(config_path):
        return {}
    try:
        progress(f"[1/7] Loading config from {config_path}...")
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading config YAML ({config_path}): {e}")
        sys.exit(1)


def load_client_context_from_config(config):
    section = config.get("analysis_report", {}) if isinstance(config, dict) else {}

    context = {
        "client_name": section.get("client_name", DEFAULT_CLIENT_CONTEXT["client_name"]),
        "client_domain": section.get("client_domain", DEFAULT_CLIENT_CONTEXT["client_domain"]),
        "client_name_patterns": section.get(
            "client_name_patterns",
            DEFAULT_CLIENT_CONTEXT["client_name_patterns"]
        ),
        "org_type": section.get("org_type", DEFAULT_CLIENT_CONTEXT["org_type"]),
        "location": section.get(
            "location",
            config.get("serpapi", {}).get("location", DEFAULT_CLIENT_CONTEXT["location"])
        ),
        "framework_description": section.get(
            "framework_description", DEFAULT_CLIENT_CONTEXT["framework_description"]
        ),
        "content_focus": section.get("content_focus", DEFAULT_CLIENT_CONTEXT["content_focus"]),
        "additional_context": section.get(
            "additional_context", DEFAULT_CLIENT_CONTEXT["additional_context"]
        ),
        "framework_terms": section.get(
            "framework_terms", DEFAULT_CLIENT_CONTEXT["framework_terms"]
        ),
    }
    if isinstance(context["client_name_patterns"], str):
        context["client_name_patterns"] = [
            p.strip() for p in context["client_name_patterns"].split(",") if p.strip()
        ]
    return context


def _extract_domain(url):
    if not url:
        return ""
    try:
        return urlparse(str(url)).netloc.replace("www.", "").lower()
    except Exception:
        return str(url).lower()


def _safe_int(v, default=0):
    if v is None:
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _top_sources_for_keyword(organic_rows, source_keyword, max_n=5):
    ctr = Counter()
    for row in organic_rows:
        if row.get("Source_Keyword") != source_keyword:
            continue
        if row.get("Query_Label") != "A":
            continue
        src = row.get("Source")
        if src:
            ctr[src] += 1
    return ctr.most_common(max_n)


def _normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _classify_entity_distribution(distribution):
    counts = Counter({
        entity: _safe_int(count)
        for entity, count in (distribution or {}).items()
        if _safe_int(count) > 0
    })
    if not counts:
        return None, "unclassified"

    ranked = counts.most_common()
    top_entity, top_count = ranked[0]
    second_count = ranked[1][1] if len(ranked) > 1 else 0
    classified_total = sum(counts.values())
    top_pct = top_count / classified_total if classified_total else 0.0

    if top_pct >= 0.60:
        return top_entity, f"dominated_by_{top_entity}"

    tied_or_close = [
        entity for entity, count in ranked
        if (top_count - count) <= 2
    ]
    if len(tied_or_close) >= 2:
        return top_entity, f"mixed_{'_'.join(sorted(tied_or_close))}"

    return top_entity, f"{top_entity}_plurality"


def _entity_label_reason_text(entity_label, dominant_type):
    label = str(entity_label or "")
    if label.startswith("dominated_by_"):
        return f"Dominated by {label.removeprefix('dominated_by_')} entities."
    if label.endswith("_plurality"):
        return f"{label.removesuffix('_plurality').replace('_', ' ')} plurality."
    if label.startswith("mixed_"):
        return f"Mixed or contested across {label.removeprefix('mixed_').replace('_', ', ')}."
    if dominant_type:
        return f"Leading entity type: {dominant_type}."
    return "Mixed entity distribution."


def _client_match_patterns(client_name_patterns):
    patterns = []
    for pattern in client_name_patterns or []:
        normalized = _normalize_text(pattern)
        if len(normalized.split()) >= 2:
            patterns.append(normalized)
    return patterns


def _contains_phrase(text, phrase):
    return phrase and phrase in _normalize_text(text)


def _extract_excerpt(text, phrase, radius=80):
    normalized_text = str(text or "")
    idx = _normalize_text(normalized_text).find(phrase)
    if idx == -1:
        return None
    start = max(0, idx - radius)
    end = min(len(normalized_text), idx + len(phrase) + radius)
    return normalized_text[start:end].strip()


def _parse_trigger_words(trigger_text):
    if isinstance(trigger_text, list):
        cleaned = []
        for item in trigger_text:
            if item is None:
                continue
            text = str(item).strip().lower()
            if text:
                cleaned.append(text)
        return cleaned
    return [part.strip().lower() for part in str(trigger_text or "").split(",") if part.strip()]


def _count_terms_in_texts(terms, texts):
    counts = {}
    for term in terms:
        total = 0
        pattern = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
        for text in texts:
            total += len(pattern.findall(str(text or "")))
        if total:
            counts[term] = total
    return counts


def _compute_strategic_flags(
    root_keywords,
    keyword_profiles,
    client_position,
    total_results_by_kw,
    paa_analysis,
    preferred_intents=None,
):
    """Compute strategic priority flags per keyword.

    Spec v2 Gap 4: when a SERP has mixed intent (serp_intent.is_mixed = True),
    set keyword_profiles[kw]['mixed_intent_strategy'] to one of:
      - "compete_on_dominant": dominant intent matches the client's existing
        intent presence (the client already ranks for this intent elsewhere).
      - "backdoor": dominant intent is uncompetable, but a non-dominant intent
        on this SERP appears in client.preferred_intents — there's a way in via
        a different content type.
      - "avoid": neither path applies.
    Non-mixed keywords get null.
    """
    preferred_intents = set(preferred_intents or [])

    # Client's existing intent presence: intents of keywords where the client
    # is currently visible. This is the client's "content-asset history" in
    # intent terms — what they've already proven they can rank for.
    client_intent_presence = set()
    for kw, profile in keyword_profiles.items():
        if profile.get("client_visible"):
            si = profile.get("serp_intent") or {}
            primary = si.get("primary_intent")
            if primary and primary not in ("uncategorised", "mixed"):
                client_intent_presence.add(primary)

    flags = {}

    client_organic = client_position.get("organic", [])
    summary = client_position.get("summary", {})
    declining = [
        item for item in client_organic
        if item.get("stability") == "declining"
    ]
    visible_kws = summary.get("keywords_with_any_visibility", [])

    if declining:
        worst = min(declining, key=lambda x: x.get("rank_delta") or 0)
        flags["defensive_urgency"] = "high"
        flags["defensive_detail"] = (
            f"Client's content '{worst.get('title', 'unknown')}' "
            f"dropped {abs(worst.get('rank_delta', 0))} positions "
            f"to rank #{worst.get('rank', '?')} for "
            f"'{worst.get('source_keyword', 'unknown')}'. "
            f"This page provides {summary.get('total_aio_citations', 0)} of the "
            f"client's AIO citations. If organic rank continues declining, "
            f"AIO citation loss is probable."
        )
    elif client_organic:
        flags["defensive_urgency"] = "low"
        flags["defensive_detail"] = "All client positions are stable or improving."
    else:
        flags["defensive_urgency"] = "none"
        flags["defensive_detail"] = "Client has no organic positions to defend."

    total_kws = len(root_keywords)
    visible_count = len(visible_kws)
    if visible_count == 0:
        flags["visibility_concentration"] = "absent"
        flags["concentration_detail"] = (
            f"Client has zero visibility across all {total_kws} tracked keywords."
        )
    elif visible_count == 1:
        flags["visibility_concentration"] = "critical"
        flags["concentration_detail"] = (
            f"Client visible for 1 of {total_kws} tracked keywords "
            f"('{visible_kws[0]}'). 100% of organic and AIO visibility depends on a single keyword cluster."
        )
    elif visible_count <= total_kws * 0.3:
        flags["visibility_concentration"] = "high"
        flags["concentration_detail"] = (
            f"Client visible for {visible_count} of {total_kws} tracked keywords."
        )
    else:
        flags["visibility_concentration"] = "distributed"
        flags["concentration_detail"] = (
            f"Client visible for {visible_count} of {total_kws} tracked keywords."
        )

    opportunity_scale = {}
    for kw in root_keywords:
        profile = keyword_profiles.get(kw, {})
        total_results = profile.get("total_results", total_results_by_kw.get(kw, 0))
        client_rank = profile.get("client_rank")
        client_delta = profile.get("client_rank_delta")
        client_visible = profile.get("client_visible", False)
        entity_dominant = profile.get("entity_dominant_type")
        entity_label = profile.get("entity_label")

        if client_visible and client_delta is not None and client_delta < 0:
            action = "defend"
            reason = (
                f"Client ranks #{client_rank}, declined {abs(client_delta)} positions. "
                f"Protect existing visibility before expanding elsewhere."
            )
        elif client_visible:
            trend_text = (
                "stable" if client_delta == 0 else
                "new (no history)" if client_delta is None else
                "improving"
            )
            action = "strengthen"
            reason = (
                f"Client ranks #{client_rank}. Position is {trend_text}. "
                f"Expand content depth to improve rank."
            )
        elif total_results < 200:
            action = "skip"
            reason = (
                f"Only {total_results} total results. Market too small to justify dedicated content investment."
            )
        elif entity_label in {"dominated_by_legal", "legal_plurality"}:
            action = "enter_cautiously"
            reason = (
                "Legal entities lead this SERP. Entry requires differentiated content "
                "that avoids competing on legal topics directly."
            )
        else:
            action = "enter"
            reason = (
                f"{total_results:,} total results. Client has no current visibility. "
                f"{_entity_label_reason_text(entity_label, entity_dominant)}"
            )

        # Spec v2 Gap 4: mixed-intent strategy.
        # Computed only for keywords whose serp_intent.is_mixed == True.
        mixed_intent_strategy = None
        si = profile.get("serp_intent") or {}
        if si.get("is_mixed"):
            # primary_intent is "mixed" when is_mixed=True; derive dominant from distribution
            distribution = si.get("intent_distribution") or {}
            dominant = max(distribution, key=distribution.get) if distribution else None
            non_dominant_intents = {
                intent for intent, share in distribution.items()
                if share > 0 and intent != dominant
            }
            if dominant in client_intent_presence:
                mixed_intent_strategy = "compete_on_dominant"
            elif preferred_intents & non_dominant_intents:
                mixed_intent_strategy = "backdoor"
            else:
                mixed_intent_strategy = "avoid"
            # Persist back onto the keyword profile so downstream consumers
            # (LLM payload, validators, advisory briefing) can reference it.
            profile["mixed_intent_strategy"] = mixed_intent_strategy
        else:
            profile["mixed_intent_strategy"] = None

        opportunity_scale[kw] = {
            "total_results": total_results,
            "client_rank": client_rank,
            "client_trend": (
                "declining" if client_delta is not None and client_delta < 0
                else "improving" if client_delta is not None and client_delta > 0
                else "stable" if client_delta == 0
                else "new" if client_visible
                else None
            ),
            "action": action,
            "reason": reason,
            "mixed_intent_strategy": mixed_intent_strategy,
        }

    flags["opportunity_scale"] = opportunity_scale

    priority_order = {"defend": 0, "strengthen": 1, "enter": 2, "enter_cautiously": 3, "skip": 4}
    priorities = []
    for kw in root_keywords:
        opp = opportunity_scale[kw]
        priorities.append({
            "action": opp["action"],
            "keyword": kw,
            "total_results": opp["total_results"],
            "reason": opp["reason"],
        })

    priorities.sort(key=lambda x: (priority_order.get(x["action"], 99), -x["total_results"]))
    flags["content_priorities"] = priorities

    cross = paa_analysis.get("cross_cluster", [])
    if cross:
        top_cross = cross[0]
        flags["top_cross_cluster_paa"] = {
            "question": top_cross["question"],
            "cluster_count": top_cross["cluster_count"],
            "combined_total_results": top_cross["combined_total_results"],
        }
    else:
        flags["top_cross_cluster_paa"] = None

    return flags


def _classify_paa_intent(paa_rows):
    """Group PAA questions by Intent_Tag written by serp_audit.py.

    Returns a dict with keys ``"External Locus"``, ``"Systemic"``, and
    ``"General"``, each containing a list of question strings.  Questions
    without an ``Intent_Tag`` fall into ``"General"``.
    """
    buckets = {"External Locus": [], "Systemic": [], "General": []}
    seen = set()
    for row in paa_rows:
        question = str(row.get("Question") or "").strip()
        if not question or question in seen:
            continue
        seen.add(question)
        tag = str(row.get("Intent_Tag") or "").strip()
        if tag in buckets:
            buckets[tag].append(question)
        else:
            buckets["General"].append(question)
    return buckets


def _build_feasibility_summary(feasibility_rows):
    """Compact summary of keyword feasibility data for the LLM payload.

    Returns a dict with:
    - ``low_feasibility``: list of {keyword, gap, suggested_pivot} for
      Low Feasibility primary keywords (query_label != "P").
    - ``moderate_feasibility``: list of keyword strings.
    - ``high_feasibility``: list of keyword strings.
    - ``pivot_serp_results``: list of {keyword, suggested_pivot, client_in_local_pack}
      for pivot keywords (query_label == "P") where pivot data was fetched.
    """
    primary = [r for r in feasibility_rows if r.get("Query_Label") != "P" and r.get("query_label") != "P"]
    pivots  = [r for r in feasibility_rows if r.get("Query_Label") == "P" or r.get("query_label") == "P"]

    low, moderate, high = [], [], []
    for row in primary:
        status = row.get("feasibility_status", "")
        kw = row.get("Keyword") or row.get("keyword_text") or ""
        gap = row.get("gap")
        suggested = row.get("suggested_keyword", "")
        if status == "Low Feasibility":
            low.append({"keyword": kw, "gap": gap, "suggested_pivot": suggested})
        elif status == "Moderate Feasibility":
            moderate.append(kw)
        elif status == "High Feasibility":
            high.append(kw)

    pivot_results = []
    for row in pivots:
        source = row.get("Source_Keyword") or row.get("source_keyword") or ""
        kw = row.get("Keyword") or row.get("keyword_text") or ""
        in_pack = row.get("Client_In_Local_Pack") if row.get("Client_In_Local_Pack") is not None else row.get("client_in_local_pack")
        pivot_results.append({
            "source_keyword": source,
            "pivot_keyword": kw,
            "client_in_local_pack": bool(in_pack) if in_pack is not None else None,
        })

    return {
        "low_feasibility": low,
        "moderate_feasibility": moderate,
        "high_feasibility": high,
        "pivot_serp_results": pivot_results,
    }


def extract_analysis_data_from_json(
    data,
    client_domain,
    client_name_patterns=None,
    framework_terms=None,
    known_brands=None,
    serp_intent_thresholds=None,
    intent_mapping=None,
    preferred_intents=None,
):
    """Build a compact, pre-verified analysis object from market_analysis_v2.json.

    New (spec v2):
        known_brands: list of competitor brand domain/name strings — drives
            domain_role classification in serp_intent and brand_only detection
            in title_patterns. If None, [].
        serp_intent_thresholds: dict overriding intent_verdict.DEFAULT_THRESHOLDS.
            If None, defaults from intent_verdict are used.
        intent_mapping: pre-loaded mapping dict (from load_intent_mapping()).
            If None, loaded once from intent_mapping.yml at the project root.
    """
    client_domain_lower = (client_domain or "").lower()
    client_name_patterns = client_name_patterns or []
    framework_terms = framework_terms or DEFAULT_CLIENT_CONTEXT["framework_terms"]
    client_phrase_patterns = _client_match_patterns(client_name_patterns)
    known_brands = list(known_brands or [])
    preferred_intents = list(preferred_intents or [])

    # Load intent mapping once. Cached at the call site if the caller supplies
    # one; otherwise loaded fresh here. Failure to load is a HARD error — the
    # rest of the pipeline assumes serp_intent is computable.
    if intent_mapping is None:
        intent_mapping = load_intent_mapping()

    # For title_patterns brand_only detection, combine the client's own brand
    # patterns with the operator-supplied known_brands so client URLs that
    # surface as bare-brand titles are classified correctly.
    title_brand_aliases = list(client_name_patterns) + known_brands

    overview = data.get("overview", [])
    organic = data.get("organic_results", [])
    citations = data.get("ai_overview_citations", [])
    paa_rows = data.get("paa_questions", [])
    autocomplete = data.get("autocomplete_suggestions", [])
    related = data.get("related_searches", [])
    modules = data.get("serp_modules", [])
    local_pack = data.get("local_pack_and_maps", [])
    bigrams_trigrams = data.get("serp_language_patterns", [])
    recs = data.get("strategic_recommendations", [])
    ads = data.get("competitors_ads", [])

    if overview:
        first = overview[0]
        metadata = {
            "run_id": first.get("Run_ID"),
            "created_at": str(first.get("Created_At") or "unknown"),
            "google_url_sample": first.get("Google_URL"),
        }
    else:
        metadata = {"run_id": "unknown", "created_at": "unknown", "google_url_sample": None}

    root_keywords = sorted({r.get("Source_Keyword") for r in overview if r.get("Source_Keyword")})

    total_results_by_kw = {}
    queries = []
    overview_by_kw = defaultdict(list)
    for r in overview:
        source_kw = r.get("Source_Keyword")
        if not source_kw:
            continue
        overview_by_kw[source_kw].append(r)
        if r.get("Query_Label") == "A" or source_kw not in total_results_by_kw:
            total_results_by_kw[source_kw] = _safe_int(r.get("Total_Results"), 0)
        aio_text = str(r.get("AI_Overview") or "")
        client_mentioned = any(_contains_phrase(aio_text, phrase) for phrase in client_phrase_patterns)
        queries.append({
            "source_keyword": source_kw,
            "query_label": r.get("Query_Label"),
            "executed_query": r.get("Executed_Query"),
            "total_results": _safe_int(r.get("Total_Results"), 0),
            "serp_features": r.get("SERP_Features"),
            "has_ai_overview": bool(r.get("Has_Main_AI_Overview")),
            "client_mentioned_in_aio_text": client_mentioned,
            "rank_1": {
                "title": r.get("Rank_1_Title"),
                "source": _extract_domain(r.get("Rank_1_Link")),
            },
            "rank_2": {
                "title": r.get("Rank_2_Title"),
                "source": _extract_domain(r.get("Rank_2_Link")),
            },
            "rank_3": {
                "title": r.get("Rank_3_Title"),
                "source": _extract_domain(r.get("Rank_3_Link")),
            },
        })

    organic_rows_by_kw = defaultdict(list)
    entity_by_kw = defaultdict(Counter)
    entity_breakdown_with_na = defaultdict(Counter)
    content_counter = Counter()
    content_breakdown_by_kw = defaultdict(Counter)
    source_counter = Counter()
    rank_deltas = []
    total_organic_rows = 0
    entity_na = 0
    client_organic = []
    top_sources_by_kw_counter = defaultdict(lambda: defaultdict(lambda: {"appearances": 0, "best_rank": 999, "entity_types": Counter()}))

    for row in organic:
        source_kw = row.get("Source_Keyword")
        label = row.get("Query_Label")
        if not source_kw:
            continue
        total_organic_rows += 1
        rank = _safe_int(row.get("Rank"), 999)
        src = row.get("Source")
        entity = row.get("Entity_Type") or "N/A"
        content_type = row.get("Content_Type") or "N/A"
        snippet = str(row.get("Snippet") or "")
        title = str(row.get("Title") or "")
        link = str(row.get("Link") or "")

        if src:
            source_counter[src] += 1
        entity_breakdown_with_na[source_kw][entity] += 1
        if entity != "N/A":
            entity_by_kw[source_kw][entity] += 1
        else:
            entity_na += 1
        if content_type != "N/A":
            content_counter[content_type] += 1
            content_breakdown_by_kw[source_kw][content_type] += 1

        if label == "A":
            # Fix 5b: apply URL pattern fallback for rows with no content
            # classification (N/A or unknown from SerpAPI raw data).
            effective_ct = content_type
            if effective_ct in ("N/A", "unknown", "other"):
                pattern_ct = classify_url_from_patterns(link, entity)
                if pattern_ct:
                    effective_ct = pattern_ct
            row_profile = {
                "rank": rank,
                "title": title,
                "source": src,
                "entity_type": entity,
                "content_type": effective_ct,
            }
            organic_rows_by_kw[source_kw].append(row_profile)
            if src:
                entry = top_sources_by_kw_counter[source_kw][src]
                entry["appearances"] += 1
                entry["best_rank"] = min(entry["best_rank"], rank)
                entry["entity_types"][entity] += 1

        if client_domain_lower and client_domain_lower in link.lower():
            delta_raw = row.get("Rank_Delta")
            delta = None if delta_raw in (None, "", "N/A") else _safe_int(delta_raw, 0)
            client_organic.append({
                "source_keyword": source_kw,
                "query_label": label,
                "rank": rank,
                "title": title,
                "link": link,
                "rank_delta": delta,
                "stability": (
                    "new" if delta is None else
                    "stable" if delta == 0 else
                    "improving" if delta > 0 else
                    "declining"
                ),
            })

        delta_raw = row.get("Rank_Delta")
        if delta_raw not in (None, "", "N/A"):
            delta = _safe_int(delta_raw, 0)
            if delta != 0:
                rank_deltas.append({
                    "source_keyword": source_kw,
                    "query_label": label,
                    "rank": rank,
                    "delta": delta,
                    "source": src,
                    "title": title,
                })

    aio_source_counter = Counter()
    aio_by_kw = defaultdict(Counter)
    client_aio_citations = []
    for row in citations:
        src = row.get("Source")
        source_kw = row.get("Source_Keyword")
        link = str(row.get("Link") or "")
        title = row.get("Title")
        if src:
            aio_source_counter[src] += 1
            aio_by_kw[source_kw][src] += 1
        if client_domain_lower and client_domain_lower in link.lower():
            client_aio_citations.append({
                "source_keyword": source_kw,
                "query_label": row.get("Query_Label"),
                "title": title,
                "link": link,
            })

    paa_unique = {}
    for row in paa_rows:
        question = row.get("Question")
        if not question:
            continue
        source_kw = row.get("Source_Keyword")
        record = paa_unique.setdefault(question, {
            "category": row.get("Category"),
            "score": _safe_int(row.get("Score"), 0),
            "source_keywords": [],
        })
        if source_kw and source_kw not in record["source_keywords"]:
            record["source_keywords"].append(source_kw)

    paa_cross_cluster = []
    paa_single_cluster = []
    for question, info in paa_unique.items():
        kws = sorted(info["source_keywords"])
        entry = {
            "question": question,
            "source_keywords": kws,
            "cluster_count": len(kws),
            "combined_total_results": sum(total_results_by_kw.get(kw, 0) for kw in kws),
            "category": info.get("category"),
        }
        if len(kws) >= 2:
            paa_cross_cluster.append(entry)
        else:
            paa_single_cluster.append(entry)
    paa_cross_cluster.sort(key=lambda item: (-item["cluster_count"], -item["combined_total_results"], item["question"]))
    paa_single_cluster.sort(key=lambda item: (-item["combined_total_results"], item["question"]))
    paa_analysis = {
        "cross_cluster": paa_cross_cluster,
        "single_cluster": paa_single_cluster,
        "summary": {
            "total_unique_questions": len(paa_unique),
            "cross_cluster_count": len(paa_cross_cluster),
            "single_cluster_count": len(paa_single_cluster),
        },
    }

    paa_by_intent = _classify_paa_intent(paa_rows)

    feasibility_rows = data.get("keyword_feasibility", [])
    feasibility_summary = _build_feasibility_summary(feasibility_rows) if feasibility_rows else None

    autocomplete_by_kw = defaultdict(list)
    autocomplete_texts = []
    for row in autocomplete:
        source_kw = row.get("Source_Keyword")
        suggestion = row.get("Suggestion")
        if source_kw and suggestion:
            autocomplete_by_kw[source_kw].append({
                "suggestion": suggestion,
                "relevance": row.get("Relevance"),
            })
            autocomplete_texts.append(str(suggestion))

    related_by_kw = defaultdict(list)
    related_texts = []
    for row in related:
        source_kw = row.get("Source_Keyword")
        term = row.get("Term")
        if source_kw and term and term not in related_by_kw[source_kw]:
            related_by_kw[source_kw].append(term)
            related_texts.append(str(term))

    bigrams = []
    trigrams = []
    for row in bigrams_trigrams:
        item = {"phrase": row.get("Phrase"), "count": _safe_int(row.get("Count"), 0)}
        if row.get("Type") == "Bigram":
            bigrams.append(item)
        elif row.get("Type") == "Trigram":
            trigrams.append(item)

    client_language_mentions = []
    for item in (bigrams + trigrams):
        phrase_l = _normalize_text(item.get("phrase"))
        if any(phrase in phrase_l for phrase in client_phrase_patterns):
            client_language_mentions.append(item)

    modules_by_kw = defaultdict(list)
    for row in modules:
        if row.get("Query_Label") == "A" and row.get("Present"):
            modules_by_kw[row.get("Source_Keyword")].append({
                "module": row.get("Module"),
                "order": _safe_int(row.get("Order"), 999),
            })

    serp_has_local = set()
    for kw in root_keywords:
        for mod in modules_by_kw.get(kw, []):
            if mod.get("module") in ("local_results", "local_map", "local_pack"):
                serp_has_local.add(kw)
                break

    local_pack_summary = {}
    client_local = []
    local_rows_by_kw = defaultdict(list)
    for row in local_pack:
        if row.get("Query_Label") != "A":
            continue
        source_kw = row.get("Source_Keyword")
        if source_kw:
            local_rows_by_kw[source_kw].append(row)

    for kw in root_keywords:
        rows = local_rows_by_kw.get(kw, [])
        if rows:
            category_counter = Counter(str(r.get("Category") or "Unknown") for r in rows)
            ratings = [float(r.get("Rating")) for r in rows if r.get("Rating") not in (None, "", "N/A")]
            client_present = False
            for row in rows:
                website = str(row.get("Website") or "")
                if client_domain_lower and client_domain_lower in website.lower():
                    client_present = True
                    client_local.append({
                        "source_keyword": kw,
                        "rank": row.get("Rank"),
                        "name": row.get("Name"),
                        "category": row.get("Category"),
                    })
            local_pack_summary[kw] = {
                "total_businesses": len(rows),
                "top_categories": category_counter.most_common(5),
                "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "client_present": client_present,
                "on_serp": kw in serp_has_local,
            }
    local_pack_summary["serp_local_pack_confirmed"] = sorted(serp_has_local)
    local_pack_summary["serp_local_pack_absent"] = sorted(kw for kw in root_keywords if kw not in serp_has_local)

    market_language = {
        "top_20_bigrams": sorted(bigrams, key=lambda x: -x["count"])[:20],
        "top_10_trigrams": sorted(trigrams, key=lambda x: -x["count"])[:10],
        "client_mentions": client_language_mentions,
        "bowen_theory_terms": [],
    }

    aio_analysis = {}
    for kw in root_keywords:
        a_query = next((q for q in overview_by_kw.get(kw, []) if q.get("Query_Label") == "A"), None)
        aio_text = str((a_query or {}).get("AI_Overview") or "")
        opening_excerpt = aio_text[:400] if aio_text else None
        client_excerpt = None
        client_mentioned = False
        for phrase in client_phrase_patterns:
            if _contains_phrase(aio_text, phrase):
                client_mentioned = True
                client_excerpt = _extract_excerpt(aio_text, phrase)
                break
        top_sources = [source for source, _count in aio_by_kw.get(kw, Counter()).most_common(10)]
        sources_named = [source for source in top_sources if _contains_phrase(aio_text, _normalize_text(source))]
        key_phrases = []
        for item in (market_language["top_20_bigrams"] + market_language["top_10_trigrams"]):
            phrase = item["phrase"]
            if _contains_phrase(aio_text, _normalize_text(phrase)):
                key_phrases.append(phrase)
        aio_analysis[kw] = {
            "has_aio": bool((a_query or {}).get("Has_Main_AI_Overview")),
            "aio_length_chars": len(aio_text),
            "sources_named_in_text": sources_named[:10],
            "client_mentioned": client_mentioned,
            "client_excerpt": client_excerpt,
            "key_phrases": key_phrases[:12],
            "opening_excerpt": opening_excerpt,
        }

    # Framework language subset is computed after AIO/language extraction to keep zeros explicit.
    term_counts = []
    for term in framework_terms:
        total = 0
        for item in (bigrams + trigrams):
            if term in _normalize_text(item.get("phrase")):
                total += _safe_int(item.get("count"), 0)
        term_counts.append({"phrase": term, "count": total})
    market_language["bowen_theory_terms"] = term_counts

    tool_recommendations_verified = []
    all_trigger_words = set()
    organic_titles = [row.get("Title") for row in organic]
    organic_snippets = [row.get("Snippet") for row in organic]
    aio_texts = [row.get("AI_Overview") for row in overview]
    paa_texts = [row.get("Question") for row in paa_rows]
    for row in recs:
        triggers = _parse_trigger_words(row.get("Triggers"))
        all_trigger_words.update(triggers)
        found = {
            "in_paa_questions": _count_terms_in_texts(triggers, paa_texts),
            "in_organic_titles": _count_terms_in_texts(triggers, organic_titles),
            "in_organic_snippets": _count_terms_in_texts(triggers, organic_snippets),
            "in_aio_text": _count_terms_in_texts(triggers, aio_texts),
            "in_autocomplete": _count_terms_in_texts(triggers, autocomplete_texts),
            "in_related_searches": _count_terms_in_texts(triggers, related_texts),
        }
        source_totals = {
            name: sum(bucket.values())
            for name, bucket in found.items()
        }
        primary_source = max(source_totals.items(), key=lambda item: item[1])[0] if any(source_totals.values()) else "none"
        tool_recommendations_verified.append({
            "pattern_name": row.get("Pattern_Name"),
            "trigger_words_searched_for": triggers,
            "triggers_found": found,
            "content_angle": row.get("Content_Angle"),
            "status_quo_message": row.get("Status_Quo_Message"),
            "reframe": row.get("Bowen_Bridge_Reframe"),
            "verdict_inputs": {
                "any_paa_evidence": bool(found["in_paa_questions"]),
                "any_autocomplete_evidence": bool(found["in_autocomplete"]),
                "total_trigger_occurrences": sum(source_totals.values()),
                "primary_evidence_source": primary_source,
            },
        })

    autocomplete_summary = {
        "total_suggestions": len(autocomplete),
        "by_keyword": {kw: len(rows) for kw, rows in autocomplete_by_kw.items()},
        "trigger_word_hits": {
            trigger: sorted({
                row["suggestion"]
                for rows in autocomplete_by_kw.values()
                for row in rows
                if re.search(rf"\b{re.escape(trigger)}\b", str(row["suggestion"]), flags=re.IGNORECASE)
            })
            for trigger in sorted(all_trigger_words)
        },
    }

    competitive_landscape = {}
    keyword_profiles = {}
    for kw in root_keywords:
        kw_rows = sorted(organic_rows_by_kw.get(kw, []), key=lambda x: x["rank"])
        top_sources = []
        for source, info in sorted(
            top_sources_by_kw_counter.get(kw, {}).items(),
            key=lambda item: (-item[1]["appearances"], item[1]["best_rank"], item[0])
        )[:5]:
            entity_type = info["entity_types"].most_common(1)[0][0] if info["entity_types"] else "N/A"
            top_sources.append({
                "source": source,
                "appearances": info["appearances"],
                "entity_type": entity_type,
                "best_rank": info["best_rank"],
            })
        competitive_landscape[kw] = {
            "total_organic_results": len(kw_rows),
            "entity_breakdown": dict(entity_breakdown_with_na.get(kw, {})),
            "top_sources": top_sources,
            "content_type_breakdown": dict(content_breakdown_by_kw.get(kw, {})),
        }

        paa_for_kw = sorted([
            question for question, info in paa_unique.items()
            if kw in info["source_keywords"]
        ])
        local_summary = local_pack_summary.get(kw, {})
        kw_client_org = [item for item in client_organic if item["source_keyword"] == kw and item["query_label"] == "A"]
        kw_client_aio = [item for item in client_aio_citations if item["source_keyword"] == kw]
        modules_list = [
            f"{item['module']}:{item['order']}"
            for item in sorted(modules_by_kw.get(kw, []), key=lambda x: x["order"])
        ]
        dominant_type, entity_label = _classify_entity_distribution(entity_by_kw.get(kw, {}))

        # SERP intent verdict — top-10 organic only (spec Fix 1 denominator rule).
        # row_profile carries 'source' (domain) not the full link; substring
        # matching on 'source' still works for client/competitor detection.
        kw_has_local_pack = kw in serp_has_local
        kw_local_pack_count = local_pack_summary.get(kw, {}).get("total_businesses", 0)
        serp_intent = compute_serp_intent(
            organic_rows=kw_rows[:10],
            has_local_pack=kw_has_local_pack,
            client_domain=client_domain_lower,
            known_brand_domains=known_brands,
            local_pack_member_count=kw_local_pack_count,
            mapping=intent_mapping,
            thresholds=serp_intent_thresholds,
        )

        # Title pattern extraction (top 10 organic titles in rank order).
        kw_titles = [r.get("title", "") for r in kw_rows[:10]]
        title_patterns = compute_title_patterns(kw_titles, brand_aliases=title_brand_aliases)

        keyword_profiles[kw] = {
            "total_results": total_results_by_kw.get(kw, 0),
            "serp_modules": modules_list,
            "has_ai_overview": aio_analysis.get(kw, {}).get("has_aio", False),
            "has_local_pack": kw_has_local_pack,
            "has_discussions_forums": any("discussions" in item["module"] or "forums" in item["module"] for item in modules_by_kw.get(kw, [])),
            "entity_distribution": dict(entity_by_kw.get(kw, {})),
            "entity_dominant_type": dominant_type,
            "entity_label": entity_label,
            "top5_organic": kw_rows[:5],
            "aio_citation_count": sum(aio_by_kw.get(kw, Counter()).values()),
            "aio_top_sources": aio_by_kw.get(kw, Counter()).most_common(5),
            "paa_questions": paa_for_kw,
            "paa_count": len(paa_for_kw),
            "autocomplete_top10": [item["suggestion"] for item in autocomplete_by_kw.get(kw, [])[:10]],
            "related_searches": related_by_kw.get(kw, [])[:10],
            "local_pack_count": local_summary.get("total_businesses", 0),
            "client_visible": bool(kw_client_org or kw_client_aio or local_summary.get("client_present")),
            "client_rank": kw_client_org[0]["rank"] if kw_client_org else None,
            "client_rank_delta": kw_client_org[0]["rank_delta"] if kw_client_org else None,
            "client_aio_cited": bool(kw_client_aio),
            "serp_intent": serp_intent,
            "title_patterns": title_patterns,
        }

    client_aio_text_mentions = []
    for kw, analysis in aio_analysis.items():
        if analysis.get("client_mentioned"):
            client_aio_text_mentions.append({
                "source_keyword": kw,
                "query_label": "A",
                "excerpt": analysis.get("client_excerpt") or analysis.get("opening_excerpt"),
            })

    client_position = {
        "organic": [],
        "aio_citations": [],
        "aio_text_mentions": client_aio_text_mentions,
        "local_pack": client_local,
        "language_pattern_mentions": client_language_mentions,
    }
    for item in client_organic:
        competitors_above = []
        for row in organic_rows_by_kw.get(item["source_keyword"], []):
            if row["rank"] < item["rank"]:
                competitors_above.append({
                    "rank": row["rank"],
                    "source": row["source"],
                    "entity_type": row["entity_type"],
                })
        enriched = dict(item)
        enriched["competitors_above"] = competitors_above
        client_position["organic"].append(enriched)
    for item in client_aio_citations:
        kw = item["source_keyword"]
        item_copy = dict(item)
        item_copy["also_mentioned_in_aio_text"] = any(m["source_keyword"] == kw for m in client_aio_text_mentions)
        item_copy["aio_text_excerpt"] = aio_analysis.get(kw, {}).get("client_excerpt")
        client_position["aio_citations"].append(item_copy)

    visible_keywords = sorted({
        item["source_keyword"] for item in client_position["organic"]
    } | {
        item["source_keyword"] for item in client_position["aio_citations"]
    } | {
        item["source_keyword"] for item in client_position["aio_text_mentions"]
    } | {
        item["source_keyword"] for item in client_position["local_pack"]
    })
    deltas = [item["rank_delta"] for item in client_position["organic"] if item["rank_delta"] is not None]
    client_position["summary"] = {
        "total_organic_appearances": len({(item["source_keyword"], item["query_label"]) for item in client_position["organic"]}),
        "total_aio_citations": len(client_position["aio_citations"]),
        "total_aio_text_mentions": len(client_position["aio_text_mentions"]),
        "total_local_pack": len(client_position["local_pack"]),
        "keywords_with_any_visibility": visible_keywords,
        "keywords_with_zero_visibility": [kw for kw in root_keywords if kw not in visible_keywords],
        "has_declining_positions": any((delta or 0) < 0 for delta in deltas),
        "worst_delta": min(deltas) if deltas else None,
    }

    strategic_flags = _compute_strategic_flags(
        root_keywords=root_keywords,
        keyword_profiles=keyword_profiles,
        client_position=client_position,
        total_results_by_kw=total_results_by_kw,
        paa_analysis=paa_analysis,
        preferred_intents=preferred_intents,
    )

    ads_out = []
    for row in ads:
        ads_out.append({
            "keyword": row.get("Source_Keyword") or row.get("Root_Keyword"),
            "advertiser": row.get("Name"),
            "position": row.get("Rank"),
            "link": row.get("Link"),
        })

    return {
        "metadata": metadata,
        "root_keywords": root_keywords,
        "queries": queries,
        "organic_summary": {
            "total_rows": total_organic_rows,
            "entity_classified_count": total_organic_rows - entity_na,
            "entity_unclassified_count": entity_na,
        },
        "source_frequency_top30": source_counter.most_common(30),
        "content_type_distribution": content_counter.most_common(10),
        "rank_deltas_top20": sorted(rank_deltas, key=lambda x: -abs(x["delta"]))[:20],
        "paa_analysis": paa_analysis,
        "paa_by_intent": paa_by_intent,
        "feasibility_summary": feasibility_summary,
        "tool_recommendations_verified": tool_recommendations_verified,
        "client_position": client_position,
        "keyword_profiles": keyword_profiles,
        "competitive_landscape": competitive_landscape,
        "aio_analysis": aio_analysis,
        "aio_citations_top25": aio_source_counter.most_common(25),
        "aio_total_citations": sum(aio_source_counter.values()),
        "aio_unique_sources": len(aio_source_counter),
        "autocomplete_by_keyword": dict(autocomplete_by_kw),
        "related_searches_by_keyword": dict(related_by_kw),
        "autocomplete_summary": autocomplete_summary,
        "local_pack_summary": local_pack_summary,
        "market_language": market_language,
        "competitor_ads": ads_out,
        "strategic_flags": strategic_flags,
    }


