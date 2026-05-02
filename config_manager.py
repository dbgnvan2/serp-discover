import os
import json
import yaml
import threading
from datetime import datetime
from abc import ABC, abstractmethod
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, scrolledtext, Text
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    # Provide dummy classes for testing without tkinter
    class tk:
        pass
    class ttk:
        class Frame:
            pass
    class messagebox:
        pass

from config_validators import (
    validate_intent_mapping,
    validate_strategic_patterns,
    validate_brief_pattern_routing,
    validate_intent_classifier_triggers,
    validate_config_yml,
    validate_domain_overrides,
    validate_classification_rules,
    validate_url_pattern_rules,
    validate_cross_file_constraints,
    VALID_INTENTS,
    VALID_CONTENT_TYPES,
    VALID_ENTITY_TYPES,
)


# Registry: file_path -> (validator_func, data_loader, data_dumper)
VALIDATORS_BY_FILE = {
    "intent_mapping.yml": validate_intent_mapping,
    "strategic_patterns.yml": validate_strategic_patterns,
    "brief_pattern_routing.yml": validate_brief_pattern_routing,
    "intent_classifier_triggers.yml": validate_intent_classifier_triggers,
    "config.yml": validate_config_yml,
    "domain_overrides.yml": validate_domain_overrides,
    "classification_rules.json": validate_classification_rules,
    "url_pattern_rules.yml": validate_url_pattern_rules,
}

# Help text registry
HELP_BY_FILE = {
    "intent_mapping.yml": (
        "Maps SERP characteristics to intent verdicts. Rules are evaluated top-to-bottom "
        "(first-match-wins); order matters. Edit rules here to refine intent classification."
    ),
    "strategic_patterns.yml": (
        "Bowen Family Systems patterns used for content brief generation. Each pattern includes "
        "triggers, status quo message, and reframe. Pattern names must match brief_pattern_routing.yml."
    ),
    "brief_pattern_routing.yml": (
        "Routes content briefs to specific patterns and keyword themes. Pattern names must exist "
        "in strategic_patterns.yml. Edit this to customize which patterns appear in briefs."
    ),
    "intent_classifier_triggers.yml": (
        "PAA External Locus and Systemic vocabulary lists. Used to classify PAA questions. "
        "Add trigger words to improve classification accuracy."
    ),
    "config.yml": (
        "Operational settings for SerpAPI, file paths, thresholds, and enrichment options. "
        "Edit these to customize tool behavior (API keys, output folders, etc.)."
    ),
    "domain_overrides.yml": (
        "Manual entity-type overrides for specific domains. When a domain is not auto-classified "
        "correctly, add it here to force a specific entity type."
    ),
    "classification_rules.json": (
        "Content types and entity types with their pattern definitions. Entity types used here "
        "must match those referenced in intent_mapping.yml and domain_overrides.yml."
    ),
    "url_pattern_rules.yml": (
        "URL pattern fallbacks for content classification. Used when other classification "
        "methods fail. Patterns are regex; they are evaluated top-to-bottom (first-match-wins)."
    ),
}

HELP_BY_FIELD = {
    "intent_mapping.rules[].intent": (
        "Primary intent category. Options:\n"
        "  - informational: User seeking information (how-to, definitions, research)\n"
        "  - commercial_investigation: Evaluating products/services before purchase\n"
        "  - transactional: Ready to buy/take action\n"
        "  - navigational: Looking for specific website/brand\n"
        "  - local: Geographic/local business search\n"
        "  - uncategorised: Unclassifiable by other rules"
    ),
    "intent_mapping.rules[].match.content_type": (
        "SERP content type to match. Must be one of: "
        + ", ".join(sorted(VALID_CONTENT_TYPES))
    ),
    "intent_mapping.rules[].match.entity_type": (
        "Entity type to match. Must be one of: "
        + ", ".join(sorted(VALID_ENTITY_TYPES)) + ", or 'any' (wildcard)"
    ),
    "strategic_patterns.yml[].Pattern_Name": (
        "Unique pattern identifier. Must match a pattern_name in brief_pattern_routing.yml exactly."
    ),
    "brief_pattern_routing.yml[].pattern_name": (
        "Must match a Pattern_Name from strategic_patterns.yml. Determines which PAA questions and keywords "
        "associate with each content brief."
    ),
    "domain_overrides.yml[].entity_type": (
        "Force a specific entity type for this domain. Must be one of: "
        + ", ".join(sorted(VALID_ENTITY_TYPES))
    ),
}


