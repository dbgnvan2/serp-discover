"""D-C-21 probe (FIXED in D2c).

Before: ai_candidate was `google_ai_overview or google_ai_overview_probe or
primary.ai_overview`, and Has_Main_AI_Overview was bool() of whichever won. In
Balanced mode (ai_fallback_without_location: true) a keyword whose Vancouver
SERP has no AI Overview was reported as having one, est_ctr_loss was charged,
and extraction/reformat plays routed on it. aio_log recorded the distinction
and nothing downstream read it.

After: parse_data records AI_Overview_Mode on the overview row.
Has_Main_AI_Overview is true only for the located SERP; an overview only the
un-located probe returned sets Has_Unlocated_AI_Overview, and the reader is
told in Parsing_Warnings."""
import os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import serp_audit

META = {"run_id": "r", "created_at": "c", "google_url": "u", "params_hash": "h"}
CASES = {
    "located, in the main response": {"google": {"organic_results": [], "ai_overview": {"snippet": "located"}}},
    "located, via the page token":   {"google": {"organic_results": []}, "google_ai_overview": {"ai_overview": {"snippet": "token"}}},
    "un-located fallback only":      {"google": {"organic_results": []}, "google_ai_overview_probe": {"snippet": "unlocated"}},
    "no overview at all":            {"google": {"organic_results": []}},
}
for name, results in CASES.items():
    parsed = serp_audit.parse_data("k", results, META)
    m, warnings = parsed[0], parsed[-1]
    print(f"{name:30s} mode={m['AI_Overview_Mode']:26s} "
          f"main={m['Has_Main_AI_Overview']!s:5s} unlocated={m['Has_Unlocated_AI_Overview']!s:5s} "
          f"text={m['AI_Overview']!r}")
    aio_warnings = [w["Message"] for w in warnings
                    if w.get("Field") == "Has_Main_AI_Overview"]
    if name == "un-located fallback only":
        assert m["Has_Main_AI_Overview"] is False, "the located SERP had none"
        assert m["Has_Unlocated_AI_Overview"] is True
        assert aio_warnings, "the reader has to be told which SERP this came from"
        print("    reader is told:", aio_warnings[0])
    else:
        assert not aio_warnings
assert serp_audit.parse_data("k", CASES["located, in the main response"], META)[0]["Has_Main_AI_Overview"]
