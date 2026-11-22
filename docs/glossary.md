# Glossary

Plain-English definitions for the SERP Intelligence tool's reports and workbook.

Generated from `glossary.yml`. Edit that file, not this one — regenerate with:

```bash
python3 generate_insight_report.py --glossary-out docs/glossary.md
```

## Terms used in the report

**AI Overview** — The AI-written summary Google places above the results. It answers the question on the page itself, so fewer people click through to any website. It cites a handful of sources — being one of them is the goal.

**answer similarity** — How much the top results reuse the same wording. It compares words, not meaning, so pages that make the same point in different words score as less similar than they really are. Read it as a floor.

**backdoor strategy** — Where a keyword has mixed intent and the only intent you serve is NOT the one the SERP mostly serves. There is a way in, but you are writing against the grain of what Google is showing. When the dominant intent is one you do serve, the call is "compete on dominant", not backdoor.

**cited-share** — The share of your keywords where the AI Overview quotes your site as one of its sources. Zero means the AI is answering your topic without crediting you.

**commodity score** — A 0–100 estimate of how easily one AI paragraph could replace the entire results page for this search. High means everyone is saying the same thing, so a generic page is worth little — say something the others do not. Its weights and its 40 / 70 bands are editorial: somebody chose them for this client's market, and "Where these thresholds come from" at the end of this appendix says whether anyone has since checked them.

**content type** — What kind of page is ranking — a guide, a news item, a service page. It tells you what format to write in. If guides dominate, a service page will struggle however good it is.

**CTR** — Click-through rate — of everyone who sees your listing, the percentage who click it. "Estimated CTR loss" is a modelled guess at the clicks the AI Overview is absorbing, not a measurement of your actual traffic. The three numbers behind that guess — the CTR-by-position curve, the 60% interception rate and the half credit for being cited — have no published source on file, so the report states them as the owner's working assumption. Record a study and a date in config.yml aio_exposure.sources and the report prints that instead.

**DA coverage** — How much of the ranking page the average rests on, written as "7/10 (3 unscored)": seven of the ten ranking domains had a Domain Authority record and three did not. Read it before the gap. The same gap from three domains is a weaker claim than from ten, and nothing else on the row tells you which you are looking at. A dash means the coverage was not recorded for that run (an older report), which is not the same as nothing having been scored.

**DA gap** — The average Domain Authority of the sites currently ranking, minus yours. A negative gap means you are stronger than the pages you would be competing with, so ranking is realistic. A positive gap means they are stronger.

**Domain Authority** — A 0–100 third-party score estimating how much ranking strength a whole website has, based largely on who links to it. Moz's invention, not Google's, so treat it as a rough comparison between sites rather than a fact about your site.

**entity dominance** — What kinds of organisation own the results — private practices, directories, government, nonprofits. It tells you who you are actually up against, which is often a directory rather than a competing counsellor.

**extraction play** — The verdict that ranking is unrealistic but being quoted is not. You format the page so an AI can lift a clean answer out of it — question headings, the answer immediately underneath. Success is measured in citations, not position.

**FAQPage markup** — Invisible labelling in the page's code that tells machines "this is a question, and this is its answer". It does not change what a human reads; it makes the question-and-answer structure unambiguous to Google and to AI engines.

**feasibility status** — The verdict on whether you could realistically rank for this keyword, read off the DA gap: within 5 points is High, 6–15 Moderate, more than 15 Low. Those three bands are editorial — somebody chose them as sensible for a local nonprofit, and nobody has yet checked them against whether the keywords they called High were ones you went on to rank for. The gap itself is a measurement; the band is a judgement about it. Read the verdict beside the weakest non-directory competitor, which answers the same question with less arithmetic between you and the evidence.

**Featured Snippet** — The boxed answer Google lifts out of one page and shows above the results. Won by answering a question directly and early on the page.

**GEO** — Generative Engine Optimisation — writing so AI answer engines can quote you, as opposed to writing to climb the ordinary rankings. The two overlap but the scoreboard is different.

**Knowledge Panel** — The information box about a person, place or organisation, usually on the right. Google builds it from what it already believes about that entity.

**Local Map Pack** — The map with roughly three business listings pinned to it, near the top of the page. It appears when Google thinks the searcher wants a nearby business. It takes a large share of the clicks, and you get into it through your Google Business Profile, not through your website.

**local pack presence** — Whether the map-and-listings box appeared for this search. When it does, the ordinary results start lower down the page and get fewer clicks.

**mixed intent** — Google is showing a blend of result types because it is unsure what searchers want. It usually means two different pages could both rank, which is an opening.

