# Configuration System for Any Small Business or Nonprofit

## The Core Insight

This configuration system was built for Living Systems Counselling (a Bowen therapy nonprofit), but **the architecture is completely industry-agnostic.**

Replace "therapy patterns" with "customer behavior patterns," and this tool works for:
- A local plumbing company
- An animal shelter
- A yoga studio
- A home renovation contractor
- A nonprofit food bank
- A digital marketing agency
- A dental practice
- A dog training business

**The config files don't care what industry you're in.** They're about capturing your business judgment.

---

## Generic Translation Guide

### Therapy-Specific → Any Business

| Therapy Term | Generic Term | What It Means |
|--------------|-------------|---------------|
| **Bowen pattern** | **Customer behavior pattern** | A recurring way customers think/act when searching |
| **Therapeutic reframe** | **Value proposition** | How you'd reposition that behavior toward your solution |
| **Status quo message** | **Customer's current belief** | What they currently believe (often limiting) |
| **Bowen bridge reframe** | **Your differentiator** | How your business solves it differently |
| **Content angle** | **Content strategy** | How you'd write content addressing this |
| **Clinical framework** | **Business framework** | Your unique approach (how you differentiate) |
| **Trigger words in PAA questions** | **Pain point keywords** | Words revealing what customers actually want |
| **Entity type: counselling provider** | **Entity type: service provider** | The type of business |
| **Systemic thinking** | **Systemic thinking** | Customers thinking about root causes (not just symptoms) |
| **Medical model thinking** | **Transactional thinking** | Customers just want quick fixes, not deep solutions |

---

## Example: Generalizing for Different Industries

### Example 1: Local Plumbing Company

**Original (Therapy):**
```yaml
- Pattern_Name: The Medical Model Trap
  Triggers: [diagnosis, treatment, disorder, clinical]
  Status_Quo_Message: You need an expert to fix your problem
  Bowen_Bridge_Reframe: You need to understand your system so you can maintain it
  Content_Angle: Why understanding your plumbing system prevents expensive repairs
```

**Generalized (Plumbing):**
```yaml
- Pattern_Name: The Quick Fix Trap
  Triggers: [emergency, immediate, urgent, now]
  Status_Quo_Message: I just need someone to fix this right now
  Differentiator: Prevention education saves money long-term
  Content_Angle: Why understanding your plumbing system prevents expensive emergency repairs
```

**What changed:**
- Pattern name: Medical → Quick Fix (captures the same trap: short-term thinking)
- Triggers: Same concept (urgency signals same behavior as seeking diagnosis)
- Status quo: Clinical framing → transactional framing
- Reframe: System understanding → system maintenance understanding
- Angle: Same idea: "understand your system"

---

### Example 2: Animal Shelter

**Generalized for Animal Rescue:**
```yaml
- Pattern_Name: The Impulse Adoption Trap
  Triggers: [cute, adorable, right now, perfect match, love at first sight]
  Status_Quo_Message: I found the perfect pet, adoption will solve my loneliness
  Differentiator: Successful adoptions need preparation and realistic expectations
  Content_Angle: Why taking time to prepare your home prevents adoption failure and heartbreak
```

**What this captures:**
- Customer belief: Emotional connection = successful pet ownership
- Your differentiation: Thoughtful matching and preparation
- Content angle: Education on responsible adoption

---

### Example 3: Nonprofit Food Bank

**Generalized for Food Security:**
```yaml
- Pattern_Name: The Shame Trap
  Triggers: [free food, charity, struggling, ashamed, stigma, judgment]
  Status_Quo_Message: Accepting help means I've failed
  Differentiator: Food security is about systems, not shame. Everyone needs help sometimes.
  Content_Angle: Reframe accessing food assistance as a smart, practical choice (not failure)
```

---

### Example 4: Digital Marketing Agency

**Generalized for Growth-Stage Startups:**
```yaml
- Pattern_Name: The DIY Trap
  Triggers: [do it yourself, cheap, free tools, save money, self-serve]
  Status_Quo_Message: I can handle marketing alone with free tools
  Differentiator: Strategic marketing saves time and gets better ROI than DIY
  Content_Angle: Hidden costs of DIY marketing: opportunity cost, mistakes, wasted months
```

---

## Mapping the 9 Config Files to Any Business

### 1. Intent Mapping → Search Intent Classification
**What it does:** Determines what a customer actually wants when they search.

**Generic examples:**
```
Plumbing: "Emergency plumbing" + local pack = local intent (they want NOW)
Yoga: "Best yoga classes" + reviews present = commercial investigation (comparing studios)
Food bank: "Food assistance near me" + nonprofit directory = informational (researching options)
Dog training: "How to train a dog" + service results = informational (learning)
```

