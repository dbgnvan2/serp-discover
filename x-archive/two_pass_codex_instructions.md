# Task: Add Strategic Flags (Pass 1) and Advisory Briefing (Pass 2)

## Context

`generate_content_brief.py` currently produces a market intelligence
report — either via LLM or via a local heuristic. The report is
factually accurate but reads as data description rather than strategic
advice. Users have to figure out "why this matters" themselves.

This task adds two things:

1. **Strategic flags** — deterministic computations added to the
   extraction output that encode prioritization logic the LLM
   should not have to figure out (e.g., "your only visible page is
   declining, fix it before creating new content").

2. **Advisory briefing** — a second LLM pass that takes the verified
   report from pass 1 and produces a short, actionable strategic
   interpretation aimed at a nonprofit executive director.

## Files to Modify

- `generate_content_brief.py` — extraction code, CLI args, and
  orchestration
- `serp_analysis_prompt_v3.md` — add a new section for the pass-2
  prompt (or create a separate file)

## Test Data

- `market_analysis_v2.json`
- `config.yml`
- Client domain: `livingsystems.ca`
- Client name patterns: `['Living Systems']`

---

## Part 1: Add `strategic_flags` to Extraction Output

### Where to Add

In `extract_analysis_data_from_json()` (starts at line 192), add a
new computation block before the final `return` statement (line 703).
The strategic flags use data already computed in the function — they
don't need new data sources.

### What to Compute

Add a function `_compute_strategic_flags()` that takes the already-
computed data structures and returns a flags dict. Then add
`"strategic_flags": strategic_flags` to the return dict.

```python
def _compute_strategic_flags(
    root_keywords,
    keyword_profiles,
    client_position,
    total_results_by_kw,
    paa_analysis,
):
    """
    Compute deterministic strategic prioritization flags.
    These encode business logic that the LLM should not guess at.
    """
    flags = {}

    # ── Defensive urgency ──
    # If any client position is declining, this takes priority
    # over new content creation.
    client_organic = client_position.get("organic", [])
    summary = client_position.get("summary", {})
    declining = [
        item for item in client_organic
        if item.get("stability") == "declining"
    ]
    visible_kws = summary.get("keywords_with_any_visibility", [])
    zero_kws = summary.get("keywords_with_zero_visibility", [])

    if declining:
        worst = min(declining, key=lambda x: x.get("rank_delta") or 0)
        flags["defensive_urgency"] = "high"
        flags["defensive_detail"] = (
            f"Client's content '{worst.get('title', 'unknown')}' "
            f"dropped {abs(worst.get('rank_delta', 0))} positions "
            f"to rank #{worst.get('rank', '?')} for "
            f"'{worst.get('source_keyword', 'unknown')}'. "
            f"This page provides "
            f"{summary.get('total_aio_citations', 0)} of the "
            f"client's AIO citations. If organic rank continues "
            f"declining, AIO citation loss is probable."
        )
    elif client_organic:
        # Client has positions but none declining
        flags["defensive_urgency"] = "low"
        flags["defensive_detail"] = (
            "All client positions are stable or improving."
        )
    else:
        flags["defensive_urgency"] = "none"
        flags["defensive_detail"] = (
            "Client has no organic positions to defend."
        )

    # ── Visibility concentration ──
    # How dependent is the client on a single keyword?
    total_kws = len(root_keywords)
    visible_count = len(visible_kws)
    if visible_count == 0:
        flags["visibility_concentration"] = "absent"
        flags["concentration_detail"] = (
            f"Client has zero visibility across all "
            f"{total_kws} tracked keywords."
        )
    elif visible_count == 1:
        flags["visibility_concentration"] = "critical"
        flags["concentration_detail"] = (
            f"Client visible for 1 of {total_kws} tracked keywords "
            f"('{visible_kws[0]}'). 100% of organic and AIO "
            f"visibility depends on a single keyword cluster."
        )
    elif visible_count <= total_kws * 0.3:
        flags["visibility_concentration"] = "high"
        flags["concentration_detail"] = (
            f"Client visible for {visible_count} of {total_kws} "
            f"tracked keywords."
        )
    else:
        flags["visibility_concentration"] = "distributed"
        flags["concentration_detail"] = (
            f"Client visible for {visible_count} of {total_kws} "
            f"tracked keywords."
        )

    # ── Per-keyword opportunity assessment ──
    # Classifies each keyword as defend / enter / skip
    opportunity_scale = {}
    for kw in root_keywords:
        profile = keyword_profiles.get(kw, {})
        total_results = profile.get("total_results", 0)
        client_rank = profile.get("client_rank")
        client_delta = profile.get("client_rank_delta")
        client_visible = profile.get("client_visible", False)
        entity_dominant = profile.get("entity_dominant_type")

        # Determine action
        if client_visible and client_delta is not None and client_delta < 0:
            action = "defend"
            reason = (
                f"Client ranks #{client_rank}, declined "
                f"{abs(client_delta)} positions. Protect existing "
                f"visibility before expanding elsewhere."
            )
        elif client_visible:
            action = "strengthen"
            reason = (
                f"Client ranks #{client_rank}. Position is "
                f"{'stable' if client_delta == 0 else 'new (no history)' if client_delta is None else 'improving'}. "
                f"Expand content depth to improve rank."
            )
        elif total_results < 200:
            action = "skip"
            reason = (
                f"Only {total_results} total results. Market too "
                f"small to justify dedicated content investment."
            )
        elif entity_dominant == "legal":
            action = "enter_cautiously"
            reason = (
                f"Legal entities dominate this SERP. Entry requires "
                f"differentiated content that avoids competing on "
                f"legal topics directly."
            )
        else:
            action = "enter"
            reason = (
                f"{total_results:,} total results. Client has no "
                f"current visibility. "
                f"Dominant entity type: {entity_dominant or 'mixed'}."
            )

        opportunity_scale[kw] = {
            "total_results": total_results,
            "client_rank": client_rank,
            "client_trend": (
                "declining" if client_delta is not None and client_delta < 0
                else "improving" if client_delta is not None and client_delta > 0
                else "stable" if client_delta == 0
                else "new" if client_visible
                else None
            ),
            "action": action,
            "reason": reason,
        }

    flags["opportunity_scale"] = opportunity_scale

    # ── Ordered content priorities ──
    # Defend first, then strengthen, then enter, then skip.
    priority_order = {"defend": 0, "strengthen": 1, "enter": 2, "enter_cautiously": 3, "skip": 4}
    priorities = []
    for kw in root_keywords:
        opp = opportunity_scale[kw]
        priorities.append({
            "action": opp["action"],
            "keyword": kw,
            "total_results": opp["total_results"],
            "reason": opp["reason"],
        })

    priorities.sort(key=lambda x: (
        priority_order.get(x["action"], 99),
        -x["total_results"],
    ))
    flags["content_priorities"] = priorities

    # ── Cross-cluster PAA value ──
    # Flag the highest-value cross-cluster questions by combined volume
    cross = paa_analysis.get("cross_cluster", [])
    if cross:
        top_cross = cross[0]
        flags["top_cross_cluster_paa"] = {
            "question": top_cross["question"],
            "cluster_count": top_cross["cluster_count"],
            "combined_total_results": top_cross["combined_total_results"],
        }
    else:
        flags["top_cross_cluster_paa"] = None

    return flags
```

### Integration

Call this function after all existing computations and before the
return statement:

```python
    strategic_flags = _compute_strategic_flags(
        root_keywords=root_keywords,
        keyword_profiles=keyword_profiles,
        client_position=client_position,
        total_results_by_kw=total_results_by_kw,
        paa_analysis=paa_analysis,
    )

    return {
        "metadata": metadata,
        # ... all existing keys ...
        "competitor_ads": ads_out,
        "strategic_flags": strategic_flags,  # NEW
    }
```

### Verification

```python
sf = extracted['strategic_flags']
assert sf['defensive_urgency'] == 'high', f"Expected high, got {sf['defensive_urgency']}"
assert sf['visibility_concentration'] == 'critical'
assert sf['content_priorities'][0]['action'] == 'defend'
assert sf['content_priorities'][0]['keyword'] == 'family cutoff counselling Vancouver'
assert sf['opportunity_scale']['reunification counselling BC']['action'] == 'skip'
print("Strategic flags verified.")
print(f"Priority order: {[(p['action'], p['keyword']) for p in sf['content_priorities']]}")
```

Expected output:
```
Strategic flags verified.
Priority order: [
  ('defend', 'family cutoff counselling Vancouver'),
  ('enter_cautiously', 'estrangement'),
  ('enter', 'estrangement grief'),
  ('enter', 'estrangement from adult children'),
  ('enter', 'reunification therapy near me'),
  ('skip', 'reunification counselling BC'),
]
```

The exact order of the "enter" keywords may vary by total_results
tiebreaking — that's fine. What matters is "defend" comes first
and "skip" comes last.

---

## Part 2: Add Advisory Briefing (Second LLM Pass)

### New CLI Arguments

Add these arguments to the argument parser:

```python
parser.add_argument(
    "--advisory-briefing", action="store_true",
    help="Run a second LLM pass to produce a strategic advisory briefing"
)
parser.add_argument(
    "--advisory-out", default="advisory_briefing.md",
    help="Output path for the advisory briefing"
)
parser.add_argument(
    "--advisory-model", default=None,
    help="Model for advisory pass (defaults to --llm-model)"
)
```

### Advisory Briefing System Prompt

Store this as a constant in the script (or in the prompt spec
markdown under a new `### Advisory System Prompt` heading, following
the same extraction pattern as the existing system/user prompts).

```python
ADVISORY_SYSTEM_PROMPT = """You are a senior SEO and content strategy advisor briefing the
executive director of a small nonprofit counselling organization.
Your job is to explain what market intelligence data means for their
organization — not to describe data, but to recommend specific actions
and explain consequences.

## How to communicate

Write as if you are sitting across a table from someone who
understands their clinical work deeply but relies on you for digital
strategy. Be direct. Use plain language. When you reference a number,
state it once and then explain what it means — do not list data points
without interpretation.

For every finding, follow this structure:
- What the data shows (one sentence)
- Why this matters to you specifically (one to two sentences
  connecting the finding to their business situation)
- What to do about it (concrete action)
- What happens if you don't (consequence of inaction)

## Rules

- Do not repeat or summarize the market intelligence report. The
  reader has already seen it. Reference findings by topic, not by
  restating them.
- Do not describe data without interpreting it.
- Do not recommend more than 3 actions. A small nonprofit cannot
  execute more than 3 content initiatives in a quarter.
- If the strategic flags show defensive_urgency as "high", the first
  action MUST be defending the declining position. Do not recommend
  creating new content ahead of stabilizing existing visibility.
- If the strategic flags show a keyword with action "skip", do not
  recommend content for it regardless of how interesting the topic
  seems.
- Do not soften bad news. If the client's position is deteriorating,
  say so plainly.
- Do not fabricate data. Every number you cite must appear in either
  the strategic flags or the market intelligence report.

## Output structure

### The Headline
One paragraph. State the single most important thing the client needs
to understand from this analysis. Lead with the most urgent finding,
not the most interesting one.

### Action 1 (highest urgency)
Two to three paragraphs. What to do, specifically. Why this is
urgent (reference the data). What happens if the client does nothing.
Include the specific page or content asset involved if one exists.

### Action 2
Same structure.

### Action 3
Same structure.

### What to Stop Thinking About
One paragraph. Name the specific keywords, content ideas, or
strategies that the data does NOT support. Explain briefly why. This
prevents the client from spending time on low-value activities.

### Next Measurement
One paragraph. What specific metrics to check in the next data run
(e.g., "rank for keyword X should be at or above Y") to assess
whether these actions worked. Be specific enough that the result is
unambiguous.
"""
```

### Advisory Briefing User Prompt Template

```python
ADVISORY_USER_TEMPLATE = """## Client Context

Organization: {client_name}
Website: {client_domain}
Type: {org_type}
Location: {location}
Theoretical framework: {framework_description}
Current content focus: {content_focus}
Additional context: {additional_context}

## Strategic Flags (pre-computed from SERP data)

<strategic_flags>
{strategic_flags_json}
</strategic_flags>

## Market Intelligence Report (verified, from first-pass analysis)

<market_report>
{market_report_text}
</market_report>

Based on the strategic flags and the verified market intelligence
report, produce the advisory briefing as specified in your
instructions.
"""
```

### Orchestration

In `list_recommendations()`, after the first-pass report is written
to disk, add the advisory briefing pass:

```python
    # After the existing report write (line ~1131):
    with open(args.report_out, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    # NEW: Advisory briefing second pass
    if args.advisory_briefing:
        if not args.use_llm:
            print("Warning: --advisory-briefing requires --use-llm. Skipping.")
        elif not ANTHROPIC_AVAILABLE or not os.getenv("ANTHROPIC_API_KEY"):
            print("Error: Advisory briefing requires anthropic package and API key.")
            sys.exit(2)
        else:
            progress("[advisory] Running second-pass strategic briefing...")
            advisory_model = args.advisory_model or args.llm_model

            advisory_user = ADVISORY_USER_TEMPLATE.format(
                client_name=context["client_name"],
                client_domain=context["client_domain"],
                org_type=context["org_type"],
                location=context["location"],
                framework_description=context["framework_description"],
                content_focus=context["content_focus"],
                additional_context=context["additional_context"],
                strategic_flags_json=json.dumps(
                    extracted["strategic_flags"],
                    indent=2,
                    default=str,
                ),
                market_report_text=report,
            )

            advisory_report = run_llm_report(
                system_prompt=ADVISORY_SYSTEM_PROMPT,
                user_prompt=advisory_user,
                model=advisory_model,
                max_tokens=4000,
            )

            with open(args.advisory_out, "w", encoding="utf-8") as f:
                f.write(advisory_report + "\n")

            progress(f"[done] Advisory briefing written to {args.advisory_out}")
```

### Usage

```bash
# Full pipeline: extraction + LLM report + advisory briefing
python generate_content_brief.py \
    --json market_analysis_v2.json \
    --list \
    --use-llm \
    --advisory-briefing \
    --config config.yml \
    --report-out content_opportunities_report.md \
    --advisory-out advisory_briefing.md
```

Or to run the advisory pass with a different model:

```bash
python generate_content_brief.py \
    --json market_analysis_v2.json \
    --list \
    --use-llm \
    --llm-model claude-sonnet-4-20250514 \
    --advisory-briefing \
    --advisory-model claude-opus-4-20250514 \
    --config config.yml
```

---

## Part 3: Update the First-Pass System Prompt

The first-pass system prompt in `serp_analysis_prompt_v3.md` should
be updated to reference the new `strategic_flags` key in its data
dictionary. Add this entry:

```
STRATEGIC FLAGS (pre-computed prioritization):
- strategic_flags.defensive_urgency: "high", "low", or "none".
  "high" means at least one client position is declining.
- strategic_flags.defensive_detail: plain-language explanation of
  what is declining and why it matters.
- strategic_flags.visibility_concentration: "critical" (1 keyword),
  "high" (few keywords), "distributed", or "absent" (zero visibility).
- strategic_flags.concentration_detail: plain-language summary.
- strategic_flags.opportunity_scale: per-keyword dict with action
  ("defend", "strengthen", "enter", "enter_cautiously", "skip"),
  total_results, client_rank, client_trend, and reason.
- strategic_flags.content_priorities: keywords ordered by action
  urgency (defend first, skip last).
- strategic_flags.top_cross_cluster_paa: the highest-value
  cross-cluster PAA question with its cluster count and volume.
```

Also add to the Section 7 (Prioritized Content Recommendations)
description:

```
Follow the priority order in strategic_flags.content_priorities.
"defend" actions must come before "enter" actions. "skip" keywords
must not receive content recommendations. State the action type
and reason from the flags for each recommendation.
```

---

## Verification

### Strategic Flags

```python
extracted = extract_analysis_data_from_json(data, ...)
sf = extracted['strategic_flags']

# Defensive urgency
assert sf['defensive_urgency'] == 'high'
assert '-5' in sf['defensive_detail'] or '5 positions' in sf['defensive_detail']

# Concentration
assert sf['visibility_concentration'] == 'critical'
assert 'family cutoff counselling Vancouver' in sf['concentration_detail']

# Priority ordering
actions = [p['action'] for p in sf['content_priorities']]
assert actions[0] == 'defend', f"First priority should be defend, got {actions[0]}"
assert actions[-1] == 'skip', f"Last priority should be skip, got {actions[-1]}"

# Skip threshold
assert sf['opportunity_scale']['reunification counselling BC']['action'] == 'skip'

# Legal caution
assert sf['opportunity_scale']['estrangement']['action'] == 'enter_cautiously'

print("All strategic flag assertions passed.")
```

### Advisory Briefing Pipeline

Run the full command and verify:

1. `content_opportunities_report.md` is generated (pass 1)
2. `advisory_briefing.md` is generated (pass 2)
3. The advisory briefing's first action relates to defending the
   declining "family cutoff counselling Vancouver" position
4. The advisory briefing does not recommend content for
   "reunification counselling BC"
5. The advisory briefing cites specific numbers from the report
   (rank #9, -5 delta, 108 AIO citations, etc.)
6. The advisory briefing contains exactly 3 actions, not more

### Token Budget for Pass 2

| Component | Approximate Size |
|---|---|
| Advisory system prompt | ~2,000 chars |
| Strategic flags JSON | ~3,000 chars |
| Pass-1 report | ~8,000-15,000 chars |
| Client context | ~1,000 chars |
| **Total input** | **~14,000-21,000 chars (~5,000-7,000 tokens)** |
| Output | ~3,000 chars (~1,000-1,500 tokens) |

This is a small, cheap API call. At Sonnet pricing it's roughly
$0.02 per run.
