# Serp-Compete — methodology-validity review

**Scope & method.** Reviewed `/Users/davemini2/ProjectsLocal/serp-compete` (Serp-compete/src, shared_config.json, clinical_dictionary.json, docs/FEATURE_GUIDE.md, docs/USER_MANUAL.md, README.md, compete-spec.md, Serp-compete/spec.md, TODO.md, LEARNINGS.md) and the only real outputs on disk (strategic_briefing_run_2 … run_11; run_11 dated 2026-03-31 is the richest; none of the saved briefings contain the v3/C-series sections — EEAT, cluster, GEO, overlap, barbell, SoV, brand, risk, YouTube — so those sections were judged from `reporting.py` text plus probes). The shipped `living_systems_intel.db` is empty (3 test rows), so every quantitative claim was checked with probe scripts under `docs/review_2026-11-04/probes/compete_method/` (`p01_semantic_scoring.py`, `p02_reporting_db.py`, `p03_eeat_cluster_geo.py`, `p04_overlap_positioning_brand.py`, outputs in `p0N_output.txt`) that call the real modules with synthetic pages / a throwaway SQLite built from the real `DatabaseManager` schema. No repo file was modified. Classification: WRONG (number does not mean what the report says), UNLABELLED HEURISTIC, UNDOCUMENTED PROVENANCE, DOC–CODE DRIFT. Items already in TODO.md are marked "already tracked". Line numbers are for the files as reviewed.

The single most important fact for reading everything below: **the pages and keywords the tool audits are not the ones in the handoff.** `main.py` groups handoff targets by domain and then throws the targets away; it asks DataForSEO for each domain's top-10 ranked keywords (Canada, API default ordering, no position filter) and audits whatever comes back. Every downstream metric — magnets, vacuums, reframes, overlap cells, barbell top-10 counts, velocity, volatility, cliff — is computed over that sample, not over the client's target keywords.

---

### C-M-01 · Audited keywords/pages are DataForSEO's per-domain top-10, not the handoff's targets
- Class: WRONG
- Impact: High
- Verdict: CONFIRMED (exact trace + run_11 output)
- Where: `Serp-compete/src/main.py:322-328, 386-393, 430-451`; `src/api_clients.py:17-45` (`ranked_keywords/live`, `"limit": 10`, no `order_by`, no position filter); `main.py:60-75` (`convert_handoff_to_targets` keeps `url`/`primary_keyword_for_url` but `group_targets` is never read in the loop); FEATURE_GUIDE §2.1; compete-spec.md:27; Serp-compete/spec.md "Reverse Lookup … Filter for pos <= 10".
- Evidence: `for domain, group_targets in domain_groups.items(): … pages = dfs_client.get_relevant_pages(domain)` — `group_targets` is unused. The handoff sampled (`competitor_handoff_couples_therapy_20260502_1634.json`) carries `source_keyword: "How much is couples therapy in Vancouver?"` per URL; run_11's magnets are instead `foundry`, `archdiocese of vancouver`, `foundry abbotsford`, `bc association`, `airport heights medical clinic` (a St. John's NL clinic page on cortico.health), `555 homer street`, `aac vancouver`, `langley counsellor`. Competitor Ranking Summary avg_pos values of 58.4 and 65.3 show keywords far outside the top 10 are included. FEATURE_GUIDE §2.1: "The keywords and competitors you see analysed are the ones Serp-Discover handed over — nothing is invented."
- Why it matters: the owner reads "Traffic Magnets" and "Systemic Vacuums" as openings on his target keywords; they are mostly competitors' brand names and navigational queries. The reframes (C-M-15), overlap queues (C-M-11), barbell top-10 counts (C-M-09) and velocity alerts inherit the wrong universe.
- Fix: audit the handoff's `url` and `primary_keyword_for_url` (that is what Tool 1 ranked). If `ranked_keywords` is kept as an enrichment, filter to keywords that contain a clinical-vocabulary term or are in the handoff keyword set, drop keywords whose text contains the domain's brand token, and print in the report which source each keyword came from.

