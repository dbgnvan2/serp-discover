"""D-C-02 probe (FIXED in D2b, commit pending).

Before: GscClient._fetch_all_rows broke on an HTTP error / network failure and
returned {} (partial). get_query_stats then wrote found=0 for EVERY unfetched
query, so a 503 / expired token / 403 was cached as "measured absent" for
cache_ttl_days; a retry inside the TTL made no request and reported every
query as 'no GSC data'.

After: the fetch reports itself incomplete, nothing is cached as an absence,
the retry asks again, and the report prints 'not reached' for a query the
fetch never resolved. Run it to see the three expectations below hold.
The same three are pinned as tests in tests/test_d2b_failure_is_not_absence.py."""
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
          "<- must be 1; 0 would mean the outage was served from cache")

# What run_gsc_analysis then prints for the user
import run_gsc_analysis as rga
rows = [{"query": "couples counselling", "query_label": "A", "source_keyword": "couples counselling",
         "has_ai_overview": True}]
for row in rows:
    row["found"] = False
    row["gsc_status"] = gsc_client.STATUS_NOT_REACHED
report = rga.generate_report(
    rows, rga.compute_sponge_effect(rows, not_reached=1), [], {"gsc": {}},
    "x.json", ("a", "b"), fetch_complete=False)
for line in report.splitlines():
    if "not reached" in line or "could not reach" in line or "Incomplete" in line:
        print("report line:", line)
assert "reported as absent, not as zero" not in report, \
    "an unreached query must not be reported as measured absence"
