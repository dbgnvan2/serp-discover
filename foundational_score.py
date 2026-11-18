#!/usr/bin/env python3
"""foundational_score.py — foundational (transferable) GEO readiness score.

Spec: yoast_geo_upgrade_spec_v1.md#Y.12 (decision gate Y-D9).

The highest-ROI GEO work is the layer that lifts the client on *every* engine —
crawlability / extractable structure / schema, and off-site brand authority —
yet the tool had no single view of it. AIVI (Y.6) measures the per-engine
*outcome* (a lagging indicator that varies per engine); this measures the
transferable *inputs* the client controls (a leading indicator that does not).
Separating them tells the client "fix these foundations first, they pay off
everywhere," which the empirical cross-engine evidence identifies as the correct
first move (see the spec's "Empirical basis" §3).

The score is **engine-agnostic by construction** and is presented FIRST in the
report, ahead of the per-engine AIVI.

Three sub-scores, each 0–100, aggregated from EXISTING data only (NO new
external calls, principle 1 — Python computes, nothing is LLM-derived):

  * **accessibility** — from ``keyword_profiles[*].extractability`` (question
    headings, answer-at-top / intro length, FAQ presence) and any crawl /
    JS-gating flags already captured.
  * **structure** — from the schema @types on the CLIENT'S OWN page
    (``keyword_profiles[*].schema_signals.client_page``) vs the
    ``schema_recommendations.yml`` contexts the client could be marking up.
    ``None`` (n/a) with a stated reason when the client has no enriched page
    in any top-10 — never a score read off its competitors' markup (D3.13).
  * **authority** — from the Y.7 brand-mention leaderboard: the client's
    off-site mention frequency across third-party answers (the signal reported
    to predict AI citation ~3× better than backlinks).

A sub-score whose inputs are entirely absent is reported ``None`` (n/a) and is
EXCLUDED from the weighted mean — weights renormalise over the present
sub-scores, it is NEVER counted as 0 (principle 3, Spec Y.12.2). Weights come
from ``config.yml`` ``foundational.weights`` (documented); malformed/missing
weights fall back to equal with a warning.

Each sub-score lists its top 2–3 concrete gaps pulled from the EXISTING
``strategic_flags.geo_alerts`` / ``schema_recommendations.yml`` sources — the
score is actionable, not just a number, and the gap strings are the existing
editorial ones, never newly invented (Spec Y.12.3).

Persistence: a ``foundational_score`` SQLite table (``run_ts, score,
accessibility, structure, authority, weights_json``) so it is trendable
(principle 5). All timestamps UTC.
"""
from __future__ import annotations

import json
import logging

import ai_visibility_messages as av_messages
import storage
import db_connect

logger = logging.getLogger(__name__)

FOUNDATIONAL_TABLE = "foundational_score"

SUBSCORES = ("accessibility", "structure", "authority")

#: Bumped whenever a sub-score changes what it measures, so a trend does not
#: print a definition change as a readiness delta (cold-review finding 6).
#: 1 = structure read ``schema_signals.schema_type_counts``, an aggregate over
#: the whole enriched top-10 (so a client absent from every top-10 scored on
#: its competitors' markup). 2 = structure reads the client's own page only
#: (D3.13).
DEFINITION_VERSION = 2

#: Recommended default: equal thirds. Only the fallback when config supplies no
#: (valid) weights — the score is always computed from the resolved weights.
DEFAULT_WEIGHTS = {"accessibility": 1 / 3, "structure": 1 / 3, "authority": 1 / 3}

#: How many concrete gaps to surface per sub-score (Spec Y.12.3: "top 2–3").
MAX_GAPS = 3


