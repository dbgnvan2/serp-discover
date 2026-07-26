# Configuration Manager Guide: Understanding & Managing the Configuration Tabs

## Overview: What is the Configuration System?

The SERP Discovery Tool uses **9 configuration files** that control how the application:
1. **Classifies** what people are searching for (their intent)
2. **Identifies** which domains are which type of organization (entity classification)
3. **Routes** content briefs to match Bowen family systems patterns in user behavior
4. **Runs** the tool (API keys, output paths, thresholds)

The **Configuration Manager** (the "Edit Configuration" button) gives you a GUI to edit all 9 files without touching code or text editors. Each tab manages one file.

**Key principle:** Configuration lives in files, not code. When you find yourself wanting to change behavior (add a new pattern, adjust a rule, override a classification), you should almost never touch Python. Instead, edit the config files. This is why the Configuration Manager exists.

---

## The 9 Configuration Tabs: What They Do & Where Data Comes From

### 1. **Intent Mapping** (`intent_mapping.yml`)

#### What it does
Decides what a searcher actually wants based on **4 factors** found in a Google SERP:
- **Content Type** — What kind of page? (service page, blog guide, directory profile, news article, PDF, etc.)
- **Entity Type** — Who runs the domain? (counselling provider, directory, nonprofit, government, etc.)
- **Local Pack** — Is there a Google Local 3-pack visible in the SERP? (yes/no)
- **Domain Role** — Whose domain is it? (your client's, a known competitor's, or someone else's)

The tab displays this as a **rule table**. Rules are evaluated **top-to-bottom; first match wins**.

#### Example
```
Content Type: guide
Entity Type: counselling
Local Pack: yes
Domain Role: other
→ Intent: informational (not local, because a guide is informational even if the SERP has a map pack)
```

#### What it impacts
- **Every keyword's intent distribution** (what % are searches where people want information vs. ready to transact vs. comparing options)
- **Content strategy recommendations** (wrong intent = wrong strategy)
- **Feasibility scoring** (if intent is wrong, feasibility becomes unreliable)

#### How to obtain/create these rules
**Sources:**
1. **You observe SERPs manually** — Run keywords through Google and look at what appeared. Does the SERP have a local pack? What kind of pages rank? What do they look like?
2. **The system infers entity & content type** — The tool automatically classifies each URL using:
   - HTML enrichment (reads the page, looks for clues)
   - Domain overrides (you manually say "psychologytoday.com is always a directory")
   - URL pattern fallbacks (regex patterns like `/therapist/` hint at content type)
3. **You decide the intent** — After seeing the classification, you decide: "When I see a [guide] on a [counselling] domain with [local pack], searchers want [informational] content, not transactional."

#### When to edit
- You run keywords and notice the intent assignments feel wrong
- A brief says "this keyword is transactional" but the SERP is clearly informational
- A competitor classification changed (a directory now looks like a direct service) and rules need to reflect that

#### Multi-client implications
**Each client may have different intent patterns:**
- A large national counselling company might want to rank for "telehealth therapy" (transactional on non-local SERPs)
- A small local nonprofit wants to rank for "counselling in North Vancouver" (local intent)

You'll need separate `intent_mapping.yml` files per client. The intent rules encode the client's business model.

---

### 2. **Domain Overrides** (`domain_overrides.yml`)

#### What it does
A simple lookup table: **domain → entity type**. When the automatic classifier guesses wrong, you override it here.

#### Example
```
psychologytoday.com: directory  (not counselling, even though profiles look like service pages)
amazon.ca: media                (not counselling)
bcacc.ca: professional_association
```

#### What it impacts
- How every URL on that domain is classified going forward
- Which intent rules apply (since entity type is part of the match)
- Competitor vs. non-competitor grouping (determines domain_role in intent mapping)

#### How to obtain/create this data

**This is NOT auto-generated.** You manually build it by:

1. **Run keywords** through the tool
2. **Look at the output** — Find URLs where the entity type looks wrong
3. **Add the override** — Domain + correct entity type
4. **Re-run** — The next analysis will use the override

**Pattern recognition:**
- First time through, you might have 20-30 overrides
- As you collect more keywords, you discover patterns (e.g., "all .gov.bc.ca sites are government")
- You add batches at a time

**Where entity types come from:**
- They're defined in `classification_rules.json` (the "valid entity types")
- Current list: `counselling`, `legal`, `directory`, `nonprofit`, `government`, `media`, `professional_association`, `education`
- You can add new types if needed (edit the Classification Rules tab)

#### When to edit
- The tool classified a domain wrong and you see it affecting multiple keywords
- You onboard a new client with a different competitor set

#### Multi-client implications
**Each client has a different competitor list.** For Living Systems (nonprofit counselling):
- `psychologytoday.com` is a directory
- But for a large private therapy practice, Psychology Today is a competitor directory

You need separate `domain_overrides.yml` per client. This file is **client-specific**.

---

### 3. **Strategic Patterns** (`strategic_patterns.yml`)

#### What it does
Defines **Bowen Family Systems therapeutic reframing patterns**. Each pattern captures a common trap that searchers are stuck in, plus how to reframe it.

#### Example
```
Pattern Name: The Blame/Reactivity Trap
Triggers: narcissist, toxic, abusive, mean, angry, hate
Status Quo: The problem is the other person
Bowen Bridge Reframe: Focus on self-regulation. You can't change them, only your response.
Content Angle: Stop diagnosing the other person and start observing your own reactivity.
```

#### What it impacts
- **Content brief routing** — When a brief detects these trigger words in PAA questions, it can mention this pattern
- **Keyword research strategy** — Helps identify keyword clusters that signal the same underlying trap
- **Content creation** — Tells content creators: "People searching with these words are stuck in this trap. Here's the reframe."

#### How to obtain/create these patterns

**This comes from your clinical/therapeutic expertise or your client's.**

For Living Systems, patterns are Bowen theory-based:
- Drawn from Bowen theory literature
- Validated through clinical experience
- Refined by observing what triggers appear in real SERP ngrams

**Process:**
1. Identify a common emotional/relational trap you see in therapy
2. Give it a name (pattern_name)
3. List trigger words that signal this trap (minimum 4-5, each 4+ chars)
4. Write the status quo message (what the stuck person believes)
5. Write the Bowen reframe (the systemic view)
6. Describe the content angle (how to write content that addresses this)

#### When to edit
- Your clinical team identifies a new common pattern in client calls
- You refine an existing pattern based on SEO data (e.g., "the triggers aren't showing up; let's revise them")

#### Multi-client implications
**These are highly client-specific.** They depend on:
- The client's therapeutic framework (Bowen? CBT? Attachment theory?)
- The patterns they see in their client base
- The content angles they want to emphasize

Living Systems uses Bowen patterns. A CBT-based practice would have different patterns.

You need separate `strategic_patterns.yml` per client.

---

### 4. **Brief Pattern Routing** (`brief_pattern_routing.yml`)

#### What it does
Maps each strategic pattern to **PAA (People Also Ask) themes, categories, and keyword hints**. This determines:
- Which PAA questions belong to which pattern?
- What keywords suggest this pattern is relevant?
- How should the pattern appear in the content brief?

#### Example
```
Pattern Name: The Blame/Reactivity Trap
PAA Themes: relationships, conflict, communication, family
PAA Categories: toxic, narcissist, deal-with, boundaries
Keyword Hints: narcissist, toxic, abusive, mean
Intent Slot Descriptions: Identify reactive patterns in relationships
```

#### What it impacts
- **Content briefs** — When generating a brief for a keyword, it mentions patterns relevant to that keyword
- **PAA question organization** — Groups PAA questions by pattern
- **Content angle clarity** — Ties each pattern to concrete PAA questions users are asking

#### How to obtain/create this data

**Built by:**
1. Running keywords and collecting PAA questions
2. Reading the PAA questions and identifying patterns
3. Assigning PAA themes/categories that align with patterns
4. Setting keyword hints (words in the keyword that trigger this pattern)

**Example workflow:**
- Keyword: "how to deal with a narcissist spouse"
- PAA Questions appearing: "Is narcissism genetic?", "How to set boundaries with a narcissist", "Should I divorce a narcissist?"
- Pattern match: The Blame/Reactivity Trap (external locus - blaming the other person)
- Route: Add "narcissist" as a keyword hint, add "relationships" as a PAA theme

#### When to edit
- You run new keywords and see PAA patterns that don't match existing routing
- A pattern's keyword hints aren't showing up in search data (they're too rare/specific)
- You add a new pattern and need to define its routing

#### Multi-client implications
**Depends on:**
- Which patterns are relevant to this client's keywords
- What PAA themes appear in their target audience's searches
- What content angles the client wants to emphasize

For Living Systems: patterns route to PAA themes about family, relationships, communication.
For a corporate wellness firm: patterns might route to PAA themes about productivity, team dynamics, stress.

You need separate `brief_pattern_routing.yml` per client.

---

### 5. **Intent Classifier Triggers** (`intent_classifier_triggers.yml`)

#### What it does
Classifies PAA (People Also Ask) questions into two vocabularies:
- **Medical triggers** — Language revealing pathology/external locus thinking ("diagnosis", "mental health", "treatment", "coping strategies")
- **Systemic triggers** — Language revealing systems thinking ("patterns", "differentiation", "how can we", "boundaries")

This helps briefs identify whether PAA questions are already aligned with the client's framework or oriented toward a different model.

#### Example
```
Medical Triggers:
  - anxiety disorder
  - should I medicate
  - coping strategies
  
Systemic Triggers:
  - differentiation
  - family patterns
  - pursue-distance
```

#### What it impacts
- **Content brief classifications** — Labels PAA questions by worldview
- **Content routing** — Identifies which questions need the "bridge" reframe vs. are already aligned
- **Confidence scoring** — If all PAA questions are medical-model, brief signals "audience is not yet ready for Bowen language"

#### How to obtain/create this data

**Built by:**
1. Collecting real PAA questions from your keywords
2. Reading them and identifying language patterns
3. Coding triggers that appear in medical-model vs. systems-model questions

**Example:**
- PAA question: "How do I know if I have anxiety disorder?"
- Contains: "anxiety" (medical) + "disorder" (medical)
- Classification: Medical-model external locus

#### When to edit
- You run keywords and see PAA questions that don't fit either vocabulary
- The triggers are too generic (matching everything) or too specific (matching nothing)
- Your client's framework changes and you need different trigger vocabularies

#### Multi-client implications
**Different frameworks use different language:**
- Bowen practices: "differentiation", "patterns", "emotional process"
- Trauma-informed: "trigger", "nervous system", "grounding"
- CBT: "thoughts", "beliefs", "automatic thoughts"

You need separate `intent_classifier_triggers.yml` per client if their therapeutic framework differs.

---

### 6. **Classification Rules** (`classification_rules.json`)

#### What it does
Defines **two things:**

1. **Valid Entity Types** — The official list of organization types the system recognizes
   - Current: counselling, legal, directory, nonprofit, government, media, professional_association, education

2. **Entity Type Descriptions** — Human-readable descriptions for each type
   - counselling: "Direct counselling or therapy service providers"
   - directory: "Sites that list therapists/providers but don't provide services themselves"

#### What it impacts
- **All dropdowns** in intent_mapping, domain_overrides, and other config tabs show these types
- **Validation** — Only these types are allowed in domain_overrides
- **Documentation** — Clarifies to users what each type means

#### How to obtain/create this data

**This is usually NOT changed; it's foundational.** But if you work with a new organization type:

1. **Identify a new type** — E.g., "health_app" (digital mental health platform)
2. **Add it** via the Classification Rules tab (+ Add Type button)
3. **Write a description** — "Mobile or web apps providing self-guided mental health tools"
4. **Use it** — Now available in domain_overrides

#### When to edit
- You encounter domain types the system doesn't have (e.g., "health_app")
- You want to split an existing type (e.g., "counselling" → "counselling_individual" + "counselling_group")
- You refine descriptions for clarity

#### Multi-client implications
**Usually shared across clients** unless you're serving very different industries. For Living Systems, this stays constant. But if you serve a health tech client, you'd add health_app, digital_mental_health, etc.

Can be shared or per-client depending on domain diversity.

---

### 7. **Config Settings** (`config.yml`)

#### What it does
Operational settings for the entire tool:
- **API keys & credentials** — SerpAPI, DataForSEO, Moz
- **Search parameters** — Geography (gl: ca), language (hl: en), location (Vancouver, BC)
- **File paths** — Input CSV, output folder
- **Thresholds** — Domain Authority gap, feasibility thresholds, intent confidence levels
- **Client context** — Client name, domain, organization type (for reports)
- **Enrichment settings** — Whether to fetch extra domain data, how many URLs per keyword

#### What it impacts
- **Everything** — API behavior, output, feasibility scoring, report generation

#### How to obtain/create this data

**Most values are client-specific or operational:**

| Setting | Where it comes from | Example |
|---------|-------------------|---------|
| **serpapi.gl** | Client's geography | `ca` for Canada |
| **serpapi.hl** | Client's language | `en` for English |
| **serpapi.location** | Client's location | `Vancouver, British Columbia, Canada` |
| **client.preferred_intents** | What content the client can produce | `[informational, transactional, local]` |
| **feasibility.client_da** | Client's Domain Authority | `35` (estimated or from SEMrush/Moz) |
| **feasibility.neighborhoods** | Local areas client serves | `[West Vancouver, North Vancouver, Lynn Valley]` |
| **analysis_report.client_name** | Client name | `Living Systems Counselling` |
| **analysis_report.org_type** | Organization description | `Small nonprofit counselling organization, established 1971` |
| **serp_intent.thresholds.*** | Intent confidence tuning | `primary_share: 0.6` (60% threshold) |

#### When to edit
- Change client's location or language
- Update client's Domain Authority (from DA lookup tool)
- Adjust thresholds based on real-world results ("60% threshold is too high, lower to 50%")
- Add new client neighborhoods
- Update input/output file paths (usually auto-done by GUI)

#### Multi-client implications
**Entirely per-client.** Each client has:
- Different geography
- Different feasibility targets
- Different capabilities (which intents they can produce)
- Different DA
- Different neighborhoods/locations

You need **separate `config.yml` per client**. This is the most client-specific file.

---

### 8. **URL Pattern Rules** (`url_pattern_rules.yml`)

#### What it does
**Fallback content classification rules.** When the HTML enricher can't determine page type (e.g., page behind a paywall, JavaScript-rendered, or slow to load), these regex patterns guess the content type from the URL.

#### Example
```
- pattern: '/therapist/'
  content_type: service

- pattern: '/blog/'
  content_type: guide

- pattern: '/(articles?|news)/'
  content_type: news
```

#### What it impacts
- **Classification completeness** — Higher % of URLs get classified
- **Classification accuracy** — When HTML can't be read, URL patterns are a backup

#### How to obtain/create this data

**Built by:**
1. Collecting URLs that failed HTML enrichment
2. Looking at their paths and guessing content type from pattern
3. Adding regex patterns that match the pattern

**Example workflow:**
- URL: `https://mysite.com/resources/getting-started-with-therapy/`
- Failed HTML enrichment
- Path pattern: `/resources/` + `/getting-started/` → likely a guide
- Add pattern: `'/resources/'` → `guide`

#### When to edit
- You see many URLs classified as "unknown" and want to improve
- You notice a pattern in URLs that keeps getting misclassified

#### Multi-client implications
**Somewhat client-specific** (their URL structure is unique) but mostly shared pattern concepts apply across clients.

Can be shared or per-client depending on URL diversity.

---

### 9. **Intent Classifier Triggers** (Already covered above in #5)

---

## How Data Flows Between Tabs

Here's how everything connects:

```
1. Domain Overrides (manual)
   ↓
   Tells system: "example.com is a [counselling provider]"

2. URL Enrichment (automatic + fallback to URL Patterns)
   ↓
   Classifies each URL as: content_type + entity_type

3. Intent Mapping (rules)
   ↓
   Matches: (content_type, entity_type, local_pack, domain_role)
   → Returns: intent (informational, transactional, etc.)

4. Intent Classifier Triggers
   ↓
   Classifies PAA questions: medical-model vs. systemic-model

5. Strategic Patterns + Brief Pattern Routing
   ↓
   Routes patterns to PAA themes/categories
   → Content brief mentions relevant patterns

6. Config Settings + Classification Rules
   ↓
   Operational parameters, client context, valid entity types
```

---

## Multi-Client Configuration Strategy

**The core question:** How do you run the tool for multiple clients?

**Answer:** Use a directory structure with per-client config bundles.

### Recommended Structure

```
serp-discover/
  serp-me.py                      (main app - unchanged)
  config.yml                      (symlink or fallback)
  domain_overrides.yml            (symlink or fallback)
  intent_mapping.yml              (symlink or fallback)
  [other shared files]
  
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
    
    other_client/
      config.yml
      domain_overrides.yml
      ... (same structure)
```

### How to Switch Clients

**Option 1: GUI File Picker**
- When you click "Edit Configuration", a dialog asks "Which client?"
- Loads the client's config directory
- All edits go to that client's files

**Option 2: Command-line Flag**
```bash
python3 serp-me.py --client living_systems
python3 serp-me.py --client other_client
```

**Option 3: Environment Variable**
```bash
export SERP_CLIENT=living_systems
python3 serp-me.py
```

### Per-Client vs. Shared Files

| File | Per-Client? | Reason |
|------|-----------|--------|
| `config.yml` | **YES** | Client's geography, DA, neighborhoods, org type |
| `domain_overrides.yml` | **YES** | Different competitor sets per client |
| `intent_mapping.yml` | **MAYBE** | If clients have different business models, yes |
| `strategic_patterns.yml` | **MAYBE** | If same therapeutic framework, shared; if different, per-client |
| `brief_pattern_routing.yml` | **MAYBE** | Tied to patterns; if patterns are shared, can share routing |
| `intent_classifier_triggers.yml` | **MAYBE** | If same framework/vocabulary, shared; if different, per-client |
| `classification_rules.json` | **SHARED** | Usually; unless clients operate in different domains |
| `url_pattern_rules.yml` | **SHARED** | URL patterns apply across most clients |

### Quick Multi-Client Setup Checklist

```
☐ Create clients/ directory
☐ Create living_systems/ subdirectory
☐ Copy all 8 YAML/JSON files to living_systems/
☐ Edit config.yml with Living Systems values
☐ Edit domain_overrides.yml with LS competitors
☐ Edit intent_mapping.yml if LS has unique intent patterns
☐ Edit strategic_patterns.yml if LS uses unique patterns
☐ Test: Run keywords for LS, verify output paths & client name
☐ Repeat for next client
☐ Update serp-me.py (or create launcher) to prompt for client selection
```

---

## Practical Example: Adding a New Client

Let's say you onboard **"Acme Therapy Group"** (Toronto-based, CBT-focused).

### Step 1: Create directory structure
```bash
mkdir -p clients/acme_therapy
```

### Step 2: Copy template files
```bash
cp *.yml *.json clients/acme_therapy/
```

### Step 3: Edit config.yml
```yaml
serpapi:
  location: Toronto, Ontario, Canada
  gl: ca

client:
  preferred_intents: [informational, commercial_investigation, transactional]

feasibility:
  client_da: 42
  neighborhoods: [Downtown Toronto, Midtown, Queen West]

analysis_report:
  client_name: Acme Therapy Group
  org_type: Private therapy practice, founded 2015
  framework_description: Cognitive Behavioral Therapy and Acceptance and Commitment Therapy
```

### Step 4: Edit domain_overrides.yml
Remove Living Systems-specific entries, add Acme's competitors:
```yaml
psychologytoday.com: directory
zencare.co: directory
betterhelp.com: directory
acmetherapy.com: counselling  (their own domain)
torontocbt.com: counselling   (competitor)
```

### Step 5: Edit strategic_patterns.yml
Replace Bowen patterns with CBT patterns:
```yaml
- Pattern_Name: The Catastrophizing Trap
  Triggers: [worst, catastrophe, terrible, disaster, ruined]
  Status_Quo_Message: "If one thing goes wrong, everything will fall apart"
  Bowen_Bridge_Reframe: "Anxiety overestimates threat. What evidence do you have?"
  Content_Angle: "How to reality-test catastrophic thoughts"
```

### Step 6: Edit intent_classifier_triggers.yml
Add CBT-specific triggers:
```yaml
medical_triggers:
  multi_word: [anxiety disorder, depression screening, coping strategies]
systemic_triggers:  # (for CBT, these are "behavioral" triggers)
  multi_word: [behavioral activation, exposure therapy, thought records]
```

### Step 7: Test
Run keywords for Acme → verify:
- Output files have "acme_therapy" in the name
- Report mentions Acme's location & framework
- Domain overrides working (psychologytoday.com classified as directory)
- Patterns are CBT-based (not Bowen)

Done! Now you can run `--client acme_therapy` whenever you work with Acme.

---

## Common Configuration Tasks

### Task: "My domain was misclassified"

1. Go to **Domain Overrides** tab
2. Click **+ Add**
3. Enter the domain and correct entity type
4. Click **Save**
5. Re-run analysis

### Task: "A rule is giving wrong intents"

1. Go to **Intent Mapping** tab
2. Find the rule (by reading the match conditions)
3. Click **Edit** (or select and click Edit button)
4. Change one of the conditions (content_type, entity_type, local_pack, domain_role)
5. Click **Save**

### Task: "Add a new Bowen pattern"

1. Go to **Strategic Patterns** tab
2. Click **+ Add Pattern**
3. Enter:
   - Pattern name (unique, no spaces)
   - Triggers (4-5 keywords, 4+ chars each, one per line)
   - Status quo message
   - Bowen reframe
   - Content angle
4. Click **Save**
5. (Optional) Go to **Brief Pattern Routing** and add PAA themes/keywords for the new pattern

### Task: "I want to change the client's Domain Authority"

1. Go to **Config Settings** tab
2. Find `feasibility.client_da`
3. Change the value (get from SEMrush, Moz, or estimate)
4. Click **Save**

### Task: "I need to support a new geography"

1. Go to **Config Settings** tab
2. Change `serpapi.location` (e.g., "Vancouver, BC" → "Toronto, ON")
3. Change `serpapi.gl` (e.g., "ca" stays same if still Canada)
4. Update `feasibility.neighborhoods` (the areas they serve)
5. Click **Save**

---

## Validation: What Happens When You Save?

Before writing files to disk, the Configuration Manager runs **four validation checks**:

1. **Schema validation** — Does the file match expected structure? (all required fields present?)
2. **Type validation** — Are entity types valid? Are intents valid?
3. **Cross-file validation** — Do strategic patterns have corresponding routing? Do domain overrides use valid entity types?
4. **Constraint validation** — Are there logical errors? (e.g., intent_mapping rules that can never match?)

If validation fails, you see detailed error messages. Fix and try again.

If validation passes, files are written and a backup is created automatically.

---

## Best Practices

1. **Test after major changes**
   - Edit a config file
   - Run a few test keywords
   - Check if behavior changed as expected

2. **Keep domain_overrides current**
   - Every time you run keywords, look for misclassifications
   - Add overrides as you discover them
   - Your domain_overrides file grows over time

3. **Document pattern rationale**
   - When you add a pattern, note in a comment why
   - Helps team members understand the clinical basis

4. **Use consistent naming**
   - Pattern names: use underscores, be descriptive ("the_blame_trap", not "bt1")
   - Trigger words: lowercase, searchable, not too generic

5. **Validate before deploying to production**
   - Use a test client first
   - Run real keywords
   - Review output carefully

6. **Version control**
   - Commit config changes when you deploy to a new client
   - Commit when you refine patterns based on data
   - Clean commit messages help track what changed and why

---

## Summary: The 9-Tab Quick Reference

| Tab | File | Client-Specific? | Created How | When to Edit |
|-----|------|------------------|-------------|--------------|
| **Intent Mapping** | intent_mapping.yml | Maybe | Manual observation | Rules feel wrong |
| **Domain Overrides** | domain_overrides.yml | Yes | Manual (as you find misclassifications) | Domain classified wrong |
| **Strategic Patterns** | strategic_patterns.yml | Maybe | Clinical expertise + SEO data | New pattern identified |
| **Brief Pattern Routing** | brief_pattern_routing.yml | Maybe | PAA data + pattern analysis | Pattern routing incomplete |
| **Intent Classifier Triggers** | intent_classifier_triggers.yml | Maybe | Real PAA corpus analysis | Vocabulary needs updating |
| **Classification Rules** | classification_rules.json | Shared | Rare; foundational | New entity/content type needed |
| **Config Settings** | config.yml | Yes | Client info (DA, location, name) | Client details change |
| **URL Pattern Rules** | url_pattern_rules.yml | Shared | URL analysis + regex patterns | Too many "unknown" classifications |

---

## Next Steps

1. **Explore the Configuration Manager** — Open serp-me.py, click "Edit Configuration"
2. **Read the inline help** — Each tab has context-sensitive help buttons
3. **Start with Domain Overrides** — Easiest to understand; immediate impact
4. **Work toward Intent Mapping** — More complex; biggest impact on strategy
5. **Plan your multi-client structure** — Decide which files are per-client vs. shared

Questions? The Configuration Manager's help text (accessible in each tab) explains every field and why it matters.
