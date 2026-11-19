"""The host settles the intent only where the ranked page could not be read.

Google serves most organic links as an encrypted /goto wrapper, so the ranked
page cannot be read for about half the results and `content_type` stays
unmeasured. `intent_mapping.yml` section 1b reaches an intent from the host for
the entity types whose intent does not vary page to page. These tests pin the
three things that make that safe: it fires only on `page_read: "no"`, it never
raises the classification-coverage figure, and the report says how much of the
figure it accounts for.

Spec: review_2026-11-04, the 2026-11-19 measurement
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enrichment
import intent_verdict as iv


def _row(entity, page_read, rank=1, content_type="Not Measured",
         link="https://example.com", fetch_state="not_destination_page"):
    return {"rank": rank, "title": "t", "link": link, "source": link,
            "entity_type": entity, "content_type": content_type,
            "page_read": page_read, "fetch_state": fetch_state}


def _verdict(rows, **kw):
    return iv.compute_serp_intent(organic_rows=rows, has_local_pack=False,
                                  mapping=iv.load_mapping(), **kw)


class TestItFiresOnlyWhenThePageWasNotRead(unittest.TestCase):

    def test_an_unread_directory_host_carries_an_intent(self):
        out = _verdict([_row("directory", "no", rank=i) for i in range(1, 7)])
        self.assertEqual(out["primary_intent"], "commercial_investigation")
        self.assertEqual(out["evidence"]["host_inferred_classified_count"], 6)

    def test_a_page_that_was_read_and_came_back_untypable_is_still_dropped(self):
        # "We looked and it told us nothing" is a different fact from "we never
        # looked": the first keeps its drop, or reading a page would be worse
        # than not reading it.
        out = _verdict([_row("directory", "yes", rank=i, content_type="other")
                        for i in range(1, 7)])
        self.assertIsNone(out["primary_intent"])
        self.assertEqual(out["evidence"]["classified_organic_url_count"], 0)
        self.assertEqual(out["evidence"]["host_inferred_classified_count"], 0)

    def test_a_row_that_never_said_is_not_read_as_unread(self):
        # An analysis JSON written before `page_read` existed carries no such
        # key. Unknown is not a terminal value (P1): the row keeps exactly the
        # treatment it had before these rules were written.
        rows = [_row("directory", "no", rank=i) for i in range(1, 7)]
        for row in rows:
            del row["page_read"]
        out = _verdict(rows)
        self.assertIsNone(out["primary_intent"])
        self.assertEqual(out["evidence"]["host_inferred_classified_count"], 0)


class TestThePageReadStateReadsTheFetchState(unittest.TestCase):
    """`enrichment.page_read_state` is what turns a run's fetch states into
    the three values the rule table keys on, so each one is pinned here."""

    def test_only_enriched_means_the_page_was_read(self):
        self.assertEqual(enrichment.page_read_state(enrichment.ENRICHED), "yes")

    def test_every_unread_state_means_the_page_was_not_read(self):
        for state in enrichment.UNREAD_STATES:
            with self.subTest(state=state):
                self.assertEqual(enrichment.page_read_state(state), "no")

    def test_a_blocked_page_was_not_read(self):
        # A 403 is not a reading of the page. Counting it as read would deny
        # the host inference to the rows that most need it.
        self.assertEqual(enrichment.page_read_state(enrichment.BLOCKED), "no")

    def test_an_absent_or_unrecognised_state_is_unknown(self):
        for value in (None, "", "   ", "something_new"):
            with self.subTest(value=value):
                self.assertEqual(enrichment.page_read_state(value), "unknown")

    def test_it_is_not_case_sensitive(self):
        self.assertEqual(enrichment.page_read_state("Enriched"), "yes")


class TestOnlyTheTypesWhoseIntentDoesNotVary(unittest.TestCase):

    def test_an_unread_counselling_host_is_not_guessed(self):
        # A practice's own site may rank with a blog post or a services page —
        # informational or transactional. The host does not settle it.
        out = _verdict([_row("counselling", "no", rank=i) for i in range(1, 7)])
        self.assertIsNone(out["primary_intent"])
        self.assertEqual(out["evidence"]["host_inferred_classified_count"], 0)

    def test_an_unread_media_host_is_not_guessed(self):
        # `media` is social hosts and retail as well as news, so it carries no
        # one intent. Every media row in the 2026-11-19 run was facebook.com.
        out = _verdict([_row("media", "no", rank=i) for i in range(1, 7)])
        self.assertIsNone(out["primary_intent"])

    def test_the_client_own_unread_page_is_still_navigational(self):
        # The domain-role overrides sit above section 1b and must keep winning.
        rows = [_row("directory", "no", rank=i,
                     link="https://livingsystems.ca/x") for i in range(1, 7)]
        out = _verdict(rows, client_domain="livingsystems.ca")
        self.assertEqual(out["primary_intent"], "navigational")
        self.assertEqual(out["evidence"]["host_inferred_classified_count"], 0)


class TestItNeverInflatesCoverage(unittest.TestCase):

    def test_coverage_counts_pages_not_host_inferences(self):
        # Ten unread directory rows give a verdict, and still say that none of
        # the page evidence was read.
        out = _verdict([_row("directory", "no", rank=i) for i in range(1, 11)])
        self.assertEqual(out["primary_intent"], "commercial_investigation")
        self.assertEqual(out["evidence"]["page_evidence_classified_count"], 0)
        self.assertEqual(out["classification_coverage"], "low")

    def test_the_two_counts_sum_to_the_classified_total(self):
        rows = [_row("directory", "no", rank=1),
                _row("directory", "yes", rank=2, content_type="guide"),
                _row("government", "no", rank=3),
                _row("counselling", "no", rank=4)]
        ev = _verdict(rows)["evidence"]
        self.assertEqual(
            ev["page_evidence_classified_count"]
            + ev["host_inferred_classified_count"],
            ev["classified_organic_url_count"])

    def test_the_breakdown_names_the_state_each_inference_came_from(self):
        rows = [_row("directory", "no", rank=1, fetch_state="blocked"),
                _row("directory", "no", rank=2,
                     fetch_state="not_destination_page")]
        ev = _verdict(rows)["evidence"]
        self.assertEqual(ev["host_inferred_by_fetch_state"],
                         {"blocked": 1, "not_destination_page": 1})


class TestTheReportSaysSo(unittest.TestCase):

    def _profiles(self, total, classified, host_inferred, by_state, unread):
        return {"kw": {"serp_intent": {"evidence": {
            "organic_url_count": total,
            "classified_organic_url_count": classified,
            "host_inferred_classified_count": host_inferred,
            "host_inferred_by_fetch_state": by_state,
        }}, "extractability": {"fetch_coverage": {"by_state": unread}}}}

    def test_the_line_states_how_many_came_from_the_host(self):
        line = enrichment.classification_coverage_line(
            self._profiles(10, 6, 4, {"not_destination_page": 4},
                           {"not_destination_page": 8}))
        self.assertIn("6 of 10", line)
        self.assertIn("4 of those", line)
        self.assertIn("from the site alone", line)

    def test_a_run_with_no_host_inference_says_nothing_about_it(self):
        line = enrichment.classification_coverage_line(
            self._profiles(10, 6, 0, {}, {"blocked": 4}))
        self.assertNotIn("from the site alone", line)
        self.assertIn("6 of 10", line)
        # and no double space where the clause would have gone
        self.assertNotIn("  ", line)

    def test_a_cause_is_not_counted_against_a_row_it_classified(self):
        # 8 rows were unread; 4 of them were classified from the host anyway.
        # Those 4 are not part of the deficit, so they are not among its
        # causes either: the causes must come to the deficit, not past it.
        line = enrichment.classification_coverage_line(
            self._profiles(10, 6, 4, {"not_destination_page": 4},
                           {"not_destination_page": 8}))
        self.assertIn("4 × the link resolved to the site root", line)
        self.assertNotIn("8 × the link resolved", line)


class TestTheRuleTableIsValidated(unittest.TestCase):

    def test_an_invalid_page_read_value_is_refused(self):
        import tempfile
        import yaml
        mapping = {"version": 1, "rules": [
            {"match": {"content_type": "any", "entity_type": "any",
                       "local_pack": "any", "domain_role": "any",
                       "page_read": "nope"},
             "intent": "informational"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".yml",
                                         delete=False) as fh:
            yaml.safe_dump(mapping, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError) as caught:
                iv.load_mapping(path)
            self.assertIn("page_read", str(caught.exception))
        finally:
            os.unlink(path)

    def test_the_shipped_table_loads(self):
        rules = iv.load_mapping()["rules"]
        inferring = [r for r in rules
                     if (r.get("match") or {}).get("page_read") == "no"]
        self.assertTrue(inferring, "section 1b should be present")
        for rule in inferring:
            self.assertIn(rule["match"]["entity_type"],
                          ("directory", "government", "publisher"))


class TestWhatThisDoesNotCover(unittest.TestCase):

    def test_a_read_page_on_a_known_directory_host_is_still_dropped(self):
        # Recorded, not endorsed: the same site classifies differently
        # depending on whether its page happened to be fetchable. Widening the
        # host rule to read-but-unmappable pages is the owner's editorial call
        # (2026-11-19 measurement, adjacent finding).
        read = _verdict([_row("directory", "yes", rank=i, content_type="other")
                         for i in range(1, 7)])
        unread = _verdict([_row("directory", "no", rank=i)
                           for i in range(1, 7)])
        self.assertIsNone(read["primary_intent"])
        self.assertEqual(unread["primary_intent"], "commercial_investigation")


if __name__ == "__main__":
    unittest.main()