### C-M-02 · "Systemic Vacuum" / reframe target = any page with systems_score 0, regardless of medical language or topic
- Class: WRONG
- Impact: High
- Verdict: CONFIRMED (probe p02 §B; run_11)
- Where: `src/database.py:1034-1045` (`WHERE … (systems_score = 0 OR systemic_label = 'Surface-Level') ORDER BY est_traffic DESC LIMIT 5`); `src/reporting.py:193-211` (magnets `ORDER BY est_traffic DESC LIMIT 20`, vacuums `systems_score == 0 | Surface-Level`); README "Key Concepts"; USER_MANUAL "Traffic Magnets … Use medical model language"; FEATURE_GUIDE §4.1–4.2.
- Evidence: run_11 lists `rcav.org (archdiocese of vancouver): Medical Score 0, Systems Score 0.0` and `foundrybc.ca (foundry): Medical Score 3` as "**primary targets** for content reframing", and spends gpt-4o tokens reframing the Archdiocese of Vancouver. Probe: a page with medical 0 / systems 0 is returned first by `identify_strategic_openings`. README defines a magnet as "High-volume competitor pages that rank well but use only medical language"; the query has no language condition at all (run_11 magnets include `Standard` pages with systems 2.5) and no position condition.
- Why it matters: the report's action list ("write these first") is driven by ETV ordering alone; a zero-vocabulary page (an empty, blocked-but-200, or off-topic page) is the top vacuum.
- Fix: require `medical_score >= penalty_thresholds.tier_1_max` (or a new `vacuum_min_medical`) AND keyword relevance (keyword in handoff set, or contains a Tier-1/Tier-2 term, and does not contain the domain's brand token) before a row can be a vacuum or a reframe target; in the report, rename "Traffic Magnets" to "Highest-ETV sampled pages" or implement the documented filter.

### C-M-03 · Branded-demand volumes are fetched for dictionary words ("lavender", "bach", "clear", "coast", "wong", "m")
- Class: WRONG
- Impact: High
- Verdict: CONFIRMED (probe p04 §C; derivation is deterministic — live volumes not fetched here)
- Where: `src/brand_utils.py:23-40` (`derive_brand_name`); `src/brand_demand.py:28-37, 82-113`; `src/comparison_features.py:118-125`; `shared_config.json → branded_demand.generic_brand_prune` (6 words); `reporting.py:371-384`; FEATURE_GUIDE §4.7.
- Evidence: run_11 domains derive to `lavendercounselling.com → 'lavender'`, `bachcounselling.com → 'bach'`, `clearcounselling.ca → 'clear'`, `coastcounselling.ca → 'coast'`, `wongcounselling.com → 'wong'`, `jerichocounselling.com → 'jericho'`, `lonsdalepsychology.ca → 'lonsdale'`, `goodlifetherapy.ca → 'goodlife'`, `m.yelp.com → 'm'`; the query set sent for Google Ads volume is `['lavender', 'lavender reviews', 'lavender pricing', 'lavender login', 'lavender cost', 'lavender vs']`. The client's token `'livingsystems'` is specific, so its share will be a rounding error next to "lavender". Prune list catches only therapy/counselling/psychology/health/wellness.
- Why it matters: the section is sold as "a lead indicator of market presence that on-page SEO can't fake"; the numbers are search demand for plants, composers and streets.
- Fix: query the display brand, not the stripped token (`"Lavender Counselling"`, plus the handoff's `client_brand_names` for the client — currently unused; `comparison_features.py:119` reads `client.brand_names` from shared_config, which does not exist). Add a sanity gate: if volume(bare token) > k × volume(token + "counselling"), mark `estimation_basis = "ambiguous_brand"` and withhold share/growth. Print the query strings used in the Excel sheet.

### C-M-04 · Competitor Ranking Summary `total_keywords` is inflated by a LEFT JOIN cross-product
- Class: WRONG
- Impact: Medium
- Verdict: CONFIRMED (probe p02 §A; run_11)
- Where: `src/reporting.py:107-123`.
- Evidence: `SUM(CASE WHEN m.keyword … THEN 1 …) … LEFT JOIN traffic_magnets tm ON m.run_id = tm.run_id AND m.domain = tm.domain` multiplies each metrics row by the number of magnet rows for the domain. Probe: 10 keywords × 3 magnets → `total_keywords 30`; 10 × 1 → 10. run_11 shows 30 for almost every domain (10 sampled keywords × 3 audited pages), 21 = 7×3, 27 = 9×3, 4 = 4×1. `avg_pos` survives (uniform multiplicity) but is an average over the API's 10 sampled keywords at any position.
- Why it matters: the first table the owner reads states each competitor "ranks for 30 keywords"; the true number is the sample size (≤10). It also feeds the "Volume Scaler" impression.
- Fix: `COUNT(DISTINCT m.keyword)` and move the magnet aggregates into a subquery grouped by domain. Rename the column `sampled_keywords (n≤10)`.

### C-M-05 · `systemic_depth = High` from a single generic Tier-2 word; "Direct Systemic" from cached pages; raw count compared with weighted score
- Class: WRONG
- Impact: Medium
- Verdict: CONFIRMED (run_11; exact trace)
- Where: `src/reporting.py:114-115, 125-138`; `src/main.py:506-509`; `src/database.py:955-973`; USER_MANUAL "Section D".
- Evidence: `has_expert = systems_score > 0 AND label != 'Surface-Level'` → "High". run_11: `hollyburn.ca` and `vancouverpsychologycentre.com` are "High" systemic depth while their magnet rows show `systems_score 0.5` (one Tier-2 token, e.g. "relationship"). "Medical" is `max_med > max_sys`, a raw count vs a ×2/×0.5 weighted score (2 medical words vs 3 Tier-2 words → "Medical"). For cache hits main.py estimates `t3 = systems_score / 2.0 if systems_score >= 2.0` — so on a re-run within 7 days a page with four generic Tier-2 words (score 2.0) becomes "t3 = 1" and the domain is tagged `Direct Systemic — Use 'Functional Facts' to provide a more rigorous Bowen alternative`.
- Why it matters: "systemic_depth" and "recommended_strategy" are the two columns the manual tells the owner to use to pick targets.
- Fix: persist `t2_count`/`t3_count` in `semantic_audits` (drop the cache estimate); define depth bands on `t3_count ≥ 1` → "Bowen vocabulary present", `t2 density` → "systems vocabulary", else "none"; never compare `medical_score` with `systems_score` directly.

### C-M-06 · Fragile-Magnet / Market-Velocity alerts fire on Moz outages, 1-point PA noise, and persist across runs
- Class: WRONG
- Impact: High
- Verdict: CONFIRMED (probe p02 §D–E)
- Where: `src/main.py:400-406, 453` (`moz_metrics_map.get(url, 0)` → PA 0 on any Moz error); `src/database.py:907-953` (`drift < -2`, docstring "and Traffic_Value is stable" — not implemented); `src/velocity_module.py:83-108` (`da_drift < 0` or `rank_drift <= -2` → "Strike this page now."; `SELECT DISTINCT url, keyword, domain FROM market_history` — no run scope); `reporting.py:88-104`.
- Evidence: Moz failure in run 2 → `{'drift': -38.0, 'alert': 'Fragile Magnet'}` and the report prints "Page Authority drifted by -38.00. The competitor is losing authority on this page. Now is the time to publish your 'Systems Approach' page." PA 38→37 with rank unchanged → `Fragile Magnet … Strike this page now.` Rank 3→5, PA flat → same. Because `get_market_alerts` compares the last two rows for every URL/keyword ever recorded, an alert repeats in every subsequent briefing until that URL is snapshotted again. Two detectors with different thresholds (−2 vs <0) render under two headings for the same event.
- Why it matters: this is the single most action-oriented sentence in the report ("publish now"), and it is produced by integer-index noise, API failures and stale history.
- Fix: store `NULL` PA when Moz failed and skip drift when either side is NULL; one detector, threshold in config (e.g. `pa_drop_min: 3` over ≥2 consecutive runs); scope alerts to URLs present in the current run; remove the "traffic stable" claim or implement it.

### C-M-07 · `visibility_cliff` measures the tool's own sampling, not the competitor's visibility
- Class: WRONG
- Impact: High
- Verdict: CONFIRMED (probe p02 §G; run dates)
- Where: `src/database.py:760-772` (`SUM(rank <= 10) … GROUP BY DATE(timestamp)`); `src/risk_radar.py:32-56`; `shared_config.json → risk_signals.cliff_drop_pct 0.3`; FEATURE_GUIDE §5.3; `reporting.py:405-427`.
- Evidence: the series is the number of `market_history` rows (≤3 per domain per run — one per audited page) with rank ≤10, summed per calendar day. Runs 5–8 were all on 2026-05-02; probe with 4 runs on one day → series `[3, 12, 3]` → `visibility_cliff high, drop 75%`. One 429 on page 2 (`domain_blocked`, no snapshot) → `[3, 1]` → `high, 66.7%`; a single page slipping from 10 to 11 → `[3, 2]` → `medium`.
- Why it matters: the Reputation-Risk Radar tells the owner a competitor "just cliffed — a window to strike" and separates "own-site warnings"; N≤3 with per-day grouping cannot support a 30% step-change test.
- Fix: group by `run_id`, divide by pages attempted that run, and require a floor (e.g. ≥10 ranked keywords per snapshot, which means a different data source: DataForSEO `domain_rank_overview` or the full `ranked_keywords` count). Until then, do not emit `visibility_cliff`; say "not measured".

### C-M-08 · "therapy" (and "trauma", "condition", "patient") is Tier-1 Medical — the client's own vocabulary scores as medical model
- Class: WRONG
- Impact: Medium
- Verdict: CONFIRMED (probe p01 §D; exact trace)
- Where: `shared_config.json → clinical.tier_1_medical` (also lists "therapy" in `stop_words`); `src/gsc_performance.py:297-315, 340-351` (`get_tier`, "Bowen page attracting Medical Model audience"); `src/positioning.py:134-146` (client focus via substring match); `reporting.py:57-71`.
- Evidence: Bowen-practice copy ("family therapy and couples therapy … Book a therapy session") → `medical_score 6, systems 0`. In the GSC section every query containing "therapy" is "Tier 1 (Medical)", so "couples therapy north vancouver" seen-but-not-clicked → "Reframe the Meta Titles with systemic depth", and any client page with systems_score > 5 found via such a query → "Clinical Mismatch: Bowen page attracting Medical Model audience" (`medical_hits` is actually `clicks`). `classify_query_tiers` uses `term in ql`, so "air conditioning" → medical ("condition"), "food processing jobs" → systems ("process").
- Why it matters: the axis the whole tool is built on labels the client's core service term as the opposing model; the GSC action items and the client's barbell focus are artefacts of that one dictionary entry.
- Fix: move "therapy", "counselling", "patient", "condition", "trauma" (ambiguous) to a neutral tier; Tier-1 should be diagnostic/pathology vocabulary only (symptom, disorder, diagnosis, medication, prognosis, syndrome, illness). Word-boundary matching in `classify_query_tiers`.

### C-M-09 · Barbell authority axis is not "the same formula for you and competitors"; the client lands `authoritative` by construction
- Class: WRONG
- Impact: Medium
- Verdict: CONFIRMED (probe p04 §B; trace)
- Where: `src/main.py:408-418` (`save_competitor_summary(domain, int(round(avg_pa)))` — average Moz **Page** Authority of the 10 sampled URLs); `src/comparison_features.py:77-84` (client `moz_da` = config `client.da` 35, `top10_count` = all GSC queries ≤10); `src/positioning.py:95-131`; `shared_config.json → positioning.framework_caption`; `reporting.py:314-322` ("the same formula for you and competitors"); feasibility `reporting.py:296-301` ("your DA vs. each competitor", column `competitor_da`); `src/analysis.py:25-33`.
- Evidence: client authority = 0.7×35 + 0.3×min(240/10,1)×100 = **54.5 → `authoritative`** with focus 1.5; a competitor needs avg PA ≥ ~29 **and** all 10 sampled keywords in the top 10 to reach 50, and the PA>50 upstream filter caps the field. The competitor's "DA" in feasibility (`client DA + 5 ≥ competitor_da`) is likewise page authority of sampled URLs. The `+5` is hard-coded in `analysis.py` while `technical.feasibility_threshold: 5` and `moderate_feasibility_max_gap: 15` sit unused in config.
- Why it matters: the report says the client is the big-and-credible end of the barbell and tells it which rivals are "beatable middle" and which are "feasible"; both are comparisons of DA to PA and of a 5000-row GSC export to a 10-keyword sample.
- Fix: fetch Moz `domain_authority` for each competitor root (the same `url_metrics` call returns it) and label the column `domain_authority`; give the client a top-10 count over the same keyword universe as competitors (or drop the top-10 component); read the `+5` from config.

### C-M-10 · Barbell "focus" is undefined noise at ≤3 pages; focus = 100 whenever one tier count is zero
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p04 §B)
- Where: `src/positioning.py:69-93, 95-108`; `src/database.py:821-839` (sums of `traffic_magnets.medical_score` / weighted `systems_score`); `reporting.py:313-334`; FEATURE_GUIDE §4.5 "small & sharply focused".
- Evidence: `{medical 3, systems 0}` → focus 100 → `niche_owner`; `{3, 0.5}` → 40.8 → `middle`; `{3, 1.5}` → 8.2 → `middle`. One "relationship" token moves a domain across the quadrant boundary. The entropy is taken over a raw count and a weighted score (C-M-05). The "⚠️ Danger zone (undifferentiated middle)" line names domains on that basis.
- Why it matters: the manual says "Middle-quadrant competitors are the softest targets"; the quadrant is decided by a handful of generic tokens on ≤3 pages.
- Fix: require a minimum tier-token total (e.g. `min_focus_tokens: 20`) before computing focus, else `insufficient_data`; compute entropy over unweighted t1/t2/t3 counts; print the counts in the table.

### C-M-11 · SERP Overlap cells and action queues are artefacts of the 10-keyword samples and of GSC-vs-DataForSEO position semantics
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p04 §A; trace)
- Where: `src/serp_overlap.py:97-156` (module docstring admits `absent` is unreachable); `src/database.py:857-883`; `src/gsc_performance.py:70-112` (90-day, all countries, `position` = GSC average); `src/api_clients.py:19-27` (Canada snapshot `rank_absolute`); `shared_config.json → serp_overlap.commodity_high_overlap 3`; `reporting.py:248-285`; FEATURE_GUIDE §4.4.
- Evidence: a competitor's own brand ("jericho counselling") → `exclusive_competitor` → "rivals rank, you're absent — your clearest content gaps to fill". Client GSC average 11.4 (90 days, global) vs rival snapshot rank 4 (Canada) → `exclusive_competitor`; the report does not say page-2 averages count as absent (the guide §9 does). "Commoditized" = ≥3 of the tracked rivals' sampled keywords coincide with the client's GSC — with 10 keywords per rival this is mostly measuring "which rivals share our head terms". `all_competitor_gap` intersects every rival's 10-keyword set, so "every tracked rival ranks" is effectively unreachable (correct, but the section header promises it). The universe is each rival's top-10 ∪ all client GSC queries, so `exclusive_self` is almost everything the client ranks for.
- Why it matters: both action queues the guide says to "work" are populated by sampling artefacts; the owner could spend content effort on a rival's brand name.
- Fix: build the keyword universe from the handoff's target keywords (C-M-01); exclude keywords containing a rival's brand token; compare like with like (use GSC `country=can`, or DataForSEO SERP for the client too); state in the section that `n rivals` is "of the ≤10 keywords sampled per rival".

