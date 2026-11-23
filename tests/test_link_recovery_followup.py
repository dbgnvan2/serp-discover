"""The second pass over the link-recovery change: one guard per finding.

The cold learning-qa pass over the first commit of this chunk found eight
places where a wrapped or blanked link still reached a consumer that treated
it as a measurement. Each test here pins one of them.

Spec: review_2026-11-04, follow-up to the 2026-11-14 reading
"""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_data_extraction  # noqa: E402
import config_validators  # noqa: E402
import feasibility  # noqa: E402
import generate_domain_override_candidates as candidates  # noqa: E402
import link_recovery  # noqa: E402
import moz_client  # noqa: E402
import query_variants  # noqa: E402
import refresh_analysis_outputs as refresh  # noqa: E402
import serp_checkpoint  # noqa: E402

WRAPPED = ("https://www.google.com/goto?url=CAESlAEBxCJF1-Le4zy3xkV3yRj6t4a"
           "YDUJsRXVKxDrurH7eFUzV-w0QUxCMg4JE")


class TestAStoredWrapperIsNotADomain:
    """A run written before the fix stored the wrapper in Link."""

    def test_normalize_domain_refuses_a_wrapper(self):
        assert candidates.normalize_domain(WRAPPED) == ""
        assert candidates.normalize_domain(
            "https://www.yellowpages.ca/x") == "yellowpages.ca"

    def test_the_override_queue_excludes_wrapped_rows_and_says_so(self, capsys):
        rows = {"organic_results": [
            {"Link": WRAPPED, "Source_Keyword": "k1", "Rank": 1},
            {"Link": WRAPPED, "Source_Keyword": "k2", "Rank": 2},
            {"Link": WRAPPED, "Source_Keyword": "k3", "Rank": 3},
        ]}
        found = candidates.collect_candidates(
            rows, {}, MagicMock(classify=lambda *a: ("directory", 0.9, "x")))
        assert not [c for c in found if "google" in c["domain"]], found
        printed = capsys.readouterr().out
        assert "3 of 3 organic row(s)" in printed, printed

    def test_a_reclassification_keeps_an_unknown_rather_than_writing_na(self):
        """P1 — overwriting an existing type with "N/A" makes unknown terminal."""
        classifier = MagicMock(classify=lambda *a: ("directory", 0.9, "x"))
        row = {"Link": WRAPPED, "Entity_Type": "competitor"}
        assert refresh.classify_domain_for_row(classifier, row) == "competitor"


class TestAnUnresolvedCitationIsNotProofOfAbsence:
    """P1/P14 — "client not cited" must come from links that were read."""

    def _probe(self, citations):
        return query_variants.execute_situational_probes(
            [{"query": "q", "source_keyword": "k", "probe_source": "paa"}],
            "run1",
            lambda query, run_id, idx: {"ai_overview": {"references": citations}},
            client_domain="livingsystems.ca",
            request_delay=0)

    def test_a_blanked_citation_is_counted_not_ignored(self):
        probe_rows, _ = self._probe([{"title": "t", "link": "", "source": "X"}])
        assert probe_rows[0]["Client_Cited"] is False
        assert probe_rows[0]["Citations_Unresolved"] == 1

    def test_a_resolved_citation_leaves_the_count_at_zero(self):
        probe_rows, _ = self._probe(
            [{"title": "t", "link": "https://livingsystems.ca/x", "source": "LS"}])
        assert probe_rows[0]["Client_Cited"] is True
        assert probe_rows[0]["Citations_Unresolved"] == 0

    def test_the_count_is_logged_when_nothing_was_established(self, caplog):
        with caplog.at_level(logging.WARNING):
            self._probe([{"title": "t", "link": "", "source": "X"}])
        assert any("no resolvable host" in r.getMessage()
                   for r in caplog.records), [r.getMessage() for r in caplog.records]

    def test_the_count_reaches_the_brief_data(self):
        """P43 — the qualifier has to travel with the flag to its consumer."""
        analysis = brief_data_extraction._build_aio_trigger_analysis(
            [], [{"Executed_Query": "q", "Word_Count": 4,
                  "Has_AI_Overview": True, "Client_Cited": False,
                  "Citations_Unresolved": 2}])
        assert analysis["probe_results"][0]["citations_unresolved"] == 2


class TestTheArchiveSaysItIsNotRaw:
    def test_the_written_copy_is_annotated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = {"organic_results": [{"link": "https://a.ca"}]}
        serp_checkpoint.save_raw_json("r1", "google", data)
        written = json.loads(
            (tmp_path / "raw" / "r1" / "google_response.json").read_text())
        assert "link_recovery" in written["_post_processing"]
        assert written["organic_results"] == data["organic_results"]

    def test_the_live_response_does_not_gain_the_key(self, tmp_path, monkeypatch):
        """The run reads this dict after the archive is written."""
        monkeypatch.chdir(tmp_path)
        data = {"organic_results": []}
        serp_checkpoint.save_raw_json("r1", "google", data)
        assert "_post_processing" not in data


