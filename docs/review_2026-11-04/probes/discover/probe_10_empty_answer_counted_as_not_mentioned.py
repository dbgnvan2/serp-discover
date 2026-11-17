"""D-C-11 probe (FLIPPED by chunk D3a): a call that produced no answer is a
failure, not an absence.

An engine can return HTTP 200 with NO answer (Gemini safety block -> empty
`candidates`; OpenAI `status: incomplete` with no message item): answer_text
"" and no exception. `run_engine_probes` used to record that as
mentioned=False / cited=False, so a blocked answer was persisted and reported
as a measured "the client was not mentioned". A raised call was worse — it was
dropped, so the question left the denominator too.

After: both are rows with status "failed", no verdict, and a per-engine
"answered N of M (K failed)" count.
"""
import os, sys
REPO = "/Users/davemini2/ProjectsLocal/serp-discover"
os.chdir(REPO); sys.path.insert(0, REPO)
from unittest.mock import patch, MagicMock
import probe_ai_visibility as pav

blocked = MagicMock(); blocked.ok = True; blocked.status_code = 200
blocked.json.return_value = {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
incomplete = MagicMock(); incomplete.ok = True; incomplete.status_code = 200
incomplete.json.return_value = {"status": "incomplete", "output": [], "model": "gpt-4o"}

with patch.dict(os.environ, {"GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k"}):
    g = pav.GeminiProbe("gemini-2.5-flash"); o = pav.ChatGPTProbe("gpt-4o")
with patch.object(pav, "post_with_transient_retry", return_value=blocked):
    print("Gemini blocked ->", g.ask("Who offers Bowen family therapy in North Vancouver?"))
with patch.object(pav, "post_with_transient_retry", return_value=incomplete):
    print("OpenAI incomplete ->", o.ask("..."))

class Empty:  # 200 OK with nothing in it
    def ask(self, q): return {"answer_text": "", "source_urls": [], "model_id": "m"}


class Raises:  # the network/quota failure
    def ask(self, q): raise RuntimeError("429 rate limited")


class Answers:
    def ask(self, q):
        return {"answer_text": "Living Systems Counselling is one option.",
                "source_urls": [], "model_id": "m"}


questions = [{"query": "q1", "source": "paa", "persona": "p"},
             {"query": "q2", "source": "paa", "persona": "p"}]
rows = pav.run_engine_probes(
    {"empty": Empty(), "raises": Raises(), "ok": Answers()}, questions,
    "", ["Living Systems"], "livingsystems.ca", [], "2026-11-04T00:00:00+00:00")
for row in rows:
    print(f"  {row['engine']}/{row['question']}: status={row['status']!r} "
          f"mentioned={row['mentioned']!r} reason={row['failure_reason']!r}")
counts = pav.engine_call_counts(rows, ["empty", "raises", "ok"], len(questions))
print("counts:", counts)

for engine in ("empty", "raises"):
    engine_rows = [r for r in rows if r["engine"] == engine]
    assert len(engine_rows) == 2, f"{engine}: a failed call must still be a row"
    assert all(r["status"] == pav.STATUS_FAILED for r in engine_rows)
    assert all(r["mentioned"] is None and r["cited"] is None for r in engine_rows), \
        f"{engine}: a failure carries no mention/cite verdict"
    assert pav.answered_rows(engine_rows) == []
    assert counts[engine] == {"planned": 2, "attempted": 2, "answered": 0, "failed": 2}
assert counts["ok"] == {"planned": 2, "attempted": 2, "answered": 2, "failed": 0}
assert all(r["mentioned"] for r in pav.answered_rows(
    [r for r in rows if r["engine"] == "ok"]))
print("\nOK — a call that produced no answer is recorded as failed, not as "
      "an answer in which the client was absent.")
