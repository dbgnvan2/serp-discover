import json, collections
d = json.load(open("/Users/davemini2/ProjectsLocal/serp-discover/tests/fixtures/market_analysis_reference_run.json"))
rows=[r for r in d["organic_results"] if r.get("Source_Keyword")=="family of origin counselling" and r.get("Query_Label")=="A"]
for k in ("Run_ID","Created_At","Google_URL","Params_Hash","Executed_Query","Root_Keyword"):
    print(k, collections.Counter(r.get(k) for r in rows))
print([r["Rank"] for r in rows])
# aio_logs / overview mention pages fetched?
for o in d["overview"]:
    print({k:o.get(k) for k in o if "page" in k.lower() or "Page" in k})
for a in d.get("aio_logs", []):
    print({k:a.get(k) for k in a if "page" in k.lower()})
