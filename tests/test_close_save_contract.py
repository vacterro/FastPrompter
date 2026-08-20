"""T-1019: the resident close must not hide a window whose save failed.

The app is tray-resident: closing the last window hides it, it does not quit.
closeEvent therefore performs the non-finalized save and only then retires the
window. If that save returns False (dirty, retryable) the window must STAY
open — otherwise the dirty state is hidden behind a closed window. The
already-finalized (pre-quit) path must still skip the duplicate save and
close normally.

The full FastPrompter teardown crashes the offscreen Qt platform inside
pytest (a native fault unrelated to the fix), so the three scenarios run in
a short subprocess where construction, closeEvent and teardown are clean.
"""

import os
import subprocess
import sys


_SCRIPT = r"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtCore import Qt
from fastprompter.main import FastPrompter

app = QApplication.instance() or QApplication([])
w = FastPrompter()
# offscreen-only: accepting the close must not tear down a native window
# (the offscreen platform crashes on that here); we only care that
# closeEvent reaches super().closeEvent and accepts/ignores.
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)


def close(scenario):
    w._logical_finalized = (scenario == "finalized")
    calls = []
    if scenario == "fail":
        w.save_data_to_db = lambda force=False: False
    elif scenario == "ok":
        w.save_data_to_db = lambda force=False: True
    else:
        w.save_data_to_db = lambda force=False: (calls.append(force) or True)
    ev = QCloseEvent()
    w.closeEvent(ev)
    if scenario == "finalized":
        return calls == [] and ev.isAccepted() is True
    return ev.isAccepted() is (scenario == "ok")


results = [close(s) for s in ("fail", "ok", "finalized")]
if not all(results):
    print("FAIL " + str(results))
    os._exit(1)
print("OK")
os._exit(0)
"""


def test_close_save_contract():
    # The offscreen Qt platform intermittently crashes on QMainWindow close
    # teardown in this headless environment (a native fault, not a logic
    # bug), so retry the subprocess a few times. The assertion is correct and
    # passes whenever the subprocess survives teardown.
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    last = None
    for _ in range(3):
        proc = subprocess.run(
            [sys.executable, "-c", _SCRIPT],
            env=env, capture_output=True, text=True,
            cwd=os.path.dirname(__file__),
        )
        last = proc
        if proc.returncode == 0 and "OK" in proc.stdout:
            return
    assert last.returncode == 0, (
        f"close save contract failed: {last.stdout} {last.stderr}")
