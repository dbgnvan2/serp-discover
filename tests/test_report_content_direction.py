"""
Test suite for the Report Content Direction specification (CD).

Spec: report_content_direction_spec.md

Covers CD.1-CD.6: the "What To Write" content plan, per-section writing
directives, readable competitor phrases, the glossary, the standing jargon
guard, and the honest section-1/section-3 labelling.

Every test here has been mutation-checked: the line it names was deleted or
inverted, the test confirmed red, and the original restored (P27).
"""

import json
import os
import re
import sys

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import generate_insight_report as gir
import pattern_matching
from generate_insight_report import generate_report


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A real run, used wherever a criterion has to hold against a genuine artifact
# rather than an idealised fixture (P19).
#
# tests/fixtures/ holds a COMMITTED trim of the 2026-08-26 run that prompted this
# spec — same keys, same keywords, same feasibility rows and strategic
# recommendations, with the long result arrays cut down. It is committed because
# output/ is gitignored: gating on the original meant every real_data test
# skipped on any machine but the one that produced it, including the two the
# spec calls standing guards (the jargon guard and the get_ngrams regression).
# A guard that runs on one machine is close to no guard, and it reads as green
# everywhere else (P25/P29).
#
# The full artifact is preferred when present, so local runs still exercise the
# untrimmed data.
FIXTURE_JSON = os.path.join(
    REPO_ROOT, "tests", "fixtures", "market_analysis_reference_run.json")
FULL_RUN_JSON = os.path.join(
    REPO_ROOT, "output",
    "market_analysis_family_of_origin_work_20260826_2004.json")
REAL_JSON = FULL_RUN_JSON if os.path.exists(FULL_RUN_JSON) else FIXTURE_JSON


def _reset_gir_caches():
    """Clear every module-level cache a patched _REPO_ROOT can poison.

    Several tests point gir._REPO_ROOT at a tmp_path. That redirects FIVE
    loaders, not two: the pattern-intent and keyword-hint loaders do NOT swallow
    and would raise FileNotFoundError on a cold cache under a patched root, and
    any of the five can be populated from tmp_path and leak into later tests.
    Today only the fixtures' shape keeps that latent (P8).
    """
    gir._DIRECTIVES_CACHE = None
    gir._GLOSSARY_CACHE = None
    gir._PATTERN_EXAMPLE_CACHE = None
    gir._PATTERN_INTENT_CLASS_CACHE = None
    gir._KEYWORD_HINTS_CACHE = None


@pytest.fixture(autouse=True)
def _clear_config_caches():
    """Reset the module-level YAML caches around every test.

    generate_insight_report caches glossary.yml and report_writing_directives.yml
    in module globals. Tests that point those loaders at temporary files must not
    leak a patched cache into the next test, in either direction.
    """
    _reset_gir_caches()
    yield
    _reset_gir_caches()


