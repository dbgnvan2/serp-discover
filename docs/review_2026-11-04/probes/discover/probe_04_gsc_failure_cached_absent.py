"""D-C-04 probe: GscClient._fetch_all_rows breaks on an HTTP error / network
failure and returns {} (partial).  get_query_stats then writes found=0 for
EVERY unfetched query, so a 503 / expired token / 403 is cached as
"measured absent" for cache_ttl_days.  A retry inside the TTL makes no
request and reports every query as 'no GSC data'."""
import os, sys, tempfile, sqlite3
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from unittest.mock import patch, MagicMock
import gsc_client

bad = MagicMock(); bad.ok = False; bad.status_code = 503; bad.json.return_value = {"error": "backend"}
good = MagicMock(); good.ok = True; good.status_code = 200
good.json.return_value = {"rows": [{"keys": ["couples counselling"], "clicks": 12, "impressions": 300,
                                     "ctr": 0.04, "position": 6.2}]}
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
c = gsc_client.GscClient("sc-domain:x.ca", db_path=db, token_provider=lambda: "tok")

with patch.object(gsc_client, "_post_with_transient_retry", return_value=bad) as post:
    r1 = c.get_query_stats(["couples counselling", "family therapy"], "2026-08-01", "2026-10-30")
    print("after 503:", r1, "| posts:", post.call_count)
print("cache rows now:", sqlite3.connect(db).execute(
    "select query, found, clicks from gsc_cache").fetchall())
with patch.object(gsc_client, "_post_with_transient_retry", return_value=good) as post:
    r2 = c.get_query_stats(["couples counselling", "family therapy"], "2026-08-01", "2026-10-30")
    print("retry while API is healthy:", r2, "| posts made:", post.call_count,
          "<- 0 means the outage was served from cache as 'absent'")

# What run_gsc_analysis then prints for the user
import run_gsc_analysis as rga
rows = [{"query": "couples counselling", "query_label": "A", "source_keyword": "couples counselling",
         "has_ai_overview": True}]
for row in rows:
    row["found"] = False
print("report line:", [l for l in rga.generate_report(rows, rga.compute_sponge_effect(rows), [],
      {"gsc": {}}, "x.json", ("a", "b")).splitlines() if "no GSC data" in l][0])
