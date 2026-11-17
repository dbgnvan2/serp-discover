# How the SERP Intelligence Tool Works — reading guide, snapshot of 2026-05-01

> **This is a dated snapshot, not the contract.** The methodology contract is
> [`docs/methodology.md`](docs/methodology.md), which CLAUDE.md names and which
> is updated in the same change as the code it describes. This file was written
> from a reading of the codebase as it stood on **2026-05-01** and has not been
> maintained since; where the two disagree, `docs/methodology.md` is right.
> Known stale passages: the trigger vocabularies it calls "effectively
> hardcoded" moved to `intent_classifier_triggers.yml` (spec I.2) and
> `serp_vocab.yml`; the two generators it says "weren't in the upload" are in
> the repo; the DA and threshold figures it quotes are whatever `config.yml`
> now holds. Kept because its plain-language Part 1 is still the clearest
> introduction to why each piece exists (review finding D-M-22).

A reading guide to what the tool does, why each piece exists, and where to look when you want to change something. Written from a fresh reading of the codebase as it stands at 2026-05-01.

This doc has two parts. **Part 1** explains the tool in plain language for people who use the output but don't write code. **Part 2** is the technical companion for people who do — or for you, when you want to evaluate or modify what the agents built.

---

# PART 1 — What the tool does and why

## The problem this tool solves

Living Systems Counselling has a marketing problem most counselling practices don't recognise. The therapy space online is dominated by two frameworks: the Gottman Method and Emotionally Focused Therapy. Search Google for "couples therapy" and you'll see those two approaches everywhere, framed in medical-model language — diagnosis, treatment, evidence-based intervention, symptom relief.

