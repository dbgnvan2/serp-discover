"""Two things about moz_competitor.py's cache.

(A) Diagnosis of the failing test
    test_moz_competitor.py::TestCollectionFreshness::test_cached_block_reports_when_it_was_collected_not_now
    The test rewrites fetched_at to the literal "2026-08-01T09:00:00+00:00" and
    expects a cache HIT.  The client's TTL is 30 days, so the row is a hit only
    until 2026-08-31.  Today (2026-11-04) it is 95 days old -> correct miss ->
    2 POSTs.  Test bug (time bomb), not a cache bug.

(B) D-C-10, FIXED in D2b (commit pending). Before: a block whose ranking call
    succeeded but whose anchor-text call hit a transient 5xx was stored with
    top-level status "ok" and served from cache for 30 days carrying
    anchor_texts.status == "error". The consumer (serp-compete
    anchor_coverage) counted it 'errored' on every run in that window and
    Tool 1 never retried it.

    After: caching is per signal. The failed anchor-text call is not cached,
    so the next run asks for it again — and only for it, one call, not a
    full four-call refetch of billed rows. Run this to see the second run
    make exactly one call and serve real anchor text."""
import os, sys, tempfile, sqlite3
from datetime import datetime, timedelta, timezone
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from unittest.mock import patch
import moz_competitor as mc
from moz_jsonrpc import MozRpcError

print("(A) days between hardcoded stale date and today:",
      (datetime.now(timezone.utc) - datetime(2026, 8, 1, 9, tzinfo=timezone.utc)).days,
      "; cache_ttl_days default =", mc.MozCompetitorClient.__init__.__defaults__[1])

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
calls = []
def fake_moz_call(method, data):
    calls.append(method)
    if method == mc.RANKING_KEYWORDS_METHOD:
        return {"ranking_keywords": [{"keyword": "bowen theory", "ranking_page": "/", "rank_position": 3,
                                      "difficulty": 20, "volume": 100}]}
    if method == mc.ANCHOR_TEXT_METHOD:
        raise MozRpcError("Moz API HTTP 503", status=503)      # transient
    raise MozRpcError("Action not found", status=404, code=-32601)

with patch.object(mc, "moz_call", fake_moz_call), patch.object(mc, "row_budget", return_value=None):
    c = mc.MozCompetitorClient(db_path=db, locale="en-US")
    b1 = c.fetch(["bowencenter.org"])["bowencenter.org"]
    print("(B) first fetch: status=%s data_available=%s anchor_texts.status=%s  (calls=%d)" %
          (b1["status"], b1["data_available"], b1["anchor_texts"]["status"], len(calls)))
    print("    cached row status:", sqlite3.connect(db).execute(
        "select status, anchor_texts from moz_competitor_cache").fetchall())
    calls.clear()

# Second run, API now healthy for both methods.
def healthy_moz_call(method, data):
    calls.append(method)
    if method == mc.RANKING_KEYWORDS_METHOD:
        return {"ranking_keywords": [{"keyword": "bowen theory", "ranking_page": "/",
                                      "rank_position": 3, "difficulty": 20,
                                      "volume": 100}]}
    if method == mc.ANCHOR_TEXT_METHOD:
        return {"anchor_texts": [{"text": "bowen center", "external_root_domains": 9,
                                  "external_pages": 30}]}
    raise MozRpcError("Action not found", status=404, code=-32601)

with patch.object(mc, "moz_call", healthy_moz_call), \
        patch.object(mc, "row_budget", return_value=None):
    c2 = mc.MozCompetitorClient(db_path=db, locale="en-US")
    b2 = c2.fetch(["bowencenter.org"])["bowencenter.org"]
    print("    second run (API now healthy): calls made =", len(calls), calls,
          "| served anchor_texts.status =", b2["anchor_texts"]["status"],
          "| items =", b2["anchor_texts"]["items"])
    assert calls == [mc.ANCHOR_TEXT_METHOD], \
        "only the signal that failed should be refetched"
    assert b2["anchor_texts"]["status"] == "ok"
    assert b2["ranking_keywords"]["items"], "the cached signal must still be served"
