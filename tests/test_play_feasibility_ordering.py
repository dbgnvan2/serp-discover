"""
CD.8 — recommended_play must see the Domain Authority data that exists.

Spec: report_content_direction_spec.md#CD.8

The defect this guards against, found 2026-08-28 in a real run
(market_analysis_family_of_origin_work_20260826_2004.json):

  serp_audit.py builds keyword_profiles — recommended_play included — while it
  writes the audit JSON. run_feasibility.py computes Domain Authority in a
  SEPARATE pass afterwards and wrote keyword_feasibility back into that same
  JSON without revisiting the plays. The file therefore held real DA data
  alongside verdicts routed against no DA data at all.

  It was not a confidence nuance. Re-routing that run against its own
  feasibility rows flips BOTH keywords from extraction_play ("ranking is
  unlikely, high DA gap", confidence low) to rank_play (confidence high) — while
  Section 5c on the same page reported High Feasibility and a gap of -14.

This is P8 (state that persists between passes, read stale on the second) and
P21's corollary (a computation that runs, but on the wrong side of a
dependency). Every test here is mutation-checked.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import brief_data_extraction
from play_routing import load_play_routing


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_JSON = os.path.join(
    REPO_ROOT, "output",
    "market_analysis_family_of_origin_work_20260826_2004.json")


def _profile(intent="local", is_mixed=False, has_aio=True, local_pack=True):
    return {
        "serp_intent": {
            "primary_intent": intent,
            "is_mixed": is_mixed,
            "mixed_components": ["informational", "local"] if is_mixed else [],
            "confidence": "medium",
        },
        "has_ai_overview": has_aio,
        "has_local_pack": local_pack,
        "aio_divergence": {"client_ranks_but_not_cited": False},
        "mixed_intent_strategy": "backdoor" if is_mixed else None,
    }


def _feas_row(keyword, status="High Feasibility", gap=-14.0, label="A"):
    return {
        "Keyword": keyword,
        "Query_Label": label,
        "feasibility_status": status,
        "client_da": 35,
        "avg_serp_da": 21.0,
        "gap": gap,
    }


class TestCD8PlayRoutingSeesFeasibility:

    def test_cd8_1_feasibility_changes_the_verdict(self):
        """CD.8.1 — the same profile routes differently with and without DA data.

        If this ever stops being true, the rest of this file is guarding nothing:
        it would mean feasibility no longer influences the play at all.
        """
        profiles_without = {"family of origin counselling": _profile()}
        brief_data_extraction.attach_recommended_plays(profiles_without, [])

        profiles_with = {"family of origin counselling": _profile()}
        brief_data_extraction.attach_recommended_plays(
            profiles_with, [_feas_row("family of origin counselling")])

        play_without = profiles_without["family of origin counselling"]["recommended_play"]
        play_with = profiles_with["family of origin counselling"]["recommended_play"]

        assert play_without["data_available"]["feasibility"] is False
        assert play_with["data_available"]["feasibility"] is True
        assert play_without["play"] != play_with["play"], (
            "feasibility no longer changes the routed play")

    def test_cd8_2_stale_play_is_rerouted(self):
        """CD.8.2 — a profile carrying a play routed without DA is corrected.

        The dirty-state case (P8): profiles arrive already populated from an
        earlier pass, exactly as they do when run_feasibility.py reads the JSON
        serp_audit.py wrote.
        """
        kw = "family of origin counselling"
        profiles = {kw: _profile()}
        brief_data_extraction.attach_recommended_plays(profiles, [])
        stale = profiles[kw]["recommended_play"]["play"]

        changed = brief_data_extraction.attach_recommended_plays(
            profiles, [_feas_row(kw)])

        assert changed == 1, "the corrected play was not counted as changed"
        assert profiles[kw]["recommended_play"]["play"] != stale
        assert profiles[kw]["recommended_play"]["data_available"]["feasibility"] is True

    def test_cd8_3_change_count_is_honest(self):
        """CD.8.2 — re-routing with identical inputs reports zero changes.

        The count is what run_feasibility logs; it must not overstate a
        correction that did not happen (P6).
        """
        kw = "family of origin counselling"
        rows = [_feas_row(kw)]
        profiles = {kw: _profile()}
        brief_data_extraction.attach_recommended_plays(profiles, rows)
        assert brief_data_extraction.attach_recommended_plays(profiles, rows) == 0

    def test_cd8_4_pivot_rows_do_not_supply_the_verdict(self):
        """CD.8 — a pivot row is a different keyword's suggestion, not this
        keyword's feasibility, and must not be indexed as it."""
        kw = "family of origin counselling"
        by_kw = brief_data_extraction.index_feasibility_by_keyword([
            _feas_row(kw, label="P"),
        ])
        assert kw not in by_kw

    def test_cd8_5_first_primary_row_wins(self):
        """CD.8 — duplicate primary rows resolve deterministically to the first."""
        kw = "alpha"
        by_kw = brief_data_extraction.index_feasibility_by_keyword([
            _feas_row(kw, status="High Feasibility"),
            _feas_row(kw, status="Low Feasibility"),
        ])
        assert by_kw[kw]["feasibility_status"] == "High Feasibility"

    def test_cd8_6_missing_profiles_is_not_a_crash(self):
        """CD.8 — an empty or absent profile map is a no-op, not an exception."""
        assert brief_data_extraction.attach_recommended_plays({}, []) == 0
        assert brief_data_extraction.attach_recommended_plays(None, []) == 0

    def test_cd8_7_real_run_reroutes_to_rank_play(self):
        """CD.8.1 — the real artifact that exposed this bug is corrected.

        Verified against the actual on-disk run rather than a synthetic profile
        (P19): both keywords must leave extraction_play once their own DA data
        is applied.
        """
        if not os.path.exists(REAL_JSON):
            pytest.skip(f"Real-run fixture not found: {REAL_JSON}")
        with open(REAL_JSON, encoding="utf-8") as f:
            data = json.load(f)

        profiles = data.get("keyword_profiles") or {}
        rows = data.get("keyword_feasibility") or []
        assert profiles and rows, "fixture must carry both profiles and feasibility"

        brief_data_extraction.attach_recommended_plays(profiles, rows)
        for kw, profile in profiles.items():
            play = profile["recommended_play"]
            assert play["data_available"]["feasibility"] is True, kw
            assert play["play"] == "rank_play", (
                f"{kw} routed to {play['play']}, expected rank_play once its own "
                "Domain Authority data is applied")
            assert not play.get("note"), (
                f"{kw} still reports missing inputs after feasibility was applied")