class BaseConfigTab(ttk.Frame):
    """Abstract base class for all configuration tabs."""

    def __init__(self, parent, file_name: str, file_type: str):
        """
        Args:
            parent: Parent widget
            file_name: Name of config file (e.g., 'intent_mapping.yml')
            file_type: 'yaml' or 'json'
        """
        super().__init__(parent)
        self.file_name = file_name
        self.file_type = file_type
        self.file_path = os.path.join(os.getcwd(), file_name)
        self.current_data = None
        self.edited_data = None
        self.load_current_data()
        self.render_ui()

    def load_current_data(self):
        """Load file from disk. Subclasses should override if custom loading needed."""
        if not os.path.exists(self.file_path):
            self.current_data = {} if self.file_type == "json" else {}
            return

        try:
            if self.file_type == "yaml":
                with open(self.file_path, "r") as f:
                    self.current_data = yaml.safe_load(f) or {}
            else:  # json
                with open(self.file_path, "r") as f:
                    self.current_data = json.load(f)
        except Exception as e:
            self.current_data = {} if self.file_type == "json" else {}
            print(f"Error loading {self.file_name}: {e}")

    def render_ui(self):
        """Render tab UI. Must be implemented by subclasses."""
        # Default: show placeholder
        placeholder = ttk.Label(
            self,
            text=f"Tab UI for {self.file_name}\n(Placeholder for Phase 1)",
            foreground="gray"
        )
        placeholder.pack(padx=20, pady=20)

    def get_edited_data(self):
        """Extract current form values into a data structure."""
        return self.current_data

    def validate(self):
        """Validate file-specific constraints. Return (is_valid, errors, warnings)."""
        validator = VALIDATORS_BY_FILE.get(self.file_name)
        if not validator:
            return (True, [], [])

        data = self.get_edited_data()
        is_valid, errors, warnings = validator(data)
        return (is_valid, errors, warnings)

    def revert_to_disk(self):
        """Reload from disk, discard unsaved changes."""
        self.load_current_data()
        self.render_ui()

    def save_to_disk(self):
        """Validate, then write to disk. Return (success, message)."""
        is_valid, errors, warnings = self.validate()

        if not is_valid:
            return (False, f"Validation failed for {self.file_name}:\n" + "\n".join(errors))

        try:
            data = self.get_edited_data()
            if self.file_type == "yaml":
                with open(self.file_path, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
            else:  # json
                with open(self.file_path, "w") as f:
                    json.dump(data, f, indent=2)

            self.current_data = data
            return (True, f"Saved {self.file_name}")
        except Exception as e:
            return (False, f"Failed to save {self.file_name}: {e}")

    def has_unsaved_changes(self):
        """Check if current data differs from disk version."""
        return self.get_edited_data() != self.current_data


class DomainOverridesTab(BaseConfigTab):
    """Tab for domain_overrides.yml with full CRUD operations."""

    def __init__(self, parent):
        super().__init__(parent, "domain_overrides.yml", "yaml")
        self.tree = None
        self.entity_type_var = None

    def render_ui(self):
        """Render domain overrides editor with treeview and buttons."""
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            frame,
            text="Domain Overrides Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("domain_overrides.yml", "")
        ttk.Label(frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Treeview with columns
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("domain", "entity_type")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
        self.tree.heading("domain", text="Domain")
        self.tree.heading("entity_type", text="Entity Type")
        self.tree.column("domain", width=300)
        self.tree.column("entity_type", width=200)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Load data into treeview
        self._load_treeview_data()

        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(button_frame, text="+ Add", command=self._add_row).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Delete", command=self._delete_row).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Edit", command=self._edit_row).pack(side="left")

    def _load_treeview_data(self):
        """Populate treeview with current data from domain_overrides.yml."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load from current_data (dict of domain -> entity_type)
        if isinstance(self.current_data, dict):
            for domain, entity_type in sorted(self.current_data.items()):
                self.tree.insert("", "end", values=(domain, entity_type))

    def _add_row(self):
        """Add a new domain override row."""
        if not TKINTER_AVAILABLE:
            return

        dialog = tk.Toplevel(self)
        dialog.title("Add Domain Override")
        dialog.geometry("400x150")
        dialog.transient(self.master)

        ttk.Label(dialog, text="Domain:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        domain_entry = ttk.Entry(dialog, width=30)
        domain_entry.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(dialog, text="Entity Type:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        entity_type_combo = ttk.Combobox(
            dialog, values=sorted(VALID_ENTITY_TYPES), width=27
        )
        entity_type_combo.grid(row=1, column=1, padx=10, pady=10)

        def save():
            domain = domain_entry.get().strip()
            entity_type = entity_type_combo.get().strip()

            if not domain or not entity_type:
                messagebox.showwarning("Incomplete", "Both domain and entity type required")
                return

            self.tree.insert("", "end", values=(domain, entity_type))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=2, column=1, padx=10, pady=10, sticky="e")

    def _delete_row(self):
        """Delete selected row."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a domain to delete")
            return

        for item in selected:
            self.tree.delete(item)

    def _edit_row(self):
        """Edit selected row."""
        if not TKINTER_AVAILABLE:
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a domain to edit")
            return

        item = selected[0]
        domain, entity_type = self.tree.item(item)["values"]

        dialog = tk.Toplevel(self)
        dialog.title(f"Edit: {domain}")
        dialog.geometry("400x150")
        dialog.transient(self.master)

        ttk.Label(dialog, text="Domain:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        domain_entry = ttk.Entry(dialog, width=30)
        domain_entry.insert(0, domain)
        domain_entry.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(dialog, text="Entity Type:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        entity_type_combo = ttk.Combobox(
            dialog, values=sorted(VALID_ENTITY_TYPES), width=27
        )
        entity_type_combo.set(entity_type)
        entity_type_combo.grid(row=1, column=1, padx=10, pady=10)

        def save():
            new_domain = domain_entry.get().strip()
            new_entity_type = entity_type_combo.get().strip()

            if not new_domain or not new_entity_type:
                messagebox.showwarning("Incomplete", "Both domain and entity type required")
                return

            self.tree.item(item, values=(new_domain, new_entity_type))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=2, column=1, padx=10, pady=10, sticky="e")

    def get_edited_data(self):
        """Extract treeview data back into dict format."""
        data = {}
        for item in self.tree.get_children():
            domain, entity_type = self.tree.item(item)["values"]
            data[domain] = entity_type
        return data


