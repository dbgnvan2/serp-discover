"""D-M-25 probe (FLIPPED by chunk D3b): a sentiment classification that FAILED
carries no verdict.

`classify_answer` catches every exception and returns
`{"polarity": "neutral", ...}`; `_parse_classification` does the same for an
unparseable response. `percent_positive` then divides by the count of those
rows, so three rate-limited calls become three measured "neutral" answers and
a 0.0 Sentiment axis — a real finding that the AI portrays the client neutrally,
built entirely out of calls that never answered.

After: polarity None, status "failed" with the reason, excluded from
percent_positive and from the Sentiment axis, and the report says "n classified
of m attempted".
"""
import os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
import answer_sentiment as asent


def raises(*a, **k):
    raise RuntimeError("429 rate limited")


def garbage(*a, **k):
    return "I'm sorry, I can't help with that."


rows = []
for runner, label in ((raises, "raised"), (garbage, "unparseable")):
    result = asent.classify_answer("Living Systems Counselling is listed.",
                                   "Living Systems", "m", llm_runner=runner)
    print(f"{label}: {result}")
    rows.append({"engine": "gemini", "brand": "Living Systems",
                 "polarity": result["polarity"],
                 "positive_aspects": result["positive_aspects"],
                 "negative_aspects": result["negative_aspects"],
                 "status": result.get("status", asent.STATUS_CLASSIFIED),
                 "failure_reason": result.get("failure_reason")})

pct = asent.percent_positive(rows, "Living Systems")
print("percent_positive over 2 failed calls:", pct)
assert all(r["polarity"] is None for r in rows), rows
assert all(r["status"] == asent.STATUS_FAILED for r in rows)
assert all(r["failure_reason"] for r in rows)
assert asent.classified_rows(rows) == []
assert pct is None, "every classification failed => not measured, not 0%"

# One real verdict alongside the two failures: the percentage is over the
# verdict, and the report says what it is over.
rows.append({"brand": "Living Systems", "polarity": "positive",
             "positive_aspects": ["warm and professional"], "negative_aspects": [],
             "status": asent.STATUS_CLASSIFIED, "failure_reason": None,
             "engine": "gemini"})
print("percent_positive with 1 of 3 classified:",
      asent.percent_positive(rows, "Living Systems"))
assert asent.percent_positive(rows, "Living Systems") == 100.0
rendered = "\n".join(asent.render_sentiment_section(
    rows, True, "Living Systems", None))
print(rendered)
assert "1 classified of 3 attempted" in rendered

print("\nOK — a call that never answered carries no opinion, and the "
      "percentage states what it is over.")
