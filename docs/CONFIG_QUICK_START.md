# Configuration System Quick Start

> **New to the configuration system?** Start here. Then read the full guides.

---

## What Is Configuration?

The tool has **9 editable config files** that control behavior. Instead of changing Python code, you change these files.

**Key insight:** Configuration = decisions. Every rule, pattern, and override is a decision you make that persists across runs.

---

## The 9 Files at a Glance

### The "Decision Engine" Files (4)

These determine what search intent is, what patterns matter, and how to route content.

| # | File | What It Does | Example |
|---|------|-------------|---------|
| 1 | **intent_mapping.yml** | Matches (content_type, entity_type, local_pack) → SERP intent | "A guide on a counselling site = informational" |
| 2 | **domain_overrides.yml** | Corrects misclassified domains | "psychologytoday.com = directory" |
| 3 | **strategic_patterns.yml** | Defines Bowen patterns & reframes | "The Blame Trap: narcissist → focus on self-regulation" |
| 4 | **brief_pattern_routing.yml** | Maps patterns to PAA themes & keywords | "Blame Trap appears in 'relationships' & 'conflict' themes" |

**When to edit:**
- Run keywords → see output → notice something wrong → fix it in one of these 4 files

---

### The "Classification Vocabulary" Files (2)

These define the building blocks used by the decision engine.

| # | File | What It Does | Example |
|---|------|-------------|---------|
| 5 | **classification_rules.json** | Lists valid entity types & describes them | "counselling = Direct therapy service providers" |
| 6 | **intent_classifier_triggers.yml** | Vocabularies for classifying PAA questions | "medical: anxiety, disorder, treatment" vs. "systemic: patterns, differentiation" |

**When to edit:**
- Rare. Only when you need a new entity type or new vocabulary.

---

### The "Operational" Files (2)

These control how the tool runs.

| # | File | What It Does | Example |
|---|------|-------------|---------|
| 7 | **config.yml** | API keys, file paths, client info, thresholds | "client_da: 35", "location: Vancouver, BC" |
| 8 | **url_pattern_rules.yml** | Fallback classification rules for URLs | "/therapist/ → service page" |

**When to edit:**
- config.yml: Every time you work with a new client
- url_pattern_rules.yml: Rarely; when you need better URL-based classification

---

## What Gets Auto-Generated vs. Manual?

### Auto-Generated (By the Tool)

- **Entity Type & Content Type** — For each URL, the tool tries to guess what it is (via HTML analysis, URL patterns)
- **Domain Role** — Whether the URL is on your client's domain, a known competitor, or other
- **Local Pack Presence** — Whether the SERP has a Google Maps 3-pack

### Manual (By You)

- **Entity Type Overrides** (domain_overrides.yml) — "That guess was wrong; it's actually a directory"
- **Patterns** (strategic_patterns.yml) — "Here's a Bowen pattern I want to track"
- **Intent Rules** (intent_mapping.yml) — "When you see [this combo], the intent is [that]"
- **Pattern Routing** (brief_pattern_routing.yml) — "This pattern shows up in [these PAA themes]"
- **Config Values** (config.yml) — "My client is in Toronto, has DA 42, serves these neighborhoods"

---

## Per-Client vs. Shared: The Quick Decision

| File | Shared or Per-Client? | Why |
|------|---------------------|-----|
| **config.yml** | 🔴 PER-CLIENT | Each client has different location, DA, name, neighborhoods |
| **domain_overrides.yml** | 🔴 PER-CLIENT | Each client has different competitors |
| **intent_mapping.yml** | 🟡 MAYBE | Share if all clients have same business model; separate if they differ |
| **strategic_patterns.yml** | 🟡 MAYBE | Share if all use Bowen; separate if frameworks differ (Bowen vs. CBT) |
| **brief_pattern_routing.yml** | 🟡 MAYBE | Depends on whether patterns are shared |
| **intent_classifier_triggers.yml** | 🟡 MAYBE | Share if all use same therapeutic vocabulary; separate if frameworks differ |
| **classification_rules.json** | 🟢 SHARED | Entity types apply universally |
| **url_pattern_rules.yml** | 🟢 SHARED | URL patterns apply across all clients |

