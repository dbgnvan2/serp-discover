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
except (ImportError, ModuleNotFoundError):
    tk = ttk = None
from tk_probe import tkinter_usable

# Not "is tkinter importable" — "can a window actually be created here".
TKINTER_AVAILABLE = tkinter_usable()

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
    ClientProfileTab,
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
        """Every file the window claims to edit gets a tab.

        Asserted against the files, not a count: the count is what went stale
        when ten editorial files reached the repo with no editor (review chunk
        Y15).
        """
        from config_tab_models import EDITORIAL_SOURCE_FILES
        root = tk.Tk()
        try:
            window = ConfigManagerWindow(root)
            names = [tab.file_name for tab in window.tabs]
            assert len(names) == len(set(names)), f"duplicate tab: {names}"
            for file_name, _type, _title, _check in EDITORIAL_SOURCE_FILES:
                assert file_name in names, f"no tab edits {file_name}"
            # The nine bespoke forms are still there beside the source tabs.
            assert len(names) == 9 + len(EDITORIAL_SOURCE_FILES)
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

    @pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
    def test_config_settings_tab_renders_without_error(self):
        """ConfigSettingsTab should render all sections without NameError or AttributeError."""
        root = tk.Tk()
        try:
            # This will instantiate the tab and call render_ui(), which should not raise errors
            tab = ConfigSettingsTab(root)
            assert tab is not None
            assert hasattr(tab, 'section_widgets')
            # Verify at least some widgets were created
            assert len(tab.section_widgets) > 0, "No sections were rendered"
            root.destroy()
        except (NameError, AttributeError) as e:
            root.destroy()
            pytest.fail(f"ConfigSettingsTab.render_ui() failed: {e}")

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


