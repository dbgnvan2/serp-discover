"""Review chunk D2c — one host gets one answer, and an error page is not content.

Three findings:

- D-C-08: 35 of the 121 domain overrides were applied to `x.ca` and ignored
  for `www.x.ca`, because the pipeline looked the SERP host up verbatim while
  the refresh path and the candidate report stripped `www.` first.
- D-C-20: a 403/429/5xx body was classified, word-counted and scored as the
  ranked page.
- D-C-21: `Has_Main_AI_Overview` was set from the un-located fallback probe as
  well as the located SERP.

(D2c.1-D2c.14)
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_data_extraction
import domain_utils
import enrichment
import generate_domain_override_candidates as candidates
import handoff_writer
import refresh_analysis_outputs
import serp_audit
from classifiers import EntityClassifier
from domain_utils import normalize_domain

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_QUERY_META = {"run_id": "r", "created_at": "c", "google_url": "u",
               "params_hash": "h"}


class TestOneDefinitionOfAHost(unittest.TestCase):
    """D2c.1 — and the two wrong ways to strip `www.`, both of which shipped."""

    def test_the_prefix_goes_and_the_case_goes(self):
        self.assertEqual(normalize_domain("WWW.Example.COM"), "example.com")
        self.assertEqual(normalize_domain("example.com"), "example.com")

    def test_a_url_and_a_bare_host_agree(self):
        self.assertEqual(normalize_domain("https://www.x.ca/a/b?q=1"), "x.ca")
        self.assertEqual(normalize_domain("//www.x.ca"), "x.ca")
        self.assertEqual(normalize_domain("x.ca"), "x.ca")

    def test_a_w_leading_label_survives(self):
        """`lstrip("www.")` strips the character set, not the prefix."""
        self.assertEqual(normalize_domain("wellness.ca"), "wellness.ca")
        self.assertEqual(normalize_domain("www.wwwellness.ca"), "wwwellness.ca")

    def test_the_sequence_is_not_stripped_from_the_middle(self):
        """`replace("www.", "")` strips it anywhere; two modules did that."""
        self.assertEqual(normalize_domain("findwww.example.com"),
                         "findwww.example.com")

    def test_the_port_and_userinfo_go(self):
        self.assertEqual(normalize_domain("http://u:p@WWW.x.ca:8443/"), "x.ca")

    def test_free_text_is_not_a_host(self):
        self.assertEqual(normalize_domain("not a url"), "")
        self.assertEqual(normalize_domain(None), "")
        self.assertEqual(normalize_domain(""), "")


class TestEveryOverrideAnswersForBothHosts(unittest.TestCase):
    """D2c.2 — asserted over the real overrides file, not a fixture."""

    def setUp(self):
        self.path = os.path.join(_REPO, "domain_overrides.yml")
        with open(self.path, encoding="utf-8") as f:
            self.overrides = yaml.safe_load(f) or {}
        self.classifier = EntityClassifier(override_file=self.path)

    def test_the_file_is_not_empty(self):
        self.assertGreater(len(self.overrides), 0,
                           "this guard is vacuous with no overrides")

    def test_www_and_bare_classify_the_same(self):
        differing = [
            d for d in self.overrides
            if self.classifier.classify("www." + str(d), None)[0]
            != self.classifier.classify(str(d), None)[0]
        ]
        self.assertEqual(differing, [])

    def test_an_override_written_with_www_still_answers(self):
        classifier = EntityClassifier(override_file=self.path)
        classifier.overrides = {normalize_domain("www.y.ca"): "counselling"}
        self.assertEqual(classifier.classify("y.ca", None)[0], "counselling")
        self.assertEqual(classifier.classify("www.y.ca", None)[0],
                         "counselling")

    def test_a_url_shaped_host_is_not_looked_up_verbatim(self):
        classifier = EntityClassifier(override_file=self.path)
        classifier.overrides = {"y.ca": "directory"}
        self.assertEqual(classifier.classify("https://www.y.ca/x", None)[0],
                         "directory")


class TestTheProducersShareTheDefinition(unittest.TestCase):
    """D2c.3/D2c.4 — the pipeline, the refresh and the report agree."""

    def test_the_candidate_report_delegates(self):
        self.assertEqual(candidates.normalize_domain("https://WWW.X.ca/a"),
                         "x.ca")

    def test_a_google_wrapper_still_has_no_domain(self):
        wrapper = "https://www.google.com/url?q=https://x.ca"
        self.assertEqual(candidates.normalize_domain(wrapper), "")

    def test_the_brief_extractor_delegates(self):
        self.assertEqual(
            brief_data_extraction._extract_domain("https://findwww.x.com/a"),
            "findwww.x.com")
        self.assertEqual(
            brief_data_extraction._domain_from_link("https://WWW.X.ca/a"),
            "x.ca")

    def test_the_refresh_path_classifies_a_www_row(self):
        classifier = EntityClassifier()
        classifier.overrides = {"x.ca": "nonprofit"}
        row = {"Link": "https://www.x.ca/page", "Entity_Type": "N/A"}
        self.assertEqual(
            refresh_analysis_outputs.classify_domain_for_row(classifier, row),
            "nonprofit")

    def test_a_covered_domain_is_not_proposed_again(self):
        """D2c.4 — the report used to keep proposing an override it had."""
        data = {"organic_results": [
            {"Link": "https://www.x.ca/a", "Root_Keyword": "k1",
             "Entity_Type": "N/A"},
            {"Link": "https://www.x.ca/b", "Root_Keyword": "k2",
             "Entity_Type": "N/A"},
            {"Link": "https://www.x.ca/c", "Root_Keyword": "k3",
             "Entity_Type": "N/A"},
        ]}
        classifier = EntityClassifier()
        classifier.overrides = {"x.ca": "counselling"}
        found = candidates.collect_candidates(
            data, {"x.ca": "counselling"}, classifier)
        self.assertNotIn("x.ca", [c.get("domain") for c in found])


class _Storage:
    def __init__(self):
        self.url_features = []
        self.domain_features = []

    def save_url_features(self, url, status, content_type, schema, words, ev):
        self.url_features.append(
            {"url": url, "status": status, "content_type": content_type,
             "word_count": words, "evidence": ev})

    def save_domain_features(self, domain, entity_type):
        self.domain_features.append((domain, entity_type))


def _fetcher(status, body=b"<html><body><h1>Checking your browser</h1></body></html>"):
    enricher = MagicMock()
    enricher.fetch_url.return_value = (
        None if status is None else
        {"url": "https://x.ca/a", "status_code": status,
         "headers": {"Content-Type": "text/html"}, "content": body,
         "is_pdf": False})
    enricher.extract_features.return_value = {
        "soup": None, "word_count_est": 6, "author_present": False,
        "question_heading_count": 0, "schema_types": [],
        "faq_present": False, "intro_text_length": 0,
        "question_headings": [], "published_time": None,
        "modified_time": None, "credential_hits": [],
        "review_marker_present": False}
    return enricher


class TestAnErrorPageIsNotContent(unittest.TestCase):
    """D2c.5-D2c.9 — the body of a 403 is the error page, not the ranked page."""

    def _run(self, status):
        item = {"Rank": 1, "Is_Destination_Page": True, "_domain": "x.ca"}
        storage = _Storage()
        enricher = _fetcher(status)
        content, entity = MagicMock(), MagicMock()
        content.classify.return_value = ("article", 0.9, ["x"])
        entity.classify.return_value = ("counselling", 0.9, ["x"])
        outcome = enrichment.enrich_row(
            item, "https://x.ca/a", 1, 5, enricher, content, entity, storage)
        return outcome, item, storage, enricher

    def test_a_403_body_is_not_parsed(self):
        outcome, item, _storage, enricher = self._run(403)
        self.assertEqual(outcome, enrichment.BLOCKED)
        enricher.extract_features.assert_not_called()
        self.assertEqual(item["Word_Count"], enrichment.NOT_MEASURED)
        self.assertEqual(item["Content_Type"], enrichment.NOT_MEASURED)
        self.assertNotIn("Author_Present", item)
        self.assertNotIn("Question_Heading_Count", item)

    def test_a_429_and_a_5xx_are_the_same(self):
        for status in (429, 500, 503):
            self.assertEqual(self._run(status)[0], enrichment.BLOCKED)

    def test_a_200_is_still_enriched(self):
        outcome, item, _storage, enricher = self._run(200)
        self.assertEqual(outcome, enrichment.ENRICHED)
        enricher.extract_features.assert_called_once()
        self.assertEqual(item["Word_Count"], 6)
        self.assertEqual(item["Content_Type"], "article")

    def test_a_301_is_still_enriched(self):
        """Only >= 400 is an error; requests follows redirects itself."""
        self.assertEqual(self._run(301)[0], enrichment.ENRICHED)

    def test_the_status_still_reaches_sqlite(self):
        """D2c.7 — a blocked page is a record, not a hole."""
        _outcome, _item, storage, _e = self._run(403)
        self.assertEqual(len(storage.url_features), 1)
        self.assertEqual(storage.url_features[0]["status"], 403)
        self.assertIsNone(storage.url_features[0]["word_count"],
                          "a blocked page has no word count, not zero")

    def test_an_unreachable_fetch_says_so(self):
        outcome, item, storage, _e = self._run(None)
        self.assertEqual(outcome, enrichment.UNREACHABLE)
        self.assertEqual(item["Fetch_Status"],
                         enrichment.status_text(enrichment.UNREACHABLE))
        self.assertEqual(storage.url_features, [],
                         "nothing was read, so nothing is recorded as read")

    def test_a_rank_beyond_the_cap_is_not_attempted(self):
        item = {"Rank": 9, "Is_Destination_Page": True}
        enricher = _fetcher(200)
        outcome = enrichment.enrich_row(
            item, "https://x.ca/a", 9, 5, enricher, None, None, _Storage())
        self.assertEqual(outcome, enrichment.NOT_ATTEMPTED)
        enricher.fetch_url.assert_not_called()

    def test_the_four_outcomes_have_distinct_words(self):
        """D2c.6 — the reader can tell them apart."""
        words = {enrichment.status_text(s, status=403) for s in (
            enrichment.ENRICHED, enrichment.BLOCKED, enrichment.UNREACHABLE,
            enrichment.NOT_ATTEMPTED, enrichment.NOT_DESTINATION_PAGE)}
        self.assertEqual(len(words), 5)

    def test_the_words_live_in_config(self):
        with open(os.path.join(_REPO, "serp_vocab.yml"), encoding="utf-8") as f:
            vocab = yaml.safe_load(f)
        self.assertIn("fetch_status", vocab)
        for state in ("enriched", "blocked", "unreachable", "not_attempted",
                      "not_destination_page", "blocked_warning"):
            self.assertIn(state, vocab["fetch_status"])

    def test_a_malformed_template_falls_back_to_english(self):
        """Not to the state key: the user reads this cell."""
        with patch.object(enrichment, "SERP_VOCAB",
                          {"fetch_status": {"blocked": "{nope}"}}):
            self.assertEqual(enrichment.status_text("blocked", status=403),
                             "Blocked (403)")

    def test_a_missing_vocab_block_falls_back_to_english(self):
        with patch.object(enrichment, "SERP_VOCAB", {}):
            for state in (enrichment.ENRICHED, enrichment.NOT_ATTEMPTED,
                          enrichment.UNREACHABLE, enrichment.NO_URL,
                          enrichment.DISABLED):
                text = enrichment.status_text(state)
                self.assertNotEqual(text, state)
                self.assertEqual(text, text.strip())
            self.assertIn("3", enrichment.status_text(
                "blocked_warning", blocked=3, attempted=5))

    def test_the_row_carries_the_state_as_well_as_the_words(self):
        """A consumer must not have to string-match editable words (P4)."""
        item = {"Rank": 9, "Is_Destination_Page": True}
        enrichment.enrich_row(item, "https://x.ca/a", 9, 5, _fetcher(200),
                              None, None, _Storage())
        self.assertEqual(item["Fetch_State"], enrichment.NOT_ATTEMPTED)
        self.assertEqual(item["Fetch_Status"],
                         enrichment.status_text(enrichment.NOT_ATTEMPTED))


class TestTheBlockedCountReachesAReader(unittest.TestCase):
    """D2c.8 — P2: "N of M" is not only in the log."""

    def test_the_warning_names_both_numbers(self):
        message = enrichment.status_text(
            "blocked_warning", blocked=2, attempted=5)
        self.assertIn("2", message)
        self.assertIn("5", message)
        self.assertIn("Not Measured", message)


class TestTheUnlocatedProbeIsADifferentQuestion(unittest.TestCase):
    """D2c.10-D2c.14 — finding D-C-21."""

    def _parse(self, results):
        return serp_audit.parse_data("k", results, _QUERY_META)

    def test_an_overview_only_the_probe_returned_is_not_charged(self):
        metrics, *rest = self._parse(
            {"google": {"organic_results": []},
             "google_ai_overview_probe": {"snippet": "unlocated"}})
        self.assertEqual(metrics["AI_Overview_Mode"],
                         "fallback_without_location")
        self.assertFalse(metrics["Has_Main_AI_Overview"])
        self.assertTrue(metrics["Has_Unlocated_AI_Overview"])

    def test_the_text_is_still_published(self):
        """D2c.11 — suppressed would be worse: the words exist."""
        metrics, *rest = self._parse(
            {"google": {"organic_results": []},
             "google_ai_overview_probe": {"snippet": "unlocated"}})
        self.assertEqual(metrics["AI_Overview"], "unlocated")

    def test_an_overview_on_the_located_serp_is_charged(self):
        metrics, *rest = self._parse(
            {"google": {"organic_results": [],
                        "ai_overview": {"snippet": "located"}}})
        self.assertEqual(metrics["AI_Overview_Mode"], "direct_in_main")
        self.assertTrue(metrics["Has_Main_AI_Overview"])
        self.assertFalse(metrics["Has_Unlocated_AI_Overview"])

    def test_a_token_followup_is_the_located_serp(self):
        metrics, *rest = self._parse(
            {"google": {"organic_results": []},
             "google_ai_overview": {"ai_overview": {"snippet": "followed"}}})
        self.assertEqual(metrics["AI_Overview_Mode"], "token_followup")
        self.assertTrue(metrics["Has_Main_AI_Overview"])

    def test_no_overview_at_all(self):
        metrics, *rest = self._parse({"google": {"organic_results": []}})
        self.assertEqual(metrics["AI_Overview_Mode"], "not_present")
        self.assertFalse(metrics["Has_Main_AI_Overview"])
        self.assertFalse(metrics["Has_Unlocated_AI_Overview"])

    def test_an_empty_probe_payload_is_not_an_overview(self):
        metrics, *rest = self._parse(
            {"google": {"organic_results": []},
             "google_ai_overview_probe": {}})
        self.assertEqual(metrics["AI_Overview_Mode"], "not_present")
        self.assertFalse(metrics["Has_Unlocated_AI_Overview"])

    def test_the_reader_is_told(self):
        """D2c.12."""
        parsed = self._parse(
            {"google": {"organic_results": []},
             "google_ai_overview_probe": {"snippet": "unlocated"}})
        warnings = parsed[-1]
        messages = [w["Message"] for w in warnings
                    if w.get("Field") == "Has_Main_AI_Overview"]
        self.assertEqual(len(messages), 1)
        self.assertIn("un-located", messages[0])

    def test_the_brief_payload_carries_both_flags(self):
        """D2c.13 — aio_exposure, commodity_score and play routing read these."""
        data = {"overview": [{"Source_Keyword": "k", "Query_Label": "A",
                              "Executed_Query": "k", "Total_Results": 10,
                              "Has_Main_AI_Overview": False,
                              "Has_Unlocated_AI_Overview": True,
                              "AI_Overview_Mode": "fallback_without_location"}],
                "organic_results": [], "paa": [], "ai_citations": []}
        extracted = brief_data_extraction.extract_analysis_data_from_json(
            data, "livingsystems.ca")
        query = extracted["queries"][0]
        self.assertFalse(query["has_ai_overview"])
        self.assertTrue(query["has_ai_overview_unlocated"])
        self.assertEqual(query["ai_overview_mode"],
                         "fallback_without_location")


class TestTheCoverageTravelsWithTheSignals(unittest.TestCase):
    """Review fix 3 — a page the fetch never read is a gap, not a finding.

    The four enriched-page signal blocks (schema, extractability, E-E-A-T,
    freshness) are measured only on pages whose body was read. Their
    denominators shrink when pages are blocked, so the block says how many
    were read, and an empty block names which it was (P1/P2).
    """

    def _rows(self, states):
        return [{"rank": i + 1, "source": f"s{i}", "fetch_state": state}
                for i, state in enumerate(states)]

    def test_blocked_pages_are_counted_not_dropped(self):
        coverage = brief_data_extraction._build_fetch_coverage(
            self._rows(["enriched", "blocked", "blocked", "unreachable"]))
        self.assertEqual(coverage["rows"], 4)
        self.assertEqual(coverage["read"], 1)
        self.assertEqual(coverage["unread"], 3)
        self.assertEqual(coverage["by_state"],
                         {"blocked": 2, "unreachable": 1})

    def test_an_empty_block_names_the_block_not_a_missing_capture(self):
        coverage = brief_data_extraction._build_fetch_coverage(
            self._rows(["blocked", "blocked"]))
        signals = brief_data_extraction._with_fetch_coverage(
            {"data_available": False}, coverage)
        self.assertIn("2 of 2", signals["reason"])
        self.assertIn("error status", signals["reason"])
        self.assertNotIn("predates", signals["reason"])

    def test_a_capture_that_never_ran_still_says_so(self):
        coverage = brief_data_extraction._build_fetch_coverage(
            self._rows(["enriched", "enriched"]))
        signals = brief_data_extraction._with_fetch_coverage(
            {"data_available": False}, coverage)
        self.assertIn("predates", signals["reason"])

    def test_a_block_with_data_still_states_its_denominator(self):
        coverage = brief_data_extraction._build_fetch_coverage(
            self._rows(["enriched", "blocked"]))
        signals = brief_data_extraction._with_fetch_coverage(
            {"data_available": True, "enriched_count": 1}, coverage)
        self.assertEqual(signals["fetch_coverage"]["unread"], 1)
        self.assertNotIn("reason", signals)

    def test_the_four_signal_blocks_carry_it_end_to_end(self):
        data = {
            "overview": [{"Source_Keyword": "k", "Query_Label": "A",
                          "Executed_Query": "k", "Total_Results": 10}],
            "organic_results": [
                {"Source_Keyword": "k", "Query_Label": "A", "Rank": 1,
                 "Source": "a.com", "Link": "https://a.com/p",
                 "Fetch_State": "blocked", "Content_Type": "Not Measured"},
            ],
            "paa": [], "ai_citations": [],
        }
        extracted = brief_data_extraction.extract_analysis_data_from_json(
            data, "livingsystems.ca")
        profile = extracted["keyword_profiles"]["k"]
        for block in ("schema_signals", "extractability", "freshness",
                      "eeat_signals"):
            with self.subTest(block=block):
                coverage = profile[block]["fetch_coverage"]
                self.assertEqual(coverage["unread"], 1)
                self.assertIn("error status", profile[block]["reason"])


class TestTheHandoffAgreesOnWhichHostIsWhich(unittest.TestCase):
    """Review fix 4 — the omit list and the competitor key are host
    comparisons too, and the client test was a substring match."""

    def _handoff(self, links, omit=None, client="livingsystems.ca"):
        organic = [{"Source_Keyword": "k", "Query_Label": "A", "Rank": i + 1,
                    "Link": link, "Title": "t", "Entity_Type": "practice",
                    "Content_Type": "guide"}
                   for i, link in enumerate(links)]
        return handoff_writer.build_competitor_handoff(
            all_organic=organic, client_domain=client,
            client_brand_names=["Living Systems"], run_id="r",
            run_timestamp="2026-11-16T00:00:00Z", omit_from_audit=omit or [],
            n=10)

    def test_an_omit_entry_written_with_www_excludes_the_bare_host(self):
        handoff = self._handoff(["https://therapist.ca/p"],
                                omit=["www.therapist.ca"])
        self.assertEqual(handoff["targets"], [])
        self.assertEqual(handoff["exclusions"]["omit_list_excluded"], 1)

    def test_the_competitor_key_is_the_canonical_host(self):
        handoff = self._handoff(["https://www.therapist.ca/p"])
        self.assertEqual(handoff["targets"][0]["domain"], "therapist.ca")

    def test_a_host_merely_containing_the_clients_is_a_competitor(self):
        handoff = self._handoff(["https://notlivingsystems.ca/p"])
        self.assertEqual([t["domain"] for t in handoff["targets"]],
                         ["notlivingsystems.ca"])
        self.assertEqual(handoff["exclusions"]["client_urls_excluded"], 0)

    def test_the_clients_own_www_host_is_still_excluded(self):
        handoff = self._handoff(["https://www.livingsystems.ca/p"])
        self.assertEqual(handoff["targets"], [])
        self.assertEqual(handoff["exclusions"]["client_urls_excluded"], 1)

    def test_a_subdomain_of_the_client_is_the_client(self):
        handoff = self._handoff(["https://blog.livingsystems.ca/p"])
        self.assertEqual(handoff["targets"], [])
        self.assertEqual(handoff["exclusions"]["client_urls_excluded"], 1)


class TestCollapsedOverrideKeysAreNotSilent(unittest.TestCase):
    """Review fix 10 — normalisation can land two keys on one host."""

    def _load(self, pairs):
        """Write the file in the given order — file order decides the winner."""
        path = os.path.join(self._dir, "domain_overrides.yml")
        with open(path, "w") as handle:
            for key, value in pairs:
                handle.write(f"{key!r}: {value}\n")
        return EntityClassifier(override_file=path)

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_two_keys_on_one_host_are_reported(self):
        with patch("builtins.print") as printed:
            classifier = self._load([("x.ca", "directory"),
                                     ("www.x.ca", "practice")])
        said = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("x.ca", said)
        self.assertIn("disagree", said)
        self.assertEqual(classifier.overrides["x.ca"], "practice")

    def test_the_same_answer_twice_is_not_a_conflict(self):
        with patch("builtins.print") as printed:
            classifier = self._load([("x.ca", "directory"),
                                     ("www.x.ca", "directory")])
        self.assertEqual(printed.call_args_list, [])
        self.assertEqual(classifier.overrides["x.ca"], "directory")

    def test_a_key_that_is_not_a_host_never_answers_for_everything(self):
        with patch("builtins.print"):
            classifier = self._load([("not a host", "directory"),
                                     ("x.ca", "practice")])
        self.assertNotIn("", classifier.overrides)
        self.assertEqual(set(classifier.overrides), {"x.ca"})


if __name__ == "__main__":
    unittest.main()
