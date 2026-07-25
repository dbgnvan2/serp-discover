# SEO/GEO Audit-Coverage Review & Enhancement Proposals — Three-Tool Suite

**Date:** 2026-07-21
**Anchor source:** Neil Patel, *How to Do an SEO Website Audit* (17-step guide) — https://neilpatel.com/blog/seo-website-audit/
**Tools reviewed:** serp-discover (Tool 1) · serp-compete (Tool 2) · TalkingToad
**Scope:** blog-anchored enhancements plus closely-adjacent ideas I judge worthwhile.
**Priority lens:** Living Systems Counselling's real constraints — one small nonprofit, cost-sensitive, effort/impact and paid-API cost flagged per item.

---

## 0. Method, confidence, and the honest headline

I read the blog in full and, in the three repos: `serp-discover` (`README.md`, `methodology.md`, `CLAUDE.md`, `seo_geo_review_20260704.md`, `seo_geo_deferred_spec_v1.md`), `serp-compete` (`README.md`, `CLAUDE.md`), and `TalkingToad` (`README.md`, `CLAUDE.md`, the full 152-code `docs/issue-codes.md`, `PLAN-V4.0.md`). Coverage claims below are checked against those catalogues and docs, **not** a line-by-line code read; where a claim depends on implementation I haven't seen, it is marked *(docs-level, verify in code)*.

**Honest headline.** This blog is a generalist audit checklist. Your three-tool suite already implements roughly 13 of its 17 steps, several of them materially deeper than the post describes — most notably AI-search visibility (step 17), structured data (14), indexing (5), and the crawl itself (1). You have also *already* run a formal review of serp-discover against a different Neil Patel piece (`seo_geo_review_20260704.md`), so the GEO/AI-visibility ideas here are largely re-confirmation, not new signal. The value in this document is therefore concentrated in a small number of genuine gaps the blog surfaces — chiefly **performance / Core Web Vitals** and **keyword cannibalization**, both of which land on TalkingToad — plus one **suite-level** idea (turning three tools into one orchestrated audit) that the blog's "an audit is one process" framing makes obvious.

---

## 1. The suite at a glance

The three tools split along the same seams a full audit naturally has:

- **serp-discover (Tool 1) — off-site market intelligence.** Google SERP scraping, competitor-URL classification (content type + entity type), deterministic per-keyword intent verdicts, Domain-Authority feasibility, Bowen-framed content briefs, AI-Overview citation capture, and the AI-visibility probing subsystem (`probe_ai_visibility.py`, `aivi.py`, `brand_mentions.py`, `citation_table.py`, `answer_sentiment.py`) that queries Claude + Gemini for client mention/citation trends.
- **serp-compete (Tool 2) — competitor page audit.** Consumes Tool 1's `competitor_handoff_*.json`; scores competitor pages for medical-vs-systems language, runs EEAT heuristics, detects internal-link clusters, and generates Bowen "reframe" outlines (GPT-4o). Outputs "traffic magnets" and "systemic vacuums."
- **TalkingToad — own-site technical + GEO crawler.** Async crawl of up to 500 pages, **152 issue codes across 13 categories** (63 of them AI-readiness), WordPress one-click fixes, image intelligence, FAQ/Entity schema generators, optional Google Search Console integration, PDF/Excel reporting.

