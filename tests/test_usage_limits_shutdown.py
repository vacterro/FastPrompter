"""Bounded, explicit UsageLimitService shutdown.

The service owns a thread pool AND real ``codex app-server`` child processes.
Before this was enforced, ``shutdown()`` was documented "non-blocking": it
cancelled nothing that had already started, never touched the children, and
left probe workers running into interpreter finalization -- which ends a
Windows process with an access violation (0xC0000005) instead of an exit code,
after a green test summary has already been printed.

    uv run pytest tests/test_usage_limits_shutdown.py -q
"""

import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot
from fastprompter.core.usage_limits.providers import _codex_probe
from fastprompter.core.usage_limits.service import UsageLimitService

# Every bounded wait in this file. Shutdown promises a ceiling, so a test that
# hangs is a failure, not a slow pass.
BOUND_S = 10.0


def _account(stable_id, provider_id="fake"):
    return AccountRef(
        provider_id=provider_id,
        stable_id=stable_id,
        display_name=stable_id,
        source_kind="configured",
        source_path=f"/tmp/{stable_id}",
        enabled=True,
        metadata={},
    )


class _BlockingProvider:
    """Probes park until released, so a sweep can be caught mid-flight."""

    provider_id = "fake"

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)
        self.started = 0
        self._lock = threading.Lock()

    def discover_accounts(self):
        return []

    def probe(self, account, deadline):
        with self._lock:
            self.started += 1
        self.entered.release()
        self.release.wait(timeout=BOUND_S)
        return UsageSnapshot(account=account, status="OK", windows=[])


def _service_with(provider, accounts):
    service = UsageLimitService({}, discover=False)
    with service._lock:
        service._providers = {"fake": provider}
        service._state.accounts = list(accounts)
    return service


def _spawn_stdin_blocked_child():
    """A child that reads stdin forever and never answers, like a hung probe."""
    return subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, bufsize=-1, text=False,
    )


def test_shutdown_cancels_probes_that_never_started():
    provider = _BlockingProvider()
    # POOL_SIZE is 3, so accounts 4..8 cannot have started yet.
    accounts = [_account(f"acct{i}") for i in range(8)]
    service = _service_with(provider, accounts)
    try:
        service.refresh()
        # Wait until the pool is saturated and the rest are queued.
        for _ in range(3):
            assert provider.entered.acquire(timeout=BOUND_S)
        with service._lock:
            futures = list(service._active_futures)
        assert len(futures) == len(accounts)

        provider.release.set()
        assert service.shutdown(timeout=BOUND_S) is True
        assert any(f.cancelled() for f in futures), (
            "queued probes must be cancelled, not silently drained")
        assert provider.started < len(accounts), (
            "a cancelled probe must never reach the provider")
    finally:
        provider.release.set()
        service.shutdown(timeout=BOUND_S)


def test_shutdown_terminates_a_running_codex_child_and_its_reader():
    proc = _spawn_stdin_blocked_child()
    session = _codex_probe.AppServerSession(proc, "test-home")
    assert proc in _codex_probe.live_probe_processes()
    assert session._reader.is_alive()

    stopped = _codex_probe.terminate_probe_processes()

    assert stopped == 1, "the live child must be reported as terminated"
    assert proc.poll() is not None, "child process still running after shutdown"
    session._reader.join(timeout=BOUND_S)
    assert not session._reader.is_alive(), "stdout reader thread never exited"
    assert proc not in _codex_probe.live_probe_processes()


def test_terminating_an_already_dead_child_is_safe():
    proc = _spawn_stdin_blocked_child()
    _codex_probe.AppServerSession(proc, "test-home")
    assert _codex_probe.terminate_probe_processes() == 1
    # Second pass: registry already empty, nothing to kill, no exception.
    assert _codex_probe.terminate_probe_processes() == 0
    _codex_probe.unregister_probe_process(proc)
    assert proc.poll() is not None


class _StubbornProc:
    """Popen-compatible child whose terminate/kill/wait all fail to kill it.

    ``poll()`` keeps returning None, which is the only trustworthy proof that
    the process is still running.
    """

    def __init__(self):
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return None

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def wait(self, timeout=None):
        self.wait_calls += 1
        raise subprocess.TimeoutExpired(cmd="stubborn", timeout=timeout)


