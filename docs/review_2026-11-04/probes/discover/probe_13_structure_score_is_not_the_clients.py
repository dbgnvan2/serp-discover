"""D-M-04 probe (FLIPPED by chunk D3b): the "foundational readiness" structure
sub-score is measured off the CLIENT's markup, not the competitors'.

`foundational_score.compute_structure` reads `schema_signals.schema_type_counts`,
which `_build_schema_signals` aggregates over the whole enriched top-10. A
client with no page in any top-10 — and therefore no markup measured at all —
still scores, because the competitors it is being compared against have the
schema types the recommendations ask for.

Before: a score; after: None (n/a) when the client has no measured page, and a
score computed from `schema_signals.client_page` when it does.
"""
import os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import foundational_score as fs

RECS = [{"label": "FAQ markup", "schema_types": ["FAQPage"]},
        {"label": "Service markup", "schema_types": ["Service"]},
        {"label": "Local business markup", "schema_types": ["LocalBusiness"]}]

# Three competitors are enriched and carry markup. The client is in no top-10,
# so nothing of the client's was ever fetched or measured.
data = {"keyword_profiles": {"family counselling north vancouver": {
    "schema_signals": {
        "data_available": True,
        "enriched_count": 3,
        "schema_type_counts": {"FAQPage": 2, "LocalBusiness": 1},
        "pages_with_schema": [
            {"rank": 1, "source": "psychologytoday.com", "schema_types": ["FAQPage"]},
            {"rank": 2, "source": "fsgv.ca", "schema_types": ["LocalBusiness"]},
            {"rank": 3, "source": "counsellingbc.com", "schema_types": ["FAQPage"]},
        ],
    }}}}

score, gaps = fs.compute_structure(data, RECS)
print("client pages measured: 0 (the client is in no enriched top-10)")
print("structure sub-score:", score)
print("gaps:", gaps)
assert score is None, "no client page measured => no structure sub-score"
assert gaps == []

# The same SERP, but the client now holds rank 4 and was enriched: FAQPage
# only, of the three recommended types.
profile = data["keyword_profiles"]["family counselling north vancouver"]
profile["schema_signals"]["client_page"] = {
    "rank": 4, "source": "livingsystems.ca", "schema_types": ["FAQPage"],
    "faq_present": True,
}
score, gaps = fs.compute_structure(data, RECS)
print("\nwith the client's own page (FAQPage only):", score, gaps)
assert score == round(100.0 / 3, 2), score   # 1 of 3 recommended types
assert any("Service" in g for g in gaps)
assert not any("FAQ markup" in g for g in gaps)

print("\nOK — the sub-score is the client's own markup. With no client page "
      "it is not measured; with one it counts only that page's types.")
