#!/usr/bin/env python3
"""commodity_score.py — Query commodity / AI-absorption risk (D4 / AV.4).

Purpose: Score each tracked keyword by how commoditized its answer is — how
         easily a single AI paragraph could replace the whole SERP.
Spec:    discover-spec.md#D4 (AV.4)
Plan:    d2_d5_implementation_plan.md (AV.4)
Tests:   tests/test_commodity_score.py

Pure, deterministic read-side assembly from signals already on
``keyword_profiles`` + the run's ``organic_results`` — no new fetch, no LLM call
on the report path (reproducible given the snapshot + ``weights_json``):

  commodity = 100 * (w_sim·answer_similarity + w_hom·serp_homogeneity
                     + w_aio·aio_present  [+ w_llm·one_paragraph_answerable])

- ``answer_similarity`` — mean pairwise **token-set Jaccard** over the top-N
  result (title + snippet) texts for the keyword (from ``data["organic_results"]``,
  grouped by ``Root_Keyword``; degrades to ``top5_organic`` titles). Higher = the
  results all say the same thing = more commoditized. Deterministic (NOT
  embeddings) so the score reproduces — the D-D4a decision.
- ``serp_homogeneity`` — SERP concentration: top entity-type share
  (``entity_distribution``) blended with title-pattern dominance
  (``title_patterns``). A uniform SERP is more absorbable.
- ``aio_present`` — ``has_ai_overview`` (an AIO already IS the absorption).
- ``one_paragraph_answerable`` — OPTIONAL gated LLM probe, **OFF by default** on
  the deterministic report path; its weight is renormalised out (aivi-style).

Weights from ``config.yml commodity.weights`` (documented-default fallback +
warning, mirroring ``aivi.resolve_weights``). Bands low/medium/high. The
recommended action is routed through the existing ``recommended_play``
(extraction_play / deprioritize), never a parallel string. Persisted to the
``commodity_score`` table, built like ``ai_aio_exposure``.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

COMMODITY_TABLE = "commodity_score"
SOURCE = "google"

#: D4 default composite weights — used ONLY when config supplies no valid value.
DEFAULT_WEIGHTS = {
    "answer_similarity": 0.4,
    "serp_homogeneity": 0.3,
    "aio_present": 0.2,
    "one_paragraph_answerable": 0.1,
}
DEFAULT_TOP_N = 5
DEFAULT_BAND_MEDIUM = 40.0   # < medium → low
DEFAULT_BAND_HIGH = 70.0     # >= high  → high
_WEIGHT_KEYS = tuple(DEFAULT_WEIGHTS)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# Config resolution (mirrors aivi.resolve_weights)
# ---------------------------------------------------------------------------

def resolve_weights(cfg: dict | None) -> dict:
    """Resolve the composite weights from ``config.yml commodity.weights``.

    A missing block, a non-numeric/negative weight, or weights summing to zero all
    fall back to the documented defaults with a logged warning; the result is
    normalised to sum 1 over the four keys (Spec: D4 — config-driven, like aivi).
    """
    raw = ((cfg or {}).get("commodity") or {}).get("weights")
    if raw is not None and not isinstance(raw, dict):
        logger.warning("commodity.weights is not a mapping — using default weights.")
        raw = None
    raw = raw or {}
    weights: dict[str, float] = {}
    for key in _WEIGHT_KEYS:
        value = raw.get(key, DEFAULT_WEIGHTS[key])
        try:
            weights[key] = float(value)
        except (TypeError, ValueError):
            logger.warning("commodity.weights.%s non-numeric — using defaults.", key)
            return dict(DEFAULT_WEIGHTS)
        if weights[key] < 0:
            logger.warning("commodity.weights.%s negative — using defaults.", key)
            return dict(DEFAULT_WEIGHTS)
    total = sum(weights.values())
    if total <= 0:
        logger.warning("commodity.weights sum to zero — using defaults.")
        return dict(DEFAULT_WEIGHTS)
    return {k: weights[k] / total for k in _WEIGHT_KEYS}


def _resolve_top_n(cfg: dict | None) -> int:
    raw = ((cfg or {}).get("commodity") or {}).get("top_n_results", DEFAULT_TOP_N)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TOP_N
    return n if n >= 2 else DEFAULT_TOP_N


def _resolve_bands(cfg: dict | None) -> tuple[float, float]:
    bands = ((cfg or {}).get("commodity") or {}).get("bands") or {}
    try:
        med = float(bands.get("medium", DEFAULT_BAND_MEDIUM))
        high = float(bands.get("high", DEFAULT_BAND_HIGH))
    except (TypeError, ValueError):
        logger.warning("commodity.bands malformed — using default bands.")
        return DEFAULT_BAND_MEDIUM, DEFAULT_BAND_HIGH
    if not 0 <= med <= high <= 100:
        logger.warning("commodity.bands out of order/range — using default bands.")
        return DEFAULT_BAND_MEDIUM, DEFAULT_BAND_HIGH
    return med, high


# ---------------------------------------------------------------------------
# Deterministic sub-scores (pure)
# ---------------------------------------------------------------------------

def _tokens(text) -> set:
    return set(_TOKEN_RE.findall(str(text or "").lower()))


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def answer_similarity(texts: list) -> float | None:
    """Mean pairwise token-set Jaccard over result texts; ``None`` for < 2 texts.

    High when the results all say the same thing (commoditized). Deterministic —
    same texts always give the same value (Spec: D4 reproducibility).
    """
    toks = [t for t in (_tokens(x) for x in (texts or [])) if t]
    if len(toks) < 2:
        return None
    pairs = [
        _jaccard(toks[i], toks[j])
        for i in range(len(toks)) for j in range(i + 1, len(toks))
    ]
    return round(sum(pairs) / len(pairs), 4) if pairs else None


def serp_homogeneity(entity_distribution: dict | None,
                     title_patterns: dict | None) -> float:
    """0–1 SERP concentration: top entity-type share blended with title-pattern
    dominance. A uniform SERP (one entity type, one title shape) → high."""
    # isinstance guards: a malformed (non-dict) profile field must not raise here —
    # generate_report composes this under serp_audit's swallowing try, so a raise
    # would silently drop the whole market_analysis_*.md (P2).
    ent = entity_distribution if isinstance(entity_distribution, dict) else {}
    ent_total = sum(ent.values()) if ent else 0
    ent_conc = (max(ent.values()) / ent_total) if ent_total else 0.0
    tp = title_patterns if isinstance(title_patterns, dict) else {}
    counts = tp.get("pattern_counts")
    counts = counts if isinstance(counts, dict) else {}
    tp_total = sum(counts.values()) if counts else 0
    tp_conc = (max(counts.values()) / tp_total) if tp_total else 0.0
    if ent_total and tp_total:
        return round((ent_conc + tp_conc) / 2, 4)
    return round(ent_conc or tp_conc, 4)   # only one signal present


def _composite(subscores: dict, weights: dict) -> float:
    """Weighted mean of the present 0–1 sub-scores × 100, with ``None`` sub-scores
    EXCLUDED and the remaining weights renormalised (aivi.compute_aivi pattern —
    e.g. the LLM term off → its weight redistributes). 0 when nothing present."""
    present = {k: v for k, v in subscores.items() if v is not None}
    if not present:
        return 0.0
    wsum = sum(weights.get(k, 0.0) for k in present)
    if wsum <= 0:
        return 0.0
    score = sum(present[k] * (weights.get(k, 0.0) / wsum) for k in present)
    return round(100.0 * score, 2)


def _band(score: float, med: float, high: float) -> str:
    if score >= high:
        return "high"
    if score >= med:
        return "medium"
    return "low"


def compute_commodity(keyword_profiles: dict, data: dict | None,
                      cfg: dict | None = None):
    """Per-keyword commodity rows + a run-level rollup. Reads existing
    ``keyword_profiles`` fields + ``data["organic_results"]`` snippets only."""
    weights = resolve_weights(cfg)
    top_n = _resolve_top_n(cfg)
    med, high = _resolve_bands(cfg)
    weights_json = json.dumps(
        {"weights": {k: round(weights[k], 6) for k in _WEIGHT_KEYS},
         "top_n": top_n, "bands": {"medium": med, "high": high},
         "similarity": "token_set_jaccard", "llm_probe": False},
        sort_keys=True,
    )

    # Group result (title + snippet) texts by keyword from the raw organic rows.
    by_kw: dict[str, list] = {}
    for row in (data or {}).get("organic_results", []) or []:
        kw = row.get("Root_Keyword")
        if kw:
            # f-string coerces a non-string Title/Snippet (P2 parity with
            # aio_exposure._cited_domains) so one malformed organic row can't
            # raise and silently drop the whole market_analysis_*.md write.
            text = f"{row.get('Title') or ''} {row.get('Snippet') or ''}".strip()
            if text:
                by_kw.setdefault(kw, []).append(text)

    rows: list[dict] = []
    band_counts = {"low": 0, "medium": 0, "high": 0}
    for kw in sorted(keyword_profiles or {}):
        profile = keyword_profiles.get(kw) or {}
        texts = by_kw.get(kw)
        if not texts:   # degrade to the profile's top-5 organic titles
            texts = [r.get("title", "") for r in (profile.get("top5_organic") or [])]
        texts = texts[:top_n]

        sim = answer_similarity(texts)
        hom = serp_homogeneity(profile.get("entity_distribution"),
                               profile.get("title_patterns"))
        aio = 1.0 if profile.get("has_ai_overview") else 0.0
        low_conf = sim is None or len(texts) < 3
        opa = None   # one_paragraph_answerable LLM probe OFF on the report path
        # P7: an UNMEASURED similarity (too few/no snippets) floors to 0 and STAYS
        # in the denominator — missing data must not inflate the score by
        # renormalising its weight away. Only the deliberately-OFF LLM term
        # (opa=None) is excluded + renormalised.
        subscores = {"answer_similarity": 0.0 if sim is None else sim,
                     "serp_homogeneity": hom, "aio_present": aio,
                     "one_paragraph_answerable": opa}
        score = _composite(subscores, weights)
        band = _band(score, med, high)
        if low_conf and band == "high":
            band = "medium"   # P7: thin evidence can't be labelled high-risk
        band_counts[band] += 1

        rows.append({
            "keyword": kw,
            "source": SOURCE,
            "answer_similarity": sim,
            "serp_homogeneity": hom,
            "aio_present": int(aio),
            "one_paragraph_answerable": None,
            "commodity_score": score,
            "risk_band": band,
            "low_confidence": int(low_conf),
            "recommended_play": (profile.get("recommended_play") or {}).get("play"),
            "weights_json": weights_json,
        })

    total = len(rows)
    rollup = {
        "total_keywords": total,
        "high_risk_count": band_counts["high"],
        "medium_risk_count": band_counts["medium"],
        "low_risk_count": band_counts["low"],
        "high_risk_share": round(100.0 * band_counts["high"] / total, 1) if total else 0.0,
        "weights_json": weights_json,
    }
    return rows, rollup


# ---------------------------------------------------------------------------
# Persistence (ai_aio_exposure conventions; idempotent per run_ts)
# ---------------------------------------------------------------------------

def init_commodity_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {COMMODITY_TABLE} (
            run_ts                   TEXT,
            keyword                  TEXT,
            source                   TEXT,
            answer_similarity        REAL,
            serp_homogeneity         REAL,
            aio_present              INTEGER,
            one_paragraph_answerable INTEGER,
            commodity_score          REAL,
            risk_band                TEXT,
            low_confidence           INTEGER,
            weights_json             TEXT
        )''')
        conn.commit()


def save_commodity(db_path: str, run_ts: str, rows: list[dict]) -> None:
    """Idempotent: re-saving the same ``run_ts`` REPLACES prior rows (the report is
    regenerated for the same run — P8, the D1 learning)."""
    init_commodity_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {COMMODITY_TABLE} WHERE run_ts = ?", (run_ts,))
        conn.executemany(
            f"""INSERT INTO {COMMODITY_TABLE}
                (run_ts, keyword, source, answer_similarity, serp_homogeneity,
                 aio_present, one_paragraph_answerable, commodity_score, risk_band,
                 low_confidence, weights_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, r["keyword"], r["source"], r["answer_similarity"],
                 r["serp_homogeneity"], int(r["aio_present"]),
                 r["one_paragraph_answerable"], r["commodity_score"], r["risk_band"],
                 int(r["low_confidence"]), r["weights_json"])
                for r in rows
            ],
        )
        conn.commit()


