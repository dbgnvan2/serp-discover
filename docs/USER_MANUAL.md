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
- For low-feasibility **service** keywords, suggests neighbourhood pivots (e.g., "Couples Counselling" → "Couples Counselling Lonsdale")
- Informational keywords (e.g. "how does birth order affect personality") get **no** neighbourhood pivot — a geographic variant is meaningless for a question nobody searches with a neighbourhood. They are listed separately for the content extraction play instead.
- If a pivot's validation SERP fetch fails, the tool says **"not measured"** rather than falsely reporting the client as absent from the local pack.

**Why:** Not all keywords are worth targeting. If competitors have DA 60 and Living Systems has DA 35, ranking is nearly impossible without massive link building. Feasibility scoring helps you focus on winnable keywords. And a neighbourhood pivot only works when *proximity can substitute for authority* — that is only true for service queries (someone looking for a counsellor near them), never for informational questions, so pivots are gated to service keywords.

---

#### 5. **Recommended Play** (the rank-vs-citation two-score model)

**What it does:** For every keyword, the tool prints a single strategic verdict —
the **Recommended Play** — in a dedicated column of `feasibility_<topic>.md` and a
per-keyword line in `market_analysis_<topic>.md`. The play is one of:

- **Rank play** (`rank_play`) — the DA gap is winnable, so *chase the organic
  ranking*. Success is measured by **organic rank improvement**.
- **Extraction play (GEO)** (`extraction_play`) — ranking is out of reach and an AI
  Overview is present, so *restructure the page answer-first to be cited by the AI
  Overview* even if you never crack the top 10. Success is measured by **AI Overview
  (AIO) citation gain**, not rank.
- **Reformat play (GEO)** (`reformat_play`) — the client *already* ranks in the
  top-10 but the AI Overview cites other sources. Reformat that **existing** page for
  answer extraction before writing anything new. This play wins over extraction — no
  point drafting new content for a page you already rank with. Also measured by AIO
  citation gain.
- **Local pivot play** (`local_pivot_play`) — a service keyword where geographic
  relevance can substitute for domain strength; pursue the hyper-local variant
  (the classic pivot, still shown in the Recommended Pivot column).
- **Deprioritise** (`deprioritize`) — signals support none of the above (e.g.
  navigational intent, or no AI-Overview opportunity); recommend no dedicated
  content investment.

**Why the two-score model matters:** Your Google rank and your AI-Overview
visibility are **two separate scores**. The source analysis that motivated this
feature found that ~90% of pages an AI Overview cites rank *21 or lower* — so a
page can be invisible in the classic top-10 yet be the one the AI quotes. Chasing
rank on a keyword the AI has already "sponged" wastes effort; the winning move
there is to be *extractable*, not to be #1.

**Example — "birth order and personality":** This is an informational keyword, not
a service, so there is no hyper-local pivot to fall back on. Its DA gap is wide
(incumbent psychology sites have high authority), and the SERP shows an AI Overview
citing pages that don't even rank in the top 10. The Recommended Play is therefore
**Extraction Play**: rewrite the Living Systems page answer-first (a crisp,
quotable definition up top, question-shaped headings) so the AI Overview cites it —
and measure success by *citation gain*, not by rank. A **Rank Play** keyword like a
low-competition local service term would instead be measured by rank improvement.

**Honesty:** when an input needed to route a play is missing (e.g. no DA/feasibility
data), the verdict still routes on the signals it has, but carries a `note` and a
`confidence: low` flag — and the report cell states "inputs missing: …" rather than
implying the verdict is fully grounded. Nothing is invented. The content brief
(Section 7) must *state and follow* each keyword's play and may never assign a
different one than the pre-computed verdict — a mismatch is a hard validation
failure. The play decision table (which play each keyword gets) and the labels live
in `play_routing.yml`, computed by `play_routing.py`; the report/brief consumers
never hardcode the taxonomy.

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

**Brand Authority (Moz, on).** Each competitor domain also gets a **Brand
Authority** score, 0-100: Moz's measure of how established a brand is,
separate from its link authority. It is a useful counterweight to Domain
Authority — a site can accumulate links without being a brand anyone searches
for. In your own market the spread is wide: psychologytoday.com scores **73**,
bowencenter.org scores **1**. Costs 1 API row per domain.

Your own domain's Brand Authority is included too, so the competitor numbers have
something to sit against: livingsystems.ca scores **1** against
psychologytoday.com's **73**. That gap is the point — it says the brand-search
signal is where the distance lies, not just the link profile.

A domain Moz has no score for is reported as *no data*, never as 0 — on a
0-100 scale, 0 is a real and damning value, so inventing one would be a
substantive false claim rather than a harmless placeholder.

**Link momentum (off, and narrower than it sounds).** Moz does **not** expose
recently-gained or recently-lost links on this plan — there is no time filter
of any kind. What can be had is linking domains *lost at some point* versus
*currently live*, with no window. That is what this optional signal reports,
under the names `lost` and `live` and with an explicit `window: none`, so it
cannot be mistaken for 60-day momentum. It is off by default; turning it on
costs two pages per competitor.

**Competitor signals in the Tool 2 handoff (Moz).** For each competitor domain
found in your SERP results, the handoff now carries what that domain actually
ranks for (keyword, the page that ranks, position, difficulty, volume) and how
the web links to it (anchor text, and how many domains and pages use each
phrase). Anchor text is often the most revealing part — it shows how others
describe a competitor, and it exposes link spam: bowencenter.org's top anchors
include several paid-backlink PBN phrases.

Limits worth knowing: this takes the **top page** from each method, not the
complete history, and each block says `truncated: true` when there was more.
It costs 1 API row per item returned, and the limits are sent as the API's own
page controls, so lowering them genuinely lowers the bill. `moz.competitor.max_competitors` (default 3) caps how many domains
are fetched per run, and results cache for 30 days.

Locale matters here too: bowencenter.org returns ranking keywords under `en-US`
but **none** under `en-CA`. If a competitor's ranking list looks empty, the
locale is the first thing to check.

**Search-intent cross-check (Moz, optional and off by default).** The tool
classifies each keyword's intent with its own rule table (`intent_mapping.yml`),
which you control. Moz can also be asked what *it* thinks the intent is, and the
two are shown side by side.

