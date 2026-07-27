"""T-555 repro attempt: what makes a plain wheel slam the view to the top?

The instrumented log caught it three times, always the same shape:
    view jumped to the top from 240
    editor.py wheelEvent -> super().wheelEvent(event)

A wheel cannot set a scrollbar to 0 from 240 by scrolling. It can only get
there if the RANGE collapsed under it - so this drives real wheel events at
a document whose scroll sits deep, and watches the maximum as well as the
value.
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "src")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

tmp = tempfile.mkdtemp(prefix="t555_")
state_mod.get_db_path = lambda pid=1: os.path.join(tmp, f"t_{pid}.db")
state_mod.run_portable_backup = lambda d: None

from fastprompter.main import FastPrompter  # noqa: E402

FastPrompter.setup_single_instance_server = lambda self: None
FastPrompter.register_all_hotkeys = lambda self: None
FastPrompter.unregister_all_hotkeys = lambda self: None

app = QApplication.instance() or QApplication([])
win = FastPrompter()
win.resize(900, 500)
win.show()
app.processEvents()

ta = win.text_area
ta.resize(700, 400)
# The log said "from 240" - a range of ~240, not the 2250 a 200-line
# document gives. A collapse to zero is only reachable when the range is
# small enough to vanish, so the document length is the variable here.
ta.setPlainText("\n".join(f"line {i}"
                          for i in range(int(os.environ.get("LINES", "30")))))
app.processEvents()

bar = ta.verticalScrollBar()
events = []
ta._watch_scroll_reset_orig = ta._watch_scroll_reset


def spy(value):
    events.append((ta._last_scroll_value, value, bar.maximum()))
    ta._watch_scroll_reset_orig(value)


ta._watch_scroll_reset = spy
bar.valueChanged.disconnect()
bar.valueChanged.connect(ta._watch_scroll_reset)


def wheel(dy, mods=Qt.KeyboardModifier.NoModifier):
    pos = QPointF(ta.width() / 2, ta.height() / 2)
    ev = QWheelEvent(pos, ta.mapToGlobal(pos.toPoint()).toPointF(),
                     QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(ta.viewport(), ev)
    app.processEvents()


print("blocks in the widget:", ta.document().blockCount())
print("first line:", repr(ta.document().firstBlock().text()[:40]))
print(f"range 0..{bar.maximum()}")
bar.setValue(bar.maximum())
app.processEvents()
print(f"parked at {bar.value()}")

events.clear()
print("\n-- plain wheel, both directions --")
for dy in (-120, -120, 120, 120):
    wheel(dy)
print(f"   value now {bar.value()}, max {bar.maximum()}")

print("\n-- ctrl+wheel (the zoom path) --")
bar.setValue(bar.maximum())
app.processEvents()
before = bar.value()
events.clear()
wheel(-120, Qt.KeyboardModifier.ControlModifier)
print(f"   {before} -> {bar.value()}, max now {bar.maximum()}")
wheel(120, Qt.KeyboardModifier.ControlModifier)
print(f"   then {bar.value()}, max {bar.maximum()}")

slams = [e for e in events if e[1] == 0 and e[0] > 200]
print(f"\nslams to zero from >200: {len(slams)}")
for prev, val, mx in slams:
    print(f"   {prev} -> {val}  (max was {mx})")
