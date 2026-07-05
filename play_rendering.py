"""play_rendering.py — shared Markdown renderers for the Recommended Play.

Purpose: give report generators (feasibility_*.md, market_analysis_*.md) and the
         brief validator a single place to render / look up a pre-computed
         keyword_profiles[kw].recommended_play verdict, so the play taxonomy is
         never hardcoded in Python.
Spec:    seo_geo_review_20260704.md (T.4 rank-vs-citation two-score model)
Tests:   test_feasibility.py::test_rpc1_recommended_play_column_extraction_not_pivot
         tests/test_report_clarity.py::test_rpc2_play_line_in_feasibility_section

Ownership: chip A (play_routing.py + play_routing.yml) OWNS the taxonomy and
computes the recommended_play field; this module is a pure CONSUMER. It reads
labels + success metrics from chip A's `plays:` map via chip A's own loader, so
there is a single source of truth.

The recommended_play verdict shape (produced by play_routing.compute_recommended_play):
    {
      "play": str,            # rank_play | extraction_play | reformat_play
                              #   | local_pivot_play | deprioritize
      "label": str,           # human label (from play_routing.yml plays.<id>.label)
      "strategy_text": str,   # one-line strategy (quotable)
      "evidence": {"matched_rule": {...}, "inputs_used": {...}},  # structural
      "data_available": {"feasibility": bool, "serp_intent": bool, "aio": bool},
      "confidence": "high" | "low",
      "note": str | None,     # honesty note when an input was missing
    }
"""
import copy

_PLAY_VOCAB_CACHE = None

_EMPTY_VOCAB = {"play_labels": {}, "play_success_metric": {}}


def load_play_vocab():
    """Return {"play_labels": {id: label}, "play_success_metric": {id: metric}}
    derived from chip A's `plays:` map in play_routing.yml.

    Reuses play_routing.load_play_routing (single source of truth). Never raises:
    a missing/malformed file yields empty vocab so the report renderers degrade
    gracefully (play columns show "—") rather than crashing report generation.
    Returns a deep copy so a caller mutating the result cannot poison the cache."""
    global _PLAY_VOCAB_CACHE
    if _PLAY_VOCAB_CACHE is None:
        labels, metrics = {}, {}
        try:
            from play_routing import load_play_routing
            routing = load_play_routing()
            for play_id, play_def in (routing.get("plays") or {}).items():
                if not isinstance(play_def, dict):
                    continue
                labels[play_id] = play_def.get("label", play_id)
                metric = play_def.get("success_metric")
                if metric:
                    metrics[play_id] = metric
        except Exception:
            labels, metrics = {}, {}
        _PLAY_VOCAB_CACHE = {"play_labels": labels, "play_success_metric": metrics}
    return copy.deepcopy(_PLAY_VOCAB_CACHE)


def _sanitize_cell(value):
    """Make free-form text safe inside a Markdown table cell: escape pipes (which
    would add spurious columns) and collapse newlines to spaces."""
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace("|", r"\|")
    return " ".join(text.split()).strip()


def _collapse(value):
    """Collapse whitespace/newlines (for inline/bullet contexts where a stray
    newline would break the bullet, but pipes are harmless)."""
    return " ".join(str(value or "").split()).strip()


def _resolve_label(play_obj, vocab):
    token = play_obj.get("play")
    return vocab.get("play_labels", {}).get(token) or play_obj.get("label") or token


def _honesty_note(play_obj):
    """The producer's honesty note (set when a routing input was missing), or ""."""
    return (play_obj.get("note") or "").strip()


def format_play_cell(play_obj, vocab=None):
    """Render a recommended_play verdict as ONE Markdown table cell.

    - No verdict at all → "—".
    - Verdict present → **Label** — strategy_text, plus an honest "inputs missing"
      caveat when the producer set a note (never a fabricated strategy).

    Free-form text is pipe/newline-sanitized so a strategy containing "|" cannot
    add a spurious column and misalign the table row.
    """
    if not play_obj:
        return "—"
    vocab = vocab or load_play_vocab()
    label = _sanitize_cell(_resolve_label(play_obj, vocab) or "—")
    strategy = _sanitize_cell(play_obj.get("strategy_text"))
    cell = f"**{label}**"
    if strategy:
        cell += f" — {strategy}"
    note = _sanitize_cell(_honesty_note(play_obj))
    if note:
        cell += f" _(inputs missing: {note})_"
    return cell


def format_play_line(play_obj, vocab=None):
    """Render a recommended_play verdict as the body of a Markdown bullet line
    (used in market_analysis_*.md intent + feasibility sections). Returns None
    when there is no verdict, so callers can skip the line entirely."""
    if not play_obj:
        return None
    vocab = vocab or load_play_vocab()
    label = _collapse(_resolve_label(play_obj, vocab) or "—")
    strategy = _collapse(play_obj.get("strategy_text"))
    body = label
    if strategy:
        body += f" — {strategy}"
    metric = vocab.get("play_success_metric", {}).get(play_obj.get("play"))
    if metric:
        body += f"  *(success metric: {metric})*"
    note = _collapse(_honesty_note(play_obj))
    if note:
        body += f"  *(inputs missing: {note})*"
    return body