### C-M-12 · EEAT: composites built from near-constant booleans, rendered to 2 dp with "high" confidence on every page
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p03 §A–C)
- Where: `src/eeat_scorer.py:113-120` (confidence = null count), `148-154` (images / "us, our" count), `165-176` (expertise 0.4 for any Tier-2 word), `186-189` (DA/60 — but main.py passes the URL's PA; `0 or None` on Moz failure), `197-205`, `253-272` (stock hosts only catch hot-linked stock); `src/semantic.py:219, 293-296` (`is_https = url.startswith("https")`, `'contact' in href`); `shared_config.json → eeat_weights`, `eeat_client_messaging.confidence_levels`; `reporting.py:169-175`; USER_MANUAL "Trustworthiness | HTTPS, contact page, privacy policy, HTTPS".
- Evidence: bare https page with a "contact" link and the words "our relationship … process we use" → `experience 0.26, expertise 0.40, authoritativeness 0.00, trustworthiness 0.70, confidence high`. Trust can only be {0, .3, .4, .6, .7, 1.0}; 0.4 of it is the scheme of the URL DataForSEO returned. Expertise's 0.4 "tier_3_or_tier_2_present" fires on "relationship". Authoritativeness = PA/60 + outbound links/5 + Organization schema; when Moz fails the DA term is excluded and the score is renormalised, so a Moz outage *raises* it. Confidence is "high" for every page that loaded and "low" only for blocked pages, while config describes 0.0–0.5/0.5–0.8/0.8–1.0 bands that are never computed. Manual's duplicated "HTTPS" is a doc typo (code .4/.3/.3). Weights have no stated source.
- Why it matters: the table reads like a measurement ("0.26 vs 0.31"); the guide's "out-signal the weak, match the strong" rests on it. It is labelled heuristic in the report — that part is honest — but the precision and the confidence column are not.
- Fix: render the booleans (byline / credentials / dates / schema / contact / privacy) as ✓/✗ columns and drop the composite, or keep the composite at 1 dp with the value set stated; compute confidence from signal coverage as the config promises; pass domain-level DA; document weights as "editorial, 2026-05".

### C-M-13 · Cluster detection with N=3: "clustered" = the other two pages link to the homepage; "isolated" = www/non-www mismatch or nothing more
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p03 §D)
- Where: `src/cluster_detector.py:69-77, 84-110, 118-122` (`_normalise` keeps scheme+host verbatim); `shared_config.json → cluster_thresholds {hub_in_degree_threshold 2, min_pages_for_signal 3}`; `technical.max_audit_pages_per_domain 3`; `reporting.py:186-190`; FEATURE_GUIDE §3.3 ("prioritise isolated/linked competitors as easier wins").
- Evidence: home + two pages that carry the usual logo/menu link home → `clustered`, hub = homepage. Three pages with no links among the three → `isolated` (the site may have hundreds of interlinked pages). Same three pages with absolute `https://c.ca/…` links while scraped as `https://www.c.ca/…` → `isolated`. With N=3 and threshold 2, the only possible hub is a page both others link to. `insufficient_data` for N<3 is honest and is the only robust output.
- Why it matters: the manual explicitly ranks competitors as "easier to overtake" on this label.
- Fix: either raise `max_audit_pages_per_domain` to ≥8 for cluster purposes, or report only `hub_is_homepage: yes/no` and `pages_sampled`, and remove the isolated/clustered advice from the guide; normalise host (`www.` strip, scheme-insensitive) before matching.

