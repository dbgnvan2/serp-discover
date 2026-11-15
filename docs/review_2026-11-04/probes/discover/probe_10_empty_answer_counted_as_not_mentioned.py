"""D-C-11 probe: an engine that returns HTTP 200 with NO answer (Gemini
safety block -> empty `candidates`; OpenAI `status: incomplete` with no
message item) yields answer_text "" and no exception, so run_engine_probes
records a row with mentioned=False / cited=False.  A blocked or empty answer
is persisted and reported as a measured 'not mentioned'."""
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

class P:  # probe returning the empty answer
    def ask(self, q): return {"answer_text": "", "source_urls": [], "model_id": "m"}
rows = pav.run_engine_probes({"gemini": P()}, [{"query": "q", "source": "paa", "persona": None}],
                             "", ["Living Systems"], "livingsystems.ca", [], "2026-11-04T00:00:00+00:00")
print("row recorded:", {k: rows[0][k] for k in ("engine", "mentioned", "cited", "answer_excerpt")})
