"""Regression: "Silos at Start" (silo_home) must open a silo at the top.

The remembered cursor/scroll position used to always win over silo_home, so
for any silo last edited below the top it never took effect. With the flag
on, opening a silo must land the cursor at position 0.

Full FastPrompter teardown crashes the offscreen Qt platform inside pytest,
so the assertion runs in a short subprocess.
"""

import os
import subprocess
import sys


_SCRIPT = r"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextCursor
from fastprompter.main import FastPrompter

app = QApplication.instance() or QApplication([])

LONG = "\n".join("line %d %s" % (i, "x" * 40) for i in range(200))

win = FastPrompter()
win.data["temp_presets"] = [LONG, "", "", "", "", "", "", "", "", ""]


def open_at(idx, home):
    win.data["silo_home"] = "True" if home else "False"
    win._switch_to_slot(idx, initial=True)
    return win.text_area.textCursor().position()


top = open_at(0, True)
bottom = open_at(0, False)

problems = []
if top != 0:
    problems.append("home-not-top:%d" % top)
if bottom == 0:
    problems.append("no-home-should-be-end:%d" % bottom)

if problems:
    print("FAIL " + " ".join(problems))
    raise SystemExit(1)
print("OK top=%d end=%d" % (top, bottom))
"""


def test_silo_home_opens_at_top():
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env, capture_output=True, text=True,
        cwd=os.path.dirname(__file__),
    )
    assert proc.returncode == 0, (
        f"silo_home contract failed: {proc.stdout} {proc.stderr}")
    assert "OK" in proc.stdout
