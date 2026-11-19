"""News hosts classify as `publisher`, and `media` keeps only social/retail.

`media` held `cbc.ca` and `vancouversun.com` beside `reddit.com`,
`youtube.com` and `amazon.ca`, so the type carried no single intent and had to
be excluded from the host inference in `intent_mapping.yml` section 1b. News
reporting answers questions, which is `informational`, so news belongs in
`publisher` — where section 1b can act on it. Four news hosts on the
2026-11-19 run (globalnews.ca, ctvnews.ca, sootoday.com, rmoutlook.com) had no
entry at all and classified as `N/A`.

Spec: review_2026-11-04, the 2026-11-19 measurement
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intent_verdict as iv
from classifiers import EntityClassifier

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "classification_rules.json")

#: Social and retail hosts. These are NOT publishers and must not become
#: intent-bearing by the back door — `media` is excluded from section 1b
#: precisely because a Reddit thread and a CBC article are not one thing.
NOT_PUBLISHERS = ("reddit.com", "youtube.com", "amazon.ca", "facebook.com")

#: The hosts that appeared as news on the 2026-11-19 run and classified N/A.
SEEN_ON_THE_RUN = ("globalnews.ca", "ctvnews.ca", "sootoday.com",
                   "rmoutlook.com")


class TestNewsHostsArePublishers(unittest.TestCase):

    def setUp(self):
        self.classifier = EntityClassifier()

    def test_the_news_hosts_from_the_run_are_no_longer_unclassified(self):
        for host in SEEN_ON_THE_RUN:
            with self.subTest(host=host):
                entity, _, _ = self.classifier.classify("www." + host, None)
                self.assertEqual(entity, "publisher")

    def test_the_broadcasters_moved_out_of_media(self):
        # These were overridden to `media` in domain_overrides.yml, and an
        # override beats the pattern lists, so moving the list entry alone
        # would have changed nothing.
        for host in ("cbc.ca", "vancouversun.com", "canadianaffairs.news"):
            with self.subTest(host=host):
                entity, _, _ = self.classifier.classify(host, None)
                self.assertEqual(entity, "publisher")

    def test_a_subdomain_of_a_news_host_is_a_publisher_too(self):
        entity, _, _ = self.classifier.classify("bc.ctvnews.ca", None)
        self.assertEqual(entity, "publisher")

    def test_social_and_retail_hosts_are_not_publishers(self):
        for host in NOT_PUBLISHERS:
            with self.subTest(host=host):
                entity, _, _ = self.classifier.classify("www." + host, None)
                self.assertNotEqual(entity, "publisher")

    def test_a_directory_host_is_still_a_directory(self):
        # directory_domains is checked before publisher_domains; this pins
        # that the new entries did not reorder that.
        entity, _, _ = self.classifier.classify("www.psychologytoday.com",
                                                None)
        self.assertEqual(entity, "directory")


class TestTheTwoListsStayDisjoint(unittest.TestCase):

    def setUp(self):
        with open(RULES_PATH, encoding="utf-8") as fh:
            self.patterns = json.load(fh)["entity_patterns"]

    def test_no_host_is_both_a_publisher_and_media(self):
        # The classifier checks publisher first, so an overlap would be a
        # silently dead `media` entry rather than an error.
        overlap = (set(self.patterns["publisher_domains"])
                   & set(self.patterns["media_domains"]))
        self.assertEqual(overlap, set())

    def test_media_holds_no_news_host(self):
        for host in self.patterns["media_domains"]:
            with self.subTest(host=host):
                self.assertNotIn("news", host)


class TestANewsHostCanNowCarryAnIntent(unittest.TestCase):
    """The point of the move: `publisher` is in section 1b, `media` is not."""

    def _rows(self, entity):
        return [{"rank": i, "title": "t", "link": "https://example.com",
                 "source": "example.com", "entity_type": entity,
                 "content_type": "Not Measured", "page_read": "no",
                 "fetch_state": "not_destination_page"}
                for i in range(1, 7)]

    def test_an_unreadable_news_page_reads_as_informational(self):
        out = iv.compute_serp_intent(organic_rows=self._rows("publisher"),
                                     has_local_pack=False,
                                     mapping=iv.load_mapping())
        self.assertEqual(out["primary_intent"], "informational")

    def test_an_unreadable_social_page_still_carries_nothing(self):
        out = iv.compute_serp_intent(organic_rows=self._rows("media"),
                                     has_local_pack=False,
                                     mapping=iv.load_mapping())
        self.assertIsNone(out["primary_intent"])


if __name__ == "__main__":
    unittest.main()
