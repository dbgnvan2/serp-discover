"""One run at a time, and a run can be stopped with everything it started.

Spec: docs/plan_stop_button_serpapi_timeout_2026-11-14.md (S1-S7)
Real short-lived processes are used: the point is what happens to them.
"""

import os
import subprocess
import sys
import time

import pytest

import pipeline_status as ps
import run_control as rc
from tk_probe import tkinter_usable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
posix_only = pytest.mark.skipif(not rc.POSIX, reason="process groups are POSIX only")

# A parent that starts a child of its own, like run_pipeline.py starting serp_audit.py.
PARENT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)
SLEEPER = "import time; time.sleep(120)"
STUBBORN = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone(pid, within=5.0):
    deadline = time.time() + within
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _start_tree(child_code=SLEEPER):
    parent = subprocess.Popen([sys.executable, "-c", PARENT.format(child=child_code)],
                              stdout=subprocess.PIPE, text=True, **rc.popen_kwargs())
    child_pid = int(parent.stdout.readline())
    return parent, child_pid


def test_second_start_is_refused_while_running():
    control = rc.RunControl()
    assert control.begin() is True
    assert control.running                      # S2: claimed before any process exists
    assert control.begin() is False
    assert control.finish() is None
    assert not control.running and control.begin() is True


def test_stop_with_nothing_running_does_nothing():
    assert rc.RunControl().stop() is False


@posix_only
def test_stop_kills_the_child_and_its_own_child():
    control = rc.RunControl(grace_seconds=2)
    control.begin()
    parent, child_pid = _start_tree()
    control.attach(parent)
    try:
        assert control.stop() is True
        assert parent.wait(timeout=5) == -15
        assert _gone(child_pid)
        assert control.finish() == rc.STOPPED
    finally:
        rc._signal_tree(parent, 9)


@posix_only
def test_stop_kills_a_child_that_ignores_sigterm():
    control = rc.RunControl(grace_seconds=0.5)
    control.begin()
    parent, child_pid = _start_tree(STUBBORN)
    time.sleep(0.3)                              # let the child install its handler
    control.attach(parent)
    try:
        control.stop(wait=True)                  # the launcher-is-closing path
        assert not _alive(child_pid) or _gone(child_pid, within=2)
        assert parent.poll() is not None
    finally:
        rc._signal_tree(parent, 9)


@posix_only
def test_stop_requested_before_the_process_exists_is_honoured():
    control = rc.RunControl(grace_seconds=1)
    control.begin()
    control.stop(reason=rc.TIMED_OUT)
    parent, child_pid = _start_tree()
    control.attach(parent)
    try:
        assert parent.wait(timeout=5) != 0 and _gone(child_pid)
        assert control.finish() == rc.TIMED_OUT
    finally:
        rc._signal_tree(parent, 9)


@pytest.mark.parametrize("code,reason,label", [
    (-15, rc.STOPPED, "STOPPED"),
    (-9, rc.STOPPED, "STOPPED"),
    (-15, rc.TIMED_OUT, "TIMED OUT"),
    (0, rc.STOPPED, "SUCCESS"),                  # it finished before the signal landed
    (-15, None, "FAILED (exit -15)"),            # killed by something else
])
def test_exit_label_for_a_stopped_run(code, reason, label):
    assert ps.exit_label("run_pipeline.py", code, stop_reason=reason) == label


def test_close_request_while_running_needs_a_decision():
    asked = []

    def confirm(answer):
        return lambda: asked.append(answer) or answer

    assert rc.close_action(False, confirm(True)) == "close" and asked == []
    assert rc.close_action(True, confirm(True)) == "stop_and_close"
    assert rc.close_action(True, confirm(False)) == "stay"


@posix_only
def test_detects_a_pipeline_started_elsewhere(tmp_path):
    script = tmp_path / "serp_audit.py"
    script.write_text(SLEEPER)
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    (elsewhere / "serp_audit.py").write_text(SLEEPER)
    here = subprocess.Popen([sys.executable, "serp_audit.py"], cwd=tmp_path)
    there = subprocess.Popen([sys.executable, "serp_audit.py"], cwd=elsewhere)
    try:
        time.sleep(0.5)
        found = [pid for pid, _cmd in rc.running_pipeline_processes(str(tmp_path))]
        assert here.pid in found and there.pid not in found
        assert rc.running_pipeline_processes(str(tmp_path), ignore_pids=[here.pid]) == []
    finally:
        here.kill()
        there.kill()


