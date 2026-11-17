"""The producers must keep calling link_recovery, and the market must be one.

Source-inspection guards, in the project's established style
(tests/test_config_manager.py::TestTabInitializationOrder): a behavioural test
that re-implements a call site cannot notice the real call site dropping the
helper, which is exactly how the 2026-11-14 run shipped 81 unusable URLs.

Spec: review_2026-11-04, follow-up to the 2026-11-14 reading
"""

import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _function(name, func):
    """The source of one top-level function."""
    src = _source(name)
    start = src.index(f"def {func}(")
    rest = src[start:]
    end = re.search(r"\n(?=def |class |# ---)", rest)
    return rest[:end.start()] if end else rest


class TestEveryFetcherRecovers:
    def test_the_audit_recovers_on_both_fetch_paths(self):
        """A resumed call is a paid-for response; it needs the same treatment."""
        body = _function("serp_audit.py", "_fetch_serp_api")
        assert body.count("link_recovery.recover_response(") == 2, (
            "_fetch_serp_api must recover on the resume path and the fresh "
            "path; a wrapped link reaching either one poisons every "
            "URL-derived stage")

    def test_the_audit_keeps_the_checkpoint_raw(self):
        """Recovery happens after the save, so raw/ stays as SerpAPI sent it."""
        body = _function("serp_audit.py", "_fetch_serp_api")
        assert body.index("serp_checkpoint.save(params, results)") < body.index(
            "link_recovery.recover_response(results)")

    def test_the_pivot_fetch_recovers_too(self):
        """P5 — the same fix on every sibling call site."""
        body = _function("run_feasibility.py", "_fetch_pivot_organic_urls")
        assert "link_recovery.recover_response(data)" in body

    def test_urls_read_back_from_an_old_run_are_dropped(self):
        body = _function("run_feasibility.py", "_get_organic_urls_by_keyword")
        assert "link_recovery.is_google_redirect(url)" in body, (
            "runs written before this fix stored the wrapper; scoring it "
            "would make Google the competitor")


class TestPageLevelFiguresAreNotTakenFromTheFrontPage:
    def test_enrichment_skips_a_recovered_link(self):
        """A recovered site root is never fetched.

        Fetching it would file the front page's word count, schema and author
        signals as the ranked page's. Behavioural since review chunk D2c
        moved the gate into enrichment.enrich_row.
        """
        import enrichment

        class _Fetcher:
            called = False

            def fetch_url(self, url):
                self.__class__.called = True
                return {"status_code": 200, "content": b"<html></html>"}

        item = {"Rank": 1, "Is_Destination_Page": False}
        outcome = enrichment.enrich_row(
            item, "https://x.ca/", 1, 5, _Fetcher(), None, None, None)
        assert outcome == enrichment.NOT_DESTINATION_PAGE
        assert _Fetcher.called is False
        assert item["Word_Count"] == enrichment.NOT_MEASURED
        assert item["Fetch_Status"] == enrichment.status_text(
            enrichment.NOT_DESTINATION_PAGE)

    def test_the_flag_reaches_the_rows_enrichment_iterates(self):
        src = _source("serp_audit.py")
        assert '"Is_Destination_Page": item.get(' in src
        assert '"link_is_destination_page", True)' in src

    def test_only_one_place_writes_page_authority(self):
        """The primary pass and the pivot pass must not drift apart.

        The first version of this guard sliced the text at the first
        `item["Competitor_DA"] =` and stayed green while the pivot pass wrote
        an ungated Page Authority 180 lines further down. One definition is
        the only property a source guard can check honestly, so the writer
        lives in moz_client and the audit may only call it.
        """
        moz = _source("moz_client.py")
        assert moz.count('item["Page_Authority"]') == 1, (
            "Page Authority is written in more than one place; the gate has "
            "to hold in all of them, so there must be only one")
        assert moz.count("def write_metrics(") == 1
        audit = _source("serp_audit.py")
        assert 'item["Page_Authority"]' not in audit, (
            "the audit must write Page Authority through "
            "moz_client.write_metrics, not itself")
        assert audit.count("moz_client_mod.write_metrics(") == 2, (
            "the primary and pivot call sites")

    def test_page_authority_is_gated_but_domain_authority_is_not(self):
        """DA is a property of the domain; PA is a property of the page."""
        body = _function("moz_client.py", "write_metrics")
        assert 'item["Page_Authority"] = pa if is_page else "Not Measured"' in body
        assert 'item["Competitor_DA"] = da' in body

    def test_the_database_is_gated_with_the_row(self):
        """P43 — one value, two sinks: the .xlsx said Not Measured while the
        database kept the front page's figure."""
        body = _function("moz_client.py", "write_metrics")
        assert "save_url_moz_metrics(url, da, pa if is_page else None)" in body

    def test_the_feasibility_window_is_sliced_before_blanks_are_dropped(self):
        """P9/P31 — filtering first slides rank 11 into "the top 10"."""
        body = _function("feasibility.py", "url_window")
        assert body.index("rows[:TOP_N_FOR_FEASIBILITY]") < body.index(
            "if usable_url(r.get(\"Link\"))")
        src = _source("serp_audit.py")
        assert src.count("feasibility_module.url_window(") == 2, (
            "the primary and pivot call sites")
        assert "][:feasibility_module.TOP_N_FOR_FEASIBILITY]" not in src, (
            "a pass is slicing its own window again")


