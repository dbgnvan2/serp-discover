"""D5 — the demand and exposure figures say what they measure.

Review: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md
Plan:   docs/review_2026-11-04/PLAN_D5_demand_and_exposure.md

One guard per finding fixed (effort tier Full, fix-batch ceiling):

* D-M-15 — the sponge and the reformat shortlist were read off tiny
  denominators, and "below the median" shortlisted half of any set whether or
  not an AI Overview was there at all (D5.1, D5.2).
* D-M-17 — traffic "at risk" was modelled clicks, uncapped by the clicks the
  property actually receives (D5.3).
* D-M-16 — the branded click share was a share of whatever keywords the run
  looked at, and the reference bands had no stated origin (D5.4).
* D-M-20 — the AIO trend differenced runs covering different keywords; three
  modelled constants were called industry reference points with no source; and
  the GSC pull answered for every country and device while the SERP it is
  compared against is one of each (D5.5, D5.6, D5.7).
"""
import sqlite3
import unittest
from unittest.mock import patch

import aio_exposure
import gsc_client
import gsc_demand
import run_gsc_analysis as rga
from demand_dashboard import compute_dashboard


def _row(query, ctr, position=3.0, aio=False, impressions=500, clicks=5):
    return {"query": query, "source_keyword": query, "query_label": "A",
            "found": True,
            "gsc_status": gsc_client.STATUS_MEASURED, "has_ai_overview": aio,
            "clicks": clicks, "impressions": impressions, "ctr": ctr,
            "position": position}


class TestD5SpongeNeedsRealTraffic(unittest.TestCase):
    """D-M-15 / D5.1 + D5.2."""

    def test_thresholds_are_editorial_and_both_gates_bite(self):
        # Both figures come from config, and a bad value degrades (P4).
        resolved = rga.resolve_sponge_thresholds(
            {"gsc": {"min_impressions": 100, "reformat_ctr_margin": 0.4}})
        self.assertEqual(resolved["min_impressions"], 100)
        self.assertEqual(resolved["reformat_ctr_margin"], 0.4)
        junk = rga.resolve_sponge_thresholds({"gsc": {"min_impressions": "lots"}})
        self.assertEqual(junk["min_impressions"], rga.DEFAULT_MIN_IMPRESSIONS)

        rows = [_row("starving", 0.005, aio=True, impressions=800),
                _row("three impressions", 0.001, aio=True, impressions=3),
                _row("no aio but below median", 0.01, impressions=900),
                # Below the median, but only 10% below it — inside the margin.
                _row("barely below median", 0.045, aio=True, impressions=900),
                _row("healthy", 0.05, impressions=900),
                _row("healthy two", 0.06, impressions=900)]
        sponge = rga.compute_sponge_effect(rows, min_impressions=50)
        # The 3-impression row is excluded from the medians and counted.
        self.assertEqual(sponge["queries_below_impression_floor"], 1)
        self.assertEqual(sponge["min_impressions"], 50)

        names = [c["query"] for c in rga.find_reformat_candidates(
            rows, sponge, set(), min_impressions=50, ctr_margin=0.25)]
        # Shortlisted: an AI Overview is present, the traffic is real, and the
        # CTR is a stated margin below the no-AIO median — not merely below it.
        self.assertIn("starving", names)
        self.assertNotIn("three impressions", names)     # too little traffic
        self.assertNotIn("no aio but below median", names)   # no AIO to blame
        # Below the median is not a finding on its own: half of any set is.
        self.assertNotIn("barely below median", names)

    def test_report_prints_the_floor_and_the_margin(self):
        rows = [_row("starving", 0.005, aio=True, impressions=800),
                _row("healthy", 0.05, impressions=900),
                _row("healthy two", 0.06, impressions=900)]
        sponge = rga.compute_sponge_effect(rows, min_impressions=50)
        candidates = rga.find_reformat_candidates(
            rows, sponge, set(), min_impressions=50, ctr_margin=0.25)
        report = rga.generate_report(rows, sponge, candidates,
                                     {"gsc": {"property": "sc-domain:x.ca"}},
                                     "market_analysis_t_20260101_0000.json",
                                     ("2026-01-01", "2026-03-31"))
        self.assertIn("50 impressions", report)
        # The margin printed is the one the run used, read from config, not
        # re-derived from the output rows (cold review 7): with no candidates
        # there is no row to read it off.
        no_candidates = rga.generate_report(
            rows, sponge, [], {"gsc": {"property": "sc-domain:x.ca",
                                       "reformat_ctr_margin": 0.4}},
            "market_analysis_t_20260101_0000.json", ("2026-01-01", "2026-03-31"))
        self.assertIn("40%", no_candidates)
        self.assertIn("25", report)                      # the margin, stated
        # The sponge is an association between two groups of queries, not a
        # measured effect of the AI Overview on this property.
        self.assertIn("association", report.lower())


