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

# --- FLIPPED by review chunk D3b (D-M-14, D3.10/D3.11) --------------------
# Before: 40 entries including "Indeed", "LinkedIn", "Pathways" and other bare
# generic words harvested from competitor Source labels. "Indeed" matched
# "Indeed, there are many options" in the sample answer above and took a
# leaderboard rank beside a real competitor; two brands on one mention each
# tied, and the alphabetical sort decided which was "rank 1".
import yaml
cfg = yaml.safe_load(open("/Users/davemini2/ProjectsLocal/serp-discover/config.yml"))
stoplist = cfg["ai_visibility"]["generic_source_stoplist"]

for word in ("Indeed", "Pathways"):
    assert word not in g, f"{word} is a generic token, not a brand"
assert "Family Services of Greater Vancouver" in g, "real brands are kept"
assert bm.gazetteer_pass(sample, g) == ["Family Services of Greater Vancouver"], \
    "'Indeed, there are many options' is not a mention of a brand"

g_stopped = bm.build_gazetteer([], d, generic_source_stoplist=stoplist)
dropped = sorted(set(g) - set(g_stopped))
print("\nfurther dropped by the editorial stoplist:", dropped)
assert "ZipRecruiter" in g, "a single token that IS its own domain is a brand"

# Competition ranking: a tie shares a rank and says so.
tie_answer = "Alpha Counselling and Beta Counselling both help."
tie = bm.build_leaderboard([{"engine": "gemini", "answer_text": tie_answer}],
                           ["Alpha Counselling", "Beta Counselling"], [], False, "x")
print("tie ranks:", [(r["brand"], r["rank"], r["tied_with"]) for r in tie["rows"]])
assert [r["rank"] for r in tie["rows"]] == [1, 1], "equal counts share a rank"
assert all(r["tied_with"] == 1 for r in tie["rows"])

print("\nOK — a generic word is not a brand, and a tie is not a win.")