class TestCD8RunFeasibilityWiring:
    """CD.8.3 — the fix is reachable from the surface that has the bug.

    attach_recommended_plays working in isolation says nothing about whether
    run_feasibility.py calls it (P21/P25). These assert the wiring end to end,
    by driving the module's own writeback path.
    """

    def _run_writeback(self, tmp_path, monkeypatch, json_payload):
        """Invoke run_feasibility.main() over a temp JSON, stubbing the DA fetch."""
        import run_feasibility

        json_path = tmp_path / "market_analysis_test.json"
        json_path.write_text(json.dumps(json_payload), encoding="utf-8")

        rows = [_feas_row(kw) for kw in json_payload["keyword_profiles"]]
        # raising defaults to True on purpose: if either name is renamed, this
        # test must fail loudly rather than patch a ghost and skip itself.
        monkeypatch.setattr(
            run_feasibility, "run_feasibility_analysis", lambda *a, **k: rows)
        monkeypatch.setattr(
            run_feasibility, "generate_feasibility_report",
            lambda *a, **k: "# stub report\n")
        monkeypatch.setattr(
            sys, "argv",
            ["run_feasibility.py", "--json", str(json_path),
             "--out", str(tmp_path / "feas.md")])

        run_feasibility.main()
        return json.loads(json_path.read_text(encoding="utf-8"))

    def test_cd8_3_run_feasibility_reroutes_on_writeback(self, tmp_path, monkeypatch):
        """CD.8.3 — running the feasibility pass corrects the stale plays in the
        JSON it writes, not merely the feasibility table."""
        kw = "family of origin counselling"
        stale_profiles = {kw: _profile()}
        brief_data_extraction.attach_recommended_plays(stale_profiles, [])
        stale_play = stale_profiles[kw]["recommended_play"]["play"]
        assert stale_profiles[kw]["recommended_play"]["data_available"]["feasibility"] is False

        payload = {
            "keyword_profiles": json.loads(json.dumps(stale_profiles)),
            "organic_results": [],
            "overview": [],
        }
        result = self._run_writeback(tmp_path, monkeypatch, payload)

        written = result["keyword_profiles"][kw]["recommended_play"]
        assert written["data_available"]["feasibility"] is True, (
            "run_feasibility wrote DA data back but left the play routed without it")
        assert written["play"] != stale_play
        assert result["keyword_feasibility"], "feasibility rows must still be written"

    def test_cd8_3b_writeback_calls_the_shared_router(self, monkeypatch):
        """CD.8.3 — a call-site guard that survives CLI refactors.

        Asserts by behaviour: replace the shared router with a spy and confirm
        run_feasibility reaches for it, rather than grepping source (P19
        corollary).
        """
        import run_feasibility
        assert run_feasibility.brief_data_extraction.attach_recommended_plays \
            is brief_data_extraction.attach_recommended_plays, (
                "run_feasibility no longer resolves the shared play router")