The seam: Tool 1 and Tool 2 look **outward** (the market and competitors); TalkingToad looks **inward** (your own site's technical and AI-readiness health). The blog's 17 steps cut across all three.

---

## 2. Coverage map — the blog's 17 steps against the suite

Verdicts: **✅ Covered** (often deeper than the post) · **🟡 Partial** · **🔴 Gap**.

| # | Blog step | Owning tool | Verdict | Notes |
|---|---|---|---|---|
| 1 | Website crawl | TalkingToad | ✅ | Async BFS crawler, 152 codes |
| 2 | Organic traffic analysis | TalkingToad (GSC) + serp-discover G.4 | ✅ | TT blends GSC into priority ranking; SD's GSC is deferred-spec |
| 3 | Meta titles & descriptions | TalkingToad (METADATA, 20 codes) | ✅ | Length/dupe/missing + WordPress auto-fix |
| 4 | Keyword cannibalization | — | 🔴 | Only within-site title/meta dupes today; no query→multi-page detection |
| 5 | Indexing issues | TalkingToad | ✅ | NOINDEX, REDIRECT_LOOP (critical), CANONICAL_*, THIN_CONTENT, robots |
| 6 | Duplicate content | TalkingToad | 🟡 | On-site dupes covered; no cross-web (Copyscape-style) detection |
| 7 | Page speed | TalkingToad | 🟡 | Proxies only: PAGE_SIZE_LARGE, PAGE_TIMEOUT, image weight — no timing |
| 8 | Core Web Vitals | — | 🔴 | No LCP/INP/CLS; no field or lab data |
| 9 | Mobile friendliness | TalkingToad | 🟡 | MISSING_VIEWPORT_META + srcset; no rendered-width test |
| 10 | Broken links | TalkingToad (BROKEN_LINK, 8 codes) | ✅ | Internal/external, 4xx/5xx, placeholder links |
| 11 | Competitive analysis | serp-discover + serp-compete | ✅ | Intent + entity + DA + semantic + clusters — well past Ubersuggest |
| 12 | Sitemap analysis | TalkingToad | ✅ | SITEMAP_MISSING + NOT_IN_SITEMAP |
| 13 | Content gap | serp-discover + serp-compete | ✅ | Content opportunities + systemic vacuums |
| 14 | Structured data | TalkingToad + serp-discover G.2 | ✅ | ~10 schema codes incl. SCHEMA_VISIBLE_MISMATCH + generators |
| 15 | E-E-A-T | TalkingToad + serp-compete + serp-discover G.3 | ✅ | AUTHOR_BYLINE_MISSING, citations/quotes/stats codes, EEAT heuristics |
| 16 | Backlink profile | — | 🔴 | Deliberate: DA proxy only across the suite; no link graph |
| 17 | AI search visibility | serp-discover (probes) + TalkingToad (63 AI codes) | ✅ | Ahead of the post: engine probing + robots AI-bot + extractability + llms.txt |

**Reading the map:** four rows are not solid green — steps 4, 8 (real gaps), and 6, 7, 9 (partials). Everything else the suite already does, in most cases beyond what the post prescribes. That is the entire actionable surface of this blog.

---

## 3. Enhancement proposals

Each item carries: **provenance** (Blog = directly traceable to a step; Adjacent = closely related idea I'm adding), **effort** (XS/S/M/L), **impact** (High/Med/Low for *this client*), **cost** (🆓 no new API · 💲 paid/new external dependency · 🔑 new credential), and a **verdict** (Do / Defer / Decline).

### 3A. TalkingToad — where most of the blog lands

**TT-1 · Core Web Vitals & measured performance** — *Blog (7, 8) · Effort M–L · Impact High · 💲🔑 (PageSpeed Insights API) · Do (phased)*
The single clearest gap in the whole suite. TalkingToad has no performance category — only weight/size proxies. Add a performance pass that, for a capped set of key pages (home, top service pages, top GSC-traffic pages), calls the **PageSpeed Insights API** (free, key-gated, rate-limited) to capture lab CWV (LCP, CLS, TBT as an INP proxy) and, where available, CrUX field data. Report against the post's thresholds (LCP < 2.5s, INP < 200ms, CLS < 0.1). Phase it: start with lab data on ~5–10 pages per run, not a full-site sweep. **Architectural note:** this moves TalkingToad from static-HTML analysis toward external measurement — a real dependency and a deliberate decision, not a checker addition. Gate it behind config (off by default) and cap calls, consistent with your existing paid-call discipline. New codes fit naturally: `CWV_LCP_SLOW`, `CWV_CLS_HIGH`, `CWV_INP_SLOW`, `PERF_TTFB_SLOW`.

**TT-2 · Keyword cannibalization via GSC** — *Blog (4) · Effort S–M · Impact Med · 🆓 (reuses existing GSC link) · Do*
You already ingest GSC. Cannibalization is a straightforward query on data you have: flag any query where **more than one of your own URLs** receives impressions/clicks (or ranks) for the same term — the classic self-competition signal. Surface it as a site-scoped finding (`KEYWORD_CANNIBALIZATION`) listing the competing URLs and which one GSC favours, with the standard recommendation (consolidate into a pillar page + 301). No new API, no new credential — this is analysis over data already flowing into the priority ranking. *(docs-level; confirm the GSC layer exposes per-query URL breakdowns.)*

**TT-3 · Promote page-speed proxies to a measured response-time capture** — *Blog (7) · Effort S · Impact Med · 🆓 · Do*
Independent of TT-1's full CWV work, the crawler already fetches every page — capturing **TTFB / total response time** during that fetch is nearly free and gives a real (if coarse) speed signal today. Add `PERF_SLOW_RESPONSE` with a documented threshold. This is the cheap 80/20 that partially closes step 7 without the PSI dependency, and it complements TT-1 rather than duplicating it (crawl-time server latency vs. rendered CWV).

**TT-4 · Rendered mobile-usability signal** — *Blog (9) · Effort S · Impact Low–Med · 🆓 · Defer*
TalkingToad already runs a render pass for JS-content checks (`JS_RENDERED_CONTENT_DIFFERS`, `RAW_HTML_JS_DEPENDENT`). Piggyback a viewport-width overflow / tap-target check on that existing render to go beyond the static `MISSING_VIEWPORT_META`. Genuine but low-priority — Google retired its own mobile test and viewport-meta already catches the common nonprofit-WordPress failure mode. Defer behind TT-1/TT-2.

**TT-5 · Cross-web duplicate/plagiarism detection** — *Blog (6) · Decline*
The post suggests Copyscape. For a single small nonprofit publishing its own content, external plagiarism scanning is low value and adds a paid dependency. On-site duplication (the real risk for a WordPress site) is already covered. Record as a deliberate non-goal.

*Already covered in TalkingToad — do **not** re-propose:* robots AI-crawler access (`AI_BOT_*`), schema breadth (`SCHEMA_*`, `JSON_LD_*`, `FAQ_SCHEMA_MISSING`), author/EEAT (`AUTHOR_BYLINE_MISSING`, `CITATIONS_*`, `QUOTATIONS_MISSING`, `STATISTICS_COUNT_LOW`), freshness (`CONTENT_STALE`, `DATE_*`), extractability/answer-first (`GEO_SUMMARY_BURIED`, `FIRST_VIEWPORT_NO_ANSWER`, `CHUNKS_NOT_SELF_CONTAINED`), llms.txt (`LLMS_TXT_*`), broken links, indexing, sitemap, security. The blog's steps 1/3/5/10/12/14/15/17 are essentially closed here.

### 3B. serp-discover — little new; mostly already on your own roadmap

**SD-1 · No new blog-derived work.** Steps this tool owns (11, 13, 17) are covered, and the blog's EEAT (15) and traffic-baseline (2) ideas already exist as **G.3** and **G.4** in your own `seo_geo_deferred_spec_v1.md`. The right action is to *ship the deferred spec*, not add scope. Flagging this explicitly so the review doesn't invent redundant work.

**SD-2 · Ground the citation-surface analysis in real client-citation data** — *Adjacent · Effort S–M · Impact Med · 🆓 · Do (cross-tool, see X-2)*
serp-discover's citation work (T.3/T.4 in your review) infers off-site citation surfaces from Google AI-Overview capture. TalkingToad separately tracks `AI_CITED_PAGE` (pages AI engines cited in the last 30 days). Feeding TalkingToad's *observed* client citations into serp-discover would replace some inference with ground truth. Detailed under X-2.

### 3C. serp-compete — extend competitor audit to the technical/GEO axis

**SC-1 · Competitor GEO/extractability comparison** — *Adjacent (extends blog 11/17) · Effort M · Impact Med–High · 🆓 · Do*
serp-compete already scores competitor pages for *language* (medical vs. systems) and EEAT. The blog's framing — AI cites what is *extractable* — implies a second axis: **why** a competitor page gets cited, not just how it's worded. Apply a subset of TalkingToad's AI-readiness logic to the competitor pages serp-compete already fetches: schema types present, author bylines/credentials, FAQ-in-HTML, answer-first structure, heading/question shape. Then "traffic magnets" can say *"this competitor page ranks and is AI-cited because it carries FAQPage schema + credentialed author + answer-first structure — which your equivalent page lacks."* This reuses checker logic that already exists in TalkingToad (shared library or ported subset) and turns reframe targets into concrete structural to-dos. Strongest net-new idea for Tool 2.

**SC-2 · Competitor Core Web Vitals / performance** — *Blog (7,8 applied to competitors) · Decline (for now)*
Technically possible via PSI, but paid-call volume scales with competitor × page count, ROI is poor for this client, and page speed rarely explains why a competitor out-ranks a small nonprofit in this niche. Revisit only if TT-1 ships and spare PSI quota exists.

### 3D. Suite-level (cross-tool) — the highest-leverage ideas

**X-1 · One orchestrated "audit," not three manual tools** — *Adjacent (blog's whole premise) · Effort M · Impact High · 🆓 · Do*
The blog treats an audit as a single 17-step process; your suite is three programs with a JSON handoff between two of them and no connection to the third. A thin orchestration layer — one command / one GUI action that runs serp-discover → serp-compete → TalkingToad against a shared client profile and merges the outputs into one dated audit report — would make the "full annual audit" a single action and eliminate the manual glue. You already have partial plumbing (`shared_config.json`, the `competitor_handoff` contract). Concretely: (a) promote `shared_config.json` to the one client-profile source all three read (serp-discover's C.9 already moves toward this); (b) add a top-level runner that sequences the three and stitches a combined executive summary. This is the structural change most aligned with how the blog — and a human auditor — actually thinks.

**X-2 · Close the AI-citation loop between TalkingToad and serp-discover** — *Adjacent · Effort S–M · Impact Med · 🆓 · Do*
Two halves that never meet: TalkingToad observes which *client* pages AI engines cited (`AI_CITED_PAGE`, `AI_HIGH_VALUE_UNCITED`); serp-discover probes AI engines about the *market* and captures AIO citations. Wire them: TalkingToad's observed client-citation list flows into serp-discover so its citation-surface/GEO analysis reflects reality, and serp-discover's "ranks-but-not-cited" alerts (your T.4) can target the exact client URLs TalkingToad flags as high-value-but-uncited. Small integration, compounding value — each tool's blind spot is the other's data. *(docs-level; verify `AI_CITED_PAGE`'s data source and export shape.)*

**X-3 · Encode the blog's audit cadence as scheduled runs** — *Blog (audit frequency) · Effort XS · Impact Low–Med · 🆓 · Do*
The post prescribes full audit annually, quarterly for fast-moving sites, mini-audits after migrations/algorithm updates/launches. Turn that into scheduled tasks: a quarterly full suite run (X-1) and a monthly lightweight TalkingToad re-crawl + AI-visibility probe, with change-over-time framing you already favour. Trivial to set up; keeps the tools earning their keep between manual pushes.

**X-4 · Make "no backlink analysis" an explicit, documented decision** — *Blog (16) · Effort XS · Impact Low · 🆓 · Do*
The blog's step 16 is a real capability gap, but a paid backlink provider (Ahrefs/Majestic/DataForSEO backlinks) is poor ROI for one nonprofit, and serp-discover already chose DA-as-proxy on purpose. Rather than leave it as a silent hole, record it as a deliberate scope boundary in each tool's docs (serp-discover's `methodology.md` already half-does this). Turns an apparent omission into a defensible choice — consistent with your "state absence, don't fake it" principle.

---

## 4. Priority summary (ranked for this client)

| Rank | ID | Enhancement | Tool | Effort | Impact | Cost | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | X-1 | One orchestrated audit + shared client profile | Suite | M | High | 🆓 | Do |
| 2 | TT-2 | Keyword cannibalization via GSC | TalkingToad | S–M | Med | 🆓 | Do |
| 3 | TT-3 | Measured crawl-time response speed | TalkingToad | S | Med | 🆓 | Do |
| 4 | SC-1 | Competitor GEO/extractability comparison | serp-compete | M | Med–High | 🆓 | Do |
| 5 | X-2 | Close the AI-citation loop | TT ↔ SD | S–M | Med | 🆓 | Do |
| 6 | TT-1 | Core Web Vitals via PageSpeed Insights | TalkingToad | M–L | High | 💲🔑 | Do (phased) |
| 7 | X-3 | Scheduled audit cadence | Suite | XS | Low–Med | 🆓 | Do |
| 8 | SD-1 | Ship deferred G.3/G.4 (already specced) | serp-discover | — | Med | varies | Do (existing plan) |
| 9 | X-4 | Document backlink exclusion as a decision | Suite | XS | Low | 🆓 | Do |
| 10 | TT-4 | Rendered mobile-usability check | TalkingToad | S | Low–Med | 🆓 | Defer |
| — | TT-5 | Cross-web plagiarism detection | TalkingToad | — | Low | 💲 | Decline |
| — | SC-2 | Competitor CWV | serp-compete | — | Low | 💲🔑 | Decline |

**Sequencing logic:** the 🆓 items that need no new dependency come first (X-1, TT-2, TT-3, SC-1, X-2, X-3, X-4). TT-1 is the highest-impact *new-capability* item but ranks sixth because it carries the only real external dependency and an architectural decision — do it deliberately, after the free wins land. The two 💲 declines are recorded so the boundary is explicit.

---

## 5. Which tool at which step — the usage map

Read as a lifecycle. The 17 blog steps regroup into five phases; each phase has a primary tool.

**Phase 1 — Market & keyword discovery (outward, before touching the site).** Tool: **serp-discover.** Covers blog steps 11 (competitive landscape), 13 (content gap), 2 (traffic/demand baseline), and the market side of 17 (AI-visibility probing, AIO citations). Output: which keywords and intents are winnable, and where the Bowen reframe angles are.

**Phase 2 — Competitor deep audit (outward, on the shortlist).** Tool: **serp-compete** (fed by Phase 1's handoff). Deepens step 11 and part of 15 — scores competitor pages for language, EEAT, link clusters; with **SC-1**, also their schema/extractability. Output: traffic magnets and systemic vacuums with concrete structural reasons.

**Phase 3 — Own-site technical + GEO audit (inward).** Tool: **TalkingToad.** Covers steps 1, 3, 5, 6, 10, 12, 14, 15 (on-site), 17 (on-site AI-readiness), and — once the proposals land — 4 (TT-2), 7 (TT-3/TT-1), 8 (TT-1), 9 (TT-4). Output: the prioritized, WordPress-fixable issue list for livingsystems.ca.

**Phase 4 — Fix & re-verify.** Tool: **TalkingToad** WordPress Fix Manager → re-crawl to confirm. The only tool of the three that *changes* the site rather than analysing it.

**Phase 5 — Monitor & recur (all three).** Cadence per **X-3**: quarterly full-suite run, monthly light TalkingToad + AI-visibility probe. Everything framed as change-over-time.

Backlinks (step 16) sit outside all phases by the **X-4** decision.

A visual version of this map (the phase flow with the 17 steps slotted into each tool) is delivered alongside this document as an interactive diagram.

---

## 6. Bottom line

This blog changes very little about *what* your tools should do — you had already converged on its GEO thesis independently, and in places you are ahead of it. Its practical yield is a short, mostly-free backlog: **make the three tools run as one audit (X-1), add the two things genuinely missing on your own site (cannibalization TT-2, real speed TT-3/TT-1), and let the competitor tool explain *why* rivals get cited (SC-1).** Core Web Vitals is the one item worth a real dependency; backlinks is the one worth an explicit "no." Everything else is confirmation that the architecture you built is the right one.
