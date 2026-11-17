"""D-C-08 probe (FIXED in D2c).

Before: EntityClassifier.classify looked the SERP host up in
domain_overrides.yml verbatim, so `www.havencollective.ca` was classified
`N/A` although the file carries `havencollective.ca`. 35 of the 121 overrides
answered for one spelling of the host and not the other, and the refresh path
and the candidate report (which both stripped `www.`) disagreed with the
pipeline.

After: domain_utils.normalize_domain is the one definition, applied to the
override keys at load and to the host before lookup. Run this to see every
override answer for both spellings."""
import os, sys, yaml
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from classifiers import EntityClassifier
from domain_utils import normalize_domain
import generate_domain_override_candidates as candidates
import brief_data_extraction as bde

overrides = yaml.safe_load(open("domain_overrides.yml")) or {}
ec = EntityClassifier()
differing = [d for d in overrides
             if ec.classify("www." + str(d), None)[0] != ec.classify(str(d), None)[0]]
print(f"overrides: {len(overrides)}; differing between 'x' and 'www.x': {len(differing)}")
print("havencollective.ca     ->", ec.classify("havencollective.ca", None)[0])
print("www.havencollective.ca ->", ec.classify("www.havencollective.ca", None)[0])
assert differing == [], "every override must answer for both spellings"

print("\nthe two wrong ways to strip the prefix, both of which shipped here:")
print("  lstrip('www.') on 'wellness.ca'      ->", "wellness.ca".lstrip("www."),
      "| normalize_domain ->", normalize_domain("wellness.ca"))
print("  replace('www.','') on 'findwww.x.com' ->", "findwww.x.com".replace("www.", ""),
      "| normalize_domain ->", normalize_domain("findwww.x.com"))
assert normalize_domain("wellness.ca") == "wellness.ca"
assert normalize_domain("findwww.x.com") == "findwww.x.com"

print("\nthe three producers now agree on one host:")
for name, value in (("candidate report", candidates.normalize_domain("https://WWW.X.ca/a")),
                    ("brief extractor", bde._extract_domain("https://WWW.X.ca/a")),
                    ("classifier lookup", normalize_domain("https://WWW.X.ca/a"))):
    print(f"  {name:18s} -> {value}")
assert len({candidates.normalize_domain("https://WWW.X.ca/a"),
            bde._extract_domain("https://WWW.X.ca/a"),
            normalize_domain("https://WWW.X.ca/a")}) == 1