### C-M-14 · GEO tier rewards WordPress/Yoast defaults over FAQ structure, and the section asserts causation ("Why Competitors Get Cited")
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p03 §E)
- Where: `src/geo_profiler.py:120-122` (Organization/Person count as "high-value schema"), `158-171` (any byline incl. "admin" = "named author byline"; `article:published_time` = "dated / fresh"), `232-251` (`_why_cited`: "These structures make the page easy for AI answer engines to quote"); `shared_config.json → geo_signals.strong_tier_min_signals 3`; `reporting.py:227-235`; FEATURE_GUIDE §3.4.
- Evidence: stock WP post (Organization+Person schema from Yoast, byline "admin", published_time, zero question headings) → **Strong**; FAQ page with FAQPage schema and two genuine question headings but no byline/date → **Moderate**. Nothing in the tool checks whether the page is cited; the serp-discover AI-visibility export (which does carry `ai_citations`) is not used to validate the tier.
- Why it matters: the section header and `why_cited` sentence tell the owner these structures are *why* rivals get cited; the owner is told to copy them as a "build checklist". The caveat line at the bottom is good but the header contradicts it.
- Fix: weight FAQPage / question headings above Organization/Person; exclude generic bylines; rename the section "Extractability signals (structural, unvalidated)"; if the AV export is present, join `ai_citations.domain` to show whether Strong-tier domains are in fact cited (that would turn the heuristic into a checkable claim).

