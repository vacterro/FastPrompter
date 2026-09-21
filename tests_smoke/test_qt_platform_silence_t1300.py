"""T-1300: the automated smoke harness is silent by default.

Proves the deterministic platform contract instead of a screenshot: the
canonical selector (``tests/_qt_platform.py``) runs before the first PyQt
import, the resulting QApplication uses the offscreen backend for ordinary
runs, ``show()`` stays logically effective under it without a desktop window,
and the native Windows plugin is reachable ONLY through the documented opt-in.

The explicit-opt-in subprocess proves the escape hatch selects the native
plugin and prints the banner; it constructs one QApplication and nothing else.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

_ROOT = Path(__file__).resolve().parents[1]
_REAL_ENV = "FASTPROMPTER_TEST_REAL_DESKTOP"


def test_session_platform_is_offscreen():
    assert QApplication.instance() is not None
    assert QApplication.platformName() == "offscreen", (
        f"automated run must be offscreen, got {QApplication.platformName()!r}")


def test_selector_runs_before_pyqt_and_forces_offscreen():
    script = (
        "import os, sys;"
        "root=os.getcwd();"
        "[sys.path.insert(0, os.path.join(root, s)) for s in ('src','tests')];"
        "os.environ.pop('QT_QPA_PLATFORM', None);"
        "from _qt_platform import configure_silent_platform;"
        "assert configure_silent_platform() == 'offscreen';"
        "assert os.environ['QT_QPA_PLATFORM'] == 'offscreen';"
        "from PyQt6.QtWidgets import QApplication;"
        "assert (QApplication.instance() or QApplication([])).platformName() == 'offscreen';"
        "print('PLATFORM_OFFSCREEN_OK')"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env={k: v for k, v in os.environ.items()
                               if k != "QT_QPA_PLATFORM"},
        timeout=300,
    )
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "PLATFORM_OFFSCREEN_OK" in done.stdout, (done.stdout, done.stderr)


def test_show_is_logically_effective_without_a_desktop_window(win):
    win.show()
    QApplication.processEvents()
    assert win.isVisible(), "offscreen show() must still report visible to Qt"
    assert not win.isWindow() or QApplication.platformName() == "offscreen"
    win.close()
    QApplication.processEvents()


def test_inherited_native_platform_is_not_trusted():
    script = (
        "import os, sys;"
        "root=os.getcwd();"
        "[sys.path.insert(0, os.path.join(root, s)) for s in ('src','tests')];"
        "os.environ['QT_QPA_PLATFORM']='windows';"
        "from _qt_platform import configure_silent_platform;"
        "assert configure_silent_platform() == 'offscreen';"
        "assert os.environ['QT_QPA_PLATFORM'] == 'offscreen';"
        "print('INHERITED_NATIVE_REFUSED')"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300,
    )
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "INHERITED_NATIVE_REFUSED" in done.stdout, (done.stdout, done.stderr)


def test_real_desktop_opt_in_selects_native_platform():
    script = (
        "import os, sys;"
        "root=os.getcwd();"
        "[sys.path.insert(0, os.path.join(root, s)) for s in ('src','tests')];"
        "os.environ.pop('QT_QPA_PLATFORM', None);"
        "from _qt_platform import configure_silent_platform, real_desktop_requested;"
        "assert real_desktop_requested() is True;"
        "assert configure_silent_platform() == 'windows';"
        "from PyQt6.QtWidgets import QApplication;"
        "print('PLATFORM=%s' % (QApplication.instance() or QApplication([])).platformName())"
    )
    env = {**os.environ, _REAL_ENV: "1"}
    env.pop("QT_QPA_PLATFORM", None)
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=300,
    )
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "PLATFORM=windows" in done.stdout, (done.stdout, done.stderr)
