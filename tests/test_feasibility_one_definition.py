"""One definition of the feasibility input set and of the row index.

Two producers write `keyword_feasibility` from the same SERP: the in-pipeline
pass in `serp_audit` and the standalone `run_feasibility`. They used to build
the input set differently — page order with the client's own URL included, vs
rank order with the client excluded — so the report's §5c and the play router
disagreed about the same keyword. Both now go through
`feasibility.select_competitor_das`, and every consumer indexes the rows with
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

    def _pipeline_das(self):
        return feasibility.select_competitor_das(
            self.urls[:10],
            lambda u: (self.by_url.get(u) or {}).get("da"),
            client_domain=CLIENT,
        )

    def _standalone_das(self):
        urls = run_feasibility._get_organic_urls_by_keyword(
            {"organic_results": self.rows})["kw"]
        return feasibility.select_competitor_das(
            urls,
            lambda u: (self.by_domain.get(feasibility.domain_of(u)) or {}).get("da"),
            client_domain=CLIENT,
        )

    def test_both_producers_select_the_same_das(self):
        self.assertEqual(self._pipeline_das(), self._standalone_das())

    def test_both_producers_report_the_same_row(self):
        pipeline = feasibility.compute_feasibility(35, self._pipeline_das())
        standalone = feasibility.compute_feasibility(35, self._standalone_das())
        for field in ("avg_serp_da", "gap", "feasibility_score",
                      "feasibility_status"):
            self.assertEqual(pipeline[field], standalone[field], field)

    def test_window_is_the_true_top_ten(self):
        """Ranks 11 and 12 must not enter the average."""
        das = self._pipeline_das()
        self.assertNotIn(_da_for_rank(11), das)
        self.assertNotIn(_da_for_rank(12), das)

    def test_client_is_excluded_so_the_denominator_is_nine(self):
        das = self._pipeline_das()
        self.assertEqual(len(das), 9)
        self.assertNotIn(_da_for_rank(4), das)

    def test_client_excluded_even_when_configured_with_www(self):
        das = feasibility.select_competitor_das(
            self.urls[:10],
            lambda u: (self.by_url.get(u) or {}).get("da"),
            client_domain="www." + CLIENT,
        )
        self.assertEqual(len(das), 9)

    def test_urls_without_a_da_record_are_omitted_not_zeroed(self):
        """None is not a DA of 0 (finding D-C-04)."""
        das = feasibility.select_competitor_das(
            self.urls[:10],
            lambda u: None if u.startswith("https://comp1.") else 50,
            client_domain=CLIENT,
        )
        self.assertNotIn(0, das)
        self.assertEqual(das, [50] * 8)

    def test_standalone_url_set_is_rank_ordered(self):
        shuffled = list(reversed(self.rows))
        urls = run_feasibility._get_organic_urls_by_keyword(
            {"organic_results": shuffled})["kw"]
        self.assertEqual(urls, self.urls[:10])


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


if __name__ == "__main__":
    unittest.main()