**Why it matters:** Wrong intent → wrong strategy
- Plumber targeting "emergency plumbing" for education? Wrong.
- Yoga studio ignoring "beginner yoga near me" (commercial)? Wrong.

---

### 2. Domain Overrides → Competitor Classification
**What it does:** Manual corrections for auto-classification.

**Generic examples:**

For a **local plumber** in Vancouver:
```yaml
angi.com: directory            # Reviews platform, not a plumber
yelp.ca: directory             # Review site
yourlocallplumber.com: competitor_plumber
bestplumbing.ca: competitor_plumber
```

For a **dog training studio**:
```yaml
akc.org: professional_association    # Breed organization
rover.com: directory                 # Pet marketplace, not a trainer
cesarsalesdogtraining.com: competitor_trainer
```

For a **nonprofit food bank**:
```yaml
findhelp.org: directory              # Social service aggregator
foodrescue.ca: partner_nonprofit     # Partner, not competitor
```

---

### 3. Customer Behavior Patterns → Strategic Patterns
**What it does:** Defines recurring customer mindsets and how to address them.

**Generic structure:**
```yaml
- Pattern_Name: [Describe the customer's limiting belief]
  Triggers: [Words that signal this belief]
  Status_Quo_Message: [What they currently think]
  Differentiator: [How you think differently]
  Content_Angle: [How you'd teach/reposition]
```

**For any business, patterns answer:**
- What do customers want?
- What limits them from getting it?
- How do we think differently?
- How do we communicate that?

---

### 4. Pattern Routing → Customer Segment Routing
**What it does:** Maps customer behavior patterns to PAA questions they're asking.

**Example for yoga studio:**
```yaml
Pattern_Name: The Perfectionism Trap
PAA_Themes: [beginner, anxiety, confidence, judgment]
PAA_Categories: [self-doubt, starting out, nervous]
Keyword_Hints: [beginner, nervous, first time, no experience]
Intent_Slot_Descriptions: Overcome beginner anxiety through supportive community
```

**The logic:**
- You identified "perfectionism trap" (customer belief: yoga requires flexibility/experience)
- People searching "beginner yoga for stiff people" are stuck in this trap
- Your content addresses: "Yoga isn't about being good; it's about showing up"

---

### 5. Intent Classifier Triggers → Customer Vocabulary Classification
**What it does:** Identifies whether PAA questions show surface-level vs. deep-thinking customers.

**Generic mapping:**
```yaml
surface_level_triggers:          # Quick fix, symptom relief
  multi_word: [how to quickly, best quick fix, fast solution, urgent help]
  single_word: [emergency, cheap, quick, fast]

deep_thinking_triggers:          # System-level understanding
  multi_word: [how to prevent, what causes, why does, root cause]
  single_word: [prevent, understand, system, sustainable]
```

**This applies to ANY business:**
- Plumber: "emergency plumbing" (surface) vs. "prevent pipe problems" (deep)
- Yoga: "best stress relief class" (surface) vs. "how to manage anxiety long-term" (deep)
- Food bank: "where to get free food" (surface) vs. "how to build food security" (deep)
- Dog training: "stop my dog barking" (surface) vs. "why does my dog bark" (deep)

---

### 6. Classification Rules → Entity Type Dictionary
**What it does:** Defines what types of competitors/resources exist in your market.

**Generic structure:**
```json
{
  "entity_types": [
    "direct_service_provider",      (you)
    "directory_or_marketplace",     (Yelp, Angi, Rover, etc.)
    "educational_resource",         (Wikipedia, blogs, courses)
    "competitor_provider",          (other plumbers, trainers, studios)
    "government_agency",            (licensing, regulation)
    "nonprofit_partner",            (related nonprofits, social services)
    "media_or_review_site",         (news, reviews)
    "professional_association"      (accrediting bodies)
  ],
  "entity_type_descriptions": {
    "direct_service_provider": "You provide the service",
    "directory_or_marketplace": "Aggregates providers (you're one of many)",
    "competitor_provider": "Another provider offering similar service",
    ...
  }
}
```

**Customize for your market:**
- Yoga studio: Add "yoga_equipment_retail" (not a competitor, but appears in searches)
- Food bank: Add "government_assistance_program" (relevant but not direct competitor)
- Plumber: Add "hardware_store" (for DIY searches)

---

### 7. Config Settings → Operational Settings
**What it does:** Client info, location, thresholds, API keys.

