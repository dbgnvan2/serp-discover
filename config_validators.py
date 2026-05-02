"""Centralized validation for all editorial configuration files.

This module provides validators for:
- intent_mapping.yml
- strategic_patterns.yml
- brief_pattern_routing.yml
- intent_classifier_triggers.yml
- config.yml
- domain_overrides.yml
- classification_rules.json
- url_pattern_rules.yml

Each validator returns: (is_valid: bool, errors: list[str], warnings: list[str])

Purpose: Prevent bad reports and crashes by validating config before save.
Spec: config_manager_spec.md
Tests: tests/test_config_validators.py
"""

import re
from typing import Any


# ============================================================================
# CONSTANTS
# ============================================================================

VALID_INTENTS = {
    "informational",
    "commercial_investigation",
    "transactional",
    "navigational",
    "local",
    "uncategorised",
}

VALID_CONTENT_TYPES = {
    "pdf",
    "directory",
    "news",
    "service",
    "guide",
    "other",
    "unknown",
    "any",
}

VALID_ENTITY_TYPES = {
    "counselling",
    "legal",
    "directory",
    "nonprofit",
    "government",
    "media",
    "professional_association",
    "education",
}

VALID_LOCAL_PACK = {"yes", "no", "any"}
VALID_DOMAIN_ROLE = {"client", "known_competitor", "other", "any"}


# ============================================================================
# VALIDATOR FUNCTIONS (File-Specific)
# ============================================================================


