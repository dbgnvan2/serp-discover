"""
CD.7 — worked examples: generic advice translated into this run's own data.

Spec: report_content_direction_spec.md#CD.7

Sections 4 and 5 stated advice in the abstract ("Produce content matching a
non-dominant but client-aligned intent") and left the reader to work out what
that meant for their keywords. Each now renders a "**Here's an example:**" line
filling editorial templates with the run's actual keyword, People Also Ask
question and competitor vocabulary.

Every test here is mutation-checked.
"""

import json
import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import generate_insight_report as gir
from test_report_content_direction import _reset_gir_caches  # noqa: E402
from generate_insight_report import generate_report

from test_report_content_direction import (  # noqa: E402
    REAL_JSON, REPO_ROOT, _mock_data, _section,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    _reset_gir_caches()
    yield
    _reset_gir_caches()


@pytest.fixture
def real_report():
    with open(REAL_JSON, encoding="utf-8") as f:
        return generate_report(json.load(f))


class TestCD7FillExample:
    """CD.7.1 — template filling never renders an empty slot."""

    def test_cd7_1_all_values_present_fills_everything(self):
        out = gir.fill_example(
            'Write about "{keyword}". Answer "{question}" first.',
            {"keyword": "family of origin work", "question": "What is it?"})
        assert out == ('Write about "family of origin work". '
                       'Answer "What is it?" first.')

    def test_cd7_1b_sentence_with_missing_value_is_dropped(self):
        """A sentence whose placeholder has no data is dropped whole.

        Half a sentence about nothing is worse than one fewer sentence, and a
        literal "None" in advice reads as a bug (P14).
        """
        out = gir.fill_example(
            'Keep this about "{keyword}". Drop this about "{question}". Keep this too.',
            {"keyword": "kw", "question": ""})
        assert "Drop this" not in out
        assert 'Keep this about "kw".' in out
        assert "Keep this too." in out

    def test_cd7_1c_no_none_or_empty_braces_ever_rendered(self):
        out = gir.fill_example(
            'A {keyword} sentence. A {question} sentence. A {term} sentence.',
            {"keyword": "kw", "question": None, "term": ""})
        assert "None" not in out
        assert "{" not in out and "}" not in out

    def test_cd7_1d_everything_missing_returns_empty(self):
        assert gir.fill_example('Only {question} here.', {"question": ""}) == ""

    def test_cd7_1e_unknown_placeholder_drops_sentence_not_report(self):
        """An editorial typo in the YAML must not raise."""
        out = gir.fill_example('Good {keyword} line. Bad {nosuch} line.',
                               {"keyword": "kw"})
        assert "Good kw line." in out
        assert "Bad" not in out

    def test_cd7_1f_closing_quote_stays_with_its_sentence(self):
        """A quoted example must not render as: was. " Then take..."""
        out = gir.fill_example(
            'He said "it was {keyword}." Then he left.', {"keyword": "kw"})
        assert '"it was kw."' in out
        assert '. "' not in out

    def test_cd7_1g_empty_template_is_empty(self):
        assert gir.fill_example("", {"keyword": "kw"}) == ""
        assert gir.fill_example(None, {"keyword": "kw"}) == ""


class TestCD7Section4Examples:
    """CD.7.2/CD.7.3 — section 4 shows worked examples."""

    def _mixed_intent_block(self, report):
        """Just the Mixed-Intent note, exclusive of the pattern blocks after it.

        Scoping matters: section 4 renders example blocks for the Bowen patterns
        too, so asserting "an example appears somewhere in section 4" would stay
        green with the mixed-intent example deleted.
        """
        section = _section(report, "## 4. Strategic Recommendations (The Bridge)")
        marker = "### ⚖️ Mixed-Intent Strategic Note"
        assert marker in section, "no mixed-intent note in this run"
        block = section.split(marker, 1)[1]
        return block.split("### 🌉", 1)[0]

    def test_cd7_2_mixed_intent_example_rendered(self, real_report):
        """CD.7.2 — the backdoor strategy is translated into this keyword."""
        block = self._mixed_intent_block(real_report)
        assert "**Here's an example:**" in block, (
            "the mixed-intent note renders no worked example")
        assert "family of origin counselling" in block
        # The example must quote a real PAA question from the run, not a stand-in.
        assert "Can you get free counselling in BC?" in block
        # And the generic advice must still be there — the example adds to it.
        assert "non-dominant but client-aligned intent" in block

    def test_cd7_2b_strategy_descriptions_come_from_yaml(self, tmp_path, monkeypatch):
        """CD.7.2 — descriptions moved out of the Python dict into editorial YAML.

        Behavioural: rewrite the YAML, the report follows (P19 corollary — not a
        source grep).
        """
        sentinel_desc = "SENTINEL-STRATEGY-DESC-2a7f"
        sentinel_ex = "SENTINEL-STRATEGY-EXAMPLE for {keyword}."
        (tmp_path / "report_writing_directives.yml").write_text(yaml.safe_dump({
            "directives": {},
            "page_types": {},
            "examples": {},
            "mixed_intent_strategies": {
                "backdoor": {"description": sentinel_desc, "example": sentinel_ex},
            },
        }), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._DIRECTIVES_CACHE = None
        gir._GLOSSARY_CACHE = None

        data = _mock_data(["alpha topic"])
        data["keyword_profiles"]["alpha topic"]["mixed_intent_strategy"] = "backdoor"
        report = generate_report(data)
        assert sentinel_desc in report
        assert "SENTINEL-STRATEGY-EXAMPLE for alpha topic." in report

    def test_cd7_2c_no_hardcoded_strategy_text_remains(self):
        """CD.7.2 — the old Python descriptions are gone, not duplicated.

        Editorial content living in two places is how the two drift apart, so the
        YAML must be the only source. Behavioural check: empty the YAML block and
        no description can appear.
        """
        strategies = gir._mixed_intent_strategies()
        assert set(strategies) >= {"compete_on_dominant", "backdoor", "avoid"}
        for key, entry in strategies.items():
            assert str(entry.get("description") or "").strip(), key

    def test_cd7_3_pattern_example_rendered(self, real_report):
        """CD.7.3 — each fired Bowen pattern shows a concrete opening."""
        section = _section(real_report, "## 4. Strategic Recommendations (The Bridge)")
        assert "Opening it might sound like" in section

    def test_cd7_3b_pattern_examples_read_from_yaml(self):
        """CD.7.3 — examples come from strategic_patterns.yml, so a report
        re-rendered from an older JSON still shows text added since that run."""
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "strategic_patterns.yml"), encoding="utf-8"))
        authored = {p["Pattern_Name"] for p in raw
                    if str(p.get("Content_Angle_Example") or "").strip()}
        assert authored, "no pattern carries a Content_Angle_Example"
        assert set(gir._pattern_examples()) >= authored

    def test_cd7_3c_every_pattern_has_an_example(self):
        """CD.7.3 — no pattern renders advice with no worked example."""
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "strategic_patterns.yml"), encoding="utf-8"))
        missing = [p["Pattern_Name"] for p in raw
                   if not str(p.get("Content_Angle_Example") or "").strip()]
        assert not missing, f"patterns with no Content_Angle_Example: {missing}"

    def test_cd7_3d_missing_example_degrades_quietly(self, real_report, monkeypatch):
        """CD.7.3 — a pattern with no example renders without one, not blank."""
        monkeypatch.setattr(gir, "_PATTERN_EXAMPLE_CACHE", {})
        with open(REAL_JSON, encoding="utf-8") as f:
            data = json.load(f)
        for rec in data.get("strategic_recommendations", []):
            rec.pop("Content_Angle_Example", None)
        report = generate_report(data)
        section = _section(report, "## 4. Strategic Recommendations (The Bridge)")
        assert "Opening it might sound like" not in section
        assert "**Content Angle (template):**" in section


