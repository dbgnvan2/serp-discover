"""The report may not quote a Moz plan figure, and the empty-feasibility
section's words live in config.

Found by the second live run after the 2026-11-04 review (2026-11-18). The run
fetched no Domain Authority, so `generate_insight_report.py` rendered its
"no feasibility data" branch, and that branch printed:

    - `MOZ_TOKEN` in `.env` (free tier, 50 rows/month)

Two defects in one sentence. The figure is wrong — this account is on the
Starter Medium plan, and `config.yml` records `moz.rows_per_month: 3000` — and
it is hardcoded, which `CLAUDE.md` forbids for exactly this value because the
real allowance is read from the account at runtime via `quota.lookup`. A
report that prints a stale plan figure as an instruction sends the reader to
buy something they already have.

The same run established the second claim this file guards: the section is not
evidence of missing credentials. `run_pipeline.py` runs steps 1.1-1.4 and
feasibility is not one of them, so a pipeline run never fetches DA however
`.env` is set. The section has to say so, or its own instructions are the
wrong fix.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md (live-run finding)
      report_clarity_spec.md (RC.5)
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import feasibility  # noqa: E402
from generate_insight_report import generate_report  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#: A plan figure is an allowance of rows per unit of time. Any wording of one
#: is matched, not just the one the live run produced — the point is that no
#: module may know this number.
PLAN_FIGURE = re.compile(
    r"\d[\d,]*\s*(?:rows?|queries|requests|credits)\s*(?:per|/|\s+an?\s+)\s*"
    r"(?:month|mo\b|day|week)", re.I)
FREE_TIER = re.compile(r"free[ -]tier", re.I)

#: What makes a rate a PLAN figure rather than an estimate of this tool's own
#: usage. `moz_competitor.brand_authority_for` explains its design choice as
#: costing "~4 rows a month" at one run a week, which is a statement about
#: this code, not a claim about a provider's allowance — the defect is a
#: module asserting what the account is entitled to.
PLAN_CONTEXT = re.compile(
    r"moz|dataforseo|serpapi|anthropic|gemini|tier|plan\b|allowance|quota",
    re.I)


def _no_feasibility_data():
    return {
        "overview": [{"Root_Keyword": "keyword_a", "Run_ID": "test_run",
                      "Created_At": "2026-05-05T00:00:00"}],
        "keyword_profiles": {"keyword_a": {
            "serp_intent": {"primary_intent": "informational",
                            "confidence": "high"}}},
        "keyword_feasibility": [],
        "organic_results": [],
        "paa_questions": [],
    }


class TestNoModuleKnowsTheMozAllowance(unittest.TestCase):

    def _sources(self):
        for path in glob.glob(os.path.join(REPO, "*.py")):
            if os.path.basename(path).startswith("test_"):
                continue
            with open(path, encoding="utf-8") as handle:
                yield path, handle.read()

    def test_no_python_module_quotes_a_plan_figure(self):
        """The allowance is read from the account at runtime (`quota.lookup`)
        and recorded in `config.yml` as `moz.rows_per_month`. A copy in source
        goes stale silently — this one was four years and one plan upgrade out
        of date and was being printed to the reader as guidance."""
        for path, text in self._sources():
            for number, line in enumerate(text.splitlines(), start=1):
                hit = PLAN_FIGURE.search(line)
                if hit is None or not PLAN_CONTEXT.search(line):
                    continue
                self.fail(
                    f"{os.path.relpath(path, REPO)}:{number} quotes a plan "
                    f"figure ({hit.group(0)}); read moz.rows_per_month or "
                    f"name no figure")

    def test_no_python_module_calls_the_moz_account_a_free_tier(self):
        """Separate from the figure: the plan is Starter Medium. "Free tier"
        was wrong on its own, and would have survived deleting the number.

        Scoped to lines that name Moz, because that is the account CLAUDE.md
        makes a claim about. `config_manager.py` carries one other free-tier
        claim, about SerpAPI page limits, with no provenance either; it is
        recorded as an adjacent issue rather than swept into this change.
        """
        for path, text in self._sources():
            for number, line in enumerate(text.splitlines(), start=1):
                if "moz" not in line.lower():
                    continue
                self.assertIsNone(
                    FREE_TIER.search(line),
                    f"{os.path.relpath(path, REPO)}:{number} calls the Moz "
                    f"account a free tier; it is Starter Medium")


class TestTheSectionSaysWhatConfigSays(unittest.TestCase):

    def setUp(self):
        feasibility._MESSAGES_CACHE = None
        self.words = feasibility.load_messages().get("no_data_section") or {}

    def test_config_carries_both_parts(self):
        self.assertTrue(self.words.get("heading"))
        self.assertTrue(self.words.get("body"))

    def test_the_render_is_the_configured_words(self):
        """Asserted against the file's own values rather than against a copy
        of them, so rewording the YAML does not break the test and a Python
        literal creeping back does."""
        report = generate_report(_no_feasibility_data())
        for key in ("heading", "body"):
            self.assertIn(self.words[key].strip(), report)

    def test_the_body_names_the_step_that_fills_the_section_in(self):
        """Credentials alone do not: `run_pipeline.py` does not run
        feasibility. A section that lists only credentials sends the reader to
        fix the one thing that was not wrong."""
        self.assertIn("run_feasibility.py", self.words["body"])

    def test_the_body_names_both_providers(self):
        for token in ("DATAFORSEO_LOGIN", "MOZ_TOKEN"):
            self.assertIn(token, self.words["body"])

    def test_the_body_quotes_no_plan_figure(self):
        self.assertIsNone(PLAN_FIGURE.search(self.words["body"]))
        self.assertIsNone(FREE_TIER.search(self.words["body"]))

    def test_a_missing_messages_file_leaves_the_section_empty(self):
        """This loader degrades everywhere else it is read; the report must
        not become the one place where a malformed editorial file aborts a
        run."""
        feasibility._MESSAGES_CACHE = {}
        try:
            report = generate_report(_no_feasibility_data())
        finally:
            feasibility._MESSAGES_CACHE = None
        self.assertNotIn("Feasibility data unavailable", report)
        self.assertIn("5c", report)


if __name__ == "__main__":
    unittest.main()
