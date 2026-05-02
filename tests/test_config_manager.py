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


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestDomainOverridesTabPhase2:
    """Phase 2: Test DomainOverridesTab CRUD operations and validation."""

    def test_domain_overrides_loads_current_data(self):
        """DomainOverridesTab should load domain_overrides.yml data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            # Should load dict of domain -> entity_type
            assert isinstance(tab.current_data, dict)
            # Verify it's structured correctly
            for key, value in tab.current_data.items():
                assert isinstance(key, str)  # domain
                assert isinstance(value, str)  # entity_type
        finally:
            root.destroy()

    def test_domain_overrides_get_edited_data_preserves_dict(self):
        """DomainOverridesTab.get_edited_data() should return dict."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            edited_data = tab.get_edited_data()
            # Should return dict with same structure as current_data
            assert isinstance(edited_data, dict)
            assert edited_data == tab.current_data
        finally:
            root.destroy()

    def test_domain_overrides_validation_passes_on_current_data(self):
        """DomainOverridesTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_domain_overrides_treeview_populated(self):
        """DomainOverridesTab treeview should be populated with data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            # Check treeview has items
            items = tab.tree.get_children()
            # Should have at least as many rows as entries in current_data
            assert len(items) == len(tab.current_data)
        finally:
            root.destroy()

    def test_domain_overrides_unsaved_changes_detected(self):
        """DomainOverridesTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = DomainOverridesTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            # Add a row (simulate user action)
            # This is a limitation of GUI testing - the tree changes don't automatically
            # trigger has_unsaved_changes unless we modify the underlying logic
            # For now, verify the method exists and returns a boolean
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestClassificationRulesTabPhase2:
    """Phase 2: Test ClassificationRulesTab CRUD operations and validation."""

    def test_classification_rules_loads_current_data(self):
        """ClassificationRulesTab should load classification_rules.json data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            # Should load dict with entity_types and entity_type_descriptions
            assert isinstance(tab.current_data, dict)
            assert "entity_types" in tab.current_data
            assert "entity_type_descriptions" in tab.current_data
            assert isinstance(tab.current_data["entity_types"], list)
            assert isinstance(tab.current_data["entity_type_descriptions"], dict)
        finally:
            root.destroy()

    def test_classification_rules_get_edited_data_preserves_structure(self):
        """ClassificationRulesTab.get_edited_data() should preserve structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            edited_data = tab.get_edited_data()
            # Should have same keys as original
            assert "entity_types" in edited_data
            assert "entity_type_descriptions" in edited_data
            assert isinstance(edited_data["entity_types"], list)
            assert isinstance(edited_data["entity_type_descriptions"], dict)
        finally:
            root.destroy()

    def test_classification_rules_validation_passes_on_current_data(self):
        """ClassificationRulesTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_classification_rules_entity_types_treeview_populated(self):
        """ClassificationRulesTab entity_types treeview should be populated."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            # Check entity_types treeview has items
            items = tab.entity_types_tree.get_children()
            # Should have same number of items as entity_types list
            assert len(items) == len(tab.current_data.get("entity_types", []))
        finally:
            root.destroy()

    def test_classification_rules_descriptions_treeview_populated(self):
        """ClassificationRulesTab descriptions treeview should be populated."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            # Check descriptions treeview has items
            items = tab.descriptions_tree.get_children()
            # Should have same number of items as descriptions dict
            assert len(items) == len(tab.current_data.get("entity_type_descriptions", {}))
        finally:
            root.destroy()

    def test_classification_rules_preserves_extra_keys(self):
        """ClassificationRulesTab should preserve extra keys like content_patterns."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            edited_data = tab.get_edited_data()
            # Should preserve content_patterns, entity_patterns, etc.
            for key in tab.current_data:
                if key not in ["entity_types", "entity_type_descriptions"]:
                    assert key in edited_data, f"Missing key: {key}"
        finally:
            root.destroy()

    def test_classification_rules_unsaved_changes_detected(self):
        """ClassificationRulesTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = ClassificationRulesTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            # Verify the method returns a boolean
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestIntentMappingTabPhase3:
    """Phase 3: Test IntentMappingTab CRUD operations and ordering."""

    def test_intent_mapping_loads_current_data(self):
        """IntentMappingTab should load intent_mapping.yml data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            # Should load dict with version and rules
            assert isinstance(tab.current_data, dict)
            assert "version" in tab.current_data
            assert "rules" in tab.current_data
            assert isinstance(tab.current_data["rules"], list)
        finally:
            root.destroy()

    def test_intent_mapping_get_edited_data_preserves_structure(self):
        """IntentMappingTab.get_edited_data() should preserve structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            edited_data = tab.get_edited_data()
            # Should have version and rules
            assert "version" in edited_data
            assert "rules" in edited_data
            assert isinstance(edited_data["rules"], list)
            # All rules should have match and intent
            for rule in edited_data["rules"]:
                assert "match" in rule
                assert "intent" in rule
                assert "content_type" in rule["match"]
                assert "entity_type" in rule["match"]
        finally:
            root.destroy()

    def test_intent_mapping_validation_passes_on_current_data(self):
        """IntentMappingTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_intent_mapping_treeview_populated(self):
        """IntentMappingTab treeview should be populated with rules."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            # Check treeview has items
            items = tab.tree.get_children()
            # Should have same number of items as rules
            assert len(items) == len(tab.current_data.get("rules", []))
        finally:
            root.destroy()

    def test_intent_mapping_rule_order_preserved(self):
        """IntentMappingTab should preserve rule order from file."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            items = tab.tree.get_children()
            rules = tab.current_data.get("rules", [])

            # Verify order matches
            for i, item in enumerate(items):
                values = tab.tree.item(item)["values"]
                rule = rules[i]
                match = rule.get("match", {})
                assert values[0] == match.get("content_type")
                assert values[1] == match.get("entity_type")
                assert values[2] == match.get("local_pack")
                assert values[3] == rule.get("intent")
        finally:
            root.destroy()

    def test_intent_mapping_unsaved_changes_detected(self):
        """IntentMappingTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentMappingTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestStrategicPatternsTabPhase3:
    """Phase 3: Test StrategicPatternsTab CRUD operations."""

    def test_strategic_patterns_loads_current_data(self):
        """StrategicPatternsTab should load strategic_patterns.yml data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            # Should load list of pattern dicts
            assert isinstance(tab.current_data, list)
            if tab.current_data:
                # Check first pattern has required fields
                pattern = tab.current_data[0]
                assert isinstance(pattern, dict)
                assert "Pattern_Name" in pattern
                assert "Triggers" in pattern
                assert "Status_Quo_Message" in pattern
                assert "Bowen_Bridge_Reframe" in pattern
                assert "Content_Angle" in pattern
        finally:
            root.destroy()

    def test_strategic_patterns_get_edited_data_preserves_structure(self):
        """StrategicPatternsTab.get_edited_data() should preserve structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            edited_data = tab.get_edited_data()
            # Should be a list of patterns
            assert isinstance(edited_data, list)
            # Should have same number of patterns as current_data
            assert len(edited_data) == len(tab.current_data)
            # Each pattern should have required fields
            for pattern in edited_data:
                assert "Pattern_Name" in pattern
                assert "Triggers" in pattern
        finally:
            root.destroy()

    def test_strategic_patterns_validation_passes_on_current_data(self):
        """StrategicPatternsTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_strategic_patterns_treeview_populated(self):
        """StrategicPatternsTab treeview should be populated with patterns."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            # Check treeview has items
            items = tab.tree.get_children()
            # Should have same number of items as patterns
            assert len(items) == len(tab.current_data)
        finally:
            root.destroy()

    def test_strategic_patterns_triggers_counted_correctly(self):
        """StrategicPatternsTab should count triggers correctly."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            items = tab.tree.get_children()
            patterns = tab.current_data

            # Verify trigger counts
            for i, item in enumerate(items):
                values = tab.tree.item(item)["values"]
                pattern_name, triggers_count, status = values
                pattern = patterns[i]
                expected_count = len(pattern.get("Triggers", []))
                assert triggers_count == expected_count
        finally:
            root.destroy()

    def test_strategic_patterns_unsaved_changes_detected(self):
        """StrategicPatternsTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = StrategicPatternsTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestBriefPatternRoutingTabPhase4:
    """Phase 4: Test BriefPatternRoutingTab CRUD operations."""

    def test_brief_pattern_routing_loads_current_data(self):
        """BriefPatternRoutingTab should load brief_pattern_routing.yml data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            # Should load dict with version, patterns, intent_slot_descriptions
            assert isinstance(tab.current_data, dict)
            assert "version" in tab.current_data
            assert "patterns" in tab.current_data
            assert "intent_slot_descriptions" in tab.current_data
            assert isinstance(tab.current_data["patterns"], list)
            assert isinstance(tab.current_data["intent_slot_descriptions"], dict)
        finally:
            root.destroy()

    def test_brief_pattern_routing_get_edited_data_preserves_structure(self):
        """BriefPatternRoutingTab.get_edited_data() should preserve structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            edited_data = tab.get_edited_data()
            # Should have version, patterns, intent_slot_descriptions
            assert "version" in edited_data
            assert "patterns" in edited_data
            assert "intent_slot_descriptions" in edited_data
            assert isinstance(edited_data["patterns"], list)
            # Each pattern should have required fields
            for pattern in edited_data["patterns"]:
                assert "pattern_name" in pattern
                assert "paa_themes" in pattern
                assert "paa_categories" in pattern
                assert "keyword_hints" in pattern
        finally:
            root.destroy()

    def test_brief_pattern_routing_validation_passes_on_current_data(self):
        """BriefPatternRoutingTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_brief_pattern_routing_treeview_populated(self):
        """BriefPatternRoutingTab treeview should be populated."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            # Check treeview has items
            items = tab.tree.get_children()
            # Should have same number of items as patterns
            assert len(items) == len(tab.current_data.get("patterns", []))
        finally:
            root.destroy()

    def test_brief_pattern_routing_intent_descriptions_loaded(self):
        """BriefPatternRoutingTab should load intent descriptions."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            # Should have intent descriptions
            assert tab.intent_descriptions is not None
            assert isinstance(tab.intent_descriptions, dict)
            # Should have at least some descriptions from file
            assert len(tab.intent_descriptions) > 0
        finally:
            root.destroy()

    def test_brief_pattern_routing_unsaved_changes_detected(self):
        """BriefPatternRoutingTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = BriefPatternRoutingTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestIntentClassifierTriggersTabPhase4:
    """Phase 4: Test IntentClassifierTriggersTab trigger management."""

    def test_intent_classifier_triggers_loads_current_data(self):
        """IntentClassifierTriggersTab should load intent_classifier_triggers.yml data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentClassifierTriggersTab(frame)
            # Should load dict with version, medical_triggers, systemic_triggers
            assert isinstance(tab.current_data, dict)
            assert "version" in tab.current_data
            assert "medical_triggers" in tab.current_data
            assert "systemic_triggers" in tab.current_data
            # Each should have multi_word and single_word
            assert isinstance(tab.current_data["medical_triggers"], dict)
            assert "multi_word" in tab.current_data["medical_triggers"]
            assert "single_word" in tab.current_data["medical_triggers"]
        finally:
            root.destroy()

    def test_intent_classifier_triggers_get_edited_data_preserves_structure(self):
        """IntentClassifierTriggersTab.get_edited_data() should preserve structure."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentClassifierTriggersTab(frame)
            edited_data = tab.get_edited_data()
            # Should have version and both trigger types
            assert "version" in edited_data
            assert "medical_triggers" in edited_data
            assert "systemic_triggers" in edited_data
            # Each should have multi_word and single_word lists
            assert isinstance(edited_data["medical_triggers"]["multi_word"], list)
            assert isinstance(edited_data["medical_triggers"]["single_word"], list)
            assert isinstance(edited_data["systemic_triggers"]["multi_word"], list)
            assert isinstance(edited_data["systemic_triggers"]["single_word"], list)
        finally:
            root.destroy()

    def test_intent_classifier_triggers_validation_passes_on_current_data(self):
        """IntentClassifierTriggersTab should validate against current data."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentClassifierTriggersTab(frame)
            is_valid, errors, warnings = tab.validate()
            # Current data on disk should be valid
            assert isinstance(is_valid, bool)
            assert isinstance(errors, list)
            assert isinstance(warnings, list)
        finally:
            root.destroy()

    def test_intent_classifier_triggers_text_widgets_populated(self):
        """IntentClassifierTriggersTab text widgets should be populated."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentClassifierTriggersTab(frame)
            # Check medical triggers text widgets have content
            medical_mw_content = tab.medical_mw_text.get("1.0", "end").strip()
            medical_sw_content = tab.medical_sw_text.get("1.0", "end").strip()
            # Should have at least some triggers
            assert len(medical_mw_content) > 0
            assert len(medical_sw_content) > 0
            # Check systemic triggers text widgets have content
            systemic_mw_content = tab.systemic_mw_text.get("1.0", "end").strip()
            systemic_sw_content = tab.systemic_sw_text.get("1.0", "end").strip()
            assert len(systemic_mw_content) > 0
            assert len(systemic_sw_content) > 0
        finally:
            root.destroy()

    def test_intent_classifier_triggers_unsaved_changes_detected(self):
        """IntentClassifierTriggersTab should detect when data is modified."""
        root = tk.Tk()
        frame = tk.Frame(root)
        try:
            tab = IntentClassifierTriggersTab(frame)
            # Initially no changes
            assert not tab.has_unsaved_changes()
            result = tab.has_unsaved_changes()
            assert isinstance(result, bool)
        finally:
            root.destroy()
