# Serp-Discover: Market Intelligence User Manual

## Table of Contents
1. [Overview](#overview)
2. [Core Purpose](#core-purpose)
3. [How the System Works](#how-the-system-works)
4. [Workflow & Steps](#workflow--steps)
5. [Key Concepts](#key-concepts)
6. [Configuration](#configuration)
7. [Understanding Your Results](#understanding-your-results)
8. [Troubleshooting](#troubleshooting)

---

## Overview

**Serp-Discover** (Tool 1) is a market intelligence platform that analyzes what people are actually searching for in Google and identifies content opportunities for Living Systems Counselling.

**Client Focus:** Living Systems Counselling — a Bowen Family Systems Theory nonprofit in North Vancouver, BC.

**Core Goal:** Discover high-volume keywords, understand user intent (what people want), identify competitors, score how feasible it is to rank, and generate strategic content briefs that map search demand to content Living Systems can realistically create.

---

## Core Purpose

### The Problem

Living Systems Counselling needs to know:
- What are people searching for (couples counselling, family therapy, relationship anxiety)?
- What do those searches actually mean (are they looking for information? finding a therapist? understanding a concept)?
- Who ranks for those keywords today?
- How hard would it be for Living Systems to rank there?
- What content should Living Systems create to capture that traffic?

Without this intelligence, content creation is guesswork. You might write a page that no one is searching for, or miss high-value keywords where the competition is weak.

### The Opportunity

Serp-Discover answers these questions by:
1. **Mining search volume** — discovering what people are looking for at scale
2. **Classifying intent** — understanding whether searches are informational, commercial, local, or navigational
3. **Competitive analysis** — identifying who ranks and how strong they are
4. **Feasibility scoring** — calculating how hard each keyword is to rank for (Domain Authority gap)
5. **Content briefing** — using AI to map search intent to specific content Living Systems should create

---

## How the System Works

### Four Core Engines

#### 1. **SERP Fetcher**
**What it does:** Queries Google (via SerpAPI) and Google Maps to see what currently ranks for each keyword.

**How it works:**
- For each keyword, fetches top 3-10 organic results (configurable)
- Also fetches Google Local (Maps) results for location-based keywords
- Preserves SERP metadata: position, page title, snippet, URL, whether the domain appears in featured content

**Why:** You can't rank for a keyword you don't understand. Seeing the actual SERP for each keyword shows you what Google thinks is relevant, what competitors are doing, and what gaps exist.

---

#### 2. **Content Classifier**
**What it does:** Analyzes the top-10 ranking pages and classifies them by:
- **Content type:** Article, directory, review, social media, local business, etc.
- **Entity type:** Therapy practice, counseling directory, news site, Reddit discussion, etc.
- **Domain role:** Authority site, competitor, adjacent service, etc.

**How it works:**
- Fetches each top-10 URL and extracts page structure, metadata, and text patterns
- Applies classification rules: URL patterns, title patterns, content type triggers, domain history
- Uses manual overrides (domain_overrides.yml) to correct misclassified sites (e.g., forcing Psychology Today as a "directory")

**Why:** You need to know what kind of content ranks. If Living Systems ranks a blog post but competitors rank directories, Living Systems is competing on the wrong content type.

---

#### 3. **Intent Classifier**
**What it does:** Determines what type of search each keyword represents.

**How it works:**
- Analyzes the top-10 URLs for patterns:
  - **Informational:** "How to" titles, educational sites, Wikipedia-style content
  - **Commercial Investigation:** Product reviews, comparison pages, pricing guides
  - **Transactional:** Sign-up pages, booking flows, directory listings
  - **Local:** Google Maps, business directories, location-specific content
  - **Navigational:** Brand names, branded searches, domain-specific content

- Uses `intent_mapping.yml` rules: `(content_type, entity_type, local_pack, domain_role) → intent verdict`
- Calculates confidence: `high` (≥8 classified), `medium` (≥5), `low` (<5)
- Flags mixed-intent SERPs (e.g., "couples counselling" returns both local services AND educational content)

**Why:** Living Systems can only realistically create informational, local, and transactional content. If a keyword is pure commercial-investigation (product reviews), Living Systems shouldn't target it. Intent classification prevents chasing keywords that don't match your content type.

---

#### 4. **Feasibility Scorer**
**What it does:** Calculates how hard each keyword is to rank for using Domain Authority (DA) gap analysis.

**How it works:**
- Fetches Domain Authority for Living Systems (fixed value, e.g., 35)
- Fetches Domain Authority for top-5 competitors ranking for that keyword
- Calculates gap: `(average competitor DA) − (Living Systems DA)`
- Assigns feasibility level:
  - **High Feasibility:** Gap ≤ 5 (rankable with quality content alone)
  - **Moderate Feasibility:** Gap 6–15 (needs local backlinks)
  - **Low Feasibility:** Gap > 15 (high-authority incumbents, pivot suggested)

- Results are cached 30 days — re-running costs nothing
- For low-feasibility keywords, suggests neighbourhood pivots (e.g., "Couples Counselling" → "Couples Counselling Lonsdale")

**Why:** Not all keywords are worth targeting. If competitors have DA 60 and Living Systems has DA 35, ranking is nearly impossible without massive link building. Feasibility scoring helps you focus on winnable keywords.

---

### Data Flow

```
Keyword CSV
    ↓
SERP Fetcher (fetch top 10 for each keyword)
    ↓
Content Classifier (classify by type, entity, role)
    ↓
Intent Classifier (determine intent + confidence + distribution)
    ↓
Feasibility Scorer (calculate DA gap + rank difficulty)
    ↓
Market Analysis JSON (source of truth, intermediate output)
    ↓
Content Briefing Engine (LLM: analyze per-keyword, generate recommendations)
    ↓
Briefing outputs:
  - content_opportunities.md (per-keyword content roadmap)
  - advisory_briefing.md (executive framing)
  - feasibility.md (DA gap analysis)
```

---

## Workflow & Steps

The system executes in 7 optional steps (accessed via GUI launcher):

### **Step 1: Run Full Pipeline** (Required)
**What:** Fetches SERPs, classifies every URL, scores feasibility, writes JSON/XLSX/MD.

**Input:** Keyword CSV file (one keyword per row, no header)

**Process:**
1. Reads keyword CSV from location specified in `config.yml`
2. Fetches SERPs via SerpAPI (Google organic + Google Maps)
3. Extracts and enriches page metadata (content type, entity type, domain role)
4. Classifies intent for each keyword (informational / commercial / transactional / local / mixed)
5. Scores feasibility using Domain Authority gap analysis
6. Writes full results to JSON, XLSX, Markdown

**Output:**
- `market_analysis_<topic>_<timestamp>.json` — source of truth (all data for downstream steps)
- `market_analysis_<topic>_<timestamp>.xlsx` — same data in spreadsheet format
- `market_analysis_<topic>_<timestamp>.md` — Markdown summary
- `competitor_handoff_<topic>_<timestamp>.json` — validated competitor list for Tool 2 (Serp-Compete)

**Cost:** SerpAPI calls (~$0.002–$0.01 per keyword depending on mode). LLM calls: None.

**Timing:** 5–30 minutes depending on keyword count and API mode (Low/Balanced/Deep Research).

---

### **Step 2: Fetch SERPs Only** (Optional)
**What:** Fetches SERPs without classification or feasibility scoring.

**When to use:** Debugging, quick keyword monitoring, or if you only want to see what ranks today.

**Output:** Partial JSON with fetch_timestamp and position data only.

---

### **Step 3: List Content Opportunities** (Optional)
**What:** Calls Anthropic LLM to generate content brief and advisory.

**Requires:** Completed Step 1 (market_analysis JSON).

**Input:** JSON from Step 1 + LLM model selection (default: Claude Opus 4.6 for main, Sonnet 4 for advisory)

**Process:**
- For each keyword, LLM reads:
  - Intent classification (informational / commercial / transactional / local)
  - Title patterns of top-10 pages
  - Competitor types and content approaches
  - Feasibility score and DA gap
  - Whether the SERP is mixed-intent
- LLM analyzes whether Living Systems should target this keyword
- LLM proposes specific content (titles, angles, formats)
- For mixed-intent SERPs, LLM chooses: compete on dominant intent, backdoor entry, or avoid

**Output:**
- `content_opportunities_<topic>_<timestamp>.md` — per-keyword analysis with specific content recommendations
- `advisory_briefing_<topic>_<timestamp>.md` — executive summary (strategic framing, top 10 priorities, risks)

**Cost:** LLM calls (~$0.08–$0.40 per run depending on keyword count and model). Anthropic API only.

**Timing:** 2–5 minutes.

---

### **Step 4: Refresh Analysis Outputs** (Optional)
**What:** Re-classifies URLs and rewrites reports without re-fetching SERPs.

**When to use:** After you've manually corrected domain overrides (Step 6), you want to re-run intent/feasibility scoring with the corrections baked in.

**Input:** Existing market_analysis JSON + updated domain_overrides.yml

**Process:**
- Re-reads JSON SERP data (does NOT re-fetch)
- Re-applies classification rules with updated domain overrides
- Re-calculates intent and feasibility
- Rewrites JSON, XLSX, Markdown reports

**Cost:** Free (no API calls).

**Timing:** <1 minute.

---

### **Step 5: Export History** (Optional)
**What:** Exports SQLite rank history to CSV files.

**When to use:** Tracking rank volatility over time, reporting rank trends to stakeholders.

**Process:**
- Queries SQLite history database (populated by each pipeline run)
- Generates time-series CSV files: one per keyword, showing positions over time

**Output:**
- `history/rank_history_<keyword>.csv` (date, position, new_rank_gap, volatility score)

**Cost:** Free.

**Timing:** <1 minute.

---

### **Step 6: Review Domain Overrides** (Optional)
**What:** GUI checklist of domains that may be misclassified.

**When to use:** After Step 1, if the classifier is uncertain about a domain's entity type (e.g., is Psychology Today a "therapy practice" or a "directory"?).

**Process:**
1. Classifier generates a list of ambiguous domains
2. GUI shows current classification + suggested alternatives
3. You check/uncheck to approve overrides
4. Saves approved overrides to `domain_overrides.yml`
5. Triggers Step 4 (Refresh Analysis) automatically

**Why:** Correct entity type classification is critical for intent classification. If Psychology Today is classified as a "therapy practice" instead of "directory," intent classification will be wrong.

---

### **Step 7: Feasibility Analysis** (Optional)
**What:** Re-runs Domain Authority scoring from existing JSON.

**When to use:** You want to re-score feasibility without re-fetching SERPs (DA results cache for 30 days, so re-running is free).

**Input:** Existing market_analysis JSON

**Process:**
- Reads JSON
- Queries Domain Authority for Living Systems + top-5 competitors per keyword
- Calculates DA gaps
- Updates feasibility verdicts
- Rewrites feasibility_<topic>.md with updated scores

**Cost:** Free (within 30-day cache window). ~$0.01–$0.05 per domain outside cache window.

**Timing:** 1–2 minutes.

---

## Key Concepts

### Domain Authority (DA)

**What:** Moz's metric (0–100) predicting how well a domain will rank in Google. Higher DA = more "authority votes" from backlinks.

**In Serp-Discover:** Used as a proxy for ranking difficulty. If competitors have DA 50+ and Living Systems has DA 35, ranking is harder.

**Important:** DA is a heuristic, not a guarantee. It's useful for comparison but not absolute truth. A DA 40 domain with great content might outrank DA 50 with weak content.

### Feasibility Gap

**Formula:** `(Average competitor DA) − (Living Systems DA)`

| Gap | Status | Interpretation |
|-----|--------|-----------------|
| ≤ 5 | ✅ High Feasibility | Rankable with quality content + on-page SEO alone |
| 6–15 | ⚠️ Moderate Feasibility | Needs local backlink building + content quality |
| > 15 | 🔴 Low Feasibility | Dominated by high-authority sites; pivot to neighbourhood keywords |

### SERP Intent

**Definition:** What type of search it is — what does the user want?

| Intent | User Wants | Example | Living Systems Can Rank? |
|--------|-----------|---------|------------------------|
| **Informational** | To understand something | "What is family emotional systems?" | ✅ Yes (educational content) |
| **Transactional** | To complete an action | "Book couples therapy session" | ✅ Yes (booking funnel) |
| **Local** | To find a nearby business | "Couples counselling North Vancouver" | ✅ Yes (local service page) |
| **Commercial Investigation** | To research options/pricing | "Best couples therapists Vancouver" | ⚠️ Maybe (review/comparison) |
| **Navigational** | To find a specific brand | "Psychology Today login" | ❌ No (brand-specific) |

**Mixed Intent:** Some SERPs contain multiple intent types (e.g., "couples counselling" returns both local business listings AND informational articles). Serp-Discover flags these and suggests a strategy: compete on the dominant intent, use a "backdoor" angle, or avoid the keyword entirely.

### Content Type

Classification of what the page is:

| Type | Example | Prevalence |
|------|---------|-----------|
| **Article** | Blog post, news, educational | 30–50% |
| **Directory** | Psychology Today, TherapyDen | 20–40% |
| **Review/Comparison** | "Best therapists for couples" | 10–20% |
| **Local Business** | Google My Business listing | 10–30% (varies by location) |
| **Social Media** | Reddit, Facebook, Twitter | 5–15% |
| **Official Site** | Therapist's own website | 5–10% |

**Why it matters:** If competitors rank with directory listings and Living Systems only has blog posts, Living Systems is competing on the wrong content type.

### Entity Type

Classification of who owns the page:

| Entity | What It Is |
|--------|-----------|
| **Therapy Practice** | Independent therapist or small practice |
| **Therapy Clinic/Network** | Multi-therapist organization |
| **Directory** | Psychology Today, TherapyDen, GoodTherapy |
| **News/Editorial** | News publication, magazine, educational site |
| **Government/Nonprofit** | Health ministry, counseling association, non-profit |
| **Commercial** | Insurance, pharma, medical device company |
| **Social** | Reddit, Facebook, Twitter |

### Keyword Prioritization: Feasibility > Intent > Confidence

When Serp-Discover recommends which keywords to target first, it ranks them using three factors in priority order. Understanding this hierarchy helps you make strategic decisions.

#### The Three Ranking Factors

**1. Feasibility (Domain Authority Gap)** — *Can we realistically rank?*
- **Why it matters:** You could identify the perfect keyword with ideal intent, but if competitors are overwhelmingly more authoritative, ranking is impossible without massive link-building investment.
- **How it works:** Compares Living Systems' Domain Authority (DA) to competitors' DA. Gap ≤ 5 is high-feasibility (rankable); gap > 15 is low-feasibility (too hard).
- **Priority:** **Always rank by feasibility first.** A moderate-feasibility keyword matching your preferred intent is a better investment than a high-intent keyword with low feasibility.

**2. SERP Intent Alignment** — *Is this something we should even target?*
- **Why it matters:** Even if a keyword is feasible, Living Systems can only create informational, transactional, and local content. A high-feasibility commercial-investigation keyword (e.g., "best couples therapy prices") isn't worth pursuing — Living Systems shouldn't be competing on pricing comparisons.
- **How it works:** Serp-Discover classifies each keyword's intent (informational, transactional, local, commercial, navigational) and checks it against `client.preferred_intents` in config.yml. If the intent matches, you should pursue the keyword. If it doesn't match, skip it no matter what the feasibility score is.
- **Priority:** **Intent matching is mandatory.** If the intent doesn't fit, the keyword is off-limits.

**3. Confidence** — *How sure are we about the intent?*
- **Why it matters:** Some keywords have clear intent (e.g., "book couples therapy" is obviously transactional). Others are ambiguous (e.g., "couples counselling" might be both local and informational). Low-confidence verdicts mean you need to validate the intent manually before investing in content.
- **How it works:** Confidence is based on how many of the top-10 results clearly indicate intent. 8+ results = high confidence. 5–7 = medium. <5 = low (mixed intent).
- **Priority:** **Within the same feasibility and intent level, prioritize high-confidence keywords.** They're easier to target and less likely to surprise you mid-way through writing.

#### Ranking Logic in Practice

**Example 1: Two high-feasibility keywords**
- Keyword A: Feasibility = High, Intent = informational (matches), Confidence = high
- Keyword B: Feasibility = High, Intent = local (matches), Confidence = medium

→ **Pursue A first**, then B. Same feasibility; A has higher confidence.

**Example 2: Mixed feasibility**
- Keyword A: Feasibility = Moderate, Intent = informational (matches), Confidence = high
- Keyword B: Feasibility = Low, Intent = informational (matches), Confidence = high

→ **Pursue A first**, then B. A is more feasible.

**Example 3: Feasibility vs. intent match**
- Keyword A: Feasibility = High, Intent = commercial (does NOT match preferred intents), Confidence = high
- Keyword B: Feasibility = Moderate, Intent = informational (matches), Confidence = high

→ **Pursue B only.** A is off-limits because the intent doesn't match, regardless of feasibility.

#### What If Feasibility Data Is Missing?

Domain Authority data comes from external APIs (DataForSEO or Moz). If those APIs fail or credentials aren't set up, feasibility data may be unavailable. In that case:
- Intent match becomes the primary ranking factor (still required to pursue)
- Confidence becomes the secondary ranking factor
- You can still prioritize, but you should re-run with DA data as soon as possible to refine your priorities

### API Usage Modes

Serp-Discover can run in different modes, trading cost for depth:

| Mode | Google Pages | Maps Pages | AI Calls | Use Case | Cost |
|------|-------------|-----------|---------|----------|------|
| **Low API** | 1 | 1 | 0 | Quick monitoring (what ranks today) | ~$0.002/keyword |
| **Balanced** *(default)* | 3 | 1 | For brief only | Regular analysis | ~$0.006/keyword + LLM |
| **Deep Research** | 5 | 3 | Full (up to 5 per keyword) | Quarterly strategic deep dive | ~$0.02/keyword + LLM |

---

## Configuration

All behavior is controlled via YAML/JSON files (no code changes needed):

### **config.yml** — Operational Settings

```yaml
serpapi:
  location: "Vancouver, British Columbia, Canada"
  google_max_pages: 3           # pages to fetch per keyword (Balanced mode)
  maps_max_pages: 3
  language: "en"

enrichment:
  max_urls_per_keyword: 5       # URLs fully enriched and analysed per keyword

feasibility:
  enabled: true
  client_da: 35                 # Living Systems DA (fixed)
  pivot_serp_fetch: true        # check local 3-pack for pivot keywords

client:
  preferred_intents:
    - informational
    - transactional
    - local

analysis_report:
  client_name: "Living Systems Counselling"
  client_domain: "livingsystems.ca"
  location: "North Vancouver, BC, Canada"
```

### **intent_mapping.yml** — SERP Intent Rules

Defines how `(content_type, entity_type, local_pack, domain_role)` maps to intent. First-match-wins — order matters.

```yaml
rules:
  - name: "directory_rule"
    content_type: "directory"
    entity_type: "directory"
    verdict: "transactional"
    description: "Directories like Psychology Today are transactional (finding a provider)"

  - name: "informational_articles"
    content_type: "article"
    entity_type: "news|nonprofit"
    verdict: "informational"
    description: "News/nonprofit articles are informational"

  - name: "local_pack"
    local_pack: true
    verdict: "local"
    description: "Google Maps results are local intent"
```

Non-engineers can add/reorder rules here without touching Python.

### **domain_overrides.yml** — Manual Classification Corrections

Override the classifier for specific domains:

```yaml
overrides:
  psychologytoday.com: "directory"
  reddit.com: "social"
  livingsystems.ca: "therapy_practice"
  wellness.com: "commercial"
```

Use after reviewing Step 6 (Domain Overrides checklist).

### **strategic_patterns.yml** — Bowen Patterns

Define Bowen Family Systems patterns with triggers and content angles:

```yaml
patterns:
  - name: "Emotional Fusion"
    triggers:
      - "losing sense of self"
      - "codependent"
      - "merged boundaries"
    status_quo: "Therapy focuses on individual emotional management"
    reframe: "Understanding family emotional systems patterns"

  - name: "Pursuit-Distance"
    triggers:
      - "partner withdrawing"
      - "one partner pursuing"
      - "emotional distance"
    status_quo: "Partners blame each other"
    reframe: "Recognizing the relational dance"
```

---

## Understanding Your Results

### Output Files

For each run, Serp-Discover produces 7 files:

| File | What It Is | Who Reads It |
|------|-----------|--------------|
| `market_analysis_<topic>_<timestamp>.json` | Full structured data — source of truth | Developers, Tool 2 (Serp-Compete) |
| `market_analysis_<topic>_<timestamp>.xlsx` | Spreadsheet version of JSON | Analysts, content team |
| `market_analysis_<topic>_<timestamp>.md` | Human-readable summary | Everyone |
| `competitor_handoff_<topic>_<timestamp>.json` | Validated top-10 competitor URLs | Tool 2 (Serp-Compete) |
| `content_opportunities_<topic>_<timestamp>.md` | Per-keyword content recommendations | Content team, strategy |
| `advisory_briefing_<topic>_<timestamp>.md` | Executive summary + top priorities | Leadership, stakeholders |
| `feasibility_<topic>_<timestamp>.md` | DA gap analysis + pivot suggestions | Strategy, SEO team |

### Reading Each File

#### market_analysis_*.md
Summary of what was analyzed:
- Total keywords processed
- SERP intent distribution (informational: 50%, local: 30%, etc.)
- Feasibility breakdown (high: 40%, moderate: 45%, low: 15%)
- Top 10 keywords by search volume
- Top 10 keywords by feasibility

**How to use:** Quick snapshot of the market landscape.

#### content_opportunities_*.md
Per-keyword content roadmap. For each keyword:
- **Keyword**: The search term
- **Search intent**: Informational / transactional / local / commercial / navigational
- **Feasibility**: High / Moderate / Low (DA gap)
- **Top competitors**: Domains that rank + their entity types
- **Recommended content**: Specific article titles, sections, format (guide, FAQ, local page)
- **Content angle**: How to frame it (Bowen systems approach vs medical model)
- **Confidence**: High (clear intent) / Medium (some ambiguity) / Low (mixed intent)

**How to use:** Content team uses this to build the publishing roadmap. Start with high-feasibility, high-confidence keywords.

#### advisory_briefing_*.md
Executive framing:
- **Key findings**: What the data reveals about the market
- **Top 10 priorities**: Which keywords to target first (feasibility + intent match + search volume)
- **Risk assessment**: Keywords Living Systems should avoid (low feasibility, wrong intent)
- **Content distribution**: How many articles of each type to create
- **Timeline**: Suggested rolling schedule (e.g., 2–3 articles/week)

**How to use:** Leadership/strategy level. Frames the market opportunity and recommends spending.

#### feasibility_*.md
DA gap analysis:
- **High feasibility keywords** (≤5 gap): Can rank with content quality alone. Prioritize these.
- **Moderate feasibility** (6–15 gap): Need local backlink strategy + content. Secondary tier.
- **Low feasibility** (>15 gap): Dominated by high-authority sites. Suggests neighbourhood pivots.

**Example pivot:**
- Keyword: "Couples Counselling" (DA gap: 25, too hard)
- Pivot: "Couples Counselling Lonsdale" (DA gap: 8, feasible)

**How to use:** SEO team uses this to decide which keywords are worth targeting + what link-building work is needed.

---

## Troubleshooting

### "SerpAPI rate limited or timed out"
**Cause:** SerpAPI has temporarily blocked requests (too many calls from same IP).

**Solution:**
- Stop the pipeline and wait 30 minutes
- Try again with Low API mode (fewer pages per keyword)
- If persistent, contact SerpAPI support

### "Domain Authority fetch failed"
**Cause:** DataForSEO API is down, or domain has no backlink data.

**Solution:**
- Results are cached for 30 days; try Step 7 (Feasibility) again tomorrow
- If DA remains unavailable, use MOZ fallback (free tier: 50 rows/month)
- Mark the domain as "unknown feasibility" and manually estimate

### "Intent classification confidence is low"
**Cause:** Top-10 results are mixed (e.g., 5 informational, 5 local). SERP truly is ambiguous.

**Solution:**
- This is honest output (not a bug). Mixed-intent SERPs require strategy: compete on dominant intent, use backdoor approach, or avoid.
- Review `intent_mapping.yml` to see if the rules can be refined
- Use Step 4 (Refresh) to re-classify with updated rules

### "Content classifier gets domain type wrong"
**Cause:** Classifier is uncertain, or a domain has multiple purposes.

**Solution:**
- Use Step 6 (Review Domain Overrides) to manually correct
- Add entry to `domain_overrides.yml`
- Run Step 4 (Refresh) to recalculate with corrections

### "LLM content brief is too generic or misses the angle"
**Cause:** LLM doesn't have enough context about Living Systems' unique approach, or `strategic_patterns.yml` doesn't include relevant patterns.

**Solution:**
- Add more patterns to `strategic_patterns.yml` (Bowen concepts, reframes, angles)
- Update `config.yml` with richer description of Living Systems' framework
- Try Deep Research API mode (more detailed competitor analysis sent to LLM)
- Try Opus 4.7 model instead of Sonnet (slower but more nuanced)

### "Keyword CSV has no keywords in output"
**Cause:** Keyword file path is wrong, or file is empty.

**Solution:**
- Check `config.yml`: `files.input_csv` should point to your keyword CSV
- Verify file exists and contains at least one keyword per row (no header)
- File should be named `keywords_*.csv` in repo root or `input/` directory

### "Market analysis JSON is huge; Excel export is slow"
**Cause:** Large keyword set (1000+ keywords) produces large JSON; Excel can struggle with many rows.

**Solution:**
- Use the JSON directly for downstream processing (more efficient)
- Split keyword CSV into smaller batches (e.g., 200 keywords per run)
- Use `market_analysis_*.md` summary instead of Excel

---

## Quick Start Guide

### Minimal Setup (15 minutes)

1. **Prepare your keyword CSV**
   - Create file: `keywords_YOUR_TOPIC.csv`
   - One keyword per row, no header
   - Example:
     ```
     couples counselling
     family therapy
     relationship anxiety North Vancouver
     ```

2. **Update config.yml**
   - Set `files.input_csv: keywords_YOUR_TOPIC.csv`
   - Verify `client.da: 35` (or your current DA)
   - Set `client.preferred_intents: [informational, transactional, local]`

3. **Run the pipeline**
   ```bash
   cd /path/to/serp-discover
   source venv/bin/activate
   python3 serp-me.py
   ```
   - Click "Run Full Pipeline"
   - Choose API mode: Balanced (default)
   - Sit back (~5–30 minutes depending on keyword count)

4. **Check the results**
   - Open `content_opportunities_YOUR_TOPIC_<timestamp>.md`
   - Read the top 10 recommended keywords
   - Share with content team

5. **Share with content team**
   - Content opportunities = what to write
   - Advisory briefing = why it matters (strategic framing)
   - Feasibility briefing = which keywords are rankable

### Advanced Features (30–60 minutes)

1. **Refine intent mapping**
   - Open Configuration Manager (GUI launcher → "Edit Configuration")
   - Click "Intent Mapping"
   - Review and edit rules for your domain
   - Save (validates before writing)

2. **Add Bowen patterns**
   - Configuration Manager → "Strategic Patterns"
   - Add patterns relevant to your content angles
   - Include triggers, reframes, content angles
   - Run Step 3 (Content Brief) again with updated patterns

3. **Review domain overrides**
   - After Step 1, GUI auto-opens domain override checklist
   - Or manually run Step 6
   - Correct misclassified domains (e.g., directories, social sites)
   - Run Step 4 (Refresh) to recalculate with corrections

4. **Deep research mode**
   - Set API mode to "Deep Research" before running pipeline
   - Fetches more pages per keyword, more detailed competitor analysis
   - LLM gets richer context for content briefing
   - Higher cost (~$0.05–$0.10 per keyword)
   - Worth it for quarterly strategic planning

5. **Track rank volatility**
   - Run Step 1 (Full Pipeline) multiple times over weeks/months
   - Step 5 (Export History) generates time-series CSVs
   - Analyze rank movement: stable keywords (safe bets) vs volatile (risky)

6. **Pivot to neighbourhood keywords**
   - Run feasibility analysis (Step 7)
   - For low-feasibility keywords (>15 gap), tool suggests pivots
   - Example: "Couples Counselling" (DA 25 gap) → "Couples Counselling Lonsdale" (DA 8 gap)
   - Create content for pivots first (easier wins)

---

## Architecture Overview (For Technical Users)

### Data Pipeline

```
Keyword CSV
    ↓
[Fetch SERPs via SerpAPI]
    ├─ Google organic results (top N, configurable)
    └─ Google Maps results (local pack, if present)
    ↓
[Extract & Enrich]
    ├─ Parse HTML, extract titles, snippets, URLs
    ├─ Apply content classifier (article, directory, review, etc.)
    └─ Apply entity classifier (practice, clinic, directory, news, etc.)
    ↓
[Intent Classifier]
    ├─ Match against intent_mapping.yml rules
    ├─ Calculate intent distribution (informational %, transactional %, etc.)
    └─ Assign primary intent + confidence + mixed-intent flag
    ↓
[Feasibility Scorer]
    ├─ Fetch Domain Authority for Living Systems + competitors
    ├─ Calculate DA gap
    └─ Assign feasibility (High / Moderate / Low)
    ↓
[market_analysis.json — Source of Truth]
    ├─ Contains all structured data for downstream steps
    └─ Validated against handoff_schema.json before persistence
    ↓
[Content Briefing Engine — LLM]
    ├─ Sends per-keyword analysis to Claude API
    ├─ Analyzes intent, feasibility, competitor strategy
    └─ Generates content recommendations
    ↓
[Output Files]
    ├─ content_opportunities.md (per-keyword roadmap)
    ├─ advisory_briefing.md (executive summary)
    ├─ feasibility.md (DA gap analysis)
    └─ competitor_handoff.json (Tool 2 input)
```

### Database Schema

**SQLite tables:**
- `rank_history`: Time-series rankings for each keyword (keyword, position, timestamp, volatility_score)
- `classification_cache`: Cached classification results for URLs (url, content_type, entity_type, domain_role)
- `domain_authority_cache`: Cached DA scores (domain, da_score, timestamp, source)

All caches are optional and safe to clear; next run regenerates them.

### Key Modules

| Module | Purpose |
|--------|---------|
| `serp_me.py` | GUI launcher (Tkinter) — entry point for all steps |
| `brief_data_extraction.py` | Fetches SERPs, parses HTML, enriches URLs |
| `classifiers.py` | Content type, entity type, intent classification |
| `brief_rendering.py` | Generates Markdown reports (summary, opportunities, advisory, feasibility) |
| `config_manager.py` | GUI for editing all config files (validation, backup, restore) |
| `config_validators.py` | Schema validation for all config files |
| `dataforseo_client.py` | API client for Domain Authority fetching |
| `brief_llm.py` | Calls Anthropic API for content briefing |
| `brief_prompts.py` | LLM prompts (structured, deterministic) |

### Backwards Compatibility

Old runs (pre-v2) lack `serp_intent`, `title_patterns`, `mixed_intent_strategy` fields. All fields are nullable on read. Older JSON can be re-briefed with current LLM without errors.

---

## Key Takeaway

**Serp-Discover solves the "what should we write?" problem by discovering what people are searching for, understanding why they're searching for it, and identifying which keywords are winnable for Living Systems.**

By understanding your market (search volume, user intent, competitor strength, ranking difficulty), you can create a content strategy that captures high-value traffic without wasting effort on impossible keywords.

Run the full pipeline once per month to track market changes. Use the content brief to prioritize the publishing roadmap. Use feasibility analysis to guide link-building strategy.

---

**Version:** 2.0  
**Last Updated:** 2026-05-02  
**For questions, see:** CLAUDE.md & docs/config_reference.md
