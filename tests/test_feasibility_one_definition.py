"""One definition of the feasibility input set and of the row index.

Two producers write `keyword_feasibility` from the same SERP: the in-pipeline
pass in `serp_audit` and the standalone `run_feasibility`. They used to build
the input set differently — page order with the client's own URL included, vs
rank order with the client excluded — so the report's §5c and the play router
disagreed about the same keyword. Both now go through
`feasibility.competitor_da_window`, and every consumer indexes the rows with
`feasibility.index_feasibility_by_keyword`.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md chunk D1
(finding D-C-19).
"""

import unittest

import feasibility
import run_feasibility


CLIENT = "livingsystems.ca"


def _ranked_rows(n=12, client_rank=4):
    """n organic rows in absolute-rank order; the client sits at client_rank."""
    rows = []
    for rank in range(1, n + 1):
        if rank == client_rank:
            link = f"https://www.{CLIENT}/page-{rank}"
        else:
            link = f"https://comp{rank}.example/page-{rank}"
        rows.append({"Rank": rank, "Link": link, "Query_Label": "A",
                     "Source_Keyword": "kw"})
    return rows


#: Deliberately distinct per rank so a wrong window changes the mean.
def _da_for_rank(rank):
    return 10 + rank


class TestOneInputSet(unittest.TestCase):

    def setUp(self):
        self.rows = _ranked_rows()
        self.urls = [r["Link"] for r in self.rows]
        # Pipeline shape: Moz results keyed by the exact URL fetched.
        self.by_url = {r["Link"]: {"da": _da_for_rank(r["Rank"])}
                       for r in self.rows}
        # Standalone shape: DA keyed by bare domain.
        self.by_domain = {feasibility.domain_of(r["Link"]): {"da": _da_for_rank(r["Rank"])}
                          for r in self.rows}

    def _pipeline_window(self):
        return feasibility.competitor_da_window(
            self.urls[:10],
            lambda u: (self.by_url.get(u) or {}).get("da"),
            client_domain=CLIENT,
        )

    def _standalone_window(self):
        window = run_feasibility._get_organic_urls_by_keyword(
            {"organic_results": self.rows})["kw"]
        return feasibility.competitor_da_window(
            window,
            lambda u: (self.by_domain.get(feasibility.domain_of(u)) or {}).get("da"),
            client_domain=CLIENT,
        )

    def test_both_producers_select_the_same_das(self):
        """The values and the coverage both, since D2a publishes both."""
        self.assertEqual(self._pipeline_window(), self._standalone_window())

    def test_both_producers_report_the_same_row(self):
        pipeline = feasibility.compute_feasibility(35, self._pipeline_window())
        standalone = feasibility.compute_feasibility(35, self._standalone_window())
        for field in ("avg_serp_da", "gap", "feasibility_score",
                      "feasibility_status", "da_count", "da_missing"):
            self.assertEqual(pipeline[field], standalone[field], field)

    def test_window_is_the_true_top_ten(self):
        """Ranks 11 and 12 must not enter the average."""
        das = self._pipeline_window().das
        self.assertNotIn(_da_for_rank(11), das)
        self.assertNotIn(_da_for_rank(12), das)

    def test_client_is_excluded_so_the_denominator_is_nine(self):
        window = self._pipeline_window()
        self.assertEqual(len(window.das), 9)
        self.assertEqual((window.measured, window.missing, window.window),
                         (9, 0, 9))
        self.assertNotIn(_da_for_rank(4), window.das)

    def test_client_excluded_even_when_configured_with_www(self):
        window = feasibility.competitor_da_window(
            self.urls[:10],
            lambda u: (self.by_url.get(u) or {}).get("da"),
            client_domain="www." + CLIENT,
        )
        self.assertEqual(window.measured, 9)

    def test_urls_without_a_da_record_are_omitted_not_zeroed(self):
        """None is not a DA of 0 (finding D-C-04), and the hole is counted."""
        window = feasibility.competitor_da_window(
            self.urls[:10],
            lambda u: None if u.startswith("https://comp1.") else 50,
            client_domain=CLIENT,
        )
        self.assertNotIn(0, window.das)
        self.assertEqual(window.das, [50] * 8)
        self.assertEqual((window.measured, window.missing, window.window),
                         (8, 1, 9))

    def test_standalone_url_set_is_rank_ordered(self):
        shuffled = list(reversed(self.rows))
        window = run_feasibility._get_organic_urls_by_keyword(
            {"organic_results": shuffled})["kw"]
        self.assertEqual(window.urls, self.urls[:10])
        self.assertEqual((window.unresolved, window.window), (0, 10))