class ClassificationRulesTab(BaseConfigTab):
    """Tab for classification_rules.json with entity types and descriptions management."""

    def __init__(self, parent):
        super().__init__(parent, "classification_rules.json", "json")
        self.entity_types_tree = None
        self.descriptions_tree = None

    def render_ui(self):
        """Render classification rules editor with two sections: entity types and descriptions."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            main_frame,
            text="Classification Rules Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("classification_rules.json", "")
        ttk.Label(main_frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 15))

        # Section 1: Entity Types
        entity_frame = ttk.LabelFrame(main_frame, text="Valid Entity Types", padding=10)
        entity_frame.pack(fill="both", expand=True, pady=(0, 15))

        ttk.Label(entity_frame, text="List of valid entity type values:", foreground="gray").pack(anchor="w", pady=(0, 5))

        tree_frame = ttk.Frame(entity_frame)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.entity_types_tree = ttk.Treeview(tree_frame, columns=("type",), show="headings", height=6)
        self.entity_types_tree.heading("type", text="Entity Type")
        self.entity_types_tree.column("type", width=300)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.entity_types_tree.yview)
        self.entity_types_tree.configure(yscroll=scrollbar.set)
        self.entity_types_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Load entity types
        self._load_entity_types()

        # Entity types buttons
        entity_btn_frame = ttk.Frame(entity_frame)
        entity_btn_frame.pack(fill="x")

        ttk.Button(entity_btn_frame, text="+ Add Type", command=self._add_entity_type).pack(side="left", padx=(0, 5))
        ttk.Button(entity_btn_frame, text="Delete Type", command=self._delete_entity_type).pack(side="left")

        # Section 2: Entity Type Descriptions
        desc_frame = ttk.LabelFrame(main_frame, text="Entity Type Descriptions", padding=10)
        desc_frame.pack(fill="both", expand=True)

        ttk.Label(desc_frame, text="Descriptions for each entity type:", foreground="gray").pack(anchor="w", pady=(0, 5))

        tree_frame2 = ttk.Frame(desc_frame)
        tree_frame2.pack(fill="both", expand=True, pady=(0, 10))

        self.descriptions_tree = ttk.Treeview(tree_frame2, columns=("type", "description"), show="headings", height=6)
        self.descriptions_tree.heading("type", text="Entity Type")
        self.descriptions_tree.heading("description", text="Description")
        self.descriptions_tree.column("type", width=200)
        self.descriptions_tree.column("description", width=400)

        scrollbar2 = ttk.Scrollbar(tree_frame2, orient="vertical", command=self.descriptions_tree.yview)
        self.descriptions_tree.configure(yscroll=scrollbar2.set)
        self.descriptions_tree.pack(side="left", fill="both", expand=True)
        scrollbar2.pack(side="right", fill="y")

        # Load descriptions
        self._load_descriptions()

        # Description buttons
        desc_btn_frame = ttk.Frame(desc_frame)
        desc_btn_frame.pack(fill="x")

        ttk.Button(desc_btn_frame, text="+ Add", command=self._add_description).pack(side="left", padx=(0, 5))
        ttk.Button(desc_btn_frame, text="Edit", command=self._edit_description).pack(side="left", padx=(0, 5))
        ttk.Button(desc_btn_frame, text="Delete", command=self._delete_description).pack(side="left")

    def _load_entity_types(self):
        """Populate entity types treeview with current data."""
        # Clear existing
        for item in self.entity_types_tree.get_children():
            self.entity_types_tree.delete(item)

        # Load from current_data
        if isinstance(self.current_data, dict) and "entity_types" in self.current_data:
            for entity_type in sorted(self.current_data["entity_types"]):
                self.entity_types_tree.insert("", "end", values=(entity_type,))

    def _load_descriptions(self):
        """Populate descriptions treeview with current data."""
        # Clear existing
        for item in self.descriptions_tree.get_children():
            self.descriptions_tree.delete(item)

        # Load from current_data
        if isinstance(self.current_data, dict) and "entity_type_descriptions" in self.current_data:
            descriptions = self.current_data["entity_type_descriptions"]
            for entity_type in sorted(descriptions.keys()):
                description = descriptions[entity_type]
                self.descriptions_tree.insert("", "end", values=(entity_type, description))

    def _add_entity_type(self):
        """Add a new entity type."""
        if not TKINTER_AVAILABLE:
            return

        dialog = tk.Toplevel(self)
        dialog.title("Add Entity Type")
        dialog.geometry("350x120")
        dialog.transient(self.master)

        ttk.Label(dialog, text="Entity Type:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        type_entry = ttk.Entry(dialog, width=25)
        type_entry.grid(row=0, column=1, padx=10, pady=10)

        def save():
            entity_type = type_entry.get().strip()

            if not entity_type:
                messagebox.showwarning("Incomplete", "Entity type name required")
                return

            self.entity_types_tree.insert("", "end", values=(entity_type,))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=1, column=1, padx=10, pady=10, sticky="e")

    def _delete_entity_type(self):
        """Delete selected entity type."""
        selected = self.entity_types_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select an entity type to delete")
            return

        for item in selected:
            self.entity_types_tree.delete(item)

    def _add_description(self):
        """Add a new entity type description."""
        if not TKINTER_AVAILABLE:
            return

        dialog = tk.Toplevel(self)
        dialog.title("Add Description")
        dialog.geometry("450x180")
        dialog.transient(self.master)

        ttk.Label(dialog, text="Entity Type:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        type_combo = ttk.Combobox(dialog, width=25)
        type_combo.grid(row=0, column=1, padx=10, pady=10)

        # Populate with current entity types
        entity_types = [self.entity_types_tree.item(i)["values"][0] for i in self.entity_types_tree.get_children()]
        type_combo["values"] = sorted(entity_types)

        ttk.Label(dialog, text="Description:").grid(row=1, column=0, padx=10, pady=10, sticky="nw")
        desc_text = Text(dialog, width=30, height=4)
        desc_text.grid(row=1, column=1, padx=10, pady=10)

        def save():
            entity_type = type_combo.get().strip()
            description = desc_text.get("1.0", "end").strip()

            if not entity_type or not description:
                messagebox.showwarning("Incomplete", "Both entity type and description required")
                return

            self.descriptions_tree.insert("", "end", values=(entity_type, description))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=2, column=1, padx=10, pady=10, sticky="e")

    def _edit_description(self):
        """Edit selected description."""
        if not TKINTER_AVAILABLE:
            return

        selected = self.descriptions_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a description to edit")
            return

        item = selected[0]
        entity_type, description = self.descriptions_tree.item(item)["values"]

        dialog = tk.Toplevel(self)
        dialog.title(f"Edit: {entity_type}")
        dialog.geometry("450x180")
        dialog.transient(self.master)

        ttk.Label(dialog, text="Entity Type:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        type_combo = ttk.Combobox(dialog, width=25)
        type_combo.grid(row=0, column=1, padx=10, pady=10)

        # Populate with current entity types
        entity_types = [self.entity_types_tree.item(i)["values"][0] for i in self.entity_types_tree.get_children()]
        type_combo["values"] = sorted(entity_types)
        type_combo.set(entity_type)

        ttk.Label(dialog, text="Description:").grid(row=1, column=0, padx=10, pady=10, sticky="nw")
        desc_text = Text(dialog, width=30, height=4)
        desc_text.insert("1.0", description)
        desc_text.grid(row=1, column=1, padx=10, pady=10)

        def save():
            new_entity_type = type_combo.get().strip()
            new_description = desc_text.get("1.0", "end").strip()

            if not new_entity_type or not new_description:
                messagebox.showwarning("Incomplete", "Both entity type and description required")
                return

            self.descriptions_tree.item(item, values=(new_entity_type, new_description))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=2, column=1, padx=10, pady=10, sticky="e")

    def _delete_description(self):
        """Delete selected description."""
        selected = self.descriptions_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a description to delete")
            return

        for item in selected:
            self.descriptions_tree.delete(item)

    def get_edited_data(self):
        """Extract treeview data back into dict format matching classification_rules.json schema."""
        data = self.current_data.copy() if isinstance(self.current_data, dict) else {}

        # Extract entity types
        entity_types = []
        for item in self.entity_types_tree.get_children():
            entity_types.append(self.entity_types_tree.item(item)["values"][0])
        data["entity_types"] = sorted(entity_types)

        # Extract descriptions
        descriptions = {}
        for item in self.descriptions_tree.get_children():
            entity_type, description = self.descriptions_tree.item(item)["values"]
            descriptions[entity_type] = description
        data["entity_type_descriptions"] = descriptions

        return data


class IntentMappingTab(BaseConfigTab):
    """Tab for intent_mapping.yml with CRUD and reordering support."""

    def __init__(self, parent):
        super().__init__(parent, "intent_mapping.yml", "yaml")
        self.tree = None

    def render_ui(self):
        """Render intent mapping editor with treeview and CRUD buttons."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            main_frame,
            text="Intent Mapping Configuration (Rules are evaluated top-to-bottom)",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("intent_mapping.yml", "")
        ttk.Label(main_frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Treeview with columns
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("content_type", "entity_type", "local_pack", "intent")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
        self.tree.heading("content_type", text="Content Type")
        self.tree.heading("entity_type", text="Entity Type")
        self.tree.heading("local_pack", text="Local Pack")
        self.tree.heading("intent", text="Intent")
        self.tree.column("content_type", width=120)
        self.tree.column("entity_type", width=120)
        self.tree.column("local_pack", width=100)
        self.tree.column("intent", width=150)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Load data into treeview
        self._load_treeview_data()

        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(button_frame, text="+ Add", command=self._add_rule).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Edit", command=self._edit_rule).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Delete", command=self._delete_rule).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="↑ Up", command=self._move_up).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="↓ Down", command=self._move_down).pack(side="left")

    def _load_treeview_data(self):
        """Populate treeview with rules from intent_mapping.yml."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load from current_data
        if isinstance(self.current_data, dict) and "rules" in self.current_data:
            for rule in self.current_data["rules"]:
                if isinstance(rule, dict) and "match" in rule:
                    match = rule["match"]
                    content_type = match.get("content_type", "")
                    entity_type = match.get("entity_type", "")
                    local_pack = match.get("local_pack", "")
                    intent = rule.get("intent", "")
                    self.tree.insert("", "end", values=(content_type, entity_type, local_pack, intent))

    def _add_rule(self):
        """Add a new intent mapping rule."""
        if not TKINTER_AVAILABLE:
            return

        dialog = tk.Toplevel(self)
        dialog.title("Add Intent Mapping Rule")
        dialog.geometry("500x300")
        dialog.transient(self.master)

        # Content Type
        ttk.Label(dialog, text="Content Type:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ct_combo = ttk.Combobox(dialog, values=sorted(VALID_CONTENT_TYPES) + ["any"], width=25)
        ct_combo.grid(row=0, column=1, padx=10, pady=10)

        # Entity Type
        ttk.Label(dialog, text="Entity Type:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        et_combo = ttk.Combobox(dialog, values=sorted(VALID_ENTITY_TYPES) + ["any"], width=25)
        et_combo.grid(row=1, column=1, padx=10, pady=10)

        # Local Pack
        ttk.Label(dialog, text="Local Pack:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        lp_combo = ttk.Combobox(dialog, values=["yes", "no", "any"], width=25)
        lp_combo.grid(row=2, column=1, padx=10, pady=10)

        # Intent
        ttk.Label(dialog, text="Intent:").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        intent_combo = ttk.Combobox(dialog, values=sorted(VALID_INTENTS), width=25)
        intent_combo.grid(row=3, column=1, padx=10, pady=10)

        # Domain Role (optional)
        ttk.Label(dialog, text="Domain Role:").grid(row=4, column=0, padx=10, pady=10, sticky="w")
        dr_combo = ttk.Combobox(dialog, values=["client", "known_competitor", "other", "any"], width=25)
        dr_combo.set("other")
        dr_combo.grid(row=4, column=1, padx=10, pady=10)

        def save():
            if not all([ct_combo.get(), et_combo.get(), lp_combo.get(), intent_combo.get(), dr_combo.get()]):
                messagebox.showwarning("Incomplete", "All fields required")
                return

            self.tree.insert("", "end", values=(
                ct_combo.get(),
                et_combo.get(),
                lp_combo.get(),
                intent_combo.get()
            ))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=5, column=1, padx=10, pady=10, sticky="e")

    def _edit_rule(self):
        """Edit selected rule."""
        if not TKINTER_AVAILABLE:
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a rule to edit")
            return

        item = selected[0]
        content_type, entity_type, local_pack, intent = self.tree.item(item)["values"]

        dialog = tk.Toplevel(self)
        dialog.title(f"Edit Rule: {intent}")
        dialog.geometry("500x300")
        dialog.transient(self.master)

        # Content Type
        ttk.Label(dialog, text="Content Type:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ct_combo = ttk.Combobox(dialog, values=sorted(VALID_CONTENT_TYPES) + ["any"], width=25)
        ct_combo.set(content_type)
        ct_combo.grid(row=0, column=1, padx=10, pady=10)

        # Entity Type
        ttk.Label(dialog, text="Entity Type:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        et_combo = ttk.Combobox(dialog, values=sorted(VALID_ENTITY_TYPES) + ["any"], width=25)
        et_combo.set(entity_type)
        et_combo.grid(row=1, column=1, padx=10, pady=10)

        # Local Pack
        ttk.Label(dialog, text="Local Pack:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        lp_combo = ttk.Combobox(dialog, values=["yes", "no", "any"], width=25)
        lp_combo.set(local_pack)
        lp_combo.grid(row=2, column=1, padx=10, pady=10)

        # Intent
        ttk.Label(dialog, text="Intent:").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        intent_combo = ttk.Combobox(dialog, values=sorted(VALID_INTENTS), width=25)
        intent_combo.set(intent)
        intent_combo.grid(row=3, column=1, padx=10, pady=10)

        # Domain Role
        ttk.Label(dialog, text="Domain Role:").grid(row=4, column=0, padx=10, pady=10, sticky="w")
        dr_combo = ttk.Combobox(dialog, values=["client", "known_competitor", "other", "any"], width=25)
        dr_combo.set("other")
        dr_combo.grid(row=4, column=1, padx=10, pady=10)

        def save():
            if not all([ct_combo.get(), et_combo.get(), lp_combo.get(), intent_combo.get(), dr_combo.get()]):
                messagebox.showwarning("Incomplete", "All fields required")
                return

            self.tree.item(item, values=(
                ct_combo.get(),
                et_combo.get(),
                lp_combo.get(),
                intent_combo.get()
            ))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=5, column=1, padx=10, pady=10, sticky="e")

    def _delete_rule(self):
        """Delete selected rule."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a rule to delete")
            return

        for item in selected:
            self.tree.delete(item)

    def _move_up(self):
        """Move selected rule up in priority (earlier in list)."""
        selected = self.tree.selection()
        if not selected or len(selected) != 1:
            messagebox.showwarning("Single Selection", "Select exactly one rule to move")
            return

        item = selected[0]
        index = self.tree.index(item)

        if index == 0:
            messagebox.showinfo("Already at Top", "This rule is already at the top priority")
            return

        values = self.tree.item(item)["values"]
        self.tree.delete(item)
        self.tree.insert("", index - 1, values=values)

    def _move_down(self):
        """Move selected rule down in priority (later in list)."""
        selected = self.tree.selection()
        if not selected or len(selected) != 1:
            messagebox.showwarning("Single Selection", "Select exactly one rule to move")
            return

        item = selected[0]
        index = self.tree.index(item)
        items = self.tree.get_children()

        if index >= len(items) - 1:
            messagebox.showinfo("Already at Bottom", "This rule is already at the lowest priority")
            return

        values = self.tree.item(item)["values"]
        self.tree.delete(item)
        self.tree.insert("", index + 1, values=values)

    def get_edited_data(self):
        """Extract treeview data back into intent_mapping.yml format."""
        data = {"version": self.current_data.get("version", 1) if isinstance(self.current_data, dict) else 1}

        rules = []
        for item in self.tree.get_children():
            content_type, entity_type, local_pack, intent = self.tree.item(item)["values"]
            rule = {
                "match": {
                    "content_type": content_type,
                    "entity_type": entity_type,
                    "local_pack": local_pack,
                    "domain_role": "other"  # Default domain_role
                },
                "intent": intent
            }
            rules.append(rule)

        data["rules"] = rules
        return data