def resolve_weights(foundational_config: dict | None) -> dict:
    """Resolve the three sub-score weights from config, falling back to equal.

    A missing block, a non-numeric or negative weight, or weights summing to
    zero all fall back to equal thirds with a logged warning. Weights are
    normalised to sum to 1 across the three sub-scores; unknown keys ignored.
    """
    raw = (foundational_config or {}).get("weights")
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("foundational.weights is not a mapping — using equal weights.")
        return dict(DEFAULT_WEIGHTS)
    weights: dict[str, float] = {}
    for sub in SUBSCORES:
        value = raw.get(sub)
        try:
            weights[sub] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "foundational.weights.%s is missing or non-numeric — using equal weights.",
                sub)
            return dict(DEFAULT_WEIGHTS)
        if weights[sub] < 0:
            logger.warning("foundational.weights.%s is negative — using equal weights.", sub)
            return dict(DEFAULT_WEIGHTS)
    total = sum(weights.values())
    if total <= 0:
        logger.warning("foundational.weights sum to zero — using equal weights.")
        return dict(DEFAULT_WEIGHTS)
    return {sub: weights[sub] / total for sub in SUBSCORES}


# ---------------------------------------------------------------------------
# Sub-score computation (deterministic; from existing collected data only)
# ---------------------------------------------------------------------------

def _client_extractability_pages(analysis_data: dict) -> list[dict]:
    """Collect the client's own extractability page rows across keyword profiles."""
    pages: list[dict] = []
    for profile in (analysis_data.get("keyword_profiles") or {}).values():
        ext = (profile or {}).get("extractability") or {}
        if not ext.get("data_available"):
            continue
        client_page = ext.get("client_page")
        if client_page:
            pages.append(client_page)
    return pages


def compute_accessibility(analysis_data: dict) -> tuple[float | None, list[str]]:
    """Accessibility/extractability sub-score (0–100) + its top gaps.

    Reads ``keyword_profiles[*].extractability`` (Spec T.2). The score rewards,
    for the client's own ranking pages, the presence of question-shaped
    headings, a substantial answer-at-top (intro text), and an FAQ block — the
    signals an AI answer engine needs to lift a complete answer. When NO keyword
    profile carries extractability data (analysis JSON predates capture) the
    sub-score is ``None`` (n/a), never 0 (principle 3).

    Gaps are drawn from the EXISTING ``strategic_flags.geo_alerts`` details
    (Spec Y.12.3) — the client-ranks-but-not-cited reformat alerts — plus, when
    no alerts exist, generic-but-existing extractability observations phrased
    from the captured page signals (no new editorial strings invented).
    """
    pages = _client_extractability_pages(analysis_data)
    geo_alerts = ((analysis_data.get("strategic_flags") or {}).get("geo_alerts")) or []

    if not pages and not geo_alerts:
        # No captured extractability signal at all — cannot measure.
        # geo_alerts alone (without page rows) still lets us report gaps but not
        # a defensible score, so treat as n/a unless we have page signals.
        return None, []

    gaps = _geo_alert_gaps(geo_alerts)

    if not pages:
        # We have alerts but no client extractability page rows: report the
        # alerts as the (only) signal and score conservatively low — the client
        # ranks but is not cited, the exact deficit this sub-score measures.
        score = 25.0 if geo_alerts else None
        return score, gaps

    # Per-client-page readiness fraction: heading-shaped, answer-at-top, FAQ.
    per_page: list[float] = []
    for page in pages:
        signals = 0
        if (page.get("question_heading_count") or 0) > 0:
            signals += 1
        if (page.get("intro_text_length") or 0) >= 200:
            signals += 1
        if page.get("faq_present"):
            signals += 1
        per_page.append(signals / 3.0)
    score = round(100.0 * sum(per_page) / len(per_page), 2)
    return score, gaps


