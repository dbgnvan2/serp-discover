"""run_control.py — start, guard and stop the launcher's child process.

No tkinter here. The launcher holds one RunControl; the Run and Stop buttons
read their state from it, so a second run cannot start and a run can be ended
together with the processes it started.

Spec: docs/plan_stop_button_serpapi_timeout_2026-11-14.md (S1-S7)
Tests: tests/test_run_control.py
"""

import atexit
import os
import signal
import subprocess
import sys
import threading

from timeouts import seconds_from_config

POSIX = os.name == "posix"

# Scripts that fetch paid data or write run outputs. A second copy must not start.
PIPELINE_SCRIPTS = ("run_pipeline.py", "serp_audit.py", "run_feasibility.py",
                    "generate_content_brief.py")

DEFAULTS = {
    "stop_grace_seconds": 5.0,           # SIGTERM, then SIGKILL after this long
    "regenerate_timeout_seconds": 300.0,  # report regeneration after feasibility
    "process_check_timeout_seconds": 5.0,  # pgrep / lsof
    "max_run_minutes": 0.0,               # 0 = no cap on a whole run
}

STOPPED, TIMED_OUT = "stopped", "timed out"


def launcher_settings(config):
    """The ``launcher`` section of config.yml with defaults filled in."""
    section = config.get("launcher") if isinstance(config, dict) else None
    section = section if isinstance(section, dict) else {}
    out = {}
    for key, default in DEFAULTS.items():
        if key == "max_run_minutes":
            try:
                value = float(section.get(key, default))
                out[key] = value if 0 <= value < float("inf") else default
            except (TypeError, ValueError):
                out[key] = default
        else:
            out[key] = seconds_from_config(section.get(key), default, f"launcher.{key}")
    return out


def popen_kwargs():
    """Start the child in its own process group so the whole run can be stopped."""
    return {"start_new_session": True} if POSIX else {}


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_tree(process, sig):
    """Signal the child's process group (POSIX) or the child alone. True if sent."""
    try:
        if POSIX:
            os.killpg(process.pid, sig)
        else:
            process.terminate() if sig == signal.SIGTERM else process.kill()
        return True
    except (ProcessLookupError, OSError):
        return False


def tree_alive(process):
    return _group_alive(process.pid) if POSIX else process.poll() is None


class RunControl:
    """One run at a time. Thread-safe: the GUI thread and the worker thread both call it."""

    def __init__(self, grace_seconds=DEFAULTS["stop_grace_seconds"]):
        self.grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._running = False
        self._process = None
        self._stop_reason = None

    @property
    def running(self):
        return self._running

    @property
    def stop_reason(self):
        return self._stop_reason

    def begin(self):
        """Claim the run before the process is started. False if one is active (S1, S2)."""
        with self._lock:
            if self._running:
                return False
            self._running, self._process, self._stop_reason = True, None, None
            return True

    def attach(self, process):
        """Hand over the started process. Honours a stop requested before it existed."""
        with self._lock:
            self._process = process
            pending = self._stop_reason
        if pending:
            self._terminate(process, wait=False)

    def finish(self):
        """The process has exited. Returns why it was stopped, or None."""
        with self._lock:
            reason = self._stop_reason
            self._running, self._process = False, None
            return reason

    def stop(self, reason=STOPPED, wait=False):
        """Stop the run and everything it started (S3). False when nothing is running.

        ``wait=True`` blocks until the processes are gone (used when the
        launcher itself is closing, so nothing is left behind).
        """
        with self._lock:
            if not self._running:
                return False
            if self._stop_reason is None:
                self._stop_reason = reason
            process = self._process
        if process is not None:
            self._terminate(process, wait)
        return True

    def _terminate(self, process, wait):
        _signal_tree(process, signal.SIGTERM)

        def kill_if_alive():
            if tree_alive(process):
                _signal_tree(process, signal.SIGKILL)

        if wait:
            try:
                process.wait(timeout=self.grace_seconds)
            except subprocess.TimeoutExpired:
                pass
            kill_if_alive()
            try:
                process.wait(timeout=self.grace_seconds)
            except subprocess.TimeoutExpired:
                pass
        else:
            timer = threading.Timer(self.grace_seconds, kill_if_alive)
            timer.daemon = True
            timer.start()


def close_action(running, confirm_stop):
    """What closing the launcher window should do (S5).

    ``confirm_stop`` is called only when a run is active; it asks the user.
    Returns "close", "stop_and_close" or "stay".
    """
    if not running:
        return "close"
    return "stop_and_close" if confirm_stop() else "stay"


def install_exit_guards(control):
    """End the run when the launcher exits by any route other than its close box.

    The child runs in its own session, so a Ctrl-C or a closed terminal no
    longer reaches it; without this it would keep running, and spending
    credits, after the launcher was gone. Call from the main thread.
    """
    atexit.register(control.stop, wait=True)

    def on_signal(signum, _frame):
        control.stop(wait=True)
        sys.exit(128 + signum)

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)


class ProcessCheckFailed(Exception):
    """The already-running check could not be made. Not the same as "none running"."""


def _process_cwd(pid, timeout):
    try:
        return os.readlink(f"/proc/{pid}/cwd")          # Linux
    except OSError:
        pass
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                             capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def running_pipeline_processes(folder, timeout=DEFAULTS["process_check_timeout_seconds"],
                               scripts=PIPELINE_SCRIPTS, ignore_pids=()):
    """Pipeline scripts already running from ``folder`` (S6): a list of (pid, command).

    A python process running one of ``scripts`` counts when its working
    directory is ``folder``, or cannot be determined. Raises ProcessCheckFailed
    when the process list cannot be read, so the caller can say so.
    """
    try:
        result = subprocess.run(["ps", "-axo", "pid=,command="],
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise ProcessCheckFailed(str(e)) from e
    if result.returncode != 0:
        raise ProcessCheckFailed((result.stderr or "").strip() or f"ps exit {result.returncode}")
    folder = os.path.realpath(folder)
    skip = {os.getpid(), *ignore_pids}
    found = []
    for line in result.stdout.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if not pid_text.isdigit() or int(pid_text) in skip:
            continue
        words = command.split()
        if not words or "python" not in os.path.basename(words[0]).lower():
            continue
        if not any(os.path.basename(w) in scripts for w in words[1:]):
            continue
        cwd = _process_cwd(int(pid_text), timeout)
        if cwd is None or os.path.realpath(cwd) == folder:
            found.append((int(pid_text), command))
    return found


def run_with_timeout(cmd, timeout, cwd=None):
    """Run a short helper command. Returns (ok, message); a timeout is a failure (S7)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:g}s"
    except OSError as e:
        return False, str(e)
    if result.returncode != 0:
        return False, (result.stderr or "").strip() or f"exit {result.returncode}"
    return True, ""
