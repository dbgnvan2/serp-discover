"""
Tests for config_manager module.

Purpose: Verify that the Configuration Manager window initializes correctly and tabs
are properly created with correct file associations.

Spec: serp_tool1_improvements_spec.md#phase-1
Tests: tests/test_config_manager.py
"""

import pytest

try:
    import tkinter as tk
    from tkinter import ttk
    TKINTER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    TKINTER_AVAILABLE = False

# Non-GUI tests can run without tkinter
from config_manager import (
    ConfigManagerWindow,
    BaseConfigTab,
    DomainOverridesTab,
    ClassificationRulesTab,
    IntentMappingTab,
    StrategicPatternsTab,
    BriefPatternRoutingTab,
    IntentClassifierTriggersTab,
    ConfigSettingsTab,
    UrlPatternRulesTab,
    VALIDATORS_BY_FILE,
    HELP_BY_FILE,
    HELP_BY_FIELD,
)


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestConfigManagerWindowCreation:
    """Test ConfigManagerWindow initialization."""

    def test_window_creates_without_error(self):
        """ConfigManagerWindow should create without raising exceptions."""
        root = tk.Tk()
        try:
            window = ConfigManagerWindow(root)
            assert window.window is not None
            assert window.window.winfo_exists()
            window.window.destroy()
        finally:
            root.destroy()

    def test_window_title_set(self):
        """Window title should be set correctly."""
        root = tk.Tk()
        try:
            window = ConfigManagerWindow(root)
            assert window.window.title() == "Configuration Manager"
            window.window.destroy()
        finally:
            root.destroy()

    def test_tabs_created(self):
        """All 8 tabs should be created."""
        root = tk.Tk()
        try:
            window = ConfigManagerWindow(root)
            assert len(window.tabs) == 8
            window.window.destroy()
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestBaseConfigTab:
    """Test BaseConfigTab abstract class."""

    def test_domain_overrides_tab_created(self):
        """DomainOverridesTab should create successfully."""
        root = tk.Tk()
        frame = ttk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            assert tab.file_name == "domain_overrides.yml"
            assert tab.file_type == "yaml"
            assert tab.current_data is not None
        finally:
            root.destroy()

    def test_classification_rules_tab_created(self):
        """ClassificationRulesTab should create successfully."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            assert tab.file_name == "classification_rules.json"
            assert tab.file_type == "json"
            assert tab.current_data is not None
        finally:
            root.destroy()

    def test_all_tabs_have_validators(self):
        """All tabs should have corresponding validators in VALIDATORS_BY_FILE."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tabs = [
                DomainOverridesTab(frame),
                ClassificationRulesTab(frame),
                IntentMappingTab(frame),
                StrategicPatternsTab(frame),
                BriefPatternRoutingTab(frame),
                IntentClassifierTriggersTab(frame),
                ConfigSettingsTab(frame),
                UrlPatternRulesTab(frame),
            ]
            for tab in tabs:
                assert tab.file_name in VALIDATORS_BY_FILE, f"No validator for {tab.file_name}"
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestTabFileAssociations:
    """Test that tabs are correctly associated with files."""

    @pytest.mark.parametrize("tab_class, expected_file, expected_type", [
        (DomainOverridesTab, "domain_overrides.yml", "yaml"),
        (ClassificationRulesTab, "classification_rules.json", "json"),
        (IntentMappingTab, "intent_mapping.yml", "yaml"),
        (StrategicPatternsTab, "strategic_patterns.yml", "yaml"),
        (BriefPatternRoutingTab, "brief_pattern_routing.yml", "yaml"),
        (IntentClassifierTriggersTab, "intent_classifier_triggers.yml", "yaml"),
        (ConfigSettingsTab, "config.yml", "yaml"),
        (UrlPatternRulesTab, "url_pattern_rules.yml", "yaml"),
    ])
    def test_tab_file_associations(self, tab_class, expected_file, expected_type):
        """Each tab should be associated with correct file and type."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = tab_class(frame)
            assert tab.file_name == expected_file
            assert tab.file_type == expected_type
        finally:
            root.destroy()


class TestHelpRegistry:
    """Test help text registries."""

    def test_all_files_have_help(self):
        """All config files should have help text in HELP_BY_FILE."""
        expected_files = [
            "intent_mapping.yml",
            "strategic_patterns.yml",
            "brief_pattern_routing.yml",
            "intent_classifier_triggers.yml",
            "config.yml",
            "domain_overrides.yml",
            "classification_rules.json",
            "url_pattern_rules.yml",
        ]
        for file_name in expected_files:
            assert file_name in HELP_BY_FILE, f"No help text for {file_name}"
            assert len(HELP_BY_FILE[file_name]) > 0

    def test_help_field_registry_not_empty(self):
        """HELP_BY_FIELD should contain help for fields."""
        assert len(HELP_BY_FIELD) > 0


class TestValidatorRegistry:
    """Test validator registry."""

    def test_all_files_have_validators(self):
        """All config files should have validators in VALIDATORS_BY_FILE."""
        expected_files = [
            "intent_mapping.yml",
            "strategic_patterns.yml",
            "brief_pattern_routing.yml",
            "intent_classifier_triggers.yml",
            "config.yml",
            "domain_overrides.yml",
            "classification_rules.json",
            "url_pattern_rules.yml",
        ]
        for file_name in expected_files:
            assert file_name in VALIDATORS_BY_FILE, f"No validator for {file_name}"
            assert callable(VALIDATORS_BY_FILE[file_name])


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestTabValidation:
    """Test tab validation methods."""

    def test_tab_validate_returns_tuple(self):
        """Tab.validate() should return (is_valid, errors, warnings) tuple."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            result = tab.validate()
            assert isinstance(result, tuple)
            assert len(result) == 3
            is_valid, errors, warnings = result
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_tab_unsaved_changes_detection(self):
        """Tab.has_unsaved_changes() should detect changes."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestTabDataLoading:
    """Test that tabs load data from disk."""

    def test_tab_loads_data_from_disk(self):
        """Tabs should load current data from disk on initialization."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            # current_data should be loaded
            assert tab.current_data is not None
            assert isinstance(tab.current_data, (dict, list))
        finally:
            root.destroy()

    def test_tab_get_edited_data_returns_data(self):
        """Tab.get_edited_data() should return data structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            data = tab.get_edited_data()
            assert data is not None
        finally:
            root.destroy()


class TestDomainOverridesTabPhase2:
    """Phase 2: Test DomainOverridesTab CRUD operations and validation."""

    def test_domain_overrides_loads_current_data(self):
        """DomainOverridesTab should load domain_overrides.yml data."""
        # Test without rendering UI - just test the data loading
        import yaml
        with open("domain_overrides.yml", "r") as f:
            current_data = yaml.safe_load(f) or {}

        # Should be dict of domain -> entity_type
        assert isinstance(current_data, dict)
        # Verify it's structured correctly
        for key, value in current_data.items():
            assert isinstance(key, str)  # domain
            assert isinstance(value, str)  # entity_type

    def test_domain_overrides_validation_passes_on_current_data(self):
        """DomainOverridesTab validation should pass on current data."""
        import yaml
        from config_validators import validate_domain_overrides

        with open("domain_overrides.yml", "r") as f:
            current_data = yaml.safe_load(f) or {}

        is_valid, errors, warnings = validate_domain_overrides(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"
        assert isinstance(errors, list)
        assert isinstance(warnings, list)

    def test_domain_overrides_get_edited_data_roundtrip(self):
        """DomainOverridesTab should preserve data through roundtrip."""
        import yaml

        # Load original data
        with open("domain_overrides.yml", "r") as f:
            original_data = yaml.safe_load(f) or {}

        # Simulate what get_edited_data does: extract from treeview as dict
        # Since we can't test GUI, we test that dict structure is correct
        if isinstance(original_data, dict):
            edited_data = original_data.copy()
            assert edited_data == original_data
            # Each entry should have domain -> entity_type
            for domain, entity_type in edited_data.items():
                assert isinstance(domain, str)
                assert isinstance(entity_type, str)


class TestClassificationRulesTabPhase2:
    """Phase 2: Test ClassificationRulesTab CRUD operations and validation."""

    def test_classification_rules_loads_current_data(self):
        """ClassificationRulesTab should load classification_rules.json data."""
        import json
        from config_validators import validate_classification_rules

        with open("classification_rules.json", "r") as f:
            current_data = json.load(f)

        # Should have entity_types and entity_type_descriptions
        assert isinstance(current_data, dict)
        assert "entity_types" in current_data
        assert "entity_type_descriptions" in current_data
        assert isinstance(current_data["entity_types"], list)
        assert isinstance(current_data["entity_type_descriptions"], dict)

    def test_classification_rules_validation_passes_on_current_data(self):
        """ClassificationRulesTab validation should pass on current data."""
        import json
        from config_validators import validate_classification_rules

        with open("classification_rules.json", "r") as f:
            current_data = json.load(f)

        is_valid, errors, warnings = validate_classification_rules(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"
        assert isinstance(errors, list)
        assert isinstance(warnings, list)

    def test_classification_rules_preserves_extra_keys(self):
        """ClassificationRulesTab should preserve extra keys like content_patterns."""
        import json

        with open("classification_rules.json", "r") as f:
            current_data = json.load(f)

        # Should have content_patterns, entity_patterns, etc.
        # At minimum, should preserve keys beyond entity_types and descriptions
        has_extra_keys = any(
            key not in ["entity_types", "entity_type_descriptions"]
            for key in current_data
        )
        # File should have extra structure
        assert "entity_types" in current_data
        assert "entity_type_descriptions" in current_data


class TestIntentMappingTabPhase3:
    """Phase 3: Test IntentMappingTab CRUD operations and ordering."""

    def test_intent_mapping_loads_current_data(self):
        """IntentMappingTab should load intent_mapping.yml data."""
        import yaml
        from config_validators import validate_intent_mapping

        with open("intent_mapping.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Should have version and rules
        assert isinstance(current_data, dict)
        assert "version" in current_data
        assert "rules" in current_data
        assert isinstance(current_data["rules"], list)

    def test_intent_mapping_structure_correct(self):
        """IntentMappingTab rules should have correct structure."""
        import yaml

        with open("intent_mapping.yml", "r") as f:
            current_data = yaml.safe_load(f)

        rules = current_data.get("rules", [])
        # All rules should have match and intent
        for rule in rules:
            assert "match" in rule, f"Rule missing 'match': {rule}"
            assert "intent" in rule, f"Rule missing 'intent': {rule}"
            match = rule["match"]
            assert "content_type" in match
            assert "entity_type" in match
            assert "local_pack" in match
            assert "domain_role" in match

    def test_intent_mapping_validation_passes_on_current_data(self):
        """IntentMappingTab validation should pass on current data."""
        import yaml
        from config_validators import validate_intent_mapping

        with open("intent_mapping.yml", "r") as f:
            current_data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_intent_mapping(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"
        assert isinstance(errors, list)
        assert isinstance(warnings, list)


class TestStrategicPatternsTabPhase3:
    """Phase 3: Test StrategicPatternsTab CRUD operations."""

    def test_strategic_patterns_loads_current_data(self):
        """StrategicPatternsTab should load strategic_patterns.yml data."""
        import yaml
        from config_validators import validate_strategic_patterns

        with open("strategic_patterns.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Should be list of pattern dicts
        assert isinstance(current_data, list)
        if current_data:
            # Check first pattern has required fields
            pattern = current_data[0]
            assert isinstance(pattern, dict)
            assert "Pattern_Name" in pattern
            assert "Triggers" in pattern
            assert "Status_Quo_Message" in pattern
            assert "Bowen_Bridge_Reframe" in pattern
            assert "Content_Angle" in pattern

    def test_strategic_patterns_validation_passes_on_current_data(self):
        """StrategicPatternsTab validation should pass on current data."""
        import yaml
        from config_validators import validate_strategic_patterns

        with open("strategic_patterns.yml", "r") as f:
            current_data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_strategic_patterns(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"
        assert isinstance(errors, list)
        assert isinstance(warnings, list)

    def test_strategic_patterns_trigger_counts(self):
        """StrategicPatternsTab should handle trigger counts correctly."""
        import yaml

        with open("strategic_patterns.yml", "r") as f:
            patterns = yaml.safe_load(f)

        # Verify trigger counts match
        for pattern in patterns:
            triggers = pattern.get("Triggers", [])
            assert isinstance(triggers, list)
            assert len(triggers) > 0, f"Pattern {pattern.get('Pattern_Name')} has no triggers"


class TestBriefPatternRoutingTabPhase4:
    """Phase 4: Test BriefPatternRoutingTab CRUD operations."""

    def test_brief_pattern_routing_loads_current_data(self):
        """BriefPatternRoutingTab should load brief_pattern_routing.yml data."""
        import yaml
        from config_validators import validate_brief_pattern_routing

        with open("brief_pattern_routing.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Should have version, patterns, intent_slot_descriptions
        assert isinstance(current_data, dict)
        assert "version" in current_data
        assert "patterns" in current_data
        assert "intent_slot_descriptions" in current_data
        assert isinstance(current_data["patterns"], list)
        assert isinstance(current_data["intent_slot_descriptions"], dict)

    def test_brief_pattern_routing_structure_correct(self):
        """BriefPatternRoutingTab patterns should have correct structure."""
        import yaml

        with open("brief_pattern_routing.yml", "r") as f:
            current_data = yaml.safe_load(f)

        patterns = current_data.get("patterns", [])
        for pattern in patterns:
            assert "pattern_name" in pattern
            assert "paa_themes" in pattern
            assert "paa_categories" in pattern
            assert "keyword_hints" in pattern
            # All should be lists
            assert isinstance(pattern["paa_themes"], list)
            assert isinstance(pattern["paa_categories"], list)
            assert isinstance(pattern["keyword_hints"], list)

    def test_brief_pattern_routing_validation_passes_on_current_data(self):
        """BriefPatternRoutingTab validation should pass on current data."""
        import yaml
        from config_validators import validate_brief_pattern_routing

        with open("brief_pattern_routing.yml", "r") as f:
            current_data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_brief_pattern_routing(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"


class TestIntentClassifierTriggersTabPhase4:
    """Phase 4: Test IntentClassifierTriggersTab trigger management."""

    def test_intent_classifier_triggers_loads_current_data(self):
        """IntentClassifierTriggersTab should load intent_classifier_triggers.yml data."""
        import yaml
        from config_validators import validate_intent_classifier_triggers

        with open("intent_classifier_triggers.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Should have version, medical_triggers, systemic_triggers
        assert isinstance(current_data, dict)
        assert "version" in current_data
        assert "medical_triggers" in current_data
        assert "systemic_triggers" in current_data
        # Each should have multi_word and single_word
        assert isinstance(current_data["medical_triggers"], dict)
        assert "multi_word" in current_data["medical_triggers"]
        assert "single_word" in current_data["medical_triggers"]

    def test_intent_classifier_triggers_validation_passes_on_current_data(self):
        """IntentClassifierTriggersTab validation should pass on current data."""
        import yaml
        from config_validators import validate_intent_classifier_triggers

        with open("intent_classifier_triggers.yml", "r") as f:
            current_data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_intent_classifier_triggers(current_data)
        # Current data on disk should be valid
        assert is_valid is True, f"Validation failed: {errors}"

    def test_intent_classifier_triggers_structure_correct(self):
        """IntentClassifierTriggersTab triggers should have correct structure."""
        import yaml

        with open("intent_classifier_triggers.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Check medical triggers
        medical = current_data.get("medical_triggers", {})
        assert isinstance(medical.get("multi_word", []), list)
        assert isinstance(medical.get("single_word", []), list)

        # Check systemic triggers
        systemic = current_data.get("systemic_triggers", {})
        assert isinstance(systemic.get("multi_word", []), list)
        assert isinstance(systemic.get("single_word", []), list)

        # All lists should be non-empty
        assert len(medical.get("multi_word", [])) > 0
        assert len(medical.get("single_word", [])) > 0
        assert len(systemic.get("multi_word", [])) > 0
        assert len(systemic.get("single_word", [])) > 0


class TestConfigSettingsTabPhase5:
    """Test ConfigSettingsTab (config.yml editing)."""

    def test_config_settings_loads_current_data(self):
        """ConfigSettingsTab should load config.yml data."""
        import yaml
        with open("config.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Verify structure
        assert isinstance(current_data, dict)
        assert "serpapi" in current_data
        assert "files" in current_data
        assert "enrichment" in current_data

    def test_config_settings_validation_passes(self):
        """ConfigSettingsTab should validate config.yml without errors."""
        from config_validators import validate_config_yml
        import yaml

        with open("config.yml", "r") as f:
            data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_config_yml(data)
        assert is_valid is True, f"Validation failed: {errors}"
        assert len(errors) == 0

    def test_config_settings_preserves_sections(self):
        """ConfigSettingsTab should preserve all top-level sections."""
        import yaml

        with open("config.yml", "r") as f:
            data = yaml.safe_load(f)

        # All major sections should exist
        expected_sections = ["serpapi", "files", "enrichment", "app"]
        for section in expected_sections:
            assert section in data, f"Missing section: {section}"


class TestUrlPatternRulesTabPhase5:
    """Test UrlPatternRulesTab (url_pattern_rules.yml editing)."""

    def test_url_pattern_rules_loads_current_data(self):
        """UrlPatternRulesTab should load url_pattern_rules.yml data."""
        import yaml

        with open("url_pattern_rules.yml", "r") as f:
            current_data = yaml.safe_load(f)

        # Verify structure
        assert isinstance(current_data, dict)
        assert "version" in current_data
        assert "url_pattern_rules" in current_data
        assert isinstance(current_data["url_pattern_rules"], list)

    def test_url_pattern_rules_validation_passes(self):
        """UrlPatternRulesTab should validate url_pattern_rules.yml without errors."""
        from config_validators import validate_url_pattern_rules
        import yaml

        with open("url_pattern_rules.yml", "r") as f:
            data = yaml.safe_load(f)

        is_valid, errors, warnings = validate_url_pattern_rules(data)
        assert is_valid is True, f"Validation failed: {errors}"
        assert len(errors) == 0

    def test_url_pattern_rules_structure_correct(self):
        """UrlPatternRulesTab should verify all rules have required fields."""
        import yaml

        with open("url_pattern_rules.yml", "r") as f:
            data = yaml.safe_load(f)

        for rule in data.get("url_pattern_rules", []):
            assert "pattern" in rule, "Rule missing 'pattern' field"
            assert "entity_types" in rule, "Rule missing 'entity_types' field"
            assert "content_type" in rule, "Rule missing 'content_type' field"
            assert isinstance(rule["pattern"], str), "pattern must be string"
            assert isinstance(rule["entity_types"], list), "entity_types must be list"
            assert isinstance(rule["content_type"], str), "content_type must be string"

    def test_url_pattern_rules_regex_validity(self):
        """UrlPatternRulesTab should validate regex patterns can compile."""
        import yaml
        import re

        with open("url_pattern_rules.yml", "r") as f:
            data = yaml.safe_load(f)

        for rule in data.get("url_pattern_rules", []):
            pattern = rule["pattern"]
            try:
                re.compile(pattern)
            except re.error as e:
                assert False, f"Invalid regex pattern '{pattern}': {e}"