### C-M-15 · Reframes: prompt asserts a "Medical Model" page even at medical 0, PAA context is never present on the handoff path, output is unlabelled model text
- Class: DOC–CODE DRIFT (plus UNLABELLED)
- Impact: Medium
- Verdict: CONFIRMED (run_11; trace)
- Where: `src/reframe_engine.py:69-100` ("A competitor page … is winning on the keyword '{keyword}' using a "Medical Model" approach (Medical Score: {medical_score})"); `src/main.py:75` (`return targets, {}` — no PAA from handoff; `handoff_schema.json` has no PAA field); `reporting.py:469-476`; FEATURE_GUIDE §6.1 ("weaving in the real 'People Also Ask' anxieties captured for that keyword"); compete-spec.md:237.
- Evidence: run_11 "Reframe: archdiocese of vancouver" (medical 0) produces 600 words on "Triangles … within the Archdiocese community". `**User Anxieties (PAA):**` never prints for handoff-driven runs. The model text is the only part of the report with no "heuristic/AI-generated" marker in the section body (the heading says "Automated"); it also fabricates first-person claims ("At Foundry Abbotsford, we advocate…").
- Why it matters: the guide says the reframe is "a concrete starting structure"; for off-topic keywords it is confident nonsense, and `temperature 0.7` means it is not reproducible.
- Fix: gate reframes on C-M-02's relevance test; pass `medical_score` only when > 0 and otherwise say "no medical vocabulary detected — reframe not applicable"; add a one-line marker "Generated by gpt-4o from the keyword, URL and score above — no page content was supplied" (true: the prompt never sees the competitor text); drop the PAA sentence from the guide until Tool 1 exports PAA.

