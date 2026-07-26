# Multi-Client Configuration Architecture

## The Problem: One Tool, Many Clients

Each client is unique:
- Different location (Toronto vs. Vancouver)
- Different business model (nonprofit vs. private practice)
- Different competitors and market
- Different therapeutic framework (Bowen vs. CBT vs. Attachment)
- Different target audiences and content angles

**How do you run one tool for many clients without maintaining N separate codebases?**

**Answer:** Configuration-driven design. Store all client differences in files, not code.

---

## Decision Tree: Which Files to Customize Per Client?

```
┌─────────────────────────────────────────────────────────────────┐
│ File: config.yml                                                │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ✓ YES (always)                                 │
│ Reason: Contains client name, DA, location, neighborhoods      │
│ Decision: Create per-client copy                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: domain_overrides.yml                                      │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ✓ YES (almost always)                          │
│ Reason: Different markets have different competitors           │
│ Decision: Create per-client copy                               │
│ Exception: If two clients serve the same market (rare), can    │
│           share a base and add client-specific overrides        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: intent_mapping.yml                                        │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ◐ MAYBE                                        │
│                                                                 │
│ Share if:                                                       │
│   - All clients are in same industry (all therapists)           │
│   - Intent patterns are the same for all                        │
│                                                                 │
│ Separate if:                                                    │
│   - Clients differ by business model:                           │
│     * Nonprofit vs. private practice                            │
│     * Telehealth vs. in-person only                             │
│     * B2C vs. B2B services                                      │
│   - Their local pack strategy differs                           │
│   - Their feasibility thresholds differ                         │
│                                                                 │
│ Decision: Start shared; separate if intent patterns differ      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: strategic_patterns.yml                                    │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ◐ MAYBE (probably yes)                        │
│ Reason: Depends on client's therapeutic framework              │
│                                                                 │
│ Share if:                                                       │
│   - All clients use same framework (all Bowen practices)        │
│                                                                 │
│ Separate if:                                                    │
│   - Client A uses Bowen, Client B uses CBT                      │
│   - Client A focuses on individual therapy, B on couples        │
│   - Patterns would confuse the audience                         │
│                                                                 │
│ Decision: Usually per-client; consider sharing only if         │
│          framework is identical                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: brief_pattern_routing.yml                                 │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ◐ MAYBE                                        │
│ Reason: Routes patterns to PAA themes; depends on whether      │
│         strategic_patterns.yml is shared or separate           │
│                                                                 │
│ Decision: If sharing patterns, share routing.                  │
│          If separating patterns, separate routing.              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: intent_classifier_triggers.yml                            │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ◐ MAYBE                                        │
│ Reason: Depends on whether PAA vocabularies differ by framework │
│                                                                 │
│ Share if:                                                       │
│   - All clients use same therapeutic framework                  │
│   - Medical vs. systemic vocabulary is the same                 │
│                                                                 │
│ Separate if:                                                    │
│   - Different frameworks have different vocabularies            │
│   - (CBT has "thought records", Bowen has "differentiation")   │
│                                                                 │
│ Decision: Usually shared; separate if frameworks differ         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: classification_rules.json                                 │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ✗ NO (shared)                                  │
│ Reason: Defines valid entity & content types; applies universally
│ Exception: If you serve very different industries               │
│          (health tech + therapy + legal), might need separate   │
│                                                                 │
│ Decision: Shared; only customize if truly different domains    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ File: url_pattern_rules.yml                                     │
├─────────────────────────────────────────────────────────────────┤
│ Client-specific? ✗ NO (shared)                                  │
│ Reason: URL patterns (like "/therapist/", "/blog/") are universal
│ Why it works: URL structure is industry-standard, not client-  │
│              specific. All therapy sites use similar URL paths. │
│                                                                 │
│ Decision: Shared across all clients                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Recommended Directory Structure

### Conservative Approach: Maximize Per-Client Separation

**Use this if:**
- You expect clients to differ significantly
- You want maximum flexibility for client-specific tuning
- You're building toward a multi-tenant SaaS

```
serp-discover/
  serp-me.py                          (unchanged - main app)
  
  [Shared libraries & utils]
  generate_content_brief.py
  intent_verdict.py
  src/
    ...
  
  [Shared config files - only fallbacks]
  classification_rules.json
  url_pattern_rules.yml
  
  clients/
    ├── _template/                    (template for new clients)
    │   ├── config.yml
    │   ├── domain_overrides.yml
    │   ├── intent_mapping.yml
    │   ├── strategic_patterns.yml
    │   ├── brief_pattern_routing.yml
    │   ├── intent_classifier_triggers.yml
    │   └── README.md                 (client-specific notes)
    │
    ├── living_systems/               (client 1)
    │   ├── config.yml                (nonprofit, Vancouver, Bowen)
    │   ├── domain_overrides.yml      (LS competitors)
    │   ├── intent_mapping.yml        (LS intent rules)
    │   ├── strategic_patterns.yml    (Bowen patterns)
    │   ├── brief_pattern_routing.yml
    │   ├── intent_classifier_triggers.yml
    │   └── README.md
    │
    ├── acme_therapy/                 (client 2)
    │   ├── config.yml                (private practice, Toronto, CBT)
    │   ├── domain_overrides.yml      (Acme's competitors)
    │   ├── intent_mapping.yml        (Acme's intent rules)
    │   ├── strategic_patterns.yml    (CBT patterns, not Bowen)
    │   ├── brief_pattern_routing.yml
    │   ├── intent_classifier_triggers.yml
    │   └── README.md
    │
    └── other_client/
        ├── config.yml
        ├── ... (same structure)
        └── README.md
```

**Pros:**
- Maximum flexibility
- Easy to customize per client
- Easy to onboard new clients (copy _template/)

**Cons:**
- Files can drift from shared base
- Manual sync if patterns change universally

---

### Balanced Approach: Share Frameworks, Per-Client Customizations

**Use this if:**
- All clients are therapists using the same frameworks (e.g., all Bowen)
- You want to avoid duplication but allow client overrides
- You expect less variation between clients

```
serp-discover/
  [Same as above]
  
  shared/                            (shared across all clients)
    ├── classification_rules.json
    ├── url_pattern_rules.yml
    ├── strategic_patterns.yml       (all Bowen; shared)
    ├── brief_pattern_routing.yml    (mapped to shared patterns)
    ├── intent_classifier_triggers.yml (Bowen vocab; shared)
    └── intent_mapping.yml           (shared base intent rules)
  
  clients/
    ├── living_systems/
    │   ├── config.yml               (LS-specific values)
    │   └── domain_overrides.yml     (LS competitors only)
    │
    ├── acme_therapy/
    │   ├── config.yml               (Acme-specific values)
    │   └── domain_overrides.yml     (Acme competitors only)
```

**In code:** App logic would be:
1. Load shared files from `shared/`
2. Overlay client-specific `domain_overrides.yml`
3. Use client-specific `config.yml`

**Pros:**
- Minimal duplication
- Easy to maintain shared frameworks
- Changes to patterns auto-apply to all clients

**Cons:**
- Requires code changes to load from multiple locations
- Harder to customize one client without affecting others

---

### Minimal Approach: One Base, Override-Only Per Client

**Use this if:**
- All clients are identical except for location/DA/competitors
- You're just tuning the same business model across geographies

```
serp-discover/
  [Main app files]
  
  config.yml                         (base; can be overridden)
  domain_overrides.yml               (base)
  intent_mapping.yml                 (shared)
  strategic_patterns.yml             (shared)
  ... [all other files shared]
  
  clients/
    ├── living_systems/
    │   ├── config.yml               (override: location, DA, neighborhoods)
    │   └── domain_overrides.yml     (override: add LS-specific overrides)
    │
    ├── acme_therapy/
    │   ├── config.yml               (override: location, DA, neighborhoods)
    │   └── domain_overrides.yml     (override: add Acme overrides)
```

**Pros:**
- Minimal file duplication
- Easy to see what differs per client

**Cons:**
- Only works if clients are very similar
- Hard to customize intent rules per client

---

## Recommended Approach for Living Systems + Future Clients

**I recommend: Conservative (Maximum Separation)**

Why?
1. You're building a repeatable tool for future clients
2. Clients will differ (Living Systems is nonprofit; next might be private)
3. Frameworks differ (Bowen vs. CBT)
4. Markets differ (North Shore Vancouver vs. Toronto)
5. It's easier to refactor toward shared later than to separate later

**Structure:**

```
clients/
  living_systems/
    config.yml
    domain_overrides.yml
    intent_mapping.yml
    strategic_patterns.yml
    brief_pattern_routing.yml
    intent_classifier_triggers.yml
    classification_rules.json
    url_pattern_rules.yml
    README.md (documents LS-specific choices)
```

**When adding a new client (e.g., Acme):**
1. Copy `living_systems/` to `acme_therapy/`
2. Edit each file:
   - config.yml: New location, DA, client name
   - domain_overrides.yml: Remove LS competitors, add Acme's
   - intent_mapping.yml: Usually leave as-is (keep base rules)
   - strategic_patterns.yml: Replace Bowen with CBT patterns (if different)
   - Everything else: Keep or adjust as needed
3. Test with Acme keywords
4. Document changes in README.md

---

## Implementation: How to Load Per-Client Config

### Option 1: Symlink Approach

Before running the tool, symlink the client's config directory:

```bash
# For Living Systems
ln -sf clients/living_systems/*.yml .
ln -sf clients/living_systems/*.json .
python3 serp-me.py

# For Acme Therapy
rm -f *.yml *.json  (unlink old symlinks)
ln -sf clients/acme_therapy/*.yml .
ln -sf clients/acme_therapy/*.json .
python3 serp-me.py
```

**Pros:** Simple, no code changes
**Cons:** Manual symlink management, error-prone

---

### Option 2: CLI Flag (Recommended)

Modify `serp-me.py`:

```python
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument('--client', default='living_systems', 
                    help='Client name (directory under clients/)')
args = parser.parse_args()

client_dir = os.path.join('clients', args.client)
config_path = os.path.join(client_dir, 'config.yml')
domain_overrides_path = os.path.join(client_dir, 'domain_overrides.yml')
# ... etc for all 8 config files

# Load configs
config = load_yaml(config_path)
domain_overrides = load_yaml(domain_overrides_path)
# ... etc
```

**Usage:**
```bash
python3 serp-me.py --client living_systems
python3 serp-me.py --client acme_therapy
```

**Pros:** Clean, scriptable, no symlink management
**Cons:** Requires code changes

---

### Option 3: Environment Variable

```python
import os

client = os.getenv('SERP_CLIENT', 'living_systems')
client_dir = os.path.join('clients', client)
# ... load configs from client_dir
```

**Usage:**
```bash
export SERP_CLIENT=living_systems
python3 serp-me.py

export SERP_CLIENT=acme_therapy
python3 serp-me.py
```

**Pros:** Flexible, shell-friendly
**Cons:** Requires env setup

---

### Option 4: GUI Client Selector (Best UX)

When user clicks "Edit Configuration" in serp-me.py, show a dialog:

```
┌──────────────────────────────┐
│ Select Client                │
├──────────────────────────────┤
│                              │
│ Which client?                │
│ ┌──────────────────────────┐ │
│ │ ▼ living_systems         │ │
│ │   acme_therapy           │ │
│ │   other_client           │ │
│ └──────────────────────────┘ │
│                              │
│         [Open Config]        │
└──────────────────────────────┘
```

When the user selects "acme_therapy" and clicks "Open Config", the Configuration Manager loads from `clients/acme_therapy/`.

**Implementation hint:** Update config_manager.py to:
1. Scan `clients/` directory
2. Show dropdown of available clients
3. Load selected client's files

**Pros:** Best user experience; no CLI knowledge needed
**Cons:** Requires UI development

---

## Managing Configuration Changes

### Scenario 1: Update a Pattern, Applies to All Clients

**Example:** You refine the "Blame/Reactivity Trap" pattern.

**If sharing strategic_patterns.yml:**
- Edit `shared/strategic_patterns.yml`
- All clients auto-get the update
- Done

**If separating strategic_patterns.yml:**
- Edit `clients/living_systems/strategic_patterns.yml`
- Edit `clients/acme_therapy/strategic_patterns.yml` (copy the same change)
- **Risk:** Drift — one client's version diverges

**Best practice:**
- Keep a "shared patterns" file in version control
- Document which clients use which patterns
- When updating, update all client copies

---

### Scenario 2: Living Systems Gets New Competitor

**Example:** A new therapy directory "TherapyFinder.ca" launches in Vancouver.

**Steps:**
1. Go to `clients/living_systems/domain_overrides.yml`
2. Add: `therapyfinder.ca: directory`
3. Save; re-run keywords
4. Living Systems' analysis now accounts for this competitor

**Other clients unaffected** (their domain_overrides.yml doesn't have this entry).

---

### Scenario 3: You Discover a Better Intent Rule, Applies to All Clients

**Example:** Guide pages on counselling domains should ALWAYS be informational, regardless of local pack.

**If sharing intent_mapping.yml:**
- Edit `shared/intent_mapping.yml`
- All clients auto-get the update
- Done

**If separating intent_mapping.yml:**
- Edit `clients/living_systems/intent_mapping.yml`
- Edit `clients/acme_therapy/intent_mapping.yml` (same change)
- Risk: drift

**Best practice:**
- Document the rule change in git commit
- Apply to all clients in same commit
- PR review before merging

---

## Version Control Strategy

### What to Commit

```
✓ All client configs (clients/*/*)
✓ Shared configs (shared/*)
✓ Application code changes
✓ Documentation
✗ Output files (market_analysis_*.xlsx, competitor_handoff_*.json)
✗ Cache files (serp_data.db in temp state)
```

### Example Commit Messages

```
Good:
  commit: Add acme_therapy client config
  Adds separate domain_overrides, config, and patterns for Acme Therapy Group.
  Location: Toronto, ON. Framework: CBT.
  
  commit: Refine intent mapping rule for guide pages
  Guide pages now always classify as informational, regardless of local pack.
  Applied to all clients.
  
  commit: Update Living Systems domain overrides
  Added therapyfinder.ca (directory), updated psychologytoday.com notes.

Bad:
  commit: config changes
  commit: fix intent mapping
```

---

## Checklist: Adding a New Client

- [ ] Create `clients/newclient/` directory
- [ ] Copy template files (or copy from living_systems/)
- [ ] Edit `config.yml`:
  - [ ] Client name & domain
  - [ ] Location & geography
  - [ ] Client DA & neighborhoods
  - [ ] Organization type & description
  - [ ] Preferred intents
- [ ] Edit `domain_overrides.yml`:
  - [ ] Remove old client's competitors
  - [ ] Add new client's competitors from their knowledge
- [ ] Edit `intent_mapping.yml`:
  - [ ] Keep shared base; adjust only if business model differs
- [ ] Edit `strategic_patterns.yml`:
  - [ ] Keep Bowen if they use Bowen; replace if different framework
- [ ] Edit `brief_pattern_routing.yml`:
  - [ ] Update to match patterns above
- [ ] Edit `intent_classifier_triggers.yml`:
  - [ ] Keep shared vocab unless framework differs
- [ ] Keep `classification_rules.json` & `url_pattern_rules.yml` as-is
- [ ] Create `README.md` documenting:
  - [ ] Client name & location
  - [ ] Therapeutic framework
  - [ ] Key decisions made (if any configs deviate from template)
  - [ ] Competitor notes
- [ ] Test:
  - [ ] Run 5-10 sample keywords
  - [ ] Verify output file paths are correct
  - [ ] Verify client name appears in report
  - [ ] Verify domain overrides working (known competitors labeled correctly)
- [ ] Commit with message: "Add {client} client config"

---

## Troubleshooting: Multi-Client Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| Output says "Living Systems" but I'm running for Acme | Wrong config.yml loaded | Verify correct client_dir is being used; check symlinks or CLI flag |
| Competitor not recognized for Acme | Old domain_overrides.yml in use | Add to acme_therapy/domain_overrides.yml; re-run |
| Intent rules changed for all clients, but I only wanted to change Acme | Edited shared intent_mapping.yml | If shared, you must edit all client copies or accept global change |
| Two clients keep affecting each other | Sharing files that should be separate | Move file to per-client; separate domain_overrides or patterns as needed |

---

## Future: SaaS Multi-Tenancy Considerations

If you scale to many clients, consider:

1. **Database instead of files** — Store configs in a database with per-client rows
2. **API for config management** — CRUD operations via REST instead of file editing
3. **Config versioning** — Track who changed what, when
4. **A/B testing configs** — Run two versions of intent_mapping on same keywords
5. **Config templates** — Pre-built patterns for common frameworks (Bowen, CBT, ACT, etc.)

For now, the file-based approach is simple and works great.

---

## Summary

**To support multiple clients:**

1. **Use the Conservative (Separation) approach**
   - Each client gets their own `clients/{name}/` directory
   - Contains all 8 configuration files
   - Shared: classification_rules.json, url_pattern_rules.yml (mostly)

2. **Implement client selection**
   - Via CLI flag: `python3 serp-me.py --client acme_therapy`
   - Via GUI dialog: Click "Edit Configuration" → select client → edit files
   - Via symlinks: Symlink client files before running (not recommended)

3. **Use version control**
   - Commit all client configs
   - Document config decisions in README per client
   - Use clear commit messages

4. **Maintain templates**
   - Keep `clients/_template/` as a starting point for new clients
   - Document decisions in template README

5. **Test after adding clients**
   - Run sample keywords
   - Verify output paths, client names, domain overrides working
   - Check that patterns/intent rules are as expected

Done! You now have a scalable, multi-client configuration system.