**Not measured** — The tool tried and could not get enough data to answer, so it says so instead of guessing. For feasibility it means fewer than five ranking domains carried a Domain Authority record, or your own was never measured — not that the keyword is hard. The keyword is still listed, with a line under "Not measured — why" saying which case it is, and the tool withholds the things that would rest on a verdict: no pivot recommendation, no "you are stronger" comparison, and no place in the best-opportunity pick. Re-run once the data provider is reachable.

**organic position** — Where your page sits in the ordinary, unpaid list of results. Position 1 is the top link. A dash means you were not found in the results checked.

**People Also Ask** — The expandable list of related questions in the middle of the results page. These are real questions Google has seen people ask, which makes them a reliable source of headings for your own page.

**rank play** — The verdict that this keyword is worth chasing a top-ten position on, because your site is strong enough relative to who is already there. Success is measured in position.

**search intent** — What the searcher is actually trying to do. This report uses four: informational (wants to understand something), local (wants somebody nearby), transactional (ready to book or buy), and mixed (the results page shows a blend, so Google is hedging).

**SERP** — Search Engine Results Page — the Google page you get after searching. Everything on it, not just the list of links.

**SERP feature** — Any box Google puts on the results page besides the plain list of blue links — a map, a video row, an answer box, an image strip. Features push the ordinary results further down the page.

**SERP homogeneity** — How alike the competing pages are to each other in type and origin. High homogeneity means the whole page is one kind of result, which is either a wall to climb or a gap to exploit.

**title pattern** — The recurring shape of the ranking page titles — "how to…", "best…", "X vs Y", a numbered list. Where one shape dominates, it is the format Google is rewarding. "No dominant pattern" means titles are varied and the format is open.

**volatility** — How much the rankings moved since the last run of the same keywords. It needs two runs of the same keyword list to mean anything.

## Columns in the .xlsx workbook