**Generic fields** (same across all industries):
```yaml
client:
  preferred_intents: [what your business can produce content for]
  client_da: 35                    [domain authority in your niche]

feasibility:
  neighborhoods: [areas you serve]
  client_location: [your location]

analysis_report:
  client_name: [your business name]
  client_domain: [your website]
  org_type: [what you are: small business, nonprofit, agency, etc.]
  framework_description: [your unique approach]
```

**Examples:**

Plumbing company:
```yaml
client:
  client_name: Mike's Plumbing Vancouver
  client_domain: mikesplumbing.ca
  org_type: Small family plumbing business, established 2010
  framework_description: Same-day emergency service + preventative education
  preferred_intents: [local, transactional]
  
feasibility:
  client_da: 28
  neighborhoods: [Vancouver, Burnaby, East Van]
```

Dog training studio:
```yaml
client:
  client_name: Positive Paws Training
  org_type: Independent dog training studio
  framework_description: Positive reinforcement; working WITH the dog's nature
  preferred_intents: [informational, transactional, commercial_investigation]
  
feasibility:
  client_da: 22
  neighborhoods: [Downtown, North Shore, Eastside]
```

---

### 8. URL Pattern Rules → Content Classification Fallback
**What it does:** Guess page type from URL when HTML analysis fails.

**Generic examples:**
```yaml
# For any service business
- pattern: '/(blog|article|resource)/'
  content_type: educational_guide

- pattern: '/(service|product)/'
  content_type: product_page

- pattern: '/(pricing|rates)/'
  content_type: pricing_page

- pattern: '/testimonial|review|case-study/'
  content_type: social_proof

# Industry-specific
# Yoga studio:
- pattern: '/class-schedule/'
  content_type: service_listing

# Plumber:
- pattern: '/(drain|pipe|water)/'
  content_type: service_page

# Dog training:
- pattern: '/training-methods/'
  content_type: educational_guide
```

---

## Multi-Client Setup for Any Industry

### Directory Structure

Same for plumbing, yoga, food bank, whatever:

```
your-tool/
  serp-me.py
  
  clients/
    _template/
      config.yml
      domain_overrides.yml
      intent_mapping.yml
      customer_behavior_patterns.yml    [renamed from strategic_patterns.yml for clarity]
      pattern_routing.yml               [renamed from brief_pattern_routing.yml]
      intent_classifier_triggers.yml
      classification_rules.json
      url_pattern_rules.yml
      README.md
    
    mikes_plumbing/
      config.yml                        [Vancouver, DA 28]
      domain_overrides.yml              [plumbing competitors]
      customer_behavior_patterns.yml    [Quick Fix Trap, DIY Trap, etc.]
      ...
    
    positive_paws_training/
      config.yml                        [Downtown, DA 22]
      domain_overrides.yml              [dog training competitors]
      customer_behavior_patterns.yml    [Punishment Trap, etc.]
      ...
    
    nonprofit_food_bank/
      config.yml                        [North Vancouver, DA 15]
      domain_overrides.yml              [food security resources]
      customer_behavior_patterns.yml    [Shame Trap, Dependency Trap, etc.]
      ...
```

---

## Generalizing the Language

### In documentation and code:

**Original (Therapy):**
- "Bowen patterns"
- "Strategic patterns"
- "Therapeutic reframe"
- "Patient"
- "Therapy domain"

**Generalized:**
- "Customer behavior patterns"
- "Market patterns"
- "Value proposition" or "Differentiation"
- "Customer" or "Prospect"
- "Service domain" or just "domain"

---

## Real-World Example: Converting to Plumbing

**Starting point:** Living Systems' config for Bowen counselling

**Step 1: Rename files for clarity**
```
strategic_patterns.yml → customer_behavior_patterns.yml
brief_pattern_routing.yml → customer_segment_routing.yml
```

**Step 2: Replace pattern content**

Before (Bowen therapy):
```yaml
- Pattern_Name: The Medical Model Trap
  Triggers: [diagnosis, disorder, medication, symptoms]
  Status_Quo_Message: I'm broken and need an expert to fix me
  Bowen_Bridge_Reframe: You're not broken; you need to understand your system
  Content_Angle: Stop seeking diagnosis; start understanding your relational patterns
```

After (Plumbing):
```yaml
- Pattern_Name: The Emergency-Only Trap
  Triggers: [emergency, burst, leak, flood, urgent, NOW]
  Status_Quo_Message: I'll ignore plumbing until something breaks
  Differentiator: Prevention costs less than emergencies
  Content_Angle: Preventative plumbing maintenance saves 10x more than emergency repairs
```