class StrategicPatternsTab(BaseConfigTab):
    """Tab for strategic_patterns.yml with pattern editing support."""

    def __init__(self, parent):
        super().__init__(parent, "strategic_patterns.yml", "yaml")
        self.tree = None

    def render_ui(self):
        """Render strategic patterns editor with treeview and CRUD buttons."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            main_frame,
            text="Strategic Patterns Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("strategic_patterns.yml", "")
        ttk.Label(main_frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Treeview with columns
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("pattern_name", "triggers_count", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
        self.tree.heading("pattern_name", text="Pattern Name")
        self.tree.heading("triggers_count", text="Triggers")
        self.tree.heading("status", text="Status")
        self.tree.column("pattern_name", width=200)
        self.tree.column("triggers_count", width=100)
        self.tree.column("status", width=200)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind double-click for editing
        self.tree.bind("<Double-1>", lambda e: self._edit_pattern())

        # Load data into treeview
        self._load_treeview_data()

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")

        ttk.Button(button_frame, text="+ Add Pattern", command=self._add_pattern).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Edit", command=self._edit_pattern).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Delete", command=self._delete_pattern).pack(side="left")

    def _load_treeview_data(self):
        """Populate treeview with patterns from strategic_patterns.yml."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load from current_data
        if isinstance(self.current_data, list):
            for pattern in self.current_data:
                if isinstance(pattern, dict):
                    pattern_name = pattern.get("Pattern_Name", "")
                    triggers = pattern.get("Triggers", [])
                    triggers_count = len(triggers) if isinstance(triggers, list) else 0

                    # Status: check if required fields are present
                    required_fields = ["Status_Quo_Message", "Bowen_Bridge_Reframe", "Content_Angle"]
                    missing = [f for f in required_fields if f not in pattern or not pattern[f]]
                    status = "✓ Complete" if not missing else f"✗ Missing: {', '.join(missing)}"

                    self.tree.insert("", "end", values=(pattern_name, triggers_count, status))

    def _add_pattern(self):
        """Add a new strategic pattern."""
        if not TKINTER_AVAILABLE:
            return

        self._edit_pattern(is_new=True)

    def _edit_pattern(self, is_new=False):
        """Edit or create a strategic pattern."""
        if not TKINTER_AVAILABLE:
            return

        if not is_new:
            selected = self.tree.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a pattern to edit")
                return
            item = selected[0]
            pattern_name = self.tree.item(item)["values"][0]

            # Find the original pattern data
            pattern_data = None
            for p in self.current_data:
                if p.get("Pattern_Name") == pattern_name:
                    pattern_data = p.copy()
                    break
            if not pattern_data:
                messagebox.showerror("Error", "Pattern not found")
                return
        else:
            pattern_data = {
                "Pattern_Name": "",
                "Triggers": [],
                "Status_Quo_Message": "",
                "Bowen_Bridge_Reframe": "",
                "Content_Angle": ""
            }
            item = None

        dialog = tk.Toplevel(self)
        dialog.title("Edit Pattern" if not is_new else "Add Pattern")
        dialog.geometry("600x500")
        dialog.transient(self.master)

        # Pattern Name
        ttk.Label(dialog, text="Pattern Name:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.insert(0, pattern_data.get("Pattern_Name", ""))
        name_entry.grid(row=0, column=1, padx=10, pady=10)

        # Triggers (multiline)
        ttk.Label(dialog, text="Triggers (one per line):", justify="left").grid(row=1, column=0, padx=10, pady=10, sticky="nw")
        triggers_text = Text(dialog, width=40, height=4)
        triggers_list = pattern_data.get("Triggers", [])
        if isinstance(triggers_list, list):
            triggers_text.insert("1.0", "\n".join(triggers_list))
        triggers_text.grid(row=1, column=1, padx=10, pady=10)

        # Status Quo Message
        ttk.Label(dialog, text="Status Quo Message:", justify="left").grid(row=2, column=0, padx=10, pady=10, sticky="nw")
        sqm_text = Text(dialog, width=40, height=3)
        sqm_text.insert("1.0", pattern_data.get("Status_Quo_Message", ""))
        sqm_text.grid(row=2, column=1, padx=10, pady=10)

        # Bowen Bridge Reframe
        ttk.Label(dialog, text="Bowen Bridge Reframe:", justify="left").grid(row=3, column=0, padx=10, pady=10, sticky="nw")
        bbr_text = Text(dialog, width=40, height=3)
        bbr_text.insert("1.0", pattern_data.get("Bowen_Bridge_Reframe", ""))
        bbr_text.grid(row=3, column=1, padx=10, pady=10)

        # Content Angle
        ttk.Label(dialog, text="Content Angle:", justify="left").grid(row=4, column=0, padx=10, pady=10, sticky="nw")
        ca_text = Text(dialog, width=40, height=3)
        ca_text.insert("1.0", pattern_data.get("Content_Angle", ""))
        ca_text.grid(row=4, column=1, padx=10, pady=10)

        def save():
            pattern_name = name_entry.get().strip()
            triggers_str = triggers_text.get("1.0", "end").strip()
            triggers = [t.strip() for t in triggers_str.split("\n") if t.strip()]
            status_quo = sqm_text.get("1.0", "end").strip()
            reframe = bbr_text.get("1.0", "end").strip()
            content_angle = ca_text.get("1.0", "end").strip()

            # Validation
            if not all([pattern_name, triggers, status_quo, reframe, content_angle]):
                messagebox.showwarning("Incomplete", "All fields required")
                return

            # Check trigger min length
            bad_triggers = [t for t in triggers if len(t) < 4]
            if bad_triggers:
                messagebox.showwarning("Validation", f"Triggers must be 4+ chars: {', '.join(bad_triggers)}")
                return

            triggers_count = len(triggers)

            # Update or insert
            if item:
                self.tree.item(item, values=(pattern_name, triggers_count, "✓ Complete"))
            else:
                self.tree.insert("", "end", values=(pattern_name, triggers_count, "✓ Complete"))

            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=5, column=1, padx=10, pady=10, sticky="e")

    def _delete_pattern(self):
        """Delete selected pattern."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a pattern to delete")
            return

        for item in selected:
            self.tree.delete(item)

    def get_edited_data(self):
        """Extract treeview data back into strategic_patterns.yml format."""
        patterns = []

        # Reconstruct from treeview
        for item in self.tree.get_children():
            pattern_name, triggers_count, status = self.tree.item(item)["values"]

            # Try to find original pattern to preserve full data
            original_pattern = None
            if isinstance(self.current_data, list):
                for p in self.current_data:
                    if p.get("Pattern_Name") == pattern_name:
                        original_pattern = p.copy()
                        break

            if original_pattern:
                # Preserve all fields from original
                patterns.append(original_pattern)
            else:
                # Create minimal pattern (should not happen in normal flow)
                pattern = {
                    "Pattern_Name": pattern_name,
                    "Triggers": [],
                    "Status_Quo_Message": "",
                    "Bowen_Bridge_Reframe": "",
                    "Content_Angle": ""
                }
                patterns.append(pattern)

        return patterns


class BriefPatternRoutingTab(BaseConfigTab):
    """Tab for brief_pattern_routing.yml with pattern routing management."""

    def __init__(self, parent):
        super().__init__(parent, "brief_pattern_routing.yml", "yaml")
        self.tree = None
        self.intent_descriptions = {}

    def render_ui(self):
        """Render brief pattern routing editor with patterns and intent descriptions."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            main_frame,
            text="Brief Pattern Routing Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("brief_pattern_routing.yml", "")
        ttk.Label(main_frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Intent Slot Descriptions section
        desc_frame = ttk.LabelFrame(main_frame, text="Intent Slot Descriptions", padding=10)
        desc_frame.pack(fill="x", pady=(0, 15))

        ttk.Label(desc_frame, text="How intent buckets appear in the brief:", foreground="gray").pack(anchor="w", pady=(0, 5))

        # Load intent descriptions
        self.intent_descriptions = self.current_data.get("intent_slot_descriptions", {}) if isinstance(self.current_data, dict) else {}

        desc_text_frame = ttk.Frame(desc_frame)
        desc_text_frame.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Label(desc_text_frame, text="Intent → Description (one per line, format: intent: description):", foreground="gray").pack(anchor="w")
        self.desc_text = Text(desc_text_frame, width=60, height=6)
        self._load_intent_descriptions()
        self.desc_text.pack(fill="both", expand=True)

        # Pattern routing section
        pattern_frame = ttk.LabelFrame(main_frame, text="Pattern Routing", padding=10)
        pattern_frame.pack(fill="both", expand=True)

        ttk.Label(pattern_frame, text="Pattern-to-PAA routing rules:", foreground="gray").pack(anchor="w", pady=(0, 5))

        # Treeview with columns
        tree_frame = ttk.Frame(pattern_frame)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("pattern_name", "themes_count", "categories_count", "keywords_count")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
        self.tree.heading("pattern_name", text="Pattern Name")
        self.tree.heading("themes_count", text="Themes")
        self.tree.heading("categories_count", text="Categories")
        self.tree.heading("keywords_count", text="Keywords")
        self.tree.column("pattern_name", width=200)
        self.tree.column("themes_count", width=80)
        self.tree.column("categories_count", width=100)
        self.tree.column("keywords_count", width=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind double-click for editing
        self.tree.bind("<Double-1>", lambda e: self._edit_pattern())

        # Load data into treeview
        self._load_treeview_data()

        # Buttons
        button_frame = ttk.Frame(pattern_frame)
        button_frame.pack(fill="x")

        ttk.Button(button_frame, text="+ Add Pattern", command=self._add_pattern).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Edit", command=self._edit_pattern).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Delete", command=self._delete_pattern).pack(side="left")

    def _load_intent_descriptions(self):
        """Load intent descriptions into text widget."""
        self.desc_text.delete("1.0", "end")
        for intent in sorted(self.intent_descriptions.keys()):
            self.desc_text.insert("end", f"{intent}: {self.intent_descriptions[intent]}\n")

    def _load_treeview_data(self):
        """Populate treeview with patterns from brief_pattern_routing.yml."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load from current_data
        if isinstance(self.current_data, dict) and "patterns" in self.current_data:
            for pattern in self.current_data["patterns"]:
                if isinstance(pattern, dict):
                    pattern_name = pattern.get("pattern_name", "")
                    themes = len(pattern.get("paa_themes", []))
                    categories = len(pattern.get("paa_categories", []))
                    keywords = len(pattern.get("keyword_hints", []))

                    self.tree.insert("", "end", values=(pattern_name, themes, categories, keywords))

    def _add_pattern(self):
        """Add a new pattern."""
        if not TKINTER_AVAILABLE:
            return

        self._edit_pattern(is_new=True)

    def _edit_pattern(self, is_new=False):
        """Edit or create a pattern routing rule."""
        if not TKINTER_AVAILABLE:
            return

        if not is_new:
            selected = self.tree.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a pattern to edit")
                return
            item = selected[0]
            pattern_name = self.tree.item(item)["values"][0]

            # Find the original pattern data
            pattern_data = None
            for p in self.current_data.get("patterns", []):
                if p.get("pattern_name") == pattern_name:
                    pattern_data = p.copy()
                    break
            if not pattern_data:
                messagebox.showerror("Error", "Pattern not found")
                return
        else:
            pattern_data = {
                "pattern_name": "",
                "paa_themes": [],
                "paa_categories": [],
                "keyword_hints": []
            }
            item = None

        dialog = tk.Toplevel(self)
        dialog.title("Edit Pattern" if not is_new else "Add Pattern")
        dialog.geometry("600x500")
        dialog.transient(self.master)

        # Pattern Name
        ttk.Label(dialog, text="Pattern Name:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.insert(0, pattern_data.get("pattern_name", ""))
        name_entry.grid(row=0, column=1, padx=10, pady=10)

        # PAA Themes
        ttk.Label(dialog, text="PAA Themes (one per line):", justify="left").grid(row=1, column=0, padx=10, pady=10, sticky="nw")
        themes_text = Text(dialog, width=40, height=4)
        themes = pattern_data.get("paa_themes", [])
        if isinstance(themes, list):
            themes_text.insert("1.0", "\n".join(themes))
        themes_text.grid(row=1, column=1, padx=10, pady=10)

        # PAA Categories
        ttk.Label(dialog, text="PAA Categories (one per line):", justify="left").grid(row=2, column=0, padx=10, pady=10, sticky="nw")
        categories_text = Text(dialog, width=40, height=3)
        categories = pattern_data.get("paa_categories", [])
        if isinstance(categories, list):
            categories_text.insert("1.0", "\n".join(categories))
        categories_text.grid(row=2, column=1, padx=10, pady=10)

        # Keyword Hints
        ttk.Label(dialog, text="Keyword Hints (one per line):", justify="left").grid(row=3, column=0, padx=10, pady=10, sticky="nw")
        keywords_text = Text(dialog, width=40, height=3)
        keywords = pattern_data.get("keyword_hints", [])
        if isinstance(keywords, list):
            keywords_text.insert("1.0", "\n".join(keywords))
        keywords_text.grid(row=3, column=1, padx=10, pady=10)

        def save():
            pattern_name = name_entry.get().strip()
            themes_str = themes_text.get("1.0", "end").strip()
            themes_list = [t.strip() for t in themes_str.split("\n") if t.strip()]
            categories_str = categories_text.get("1.0", "end").strip()
            categories_list = [c.strip() for c in categories_str.split("\n") if c.strip()]
            keywords_str = keywords_text.get("1.0", "end").strip()
            keywords_list = [k.strip() for k in keywords_str.split("\n") if k.strip()]

            # Validation
            if not all([pattern_name, themes_list, categories_list, keywords_list]):
                messagebox.showwarning("Incomplete", "All fields required (themes, categories, keywords)")
                return

            # Update or insert
            if item:
                self.tree.item(item, values=(pattern_name, len(themes_list), len(categories_list), len(keywords_list)))
            else:
                self.tree.insert("", "end", values=(pattern_name, len(themes_list), len(categories_list), len(keywords_list)))

            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=1, padx=10, pady=10, sticky="e")

    def _delete_pattern(self):
        """Delete selected pattern."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a pattern to delete")
            return

        for item in selected:
            self.tree.delete(item)

    def get_edited_data(self):
        """Extract treeview data back into brief_pattern_routing.yml format."""
        data = {"version": self.current_data.get("version", 1) if isinstance(self.current_data, dict) else 1}

        # Parse intent descriptions from text widget
        intent_descriptions = {}
        desc_lines = self.desc_text.get("1.0", "end").strip().split("\n")
        for line in desc_lines:
            if ":" in line:
                intent, desc = line.split(":", 1)
                intent_descriptions[intent.strip()] = desc.strip()

        data["intent_slot_descriptions"] = intent_descriptions

        # Reconstruct patterns from treeview
        patterns = []
        for item in self.tree.get_children():
            pattern_name, themes_count, categories_count, keywords_count = self.tree.item(item)["values"]

            # Try to find original pattern to preserve full data
            original_pattern = None
            if isinstance(self.current_data, dict):
                for p in self.current_data.get("patterns", []):
                    if p.get("pattern_name") == pattern_name:
                        original_pattern = p.copy()
                        break

            if original_pattern:
                patterns.append(original_pattern)
            else:
                # Create minimal pattern (should not happen in normal flow)
                pattern = {
                    "pattern_name": pattern_name,
                    "paa_themes": [],
                    "paa_categories": [],
                    "keyword_hints": []
                }
                patterns.append(pattern)

        data["patterns"] = patterns
        return data


