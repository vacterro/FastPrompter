"""T-555 hypothesis 3: a fold leaves the scrollbar range stale.

The captured stack is SHORT - between super().wheelEvent and
_watch_scroll_reset there is not one python frame - so the range collapsed
inside Qt, synchronously, during its own wheel handling.

QPlainTextEdit lays blocks out lazily and treats the scrollbar maximum as
an estimate it corrects as blocks are laid out. Folding hides blocks, so
the document can be far shorter than the estimate. Wheel, Qt re-lays out,
discovers the real height, max collapses, value clamps to 0 - and the view
snaps to the top.
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "src")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication


def FLUSHPRINT(*a, **k):
    k["flush"] = True
    __builtins__.print(*a, **k)


import fastprompter.core.state as state_mod

tmp = tempfile.mkdtemp(prefix="fold_")
state_mod.get_db_path = lambda pid=1: os.path.join(tmp, f"f_{pid}.db")
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

# a document with fold anchors: headers with bodies under them
lines = []
for h in range(int(os.environ.get("HEADERS", "6"))):
    lines.append(f"# Header {h}")
    lines += [f"  body line {h}.{i}" for i in range(14)]
ta.setPlainText("\n".join(lines))
app.processEvents()

bar = ta.verticalScrollBar()
slams = []
bar.valueChanged.connect(
    lambda v: slams.append((ta._last_scroll_value, v, bar.maximum())))


def wheel(dy):
    pos = QPointF(ta.width() / 2, ta.height() / 2)
    QApplication.sendEvent(ta.viewport(), QWheelEvent(
        pos, ta.mapToGlobal(pos.toPoint()).toPointF(), QPoint(0, 0),
        QPoint(0, dy), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    app.processEvents()


FLUSHPRINT(f"unfolded range 0..{bar.maximum()}  blocks={ta.document().blockCount()}")

doc = ta.document()
folded = 0
block = doc.firstBlock()
while block.isValid():
    if ta._is_fold_anchor(block):
        ta.toggle_fold(block)
        folded += 1
    block = block.next()
app.processEvents()

FLUSHPRINT(f"after folding {folded} anchors: range 0..{bar.maximum()}")
vis = 0
b = doc.firstBlock()
while b.isValid():
    if b.isVisible():
        vis += 1
    b = b.next()
FLUSHPRINT(f"visible blocks now: {vis} of {doc.blockCount()}")

bar.setValue(bar.maximum())
app.processEvents()
FLUSHPRINT(f"parked at {bar.value()} (max {bar.maximum()})")

slams.clear()
for dy in (-120, -120, 120, -120):
    wheel(dy)

FLUSHPRINT(f"value now {bar.value()}, max {bar.maximum()}")
hits = [s for s in slams if s[1] == 0 and s[0] > 200]
FLUSHPRINT(f"\nslams to zero from >200: {len(hits)}")
for prev, val, mx in hits:
    FLUSHPRINT(f"   {prev} -> {val}  (max {mx})")
if not hits and slams:
    FLUSHPRINT("  transitions seen:", slams[:6])
