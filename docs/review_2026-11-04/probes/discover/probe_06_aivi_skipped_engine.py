"""D-C-06 probe: run_report_enrichment loops over the CONFIGURED engine list,
not the engines that actually produced answers.  An engine skipped for a
missing key (or whose every call failed) gets mentions_axis 0.0, ranking 0,
citations 0 -> AIVI 0.0 computed AND persisted to ai_visibility_index as a
real trend point; engine_transfer counts it as 'not mentioned'; the
prioritisation ranks it as the biggest 'opportunity'."""
import os, sys, tempfile, sqlite3, json
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import probe_ai_visibility as pav

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
config = {"analysis_report": {"client_domain": "livingsystems.ca", "client_name": "Living Systems",
                              "client_name_patterns": ["Living Systems"]},
          "known_brands": [], "aivi": {}, "sentiment": {"enabled": False}}
rows = [{"run_ts": "2026-11-04T00:00:00+00:00", "engine": "gemini", "model": "g", "question": "q1",
         "mentioned": True, "cited": True, "competitors_cited": [], "answer_excerpt": "",
         "answer_text": "Living Systems Counselling is an option.",
         "source_urls": ["https://livingsystems.ca/x"], "persona": None, "source": "paa"}]
# 'openai' was configured but skipped (no OPENAI_API_KEY) -> zero rows for it.
enr = pav.run_report_enrichment(rows, ["gemini", "openai"], config, {"organic_results": []},
                                "2026-11-04T00:00:00+00:00", "topic", db, None,
                                out_dir=tempfile.mkdtemp())
for eng, res in enr["aivi"]["per_engine"].items():
    print(f"AIVI {eng}: {res['aivi']} axes={res['axes']} excluded={res['excluded']}")
print("persisted ai_visibility_index rows:",
      sqlite3.connect(db).execute("select engine, aivi, mentions_axis from ai_visibility_index").fetchall())
print("all_engine_avg:", enr["aivi"]["all_engine_avg"])
print("transfer statement:", enr["transfer"].get("statement") or
      {k: v for k, v in enr["transfer"].items() if k in ("engine_count", "mentioned_count", "cited_count")})
print("prioritisation:", [(e.get("engine"), e.get("aivi")) for e in
      (enr["engine_strategy"]["prioritization"] if isinstance(enr["engine_strategy"]["prioritization"], list)
       else enr["engine_strategy"]["prioritization"].get("ranking", []))][:3])
