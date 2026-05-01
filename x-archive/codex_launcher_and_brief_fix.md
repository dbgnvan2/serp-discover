# Task: Keyword File Management UI and Brief Template Fix

## Two independent changes in this task:

1. **Launcher UI**: Replace single keyword input with keyword file
   management — select existing files, add new keywords, auto-name
   files from first keyword, auto-name output files to match.

2. **Brief generator fix**: The content briefs appended to
   `market_analysis_v2.md` assign identical PAA questions and
   competitors to 3 of 4 briefs because the trigger-matching
   fallback dumps the first 5 PAA questions from the entire dataset
   regardless of relevance.

---

## Change 1: Keyword File Management

### Current Behavior

The launcher has a single text input for one keyword. The config.yml
points to a hardcoded `keywords.csv`. Each run overwrites the
previous output files.

### Desired Behavior

The launcher provides two inputs:

**A) Keyword file selector (dropdown)**
- Scans the working directory for files matching `keywords_*.csv`
- Shows them sorted by most recently modified (newest first)
- Each entry shows the filename and keyword count, e.g.:
  `keywords_estrangement.csv (6 keywords)`
- Includes an empty/none option for when creating a new file

**B) New keywords input (text field)**
- Label: "New Keywords (comma separated)"
- Accepts multiple keywords separated by commas
- Replaces the current single-keyword input

### Logic When Run Is Triggered

**Case 1: Existing file selected, no new keywords entered**
- Use the selected file as-is. This is the standard monthly re-run.
- Set `config.files.input_csv` to the selected file path.

**Case 2: No file selected, new keywords entered**
- Parse the comma-separated input into individual keywords (trim
  whitespace from each).
- Generate filename from the first keyword:
  - Lowercase
  - Replace spaces with underscores
  - Strip characters that aren't alphanumeric or underscore
  - Prefix with `keywords_`, suffix with `.csv`
  - Example: "estrangement grief, family cutoff counselling Vancouver"
    → `keywords_estrangement_grief.csv`
- Write the keywords to this new CSV file (one keyword per line,
  matching the existing CSV format your tool expects).
- Set `config.files.input_csv` to the new file path.

**Case 3: Existing file selected AND new keywords entered**
- Load the existing file's keywords.
- Parse the new comma-separated keywords.
- Merge them, deduplicating (case-insensitive comparison, preserve
  the casing of the first occurrence).
- Write the merged list back to the same file.
- Set `config.files.input_csv` to the existing file path.
- Log which keywords were added: "Added 2 new keywords to
  keywords_estrangement.csv: 'family triangulation counselling',
  'emotional cutoff therapy BC'"

**Case 4: No file selected, no keywords entered**
- Error: "Please select an existing keyword file or enter new
  keywords."

### Output File Naming

When the keyword file is determined, derive the topic slug from the
filename:

```python
# keywords_estrangement_grief.csv → estrangement_grief
topic_slug = keyword_filename.replace("keywords_", "").replace(".csv", "")
```

Use this slug to name all output files:

```python
output_names = {
    "output_xlsx": f"market_analysis_{topic_slug}.xlsx",
    "output_json": f"market_analysis_{topic_slug}.json",
    "output_md": f"market_analysis_{topic_slug}.md",
    "report_out": f"content_opportunities_{topic_slug}.md",
    "advisory_out": f"advisory_briefing_{topic_slug}.md",
}
```

Override the corresponding config values before the SERP tool runs.

### Date-Stamped Archiving

Before writing new output files, check if previous versions exist.
If they do, move them to a `runs/` subdirectory with a date stamp:

```python
import shutil
from datetime import datetime

archive_dir = "runs"
os.makedirs(archive_dir, exist_ok=True)
date_stamp = datetime.now().strftime("%Y%m%d")

for output_file in output_names.values():
    if os.path.exists(output_file):
        base, ext = os.path.splitext(output_file)
        archived = os.path.join(archive_dir, f"{base}_{date_stamp}{ext}")
        # Don't overwrite an existing archive from the same day
        if not os.path.exists(archived):
            shutil.move(output_file, archived)
```

This preserves previous runs for cross-run comparison without
cluttering the working directory.

### CSV Format

Match whatever format your existing keyword CSV uses. Typically
this is one keyword per row with a header:

```csv
keyword
estrangement
estrangement from adult children
estrangement grief
family cutoff counselling Vancouver
reunification therapy near me
reunification counselling BC
```

Verify the existing CSV format and match it exactly.

### Dropdown Refresh

After a run completes (or after creating/updating a keyword file),
refresh the dropdown contents so the new or updated file appears
immediately.

---

