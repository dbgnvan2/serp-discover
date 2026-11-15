import json, sys, collections
p = "/Users/davemini2/ProjectsLocal/serp-discover/tests/fixtures/market_analysis_reference_run.json"
d = json.load(open(p))
print("top keys:", list(d.keys()))
print("analysed_keywords:", d.get("analysed_keywords"))
kp = d.get("keyword_profiles", {})
for kw, prof in kp.items():
    si = prof.get("serp_intent", {})
    print("\nKW:", kw)
    print("  serp_intent:", si.get("primary_intent"), si.get("is_mixed"), si.get("confidence"), si.get("intent_distribution"), si.get("evidence"))
    print("  title_patterns:", prof.get("title_patterns"))
    print("  mixed_intent_strategy:", prof.get("mixed_intent_strategy"))
    print("  recommended_play:", prof.get("recommended_play"))
    print("  has_aio:", prof.get("has_ai_overview"), "client_rank:", prof.get("client_rank"), "client_aio_cited:", prof.get("client_aio_cited"))
    print("  moz:", prof.get("moz"), "moz_intent:", prof.get("moz_intent"))
# organic rows by label & rank with content types
org = d.get("organic_results", [])
c = collections.Counter()
for r in org:
    if r.get("Query_Label") == "A":
        rk = r.get("Rank")
        try: rk=int(rk)
        except: rk=99
        c[(r.get("Source_Keyword"), "r<=5" if rk<=5 else ("r6-10" if rk<=10 else "r>10"), r.get("Content_Type"))] += 1
for k,v in sorted(c.items(), key=lambda x: str(x)):
    print(k, v)
print("\nkeyword_feasibility:")
for r in d.get("keyword_feasibility", []):
    print(" ", {k: r.get(k) for k in ("Keyword","Query_Label","Avg_SERP_DA","DA_Gap","Feasibility_Status","Pivot_Keyword","Top10_DA_Values","da_values","Client_DA")})
