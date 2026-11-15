"""D-C-02 probe: run_feasibility decides `da_data_available` at RUN level.
A keyword whose competitor domains all missed DA (batch failure, provider
had no record, or only the client's own domain ranked) gets
compute_feasibility(client_da, []) -> "Low Feasibility" with no numbers,
and the pivot machinery fires on it.  Also: the average is over however many
URLs had DA, with no N-of-M stated."""
import os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from unittest.mock import patch
import run_feasibility as rf
from feasibility import compute_feasibility

print("compute_feasibility(35, []) ->", compute_feasibility(35, []))

data = {"organic_results": [
    # keyword 1: three competitor URLs, DA known for all
    {"Query_Label": "A", "Source_Keyword": "kw one", "Link": "https://a.com/x", "Rank": 1},
    {"Query_Label": "A", "Source_Keyword": "kw one", "Link": "https://b.com/x", "Rank": 2},
    {"Query_Label": "A", "Source_Keyword": "kw one", "Link": "https://c.com/x", "Rank": 3},
    # keyword 2: ten competitor URLs, DA known for only ONE of them (others
    # were in a batch that 503'd / had no record)
    *[{"Query_Label": "A", "Source_Keyword": "kw two", "Link": f"https://d{i}.com/x", "Rank": i}
      for i in range(1, 11)],
    # keyword 3: only the client ranks + two domains the provider never returned
    {"Query_Label": "A", "Source_Keyword": "kw three", "Link": "https://livingsystems.ca/p", "Rank": 1},
    {"Query_Label": "A", "Source_Keyword": "kw three", "Link": "https://zz1.com/x", "Rank": 2},
    {"Query_Label": "A", "Source_Keyword": "kw three", "Link": "https://zz2.com/x", "Rank": 3},
]}
config = {"feasibility": {"client_da": 35, "neighborhoods": ["Lonsdale"], "non_profit_location": "North Vancouver"},
          "analysis_report": {"client_domain": "livingsystems.ca"}, "moz": {}}

class FakeDFS:
    def __init__(self, **kw): pass
    def get_domain_metrics(self, urls):
        known = {"https://a.com/x": 40, "https://b.com/x": 50, "https://c.com/x": 60,
                 "https://d1.com/x": 90, "https://livingsystems.ca/p": 35}
        return {u: {"da": known[u], "pa": known[u], "fetched_at": "now"} for u in urls if u in known}

with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "x", "DATAFORSEO_PASSWORD": "y"}), \
     patch.object(rf, "DataForSEOClient", FakeDFS), patch.object(rf, "DATAFORSEO_AVAILABLE", True):
    rows = rf.run_feasibility_analysis(data, config, do_pivot_serp=False)
for r in rows:
    print(f"{r['Keyword']!r:12} status={r['feasibility_status']!r:22} avg_serp_da={r['avg_serp_da']} "
          f"gap={r['gap']} pivot_status={r['pivot_status']!r} suggested={r['suggested_keyword']!r}")