def test_stubborn_child_stays_registered_and_reports_incomplete():
    """W2-006: a child that survives terminate/kill must NOT be unregistered.

    Before the repair, ``_stop_process`` returned the PRE-attempt liveness, so
    a provably live child was reported stopped and erased from the only
    process-wide registry later shutdown passes use.
    """
    proc = _StubbornProc()
    _codex_probe.attach_probe_reader(proc, None)
    assert proc in _codex_probe.live_probe_processes()

    stopped = _codex_probe.terminate_probe_processes(grace_s=0.0, passes=1)

    assert stopped == 0, "a still-live child must not be reported stopped"
    assert proc in _codex_probe.live_probe_processes(), (
        "a still-live child must remain registered for a later retry")
    try:
        assert proc.terminate_calls == 1
        assert proc.kill_calls == 1
    finally:
        _codex_probe.unregister_probe_process(proc)


def test_stubborn_child_is_reaped_once_poll_reports_death():
    """A later pass that observes a terminal poll() retires the child cleanly."""
    proc = _StubbornProc()
    _codex_probe.attach_probe_reader(proc, None)
    state = {"alive": True}

    def poll():
        return None if state["alive"] else 0

    proc.poll = poll
    assert _codex_probe.terminate_probe_processes(grace_s=0.0, passes=1) == 0
    assert proc in _codex_probe.live_probe_processes()
    state["alive"] = False
    assert _codex_probe.terminate_probe_processes(grace_s=0.0, passes=1) == 1
    assert proc not in _codex_probe.live_probe_processes()


def test_shutdown_returns_inside_its_bound_with_a_wedged_probe():
    provider = _BlockingProvider()
    service = _service_with(provider, [_account("wedged")])
    try:
        service.refresh()
        assert provider.entered.acquire(timeout=BOUND_S)
        start = time.monotonic()
        # The probe is still parked, so the bounded wait must expire and say so
        # instead of blocking on it.
        finished = service.shutdown(timeout=0.5)
        elapsed = time.monotonic() - start
        assert finished is False, (
            "a probe still running past the bound must be reported")
        assert elapsed < BOUND_S, f"shutdown took {elapsed:.1f}s, expected bounded"
    finally:
        provider.release.set()


def test_repeated_shutdown_is_idempotent():
    service = UsageLimitService({}, discover=False)
    assert service.shutdown() is True
    assert service.shutdown() is True
    assert service.shutdown(timeout=0.0) is True


def test_no_probe_is_accepted_after_shutdown():
    provider = _BlockingProvider()
    service = _service_with(provider, [_account("late")])
    service.shutdown()
    service.refresh()
    service.refresh(rediscover=True)
    time.sleep(0.1)
    assert provider.started == 0
    with service._lock:
        assert service._active_futures == set()


def test_shutdown_leaves_no_service_worker_threads_alive():
    provider = _BlockingProvider()
    service = _service_with(provider, [_account(f"a{i}") for i in range(4)])
    service.refresh()
    assert provider.entered.acquire(timeout=BOUND_S)
    provider.release.set()
    assert service.shutdown(timeout=BOUND_S) is True

    deadline = time.monotonic() + BOUND_S
    while time.monotonic() < deadline:
        alive = [t.name for t in threading.enumerate()
                 if t.name.startswith("fastprompter-limit-sweep")]
        if not alive:
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"sweep threads still alive: {alive}")


def test_fire_after_widget_deletion_cannot_touch_the_dead_widget(qapp):
    from PyQt6 import sip

    from fastprompter.ui.limit_gauges import LimitGauges

    service = UsageLimitService({}, discover=False)
    try:
        gauges = LimitGauges(object(), service)
        sip.delete(gauges)
        assert sip.isdeleted(gauges)
        # The service still holds the registered callback. Firing it must be a
        # no-op rather than an emit on a destroyed QWidget.
        service._fire()

        service.shutdown()
        service._fire()
    finally:
        service.shutdown()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
