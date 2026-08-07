"""Tests that run_pipeline.py sub-step numbering aligns with the GUI.

Purpose: The Full Pipeline is GUI item 1; its four internal sub-steps must be
         logged as Step 1.1-1.4 so they don't collide with the GUI's own item
         numbers 1-4 (which previously read like "Step 3" == GUI item 3).
Spec:    GUI outputs/numbering alignment request (2026-08-07)
Tests:   tests/test_pipeline_step_numbering.py
"""

import ast
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_PATH = os.path.join(REPO_ROOT, "run_pipeline.py")


def _run_command_descriptions():
    """Return the description string passed to each run_command(...) call."""
    with open(PIPELINE_PATH, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=PIPELINE_PATH)
    descs = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_command"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
        ):
            descs.append(node.args[1].value)
    return descs


DESCS = _run_command_descriptions()


def test_four_substeps():
    assert len(DESCS) == 4, DESCS


def test_substeps_use_dotted_item1_numbering():
    """Sub-steps are labelled Step 1.1 .. 1.4 (ast.walk order is not source order)."""
    prefixes = {d.split(":", 1)[0].strip() for d in DESCS}
    assert prefixes == {"Step 1.1", "Step 1.2", "Step 1.3", "Step 1.4"}, DESCS


def test_no_bare_stepN_that_collides_with_gui_items():
    """No sub-step is labelled a bare 'Step N:' (N in 1..7) that collides with a GUI item."""
    for d in DESCS:
        assert not re.match(r"^Step [1-7]:", d), (
            f"Sub-step '{d}' uses bare GUI-item numbering; use Step 1.x instead."
        )
