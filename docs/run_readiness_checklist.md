# Run readiness checklist

What must be in place for a run in which nothing is missing or skipped
because of configuration. Verified against this machine on 2026-11-19 at
v1.5.0; re-check the boxes rather than trusting this list, because the
reasons change.

Every item below is a **configuration** gap, not a defect. The tool states
absence honestly in all of these cases — it prints "not measured" rather
than a zero — so a run with boxes unticked produces an honest report with
holes in it, not a wrong one.

---

## A. Credentials (`.env`)

| | Variable | State on 2026-11-19 | What is missing from a run without it |
|---|---|---|---|
| ☑ | `SERPAPI_KEY` | present | nothing — SERP fetching works |
| ☑ | `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | present since 2026-11-21; answered 72 of 72 URLs that day | nothing — Domain Authority, the feasibility score and the DA-gap ranking all work. The primary pay-per-use provider |
| ☐ | `MOZ_TOKEN` | present, **rows spent** (2026-11-21: 750 allotted, 769 used) | the fallback DA provider and all keyword demand (monthly volume). Authenticates fine; returns HTTP 403 `insufficient-quota` until the period resets |
| ☑ | `ANTHROPIC_API_KEY` | exported in the shell, and in the key registry | nothing — the Claude engine runs |
| ☑ | `OPENAI_API_KEY` | not in `.env`; filled from the key registry | nothing — the ChatGPT engine runs |
| ☑ | `GEMINI_API_KEY` | not in `.env`; filled from the key registry | nothing — the Gemini engine runs |
| ☐ | `PERPLEXITY_API_KEY` | **absent everywhere** | the Perplexity engine. The registry holds no Perplexity key, so this one needs `.env` |
| ☐ | `GSC_CREDENTIALS_PATH` | absent | `run_gsc_analysis.py` entirely — real clicks, the CTR gap, the reformat shortlist |

Three of the four AI-visibility engines now run. The probe reads the shared
key registry (`~/.config/llm/keys.json`) for any key the environment does not
carry, mapped per engine by `ai_visibility.key_registry_providers` in
`config.yml`. The environment still wins, so a key placed in `.env` for this
tool is never overridden.

**Two corrections to what an earlier reading of this file said.**
`ANTHROPIC_API_KEY` is not in `.env`, but it is exported in the shell
environment — so the Claude engine was working all along when the tool was
run from a terminal, and is now also covered from the registry when it is
not (a GUI launched from Finder, or a scheduled run, inherits no shell
export). And the registry's key for a provider is only usable if it
authenticates against the engine's own endpoint; all eleven providers in the
registry pass a connection test as of 2026-11-19.

## B. `config.yml` switches

| | Key | State | Effect |
|---|---|---|---|
| ☐ | `gsc.enabled` | `false` | GSC is off by config as well as by credentials — both must change |
| ☐ | `gsc.feed_strategic_flags` | `false` | GSC findings do not reach the strategic sections even once GSC runs |
| ☐ | `feasibility.client_da` | `35` | measure it, do not inherit it. Every DA gap in the report is relative to this number |
| ☐ | `thresholds_provenance` | partly blank | any family left blank prints as "editorial, uncalibrated" in report §A, which is honest but tells the reader the band was nobody's measurement |
| ☐ | `enrichment.enable_domain_age` | `false` | optional signal, off by choice |

## C. Model IDs rot — verify before each run

Checked 2026-11-19: `report_llm.main_model` (`gemini-4-hydrogen`) **is** live.
`ai_visibility.claude_model` (`claude-sonnet-4-6`), `openai_model` (`gpt-4o`)
and `gemini_model` (`gemini-2.5-flash`) are unverified here because those
engines have no keys. A retired ID returns 404 at call time.

```bash
cd ~/ProjectsLocal/serp-discover && source venv/bin/activate && PYTHONPATH=~/ProjectsLocal/global-api-config python3 -c "import llm_providers as lp; print('\n'.join(lp.list_models(lp.get_provider('gemini-serp'))))"
```

Names come back prefixed `models/` — compare on the part after the slash.

## D. Steps `run_pipeline.py` does NOT run

The pipeline is steps 1.1–1.4 only: fetch, validate, verify enrichment,
domain-override candidates. A complete run means running these too, in
order:

| | Step | Script | Note |
|---|---|---|---|
| ☐ | Feasibility | `run_feasibility.py` | GUI step 7. Cached, so free to re-run. Needs §A's DA provider |
| ☐ | Domain override review | GUI step 6 | new hosts appear every run; unreviewed hosts classify as `N/A` and drop out of the intent verdict |
| ☐ | Content brief | `generate_content_brief.py` | GUI step 3. Run after feasibility, so the brief can speak about the DA gap |
| ☐ | AI visibility | `probe_ai_visibility.py` | three of four engines run; Perplexity is skipped and reported as not measured |
| ☐ | GSC analysis | `run_gsc_analysis.py` | needs §A and §B |
| ☐ | Tool 2 | `serp-compete` on the `competitor_handoff_*.json` | the handoff is written by the run; Tool 2 is a separate invocation |

## E. Ceilings no configuration removes

- **Roughly half of all organic URLs are unreadable.** Google serves them as
  encrypted `google.com/goto?url=…` links and SerpAPI passes them through
  verbatim — 52 of 100 on the 2026-11-19 verdict window. Those pages cannot
  be fetched or classified from their own content. Host inference covers the
  known ones; small independent sites stay unclassified. Three recovery
  routes were tested and all are dead.
- **Google no longer publishes its result-count estimate.** `Total_Results`
  comes back as the fetched page's own count, so no keyword gets a market-size
  figure. The tool withholds it rather than quoting a page size.
- **A keyword can be unmeasurable rather than unmeasured.** `family dynamics`
  ranks six unrecognised small hosts and gets no verdict; that is the ceiling
  above, not a missing credential.
