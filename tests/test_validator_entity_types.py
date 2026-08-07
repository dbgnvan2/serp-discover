"""Guard: the domain-override validator accepts every real entity type.

Purpose: config_validators.VALID_ENTITY_TYPES must stay in sync with the
         classifier taxonomy (classifiers.ENTITY_TYPES <- classification_rules.json).
         The old hardcoded set omitted "publisher" (Y.8), so a valid
         domain_overrides entry mapping a domain to "publisher" failed validation.
Spec:    taxonomy-drift fix (2026-08-07); same class as the publisher KeyError fix.
Tests:   tests/test_validator_entity_types.py

No tkinter: pure validator + taxonomy import.
"""

from classifiers import ENTITY_TYPES
from config_validators import VALID_ENTITY_TYPES, validate_domain_overrides


def test_validator_covers_every_classifier_entity_type():
    """Every ENTITY_TYPES value must be accepted by the domain-override validator."""
    missing = [t for t in ENTITY_TYPES if t not in VALID_ENTITY_TYPES]
    assert not missing, f"validator rejects real entity types: {missing}"


def test_publisher_is_accepted():
    """Explicit regression guard for the 'publisher' entity type."""
    assert "publisher" in ENTITY_TYPES
    ok, errors, _ = validate_domain_overrides({"medium.com": "publisher"})
    assert ok is True, errors


def test_bogus_type_still_rejected():
    """A genuinely invalid type is still rejected (validator not neutered)."""
    ok, errors, _ = validate_domain_overrides({"example.com": "not_a_real_type"})
    assert ok is False and errors
