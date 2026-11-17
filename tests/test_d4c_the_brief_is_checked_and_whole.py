"""Guards for review chunk D4c — the brief is checked, and what is written is whole.

Spec: docs/review_2026-11-04/PLAN_D4c_the_brief_is_checked_and_whole.md
One guard per finding fixed (D4.11, D4.12, D4.13, D4.14, D4.16).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_validation
import generate_insight_report
import pipeline_status
import refresh_analysis_outputs


def _extracted(play="rank_play", client_rank=7, avg_da=42.0, gap=30.0):
    return {
        "queries": [],
        "keyword_profiles": {
            "family of origin work": {
                "client_rank": client_rank,
                "total_results": 1200,
                "total_results_measured": True,
                "recommended_play": {"play": play, "label": "Rank play"},
            }
        },
        "keyword_feasibility": [
            {"Keyword": "family of origin work", "Query_Label": "A",
             "avg_serp_da": avg_da, "gap": gap},
        ],
    }


# ---------------------------------------------------------------- D4.11

def test_d4_11_play_parity_sees_a_bare_label_under_a_keyword_heading():
    """A contradicting play is caught wherever the brief states it (D-C-07).

    The rule used to anchor on the Section-2 profile block and on the exact
    configured label, parenthetical included — so it fired only on a phrasing
    the model does not use, in a section it does not use.
    """
    report = (
        "## Brief 1: family of origin work\n\n"
        "Recommended play: **Extraction play**\n\n"
        "Write the page as a direct answer.\n"
    )
    issues = brief_validation.validate_llm_report(report, _extracted())
    assert any("assigns a different play" in i for i in issues), issues

    # The pre-computed play stated under the same heading is not a contradiction.
    ok = brief_validation.validate_llm_report(
        report.replace("Extraction play", "Rank play"), _extracted())
    assert not any("assigns a different play" in i for i in ok), ok

    # Overlapping keywords: real CSVs hold "couples counselling" and "couples
    # counselling for trust issues". A substring match made the longer
    # keyword's section the shorter one's, and both statements being true did
    # not stop the HARD rule aborting the report.
    overlapping = {
        "queries": [],
        "keyword_profiles": {
            "couples counselling": {
                "recommended_play": {"play": "rank_play", "label": "Rank play"}},
            "couples counselling for trust issues": {
                "recommended_play": {"play": "extraction_play",
                                     "label": "Extraction play"}},
        },
    }
    truthful = ("## couples counselling\n\nRecommended play: **Rank play**\n\n"
                "## couples counselling for trust issues\n\n"
                "Recommended play: **Extraction play**\n")
    bleed = brief_validation.validate_llm_report(truthful, overlapping)
    assert not any("assigns a different play" in i for i in bleed), bleed

    # Attribution is by phrase, not by substring.
    assert brief_validation._names_keyword("couples counselling", "counselling")
    assert not brief_validation._names_keyword("precounselling", "counselling")
    assert not brief_validation._names_keyword("counselling-services",
                                               "counselling")


# ---------------------------------------------------------------- D4.16

def test_d4_16_numbers_the_brief_restates_are_checked_against_the_data():
    """client_rank / avg_serp_da / gap / total_results are checked (D-M-27).

    None of these fields appeared in the validator, so a rank or SERP DA the
    model restated wrongly was written out as fact.
    """
    wrong = ("## family of origin work\n\n"
             "The client ranks #3 for this keyword.\n")
    issues = brief_validation.validate_llm_report(wrong, _extracted(client_rank=7))
    assert any("contradicts the data" in i for i in issues), issues

    right = wrong.replace("#3", "#7")
    assert not any("contradicts the data" in i for i in
                   brief_validation.validate_llm_report(right, _extracted(client_rank=7)))

    # An unmeasured field has no number to disagree with: that case belongs to
    # the gates that already cover it, not to this one.
    unmeasured = _extracted()
    unmeasured["keyword_feasibility"][0]["avg_serp_da"] = None
    da_claim = ("## family of origin work\n\n"
                "The average SERP Domain Authority is 80.\n")
    assert not any("contradicts the data" in i for i in
                   brief_validation.validate_llm_report(da_claim, unmeasured))

    # The fields must reach the validator on the path production uses: the
    # avg_serp_da and gap rules read `keyword_feasibility`, which the extractor
    # did not return, so the two checks matched nothing on a real run.
    import brief_data_extraction
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = os.path.join(
        repo, "output",
        "market_analysis_family-of-origin-seo-phrases_20260828_1433.json")
    if os.path.exists(fixture):
        with open(fixture) as fh:
            real = json.load(fh)
        extracted = brief_data_extraction.extract_analysis_data_from_json(
            real, "livingsystems.ca", ["Living Systems"])
        rows = extracted.get("keyword_feasibility") or []
        assert rows, "extract_analysis_data_from_json must return the rows"
        kw, da = rows[0]["Keyword"], rows[0]["avg_serp_da"]
        claim = f"## {kw}\n\nThe average SERP Domain Authority is 80.\n"
        assert any("contradicts the data" in i for i in
                   brief_validation.validate_llm_report(claim, extracted))
        true_claim = claim.replace("80", str(da))
        assert not any("contradicts the data" in i for i in
                       brief_validation.validate_llm_report(true_claim, extracted))

    # Demand language is gated per keyword, not per run: one measured volume
    # used to license the claim for every other keyword.
    mixed = {"queries": [], "keyword_profiles": {
        "kw one": {"moz": {"data_available": True, "volume": 1000}},
        "kw two": {}}}
    assert any("search demand for 'kw two'" in i for i in
               brief_validation.validate_llm_report(
                   "## kw two\n\nThis keyword gets 1,900 monthly searches.\n", mixed))
    assert not any("search demand" in i for i in
                   brief_validation.validate_llm_report(
                       "## kw one\n\nThis keyword gets 1,000 monthly searches.\n", mixed))

    # The duplicate definition of validate_extraction is gone: a second,
    # byte-identical copy shadowed the first, so edits to it did nothing.
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "brief_validation.py")) as fh:
        assert fh.read().count("\ndef validate_extraction(") == 1


# ---------------------------------------------------------------- D4.13

def test_d4_13_the_content_briefs_assembly_has_one_home(tmp_path, monkeypatch):
    """Both the pipeline and `--out` build the briefs from one function (D-C-12)."""
    data = {"strategic_recommendations": [], "keyword_profiles": {}}
    assert generate_insight_report.build_content_briefs_section(data) == []

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("serp_audit.py", "generate_insight_report.py"):
        with open(os.path.join(root, name)) as fh:
            src = fh.read()
        assert "build_content_briefs_section(" in src, name
    # The assembly is not inlined a second time in the audit.
    with open(os.path.join(root, "serp_audit.py")) as fh:
        assert '"# Content Briefs' not in fh.read()

    # A brief that cannot be rendered must not take the report with it: before
    # the briefs moved here, `--out` always wrote the report.
    src = tmp_path / "run.json"
    src.write_text(json.dumps({"overview": [], "analysed_keywords": []}))
    out = tmp_path / "run.md"
    monkeypatch.setattr(generate_insight_report, "build_content_briefs_section",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(sys, "argv",
                        ["generate_insight_report.py", "--json", str(src),
                         "--out", str(out)])
    generate_insight_report.main()
    written = out.read_text()
    assert written
    assert "boom" in written


# ---------------------------------------------------------------- D4.14

def test_d4_14_a_keyword_with_no_serp_data_is_named_and_changes_the_exit_code(tmp_path):
    """A failed fetch is reported, not absorbed (D-C-13).

    `root_keywords` derive from the overview rows, so the keyword was invisible
    to every count and to `validate_extraction`.
    """
    data = {
        "analysed_keywords": ["family of origin work", "couples counselling"],
        "overview": [{"Source_Keyword": "family of origin work"}],
        "keyword_profiles": {"family of origin work": {}},
        "root_keywords": ["family of origin work"],
    }
    assert brief_validation.missing_serp_keywords(data) == ["couples counselling"]

    # Both numbers are keywords. `overview` holds one row per query job, so
    # counting its rows reported 13 analysed for a run of 8.
    report = generate_insight_report.generate_report(
        {"overview": [{"Source_Keyword": "family of origin work",
                       "Query_Label": "A"},
                      {"Source_Keyword": "family of origin work",
                       "Query_Label": "A.1"}],
         "analysed_keywords": ["family of origin work", "couples counselling"],
         "keyword_profiles": {"family of origin work": {}}})
    assert "**Keywords Analyzed:** 1 of 2" in report, report[:400]
    assert "couples counselling" in report
    assert any("couples counselling" in w
               for w in brief_validation.validate_extraction(data))

    # The outputs are real for the keywords that did return, so they are kept
    # and recorded — but the exit code is not EXIT_OK, which is what gates the
    # run-completed stamp used as the rank-delta baseline.
    paths = {}
    for name, ext in (("json", ".json"), ("xlsx", ".xlsx"), ("md", ".md")):
        f = tmp_path / f"market_analysis_x{ext}"
        f.write_text("x")
        paths[name] = str(f)
    out = tmp_path / "market_analysis_x.json"
    cfg = tmp_path / "config.yml"
    cfg.write_text("files: {}\n")
    code = pipeline_status.finish_run(
        {k: True for k in paths}, paths, config_path=str(cfg),
        incomplete_keywords=["couples counselling"])
    assert code == pipeline_status.EXIT_PARTIAL
    assert code != pipeline_status.EXIT_OK
    assert out.exists() and not (tmp_path / "market_analysis_x.json.failed").exists()
    assert pipeline_status.exit_label("serp_audit.py", code) == "PARTIAL"
    assert pipeline_status.exit_label("run_pipeline.py", code) == "PARTIAL"
    # 2 from any other script is still an ordinary failure.
    assert pipeline_status.exit_label("validate_xlsx_vs_json.py", code) != "PARTIAL"


# ---------------------------------------------------------------- D4.12

def test_d4_12_the_refresh_rebuilds_what_reclassification_invalidates(tmp_path):
    """Re-classifying rows rebuilds the profiles derived from them (D-C-09).

    The refresh wrote `Entity_Type` and stopped, leaving `keyword_profiles` —
    entity counts, the entity distribution, the AIO citation analysis —
    describing the previous taxonomy.
    """
    data = {
        "overview": [{"Source_Keyword": "family of origin work", "Run_ID": "r1",
                      "Created_At": "2026-11-17", "Query_Label": "A"}],
        "organic_results": [{"Source_Keyword": "family of origin work",
                             "Query_Label": "A", "Rank": 1,
                             "Link": "https://psychologytoday.com/x",
                             "Source": "Psychology Today",
                             "Entity_Type": "directory"}],
        "keyword_profiles": {"family of origin work": {"stale": True}},
        "analysed_keywords": ["family of origin work"],
    }
    built, changed = refresh_analysis_outputs.rebuild_keyword_profiles(data, {})
    assert built == 1
    assert changed == 1
    assert data["keyword_profiles"]["family of origin work"] != {"stale": True}

    # And it says what a refresh cannot rebuild, so it is not read as a re-run.
    assert refresh_analysis_outputs.NOT_REBUILT
    assert any("Markdown report" in n for n in refresh_analysis_outputs.NOT_REBUILT)
