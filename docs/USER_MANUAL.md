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
- Fetches Domain Authority for the top 10 competitors ranking for that keyword
- Fetches Domain Authority for Living Systems **in the same request**, so both
  sides of the gap come off the same provider's scale (see "Whose DA is it?"
  below — this matters more than it sounds)
- Calculates gap: `(average competitor DA) − (Living Systems DA)`
- Assigns feasibility level:
  - **High Feasibility:** Gap ≤ 5 (rankable with quality content alone)
  - **Moderate Feasibility:** Gap 6–15 (needs local backlinks)
  - **Low Feasibility:** Gap > 15 (high-authority incumbents, pivot suggested)
  - **Not Measured:** fewer than 5 of the ranking domains carried a Domain
    Authority record, or Living Systems' own DA was never measured. The
    keyword is still listed, with the numbers that *were* measured, but with
    no verdict and no pivot — an unmeasured keyword used to be reported as
    "Low Feasibility", which looks identical to a real finding and triggered
    a pivot recommendation of its own.

**What the DA Coverage column tells you.** Both reports print the coverage the
average rests on: `7/10 (3 unscored)` means seven of the ten ranking domains
had a DA record and three did not. Read it before you read the gap. A gap
built on three domains is a weaker claim than the same gap built on ten, and
the two look identical without this column.

A domain the provider holds no authority for is **left out of the average**,
never counted as a DA of zero. Counting absences as zeros pulled the
competitor average down, which made the gap look *smaller* and the keyword
look winnable — so the tool recommended chasing keywords that DA-90
directories own, because the domains nobody scored counted as having no
authority at all. If you have older reports, their feasibility figures were
computed that way and should be regenerated.

**Whose DA is it?** The tool has two DA providers (DataForSEO first, Moz as
fallback) and *their numbers are not interchangeable*: both are 0–100 and both
are called "DA", but they are different vendors' models. Living Systems scores
19 on DataForSEO against the 35 recorded in `config.yml`. So the tool now
looks up Living Systems' own DA through whichever provider scored the
competitors, and the `Client DA` cell says where the figure came from:

- `19` — measured by the active provider. This is the number the gap uses.
- `19 (override)` — you passed `--client-da 19` yourself.
- `35 (config, not measured by moz)` — the provider had no record, so the
  `config.yml` value stands in. Its scale against that provider is unverified,
  so treat the gap as indicative, not like-for-like.
- `not measured` — no provider was reachable. Every keyword reads "Not
  measured"; the tool will not score live competitors against a fixed number.

**Where to look when a keyword has no verdict.** Both reports carry a **Not
measured — why** list under the feasibility table, one line per keyword,
saying which of three things happened: no DA provider was reachable (an
operator fix — set the credentials and run again), nothing in the keyword's
top ten could be scored at all, or too few of the ten carried a record for a
verdict. The line names the coverage, so you can see how close the run came.

**What a withheld verdict also withholds.** A keyword with no verdict is not
quietly treated as a bad keyword, and not treated as a good one either:

- No neighbourhood pivot is recommended and no paid Maps fetch is made for
  one. Earlier versions answered an unmeasured keyword with "Current keyword
  is feasible. No pivot required." — a conclusion in the opposite direction
  from the data.
- Section 1 states the coverage instead of saying whose site is stronger. A
  mean over two of ten domains is not a comparison.
- Section 0 will not name it as the single best opportunity. If no keyword in
  the run has a verdict, Section 0 says so and points at 5c rather than
  picking one on intent alone.
- It still appears everywhere a measured keyword does, including the brief's
  payload, so neither you nor the LLM sees a run of ten keywords as a run of
  the three that happened to be scored.

- Results are cached 30 days — re-running costs nothing. An *absence* is
  cached for 7 days rather than 30: "the provider has no figure for this
  domain" stops being true as soon as the provider crawls it, so the tool
  asks again sooner rather than reporting "Not measured" for a month after
  the figure became available
- For low-feasibility **service** keywords, suggests neighbourhood pivots (e.g., "Couples Counselling" → "Couples Counselling Lonsdale")
- Informational keywords (e.g. "how does birth order affect personality") get **no** neighbourhood pivot — a geographic variant is meaningless for a question nobody searches with a neighbourhood. They are listed separately for the content extraction play instead.
- If a pivot's validation SERP fetch fails, the tool says **"not measured"** rather than falsely reporting the client as absent from the local pack.
- Whether a keyword counts as a service keyword is decided by the **measured
  SERP intent** — what the result page actually turned out to be — and only
  falls back to reading the words of the keyword when no intent could be
  measured. The full run used to decide it on the keyword's words alone while
  the standalone feasibility script used the measured verdict, so the same
  keyword could get a pivot in one and not the other. The run now prints
  `[Pivot gate] N of M keyword(s) decided on a measured SERP intent; the rest
  on the keyword text`, so you can see which basis was used.

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
**What:** Calls an LLM to generate the content brief and advisory. Which provider and model is set under `report_llm` in `config.yml` (see "Choosing the report model" below).

**Requires:** Completed Step 1 (market_analysis JSON).

**Input:** JSON from Step 1 + LLM model selection (defaults: `report_llm.main_model` and `report_llm.advisory_model` in `config.yml`)

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

**Cost:** LLM calls. The ~$0.08–$0.40 per run figure was measured with Claude models; no figure has been measured for other providers. Prompt caching is used on the Anthropic path only.

#### Choosing the report model

**What it does.** The main report and the advisory briefing are written by one LLM provider. The provider is an entry in the shared key file `~/.config/llm/keys.json` (the same file your other tools read), named in `config.yml`:

```yaml
report_llm:
  provider: gemini-serp        # entry name in ~/.config/llm/keys.json
  main_model: gemini-4-hydrogen
  advisory_model: gemini-4-hydrogen
```

Any provider with the `anthropic` or `openai` dialect works. Google models are reached through Google's OpenAI-compatible endpoint, so a Google entry has `"dialect": "openai"`. The API key lives in the key file only, never in `config.yml`.

**Why it matters.** The models must belong to the provider. To go back to Claude, change `provider` to an Anthropic entry and both models to Claude model IDs; nothing else changes. The launcher's two dropdowns list that provider's live models (filtered by `model_include` / `model_exclude` so image, speech and embedding models are left out), with the two configured models first.

**Token limits.** `report_llm.main_max_tokens` and `advisory_max_tokens` cap the length of each answer. Some models, Hydrogen among them, reason before they answer, and that reasoning counts against the cap: on a 9-keyword run Hydrogen used about 19,000 tokens to produce a 10,000-token report. If you see "the answer was cut off at the N-token limit", raise the number. The run prints the token usage of every call so you can see how close it came.