def test_process_check_failure_is_reported_not_read_as_none_running(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("ps")
    monkeypatch.setattr(rc.subprocess, "run", boom)
    with pytest.raises(rc.ProcessCheckFailed):
        rc.running_pipeline_processes(".")


LAUNCHER_STANDIN = (
    "import subprocess, sys, time\n"
    "sys.path.insert(0, {repo!r})\n"
    "import run_control as rc\n"
    "control = rc.RunControl(grace_seconds=1)\n"
    "control.begin()\n"
    "child = subprocess.Popen([sys.executable, '-c', {child!r}], **rc.popen_kwargs())\n"
    "control.attach(child)\n"
    "rc.install_exit_guards(control)\n"
    "print(child.pid, flush=True)\n"
    "{ending}\n"
)


@posix_only
@pytest.mark.parametrize("ending,signal_name", [
    ("while True: time.sleep(0.1)", "SIGTERM"),      # killed
    ("while True: time.sleep(0.1)", "SIGHUP"),       # its terminal was closed
    ("while True: time.sleep(0.1)", "SIGINT"),       # Ctrl-C
    ("raise SystemExit(0)", None),                   # any ordinary exit
])
def test_run_ends_when_the_launcher_exits_another_way(ending, signal_name):
    import signal
    code = LAUNCHER_STANDIN.format(repo=REPO, child=SLEEPER, ending=ending)
    launcher = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    child_pid = int(launcher.stdout.readline())
    try:
        if signal_name:
            assert _alive(child_pid)
            launcher.send_signal(getattr(signal, signal_name))
        launcher.wait(timeout=10)
        assert _gone(child_pid)
    finally:
        launcher.kill()
        try:
            os.killpg(child_pid, 9)
        except (ProcessLookupError, PermissionError):
            pass


def test_regenerate_timeout_is_reported():
    ok, message = rc.run_with_timeout([sys.executable, "-c", SLEEPER], timeout=0.5)
    assert ok is False and "timed out" in message
    assert rc.run_with_timeout([sys.executable, "-c", "print(1)"], timeout=10) == (True, "")
    ok, message = rc.run_with_timeout(
        [sys.executable, "-c", "import sys; sys.stderr.write('bad json'); sys.exit(3)"], timeout=10)
    assert ok is False and message == "bad json"


@pytest.mark.parametrize("section,key,expected", [
    ({}, "stop_grace_seconds", 5.0),
    ({"stop_grace_seconds": 0}, "stop_grace_seconds", 5.0),
    ({"regenerate_timeout_seconds": "90"}, "regenerate_timeout_seconds", 90.0),
    ({}, "max_run_minutes", 0.0),
    ({"max_run_minutes": 45}, "max_run_minutes", 45.0),
    ({"max_run_minutes": -1}, "max_run_minutes", 0.0),
    ({"max_run_minutes": "soon"}, "max_run_minutes", 0.0),
])
def test_launcher_settings(section, key, expected):
    assert rc.launcher_settings({"launcher": section})[key] == expected


def test_launcher_wiring():
    """Source checks (the repo's convention for Tk wiring that needs no display)."""
    src = open(os.path.join(REPO, "serp-me.py"), encoding="utf-8").read()
    on_select = src[src.index("    def on_select("):src.index("    def _selection_is_runnable(")]
    assert "_refresh_run_buttons()" in on_select and 'run_btn.config(state="normal")' not in on_select
    assert 'protocol("WM_DELETE_WINDOW", self.on_close)' in src
    assert "**popen_kwargs()" in src and "self.run_control.begin()" in src
    assert "install_exit_guards(app.run_control)" in src and '"::tk::mac::Quit", self.on_close' in src


@pytest.mark.skipif(not tkinter_usable(), reason="no usable Tk display")
def test_run_and_stop_buttons_follow_the_run_state(monkeypatch):
    import importlib.util
    import tkinter as tk
    monkeypatch.setattr(rc, "running_pipeline_processes", lambda *a, **k: [])
    spec = importlib.util.spec_from_file_location("serp_me", os.path.join(REPO, "serp-me.py"))
    serp_me = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serp_me)
    monkeypatch.setattr(serp_me, "get_report_model_options",       # no HTTP call at startup
                        lambda settings, **k: [])
    root = tk.Tk()
    root.withdraw()
    try:
        app = serp_me.SerpLauncherApp(root)
        state = lambda: (str(app.run_btn.cget("state")), str(app.stop_btn.cget("state")))
        assert state() == ("normal", "disabled")

        assert app.run_control.begin()
        app.on_select(None)                       # a list click during a run (review M2)
        assert state() == ("disabled", "normal")

        app.run_control.finish()
        app._refresh_run_buttons()
        assert state() == ("normal", "disabled")

        app.external_runs = [(1, "python serp_audit.py")]    # started elsewhere, still going
        monkeypatch.setattr(serp_me, "running_pipeline_processes", lambda *a, **k: [(1, "x")])
        app.on_select(None)
        assert state() == ("disabled", "disabled")
        monkeypatch.setattr(serp_me, "running_pipeline_processes", lambda *a, **k: [])
        app.on_select(None)                       # it has finished: checked again on click
        assert state() == ("normal", "disabled")
    finally:
        root.destroy()
