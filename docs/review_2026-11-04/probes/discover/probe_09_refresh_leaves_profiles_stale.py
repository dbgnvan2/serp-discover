"""D-C-09 probe: refresh_analysis_outputs.py re-classifies organic_results[*].Entity_Type
only.  keyword_profiles (serp_intent, entity_distribution, entity_label,
recommended_play), ai_overview_citations, and the markdown report are left as
they were, so the JSON now contradicts itself and the regenerated market report
(which reads keyword_profiles from the JSON) still shows the pre-override verdicts.
Also shows D-C-10: the pipeline looks overrides up by the raw netloc
(www.<domain>), so an override keyed by the bare domain never applies."""
import os, sys, json, shutil, tempfile, yaml
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import refresh_analysis_outputs as rao
from classifiers import EntityClassifier

tmp = tempfile.mkdtemp()
src = "tests/fixtures/market_analysis_reference_run.json"
jpath = os.path.join(tmp, "market_analysis_x.json"); shutil.copy(src, jpath)
d = json.load(open(jpath))
kw = "family of origin counselling"
before_rows = [(r["Link"], r["Entity_Type"]) for r in d["organic_results"] if r["Source_Keyword"] == kw][:30]
before_profile = {k: d["keyword_profiles"][kw][k] for k in ("entity_distribution", "entity_label")}
before_intent = d["keyword_profiles"][kw]["serp_intent"]["primary_intent"], d["keyword_profiles"][kw]["serp_intent"]["evidence"]["classified_organic_url_count"]

# A user approves overrides that flip every N/A row for this keyword to 'legal'.
ov = yaml.safe_load(open("domain_overrides.yml")) or {}
from urllib.parse import urlparse
for link, et in before_rows:
    if et == "N/A":
        ov[urlparse(link).netloc.lower().replace("www.", "")] = "legal"
ov_path = os.path.join(tmp, "domain_overrides.yml"); yaml.safe_dump(ov, open(ov_path, "w"))

res = rao.refresh_analysis_outputs(jpath, os.path.join(tmp, "none.xlsx"), ov_path, os.path.join(tmp, "cand.md"))
print("refresh result:", res)
d2 = json.load(open(jpath))
after_rows = [(r["Link"], r["Entity_Type"]) for r in d2["organic_results"] if r["Source_Keyword"] == kw][:30]
print("rows changed N/A->legal:", sum(1 for (l1, a), (l2, b) in zip(before_rows, after_rows) if a != b))
after_profile = {k: d2["keyword_profiles"][kw][k] for k in ("entity_distribution", "entity_label")}
print("keyword_profiles.entity_distribution before:", before_profile["entity_distribution"])
print("keyword_profiles.entity_distribution after :", after_profile["entity_distribution"],
      "<- unchanged" if before_profile == after_profile else "")
print("serp_intent (primary, classified_count) after refresh:",
      d2["keyword_profiles"][kw]["serp_intent"]["primary_intent"],
      d2["keyword_profiles"][kw]["serp_intent"]["evidence"]["classified_organic_url_count"],
      "(before:", before_intent, ")")

# D-C-10 www. lookup
ec = EntityClassifier(override_file=ov_path)
print("\nclassify('havencollective.ca')     ->", ec.classify("havencollective.ca", None)[0])
print("classify('www.havencollective.ca') ->", ec.classify("www.havencollective.ca", None)[0],
      "  <- what serp_audit passes (urlparse(url).netloc)")
