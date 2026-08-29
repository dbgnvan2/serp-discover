# Glossary

Plain-English definitions for the SERP Intelligence tool's reports and workbook.

Generated from `glossary.yml`. Edit that file, not this one — regenerate with:

```bash
python3 generate_insight_report.py --glossary-out docs/glossary.md
```

## Terms used in the report

**AI Overview** — The AI-written summary Google places above the results. It answers the question on the page itself, so fewer people click through to any website. It cites a handful of sources — being one of them is the goal.

**answer similarity** — How much the top results reuse the same wording. It compares words, not meaning, so pages that make the same point in different words score as less similar than they really are. Read it as a floor.

**backdoor strategy** — Where a keyword has mixed intent, deliberately writing for the less-served side of the blend. You avoid the crowded fight and still appear on the same page.

**cited-share** — The share of your keywords where the AI Overview quotes your site as one of its sources. Zero means the AI is answering your topic without crediting you.

**commodity score** — A 0–100 estimate of how easily one AI paragraph could replace the entire results page for this search. High means everyone is saying the same thing, so a generic page is worth little — say something the others do not.

**content type** — What kind of page is ranking — a guide, a news item, a service page. It tells you what format to write in. If guides dominate, a service page will struggle however good it is.

**CTR** — Click-through rate — of everyone who sees your listing, the percentage who click it. "Estimated CTR loss" is a modelled guess at the clicks the AI Overview is absorbing, not a measurement of your actual traffic.

**DA gap** — Your Domain Authority minus the average of the sites currently ranking. A negative gap means you are stronger than the page you would be competing with, so ranking is realistic. A positive gap means they are stronger.

**Domain Authority** — A 0–100 third-party score estimating how much ranking strength a whole website has, based largely on who links to it. Moz's invention, not Google's, so treat it as a rough comparison between sites rather than a fact about your site.

**entity dominance** — What kinds of organisation own the results — private practices, directories, government, nonprofits. It tells you who you are actually up against, which is often a directory rather than a competing counsellor.

**extraction play** — The verdict that ranking is unrealistic but being quoted is not. You format the page so an AI can lift a clean answer out of it — question headings, the answer immediately underneath. Success is measured in citations, not position.

**FAQPage markup** — Invisible labelling in the page's code that tells machines "this is a question, and this is its answer". It does not change what a human reads; it makes the question-and-answer structure unambiguous to Google and to AI engines.

**Featured Snippet** — The boxed answer Google lifts out of one page and shows above the results. Won by answering a question directly and early on the page.

**GEO** — Generative Engine Optimisation — writing so AI answer engines can quote you, as opposed to writing to climb the ordinary rankings. The two overlap but the scoreboard is different.

**Knowledge Panel** — The information box about a person, place or organisation, usually on the right. Google builds it from what it already believes about that entity.

**Local Map Pack** — The map with roughly three business listings pinned to it, near the top of the page. It appears when Google thinks the searcher wants a nearby business. It takes a large share of the clicks, and you get into it through your Google Business Profile, not through your website.

**local pack presence** — Whether the map-and-listings box appeared for this search. When it does, the ordinary results start lower down the page and get fewer clicks.

**mixed intent** — Google is showing a blend of result types because it is unsure what searchers want. It usually means two different pages could both rank, which is an opening.

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
| `Entity_Type` | Organic_Results | What kind of organisation owns the page — counselling practice, directory, government, nonprofit, publisher. "N/A" means the classifier could not tell, not that the page has no owner. |
| `Content_Type` | Organic_Results | What kind of page it is — guide, news, service page. "other" is the classifier's unknown bucket, not a format you can write. |
| `FAQ_Present / Schema_Types` | Organic_Results | Whether the page carries machine-readable question-and-answer labelling, and which schema.org types it declares. Pages with FAQ markup are easier for AI answer engines to quote. |
| `Question_Heading_Count / Question_Headings` | Organic_Results | How many of the page's headings are phrased as questions, and what they are. A high count on competitors is a sign the topic rewards answer-first format. |
| `Credential_Hits / Author_Present / Review_Marker_Present` | Organic_Results | Trust signals found on the page — professional credentials named, a bylined author, visible reviews. These are the E-E-A-T markers Google associates with expertise. |
| `Intro_Text_Length` | Organic_Results | Characters of prose before the page's first substantive heading. A large number means the answer is buried, which makes the page hard to quote. |
| `client_da` | Keyword_Feasibility | Your site's Domain Authority — a 0-100 third-party estimate of ranking strength, based largely on who links to you. |
| `avg_serp_da` | Keyword_Feasibility | The average Domain Authority of the sites currently ranking for this keyword. This is what you are being compared against. |
| `gap` | Keyword_Feasibility | avg_serp_da minus client_da. Negative means you are the stronger site and ranking is realistic. Positive means they are stronger. Within about two points, treat it as level — the underlying score is an estimate. |
| `feasibility_score / feasibility_status` | Keyword_Feasibility | The gap turned into a normalised score and a High / Moderate / Low verdict. "Not Measured" means Domain Authority could not be fetched, which is different from a low score. |
| `pivot_status / suggested_keyword / all_variants` | Keyword_Feasibility | Whether the tool suggests targeting a narrower neighbourhood-level keyword instead, which one, and every variant it considered. Only generated for service-type keywords. |
| `Client_In_Local_Pack` | Keyword_Feasibility | Whether your business appeared in the map box. Blank means the check could not be run — not that you were absent. |
| `Type / Phrase / Count` | SERP_Language_Patterns | Repeated two- and three-word phrases from the SERP text, with how often each appeared. Stop words are stripped before counting here, so phrases read oddly ("family origin"). The readable version is in the Markdown report, Section 3. |
| `Has_Main_AI_Overview / Has_PAA_AI_Overview` | Overview | Whether Google showed an AI-written summary at the top of the page, and whether one appeared inside the People Also Ask box. |
| `AI_Sentiment / AI_Subjectivity / AI_Reading_Level` | Overview | Automated readings of the AI Overview's tone, opinion level and reading difficulty. Indicative only — useful for comparing runs, not as absolute measures. |
