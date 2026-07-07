"""Tests for Y.12 foundational (transferable) GEO readiness score.

Spec: yoast_geo_upgrade_spec_v1.md#Y.12
- Y.12.1 deterministic; all-zero→0, all-max→100, mixed=hand-computed.
- Y.12.2 missing sub-score inputs → n/a, excluded from the weighted mean
  (renormalised), never counted as 0.
- Y.12.3 each sub-score surfaces gaps from EXISTING geo_alerts / schema recs,
  not new invented strings.
- Y.12.4 weights from config; table idempotent and trendable.
"""
import os
import sqlite3
import tempfile
import unittest

import foundational_score as fs


def _analysis_all_max():
    """Client pages fully extraction-ready; schema fully covered; no gaps."""
    return {
        "keyword_profiles": {
            "kw1": {
                "extractability": {
                    "data_available": True,
                    "client_page": {
                        "question_heading_count": 5,
                        "intro_text_length": 400,
                        "faq_present": True,
                    },
                },
                "schema_signals": {
                    "data_available": True,
                    "schema_type_counts": {
                        "FAQPage": 3, "ProfessionalService": 2, "LocalBusiness": 1,
                        "Person": 1, "Article": 1, "Organization": 1,
                    },
                },
            },
        },
        "strategic_flags": {"geo_alerts": []},
    }


def _analysis_all_zero():
    """Client pages with none of the extraction signals; no schema; no coverage."""
    return {
        "keyword_profiles": {
            "kw1": {
                "extractability": {
                    "data_available": True,
                    "client_page": {
                        "question_heading_count": 0,
                        "intro_text_length": 0,
                        "faq_present": False,
                    },
                },
                "schema_signals": {"data_available": True, "schema_type_counts": {}},
            },
        },
        "strategic_flags": {"geo_alerts": [
            {"keyword": "kw1", "detail": "Client ranks but the AI Overview cites others."},
        ]},
    }


_SCHEMA_RECS = [
    {"context": "faq_block", "label": "FAQ section", "schema_types": ["FAQPage"]},
    {"context": "service_page", "label": "Service page",
     "schema_types": ["ProfessionalService", "LocalBusiness"]},
    {"context": "practitioner_bio", "label": "Practitioner biography",
     "schema_types": ["Person"]},
    {"context": "educational_article", "label": "Educational article",
     "schema_types": ["Article"]},
    {"context": "organization_home", "label": "Organization / home page",
     "schema_types": ["Organization"]},
]


def _lb_all_max():
    """Client is the sole/leading brand → authority 100."""
    return {"openai": {"rows": [
        {"brand": "Living Systems", "mention_count": 5, "is_client": True},
    ]}}


def _lb_all_zero():
    """Client absent; a rival dominates → authority 0 + rival gap."""
    return {"openai": {"rows": [
        {"brand": "Psychology Today", "mention_count": 4, "is_client": False},
    ]}}


