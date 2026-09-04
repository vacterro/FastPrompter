"""Regression: nothing reachable before the settings panel is built may
dereference a settings widget.

The settings tabs are built lazily on first reveal (``_ensure_settings_built``),
so on a fresh start with ``hide_extra=True`` attributes such as ``cb_ctrl_c``
or ``cb_lock_window`` do not exist yet. Editor Ctrl+C and the window hotkeys
are reachable in exactly that state, so they must read the persisted data
value instead of the widget.

Full FastPrompter teardown crashes the offscreen Qt platform inside pytest, so
the assertions run in a short subprocess.
"""

import os
import subprocess
import sys

_SCRIPT = r"""
import os
import tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_tmp = tempfile.mkdtemp(prefix="fastprompter_lazy_")
state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmp, "lazy.db")
state_mod.run_portable_backup = lambda data, profile_id=1, **kw: None

from fastprompter.main import FastPrompter

app = QApplication.instance() or QApplication([])

win = FastPrompter()

problems = []
if getattr(win, "_settings_built", False):
    problems.append("settings-already-built")
if getattr(win, "cb_ctrl_c", None) is not None:
    problems.append("cb_ctrl_c-exists")

# Ctrl+C in the editor: reads ctrl_c_closes without the checkbox.
win.data["ctrl_c_closes"] = "False"
win.text_area.setPlainText("hello")
try:
    win.text_area.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier, "c"))
except AttributeError as exc:
    problems.append("ctrl_c:%s" % exc)

# Window hotkeys: Alt+E / Alt+S flip persisted state without the checkboxes.
try:
    before = win.data.get("window_locked", "False")
    win.toggle_lock()
    if win.data.get("window_locked", "False") == before:
        problems.append("toggle_lock-did-nothing")
except AttributeError as exc:
    problems.append("toggle_lock:%s" % exc)

try:
    before = win.data.get("always_on_top", "True")
    win.toggle_always_on_top()
    if win.data.get("always_on_top", "True") == before:
        problems.append("toggle_aot-did-nothing")
except AttributeError as exc:
    problems.append("toggle_aot:%s" % exc)

if getattr(win, "_settings_built", False):
    problems.append("settings-built-by-hotkeys")

if problems:
    print("FAIL " + " ".join(problems))
    raise SystemExit(1)
print("OK")
"""


def test_hotkeys_and_ctrl_c_work_before_settings_are_built():
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env, capture_output=True, text=True,
        cwd=os.path.dirname(__file__),
    )
    assert proc.returncode == 0, (
        f"stdout={proc.stdout!r}\nstderr={proc.stderr[-2000:]!r}")
    assert "OK" in proc.stdout
