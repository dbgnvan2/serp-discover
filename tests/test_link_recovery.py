"""Google redirect wrappers must never reach a URL-derived stage.

Every case here is drawn from the real 2026-11-14 run
(``raw/20261114_155451``), where all 81 organic links and all 65 AI-Overview
citations came back as ``https://www.google.com/goto?url=CAES…`` and the whole
URL-derived half of the pipeline silently read ``www.google.com``.

Spec: review_2026-11-04, follow-up to the 2026-11-14 reading
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import link_recovery  # noqa: E402

WRAPPED = ("https://www.google.com/goto?url=CAESlAEBxCJF1-Le4zy3xkV3yRj6t4a"
           "YDUJsRXVKxDrurH7eFUzV-w0QUxCMg4JE")


class TestItRecognisesAWrapper:
    def test_a_goto_wrapper_is_not_a_destination(self):
        assert link_recovery.is_google_redirect(WRAPPED)

    def test_the_older_url_form_counts_too(self):
        assert link_recovery.is_google_redirect(
            "https://www.google.com/url?sa=t&url=CAESgwEBxCJF19&ved=2ahUKEwj")

    def test_a_country_domain_counts_too(self):
        assert link_recovery.is_google_redirect("https://www.google.ca/goto?url=CAES1")

    @pytest.mark.parametrize("url", [
        "https://www.psychologytoday.com/ca/therapists/bc/north-vancouver",
        "https://www.google.com/maps/place/Blue+Sky",   # a real Google page
        "https://www.google.com/search?q=counselling",
        "", None,
    ])
    def test_a_real_url_is_left_alone(self, url):
        assert not link_recovery.is_google_redirect(url)


class TestItRecoversTheHost:
    def test_an_organic_row_recovers_from_displayed_link(self):
        row = {"link": WRAPPED,
               "displayed_link": "https://www.yellowpages.ca › Counselling+Services › N...",
               "source": "YellowPages.ca"}
        assert link_recovery.recover_row(row) == "recovered"
        assert row["link"] == "https://www.yellowpages.ca"
        assert row["link_recovered_from"] == "displayed_link"
        assert row["original_link"] == WRAPPED

    def test_an_aio_citation_recovers_from_the_favicon_url(self):
        row = {"link": WRAPPED, "source": "Psychology Today",
               "source_icon": ("https://encrypted-tbn2.gstatic.com/faviconV2"
                               "?url=https://www.psychologytoday.com&client=X")}
        assert link_recovery.recover_row(row) == "recovered"
        assert row["link"] == "https://www.psychologytoday.com"

    def test_a_brand_name_in_source_is_not_mistaken_for_a_host(self):
        """"The Best Vancouver" is a publication, not a domain."""
        row = {"link": WRAPPED, "source": "The Best Vancouver"}
        assert link_recovery.recover_row(row) == "lost"
        assert row["link"] == ""

    def test_a_hostname_in_source_is_used(self):
        row = {"link": WRAPPED, "source": "www.goodlifetherapy.ca"}
        assert link_recovery.recover_row(row) == "recovered"
        assert row["link"] == "https://www.goodlifetherapy.ca"

    def test_a_sitelink_inherits_its_parent_result_host(self):
        """A sitelink carries only a title; it belongs to its result's site."""
        row = {"link": WRAPPED, "title": "Couples Counselling"}
        assert link_recovery.recover_row(
            row, parent_host="https://www.clearheartcounselling.com") == "recovered"
        assert row["link"] == "https://www.clearheartcounselling.com"
        assert row["link_recovered_from"] == "parent"

    def test_a_wrapper_still_carrying_a_real_url_is_unwrapped_whole(self):
        """Not every wrapper is an opaque blob; keep the page when it is there."""
        row = {"link": "https://www.google.com/url?sa=t&url=https://x.ca/couples"}
        assert link_recovery.recover_row(row) == "recovered"
        assert row["link"] == "https://x.ca/couples"
        assert row["link_is_destination_page"] is True