class TestSubscores(unittest.TestCase):
    def test_all_max_is_100(self):
        # Y.12.1
        r = fs.compute_foundational_score(_analysis_all_max(), _SCHEMA_RECS, _lb_all_max())
        self.assertEqual(r["subscores"]["accessibility"], 100.0)
        self.assertEqual(r["subscores"]["structure"], 100.0)
        self.assertEqual(r["subscores"]["authority"], 100.0)
        self.assertEqual(r["score"], 100.0)

    def test_all_zero_is_0(self):
        # Y.12.1
        r = fs.compute_foundational_score(_analysis_all_zero(), _SCHEMA_RECS, _lb_all_zero())
        self.assertEqual(r["subscores"]["accessibility"], 0.0)
        self.assertEqual(r["subscores"]["structure"], 0.0)
        self.assertEqual(r["subscores"]["authority"], 0.0)
        self.assertEqual(r["score"], 0.0)

    def test_mixed_hand_computed(self):
        # Y.12.1 — accessibility: 1 of 3 page signals present → 33.33.
        # structure: 3 of 6 recommended types observed → 50.0.
        # authority: client 2 / leader 4 → 50.0.
        # Equal thirds mean: (33.33 + 50 + 50)/3 = 44.44.
        analysis = {
            "keyword_profiles": {
                "kw1": {
                    "extractability": {
                        "data_available": True,
                        "client_page": {"question_heading_count": 3,
                                        "intro_text_length": 10, "faq_present": False},
                    },
                    "schema_signals": {
                        "data_available": True,
                        "schema_type_counts": {"FAQPage": 1, "Person": 1, "Article": 1},
                    },
                },
            },
            "strategic_flags": {"geo_alerts": []},
        }
        lb = {"openai": {"rows": [
            {"brand": "Rival", "mention_count": 4, "is_client": False},
            {"brand": "Living Systems", "mention_count": 2, "is_client": True},
        ]}}
        r = fs.compute_foundational_score(analysis, _SCHEMA_RECS, lb)
        self.assertEqual(r["subscores"]["accessibility"], 33.33)
        self.assertEqual(r["subscores"]["structure"], 50.0)
        self.assertEqual(r["subscores"]["authority"], 50.0)
        self.assertEqual(r["score"], 44.4)

    def test_deterministic(self):
        a, s, l = _analysis_all_max(), _SCHEMA_RECS, _lb_all_max()
        self.assertEqual(
            fs.compute_foundational_score(a, s, l),
            fs.compute_foundational_score(a, s, l))


class TestNaRenormalization(unittest.TestCase):
    def test_missing_inputs_are_na_and_excluded(self):
        # Y.12.2 — no extractability, no schema data, no leaderboard → all n/a.
        empty = {"keyword_profiles": {}, "strategic_flags": {"geo_alerts": []}}
        r = fs.compute_foundational_score(empty, _SCHEMA_RECS, None)
        self.assertIsNone(r["subscores"]["accessibility"])
        self.assertIsNone(r["subscores"]["structure"])
        self.assertIsNone(r["subscores"]["authority"])
        self.assertEqual(set(r["excluded"]), {"accessibility", "structure", "authority"})
        # No present sub-score → score 0.0 (nothing measurable), not fabricated.
        self.assertEqual(r["score"], 0.0)

    def test_na_axis_excluded_not_zero(self):
        # Y.12.2 — structure present (100), accessibility n/a, authority present
        # (100). n/a axis excluded → mean over the two present axes = 100, NOT
        # dragged toward 0 by a phantom zero.
        analysis = {
            "keyword_profiles": {
                "kw1": {
                    "schema_signals": {
                        "data_available": True,
                        "schema_type_counts": {
                            "FAQPage": 1, "ProfessionalService": 1, "LocalBusiness": 1,
                            "Person": 1, "Article": 1, "Organization": 1},
                    },
                    # no extractability key → accessibility n/a
                },
            },
            "strategic_flags": {"geo_alerts": []},
        }
        r = fs.compute_foundational_score(analysis, _SCHEMA_RECS, _lb_all_max())
        self.assertIsNone(r["subscores"]["accessibility"])
        self.assertEqual(r["subscores"]["structure"], 100.0)
        self.assertEqual(r["subscores"]["authority"], 100.0)
        self.assertEqual(r["score"], 100.0)  # not 66.7 — n/a truly excluded


