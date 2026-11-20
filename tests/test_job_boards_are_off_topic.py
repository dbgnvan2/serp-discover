"""A job board is not a competitor — it means Google answered another query.

Covers the 2026-11-19 change that gave job boards their own entity type,
mapped them to `uncategorised`, and made the report say a keyword is off topic
rather than unmeasured when they hold the page.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classifiers
import generate_insight_report as gir
import intent_verdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rules():
    with open(os.path.join(REPO, "classification_rules.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _board_row(link="https://www.glassdoor.ca/Job/x.htm", content_type="Not Measured"):
    return {
        "link": link,
        "content_type": content_type,
        "entity_type": "job_board",
        "fetch_state": "not_destination_page",
    }


def _counselling_row(content_type="guide"):
    return {
        "link": "https://example-counselling.ca/p",
        "content_type": content_type,
        "entity_type": "counselling",
        "fetch_state": "enriched",
        "page_read": "yes",
    }


class TestTheHostsSeenOnTheRunAreClassified(unittest.TestCase):
    """Every job board the 2026-11-19 run ranked must now type as one."""

    MEASURED_HOSTS = [
        "www.glassdoor.ca",
        "www.glassdoor.co.in",
        "www.simplyhired.ca",
        "bebee.com",
        "www.jobboom.com",
        "ca.jobrapido.com",
    ]

    def test_measured_hosts_classify_as_job_board(self):
        clf = classifiers.EntityClassifier()
        for host in self.MEASURED_HOSTS:
            with self.subTest(host=host):
                entity, conf, evidence = clf.classify(host, None)
                self.assertEqual(entity, "job_board", f"{host} -> {entity}")
                self.assertIn("known_job_board_domain", evidence)

    def test_a_job_board_is_typed_without_reading_the_page(self):
        """soup=None is the encrypted-link case; the host still settles it."""
        entity, _, _ = classifiers.EntityClassifier().classify("www.glassdoor.ca", None)
        self.assertEqual(entity, "job_board")

    def test_job_board_beats_the_no_content_fallback(self):
        """Before this change these hosts fell through to `N/A`."""
        entity, _, evidence = classifiers.EntityClassifier().classify("bebee.com", None)
        self.assertNotEqual(entity, "N/A")
        self.assertNotIn("fallback_no_content", evidence)


class TestAJobBoardIsNotADirectory(unittest.TestCase):
    """The distinction the change exists to preserve."""

    def test_job_boards_are_checked_before_directories(self):
        src = open(os.path.join(REPO, "classifiers.py"), encoding="utf-8").read()
        self.assertLess(
            src.index("job_board_domains"),
            src.index('patterns.get("directory_domains"'),
            "a job board must be typed before the directory check, or an "
            "employment SERP reads as a page of therapist directories",
        )

    def test_a_therapist_directory_still_types_as_directory(self):
        entity, _, _ = classifiers.EntityClassifier().classify(
            "www.psychologytoday.com", None)
        self.assertEqual(entity, "directory")

    def test_the_two_lists_are_disjoint(self):
        """An overlapping host would be a silently dead entry in one list."""
        patterns = _rules()["entity_patterns"]
        boards = set(patterns["job_board_domains"])
        for key in ("directory_domains", "professional_association_domains",
                    "publisher_domains", "media_domains"):
            with self.subTest(list=key):
                self.assertEqual(boards & set(patterns.get(key, [])), set())

    def test_no_entry_can_never_match(self):
        """Matching sees a normalised HOST: a path or a .gc.ca host is dead."""
        for host in _rules()["entity_patterns"]["job_board_domains"]:
            with self.subTest(host=host):
                self.assertNotIn("/", host)
                self.assertFalse(host.endswith(".gc.ca"),
                                 "a .gc.ca host is settled by the TLD rule first")

    def test_an_override_does_not_already_pin_a_job_board(self):
        """Overrides are checked before every pattern list."""
        clf = classifiers.EntityClassifier()
        for host in _rules()["entity_patterns"]["job_board_domains"]:
            with self.subTest(host=host):
                self.assertNotIn(host, clf.overrides)

    def test_the_entity_type_is_declared(self):
        rules = _rules()
        self.assertIn("job_board", rules["entity_types"])
        self.assertIn("job_board", rules["entity_type_descriptions"])


class TestTheIntentIsDroppedDeliberately(unittest.TestCase):
    """No counselling-search intent exists in a job listing to infer."""

    def test_an_unread_job_board_is_uncategorised(self):
        mapping = intent_verdict.load_mapping()
        intent = intent_verdict._classify_url(
            {"content_type": "Not Measured", "entity_type": "job_board",
             "local_pack": "no", "domain_role": "other",
             "page_read": "no", "content_type_usable": "no"},
            mapping["rules"])
        self.assertEqual(intent, "uncategorised")

    def test_a_READ_job_board_is_also_uncategorised(self):
        """The host rules must not launder a read job board into an intent."""
        mapping = intent_verdict.load_mapping()
        for content_type in ("directory", "service", "guide", "news", "pdf"):
            with self.subTest(content_type=content_type):
                intent = intent_verdict._classify_url(
                    {"content_type": content_type, "entity_type": "job_board",
                     "local_pack": "yes", "domain_role": "other",
                     "page_read": "yes", "content_type_usable": "yes"},
                    mapping["rules"])
                self.assertEqual(intent, "uncategorised")

    def test_a_job_board_is_never_commercial_investigation(self):
        """The specific mis-filing this rule prevents."""
        result = intent_verdict.compute_serp_intent(
            [_board_row() for _ in range(10)], False,
            client_domain="livingsystems.ca")
        self.assertEqual(result["intent_distribution"]["commercial_investigation"], 0)
        self.assertIsNone(result["primary_intent"])

    def test_job_boards_do_not_raise_the_classified_count(self):
        rows = [_board_row() for _ in range(6)] + [_counselling_row() for _ in range(4)]
        ev = intent_verdict.compute_serp_intent(
            rows, False, client_domain="livingsystems.ca")["evidence"]
        self.assertEqual(ev["classified_organic_url_count"], 4)
        self.assertEqual(ev["uncategorised_organic_url_count"], 6)

    def test_job_boards_are_not_counted_as_host_inferred(self):
        """They are dropped, not inferred, so coverage must not move."""
        ev = intent_verdict.compute_serp_intent(
            [_board_row() for _ in range(10)], False,
            client_domain="livingsystems.ca")["evidence"]
        self.assertEqual(ev["host_inferred_classified_count"], 0)


class TestTheCountIsRecorded(unittest.TestCase):

    def test_off_topic_rows_are_counted(self):
        rows = [_board_row() for _ in range(6)] + [_counselling_row() for _ in range(4)]
        ev = intent_verdict.compute_serp_intent(
            rows, False, client_domain="livingsystems.ca")["evidence"]
        self.assertEqual(ev["off_topic_organic_url_count"], 6)
        self.assertEqual(ev["organic_url_count"], 10)

    def test_a_page_with_no_job_boards_counts_zero(self):
        ev = intent_verdict.compute_serp_intent(
            [_counselling_row() for _ in range(10)], False,
            client_domain="livingsystems.ca")["evidence"]
        self.assertEqual(ev["off_topic_organic_url_count"], 0)

    def test_the_type_list_is_editorial(self):
        """The judgement lives in the mapping file, not in Python."""
        mapping = intent_verdict.load_mapping()
        self.assertIn("job_board", mapping["off_topic_entity_types"])

    def test_a_type_added_to_the_file_is_counted(self):
        mapping = intent_verdict.load_mapping()
        mapping["off_topic_entity_types"] = ["directory"]
        ev = intent_verdict.compute_serp_intent(
            [{"link": "https://psychologytoday.com/x", "content_type": "service",
              "entity_type": "directory"}], False,
            client_domain="livingsystems.ca", mapping=mapping)["evidence"]
        self.assertEqual(ev["off_topic_organic_url_count"], 1)

    def test_a_missing_list_falls_back_rather_than_counting_nothing(self):
        mapping = intent_verdict.load_mapping()
        for broken in ({}, {"off_topic_entity_types": []},
                       {"off_topic_entity_types": "job_board"}):
            with self.subTest(broken=broken):
                self.assertEqual(
                    intent_verdict._off_topic_entity_types(broken),
                    frozenset(intent_verdict.DEFAULT_OFF_TOPIC_ENTITY_TYPES))

    def test_the_entity_type_is_matched_case_insensitively(self):
        ev = intent_verdict.compute_serp_intent(
            [{"link": "https://glassdoor.ca/x", "content_type": "Not Measured",
              "entity_type": " Job_Board "}], False,
            client_domain="livingsystems.ca")["evidence"]
        self.assertEqual(ev["off_topic_organic_url_count"], 1)


class TestTheReportSaysOffTopicNotUnknown(unittest.TestCase):

    def _profile(self, organic, off_topic, intent=None, mixed=False):
        return {"serp_intent": {
            "primary_intent": intent,
            "is_mixed": mixed,
            "evidence": {"organic_url_count": organic,
                         "off_topic_organic_url_count": off_topic}}}

    def test_a_job_board_page_reads_off_topic(self):
        action = gir._get_keyword_action(
            "family roles", self._profile(10, 6), {}, ["informational"])
        self.assertEqual(action, "🚫 Off-topic SERP")

    def test_below_the_share_it_stays_intent_unknown(self):
        action = gir._get_keyword_action(
            "family dynamics", self._profile(10, 4), {}, ["informational"])
        self.assertEqual(action, "❓ Intent unknown")

    def test_a_keyword_WITH_a_verdict_is_unaffected(self):
        """Off-topic never overrides a real verdict."""
        action = gir._get_keyword_action(
            "my parents and siblings",
            self._profile(10, 6, intent="informational"), {}, ["informational"])
        self.assertEqual(action, "📊 Unranked")

    def test_an_old_json_without_the_count_still_reads_unknown(self):
        """P1 — a missing count is not a zero-width page."""
        profile = {"serp_intent": {"primary_intent": None, "evidence": {}}}
        self.assertEqual(
            gir._get_keyword_action("x", profile, {}, ["informational"]),
            "❓ Intent unknown")

    def test_no_organic_results_does_not_divide_by_zero(self):
        self.assertEqual(
            gir._get_keyword_action("x", self._profile(0, 0), {}, ["informational"]),
            "❓ Intent unknown")

    def test_the_share_is_editorial(self):
        self.assertEqual(
            intent_verdict.off_topic_min_share(intent_verdict.load_mapping()),
            0.5)

    def test_the_share_is_read_from_the_file(self):
        self.assertEqual(
            intent_verdict.off_topic_min_share({"off_topic_min_share": 0.9}), 0.9)

    def test_a_malformed_share_falls_back(self):
        for broken in ({}, {"off_topic_min_share": 0},
                       {"off_topic_min_share": "half"},
                       {"off_topic_min_share": True}):
            with self.subTest(broken=broken):
                self.assertEqual(
                    intent_verdict.off_topic_min_share(broken),
                    intent_verdict.DEFAULT_OFF_TOPIC_MIN_SHARE)

    def test_off_topic_sorts_after_every_other_action(self):
        src = open(os.path.join(REPO, "generate_insight_report.py"),
                   encoding="utf-8").read()
        self.assertIn('5 if action.startswith("⛔") else', src)


class TestTheRuleTableIsValidated(unittest.TestCase):

    def _write(self, tmpdir, data):
        import yaml
        path = os.path.join(tmpdir, "m.yml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh)
        return path

    def _valid(self):
        return {"version": 1,
                "rules": [{"match": {"content_type": "any", "entity_type": "any",
                                     "local_pack": "any", "domain_role": "any"},
                           "intent": "informational"}]}

    def test_a_non_list_type_set_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data = self._valid()
            data["off_topic_entity_types"] = "job_board"
            with self.assertRaises(ValueError) as ctx:
                intent_verdict.load_mapping(self._write(tmp, data))
            self.assertIn("off_topic_entity_types", str(ctx.exception))

    def test_a_share_outside_the_range_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for bad in (0, 1.5, -0.2, "half"):
                with self.subTest(bad=bad):
                    data = self._valid()
                    data["off_topic_min_share"] = bad
                    with self.assertRaises(ValueError) as ctx:
                        intent_verdict.load_mapping(self._write(tmp, data))
                    self.assertIn("off_topic_min_share", str(ctx.exception))

    def test_both_keys_stay_optional(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            intent_verdict.load_mapping(self._write(tmp, self._valid()))


if __name__ == "__main__":
    unittest.main()
