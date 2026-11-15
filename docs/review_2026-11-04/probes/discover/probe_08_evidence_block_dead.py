"""D-C-08 probe: generate_insight_report's RC.4.1 'Why this pattern fired'
evidence block reads organic rows with keys "title" / "domain", but
serp_audit writes "Title" / "Link" / "Source".  The block therefore never
renders on real data.  Rendering the same report with the keys lower-cased
makes it appear, proving the key mismatch is the only reason."""
import os, sys, json, copy
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import generate_insight_report as gir

data = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
recs = data["strategic_recommendations"]
print("patterns with Detected_Triggers:",
      [(r["Pattern_Name"], r.get("Detected_Triggers")) for r in recs if r.get("Detected_Triggers") not in (None, "N/A")])
# Give the most-relevant keyword one organic TITLE that contains a trigger
# word, in the producer's real key spelling ("Title").
kw = gir._get_most_relevant_keyword(recs[0], data["organic_results"], data["keyword_profiles"], data["paa_questions"])
hit = next(r for r in data["organic_results"] if r["Root_Keyword"] == kw)
hit["Title"] = "Registered Clinical Counsellor — family of origin work"
md = gir.generate_report(data)
print("render with producer keys (Title/Link/Source) contains evidence block:", "Why this pattern fired" in md)

lowered = copy.deepcopy(data)
for row in lowered["organic_results"]:
    row["title"] = row.get("Title", "")
    row["domain"] = row.get("Source", "")
md2 = gir.generate_report(lowered)
print("same data with lower-case 'title'/'domain' keys contains evidence block:", "Why this pattern fired" in md2)