**Step 3: Adjust domain_overrides.yml**

Before (Therapy):
```yaml
psychologytoday.com: directory
zencare.co: directory
```

After (Plumbing):
```yaml
angi.com: directory
yelp.ca: directory
home-depot.ca: hardware_retailer
```

**Step 4: Adjust config.yml**

Before:
```yaml
client_name: Living Systems Counselling
framework_description: Bowen Family Systems Theory
preferred_intents: [informational, transactional, local]
```

After:
```yaml
client_name: Mike's Plumbing Vancouver
framework_description: Same-day emergency response + preventative education
preferred_intents: [local, transactional, commercial_investigation]
```

**Done.** Now you have a plumbing tool.

---

## Why This Works for Any Industry

### The Config System is About:

1. **Understanding your market** (what entities exist, which are competitors)
   - Therapy: therapists, directories, nonprofits
   - Plumbing: plumbers, hardware stores, directories, suppliers
   - Yoga: studios, fitness centers, online classes, app platforms

2. **Understanding customer intent** (what do they actually want when they search?)
   - Therapy: informational vs. transactional vs. local
   - Plumbing: emergency vs. preventative vs. shopping
   - Yoga: beginner class vs. specific style vs. membership

3. **Understanding customer mindsets** (what limits them from choosing you?)
   - Therapy: shame, blame, fusion
   - Plumbing: DIY culture, cost anxiety, trust in brand names
   - Yoga: perfectionism, fitness anxiety, style snobbery
   - Food bank: shame, pride, not knowing it's available

4. **Your differentiation** (how you solve their limiting belief)
   - Therapy: system-thinking vs. pathology-thinking
   - Plumbing: education + emergency service vs. just emergency
   - Yoga: community + skill-building vs. individual performance
   - Food bank: dignity-centered access vs. charity/shame

5. **How to talk to them** (content that addresses the mindset)
   - Therapy: Bowen reframing
   - Plumbing: "Here's why prevention matters"
   - Yoga: "You're not behind; you're starting"
   - Food bank: "Food security is smart planning, not shame"

**The tool doesn't care about the specifics. It's a framework for capturing business judgment.**

---

## Adapting the Docs for Your Industry

If you're using this for a plumbing company, rewrite:

**Original:** "Strategic Patterns: Bowen Family Systems therapeutic reframing patterns"

**Generalized:** "Customer Behavior Patterns: Common limiting beliefs your customers hold, and how your business addresses them"

**Then provide examples for your industry:**

```
Pattern: The DIY Trap
Triggered by: "I can do it myself", "YouTube tutorials", "hardware store sells it"
Belief: "Plumbing is simple; professionals are ripping me off"
Your angle: "Complex systems need trained diagnosis. You might save $500 now, 
            but miss the main pipe problem ($5k later)"
```

---

## Checklist: Generalizing for Your Business

- [ ] Rename files for clarity (strategic_patterns → customer_behavior_patterns, etc.)
- [ ] Replace pattern content with your customer mindsets
- [ ] Update domain_overrides with your actual competitors
- [ ] Update config.yml with your business details
- [ ] Update classification_rules with your entity types
- [ ] Update intent mapping if your intent types differ (or keep as-is)
- [ ] Update trigger vocabularies for your customer language
- [ ] Test: Run sample keywords in your industry
- [ ] Update documentation to use your industry terminology
- [ ] Build domain_overrides gradually as you run keywords

---

## Summary: It's Not About Therapy

The configuration system is **industry-agnostic** because it's about:

✓ Classifying what types of entities exist in your market
✓ Understanding what customers actually want (intent)
✓ Identifying limiting beliefs that drive search behavior
✓ Encoding your business differentiation in content strategy
✓ Managing this for multiple clients

Whether you're a therapist, plumber, yoga studio, or food bank, the framework is identical.

Just swap the content. The structure stays the same.

---

## Next: What to Actually Change

If you're building this for **[Your Industry]**:

1. Read CONFIGURATION_GUIDE.md (the logic applies universally)
2. For each file, mentally swap:
   - "Counselling" → "[Your service type]"
   - "Bowen patterns" → "[Your customer mindsets]"
   - "Therapeutic reframe" → "[Your value proposition]"
3. Rebuild customer_behavior_patterns.yml with YOUR patterns
4. Rebuild domain_overrides.yml with YOUR competitors
5. Update config.yml with YOUR business details

The rest (intent_mapping.yml, classification_rules.json, url_pattern_rules.yml) mostly stays the same across industries.

Done! Now you have a market intelligence tool for your business.
