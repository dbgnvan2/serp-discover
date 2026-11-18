"""The serp-discover half of the Tool 1 → Tool 2 handoff contract.

Review chunk X. `handoff_schema.json` says whether a handoff is well-formed;
it cannot say what a field *means*. This file holds the producer's side of the
meanings, and `serp-compete/Serp-compete/tests/test_handoff_contract.py` holds
the consumer's. Both call the real code: a contract test that re-implements
the contract tests nothing, which is how `client_brand_names` stayed broken
for months with two green suites.

What the producer promises, and where it is checked:

1. **One host, one form.** Every host the handoff publishes —
   `targets[].domain`, `client_domain`, and every `moz.domains` key — is the
   canonical form `domain_utils.normalize_domain` returns: lower-cased, no
   leading `www.`, no port, no credentials. The consumer normalises what it
   reads anyway (it must: handoff files already on disk carry the old form),
   but the producer no longer publishes two forms in one file.
2. **Absolute rank.** `targets[].rank` counts organic results across the whole
   SERP, as of `schema_version` 2.0, so two targets never both claim rank 1.
3. **The version says which.** `SCHEMA_VERSION_BASE` / `_WITH_MOZ` are the
   versions serp-compete lists in `handoff.absolute_rank_versions`.
4. **`client_brand_names` is published**, because the consumer reads it.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
      docs/handoff_contract.md
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import handoff_writer
import moz_competitor
from domain_utils import normalize_domain

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _organic(keyword, rank, url, label="A"):
    return {"Root_Keyword": keyword, "Rank": rank, "Link": url,
            "Title": f"T {url}", "Entity_Type": "practice",
            "Content_Type": "service_page", "Query_Label": label}


ROWS = [
    _organic("couples therapy", 1, "https://www.psychologytoday.com/ca/x"),
    _organic("couples therapy", 2, "https://notlivingsystems.ca/a"),
    _organic("couples therapy", 3, "https://WWW.JaneApp.com/b"),
    _organic("couples therapy", 4, "https://www.livingsystems.ca/me"),
    _organic("marriage counselling", 11, "https://goodlifetherapy.ca/p"),
]


class TestEveryPublishedHostIsCanonical(unittest.TestCase):
    """Contract 1 — the handoff never carries two forms of one host."""

    def _handoff(self, client_domain, omit=None):
        moz_block = {"domains": {
            d: {"data_available": True, "status": "ok",
                "domain_authority": 50}
            for d in moz_competitor.competitor_domains(
                ROWS, client_domain, omit)}}
        return handoff_writer.build_competitor_handoff(
            ROWS, run_id="r1", run_timestamp="2026-11-17T00:00:00Z",
            client_domain=client_domain, client_brand_names=["Living Systems"],
            omit_from_audit=omit, moz_competitor=moz_block)

    def test_the_targets_the_moz_keys_and_the_client_agree(self):
        handoff = self._handoff("livingsystems.ca")
        hosts = [t["domain"] for t in handoff["targets"]]
        hosts += list(handoff["moz"]["domains"])
        hosts.append(handoff["client_domain"])
        for host in hosts:
            self.assertEqual(host, normalize_domain(host),
                             f"{host} is not the canonical form")
            self.assertFalse(host.startswith("www."), host)

    def test_the_published_client_domain_is_canonical(self):
        """It was the raw `config.yml` value, so a `www.` there published a
        handoff whose `client_domain` did not match its own targets' form."""
        handoff = self._handoff("WWW.LivingSystems.ca")
        self.assertEqual(handoff["client_domain"], "livingsystems.ca")

    def test_the_config_form_does_not_decide_who_is_measured(self):
        """The exclusions used to turn on a `www.` somebody typed in config.

        The client test was the substring test D-C-08 removed elsewhere, so a
        bare `livingsystems.ca` dropped `notlivingsystems.ca` as "the client",
        and the omit list only matched a host written in the same form. Which
        competitors the Moz row budget is spent on followed from that.
        """
        bare = self._handoff("livingsystems.ca", ["janeapp.com"])
        wwwed = self._handoff("www.livingsystems.ca", ["www.janeapp.com"])
        self.assertEqual(sorted(bare["moz"]["domains"]),
                         sorted(wwwed["moz"]["domains"]))
        self.assertEqual([t["domain"] for t in bare["targets"]],
                         [t["domain"] for t in wwwed["targets"]])
        # The competitor whose name merely contains the client's is kept.
        self.assertIn("notlivingsystems.ca", bare["moz"]["domains"])
        # The client's own host, in either form, is not a competitor.
        self.assertNotIn("livingsystems.ca", bare["moz"]["domains"])
        # The omit list is honoured in either form.
        self.assertNotIn("janeapp.com", bare["moz"]["domains"])
        self.assertNotIn("janeapp.com", wwwed["moz"]["domains"])

    def test_a_subdomain_of_the_client_is_not_a_competitor(self):
        rows = ROWS + [_organic("couples therapy", 5,
                                "https://blog.livingsystems.ca/post")]
        domains = moz_competitor.competitor_domains(
            rows, "livingsystems.ca", None)
        self.assertNotIn("blog.livingsystems.ca", domains)