class TestD5AtRiskIsBoundedByMeasuredClicks(unittest.TestCase):
    """D-M-17 / D5.3."""

    @staticmethod
    def _db(rows):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "serp_data.db")
        with sqlite3.connect(path) as conn:
            conn.execute('''CREATE TABLE gsc_cache (
                query TEXT, start_date TEXT, end_date TEXT, clicks INTEGER,
                impressions INTEGER, ctr REAL, position REAL, found INTEGER,
                fetched_at TEXT, filters TEXT)''')
            for query, clicks, impressions in rows:
                conn.execute(
                    "INSERT INTO gsc_cache (query, clicks, impressions, ctr, "
                    "position, start_date, end_date, found, fetched_at, filters) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    # GSC's ctr is exactly clicks/impressions; a fixture that
                    # breaks that cannot distinguish two formulas.
                    (query, clicks, impressions,
                     (clicks / impressions) if impressions else 0.0, 1.0,
                     "2026-01-01", "2026-03-31", 1, "2026-03-31T00:00", ""))
            conn.commit()
        return path

    @staticmethod
    def _profile(cited=False):
        return {"has_ai_overview": True, "client_rank": 1,
                "client_aio_cited": cited, "aio_top_sources": []}

    def test_estimate_is_a_share_of_the_clicks_that_exist(self):
        db = self._db([("anxiety therapy", 5, 1000)])
        dash = compute_dashboard(
            {"anxiety therapy": self._profile()}, {}, db_path=db)
        # 1000 impressions x the 0.168 CTR-point loss would be 168 clicks at
        # risk on a query with 5 clicks. The figure is the interception share
        # (0.60) applied to the measured clicks: 3.0.
        self.assertEqual(dash["est_traffic_at_risk"], 3.0)

    def test_being_cited_halves_the_share_and_the_window_is_printed(self):
        import demand_dashboard
        db = self._db([("anxiety therapy", 5, 1000), ("cited kw", 5, 1000),
                       ("no clicks", 0, 5000)])
        profiles = {"anxiety therapy": self._profile(),
                    "cited kw": self._profile(cited=True),
                    "no clicks": self._profile()}
        dash = compute_dashboard(profiles, {}, db_path=db)
        # Only the not-cited keyword with clicks contributes: 5 x 0.60.
        self.assertEqual(dash["est_traffic_at_risk"], 3.0)
        self.assertEqual([d["keyword"] for d in dash["keywords_at_risk"]],
                         ["anxiety therapy"])
        # Impressions with no clicks: nothing to intercept, but named, because
        # it is the most exposed case, not an absence.
        self.assertEqual(dash["zero_click_at_risk"], ["no clicks"])
        self.assertEqual(dash["gsc_window"]["start"], "2026-01-01")
        body = "\n".join(demand_dashboard.render_dashboard_section(dash))
        self.assertIn("2026-01-01", body)
        self.assertIn("2026-03-31", body)
        self.assertIn("no clicks", body)


