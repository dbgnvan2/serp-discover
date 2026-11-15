"""D-C-03 probe: DataForSEO bulk_ranks returns `"rank": null` for a domain it
has no backlink data for.  dataforseo_client coerces that to DA 0, returns it
as a real metric, and caches it for 30 days.  A second client instance then
serves DA=0 from cache without calling the API."""
import os, sys, tempfile, sqlite3
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from unittest.mock import patch, MagicMock
import dataforseo_client as dfs

resp = MagicMock(); resp.ok = True; resp.status_code = 200
resp.json.return_value = {"tasks": [{"status_code": 20000, "result": [{"items": [
    {"target": "known.com", "rank": 44},
    {"target": "unknown-new-site.ca", "rank": None},
]}]}]}
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "x", "DATAFORSEO_PASSWORD": "y"}), \
     patch.object(dfs, "_post_with_transient_retry", return_value=resp) as post:
    c = dfs.DataForSEOClient(db_path=db)
    out = c.get_domain_metrics(["https://known.com/a", "https://unknown-new-site.ca/b"])
    print("first call result:", out, "| posts:", post.call_count)
    c2 = dfs.DataForSEOClient(db_path=db)
    out2 = c2.get_domain_metrics(["https://unknown-new-site.ca/b"])
    print("second call (fresh client) result:", out2, "| posts:", post.call_count)
print("cache rows:", sqlite3.connect(db).execute("select domain, domain_authority from da_cache").fetchall())
from feasibility import compute_feasibility
print("feasibility with that fabricated 0 alongside two DA-70 sites:", compute_feasibility(35, [70, 70, 0]))
print("feasibility with the unknown site omitted:", compute_feasibility(35, [70, 70]))