def compute_structure(analysis_data: dict, schema_recommendations: list[dict] | None
                      ) -> tuple[float | None, list[str], str | None]:
    """Structure/schema sub-score (0–100) + its top gaps.

    Compares the schema.org @types on the CLIENT'S OWN pages
    (``keyword_profiles[*].schema_signals.client_page``) against the schema
    contexts the client could be marking up (``schema_recommendations.yml``).
    Score = covered recommended types / total recommended types. When the
    client has no enriched page in any keyword's top-10 the sub-score is
    ``None`` (n/a), never 0 — nothing of the client's was measured.

    D-M-04: this read ``schema_signals.schema_type_counts``, an aggregate over
    the whole enriched top-10, so a client absent from every top-10 scored
    66.67 on its COMPETITORS' markup and the "foundational readiness" section
    reported it as the client's own. Spec: D3.13.

    Gaps are the EXISTING ``schema_recommendations.yml`` labels for the
    recommended types not yet observed (Spec Y.12.3 — sourced from schema recs,
    not new strings). When the client is unmeasured the gaps are every
    recommended type: they are recommendations, not measurements, and the
    client least visible in the SERPs is exactly the one that needs them
    (cold-review finding 6).

    Returns ``(score, gaps, reason)``. *reason* is ``None`` when a score was
    computed, and otherwise says WHICH unmeasured state this is — "no schema
    contexts are configured" and "the client has no page in any top-10" are
    two different facts and both used to print a bare ``n/a`` (cold-review
    finding 6; the same defect `feasibility_messages.yml` and
    `gsc_messages.yml` exist to prevent). The words are editorial and live in
    ``ai_visibility_messages.yml``.
    """
    recs = schema_recommendations or []
    recommended_types: dict[str, str] = {}  # schema type -> rec label
    for rec in recs:
        label = rec.get("label") or rec.get("context") or ""
        for stype in rec.get("schema_types") or []:
            recommended_types.setdefault(str(stype), label)
    if not recommended_types:
        return None, [], av_messages.line(
            "foundational_structure_no_recs",
            "no schema contexts are configured in schema_recommendations.yml")

    observed_types: set[str] = set()
    client_measured = False
    for profile in (analysis_data.get("keyword_profiles") or {}).values():
        signals = (profile or {}).get("schema_signals") or {}
        if not signals.get("data_available"):
            continue
        client_page = signals.get("client_page")
        if not client_page:
            continue
        client_measured = True
        for stype in client_page.get("schema_types") or []:
            observed_types.add(str(stype))

    if not client_measured:
        # The client is in no enriched top-10: its markup was never fetched.
        # The recommendations still stand, so they are still reported as gaps
        # — an unmeasured client is the one that needs them most.
        return None, _recommendation_gaps(recommended_types, recommended_types), \
            av_messages.line(
                "foundational_structure_no_client_page",
                "the client has no enriched page in any keyword's top-10 this "
                "run, so its own markup was never fetched")

    covered = [t for t in recommended_types if t in observed_types]
    missing = [t for t in recommended_types if t not in observed_types]
    score = round(100.0 * len(covered) / len(recommended_types), 2)

    # Gaps: the existing rec labels for missing recommended schema types.
    return score, _recommendation_gaps(recommended_types, missing), None


def _recommendation_gaps(recommended_types: dict[str, str],
                         wanted) -> list[str]:
    """The EXISTING schema-recommendation labels, phrased as gaps (Y.12.3).

    No new editorial strings: the label comes from
    ``schema_recommendations.yml``.
    """
    gaps: list[str] = []
    seen: set[str] = set()
    for stype in wanted:
        label = recommended_types.get(stype) or ""
        gap = f"Add {stype} markup ({label})" if label else f"Add {stype} markup"
        if gap not in seen:
            seen.add(gap)
            gaps.append(gap)
        if len(gaps) >= MAX_GAPS:
            break
    return gaps


