"""D4 / AV.4 — Query Commodity / AI-Absorption Risk.

Spec: discover-spec.md#D4. Plan: d2_d5_implementation_plan.md (AV.4).
Deterministic composite (no LLM on the report path); scoring + P7 adversarial +
reproducibility + persistence + P21 wiring, per the D1 discipline.
"""
import json

import commodity_score as cs
from commodity_score import (
    answer_similarity, build_commodity_report, compute_commodity,
    get_commodity_for_run, render_commodity_section, resolve_weights,
    save_commodity, serp_homogeneity,
)

CFG = {"commodity": {
    "weights": {"answer_similarity": 0.4, "serp_homogeneity": 0.3,
                "aio_present": 0.2, "one_paragraph_answerable": 0.1},
    "top_n_results": 5, "bands": {"medium": 40, "high": 70},
}}


def _profile(entity=None, patterns=None, aio=False, play=None, titles=None):
    return {
        "has_ai_overview": aio,
        "entity_distribution": entity or {},
        "title_patterns": {"pattern_counts": patterns or {}},
        "recommended_play": {"play": play} if play else {},
        "top5_organic": [{"title": t} for t in (titles or [])],
    }


def _organic(kw, *snippets):
    return [{"Root_Keyword": kw, "Title": s, "Snippet": s} for s in snippets]


# --- sub-scores ---------------------------------------------------------------

def test_answer_similarity_identical_vs_diverse():
    assert answer_similarity(["couples therapy helps", "couples therapy helps"]) == 1.0
    diverse = answer_similarity(["couples therapy in vancouver", "birth order and anxiety"])
    assert diverse < 1.0
    assert answer_similarity(["only one text"]) is None      # < 2 texts → undefined
    assert answer_similarity([]) is None


def test_serp_homogeneity_concentration():
    assert serp_homogeneity({"directory": 8}, {"how_to": 8}) == 1.0   # one type, one shape
    mixed = serp_homogeneity({"a": 2, "b": 2, "c": 2, "d": 2}, {"how_to": 2, "what_is": 2})
    assert mixed < 1.0
    assert serp_homogeneity({}, {}) == 0.0                            # no signal → 0


def test_composite_all_max_is_100_with_llm_off_renormalized():
    """LLM term OFF (None) → its weight renormalizes over the other three, so an
    all-1 input still reaches 100 (not capped at 90)."""
    profiles = {"kw": _profile(entity={"directory": 5}, patterns={"how_to": 5}, aio=True)}
    data = {"organic_results": _organic("kw", "same text", "same text", "same text")}
    rows, _ = compute_commodity(profiles, data, CFG)
    assert rows[0]["one_paragraph_answerable"] is None
    assert rows[0]["commodity_score"] == 100.0
    assert rows[0]["risk_band"] == "high"


# --- AV.4 P7 adversarial: commoditized query scores higher, sorts first -------

def test_av4_adversarial_commodity_scores_higher_and_first():
    profiles = {
        "commodity kw": _profile(entity={"directory": 6}, patterns={"what_is": 6}, aio=True),
        "unique kw": _profile(entity={"a": 1, "b": 1, "c": 1}, patterns={"how_to": 1, "vs": 1, "best": 1}),
    }
    data = {"organic_results": (
        _organic("commodity kw", "what is anxiety", "what is anxiety", "what is anxiety")
        + _organic("unique kw", "vancouver couples retreat", "bowen family theory explained",
                   "cost of therapy in bc")
    )}
    rows, rollup = compute_commodity(profiles, data, CFG)
    by = {r["keyword"]: r for r in rows}
    assert by["commodity kw"]["commodity_score"] > by["unique kw"]["commodity_score"]
    body = "\n".join(render_commodity_section(rows, rollup))
    assert body.index("commodity kw") < body.index("unique kw")   # highest-risk first


def test_av4_low_confidence_row_does_not_lead_queue():
    """P7 — a thin/low-confidence keyword (missing snippets, one entity bucket, AIO)
    must NOT outrank a well-measured commoditized keyword, and can't be labelled high."""
    profiles = {
        "thin kw": _profile(entity={"directory": 1}, aio=True),   # 0 texts → low_conf
        "measured kw": _profile(entity={"directory": 6}, patterns={"what_is": 6}, aio=True),
    }
    data = {"organic_results": _organic("measured kw", "what is x", "what is x", "what is x")}
    rows, rollup = compute_commodity(profiles, data, CFG)
    by = {r["keyword"]: r for r in rows}
    assert by["thin kw"]["low_confidence"] == 1
    assert by["thin kw"]["risk_band"] != "high"               # capped — thin evidence
    assert by["measured kw"]["low_confidence"] == 0
    body = "\n".join(render_commodity_section(rows, rollup))
    assert body.index("measured kw") < body.index("thin kw")  # confident row leads