class TestCD7Section5Examples:
    """CD.7.4/CD.7.5 — section 5 shows worked examples."""

    def test_cd7_4_entity_dominance_example_rendered(self, real_report):
        section = _section(real_report, "## 5. SERP Composition (Enriched Data)")
        assert "**Here's an example:**" in section
        assert "% of the results for" in section

    def test_cd7_4b_content_type_example_rendered(self, real_report):
        section = _section(real_report, "## 5. SERP Composition (Enriched Data)")
        assert "% of what ranks is" in section

    def test_cd7_5_unwritable_types_never_named_as_a_format(self, real_report):
        """CD.7.5 — "other" is the classifier's unknown bucket, not a format.

        In the real run "other" is the LARGEST content type at 51.1%, so a naive
        max() would tell the reader to "write that format". It must name the
        largest writable type instead.
        """
        section = _section(real_report, "## 5. SERP Composition (Enriched Data)")
        assert 'of what ranks is "other"' not in section
        assert 'of what ranks is "guide"' in section

    def test_cd7_5b_unwritable_entities_never_named(self, monkeypatch):
        """CD.7.5 — the same rule for entity types ("N/A" is not a competitor).

        The real run has "counselling" as the largest entity anyway, so it cannot
        exercise the filter. Force "N/A" to the top: a naive max() would then
        tell the reader they are writing against "N/A pages".
        """
        monkeypatch.setattr(
            gir.metrics, "get_entity_dominance",
            lambda run_id: {
                "entity_dominance": {"N/A": 62.0, "counselling": 30.0,
                                     "directory": 8.0},
                "content_dominance": {"guide": 100.0},
            })
        with open(REAL_JSON, encoding="utf-8") as f:
            report = generate_report(json.load(f))
        section = _section(report, "## 5. SERP Composition (Enriched Data)")
        assert "are N/A pages" not in section, (
            "the classifier's unknown bucket was named as the competition")
        assert "are counselling pages" in section, (
            "expected the largest *identified* entity type instead")

    def test_cd7_5c_unwritable_list_is_editorial(self):
        """CD.7.5 — the bucket list is config, not a Python literal."""
        raw = yaml.safe_load(open(
            os.path.join(REPO_ROOT, "report_writing_directives.yml"), encoding="utf-8"))
        assert "unwritable_content_types" in raw
        assert "other" in {str(v).lower() for v in raw["unwritable_content_types"]}
        assert "other" in gir._unwritable_content_types()

    def test_cd7_5d_all_types_unwritable_renders_no_example(self, monkeypatch):
        """CD.7.5 — when nothing writable ranks, say nothing rather than guess."""
        monkeypatch.setattr(
            gir, "_unwritable_content_types", lambda: {"other", "guide", "news",
                                                       "service", "n/a"})
        with open(REAL_JSON, encoding="utf-8") as f:
            report = generate_report(json.load(f))
        section = _section(report, "## 5. SERP Composition (Enriched Data)")
        assert "% of what ranks is" not in section


class TestCD7ExamplesAreGrounded:
    """CD.7 — examples must quote the run, not invent detail."""

    def test_cd7_6_example_values_come_from_the_keyword(self):
        """Values are that keyword's own question and vocabulary."""
        with open(REAL_JSON, encoding="utf-8") as f:
            data = json.load(f)
        kw = "family of origin work"
        vals = gir._example_values(data, kw)
        assert vals["keyword"] == kw
        assert vals["question"] in data["keyword_profiles"][kw]["paa_questions"]

    def test_cd7_6b_unknown_keyword_yields_blank_values_not_a_crash(self):
        with open(REAL_JSON, encoding="utf-8") as f:
            data = json.load(f)
        vals = gir._example_values(data, "no such keyword")
        assert vals["question"] == ""
        assert vals["components"] == ""

    def test_cd7_6c_no_example_renders_with_a_placeholder_left_in(self, real_report):
        """CD.7 — no rendered example leaks a brace or a None."""
        for line in real_report.split("\n"):
            if line.startswith("**Here's an example:**"):
                assert "{" not in line and "}" not in line, line
                assert "None" not in line, line