## Change 2: Fix Content Brief PAA Assignment

### Problem

The content briefs appended to `market_analysis_v2.md` assign
identical PAA questions to multiple briefs. The root cause is a
two-part fallback failure:

**Part A: Trigger words don't match PAA question text.**
The brief generator searches PAA questions for trigger words like
"connection", "bond", "communication" (Fusion Trap) or "clinical",
"registered", "mental health" (Medical Model Trap). These words
describe the SERP competitive language, not the questions users ask.
Users ask "When should you stop reaching out to an estranged child?"
— none of those trigger words appear in this question. Result:
zero matches for 3 of 4 recommendations.

**Part B: The fallback dumps generic questions.**
When zero trigger matches are found, the code falls back to
`paa[:5]` — the first 5 PAA questions from the entire dataset,
in whatever order they appear. This produces identical PAA lists
for every brief that has zero trigger matches. Result: Briefs 1,
2, and 4 all show the same 5 estrangement questions, regardless
of whether the brief is about "fusion" or "blame/reactivity" or
"the medical model."

**Part C: Competitors are also identical.**
`organic[:3]` takes the first 3 organic results from the entire
dataset. These are the same for every brief.

### The Correct Behavior

Each brief should show PAA questions and competitors that are
relevant to that brief's strategic angle. Since the trigger words
are the wrong matching signal (they describe competitor language,
not user questions), the matching strategy needs to change.

### Fix

This fix applies to the code that generates the content briefs
in `market_analysis_v2.md`. Depending on your codebase, this may
be in the SERP tool's MD report generator, or in the legacy
`generate_brief()` function in `generate_content_brief.py` (line
1150), or both. Apply the fix wherever the brief generation lives.

**Step 1: Match PAA questions by semantic relevance, not trigger
words.**

Instead of searching PAA question text for trigger words, score
each PAA question against the recommendation's thematic intent.
The simplest approach that doesn't require an LLM:

```python
# Define thematic keywords per recommendation pattern.
# These are different from trigger words — they describe the
# TOPIC the recommendation addresses, not the competitive language.
BRIEF_PAA_THEMES = {
    "The Medical Model Trap": [
        "therapy", "therapist", "counselling", "counselor",
        "session", "diagnosis", "mental health", "treatment",
        "professional", "psychologist",
    ],
    "The Fusion Trap": [
        "reach out", "reconnect", "contact", "close",
        "relationship", "communicate", "talking",
        "stop reaching", "go no contact",
    ],
    "The Resource Trap": [
        "cost", "free", "afford", "pay", "price", "insurance",
        "covered", "sliding scale", "low cost", "how much",
    ],
    "The Blame/Reactivity Trap": [
        "toxic", "narcissist", "abusive", "signs", "fault",
        "blame", "anger", "deal with", "mean",
    ],
}
```

Score each PAA question against the theme list:

```python
def score_paa_for_brief(question_text, theme_words):
    """Score how relevant a PAA question is to a brief's theme."""
    q_lower = question_text.lower()
    return sum(1 for word in theme_words if word in q_lower)


def get_relevant_paa(paa_questions, pattern_name, max_results=5):
    """Return PAA questions ranked by relevance to the brief theme."""
    theme_words = BRIEF_PAA_THEMES.get(pattern_name, [])
    if not theme_words:
        return paa_questions[:max_results]

    scored = [
        (q, score_paa_for_brief(q.get("Question", ""), theme_words))
        for q in paa_questions
    ]
    # Sort by score descending, then by original order
    scored.sort(key=lambda x: -x[1])

    # Take questions with score > 0 first, then fill with
    # highest-distress unmatched questions if needed
    matched = [q for q, score in scored if score > 0][:max_results]

    if len(matched) < max_results:
        # Fill remaining slots with high-distress questions
        # that weren't already selected
        matched_texts = {q.get("Question") for q in matched}
        distress = [
            q for q in paa_questions
            if q.get("Category") in ("Distress", "Reactivity")
            and q.get("Question") not in matched_texts
        ]
        matched.extend(distress[:max_results - len(matched)])

    if len(matched) < max_results:
        # Still short — fill with remaining unselected questions
        matched_texts = {q.get("Question") for q in matched}
        remaining = [
            q for q in paa_questions
            if q.get("Question") not in matched_texts
        ]
        matched.extend(remaining[:max_results - len(matched)])

    return matched[:max_results]
```

Replace the current trigger-matching block:

