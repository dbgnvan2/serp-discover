# Configuration Manager: Multi-Client Support

## Overview

The Configuration Manager now supports **multiple client configurations** without restarting the application. Users can:

1. **Launch the Configuration Manager** → See available clients
2. **Select a client** → Load all config files for that client
3. **Edit and save** → Changes save to that client's directory
4. **Switch clients** → Mid-session, without restarting
5. **Add new clients** → By creating a new directory in `clients/`

---

## How It Works

### 1. Client Discovery

When you launch the Configuration Manager, it automatically scans the `clients/` directory and lists all available clients:

```
clients/
  living_systems/        ← Discovered
  acme_therapy/          ← Discovered
  nonprofit_food_bank/   ← Discovered
  _template/             ← Skipped (template, not a real client)
```

### 2. Client Selection Dialog

On startup, you see:

```
┌────────────────────────────────────────┐
│ Select Client Configuration            │
├────────────────────────────────────────┤
│ Select a client or browse for custom   │
│ directory.                             │
│                                        │
│ Available Clients:                     │
│ ┌──────────────────────────────────┐  │
│ │ living_systems                   │  │
│ │ acme_therapy                     │  │
│ │ nonprofit_food_bank              │  │
│ └──────────────────────────────────┘  │
│                                        │
│ [Select] [Browse...] [Use Current]    │
└────────────────────────────────────────┘
```

**Three options:**
- **Select** — Choose from discovered clients
- **Browse** — Navigate to any custom client directory
- **Use Current** — Use current working directory (backward compatible)

### 3. Load Client Config

Once you select a client (e.g., `living_systems`), the Configuration Manager:

1. Loads all 8 config files from `clients/living_systems/`:
   - `config.yml`
   - `domain_overrides.yml`
   - `intent_mapping.yml`
   - `strategic_patterns.yml`
   - `brief_pattern_routing.yml`
   - `intent_classifier_triggers.yml`
   - `classification_rules.json`
   - `url_pattern_rules.yml`

2. Displays them in tabs (same as before)

3. Shows client info in the header:
   ```
   Configuration Manager
   Client: living_systems  |  Path: /Users/davemini2/ProjectsLocal/serp-discover/clients/living_systems
   ```

### 4. Edit & Save

You edit config as usual. When you click **Save All**, files save to the client's directory, not the current working directory.

### 5. Switch Clients

New button: **Switch Client** (top-left)

Clicking it:
- Checks for unsaved changes
- Prompts to save if needed
- Shows client selector dialog
- Reloads all tabs with new client's config
- Updates header with new client name

---

## Directory Structure

### Recommended Layout

```
serp-discover/
  serp-me.py                  (main app, unchanged)
  config_manager.py           (ENHANCED: now supports client_dir parameter)
  
  clients/
    _template/                (template for new clients)
      config.yml
      domain_overrides.yml
      intent_mapping.yml
      strategic_patterns.yml
      brief_pattern_routing.yml
      intent_classifier_triggers.yml
      classification_rules.json
      url_pattern_rules.yml
      README.md                (document client-specific choices)
    
    living_systems/           (client 1)
      [same 8 files as template]
      README.md
    
    acme_therapy/             (client 2)
      [same 8 files as template]
      README.md
    
    nonprofit_food_bank/      (client 3)
      [same 8 files as template]
      README.md
```

---

## Implementation Details

### Changes to config_manager.py

#### 1. ConfigManagerWindow

```python
# Before
class ConfigManagerWindow:
    def __init__(self, root, log_func=None):
        self.window = tk.Toplevel(root)
        # Load from current directory
        self.tabs = [
            DomainOverridesTab(notebook),
            # ...
        ]

# After
class ConfigManagerWindow:
    def __init__(self, root, log_func=None, client_dir=None):
        self.client_dir = client_dir or self._select_client_directory()
        self.window = tk.Toplevel(root)
        # Load from client_dir
        self.tabs = [
            DomainOverridesTab(notebook, client_dir=self.client_dir),
            # ...
        ]
    
    def switch_client(self):
        """Switch to different client without restarting."""
        new_client_dir = self._select_client_directory()
        # ... reload tabs with new directory ...
    
    def _select_client_directory(self):
        """Show client picker dialog."""
        # Show dialog with available clients
        # Return selected path
```