class TestALostHostIsNotGoogle:
    def test_an_unrecoverable_row_has_no_url_rather_than_googles(self):
        """P1 — unknown is not a terminal value. google.com would be scored as
        a competitor with Google's Domain Authority."""
        row = {"link": WRAPPED, "title": "Something"}
        assert link_recovery.recover_row(row) == "lost"
        assert row["link"] == ""
        assert row["original_link"] == WRAPPED


class TestAHostIsNotThePage:
    def test_a_recovered_row_says_it_is_not_the_ranked_page(self):
        """The guard the enrichment and Page-Authority skips depend on."""
        row = {"link": WRAPPED,
               "displayed_link": "https://www.yellowpages.ca › Counselling"}
        link_recovery.recover_row(row)
        assert row["link_is_destination_page"] is False

    def test_an_untouched_row_carries_no_annotation(self):
        """An unwrapped link is a real page, and callers default to True."""
        row = {"link": "https://livingsystems.ca/couples"}
        assert link_recovery.recover_row(row) == ""
        for key in link_recovery.ANNOTATIONS:
            assert key not in row


class TestItReachesEveryContainer:
    """Enumerating the named lists missed four containers in the real run."""

    def _response(self):
        return {
            "organic_results": [
                {"link": WRAPPED, "displayed_link": "https://a.ca › x",
                 "sitelinks": {"list": [{"link": WRAPPED, "title": "inner"}]}},
            ],
            "ads": [{"link": WRAPPED, "displayed_link": "https://ad.ca › y",
                     "sitelinks": [{"link": WRAPPED, "title": "ad inner"}]}],
            "ai_overview": {
                "references": [
                    {"link": WRAPPED, "source_icon": "https://g/f?url=https://ref.ca"}],
                "text_blocks": [
                    {"list": [{"snippet_links": [{"link": WRAPPED, "title": "t"}]}]}],
            },
            "related_questions": [
                {"question": "q", "references": [
                    {"link": WRAPPED, "source": "paa.ca"}]}],
        }

    def test_no_wrapper_survives_anywhere(self):
        response = self._response()
        link_recovery.recover_response(response)

        found = []

        def walk(node):
            if isinstance(node, dict):
                if link_recovery.is_google_redirect(node.get("link")):
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(response)
        assert not found, f"{len(found)} wrapped link(s) survived recovery"

    def test_nested_links_inherit_their_container(self):
        response = self._response()
        link_recovery.recover_response(response)
        assert (response["organic_results"][0]["sitelinks"]["list"][0]["link"]
                == "https://a.ca")
        assert response["ads"][0]["sitelinks"][0]["link"] == "https://ad.ca"

    def test_the_counts_reconcile_with_the_rows(self):
        """P2 — a recovery that silently changed data would be invisible."""
        counts = link_recovery.recover_response(self._response())
        assert counts["wrapped"] == 7
        assert counts["recovered"] + counts["lost"] == counts["wrapped"]
        # The AI-Overview snippet_link has no host anywhere and no parent.
        assert counts["lost"] == 1
        assert counts["lost_organic"] == 0

    def test_a_lost_organic_row_is_counted_separately(self):
        """A lost organic row is a lost measurement; a lost inline link is not."""
        counts = link_recovery.recover_response(
            {"organic_results": [{"link": WRAPPED, "title": "no host anywhere"}]})
        assert counts["lost_organic"] == 1

    def test_recovery_is_idempotent(self):
        """serp_audit recovers on both the fetch and the resume path."""
        response = self._response()
        link_recovery.recover_response(response)
        again = link_recovery.recover_response(response)
        assert again["wrapped"] == 0
        assert response["organic_results"][0]["link"] == "https://a.ca"

    @pytest.mark.parametrize("response", [None, [], "", 42])
    def test_a_non_response_does_not_raise(self, response):
        assert link_recovery.recover_response(response)["wrapped"] == 0


class TestALostLinkReadsLikeEveryOtherMissingField:
    """parse_data must not emit a blank cell where the convention is "N/A"."""

    def test_the_audit_maps_an_empty_link_to_na(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "serp_audit.py"), encoding="utf-8").read()
        assert '"Link": item.get("link") or "N/A",' in src, (
            'item.get("link", "N/A") returns "" for a row whose link recovery '
            'blanked, so the default never fires')
