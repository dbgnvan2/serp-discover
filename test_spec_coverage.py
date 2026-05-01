"""
Tests for spec coverage matrix — C.3.2 through C.3.6.

Spec: serp_tool1_cleanup_spec.md C.3
"""
import os
import re
import subprocess
import sys
import unittest

COVERAGE_PATH = os.path.join(os.path.dirname(__file__), "docs", "spec_coverage.md")
REPO_ROOT = os.path.dirname(__file__)


def _load_coverage():
    with open(COVERAGE_PATH, encoding="utf-8") as f:
        return f.read()


def _parse_table_rows(text: str) -> list[dict]:
    """Parse the markdown table into a list of row dicts."""
    rows = []
    in_table = False
    headers = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not cells:
            continue
        if headers is None:
            headers = cells
            in_table = True
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


class TestSpecCoverageC32MinimumRowCount(unittest.TestCase):
    """C.3.2 — Table contains at least 50 rows."""

    def test_c32_minimum_row_count(self):
        rows = _parse_table_rows(_load_coverage())
        self.assertGreaterEqual(
            len(rows), 50,
            f"spec_coverage.md table has {len(rows)} rows; expected ≥ 50"
        )


class TestSpecCoverageC33NoEmptyCells(unittest.TestCase):
    """C.3.3 — Every row has all six columns populated; manual rows have Manual Verification entry."""

    REQUIRED_COLUMNS = {"Spec ID", "Spec File", "Description", "Implementation", "Test", "Status"}

    def test_c33_no_empty_cells(self):
        text = _load_coverage()
        rows = _parse_table_rows(text)
        manual_section = ""
        if "## Manual Verification" in text:
            manual_section = text.split("## Manual Verification")[1]

        for i, row in enumerate(rows):
            for col in self.REQUIRED_COLUMNS:
                self.assertIn(col, row, f"Row {i+1} ({row.get('Spec ID','?')}): missing column '{col}'")
                self.assertTrue(
                    row[col].strip(),
                    f"Row {i+1} ({row.get('Spec ID','?')}): column '{col}' is empty"
                )
            if row.get("Test", "").strip() == "manual":
                spec_id = row.get("Spec ID", "").strip()
                self.assertIn(
                    spec_id, manual_section,
                    f"Row {spec_id} has Test=manual but is not listed in Manual Verification section"
                )


class TestSpecCoverageC34ImplementationPathsExist(unittest.TestCase):
    """C.3.4 — Every Implementation cell naming a file path refers to a file that exists."""

    # Patterns that indicate a file path rather than a description
    _FILE_PATTERN = re.compile(r"(?:^|[\s,])([\w./\-]+\.(?:py|yml|yaml|json|md))")

    def test_c34_implementation_paths_exist(self):
        rows = _parse_table_rows(_load_coverage())
        missing = []
        for row in rows:
            impl = row.get("Implementation", "")
            status = row.get("Status", "")
            if status in ("superseded", "not done"):
                continue
            for match in self._FILE_PATTERN.finditer(impl):
                path = match.group(1).strip(" ,")
                full = os.path.join(REPO_ROOT, path)
                if not os.path.exists(full):
                    missing.append(f"{row.get('Spec ID','?')}: {path}")
        self.assertEqual(
            missing, [],
            "Implementation cells reference non-existent files:\n" + "\n".join(missing)
        )


class TestSpecCoverageC35NamedTestsExist(unittest.TestCase):
    """C.3.5 — Every Test cell naming a test refers to a test that exists."""

    _TEST_PATTERN = re.compile(r"(test_\w+\.py)::(test_\w+)")

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        cls.collected = result.stdout + result.stderr

    def test_c35_named_tests_exist(self):
        rows = _parse_table_rows(_load_coverage())
        missing = []
        for row in rows:
            test_cell = row.get("Test", "")
            status = row.get("Status", "")
            if status in ("superseded", "not done") or test_cell.strip() in ("manual", "—", "n/a — superseded", ""):
                continue
            for match in self._TEST_PATTERN.finditer(test_cell):
                test_name = match.group(2)
                if test_name not in self.collected:
                    missing.append(f"{row.get('Spec ID','?')}: {test_name}")
        self.assertEqual(
            missing, [],
            "Test cells reference non-existent tests:\n" + "\n".join(missing)
        )


class TestSpecCoverageC36ManualSectionComplete(unittest.TestCase):
    """C.3.6 — Manual Verification section lists every criterion with Test=manual."""

    def test_c36_manual_section_complete(self):
        text = _load_coverage()
        self.assertIn(
            "## Manual Verification", text,
            "spec_coverage.md must contain a '## Manual Verification' section"
        )
        rows = _parse_table_rows(text)
        manual_section = text.split("## Manual Verification")[1]
        missing = []
        for row in rows:
            if row.get("Test", "").strip() == "manual":
                spec_id = row.get("Spec ID", "").strip()
                if spec_id not in manual_section:
                    missing.append(spec_id)
        self.assertEqual(
            missing, [],
            "These manual criteria are not listed in Manual Verification section:\n" + "\n".join(missing)
        )


if __name__ == "__main__":
    unittest.main()