### C-M-16 · YouTube `none_found` is rendered as a definitive ✗ "no channel"; a handle equal to the generic brand token is `confirmed`
- Class: WRONG (label) / UNLABELLED
- Impact: Low–Medium
- Verdict: CONFIRMED (probe p04 §E; trace)
- Where: `src/youtube_presence.py:149-162` (search top-3 by domain stem; no name match → `none_found`, `has_channel False`), `174-200` (`handle = ncustom == nstem or ncustom == ntoken`); `reporting.py:440-465` ("`none_found` = no channel"); FEATURE_GUIDE §4.8 (same wording).
- Evidence: `bachcounselling.com` vs a channel `@bach` → `(high, 'handle') → confirmed`. A therapist whose channel is titled by her own name (not the practice stem) and whose About lacks the domain → `none_found` → "✗". The guide distinguishes `error` (retryable) from `none_found` as if the latter were a measured negative.
- Why it matters: "state absence, don't fake it" — `none_found` is "not found by a 3-result name search", not "no channel".
- Fix: require handle == stem (not token) for `high`; render `none_found` as "none matched (name search, top 3)"; set `has_channel NULL` for that state.

### C-M-17 · SoV: competitors mentioned by display name but never cited vanish into "other", and only the client's share is printed
- Class: UNLABELLED HEURISTIC
- Impact: Low–Medium
- Verdict: CONFIRMED (probe p04 §D; depends on serp-discover export format — real export sampled: `brand: "Living Systems"`)
- Where: `src/sov_analyzer.py:118-140` (`nb in competitor_brand_set` compares the normalised export brand "jericho counselling" with the derived token "jericho"); `src/comparison_features.py:99-102`; `reporting.py:351-360` (`category != 'other'` filter; `presence_rate` never printed).
- Evidence: export with Living Systems 2 mentions / Jericho Counselling 6 → rows `client 25%`, `other 75%`; report prints "Mention share: Living Systems (you) 25%" with no visible 75%. `mention_share` is share of brand mentions (all brands incl. other), not share of answers; `presence_rate` (count/questions_total — the "whose brand the models return" quantity the guide describes) is computed but not shown. "Cited but you're not" is engine-wide (client never cited by that engine), not per-question as the guide's "cites … but never cites you alongside" implies.
- Fix: match competitor brands by `derive_brand_name(export brand)` or by substring of the display name; print `presence_rate` ("named in k of n answers") instead of or beside mention share; print the "other" remainder so shares visibly sum to 100.