**Quick rule of thumb:**
- Always separate: config.yml, domain_overrides.yml
- Probably separate: strategic_patterns.yml (unless all clients use Bowen)
- Probably shared: classification_rules.json, url_pattern_rules.yml
- Maybe either: intent_mapping.yml, brief_pattern_routing.yml, intent_classifier_triggers.yml

---

## Directory Structure (Conservative Approach — Recommended)

```
serp-discover/
  serp-me.py                          (main app)
  
  clients/
    ├── _template/                    (copy this for new clients)
    │   ├── config.yml
    │   ├── domain_overrides.yml
    │   ├── intent_mapping.yml
    │   ├── strategic_patterns.yml
    │   ├── brief_pattern_routing.yml
    │   ├── intent_classifier_triggers.yml
    │   ├── classification_rules.json
    │   ├── url_pattern_rules.yml
    │   └── README.md                 (notes on this client's setup)
    │
    ├── living_systems/               (client 1)
    │   ├── config.yml                (LS values: Vancouver, DA 35, Bowen)
    │   ├── domain_overrides.yml      (LS competitors)
    │   ├── [rest of files]
    │   └── README.md
    │
    └── acme_therapy/                 (client 2)
        ├── config.yml                (Acme values: Toronto, DA 42, CBT)
        ├── domain_overrides.yml      (Acme competitors)
        ├── [rest of files]
        └── README.md
```

**To run for a client:**
```bash
python3 serp-me.py --client living_systems
python3 serp-me.py --client acme_therapy
```

---

## Your First 5 Changes

### 1. Edit config.yml for Your Client

```yaml
client:
  preferred_intents: [informational, transactional, local]

feasibility:
  client_da: 35                      # Your Domain Authority

analysis_report:
  client_name: Living Systems Counselling
  client_domain: livingsystems.ca
  location: North Vancouver, BC, Canada
  
serpapi:
  location: Vancouver, British Columbia, Canada
  gl: ca
```

**When you're done:** Output reports will have your client's name and location.

---

### 2. Build domain_overrides.yml Over Time

**First run:**
- Run 10 keywords
- Look at output
- Find domains classified wrong
- Add 3-5 overrides

**Second run:**
- Run 10 more keywords
- Find new misclassifications
- Add 5-10 more overrides
- Now you have 8-15 overrides

**After 3-5 runs:**
- You'll have 20-50 overrides
- Covers most of your market
- Add new ones as you discover them

**Example:**

```yaml
psychologytoday.com: directory        # Therapist profiles, but it's a directory
zencare.co: directory                 # Same
bcacc.ca: professional_association    # Counsellor certification body
facebook.com: media                   # Not a therapy provider
```

---

### 3. Use Intent Mapping Rules As-Is (Mostly)

**Default intent_mapping.yml works for most clients.** Don't change it unless:
- You're a telehealth-only practice (then adjust local pack rules)
- Your business model is completely different from the default

**Learn it by:**
- Run keywords
- Look at intent distribution
- If intent looks wrong, **ask the team first** before editing

---

### 4. Keep Strategic Patterns as Living Systems Provided Them

**The Bowen patterns (The Blame Trap, The Fusion Trap, etc.) are clinically grounded.**

Don't remove patterns lightly. But do:
- Add new patterns if your clinical team identifies a new trap
- Update triggers if they're not showing up in real search data

---

### 5. Don't Touch (Yet)

Leave these alone for now:

- **classification_rules.json** — Only edit if you need a new entity type
- **url_pattern_rules.yml** — Only edit if URL classification is poor
- **intent_classifier_triggers.yml** — Only edit if PAA classification looks wrong

---

## Common Changes: Copy-Paste Examples

### "Add a new domain override"

```bash
# Edit domain_overrides.yml:
newsite.ca: counselling
anothersite.com: directory
```

Then save and re-run keywords.

### "Add a new Bowen pattern"

Edit strategic_patterns.yml:

```yaml
- Pattern_Name: The Escape Trap
  Triggers:
    - avoid
    - withdraw
    - isolate
    - hide
    - run
  Status_Quo_Message: >-
    I can protect myself by avoiding contact
  Bowen_Bridge_Reframe: >-
    Escape creates more anxiety long-term. Stay present and differentiate.
  Content_Angle: >-
    Why withdrawal triggers deeper pursuit and how to stay regulated instead
```

Then edit brief_pattern_routing.yml to add routing for the new pattern.

