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

# --- FLIPPED by review chunk D3b (D-M-18, D3.8) ---------------------------
# Before: generate() emitted all 22 prospective_client questions first, so the
# max_questions=20 cap asked 20 prospective_client questions and none of the
# other two personas. Their per-persona mention rate then showed "no data" —
# a cap reading as a finding about those personas.
from collections import Counter as _Counter
from profile_questions import interleave_by_persona

generated = _Counter(q["persona"] for q in qs)
kept_counts = _Counter(q["persona"] for q in kept)
print("\ngenerated:", dict(generated))
print("asked at max_questions=20:", dict(kept_counts))
assert set(kept_counts) == set(generated), (
    "every persona that generated a question must be asked at least one")
for persona, total in generated.items():
    assert kept_counts[persona] >= min(total, 20 // len(generated)), \
        f"{persona} got {kept_counts[persona]} of a fair share"
first = [q["persona"] for q in kept[:len(generated)]]
assert len(set(first)) == len(generated), f"the first questions round-robin: {first}"

print("\nOK — the cap costs every persona a question, not the last personas "
      "all of theirs.")