@pytest.fixture
def real_data():
    # No skip: FIXTURE_JSON is committed, so this always has an artifact to read.
    # A missing file here is a repo problem and must fail, not skip.
    with open(REAL_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_cd11_6_reference_fixture_is_committed():
    """CD.11.6 — the guards' artifact is in the repo, not only on one machine.

    output/ is gitignored. Gating the standing guards on a file that lives there
    meant they skipped everywhere else and still reported green (P25/P29).
    """
    assert os.path.exists(FIXTURE_JSON), (
        "tests/fixtures/market_analysis_reference_run.json is missing — the "
        "real-artifact guards will skip on every clone")
    with open(FIXTURE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    # The fixture must still carry what the guards actually assert on.
    assert len(data["keyword_profiles"]) == 2
    assert len(data["keyword_feasibility"]) == 2
    assert data["serp_language_patterns"]
    assert {r["Pattern_Name"] for r in data["strategic_recommendations"]} == {
        "The Medical Model Trap", "The Resource Trap"}


@pytest.fixture
def real_report(real_data):
    return generate_report(real_data)


def _mock_data(keywords, feasibility=True, paa=True, features=None):
    """Build a minimal report input for `keywords` (an ordered list)."""
    overview = []
    for idx, kw in enumerate(keywords):
        row = {
            "Root_Keyword": kw,
            "Source_Keyword": kw,
            "Run_ID": "test_run",
            "Created_At": "2026-08-28T00:00:00",
            "Rank_1_Snippet": f"Bowen family systems therapy helps with {kw}.",
        }
        if features is not None:
            row["SERP_Features"] = features[idx]
        overview.append(row)

    profiles = {}
    for kw in keywords:
        profiles[kw] = {
            "serp_intent": {
                "primary_intent": "informational",
                "confidence": "high",
                "is_mixed": False,
                "mixed_components": [],
            },
            "has_ai_overview": True,
            "client_aio_cited": False,
            "has_local_pack": False,
            "paa_questions": ([f"What is {kw}?"] if paa else []),
            "recommended_play": {
                "play": "extraction_play",
                "label": "Extraction play (GEO)",
                "strategy_text": "Restructure the page answer-first.",
                "data_available": {"feasibility": True},
            },
            "entity_distribution": {"counselling": 8},
        }

    feas = []
    if feasibility:
        for kw in keywords:
            feas.append({
                "Keyword": kw,
                "Query_Label": "A",
                "feasibility_status": "High Feasibility",
                "client_da": 35,
                "avg_serp_da": 20.0,
                "gap": -15.0,
            })

    return {
        "overview": overview,
        "keyword_profiles": profiles,
        "keyword_feasibility": feas,
        "organic_results": [],
        "paa_questions": [],
        "related_searches": [],
        "derived_expansions": [],
        "autocomplete_suggestions": [],
        "competitors_ads": [],
    }


def _section(report, heading):
    """Return the text of one '## ' section, exclusive of the next one."""
    lines = report.split("\n")
    out, capturing = [], False
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            capturing = line.strip() == heading.strip()
            if capturing:
                continue
        if capturing:
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- CD.1


class TestCD1ContentPlan:
    """CD.1 — the 'What To Write' content plan."""

    def test_cd1_1_content_plan_section_placement(self, real_report):
        """CD.1.1 — §1 renders, after §0 and before §1b."""
        assert "## 1. What To Write" in real_report
        pos_exec = real_report.index("## 0. Executive Summary")
        pos_plan = real_report.index("## 1. What To Write")
        pos_overview = real_report.index("## 1b. Market Overview")
        assert pos_exec < pos_plan < pos_overview

    def test_cd1_2_exact_one_option_per_keyword(self, real_data, real_report):
        """CD.1.2 — exactly one option per keyword. Exact count, not a floor (P29)."""
        expected = len(real_data["keyword_profiles"])
        headings = re.findall(r"^### Option \d+ — ", real_report, re.MULTILINE)
        assert len(headings) == expected, (
            f"expected exactly {expected} options, found {len(headings)}")

    def test_cd1_2b_option_numbers_are_sequential(self, real_report):
        """CD.1.2 — numbering runs 1..N with no gaps or repeats."""
        numbers = [int(n) for n in
                   re.findall(r"^### Option (\d+) — ", real_report, re.MULTILINE)]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_cd1_3_option_order_matches_exec_summary(self, real_data, real_report):
        """CD.1.3 — Option 1 is the Executive Summary's best keyword.

        The highest-regression-risk criterion in the spec: a report that names one
        keyword in §0 and a different Option 1 in §1 is worse than no plan.
        """
        config = gir._load_config()
        preferred = config.get("client", {}).get("preferred_intents", ["informational"])
        best_kw, _ = gir._get_best_opportunity_keyword(
            real_data["keyword_profiles"],
            real_data.get("keyword_feasibility", []),
            preferred)
        assert best_kw, "fixture must have a best keyword for this test to mean anything"
        first = re.search(r"^### Option 1 — (.+)$", real_report, re.MULTILINE)
        assert first, "no Option 1 rendered"
        assert first.group(1).strip() == best_kw

    def test_cd1_3b_order_agrees_on_partial_feasibility(self):
        """CD.1.3 — the §0/§1 pin holds when only SOME keywords have DA data.

        This is the exact case the pin exists for, and it has to be built
        deliberately: §0 ranks only keywords that appear in the feasibility
        table, §1 lists every keyword. Give "zebra topic" a feasibility row of
        "Not Measured" (which scores 0, like having none) and give "alpha topic"
        no row at all, and the two rankings tie on every numeric component and
        break the tie alphabetically over different sets — §0 picks zebra
        because it is the only candidate, §1 picks alpha because it sorts first.
        Without the pin, Option 1 contradicts the Executive Summary.
        """
        data = _mock_data(["zebra topic", "alpha topic"], feasibility=False)
        data["keyword_feasibility"] = [{
            "Keyword": "zebra topic",
            "Query_Label": "A",
            "feasibility_status": "Not Measured",
            "client_da": None,
            "avg_serp_da": None,
            "gap": None,
        }]

        best_kw, _ = gir._get_best_opportunity_keyword(
            data["keyword_profiles"], data["keyword_feasibility"], ["informational"])
        assert best_kw == "zebra topic", (
            "fixture no longer produces the divergence this test exists to cover")
        unpinned = gir._rank_keywords(
            data["keyword_profiles"], data["keyword_feasibility"], ["informational"])
        assert unpinned[0][0] == "alpha topic", (
            "fixture no longer diverges: the raw ranking already agrees with §0, "
            "so this test would pass with the pin removed")

        report = generate_report(data)
        first = re.search(r"^### Option 1 — (.+)$", report, re.MULTILINE)
        assert first, "no Option 1 rendered"
        assert first.group(1).strip() == best_kw

    def test_cd1_4_option_carries_all_fields(self, real_report):
        """CD.1.4 — every option renders all seven fields."""
        plan = _section(real_report, "## 1. What To Write")
        blocks = plan.split("### Option ")[1:]
        assert blocks, "no option blocks found"
        required = [
            "**Page type:**",
            "**Why this one:**",
            "**Target search:**",
            "**What the page must do:**",
            "**Questions to use as headings:**",
            "**Terms to work in:**",
            "**Success looks like:**",
        ]
        for block in blocks:
            for field in required:
                assert field in block, f"{field} missing from option block: {block[:60]}"

    def test_cd1_5_no_padding_below_three(self):
        """CD.1.5 — two keywords produce two options, not three."""
        report = generate_report(_mock_data(["alpha topic", "beta topic"]))
        headings = re.findall(r"^### Option \d+ — ", report, re.MULTILINE)
        assert len(headings) == 2

    def test_cd1_5b_single_keyword_reads_singular(self):
        """CD.1.5 — a one-keyword run says 'page', not 'pages'."""
        report = generate_report(_mock_data(["alpha topic"]))
        plan = _section(report, "## 1. What To Write")
        assert "1 page to consider" in plan
        assert len(re.findall(r"^### Option \d+ — ", report, re.MULTILINE)) == 1

    def test_cd1_6_missing_paa_stated_not_blank(self):
        """CD.1.6 — no PAA data produces an honest line, not an empty heading."""
        report = generate_report(_mock_data(["alpha topic"], paa=False))
        plan = _section(report, "## 1. What To Write")
        assert "None captured for this search" in plan

    def test_cd1_6b_no_keywords_states_so(self):
        """CD.1.6 — an empty run says there is nothing to write."""
        report = generate_report(_mock_data([]))
        plan = _section(report, "## 1. What To Write")
        assert "nothing to" in plan.lower()

    def test_cd1_7_terms_are_per_keyword(self, real_data):
        """CD.1.4 — each option's terms come from its own SERP, not a global list.

        Two keywords whose snippets share no vocabulary must not be given the same
        'Terms to work in' line — that would read as per-keyword advice while
        being a single run-wide list.
        """
        data = _mock_data(["alpha topic", "beta topic"])
        data["overview"][0]["Rank_1_Snippet"] = (
            "emotional cutoff and emotional cutoff in differentiation work "
            "emotional cutoff")
        data["overview"][1]["Rank_1_Snippet"] = (
            "blended families and blended families in stepfamily care "
            "blended families")
        report = generate_report(data)
        plan = _section(report, "## 1. What To Write")
        term_lines = re.findall(r"\*\*Terms to work in:\*\* (.+)$", plan, re.MULTILINE)
        assert len(term_lines) == 2
        assert term_lines[0] != term_lines[1], (
            "both options got identical terms — the per-keyword filter is not applied")
        assert "emotional cutoff" in term_lines[0]
        assert "blended families" in term_lines[1]

    def test_cd1_8_play_honesty_note_rendered(self, real_report):
        """CD.1.4 — a play routed on partial inputs carries its caveat.

        Showing strategy_text without the producer's note presents a
        low-confidence verdict as settled fact (P2/P14).
        """
        plan = _section(real_report, "## 1. What To Write")
        assert "Caveat:" in plan
        assert "feasibility/DA data unavailable" in plan

    def test_cd1_9_feasibility_conflict_flagged(self, real_report):
        """CD.1.4 — a play routed without DA data against a measured High
        Feasibility is named as a disagreement, not silently shown as both."""
        plan = _section(real_report, "## 1. What To Write")
        assert "These two disagree" in plan

    def test_cd1_9b_no_conflict_flag_when_inputs_present(self):
        """CD.1.4 — the disagreement notice fires only on the real conflict."""
        report = generate_report(_mock_data(["alpha topic"]))
        plan = _section(report, "## 1. What To Write")
        assert "These two disagree" not in plan

    def test_cd1_10_da_gap_within_noise_not_called_a_direction(self):
        """CD.1.4 — a sub-threshold DA gap reads as level, not as a winner.

        DA is a 0-100 third-party estimate; declaring "they are stronger" off 0.6
        points would contradict the High Feasibility status on noise.
        """
        data = _mock_data(["alpha topic"])
        data["keyword_feasibility"][0].update(
            {"client_da": 35, "avg_serp_da": 35.6, "gap": 0.6})
        report = generate_report(data)
        plan = _section(report, "## 1. What To Write")
        assert "effectively level" in plan
        assert "they are stronger than you" not in plan


# ---------------------------------------------------------------- CD.2


class TestCD2WritingDirectives:
    """CD.2 — per-section writing directives."""

    DIRECTIVE_SECTIONS = [
        ("section_1b", "## 1b. Market Overview"),
        ("section_2", "## 2. The 'Anxiety Loop' (User Intent)"),
        ("section_3", "## 3. The Words Competitors Use"),
        ("section_4", "## 4. Strategic Recommendations (The Bridge)"),
        ("section_5", "## 5. SERP Composition (Enriched Data)"),
        ("section_5b", "## 5b. Per-Keyword SERP Intent"),
        ("section_5c", "## 5c. Keyword Feasibility & Pivot Recommendations"),
        ("section_5d", "## 5d. AI Overview Exposure"),
        ("section_5e", "## 5e. Query Commodity / AI-Absorption Risk"),
    ]

    def test_cd2_1_directive_present_each_section(self, real_report):
        """CD.2.1 — every configured section renders its directive.

        Exact membership over the configured set, not a count (P29): a section
        that silently loses its directive fails here.
        """
        configured = (gir._load_directives().get("directives") or {})
        missing = []
        for key, heading in self.DIRECTIVE_SECTIONS:
            if key not in configured:
                continue
            if heading not in real_report:
                continue
            body = _section(real_report, heading)
            if "**When you write:**" not in body:
                missing.append(key)
        assert not missing, f"sections rendered without their directive: {missing}"

    def test_cd2_1b_all_yaml_directives_are_reachable(self, real_report):
        """CD.2.1 — no directive sits in the YAML with no section to render it.

        Catches the P25 shape: editorial text added to config that no surface
        ever passes through to the reader.
        """
        configured = set((gir._load_directives().get("directives") or {}).keys())
        known = {key for key, _ in self.DIRECTIVE_SECTIONS}
        orphaned = configured - known
        assert not orphaned, (
            f"directives with no known section: {sorted(orphaned)} — either wire "
            "them up or remove them from report_writing_directives.yml")

    def test_cd2_2_directive_text_sourced_from_yaml(self, tmp_path, monkeypatch):
        """CD.2.2 — behavioural: change the YAML, change the output.

        Asserts the wiring by observing output, not by grepping source (P19
        corollary).
        """
        sentinel = "SENTINEL-DIRECTIVE-TEXT-9f2a"
        cfg = tmp_path / "report_writing_directives.yml"
        cfg.write_text(yaml.safe_dump({
            "directives": {"section_2": sentinel},
            "page_types": {"unknown": {"default": "x"}},
        }), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._DIRECTIVES_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert sentinel in report

    def test_cd2_3_missing_yaml_degrades_safely(self, tmp_path, monkeypatch):
        """CD.2.3 — a missing directives file loses the directives, not the report."""
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))  # no YAML here
        gir._DIRECTIVES_CACHE = None
        gir._GLOSSARY_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert "## 1. What To Write" in report
        assert "### Option 1 — alpha topic" in report
        assert "**When you write:**" not in report

    def test_cd2_3b_malformed_yaml_degrades_safely(self, tmp_path, monkeypatch):
        """CD.2.3 — a YAML file that parses to the wrong shape must not raise."""
        cfg = tmp_path / "report_writing_directives.yml"
        cfg.write_text("- this is a list, not a mapping\n", encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._DIRECTIVES_CACHE = None
        gir._GLOSSARY_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert "### Option 1 — alpha topic" in report

    def test_cd2_4_directive_follows_its_heading(self, real_report):
        """CD.2.1 — the directive sits under the heading it belongs to, and a
        blank line separates it so Markdown does not fold it into a list."""
        lines = real_report.split("\n")
        idx = lines.index("## 2. The 'Anxiety Loop' (User Intent)")
        window = lines[idx:idx + 6]
        directive_at = next(
            i for i, l in enumerate(window) if l.startswith("**When you write:**"))
        assert window[directive_at - 1].strip() == ""

    def test_cd2_5_page_types_sourced_from_yaml(self, tmp_path, monkeypatch):
        """CD.2.2 — page-type labels are editorial config, not Python literals."""
        sentinel = "SENTINEL-PAGE-TYPE-4b1c"
        cfg = tmp_path / "report_writing_directives.yml"
        cfg.write_text(yaml.safe_dump({
            "directives": {},
            "page_types": {"extraction_play": {"default": sentinel}},
        }), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._DIRECTIVES_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert sentinel in report


# ---------------------------------------------------------------- CD.3


class TestCD3DisplayPhrases:
    """CD.3 — phrases a human can read."""

    def test_cd3_1_internal_stopwords_preserved(self):
        """CD.3.1 — 'family of origin' survives intact, never 'family origin'."""
        out = pattern_matching.get_display_ngrams("family of origin work", 3)
        assert "family of origin" in out
        assert "family origin" not in out

    def test_cd3_1b_get_ngrams_still_strips_them(self):
        """CD.3.1 — the contrast is real: get_ngrams keeps its old behaviour."""
        assert "family origin" in pattern_matching.get_ngrams("family of origin work", 2)

    def test_cd3_2_no_cross_connector_phrases(self):
        """CD.3.2 — words made adjacent only by deleting a connector never pair."""
        text = "Family Institute at Greater Vancouver"
        produced = (pattern_matching.get_display_ngrams(text, 2)
                    + pattern_matching.get_display_ngrams(text, 3))
        assert "family greater" not in produced
        assert "family institute" in produced

    def test_cd3_2b_leading_and_trailing_stopwords_dropped(self):
        """CD.3.2 — a span may not begin or end on a stop word."""
        for phrase in pattern_matching.get_display_ngrams("family of origin work", 3):
            first, last = phrase.split()[0], phrase.split()[-1]
            assert first not in pattern_matching.STOP_WORDS
            assert last not in pattern_matching.STOP_WORDS

    def test_cd3_3_keyword_echo_suppressed(self):
        """CD.3.3 — a phrase that is a sub-span of the search term is not a finding."""
        assert pattern_matching.is_keyword_echo(
            "family of origin", ["family of origin work"])
        assert not pattern_matching.is_keyword_echo(
            "emotional cutoff", ["family of origin work"])

    def test_cd3_3b_echo_excluded_from_counted_phrases(self):
        """CD.3.3 — suppression is applied by get_display_phrases, not just
        available as a helper (the P21 'built but not wired' shape)."""
        texts = ["family of origin work matters"] * 5
        phrases = [r["Phrase"] for r in pattern_matching.get_display_phrases(
            texts, keywords=["family of origin work"])]
        assert "family of origin" not in phrases

    def test_cd3_3c_echo_kept_when_no_keywords_given(self):
        """CD.3.3 — suppression is scoped to the analysed keywords."""
        texts = ["family of origin work matters"] * 5
        phrases = [r["Phrase"] for r in pattern_matching.get_display_phrases(
            texts, keywords=None)]
        assert "family of origin" in phrases

    def test_cd3_4_thin_input_states_insufficient_data(self):
        """CD.3.4 — all-echo input renders the honest message, not a padded list.

        Zero-from-non-empty is reported as a finding, not passed off as silence
        (P19).
        """
        data = _mock_data(["family of origin work"])
        data["overview"][0].pop("Rank_1_Snippet")
        data["related_searches"] = [
            {"Source_Keyword": "family of origin work",
             "Term": "family of origin work"}
            for _ in range(5)
        ]
        report = generate_report(data)
        section = _section(report, "## 3. The Words Competitors Use")
        assert "No distinct competitor vocabulary" in section
        assert "occurrences" not in section

    def test_cd3_4b_no_source_text_distinguished_from_no_findings(self):
        """CD.3.4 — 'nothing captured' and 'nothing distinct' are different
        messages, so an empty run cannot masquerade as an analysed one (P2)."""
        data = _mock_data(["alpha topic"])
        for row in data["overview"]:
            row.pop("Rank_1_Snippet", None)
        data.pop("serp_language_patterns", None)
        report = generate_report(data)
        section = _section(report, "## 3. The Words Competitors Use")
        assert "No competitor text was captured" in section

    def test_cd3_5_get_ngrams_and_triggers_unchanged(self, real_data):
        """CD.3.5 — the shared function and its trigger matching are untouched.

        Runs against the real artifact, not a synthetic fixture (P19). CD.3 added
        a parallel display path precisely so this stayed true; if get_ngrams is
        ever "tidied up" to fix display, this goes red.
        """
        texts = pattern_matching.collect_snippet_texts(
            overview=real_data.get("overview") or [],
            competitors=real_data.get("competitors_ads") or [],
            expansion=(real_data.get("related_searches") or [])
                      + (real_data.get("derived_expansions") or []),
            autocomplete=real_data.get("autocomplete_suggestions") or [],
        )
        assert texts, "real fixture must carry snippet text"

        # get_ngrams still strips stop words before joining.
        grams = []
        for t in texts:
            grams.extend(pattern_matching.get_ngrams(t, 2))
        assert "family origin" in grams

        # And the Bowen trigger matcher still fires on the stored patterns.
        stored = real_data.get("serp_language_patterns") or []
        assert stored, "real fixture must carry serp_language_patterns"
        recs = pattern_matching.analyze_strategic_opportunities(
            stored, keywords=list(real_data.get("keyword_profiles", {}).keys()))
        detected = {r["Pattern_Name"] for r in recs}
        assert "The Medical Model Trap" in detected
        assert "The Resource Trap" in detected

    def test_cd3_6_display_phrases_wired_to_report(self, real_report):
        """CD.3.6 — §3 shows the readable phrases, not the stripped ones."""
        section = _section(real_report, "## 3. The Words Competitors Use")
        assert "occurrences" in section
        assert "family greater" not in section
        assert "family systems" in section

    def test_cd3_6b_stored_key_preferred_over_recompute(self):
        """CD.3.6 — serp_display_phrases is consumed when present."""
        data = _mock_data(["alpha topic"])
        data["serp_display_phrases"] = [
            {"Phrase": "stored sentinel phrase", "Count": 7}]
        report = generate_report(data)
        section = _section(report, "## 3. The Words Competitors Use")
        assert "stored sentinel phrase" in section
        assert "(7 occurrences)" in section

    def test_cd3_6c_recomputes_when_key_absent(self, real_data):
        """CD.3.6 — a JSON written before CD.3 still gets readable phrases.

        The real fixture predates serp_display_phrases, which is the point.
        """
        assert "serp_display_phrases" not in real_data
        rows = gir._display_phrases_for_report(real_data)
        assert rows, "fallback recompute produced nothing"
        phrases = {r["Phrase"] for r in rows}
        # The defect this names is a phrase whose words were only made adjacent
        # by deleting a connector. Assert against that phrase, not against the
        # word "greater" — "greater vancouver" is a real contiguous quote, and
        # the earlier form checked only the FIRST word, so "family greater"
        # (the actual defect) would have passed.
        assert "family greater" not in phrases
        for phrase in phrases:
            assert phrase not in ("family origin", "origin family"), (
                f"{phrase!r} is a stop-word-stripped artifact, not a quote")

    def test_cd3_7_collector_is_shared_by_producer_and_consumer(self):
        """CD.3 — serp_audit and the report generator use ONE snippet collector,
        so the two cannot drift apart on which fields hold competitor text (P19)."""
        import ast
        import serp_audit
        # Behavioural half: the same function object is reachable from both.
        assert serp_audit.pattern_matching.collect_snippet_texts \
            is pattern_matching.collect_snippet_texts
        # And serp_audit actually calls it. Parse for the call node rather than
        # grepping for a substring, which a comment mentioning the name would
        # satisfy just as well (P19 corollary).
        src = open(os.path.join(REPO_ROOT, "serp_audit.py"), encoding="utf-8").read()
        called = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called.add(func.attr)
                elif isinstance(func, ast.Name):
                    called.add(func.id)
        assert "collect_snippet_texts" in called, (
            "serp_audit.py has no call to collect_snippet_texts — it has its "
            "own copy of the snippet-field list, which will drift")


# ---------------------------------------------------------------- CD.4 / CD.5


class TestCD4Glossary:
    """CD.4 — the glossary appendix."""

    def test_cd4_1_glossary_section_present(self, real_report):
        """CD.4.1 — the glossary renders, and renders last."""
        assert "## A. Glossary" in real_report
        after = real_report[real_report.index("## A. Glossary") + 1:]
        assert "## " not in after, "a section follows the glossary"

    def test_cd4_2_every_rendered_term_defined(self, real_report):
        """CD.4.2 — every glossary term used in the body is defined below it."""
        body = real_report[:real_report.index("## A. Glossary")]
        glossary = real_report[real_report.index("## A. Glossary"):]
        undefined = []
        for entry in gir._load_glossary():
            if gir.term_appears_in(body, entry):
                if f"**{entry['term']}**" not in glossary:
                    undefined.append(entry["term"])
        assert not undefined, f"used in the report but not defined: {undefined}"

    def test_cd4_3_absent_terms_omitted(self, real_report):
        """CD.4.3 — a term the report never used is not defined."""
        body = real_report[:real_report.index("## A. Glossary")]
        glossary = real_report[real_report.index("## A. Glossary"):]
        wrongly_present = [
            e["term"] for e in gir._load_glossary()
            if not gir.term_appears_in(body, e)
            and f"**{e['term']}**" in glossary
        ]
        assert not wrongly_present, (
            f"defined but never used in this run: {wrongly_present}")

    def test_cd4_3b_some_term_actually_omitted(self, real_report):
        """CD.4.3 — the filter does something: this run does not use every term.

        Without this, test_cd4_3 would pass trivially if the filter were removed
        and every term rendered.
        """
        body = real_report[:real_report.index("## A. Glossary")]
        unused = [e["term"] for e in gir._load_glossary()
                  if not gir.term_appears_in(body, e)]
        assert unused, (
            "every glossary term appears in this run, so CD.4.3 proves nothing "
            "here — add a term this run cannot contain, or use another fixture")

    def test_cd4_4_definitions_sourced_from_yaml(self, tmp_path, monkeypatch):
        """CD.4.4 — behavioural: the definition text comes from glossary.yml."""
        sentinel = "SENTINEL-DEFINITION-7c3d"
        cfg = tmp_path / "glossary.yml"
        cfg.write_text(yaml.safe_dump({
            "terms": [{"term": "Domain Authority",
                       "aliases": ["Domain Authority", "DA"],
                       "definition": sentinel}]
        }), encoding="utf-8")
        (tmp_path / "report_writing_directives.yml").write_text(
            yaml.safe_dump({"directives": {}, "page_types": {}}), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._GLOSSARY_CACHE = None
        gir._DIRECTIVES_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert sentinel in report

    def test_cd4_5_missing_glossary_degrades_safely(self, tmp_path, monkeypatch):
        """CD.4 — no glossary.yml loses the appendix, not the report."""
        (tmp_path / "report_writing_directives.yml").write_text(
            yaml.safe_dump({"directives": {}, "page_types": {}}), encoding="utf-8")
        monkeypatch.setattr(gir, "_REPO_ROOT", str(tmp_path))
        gir._GLOSSARY_CACHE = None
        gir._DIRECTIVES_CACHE = None
        report = generate_report(_mock_data(["alpha topic"]))
        assert "### Option 1 — alpha topic" in report
        assert "## A. Glossary" not in report

    def test_cd4_6_term_match_is_whole_word(self):
        """CD.4 — matching is anchored, so prose containing the letters does not
        count as a use of the term (P19 corollary)."""
        entry = {"term": "DA", "aliases": ["DA"], "definition": "x"}
        assert not gir.term_appears_in("the panda ate", entry)
        assert gir.term_appears_in("the DA gap is wide", entry)

    def test_cd4_7_every_glossary_entry_has_a_definition(self):
        """CD.4 — no entry in the YAML is missing its definition."""
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "glossary.yml"), encoding="utf-8"))
        for entry in raw["terms"]:
            assert entry.get("term"), f"entry with no term: {entry}"
            assert str(entry.get("definition") or "").strip(), (
                f"{entry.get('term')} has no definition")


class TestCD5JargonGuard:
    """CD.5 — the standing guard against new undefined jargon."""

    # Terms of art a reader could not be expected to know. Every one must either
    # be absent from the report or carry a glossary definition. Exact membership,
    # deliberately not a count (P29).
    GUARDED_TERMS = [
        "SERP", "PAA", "AIO", "AI Overview", "Domain Authority", "DA gap",
        "CTR", "GEO", "FAQPage", "Local Map Pack", "Featured Snippet",
        "Knowledge Panel", "commodity score", "SERP homogeneity",
        "answer similarity", "entity dominance", "backdoor", "extraction play",
        "rank play", "cited-share",
    ]

    def test_cd5_1_no_undefined_jargon(self, real_report):
        """CD.5.1 — every guarded term in the body has a glossary definition."""
        split = real_report.index("## A. Glossary")
        body, glossary = real_report[:split], real_report[split:]
        entries = gir._load_glossary()

        undefined = []
        for term in self.GUARDED_TERMS:
            if not re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)',
                             body, re.IGNORECASE):
                continue
            covered = any(
                f"**{e['term']}**" in glossary
                and any(a.lower() == term.lower()
                        for a in gir.glossary_term_aliases(e))
                for e in entries)
            if not covered:
                undefined.append(term)
        assert not undefined, (
            f"jargon used in the report with no glossary entry: {undefined} — "
            "add each to glossary.yml or remove it from the report")

    def test_cd5_2_guard_catches_removed_definition(self, real_data, monkeypatch):
        """CD.5.2 — the guard is not vacuous: drop a definition and it fires.

        Proves the check can fail, rather than passing because it never looks
        (P27). Uses the same logic as CD.5.1 against a glossary with one entry
        deliberately removed.
        """
        full = gir._load_glossary()
        target = next(e for e in full if e["term"] == "Domain Authority")
        reduced = [e for e in full if e["term"] != "Domain Authority"]
        monkeypatch.setattr(gir, "_GLOSSARY_CACHE", reduced)

        report = generate_report(real_data)
        split = report.index("## A. Glossary")
        body, glossary = report[:split], report[split:]

        assert re.search(r'(?<!\w)Domain Authority(?!\w)', body), (
            "fixture must use the term for this test to mean anything")
        covered = any(
            f"**{e['term']}**" in glossary
            and any(a.lower() == "domain authority"
                    for a in gir.glossary_term_aliases(e))
            for e in reduced)
        assert not covered, "removing the entry did not make the term undefined"
        assert target["term"] == "Domain Authority"

    def test_cd5_3_guarded_terms_exist_in_glossary(self):
        """CD.5 — every guarded term is actually definable.

        A guard listing a term glossary.yml has never heard of would fire on the
        first report that used it, with no way to satisfy it.
        """
        aliases = set()
        for entry in gir._load_glossary():
            aliases.update(a.lower() for a in gir.glossary_term_aliases(entry))
        missing = [t for t in self.GUARDED_TERMS if t.lower() not in aliases]
        assert not missing, (
            f"guarded terms with no glossary.yml entry: {missing}")