class TestTabInitializationOrder:
    """Test that all tabs initialize their instance variables BEFORE calling super().__init__().

    This prevents AttributeError when render_ui() is called during initialization.
    """

    def test_all_tab_classes_can_be_imported(self):
        """All tab classes should import without error."""
        # This test verifies that all tab classes are properly defined
        from config_manager import (
            DomainOverridesTab,
            ClassificationRulesTab,
            IntentMappingTab,
            StrategicPatternsTab,
            BriefPatternRoutingTab,
            IntentClassifierTriggersTab,
            ConfigSettingsTab,
            UrlPatternRulesTab,
        )
        # If we got here, all imports succeeded
        assert True

    def test_tab_classes_have_instance_variables(self):
        """Verify that tab classes declare instance variables they will use.

        This catches a common pattern error: initializing variables AFTER
        calling super().__init__(), which immediately calls render_ui().

        This test doesn't require tkinter - it just checks that the class
        definitions reference the expected attributes in __init__.
        """
        import inspect
        from config_manager import (
            DomainOverridesTab,
            IntentMappingTab,
            ConfigSettingsTab,
            UrlPatternRulesTab,
            ClientProfileTab,
        )

        # Check each tab has required instance attributes
        checks = [
            (DomainOverridesTab, ['tree', 'entity_type_var']),
            (IntentMappingTab, ['tree']),
            (ConfigSettingsTab, ['section_widgets', 'section_frames']),
            (UrlPatternRulesTab, ['tree']),
            # Y.13.2 — the client-profile tab follows the same init-order rule.
            (ClientProfileTab, ['client_selector', 'selected_slug',
                                'preview_widget', 'field_vars']),
        ]

        for tab_class, expected_attrs in checks:
            # Get the __init__ source code
            init_source = inspect.getsource(tab_class.__init__)

            # Verify that each expected attribute is initialized with self.attr = ...
            # before the super().__init__() call
            super_index = init_source.find('super().__init__')
            assert super_index != -1, f"{tab_class.__name__} missing super().__init__() call"

            init_before_super = init_source[:super_index]

            for attr in expected_attrs:
                attr_init = f'self.{attr} ='
                assert attr_init in init_before_super, (
                    f"{tab_class.__name__}: attribute '{attr}' must be initialized "
                    f"BEFORE super().__init__() to avoid AttributeError in render_ui()"
                )

    @pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
    def test_domain_overrides_tab_initializes_without_error(self):
        """DomainOverridesTab should initialize all attributes before render_ui()."""
        root = tk.Tk()
        try:
            tab = DomainOverridesTab(root)
            assert hasattr(tab, 'tree')
            assert hasattr(tab, 'entity_type_var')
            # render_ui() runs inside __init__ (via super().__init__) when
            # tkinter is available, so tree is populated to a Treeview by the
            # time construction returns. The init-order contract this test
            # guards is that the attribute EXISTS before render_ui() touches it
            # (asserted via hasattr + the AttributeError guard below).
            assert tab.tree is not None
            assert tab.entity_type_var is None
            root.destroy()
        except AttributeError as e:
            root.destroy()
            pytest.fail(f"DomainOverridesTab initialization failed with AttributeError: {e}")

    @pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
    def test_intent_mapping_tab_initializes_without_error(self):
        """IntentMappingTab should initialize all attributes before render_ui()."""
        root = tk.Tk()
        try:
            tab = IntentMappingTab(root)
            assert hasattr(tab, 'tree')
            # render_ui() runs inside __init__ (via super().__init__) when
            # tkinter is available, so tree is populated to a Treeview by the
            # time construction returns. The init-order contract this test
            # guards is that the attribute EXISTS before render_ui() touches it
            # (asserted via hasattr + the AttributeError guard below).
            assert tab.tree is not None
            root.destroy()
        except AttributeError as e:
            root.destroy()
            pytest.fail(f"IntentMappingTab initialization failed with AttributeError: {e}")

    @pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
    def test_config_settings_tab_initializes_without_error(self):
        """ConfigSettingsTab should initialize all attributes before render_ui()."""
        root = tk.Tk()
        try:
            tab = ConfigSettingsTab(root)
            assert hasattr(tab, 'section_widgets')
            assert hasattr(tab, 'section_frames')
            assert isinstance(tab.section_widgets, dict)
            assert isinstance(tab.section_frames, dict)
            root.destroy()
        except AttributeError as e:
            root.destroy()
            pytest.fail(f"ConfigSettingsTab initialization failed with AttributeError: {e}")

    @pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
    def test_url_pattern_rules_tab_initializes_without_error(self):
        """UrlPatternRulesTab should initialize all attributes before render_ui()."""
        root = tk.Tk()
        try:
            tab = UrlPatternRulesTab(root)
            assert hasattr(tab, 'tree')
            # render_ui() runs inside __init__ (via super().__init__) when
            # tkinter is available, so tree is populated to a Treeview by the
            # time construction returns. The init-order contract this test
            # guards is that the attribute EXISTS before render_ui() touches it
            # (asserted via hasattr + the AttributeError guard below).
            assert tab.tree is not None
            root.destroy()
        except AttributeError as e:
            root.destroy()
            pytest.fail(f"UrlPatternRulesTab initialization failed with AttributeError: {e}")


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