def get_commodity_for_run(db_path: str, run_ts: str) -> list[dict]:
    init_commodity_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT keyword, commodity_score, risk_band, answer_similarity,
                       serp_homogeneity, aio_present, low_confidence
                FROM {COMMODITY_TABLE} WHERE run_ts = ?
                ORDER BY low_confidence ASC, commodity_score DESC, keyword ASC""",
            (run_ts,),
        ).fetchall()
    return [
        {"keyword": k, "commodity_score": s, "risk_band": b, "answer_similarity": sim,
         "serp_homogeneity": hom, "aio_present": bool(aio), "low_confidence": bool(lc)}
        for k, s, b, sim, hom, aio, lc in rows
    ]


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

_PLAY_LABEL = {
    "extraction_play": "extraction", "deprioritize": "deprioritize",
    "rank_play": "rank", "reformat_play": "reformat", "local_pivot_play": "local pivot",
}
_CAVEAT = (
    "*Indicative.* `Commodity score` is a deterministic 0–100 blend of answer "
    "similarity (how alike the top results read), SERP homogeneity, and AI-Overview "
    "presence — weights in `config.yml commodity.weights`. High = the answer is easily "
    "replaced by one AI paragraph → differentiate or route to extraction/deprioritize. "
    "Answer similarity is **lexical** (shared wording), so results that *paraphrase* the "
    "same answer in different words read as less similar than they are — treat the score "
    "as a floor, not a ceiling. `low` confidence marks keywords with < 3 results or too "
    "few texts to compare (an unmeasured similarity floors to 0, and these rows are "
    "sorted last and never labelled high-risk)."
)


def render_commodity_section(rows: list[dict], rollup: dict) -> list[str]:
    """Render ``## 5e. Query Commodity Risk`` — highest-risk keywords first."""
    out: list[str] = []
    out.append("## 5e. Query Commodity / AI-Absorption Risk")
    out.append(
        "How commoditized each keyword's answer is — how easily a single AI "
        "paragraph could replace the whole SERP. The **differentiate-or-lose** queue: "
        "highest-risk keywords first."
    )
    out.append("")
    if not rows:
        out.append("*No tracked keywords in this run.*")
        out.append("")
        return out
    out.append(
        f"**High-risk:** {rollup.get('high_risk_count', 0)}/"
        f"{rollup.get('total_keywords', 0)} keywords "
        f"({rollup.get('high_risk_share', 0.0):.1f}%)."
    )
    out.append("")
    out.append("| Keyword | Commodity | Band | Answer sim. | SERP homog. | AIO | Play |")
    out.append("|---------|-----------|------|-------------|-------------|-----|------|")
    # Low-confidence rows are demoted below confident ones — a thin/flagged row
    # must never lead the differentiate-or-lose queue (P7).
    ordered = sorted(rows, key=lambda r: (int(r["low_confidence"]),
                                          -float(r["commodity_score"]), r["keyword"]))
    for r in ordered:
        sim = "—" if r["answer_similarity"] is None else f"{r['answer_similarity']:.2f}"
        band = r["risk_band"] + (" ⚠️" if r["low_confidence"] else "")
        play = _PLAY_LABEL.get(r.get("recommended_play"), "—")
        out.append(
            f"| {r['keyword']} | {float(r['commodity_score']):.1f} | {band} | {sim} "
            f"| {float(r['serp_homogeneity']):.2f} | {'yes' if r['aio_present'] else 'no'} "
            f"| {play} |"
        )
    out.append("")
    out.append(_CAVEAT)
    out.append("")
    return out


def build_commodity_report(keyword_profiles: dict, data: dict | None,
                           cfg: dict | None, db_path: str | None = None,
                           run_ts: str | None = None) -> list[str]:
    """Compute → (optionally persist) → render. Pure render when db_path/run_ts
    absent; persists (idempotently) when both supplied. Persistence never breaks
    report generation."""
    rows, rollup = compute_commodity(keyword_profiles, data, cfg)
    if db_path and run_ts:
        try:
            save_commodity(db_path, run_ts, rows)
        except Exception as exc:   # persistence must never break the report
            logger.warning("commodity_score persistence failed: %s", exc)
    return render_commodity_section(rows, rollup)
