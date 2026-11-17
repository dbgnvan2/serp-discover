"""D-C-05 / D-M-03 probe (FLIPPED by chunk D3a): an engine that answered
nothing is not measured.

Before: `run_report_enrichment` looped over the CONFIGURED engine list, so an
engine skipped for a missing key (or whose every call failed) got
mentions_axis 0.0, ranking 0 and citations 0 -> AIVI 0.0, persisted to
ai_visibility_index as a real trend point, averaged into all_engine_avg, and
ranked FIRST in the prioritisation as the biggest opportunity.

After: it gets no AIVI row, no place in the average, and is named in
`engines_unmeasured` / the prioritisation's `not_measured` list instead.
"""
import os, sys, tempfile, sqlite3
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import probe_ai_visibility as pav

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
config = {"analysis_report": {"client_domain": "livingsystems.ca", "client_name": "Living Systems",
                              "client_name_patterns": ["Living Systems"]},
          "known_brands": [], "aivi": {}, "sentiment": {"enabled": False}}
rows = [{"run_ts": "2026-11-04T00:00:00+00:00", "engine": "gemini", "model": "g", "question": "q1",
         "status": pav.STATUS_ANSWERED, "failure_reason": None,
         "mentioned": True, "cited": True, "competitors_cited": [], "answer_excerpt": "",
         "answer_text": "Living Systems Counselling is an option.",
         "source_urls": ["https://livingsystems.ca/x"], "persona": None, "source": "paa"}]
# 'openai' was configured but skipped (no OPENAI_API_KEY) -> zero rows for it.
enr = pav.run_report_enrichment(
    rows, ["gemini", "openai"], config, {"organic_results": []},
    "2026-11-04T00:00:00+00:00", "topic", db, None, out_dir=tempfile.mkdtemp(),
    skipped=[{"engine": "openai", "reason": "OPENAI_API_KEY not set"}],
    questions_planned=1)

per_engine = enr["aivi"]["per_engine"]
for eng, res in per_engine.items():
    print(f"AIVI {eng}: {res['aivi']} axes={res['axes']} excluded={res['excluded']}")
persisted = sqlite3.connect(db).execute(
    "select engine, aivi, mentions_axis from ai_visibility_index").fetchall()
print("persisted ai_visibility_index rows:", persisted)
print("all_engine_avg:", enr["aivi"]["all_engine_avg"],
      "over", enr["aivi"]["all_engine_avg_n"], "engine(s)")
print("engines_measured:", enr["aivi"]["engines_measured"])
print("engines_unmeasured:", [(e["engine"], e["reason"]) for e in enr["aivi"]["engines_unmeasured"]])
print("prioritisation:", [e["engine"] for e in enr["engine_strategy"]["prioritization"]])
print("not_measured:", [(e["engine"], e["reason"]) for e in enr["engine_strategy"]["not_measured"]])

assert "openai" not in per_engine, "openai was not measured — it must carry no AIVI"
assert [r[0] for r in persisted] == ["gemini"], "an unmeasured engine must persist no row"
assert enr["aivi"]["all_engine_avg"] == 100.0, "the average is over the measured engine only"
assert enr["aivi"]["all_engine_avg_n"] == 1
assert [e["engine"] for e in enr["aivi"]["engines_unmeasured"]] == ["openai"]
assert "OPENAI_API_KEY" in enr["aivi"]["engines_unmeasured"][0]["reason"]
assert "openai" not in [e["engine"] for e in enr["engine_strategy"]["prioritization"]], \
    "an unmeasured engine must not be ranked as an opportunity"
assert "openai" in [e["engine"] for e in enr["engine_strategy"]["not_measured"]]
assert not enr["transfer"].get("measurable"), \
    "one measured engine cannot carry a cross-engine transfer verdict"
print("\nOK — an engine that answered nothing carries no score.")
