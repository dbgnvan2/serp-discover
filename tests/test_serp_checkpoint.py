"""Paid SerpAPI responses are kept as they arrive and reused by a resumed run.

Spec: docs/plan_checkpoint_resume_and_m3_2026-11-14.md (C1-C8)
"""

import json
import logging
import os

import pytest

import serp_audit
import serp_checkpoint as cp

KEY = "sk-secret-123"


class _FakeSearch:
    """Stands in for serpapi.GoogleSearch. ``fail`` holds queries that error."""
    calls = []
    fail = set()

    def __init__(self, params):
        self.params = params

    def get_dict(self):
        type(self).calls.append(self.params["q"])
        if self.params["q"] in self.fail:
            return {"error": "Google hasn't returned any results for this query."}
        return {"q": self.params["q"], "echo": f"key={self.params['api_key']}"}


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _FakeSearch.calls, _FakeSearch.fail = [], set()
    monkeypatch.setattr(serp_audit, "GoogleSearch", _FakeSearch)
    monkeypatch.setattr(serp_audit, "SERPAPI_AVAILABLE", True)
    monkeypatch.setattr(serp_audit, "SERPAPI_CALL_COUNT", 0)
    monkeypatch.setattr(serp_audit, "RETRY_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(serp_audit.time, "sleep", lambda s: None)
    monkeypatch.delenv(cp.RESUME_ENV, raising=False)
    return serp_audit


def _fetch(audit, queries, run_id, resume=None, config=None, code=0):
    """One tracked run that makes one call per query. Returns the responses."""
    out = []

    def run(_run_id):
        for q in queries:
            out.append(audit._fetch_serp_api({"engine": "google", "q": q, "api_key": KEY}))
        return code

    environ = {cp.RESUME_ENV: resume} if resume else {}
    exit_code = cp.tracked_run(run_id, "keywords_x.csv", config or {}, run, environ=environ)
    return out, exit_code


def _call_files(run_id):
    return sorted(os.listdir(os.path.join("raw", run_id, "calls")))


def _state(run_id):
    with open(os.path.join("raw", run_id, "run_state.json")) as f:
        return json.load(f)


def _age_calls(run_id, hours):
    folder = os.path.join("raw", run_id, "calls")
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        with open(path) as f:
            record = json.load(f)
        record["saved_at"] -= hours * 3600
        with open(path, "w") as f:
            json.dump(record, f)


def test_each_call_is_saved_under_its_own_name(audit):
    _fetch(audit, ["Family Therapy!", "family therapy", "couples"], "run1")
    names = _call_files("run1")
    assert len(names) == 3 and not [n for n in names if n.endswith(".tmp")]
    assert names[0].startswith("0001_google_family-therapy_")
    assert names[2].startswith("0003_google_couples_")
    with open(os.path.join("raw", "run1", "calls", names[2])) as f:
        assert json.load(f)["response"]["q"] == "couples"


def test_api_key_is_not_stored(audit):
    _fetch(audit, ["alpha"], "run1")           # the fake response echoes the key
    name = _call_files("run1")[0]
    with open(os.path.join("raw", "run1", "calls", name)) as f:
        text = f.read()
    assert KEY not in text and KEY not in name
    assert "api_key" not in json.loads(text)["params"]


def test_failed_call_is_not_checkpointed(audit):
    _FakeSearch.fail = {"beta"}
    responses, _ = _fetch(audit, ["alpha", "beta"], "run1")
    assert responses[1] is None
    assert len(_call_files("run1")) == 1


def test_resume_reuses_stored_calls_and_fetches_the_rest(audit, monkeypatch, capsys):
    _FakeSearch.fail = {"beta"}
    _fetch(audit, ["alpha", "beta"], "run1", code=1)
    _FakeSearch.calls, _FakeSearch.fail = [], set()
    monkeypatch.setattr(audit, "SERPAPI_CALL_COUNT", 0)

    seen = {}

    def run(_run_id):
        seen["responses"] = [
            audit._fetch_serp_api({"engine": "google", "q": q, "api_key": "another-key"})
            for q in ("alpha", "beta")]
        seen["summary"] = cp.summary()
        print(cp.calls_line(audit.SERPAPI_CALL_COUNT))
        return 0

    assert cp.tracked_run("run2", "keywords_x.csv", {}, run, environ={cp.RESUME_ENV: "run1"}) == 0

    assert _FakeSearch.calls == ["beta"]                 # alpha came from disk
    assert audit.SERPAPI_CALL_COUNT == 1
    assert seen["responses"][0]["q"] == "alpha"
    assert seen["summary"] == {"resumed_from": "run1", "reused_calls": 1}      # C5
    assert "Reused 1 stored responses; made 1 new SerpAPI calls" in capsys.readouterr().out
    assert len(_call_files("run2")) == 2                 # run2 can itself be resumed
    assert _state("run2")["reused_calls"] == 1


def test_run_with_failed_queries_exits_zero_but_stays_resumable(audit):
    def run(_run_id):
        audit._fetch_serp_api({"engine": "google", "q": "alpha", "api_key": KEY})
        cp.fetch_summary({"planned": 2, "fetched": 1, "failed": [{"query": "beta"}],
                          "pivot_failed": []})
        return 0                                   # outputs written, one query failed

    assert cp.tracked_run("partial", "keywords_x.csv", {}, run, environ={}) == 0
    assert _state("partial")["status"] == "incomplete"
    assert _state("partial")["failed_queries"] == 1
    assert cp.find_resumable_run("keywords_x.csv", 24)["run_id"] == "partial"


def _token_run(audit, run_id, steps, resume=None):
    """steps: list of params dicts (api_key added). Returns the responses."""
    out = []

    def run(_run_id):
        for params in steps:
            out.append(audit._fetch_serp_api({**params, "api_key": KEY}))
        return 1

    cp.tracked_run(run_id, "keywords_x.csv", {}, run,
                   environ={cp.RESUME_ENV: resume} if resume else {})
    return out


def test_stored_response_with_unfinished_token_followups_is_fetched_again(audit, monkeypatch):
    """A reused primary would hand the follow-up an expired token on every resume."""
    def get_dict(self):
        _FakeSearch.calls.append(self.params.get("q") or self.params["engine"])
        if self.params["engine"] == "google":
            return {"q": self.params["q"],
                    "ai_overview": {"page_token": "aio-" + self.params["q"]},
                    "related_questions": [{"next_page_token": "rq-" + self.params["q"]}]}
        return {"followup": True}

    monkeypatch.setattr(_FakeSearch, "get_dict", get_dict)
    primary = lambda q: {"engine": "google", "q": q}
    aio = lambda q: {"engine": "google_ai_overview", "page_token": "aio-" + q}
    rq = lambda q: {"engine": "google_related_questions", "next_page_token": "rq-" + q}

    # Run 1: alpha finished (the run went on to beta); beta stopped before its follow-ups.
    _token_run(audit, "run1", [primary("alpha"), aio("alpha"), rq("alpha"), primary("beta")])
    _FakeSearch.calls = []
    _token_run(audit, "run2", [primary("alpha"), aio("alpha"), rq("alpha"), primary("beta")],
               resume="run1")
    assert _FakeSearch.calls == ["beta"]             # alpha and its follow-ups from disk

    # Run 3 stopped after alpha's AI Overview follow-up, before its related questions.
    _token_run(audit, "run3", [primary("gamma"), aio("gamma")])
    _FakeSearch.calls = []
    _token_run(audit, "run4", [primary("gamma")], resume="run3")
    assert _FakeSearch.calls == ["gamma"]


def test_changed_parameters_are_fetched_again(audit):
    _fetch(audit, ["alpha"], "run1")
    _FakeSearch.calls = []

    def run(_run_id):
        audit._fetch_serp_api({"engine": "google", "q": "alpha", "location": "Vancouver",
                               "api_key": KEY})
        return 0

    cp.tracked_run("run2", "keywords_x.csv", {}, run, environ={cp.RESUME_ENV: "run1"})
    assert _FakeSearch.calls == ["alpha"]


def test_stale_checkpoints_are_ignored_and_counted(audit, caplog):
    _fetch(audit, ["alpha", "beta"], "run1")
    _age_calls("run1", hours=3)
    _FakeSearch.calls = []
    with caplog.at_level(logging.WARNING):
        _fetch(audit, ["alpha", "beta"], "run2", resume="run1",
               config={"serpapi": {"resume_max_age_hours": 2}})
    assert _FakeSearch.calls == ["alpha", "beta"]
    assert "ignored 2 stored responses older than 2h" in caplog.text


def test_missing_resume_run_fails(audit, caplog):
    with caplog.at_level(logging.ERROR):
        responses, code = _fetch(audit, ["alpha"], "run2", resume="no_such_run")
    assert code == 1 and responses == [] and _FakeSearch.calls == []
    assert "Cannot resume run no_such_run" in caplog.text
    assert _state("run2")["status"] == "failed"


def test_run_state_follows_the_run(audit):
    seen = {}

    def run(run_id):
        seen["during"] = _state(run_id)
        return 0

    cp.tracked_run("ok", "/some/dir/keywords_x.csv", {}, run, environ={})
    assert seen["during"]["status"] == "running"
    assert seen["during"]["input_csv"] == "keywords_x.csv"
    assert _state("ok")["status"] == "complete"

    cp.tracked_run("bad", "keywords_x.csv", {}, lambda run_id: 1, environ={})
    assert _state("bad")["status"] == "failed"

    with pytest.raises(RuntimeError):
        cp.tracked_run("crash", "keywords_x.csv", {}, _raise, environ={})
    assert _state("crash")["status"] == "failed"
    assert cp.ACTIVE is None                       # nothing leaks into the next run


def _raise(run_id):
    raise RuntimeError("parse error on keyword 7")


def test_raw_files_no_longer_overwrite_each_other(audit):
    def run(run_id):
        for q in ("alpha", "beta"):
            data = audit._fetch_serp_api({"engine": "google", "q": q, "api_key": KEY})
            audit.save_raw_json(run_id, "google", data)
        return 0

    cp.tracked_run("run1", "keywords_x.csv", {}, run, environ={})
    names = sorted(n for n in os.listdir("raw/run1") if n.endswith("_response.json"))
    assert names == ["0001_alpha_google_response.json", "0002_beta_google_response.json"]


@pytest.mark.parametrize("value, expected, warns", [
    (None, 24.0, False), (6, 6.0, False), (0, 0.0, False),
    (-1, 24.0, True), ("soon", 24.0, True), (True, 24.0, True),
])
def test_resume_max_age_is_read_from_config(value, expected, warns, caplog):
    config = {"serpapi": {"resume_max_age_hours": value}} if value is not None else {}
    with caplog.at_level(logging.WARNING):
        assert cp.resume_max_age_hours(config) == expected
    assert ("resume_max_age_hours" in caplog.text) is warns


# --- C8: what the launcher offers to resume -----------------------------------

def test_resumable_run_is_found_for_the_same_keyword_file(audit):
    _fetch(audit, ["alpha", "beta"], "20261114_090000", code=1)     # failed: resumable
    found = cp.find_resumable_run("/any/where/keywords_x.csv", 24)
    assert found["run_id"] == "20261114_090000" and found["stored_calls"] == 2
    assert found["age_minutes"] == 0

    assert cp.find_resumable_run("keywords_other.csv", 24) is None   # another file
    assert cp.find_resumable_run("keywords_x.csv", 0) is None        # 0 = never reuse
    _age_calls("20261114_090000", hours=30)
    assert cp.find_resumable_run("keywords_x.csv", 24) is None       # too old


def test_a_killed_run_is_resumable_and_a_completed_one_is_not(audit):
    _fetch(audit, ["alpha"], "killed", code=1)
    cp.write_run_state("killed", cp.RUNNING)            # what a kill leaves behind
    assert cp.find_resumable_run("keywords_x.csv", 24)["run_id"] == "killed"

    _fetch(audit, ["alpha"], "later", code=0)           # a newer run that completed
    assert cp.find_resumable_run("keywords_x.csv", 24) is None


@pytest.mark.parametrize("answer, expected", [(True, "20261114_090000"), (False, None)])
def test_launcher_asks_before_reusing(audit, monkeypatch, answer, expected):
    import importlib.util
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.syspath_prepend(here)
    spec = importlib.util.spec_from_file_location("serp_me", os.path.join(here, "serp-me.py"))
    serp_me = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serp_me)

    _fetch(audit, ["alpha", "beta"], "20261114_090000", code=1)
    asked, logged = [], []
    monkeypatch.setattr(serp_me.messagebox, "askyesno",
                        lambda title, text, **k: asked.append(text) or answer)

    class Stub:
        load_config = staticmethod(lambda: {})
        log = staticmethod(logged.append)

    got = serp_me.SerpLauncherApp._ask_resume(Stub(), "/x/keywords_x.csv")
    assert got == expected
    assert "keywords_x.csv stopped after 2 stored responses, 0 minutes ago" in asked[0]
    assert logged and "20261114_090000" in logged[0]

    asked.clear()                                    # nothing to resume: no question
    assert serp_me.SerpLauncherApp._ask_resume(Stub(), "keywords_other.csv") is None
    assert asked == []


def test_launcher_hands_the_resume_run_to_the_child():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "serp-me.py"), encoding="utf-8") as f:
        source = f.read()
    assert "find_resumable_run(" in source
    assert "env[serp_checkpoint.RESUME_ENV]" in source