class TestD5BrandedShareIsAboutTheProperty(unittest.TestCase):
    """D-M-16 / D5.4."""

    CFG = {"analysis_report": {"client_name_patterns": ["living systems"]}}

    def test_property_rows_drive_the_band_and_tracked_stays_beside_it(self):
        tracked = [{"query": "living systems counselling", "found": True,
                    "clicks": 9, "impressions": 100},
                   {"query": "family therapy", "found": True,
                    "clicks": 1, "impressions": 100}]
        property_rows = {
            "living systems counselling": {"clicks": 9, "impressions": 100},
            "family therapy": {"clicks": 1, "impressions": 100},
            "anxiety help north vancouver": {"clicks": 90, "impressions": 900},
        }
        _, score = gsc_demand.compute_demand(
            [dict(r) for r in tracked], self.CFG, property_rows=property_rows)
        self.assertEqual(score["branded_click_share"], 0.9)          # tracked
        self.assertEqual(score["property_branded_click_share"], 0.09)
        self.assertEqual(score["band_basis"], "property")
        self.assertEqual(score["benchmark_band"], "avg")             # from 9%
        body = "\n".join(gsc_demand.render_demand_section(score))
        self.assertIn("every query the property got clicks on", body)
        self.assertIn("withholds rare queries", body)
        self.assertIn("tracked queries only", body)

    def test_no_property_rows_says_so_rather_than_passing_tracked_off(self):
        tracked = [{"query": "living systems counselling", "found": True,
                    "clicks": 9, "impressions": 100},
                   {"query": "family therapy", "found": True,
                    "clicks": 1, "impressions": 100}]
        _, score = gsc_demand.compute_demand(tracked, self.CFG)
        self.assertEqual(score["band_basis"], "tracked")
        self.assertFalse(score["property_available"])
        body = "\n".join(gsc_demand.render_demand_section(score))
        self.assertIn("No property-wide figure", body)

    def test_property_figure_stands_without_a_tracked_measurement(self):
        """Cold review 4 — the keyword file matching no clicking query is the
        case the property share exists for, not a reason to print nothing."""
        tracked = [{"query": "family therapy", "found": True,
                    "clicks": 0, "impressions": 100}]
        property_rows = {
            "living systems counselling": {"clicks": 9, "impressions": 100},
            "anxiety help": {"clicks": 91, "impressions": 900},
        }
        _, score = gsc_demand.compute_demand(
            tracked, self.CFG, property_rows=property_rows,
            filters={"text": "country CAN, desktop only"})
        self.assertTrue(score["property_available"])
        self.assertFalse(score["data_available"])
        self.assertEqual(score["benchmark_band"], "avg")
        body = "\n".join(gsc_demand.render_demand_section(score))
        self.assertNotIn("No branded share this run", body)
        # Cold review 6 — the figure says which searchers it is about, and
        # that Search Console withholds rare queries.
        self.assertIn("country CAN, desktop only", body)
        self.assertIn("withholds rare queries", body)
        self.assertEqual(score["property_query_count"], 2)

    def test_bands_state_where_they_come_from(self):
        self.assertIn("assumption", gsc_demand.band_source({}))
        cited = {"gsc_demand": {"bands": {"source": "Acme 2026, retrieved 2026-03-01"}}}
        self.assertEqual(gsc_demand.band_source(cited),
                         "Acme 2026, retrieved 2026-03-01")
        _, score = gsc_demand.compute_demand(
            [{"query": "living systems", "found": True, "clicks": 1,
              "impressions": 10}], {**self.CFG, **cited})
        self.assertIn("Acme 2026",
                      "\n".join(gsc_demand.render_demand_section(score)))


