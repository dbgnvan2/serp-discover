"""The client-DA fallback says who measured it and when.

`feasibility.client_da` was 35, from nobody and no date, while DataForSEO
measured 32 on 2026-11-21. A live measurement always wins, so the stale value
was harmless on a run where a provider answered — and silently three points
wrong in every gap on a run where none did.

These tests pin that the fallback travels with its provenance, that a run
distinguishes "the same provider measured a different figure, so this is
stale" from "another provider's scale, not comparable", and that one
precedence serves both producers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import feasibility

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Log:
    """Collects the rendered log lines, so the words can be asserted."""

    def __init__(self):
        self.lines = []

    def __call__(self, msg, *args):
        self.lines.append(msg % args if args else msg)

    @property
    def text(self):
        return "\n".join(self.lines)


def _resolve(measured, provider, config_value, config_source):
    info, warn = _Log(), _Log()
    da, source = feasibility.resolve_client_da(
        "livingsystems.ca", lambda d: measured, provider, config_value,
        None, info, warn, config_source)
    return da, source, info, warn


MEASURED = {"da": 32, "fetched_at": "2026-11-21"}


class TestTheConfiguredFallbackIsResolvedOnce(unittest.TestCase):

    def test_the_pair_comes_back_together(self):
        self.assertEqual(
            feasibility.resolve_client_da_config(
                {"client_da": 32, "client_da_source": "dataforseo 2026-11-21"}),
            (32, "dataforseo 2026-11-21"))

    def test_the_shared_config_wins(self):
        self.assertEqual(
            feasibility.resolve_client_da_config(
                {"client_da": 32, "client_da_source": "dataforseo 2026-11-21"},
                {"da": 40, "da_source": "moz 2026-01-01"}),
            (40, "moz 2026-01-01"))

    def test_an_absent_fallback_is_none_not_zero(self):
        self.assertEqual(feasibility.resolve_client_da_config({}), (None, ""))

    def test_a_non_numeric_fallback_warns_and_is_absent(self):
        with self.assertLogs(level="WARNING"):
            self.assertEqual(
                feasibility.resolve_client_da_config({"client_da": "junk"}),
                (None, ""))

    def test_both_producers_use_the_resolver(self):
        for name in ("serp_audit.py", "run_feasibility.py"):
            with self.subTest(module=name):
                src = open(os.path.join(REPO, name), encoding="utf-8").read()
                self.assertIn("resolve_client_da_config", src)
                self.assertNotIn('.get("client_da", 35)', src)


class TestAStaleFallbackSaysSo(unittest.TestCase):

    def test_the_same_provider_measuring_differently_means_stale(self):
        _, _, info, _ = _resolve(MEASURED, "dataforseo", 35,
                                 "dataforseo 2026-11-01")
        self.assertIn("STALE", info.text)
        self.assertIn("set feasibility.client_da to 32", info.text)

    def test_another_provider_is_a_scale_difference_not_staleness(self):
        _, _, info, _ = _resolve(MEASURED, "dataforseo", 35, "moz 2026-01-01")
        self.assertNotIn("STALE", info.text)
        self.assertIn("not comparable", info.text)

    def test_an_unrecorded_source_says_it_is_unrecorded(self):
        _, _, info, _ = _resolve(MEASURED, "dataforseo", 35, "")
        self.assertIn("source unrecorded", info.text)

    def test_a_matching_figure_says_nothing(self):
        _, _, info, _ = _resolve(MEASURED, "dataforseo", 32,
                                 "dataforseo 2026-11-21")
        self.assertEqual(info.lines, [])


class TestTheFallbackRowNamesItsProvenance(unittest.TestCase):

    def test_the_source_string_carries_who_and_when(self):
        da, source, _, warn = _resolve({}, "dataforseo", 32,
                                       "dataforseo 2026-11-21")
        self.assertEqual(da, 32)
        self.assertIn("dataforseo 2026-11-21", source)
        self.assertIn("config fallback", source)

    def test_the_same_provider_fallback_is_old_not_unscaled(self):
        # Its scale holds — the same provider measured it; only the date is
        # old. Calling that "scale unverified" told the reader the wrong thing.
        _, _, _, warn = _resolve({}, "dataforseo", 32, "dataforseo 2026-11-21")
        self.assertIn("the scale holds", warn.text)
        self.assertNotIn("unverified", warn.text)

    def test_another_provider_fallback_is_unverified(self):
        _, _, _, warn = _resolve({}, "dataforseo", 35, "moz 2026-01-01")
        self.assertIn("unverified", warn.text)

    def test_an_unrecorded_source_still_falls_back(self):
        da, source, _, warn = _resolve({}, "dataforseo", 35, "")
        self.assertEqual(da, 35)
        self.assertIn("unmeasured", source)
        self.assertIn("source unrecorded", warn.text)


class TestTheShippedConfigIsTheMeasuredFigure(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(REPO, "config.yml"), encoding="utf-8") as fh:
            self.cfg = yaml.safe_load(fh) or {}
        self.feas = self.cfg.get("feasibility") or {}

    def test_the_fallback_records_its_provenance(self):
        source = str(self.feas.get("client_da_source", "")).strip()
        self.assertTrue(source, "client_da_source is empty — the fallback "
                                "would be a number from nobody again")
        self.assertRegex(source, r"\d{4}-\d{2}-\d{2}",
                         "client_da_source must name a date")

    def test_the_provenance_names_a_provider_the_tool_can_use(self):
        source = str(self.feas.get("client_da_source", "")).lower()
        self.assertTrue(any(p in source for p in ("dataforseo", "moz")),
                        source)

    def test_the_fallback_is_a_plausible_authority_figure(self):
        da, _ = feasibility.resolve_client_da_config(self.feas)
        self.assertIsNotNone(da)
        self.assertTrue(0 <= da <= 100, da)


if __name__ == "__main__":
    unittest.main()