class TestTheRealMozBlockPublishesCanonicalHosts(unittest.TestCase):
    """Contract 1, through the only code that writes a real `moz` block.

    `build_handoff_block` is what a run calls. Asserting over a `moz` block
    this test assembled itself would prove nothing about it: the client entry
    was `client_domain.lower()` — `www.` kept — while every competitor key
    beside it was canonical, and a test that built its own block was green
    throughout.
    """

    CONFIG = {"moz": {"enabled": True,
                      "brand_authority": {"enabled": True},
                      "competitor": {"enabled": True,
                                     "client_anchor_texts": True}}}

    def _block(self, client_domain):
        import tempfile
        from unittest import mock

        asked = []

        def _fetch(self, domains):
            asked.extend(domains)
            return {d: {"data_available": True} for d in domains}

        def _brand(self, domain):
            asked.append(domain)
            return {"brand_authority": 11}

        def _anchors(self, domain):
            asked.append(domain)
            return {"status": "ok", "items": []}

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(moz_competitor.MozCompetitorClient,
                                   "fetch", _fetch), \
                 mock.patch.object(moz_competitor.MozCompetitorClient,
                                   "brand_authority_for", _brand), \
                 mock.patch.object(moz_competitor.MozCompetitorClient,
                                   "anchor_texts_for", _anchors):
                block = moz_competitor.build_handoff_block(
                    self.CONFIG, ROWS, client_domain,
                    db_path=os.path.join(tmp, "t.db"))
        return block, asked

    def test_the_client_entry_carries_the_canonical_host(self):
        block, _ = self._block("WWW.LivingSystems.ca")
        self.assertEqual(block["client"]["domain"], "livingsystems.ca")

    def test_every_domains_key_is_canonical(self):
        block, _ = self._block("livingsystems.ca")
        for host in block["domains"]:
            self.assertEqual(host, normalize_domain(host), host)

    def test_the_paid_calls_are_billed_under_the_canonical_host(self):
        """The Moz cache key is (domain, scope, locale), so a `www.` form
        queries and bills the client's own site under a key no other path
        reads."""
        _, asked = self._block("WWW.LivingSystems.ca")
        self.assertIn("livingsystems.ca", asked)
        for host in asked:
            self.assertEqual(host, normalize_domain(host), host)


class TestRankIsAbsolute(unittest.TestCase):
    """Contract 2 and 3 — and the version that tells the consumer so."""

    def test_two_targets_never_both_claim_rank_one(self):
        rows = [_organic("couples therapy", 1, "https://a.com/1"),
                _organic("couples therapy", 2, "https://b.com/2"),
                _organic("couples therapy", 11, "https://c.com/3")]
        handoff = handoff_writer.build_competitor_handoff(
            rows, run_id="r", run_timestamp="t",
            client_domain="livingsystems.ca", client_brand_names=[], n=20)
        ranks = [t["rank"] for t in handoff["targets"]]
        self.assertEqual(len(ranks), len(set(ranks)), ranks)
        # Rank 11 is kept as 11: an absolute rank past the first page is not
        # renumbered to 1 by the handoff.
        self.assertIn(11, ranks)

    def test_the_version_is_one_the_consumer_calls_absolute(self):
        self.assertEqual(handoff_writer.SCHEMA_VERSION_BASE, "2.0")
        self.assertEqual(handoff_writer.SCHEMA_VERSION_WITH_MOZ, "2.1")
        doc = open(os.path.join(REPO, "docs", "handoff_contract.md"),
                   encoding="utf-8").read()
        self.assertIn("schema_version 2.0", doc)


class TestTheConsumersFieldsArePublished(unittest.TestCase):

    def test_client_brand_names_is_written(self):
        handoff = handoff_writer.build_competitor_handoff(
            ROWS, run_id="r", run_timestamp="t",
            client_domain="livingsystems.ca",
            client_brand_names=["Living Systems Counselling"])
        self.assertEqual(handoff["client_brand_names"],
                         ["Living Systems Counselling"])

    def test_the_gsc_pull_is_stated_in_the_contract(self):
        """Both tools pull GSC independently, so the contract names the
        window, the country and the device each side restricts to — a CTR
        from a desktop-only pull is not comparable with an all-device one."""
        doc = open(os.path.join(REPO, "docs", "handoff_contract.md"),
                   encoding="utf-8").read()
        for word in ("gsc.lookback_days", "gsc.country", "gsc.device",
                     "gsc_settings.date_range_days"):
            self.assertIn(word, doc, word)


if __name__ == "__main__":
    unittest.main()