class TestTheMarketComparisonReadsEveryFieldBothNameTogether:
    def _warnings(self, searched, scored):
        _, _, warnings = config_validators.validate_config_yml({
            "serpapi": {"location": searched},
            "feasibility": {"non_profit_location": scored},
        })
        return [w for w in warnings if "different market" in w]

    def test_a_region_disagreement_is_caught(self):
        """Comparing the first field alone passed a city in another country."""
        assert self._warnings("North Vancouver,Washington,United States",
                              "North Vancouver,British Columbia,Canada")

    def test_an_abbreviated_region_does_not_false_fire(self):
        """"North Vancouver, BC" is the same market, differently spelled."""
        assert not self._warnings("North Vancouver,British Columbia,Canada",
                                  "North Vancouver, British Columbia")

    def test_a_city_only_setting_still_compares_the_city(self):
        assert self._warnings("Vancouver,British Columbia,Canada",
                              "North Vancouver")
        assert not self._warnings("North Vancouver,British Columbia,Canada",
                                  "North Vancouver")


class TestAlreadyLocalIsMatchedOnWordBoundaries:
    @pytest.mark.parametrize("keyword,city,expected", [
        ("therapy for bayside families", "North Bay", False),
        ("counselling in north bay", "North Bay", True),
        ("counselling in bay", "North Bay", True),
        ("couples counselling vancouver", "North Vancouver", True),
        ("couples counselling", "North Vancouver", False),
        ("vancouverite therapy", "North Vancouver", False),
    ])
    def test_a_substring_is_not_a_place(self, keyword, city, expected):
        """A bare `in` test sent "bayside" queries out with no location."""
        assert query_variants.names_place(keyword, city) is expected

    def test_the_audit_uses_the_shared_test(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "serp_audit.py"), encoding="utf-8").read()
        # Since query_location_fix QL.2 the audit reaches names_place through
        # the shared query builder, which Bing uses too.
        assert "query_variants.build_query_term(" in src
        import query_variants
        assert "names_place(keyword, city)" in open(query_variants.__file__, encoding="utf-8").read()
        assert "phrase in keyword.lower()" not in src


class TestASettledErrorIsNotRetried:
    """Consequence tests since review chunk Y8 moved the loop into
    `serp_fetch`: a settled error must spend one paid call, not the whole
    budget, which is the fact the old source guard stood in for (P27)."""

    def _calls_for(self, error_text):
        import pytest
        import http_retry
        import serp_fetch

        calls = []

        class _Search:
            def __init__(self, params):
                pass

            def get_dict(self):
                calls.append(1)
                return {"error": error_text}

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(http_retry, "SERPAPI_RETRY_ATTEMPTS", 3)
            monkeypatch.setattr(serp_fetch.time, "sleep", lambda s: None)
            monkeypatch.setattr(serp_fetch.serp_checkpoint, "lookup",
                                lambda params: None)
            out = serp_fetch.fetch({"q": "x"}, timeout_seconds=5,
                                   client=_Search, available=True)
        finally:
            monkeypatch.undo()
        return out, len(calls)

    def test_a_parameter_error_aborts_rather_than_backing_off(self):
        """Three retries on "unsupported location" spend the search allowance."""
        for error_text in ("Unsupported location parameter",
                           "Invalid location provided",
                           "Invalid parameter: num"):
            out, calls = self._calls_for(error_text)
            assert out is None
            assert calls == 1, (
                f"{error_text!r} is settled, so it must spend one paid call, "
                f"not {calls}")

    def test_a_transient_error_still_spends_the_budget(self):
        out, calls = self._calls_for("Google hasn't returned any results")
        assert out is None
        assert calls == 3


class TestTheExtractedHelpersBehave:
    """The wiring guards prove one definition; these prove what it does."""

    def test_page_authority_is_withheld_for_a_site_root(self):
        storage = MagicMock()
        rows = [{"Link": "https://a.ca", "Is_Destination_Page": False},
                {"Link": "https://b.ca/page", "Is_Destination_Page": True}]
        moz_client.write_metrics(
            rows,
            {"https://a.ca": {"da": 70, "pa": 55},
             "https://b.ca/page": {"da": 40, "pa": 31}},
            storage, True)
        assert rows[0]["Competitor_DA"] == 70
        assert rows[0]["Page_Authority"] == "Not Measured"
        assert rows[1]["Page_Authority"] == 31
        storage.save_url_moz_metrics.assert_any_call("https://a.ca", 70, None)
        storage.save_url_moz_metrics.assert_any_call("https://b.ca/page", 40, 31)

    def test_a_row_with_no_moz_result_is_left_alone(self):
        rows = [{"Link": "https://a.ca"}, {"Link": ""}]
        moz_client.write_metrics(rows, {}, MagicMock(), True)
        assert "Competitor_DA" not in rows[0]

    def test_the_window_is_the_top_n_rows_not_the_top_n_usable_ones(self):
        """P9/P31 — filtering first slides rank 11 into "the top 10"."""
        rows = [{"Link": "N/A" if i <= 3 else f"https://r{i}.ca"}
                for i in range(1, 15)]
        window = feasibility.url_window(rows)
        assert len(window.urls) == feasibility.TOP_N_FOR_FEASIBILITY - 3, window
        assert "https://r11.ca" not in window.urls, (
            "rank 11 was pulled into the window to replace a blank")
        # D2a: the three unresolved positions are reported, not discarded —
        # the denominator a mean is quoted over is the window, not the
        # usable rows.
        assert (window.unresolved, window.window) == (
            3, feasibility.TOP_N_FOR_FEASIBILITY), window

    def test_the_hole_is_reported(self):
        logged = []
        feasibility.url_window(
            [{"Link": ""}] + [{"Link": f"https://r{i}.ca"} for i in range(9)],
            "'x' feasibility", logged.append)
        assert logged and "1 of the top 10" in logged[0], logged
