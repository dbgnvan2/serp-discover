import sys, os, logging, json
logging.disable(logging.WARNING)
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover"); os.chdir("/Users/davemini2/ProjectsLocal/serp-discover")
import brief_data_extraction as bde, aio_exposure, yaml
cfg = yaml.safe_load(open("config.yml"))
# Mixed SERP where the DOMINANT intent is informational (a preferred intent) and client has no visibility
profiles = {"kw": {"client_visible": False, "serp_intent": {"is_mixed": True, "primary_intent": "mixed",
             "intent_distribution": {"informational": 4, "commercial_investigation": 0, "transactional": 3, "navigational": 0, "local": 1}}}}
flags = bde._compute_strategic_flags if hasattr(bde, "_compute_strategic_flags") else None
import inspect
fn = [f for n,f in inspect.getmembers(bde, inspect.isfunction) if "strategic" in n and "flag" in n]
print("fn:", [f.__name__ for f in fn])
f = fn[0]
out = f(["kw"], profiles, {"organic": [], "summary": {"keywords_with_any_visibility": []}}, {"kw": 5000}, {}, preferred_intents=["informational","transactional","local"])
print("dominant=informational (preferred) → strategy:", profiles["kw"]["mixed_intent_strategy"])
# tie: informational 3 / local 3 (fixture case)
profiles["kw"]["serp_intent"]["intent_distribution"] = {"local": 3, "informational": 3, "transactional": 1, "commercial_investigation": 0, "navigational": 0}
f(["kw"], profiles, {"organic": [], "summary": {"keywords_with_any_visibility": []}}, {"kw": 5000}, {}, preferred_intents=["informational","transactional","local"])
print("tie local 3 / informational 3, dict order local first → strategy:", profiles["kw"]["mixed_intent_strategy"],
      "| dominant picked:", max(profiles["kw"]["serp_intent"]["intent_distribution"], key=profiles["kw"]["serp_intent"]["intent_distribution"].get))
# total_results skip threshold
profiles2 = {"kw": {"client_visible": False, "total_results": 150, "serp_intent": {"is_mixed": False}}}
f(["kw"], profiles2, {"organic": [], "summary": {"keywords_with_any_visibility": []}}, {"kw": 150}, {}, preferred_intents=[])
print("total_results=150 → action/reason:", out and None, )
import pprint
res = f(["kw"], profiles2, {"organic": [], "summary": {"keywords_with_any_visibility": []}}, {"kw": 150}, {}, preferred_intents=[])
print(res["opportunity_scale"]["kw"]["action"], "|", res["opportunity_scale"]["kw"]["reason"])

# Demand dashboard: at-risk clicks vs actual clicks
rc = aio_exposure.resolve_exposure_config(cfg)
loss = aio_exposure.est_ctr_loss(1, True, False, rc)
impressions, actual_clicks = 1000, 60
print(f"rank 1 + AIO, not cited: est_ctr_loss={loss}; impressions={impressions} → 'traffic at risk' = {impressions*loss:.0f} clicks vs GSC actual clicks {actual_clicks} (CTR {actual_clicks/impressions:.1%})")
