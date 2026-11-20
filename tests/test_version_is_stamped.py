"""The version is written once, and the record of it cannot drift.

Before v1.5.0 the tool had no version at all, so a report named its run but
not the build that produced it — and several figures changed meaning in the
2026-11-04 review. These tests hold three things: the number has one home,
`CHANGELOG.md`'s newest entry names that same number, and the two places a
reader sees it (the GUI title, the market report's header) read it rather
than carrying a literal of their own.
"""
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import _version  # noqa: E402

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as fh:
        return fh.read()


def _without_comments(body):
    """Code only. A version NAMED in a comment explains why a line is the way
    it is; a version used as data is a copy that can go stale, and only the
    second is a defect."""
    return "\n".join(line.split("#", 1)[0] for line in body.splitlines())


class TestTheNumberHasOneHome(unittest.TestCase):

    def test_version_is_a_semver_string(self):
        self.assertIsInstance(_version.__version__, str)
        self.assertRegex(_version.__version__, SEMVER)

    def test_no_other_module_declares_its_own_version(self):
        """A second `__version__` is a second answer to the same question."""
        offenders = []
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs
                       if d not in {"venv", ".git", "__pycache__", "output",
                                    "raw", "node_modules"}]
            for name in files:
                if not name.endswith(".py") or name == "_version.py":
                    continue
                path = os.path.join(root, name)
                if os.path.basename(path).startswith("test_"):
                    continue
                with open(path, encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                if re.search(r"^__version__\s*=", body, re.M):
                    offenders.append(os.path.relpath(path, REPO))
        self.assertEqual(offenders, [], f"a second version lives in {offenders}")


class TestTheChangelogNamesThisVersion(unittest.TestCase):

    def test_changelog_exists(self):
        self.assertTrue(os.path.exists(os.path.join(REPO, "CHANGELOG.md")))

    def test_newest_entry_is_the_current_version(self):
        """Rule 15: a behaviour change updates the document describing it."""
        entries = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", _read("CHANGELOG.md"),
                             re.M)
        self.assertTrue(entries, "CHANGELOG.md has no `## [x.y.z]` entry")
        self.assertEqual(
            entries[0], _version.__version__,
            "CHANGELOG.md's newest entry names "
            f"{entries[0]!r} but _version.py says {_version.__version__!r} — "
            "bump both or neither")


class TestTheReadmeNamesThisVersion(unittest.TestCase):
    """The README states the version in prose, which is a copy. Checked
    rather than trusted: nothing else would notice it going stale."""

    def test_readme_names_the_current_version(self):
        found = re.findall(r"\*\*v(\d+\.\d+\.\d+)\*\*", _read("README.md"))
        self.assertTrue(found, "README.md names no version")
        self.assertEqual(
            found[0], _version.__version__,
            f"README.md says v{found[0]} but _version.py says "
            f"{_version.__version__}")


class TestWhatAReaderSeesReadsIt(unittest.TestCase):
    """Source inspection: a literal here is a copy that can go stale."""

    CARRIERS = ("serp-me.py", "generate_insight_report.py")

    def test_each_carrier_imports_the_version(self):
        for name in self.CARRIERS:
            with self.subTest(file=name):
                self.assertIn("from _version import __version__", _read(name))

    def test_no_carrier_hardcodes_a_version_number(self):
        for name in self.CARRIERS:
            with self.subTest(file=name):
                found = re.findall(r"\bv\d+\.\d+\.\d+\b",
                                   _without_comments(_read(name)))
                self.assertEqual(found, [], f"{name} hardcodes {found}")

    def test_the_gui_title_carries_the_version(self):
        self.assertIn('f"SERP Intelligence Launcher v{__version__}"',
                      _read("serp-me.py"))

    def test_the_report_header_carries_the_version(self):
        self.assertIn("**Tool version:** v{__version__}",
                      _read("generate_insight_report.py"))


if __name__ == "__main__":
    unittest.main()