def validate_intent_mapping(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate intent_mapping.yml structure.

    Purpose: Ensure intent mapping rules are well-formed
    Spec: config_manager_spec.md#intent-mapping-validation
    Tests: tests/test_config_validators.py::test_validate_intent_mapping_*
    """
    errors = []
    warnings = []

    # Top-level structure
    if not isinstance(data, dict):
        errors.append("intent_mapping must be a dict")
        return (False, errors, warnings)

    if "version" not in data:
        errors.append("intent_mapping missing 'version' key")
    elif data["version"] != 1:
        errors.append(f"intent_mapping version must be 1, got {data['version']}")

    if "rules" not in data:
        errors.append("intent_mapping missing 'rules' key")
        return (False, errors, warnings)

    rules = data["rules"]
    if not isinstance(rules, list):
        errors.append("intent_mapping['rules'] must be a list")
        return (False, errors, warnings)

    if not rules:
        errors.append("intent_mapping['rules'] must be non-empty")
        return (False, errors, warnings)

    # Validate each rule
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{i}] must be a dict, got {type(rule).__name__}")
            continue

        # Check required keys
        if "match" not in rule:
            errors.append(f"rules[{i}] missing 'match' key")
        if "intent" not in rule:
            errors.append(f"rules[{i}] missing 'intent' key")
            continue

        # Validate intent
        intent = rule["intent"]
        if intent not in VALID_INTENTS:
            errors.append(
                f"rules[{i}]['intent'] = {intent!r}; must be one of {VALID_INTENTS}"
            )

        # Validate match keys
        if "match" in rule:
            match = rule["match"]
            if not isinstance(match, dict):
                errors.append(f"rules[{i}]['match'] must be a dict")
                continue

            required_match_keys = {
                "content_type",
                "entity_type",
                "local_pack",
                "domain_role",
            }
            missing_keys = required_match_keys - set(match.keys())
            if missing_keys:
                errors.append(f"rules[{i}]['match'] missing keys: {missing_keys}")

            # Validate match values
            if "content_type" in match:
                ct = match["content_type"]
                if ct not in VALID_CONTENT_TYPES:
                    errors.append(
                        f"rules[{i}]['match']['content_type'] = {ct!r}; "
                        f"must be one of {VALID_CONTENT_TYPES}"
                    )

            if "entity_type" in match:
                et = match["entity_type"]
                if et != "any" and et not in VALID_ENTITY_TYPES:
                    errors.append(
                        f"rules[{i}]['match']['entity_type'] = {et!r}; "
                        f"must be one of {VALID_ENTITY_TYPES | {'any'}}"
                    )

            if "local_pack" in match:
                lp = match["local_pack"]
                if lp not in VALID_LOCAL_PACK:
                    errors.append(
                        f"rules[{i}]['match']['local_pack'] = {lp!r}; "
                        f"must be one of {VALID_LOCAL_PACK}"
                    )

            if "domain_role" in match:
                dr = match["domain_role"]
                if dr not in VALID_DOMAIN_ROLE:
                    errors.append(
                        f"rules[{i}]['match']['domain_role'] = {dr!r}; "
                        f"must be one of {VALID_DOMAIN_ROLE}"
                    )

    return (len(errors) == 0, errors, warnings)


def validate_strategic_patterns(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate strategic_patterns.yml structure.

    Purpose: Ensure Bowen patterns are well-formed
    Spec: config_manager_spec.md#strategic-patterns-validation
    Tests: tests/test_config_validators.py::test_validate_strategic_patterns_*
    """
    errors = []
    warnings = []

    if not isinstance(data, list):
        errors.append("strategic_patterns must be a list of dicts")
        return (False, errors, warnings)

    if not data:
        errors.append("strategic_patterns must be non-empty")
        return (False, errors, warnings)

    pattern_names = set()

    for i, pattern in enumerate(data):
        if not isinstance(pattern, dict):
            errors.append(f"patterns[{i}] must be a dict, got {type(pattern).__name__}")
            continue

        # Required fields
        required_fields = {
            "Pattern_Name",
            "Triggers",
            "Status_Quo_Message",
            "Bowen_Bridge_Reframe",
            "Content_Angle",
        }
        missing = required_fields - set(pattern.keys())
        if missing:
            errors.append(f"patterns[{i}] missing fields: {missing}")

        # Validate Pattern_Name
        if "Pattern_Name" in pattern:
            pn = pattern["Pattern_Name"]
            if not isinstance(pn, str) or not pn.strip():
                errors.append(f"patterns[{i}]['Pattern_Name'] must be non-empty string")
            else:
                if pn in pattern_names:
                    errors.append(f"Pattern_Name {pn!r} is not unique (patterns[{i}])")
                pattern_names.add(pn)

        # Validate Triggers
        if "Triggers" in pattern:
            triggers = pattern["Triggers"]
            if not isinstance(triggers, list):
                errors.append(f"patterns[{i}]['Triggers'] must be a list")
            elif not triggers:
                errors.append(f"patterns[{i}]['Triggers'] must be non-empty")
            else:
                for j, trigger in enumerate(triggers):
                    if not isinstance(trigger, str):
                        errors.append(
                            f"patterns[{i}]['Triggers'][{j}] must be a string, "
                            f"got {type(trigger).__name__}"
                        )
                    elif len(trigger.strip()) < 4:
                        errors.append(
                            f"patterns[{i}]['Triggers'][{j}] = {trigger!r}; "
                            f"min 4 chars"
                        )

        # Validate text fields (non-empty)
        for field in ["Status_Quo_Message", "Bowen_Bridge_Reframe", "Content_Angle"]:
            if field in pattern:
                val = pattern[field]
                if not isinstance(val, str) or not val.strip():
                    errors.append(
                        f"patterns[{i}]['{field}'] must be non-empty string"
                    )

        # Optional field
        if "Relevant_Intent_Class" in pattern:
            ric = pattern["Relevant_Intent_Class"]
            if ric not in {"External Locus", "Systemic"}:
                errors.append(
                    f"patterns[{i}]['Relevant_Intent_Class'] = {ric!r}; "
                    f"must be 'External Locus' or 'Systemic'"
                )

    return (len(errors) == 0, errors, warnings)


def validate_brief_pattern_routing(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate brief_pattern_routing.yml structure.

    Purpose: Ensure PAA routing rules are well-formed
    Spec: config_manager_spec.md#brief-pattern-routing-validation
    Tests: tests/test_config_validators.py::test_validate_brief_pattern_routing_*
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append("brief_pattern_routing must be a dict")
        return (False, errors, warnings)

    if "version" not in data:
        errors.append("brief_pattern_routing missing 'version' key")
    elif data["version"] != 1:
        errors.append(f"version must be 1, got {data['version']}")

    if "patterns" not in data:
        errors.append("brief_pattern_routing missing 'patterns' key")
        return (False, errors, warnings)

    patterns = data["patterns"]
    if not isinstance(patterns, list):
        errors.append("patterns must be a list")
        return (False, errors, warnings)

    # Validate each pattern routing
    for i, pattern in enumerate(patterns):
        if not isinstance(pattern, dict):
            errors.append(f"patterns[{i}] must be a dict")
            continue

        required = {"pattern_name", "paa_themes", "paa_categories", "keyword_hints"}
        missing = required - set(pattern.keys())
        if missing:
            errors.append(f"patterns[{i}] missing keys: {missing}")

        # Validate pattern_name exists (cross-file check happens later)
        if "pattern_name" in pattern:
            pn = pattern["pattern_name"]
            if not isinstance(pn, str) or not pn.strip():
                errors.append(f"patterns[{i}]['pattern_name'] must be non-empty string")

        # Validate list fields
        for field in ["paa_themes", "paa_categories", "keyword_hints"]:
            if field in pattern:
                val = pattern[field]
                if not isinstance(val, list):
                    errors.append(
                        f"patterns[{i}]['{field}'] must be a list, "
                        f"got {type(val).__name__}"
                    )

    # Check intent_slot_descriptions if present
    if "intent_slot_descriptions" in data:
        isd = data["intent_slot_descriptions"]
        if not isinstance(isd, dict):
            errors.append("intent_slot_descriptions must be a dict")
        # Intent types check done in cross-file validation

    return (len(errors) == 0, errors, warnings)


def validate_intent_classifier_triggers(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate intent_classifier_triggers.yml structure.

    Purpose: Ensure trigger vocabularies are well-formed
    Spec: config_manager_spec.md#intent-classifier-triggers-validation
    Tests: tests/test_config_validators.py::test_validate_intent_classifier_triggers_*
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append("intent_classifier_triggers must be a dict")
        return (False, errors, warnings)

    if "version" not in data:
        errors.append("Missing 'version' key")
    elif data["version"] != 1:
        errors.append(f"version must be 1, got {data['version']}")

    # Check medical_triggers
    if "medical_triggers" not in data:
        errors.append("Missing 'medical_triggers' key")
    else:
        mt = data["medical_triggers"]
        if not isinstance(mt, dict):
            errors.append("medical_triggers must be a dict")
        else:
            for key in ["multi_word", "single_word"]:
                if key not in mt:
                    errors.append(f"medical_triggers missing '{key}' key")
                elif not isinstance(mt[key], list):
                    errors.append(
                        f"medical_triggers['{key}'] must be list, "
                        f"got {type(mt[key]).__name__}"
                    )
                else:
                    for j, trigger in enumerate(mt[key]):
                        if not isinstance(trigger, str):
                            errors.append(
                                f"medical_triggers['{key}'][{j}] must be string"
                            )
                        elif len(trigger.strip()) < 3:
                            errors.append(
                                f"medical_triggers['{key}'][{j}] = {trigger!r}; "
                                f"min 3 chars"
                            )

    # Check systemic_triggers (same structure)
    if "systemic_triggers" not in data:
        errors.append("Missing 'systemic_triggers' key")
    else:
        st = data["systemic_triggers"]
        if not isinstance(st, dict):
            errors.append("systemic_triggers must be a dict")
        else:
            for key in ["multi_word", "single_word"]:
                if key not in st:
                    errors.append(f"systemic_triggers missing '{key}' key")
                elif not isinstance(st[key], list):
                    errors.append(
                        f"systemic_triggers['{key}'] must be list, "
                        f"got {type(st[key]).__name__}"
                    )
                else:
                    for j, trigger in enumerate(st[key]):
                        if not isinstance(trigger, str):
                            errors.append(
                                f"systemic_triggers['{key}'][{j}] must be string"
                            )
                        elif len(trigger.strip()) < 3:
                            errors.append(
                                f"systemic_triggers['{key}'][{j}] = {trigger!r}; "
                                f"min 3 chars"
                            )

    return (len(errors) == 0, errors, warnings)


def validate_config_yml(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate config.yml structure.

    Purpose: Ensure operational settings are well-formed
    Spec: config_manager_spec.md#config-settings-validation
    Tests: tests/test_config_validators.py::test_validate_config_yml_*
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append("config.yml must be a dict")
        return (False, errors, warnings)

    # Optional sections with basic type checks
    if "serpapi" in data and not isinstance(data["serpapi"], dict):
        errors.append("serpapi must be a dict")

    if "files" in data and not isinstance(data["files"], dict):
        errors.append("files must be a dict")

    if "enrichment" in data and not isinstance(data["enrichment"], dict):
        errors.append("enrichment must be a dict")

    if "app" in data and not isinstance(data["app"], dict):
        errors.append("app must be a dict")

    if "client" in data and not isinstance(data["client"], dict):
        errors.append("client must be a dict")

    if "analysis_report" in data and not isinstance(data["analysis_report"], dict):
        errors.append("analysis_report must be a dict")

    # Threshold validation (if serp_intent.thresholds present)
    if "serp_intent" in data and isinstance(data["serp_intent"], dict):
        if "thresholds" in data["serp_intent"]:
            thresholds = data["serp_intent"]["thresholds"]
            if isinstance(thresholds, dict):
                for key in ["confidence_high", "confidence_medium"]:
                    if key in thresholds:
                        val = thresholds[key]
                        if not isinstance(val, (int, float)) or not (0 <= val <= 1):
                            errors.append(
                                f"serp_intent.thresholds['{key}'] must be 0-1, "
                                f"got {val}"
                            )

    return (len(errors) == 0, errors, warnings)


def validate_domain_overrides(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate domain_overrides.yml structure (flat key-value).

    Purpose: Ensure domain overrides are well-formed
    Spec: config_manager_spec.md#domain-overrides-validation
    Tests: tests/test_config_validators.py::test_validate_domain_overrides_*
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append("domain_overrides must be a dict (domain → entity_type)")
        return (False, errors, warnings)

    for domain, entity_type in data.items():
        if not isinstance(domain, str) or not domain.strip():
            errors.append(f"Domain key must be non-empty string, got {domain!r}")

        if not isinstance(entity_type, str):
            errors.append(
                f"domain_overrides[{domain!r}] value must be string, "
                f"got {type(entity_type).__name__}"
            )
        elif entity_type not in VALID_ENTITY_TYPES:
            errors.append(
                f"domain_overrides[{domain!r}] = {entity_type!r}; "
                f"must be one of {VALID_ENTITY_TYPES}"
            )

    return (len(errors) == 0, errors, warnings)


def validate_classification_rules(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate classification_rules.json structure.

    Purpose: Ensure entity/content classification rules are well-formed
    Spec: config_manager_spec.md#classification-rules-validation
    Tests: tests/test_config_validators.py::test_validate_classification_rules_*
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append("classification_rules must be a dict")
        return (False, errors, warnings)

    # Check entity_types list
    if "entity_types" not in data:
        errors.append("Missing 'entity_types' key")
    else:
        et = data["entity_types"]
        if not isinstance(et, list):
            errors.append("entity_types must be a list")
        elif not et:
            errors.append("entity_types must be non-empty")

    # Check entity_type_descriptions (if present)
    if "entity_type_descriptions" in data:
        etd = data["entity_type_descriptions"]
        if not isinstance(etd, dict):
            errors.append("entity_type_descriptions must be a dict")
        # Cross-file: check keys match entity_types (done in cross-file validation)

    return (len(errors) == 0, errors, warnings)


def validate_url_pattern_rules(data: Any) -> tuple[bool, list[str], list[str]]:
    """
    Validate url_pattern_rules.yml structure.

    Purpose: Ensure URL pattern rules are well-formed
    Spec: config_manager_spec.md#url-pattern-rules-validation
    Tests: tests/test_config_validators.py::test_validate_url_pattern_rules_*
    """
    errors = []
    warnings = []

    # Handle both file structure (dict with version + url_pattern_rules) and list-only
    if isinstance(data, dict):
        if "url_pattern_rules" not in data:
            errors.append("url_pattern_rules file must contain 'url_pattern_rules' key")
            return (False, errors, warnings)
        rules = data["url_pattern_rules"]
    else:
        rules = data

    if not isinstance(rules, list):
        errors.append("url_pattern_rules must be a list of dicts")
        return (False, errors, warnings)

    if not rules:
        errors.append("url_pattern_rules must be non-empty")
        return (False, errors, warnings)

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{i}] must be a dict")
            continue

        required = {"pattern", "content_type", "entity_types"}
        missing = required - set(rule.keys())
        if missing:
            errors.append(f"rules[{i}] missing keys: {missing}")

        # Validate pattern (regex)
        if "pattern" in rule:
            pattern = rule["pattern"]
            if not isinstance(pattern, str):
                errors.append(f"rules[{i}]['pattern'] must be string")
            else:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    errors.append(
                        f"rules[{i}]['pattern'] = {pattern!r}; invalid regex: {e}"
                    )

        # Validate content_type
        if "content_type" in rule:
            ct = rule["content_type"]
            valid_content = {
                "pdf",
                "directory",
                "news",
                "service",
                "guide",
                "other",
            }
            if ct not in valid_content:
                errors.append(
                    f"rules[{i}]['content_type'] = {ct!r}; "
                    f"must be one of {valid_content}"
                )

        # Validate entity_types
        if "entity_types" in rule:
            ets = rule["entity_types"]
            if not isinstance(ets, list):
                errors.append(f"rules[{i}]['entity_types'] must be list")
            else:
                for et in ets:
                    if et != "any" and et not in VALID_ENTITY_TYPES:
                        errors.append(
                            f"rules[{i}]['entity_types'] contains {et!r}; "
                            f"must be one of {VALID_ENTITY_TYPES | {'any'}}"
                        )

    return (len(errors) == 0, errors, warnings)


# ============================================================================
# CROSS-FILE VALIDATION
# ============================================================================


def validate_cross_file_constraints(
    intent_mapping: dict | None = None,
    strategic_patterns: list | None = None,
    brief_pattern_routing: dict | None = None,
    domain_overrides: dict | None = None,
    classification_rules: dict | None = None,
) -> tuple[bool, list[str], list[str]]:
    """
    Validate constraints across multiple config files.

    Purpose: Catch broken references between files before save
    Spec: config_manager_spec.md#cross-file-validation
    Tests: tests/test_config_validators.py::test_cross_file_*
    """
    errors = []
    warnings = []

    # Build valid sets from classification_rules
    valid_entity_types = set()
    if classification_rules and isinstance(classification_rules, dict):
        if "entity_types" in classification_rules:
            et = classification_rules["entity_types"]
            if isinstance(et, list):
                valid_entity_types = set(et)

    # Check intent_mapping entity_types
    if intent_mapping and isinstance(intent_mapping, dict):
        if "rules" in intent_mapping:
            for i, rule in enumerate(intent_mapping["rules"]):
                if isinstance(rule, dict) and "match" in rule:
                    match = rule["match"]
                    if isinstance(match, dict):
                        et = match.get("entity_type", "any")
                        if et != "any" and et not in valid_entity_types:
                            errors.append(
                                f"intent_mapping rules[{i}] references "
                                f"entity_type {et!r} not in classification_rules"
                            )

    # Check domain_overrides entity_types
    if domain_overrides and isinstance(domain_overrides, dict):
        override_types = set(domain_overrides.values())
        invalid = override_types - valid_entity_types
        if invalid:
            errors.append(
                f"domain_overrides uses entity_types not in "
                f"classification_rules: {invalid}"
            )

    # Check strategic_patterns refs in brief_pattern_routing
    if strategic_patterns and brief_pattern_routing:
        if isinstance(strategic_patterns, list) and isinstance(
            brief_pattern_routing, dict
        ):
            pattern_names = {p.get("Pattern_Name") for p in strategic_patterns if isinstance(p, dict)}

            if "patterns" in brief_pattern_routing:
                routing_patterns = brief_pattern_routing["patterns"]
                if isinstance(routing_patterns, list):
                    for i, rp in enumerate(routing_patterns):
                        if isinstance(rp, dict):
                            pn = rp.get("pattern_name")
                            if pn and pn not in pattern_names:
                                errors.append(
                                    f"brief_pattern_routing patterns[{i}] "
                                    f"references pattern_name {pn!r} "
                                    f"not in strategic_patterns"
                                )

    return (len(errors) == 0, errors, warnings)