Moz never overrides your rules. Where the two agree, that is a confidence
signal. Where they disagree, the report flags it as an open question worth a
human look and quotes both readings — it does not pick a winner. The two use
different vocabularies (Moz has four labels; this tool also has
`commercial_investigation`, `local` and `uncategorised`), so a mapping table in
`config.yml` translates between them; a keyword whose intent cannot be compared
is reported as **not comparable**, which is different from a disagreement.

Turn it on with `moz.search_intent.enabled: true`. It costs 1 API row per
keyword.

**Keyword demand metrics (Moz).** Each root keyword is also looked up in Moz's
keyword index, and the result is handed to the report as data:

- **Volume** — estimated monthly searches.
- **Difficulty** (0–100) — how hard the first page is to break into.
- **Organic CTR** (0–100) — the share of searches that click an organic result.
  A low value means the SERP answers the question itself, so ranking wins less
  traffic than the volume suggests.
- **Priority** (0–100) — Moz's blend of the three above.

**When Moz has no record, the report says so and stops there.** Many local and
low-volume phrases genuinely aren't in Moz's index — in this client's own data,
"family counselling north vancouver" returns metrics while "bowen family systems
therapy" has no record at all. That is reported as *no data*, never as a volume
of 0: "Moz has no record" and "nobody searches this" are different claims, and
only the first one is supported. The report is instructed not to make demand
claims for those keywords.

This costs API quota — 4 rows per keyword that has data, nothing for keywords
with no record — so it is capped by `moz.keyword_metrics.max_keywords` (default
50) and stops early rather than exceeding your monthly allowance, naming the
keywords it skipped. Results are cached for 30 days, so re-running a report
costs nothing.

**Also collected alongside DA (Moz only):** each URL looked up through Moz now also
records a **Spam Score** (0–100 — Moz's estimate of how closely a site resembles sites
that have been penalised; lower is better) and a set of **link counts** (how many pages
and how many distinct domains link to the page and to the root domain). These are
context, not scoring inputs: they do **not** change the feasibility calculation. Use
them to sanity-check a competitor — a high DA next to a high Spam Score is a weaker
target than DA alone suggests. Which link-count fields are kept is editorial and lives
in `config.yml` under `moz.site_metrics.link_count_fields`. When Moz has no Spam Score
for a URL the field is blank rather than 0, so "no data" is never shown as "clean".

**In Serp-Discover:** Used as a proxy for ranking difficulty. If competitors have DA 50+ and Living Systems has DA 35, ranking is harder.

**Important:** DA is a heuristic, not a guarantee. It's useful for comparison but not absolute truth. A DA 40 domain with great content might outrank DA 50 with weak content.

### Feasibility Gap

**Formula:** `(Average competitor DA) − (Living Systems DA)`

| Gap | Status | Interpretation |
|-----|--------|-----------------|
| ≤ 5 | ✅ High Feasibility | Rankable with quality content + on-page SEO alone |
| 6–15 | ⚠️ Moderate Feasibility | Needs local backlink building + content quality |
| > 15 | 🔴 Low Feasibility | Dominated by high-authority sites; **service** keywords pivot to neighbourhood variants, informational keywords route to the extraction play |

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

### AI Overview Exposure & Estimated Zero-Click Loss

**What it is.** A Google **AI Overview (AIO)** is the AI-generated answer box that
can appear above the organic results. When it does, it often answers the query
directly — so the searcher never clicks through, even to the #1 result. The
market-analysis report's **Section 5d — AI Overview Exposure** estimates, per
keyword, how much of your organic click-through the AIO is likely intercepting,
and whether *your* site is cited **inside** the Overview.

**Why it matters.** Rank no longer equals traffic. Ranking #1 under a rich AIO can
lose more clicks than ranking #3 with no AIO. And being *cited inside the AIO* is
the new "position zero" — it partially offsets the visibility the Overview takes.
Section 5d turns this into a priority queue: the keywords where you are **not**
cited and the estimated loss is highest are where to act first (earn the citation,
or reformat the page to be AIO-extractable).

**How to read it.**

| Column | Meaning |
|--------|---------|
| **Organic position** | Your Google rank for the keyword (— if unranked) |
| **AIO present** | Whether an AI Overview showed for this query |
| **Client cited?** | Whether the AIO cited one of your URLs (✓) or not (✗) |
| **Est. CTR loss** | Modeled organic click-through lost to the AIO (higher = worse) |

*Example.* Two keywords both rank #1 with an AIO. On keyword A your site is cited
inside the Overview; on keyword B it is not. B shows the **higher** estimated loss
and sorts to the top of the queue — that is the one bleeding clicks with nothing to
show for it.

**It is an estimate, not a measurement.** `Est. CTR loss` combines a reference
organic-CTR-by-position curve with an industry AI-Overview interception rate
(~60%), reduced by `citation_credit` when you are cited. Those reference numbers
live in `config.yml → aio_exposure` (`aio_ctr_multiplier`, `citation_credit`,
`ctr_curve`) and are yours to tune — they are **industry reference points, not
measured livingsystems.ca data**, which is why the report labels every figure
"estimated". For *first-party* click loss, see the GSC sponge-effect analysis.
Because AIOs change constantly, the section trends coverage and cited-share across
runs — read the movement, not one number.

### Query Commodity / AI-Absorption Risk

**What it is.** Section 5e of the market-analysis report scores each keyword 0–100 on
how *commoditized* its answer is — how easily one AI paragraph could replace the entire
page of results. It combines how similar the top results read to each other, how uniform
the SERP is (one type of site, one type of headline), and whether an AI Overview already
appears.

**Why it matters.** If a hundred pages answer a question the same way, an AI answer can
absorb all of them — ranking there becomes a race to the bottom. High-commodity keywords
are where generic content loses; the response is to **differentiate** (a distinct
systemic angle only you can write) or to route the keyword to extraction/deprioritize.
The table is a "differentiate-or-lose" queue, highest-risk first, and each row carries
its Recommended Play so the action is explicit.

**It is indicative, not a verdict.** The score is a deterministic heuristic (no AI is
asked to judge), reproducible run to run, with the blend weights in
`config.yml commodity.weights`. Keywords with too few results to compare are flagged
low-confidence rather than scored with false precision.

### Branded vs Non-Branded Demand (Search Console)