**What a failure looks like.** There is no fallback to another provider or model. If the provider is missing from the key file, has no key, rejects the model, or times out, the step stops and names the provider and model. If the answer is empty, refused, or cut off at the token limit, nothing is written: a short report is never saved as if it were complete. Each LLM-written file ends with a line naming the model and provider that wrote it.

`brand_mentions.llm_model` and `sentiment.llm_model` (both features are off by default) are sent to this same provider, so they must also be that provider's model IDs.

**Timing:** 2–5 minutes.

---

### **Step 4: Refresh Analysis Outputs** (Optional)
**What:** Re-classifies the URLs in a stored run and rebuilds what that classification feeds, without re-fetching SERPs.

**When to use:** After you've manually corrected domain overrides (Step 6) and want the corrections reflected in the stored run.

**Input:** Existing market_analysis JSON + updated domain_overrides.yml

**Process:**
- Re-reads JSON SERP data (does NOT re-fetch)
- Re-applies classification rules with updated domain overrides to `organic_results` in the JSON and to the `Organic_Results` sheet in the XLSX
- Prints, for each of the two files, how many rows carry no usable domain (a Google redirect wrapper or a blank link) and therefore keep their existing `Entity_Type`. Those rows are not counted as updated on either side: the "N rows updated" figures are the rows actually written. The workbook also says so when it is missing, has no `Organic_Results` sheet, or lacks one of the Link / Source / Entity_Type columns — "0 rows updated" otherwise reads as "nothing needed changing"
- Rebuilds `keyword_profiles` from the re-classified rows — the entity counts, the entity distribution and the AI-Overview citation analysis are all derived from them — and prints how many profiles changed
- Regenerates `domain_override_candidates.md`

**What it does NOT rebuild** (and says so when it runs):
- The Markdown report. Re-render it yourself with
  `python3 generate_insight_report.py --json <json> --out <md>`.
- `keyword_feasibility`. Domain Authority comes from a paid API call, so the
  DA figures stay those of the run that fetched them.

A refresh is not a re-run. Anything that needs the SERP data itself, rather
than the rows already on disk, still needs Step 1.

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

**What the rank chart counts as history:** `visualize_volatility.py` plots only
the primary SERP query of runs that finished. A run can store rows for other
queries under the same keyword text — a neighbourhood pivot ("P") or an
AI-likely alternative ("S") — and those measure a different search, so a pivot
sitting at rank 1 is not the client at rank 1 for the keyword. A run that was
cancelled part-way has only some of its rows. Both are left out, and the chart
prints how many of the stored rows it left out, so a short line is not read as
a short history. The keyword menu lists only keywords that have rows left
after that, so it never offers a chart with nothing on it.

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

### **Step 7: Feasibility Analysis**
**What:** Scores Domain Authority from an existing market_analysis JSON, and
rewrites the market report with the feasibility section filled in.

**When to use:** Every run where you want a feasibility verdict, and again
whenever you want to re-score without re-fetching SERPs (DA results cache for
30 days, so re-running inside that window is free).

**This step is not optional if you want feasibility.** The Full Pipeline runs
steps 1.1-1.4 and feasibility is not one of them, so a pipeline run alone
never fetches Domain Authority, however `DATAFORSEO_LOGIN` / `MOZ_TOKEN` are
set in `.env`. Section 5c of the market report then says "Feasibility data
unavailable for this run" and names this step. Run it against that run's
`output/market_analysis_*.json` and the section fills in.

**Credentials:** `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` (primary,
pay-per-use) or `MOZ_TOKEN` (fallback). The Moz row allowance is read from
the account at runtime — no plan figure is recorded in this tool, so none can
go stale and mislead you.

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

**Your own domain is checked too.** Because your site is excluded from the competitor list,
its anchor text is sent separately (`moz.competitor.client_anchor_texts`, on by default,
one extra anchor page per run). This is what lets Tool 2 tell you if **someone else is
pointing spam links at you** — and on the first live run it found exactly that: the same
paid-link network that targets bowencenter.org is also pointing PBN anchors at
livingsystems.ca from 4 domains. That is a scraper working the whole niche, not something
anyone bought, which is why the report says links *received*.

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
| — | ⚠️ Not measured | Fewer than 5 ranking domains carried a DA record, or Living Systems' own DA was not measured. Not a verdict: the row says which case it is, and re-running once the DA provider is reachable fixes it |

A verdict needs at least **5** of the ranking domains to carry a DA record
(`feasibility.MIN_DA_FOR_VERDICT`). Below that the average, gap and score are
still shown — they are what was measured — but the status is withheld. Four
domains out of ten is not a finding about a SERP.

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

**One AI Overview, two different questions.** The tool asks Google for your
market (North Vancouver). When a keyword's located search returns no AI
Overview, it asks the same words again *without* a location, because that
tells you whether Google has an overview for the topic at all. The two are
not the same finding, and the report keeps them apart: `AI_Overview_Mode` on
the Overview sheet says which search the overview came from, and only an
overview on the **located** search counts as AIO exposure for you. An
overview that only the un-located search returned is reported as
`Has_Unlocated_AI_Overview`. Read it as "Google has an answer box for these
words somewhere, but not for a searcher here" — no estimated click loss is
charged against it, and no extraction play is routed on it. The
Parsing_Warnings sheet names every keyword where this happened.

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

