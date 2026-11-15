import json
d = json.load(open("/Users/davemini2/ProjectsLocal/serp-discover/tests/fixtures/market_analysis_reference_run.json"))
for r in d["organic_results"]:
    if r.get("Source_Keyword")=="family of origin counselling" and r.get("Query_Label")=="A":
        print(r.get("Rank"), r.get("Page") , r.get("Content_Type"), r.get("Entity_Type"), r.get("Link")[:70], "| ", r.get("Title")[:50])
print(len([r for r in d["organic_results"] if r.get("Query_Label")=="A"]))
print("keys of one row:", list(d["organic_results"][0].keys()))
print("overview rows:", [(o.get("Keyword"), o.get("Query_Label"), o.get("Query")) for o in d["overview"]])
print("feasibility keys:", list(d["keyword_feasibility"][0].keys()) if d["keyword_feasibility"] else None)
print(d["keyword_feasibility"][0] if d["keyword_feasibility"] else None)