def compute_authority(leaderboards: dict | None,
                      client_name_patterns: list[str] | None = None
                      ) -> tuple[float | None, list[str]]:
    """Off-site authority sub-score (0–100) + its top gaps.

    Uses the Y.7 brand-mention leaderboards (per engine). Off-site authority is
    proxied by the client's own answer-mention frequency across third-party AI
    answers — the "brand mentions across trusted third-party sources" signal the
    empirical basis reports as ~3× more predictive of citation than backlinks.

    Score = client mention share of the leader's mention count, across engines
    (client mentions / top-brand mentions), 0–100. ``None`` (n/a) when NO
    leaderboard has any rows (no answer data yet). The gaps name the top rival
    brands the AI names in the client's place (from the leaderboard itself,
    existing brand strings — no new editorial content).
    """
    if not leaderboards:
        return None, []

    client_total = 0
    leader_total = 0
    have_rows = False
    rival_counts: dict[str, int] = {}
    for lb in leaderboards.values():
        rows = (lb or {}).get("rows") or []
        if rows:
            have_rows = True
        leader_here = 0
        for row in rows:
            count = int(row.get("mention_count") or 0)
            leader_here = max(leader_here, count)
            if row.get("is_client"):
                client_total += count
            else:
                rival_counts[row["brand"]] = rival_counts.get(row["brand"], 0) + count
        leader_total += leader_here

    if not have_rows:
        return None, []

    if leader_total <= 0:
        score = 0.0
    else:
        score = round(min(100.0, 100.0 * client_total / leader_total), 2)

    # Gaps: the top rival brands the AI names instead of the client — existing
    # brand strings from the leaderboard, phrased as an outreach/authority gap.
    gaps: list[str] = []
    for brand, _count in sorted(rival_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        gaps.append(
            f"Build third-party authority: AI names '{brand}' in the client's place"
        )
        if len(gaps) >= MAX_GAPS:
            break
    return score, gaps


def _geo_alert_gaps(geo_alerts: list[dict]) -> list[str]:
    """Top gaps from the EXISTING strategic_flags.geo_alerts details (Y.12.3).

    Returns the alert ``detail`` strings verbatim (existing editorial content),
    capped at MAX_GAPS. Never fabricates a string.
    """
    gaps: list[str] = []
    for alert in geo_alerts or []:
        detail = str((alert or {}).get("detail") or "").strip()
        keyword = str((alert or {}).get("keyword") or "").strip()
        if not detail:
            continue
        gap = f"[{keyword}] {detail}" if keyword else detail
        gaps.append(gap)
        if len(gaps) >= MAX_GAPS:
            break
    return gaps


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_foundational_score(analysis_data: dict,
                               schema_recommendations: list[dict] | None,
                               leaderboards: dict | None,
                               weights: dict | None = None,
                               client_name_patterns: list[str] | None = None
                               ) -> dict:
    """Aggregate the three sub-scores into a 0–100 foundational readiness score.

    Returns::

        {
          "score": float | None,          # 0–100, or None — nothing measured
          "score_reason": str | None,     # WHY there is no composite
          "subscores": {sub: value|None}, # value 0–100 or None (n/a)
          "gaps": {sub: [str, ...]},      # top 2–3 concrete gaps per sub-score
          "weights_used": {sub: float},
          "excluded": [sub, ...],         # n/a sub-scores excluded from the mean
          "reasons": {sub: str|None},     # WHY an n/a sub-score is n/a
          "definition_version": int,      # what the sub-scores measured
        }

    n/a sub-scores are EXCLUDED and the weights of the present sub-scores are
    renormalised so the score stays 0–100 (Spec Y.12.2) — never counted as 0.
    With NO sub-score measured, or with every configured weight at zero, the
    score is ``None`` and ``score_reason`` says which: a 0.0 there was a
    measurement nobody made, and it was written to the trend table (review
    chunk Y3).
    Deterministic given inputs (Spec Y.12.1).
    """
    weights = weights or dict(DEFAULT_WEIGHTS)

    accessibility, acc_gaps = compute_accessibility(analysis_data)
    structure, str_gaps, str_reason = compute_structure(
        analysis_data, schema_recommendations)
    authority, auth_gaps = compute_authority(leaderboards, client_name_patterns)

    subscores: dict[str, float | None] = {
        "accessibility": accessibility,
        "structure": structure,
        "authority": authority,
    }
    gaps = {
        "accessibility": acc_gaps,
        "structure": str_gaps,
        "authority": auth_gaps,
    }

    present = {sub: v for sub, v in subscores.items() if v is not None}
    excluded = [sub for sub in SUBSCORES if subscores[sub] is None]

    weight_sum = sum(weights.get(sub, 0.0) for sub in present)
    score: float | None
    score_reason: str | None = None
    if not present:
        # Nothing was measured, so there is no composite. 0.0 here was printed
        # as "0.0/100" and written to the trend table as a real row, so the
        # next run's Δ was measured against a number nobody measured — the
        # thing this function's own docstring forbids for a single axis
        # (P1/P6, review chunk Y3).
        score = None
        score_reason = av_messages.line(
            "foundational_no_subscore",
            "none of the three sub-scores could be measured this run")
    elif weight_sum <= 0:
        # A configuration error, not a measurement: the axes were measured and
        # the weights discard all of them. Which error it is matters — telling
        # the owner "every weight is zero" when they weighted one axis that
        # happened to be unmeasurable this run is false, and `resolve_weights`
        # makes the all-zero case unreachable from config anyway (cold review
        # of chunk Y3).
        score = None
        if all(float(weights.get(sub, 0.0) or 0.0) <= 0 for sub in SUBSCORES):
            score_reason = av_messages.line(
                "foundational_no_weight",
                "every configured weight is zero, so the weighted mean has no "
                "basis")
        else:
            _measured = ", ".join(_SUB_LABELS.get(sub, sub)
                                  for sub in SUBSCORES if sub in present)
            score_reason = av_messages.line(
                "foundational_measured_axes_unweighted",
                "the only sub-score(s) measured this run ({measured}) carry "
                "zero weight, so there is nothing to average",
                measured=_measured)
    else:
        score = round(sum(
            max(0.0, min(100.0, present[sub])) * (weights.get(sub, 0.0) / weight_sum)
            for sub in present
        ), 1)

    return {
        "score": score,
        "score_reason": score_reason,
        "subscores": subscores,
        "gaps": gaps,
        "reasons": {"structure": str_reason},
        "definition_version": DEFINITION_VERSION,
        "weights_used": {sub: weights.get(sub, 0.0) for sub in SUBSCORES},
        "excluded": excluded,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def init_foundational_table(db_path: str) -> None:
    with db_connect.connection(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {FOUNDATIONAL_TABLE} (
            run_ts        TEXT,
            score         REAL,
            accessibility REAL,
            structure     REAL,
            authority     REAL,
            weights_json  TEXT,
            definition_version INTEGER
        )''')
        # Through `storage._add_missing_columns`, so a locked or missing table
        # raises instead of counting as a finished migration (cold review of
        # chunk Y5): a pre-D3b row predates the column and reads as
        # definition 1, which is what it was.
        storage._add_missing_columns(
            conn, FOUNDATIONAL_TABLE,
            [("definition_version", "INTEGER")])
        conn.commit()


def save_foundational_score(db_path: str, run_ts: str, result: dict) -> None:
    init_foundational_table(db_path)
    subs = result.get("subscores", {})
    with db_connect.connection(db_path) as conn:
        conn.execute(f"DELETE FROM {FOUNDATIONAL_TABLE} WHERE run_ts = ?",
                     (run_ts,))   # idempotent per run_ts — P8
        conn.execute(
            f"""INSERT INTO {FOUNDATIONAL_TABLE}
                (run_ts, score, accessibility, structure, authority,
                 weights_json, definition_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_ts, result.get("score"),
             subs.get("accessibility"), subs.get("structure"), subs.get("authority"),
             json.dumps(result.get("weights_used", {})),
             int(result.get("definition_version") or DEFINITION_VERSION)),
        )
        conn.commit()


def get_foundational_trend(db_path: str, limit: int = 5) -> list[dict]:
    """Per-run foundational score, oldest→newest (trendable, Spec Y.12.4)."""
    init_foundational_table(db_path)
    with db_connect.connection(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts, score, accessibility, structure, authority,
                       definition_version
                FROM {FOUNDATIONAL_TABLE}
                ORDER BY run_ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    trend = [
        {"run_ts": rt, "score": s, "accessibility": a, "structure": st,
         "authority": au, "definition_version": (dv if dv is not None else 1)}
        for rt, s, a, st, au, dv in rows
    ]
    trend.reverse()
    return trend


# ---------------------------------------------------------------------------
# Report section (rendered FIRST, ahead of per-engine AIVI)
# ---------------------------------------------------------------------------

_CAVEAT = (
    "*This is the transferable, do-first layer: unlike per-engine AIVI, "
    "improving accessibility, structure/schema, and off-site authority lifts "
    "the client on every AI engine at once. Fix these foundations before "
    "chasing any single engine.*"
)

_SUB_LABELS = {
    "accessibility": "Accessibility / extractability",
    "structure": "Structure / schema",
    "authority": "Off-site authority",
}


def _sub_cell(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def render_foundational_section(result: dict, trend: list[dict] | None = None
                                ) -> list[str]:
    """Render the foundational readiness section — presented FIRST (Spec Y.12.2).

    Shows the headline 0–100 score, the three sub-scores (n/a where excluded),
    the prior-run delta, and each sub-score's top 2–3 concrete gaps sourced from
    the existing geo_alerts / schema recommendations. Leads the report, ahead of
    per-engine AIVI, as the cross-platform priority.
    """
    out: list[str] = []
    out.append("## Foundational GEO readiness (cross-platform priority)")
    out.append(
        "A single 0–100 score for the transferable layer the client controls: "
        "technical accessibility / answer-extractability, clean structure and "
        "schema, and off-site brand authority. Weights are configurable "
        "(`foundational.weights`, default equal thirds); a sub-score with no "
        "captured data is shown `n/a` and excluded from the weighted mean, "
        "never counted as zero."
    )
    out.append("")

    subs = result.get("subscores", {})
    delta = "—"
    trend = trend or []
    if len(trend) >= 2:
        # A definition change is not a readiness delta (cold-review finding 6):
        # rows written before D3b hold a structure value read off the enriched
        # top-10, so the two scores measure different things and their
        # difference means nothing. Stated whether or not both scores are
        # present, because the incomparability is a fact about the two rows,
        # not about this run's score (cold review of chunk Y3).
        if trend[-1].get("definition_version", 1) \
                != trend[-2].get("definition_version", 1):
            delta = av_messages.line(
                "foundational_delta_definition_changed",
                "n/a — the structure sub-score changed definition since the "
                "prior run, so the two scores are not comparable")
        elif trend[-1].get("score") is not None \
                and trend[-2].get("score") is not None:
            delta = f"{trend[-1]['score'] - trend[-2]['score']:+.1f}"

    _score = result.get("score")
    if _score is None:
        line = av_messages.line(
            "foundational_score_not_measured",
            "**Foundational readiness: not measured** — {reason}",
            reason=(result.get("score_reason")
                    or "nothing was measured this run"))
        if delta != "—":
            # There is no Δ for THIS run, but a trend the reader can see may
            # still carry a note of its own (a definition change), and that
            # note is not replaced by this run being unmeasured.
            line = f"{line} (Δ prior {delta})"
        out.append(line)
    else:
        out.append(f"**Foundational readiness: {_score:.1f}/100** "
                   f"(Δ prior {delta})")
    out.append("")
    out.append("| Sub-score | Value |")
    out.append("|-----------|-------|")
    for sub in SUBSCORES:
        out.append(f"| {_SUB_LABELS[sub]} | {_sub_cell(subs.get(sub))} |")
    out.append("")
    # An n/a cell says nothing about WHICH unmeasured state it is, so the
    # reason is printed beside the table (cold-review finding 6).
    reasons = result.get("reasons", {}) or {}
    stated = False
    for sub in SUBSCORES:
        reason = reasons.get(sub)
        if subs.get(sub) is None and reason:
            out.append(av_messages.line(
                "foundational_subscore_reason", "*{label}: {reason}.*",
                label=_SUB_LABELS[sub], reason=reason))
            stated = True
    if stated:
        out.append("")

    gaps = result.get("gaps", {}) or {}
    out.append("### Top gaps to fix first")
    any_gap = False
    for sub in SUBSCORES:
        sub_gaps = gaps.get(sub) or []
        if not sub_gaps:
            continue
        any_gap = True
        out.append(f"**{_SUB_LABELS[sub]}:**")
        for gap in sub_gaps:
            out.append(f"- {gap}")
        out.append("")
    if not any_gap:
        out.append(
            "*No concrete gaps surfaced from the current data (no geo_alerts, "
            "full schema coverage, and no rival authority gap). Re-run after the "
            "next crawl to refresh.*")
        out.append("")

    out.append(_CAVEAT)
    out.append("")
    return out
