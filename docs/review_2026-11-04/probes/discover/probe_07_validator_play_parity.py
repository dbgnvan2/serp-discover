"""D-C-07 probe: the recommended_play parity HARD-fail in brief_validation
only inspects the Section-2 block that starts `**<keyword> (N total ...)**`
and ends at the next `\\n\\n**`.  The canonical "Recommended play: <label>"
statement the prompt asks for lives in Section 7, outside that block, so a
brief that assigns the WRONG play is never caught.  Demonstrated on the real
2026-08-26 brief + its reference JSON, with the play label flipped."""
import os, sys, json, re
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import brief_data_extraction as bde, brief_validation as bv

data = json.load(open("tests/fixtures/market_analysis_reference_run.json"))
ex = bde.extract_analysis_data_from_json(data, client_domain="livingsystems.ca",
                                         client_name_patterns=["Living Systems"])
kw = "family of origin counselling"
pre = ex["keyword_profiles"][kw]["recommended_play"]
print("pre-computed play for", repr(kw), "=", pre["play"], "/", pre["label"])

report = open("content_opportunities_family_of_origin_work_20260826_2031.md", encoding="utf-8").read()
m = re.search(r"Recommended play: \*\*([^*]+)\*\*", report)
print("report's Section-7 statement:", m.group(0))
flipped = report.replace(m.group(0), "Recommended play: **Extraction play**")
assert "Recommended play: **Extraction play**" in flipped
issues = bv.validate_llm_report(flipped, ex)
play_issues = [i for i in issues if "recommended_play" in i]
print("validator play-parity issues on the FLIPPED report:", play_issues or "NONE")
print("hard failure flagged:", bv.has_hard_validation_failures(play_issues))

# Section-2 block the validator actually scans for this keyword:
sec = re.search(rf"\*\*{re.escape(kw)} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)", flipped, re.I | re.S)
print("scanned block contains 'recommended play'?:", "recommended play" in sec.group(1).lower())

# Control: put the wrong play INSIDE the Section-2 block.  Note the second
# defect: the regex is built from the yml label "Extraction play (GEO)", so
# even inside the block the bare "Extraction play" the LLM writes is missed.
for label in ("Extraction play", "Extraction play (GEO)"):
    inside = flipped.replace(f"**{kw} (134,000 total indexed results)**",
                             f"**{kw} (134,000 total indexed results)** Recommended play: {label}.")
    print(f"control, statement inside Section-2 block as {label!r}:",
          [i for i in bv.validate_llm_report(inside, ex) if "recommended_play" in i][:1] or "NONE")
print("play labels the regex is built from:", bv._load_play_vocab().get("play_labels"))
