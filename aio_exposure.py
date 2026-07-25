#!/usr/bin/env python3
"""aio_exposure.py — AI Overview zero-click exposure.

Purpose: Estimate, per tracked keyword, the organic click-through a Google AI
         Overview (AIO) is likely intercepting, and whether the client is cited
         inside it — the market-side complement to the GSC sponge effect.
Spec:    discover-spec.md#D1 (AV.1)
Plan:    d1_aio_exposure_plan.md
Tests:   tests/test_aio_exposure.py

Rankings no longer predict clicks: an AIO can intercept the click at position 1.
This module is pure read-side assembly — every input already exists on
``keyword_profiles`` (verified in ``brief_data_extraction.py``), so there is no
new SERP fetch and no LLM call:

  * ``aio_present``      ← ``keyword_profiles[kw].has_ai_overview``
  * ``organic_position`` ← ``keyword_profiles[kw].client_rank`` (None = unranked)
  * ``client_cited``     ← ``keyword_profiles[kw].client_aio_cited`` (the AIO lists
                           a client URL among its sources; the flag is computed
                           upstream with ``_is_client_domain`` registrable-domain
                           matching — owner-approved over the spec's reconstructed
                           formula, D-1)
  * ``cited_urls``       ← ``keyword_profiles[kw].aio_top_sources`` (cited domains)

The click-impact estimate is a HEURISTIC. Every constant (the organic CTR curve,
the AIO interception multiplier, the citation credit) lives in ``config.yml
aio_exposure`` and is resolved with a documented-default fallback + warning,
mirroring ``aivi.resolve_weights``. The report labels every value "estimated" —
these are industry reference points, never measured livingsystems.ca CTR.

Persistence mirrors ``citation_table``: an ``ai_aio_exposure`` SQLite table plus a
per-run rollup (``aio_coverage_pct``, ``cited_share``) that trends over
``history_runs``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

AIO_EXPOSURE_TABLE = "ai_aio_exposure"
SOURCE = "google"  # D-6: SERP provider; a per-source column keeps future sources additive.

# D-5: documented defaults — used ONLY when config supplies no valid value. The
# organic CTR curve and the AIO interception multiplier are INDUSTRY REFERENCE
# POINTS (labelled "estimated" in the report), not measured client CTR. Editable
# in config.yml aio_exposure.
DEFAULT_AIO_CTR_MULTIPLIER = 0.60   # industry "~60% AIO CTR interception" reference
DEFAULT_CITATION_CREDIT = 0.5       # a client citation inside the AIO recovers half
DEFAULT_HISTORY_RUNS = 5
DEFAULT_CTR_CURVE = {
    1: 0.280, 2: 0.150, 3: 0.100, 4: 0.070, 5: 0.050,
    6: 0.040, 7: 0.030, 8: 0.025, 9: 0.020, 10: 0.015,
}

_RUN_TS_RE = re.compile(r"(\d{8}_\d{4})")


# ---------------------------------------------------------------------------
# Config resolution (mirrors aivi.resolve_weights)
# ---------------------------------------------------------------------------

def resolve_exposure_config(cfg: dict | None) -> dict:
    """Resolve the CTR curve + multipliers from ``config.yml aio_exposure``.

    A missing block, a non-numeric multiplier/credit, or a malformed curve each
    fall back to the documented default with a logged warning (Spec: D1 —
    config-driven constants). ``aio_ctr_multiplier`` is clamped to [0,1] and
    ``citation_credit`` to [0,1].
    """
    raw = (cfg or {}).get("aio_exposure")
    if raw is not None and not isinstance(raw, dict):
        logger.warning("aio_exposure is not a mapping — using default exposure config.")
        raw = None
    raw = raw or {}

    mult = _resolve_unit(raw.get("aio_ctr_multiplier", DEFAULT_AIO_CTR_MULTIPLIER),
                         DEFAULT_AIO_CTR_MULTIPLIER, "aio_ctr_multiplier")
    credit = _resolve_unit(raw.get("citation_credit", DEFAULT_CITATION_CREDIT),
                           DEFAULT_CITATION_CREDIT, "citation_credit")
    return {
        "aio_ctr_multiplier": mult,
        "citation_credit": credit,
        "ctr_curve": _resolve_curve(raw.get("ctr_curve")),
    }


def _resolve_unit(value, default: float, name: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        logger.warning("aio_exposure.%s is non-numeric — using %.2f.", name, default)
        return default
    if not 0.0 <= num <= 1.0:
        logger.warning("aio_exposure.%s out of [0,1] — using %.2f.", name, default)
        return default
    return num


def _resolve_curve(curve_raw) -> dict:
    if not isinstance(curve_raw, dict) or not curve_raw:
        if curve_raw is not None:
            logger.warning("aio_exposure.ctr_curve malformed — using default curve.")
        return dict(DEFAULT_CTR_CURVE)
    curve: dict[int, float] = {}
    for pos, val in curve_raw.items():
        try:
            curve[int(pos)] = float(val)
        except (TypeError, ValueError):
            logger.warning("aio_exposure.ctr_curve[%r] invalid — skipped.", pos)
    if not curve:
        logger.warning("aio_exposure.ctr_curve had no valid entries — using default.")
        return dict(DEFAULT_CTR_CURVE)
    return curve


def _resolve_history_runs(exposure_cfg: dict | None) -> int:
    """``history_runs`` clamped to ``>= 1``. A negative value would become SQLite
    ``LIMIT -1`` (unbounded); a non-numeric value falls back. Default is
    ``DEFAULT_HISTORY_RUNS``."""
    raw = (exposure_cfg or {}).get("history_runs", DEFAULT_HISTORY_RUNS)
    try:
        num = int(raw)
    except (TypeError, ValueError):
        logger.warning("aio_exposure.history_runs is non-numeric — using %d.",
                       DEFAULT_HISTORY_RUNS)
        return DEFAULT_HISTORY_RUNS
    if num < 1:
        logger.warning("aio_exposure.history_runs < 1 — using %d.", DEFAULT_HISTORY_RUNS)
        return DEFAULT_HISTORY_RUNS
    return num


def _cited_domains(aio_top_sources) -> list:
    """Cited domains from ``aio_top_sources``, tolerating malformed shapes (P2).

    Expected: a list of ``(domain, count)`` pairs (``Counter.most_common``, which
    round-trips through JSON as ``["domain", count]``). A legacy / hand-edited /
    alternate element — a bare string, a dict, a wrong-arity entry — is SKIPPED
    rather than raising, so one bad field degrades the 5d section locally instead
    of aborting the whole market-analysis report write (``serp_audit.py`` wraps
    the render in a swallowing ``try/except`` *before* the file is written, so an
    unguarded ``ValueError`` here would silently drop ``market_analysis_*.md``).
    """
    out: list = []
    for item in aio_top_sources or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, (list, tuple)) and item:
            out.append(item[0])
        # dict / empty / other → skipped
    return out


# ---------------------------------------------------------------------------
# Core heuristic (pure, reproducible — no wall-clock, no randomness)
# ---------------------------------------------------------------------------

def ctr_base(position, curve: dict) -> float:
    """Reference organic CTR for a 1-based position; 0.0 when unranked/off-curve.

    D-4: an unranked client (``position is None``) has no organic CTR to lose, so
    its ``est_ctr_loss`` is 0.0 even under an AIO. Positions beyond the configured
    curve also return 0.0 (negligible tail).
    """
    if position is None:
        return 0.0
    try:
        pos = int(position)
    except (TypeError, ValueError):
        return 0.0
    return float(curve.get(pos, 0.0))


def est_ctr_loss(position, aio_present: bool, client_cited: bool, cfg: dict) -> float:
    """Estimated organic CTR lost to the AIO for one keyword (heuristic).

    ``0.0`` when no AIO. Otherwise ``ctr_base(position) * aio_ctr_multiplier``,
    reduced by ``citation_credit`` when the client is cited inside the AIO. Pure
    function of the snapshot + resolved config (Spec: D1 — reproducibility).
    """
    if not aio_present:
        return 0.0
    loss = ctr_base(position, cfg["ctr_curve"]) * cfg["aio_ctr_multiplier"]
    if client_cited:
        loss *= (1.0 - cfg["citation_credit"])
    return round(loss, 4)


def compute_aio_exposure(keyword_profiles: dict, cfg: dict | None = None):
    """Per-keyword AIO exposure rows + a run-level rollup.

    Reads only existing ``keyword_profiles`` fields. Returns ``(rows, rollup)``
    where each row matches the ``ai_aio_exposure`` columns (minus ``run_ts``), and
    ``rollup`` is ``{total_keywords, aio_present_count, client_cited_count,
    aio_coverage_pct, cited_share, weights_json}``.
    """
    resolved = resolve_exposure_config(cfg)
    weights_json = json.dumps({
        "aio_ctr_multiplier": resolved["aio_ctr_multiplier"],
        "citation_credit": resolved["citation_credit"],
        "ctr_curve": {str(k): v for k, v in sorted(resolved["ctr_curve"].items())},
    }, sort_keys=True)

    rows: list[dict] = []
    aio_present_count = 0
    client_cited_count = 0
    for kw in sorted(keyword_profiles or {}):
        profile = keyword_profiles.get(kw) or {}
        aio_present = bool(profile.get("has_ai_overview"))
        # client_cited is gated on aio_present so we can never report a citation
        # without an Overview to be cited in (defensive; the upstream flag already
        # implies an AIO with citations).
        client_cited = bool(profile.get("client_aio_cited")) and aio_present
        position = profile.get("client_rank")  # None = unranked
        cited_domains = _cited_domains(profile.get("aio_top_sources"))

        loss = est_ctr_loss(position, aio_present, client_cited, resolved)
        aio_present_count += int(aio_present)
        client_cited_count += int(client_cited)

        rows.append({
            "keyword": kw,
            "source": SOURCE,
            "aio_present": int(aio_present),
            "client_cited": int(client_cited),
            "cited_urls_json": json.dumps(cited_domains),
            "organic_position": position if position is not None else None,
            "est_ctr_loss": loss,
            "weights_json": weights_json,
        })

    total = len(rows)
    rollup = {
        "total_keywords": total,
        "aio_present_count": aio_present_count,
        "client_cited_count": client_cited_count,
        "aio_coverage_pct": round(100.0 * aio_present_count / total, 1) if total else 0.0,
        "cited_share": (round(100.0 * client_cited_count / aio_present_count, 1)
                        if aio_present_count else 0.0),
        "weights_json": weights_json,
    }
    return rows, rollup


# ---------------------------------------------------------------------------
# Persistence (probe_ai_visibility / citation_table conventions)
# ---------------------------------------------------------------------------

def init_aio_exposure_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {AIO_EXPOSURE_TABLE} (
            run_ts           TEXT,
            keyword          TEXT,
            source           TEXT,
            aio_present      INTEGER,
            client_cited     INTEGER,
            cited_urls_json  TEXT,
            organic_position INTEGER,
            est_ctr_loss     REAL,
            weights_json     TEXT
        )''')
        conn.commit()


def save_aio_exposure(db_path: str, run_ts: str, rows: list[dict]) -> None:
    """Persist one run's rows. **Idempotent**: re-saving the same ``run_ts``
    REPLACES the prior rows. The market-analysis report is regenerated for the
    same run (e.g. serp-me's post-feasibility auto-regenerate, and the primary
    ``serp_audit.py`` write share one timestamp), so a bare INSERT would
    accumulate duplicate keyword rows per regeneration and inflate
    ``get_aio_exposure_for_run`` (P8)."""
    init_aio_exposure_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {AIO_EXPOSURE_TABLE} WHERE run_ts = ?", (run_ts,))
        conn.executemany(
            f"""INSERT INTO {AIO_EXPOSURE_TABLE}
                (run_ts, keyword, source, aio_present, client_cited,
                 cited_urls_json, organic_position, est_ctr_loss, weights_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (run_ts, r["keyword"], r["source"], int(r["aio_present"]),
                 int(r["client_cited"]), r["cited_urls_json"],
                 r["organic_position"], float(r["est_ctr_loss"]), r["weights_json"])
                for r in rows
            ],
        )
        conn.commit()