**It is an estimate, not a measurement.** `Est. CTR loss` combines an
organic-CTR-by-position curve with an AI-Overview interception rate (~60%),
reduced by `citation_credit` when you are cited. Those numbers live in
`config.yml → aio_exposure` (`aio_ctr_multiplier`, `citation_credit`,
`ctr_curve`) and are yours to tune. **None of the three has a source on file.**
They were described as "industry reference points", but no study and no date was
ever recorded for them, and third-party CTR figures move year to year — so the
report now says, in the caveat under the table, that they are your working
assumption. When you find a figure you trust, write the citation into
`config.yml → aio_exposure.sources` (for example "Acme CTR study, published
2026-02, retrieved 2026-03-01") and the report prints that instead. For
*first-party* click loss, see the GSC sponge-effect analysis.

Because AIOs change constantly, the section trends coverage and cited-share across
runs — read the movement, not one number. The trend compares **only runs that
covered the same keywords.** Coverage and cited-share are shares of the keywords a
run looked at, so adding one local keyword that happens to show an AI Overview
would raise "AIO coverage" with nothing about the market having changed. Runs with
a different keyword set are named and left out of the comparison instead.

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
is a sign the brand is compounding, not eroding. The report bands the share against two
reference figures (below-average < 2.4%, top ≥ 10%) — reference points, not targets
for this client. **Neither figure has a source on file**, so the report says they are
your working assumption; write a citation into `config.yml → gsc_demand.bands.source`
and it prints that instead.

**Which share is the headline.** Two shares are reported, because they answer
different questions:

- **Over the whole property** — every query your site got clicks on in the window.
  This is the figure about your demand, and it is the one the band is taken from.
- **Over this run's tracked queries only** — the keywords in the CSV this run used.
  This one moves with the keyword file: add a branded keyword and it rises with
  nothing about your demand having changed. It is shown for context, labelled, and
  never compared against the property figure.

The property figure needs a live pull: when the run was served from the 7-day cache,
or the pull did not finish, the report says there is no property-wide figure this run
rather than letting the tracked figure stand in for it.

**Reading it honestly.** GSC's 2–3 day reporting lag means the most recent run is
provisional. Because Search Console returns per-query totals (not per-day), the trend
builds up run over run, and a run measuring one share is never differenced against a
run measuring the other.

### Demand vs Clicks

**What it is.** Section 5f of the market-analysis report puts the AI-Overview coverage
(how often an AI answer sits above your results) next to your actual Search Console
clicks, and estimates how much of your traffic those AI answers are likely intercepting.

**Why it matters.** It's the one place the "ranking ≠ traffic" problem is made concrete
for your own site: you see the share of your keywords with an AI Overview, whether you're
cited in it, and a rough estimate of the clicks at risk on the keywords where you're not.
That turns an abstract worry into a shortlist.

**The "at risk" figure cannot exceed the clicks you have.** An AI Overview can only
take clicks your site actually receives, so the estimate is a *share* of your measured
clicks for that keyword — the modelled interception rate (60% by default, halved where
you are cited) applied to the clicks Search Console counted. It cannot come out above
them. The earlier version multiplied the rate by your *impressions* instead, and
reported a page with 1 000 impressions and 5 clicks as having 168 clicks at risk;
capping that at the measured clicks was no better, because it then reported all 5 of
them. A keyword with an AI Overview and no clicks at all has nothing left to intercept,
so it adds nothing to the total — but those keywords are listed by name under the
figure, because having no clicks under an AI answer is the worst case, not a blank.
The window the Search Console figures cover is printed with them, and so is the
country and device the figures are for: the dashboard reads only the Search Console
rows pulled for the population you configured, so a Canadian-desktop pull and an
unfiltered one are never added together.

**What it does and doesn't show.** It's a **snapshot** — the point-in-time position, not
a trend. The full "demand holding while clicks fall" trend line is deliberately not built:
it would need per-keyword search-volume data (which the SERP sources don't provide) and
daily Search Console history (Console gives per-query totals), so inventing it would be
guessing. For the demand trend that *can* be measured honestly, see the
branded-vs-non-branded share in the GSC analysis report. If GSC isn't connected, this
section shows the AI-Overview coverage and points you to connect GSC for the clicks overlay.

### Keyword Prioritization: Feasibility > Intent > Intent certainty

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

**When a SERP is mixed.** Some SERPs serve more than one intent at once. The
`mixed_intent_strategy` field says what to do about it, and it is decided
against `client.preferred_intents`:

- `compete_on_dominant` — the intent the SERP mostly serves is one you serve.
  Write for that intent. `mixed_intent_lead` names which one (if you already
  rank for one of the tied leaders, that one).
- `backdoor` — you only serve a *minority* intent on this SERP. There is a way
  in, but you are writing against the grain of what Google is showing.
- `avoid` — none of the intents on this SERP is one you serve.

`mixed_intent_dominant` lists the leading intents and `mixed_intent_dominant_tied`
is true when two or more lead by the same share, so a tie is reported as a tie
rather than broken silently (D-M-11).

**"Market too small"** is a judgement about *demand*, so it is read from the Moz
monthly search volume against `moz.keyword_metrics.min_volume_for_investment`
(default 20). It used to be read from Google's "about N results" page-count
estimate, which counts indexed pages, not searchers, and is missing on many
SERPs — a missing estimate was read as zero, so the keyword was called too
small on no evidence at all (D-M-12). A keyword with no volume figure is no
longer called too small; the absence is stated instead.

**3. Intent certainty** — *How clearly does one intent lead?*
- **Why it matters:** Some keywords have clear intent (e.g., "book couples therapy" is obviously transactional). Others are ambiguous (e.g., "couples counselling" might be both local and informational). A low-certainty verdict means you need to validate the intent manually before investing in content.
- **How it works:** Certainty is the share of the *classified* results that agreed on the leading intent, measured against `serp_intent.thresholds.confidence_high` (0.8) and `confidence_medium` (0.5) in `config.yml`. Six of ten results informational and four commercial is a 60% share — medium.
- **Read it beside Coverage.** Coverage is a different number: how many of the ten results could be classified at all. It is capped by `enrichment.max_urls_per_keyword`, so raising that raises coverage without any SERP having changed, and results below the enrichment limit are classified from the URL shape only. Both columns are printed, because eight results unreadable and the other two agreeing is a 100% share over a coverage of "low" — not a certain verdict.
- **Before November 2026** one column called "Confidence" showed the coverage count alone, so a 6/4 split read as "high confidence" and the two `confidence_*` settings had no reader at all (review findings D-M-10, D-C-17).
- **Priority:** **Within the same feasibility and intent level, prioritize high-certainty keywords.** They're easier to target and less likely to surprise you mid-way through writing.

#### Ranking Logic in Practice

**Example 1: Two high-feasibility keywords**
- Keyword A: Feasibility = High, Intent = informational (matches), Certainty = high
- Keyword B: Feasibility = High, Intent = local (matches), Certainty = medium

→ **Pursue A first**, then B. Same feasibility; A has higher confidence.

**Example 2: Mixed feasibility**
- Keyword A: Feasibility = Moderate, Intent = informational (matches), Certainty = high
- Keyword B: Feasibility = Low, Intent = informational (matches), Certainty = high

→ **Pursue A first**, then B. A is more feasible.

**Example 3: Feasibility vs. intent match**
- Keyword A: Feasibility = High, Intent = commercial (does NOT match preferred intents), Certainty = high
- Keyword B: Feasibility = Moderate, Intent = informational (matches), Certainty = high

→ **Pursue B only.** A is off-limits because the intent doesn't match, regardless of feasibility.

Section 0's single "best opportunity" applies that rule too. It previously ranked
on feasibility and used intent only to break ties, so it could name the one
keyword the action column marked ⛔ Mismatched intent two lines below. It now
picks only from keywords that pass both gates, and when none does it says how
many were blocked by intent mismatch versus how many have no intent verdict at
all — the first means widening `client.preferred_intents`, the second means
re-running with more enrichment.

#### What If Feasibility Data Is Missing?

Domain Authority data comes from external APIs (DataForSEO or Moz). Moz needs only `MOZ_TOKEN` in your `.env` — the audit previously looked for `MOZ_ACCESS_ID` and `MOZ_SECRET_KEY`, which this project never used, so Moz enrichment stayed off during audit runs no matter what was configured. It now runs whenever `MOZ_TOKEN` is set and `feasibility.enabled` is true, and the run log reports how many API rows each fetch billed (cache hits bill nothing). If those APIs fail or credentials aren't set up, feasibility data may be unavailable. In that case:
- Intent match becomes the primary ranking factor (still required to pursue)
- Intent certainty becomes the secondary ranking factor
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
  location: "North Vancouver,British Columbia,Canada"   # the market measured
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

#### The two settings that name a market must agree

`serpapi.location` decides which market Google is asked about.
`feasibility.non_profit_location` decides which market the feasibility
verdicts and the neighbourhood pivots assume. If they disagree, the run
measures one city and scores another, and every competitor, local pack and
Domain Authority gap in the report belongs to the wrong place.

That happened on 2026-11-14: the run searched Vancouver while feasibility
scored North Vancouver, so the client's absence from all nine map packs meant
nothing. Saving a config where they disagree now raises a warning naming both
settings and the place fields they differ on. The check compares every field
both of them name, so "North Vancouver, British Columbia" counts as agreeing
with "North Vancouver,British Columbia,Canada", while a North Vancouver in
Washington does not. It is a warning rather than an error because measuring a
neighbouring market deliberately is a reasonable thing to want.

Use the name SerpAPI itself uses — look it up at
`https://serpapi.com/locations.json?q=<city>` and copy the `canonical_name`
("North Vancouver,British Columbia,Canada"). A location SerpAPI does not
support is an error it returns rather than a result, and the run now stops
fetching that query immediately instead of retrying three times with backoff:
a setting it has rejected once will be rejected again, and the retries spend
the search allowance to be told so.

#### Why some rows say "Not Measured" for page-level figures

Google no longer puts the destination URL in a search result. Since late 2026
it serves `https://www.google.com/goto?url=…` with the real address hidden
inside, and the tool can recover only the **site**, not the page that ranked.
Those rows are marked `Is_Destination_Page = FALSE`, and everything that is a
property of the page reads **Not Measured** rather than a figure taken from
the site's front page: `Word_Count`, `Content_Type`, the schema / FAQ / author
signals, and `Page_Authority`.

There is a second reason a row reads Not Measured, and the new
**`Fetch_Status`** column tells you which it was:

| `Fetch_Status` | What happened | What to do |
|---|---|---|
| `Enriched` | The page was read. | Nothing — the page-level figures are real. |
| `Blocked (403)` / `(429)` / `(503)` | The site answered with an error or a bot challenge instead of the page. | Nothing is wrong with your analysis; the site refused this reader. The figures read Not Measured rather than zero. Re-running later often works, since a block is usually temporary. |
| `Not Read (network, retry)` | Every attempt failed at the network layer — a timeout, a connection reset, a host that did not resolve — after the fetch had already retried with backoff. | Re-run. This is a fact about the attempt, not about the page: it says nothing about the site, and the page may read fine next time. Several of these in one run usually means your own connection. |
| `Unreachable` | No request could be made at all — a URL the fetcher cannot form a request for (no scheme, an unparseable address) or a redirect loop. | Retrying will not help. Check the URL on the SERP row. |
| `Not Fetched` | The result ranked below the enrichment cap (`technical.max_urls_to_enrich`), so the page was never asked for. | Raise the cap if you need page-level detail further down the SERP. |
| `Not The Ranked Page` | Google hid the destination URL (see above). | Nothing — the site-level findings stand. |
| `No URL` | The result carried no link at all. | Nothing — there was nothing to fetch. |
| `Not Enriched (disabled)` | Page enrichment was switched off for this run (`technical.enrichment_enabled`). | Switch it on if you want page-level detail. |

Beside the words there is a machine-readable **`Fetch_State`** column
(`enriched`, `blocked`, `fetch_retryable`, `unreachable`, `not_attempted`,
`not_destination_page`, `no_url`, `enrichment_disabled`). The words in
`Fetch_Status` are editable in `serp_vocab.yml`; anything that filters or
counts rows reads `Fetch_State`, so re-wording a status never changes a
number.


The distinction matters because a blocked page used to be read as a *measured*
page. A Cloudflare "Checking your browser" page contains about six words, no
author byline and no FAQ markup, and all three of those used to be filed as
facts about the competitor's page: a thin, anonymous, unstructured article
that your own page could easily beat. It was never that page. The run log and
the **Parsing_Warnings** sheet now say "N of M pages returned an error status
and were not read".

What still works is everything that is a property of the site: who the
competitor is, what kind of organisation they are, and the Domain Authority
that drives the feasibility gap. So feasibility, intent, the local pack and
the competitor set are unaffected; only "how long is their page and what is
on it" is lost. A result whose site cannot be recovered at all is reported
with no URL and excluded, never filed under google.com.

The same hiding reaches the AI-visibility probes, where the question is
whether the AI Overview cited *you*. A citation whose site cannot be
recovered cannot answer that either way, so the probe row carries
`Citations_Unresolved` alongside `Client_Cited`. Read them together:
`Client_Cited = FALSE` with `Citations_Unresolved = 0` means you were not
cited, and the same FALSE with a count above zero means the question was not
settled — one of the untraceable citations may have been yours.

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

### What "Rank" means, and why older outputs disagree

Every rank in your outputs — the `Rank` column in the workbook, `client_rank`
in the JSON, the handoff's target ranks, the "top 10" the feasibility table
scores — is the **real position on the Google results page**. Rank 12 means
twelfth; it is not "second on page two".

That was not true of runs before 16 November 2026. The SERP provider numbers
each page of results from 1, so a three-page fetch came back as 1–10, then
1–10 again, then 1–10 again, and the tool stored those numbers as they came.
Three different pages all looked like rank 1. The practical effects, all now
fixed:

- **Your own position was flattered.** A page sitting around 25th was reported
  as 7th, because it was 7th *on its page*. In one audited run the report said
  the client ranked 7th while 17 competitors sat above it.
- **"Top 10" was not the top 10.** The ten URLs the feasibility table measured
  your Domain Authority gap against were drawn from positions 30 to 50. The
  gap, the status (High / Moderate / Low Feasibility) and the pivot advice were
  all computed against the wrong competitors.
- **Page fetching spread too thin.** `enrichment.max_urls_per_keyword: 5` was
  letting about 14 pages per keyword through, since it admitted five per
  fetched page. It now means five pages per keyword. If you want the old
  breadth of enriched pages, raise that number — it is a real cost, roughly
  one page fetch each.
- **Rank changes between runs could be invented.** Deltas now compare against
  the previous run that actually finished, using only the main query's rows.
  Runs that aborted part-way, and the alternative phrasings the tool tries,
  no longer act as a baseline.

**What this means for you:** any `market_analysis_*`, `feasibility_*` or
`competitor_handoff_*` file from before 16 November 2026 has wrong ranks, and
every number derived from them — feasibility gaps, recommended plays, the
competitor lists sent to Serp-Compete — is wrong with them. Re-run the audit
on any keyword set you are still working from. Run-to-run rank history also
starts fresh: older rows carry no record of which query produced them, so the
tool reports that it cannot compare them rather than guessing.

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
| 0. Executive Summary | The single best keyword, the first thing to write, and how many ranked results could be classified |
| **1. What To Write** | The ranked content plan — one numbered option per keyword |
| 1b. Market Overview | Which search-page features appeared, and on how many keywords |
| 2. The 'Anxiety Loop' | Real questions searchers ask, to use as page headings |
| 3. The Words Competitors Use | Vocabulary already on the results page |
| 4. Strategic Recommendations | The Bowen argument the page should make, with how much of the page set carries each pattern's trigger words |
| 5–5f | The underlying data: competitor mix, intent, feasibility, AI Overview exposure, commodity risk |
| 6. Market Volatility | Rank movement since the last run of the same keywords. When it cannot be measured the section says why — no completed previous run, no primary-query rows, or no URL ranked for the same keyword in both runs — rather than disappearing |
| **A. Glossary** | Plain-English definition of every term of art used above, plus where every band and weight in the report came from |

**How to use:** read Section 1, write the page, and drop into the numbered
sections when you want the evidence behind a recommendation.

##### "Ranked results classified: N of M" — read this line first

Section 0 states how many of the run's ranked competitor results could be
classified, and, for the rest, what stopped them, counted by the reason each
row recorded:

> **Ranked results classified:** 15 of 221. SERP intent is read from
> classified results only, so a keyword with few of them gets no intent
> verdict and no page recommendation. The rest were not classified because
> 125 × Not The Ranked Page, 58 × Not Fetched, 14 × Blocked (403), 9 × No URL.

**Why it matters:** a keyword's SERP intent is read from the content types of
the pages ranking for it. Where few of them were classified there is no intent
verdict, the action column reads `❓ Intent unknown`, and the content plan
recommends no page — not because the keyword is bad, but because the run could
not see enough of the results page. The line tells you which it is, and what to
change:

- **Not The Ranked Page** — Google returned a redirect that could only be
  resolved to the competitor's home page, so the actual ranking page was never
  read. Nothing to fix locally; re-running usually returns direct links for a
  different share of results.
- **Not Fetched** — the result sat past `enrichment.max_urls_per_keyword`, or
  enrichment was off. Raise the cap or switch it on.
- **Blocked (NNN)** / **Not Read (network, retry)** — the competitor's site
  refused or never answered. Nothing to fix; those pages stay unclassified.
- **No URL** — the result carried no link at all.

When nothing at all was classified the line says so outright ("none of M")
rather than "0 of M", because no keyword can have an intent verdict on that
run, and the report's ten "Deprioritise" verdicts are an absence of evidence
rather than a judgement about the keywords.

The wording lives in `serp_vocab.yml` under `classification_coverage`.

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
- **Feasibility**: High / Moderate / Low (DA gap). The three bands are editorial — somebody chose them as sensible for a local nonprofit, and the report's glossary appendix says plainly that nobody has checked them against whether the keywords it called High were ones you went on to rank for
- **Weakest (non-dir)**: the lowest Domain Authority holding a top-10 slot, and the lowest that is not a directory. This is the figure that answers "does anything my size have room here", which the average cannot: one Psychology Today listing moves the average far enough to hide nine small clinics. `12 (?)` means no ranking page carried an entity type this run, so the directory split was not measured — it does not mean no directory ranks there. A `?` after the second figure (`12 (40?)`, `12 (none?)`) means only some of the ranking pages were classified, so that figure stands over those and not over the top 10 — with one page classified, the "weakest non-directory" can be the strongest site on the page, and the sentence in section 5c says how many were classified
- **Top competitors**: Domains that rank + their entity types
- **Recommended content**: Specific article titles, sections, format (guide, FAQ, local page)
- **Content angle**: How to frame it (Bowen systems approach vs medical model)
- **Classification coverage**: High / Medium / Low — how many of the ten ranking URLs could be classified at all, not how clear the intent is
- **Intent certainty**: High (one intent clearly leads) / Medium (some ambiguity) / Low (no intent leads) / not measured (nothing on the page was classified)

**How to use:** Content team uses this to build the publishing roadmap. Start with high-feasibility, high-certainty keywords — and check the coverage beside the certainty, because a share measured over two readable results is not the same evidence as one measured over ten.

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

#### What Section 4's "Triggers found" line actually measures

**What it is.** A Bowen pattern is reported when one of its trigger words
appears in the SERP text the run collected — the snippets, the ad copy, the
related searches — which is not the same as the body text of the ranking
pages, and holds several entries per result. The line under each pattern says
how many of those text blocks carry each trigger and how many carry any of
them at all: "clinical (1 of 20 SERP text blocks) — 2 of 20 scanned SERP text
blocks carry at least one (10%)". It says "text blocks" rather than "pages"
because a page-level count is not what was taken.

**Why it matters.** This is trigger-word presence. It is not an analysis of how
those pages frame the problem, and a pattern that fired in one text block out
of twenty is not evidence that the market thinks that way. Until the counts were
printed, every fired pattern read the same — and four of the triggers were
words that appear on essentially every counselling page in BC ("registered" is
in every RCC byline, "mental health" is the topic's own name, "close" and
"communication" are the vocabulary of every couples page), so those patterns
fired on every run and the verdict carried no information. Those four triggers
have been removed. If you add a trigger to `strategic_patterns.yml`, add
vocabulary only somebody inside the trap would use — the file's own rule at the
top says the same thing.

**Where no count appears.** "trigger-word presence not quantified this run"
means no page text reached the matcher. It does not mean the triggers were
looked for and found on no page.

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

**Every persona gets asked something.** The question list is capped (by
`ai_visibility.max_questions` and by the `max_total_calls` ceiling), and the
cap now takes one question from each persona before a second from any. It used
to take the list in order, and because the prospective-client persona
generates far more questions than the others, a 27-question plan cut to 20
asked **twenty prospective-client questions and none at all** for the
clinician/trainee or the referrer — whose rows then read as no data, which
looks like the AI ignoring those audiences rather than the tool never having
asked. The plan line now prints how many of the generated questions the run is
asking, and names any persona the cap still left with none.

**A tie is not a loss, and a generic word is not a rival.** Two things about
the competitor leaderboard were misleading. Brands on the *same* mention count
used to be ranked by alphabetical order, so a client tied with one rival on
two mentions each was reported as "#3" behind it; equal counts now share a
rank and the report says "tied with 1 other brand(s) — not ahead of them".
And the brand list is harvested from the competitor names Google shows, which
included bare words like "Indeed" and "Pathways": "Indeed, there are several
options" counted as a mention of a competitor called Indeed, which then took a
leaderboard place beside a real practice. A harvested name now has to be two
or more words, or a single word that also appears in its own website's
address (ZipRecruiter; and "Indeed" beside `ca.indeed.com` counts, because
"indeed" is part of that address — an earlier version of this rule looked
only at the first part of the address and so threw away any one-word brand
on a `ca.*` or `blog.*` host, which in a Canadian directory market is most
of them). You can drop any others outright by adding them to
`ai_visibility.generic_source_stoplist` in `config.yml`. Brands you list
yourself in `known_brands` are never filtered, and the log says how many
harvested names were dropped and why.

**A dash in the Brand column is a question, not an answer.** The citations
table names the brand behind each cited URL where it can, from the
`known_brands` list in `config.yml`, and prints "—" where it cannot. That dash
meant two different things: this citation is from nobody we track, and this
citation has no brand at all. Nothing counted them, so an engine citing twenty
untracked competitors read the same as an engine citing none. Under the table
the report now says how many of that engine's citations carry no brand — by
citation count, not by row, because one untracked domain can be cited a dozen
times — and where to put them: `config.yml → known_brands`, with the
candidates the run already surfaced in
`brand_mentions_candidates_<topic>_<timestamp>.md`. Where *nothing* could be
attributed the line says so in its own words, because that is the case where
the leaderboard above holds no competitor at all and would otherwise read as
"no competitor is cited".

A shared rank is also not a win in the **score**: the Ranking axis that feeds
AIVI used to give a client tied at first place with five other brands a
perfect 100, a few lines away from prose saying "not ahead of them". A tie now
scores the mid-point of the places the tied brands occupy. And where several
brands tie for *top competitor* — the one benchmarked in the Sentiment
section — the report names the tie instead of letting alphabetical order
present one of them as the leader.

**What counts as naming you.** A mention now has to match your name on a word
boundary, and you can list phrases that contain your name but do not mean you
under `ai_visibility.negative_terms`. For Living Systems this matters
directly: "living systems theory" is the academic subject the practice teaches
about, and an answer explaining that theory was being counted as the AI
recommending Living Systems Counselling — inflating the mention rate with
answers that never named the practice at all.

The exclusion applies to the *phrase*, not the whole answer. An AI answer
runs to several paragraphs and often explains the theory in one and names the
practice in the next; vetoing the entire answer would have thrown away the
real mention along with the false one. The same word-boundary test and the
same exclusion list now also govern the competitor leaderboard and which
answers buy a sentiment classification — before, the fix applied only to the
mention rate, so the inflated figure simply moved to your rank, your
authority sub-score and your sentiment.

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

**An `n/a` says which `n/a` it is.** The structure / schema sub-score is
`n/a` for two quite different reasons: you have no page in any keyword's
top 10 this run, so none of your markup was ever fetched; or no schema
contexts are configured for the tool to measure against. Both printed a bare
`n/a`. The report now states the reason beneath the table, and in the first
case it still lists the schema recommendations as gaps — they are advice, not
a measurement, and a site with no page in any top 10 is the one that needs
them most. Because the sub-score changed what it measures (your own page,
not the whole top 10), the "Δ prior" figure is suppressed across that
boundary rather than printing a change of definition as a change in
readiness.

**A sentiment classification that failed is not a neutral one.** When
sentiment is enabled, each answer that names you (or the top competitor) is
classified positive / neutral / negative by one LLM call. A call that errors or
comes back unreadable is now recorded as **failed** with no verdict, left out
of the "% positive" and out of AIVI's Sentiment axis, and the report states
what the percentage is over ("1 classified of 3 attempted"). Before, every
such failure was stored as **neutral**, so a run throttled by rate limits
produced a wall of neutral verdicts and a Sentiment axis of 0 — a confident
reading of how the AI portrays you, assembled entirely from calls that never
answered. If every classification for a brand fails, the line says so and asks
you to re-run.

A classification that was never *attempted* is a third state. Sentiment calls
count against the same `max_total_calls` ceiling as the probe questions, so on
a long run the budget is often spent before the sentiment pass begins. Those
answers are now recorded as **skipped (budget)**, and the line says the budget
ran out — it used to print "no answer this run portrayed this brand" over
answers that did portray it, which is the one reading that would make you stop
looking.

**"Not measured" is not a zero.** An engine the run could not reach — no API
key, every call rate-limited or safety-blocked — now carries **no** AIVI at
all. It is listed by name with the reason ("skipped — no API key", "0 of 20
calls returned an answer"), it is left out of the all-engine average (which
says how many engines it is over), and it is left out of the platform
prioritisation. It used to score 0, and because a low AIVI means "high
opportunity", the engine the tool could never reach came out **top of the
list of where to spend next**. Its history is still shown, so a gap in the
trend reads as a gap. Where the report quotes the all-engine average it
now says how many engines that average covers ("over 1 of 4 enabled
engines"), and an engine that answered nothing has its leaderboard and
citation headings read "not measured — 0 of 20 calls returned an answer"
instead of "no brands were named" — which would have told you the AI named
nobody, when in truth it never answered.

**"Enable another engine" versus "run it again".** The cross-engine transfer
section compares which sources each engine cites, so it needs two engines. It
now tells you which of the two situations you are in: with only one engine
switched on it asks you to enable a second, and when several engines were
switched on but only one answered it says so ("only 1 of 4 enabled engines
returned an answer") and asks you to re-run. Before, both read as the first,
so a run spoiled by rate limits looked like a configuration you had got
wrong.

Two more things changed with it. The per-engine table now reads **"answered N
of M (K failed)"**: a call that errored, or that came back with no text and no
sources, is recorded as a failure and carries no verdict, and both mention and
citation rates are over the answers you actually got. Before, a blocked answer
was filed as "the client was not mentioned" and an errored call vanished from
the denominator, so a half-blocked engine read as a fully-measured one with a
bad score. And where two engines each cited nothing, the citation-overlap
figure used to read **1.00** — perfect agreement — because two empty sets are
technically identical; it now reads "not measurable", which is what it is.

What to do about it: re-run the engine before you act on its absence. An
engine with no measurement is not an opportunity and not a weakness — it is
a question you have not asked yet.

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
stored each run so you can watch it climb. When *all three* sub-scores are
`n/a` — or every weight in `foundational.weights` is zero — the headline reads
"**Foundational readiness: not measured**" with the reason. A row is still
stored for the run — the run happened — but with no score, so no Δ is ever
computed against it. It used to read "0.0/100" and store that zero, so the
next run's Δ was measured against a number nobody measured.

**What "the client's own pages" means for the structure sub-score.** It is
measured strictly from the markup on *your* pages, and your page has to be in
one of the fetched top-10s for the tool to have read it. When you rank nowhere
for any keyword in the run, this sub-score is **n/a** — the tool has no
measurement of your markup — and it is dropped from the average rather than
counted. Until this was corrected it read the markup of the whole top-10, so a
client who appeared in none of them was scored on its *competitors'* schema and
could be told it was two-thirds of the way there on markup it had never been
measured for. If you see `n/a` here, the fix is to get a page ranking (or add a
keyword you do rank for) so there is something of yours to read.

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

**One country, one device.** The pull is restricted to the same country and
device the SERP fetch used (`config.yml → gsc.country` / `gsc.device`,
defaulting to `serpapi.gl` / `serpapi.device`), so a CTR here and a rank there
describe the same searchers. The filters are printed beside the window at the top
of the report. Set either to `all` to pull everything, and the report warns that
the two sides are no longer comparable.

**Why it matters — the "sponge" effect:** the SERP tool sees rank but
never clicks. A page can hold position #3 and still starve, because an AI
Overview above it answers the question and soaks up the click. That loss
is invisible in ranking reports; it only shows in the client's own CTR.

**How to read the sponge table:** the table compares the *median CTR at
comparable position* — e.g. among queries where the client ranks 1–3,
what's the typical CTR when an AI Overview is present vs when it isn't?
- A **lower AIO median at the same position band** is an **association,
  not a measured effect**: the two buckets are different queries, differing
  in more than whether an AI Overview appeared, and nothing here is a
  before-and-after on the same query. Read it as a signal worth following,
  not as proof the overview took the clicks. The report says so above the
  table.
- Each band is only compared when **both** buckets hold at least 3
  queries; otherwise the row says "insufficient data" — the tool never
  extrapolates from one or two queries.
- A query needs at least **50 impressions** in the window to count at all
  (`config.yml → gsc.min_impressions`). One click on three impressions is a
  33% CTR and means nothing. The report says how many queries fell below
  the floor, so you can see what was left out.
- The **reformat candidates** list below it names the queries that rank
  well (top 10), **have an AI Overview on the SERP**, and earn a CTR at
  least **25% below** the no-AIO median for their band
  (`config.yml → gsc.reformat_ctr_margin`). Both conditions matter: half of
  any set is below its own median, and a page with no AI Overview above it
  is losing clicks to something else. Rows flagged ⚑ also
  carry a GEO alert (the client ranks but the AI Overview cites other
  sources): reformat those pages for answer extraction FIRST, because
  fixing them can win back both the citation and the click.
- A query can be missing from the figures for two different reasons, and
  the report says which:
  - **"no impressions in window"** — Search Console answered, and holds no
    impressions for that query in the window. That is a real finding about
    the client's traffic, reported as absent and never invented as zero.
  - **"not reached"** — the Search Console request failed, or stopped
    part-way through. That says nothing at all about the client. Nothing is
    cached for those queries, so the next run asks for them again; the
    report prints an **"Incomplete fetch"** warning at the top of the
    Coverage section, every count below it covers only the queries that
    were reached, and no branded-share figure is written to the trend
    (a share of a truncated set is not comparable with other runs). When
    you see that warning, re-run before quoting any of the numbers.
- The bands themselves (positions 1-3 / 4-10 / 11-20) and how many queries a
  band needs before it reports a median (3 in each bucket) are settings, not
  fixed rules: `gsc.position_bands` and `gsc.min_bucket_size` in `config.yml`.
  Widen the bands if your pages sit deeper than the defaults assume; raise the
  bucket size if you want a median only over a larger group. A band that
  cannot hold a query, bands that overlap or leave a gap, or a bucket size
  below 1, are refused with a warning and the default used, because a
  "median" over one query is not a comparison and a query must count once.
  If you widen the bands past position 10, raise `gsc.reformat_max_position`
  with them: the reformat shortlist only considers queries at or above that
  position, and the run warns when the two cannot agree.
- "Insufficient data" in a sponge band means the band genuinely did not have
  enough queries — unless queries were never reached, in which case the row
  says so, because a gap in the fetch is not a measurement of the client.
- The reformat-candidates section states how many queries it searched. "No
  candidates" over 4 of 40 queries is not the same statement as "no
  candidates" over 40 of 40.

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

## Stopping a run, and one run at a time

- **Stop button** (beside "Run Selected Script"): enabled only while a script is running. It asks
  for confirmation, then ends the script and everything it started (the pipeline starts the
  audit as a separate process; both are ended). The log shows `STOPPED`. A stopped audit writes
  no output files and leaves `config.yml` pointing at the previous run. SerpAPI calls already
  made are still charged, and their responses stay under `raw/<run id>/calls/` (see "Resuming
  an unfinished run" below).
- **Nothing is written until a run starts.** Clicking Run and then cancelling at a prompt
  changes no file. Keywords typed into the new-keywords box are added to the keyword file
  only when the script actually starts; the log names the file. `config.yml` is updated with
  the keyword file and output paths only when the audit step has written all its outputs, so
  a run that is stopped or fails during the audit leaves it pointing at the last good run.
  (A run that fails in a later pipeline step, such as the xlsx/JSON check, has already
  recorded the new paths.)
- **A keyword file is never replaced.** New keywords with no file selected are saved as
  `keywords_<first keyword>.csv`. If that file already exists with different keywords, the
  launcher asks "Add the new keywords to it?" and says how many keywords the run will then
  use. Yes adds them; No cancels the run and leaves the file as it was.
- **Run is disabled for the whole run.** Clicking another script in the list no longer
  re-enables it, so a second pipeline cannot be started by accident.
- **A pipeline started somewhere else** (a second launcher window, a terminal) from the same
  folder also disables Run. The log names the process. Click any script in the list to check
  again once it has finished.
- **Closing the window during a run** asks "Stop the run and close?". Yes ends the run first;
  No keeps the window open. Cmd-Q asks the same question. If the launcher is ended some other
  way (Ctrl-C in its terminal, the terminal closed), the run is ended with it. The run is never
  left going with no window.
- **Why it matters:** each run spends SerpAPI credits. Two runs at once write the same output
  and config files, and a run with no window could not be seen or ended.

## Troubleshooting

### "Process finished with status FAILED (exit N)"
**What it means:** the step did not complete. The log lines above it say why. A run now fails,
instead of reporting success, when:
- the SerpAPI key or the serpapi package is missing, or the keyword CSV cannot be read;
- no query returned usable SERP data ("Fetched 0 of N queries") — no output files are written;
- the JSON, XLSX, Markdown or competitor-handoff file could not be written (for example the
  workbook is open in Excel). `config.yml` keeps pointing at the previous run's files, and the
  files that were written are renamed with a `.failed` suffix, so no later step reads a
  half-written run. Remove the suffix by hand if you want to inspect them;
- the pipeline cannot find the audit's output files.

`MISMATCH` is used only for the data-validation step, when the workbook and the JSON disagree.

### "Fetched N of M queries — K failed"
**What it means:** some queries returned no data but the run continued, because the rest of a
paid run is still worth reviewing. The failed queries are named in the log and stored in the
JSON under `fetch_summary` (`planned`, `fetched`, `failed`, and `pivot_failed` for the
secondary pivot-keyword fetches). The report covers only the queries
that were fetched; re-run the failed keywords if they matter.

### Resuming an unfinished run
**What it does:** every SerpAPI response is saved to its own file under
`raw/<run id>/calls/` as soon as it arrives. If a Full Pipeline run is stopped, crashes or
fails, the next time you start Full Pipeline for the same keyword file the launcher asks:
"The last run for keywords_x.csv stopped after N stored responses, X minutes ago. Reuse them?"
- **Yes** — the audit runs again from the start, but takes every search it already has from
  disk and only pays for the missing ones. The end of the log reads
  "Reused N stored responses; made M new SerpAPI calls".
- **No** — everything is fetched again.

**Why it matters:** before this, a run that failed on keyword 18 of 20 lost all 18 paid
results. Now it costs only the searches that had not been made.

**Limits to know:**
- A stored response is reused only when the search is identical (same query, location, mode,
  page). Changing the API mode or location between runs means those searches are paid again.
- Stored responses older than `serpapi.resume_max_age_hours` (24 by default; 0 = never
  reuse) are not offered, because search results change.
- A resumed report mixes results fetched at different times. The output JSON records this
  under `fetch_summary` as `resumed_from` (the earlier run id) and `reused_calls`.
- Only the newest run for the keyword file is offered, and only if it did not finish. A run
  that wrote its outputs but had failed queries ("Fetched N of M") counts as unfinished, so
  the failed queries can be retried without paying for the rest again.
- A search whose follow-up calls (AI Overview, related questions) had not finished is
  fetched again, because the follow-up tokens in a stored response expire. Expect the last
  keyword of the stopped run to be paid for a second time.
- With `serpapi.no_cache: true`, answering Yes still reuses the stored responses; they were
  fresh when the earlier run fetched them.
- Only the audit's searches are stored. The pivot searches made by Run Feasibility Analysis
  are not.
- From a terminal: `SERP_RESUME_RUN_ID=<run id> python3 serp_audit.py`. A run id that does
  not exist stops the run with an error rather than fetching everything at full price.
- `raw/` is never cleaned up automatically. Delete old run folders by hand when it grows.

### "SerpAPI rate limited or timed out"
**Cause:** SerpAPI has temporarily blocked requests (too many calls from same IP), or a call
did not answer within `serpapi.timeout_seconds` (60 by default). A call that times out is
retried up to `serpapi.retry_max_attempts` times (3 by default, one more than the
`http_retry.attempts` used for every other host because a SERP fetch is a paid call against
a single vendor that the run cannot continue without); if every attempt fails the query is
listed under "Fetched N of M queries" and the run carries on with the rest. If either of the
two SerpAPI retry settings holds something that is not a positive number, the run warns,
names the setting and uses the documented default — it no longer stops with a traceback
before any keyword is fetched.

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
   - Save All (validates first; writes only the files you changed — see `docs/config_reference.md`, "Saving")

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

6. **Change the words the report uses**
   - Open Configuration Manager (GUI launcher → "Edit Configuration")
   - Ten tabs edit an editorial file's own text rather than a form: Feasibility
     Wording, Search Console Wording, AI Visibility Wording, SERP Vocabulary,
     Glossary, Recommended Plays, Engine Profiles, Report Directives, Brief
     Validation, Schema Recommendations
   - WHAT THEY DO: these files hold the judgements, not the measurements — the
     status labels and the sentences explaining why a keyword has no verdict,
     the decision table that picks one of five recommended plays, the
     definition of every term of art the report prints, the per-engine advice,
     the "When you write:" line under each report section
   - WHY IT MATTERS: each of these is the **only** home for its words. Four
     Python copies of one status map are how a single unmeasured state came to
     be called "No DA Data" in one output and "Not Measured" in another. Change
     the file and every output that uses those words follows
   - The tab shows the file as it is, comments included. The syntax is checked
     before anything is written: a mistake is reported with its line and
     nothing is saved, so a bad edit cannot break the next run. Comments you
     add survive exactly, which is the point of writing down why a threshold is
     what it is
   - Two of the files are checked further, because valid YAML is not a valid
     rule table: Recommended Plays and Brief Validation are handed to the code
     that reads them, so a play table missing its `rules` list, or a validation
     file that declares no numeric checks, is refused with what that code said.
     Without it, deleting a section parsed cleanly and either killed the next
     run or turned every numeric check off with nothing saying so
   - If a file is already broken when the manager opens, its source tab loads
     the text anyway and says so in red. Fix the syntax there and save — the
     text is re-parsed first, so a repair that is still wrong is refused and
     the file on disk is left as it was
   - NOT HERE: thresholds and weights are numbers, not wording. They are in
     Config Settings (`config.yml`)

7. **Pivot to neighbourhood keywords (service keywords only)**
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
| `brief_llm.py` | Calls the configured LLM provider for the content brief |
| `report_llm.py` | Reads `report_llm` from `config.yml` and resolves the provider from the shared key file |
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