| Column | Sheet | Meaning |
|---|---|---|
| `Run_ID` | all | Timestamp identifying one run of the tool. Every row from the same run carries the same value, so you can separate runs when sheets are combined. |
| `Root_Keyword / Source_Keyword` | most | The keyword from your CSV that this row came from. Source_Keyword is the specific search executed; Root_Keyword is the original seed it derived from. |
| `Query_Label` | Overview, Keyword_Feasibility | Which variant of the search this row is. "A" is the keyword as you supplied it; "P" is a hyper-local pivot variant the tool generated. Pivot rows are suggestions, not measurements of your keyword. |
| `Executed_Query` | most | The exact text sent to Google, after any location or variant handling. Check this when results look unrelated to the keyword you entered. |
| `Params_Hash` | most | A fingerprint of the search parameters used. Two rows with the same hash were fetched under identical conditions and are directly comparable. |
| `SERP_Features` | Overview | Which boxes Google showed besides the plain links (map pack, video row, answer box). "Standard Organic" is not a feature — it means none were found. |
| `Rank` | Organic_Results | Position in the unpaid results. 1 is the top link. |
| `Rank_Delta` | Organic_Results | How many positions this URL moved since the previous run of the same keyword. Positive is an improvement. Blank means no comparable earlier run. |
| `Is_Destination_Page` | Organic_Results | Whether the Link is the page that actually ranked. Google now hides result URLs behind a redirect, and the tool can usually recover only the site, not the page. FALSE means anything page-level for that row — Word_Count, Content_Type, Page Authority — reads "Not Measured" rather than being taken from the wrong page. Read it with Link_Status, which says whether the site was recovered or nothing was. |
| `Link_Status` | Organic_Results | Where this row's Link came from. "destination" is the page that ranked, as Google sent it. "site_root" means Google hid the URL and only the site could be recovered: the competitor is known, the page is not. "unrecovered" means not even the site could be recovered, so the row has no URL and counts towards nothing — not a competitor with no authority, a result that was never measured. |
| `Client_Cited` | Situational_Probes | Whether your site was among the sources the AI Overview cited for this probe question. FALSE on its own means you were not cited. FALSE beside a non-zero Citations_Unresolved means the question was not settled: some of the citations could not be traced to a site, and one of them may have been yours. |
| `Citations_Unresolved` | Situational_Probes | How many of this probe's AI Overview citations Google hid behind a redirect that could not be traced back to a site. Those citations were counted but not identified, so they can neither confirm nor rule out a mention of you. Zero means every citation was identified and Client_Cited is a measurement. |
| `Entity_Type` | Organic_Results | What kind of organisation owns the page — counselling practice, directory, government, nonprofit, publisher. "N/A" means the classifier could not tell, not that the page has no owner. |
| `Content_Type` | Organic_Results | What kind of page it is — guide, news, service page. "other" is the classifier's unknown bucket, not a format you can write. |
| `FAQ_Present / Schema_Types` | Organic_Results | Whether the page carries machine-readable question-and-answer labelling, and which schema.org types it declares. Pages with FAQ markup are easier for AI answer engines to quote. |
| `Question_Heading_Count / Question_Headings` | Organic_Results | How many of the page's headings are phrased as questions, and what they are. A high count on competitors is a sign the topic rewards answer-first format. |
| `Credential_Hits / Author_Present / Review_Marker_Present` | Organic_Results | Trust signals found on the page — professional credentials named, a bylined author, visible reviews. These are the E-E-A-T markers Google associates with expertise. |
| `Intro_Text_Length` | Organic_Results | Characters of prose before the page's first substantive heading. A large number means the answer is buried, which makes the page hard to quote. |
| `client_da` | Keyword_Feasibility | Your site's Domain Authority — a 0-100 third-party estimate of ranking strength, based largely on who links to you. |
| `avg_serp_da` | Keyword_Feasibility | The average Domain Authority of the sites currently ranking for this keyword. This is what you are being compared against. It averages only the ranking domains that had a Domain Authority record — read da_count beside it, since an average of three domains and an average of ten look identical here. |
| `da_count / da_missing` | Keyword_Feasibility | How many of the ranking domains had a Domain Authority record (da_count) and how many did not (da_missing). Together they are the window avg_serp_da was taken over. A domain with no record is left out of the average, never counted as a Domain Authority of zero — counting absences as zeros pulled the average down and made hard keywords look winnable. |
| `da_provider` | Keyword_Feasibility | Which service supplied the Domain Authority figures on this row — dataforseo or moz. Their scores are not interchangeable, so never compare a figure from one against a figure from the other, or track a trend across both. |
| `client_da_source` | Keyword_Feasibility | Where your own Domain Authority on this row came from: the provider plus the date it was measured, "operator override" if you passed one on the command line, or "config fallback (unmeasured, ...)" when the provider had no record and the value in config.yml stood in. A config value is not a measurement and may be on a different vendor's scale, so a gap built on one is indicative. |
| `gap` | Keyword_Feasibility | avg_serp_da minus client_da. Negative means you are the stronger site and ranking is realistic. Positive means they are stronger. Within about two points, treat it as level — the underlying score is an estimate. |
| `feasibility_score / feasibility_status` | Keyword_Feasibility | The gap turned into a normalised score and a High / Moderate / Low verdict. "Not Measured" means there was not enough measured Domain Authority to give a verdict — fewer than five ranking domains had a record, or your own Domain Authority was never measured. That is different from a low score, and the row still shows whatever numbers were measured. |
| `min_competitor_da / min_non_directory_da` | Keyword_Feasibility | The weakest Domain Authority holding a top-10 slot, and the weakest that is not a directory. These answer the question the average cannot: whether anything your size has room on this page. One strong directory pulls the average either way, so a page with five DA-12 clinics on it can read harder than one with a single DA-92 listing site. A blank non-directory figure means no ranking page carried an entity type this run, so the split was not measured — it does not mean no directory ranks here. `entities_known` says how many of the scored pages were classified at all: where that is fewer than all of them, the non-directory figure stands over those pages only, and the report's cell says so — "0 · non-dir 61 (7 of 10 typed)" means the weakest page of any kind scores 0, the weakest that is not a directory scores 61, and 7 of the 10 scored pages had a type to judge by. A cell reading "non-dir not measured" is the unmeasured split; "all directories" is the measured fact that every scored competitor is one. |
| `pivot_status / suggested_keyword / all_variants` | Keyword_Feasibility | Whether the tool suggests targeting a narrower neighbourhood-level keyword instead, which one, and every variant it considered. Only generated for service-type keywords. |
| `Client_In_Local_Pack` | Keyword_Feasibility | Whether your business appeared in the map box. Blank means the check could not be run — not that you were absent. |
| `Type / Phrase / Count` | SERP_Language_Patterns | Repeated two- and three-word phrases from the SERP text, with how often each appeared. Stop words are stripped before counting here, so phrases read oddly ("family origin"). The readable version is in the Markdown report, Section 3. |
| `Has_Main_AI_Overview / Has_PAA_AI_Overview` | Overview | Whether Google showed an AI-written summary at the top of the page, and whether one appeared inside the People Also Ask box. |
| `AI_Sentiment / AI_Subjectivity / AI_Reading_Level` | Overview | Automated readings of the AI Overview's tone, opinion level and reading difficulty. Indicative only — useful for comparing runs, not as absolute measures. |
