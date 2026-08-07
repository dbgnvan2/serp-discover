"""
Tests that the domain-review window's colour map stays in sync with the entity
taxonomy.

Purpose: Every entity type in ENTITY_TYPES (sourced from classification_rules.json)
         must have a DOMAIN_REVIEW_TAG_STYLES entry in serp-me.py, otherwise the
         review window's legend loop KeyErrors and the whole window fails to open.
Spec:    classification_rules.json publisher entity type (Y.8 citation table)
Tests:   tests/test_domain_review_styles.py

Regression guard for the 'publisher' KeyError: 'publisher' was added to
ENTITY_TYPES via classification_rules.json but never added to the hardcoded
DOMAIN_REVIEW_TAG_STYLES map, crashing both the pipeline auto-open and the
manual "Review Domain Override Candidates" step with `Error: 'publisher'`.

Uses AST parsing rather than importing serp-me.py so it runs without tkinter.
"""

import ast
import os

from classifiers import ENTITY_TYPES

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERP_ME_PATH = os.path.join(REPO_ROOT, "serp-me.py")


def _extract_tag_style_keys():
    """Return the keys of DOMAIN_REVIEW_TAG_STYLES without importing tkinter."""
    with open(SERP_ME_PATH, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=SERP_ME_PATH)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not any(t.id == "DOMAIN_REVIEW_TAG_STYLES" for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError("DOMAIN_REVIEW_TAG_STYLES not found in serp-me.py")


def test_every_entity_type_has_a_review_style():
    """Every ENTITY_TYPES value must have a DOMAIN_REVIEW_TAG_STYLES entry."""
    style_keys = _extract_tag_style_keys()
    missing = [etype for etype in ENTITY_TYPES if etype not in style_keys]
    assert not missing, (
        "Entity types present in ENTITY_TYPES but missing from "
        f"DOMAIN_REVIEW_TAG_STYLES in serp-me.py: {missing}. "
        "Add a colour entry so the domain-review legend does not KeyError."
    )


def test_publisher_type_has_a_review_style():
    """Explicit regression guard for the 'publisher' KeyError."""
    style_keys = _extract_tag_style_keys()
    assert "publisher" in ENTITY_TYPES
    assert "publisher" in style_keys


def test_unknown_fallback_style_present():
    """The 'unknown' fallback style must exist (legend + row-tag fallback)."""
    style_keys = _extract_tag_style_keys()
    assert "unknown" in style_keys
