import sys, json
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover")
import brand_mentions as bm
d = json.load(open("/Users/davemini2/ProjectsLocal/serp-discover/tests/fixtures/market_analysis_reference_run.json"))
g = bm.build_gazetteer([], d)
print(len(g), "gazetteer entries:")
print(g)
sample = ("Indeed, there are many options. The Counselling BC directory lists providers. "
          "About half of clinics offer sliding scale. Living systems theory suggests families are systems. "
          "You could try Family Services of Greater Vancouver or a Lotus-style approach.")
print("matches in sample answer:", bm.gazetteer_pass(sample, g))
lb = bm.build_leaderboard([{"engine":"gemini","answer_text":sample}], g, ["Living Systems"], False, "x")
print("client_rank:", lb["client_rank"], [ (r["brand"], r["mention_count"], r["is_client"]) for r in lb["rows"]])
print("ranking axis:", bm.client_ranking_axis(lb["client_rank"], len(lb["rows"])))