class TestGapsFromExistingSources(unittest.TestCase):
    def test_accessibility_gaps_come_from_geo_alerts(self):
        # Y.12.3 — the gap text is the EXISTING geo_alert detail, verbatim.
        detail = "Client ranks in the organic top-10 but the AI Overview cites others."
        analysis = {
            "keyword_profiles": {
                "kw1": {"extractability": {
                    "data_available": True,
                    "client_page": {"question_heading_count": 0,
                                    "intro_text_length": 0, "faq_present": False}}},
            },
            "strategic_flags": {"geo_alerts": [{"keyword": "kw1", "detail": detail}]},
        }
        r = fs.compute_foundational_score(analysis, _SCHEMA_RECS, None)
        gaps = r["gaps"]["accessibility"]
        self.assertTrue(any(detail in g for g in gaps),
                        "accessibility gap must be sourced from the existing geo_alert detail")

    def test_structure_gaps_come_from_schema_rec_labels(self):
        # Y.12.3 — missing recommended type surfaces its EXISTING rec label.
        analysis = {
            "keyword_profiles": {
                "kw1": {"schema_signals": {
                    "data_available": True,
                    "schema_type_counts": {"FAQPage": 1}}},  # only FAQPage present
            },
            "strategic_flags": {"geo_alerts": []},
        }
        r = fs.compute_foundational_score(analysis, _SCHEMA_RECS, None)
        gaps = r["gaps"]["structure"]
        # The rec labels for missing types (Service page, Practitioner biography,
        # Educational article, Organization) must be the source of the gap text.
        rec_labels = {rec["label"] for rec in _SCHEMA_RECS}
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertTrue(any(label in gap for label in rec_labels),
                            f"structure gap {gap!r} must reference an existing schema-rec label")

    def test_authority_gaps_name_existing_leaderboard_brands(self):
        # Y.12.3 — gaps name rival brands from the leaderboard, existing strings.
        r = fs.compute_foundational_score(_analysis_all_zero(), _SCHEMA_RECS, _lb_all_zero())
        gaps = r["gaps"]["authority"]
        self.assertTrue(any("Psychology Today" in g for g in gaps))


class TestWeightsAndPersistence(unittest.TestCase):
    def test_weights_from_config_change_score(self):
        # Y.12.4 — weighting all on structure (100) over accessibility (0).
        analysis = {
            "keyword_profiles": {
                "kw1": {
                    "extractability": {
                        "data_available": True,
                        "client_page": {"question_heading_count": 0,
                                        "intro_text_length": 0, "faq_present": False}},
                    "schema_signals": {
                        "data_available": True,
                        "schema_type_counts": {
                            "FAQPage": 1, "ProfessionalService": 1, "LocalBusiness": 1,
                            "Person": 1, "Article": 1, "Organization": 1}},
                },
            },
            "strategic_flags": {"geo_alerts": []},
        }
        w = fs.resolve_weights({"weights": {"accessibility": 0, "structure": 1, "authority": 0}})
        r = fs.compute_foundational_score(analysis, _SCHEMA_RECS, _lb_all_zero(), w)
        self.assertEqual(r["score"], 100.0)  # all weight on the 100 structure axis

    def test_malformed_weights_fall_back_equal(self):
        self.assertEqual(fs.resolve_weights({"weights": "nope"}), fs.DEFAULT_WEIGHTS)
        self.assertEqual(fs.resolve_weights({"weights": {"accessibility": "x"}}),
                         fs.DEFAULT_WEIGHTS)
        self.assertEqual(fs.resolve_weights({"weights": {"accessibility": 0,
                                                         "structure": 0, "authority": 0}}),
                         fs.DEFAULT_WEIGHTS)

    def test_table_idempotent_and_trendable(self):
        # Y.12.4
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            fs.init_foundational_table(db)
            fs.init_foundational_table(db)  # idempotent
            r1 = fs.compute_foundational_score(_analysis_all_zero(), _SCHEMA_RECS, _lb_all_zero())
            r2 = fs.compute_foundational_score(_analysis_all_max(), _SCHEMA_RECS, _lb_all_max())
            fs.save_foundational_score(db, "2026-07-06T00:00:00+00:00", r1)
            fs.save_foundational_score(db, "2026-07-06T01:00:00+00:00", r2)
            trend = fs.get_foundational_trend(db)
            self.assertEqual(len(trend), 2)
            self.assertEqual(trend[0]["score"], 0.0)   # oldest first
            self.assertEqual(trend[1]["score"], 100.0)
        finally:
            os.remove(db)


class TestReport(unittest.TestCase):
    def test_section_leads_and_lists_gaps(self):
        r = fs.compute_foundational_score(_analysis_all_zero(), _SCHEMA_RECS, _lb_all_zero())
        md = "\n".join(fs.render_foundational_section(r, []))
        self.assertIn("Foundational GEO readiness", md)
        self.assertIn("cross-platform priority", md)
        self.assertIn("Top gaps to fix first", md)


if __name__ == "__main__":
    unittest.main()
