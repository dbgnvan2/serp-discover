"""query_variants.py — generated query variants for the SERP audit.

Owns the query text generation that expands each root keyword beyond the
plain "A" query, plus the situational probe execution loop:

- de-localisation shared by all variant generators;
- "A.1"/"A.2" AI-likely informational alternatives (templates in
  serp_vocab.yml ai_alternative_templates);
- autocomplete fallback variants;
- "S"-label situational (conversational) query probes (Spec:
  seo_geo_deferred_spec_v1.md#T.5): 6+-word situation-style queries that
  measure the AI Overview trigger rate by query length on the client's
  own market. Probe results feed ONLY the AIO trigger-rate analysis
  (aio_trigger_analysis) and the AI Overview citation rows — never
  organic metrics, intent verdicts, volatility, or the competitor
  handoff (T.5.3).

All functions are pure given their arguments; serp_audit.py binds them to
its config globals so runtime-mode overrides and tests keep working.
"""
import json
import logging
import os
import re
import time
from datetime import datetime


def delocalise_keyword(base_keyword, city):
    """Strip local suffixes and 'best/top' prefixes from a keyword.

    Shared by the A.1/A.2 informational alternatives and the "S"-label
    situational probe templates — both build conversational queries
    around the de-localised core phrase.
    """
    q = (base_keyword or "").strip()
    if not q:
        return ""

    city_lower = (city or "").strip().lower()
    base = q
    base_lower = base.lower()

    # Remove obvious local suffixes (often suppress AI overviews).
    directional_city_pattern = rf"\s+in\s+(north|south|east|west)\s+{re.escape(city_lower)}$"
    if re.search(directional_city_pattern, base_lower):
        base = re.sub(directional_city_pattern, "", base, flags=re.I).strip()
        base_lower = base.lower()
    directional_city_pattern_2 = rf"\s+(north|south|east|west)\s+{re.escape(city_lower)}$"
    if re.search(directional_city_pattern_2, base_lower):
        base = re.sub(directional_city_pattern_2, "", base, flags=re.I).strip()
        base_lower = base.lower()

    for suffix in (f" in {city_lower}", f" near {city_lower}", f" {city_lower}"):
        if base_lower.endswith(suffix):
            base = base[:len(base) - len(suffix)].strip()
            base_lower = base.lower()
            break

    return re.sub(r"^(best|top)\s+", "", base, flags=re.I).strip()


def is_service_like(keyword, service_tokens, city=None):
    """Return True when the (de-localised) keyword names a therapy service.

    Single source of the "service-like" definition, shared by
    ``ai_query_alternatives`` (AI-likely alternatives) and the hyper-local
    pivot gate in ``feasibility.generate_hyper_local_pivot``. The token list
    is editorial → serp_vocab.yml ``service_like_tokens``; never hardcode a
    parallel list. Substring match on the de-localised keyword, mirroring the
    original inline check.

    Geographic (neighbourhood) pivots only substitute proximity for authority
    on service-intent queries; informational queries ("how does birth order
    affect personality") must not be gated as service-like.

    Spec: seo_geo_review_20260704.md (chip B, B.1.a).
    """
    q = (keyword or "").strip()
    if not q:
        return False
    base = delocalise_keyword(q, city) if city else q
    base_lower = base.lower()
    return any(tok in base_lower for tok in service_tokens)


def ai_query_alternatives(base_keyword, city, service_tokens, templates_map):
    """Generate two AI-likely informational alternatives for a base query.

    Token list and question templates are editorial → serp_vocab.yml
    (seo_geo_review C.4): service_tokens = service_like_tokens,
    templates_map = ai_alternative_templates.
    """
    q = (base_keyword or "").strip()
    if not q:
        return []

    base = delocalise_keyword(q, city)
    base_lower = base.lower()
    if not base:
        return []

    if is_service_like(base, service_tokens):
        templates = templates_map["service"]
        topic = base
    elif base_lower.startswith("help with "):
        templates = templates_map["help_with"]
        topic = base[10:].strip()
    else:
        templates = templates_map["default"]
        topic = base
    alternatives = [t.format(base=base, topic=topic, city=city) for t in templates]

    out = []
    seen = set()
    for candidate in alternatives:
        normalized = candidate.strip()
        key = normalized.lower()
        if normalized and key != q.lower() and key not in seen:
            out.append(normalized)
            seen.add(key)
    return out


def autocomplete_query_variants(keyword, city):
    """Build fallback autocomplete queries for long/local phrases."""
    q = (keyword or "").strip()
    variants = [q]

    city_lower = (city or "").strip().lower()
    lowered = q.lower()
    if city_lower:
        for suffix in (f" in {city_lower}", f" {city_lower}"):
            if lowered.endswith(suffix):
                trimmed = q[:len(q) - len(suffix)].strip()
                if trimmed:
                    variants.append(trimmed)

    for prefix in ("help with ", "help for ", "need help with "):
        if lowered.startswith(prefix):
            core = q[len(prefix):].strip()
            if core:
                variants.append(core)
                variants.append(f"{core} help")
            break

    deduped = []
    seen = set()
    for item in variants:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


# --- SITUATIONAL (CONVERSATIONAL) QUERY PROBES ---
# Spec: seo_geo_deferred_spec_v1.md#T.5.

