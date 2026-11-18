"""keyword_demand.py — one answer to "is this keyword's demand measured?"

Review chunk Y1 (adjacent issue logged in D4c). The question was implemented
four times: ``brief_data_extraction._demand_assessment`` and
``_demand_too_small``, and ``brief_validation._keyword_volume`` /
``_any_demand_measured``. Duplicate predicates must agree and nothing made
them — and the whole point of D4.7/D4.16 was that an unmeasured keyword must
never be reported as a small market. Four copies of that distinction is four
chances to lose it.

Three states, and only two are conclusions:

- a measured volume below the editorial floor — a small market;
- a measured volume at or above it — a market worth entering;
- no Moz record for this keyword (``data_available`` false, or ``volume``
  ``None``, which low-volume and local keywords often have) — an UNMEASURED
  market, which draws no conclusion either way (P1).

Spec: docs/review_2026-11-04/PLAN_Y1_one_definition_each.md
Tests: tests/test_y1_one_definition_each.py
"""
from __future__ import annotations

__all__ = ["measured_volume", "any_measured", "too_small", "assessment"]


def measured_volume(profile):
    """The measured monthly volume for one keyword profile, or ``None``.

    ``None`` means "not measured", never "zero": a keyword Moz holds no record
    for carries no volume field at all.
    """
    moz = (profile or {}).get("moz")
    if not isinstance(moz, dict) or not moz.get("data_available"):
        return None
    return moz.get("volume")


def any_measured(keyword_profiles) -> bool:
    """True when at least one keyword carries a measured monthly volume."""
    return any(measured_volume(p) is not None
               for p in (keyword_profiles or {}).values())


def assessment(profile: dict, min_volume) -> tuple[bool, str]:
    """``(too_small, why the question could or could not be answered)``.

    The caller needs to tell "demand measured and adequate" from "demand never
    assessed": on the audit path no Moz metrics are fetched at all, so the rule
    is silently inert and the record must say so.
    """
    if not min_volume:
        return False, "no volume floor configured"
    moz = (profile or {}).get("moz")
    if not isinstance(moz, dict):
        # A truthy non-dict (a string from a hand-edited JSON) must not raise
        # here: the two predicates this module replaced returned "not
        # measured" for it, and a crash on the report path is a worse answer
        # than an honest unknown (cold review of chunk Y1).
        return False, "demand not measured (no Moz record)"
    if not moz.get("data_available"):
        return False, (f"demand not measured "
                       f"({moz.get('status') or 'no Moz record'})")
    volume = moz.get("volume")
    if volume is None:
        return False, "Moz returned no volume for this keyword"
    try:
        return float(volume) < float(min_volume), "measured"
    except (TypeError, ValueError):
        return False, "Moz volume was not a number"


def too_small(profile: dict, min_volume) -> bool:
    """True only when a real demand figure says the market is too small."""
    return assessment(profile, min_volume)[0]