```python
# OLD (lines ~1165-1175 in generate_content_brief.py):
relevant_paa = []
if triggers and triggers[0] != "N/A":
    for q in paa:
        q_text = str(q.get("Question", "")).lower()
        if any(t and t.lower() in q_text for t in triggers):
            relevant_paa.append(q.get("Question"))
if not relevant_paa:
    relevant_paa = [q.get("Question") for q in paa[:5]]
else:
    relevant_paa = relevant_paa[:5]

# NEW:
relevant_paa_records = get_relevant_paa(
    paa, rec.get("Pattern_Name"), max_results=5
)
relevant_paa = [q.get("Question") for q in relevant_paa_records]
```

**Step 2: Match competitors by keyword cluster, not global first-3.**

Instead of `organic[:3]`, select competitors relevant to the
recommendation's topic:

```python
def get_relevant_competitors(organic_results, pattern_name, max_results=3):
    """Return competitor titles relevant to the brief's theme."""
    theme_words = BRIEF_PAA_THEMES.get(pattern_name, [])
    seen_titles = set()
    scored = []
    for o in organic_results:
        title = o.get("Title", "")
        if title in seen_titles:
            continue
        seen_titles.add(title)
        title_lower = title.lower()
        snippet_lower = str(o.get("Snippet", "")).lower()
        combined = title_lower + " " + snippet_lower
        score = sum(1 for w in theme_words if w in combined)
        scored.append((title, score))

    scored.sort(key=lambda x: -x[1])
    # Take the highest-scoring, but if all zero, fall back to
    # top-ranked results (not random)
    top = [title for title, score in scored if score > 0][:max_results]
    if len(top) < max_results:
        remaining = [
            title for title, score in scored
            if title not in top
        ]
        top.extend(remaining[:max_results - len(top)])
    return top[:max_results]
```

Replace:
```python
# OLD:
top_competitors = [o.get("Title") for o in organic[:3]]

# NEW:
top_competitors = get_relevant_competitors(
    organic, rec.get("Pattern_Name"), max_results=3
)
```

**Step 3: Apply the same fix to the upstream MD brief generator.**

If the briefs in `market_analysis_v2.md` are generated by a
different code path (the SERP analysis tool rather than
`generate_content_brief.py`), apply the same `BRIEF_PAA_THEMES`
matching logic there. The pattern is the same: find where PAA
questions are selected for each brief, replace the trigger-word
matching with theme-based scoring, and replace the global
`organic[:3]` with theme-scored competitor selection.

Search the SERP tool codebase for:
- The fallback `paa[:5]` or similar pattern
- The `organic[:3]` competitor selection
- Any code that assigns PAA questions to briefs/recommendations

### Verification

After the fix, run the tool and check the output
`market_analysis_v2.md`:

1. Brief 1 (Medical Model Trap) should show PAA questions about
   therapy, sessions, therapists, or mental health — NOT the same
   5 generic estrangement questions as Brief 2.

2. Brief 2 (Fusion Trap) should show PAA questions about reaching
   out, contact, reconnection — questions about relationship
   dynamics.

3. Brief 3 (Resource Trap) should show PAA questions about cost,
   free counselling, insurance coverage.

4. Brief 4 (Blame/Reactivity Trap) should show PAA questions about
   toxic relationships, signs of dysfunction.

5. No two briefs should have identical PAA question lists unless the
   dataset genuinely has the same questions matching both themes.

6. The "Competition" section should show different competitor titles
   per brief, reflecting the thematic differences.

Specific check against current data: Brief 3 (Resource Trap) should
include "How to get free grief counselling?", "Is there free
counseling in BC?", "Can you get free counselling in BC?", and
"How to get therapy covered in BC?" — these are the PAA questions
that actually match the resource/cost theme. The current output
shows none of these because the trigger word "free" doesn't appear
in "When should you stop reaching out to an estranged child?"

---

## Testing Both Changes Together

After implementing both changes:

1. In the launcher, enter new keywords: "estrangement, estrangement
   from adult children, estrangement grief"
2. Verify file created: `keywords_estrangement.csv` with 3 keywords
3. Run the analysis
4. Verify output files are named:
   `market_analysis_estrangement.xlsx`,
   `market_analysis_estrangement.json`,
   `market_analysis_estrangement.md`,
   `content_opportunities_estrangement.md`
5. Open `market_analysis_estrangement.md` and verify the content
   briefs have differentiated PAA questions per brief
6. In the launcher dropdown, verify `keywords_estrangement.csv (3
   keywords)` now appears
7. Add new keywords: "family cutoff counselling Vancouver,
   reunification therapy near me"
8. Select the existing `keywords_estrangement.csv` AND enter the
   new keywords
9. Verify the file now contains 5 keywords (no duplicates)
10. Run again
11. Verify previous output files moved to `runs/` with date stamp
12. Verify new output files use the same `_estrangement` slug