class TestOneMarket:
    def test_the_two_fallback_locations_agree(self):
        """Two modules hold the fallback; a drift is a silently wrong market."""
        import probe_ai_visibility
        import run_feasibility
        assert (probe_ai_visibility.DEFAULT_LOCATION
                == run_feasibility.DEFAULT_LOCATION)

    def test_no_module_still_falls_back_to_the_wrong_city(self):
        for name in ("serp_audit.py", "run_feasibility.py",
                     "probe_ai_visibility.py"):
            assert '"Vancouver, British Columbia, Canada"' not in _source(name), (
                f"{name} still falls back to Vancouver, which is a different "
                f"market from the client's North Vancouver")

    def test_the_shipped_config_names_one_market(self):
        """The 2026-11-14 run searched one city and scored another."""
        from config_validators import validate_config_yml
        with open(os.path.join(REPO_ROOT, "config.yml"), encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        _, _, warnings = validate_config_yml(data)
        assert not [w for w in warnings if "different market" in w], warnings

    def test_a_disagreement_is_reported(self):
        """The guard is not vacuous: it fires on the config that shipped."""
        from config_validators import validate_config_yml
        ok, errors, warnings = validate_config_yml({
            "serpapi": {"location": "Vancouver, British Columbia, Canada"},
            "feasibility": {"non_profit_location": "North Vancouver"},
        })
        assert ok and not errors, "a mismatch is a warning, not a failure"
        assert any("different market" in w for w in warnings), warnings

    def test_a_match_is_not_reported(self):
        from config_validators import validate_config_yml
        _, _, warnings = validate_config_yml({
            "serpapi": {"location": "North Vancouver,British Columbia,Canada"},
            "feasibility": {"non_profit_location": "North Vancouver"},
        })
        assert not warnings, warnings


class TestTheHandoffSaysWhatItLost:
    """Recovery collapses same-site ranked pages into one target.

    Before recovery each ranked page had its own distinct wrapper, so nothing
    collapsed — and nothing was usable either. Now two pages on one site
    arrive as the same site root: a real consequence of the fix, and one that
    must be counted rather than quietly reducing the target list (P2).
    """

    def _rows(self):
        return [
            {"Link": "https://competitor.ca", "Rank": 1, "Title": "page one",
             "Root_Keyword": "couples counselling", "Query_Label": "A",
             "Is_Destination_Page": False},
            {"Link": "https://competitor.ca", "Rank": 4, "Title": "page two",
             "Root_Keyword": "couples counselling", "Query_Label": "A",
             "Is_Destination_Page": False},
            {"Link": "https://other.ca/some-page", "Rank": 2, "Title": "three",
             "Root_Keyword": "couples counselling", "Query_Label": "A",
             "Is_Destination_Page": True},
        ]

    def _build(self):
        import handoff_writer
        return handoff_writer.build_competitor_handoff(
            self._rows(), "T", "2026-11-16T00:00:00", "livingsystems.ca", [])

    def test_the_collapse_is_logged(self, caplog):
        import logging as _logging
        with caplog.at_level(_logging.WARNING):
            self._build()
        messages = [r.getMessage() for r in caplog.records]
        assert any("could not be told apart" in m for m in messages), messages
        assert any("1 ranked page(s)" in m for m in messages), messages

    def test_a_distinct_page_is_still_its_own_target(self):
        handoff = self._build()
        urls = [t["url"] for t in handoff["targets"]]
        assert urls.count("https://competitor.ca") == 1
        assert "https://other.ca/some-page" in urls
