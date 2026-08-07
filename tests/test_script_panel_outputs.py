"""Tests that every GUI script lists its outputs in the Context & Usage panel.

Purpose: Each entry in serp-me.py `self.scripts` must document an OUTPUTS
         section in its `desc` (shown in the Context & Usage panel), and its
         label number must align with the menu position.
Spec:    GUI outputs/numbering alignment request (2026-08-07)
Tests:   tests/test_script_panel_outputs.py

AST-based (no tkinter): parse serp-me.py and inspect the self.scripts list.
"""

import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERP_ME_PATH = os.path.join(REPO_ROOT, "serp-me.py")


def _joined_str(node):
    """Return the concatenated string value of a str/JoinedStr constant node."""
    parts = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            parts.append(sub.value)
    return "".join(parts)


def _extract_scripts():
    """Return list of {label, desc} dicts from the self.scripts assignment."""
    with open(SERP_ME_PATH, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=SERP_ME_PATH)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = node.targets
        is_scripts = any(
            isinstance(t, ast.Attribute) and t.attr == "scripts" for t in targets
        )
        if not is_scripts or not isinstance(node.value, ast.List):
            continue
        scripts = []
        for elt in node.value.elts:
            if not isinstance(elt, ast.Dict):
                continue
            entry = {}
            for k, v in zip(elt.keys, elt.values):
                if isinstance(k, ast.Constant) and k.value in ("label", "desc"):
                    entry[k.value] = _joined_str(v)
            if "label" in entry:
                scripts.append(entry)
        return scripts
    raise AssertionError("self.scripts assignment not found in serp-me.py")


SCRIPTS = _extract_scripts()


def test_seven_menu_items_found():
    """The menu has the seven numbered items shown in the GUI."""
    labels = [s["label"] for s in SCRIPTS]
    assert len(labels) == 7, labels


def test_every_item_documents_outputs():
    """Every script's Context & Usage text includes an OUTPUTS section."""
    missing = [s["label"] for s in SCRIPTS if "OUTPUTS:" not in s.get("desc", "")]
    assert not missing, f"Items missing an OUTPUTS section in their panel text: {missing}"


def test_labels_are_numbered_one_through_seven():
    """Labels start with their menu number 1..7 in order (numbering aligns with GUI)."""
    numbers = [s["label"].split(".", 1)[0].strip() for s in SCRIPTS]
    assert numbers == [str(i) for i in range(1, 8)], numbers
