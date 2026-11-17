"""gsc_filters.py — which searchers the Search Console figures are about.

Pure config reading, no network and no heavy dependency, so both the GSC client
(``gsc_client``) and the read-side demand dashboard (``demand_dashboard``, which
reads the same ``gsc_cache`` table) resolve the country/device restriction from
one place. The pipeline must not import ``gsc_client``
(``tests/test_gsc.py::test_pipeline_never_imports_gsc_client``), and two copies
of this mapping would drift (P31).

Spec: docs/review_2026-11-04/PLAN_D5_demand_and_exposure.md (D5.7)
Tests: tests/test_d5_demand_and_exposure.py
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


#: GSC's country dimension takes a 3-letter ISO-3166-1 alpha-3 code; the SERP
#: fetch's ``serpapi.gl`` is alpha-2. Only the codes this client's market needs
#: are mapped — an unmapped code is reported, not guessed (D5.7).
COUNTRY_ALPHA2_TO_ALPHA3 = {
    "ca": "can", "us": "usa", "gb": "gbr", "au": "aus", "nz": "nzl",
    "ie": "irl", "za": "zaf", "in": "ind",
}
#: The alpha-3 codes this build will send. Any other 3-letter string used to be
#: passed through unchecked: GSC accepts an unknown filter, returns no rows, the
#: short page reads as "the property is empty", and every query is then cached as
#: a measured absence for the TTL — the D-C-02 failure re-entering through the
#: filter path (cold review 8).
KNOWN_ALPHA3 = set(COUNTRY_ALPHA2_TO_ALPHA3.values())
GSC_DEVICES = {"desktop": "DESKTOP", "mobile": "MOBILE", "tablet": "TABLET"}


def resolve_query_filters(cfg: dict | None) -> dict:
    """The country/device the GSC pull is restricted to.

    The SERP side of every figure in this report is fetched for one country and
    one device (``serpapi.gl`` / ``serpapi.device``). An unfiltered GSC pull
    answers for every country and every device, so a CTR compared against that
    SERP is two different populations — Canadian desktop ranking against
    worldwide all-device clicks (finding D-M-20 / D5.7).

    ``gsc.country`` / ``gsc.device`` override; either set to ``null`` or
    ``"all"`` turns that filter off deliberately. Defaults mirror the SERP
    fetch. Returns ``{"country", "device", "warnings"}`` — the resolved GSC
    values (``None`` when unfiltered) and anything that could not be mapped.
    """
    cfg = cfg or {}
    gsc_cfg = cfg.get("gsc") or {}
    serp_cfg = cfg.get("serpapi") or {}
    warnings: list[str] = []

    def _off(value) -> bool:
        return value is None or str(value).strip().lower() in ("", "all", "none")

    raw_country = (gsc_cfg["country"] if "country" in gsc_cfg
                   else serp_cfg.get("gl"))
    country = None
    if "country" in gsc_cfg and _off(raw_country):
        pass                                    # filter switched off on purpose
    elif raw_country:
        code = str(raw_country).strip().lower()
        country = COUNTRY_ALPHA2_TO_ALPHA3.get(
            code, code if code in KNOWN_ALPHA3 else None)
        if not country:
            warnings.append(
                f"GSC country filter not applied: '{raw_country}' is not a "
                "country code this build knows "
                f"({', '.join(sorted(COUNTRY_ALPHA2_TO_ALPHA3))}). Pulling "
                "every country. Add the code to COUNTRY_ALPHA2_TO_ALPHA3, or "
                "set gsc.country to 'all' to make this deliberate.")

    raw_device = (gsc_cfg["device"] if "device" in gsc_cfg
                  else serp_cfg.get("device"))
    device = None
    if "device" in gsc_cfg and _off(raw_device):
        pass
    elif raw_device:
        key = str(raw_device).strip().lower()
        device = GSC_DEVICES.get(key)
        if not device:
            warnings.append(
                f"GSC device filter not applied: '{raw_device}' is not one of "
                "desktop/mobile/tablet (set gsc.device, or 'all' to pull every "
                "device).")

    return {"country": country, "device": device, "warnings": warnings}


def filters_text(filters: dict) -> str:
    """One phrase naming what the pull was restricted to, for the report."""
    parts = []
    parts.append(f"country {filters.get('country').upper()}" if filters.get("country")
                 else "every country")
    parts.append(f"{filters.get('device').lower()} only" if filters.get("device")
                 else "every device")
    return ", ".join(parts)



def cache_filter_key(filters: dict | None) -> str:
    """The ``gsc_cache.filters`` value for a resolved filter set.

    ``""`` means unfiltered, which is also what rows written before the column
    existed carry, so an old row is served only to an unfiltered pull.
    """
    country = (filters or {}).get("country") or ""
    device = (filters or {}).get("device") or ""
    return "" if not (country or device) else f"{country}|{device}"
