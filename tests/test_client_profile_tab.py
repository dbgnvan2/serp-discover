"""Tests for the Client Profile & Queries tab (Y.13) — data layer.

Spec: yoast_geo_upgrade_spec_v1.md#Y.13. These are BUSINESS-LOGIC tests: they
exercise the load -> edit -> save round trip, validation, and the no-cost
question preview WITHOUT tkinter (per CLAUDE.md, business logic must not require
the GUI framework). Only true widget-interaction tests may skip when tkinter is
absent; those live in test_config_manager.py.

- Y.13.1 save round-trip: editing client A leaves client B byte-for-byte intact.
- Y.13.2 init-order source-inspection test lives in test_config_manager.py
  (TestTabInitializationOrder) — the ClientProfileTab is added to its checks.
- Y.13.3 preview returns Y.1's generated questions, no network/API call.
- Y.13.4 malformed input (empty persona label, non-mapping) is rejected and
  nothing is written.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

import config_manager as cm


def _two_client_data():
    return {
        "client_a": {
            "brand_name": "Alpha Co",
            "primary_city": "Alpha",
            "personas": [
                {"label": "seeker", "seed_questions": ["a question one"]},
            ],
        },
        "client_b": {
            "brand_name": "Beta Co",
            "primary_city": "Beta",
            "secondary_cities": ["Gamma"],
            "personas": [
                {"label": "referrer", "seed_questions": ["b question two"]},
            ],
        },
    }


class TestSaveRoundTrip(unittest.TestCase):
    """Y.13.1 — the single save path preserves other clients' blocks."""

    def test_upsert_leaves_other_client_intact(self):
        data = _two_client_data()
        original_b = yaml.safe_dump(data["client_b"], sort_keys=False)

        edited_a = dict(data["client_a"])
        edited_a["brand_name"] = "Alpha Renamed"
        updated = cm.upsert_client_block(data, "client_a", edited_a)

        self.assertEqual(updated["client_a"]["brand_name"], "Alpha Renamed")
        # client_b block is byte-for-byte identical after the edit+save.
        self.assertEqual(
            yaml.safe_dump(updated["client_b"], sort_keys=False), original_b)
        # Input mapping was not mutated.
        self.assertEqual(data["client_a"]["brand_name"], "Alpha Co")

    def test_full_file_round_trip_on_disk(self):
        data = _two_client_data()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "client_profiles.yml")
            with open(path, "w") as f:
                yaml.safe_dump(data, f, sort_keys=False)

            loaded = cm.load_client_profiles_file(path)
            self.assertEqual(set(loaded), {"client_a", "client_b"})

            edited = dict(loaded["client_a"])
            edited["domain"] = "alpha.example"
            updated = cm.upsert_client_block(loaded, "client_a", edited)
            ok, errors, _ = cm.validate_client_profiles(updated)
            self.assertTrue(ok, errors)

            with open(path, "w") as f:
                yaml.safe_dump(updated, f, sort_keys=False)
            reloaded = cm.load_client_profiles_file(path)
            self.assertEqual(reloaded["client_a"]["domain"], "alpha.example")
            self.assertEqual(reloaded["client_b"], data["client_b"])


class TestValidation(unittest.TestCase):
    """Y.13.4 — malformed input is rejected; nothing written."""

    def test_valid_block_passes(self):
        ok, errors, _ = cm.validate_client_block(
            _two_client_data()["client_b"])
        self.assertTrue(ok, errors)

    def test_empty_persona_label_rejected(self):
        block = {"personas": [{"label": "", "seed_questions": ["x"]}]}
        ok, errors, _ = cm.validate_client_block(block)
        self.assertFalse(ok)
        self.assertTrue(any("empty label" in e for e in errors))

    def test_duplicate_persona_label_rejected(self):
        block = {"personas": [{"label": "dup"}, {"label": "dup"}]}
        ok, errors, _ = cm.validate_client_block(block)
        self.assertFalse(ok)
        self.assertTrue(any("Duplicate persona label" in e for e in errors))

    def test_non_mapping_block_rejected(self):
        ok, errors, _ = cm.validate_client_block("not a mapping")
        self.assertFalse(ok)

    def test_intents_must_be_mapping(self):
        block = {"personas": [{"label": "p", "intents": ["not", "a", "map"]}]}
        ok, errors, _ = cm.validate_client_block(block)
        self.assertFalse(ok)

    def test_save_is_blocked_when_invalid(self):
        # A malformed edited mapping fails validate_client_profiles, so the
        # tab's save path (which validates first) would refuse to write.
        bad = {"client_a": {"personas": [{"label": ""}]}}
        ok, errors, _ = cm.validate_client_profiles(bad)
        self.assertFalse(ok)


class TestPreviewNoNetwork(unittest.TestCase):
    """Y.13.3 — preview returns Y.1 questions with no API/network call."""

    def test_preview_returns_generated_questions(self):
        data = _two_client_data()
        rows = cm.preview_client_questions(data, "client_b")
        self.assertTrue(rows)
        self.assertTrue(all(set(r) == {"question", "persona", "city", "intent"}
                            for r in rows))
        self.assertIn("b question two", [r["question"] for r in rows])

    def test_preview_unknown_slug_returns_empty(self):
        self.assertEqual(
            cm.preview_client_questions(_two_client_data(), "nope"), [])

    def test_preview_makes_no_network_call(self):
        # Guard: profile_questions.generate is pure. If anything tried a paid
        # call it would go through requests; assert requests is never touched.
        with patch("requests.post") as mpost, patch("requests.get") as mget:
            cm.preview_client_questions(_two_client_data(), "client_a")
        mpost.assert_not_called()
        mget.assert_not_called()

    def test_preview_matches_profile_questions_generate(self):
        import profile_questions
        data = _two_client_data()
        self.assertEqual(
            cm.preview_client_questions(data, "client_a"),
            profile_questions.generate(data["client_a"]))


class TestShippedProfileLoads(unittest.TestCase):
    """The real client_profiles.yml loads and previews cleanly."""

    def test_shipped_file_previews(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data = cm.load_client_profiles_file(
            os.path.join(repo_root, "client_profiles.yml"))
        ok, errors, _ = cm.validate_client_profiles(data)
        self.assertTrue(ok, errors)
        rows = cm.preview_client_questions(data, "living_systems")
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
