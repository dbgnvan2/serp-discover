"""Every SerpAPI call has a working timeout.

Spec: docs/plan_stop_button_serpapi_timeout_2026-11-14.md (T1-T4)
"""

import logging

import pytest
import requests

import feasibility
import run_feasibility
import serp_audit
import timeouts


class _FakeSearch:
    """Stands in for serpapi.GoogleSearch: records the timeout in force at call time."""

    seen = []
    outcome = None          # an exception class to raise, or a dict to return

    def __init__(self, params):
        self.timeout = 60000        # the real client's default

    def get_dict(self):
        type(self).seen.append(self.timeout)
        if isinstance(self.outcome, dict):
            return self.outcome
        raise self.outcome("stalled")


@pytest.fixture
def fake_search(monkeypatch):
    _FakeSearch.seen = []
    monkeypatch.setattr(serp_audit, "GoogleSearch", _FakeSearch)
    monkeypatch.setattr(serp_audit, "SERPAPI_AVAILABLE", True)
    monkeypatch.setattr(serp_audit, "SERPAPI_TIMEOUT_SECONDS", 7.5)
    monkeypatch.setattr(serp_audit, "RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(serp_audit.time, "sleep", lambda s: None)
    return _FakeSearch


def test_search_is_given_the_configured_timeout(fake_search):
    fake_search.outcome = {"organic_results": []}
    assert serp_audit._fetch_serp_api({"q": "x"}) == {"organic_results": []}
    assert fake_search.seen == [7.5]


def test_timeout_is_retried_then_reported_failed(fake_search, caplog):
    fake_search.outcome = requests.Timeout
    with caplog.at_level(logging.ERROR):
        assert serp_audit._fetch_serp_api({"q": "x"}) is None
    assert fake_search.seen == [7.5, 7.5, 7.5]
    assert [r for r in caplog.records if "attempt 2" in r.getMessage()]


def test_timeout_error_log_does_not_contain_the_api_key(fake_search, caplog, monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "SECRETKEY123")

    class _Leaky(requests.Timeout):
        def __str__(self):
            return "Max retries exceeded with url: /search?q=x&api_key=SECRETKEY123"

    fake_search.outcome = _Leaky
    with caplog.at_level(logging.ERROR):
        serp_audit._fetch_serp_api({"q": "x", "api_key": "SECRETKEY123"})
    assert caplog.records and "SECRETKEY123" not in caplog.text


def test_real_client_passes_the_timeout_to_requests(monkeypatch):
    """Guards against a client release that stops reading ``.timeout``."""
    serpapi = pytest.importorskip("serpapi")
    import serpapi.serp_api_client as client_module
    seen = []

    class _Response:
        text = '{"organic_results": []}'

    def fake_get(url, params=None, timeout=None, **kwargs):
        seen.append(timeout)
        return _Response()

    monkeypatch.setattr(client_module.requests, "get", fake_get)
    monkeypatch.setattr(serp_audit, "GoogleSearch", serpapi.GoogleSearch)
    monkeypatch.setattr(serp_audit, "SERPAPI_AVAILABLE", True)
    monkeypatch.setattr(serp_audit, "SERPAPI_TIMEOUT_SECONDS", 7.5)

    assert serp_audit._fetch_serp_api({"q": "x", "api_key": "k"}) == {"organic_results": []}
    assert seen == [7.5]


def test_module_timeout_comes_from_config():
    assert serp_audit.SERPAPI_TIMEOUT_SECONDS == timeouts.serpapi_timeout(serp_audit.CONFIG)
    assert 0 < serp_audit.SERPAPI_TIMEOUT_SECONDS <= 600


@pytest.mark.parametrize("value", [0, -5, "soon", "", True, False, float("inf"), [30]])
def test_bad_timeout_config_falls_back_to_default(value, caplog):
    with caplog.at_level(logging.WARNING):
        got = timeouts.serpapi_timeout({"serpapi": {"timeout_seconds": value}})
    assert got == timeouts.DEFAULT_SERPAPI_TIMEOUT_SECONDS
    assert len(caplog.records) == 1


@pytest.mark.parametrize("config,expected", [
    ({"serpapi": {"timeout_seconds": 25}}, 25.0),
    ({"serpapi": {"timeout_seconds": "12.5"}}, 12.5),
    ({"serpapi": {}}, timeouts.DEFAULT_SERPAPI_TIMEOUT_SECONDS),
    ({}, timeouts.DEFAULT_SERPAPI_TIMEOUT_SECONDS),
    ({"serpapi": None}, timeouts.DEFAULT_SERPAPI_TIMEOUT_SECONDS),
])
def test_timeout_is_read_from_config(config, expected, caplog):
    with caplog.at_level(logging.WARNING):
        assert timeouts.serpapi_timeout(config) == expected
    assert caplog.records == []          # an absent key is not worth a warning


@pytest.mark.parametrize("fetch", ["_fetch_pivot_local_pack", "_fetch_pivot_organic_urls"])
def test_feasibility_serpapi_calls_use_the_configured_timeout(fetch, monkeypatch):
    seen = []

    class _Requests:
        @staticmethod
        def get(url, params=None, timeout=None):
            seen.append(timeout)
            raise requests.Timeout("stalled")

    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    monkeypatch.setattr(run_feasibility, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(run_feasibility, "_requests", _Requests)

    rows, ok = getattr(run_feasibility, fetch)("kw", {"serpapi": {"timeout_seconds": 33}})

    # _fetch_pivot_organic_urls returns a URLWindow (D2a); the local-pack
    # fetch returns a plain list. Both must come back empty on a timeout,
    # and empty must not read as "nothing ranked here" — the False says the
    # fetch failed, which is what the caller gates on (P1).
    empty = rows.urls if isinstance(rows, feasibility.URLWindow) else rows
    assert seen == [33.0] and ok is False and empty == []
    if isinstance(rows, feasibility.URLWindow):
        assert rows.window == 0, rows