def test_av4_unmeasured_similarity_floors_not_inflates():
    """P7 — missing snippets (sim None) FLOOR to 0, not renormalize their weight onto
    the others; a no-text row cannot reach 'high' on the strength of the data it lacks."""
    profiles = {"kw": _profile(entity={"directory": 5}, patterns={"what_is": 5}, aio=True)}
    rows, _ = compute_commodity(profiles, {"organic_results": []}, CFG)   # no texts
    row = rows[0]
    assert row["answer_similarity"] is None                  # honest: not measured
    # sim floored to 0 → 100*(0.3·1 + 0.2·1)/0.9 ≈ 55.6, NOT the 100 a renormalize gives
    assert row["commodity_score"] < 70
    assert row["low_confidence"] == 1


# --- bands / low_confidence ---------------------------------------------------

def test_bands_and_low_confidence():
    # < 3 texts → low_confidence; diverse, no AIO → low band
    profiles = {"kw": _profile(entity={"a": 1, "b": 1}, patterns={"how_to": 1, "what_is": 1})}
    data = {"organic_results": _organic("kw", "alpha beta", "gamma delta")}   # 2 texts
    rows, _ = compute_commodity(profiles, data, CFG)
    assert rows[0]["low_confidence"] == 1                    # only 2 texts (<3)
    assert rows[0]["risk_band"] == "low"


def test_no_texts_similarity_none_low_confidence():
    profiles = {"kw": _profile(entity={"directory": 3})}     # no organic, no titles
    rows, _ = compute_commodity(profiles, {"organic_results": []}, CFG)
    assert rows[0]["answer_similarity"] is None
    assert rows[0]["low_confidence"] == 1


def test_degrades_to_top5_titles_when_no_organic_results():
    profiles = {"kw": _profile(entity={"directory": 3},
                               titles=["same head", "same head", "same head"])}
    rows, _ = compute_commodity(profiles, {}, CFG)           # no organic_results key
    assert rows[0]["answer_similarity"] == 1.0               # identical titles


# --- config-driven weights ----------------------------------------------------

def test_weights_from_config_change_score():
    profiles = {"kw": _profile(entity={"directory": 5}, patterns={"how_to": 5}, aio=True)}
    data = {"organic_results": _organic("kw", "t", "t", "t")}
    default_row = compute_commodity(profiles, data, CFG)[0][0]
    aio_heavy = {"commodity": {**CFG["commodity"],
                               "weights": {"answer_similarity": 0.1, "serp_homogeneity": 0.1,
                                           "aio_present": 0.8, "one_paragraph_answerable": 0.0}}}
    row = compute_commodity(profiles, data, aio_heavy)[0][0]
    assert row["commodity_score"] == default_row["commodity_score"] == 100.0  # all-max both


def test_malformed_weights_fall_back(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        w = resolve_weights({"commodity": {"weights": {"answer_similarity": "x"}}})
    assert w == cs.DEFAULT_WEIGHTS
    assert "commodity.weights" in caplog.text


# --- reproducibility ----------------------------------------------------------

def test_reproducible():
    profiles = {"a": _profile(entity={"directory": 4}, patterns={"how_to": 4}, aio=True),
                "b": _profile(entity={"x": 1, "y": 1})}
    data = {"organic_results": _organic("a", "same", "same") + _organic("b", "one", "two")}
    r1, roll1 = compute_commodity(profiles, data, CFG)
    r2, roll2 = compute_commodity(profiles, data, CFG)
    assert r1 == r2 and roll1 == roll2
    assert json.loads(r1[0]["weights_json"])["similarity"] == "token_set_jaccard"


# --- persistence + wiring -----------------------------------------------------

def test_save_idempotent_same_run_ts(tmp_path):
    db = str(tmp_path / "serp_data.db")
    profiles = {"kw": _profile(entity={"directory": 3}, aio=True)}
    rows, _ = compute_commodity(profiles, {"organic_results": _organic("kw", "a b", "a b")}, CFG)
    save_commodity(db, "20260725_1000", rows)
    save_commodity(db, "20260725_1000", rows)          # regenerate same run
    assert len(get_commodity_for_run(db, "20260725_1000")) == 1


def test_av4_build_persists_and_renders(tmp_path):
    """P21 — build_commodity_report renders 5e AND persists when db+run_ts given."""
    db = str(tmp_path / "serp_data.db")
    profiles = {"kw": _profile(entity={"directory": 3}, aio=True, play="extraction_play")}
    data = {"organic_results": _organic("kw", "same answer", "same answer")}
    lines = build_commodity_report(profiles, data, CFG, db_path=db, run_ts="20260725_1100")
    assert any("## 5e. Query Commodity" in ln for ln in lines)
    assert any("extraction" in ln for ln in lines)     # recommended_play passthrough
    assert len(get_commodity_for_run(db, "20260725_1100")) == 1


def test_av4_render_only_without_db():
    profiles = {"kw": _profile(entity={"directory": 3})}
    lines = build_commodity_report(profiles, {"organic_results": []}, CFG)
    assert any("## 5e. Query Commodity" in ln for ln in lines)