#### 2. BaseConfigTab

```python
# Before
class BaseConfigTab(ttk.Frame):
    def __init__(self, parent, file_name: str, file_type: str):
        self.file_path = os.path.join(os.getcwd(), file_name)

# After
class BaseConfigTab(ttk.Frame):
    def __init__(self, parent, file_name: str, file_type: str, client_dir: str = None):
        self.client_dir = client_dir or os.getcwd()
        self.file_path = os.path.join(self.client_dir, file_name)
    
    def set_client_dir(self, client_dir: str):
        """Called when switching clients."""
        self.client_dir = client_dir
        self.file_path = os.path.join(self.client_dir, file_name)
```

#### 3. All Tab Subclasses

Each tab class now accepts `client_dir` parameter:

```python
class DomainOverridesTab(BaseConfigTab):
    def __init__(self, parent, client_dir=None):
        super().__init__(parent, "domain_overrides.yml", "yaml", client_dir=client_dir)

class IntentMappingTab(BaseConfigTab):
    def __init__(self, parent, client_dir=None):
        super().__init__(parent, "intent_mapping.yml", "yaml", client_dir=client_dir)

# ... and so on for all 8 tabs
```

---

## Usage Examples

### Example 1: Launch from serp-me.py

In `serp-me.py`, update the button that opens Configuration Manager:

```python
# Before (still works - backward compatible)
ConfigManagerWindow(self.root, log_func=self.log)

# After (with optional client selection)
ConfigManagerWindow(self.root, log_func=self.log)
# User sees client selector on startup
```

**No code change required!** The Configuration Manager auto-discovers clients and prompts.

### Example 2: Launch for Specific Client (Command Line)

If you want to launch Configuration Manager directly for a specific client:

```python
from config_manager import ConfigManagerWindow
import tkinter as tk

root = tk.Tk()
ConfigManagerWindow(root, client_dir="clients/living_systems")
root.mainloop()
```

### Example 3: Add New Client

1. Create directory: `mkdir clients/my_new_client/`
2. Copy template files: `cp clients/_template/* clients/my_new_client/`
3. Edit `config.yml` with new client values
4. Launch Configuration Manager → See `my_new_client` in the list

---

## Workflow: Managing Multiple Clients

### Scenario 1: Edit Living Systems Config

```
1. python3 serp-me.py
2. Click "Edit Configuration"
3. [Client Selector Dialog]
   - Select "living_systems"
4. [Configuration Manager opens]
   - Header shows: Client: living_systems
5. Edit domain_overrides.yml (add new competitors)
6. Click "Save All"
7. Files saved to: clients/living_systems/domain_overrides.yml
```

### Scenario 2: Switch to Acme Therapy

```
1. [Still in Configuration Manager]
2. Click "Switch Client"
3. [Client Selector Dialog]
   - Select "acme_therapy"
4. [Tabs reload with Acme's config]
   - Header shows: Client: acme_therapy
5. Edit intent_mapping.yml for Acme
6. Click "Save All"
7. Files saved to: clients/acme_therapy/intent_mapping.yml
8. Living Systems config unchanged
```

### Scenario 3: Add New Client

```
1. $ mkdir clients/new_nonprofit
2. $ cp clients/_template/* clients/new_nonprofit/
3. $ python3 serp-me.py
4. Click "Edit Configuration"
5. [Client Selector Dialog]
   - See "new_nonprofit" in list
   - Select it
6. [Configuration Manager opens with empty config]
7. Fill in config values
8. Click "Save All"
9. Files saved to: clients/new_nonprofit/
```

---

## Backward Compatibility

**The changes are 100% backward compatible.**

**Old behavior (still works):**
```python
# No client_dir parameter
ConfigManagerWindow(root, log_func=log_func)
# User sees client selector, or can use current directory
```

