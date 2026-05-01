"""Unit tests for title_patterns.py.

Covers:
  - Each pattern's positive and negative cases
  - Priority ordering (vs_comparison beats how_to, listicle beats best_of)
  - brand_only equality (not substring) detection
  - Dominant pattern threshold (≥4 of top 10) and 'other' exclusion
  - Empty / partial / malformed inputs
"""

from __future__ import annotations

import pytest

from title_patterns import (
    DOMINANT_THRESHOLD,
    _classify_title,
    _is_brand_only,
    _strip_site_suffix,
    compute_title_patterns,
)


# ─── _strip_site_suffix ──────────────────────────────────────────────────────


class TestStripSiteSuffix:
    @pytest.mark.parametrize("title,expected", [
        ("Title | Site Name", "Title"),
        ("Title - Site Name", "Title"),
        ("Title — Site Name", "Title"),
        ("Title · Site Name", "Title"),
        ("No Separator Here", "No Separator Here"),
        ("Title | A | B", "Title"),  # only first split
        ("  Padded Title  | Site  ", "Padded Title"),
    ])
    def test_strip(self, title, expected):
        assert _strip_site_suffix(title) == expected


# ─── _is_brand_only ──────────────────────────────────────────────────────────


class TestBrandOnly:
    BRANDS = ["Living Systems", "Psychology Today", "BetterHelp"]

    def test_exact_brand_segment_matches(self):
        assert _is_brand_only("Living Systems | livingsystems.ca", self.BRANDS)

    def test_brand_alone_matches(self):
        assert _is_brand_only("Psychology Today", self.BRANDS)

    def test_brand_with_extra_text_does_not_match(self):
        # "Living Systems Counselling Couples Programs" is NOT brand-only — the
        # leftmost segment carries topical content beyond the brand.
        assert not _is_brand_only(
            "Living Systems Counselling Couples Programs", self.BRANDS
        )

    def test_no_brand_match(self):
        assert not _is_brand_only("Random Page Title", self.BRANDS)

    def test_case_insensitive(self):
        assert _is_brand_only("LIVING SYSTEMS", self.BRANDS)

    def test_empty_brand_list(self):
        assert not _is_brand_only("Living Systems", [])

    def test_empty_alias_skipped(self):
        # Empty strings in alias list shouldn't match anything
        assert not _is_brand_only("foo", ["", "  "])


# ─── _classify_title ─────────────────────────────────────────────────────────


class TestClassifyTitle:
    BRANDS = ["Living Systems", "Psychology Today"]

    # how_to
    @pytest.mark.parametrize("title", [
        "How to Find a Therapist in Vancouver",
        "How do I choose a counsellor",
        "How can I improve my marriage",
        "  How To Cope With Anxiety",  # leading whitespace
    ])
    def test_how_to_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "how_to"

    @pytest.mark.parametrize("title", [
        "Therapy: How It Works",  # 'how' not at start
        "Anyhow, here's the answer",  # 'how' embedded
    ])
    def test_how_to_does_not_match(self, title):
        assert _classify_title(title, self.BRANDS) != "how_to"

    # what_is
    @pytest.mark.parametrize("title", [
        "What is Bowen Family Systems Theory",
        "What are the benefits of couples counselling",
        "What does differentiation of self mean",
    ])
    def test_what_is_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "what_is"

    # vs_comparison — priority test
    @pytest.mark.parametrize("title", [
        "EFT vs Bowen Therapy",
        "CBT versus DBT",
        "Therapy vs. Counselling",
        "How to Compare X vs Y",  # 'how to' loses to 'vs'
    ])
    def test_vs_comparison_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "vs_comparison"

    def test_vs_comparison_beats_how_to(self):
        # Spec example: "How To Compare X vs Y" → vs_comparison, not how_to
        assert _classify_title(
            "How To Compare CBT vs DBT", self.BRANDS
        ) == "vs_comparison"

    # listicle_numeric
    @pytest.mark.parametrize("title", [
        "5 Best Therapists in Vancouver",
        "10 Things to Know About Therapy",
        "Top 7 Counselling Approaches",
        "  3 Reasons to Try EFT",
    ])
    def test_listicle_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "listicle_numeric"

    def test_listicle_beats_best_of(self):
        # "5 Best…" — listicle priority is higher than best_of
        assert _classify_title(
            "5 Best Couples Counsellors", self.BRANDS
        ) == "listicle_numeric"

    @pytest.mark.parametrize("title", [
        "5th Time I Tried Therapy",  # ordinal, not listicle
        "G2 Reviews of Counselling Apps",  # not leading number
    ])
    def test_listicle_does_not_match(self, title):
        assert _classify_title(title, self.BRANDS) != "listicle_numeric"

    # best_of
    @pytest.mark.parametrize("title", [
        "Best Couples Counsellors in Vancouver",
        "Top Rated Therapists",
        "Top-Rated Counselling Services",
    ])
    def test_best_of_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "best_of"

    # question (only when not what_is)
    @pytest.mark.parametrize("title", [
        "Why does counselling work?",
        "When should I see a therapist",
        "Where can I find a counsellor",
        "Is online therapy effective?",
        "Can therapy fix my relationship?",
        "Does cognitive therapy actually help?",
    ])
    def test_question_matches(self, title):
        assert _classify_title(title, self.BRANDS) == "question"

    def test_question_via_trailing_qmark(self):
        # No interrogative starter, but trailing "?"
        assert _classify_title(
            "Therapy might just save your marriage?", self.BRANDS
        ) == "question"

    # what_is beats question
    def test_what_is_beats_question(self):
        # "What is X" matches both what_is and question; what_is is higher.
        assert _classify_title(
            "What is differentiation of self?", self.BRANDS
        ) == "what_is"

    # brand_only
    def test_brand_only_matches(self):
        assert _classify_title(
            "Psychology Today | psychologytoday.com", self.BRANDS
        ) == "brand_only"

    # other
    @pytest.mark.parametrize("title", [
        "An Introduction to Family Systems",
        "Notes on Bowen Theory and Practice",
    ])
    def test_other_fallback(self, title):
        assert _classify_title(title, self.BRANDS) == "other"

    def test_empty_title_is_other(self):
        assert _classify_title("", self.BRANDS) == "other"
        assert _classify_title("   ", self.BRANDS) == "other"


