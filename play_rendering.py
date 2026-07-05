"""play_rendering.py — shared loader + Markdown renderers for the Recommended Play.

Purpose: give report generators (feasibility_*.md, market_analysis_*.md) and the
         brief validator a single place to read the play vocabulary and render a
         pre-computed keyword_profiles[kw].recommended_play verdict, so the play
         taxonomy is never hardcoded in Python.
Spec:    seo_geo_review_20260704.md (T.4 rank-vs-citation two-score model)
Tests:   test_feasibility.py::test_rpc1_recommended_play_column_extraction_not_pivot
         tests/test_report_clarity.py::test_rpc2_play_line_in_feasibility_section

Ownership: chip A owns the routing rules + the recommended_play field; this module
is a pure CONSUMER of the vocabulary block in play_routing.yml.
"""
import os

import yaml

_PLAY_ROUTING_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "play_routing.yml"
)
_PLAY_VOCAB_CACHE = None

_EMPTY_VOCAB = {"play_labels": {}, "play_claim_phrases": {}, "play_success_metric": {}}


def load_play_vocab():
    """Load the play vocabulary (labels, claim phrases, success metrics) from
    play_routing.yml. Never raises: a missing/broken file yields empty vocab so
    consumers degrade gracefully (surface-not-crash)."""
    global _PLAY_VOCAB_CACHE
    if _PLAY_VOCAB_CACHE is not None:
        return _PLAY_VOCAB_CACHE
    vocab = dict(_EMPTY_VOCAB)
    try:
        if os.path.exists(_PLAY_ROUTING_PATH):
            with open(_PLAY_ROUTING_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            vocab = {key: (loaded.get(key) or {}) for key in _EMPTY_VOCAB}
    except Exception:
        vocab = dict(_EMPTY_VOCAB)
    _PLAY_VOCAB_CACHE = vocab
    return vocab


def _resolve_label(play_obj, vocab):
    token = play_obj.get("play")
    return vocab.get("play_labels", {}).get(token) or play_obj.get("label") or token


def _evidence_str(play_obj, limit=2):
    evidence = play_obj.get("evidence")
    if not evidence:
        return ""
    if isinstance(evidence, str):
        return evidence.strip()
    parts = [str(e).strip() for e in evidence if str(e).strip()]
    return "; ".join(parts[:limit])


def format_play_cell(play_obj, vocab=None):
    """Render a recommended_play verdict as ONE Markdown table cell.

    - No verdict at all → "—".
    - data_available is False → honest "inputs missing" note; NEVER a fabricated
      strategy.
    - Otherwise → **Label** — strategy_text (+ compact evidence).
    """
    if not play_obj:
        return "—"
    vocab = vocab or load_play_vocab()
    label = _resolve_label(play_obj, vocab) or "—"
    if play_obj.get("data_available", True) is False:
        return f"**{label}** — *play inputs missing; not computed*"
    strategy = (play_obj.get("strategy_text") or "").strip()
    cell = f"**{label}**"
    if strategy:
        cell += f" — {strategy}"
    evidence = _evidence_str(play_obj)
    if evidence:
        cell += f" _(evidence: {evidence})_"
    return cell


def format_play_line(play_obj, vocab=None):
    """Render a recommended_play verdict as the body of a Markdown bullet line
    (used in market_analysis_*.md intent + feasibility sections). Returns None
    when there is no verdict, so callers can skip the line entirely."""
    if not play_obj:
        return None
    vocab = vocab or load_play_vocab()
    label = _resolve_label(play_obj, vocab) or "—"
    if play_obj.get("data_available", True) is False:
        return f"{label} — *play inputs missing; not computed*"
    strategy = (play_obj.get("strategy_text") or "").strip()
    body = label
    if strategy:
        body += f" — {strategy}"
    metric = vocab.get("play_success_metric", {}).get(play_obj.get("play"))
    if metric:
        body += f"  *(success metric: {metric})*"
    return body
