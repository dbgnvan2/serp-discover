"""The one place this tool's version number is written.

Before v1.5.0 the tool had no version at all: no `__version__`, no
`CHANGELOG.md`, no git tag. A report handed to a client therefore said which
run produced it and when, but not which build of the tool — so a figure that
changed meaning (the 2026-11-19 review changed several, `total_results` and
the intent verdict among them) could not be told apart from the same figure
measured a month earlier under the old rules. A reader comparing two reports
had no way to know they were reading two different tools.

The number is written HERE and nowhere else. The GUI title and the market
report's header both read it, so the three can never disagree, and a standing
test (`tests/test_version_is_stamped.py`) fails the build when
`CHANGELOG.md`'s newest entry names a different version from this one — the
version and the record of what changed in it move together or not at all.

Bumping it: edit this file, add the matching `## [x.y.z]` section to
`CHANGELOG.md`, and tag the commit `vx.y.z` in both repos. The minor digit
carries a review of this size; the patch digit carries a fix.
"""

__version__ = "1.5.0"