class TestRowIndexIsFirstWins(unittest.TestCase):

    def test_ai_alternative_row_does_not_overwrite_the_primary(self):
        rows = [
            {"Keyword": "kw", "Query_Label": "A", "avg_serp_da": 20.0},
            {"Keyword": "kw", "Query_Label": "A.1", "avg_serp_da": 55.0},
        ]
        indexed = feasibility.index_feasibility_by_keyword(rows)
        self.assertEqual(indexed["kw"]["Query_Label"], "A")
        self.assertEqual(indexed["kw"]["avg_serp_da"], 20.0)

    def test_pivot_rows_are_not_a_keywords_verdict(self):
        rows = [{"Keyword": "kw pivot", "Query_Label": "P"}]
        self.assertEqual(feasibility.index_feasibility_by_keyword(rows), {})

    def test_lower_case_query_label_key_is_honoured(self):
        rows = [{"keyword_text": "kw", "query_label": "P"}]
        self.assertEqual(feasibility.index_feasibility_by_keyword(rows), {})

    def test_brief_data_extraction_delegates_to_the_one_definition(self):
        import brief_data_extraction
        rows = [
            {"Keyword": "kw", "Query_Label": "A", "avg_serp_da": 20.0},
            {"Keyword": "kw", "Query_Label": "A.1", "avg_serp_da": 55.0},
        ]
        self.assertEqual(
            brief_data_extraction.index_feasibility_by_keyword(rows),
            feasibility.index_feasibility_by_keyword(rows),
        )


class TestReportRendersOneRowPerKeyword(unittest.TestCase):

    def test_section_5c_does_not_duplicate_a_keyword(self):
        import generate_insight_report
        rows = [
            {"Keyword": "kw", "Query_Label": "A", "client_da": 35,
             "avg_serp_da": 20.0, "gap": -15.0,
             "feasibility_status": "High Feasibility"},
            {"Keyword": "kw", "Query_Label": "A.1", "client_da": 35,
             "avg_serp_da": 55.0, "gap": 20.0,
             "feasibility_status": "Low Feasibility"},
        ]
        indexed = generate_insight_report.index_feasibility_by_keyword(rows)
        self.assertEqual(len(indexed), 1)
        self.assertEqual(indexed["kw"]["feasibility_status"],
                         "High Feasibility")


class TestEveryProducerUsesTheSharedHelper(unittest.TestCase):
    """Source-inspection guards, in the style of
    ``tests/test_config_manager.py::TestTabInitializationOrder``.

    The behavioural tests above re-implement each call site by hand, so they
    prove the helper is deterministic — not that the producers still call it.
    They stayed green while serp_audit's pivot pass kept its own inline
    comprehension, which averaged the client in as its own competitor.
    """

    def _src(self, name):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / name).read_text()

    def test_serp_audit_has_no_inline_da_comprehension(self):
        src = self._src("serp_audit.py")
        self.assertEqual(src.count("feasibility_module.competitor_da_window"),
                         2,
                         "both feasibility passes must use the shared helper")
        self.assertNotIn('for v in pivot_moz.values() if v.get("da")', src)

    def test_run_feasibility_has_no_inline_da_comprehension(self):
        src = self._src("run_feasibility.py")
        self.assertEqual(src.count("feasibility_module.competitor_da_window"),
                         2,
                         "the primary and pivot passes must both use it")
        self.assertNotIn('[v["da"] for v in pivot_da_data.values()]', src)

    def test_the_window_size_is_not_pre_sliced_with_a_literal(self):
        """Raising TOP_N_FOR_FEASIBILITY must actually widen the window.

        Both producers sliced to a literal 10 before calling the helper, so
        lowering the constant worked and raising it silently did nothing. The
        window now lives in ``feasibility.url_window``; serp_audit must take
        no slice of its own, and the one definition must use the constant.
        """
        audit = self._src("serp_audit.py")
        self.assertNotIn("][:10]", audit)
        self.assertNotIn("[:feasibility_module.TOP_N_FOR_FEASIBILITY]", audit,
                         "the window is feasibility.url_window's to take; a "
                         "pass slicing again applies it twice")
        self.assertIn("rows[:TOP_N_FOR_FEASIBILITY]",
                      self._src("feasibility.py"))
        for sig in ("max_urls: int = feasibility_module.TOP_N_FOR_FEASIBILITY",
                    "max_per_keyword: int = feasibility_module.TOP_N_FOR_FEASIBILITY"):
            self.assertIn(sig, self._src("run_feasibility.py"))

    def test_an_unmeasured_keyword_still_gets_a_row(self):
        """serp_audit used to append nothing when no DA was measured, so the
        keyword vanished from §5b with no record that it was attempted."""
        src = self._src("serp_audit.py")
        self.assertNotIn('if competitor_das and query_label == "A":', src)
        self.assertIn('if query_label == "A":', src)


if __name__ == "__main__":
    unittest.main()
