"""D-C-20 probe (FIXED in D2c).

Before: url_enricher.fetch_url returns the body of a 403/429/5xx as readily as
a 200, and the enrichment loop's only gate was `if fetch_res:`. A Cloudflare
challenge page was therefore classified and measured as the ranked page: its
six words became Word_Count, its missing byline became Author_Present False,
and both fed extractability, E-E-A-T and foundational accessibility. The
status reached SQLite only.

After: a response at or above 400 is recorded and not read. The row carries
Fetch_Status, the page-level fields read Not Measured, and 'N of M pages
blocked' reaches the Parsing_Warnings sheet."""
import os, sys
from unittest.mock import MagicMock, patch
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import enrichment, url_enricher

head = MagicMock(); head.headers = {"Content-Type": "text/html"}
get = MagicMock(); get.status_code = 403; get.headers = {"Content-Type": "text/html"}
get.content = b"<html><head><title>Just a moment...</title></head><body><h1>Checking your browser</h1></body></html>"
real = url_enricher.UrlEnricher()
with patch.object(url_enricher.requests, "head", return_value=head), \
        patch.object(url_enricher.requests, "get", return_value=get):
    fetched = real.fetch_url("https://psychologytoday.com/x")
print("fetch_url on a 403 still returns the body:", fetched["status_code"],
      len(fetched["content"]), "bytes")
print("what extract_features reads off it:",
      {k: real.extract_features(fetched).get(k)
       for k in ("word_count_est", "author_present", "question_heading_count")})


class _Storage:
    rows = []
    def save_url_features(self, url, status, ctype, schema, words, ev):
        self.rows.append((status, ctype, words))
    def save_domain_features(self, domain, etype):
        pass


for status in (200, 403, 429, 503, None):
    enricher = MagicMock()
    enricher.fetch_url.return_value = (None if status is None else dict(fetched, status_code=status))
    enricher.extract_features.return_value = {
        "soup": None, "word_count_est": 6, "author_present": False,
        "schema_types": [], "faq_present": False, "question_heading_count": 0,
        "question_headings": [], "intro_text_length": 0,
        "published_time": None, "modified_time": None,
        "credential_hits": [], "review_marker_present": False}
    content = MagicMock(); content.classify.return_value = ("article", 0.9, [])
    entity = MagicMock(); entity.classify.return_value = ("directory", 0.9, [])
    item = {"Rank": 1, "Is_Destination_Page": True, "_domain": "psychologytoday.com"}
    outcome = enrichment.enrich_row(item, "https://psychologytoday.com/x", 1, 5,
                                    enricher, content, entity, _Storage())
    print(f"  status {str(status):5s} -> outcome {outcome:12s} "
          f"Word_Count={item['Word_Count']!r:14s} Fetch_Status={item['Fetch_Status']!r}")
    if status is not None and status >= 400:
        assert outcome == enrichment.BLOCKED
        assert item["Word_Count"] == enrichment.NOT_MEASURED
        assert "Author_Present" not in item, "nothing is taken from an error page"

print("blocked count for the reader:",
      enrichment.status_text("blocked_warning", blocked=3, attempted=5))
print("statuses recorded in SQLite:", _Storage.rows)
