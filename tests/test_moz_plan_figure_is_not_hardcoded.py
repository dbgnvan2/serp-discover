"""The report may not quote a Moz plan figure, and the empty-feasibility
section's words live in config.

Found by the second live run after the 2026-11-04 review (2026-11-18). The run
fetched no Domain Authority, so `generate_insight_report.py` rendered its
"no feasibility data" branch, and that branch printed:

    - `MOZ_TOKEN` in `.env` (free tier, 50 rows/month)

Two defects in one sentence. The figure is wrong — this account is on the
Starter Medium plan, and `config.yml` records the allowance read from the
account at runtime (`moz.rows_per_month`, 750 on 2026-11-21) — and
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
import ast
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

#: Directories that are not this tool's source.
SKIP_DIRS = {"venv", ".git", "node_modules", "__pycache__", "output",
             ".claude", "docs"}


def _modules():
    """Every Python module in the repo, not just the top level.

    The first version of this guard globbed `REPO/*.py`, which proves nothing
    about `scripts/` or any package directory added later while the failure
    message says "no module may know this number" (P31: an absence computed
    over a narrowed population is not the absence claimed). Found by this
    change's own cold review.
    """
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and not d.startswith(".")]
        for name in sorted(files):
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                yield path, handle.read()


def _string_constants(text):
    """Every string constant a reader could be shown, joined as they see it.

    A physical-line scan is the wrong unit: the literal this guard exists to
    forbid was an implicitly-concatenated multi-line string, and it tripped
    the first version of the guard only because one of its fragments happened
    to carry both the figure and the word "tier". Re-wrapped as
    `"...MOZ_TOKEN in .env\\n" "(50 rows/month)\\n"` it would have passed with
    the defect intact. The AST joins adjacent fragments for us, so the text
    under test is the sentence rather than the source layout.

    Docstrings are excluded, and so are comments by construction. Neither is
    printed to a reader, and both are where a module legitimately explains
    its own cost: `moz_competitor.brand_authority_for` records that leaving
    one call uncached costs "~4 rows a month" at one run a week, which is a
    statement about this code, not a claim about what the account is entitled
    to. The defect this guard forbids is a figure a reader is shown.
    """
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            yield node.value


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

    def test_no_python_module_quotes_a_plan_figure(self):
        """The allowance is read from the account at runtime (`quota.lookup`)
        and recorded in `config.yml` as `moz.rows_per_month`. A copy in source
        goes stale silently — this one was a plan upgrade out of date and was
        being printed to the reader as guidance."""
        for path, text in _modules():
            for value in _string_constants(text):
                hit = PLAN_FIGURE.search(value)
                if hit is None or not PLAN_CONTEXT.search(value):
                    continue
                self.fail(
                    f"{os.path.relpath(path, REPO)} quotes a plan figure "
                    f"({hit.group(0)}); read moz.rows_per_month or name no "
                    f"figure")

    def test_no_python_module_calls_the_moz_account_a_free_tier(self):
        """Separate from the figure: the plan is Starter Medium. "Free tier"
        was wrong on its own, and would have survived deleting the number.

        Scoped to strings that name Moz, because that is the account
        CLAUDE.md makes a claim about. `config_manager.py` carries one other
        free-tier claim, about SerpAPI page limits, with no provenance
        either; it is recorded as an adjacent issue rather than swept into
        this change.
        """
        for path, text in _modules():
            for value in _string_constants(text):
                if "moz" not in value.lower():
                    continue
                self.assertIsNone(
                    FREE_TIER.search(value),
                    f"{os.path.relpath(path, REPO)} calls the Moz account a "
                    f"free tier; it is Starter Medium")

    def test_the_scan_sees_more_than_the_repo_root(self):
        """The guard's own population, asserted rather than assumed: a
        narrowed scan would pass every absence test above while proving
        nothing about the modules it skipped."""
        paths = {os.path.relpath(p, REPO) for p, _ in _modules()}
        self.assertIn("generate_insight_report.py", paths)
        self.assertTrue(
            any(os.sep in p for p in paths),
            "the scan found no module below the repo root; it is globbing "
            "the top level again")

    def test_the_scan_reads_joined_string_fragments(self):
        """The unit under test is the sentence, not the source line."""
        source = 'x = ("MOZ_TOKEN in .env "\n     "(50 rows/month)")\n'
        joined = list(_string_constants(source))
        self.assertTrue(any(PLAN_FIGURE.search(v) and PLAN_CONTEXT.search(v)
                            for v in joined), joined)


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

    def _rendered_with(self, messages):
        feasibility._MESSAGES_CACHE = messages
        try:
            return generate_report(_no_feasibility_data())
        finally:
            feasibility._MESSAGES_CACHE = None

    def test_an_unreadable_messages_file_still_says_what_is_missing(self):
        """Section 5c is outside `_safe_section`, so it may not raise — and it
        may not fall silent either. The first version of this fix rendered
        nothing when the file could not be read, and an empty section reads
        as "nothing to report" rather than "Domain Authority was never
        fetched". The built-in wording says it was used (P2)."""
        report = self._rendered_with({})
        self.assertIn("Feasibility data unavailable", report)
        self.assertIn("run_feasibility.py", report)
        self.assertIn("could not be read", report)

    def test_a_wrongly_shaped_block_does_not_abort_the_report(self):
        """The likeliest typo in a hand-edited block is writing it as a plain
        value. `.get(...) or {}` guards `None`, not a wrong type, and the
        AttributeError took down the whole market report rather than the
        section."""
        for shape in ("a string, not a block", ["a", "list"], 7):
            with self.subTest(shape=type(shape).__name__):
                report = self._rendered_with({"no_data_section": shape})
                self.assertIn("Feasibility data unavailable", report)
                self.assertIn("5c", report)

    def test_the_fallback_wording_quotes_no_plan_figure(self):
        """It is a Python literal by design, so it is the one string the
        module-wide guard above must still clear."""
        from generate_insight_report import FALLBACK_NO_FEASIBILITY
        self.assertIsNone(PLAN_FIGURE.search(FALLBACK_NO_FEASIBILITY))
        self.assertIsNone(FREE_TIER.search(FALLBACK_NO_FEASIBILITY))

    def test_every_paragraph_in_the_block_is_rendered(self):
        """The first version read a hardcoded `("heading", "body")`, so a
        third paragraph added to the YAML was silently unread (P36). The
        block's own order is the render order."""
        report = self._rendered_with({"no_data_section": {
            "heading": "FIRST-MARKER", "body": "SECOND-MARKER",
            "postscript": "THIRD-MARKER"}})
        self.assertLess(report.index("FIRST-MARKER"),
                        report.index("SECOND-MARKER"))
        self.assertIn("THIRD-MARKER", report)


if __name__ == "__main__":
    unittest.main()
