import sys, os, logging
logging.disable(logging.WARNING)
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover"); os.chdir("/Users/davemini2/ProjectsLocal/serp-discover")
from feasibility import compute_feasibility, generate_hyper_local_pivot
from intent_verdict import compute_serp_intent, load_mapping
import generate_insight_report as gir
import play_routing

print("== feasibility: empty DA list ==")
print(compute_feasibility(35, []))
print("== feasibility: 7 of 10 competitors have DA; 3 missing dropped (what run_feasibility does) ==")
print(compute_feasibility(35, [60, 55, 50, 48, 52, 58, 61]))
print("== feasibility: same 7 + 3 unknown domains coerced to DA 0 (what dataforseo/moz 'or 0' does) ==")
print(compute_feasibility(35, [60, 55, 50, 48, 52, 58, 61, 0, 0, 0]))
print("== feasibility: 1 directory DA 92 + 9 clinics DA 18 ==")
print(compute_feasibility(35, [92] + [18]*9))
print("== feasibility: 5 directories DA 85 + 5 clinics DA 12 (mean says Moderate; 5 DA-12 sites rank) ==")
print(compute_feasibility(35, [85]*5 + [12]*5))
print("== feasibility_score > 1 (docstring says 0..1) ==")
print(compute_feasibility(35, [20]*10))
print("== pivot text for a Low Feasibility keyword (claims 'high-authority directories' unconditionally) ==")
print(generate_hyper_local_pivot("how does family therapy work", "North Vancouver", {"status":"Low Feasibility","avg_competitor_da":70}, ["Lonsdale"], is_service_like=True)["strategy"])

m = load_mapping()
def row(ct, et, src="x.com"): return {"rank":1,"title":"t","source":src,"entity_type":et,"content_type":ct}
print("\n== intent: 5 classified of 10 — 2 info, 1 trans, 1 local, 1 nav(client) → primary from 2 URLs? ==")
rows = [row("guide","counselling"), row("guide","counselling"), row("service","counselling"), row("service","counselling"), row("guide","x","livingsystems.ca/a")] + [row("other","N/A")]*5
r = compute_serp_intent(rows, has_local_pack=False, client_domain="livingsystems.ca", mapping=m)
# note: local requires local pack; make one of the service rows local by local pack... keep simple
print(r["primary_intent"], r["is_mixed"], r["confidence"], r["intent_distribution"], r["evidence"]["classified_organic_url_count"])
print("== intent: 10/10 classified, 6 info / 4 trans → 'high' confidence primary ==")
rows = [row("guide","counselling")]*6 + [row("service","counselling")]*4
r = compute_serp_intent(rows, has_local_pack=False, mapping=m)
print(r["primary_intent"], r["is_mixed"], r["confidence"], r["intent_distribution"])
print("== intent: 4 classified (all info) of 10 → primary None, confidence low ==")
rows = [row("guide","counselling")]*4 + [row("other","N/A")]*6
r = compute_serp_intent(rows, has_local_pack=False, mapping=m)
print(r["primary_intent"], r["is_mixed"], r["confidence"])
print("== intent: config confidence_high=0.8 threshold passed in — ignored? ==")
rows = [row("guide","counselling")]*8 + [row("other","N/A")]*2
r = compute_serp_intent(rows, has_local_pack=False, mapping=m, thresholds={"confidence_high":0.99,"confidence_medium":0.95})
print("confidence with confidence_high=0.99 passed:", r["confidence"])

print("\n== Section 0: High-feasibility keyword with non-preferred intent vs Moderate preferred ==")
profiles = {
  "kwA": {"serp_intent":{"primary_intent":"navigational","confidence":"high","is_mixed":False}},
  "kwB": {"serp_intent":{"primary_intent":"informational","confidence":"high","is_mixed":False}},
}
feas = [{"Keyword":"kwA","Query_Label":"A","feasibility_status":"High Feasibility"},
        {"Keyword":"kwB","Query_Label":"A","feasibility_status":"Moderate Feasibility"}]
pref = ["informational","transactional","local"]
best, reason = gir._get_best_opportunity_keyword(profiles, feas, pref)
print("best opportunity:", best, "|", reason)
for kw in profiles:
    print(kw, "action:", gir._get_keyword_action(kw, profiles[kw], [f for f in feas if f["Keyword"]==kw][0], pref))

print("\n== play routing: feasibility unknown + informational + AIO → strategy_text ==")
rp = play_routing.compute_recommended_play({"serp_intent":{"primary_intent":"informational"},"has_ai_overview":True,"has_local_pack":False,"aio_divergence":{}}, None, "family of origin work", ["therapy"])
print(rp["play"], "|", rp["strategy_text"][:60], "| note:", rp["note"])
print("== play routing: High feasibility + navigational → rank_play ==")
rp = play_routing.compute_recommended_play({"serp_intent":{"primary_intent":"navigational"},"has_ai_overview":False,"has_local_pack":False,"aio_divergence":{}}, {"feasibility_status":"High Feasibility"}, "x", [])
print(rp["play"])
print("== play routing: is_service_like differs from query_variants? 'how does family therapy work north vancouver' ==")
import query_variants
print("play_routing:", play_routing._is_service_like("how does family therapy work", ["therapy"]), "| query_variants:", query_variants.is_service_like("how does family therapy work", ["therapy"], "North Vancouver"))