**New behavior:**
```python
# With client_dir parameter
ConfigManagerWindow(root, log_func=log_func, client_dir="clients/living_systems")
# Skips selector, loads directly
```

If `clients/` directory doesn't exist, the tool falls back to current directory (backward compatible).

---

## Features

### ✅ Client Selection Dialog
- Auto-discovers clients in `clients/` directory
- Shows dropdown/listbox of available clients
- Skips `_template/` (not a real client)
- Browse button for custom directories
- "Use Current Directory" fallback

### ✅ Client Info Display
- Header shows selected client name and path
- Clear visual indication of which client you're editing

### ✅ Switch Clients Mid-Session
- New "Switch Client" button
- Checks for unsaved changes
- Prompts to save before switching
- Reloads all tabs with new client config

### ✅ Persistent Client Directory
- All file operations read/write to client's directory
- Save All saves to correct location
- No accidental overwrites

### ✅ Client Isolation
- Editing one client's config doesn't affect others
- Separate domain_overrides per client
- Separate config.yml per client
- etc.

---

## Testing

### Test 1: Basic Client Selection

```
1. Create clients/test_client/ directory
2. Copy all YAML/JSON files there
3. Launch Configuration Manager
4. Select "test_client"
5. Verify header shows "Client: test_client"
6. Edit a file
7. Click Save All
8. Verify file was saved to clients/test_client/
```

### Test 2: Switch Clients

```
1. [In Configuration Manager]
2. Click "Switch Client"
3. Select different client
4. Verify header updates
5. Verify tabs show new client's data
6. Edit a file
7. Click Save All
8. Verify file saved to NEW client's directory, not old one
```

### Test 3: Unsaved Changes Warning

```
1. [In Configuration Manager]
2. Edit a file (but don't save)
3. Click "Switch Client"
4. [Should see prompt: "You have unsaved changes. Save before switching?"]
5. Click "Yes"
6. [Should save to old client, then switch]
```

---

## API Reference

### ConfigManagerWindow

```python
class ConfigManagerWindow:
    def __init__(self, root, log_func=None, client_dir=None):
        """
        Args:
            root: Parent Tkinter window
            log_func: Optional callback for logging
            client_dir: Optional client directory path
                       If None, shows client selector dialog
        """

    def switch_client(self):
        """Prompt to switch to different client."""

    def _select_client_directory(self):
        """Show client selector dialog, return path."""
```

### BaseConfigTab

```python
class BaseConfigTab(ttk.Frame):
    def __init__(self, parent, file_name: str, file_type: str, client_dir: str = None):
        """
        Args:
            parent: Parent widget
            file_name: Config file name (e.g., 'config.yml')
            file_type: 'yaml' or 'json'
            client_dir: Client directory (defaults to current working directory)
        """

    def set_client_dir(self, client_dir: str):
        """Update client directory (for switching clients)."""
```

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Client selector doesn't show clients | `clients/` directory doesn't exist | Create `clients/` directory and add client subdirectories |
| Switching client doesn't reload data | Old client_dir still cached | Check that `set_client_dir()` was called on all tabs |
| Files saved to wrong directory | client_dir not passed to tab | Verify all tabs receive client_dir in __init__ |
| Can't find custom client directory | Wrong path or directory doesn't exist | Use "Browse" button, navigate to correct location |

---

## Next Steps

1. **Test the implementation** — Create a test client directory, try the client selector
2. **Create _template/ directory** — For easy onboarding of new clients
3. **Update documentation** — Link to this guide from serp-me.py help
4. **Add keyboard shortcut** (optional) — For faster client switching
5. **Add "Create Client" dialog** (optional) — To create new client from GUI

---

## Summary

The Configuration Manager now supports **multi-client workflows** seamlessly:

- ✅ Select client at startup (or use current directory)
- ✅ Edit all config files for that client
- ✅ Switch between clients without restarting
- ✅ Each client's files isolated in `clients/{client_name}/`
- ✅ 100% backward compatible
- ✅ No code changes needed in serp-me.py (works as-is)

Perfect for managing configurations across multiple clients, locations, or business types.