def get_aio_exposure_for_run(db_path: str, run_ts: str) -> list[dict]:
    init_aio_exposure_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT keyword, source, aio_present, client_cited, cited_urls_json,
                       organic_position, est_ctr_loss, weights_json
                FROM {AIO_EXPOSURE_TABLE}
                WHERE run_ts = ?
                ORDER BY est_ctr_loss DESC, keyword ASC""",
            (run_ts,),
        ).fetchall()
    return [
        {"keyword": k, "source": s, "aio_present": bool(ap), "client_cited": bool(cc),
         "cited_urls_json": cu, "organic_position": op, "est_ctr_loss": loss,
         "weights_json": wj}
        for k, s, ap, cc, cu, op, loss, wj in rows
    ]


def get_aio_exposure_trend(db_path: str, limit: int = DEFAULT_HISTORY_RUNS) -> list[dict]:
    """Per-run rollup (coverage %, cited share, mean loss), oldest→newest."""
    init_aio_exposure_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT run_ts,
                       COUNT(*)          AS total,
                       SUM(aio_present)  AS aio_present,
                       SUM(client_cited) AS client_cited,
                       AVG(est_ctr_loss) AS mean_loss
                FROM {AIO_EXPOSURE_TABLE}
                GROUP BY run_ts
                ORDER BY run_ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    trend = []
    for run_ts, total, aio_present, client_cited, mean_loss in rows:
        total = total or 0
        aio_present = aio_present or 0
        client_cited = client_cited or 0
        trend.append({
            "run_ts": run_ts,
            "aio_coverage_pct": round(100.0 * aio_present / total, 1) if total else 0.0,
            "cited_share": (round(100.0 * client_cited / aio_present, 1)
                            if aio_present else 0.0),
            "mean_est_ctr_loss": round(mean_loss or 0.0, 4),
        })
    trend.reverse()
    return trend


def run_ts_from_filename(path: str | None) -> str | None:
    """Extract the ``YYYYMMDD_HHMM`` run stamp from a ``market_analysis_*`` name.

    Returns ``None`` when unparseable, so the caller SKIPS persistence rather than
    fabricating a wall-clock stamp (which would corrupt reproducibility / trend
    identity — P1/P6).
    """
    if not path:
        return None
    # basename only, so a timestamped ANCESTOR directory can't mis-key the run
    # (kept consistent with gsc_demand.run_ts_from_filename).
    match = _RUN_TS_RE.search(os.path.basename(str(path)))
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------

_ESTIMATE_CAVEAT = (
    "*Estimates only.* `Est. CTR loss` is a modeled figure = a configurable "
    "organic CTR curve × an industry AI-Overview interception multiplier "
    "(`aio_exposure.aio_ctr_multiplier`, default 0.60 — an industry reference "
    "point, **not** measured livingsystems.ca CTR). A client citation inside the "
    "AIO reduces the estimate by `aio_exposure.citation_credit`. Results drift "
    "run-to-run — read the trend, not one number."
)


def render_aio_exposure_section(rows: list[dict], rollup: dict,
                                trend: list[dict] | None = None) -> list[str]:
    """Render ``## 5d. AI Overview Exposure`` — sorted with the highest-loss,
    not-cited keywords first (the priority queue)."""
    out: list[str] = []
    out.append("## 5d. AI Overview Exposure")
    out.append(
        "Per-keyword estimate of how much organic click-through the Google AI "
        "Overview (AIO) is likely intercepting — and whether the client is cited "
        "*inside* the AIO. Keywords where the client is **not** cited and the "
        "estimated loss is highest are the priority."
    )
    out.append("")
    if not rows:
        out.append("*No tracked keywords in this run.*")
        out.append("")
        return out

    out.append(
        f"**AIO coverage:** {rollup.get('aio_coverage_pct', 0.0):.1f}% of tracked "
        f"keywords show an AI Overview "
        f"({rollup.get('aio_present_count', 0)}/{rollup.get('total_keywords', 0)}). "
        f"**Client cited-share:** {rollup.get('cited_share', 0.0):.1f}% of AIO "
        "keywords cite the client."
    )
    if trend and len(trend) >= 2:
        prev, curr = trend[-2], trend[-1]
        d_cov = curr["aio_coverage_pct"] - prev["aio_coverage_pct"]
        d_cited = curr["cited_share"] - prev["cited_share"]
        out.append(
            f"*Δ prior run: coverage {d_cov:+.1f} pts, cited-share {d_cited:+.1f} pts.*"
        )
    out.append("")
    out.append("| Keyword | Organic position | AIO present | Client cited? | Est. CTR loss |")
    out.append("|---------|------------------|-------------|---------------|---------------|")
    # Default sort: highest est_ctr_loss where client_cited=false first (D1 spec).
    ordered = sorted(
        rows, key=lambda r: (int(r["client_cited"]), -float(r["est_ctr_loss"]), r["keyword"])
    )
    for r in ordered:
        pos = r.get("organic_position")
        pos_str = str(pos) if pos is not None else "—"
        aio = "yes" if r["aio_present"] else "no"
        if not r["aio_present"]:
            cited_flag, loss_str = "—", "—"
        else:
            cited_flag = "✓ cited" if r["client_cited"] else "✗ not cited"
            loss_str = f"{float(r['est_ctr_loss']):.3f}"
        out.append(
            f"| {r['keyword']} | {pos_str} | {aio} | {cited_flag} | {loss_str} |"
        )
    out.append("")
    out.append(_ESTIMATE_CAVEAT)
    out.append("")
    return out


def build_aio_exposure_report(keyword_profiles: dict, cfg: dict | None,
                              db_path: str | None = None,
                              run_ts: str | None = None) -> list[str]:
    """Compute → (optionally persist + trend) → render. Returns markdown lines.

    Pure render when ``db_path``/``run_ts`` are absent (the unit-test / JSON-only
    path). When BOTH are supplied (production ``main()``), the rows are persisted
    to ``ai_aio_exposure`` and the trend delta is included. Persistence never
    breaks report generation — a DB failure downgrades to render-only + a warning.
    """
    rows, rollup = compute_aio_exposure(keyword_profiles, cfg)
    trend = None
    if db_path and run_ts:
        try:
            save_aio_exposure(db_path, run_ts, rows)
            history = _resolve_history_runs((cfg or {}).get("aio_exposure"))
            trend = get_aio_exposure_trend(db_path, limit=history)
        except Exception as exc:  # persistence must never break the report
            logger.warning("aio_exposure persistence/trend failed: %s", exc)
            trend = None
    return render_aio_exposure_section(rows, rollup, trend)