**What it is.** When Google Search Console is connected, the GSC analysis report
splits the client's search demand into **branded** (people searching the name —
"living systems counselling") and **non-branded** (generic — "couples therapy") and
tracks the branded share of clicks over time.

**Why it matters.** Clicks can fall while *demand* holds. Non-branded clicks are the
first to be absorbed by AI answers; branded demand — people who already know and want
you — is stickier and predicts survival. A rising branded share as generic clicks fall
is a sign the brand is compounding, not eroding. The report bands the share against an
industry reference (below-average < 2.4%, top ≥ 10%) — a reference point, not a target
for this client.

**Reading it honestly.** The share is over the queries the tool tracked (not the whole
site), the bands are industry reference not goals, and GSC's 2–3 day reporting lag means
the most recent run is provisional. Because Search Console returns per-query totals (not
per-day), the trend builds up run over run.

### Demand vs Clicks

**What it is.** Section 5f of the market-analysis report puts the AI-Overview coverage
(how often an AI answer sits above your results) next to your actual Search Console
clicks, and estimates how much of your traffic those AI answers are likely intercepting.

**Why it matters.** It's the one place the "ranking ≠ traffic" problem is made concrete
for your own site: you see the share of your keywords with an AI Overview, whether you're
cited in it, and a rough estimate of the clicks at risk on the keywords where you're not.
That turns an abstract worry into a shortlist.