class IntentClassifierTriggersTab(BaseConfigTab):
    """Tab for intent_classifier_triggers.yml with medical and systemic trigger management."""

    def __init__(self, parent):
        super().__init__(parent, "intent_classifier_triggers.yml", "yaml")
        self.medical_mw_text = None
        self.medical_sw_text = None
        self.systemic_mw_text = None
        self.systemic_sw_text = None

    def render_ui(self):
        """Render intent classifier triggers editor with two sections: medical and systemic."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        ttk.Label(
            main_frame,
            text="Intent Classifier Triggers Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))

        help_text = HELP_BY_FILE.get("intent_classifier_triggers.yml", "")
        ttk.Label(main_frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Medical Triggers Section
        medical_frame = ttk.LabelFrame(main_frame, text="Medical Triggers", padding=10)
        medical_frame.pack(fill="both", expand=True, pady=(0, 15))

        # Medical Multi-word
        ttk.Label(medical_frame, text="Multi-word triggers (one per line):", foreground="gray").pack(anchor="w", pady=(0, 5))
        self.medical_mw_text = Text(medical_frame, width=60, height=5)
        self.medical_mw_text.pack(fill="both", expand=True, pady=(0, 10))

        # Medical Single-word
        ttk.Label(medical_frame, text="Single-word triggers (one per line, min 3 chars):", foreground="gray").pack(anchor="w", pady=(0, 5))
        self.medical_sw_text = Text(medical_frame, width=60, height=6)
        self.medical_sw_text.pack(fill="both")

        # Systemic Triggers Section
        systemic_frame = ttk.LabelFrame(main_frame, text="Systemic Triggers", padding=10)
        systemic_frame.pack(fill="both", expand=True)

        # Systemic Multi-word
        ttk.Label(systemic_frame, text="Multi-word triggers (one per line):", foreground="gray").pack(anchor="w", pady=(0, 5))
        self.systemic_mw_text = Text(systemic_frame, width=60, height=5)
        self.systemic_mw_text.pack(fill="both", expand=True, pady=(0, 10))

        # Systemic Single-word
        ttk.Label(systemic_frame, text="Single-word triggers (one per line, min 3 chars):", foreground="gray").pack(anchor="w", pady=(0, 5))
        self.systemic_sw_text = Text(systemic_frame, width=60, height=6)
        self.systemic_sw_text.pack(fill="both")

        # Load data
        self._load_data()

    def _load_data(self):
        """Load triggers from intent_classifier_triggers.yml into text widgets."""
        if isinstance(self.current_data, dict):
            # Medical triggers
            medical = self.current_data.get("medical_triggers", {})
            if isinstance(medical, dict):
                mw = medical.get("multi_word", [])
                if isinstance(mw, list):
                    self.medical_mw_text.insert("1.0", "\n".join(mw))

                sw = medical.get("single_word", [])
                if isinstance(sw, list):
                    self.medical_sw_text.insert("1.0", "\n".join(sw))

            # Systemic triggers
            systemic = self.current_data.get("systemic_triggers", {})
            if isinstance(systemic, dict):
                mw = systemic.get("multi_word", [])
                if isinstance(mw, list):
                    self.systemic_mw_text.insert("1.0", "\n".join(mw))

                sw = systemic.get("single_word", [])
                if isinstance(sw, list):
                    self.systemic_sw_text.insert("1.0", "\n".join(sw))

    def get_edited_data(self):
        """Extract text widget data back into intent_classifier_triggers.yml format."""
        data = {"version": self.current_data.get("version", 1) if isinstance(self.current_data, dict) else 1}

        # Parse medical triggers
        medical_mw_str = self.medical_mw_text.get("1.0", "end").strip()
        medical_mw = [t.strip() for t in medical_mw_str.split("\n") if t.strip()]

        medical_sw_str = self.medical_sw_text.get("1.0", "end").strip()
        medical_sw = [t.strip() for t in medical_sw_str.split("\n") if t.strip()]

        data["medical_triggers"] = {
            "multi_word": medical_mw,
            "single_word": medical_sw
        }

        # Parse systemic triggers
        systemic_mw_str = self.systemic_mw_text.get("1.0", "end").strip()
        systemic_mw = [t.strip() for t in systemic_mw_str.split("\n") if t.strip()]

        systemic_sw_str = self.systemic_sw_text.get("1.0", "end").strip()
        systemic_sw = [t.strip() for t in systemic_sw_str.split("\n") if t.strip()]

        data["systemic_triggers"] = {
            "multi_word": systemic_mw,
            "single_word": systemic_sw
        }

        return data


class ConfigSettingsTab(BaseConfigTab):
    """Tab for config.yml."""

    def __init__(self, parent):
        super().__init__(parent, "config.yml", "yaml")

    def render_ui(self):
        """Placeholder UI for Phase 1."""
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            frame,
            text="Configuration Settings",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w")

        help_text = HELP_BY_FILE.get("config.yml", "")
        ttk.Label(frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(5, 15))

        ttk.Label(frame, text="Phase 1: Placeholder", foreground="gray").pack(anchor="w")


class UrlPatternRulesTab(BaseConfigTab):
    """Tab for url_pattern_rules.yml."""

    def __init__(self, parent):
        super().__init__(parent, "url_pattern_rules.yml", "yaml")

    def render_ui(self):
        """Placeholder UI for Phase 1."""
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            frame,
            text="URL Pattern Rules Configuration",
            font=("Helvetica", 12, "bold")
        ).pack(anchor="w")

        help_text = HELP_BY_FILE.get("url_pattern_rules.yml", "")
        ttk.Label(frame, text=help_text, wraplength=600, justify="left").pack(anchor="w", pady=(5, 15))

        ttk.Label(frame, text="Phase 1: Placeholder", foreground="gray").pack(anchor="w")


class ConfigManagerWindow:
    """Main Configuration Manager window with tabbed interface."""

    def __init__(self, root, log_func=None):
        """
        Args:
            root: Parent Tkinter window
            log_func: Optional function to log messages to main window
        """
        self.root = root
        self.log = log_func or (lambda msg: print(msg))
        self.window = tk.Toplevel(root)
        self.window.title("Configuration Manager")
        self.window.geometry("1000x700")
        self.window.transient(root)

        # Header
        header_frame = ttk.Frame(self.window)
        header_frame.pack(fill="x", padx=15, pady=15)

        ttk.Label(
            header_frame,
            text="Configuration Manager",
            font=("Helvetica", 14, "bold")
        ).pack(anchor="w")

        ttk.Label(
            header_frame,
            text="Edit editorial configuration files (YAML/JSON) with validation and help guidance.",
            foreground="gray"
        ).pack(anchor="w")

        # Tabbed interface
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.tabs = [
            DomainOverridesTab(notebook),
            ClassificationRulesTab(notebook),
            IntentMappingTab(notebook),
            StrategicPatternsTab(notebook),
            BriefPatternRoutingTab(notebook),
            IntentClassifierTriggersTab(notebook),
            ConfigSettingsTab(notebook),
            UrlPatternRulesTab(notebook),
        ]

        # Add tabs to notebook
        for tab in self.tabs:
            notebook.add(tab, text=tab.file_name)

        # Footer buttons
        footer_frame = ttk.Frame(self.window)
        footer_frame.pack(fill="x", padx=15, pady=(0, 15))

        ttk.Button(
            footer_frame,
            text="Validate All",
            command=self.validate_all
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            footer_frame,
            text="Save All",
            command=self.save_all
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            footer_frame,
            text="Discard Changes",
            command=self.discard_changes
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            footer_frame,
            text="Close",
            command=self.close_window
        ).pack(side="left")

        self.log("[Config Manager] Window opened\n")

    def validate_all(self):
        """Validate all tabs."""
        all_valid = True
        errors_by_file = {}

        for tab in self.tabs:
            is_valid, errors, warnings = tab.validate()
            if not is_valid:
                all_valid = False
                errors_by_file[tab.file_name] = errors

        if all_valid:
            messagebox.showinfo("Validation", "All configuration files are valid.")
            self.log("[Config Manager] All files validated successfully\n")
        else:
            error_msg = "Validation failed:\n\n"
            for file_name, errors in errors_by_file.items():
                error_msg += f"{file_name}:\n"
                for error in errors:
                    error_msg += f"  - {error}\n"
            messagebox.showerror("Validation Failed", error_msg)
            self.log("[Config Manager] Validation failed\n")

    def save_all(self):
        """Save all tabs to disk."""
        self.validate_all()

        for tab in self.tabs:
            success, message = tab.save_to_disk()
            if not success:
                messagebox.showerror("Save Failed", message)
                self.log(f"[Config Manager] Save failed: {message}\n")
                return

        messagebox.showinfo("Success", f"Saved {len(self.tabs)} configuration files.")
        self.log("[Config Manager] All files saved successfully\n")

    def discard_changes(self):
        """Discard unsaved changes and revert to disk."""
        has_changes = any(tab.has_unsaved_changes() for tab in self.tabs)
        if not has_changes:
            messagebox.showinfo("Discard", "No unsaved changes to discard.")
            return

        confirm = messagebox.askyesno(
            "Discard Changes",
            "Discard all unsaved changes and reload from disk?"
        )
        if confirm:
            for tab in self.tabs:
                tab.revert_to_disk()
            messagebox.showinfo("Success", "All changes discarded.")
            self.log("[Config Manager] Changes discarded, data reloaded from disk\n")

    def close_window(self):
        """Close the configuration manager window."""
        has_changes = any(tab.has_unsaved_changes() for tab in self.tabs)
        if has_changes:
            confirm = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?"
            )
            if confirm is None:
                return  # Cancel
            elif confirm:
                self.save_all()

        self.window.destroy()
        self.log("[Config Manager] Window closed\n")