# ---------------------------------------------------------------- CD.6


class TestCD6HonestLabelling:
    """CD.6 — §1b and §3 stop claiming more than the data supports."""

    def test_cd6_1_feature_counts_not_dominance_claim(self, real_report):
        """CD.6.1 — features carry per-keyword counts; 'Dominant' is gone."""
        assert "Dominant SERP Features" not in real_report
        overview = _section(real_report, "## 1b. Market Overview")
        assert "Search page features found" in overview
        assert re.search(r"Local Map Pack — \d+ of \d+ keywords?", overview)

    def test_cd6_1b_counts_reflect_the_data(self):
        """CD.6.1 — the count is the real number of keywords showing the feature."""
        data = _mock_data(
            ["a topic", "b topic", "c topic"],
            features=["Local Map Pack", "Local Map Pack, Video Carousel",
                      "Standard Organic"])
        report = generate_report(data)
        overview = _section(report, "## 1b. Market Overview")
        assert "Local Map Pack — 2 of 3 keywords" in overview
        assert "Video Carousel — 1 of 3 keywords" in overview

    def test_cd6_2_standard_organic_rendered_as_null_result(self):
        """CD.6.2 — the fallback string is never listed as a feature."""
        data = _mock_data(["a topic", "b topic"],
                          features=["Standard Organic", "Standard Organic"])
        report = generate_report(data)
        overview = _section(report, "## 1b. Market Overview")
        assert "Standard Organic" not in overview
        assert "No extra features — 2 of 2 keywords" in overview

    def test_cd6_2b_mixed_run_reports_both(self):
        """CD.6.2 — a run with some featured and some plain reports each honestly."""
        data = _mock_data(["a topic", "b topic"],
                          features=["Local Map Pack", "Standard Organic"])
        report = generate_report(data)
        overview = _section(report, "## 1b. Market Overview")
        assert "Local Map Pack — 1 of 2 keywords" in overview
        assert "No extra features — 1 of 2 keywords" in overview
        assert "Standard Organic" not in overview

    def test_cd6_3_section3_heading_matches_content(self, real_report):
        """CD.6.3 — §3 no longer promises the contrast §4 performs."""
        assert "## 3. The Words Competitors Use" in real_report
        assert "## 3. The 'Status Quo' (Competitor Language)" not in real_report
        section3 = _section(real_report, "## 3. The Words Competitors Use")
        # It may point AT section 4 for the contrast, but must not claim to be it.
        assert "Section 4 is where" in section3

    def test_cd6_3b_narrative_promise_lives_with_section_4(self, real_report):
        """CD.6.3 — the Medical Model vs. Systemic framing appears only as a
        pointer in §3, while §4 is the section that actually delivers it."""
        section4 = _section(real_report, "## 4. Strategic Recommendations (The Bridge)")
        assert "Medical Model" in section4

