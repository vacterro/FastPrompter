"""T-1477 regression: a real mouse gesture must actually start a drag.

The Chest view's drag machinery was intact and the slot reordering tests were
green, yet nothing happened when a user picked an item up and moved it.
_apply_view_mode sets QListWidget.Movement.Static after __init__ has already
called setDragEnabled(True), and Qt clears dragEnabled when the movement
changes -- so QAbstractItemView's mouseMoveEvent never reached startDrag.

These tests drive a live QListWidget viewport with QTest mouse events and
assert on startDrag itself, never on chest_internal_drop called directly.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget


class _Main(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = dict(data)
        self._current_lang = "EN"
        self.dirty = 0

    def mark_dirty(self):
        self.dirty += 1


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _make_panel(app, tmp_path, files=("a.png", "b.txt", "c.md"),
                view="Chest"):
    from fastprompter.ui.file_container import FileContainerPanel
    for name in files:
        p = tmp_path / name
        if name.endswith(".png"):
            img = QImage(40, 20, QImage.Format.Format_RGB32)
            img.fill(QColor("red"))
            assert img.save(str(p))
        else:
            p.write_text(name)
    main = _Main(file_panel_view=view, silo_chest_slots="64")
    panel = FileContainerPanel(main)
    panel.open_for(str(tmp_path), "t")
    for _ in range(80):
        app.processEvents()
    return main, panel


def _real_item_center(panel, row=0):
    """The viewport point a hand would actually press on."""
    lw = panel.file_list
    rect = lw.visualItemRect(lw.item(row))
    return rect.center()


def _hold_and_move(panel, app, row=0, extra=None):
    """Press a real item, hold it, and move past the drag threshold."""
    lw = panel.file_list
    vp = lw.viewport()
    start = _real_item_center(panel, row)
    qtest_mod = Qt.KeyboardModifier.NoModifier
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, qtest_mod, start)
    for _ in range(30):
        app.processEvents()
    reached = extra if extra is not None else QApplication.startDragDistance() + 8
    for step in range(1, reached + 1):
        QTest.mouseMove(vp, start + QPoint(step, 0))
        app.processEvents()
    return vp, start, reached


def test_plain_click_selects_without_dragging(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        started = []
        real = type(lw).startDrag

        def spy(self, actions):
            started.append(actions)
            return real(self, actions)

        type(lw).startDrag = spy
        try:
            vp = lw.viewport()
            at = _real_item_center(panel, 0)
            QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, at)
            for _ in range(30):
                app.processEvents()
            assert len(started) == 0, "a stationary click must not drag"
            assert len(lw.selectedItems()) == 1, "a click must still select"
        finally:
            type(lw).startDrag = real
    finally:
        panel.close()
        panel.deleteLater()


def test_chest_view_enables_dragging(app, tmp_path):
    """The defect: Static movement silently revoked dragEnabled."""
    main, panel = _make_panel(app, tmp_path, view="Chest")
    try:
        assert panel._view_mode() == "Chest"
        assert panel.file_list.dragEnabled() is True, \
            "setMovement(Static) cleared dragEnabled, so no drag can start"
        assert panel.file_list.acceptDrops() is True
    finally:
        panel.close()
        panel.deleteLater()


def test_list_view_enables_dragging(app, tmp_path):
    main, panel = _make_panel(app, tmp_path, view="List")
    try:
        assert panel._view_mode() == "List"
        assert panel.file_list.dragEnabled() is True
    finally:
        panel.close()
        panel.deleteLater()


def test_icons_view_enables_dragging(app, tmp_path):
    main, panel = _make_panel(app, tmp_path, view="Icons")
    try:
        assert panel._view_mode() == "Icons"
        assert panel.file_list.dragEnabled() is True
    finally:
        panel.close()
        panel.deleteLater()


def test_press_hold_and_move_starts_a_real_drag(app, tmp_path):
    """The gesture the user reported, driven with genuine Qt mouse events."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        started = []
        real = type(lw).startDrag

        def spy(self, actions):
            started.append(actions)
            return real(self, actions)

        type(lw).startDrag = spy
        try:
            vp, _start, _reached = _hold_and_move(panel, app, row=0)
            assert len(started) >= 1, \
                "press-and-move past the drag threshold never called startDrag"
            # the item stays selected through the gesture
            assert len(lw.selectedItems()) >= 1
        finally:
            type(lw).startDrag = real
    finally:
        panel.close()
        panel.deleteLater()


