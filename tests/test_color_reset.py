"""T-1010: ColorConfigDialog.reset_colors must restore every canonical key.

The Reset map used to be a hand-maintained copy of the colour defaults that
missed the six notification controls added later; indexing it raised KeyError
the moment one of those controls was reset. The single source of truth is
``canonical_defaults``, so Reset must read from it and never KeyError.

The dialog is heavy to construct under the offscreen Qt platform inside
pytest (a native fault unrelated to the fix), so the assertion runs in a
short subprocess where it constructs and resets cleanly.
"""

import os
import subprocess
import sys


_SCRIPT = r"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget
from fastprompter.theme.themes import CUSTOM_COLOR_DEFAULTS
from fastprompter.ui.settings import ColorConfigDialog

app = QApplication.instance() or QApplication([])


class _FakeMain(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self._current_lang = "EN"

    def styleSheet(self):
        return ""


dlg = ColorConfigDialog(_FakeMain())

# disturb a couple of notification controls so Reset has something to undo
dlg.custom_colors["notif_header_text"] = "#000000"
dlg.custom_colors["notif_btn_pressed"] = "#000000"

dlg.reset_colors()

notif = ("notif_header_text", "notif_info", "notif_border_dark",
         "notif_btn_bg", "notif_btn_text", "notif_btn_pressed")
problems = []
for key in notif:
    if key not in dlg.custom_colors:
        problems.append(f"missing:{key}")
    elif dlg.custom_colors[key] != dlg.canonical_defaults[key]:
        problems.append(f"mismatch:{key}")
    elif dlg.custom_colors[key] != CUSTOM_COLOR_DEFAULTS[key]:
        problems.append(f"not-canonical:{key}")
for key, btn in dlg.color_buttons.items():
    if btn.text() != dlg.canonical_defaults.get(key, "#000000"):
        problems.append(f"button:{key}")
for key, value in dlg.canonical_defaults.items():
    if dlg.custom_colors.get(key) != value:
        problems.append(f"restore:{key}")

if problems:
    print("FAIL " + " ".join(problems))
    raise SystemExit(1)
print("OK")
"""


def test_reset_restores_every_canonical_key_including_notifications():
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env, capture_output=True, text=True,
        cwd=os.path.dirname(__file__),
    )
    assert proc.returncode == 0, (
        f"reset contract failed: {proc.stdout} {proc.stderr}")
    assert "OK" in proc.stdout
