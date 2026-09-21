"""Shared smoke fixtures: one canonical window harness for tests_smoke/.

Every module works inside its own ``SmokeEnv``: scoped process-global patches
(restored at module teardown), a unique temp root and database identity, and
the canonical window retirement from ``_smoke_support``. Module-local ``win``
fixtures only choose show/size/setup; they never install patches or retire
windows by hand.

Also mutes every sound exit at the device level, so running tests from
tests_smoke/ (or any subdirectory) never plays audio even when the root
conftest is not loaded.
"""
from __future__ import annotations

import os
import sys

# T-1300: the platform MUST be selected before the QApplication built below,
# which is itself imported before any smoke module can run. The root conftest
# already established it for a repo-root run; this guarantees the same contract
# when a single smoke module (or tests_smoke/ alone) is executed.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests")))
from _qt_platform import configure_silent_platform, real_desktop_requested

configure_silent_platform()

import pytest
from _smoke_support import (
    SmokeEnv,
    SmokeWindowFactory,
    mute_sound_at_device,
    restore_sound_at_device,
)
from PyQt6.QtWidgets import QApplication

# Every smoke module must be runnable standalone: the shared window harness
# constructs real widgets, and Qt refuses to build a QWidget before a
# QApplication exists. This used to be an accident of the old conftest
# importing test_app_smoke (which creates one at import).
_APP = QApplication.instance() or QApplication([])

# T-1300 fail-fast: if the run was asked to be silent but Qt still resolved a
# native platform, abort now instead of constructing hundreds of real windows.
# (The check above imports PyQt only after configure_silent_platform, so a
# correct run can never trip this; an explicit real-desktop opt-in can.)
if _APP.platformName() != "offscreen" and not real_desktop_requested():
    raise SystemExit(
        f"T-1300 Qt platform contract violated: QApplication platform is "
        f"{_APP.platformName()!r}, expected 'offscreen'. Set "
        f"FASTPROMPTER_TEST_REAL_DESKTOP=1 to opt into the real desktop.")


@pytest.fixture(autouse=True, scope="module")
def smoke_env(request, tmp_path_factory):
    """Per-module scoped environment: temp root, DB identity, global patches.

    A module-owned ``_tmpdir`` is adopted as the fixture root when present
    (it is unique per module by construction); otherwise a private temp dir
    is created. ``SMOKE_DB_STEM`` overrides the database filename stem for
    modules whose tests reconstruct the path themselves.
    """
    module = request.module
    env = SmokeEnv(
        root=getattr(module, "_tmpdir", None),
        tmp_path_factory=tmp_path_factory,
        db_stem=getattr(module, "SMOKE_DB_STEM", "smoke"),
    )
    yield env
    env.finalize()


@pytest.fixture(scope="module")
def smoke_win(smoke_env):
    return SmokeWindowFactory(smoke_env)


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create()
    yield w
    smoke_win.retire(w)


@pytest.fixture
def fresh_win(tmp_path_factory):
    """A window nobody else has touched, on its own fresh temp root.

    Every invocation gets a NEW database directory, so no earlier smoke
    fixture can influence the next one through SQLite state.
    """
    env = SmokeEnv(tmp_path_factory=tmp_path_factory)
    factory = SmokeWindowFactory(env)
    w = factory.create()
    yield w
    factory.retire(w)
    env.finalize()


@pytest.fixture(autouse=True)
def _isolate_usage_probes(monkeypatch):
    # GUI smoke uses seeded snapshots. Opening hundreds of windows must not
    # probe the developer's actual accounts or depend on live vendor latency.
    from fastprompter.core.usage_limits.service import UsageLimitService
    monkeypatch.setattr(UsageLimitService, "schedule_auto", lambda *a, **kw: None)


@pytest.fixture(autouse=True, scope="session")
def _smoke_mute_sound():
    """Session-wide device mute that explicitly owns what it replaces.

    The release gate runs ``pytest tests/ tests_smoke/`` in ONE process, so a
    smoke-only substitution must not outlive the smoke tests. The originals
    are captured by ``mute_sound_at_device`` BEFORE the replacement and the
    exact class-dict/module objects are restored here at session teardown.
    """
    mute_sound_at_device()
    try:
        yield
    finally:
        restore_sound_at_device()