def situational_template_probes(base_keyword, templates, city):
    """Fill the editorial situational_templates for one root keyword.

    Templates live in serp_vocab.yml (editorial); placeholders are
    {base} (de-localised keyword), {topic} (subject after "help with ",
    else the base), and {city}. Spec: seo_geo_deferred_spec_v1.md#T.5.
    """
    base = delocalise_keyword(base_keyword, city)
    if not base:
        return []
    if base.lower().startswith("help with "):
        topic = base[10:].strip() or base
    else:
        topic = base

    out = []
    seen = set()
    for template in templates:
        try:
            candidate = template.format(base=base, topic=topic, city=city).strip()
        except (KeyError, IndexError):
            logging.warning(
                f"situational_templates entry has an unknown placeholder, skipping: {template!r}"
            )
            continue
        key = candidate.lower()
        if candidate and key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def generate_situational_probes(ordered_keywords, paa_rows, max_total,
                                per_keyword, templates, city, min_words=6):
    """Build the "S"-label probe list, capped by both config limits.

    Sources per root keyword, in priority order (T.5.2):
      a. the keyword's own PAA questions of min_words+ words, verbatim
         (they are already conversational), External Locus ones first;
      b. editorial templates from serp_vocab.yml situational_templates.

    Returns a list of {"query", "source_keyword", "probe_source"} dicts.
    Spec: seo_geo_deferred_spec_v1.md#T.5.
    """
    probes = []
    seen_queries = set()
    for kw in ordered_keywords:
        if len(probes) >= max_total:
            break
        kw_paa = [r for r in paa_rows if r.get("Source_Keyword") == kw]
        candidates = []
        for prefer_external in (True, False):
            for row in kw_paa:
                question = str(row.get("Question") or "").strip()
                if not question or len(question.split()) < min_words:
                    continue
                is_external = row.get("Intent_Tag") == "External Locus"
                if is_external != prefer_external:
                    continue
                candidates.append((question, "paa"))
        for template_query in situational_template_probes(kw, templates, city):
            candidates.append((template_query, "template"))

        added = 0
        for query, probe_source in candidates:
            if added >= per_keyword or len(probes) >= max_total:
                break
            key = query.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            probes.append({
                "query": query,
                "source_keyword": kw,
                "probe_source": probe_source,
            })
            added += 1
    return probes


def situational_keyword_order(root_keywords, keywords_mode, analysis_path):
    """Order root keywords for probing.

    "priority" mode follows the strategic_flags.content_priorities order
    from the most recent analysis JSON (the same source A.1/A.2 priority
    selection uses); keywords absent from that list — and "all" mode —
    keep the input CSV order. Spec: seo_geo_deferred_spec_v1.md#T.5
    (gate D-1: top keywords get probed first under the run cap).
    """
    ordered = []
    if keywords_mode == "priority" and analysis_path and os.path.exists(analysis_path):
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            priorities = data.get("strategic_flags", {}).get("content_priorities", [])
            for item in priorities:
                kw = (item.get("keyword") or "").strip()
                if kw in root_keywords and kw not in ordered:
                    ordered.append(kw)
        except Exception as exc:
            logging.warning(f"Situational probe priority order unavailable: {exc}")
    for kw in root_keywords:
        if kw not in ordered:
            ordered.append(kw)
    return ordered


def execute_situational_probes(jobs, run_id, fetch_probe, client_domain,
                               request_delay=0.0):
    """Execute prepared probe jobs and return (probe_rows, citation_rows).

    - probe_rows: one record per executed probe (Query_Label "S") for the
      analysis JSON's situational_probes list — feeds ONLY the AIO
      trigger-rate analysis (aio_trigger_analysis).
    - citation_rows: AI Overview citations observed on probe SERPs,
      shaped like the ai_overview_citations rows (Query_Label "S").

    fetch_probe(query, run_id, probe_index) performs exactly one paid
    SerpAPI call (serp_audit.fetch_situational_probe). This pass touches
    no other surface: no organic rows, no SQLite writes (volatility
    unaffected), no maps calls, no enrichment (T.5.3).
    Spec: seo_geo_deferred_spec_v1.md#T.5.
    """
    client_domain_lower = (client_domain or "").lower()

    probe_rows = []
    citation_rows = []
    for idx, job in enumerate(jobs, start=1):
        print(f"  [Probe S {idx}/{len(jobs)}] '{job['query']}' (from '{job['source_keyword']}')")
        results = fetch_probe(job["query"], run_id, idx)

        common = {
            "Run_ID": run_id,
            "Created_At": datetime.now().isoformat(),
            "Root_Keyword": job["source_keyword"],
            "Source_Keyword": job["source_keyword"],
            "Query_Label": "S",
            "Executed_Query": job["query"],
        }

        has_aio = False
        client_cited = False
        if results:
            aio_data = results.get("ai_overview") or {}
            has_aio = bool(aio_data)
            # Citations only when present directly in the single response —
            # no token follow-up call is made for probes (cap discipline).
            for citation in (aio_data.get("citations") or aio_data.get("references") or []):
                if not isinstance(citation, dict):
                    continue
                link = citation.get("link")
                citation_rows.append({
                    **common,
                    "Title": citation.get("title"),
                    "Link": link,
                    "Source": citation.get("source"),
                })
                if link and client_domain_lower and client_domain_lower in str(link).lower():
                    client_cited = True

        probe_rows.append({
            **common,
            "Probe_Source": job["probe_source"],
            "Word_Count": len(job["query"].split()),
            "Has_AI_Overview": has_aio,
            "Client_Cited": client_cited,
            "Fetch_Failed": results is None,
        })
        time.sleep(request_delay)

    return probe_rows, citation_rows
