"""D-C-01 probe: SerpAPI `position` restarts at 1 on every paginated page, and
serp_audit uses it verbatim as `Rank`.  Shows (a) the real reference run carries
three 1..10 sequences per keyword, (b) brief_data_extraction reports the
client's page-3 position as `client_rank` 7, (c) run_feasibility's "top 10" is
built from three pages, (d) _merge_google_pages does not renumber."""
import json, os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)

d = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
org = d["organic_results"]
for kw in d["keyword_profiles"]:
    rows = [r for r in org if r["Source_Keyword"] == kw and r["Query_Label"] == "A"]
    print(f"{kw!r}: {len(rows)} organic rows, Rank sequence = {[r['Rank'] for r in rows]}")
    for i, r in enumerate(rows):
        if "livingsystems" in r["Link"]:
            print(f"   client row is list index {i} (0-based) -> true SERP position ~{i+1}, "
                  f"but Rank field = {r['Rank']}")
    print(f"   keyword_profiles[kw]['client_rank'] = {d['keyword_profiles'][kw]['client_rank']}")
    print(f"   top5_organic ranks = {[r['rank'] for r in d['keyword_profiles'][kw]['top5_organic']]}")

# (b) reproduce through the extractor itself
import brief_data_extraction as bde
ex = bde.extract_analysis_data_from_json(d, client_domain="livingsystems.ca",
                                         client_name_patterns=["Living Systems"])
kp = ex["keyword_profiles"]["family of origin counselling"]
print("\nextract_analysis_data_from_json -> client_rank =", kp["client_rank"],
      "| organic_url_count used for serp_intent =", kp["serp_intent"]["evidence"]["organic_url_count"])
print("competitors_above count for client:",
      len([o for o in ex["client_position"]["organic"] if o["source_keyword"]=="family of origin counselling"][0]["competitors_above"]),
      "(a true #7 would have 6)")

# (c) run_feasibility top-10 selection
import run_feasibility as rf
by_kw = rf._get_organic_urls_by_keyword(d)
urls = by_kw["family of origin counselling"]
rank_of = {r["Link"]: (org.index(r)) for r in org if r["Source_Keyword"]=="family of origin counselling"}
print("\nrun_feasibility 'top 10' URLs -> their true list positions:",
      sorted(rank_of[u] + 1 for u in urls))

# (d) synthetic: two pages with page-relative positions merged by serp_audit
import serp_audit
p1 = {"organic_results": [{"link": f"http://a{i}.com", "position": i} for i in range(1, 11)]}
p2 = {"organic_results": [{"link": f"http://b{i}.com", "position": i} for i in range(1, 11)]}
merged = serp_audit._merge_google_pages([p1, p2])
print("\n_merge_google_pages positions:", [r["position"] for r in merged["organic_results"]])
