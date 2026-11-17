"""Does a configured-but-skipped engine get an AIVI of 0 persisted / reported?"""
import sys, json, os, tempfile, sqlite3, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover")
os.chdir("/Users/davemini2/ProjectsLocal/serp-discover")
import yaml
import probe_ai_visibility as pav
cfg = yaml.safe_load(open("config.yml"))
data = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "t.db")
# Only gemini actually answered; openai & perplexity were "skipped" (no key)
rows = [
  {"run_ts":"2026-11-04T00:00:00+00:00","engine":"gemini","model":"g","question":"q1",
   "mentioned":True,"cited":True,"competitors_cited":[],"answer_excerpt":"",
   "persona":None,"source":None,
   "answer_text":"Living Systems Counselling in North Vancouver offers Bowen therapy. Indeed, Theravive lists others.",
   "source_urls":["https://livingsystems.ca/x","https://www.theravive.com/y"]},
  {"run_ts":"2026-11-04T00:00:00+00:00","engine":"gemini","model":"g","question":"q2",
   "mentioned":False,"cited":False,"competitors_cited":[],"answer_excerpt":"",
   "persona":None,"source":None,"answer_text":"Try Family Services of Greater Vancouver.","source_urls":["https://fsgv.ca/"]},
]
engines = ["gemini","openai","perplexity"]
enr = pav.run_report_enrichment(rows, engines, cfg, data, "2026-11-04T00:00:00+00:00", "t", db, None, out_dir=tmp)
for e, res in enr["aivi"]["per_engine"].items():
    print(e, "AIVI:", res["aivi"], "axes:", res["axes"], "excluded:", res["excluded"])
print("all_engine_avg:", enr["aivi"].get("all_engine_avg"))
con = sqlite3.connect(db)
print("persisted ai_visibility_index rows:", con.execute("select engine, aivi, mentions_axis from ai_visibility_index").fetchall())
print("gemini leaderboard:", [(r["brand"], r["mention_count"], r["is_client"]) for r in enr["leaderboards"]["gemini"]["rows"]])
print("transfer:", {k: v for k, v in enr.get("transfer", {}).items() if k in ("client_mentioned_engines","engines_measured","visibility_transfer","measurable","note")} if isinstance(enr.get("transfer"), dict) else enr.get("transfer"))
print("prioritization:", [e["engine"] for e in enr["engine_strategy"]["prioritization"]])
print("ENR KEYS:", list(enr.keys()))
print("transfer full:", json.dumps(enr.get("transfer"), indent=1, default=str)[:1500])
print("prio:", json.dumps(enr["engine_strategy"], default=str)[:800])
rep = pav.generate_report("tests/fixtures/market_analysis_reference_run.json", "2026-11-04T00:00:00+00:00", engines, rows, {e: [] for e in engines},
      [{"engine":"openai","reason":"OPENAI_API_KEY not set"},{"engine":"perplexity","reason":"PERPLEXITY_API_KEY not set"}], "I'm in North Vancouver, BC.", "Living Systems Counselling", enrichment=enr)
open(os.path.join(tmp,"rep.md"),"w").write(rep)
print("REPORT at", os.path.join(tmp,"rep.md"))

# --- FLIPPED by review chunk D3a ------------------------------------------
# Before: openai and perplexity were never asked (no API key), yet each got
# AIVI 0.0 persisted as a trend point, each dragged all_engine_avg down, the
# transfer section read a "moderate overlap" interpretation off their two
# empty citation sets, and the prioritisation ranked them above the one
# engine that was actually measured.
measured = enr["aivi"]["engines_measured"]
unmeasured = {e["engine"]: e["reason"] for e in enr["aivi"]["engines_unmeasured"]}
print("engines_measured:", measured)
print("engines_unmeasured:", unmeasured)
assert measured == ["gemini"]
assert set(unmeasured) == {"openai", "perplexity"}
# This probe asks nothing of openai/perplexity and passes no skip list, so
# the reason is the generic one; probe_06 covers the keyed-skip reason.
assert all("no questions were asked" == r for r in unmeasured.values()), unmeasured
assert set(enr["aivi"]["per_engine"]) == {"gemini"}
assert [r[0] for r in con.execute(
    "select engine from ai_visibility_index").fetchall()] == ["gemini"]
assert enr["aivi"]["all_engine_avg_n"] == 1
assert not enr["transfer"]["measurable"]
assert [e["engine"] for e in enr["engine_strategy"]["prioritization"]] == ["gemini"]
assert set(e["engine"] for e in enr["engine_strategy"]["not_measured"]) == {
    "openai", "perplexity"}
assert "not measured" in rep
print("\nOK — the two engines that were never asked carry no score, and the "
      "report names them.")
