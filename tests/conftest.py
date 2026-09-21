import json
import os
import threading

# Run all Qt tests headless. Without a platform plugin the GUI tests fail to
# construct a QApplication on a machine with no display; the offscreen platform
# is the standard headless backend and exercises the same code paths.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import pytest
from _timer_isolation import abandoned_idle_timer
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

_QT_LIFETIME_TRACE = os.environ.get("FASTPROMPTER_QT_LIFETIME_TRACE") == "1"


def _qt_lifetime_record(nodeid):
    """Bounded teardown metadata for T-1288 placement work; never user data."""
    app = QApplication.instance()
    if app is None:
        return None
    try:
        widgets = app.allWidgets()
        tops = app.topLevelWidgets()
    except RuntimeError:
        return None
    histogram = {}
    for widget in widgets:
        try:
            name = type(widget).__name__
        except RuntimeError:
            continue
        histogram[name] = histogram.get(name, 0) + 1
    known = {
        "FastPrompter": histogram.get("FastPrompter", 0),
        "VaultTextEdit": histogram.get("VaultTextEdit", 0),
        "SoundSettingsDialog": histogram.get("SoundSettingsDialog", 0),
        "TimerToast": histogram.get("TimerToast", 0),
        "QTimer(reachable from top-level widgets)": sum(
            len(t.findChildren(QTimer)) for t in tops
        ),
    }
    return {
        "nodeid": nodeid,
        "widgets": len(widgets),
        "top_level_widgets": len(tops),
        "visible_top_level_widgets": sum(1 for t in tops if t.isVisible()),
        "known": known,
        "object_classes": dict(
            sorted(histogram.items(), key=lambda kv: -kv[1])[:15]
        ),
        "threads": threading.active_count(),
    }


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _disarm_abandoned_editor_idle_timers():
    """T-1260: no test may leave an armed timer whose callback cannot run.

    ``VaultTextEdit`` arms a 2 s single-shot idle timer on every scroll
    (editor.py:368) and its timeout calls ``main_win.capture_silo_state()``
    (editor.py:2664). Eleven test files build an editor over a
    ``SimpleNamespace`` main-window double that has no such method, scroll it,
    and walk away. The widget stays alive on the shared QApplication with the
    timer still armed, and PyQt6 turns an exception raised inside a slot into
    ``qFatal()`` -- so the next test that pumps the event loop for longer than
    two seconds does not fail, it ABORTS THE INTERPRETER: measured as
    ``Fatal Python error: Aborted`` at 76 %% of ``pytest tests/``, inside
    ``tests/test_timer_fire.py::_wait_until``, with no summary and no failing
    test name. Twenty-two such timers were armed and abandoned by the time the
    run reached ``tests/test_logging.py``.

    The selection rule is ``_timer_isolation.abandoned_idle_timer`` and is
    covered by ``tests/test_editor_timer_isolation.py``: a production-shaped
    owner is never disarmed, unrelated objects are never touched, and nothing
    process-wide is drained or cleared. Widgets are left alive -- module-scoped
    fixtures legitimately keep editors -- only the abandoned timer is stopped.
    """
    yield
    if QApplication.instance() is None:
        return
    for widget in QApplication.allWidgets():
        timer = abandoned_idle_timer(widget)
        if timer is not None:
            timer.stop()


@pytest.fixture(autouse=True)
def _qt_lifetime_trace(request):
    """T-1288 opt-in ownership trace: FASTPROMPTER_QT_LIFETIME_TRACE=1 writes
    one bounded metadata line per test; no production behavior depends on it."""
    yield
    if not _QT_LIFETIME_TRACE:
        return
    record = _qt_lifetime_record(request.node.nodeid)
    if record is None:
        return
    path = os.environ.get(
        "FASTPROMPTER_QT_LIFETIME_TRACE_FILE", "qt_lifetime_trace.jsonl"
    )
    try:
        with open(path, "a", encoding="utf-8") as sink:
            sink.write(json.dumps(record) + "\n")
    except OSError:
        pass


@pytest.fixture(autouse=True, scope="session")
def mute_sounds():
    """Silence all tests by mocking the underlying audio players."""
    patches = []
    
    try:
        __import__("winsound")
        patches.append(patch("fastprompter.core.sound_manager.winsound"))
    except ImportError:
        pass

    try:
        from PyQt6.QtMultimedia import QSoundEffect
        patches.append(patch.object(QSoundEffect, 'play'))
    except ImportError:
        pass
        
    for p in patches:
        try:
            p.start()
        except Exception:
            pass
            
    yield
    
    for p in reversed(patches):
        try:
            p.stop()
        except Exception:
            pass