class TestD5ExposureComparesLikeWithLike(unittest.TestCase):
    """D-M-20 / D5.5 + D5.6 + D5.7."""

    def test_trend_only_differences_runs_with_the_same_keyword_set(self):
        import tempfile, os
        db = os.path.join(tempfile.mkdtemp(), "serp_data.db")
        def _rows(*keywords):
            return [{"keyword": k, "source": "google", "aio_present": 1,
                     "client_cited": 0, "cited_urls_json": "[]",
                     "organic_position": 1, "est_ctr_loss": 0.168,
                     "weights_json": "{}"} for k in keywords]
        aio_exposure.save_aio_exposure(db, "20260101_0000", _rows("a", "b"))
        aio_exposure.save_aio_exposure(db, "20260102_0000", _rows("a"))
        aio_exposure.save_aio_exposure(db, "20260103_0000", _rows("a", "b"))
        trend = aio_exposure.get_aio_exposure_trend(db, limit=5)
        self.assertEqual([p["comparable"] for p in trend], [True, False, True])
        lines = aio_exposure._trend_lines(trend)
        body = "\n".join(lines)
        # The Δ skips the odd run out and names it.
        self.assertIn("20260101_0000", body)
        self.assertIn("20260102_0000 is excluded", body)
        self.assertIn("b", body)

    def test_modelled_constants_state_their_origin(self):
        caveat = aio_exposure.estimate_caveat({})
        self.assertIn("assumption", caveat)
        self.assertNotIn("industry reference point", caveat.lower())
        cited = {"aio_exposure": {"sources": {
            "aio_ctr_multiplier": "Acme CTR study 2026-02",
            "citation_credit": "Acme CTR study 2026-02",
            "ctr_curve": "Acme CTR study 2026-02"}}}
        self.assertIn("Acme CTR study 2026-02", aio_exposure.estimate_caveat(cited))

    def test_pull_is_restricted_to_the_serp_fetch_population(self):
        cfg = {"serpapi": {"gl": "ca", "device": "desktop"}}
        resolved = gsc_client.resolve_query_filters(cfg)
        self.assertEqual(resolved["country"], "can")
        self.assertEqual(resolved["device"], "DESKTOP")
        self.assertEqual(resolved["warnings"], [])
        # Explicitly switched off, and said so.
        off = gsc_client.resolve_query_filters(
            {**cfg, "gsc": {"country": "all", "device": "all"}})
        self.assertIsNone(off["country"])
        self.assertIn("every country", gsc_client.filters_text(off))
        # An unmappable code is reported, never guessed.
        bad = gsc_client.resolve_query_filters({"gsc": {"country": "Canadaland"}})
        self.assertIsNone(bad["country"])
        self.assertTrue(bad["warnings"])

    def test_filters_travel_in_the_request_and_the_cache_key(self):
        import tempfile, os
        db = os.path.join(tempfile.mkdtemp(), "serp_data.db")
        client = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=db, token_provider=lambda: "tok",
            filters={"country": "can", "device": "DESKTOP"})
        payloads = []

        class _Resp:
            ok = True
            status_code = 200
            def json(self):
                return {"rows": [{"keys": ["family therapy"], "clicks": 3,
                                  "impressions": 100, "ctr": 0.03,
                                  "position": 4.0}]}

        def _post(url, headers=None, json=None, timeout=None):
            payloads.append(json)
            return _Resp()

        with patch("gsc_client.requests.post", _post):
            stats = client.get_query_stats(
                ["family therapy"], "2026-01-01", "2026-03-31")
        self.assertEqual(
            payloads[0]["dimensionFilterGroups"],
            [{"filters": [{"dimension": "country", "operator": "equals",
                           "expression": "can"},
                          {"dimension": "device", "operator": "equals",
                           "expression": "DESKTOP"}]}])
        self.assertIn("family therapy", stats.stats)
        # A client pulling every country must not be served those rows.
        unfiltered = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=db, token_provider=lambda: "tok")
        cached, absent, to_fetch = unfiltered._cache_lookup(
            ["family therapy"], "2026-01-01", "2026-03-31")
        self.assertEqual(to_fetch, ["family therapy"])
        self.assertEqual(cached, {})

    def test_absence_names_the_population_it_is_absent_from(self):
        """Cold review 1 — "no impressions" under a desktop-only pull is no
        impressions for desktop searchers, not a fact about the client."""
        rows = [_row("family therapy", 0.03, impressions=900),
                {"query": "mobile only kw", "query_label": "A",
                 "source_keyword": "mobile only kw", "found": False,
                 "gsc_status": gsc_client.STATUS_MEASURED_ABSENT,
                 "has_ai_overview": False}]
        sponge = rga.compute_sponge_effect(rows, min_impressions=50)
        report = rga.generate_report(
            rows, sponge, [], {"gsc": {"property": "sc-domain:x.ca"},
                               "serpapi": {"gl": "ca", "device": "desktop"}},
            "market_analysis_t_20260101_0000.json", ("2026-01-01", "2026-03-31"),
            filters={"country": "can", "device": "DESKTOP"})
        self.assertIn("no impressions recorded in the window for country CAN, "
                      "desktop only", report)
        self.assertIn("no impressions in window for country CAN, desktop only",
                      report)

    def test_dashboard_reads_only_the_configured_population(self):
        """Cold review 2 — the dashboard reads the same cache, so it must not
        sum an unfiltered row and a filtered one into one click total."""
        import os, tempfile
        from demand_dashboard import compute_dashboard as _dash
        db = os.path.join(tempfile.mkdtemp(), "serp_data.db")
        with sqlite3.connect(db) as conn:
            conn.execute('''CREATE TABLE gsc_cache (
                query TEXT, start_date TEXT, end_date TEXT, clicks INTEGER,
                impressions INTEGER, ctr REAL, position REAL, found INTEGER,
                fetched_at TEXT, filters TEXT)''')
            conn.executemany(
                "INSERT INTO gsc_cache (query, clicks, impressions, ctr, "
                "position, start_date, end_date, found, fetched_at, filters) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [("filtered kw", 10, 1000, 0.01, 1.0, "2026-01-01",
                  "2026-03-31", 1, "2026-03-31T00:00", "can|DESKTOP"),
                 ("unfiltered kw", 90, 9000, 0.01, 1.0, "2026-01-01",
                  "2026-03-31", 1, "2026-03-31T00:00", "")])
            conn.commit()
        profiles = {k: {"has_ai_overview": True, "client_rank": 1,
                        "client_aio_cited": False, "aio_top_sources": []}
                    for k in ("filtered kw", "unfiltered kw")}
        cfg = {"serpapi": {"gl": "ca", "device": "desktop"}}
        dash = _dash(profiles, cfg, db_path=db)
        self.assertEqual(dash["total_clicks"], 10)       # not 100
        self.assertEqual(dash["matched_query_count"], 1)
        self.assertIn("country CAN", dash["gsc_population"])
        # With the filter off, the other row is the one that answers.
        off = _dash(profiles, {**cfg, "gsc": {"country": "all", "device": "all"}},
                    db_path=db)
        self.assertEqual(off["total_clicks"], 90)

    def test_cache_holds_both_filter_variants(self):
        """Cold review 8 — `filters` is in the primary key, so one
        configuration's write does not evict the other's row."""
        import os, tempfile
        db = os.path.join(tempfile.mkdtemp(), "serp_data.db")
        filtered = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=db, token_provider=lambda: "t",
            filters={"country": "can", "device": "DESKTOP"})
        plain = gsc_client.GscClient(
            "sc-domain:x.ca", db_path=db, token_provider=lambda: "t")
        filtered._cache_store(
            {"kw": {"clicks": 1, "impressions": 10, "ctr": 0.1,
                    "position": 3.0}}, "2026-01-01", "2026-03-31")
        plain._cache_store(
            {"kw": {"clicks": 50, "impressions": 500, "ctr": 0.1,
                    "position": 3.0}}, "2026-01-01", "2026-03-31")
        self.assertEqual(
            filtered._cache_lookup(["kw"], "2026-01-01", "2026-03-31")[0]
            ["kw"]["clicks"], 1)
        self.assertEqual(
            plain._cache_lookup(["kw"], "2026-01-01", "2026-03-31")[0]
            ["kw"]["clicks"], 50)
        # An unrecognised 3-letter code is never sent: GSC would accept it,
        # return nothing, and every query would cache as a measured absence.
        bad = gsc_client.resolve_query_filters({"gsc": {"country": "zzz"}})
        self.assertIsNone(bad["country"])
        self.assertTrue(bad["warnings"])

    def test_report_names_the_population_beside_the_window(self):
        rows = [_row("family therapy", 0.03, impressions=900)]
        sponge = rga.compute_sponge_effect(rows, min_impressions=50)
        report = rga.generate_report(
            rows, sponge, [], {"gsc": {"property": "sc-domain:x.ca"},
                               "serpapi": {"gl": "ca", "device": "desktop"}},
            "market_analysis_t_20260101_0000.json", ("2026-01-01", "2026-03-31"),
            filters={"country": "can", "device": "DESKTOP"})
        self.assertIn("country CAN", report)
        self.assertIn("desktop only", report)
        self.assertNotIn("Mixed populations", report)
        unfiltered = rga.generate_report(
            rows, sponge, [], {"gsc": {"property": "sc-domain:x.ca"},
                               "serpapi": {"gl": "ca", "device": "desktop"}},
            "market_analysis_t_20260101_0000.json", ("2026-01-01", "2026-03-31"))
        self.assertIn("Mixed populations", unfiltered)


if __name__ == "__main__":
    unittest.main()
