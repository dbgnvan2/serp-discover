import sys, os, json, logging
logging.disable(logging.WARNING)
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover"); os.chdir("/Users/davemini2/ProjectsLocal/serp-discover")
import handoff_writer, run_feasibility
d = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
import inspect
sig = inspect.signature(handoff_writer.build_competitor_handoff)
print(sig)
h = handoff_writer.build_competitor_handoff(d["organic_results"], run_id="x", run_timestamp="x", client_domain="livingsystems.ca", client_brand_names=["Living Systems"], n=10, omit_from_audit=[])
# index rows by url → (page-order index within label A list) for the keyword
order = {}
for kw in ("family of origin counselling",):
    rows=[r for r in d["organic_results"] if r.get("Source_Keyword")==kw and r.get("Query_Label")=="A"]
    for i,r in enumerate(rows): order[r["Link"]] = i+1
print("handoff targets for 'family of origin counselling' (rank field vs. true merged position):")
for t in h["targets"]:
    if t["source_keyword"]=="family of origin counselling":
        print(f"  rank={t['rank']}  merged_pos={order.get(t['url'],'(variant/other label)')}  {t['url'][:60]}")
print("\nrun_feasibility top-10 URL selection for the same keyword (merged positions):")
sel = run_feasibility._get_organic_urls_by_keyword(d)["family of origin counselling"]
print([order.get(u) for u in sel])