### "Change your client's Domain Authority"

Edit config.yml:

```yaml
feasibility:
  client_da: 42                      # Changed from 35 to 42
```

Re-run analysis; feasibility scores will adjust.

---

## How to Know If a Config Change Worked

After editing config, run 5 test keywords and check:

1. **config.yml change** → Check output: Does it have your new client name? New location?
2. **domain_overrides.yml change** → Check output: Is the domain now classified correctly?
3. **intent_mapping.yml change** → Check output: Do intent distributions match what you'd expect?
4. **pattern change** → Check brief: Do new patterns appear? Old patterns gone?

If the answer is yes, the change worked. If no, the change didn't take effect (maybe you didn't save?).

---

## When You're Stuck

| Problem | Where to Look | Fix |
|---------|---------------|-----|
| "A domain is classified wrong" | domain_overrides.yml | Add the domain + correct entity type |
| "Intent distributions look wrong" | intent_mapping.yml + output | Check the rule conditions; adjust if needed |
| "Patterns aren't showing in briefs" | strategic_patterns.yml + brief_pattern_routing.yml | Verify pattern name matches; check routing has PAA themes |
| "Client name is wrong in report" | config.yml → analysis_report.client_name | Update the name; re-run |
| "Output goes to wrong folder" | config.yml → files.output_* | Update paths; re-run |

---

## Next Steps

1. **Read CONFIGURATION_GUIDE.md** (5 min skim → 30 min deep read)
   - Detailed explanation of each of the 9 files
   - When to edit them
   - How data is created/obtained
   - Multi-client implications per file

2. **Read MULTI_CLIENT_ARCHITECTURE.md** (10 min skim → 45 min deep read)
   - Decision tree for what to customize per client
   - Directory structure recommendations
   - Implementation options (CLI flag vs. symlink vs. GUI)
   - Checklist for onboarding new clients

3. **Try it yourself**
   - Create `clients/living_systems/` directory
   - Copy the 8 YAML/JSON files there
   - Edit `config.yml` with your values
   - Run a few keywords
   - Edit domain_overrides.yml with your competitors
   - Re-run; check the output

4. **Build domain_overrides.yml gradually**
   - Run keywords
   - Find misclassifications
   - Add overrides
   - Repeat until you've covered your market

---

## Configuration System Philosophy

**The core idea:**

> Configuration is where your judgment lives. Code is generic; files are specific. As you learn your market, you encode that learning in files. Over time, your config files become a repository of domain expertise.

**Example:**
- You discover: "Therapists on Psychology Today are always investigated by searchers, never booked directly from their profiles."
- You encode this: A rule in `intent_mapping.yml` that says "service page on directory domain = commercial_investigation, not transactional"
- Next time you run keywords: That rule auto-applies to Psychology Today profiles

**This is why we have the Configuration Manager.** No more "quick fix in Python code." Just edit the config file, and you're done.

---

## Questions This Guide Answers

✓ "What are the 9 tabs in Edit Configuration?" → See the table above
✓ "What does each tab do?" → See CONFIGURATION_GUIDE.md
✓ "Are entity types auto-generated?" → No; you override them in domain_overrides.yml
✓ "How do I build the strategic patterns?" → Clinically, based on observation; see Strategic Patterns section
✓ "How do I manage this for multiple clients?" → See MULTI_CLIENT_ARCHITECTURE.md
✓ "Which files should be per-client?" → See the table above
✓ "How do I add a new client?" → Copy the _template/ directory; edit config & domain_overrides

---

## Resources

| Document | When to Read | Time |
|----------|-------------|------|
| **CONFIG_QUICK_START.md** (this file) | First thing | 5 min |
| **CONFIGURATION_GUIDE.md** | To understand each tab | 30 min |
| **MULTI_CLIENT_ARCHITECTURE.md** | To plan multi-client setup | 45 min |
| config_manager.py source | To implement GUI changes | 20 min |
| CLAUDE.md (project instructions) | To understand project structure | 10 min |

---

## One More Thing

**The Configuration Manager has built-in help.** In the GUI:
- Each tab has a help text at the top
- Each field has a tooltip (hover over the `?` icon)
- Validation errors are detailed and actionable

Use the GUI help; it's often faster than reading docs.

Good luck! 🚀
