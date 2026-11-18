"""pivot_pass.py — the neighbourhood-pivot decision for one run.

`serp_audit` used to decide every keyword's pivot inside the SERP fetch loop,
one keyword at a time, and so called `feasibility.generate_hyper_local_pivot`
with neither `serp_intent` nor `entity_distribution`: `keyword_profiles` does
not exist until every keyword has been fetched. The function documents the
measured verdict as outranking the keyword-token guess, and in the pipeline
there was no verdict to outrank it with — while the standalone
`run_feasibility.py` passed both. Two entry points, the same SERP, different
pivots.

This module is the pass that runs between the fetch loop and the pivot SERP
fetch that consumes its output, so both entry points decide on the same
measured facts.

Spec: docs/review_2026-11-04/PLAN_Y6_the_pipeline_agrees_with_the_run.md
"""
from __future__ import annotations

import logging

import brief_data_extraction
import feasibility

logger = logging.getLogger(__name__)


def build_pivot_profiles(all_metrics, all_organic, all_paa, all_local_pack,
                         all_ai_citations, all_serp_modules, keywords,
                         config, client_domain):
    """`keyword_profiles` for the pivot decision, from the label-A rows.

    Through the one shared builder
    `brief_data_extraction.build_keyword_profiles`, which the end of the run
    calls again over the complete data. Reimplementing "what this SERP is"
    here is how two definitions of it come to disagree (P32).

    A build failure is logged and returns `{}`: every caller treats a missing
    profile as "not measured", which is the state the pivot had before this
    pass existed, so a failure degrades to that rather than stopping a run
    that has already paid for its SERPs (P1/P2).

    The data passed is a subset of the dict the end of the run passes — the
    n-grams, the strategic recommendations and the display phrases do not
    exist yet at this point in the pipeline. It is the subset that determines
    the two fields the pivot reads: `serp_intent` is computed from the label-A
    organic rows, the local pack, the client domain and `known_brands`, and
    `entity_distribution` is counted off those same organic rows. A field the
    pivot does not read may differ between this profile and the run's final
    one; the two fields it does read cannot.
    """
    try:
        # The builder warns per keyword about duplicate and repeated-rank
        # rows in `entity_distribution`, and the end of the run calls it
        # again over the complete data: without this the operator sees every
        # such line twice and a reader counting them double-counts the
        # evidence (cold review of chunk Y6, finding 10). The run's own build
        # still prints them.
        _builder_log = logging.getLogger(brief_data_extraction.__name__)
        _was = _builder_log.level
        _builder_log.setLevel(logging.ERROR)
        try:
            return brief_data_extraction.build_keyword_profiles(
                {
                    "overview": all_metrics,
                    "organic_results": all_organic,
                    "paa_questions": all_paa,
                    "local_pack_and_maps": all_local_pack,
                    "ai_overview_citations": all_ai_citations,
                    "serp_modules": all_serp_modules,
                    "analysed_keywords": list(keywords or []),
                },
                config, client_domain=client_domain)
        finally:
            _builder_log.setLevel(_was)
    except ValueError:
        # A malformed `play_routing.yml` is a HARD error by design — the
        # builder raises so a broken editorial file cannot route every
        # keyword to an accidental default. Degrading it to "no profiles"
        # would hide exactly that (P32, same review).
        raise
    except Exception as exc:
        logger.warning(
            "Pivot profiles could not be built (%s) — every pivot this run is "
            "decided on the keyword text alone, and the strategy paragraphs "
            "will not name the SERP composition.", exc)
        return {}


def decide_pivots(pending, profiles, *, location, neighborhoods,
                  pivotable_intents, pivot_fetch, storage, run_id,
                  log=print):
    """``(feasibility rows, pivot fetch jobs)`` for one run's label-A keywords.

    *pending* is one entry per keyword from the fetch loop, carrying the
    feasibility figures the Moz batch produced, the DA provenance and the
    service-token guess. *profiles* is `build_pivot_profiles`' result; a
    keyword missing from it is decided exactly as it was before this pass
    existed, on the token guess alone, which the refusal text already names.

    *storage* is `None` when enrichment is off, so nothing is written.
    """
    rows: list[dict] = []
    jobs: list[tuple[str, str, str]] = []
    measured = 0
    for entry in pending or []:
        feas = entry["feas"]
        profile = profiles.get(entry["keyword"]) or {}
        serp_intent = profile.get("serp_intent")
        pivot = feasibility.generate_hyper_local_pivot(
            primary_keyword=entry["keyword"],
            non_profit_location=location,
            feasibility_results={
                "status": feas["feasibility_status"],
                "avg_competitor_da": feas["avg_serp_da"],
            },
            neighborhoods=neighborhoods,
            is_service_like=entry["is_service_like"],
            # The two measured inputs, the same ones `run_feasibility.py`
            # passes. Absent they are `None`, the honest "not measured" the
            # function already handles.
            serp_intent=serp_intent,
            entity_distribution=profile.get("entity_distribution"),
            pivotable_intents=pivotable_intents,
        )
        # Counted off the basis the gate reported, not off the presence of
        # a `serp_intent` block: `compute_serp_intent` always returns a dict,
        # with `primary_intent` None when too few of the ten URLs classified,
        # so a truthiness test reported "N of N decided on a measured SERP
        # intent" in exactly the degraded case this line exists to make loud
        # (cold review of chunk Y6, finding 1).
        if str(pivot.get("gate_source") or "").startswith("serp_intent"):
            measured += 1

        row = {
            **feas,
            **pivot,
            "Keyword": entry["keyword"],
            "Query_Label": "A",
            "da_provider": "moz",
            "client_da_source": entry["client_da_source"],
            "Client_In_Local_Pack": None,
        }
        rows.append(row)

        # The row IS the assessment: one argument, so a field added to it
        # cannot be forgotten here (F9).
        if storage is not None:
            storage.save_feasibility_from_row(
                row, run_id, "A",
                pivot_variants=pivot.get("all_variants", []))

        log(f"  [Feasibility] {entry['keyword']}: "
            f"{feasibility.status_label(feas['feasibility_status'], bare_icon=True)} "
            f"{feas['feasibility_status']} "
            f"(gap={feas['gap']}, avg_da={feas['avg_serp_da']})")

        if (feas["feasibility_status"] == "Low Feasibility"
                and pivot_fetch and pivot.get("suggested_keyword")):
            jobs.append((pivot["suggested_keyword"], entry["keyword"], "P"))
            log(f"  [Pivot queued] → {pivot['suggested_keyword']}")

    if pending:
        # P2 — how many pivots were decided on a measured SERP rather than on
        # the keyword's words, so a run where the profiles failed to build
        # does not read like one where they did.
        log(f"  [Pivot gate] {measured} of {len(pending)} keyword(s) decided "
            f"on a measured SERP intent; the rest on the keyword text.")
    return rows, jobs