# ---------------------------------------------------------------- CD.11


class TestCD11SweepFixes:
    """CD.11 — fixes for the pre-push sweep findings on CD.1-CD.10."""

    def test_cd11_1_display_boundary_uses_generic_stop_words(self):
        """CD.11.1 — the market's own nouns must not block a phrase boundary.

        `stop_words` in serp_vocab.yml is a DOMAIN noise list — it contains
        counselling, therapy, clinic, vancouver, bc — because get_ngrams wants
        them stripped so Bowen triggers stand out. Using it as the display
        boundary rule made the "words competitors use" section structurally
        unable to emit the market's core vocabulary. This is the case the
        original CD.3 tests missed: "family of origin" passes under BOTH lists,
        because "of" is generic, so it could not detect the confusion.
        """
        text = "Family counselling services in North Vancouver for couples therapy."
        produced = set(pattern_matching.get_display_ngrams(text, 2))
        for phrase in ("family counselling", "couples therapy", "north vancouver"):
            assert phrase in produced, (
                f"{phrase!r} cannot be produced — the display boundary is using "
                "the domain noise list, not generic English")

    def test_cd11_1b_domain_terms_still_stripped_for_trigger_matching(self):
        """CD.11.1 — get_ngrams keeps the domain list. Both behaviours coexist."""
        grams = pattern_matching.get_ngrams(
            "family counselling services vancouver", 2)
        assert not any("counselling" in g for g in grams), (
            "get_ngrams should still strip domain nouns for trigger matching")

    def test_cd11_1c_display_list_holds_no_topic_nouns(self):
        """CD.11.1 — guard the editorial file against the same confusion."""
        display = pattern_matching.DISPLAY_STOP_WORDS
        for noun in ("counselling", "counseling", "counsellor", "therapy",
                     "therapist", "clinic", "centre", "center", "vancouver",
                     "bc", "british", "columbia", "north", "west", "canada",
                     "service", "services", "support", "help"):
            assert noun not in display, (
                f"{noun!r} is a topic noun and must not be a display stop word — "
                "it would delete every phrase beginning or ending on it")

    def test_cd11_1d_question_words_are_not_display_stop_words(self):
        """CD.11.1 — a phrase may legitimately start with a question word."""
        for word in ("how", "what", "why", "when", "where", "which", "who"):
            assert word not in pattern_matching.DISPLAY_STOP_WORDS

    def test_cd11_1e_short_content_word_no_longer_kills_the_span(self):
        """CD.11.1 — one short-but-meaningful token must not delete the phrase."""
        assert "counselling bc" in pattern_matching.get_display_ngrams(
            "counselling bc directory", 2)

    def test_cd11_2_empty_result_states_the_real_cause(self):
        """CD.11.2 — "nothing repeated" is not "everything was the search term".

        The single all-echo message was printed for every empty outcome, which
        states a confident wrong cause as if it were a finding (P14).
        """
        nothing_repeated = gir._no_phrases_message(
            {"texts": 8, "candidates": 12, "met_min_count": 0,
             "echo_suppressed": 0, "kept": 0, "min_count": 2})
        assert "No phrase appeared at least 2 times" in nothing_repeated
        assert "restatement" not in nothing_repeated

        all_echo = gir._no_phrases_message(
            {"texts": 8, "candidates": 12, "met_min_count": 4,
             "echo_suppressed": 4, "kept": 0, "min_count": 2})
        assert "restatements of the search terms" in all_echo

        nothing_captured = gir._no_phrases_message(
            {"texts": 0, "candidates": 0, "met_min_count": 0,
             "echo_suppressed": 0, "kept": 0, "min_count": 2})
        assert "No competitor text was captured" in nothing_captured

    def test_cd11_2b_stats_reflect_what_was_dropped(self):
        """CD.11.2 — the counts the message relies on are real."""
        stats = {}
        texts = ["family of origin work matters"] * 4 + ["emotional cutoff runs deep"] * 3
        pattern_matching.get_display_phrases(
            texts, keywords=["family of origin work"], stats=stats)
        assert stats["texts"] == 7
        assert stats["met_min_count"] >= 1
        assert stats["echo_suppressed"] >= 1
        assert stats["kept"] == stats["met_min_count"] - stats["echo_suppressed"]

    def test_cd11_3_stored_empty_list_is_respected(self):
        """CD.11.3 — an explicitly-stored empty result is a fact, not a gap.

        Truthiness made "the producer ran and honestly found nothing"
        indistinguishable from "this JSON predates the key", sending an honest
        empty result back through a recompute that could then print phrases the
        producer had deliberately suppressed (P2/P19).
        """
        data = _mock_data(["alpha topic"])
        data["overview"][0]["Rank_1_Snippet"] = (
            "emotional cutoff and emotional cutoff again emotional cutoff")
        data["serp_display_phrases"] = []
        rows, stats = gir._display_phrases_with_source(data)
        assert rows == [], "a stored empty list was overridden by a recompute"
        assert stats["stored"] is True

    def test_cd11_3b_absent_key_still_recomputes(self):
        """CD.11.3 — and the fallback for older JSONs still works."""
        data = _mock_data(["alpha topic"])
        data["overview"][0]["Rank_1_Snippet"] = (
            "emotional cutoff and emotional cutoff again emotional cutoff")
        data.pop("serp_display_phrases", None)
        rows, stats = gir._display_phrases_with_source(data)
        assert stats["stored"] is False
        assert rows, "the recompute fallback produced nothing"

    def test_cd11_3c_echo_vocabulary_prefers_the_analysed_keywords(self):
        """CD.11.3 — producer and consumer share ONE echo vocabulary.

        serp_audit suppresses echo against the CSV keyword list; the report used
        keyword_profiles.keys(). A keyword that produced no profile was missing
        from the consumer's set, so the report could print phrases the producer
        had suppressed, under a caption promising they were excluded.
        """
        data = _mock_data(["alpha topic"])
        data["analysed_keywords"] = ["alpha topic", "family of origin work"]
        assert gir._analysed_keywords(data) == [
            "alpha topic", "family of origin work"]

        data.pop("analysed_keywords")
        assert gir._analysed_keywords(data) == ["alpha topic"]

    def test_cd11_4_bad_config_value_degrades(self, monkeypatch):
        """CD.11.4 — a typo'd config number must not abort the run.

        The threshold was a module-level float() over a user-edited config, and
        serp_audit imports this module at top level, so `da_gap_noise_floor: ""`
        aborted the whole audit before a single SerpAPI call.
        """
        monkeypatch.setattr(
            gir, "_load_config",
            lambda: {"report": {"da_gap_noise_floor": "",
                                "phrase_min_count": "not a number"}})
        assert gir._da_gap_noise_floor() == gir._DA_GAP_NOISE_FLOOR_DEFAULT
        assert gir._phrase_min_count() == gir._PHRASE_MIN_COUNT_DEFAULT

    def test_cd11_4b_negative_config_value_degrades(self, monkeypatch):
        monkeypatch.setattr(
            gir, "_load_config", lambda: {"report": {"phrase_limit": -5}})
        assert gir._phrase_limit() == gir._PHRASE_LIMIT_DEFAULT

    def test_cd11_4c_valid_config_value_is_honoured(self, monkeypatch):
        monkeypatch.setattr(
            gir, "_load_config", lambda: {"report": {"da_gap_noise_floor": 7.5}})
        assert gir._da_gap_noise_floor() == 7.5

    def test_cd11_5_string_gap_does_not_break_the_plan(self):
        """CD.11.5 — a numeric-string gap must not collapse the content plan.

        One branch coerced with float() and the next compared the raw value, so
        a string gap raised TypeError inside _safe_section and replaced the
        whole of section 1 with "Section unavailable this run".
        """
        data = _mock_data(["alpha topic"])
        data["keyword_feasibility"][0]["gap"] = "-15.0"
        report = generate_report(data)
        assert "Section unavailable" not in report
        plan = _section(report, "## 1. What To Write")
        assert "### Option 1 — alpha topic" in plan
        assert "stronger site here" in plan

    def test_cd11_5b_unparseable_gap_omits_the_direction(self):
        """CD.11.5 — an unusable gap drops the claim rather than guessing."""
        data = _mock_data(["alpha topic"])
        data["keyword_feasibility"][0]["gap"] = "not a number"
        report = generate_report(data)
        assert "Section unavailable" not in report
        plan = _section(report, "## 1. What To Write")
        assert "stronger site here" not in plan
        assert "effectively level" not in plan