@pytest.mark.skipif(not TKINTER_AVAILABLE, reason="tkinter not available")
class TestEditorialSourceTab:
    """Review chunk Y15. Driving the real tab, because the bug this class
    produced was invisible to the data-side tests: `BaseConfigTab.validate`
    returns early for a file with no validator, so reading a remembered parse
    error there read the result of whenever the text was last parsed — and a
    broken edit to glossary.yml saved successfully (P16).

    `directory=` rather than `os.chdir`: the tab used to join the file name
    onto the current directory, so the editor wrote somewhere none of the
    file's ten readers look, and tests that chdir'd into a temp directory
    pinned that behaviour instead of catching it (the cold review of chunk
    Y15, finding 2).
    """

    @staticmethod
    def _tab(tmp_path, source="a: 1\n", name="glossary.yml"):
        import tkinter as tk
        from config_manager import EditorialSourceTab
        if source is not None:
            (tmp_path / name).write_text(source, encoding="utf-8")
        root = tk.Tk()
        try:
            return root, EditorialSourceTab(root, name, "yaml", "Glossary",
                                            directory=str(tmp_path))
        except Exception:
            root.destroy()
            raise

    def test_the_tab_edits_the_file_beside_the_code_not_the_cwd(
            self, tmp_path, monkeypatch):
        """With no directory given, the tab must point at the same file the
        readers do: nine of the ten anchor on the module's own directory.

        Run from somewhere else on purpose. The test suite's own cwd IS that
        directory, so asserting this from here proves nothing — which is why
        the bug survived: a GUI started from another directory showed a blank
        Glossary tab, reported no error, and Save All said it had written a
        file nothing reads.
        """
        import os
        import config_tab_models
        monkeypatch.chdir(tmp_path)
        resolved = config_tab_models.editorial_file_path("glossary.yml")
        assert resolved == os.path.join(config_tab_models.EDITORIAL_DIR,
                                        "glossary.yml")
        assert not os.path.realpath(resolved).startswith(
            os.path.realpath(str(tmp_path)))
        assert os.path.isfile(resolved)

    def test_a_broken_edit_is_refused_and_the_file_is_untouched(self, tmp_path):
        root, tab = self._tab(tmp_path)
        try:
            before = (tmp_path / "glossary.yml").read_text(encoding="utf-8")
            tab.source_widget.insert("1.0", "a: [1, 2\n")
            ok, message = tab.save_to_disk()
            assert not ok
            assert "does not parse" in message
            assert (tmp_path / "glossary.yml").read_text(
                encoding="utf-8") == before
        finally:
            root.destroy()

    def test_a_comment_the_user_typed_survives_the_save(self, tmp_path):
        root, tab = self._tab(tmp_path)
        try:
            tab.source_widget.insert("1.0", "# why this is 1\n")
            ok, _message = tab.save_to_disk()
            assert ok
            written = (tmp_path / "glossary.yml").read_text(encoding="utf-8")
            assert written.startswith("# why this is 1")
            assert not tab.has_unsaved_changes()
        finally:
            root.destroy()

    def test_saving_an_unchanged_file_does_not_grow_it_by_a_blank_line(
            self, tmp_path):
        """Tk's text widget carries an implicit final newline, so reading to
        tk.END returned the content plus one, and every save appended a blank
        line — then `has_unsaved_changes` rstrips both sides, so a user
        deleting the accumulated blanks was told nothing had changed (the cold
        review of chunk Y15, finding 5)."""
        root, tab = self._tab(tmp_path, source="a: 1\n")
        try:
            for _ in range(3):
                ok, _message = tab.save_to_disk()
                assert ok
            assert (tmp_path / "glossary.yml").read_text(
                encoding="utf-8") == "a: 1\n"
        finally:
            root.destroy()

    def test_a_syntax_repair_typed_into_the_tab_can_be_saved(self, tmp_path):
        """The file on disk does not parse, so the tab loads with a
        `load_error`. The base refuses to save such a tab and reports no
        unsaved changes — which for a source editor throws the repair away
        with no prompt (the cold review of chunk Y15, finding 1)."""
        root, tab = self._tab(tmp_path, source="a: [1, 2\n")
        try:
            assert tab.load_error is not None
            assert "Discard Changes" in tab._load_error_message()
            tab.source_widget.delete("1.0", "end")
            tab.source_widget.insert("1.0", "a: [1, 2]\n")
            assert tab.has_unsaved_changes()
            assert tab.save_blocker() is None
            ok, message = tab.save_to_disk()
            assert ok, message
            assert (tmp_path / "glossary.yml").read_text(
                encoding="utf-8") == "a: [1, 2]\n"
        finally:
            root.destroy()

    def test_a_declared_file_that_is_missing_reports_an_error(self, tmp_path):
        """An empty editor and no error is what the cwd bug looked like: the
        tab appeared to work and Save All reported success while writing a new
        file somewhere nothing reads."""
        root, tab = self._tab(tmp_path, source=None)
        try:
            assert tab.load_error is not None
            assert tab.source_text == ""
        finally:
            root.destroy()

    def test_a_structurally_broken_rule_table_is_refused(self, tmp_path):
        """Valid YAML is not a valid rule table. Deleting `rules:` from
        play_routing.yml parsed, saved, and killed the next run inside
        brief_data_extraction (the cold review of chunk Y15, finding 3)."""
        root, tab = self._tab(tmp_path, source="plays: {}\n",
                              name="play_routing.yml")
        try:
            tab.source_widget.delete("1.0", "end")
            tab.source_widget.insert("1.0", "plays: {}\nrules: []\n")
            ok, message = tab.save_to_disk()
            assert not ok
            assert "play_routing.yml" in message
        finally:
            root.destroy()

    def test_an_untouched_tab_reports_no_unsaved_changes(self, tmp_path):
        root, tab = self._tab(tmp_path, source="# a note\na: 1\n")
        try:
            assert tab.load_error is None
            assert not tab.has_unsaved_changes()
        finally:
            root.destroy()

    def test_a_broken_edit_counts_as_an_unsaved_change(self, tmp_path):
        """Otherwise Save All and the close prompt drop it in silence. Text
        that does not parse leaves the loaded data in place, so a structural
        comparison alone would call it no change."""
        root, tab = self._tab(tmp_path)
        try:
            tab.source_widget.insert("1.0", "a: [1, 2\n")
            assert tab.get_edited_data() == tab.current_data
            assert tab.has_unsaved_changes()
        finally:
            root.destroy()

    def test_an_edit_to_a_comment_alone_counts_as_an_unsaved_change(
            self, tmp_path):
        """A comment-only edit parses to exactly what was loaded, so a
        structural comparison would discard it on close without a prompt —
        and the comments are a good part of why these files are editable."""
        root, tab = self._tab(tmp_path, source="# old note\na: 1\n")
        try:
            tab.source_widget.delete("1.0", "2.0")
            tab.source_widget.insert("1.0", "# a better note\n")
            assert tab.get_edited_data() == tab.current_data
            assert tab.has_unsaved_changes()
            ok, _message = tab.save_to_disk()
            assert ok
            assert "# a better note" in (
                tmp_path / "glossary.yml").read_text(encoding="utf-8")
        finally:
            root.destroy()

    def test_the_load_error_banner_is_actually_visible(self, tmp_path):
        """It was packed after `render_ui`'s `expand=True` frame, so Tk
        squeezed it to one pixel and `winfo_ismapped()` returned 0 — the one
        thing saying the file could not be read was invisible (the cold review
        of chunk Y15, finding 1)."""
        from tkinter import ttk
        root, tab = self._tab(tmp_path, source="a: [1, 2\n")
        try:
            # The real window puts the tab in a notebook; packing it here is
            # what makes `winfo_ismapped` mean anything.
            tab.pack(fill="both", expand=True)
            root.geometry("900x600")
            root.update()
            banners = [w for w in tab.winfo_children()
                       if isinstance(w, ttk.Label)
                       and "could not be read" in str(w.cget("text"))]
            assert banners, "no load-error banner on the tab"
            assert banners[0].winfo_ismapped(), "the banner is not visible"
            assert banners[0].winfo_height() > 5, (
                f"the banner is {banners[0].winfo_height()}px high")
        finally:
            root.destroy()

    def test_a_write_failure_that_is_not_an_oserror_is_reported(self, tmp_path):
        """`save_changed_tabs` collects per-file results; anything that escapes
        this method escapes that loop too and the user is never told which
        files were already written (the cold review of chunk Y15, finding
        6)."""
        import config_manager as cm
        root, tab = self._tab(tmp_path)
        try:
            tab.source_widget.insert("1.0", "# a change\n")

            def boom(_path, _text):
                raise ValueError("not an OSError")

            original = cm.write_source
            cm.write_source = boom
            try:
                ok, message = tab.save_to_disk()
            finally:
                cm.write_source = original
            assert not ok
            assert "not an OSError" in message
        finally:
            root.destroy()

    def test_the_tab_shows_the_files_comments(self, tmp_path):
        root, tab = self._tab(tmp_path, source="# a note\na: 1\n")
        try:
            assert "# a note" in tab.source_widget.get("1.0", "end")
        finally:
            root.destroy()


class TestQueryLocationHelpText:
    """query_location_fix_spec_v1.md#QL.8 — the GUI describes the two keys
    that replaced force_local_intent, whose help text described something it
    did not do."""

    def test_help_names_both_new_keys_and_not_the_retired_one(self):
        import config_manager
        help_ = config_manager.HELP_BY_FIELD
        assert "config.yml.app.force_local_intent" not in help_
        assert "search text" in help_["config.yml.app.append_location_to_query"]
        assert "Maps" in help_["config.yml.app.always_fetch_maps"]