**What it does and doesn't show.** It's a **snapshot** — the point-in-time position, not
a trend. The full "demand holding while clicks fall" trend line is deliberately not built:
it would need per-keyword search-volume data (which the SERP sources don't provide) and
daily Search Console history (Console gives per-query totals), so inventing it would be
guessing. For the demand trend that *can* be measured honestly, see the
branded-vs-non-branded share in the GSC analysis report. If GSC isn't connected, this
section shows the AI-Overview coverage and points you to connect GSC for the clicks overlay.

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

Domain Authority data comes from external APIs (DataForSEO or Moz). Moz needs only `MOZ_TOKEN` in your `.env` — the audit previously looked for `MOZ_ACCESS_ID` and `MOZ_SECRET_KEY`, which this project never used, so Moz enrichment stayed off during audit runs no matter what was configured. It now runs whenever `MOZ_TOKEN` is set and `feasibility.enabled` is true, and the run log reports how many API rows each fetch billed (cache hits bill nothing). If those APIs fail or credentials aren't set up, feasibility data may be unavailable. In that case:
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

### **shared_config.json** — Cross-Tool Shared Settings (optional, out-of-repo)

**What it is:** one optional JSON file, stored one directory ABOVE this repo
(`../shared_config.json`), that both this tool and Tool 2 (the competitor
audit tool) read. It carries the settings that must agree across tools:
the client's Domain Authority, domain, and location; the stop-word list;
the feasibility thresholds; and the omitted-domains file path.

**Why it exists:** if the two tools disagreed about who the client is or
what "feasible" means, their outputs could not be compared. Putting those
values in one shared file outside either repo makes them a single source of
truth. When the file is present, its values override the same settings in
`config.yml` and `serp_vocab.yml`; when it is absent, the in-repo defaults
apply and the run log says so. A broken (malformed) file never crashes a
run — the tool logs one warning naming the file and falls back to defaults,
so you always know which settings were actually in effect.

**Relocating it:** set the `SERP_SHARED_CONFIG` environment variable to the
file's full path if your deployment doesn't keep it one directory up.
The full key list is in `docs/config_reference.md` ("Shared config").

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

> **Serp-Compete export (AI-visibility).** Separately, the standalone AI-visibility
> probe (`probe_ai_visibility.py`) writes `ai_visibility_<topic>_<ts>.md`, and
> `export_ai_visibility.py` writes `output/ai_visibility_export_<slug>_<ts>.json` —
> a schema-validated snapshot of the per-engine brand-mention and citation
> leaderboards. **Why it matters:** Serp-Compete (Tool 2) consumes this file to
> compute *competitive AI Share-of-Voice* — whose brand and sources the models
> return for category questions, yours or your competitors' — without re-running
> any paid probes. Before any probe run exists, the export is written with
> `data_available: false` so Tool 2 degrades gracefully instead of failing.

> **Own-brand negative-sentiment alert.** When per-brand sentiment is enabled
> (`sentiment.enabled: true`), the AI-visibility report raises a prominent alert if
> the AI answers portray **your** brand negatively this run — showing how many
> answers, on which engines, and the recurring negative phrases — so a reputation
> problem in the models' answers surfaces immediately rather than being buried in a
> table. With sentiment off (the default) the report simply says "not measured" and
> never invents a verdict. Separately, `ai_visibility.store_raw_answer` (off by
> default) retains each full AI answer for auditing; leave it off unless you need the
> verbatim text, since answers are long and may contain personal information.

### Reading Each File

#### market_analysis_*.md

The main report. It opens with what to write and works backwards to the evidence.

| Section | What it gives you |
|---|---|
| 0. Executive Summary | The single best keyword, and the first thing to write |
| **1. What To Write** | The ranked content plan — one numbered option per keyword |
| 1b. Market Overview | Which search-page features appeared, and on how many keywords |
| 2. The 'Anxiety Loop' | Real questions searchers ask, to use as page headings |
| 3. The Words Competitors Use | Vocabulary already on the results page |
| 4. Strategic Recommendations | The Bowen argument the page should make |
| 5–5f | The underlying data: competitor mix, intent, feasibility, AI Overview exposure, commodity risk |
| 6. Market Volatility | Rank movement since the last run of the same keywords |
| **A. Glossary** | Plain-English definition of every term of art used above |

**How to use:** read Section 1, write the page, and drop into the numbered
sections when you want the evidence behind a recommendation.

##### Section 1 — What To Write

One numbered **Option** per analysed keyword, best first. The order is the same
ranking the Executive Summary uses, so Option 1 is always the keyword named at
the top of the report — the two can never disagree.

Each option answers seven questions:

- **Page type** — a guide, a local service page, a rewrite, or nothing at all.
  Derived from the recommended play plus whether the search shows local intent.
- **Why this one** — the Domain Authority comparison in plain terms, plus
  whether an AI Overview appears and whether it cites you.
- **Target search** — the keyword to write for.
- **What the page must do** — the play's instruction. Where the play was decided
  without some of its inputs, the caveat is printed underneath it, and where the
  play contradicts the measured feasibility in Section 5c, the report says so
  explicitly rather than presenting both as fact.

  Reports generated before 2026-08-28 can show that contradiction, because the
  play verdict used to be computed before Domain Authority was fetched and was
  never revisited afterwards. Runs from that date on route the plays again once
  DA data exists, so the two agree. An older `market_analysis_*.json` still
  carries the stale verdict — re-run the feasibility step on it to correct it.
- **Questions to use as headings** — real People Also Ask questions for *that*
  keyword. Use them word-for-word.
- **Terms to work in** — vocabulary from that keyword's own results page.
- **Success looks like** — organic rank, or AI Overview citation. These are
  different goals and they are written differently.

If a keyword has no PAA questions or no distinct vocabulary, the option says so.
It never invents filler, and a two-keyword run produces two options, not three.

##### Writing directives

Sections 1b through 5e each carry a **"When you write:"** line explaining how
that section's data should change the page. The text is editorial and lives in
`report_writing_directives.yml` — edit that file, not Python, to reword it.

##### Section 3 — a note on what it can and cannot tell you

The phrases come from the text *Google displayed* — result snippets, the AI
Overview, ad copy, related searches and autocomplete — not from the full body
text of competitor pages. Phrases that merely restate your own search term are
excluded, because the search term appearing in the results says nothing about
how competitors write.

On a small keyword set that exclusion can empty the list. When it does, the
report says "no distinct competitor vocabulary" rather than padding the section
with restatements of your keyword. That is a real finding: analyse more
keywords, or a wider set of related terms, to get a usable vocabulary list.

##### Worked examples in sections 4 and 5

Every piece of general advice is followed by a **"Here's an example:"** line that
translates it into your data — your keyword, a real question from your results
page, your competitors' vocabulary. It is not a written post; it is the advice
made specific enough to start from.

The example text is editorial and lives in config, so you can rewrite it in your
own voice without touching code:

- Mixed-intent strategy examples and the section-5 examples:
  `report_writing_directives.yml`
- Per-pattern openings (the Bowen blocks): `Content_Angle_Example` in
  `strategic_patterns.yml`

Templates use placeholders like `{keyword}` and `{question}`. If a run has no
data for a placeholder, the sentence containing it is dropped rather than
rendered with a blank — so an example is always complete, just sometimes shorter.

One deliberate exclusion: section 5's examples never tell you to write "other"
or compete with "N/A" pages. Those are the classifier's unknown buckets, not
formats or competitors. In your 2026-08-26 run "other" was the *largest* content
type at 51.1%, so a naive reading would have recommended writing it.

##### Section A — Glossary

Every term of art in the report, defined in plain English, and *only* the terms
this particular run actually used. Definitions live in `glossary.yml`. A
standing test fails the build if a guarded term appears in the report with no
definition, so the report cannot quietly reacquire unexplained jargon.

The glossary costs nothing to produce — it is a lookup from `glossary.yml`, not
generated text, so there is no API call and no token cost at any surface. The
same file feeds two other places:

- **The `.xlsx` workbook** gets a **Glossary sheet** explaining its column
  headers (`avg_serp_da`, `gap`, `Params_Hash`, `Rank_Delta` and the rest). The
  headers themselves are deliberately not renamed — the JSON and the workbook
  share one set of field names that a validator checks, and renaming them would
  break that check and any formulas you have built on the file.
- **`docs/glossary.md`** is the whole glossary as a standalone document, terms
  and columns, for reading or sharing on its own. Regenerate it after editing
  `glossary.yml`:

```bash
python3 generate_insight_report.py --glossary-out docs/glossary.md
```

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

#### The FAQ / Answer-Extraction Plan (report Section 5b)

**What it is:** For each priority keyword, the report recommends up to three real
People Also Ask questions — quoted word-for-word from the SERP — to be used as
literal headings on the client's page, each with answer-first formatting
guidance and a structured-data (schema.org markup) recommendation.

**Why it matters:** AI answer surfaces (Google's AI Overviews and AI assistants)
don't read a page the way a person does. They scan for a complete, confident
answer they can lift directly. A page that opens each section with the exact
question a searcher asks, followed immediately by a 1–3 sentence direct answer,
is far more likely to be cited than one that buries the answer after warm-up
prose. This is also why the plan distinguishes two kinds of questions:

- **Reframe candidates** (medical-model framing, e.g. "How is anxiety
  diagnosed?"): the searcher is inside the framing Living Systems
  differentiates from. Answering these in Bowen terms is the differentiation
  play — the report states the reframe angle for each.
- **Aligned demand** (already in systems language, e.g. "How does family of
  origin affect relationships?"): demand Living Systems is naturally
  positioned to answer; no reframe needed.

**The structured-data line:** for each keyword the report states how many of
the analyzed top-10 pages carry FAQ markup (FAQPage) and which schema.org
types dominate, then recommends markup for the client's page. Recommendations
come from the editorial table in `schema_recommendations.yml` — edit that file
(not Python) to change what markup the tool may recommend.

#### The citation surface map and GEO alerts (report Section 4)

**What it is:** the report classifies every source the AI Overview cites
(directory, media, counselling competitor, …) and reports two things most
SEO tools miss:

- **Outreach candidates** — third-party surfaces (Psychology Today-style
  directories, media outlets, associations, named Reddit/forum threads) that
  the AI Overview already trusts for your keywords. Being listed, complete,
  and mentioned on those surfaces is how you occupy the roughly three-quarters
  of AI citations that point somewhere other than a brand's own site.
- **GEO alerts** — keywords where Living Systems ranks in the organic top-10
  but the AI Overview cites other sources instead. This is the single most
  actionable AI-visibility signal: the page already ranks, so reformatting it
  for answer extraction (see Section 5b) is cheaper and faster than writing
  anything new.

**Why it matters:** Google rank and AI citation are separate scores. A page
can rank #3 and be invisible in the AI answer, and a page that doesn't rank
top-10 can be cited. The divergence lists in Section 4 make that gap visible
per keyword instead of leaving it to intuition. Which entity types count as
outreach surfaces is configurable in `config.yml` under
`geo.outreach_entity_types`.

#### The answer-extractability audit (evidence behind Section 5b)

**What it is:** for every competitor page the tool fetches, it now measures
three things AI answer engines respond to: how many section headings are
phrased as questions (in the searcher's own words), how much warm-up text sits
before the first section heading (a long intro buries the answer), and whether
the page has an FAQ block. The report compares these numbers on pages the AI
Overview actually cites versus pages that merely rank, and shows where Living
Systems' own page sits.

**Why it matters:** "format your page for AI" is usually generic advice. This
turns it into a measurement: if cited pages average four question headings and
the client's page has none — or the client's answer starts 2,000 characters
into the page — the report can say exactly what to restructure and why, before
recommending any new content.

#### The content freshness audit (evidence behind Section 2)

**What it is:** for every competitor page the tool fetches, it now captures
the page's published and last-modified dates (from the page's own metadata —
never guessed from body text) and computes each page's age as of the day the
SERP data was collected. Per keyword, the report can state the median age of
the dated ranking pages, how many ranking pages carry no date at all, and how
old Living Systems' own page is.

**Why it matters:** therapy content is YMYL ("Your Money or Your Life"), and
both Google and AI answer surfaces prefer fresh YMYL content. "The top-10 for
this keyword is young" means new content must launch current and be
maintained; "the client's page is two years older than the median" is a
concrete refresh trigger that costs far less than new content. The undated
count is honest signal too: service pages often carry no dates, and the tool
reports that rather than pretending undated pages are new — an undated page
is never counted as age zero.

#### The E-E-A-T author-signal audit (evidence behind Sections 5b and 7)

**What it is:** for every competitor page the tool fetches, it detects
whether the page shows a named author (a byline, an author link, or author
markup in the page's structured data), which professional credentials appear
near the byline or in the opening text (RCC, MSW, PhD, "registered clinical
counsellor", and so on), and whether the page carries a "medically reviewed"
/ "clinically reviewed" line. The report then states, per keyword, how many
of the analyzed ranking pages carry credentialed bylines and whether Living
Systems' own page does.

**Why it matters:** therapy content is YMYL, and both Google and AI answer
engines weight visible author expertise on health content. If seven of eight
ranking pages show credentialed authors and the client's page shows none,
adding a visible credentialed byline is likely a prerequisite — cheaper than
new content and invisible to generic SEO checklists. The credential and
review vocabularies are editorial: edit the `eeat_signals` section of
`serp_vocab.yml` (not Python) to add designations the tool should recognize.
Short tokens match whole words only ("RP" never matches inside "harp"). How
much of each page's opening text is scanned is configurable via
`enrichment.eeat_scan_chars` in `config.yml` (default 8000 characters).

#### The situational query probes and AI-answer trigger rate (report Section 4)

**What it is:** an optional probe pass that searches Google the way people
actually talk to AI assistants. Instead of a keyword like "couples
counselling north vancouver", each probe is a full situation — "why does my
partner refuse to go to counselling" — taken verbatim from the keyword's own
People-Also-Ask questions (6+ words, medical-model-framed ones first) or,
when a keyword has no long questions, from editorial templates you can edit
in `serp_vocab.yml` (`situational_templates`). The report then states the
measured AI Overview trigger rate by query length — how often 1–3-word,
4–5-word, and 6+-word queries produced an AI answer in THIS run — and names
any probe where Living Systems was cited in the AI answer.

**Why it matters:** the claim driving this feature is that short keywords
trigger an AI answer roughly 23% of the time while six-plus-word,
situation-style queries trigger one about 77% of the time — and that nobody
types keywords into ChatGPT; they describe their whole situation. If that
holds on this market, the future search surface for these keywords is the AI
answer, not the ten blue links, and answer-extraction formatting (Section 5b)
becomes the priority. Rather than assuming the industry figure, the probes
measure it on the client's own keywords, in the client's own city, so
strategy rests on local evidence.

**Cost control:** every probe is a paid SerpAPI call, so the feature is OFF
by default (`situational_probes.enabled: false` in `config.yml`). When
enabled it is hard-capped at `max_probes_per_run` calls (default 6 — two
probes for each of the top three priority keywords), and the run log prints
exactly how many probe calls were made. Deep Research mode turns probes on;
Low API mode never runs them. Probe results feed only the trigger-rate
analysis and the AI-citation data — they never distort organic rankings,
intent verdicts, rank-change history, or the competitor handoff file.

#### The Bing visibility check (report Section 4)

**What it is:** an optional pass that runs each root keyword once against
Bing (via SerpAPI) and records whether livingsystems.ca appears, at what
rank, with which domains holding Bing's top three. The report then puts the
Google and Bing positions side by side per keyword — "visible on Google at
#4 but absent from Bing's top-20", or the reverse. Bing results are not
classified or enriched; this is purely a visibility snapshot.

**Why it matters:** ChatGPT's web search grounds substantially on Bing's
index, so Bing standing is a proxy for a whole AI-referral surface that
Google data cannot show. A page that ranks well on Google but is invisible
on Bing is invisible to a growing class of AI-assisted searchers — and
nobody notices, because almost all reporting is Google-only. If the check
is off (the default), the report says so explicitly rather than guessing.

**Cost control:** each checked keyword is one paid SerpAPI call, so the
feature is OFF by default (`bing_check.enabled: false` in `config.yml`).
Turn it on to add exactly one call per root keyword; `bing_check.num`
(default 20) controls how deep the Bing results go, and the run log states
how many Bing calls were made.

#### Client profiles and persona-segmented questions (`client_profiles.yml`)

**What it is:** a per-client profile that generates the natural-language
questions real AI-assistant users ask — grouped by **persona** (who is asking)
and **funnel tier** (how ready they are to book). The tool has always been able
to probe questions derived from a keyword CSV; this adds a second, parallel
source that does not need a keyword list at all. Each client gets one profile
block in `client_profiles.yml` (keyed by the **client** slug, e.g.
`living_systems` — not the topic slug that names output files). A profile
carries the brand, domain, region, cities, a one-paragraph service
description, and a list of personas. For Living Systems the shipped personas
are the **prospective client** (with two tiers — top-of-funnel
*informational* concept questions and booking-intent *local_transactional*
queries), the **clinician/trainee**, and the **referrer**.

Two kinds of questions are generated. `seed_questions` are the client's own
hand-authored queries, probed **verbatim** — "family of origin issues", "how
does birth order affect personality" — never reworded or city-suffixed.
`templates` expand: a booking-intent local tier fans "relationship counselling
{city}" out across North Vancouver, West Vancouver, and Vancouver, **plus** a
"relationship counselling near me" variant, **plus** a de-localised "relationship
counselling" copy (because the AI-answer probe needs the non-local phrasing
too). You preview the exact expanded list — with persona, tier, and city tags —
in the Settings **"Client Profile & Queries"** tab before any run; generation
is deterministic and costs nothing.

**Why it matters:** people do not talk to an AI assistant in keywords. They ask
questions shaped by who they are and what they need, and those questions span
audiences a keyword list quietly misses. A therapy keyword set surfaces the
therapy-seeker; it never surfaces the **clinician** looking for Bowen training
or the **GP/referrer** deciding where to send a family — yet both are people
whose AI answer could name (or omit) the client. Separating the funnel tiers
matters too: a review found the client had been probing only top-of-funnel
concept questions ("repeating relationship patterns") and none of the
booking-intent local queries ("family therapist North Vancouver") that actually
convert. The profile makes both explicit, per client, and editable in the GUI.

**Editing profiles in Settings (the "Client Profile & Queries" tab):** open
**Edit Configuration** and choose the tab. Pick the client from the selector at
the top, then edit the brand, domain, location, cities, and each persona's
funnel tiers — the verbatim seed questions and the per-city templates. Click
**Preview generated questions** to see the exact list the probe would ask, each
tagged with its persona, tier, and city, before you spend anything: the preview
is generation only, with zero API calls. Saving is atomic and validated — it
round-trips through the same loader the probe uses, rejects mistakes like an
empty persona label with an inline message, and never disturbs any other
client's profile. WHY this lives in the GUI: this is a multi-client tool, so
each website's personas and funnel queries are set per client, in Settings —
not by hand-editing YAML and not in a keyword CSV.

#### The AI-engine visibility probe (standalone: ai_visibility_*.md)

**What it is:** a standalone script (`python probe_ai_visibility.py --yes`)
that asks real AI assistants — **Claude, Google Gemini, ChatGPT (OpenAI),
and Perplexity**, each with web search/grounding turned on — the same
situation-style questions a
therapy-seeker would type ("my partner refuses to try counselling what can
I do", prefixed with "I'm in North Vancouver, BC."), and records per engine
whether the answer **mentioned** Living Systems by name, **cited**
livingsystems.ca as a source, and which **competitors** were cited instead.
Questions are chosen by a **precedence chain**: **profile-seeded persona
questions first** (from the client's block in `client_profiles.yml` — the
audience-shaped questions real assistant users ask, see "Client profiles and
persona-segmented questions" above), then the run's own situational probes,
then long People-Also-Ask questions, then the editorial templates in
`serp_vocab.yml`. When no client profile is present the chain simply starts
at situational probes — behaviour is exactly as before. Every probe row now
also records **which persona** seeded it and **which source** in the chain it
came from (`profile` / `situational` / `paa` / `template`), so the report can
break results down by audience. Every run is stored in the local database,
and the report shows this run's mention/citation rate per engine next to the
same rates from previous runs.

**Share of voice — visibility relative to whom:** the report includes a
**cross-engine share-of-voice** section. Answering "does the client appear?"
is only half the question a client pays for; the other half is "**relative to
whom?**" For each engine the section lists the client's mention and citation
rate this run alongside the **top competitor domains the engine cited
instead** — because knowing which rivals the AI recommends in the client's
place is the actionable signal (it names the outreach and content targets).
Because the probe questions carry persona tags, the section also gives a
**per-persona breakdown** of the client's mention rate — so you can see, for
example, that the client surfaces well for prospective-client questions but
not for referrer questions. Every value carries its run count, and the
section reiterates the snapshot caveat: read the per-engine, per-persona
trend across runs, never a single number. When no profile is wired in, the
per-persona table states plainly that no persona-tagged questions ran (it is
never faked as zeros).

**Why it matters — and why it's a trend, not a snapshot:** AI answers are a
growing referral surface: people increasingly ask an assistant instead of
searching, and whether the assistant names or links Living Systems decides
whether those people ever reach the site. But assistant behaviour swings
between model versions — the same question can produce a citation one month
and silence the next. A single measurement is therefore nearly meaningless;
the signal is the direction across runs ("cited in 2 of the last 5 runs,
up from 0"). That's why the tool records every run per engine and the report
always carries a caveat that single-run values are snapshots.

**Choosing engines:** `config.yml ai_visibility.engines` (default
`gemini`, `openai`, and `perplexity` for this client — gate Y-D9) controls
which assistants run; `--engines openai` (or any comma-separated subset)
overrides for one run. Four engines are supported: `claude`, `gemini`,
`openai` (ChatGPT), and `perplexity`. Each is key-gated and skipped with a
warning (never an abort) if its key is missing, and the rest of the run
completes: Claude uses your existing `ANTHROPIC_API_KEY`, Gemini needs
`GEMINI_API_KEY`, **ChatGPT needs `OPENAI_API_KEY`** (Y.2 — uses OpenAI's
web-search-enabled Responses API, returning the URL citations it retrieved),
and **Perplexity needs `PERPLEXITY_API_KEY`** (Y.3 — uses a Sonar
search-grounded model, which is citation-first and returns explicit source
URLs, making it a high-signal target for the "cited" metric).

*Tier caveat:* OpenAI's citation annotations and Perplexity's Sonar
citations are confirmed against the vendors' current (2026-07) docs, but the
exact citation fields and whether they appear can vary by account tier and
model. Endpoints and model ids are all set in `config.yml`, so you can point
each engine at the tier/model your account has without a code change; if an
engine's tier returns no citations, the probe still measures whether the
answer *mentions* the client — only the citation-based "cited" flag reads as
absent, and it is never faked.

**Why per-engine coverage matters — optimization does not transfer:** a
strong showing on one AI engine does **not** carry over to the others.
Independent cross-engine analyses report that the source URLs different
engines cite overlap only ~11–18% (they draw on different retrieval
backends — ChatGPT leans on a Bing-derived, consensus-heavy index and cites
few sources; Perplexity is freshness- and community-heavy and cites many;
Gemini mirrors Google's index; Claude favours structured depth). So being
cited by Gemini tells you almost nothing about ChatGPT or Perplexity. That
is exactly why the report keeps **every metric per engine, never only an
average**, and why measuring all the engines the client's audience actually
uses — not just one — is the point of adding ChatGPT and Perplexity here.
For a Google-organic local nonprofit like Living Systems, Gemini/Google AI
surfaces usually carry the most existing SEO weight, ChatGPT reaches the
most people, and Perplexity punches above its usage weight for referral
clicks — which is why all three are ON by default and Claude is available
but off.

**Cost control:** each question is one paid API call per engine (default
cap: 20 questions × 3 default engines = 60 calls). On top of the per-engine
`max_questions` cap there is a **hard total-calls ceiling**
(`ai_visibility.max_total_calls`, default 60) that applies across
questions × engines — so as more engines are enabled the total spend can
never run away. The script always prints that math first, including the
ceiling, and if the plan would exceed the ceiling it truncates the question
set so it never does. It makes **zero** calls unless you pass `--yes` (or set
`ai_visibility.assume_yes: true`); over-budget without `--yes` still spends
nothing.

#### The AI Visibility Index, leaderboard, citations, and sentiment (in the same ai_visibility_*.md report)

The same probe report now also carries four enrichment sections, computed
from the answers already fetched — **no extra API calls** except the opt-in
sentiment step. Together they turn "does the client appear?" into a scorecard
of *how* the client shows up and *who beats them*.

**AI Visibility Index (AIVI) — the single headline number.** *What:* a
0–100 score per engine (plus an all-engine average) built from four
equally-weighted axes — **Mentions** (share of questions that named the
client), **Ranking** (the client's place on the competitor leaderboard below,
normalised so rank 1 = 100 and unranked = 0), **Citations** (client-owned
source URLs as a share of all sources the engine cited), and **Sentiment**
(the client's % positive, when that opt-in feature is on). *Why:* raw
mention/citation rates don't answer "are we getting more visible?" at a
glance; a composite does, and because it is stored every run it is readable
as a trend with a prior-run delta. The weighting lives in `config.yml`
(`aivi.weights`) so it is tunable and defensible — the number is always
computed by the tool, never invented by an AI. When sentiment is off its axis
shows **n/a** and is dropped from the average (the other three re-weight to
fill the gap); it is never silently counted as zero, because an unmeasured
thing is not a zero. Read AIVI as a per-engine snapshot-trend, not a verdict:
AI answers swing between runs, and a strong AIVI on one engine does not carry
to the others.

**Competitor mention leaderboard — who the AI names instead of you.** *What:*
a ranked list of the brands the AI *named in its answer text* (not merely the
domains it linked), with the client's own rank called out ("#7 of 18 named
brands", or "not mentioned"). *Why:* in AI answers the dominant signal is
being *named* — Yoast's report found 24 rival brands named across five
answers, many with no link at all, which a link-only check misses entirely.
The leaderboard is built deterministically from your `known_brands` list plus
the recurring competitors in the latest analysis, so it works with no AI call.
An **optional** AI extraction pass (`brand_mentions.llm_extraction`, off by
default) can surface brands you haven't listed yet; any new names it finds are
written to a review file, `brand_mentions_candidates_<topic>_<ts>.md`, for you
to promote into `known_brands` in `config.yml` — the tool never grows its
brand list silently behind your back.

**Citations table — the sources the AI trusts, as an outreach list.** *What:*
every source URL each engine returned, listed once (identical URLs merged with
a cite count), each tagged with its domain, a **category** (publisher,
directory, media, government, and so on — taken straight from the tool's
existing site classifier, not a separate list), and the brand it supports;
the client's own sources are flagged. Tracking parameters like
`?utm_source=openai` are kept exactly as returned, because they confirm the
citation came from the live engine. *Why:* these are the sources the AI trusts
for this topic — i.e. the highest-value content-partnership and outreach
targets. The section ends with a one-line "top cited domains for this topic"
shortlist you can act on directly.

**Sentiment — what the AI says about you (opt-in).** *What:* when you turn it
on (`sentiment.enabled: true` in `config.yml`), the tool runs one AI
classification per answer that mentions the client or the top competitor and
reports **% positive** for each, with the actual **positive/negative keyword
phrases** the answer used (e.g. a competitor's positives "integrated supports
for youth and families", "no-cost assessment"; a negative "may require a
physician referral"). *Why:* for a nonprofit whose reputation is the product,
"what does the AI say *about* us" matters as much as whether it names us. It is
**off by default** because it costs one extra AI call per qualifying answer
(counted against the same total-calls ceiling); when off, the report plainly
says "sentiment not measured" and AIVI drops the axis rather than faking a
score. *Caveat:* AI sentiment is an estimate, not a measured fact — read it as
a trend across runs, and confirm any single striking result by reading the
answer excerpt the tool stores.

#### Engine strategy: the foundational score, per-engine advice, and the transfer metric (top of the same ai_visibility_*.md report)

These three sections answer the strategic question behind all the numbers
above: **which AI platforms should this client work on, and does improving one
help the others?** They rest on a well-replicated finding — visibility on one
AI engine mostly does *not* carry to another (the engines cite mostly different
sources), *except* for one shared foundation that lifts them all.

**Foundational GEO readiness — the transferable, do-first layer (presented
first, ahead of AIVI).** *What:* a single 0–100 score for the layer the client
controls and that pays off on *every* engine at once — (1) accessibility /
answer-extractability (can an AI lift a complete answer from the page: question
-shaped headings, an answer at the top, an FAQ block), (2) structure / schema
(the schema.org markup the client's own pages carry vs what the topic warrants),
and (3) off-site authority (how often third-party AI answers *name* the client
vs the rivals — the signal reported to predict AI citation roughly three times
better than backlinks). Each sub-score lists its top two-or-three concrete gaps,
drawn from data the tool already computed (the rank-vs-citation "geo alerts", the
missing schema types, the rival brands the AI names in the client's place) — so
it is a to-do list, not just a grade. *Why it comes first:* AIVI measures the
*outcome* (a lagging result that differs per engine); this measures the
transferable *inputs* (a leading indicator that does not). The empirical evidence
says fix these foundations before chasing any single engine — they are the only
work that lifts all engines together. A sub-score with no captured data shows
`n/a` and is dropped from the average (never counted as zero), and the score is
stored each run so you can watch it climb.

**Per-engine recommendations — because optimisation does not transfer.** *What:*
a "what to change here" block per engine (ChatGPT, Perplexity, Gemini, Claude),
plus a prioritisation list ranking the engines you have enabled. *Why the advice
differs by engine:* each engine retrieves from a different backend with a
different taste — ChatGPT leans encyclopedic/consensus and cites few sources;
Perplexity rewards fresh, community-referenced content and cites many; Gemini
mirrors Google's own rankings; Claude favours structured depth. Because a win on
one does not transfer, one set of tips would be wrong for the others. All the
advice lives in the editorial `engine_profiles.yml` — edit that file to tune it;
nothing is baked into code. The prioritisation blends current opportunity (a low
AIVI is high upside), engine reach, and referral-click value, but it is
explicitly **indicative guidance, not a fixed order**: a local nonprofit whose
audience arrives via Google organic should usually favour Google's AI surfaces
first, because existing SEO partly carries over there. *Caveat, stated in the
report:* the backends and these figures shift over time and many come from
vendors — treat them as direction, and re-measure.

**Cross-engine transfer — "if I optimise once, am I good everywhere?"** *What:*
this client's *actual* overlap across the engines you ran, not an industry
average: on how many engines the client is mentioned/cited ("mentioned on 2 of
3 engines"), how much the engines' cited-source sets overlap (a 0-to-1 score
where 1.0 means identical sources and 0.0 means completely different ones), and
how the client's leaderboard rank varies across engines. *Why it matters:* it
answers the "optimise once?" question directly from the client's own data —
**high overlap means the foundational work above is enough; low overlap means
you also need per-engine targeting.** It needs at least two engines enabled; with
one engine it simply says "transfer not measurable (single engine)". As always, a
single run is a snapshot — read the trend.

#### The Search Console sponge analysis (standalone: gsc_analysis_*.md)

**What it is:** a standalone script (`python run_gsc_analysis.py`) that
joins Google Search Console — the client's own free, first-party
clicks/impressions data — onto the keywords and question-style queries
from the latest market analysis. For every query it shows clicks,
impressions, click-through rate (CTR), average position, and whether
Google showed an AI Overview for it in this run. It writes a markdown
report plus a JSON sidecar the content brief can optionally consume.

**Why it matters — the "sponge" effect:** the SERP tool sees rank but
never clicks. A page can hold position #3 and still starve, because an AI
Overview above it answers the question and soaks up the click. That loss
is invisible in ranking reports; it only shows in the client's own CTR.

**How to read the sponge table:** the table compares the *median CTR at
comparable position* — e.g. among queries where the client ranks 1–3,
what's the typical CTR when an AI Overview is present vs when it isn't?
- A **lower AIO median at the same position band** is the sponge effect
  measured on the client's own traffic: rankings intact, clicks absorbed.
- Each band is only compared when **both** buckets hold at least 3
  queries; otherwise the row says "insufficient data" — the tool never
  extrapolates from one or two queries.
- The **reformat candidates** list below it names the queries that rank
  well (top 10) but earn a CTR below the no-AIO median for their band —
  the pages losing clicks despite good positions. Rows flagged ⚑ also
  carry a GEO alert (the client ranks but the AI Overview cites other
  sources): reformat those pages for answer extraction FIRST, because
  fixing them can win back both the citation and the click.
- Queries with "no GSC data" had no recorded impressions in the window —
  reported as absent, never invented as zero.

**Setup (one-time, service account):**
1. In Google Cloud Console, create (or reuse) a project, enable the
   **Search Console API**, and create a **service account**. Download its
   JSON key file.
2. In **Search Console → Settings → Users and permissions**, add the
   service account's email address (`...@...iam.gserviceaccount.com`) as
   a user (Full or Restricted) on the `livingsystems.ca` property. This
   grant is what lets the headless key read the data — without it every
   call returns a permission error.
3. In `.env`, set `GSC_CREDENTIALS_PATH=/path/to/key.json`, and in
   `config.yml` set `gsc.enabled: true` (check `gsc.property` matches the
   Search Console property, e.g. `sc-domain:livingsystems.ca`).

GSC is free — there is no API spend to guard — but the integration stays
off (`gsc.enabled: false`) until the grant exists, and when disabled or
unconfigured the script exits with a clear message and zero API calls.
Results are cached locally for 7 days. If `gsc.feed_strategic_flags` is
turned on, the content brief will quote these numbers, but only ever
about the client's own pages — they are private data, never presented as
market-wide facts.

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
- **Low feasibility** (>15 gap): Dominated by high-authority sites. Service keywords get neighbourhood pivots; informational keywords are listed separately for the extraction play.

**Example pivot (service keyword):**
- Keyword: "Couples Counselling" (DA gap: 25, too hard)
- Pivot: "Couples Counselling Lonsdale" (DA gap: 8, feasible)

**No pivot for informational keywords:** "How does birth order affect personality" is Low Feasibility too, but a neighbourhood variant ("…West Vancouver") is nonsense — nobody searches it that way. These appear under "Informational Keywords (no geo pivot)" and are handled by content extractability, not geography.

**Not-measured honesty:** If the pivot's validation SERP fetch fails, the local-pack column reads "not measured (validation fetch failed)" — a transient fetch error is never rendered as a real "not in local pack" result.

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
- If DA remains unavailable, use the Moz fallback. The account is the Starter Medium
  API plan, not the free tier; the real monthly row allowance is read at runtime via
  `quota.lookup` and recorded as `moz.rows_per_month` in `config.yml` (3,000 rows as
  of 2026-08-27, 1 row per URL looked up)
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

6. **Pivot to neighbourhood keywords (service keywords only)**
   - Run feasibility analysis (Step 7)
   - For low-feasibility **service** keywords (>15 gap), tool suggests pivots
   - Example: "Couples Counselling" (DA 25 gap) → "Couples Counselling Lonsdale" (DA 8 gap)
   - Create content for pivots first (easier wins)
   - Informational keywords are **not** pivoted — they surface under "Informational Keywords (no geo pivot)" for the content extraction play instead

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