def test_view_cycle_keeps_dragging_enabled(app, tmp_path):
    """Every view the cycle can land in must leave drag enabled."""
    main, panel = _make_panel(app, tmp_path)
    try:
        for _ in range(len(_VIEW_MODES())):
            try:
                panel._cycle_view()
            except Exception:
                pass
            for _ in range(20):
                app.processEvents()
            assert panel.file_list.dragEnabled() is True, \
                f"{panel._view_mode()} view left drag disabled"
    finally:
        panel.close()
        panel.deleteLater()


def _VIEW_MODES():
    from fastprompter.ui.file_container import FileContainerPanel
    return FileContainerPanel._VIEW_MODES


def test_external_drop_is_not_routed_through_the_chest_slot_path(app, tmp_path):
    """An out-of-app Explorer drag must never enter the chest slot machinery.

    Enabling dragging makes an external drop reach _FileList.dropEvent for the
    first time, so the boundary must be pinned: a drop whose source is not this
    list is ignored by the list and left to the panel's import handler, and
    nothing is copied onto the disk by the slot path.
    """
    from PyQt6.QtCore import QMimeData, QPointF, QUrl
    from PyQt6.QtGui import QDropEvent

    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        calls = []
        real_chest = panel.chest_internal_drop

        def chest_spy(paths, target):
            calls.append(("chest", paths))
            return real_chest(paths, target)

        panel.chest_internal_drop = chest_spy
        try:
            outside = tmp_path / "outside.txt"
            outside.write_text("FROM EXPLORER")
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(outside))])
            ev = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
            lw.dropEvent(ev)
            for _ in range(30):
                app.processEvents()
            assert calls == [], \
                "an external drop reached the chest slot reordering path"
            assert lw._chest_internal_drag(ev) is False, \
                "an external drop must not be recognised as an internal drag"
        finally:
            panel.chest_internal_drop = real_chest
    finally:
        panel.close()
        panel.deleteLater()


def test_drag_start_never_moves_files_on_disk(app, tmp_path):
    """Merely dragging must be a visual gesture, not a filesystem mutation.

    The drop-event handle carries mw.mark_dirty() and the folder rename for the
    real move; a drag start alone must not touch any of it. The existing
    T-1313 order-persistence suites cover the opposite half of ATM-05.
    """
    main, panel = _make_panel(app, tmp_path)
    try:
        before = sorted(os.listdir(str(tmp_path)))
        _hold_and_move(panel, app, row=0)
        for _ in range(40):
            app.processEvents()
        assert sorted(os.listdir(str(tmp_path))) == before, \
            "dragging mutated the filesystem"
    finally:
        panel.close()
        panel.deleteLater()

def test_shift_selection_gesture_never_reaches_start_drag(app, tmp_path):
    """The same defect class, split by gesture owner.

    Shift is now a selection gesture: a Shift press-and-move sweeps a
    rectangle across the grid and must NEVER reach startDrag, because a
    selection that drags is how files get moved by accident. An ordinary
    press-and-move still drags, so T-1477's restoration stays intact."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        seen = []
        real = type(lw).startDrag

        def spy(self, actions):
            seen.append(actions)
            return real(self, actions)

        type(lw).startDrag = spy
        try:
            start = _real_item_center(panel, 0)
            QTest.mousePress(lw.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ShiftModifier, start)
            for _ in range(30):
                app.processEvents()
            for step in range(1, QApplication.startDragDistance() + 20):
                QTest.mouseMove(lw.viewport(), start + QPoint(step, 0))
                app.processEvents()
            QTest.mouseRelease(lw.viewport(), Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.ShiftModifier,
                               start + QPoint(QApplication.startDragDistance()
                                              + 20, 0))
            for _ in range(30):
                app.processEvents()
            assert seen == [], \
                "a Shift selection sweep entered the drag machinery"
            assert lw._sweeping is False, "the sweep gesture never finished"
            # the ordinary gesture still drags
            vp, _s, _r = _hold_and_move(panel, app, row=0)
            assert seen, "the ordinary press-and-move no longer drags"
        finally:
            type(lw).startDrag = real
    finally:
        panel.close()
        panel.deleteLater()