### C-M-18 · Thresholds and weights with no stated source; several config keys are dead and the live thresholds are hard-coded
- Class: UNDOCUMENTED PROVENANCE (and DOC–CODE DRIFT)
- Impact: Medium
- Verdict: CONFIRMED (grep)
- Where: `Serp-compete/spec.md` "Revision 2/3/4" (Tier-3 ×2.0, Tier-2 ×0.5, Tier-1 > 10, −50%; Volume Scaler 1000/15; Generalist 10; drift < −2; `+5`); `src/main.py:410` (`avg_pa > 50` hard-coded; not in config); `src/database.py:1022` (volatility `>= 3` hard-coded while `risk_signals.volatility_high_shift 6` exists); `src/database.py:965-971` (1000/15/10 hard-coded); `src/analysis.py:30` (`+ 5` hard-coded); unused config keys `technical.feasibility_threshold`, `moderate_feasibility_max_gap`, `score_normaliser`, `penalty_thresholds.pseudo_systems_threshold`, `gsc_settings.position_target_max`; `eeat_weights` (no source); `eeat_scorer.py:152, 187-189, 269` (÷10, ÷60, ÷5, 80% stock ratio — code constants); `geo_signals` 3/1; `serp_overlap.commodity_high_overlap 3`; `risk_signals.cliff_drop_pct 0.3`; README "All settings in `shared_config.json`"; USER_MANUAL "Tier 1 count above the `penalty_thresholds.tier_1_max` value".
- Evidence: every threshold traces to a spec line that states it, none to a rationale, calibration or citation. The guide §3.1 says "Exact weights/thresholds live in shared_config.json … editable without code changes" — true for the semantic weights, false for PA>50, +5, volatility 3, Volume Scaler, EEAT normalisers.
- Why it matters: a retired engineer will ask "where does 10 come from?"; the honest answer is "chosen in March 2026 without data", and the docs imply otherwise.
- Fix: for each threshold add a `_source` note in `shared_config.json` ("editorial default, uncalibrated, 2026-03") and a one-line "Provenance" column in FEATURE_GUIDE §9; move the hard-coded ones into config and delete the dead keys.

### C-M-19 · Vocabulary counting mechanics: no length normalisation, no lemmas, hyphenated entries unreachable, nested phrases double-counted, menu text counted
- Class: UNLABELLED HEURISTIC
- Impact: Medium
- Verdict: CONFIRMED (probe p01 §B, C, E, F, G, H)
- Where: `src/semantic.py:118-128` (only `nav/footer/script/style/aside` stripped; `<header>`/div menus survive; headers text is prepended so h1–h3 are counted twice), `391-414` (`token.text in set` — no lemma; multi-word phrases via `str.count`); `clinical.tier_2_systems` contains `self-regulation` (spaCy splits it; never matched), `process`, `relationship`, `attachment`, `internal family systems` (a different model); `scoring_logic.py:61-80`.
- Evidence: 5 medical words score 5 in a 5-word text and 5 in an 805-word text; "triangle"×3 → 0, "triangles"×3 → 3; "treatments" → 0; "self-regulation"×3 → 0; "differentiation of self" → t2 1 + t3 1 (score 2.5); "emotional process" → t2 2; a `<header>` menu listing seven treatment services → medical 9 on an about-page whose body is about distance and pursuit; "booking process … PDF attachment … internal family systems" → systems 3.0. The Surface-Level threshold is an absolute count over headings + first 500 words.
- Why it matters: medical_score and systems_score are the inputs to vacuum selection, depth, focus and the reframe prompt; they are sensitive to template boilerplate and dictionary spelling, not to what the page argues.
- Fix: use `token.lemma_` with lemmatised dictionary entries and spaCy `PhraseMatcher` for every multi-token/hyphenated entry (count each span once, longest match wins); strip `<header>` and elements with `menu`/`nav` in class; count body only, once; report densities per 1000 words with the window size; make Surface-Level a density threshold.