Living Systems works in a different framework: Bowen Family Systems Theory. The vocabulary is different (differentiation, reactivity, multigenerational patterns) and so is the underlying premise (the goal isn't to fix what's broken, it's to map and modify the emotional system). This is a real intellectual difference, not a marketing slogan. But it means the standard SEO advice — "rank for the keywords your competitors rank for" — leads Living Systems into a content arms race with much larger sites speaking a different language.

The tool exists to help Living Systems compete differently: identify keywords where the dominant content is medical-model framed, and produce Bowen-framed content that occupies a distinct intellectual position in the same SERP.

## What the tool actually produces

Each time you run it on a keyword set (e.g. "couples therapy" with about six keywords), you get five files:

1. **`market_analysis_<topic>_<timestamp>.json`** — the full structured data from the run. Source of truth for everything else. You don't read this directly; everything else is generated from it.

2. **`market_analysis_<topic>_<timestamp>.md`** — a human-readable report with seven sections: market overview, anxiety-loop questions people are asking, dominant competitor language, strategic recommendations, SERP composition data, per-keyword intent verdicts, and market volatility (rank changes since last run).

3. **`market_analysis_<topic>_<timestamp>.xlsx`** — the same data in Excel for filtering and ad-hoc analysis.

4. **`competitor_handoff_<topic>_<timestamp>.json`** — a clean list of the top competitor URLs per keyword, formatted for the second tool in this suite (`serp-compete`) which audits competitors in depth.

5. **`content_opportunities_<topic>_<timestamp>.md`** and **`advisory_briefing_<topic>_<timestamp>.md`** — written by Anthropic's Claude using all the structured data above. The first is detailed content recommendations; the second is an executive-level "what to do" briefing.

The first run takes roughly five minutes and costs about $0.50 in API fees. Subsequent runs against the same keyword set cost less because Domain Authority lookups are cached for 30 days.

## What the tool does, step by step

The tool runs in a fixed pipeline. Each step has a specific purpose; understanding why each exists helps you know when something is off.

### Step 1 — Fetch the SERP for each keyword

For each keyword in your input CSV, the tool calls SerpAPI to get Google's search results for the location "Vancouver, British Columbia, Canada." It collects multiple pages depending on the API mode (1 page in Low API mode, 3 in Balanced, configurable in Deep Research).

What it captures: the top organic results, the local map pack, People Also Ask questions, related searches, autocomplete suggestions, AI Overview text and citations, and any other SERP modules Google showed.

**Why this matters.** Google's results are different in different locations. Searching from Vancouver returns different results than searching from Toronto. The location is hardcoded to Vancouver because that's where Living Systems' clients are.

### Step 2 — Visit the top competitor pages

For the top URLs per keyword (default 5 pages of analysis per keyword), the tool fetches the actual HTML and parses it. It extracts the page title, meta description, first chunk of body text, headings, and any structured data Google would see.

**Why this matters.** Knowing that a URL ranked #1 isn't enough. The tool needs to know *what kind of page* is ranking — a service page, a blog post, a directory listing, a PDF — because that tells you what content format Google rewards for that keyword.

### Step 3 — Classify what each page IS

Two classifiers run on each fetched page:

**Content Type classifier.** Looks at the URL, headers, page text, and title and assigns one of: `service`, `guide`, `directory`, `news`, `pdf`, or `other`. Rules are a mix of URL patterns ("does the URL contain `/services/`?"), HTML signals ("does it have an `article:published_time` meta tag?"), and content heuristics ("does the title start with 'Top 10' or 'Best...'?").

**Entity Type classifier.** Looks at the *domain* (not the page) and assigns one of: `counselling`, `directory`, `legal`, `nonprofit`, `government`, `media`, `professional_association`, `education`, or `N/A`. So `psychologytoday.com` is `directory`, `wellspringcounselling.ca` is `counselling`, `cbc.ca` is `media`.

**Why this matters.** A service page on a counselling provider's domain is a fundamentally different ranking signal than a service page on a directory site. The same content type means different things depending on who's hosting it. Both classifications are needed to read the SERP properly.

**An honest caveat.** Both classifiers are rules-based, not ML. They're transparent and auditable but they're imperfect. About 30-40% of URLs in any given SERP get classified as `other` or `N/A` — the tool can't always tell what a page is. This is reflected downstream in confidence scores rather than being papered over.

### Step 4 — Find the questions people are asking

People Also Ask (PAA) questions appear in many SERPs. The tool collects them and runs each one through a third classifier:

- **External Locus** — the question is framed in medical-model language ("How is depression diagnosed?", "What's the treatment for anxiety disorder?")
- **Systemic** — the question is framed in family-systems language ("How does family of origin affect adult relationships?")
- **General** — neither framing dominates ("How much does therapy cost?")

**Why this matters.** External-Locus questions are the prime targets for Bowen reframing. They reveal that the searcher is operating inside the medical-model framing the tool wants to challenge. The content brief uses these questions as anchor points: "here's a question someone is actually asking, framed in the worldview Living Systems differentiates from — here's the systemic-framed answer."

### Step 5 — Compute a SERP intent verdict

For each keyword, the tool now has the top 10 organic URLs, each tagged with a content type and an entity type, plus a flag for whether the SERP has a local map pack. From this, it computes one verdict per keyword: what is the *primary search intent* of this SERP?

The five intent buckets:
- **informational** — searcher is learning ("how does couples therapy work")
- **transactional** — searcher is ready to engage a provider ("book a couples therapist")
- **local** — searcher wants someone nearby (transactional + local pack present)
- **commercial_investigation** — searcher is comparing options ("best couples therapy approaches")
- **navigational** — searcher is going to a specific brand they already know

A keyword is **mixed-intent** when no single bucket clears 60% of classified URLs (or 40% with a clear lead). Mixed intent is a strategic situation, not a problem — it means there's room to compete by occupying a less-contested intent slot.

The mapping from page properties to intent buckets lives in `intent_mapping.yml`. This file is editorial: it encodes judgment calls like "a service page on a directory domain isn't really transactional, the user is still comparing." Editing this file changes the verdicts without touching code.

**Why this matters.** Knowing a keyword is mixed-intent vs. dominantly transactional shapes what content to write. For a dominantly transactional keyword, you need a service page and good local SEO. For a mixed-intent keyword, you can write the informational guide that the transactional sites won't write, and rank without competing head-on.

### Step 6 — Match competitor language against Bowen patterns

The tool builds an n-gram corpus from all the SERP titles, snippets, and page text it collected. Then it checks that corpus against four pre-defined "traps" in `strategic_patterns.yml`:

- **The Medical Model Trap** — vocabulary like "diagnosis," "clinical," "treatment," "patient"
- **The Fusion Trap** — vocabulary like "connection," "intimacy," "communication," "reconnect"
- **The Resource Trap** — vocabulary like "free," "low cost," "sliding scale," "covered"
- **The Blame/Reactivity Trap** — vocabulary like "narcissist," "toxic," "abusive," "mean"

Each trap has trigger words. If any trigger word appears in the corpus (as a whole word, not a substring), the trap "fires" and gets included in the strategic recommendations.

Each trap also has a Bowen reframe: a pre-written statement of what the systemic alternative is, plus a content angle for the recommended article.

**Why this matters.** This is the editorial core of the tool. It encodes Living Systems' point of view: here are four common ways the SERP frames couples problems, and here's what the Bowen-framed alternative would say in each case. The reframes aren't generated by the LLM — they're written by you (or whoever wrote `strategic_patterns.yml`), so they're consistent with how Living Systems actually thinks about the work.

If the file is wrong, the recommendations will be wrong. The patterns are the soul of the tool.

### Step 7 — Score how feasible each keyword actually is

The tool calls DataForSEO (or Moz as fallback) to look up the Domain Authority of each ranking competitor. It compares against Living Systems' DA (currently 35) and computes a "gap":

- **Gap ≤ 5** — high feasibility, you can rank with content quality alone
- **Gap 6-15** — moderate, you need local backlink building
- **Gap > 15** — low, you'd need significant authority work; a "neighbourhood pivot" suggestion is offered (e.g., "Couples Counselling" → "Couples Counselling Lonsdale")

**Why this matters.** Without this, you'd waste resources writing content for keywords you can't actually win. DA gap is a rough but useful proxy for how realistic each keyword is as a near-term target.

### Step 8 — Hand structured data to Claude for the brief

Everything above is deterministic Python — given the same SERPs as input, you get the same verdicts as output. Step 8 is where the LLM enters.

The tool sends Claude a structured payload containing all the pre-computed verdicts (intent, mixed-intent strategy, competitor language patterns, PAA questions tagged by intent, feasibility scores) plus the raw SERP data. Claude writes the content brief and the executive advisory.

The LLM is constrained: a validator runs after generation and rejects the output (with a retry) if Claude contradicts any of the pre-computed verdicts. This is why the verdicts are pre-computed — the LLM is doing synthesis and writing, not arithmetic. Hard contradictions (claiming a SERP is informational when the data says it's transactional) cause a hard failure with no retry.

**Why this matters.** LLMs are good at writing but mediocre at counting. Asking Claude to "look at these 10 URLs and tell me the intent breakdown" produces inconsistent results. Computing the breakdown deterministically and giving Claude the answer means the brief reads well *and* the numbers are right.

### Step 9 — Write the competitor handoff file

After the main pipeline finishes, the tool writes a separate JSON file: `competitor_handoff_<topic>_<timestamp>.json`. This is a clean, schema-validated list of the top competitor URLs per keyword, designed to be consumed by the companion tool `serp-compete` (Tool 2) which audits competitor pages in depth.

Tool 2 isn't covered here — it's a separate tool with its own architecture — but the handoff file is the contract between them.

## How to read the output

Three things to focus on when looking at a `market_analysis_*.md` report:

**1. Section 5b — Per-Keyword SERP Intent.** This is the deterministic verdict for each keyword. Look at the `Primary intent` and `Confidence` first. High confidence + clear primary intent = the SERP has a definite shape and you should respect it. Mixed intent + medium confidence = there's room to compete from a less-contested angle.

**2. Section 4 — Strategic Recommendations.** Each Bowen pattern that fired in this run shows up here, with the trigger words found and the recommended content angle. If a pattern is missing (e.g. The Blame/Reactivity Trap doesn't appear in some runs), it means none of that pattern's trigger words appeared in the SERP corpus — which is honest behavior, not a bug.

**3. The Mixed-Intent Strategic Notes at the top of Section 4.** When the tool says `Strategy: backdoor` for a keyword, it means the dominant intent of the SERP is something Living Systems can't easily compete on (e.g. local service pages dominate), but a less-represented intent (e.g. informational) aligns with what Living Systems can produce. The "backdoor" is to write the informational guide that the local-service competitors won't write.

## What the tool does NOT do

These are out of scope, and knowing the boundaries matters:

- It does not crawl competitors' full sites — only the pages that ranked. (Tool 2 does deeper competitor audits.)
- It does not score backlink profiles — only Domain Authority as a single proxy.
- It does not write or publish content — it tells you what to write.
- It does not predict what will rank if you publish — it identifies opportunities; outcomes depend on execution.
- It does not track ongoing rankings — Step 1 captures a snapshot at one point in time. Run it again to see changes.
- It does not handle non-English SERPs.

## Where the tool can be wrong

In rough order of how often each one matters:

1. **The classifier marks a lot of URLs as `other` or `N/A`.** When this happens for a particular keyword, the confidence drops. The verdict is honest about the uncertainty, but you may want to check those uncategorised URLs manually.

2. **The Bowen pattern triggers can over- or under-fire.** Trigger words are whole-word matched, so "mean" doesn't fire on "meaning" — but a single common word like "free" can fire on contexts that aren't really about cost. The trigger lists in `strategic_patterns.yml` are editorial; they need occasional review.

3. **The intent mapping reflects judgment calls.** A reasonable person might disagree with "service-page-on-directory = commercial_investigation" (some would call it transactional). The mapping is in `intent_mapping.yml` with the rationale documented inline.

4. **DA scores are a rough signal.** A keyword can be more or less competitive than DA gap suggests. Very narrow keywords may show low competition by DA but be genuinely hard to win because the searchers have already converged on a small number of incumbents.

5. **The LLM writes the actual brief text.** The structured data going in is deterministic; the prose Claude generates is not. Two runs against the same JSON can produce briefs with slightly different framing or emphasis. The validator catches factual contradictions but not stylistic drift.

6. **Mixed-intent strategy is a heuristic.** The "backdoor" recommendation assumes Living Systems can produce the alternative-intent content. Whether that's actually true depends on resourcing.

---

# PART 2 — Technical reading guide

This part assumes you can read Python and YAML. It's organised around the source files, in the order they execute.

## File-by-file orientation

### `serp_audit.py` — the orchestrator

This is the main entry point for a pipeline run. It:

1. Loads `config.yml` and the keyword CSV
2. Calls SerpAPI for each keyword (with retries and rate-limit handling)
3. Optionally fetches and parses the top N pages per keyword
4. Runs the two classifiers on each fetched page
5. Builds the n-gram corpus and matches against `strategic_patterns.yml`
6. Computes per-keyword `serp_intent` via `intent_verdict.compute_serp_intent`
7. Writes the JSON, XLSX, and MD outputs
8. Writes the competitor handoff file (if there are organic results)
9. Persists run history to `serp_data.db` (SQLite)

Reading order suggestion: start at `if __name__ == "__main__":` and work backwards through the orchestration functions.

### `classifiers.py` — content type and entity type rules

Two classes:

- **`ContentClassifier.classify(url, soup, headers, entity_type)`** — returns `(content_type, confidence, evidence_list)`. Order of checks: PDF → directory URL pattern → empty soup fallback → news (article:published_time meta) → service signals (≥2 service keywords in first 5000 chars) → guide titles → high word count → `other`.
- **`EntityClassifier.classify(domain, soup)`** — returns `(entity_type, confidence, evidence_list)`. Order: manual override (from `domain_overrides.yml`) → TLD signals (`.gov`, `.edu`) → known directory/media/legal/counselling domain lists → text content keywords → `N/A`.

Both classifiers load their pattern lists from `classification_rules.json`. That JSON file is where the actual signal lists live (legal terms, counselling terms, nonprofit keywords, etc.). It's not in your upload but it's the authoritative source for what each classifier looks for.

The fallback `classify_url_from_patterns()` function loads `url_pattern_rules.yml` and applies it when HTML classification fails. This was added during the v2 work to recover URLs the HTML classifier couldn't read.

**A real limitation:** the `service` classifier is genuinely fragile. It requires "two or more service signals in the first 5000 chars" and "service signals" are common words like "book," "schedule," "appointment." Many legitimate service pages don't trip this rule. This is part of why so many URLs get classified as `other`.

### `intent_classifier.py` — PAA and keyword tagging (External Locus / Systemic / General)

Despite the name, this is *not* the SERP intent classifier. It tags individual question or keyword strings as Bowen-aligned, medical-aligned, or neutral.

The trigger vocabularies (`DEFAULT_MEDICAL_TRIGGERS`, `DEFAULT_SYSTEMIC_TRIGGERS`) are defined as `frozenset` constants at the top of the file. They can be overridden at construction time but currently aren't — they're effectively hardcoded.

**This is the next file to externalise.** The Bowen patterns moved from hardcoded to `strategic_patterns.yml` recently; the External Locus / Systemic vocabularies should make the same move. The file even has a comment saying "trigger vocabulary can be extended via config without code changes" but no config path is wired up.

Matching logic: word-boundary regex for single-word triggers, substring for multi-word phrases. Multi-word matches are checked first (longest first) so "family system" beats just "system." Matched spans are consumed so a phrase doesn't double-count its constituent words.

Confidence is `matched_token_count / total_token_count`, capped at 1.0. Short questions with one strong trigger score higher than long questions with the same number of matches.

### `intent_verdict.py` — SERP intent verdict (per keyword)

This is the Tool 1 v2 work. Reading the docstring at the top is worth it — it explicitly states the contract.

`compute_serp_intent()` takes the top-10 organic results (caller must cap), the local pack flag, the client domain, known competitor brands, and the loaded mapping. Returns the `serp_intent` block.

The decision flow:
1. For each URL, derive a `domain_role` (client / known_competitor / other)
2. For each URL, walk `intent_mapping.yml` rules top-to-bottom; first match wins
3. Tally counts per intent bucket
4. Apply primary/mixed thresholds (60% primary, or 40% with ≤20% runner-up)
5. Compute confidence from the count of classified URLs (high ≥8, medium ≥5, low otherwise)

The code is well-defended: empty inputs are handled, malformed YAML raises `ValueError` with a clear message, the mapping schema is validated on load.

**One thing to note:** `local_pack_member_count` is a parameter but the test fixtures may not always populate it. If you change calling code, double-check this is being passed correctly — it appears in the output `evidence` block but isn't used in the verdict computation itself.

### `intent_mapping.yml` — the intent rule table

First-match-wins ordered list. Top of file = highest priority. The header documents the schema, the priority order, and five edge cases by name.

This file is editorial. Read the rationale comments for each rule before modifying. The order matters: domain-role overrides come first (so a client URL is always navigational regardless of content type), then unclassified content gets dropped early (`other` and `unknown` → `uncategorised`), then service rules with locality, then content-type-specific rules, then a catch-all safety net.

The `uncategorised` intent is special: it's tracked in evidence but excluded from `intent_distribution`. This is what causes confidence to drop when the classifier can't read enough URLs.

### `strategic_patterns.yml` — the four Bowen traps

Each entry has: `Pattern_Name`, `Triggers`, `Status_Quo_Message`, `Bowen_Bridge_Reframe`, `Content_Angle`. The header explains good vs. bad triggers and enforces a 4-character minimum.

Field names match what `serp_audit.py` writes into the JSON output, so renaming a field requires changing the consumer too. The five fields are required for every pattern; there's no schema validator (yet), but missing fields would surface as `KeyError` during pattern matching.

**The "mean" trigger is correct as written.** With word-boundary matching (which the header confirms is enforced in code), "mean" matches "being mean" but not "meaning." If you saw the Blame/Reactivity Trap drop out of a recent report, it's because none of its triggers appeared in that run's corpus — not because the matching is broken.

### Output: `market_analysis_*.json`

Top-level keys (from the May 1 fixture):
- `overview` — per-keyword summary stats
- `organic_results` — every organic URL across all keywords (~170 rows)
- `paa_questions`, `related_searches`, `derived_expansions`, `autocomplete_suggestions` — SERP-collected metadata
- `serp_language_patterns` — n-gram counts from competitor language
- `strategic_recommendations` — the matched Bowen patterns with triggers found
- `local_pack_and_maps` — local pack entries
- `ai_overview_citations` — AI Overview source URLs
- `serp_modules` — which Google modules appeared per keyword
- `keyword_profiles` — the v2 deterministic verdicts per keyword (this is the new structure)
- `keyword_feasibility` — DA gap scores

`keyword_profiles[kw]` contains:
- `serp_intent` (from `intent_verdict.py`)
- `title_patterns`
- `mixed_intent_strategy`
- Other per-keyword pre-computed fields

The downstream LLM consumes `keyword_profiles` directly; it doesn't re-derive intent from organic_results. This is enforced by the validator.

### Configuration files

- **`config.yml`** — operational settings: SerpAPI location, page counts, file paths, feasibility thresholds, LLM models, client context for prompts. Most agent-modifiable values live here.
- **`domain_overrides.yml`** — manual entity-type overrides. Reviewed via the GUI's domain override workflow.
- **`intent_mapping.yml`** — SERP intent rules (described above).
- **`strategic_patterns.yml`** — Bowen patterns (described above).
- **`url_pattern_rules.yml`** — URL pattern fallbacks for the content classifier.
- **`classification_rules.json`** — the pattern lists the two classifiers use.
- **`clinical_dictionary.json`** — Bowen-vs-medical vocabulary tiers (used by Tool 2; may also be consulted here).

## What's well-done

- The intent verdict separation between Python (deterministic) and LLM (synthesis) is the right design and is enforced by validators.
- `intent_mapping.yml` and `strategic_patterns.yml` are well-documented YAML files with clear schemas and rationales.
- The `intent_verdict.py` module has explicit handling of edge cases (empty input, low classification count, malformed YAML).
- The competitor handoff has its own JSON schema and is validated before writing.
- The PAA classifier consumes spans (so phrase matches don't double-count), which is the correct design.

## What's worth attention

In rough priority order, things you may want to look at:

1. **`intent_classifier.py` should externalize its trigger lists.** The Bowen patterns moved to YAML; the External-Locus/Systemic vocabularies should follow. Same shape as `strategic_patterns.yml`. Until this is done, modifying which words count as "medical model" requires a code change.

2. **The content classifier's high false-`other` rate.** The `service` rule (≥2 service signals in first 5000 chars) is too strict for many real service pages. The fallback `url_pattern_rules.yml` helps but doesn't fully close the gap. Worth diagnosing on a specific run to see which URLs are slipping through and why.

3. **`generate_content_brief.py` and `generate_insight_report.py` weren't in the upload.** I can't speak to their structure. If you want them reviewed, send them next.

4. **Fixture-vs-production divergence.** The cleanup spec status report claimed "all four pattern blocks" for tests that pass against synthetic fixtures, but production output has only patterns whose triggers actually fired. The tests are honest within their scope but the test names are misleading. Worth either renaming the tests or adding an integration test that runs against real fixtures.

5. **`config.yml` keys that look unused.** A scan of how `config.yml` keys are consumed would surface dead settings. Settings that exist but aren't read are a maintenance hazard.

## Where to look when something seems off

| Symptom | Where to look first |
|---|---|
| Wrong intent verdict on a keyword | `intent_mapping.yml` rules, in priority order |
| Wrong content type for a URL | `classification_rules.json` patterns; then `ContentClassifier.classify` |
| Wrong entity type for a domain | `domain_overrides.yml`; then `EntityClassifier.classify` |
| Bowen pattern firing falsely | `strategic_patterns.yml` triggers list for that pattern |
| Bowen pattern not firing when it should | Same file — triggers may not match the actual SERP language |
| Low confidence on a keyword | Look at `evidence.uncategorised_organic_url_count`; the classifier couldn't read enough URLs |
| LLM brief contradicts the data | Validator should catch this; check `*.validation.md` |
| Missing competitor handoff file | Probably no organic results were captured; check raw SerpAPI output |
| Domain Authority all blank | `DATAFORSEO_LOGIN`/`MOZ_TOKEN` not set, or both providers down |

## A note on what I couldn't verify

I read the code as it was uploaded. I did not run the tool. So:

- Tests claimed to pass in the spec coverage matrix — I haven't verified them.
- File paths claimed in the README — I haven't verified all the paths exist.
- The interaction between `serp_audit.py` and the LLM brief generator — I have only the audit side; the brief side was not in the upload.

For anything in this doc that turns out to be wrong, the source code is authoritative, not this doc.
