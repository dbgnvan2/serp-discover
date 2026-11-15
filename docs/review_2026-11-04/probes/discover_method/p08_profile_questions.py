import sys, os, collections
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-discover"); os.chdir("/Users/davemini2/ProjectsLocal/serp-discover")
import yaml, profile_questions, probe_ai_visibility as pav
profiles = yaml.safe_load(open("client_profiles.yml"))
prof = profiles.get("living_systems") or list(profiles.values())[0]
qs = profile_questions.generate(prof)
print("profile questions generated:", len(qs))
print("by persona:", collections.Counter(q["persona"] for q in qs))
print("by intent:", collections.Counter(q["intent"] for q in qs))
# What does build_question_set keep at max_questions=20 and ceiling 60/3 engines?
import json
data = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
kept = pav.build_question_set(data, [], "Vancouver", 20, profile_questions=qs)
print("kept at max_questions=20:", len(kept), collections.Counter(q.get("persona") for q in kept))
print("first 5:", [q["query"] for q in kept[:5]])
print("order of personas in kept:", [q.get("persona") for q in kept])
