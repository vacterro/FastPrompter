"""Canonical Qt platform selection for every pytest tree (T-1300).

One owner for the silent/offscreen test contract, shared by ``tests/`` and
``tests_smoke/`` so the two suites cannot drift again. Qt reads
``QT_QPA_PLATFORM`` ONCE -- when the first ``QApplication`` is constructed --
so this must run before any PyQt import in the process.

Default: ``offscreen``. Deterministic and non-intrusive: no windows, no
taskbar entries, no focus steal, no tray balloons. The native Windows plugin
is only selected through the explicit opt-in
``FASTPROMPTER_TEST_REAL_DESKTOP=1``; an inherited ``windows`` value in the
operator's environment is deliberately NOT trusted (an automated run must not
accidentally drive the real desktop).

This governs the pytest harness only. It is never imported by the
application, so the packaged EXE / release probe keep the real Windows
platform.
"""

from __future__ import annotations

import os

OFFSCREEN = "offscreen"
REAL_DESKTOP_ENV = "FASTPROMPTER_TEST_REAL_DESKTOP"

_TRUE = {"1", "true", "yes", "on"}


def real_desktop_requested() -> bool:
    """True only for the documented explicit native-desktop opt-in."""
    return os.environ.get(REAL_DESKTOP_ENV, "").strip().lower() in _TRUE


def configure_silent_platform() -> str:
    """Establish the QPA platform before the first PyQt import.

    Idempotent. Returns the platform name that will be requested. Call this at
    the top of every conftest that may construct a ``QApplication`` before
    another conftest has run.
    """
    if real_desktop_requested():
        # Explicit opt-in: keep a caller-provided native platform, else default
        # to the real Windows plugin. Set it so the contract check has a value.
        chosen = os.environ.get("QT_QPA_PLATFORM", "") or "windows"
        os.environ["QT_QPA_PLATFORM"] = chosen
        return chosen
    # Force, do not setdefault: an inherited native value is exactly the
    # silent-mode violation this module exists to prevent.
    os.environ["QT_QPA_PLATFORM"] = OFFSCREEN
    return OFFSCREEN