### C-M-20 · Smaller doc–code and labelling drifts in the report text
- Class: DOC–CODE DRIFT
- Impact: Low
- Verdict: CONFIRMED (trace)
- Where / evidence:
  - `est_traffic` is DataForSEO `etv` (`main.py:440`), undefined in every doc; the overlap section's "Volume by cell (est. traffic)" and Excel `keyword_volume` are `MAX(traffic)` = the best-ranking *competitor's* ETV, not search volume (`database.py:871-883`).
  - USER_MANUAL "Traffic Magnets … Rank well (top 10)" — no position filter anywhere (run_11 avg_pos 58–65).
  - FEATURE_GUIDE §4.7 / `reporting.py:373-375` "your own figure is GSC-anchored when the serp-discover D2 export is available" — `own_anchor=None` is hard-wired (`comparison_features.py:125`); D2 is never read (its absence is already tracked in TODO; the misleading report sentence is not).
  - Volatility Alerts table prints `shift` with no sign convention (positive = worse).
  - `handoff.supported_versions ["2.0","2.1"]` vs the real handoff `schema_version "1.0"` and `handoff_schema.json` — the config key is decorative.
  - `convert_handoff_to_targets` comment "Handoff doesn't include traffic; it's deterministic audit data" — then traffic is taken from DataForSEO anyway.
  - Executive Summary is a fixed sentence; it never states run coverage (domains attempted / skipped by PA filter / blocked / cached), which only reaches the console ("Enrichment coverage"), so a reader of the .md cannot tell fresh from carried-forward sections despite §9's promise.
- Fix: define `est_traffic` ("DataForSEO estimated monthly visits for this keyword×position, not measured traffic") in the magnets header; rename `keyword_volume` → `best_rival_etv`; delete the D2 sentence until wired; add a sign note; write the enrichment-coverage and PA-filter/blocked counts into the Executive Summary.

---

## Checked and found sound
- `serp_overlap`: when the GSC map is empty every row is `self_unknown` and the exclusive queues are withheld, with a loud banner (probe p04 §A).
- `risk_radar.detect_anchor_spam` + `anchor_caveat_lines`: severity gated on widest-anchor reach and sample truncation; "received, not bought" caveat travels with every row; unreadable coverage is stated, including for runs that predate the table.
- `brand_demand`: an all-zero volume response is labelled `volume_unavailable`, not rendered as zero demand.
- `sov_analyzer` / `youtube_presence`: a missing export or API key yields an absent section, never zeros; YouTube `error` is distinct from `none_found` and quota exhaustion is surfaced.
- `geo_profiler._count_question_headings`: requires a trailing "?" and an interrogative opener (resists "How We Help").
- `positioning.compute_authority`: a missing DA is excluded and renormalised, not treated as 0; `insufficient_data` is used rather than `middle`.
- `cluster_detector`: N<3 → `insufficient_data`; `enrichment.finalize_domain_cluster` carries forward rather than computing on a mixed cache/fresh subset.
- `main.py:476-484`: blocked/errored scrapes are not saved as zero-score magnets (the 429 circuit breaker works).
- `serp_overlap.rollup_by_cell`: each keyword contributes to exactly one cell.
- `risk_radar.detect_parasite`: requires topical mismatch AND a whole-word commercial term; the subfolder name alone never triggers.
- `reporting.py` EEAT, cluster, GEO, overlap, barbell, SoV, brand, risk and YouTube sections all carry an in-report heuristic caveat line (the problem is the headline numbers, not the absence of caveats).

## Not examined
- `orchestrator.py` (Streamlit GUI), `step_dag.py`, `infiltrator.py`, `competitor_mining.py`, `strike_mapper.py` (offline/legacy paths not on `run_audit`).
- `handoff_moz.py` parsing and coverage arithmetic (TODO already lists its open edge cases).
- `youtube_client.py` live API behaviour; DataForSEO ETV and Google Ads volume methodology; GSC OAuth.
- The two pytest suites (what they assert), the Excel export, and `recalculate_scores.py`.
- The `~/.claude/standards/*.md` referenced by CLAUDE.md (not present in the copy).
