import sys, json
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover")
import commodity_score as cs
d = json.load(open("/Users/davemini2/ProjectsLocal/serp-discover/tests/fixtures/market_analysis_reference_run.json"))
import yaml
cfg = yaml.safe_load(open("/Users/davemini2/ProjectsLocal/serp-discover/config.yml"))
rows, rollup = cs.compute_commodity(d["keyword_profiles"], d, cfg)
for r in rows:
    print({k: r[k] for k in ("keyword","answer_similarity","serp_homogeneity","aio_present","commodity_score","risk_band","low_confidence")})
# Show what homogeneity would be if 'other' titles were excluded
for kw, p in d["keyword_profiles"].items():
    tp = p["title_patterns"]["pattern_counts"]
    ent = p["entity_distribution"]
    print(kw, "title counts", tp, "entity", ent)
    counts_wo = {k:v for k,v in tp.items() if k!="other"}
    print("  homog as computed:", cs.serp_homogeneity(ent, p["title_patterns"]),
          " entity-only conc:", max(ent.values())/sum(ent.values()),
          " title conc excl other:", (max(counts_wo.values())/sum(counts_wo.values())) if sum(counts_wo.values()) else None)
# Which texts were used
by_kw={}
for row in d["organic_results"]:
    kw=row.get("Root_Keyword")
    if kw: by_kw.setdefault(kw,[]).append((row.get("Query_Label"),row.get("Rank"),(row.get("Title") or "")[:40]))
for kw,v in by_kw.items(): print(kw, v[:5])