# ─── compute_title_patterns ──────────────────────────────────────────────────


class TestComputeTitlePatterns:
    BRANDS = ["Living Systems", "Psychology Today"]

    def test_empty_returns_none(self):
        assert compute_title_patterns([]) is None

    def test_all_whitespace_returns_none(self):
        assert compute_title_patterns(["", "  ", "\t"]) is None

    def test_dominant_when_4_of_10_hit_threshold(self):
        titles = [
            "How to Find a Therapist",
            "How to Cope With Stress",
            "How to Choose Counselling",
            "How to Help Your Partner",
            # 4 how_to so far, threshold met
            "Best Therapists in Vancouver",
            "5 Tips for Couples",
            "What is EFT",
            "Therapy guide",
            "Counselling overview",
            "Mental health resources",
        ]
        result = compute_title_patterns(titles, self.BRANDS)
        assert result["dominant_pattern"] == "how_to"
        assert result["pattern_counts"]["how_to"] == 4
        assert result["total_titles"] == 10

    def test_no_dominant_when_no_pattern_hits_4(self):
        titles = [
            "How to Find a Therapist",  # how_to
            "How to Cope",                # how_to (2)
            "Best Therapists",            # best_of
            "5 Tips",                     # listicle
            "What is EFT",                # what_is
            "Why does therapy work?",     # question
            "Therapy guide",              # other
            "Counselling overview",       # other
            "Mental health",              # other
            "An overview",                # other
        ]
        result = compute_title_patterns(titles, self.BRANDS)
        assert result["dominant_pattern"] is None

    def test_other_never_becomes_dominant(self):
        # 6 'other' titles — should NOT trigger dominant_pattern
        titles = [
            "An Introduction to Therapy",
            "Notes on Bowen",
            "Therapy concepts",
            "Counselling reflections",
            "Mental health discussion",
            "Family systems thinking",
            "How to Cope",     # how_to (1)
            "How to Find Help", # how_to (2)
            "Best Therapists",  # best_of
            "5 Tips",           # listicle
        ]
        result = compute_title_patterns(titles, self.BRANDS)
        assert result["dominant_pattern"] is None
        assert result["pattern_counts"]["other"] == 6

    def test_brand_only_can_be_dominant(self):
        # 4 brand-only titles → dominant_pattern = brand_only (signal: SERP is
        # branded/navigational)
        titles = [
            "Living Systems | livingsystems.ca",
            "Psychology Today",
            "Living Systems",
            "Psychology Today | psychologytoday.com",
            "How to Find Help",
            "Best Therapists",
            "5 Tips",
            "What is EFT",
            "Therapy guide",
            "Counselling overview",
        ]
        result = compute_title_patterns(titles, self.BRANDS)
        assert result["dominant_pattern"] == "brand_only"
        assert result["pattern_counts"]["brand_only"] == 4

    def test_top_n_limits_input(self):
        # 15 titles supplied; only top 10 analysed by default
        titles = ["How to Find Help"] * 15
        result = compute_title_patterns(titles, self.BRANDS)
        assert result["total_titles"] == 10
        assert result["pattern_counts"]["how_to"] == 10

    def test_examples_capped_at_3(self):
        titles = [f"How to Step {i}" for i in range(10)]
        result = compute_title_patterns(titles, self.BRANDS)
        assert len(result["examples"]["how_to"]) == 3

    def test_examples_only_for_seen_patterns(self):
        # If a pattern has 0 hits, it shouldn't appear in the examples dict
        titles = ["How to Find Help"]
        result = compute_title_patterns(titles, self.BRANDS)
        assert "how_to" in result["examples"]
        assert "vs_comparison" not in result["examples"]

    def test_pattern_counts_schema_is_stable(self):
        # All known pattern names appear in counts even with zero hits — this
        # makes downstream validation easier (no KeyError surprises).
        result = compute_title_patterns(["How to Cope"], self.BRANDS)
        expected = {"how_to", "what_is", "best_of", "vs_comparison",
                    "listicle_numeric", "brand_only", "question", "other"}
        assert set(result["pattern_counts"].keys()) == expected

    def test_counts_sum_to_total_titles(self):
        titles = [
            "How to Find Help",        # how_to
            "Best Therapists",          # best_of
            "5 Tips",                   # listicle
            "What is EFT",              # what_is
            "Therapy?",                 # question
            "EFT vs CBT",               # vs_comparison
            "Living Systems",           # brand_only
            "An Introduction",          # other
        ]
        result = compute_title_patterns(titles, self.BRANDS)
        assert sum(result["pattern_counts"].values()) == result["total_titles"] == 8

    def test_dominant_threshold_customisable(self):
        titles = ["How to Help"] * 3 + ["Other"] * 7
        # Default threshold (4) → no dominant
        assert compute_title_patterns(titles, [])["dominant_pattern"] is None
        # Custom threshold (3) → how_to dominant
        custom = compute_title_patterns(titles, [], dominant_threshold=3)
        assert custom["dominant_pattern"] == "how_to"
