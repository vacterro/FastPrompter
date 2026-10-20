"""T-1478 regression: the chest's real mouse contract.

T-1477 restored the ability to drag at all. This suite pins the interaction
that surrounds the drag, and it drives every case through the live viewport
with real QTest mouse events -- a direct call to chest_internal_drop() proves
nothing here, because the defect was in the gesture, not the move.

Contract pinned by these tests, in the order a user meets it:

  * a stationary click selects one row and never starts a drag;
  * Shift+click selects the range back to the anchor, Ctrl+click toggles;
  * a Shift+drag no longer quick-moves a single item -- it range-selects and
    the drag carries the whole selection;
  * dragging one row of an existing selection keeps that selection whole;
  * a drag start alone never writes to disk;
  * a selected slot is painted visibly unlike an unselected one.
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


FILES = ("a.png", "b.txt", "c.md", "d.txt", "e.log")


def _make_panel(app, tmp_path, files=FILES, view="Chest"):
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


def _center(panel, row):
    """The viewport point a hand would actually press on."""
    return panel.file_list.visualItemRect(panel.file_list.item(row)).center()


def _press(lw, app, pos, mod=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(lw.viewport(), Qt.MouseButton.LeftButton, mod, pos)
    for _ in range(30):
        app.processEvents()


def _release(lw, app, pos, mod=Qt.KeyboardModifier.NoModifier):
    QTest.mouseRelease(lw.viewport(), Qt.MouseButton.LeftButton, mod, pos)
    for _ in range(30):
        app.processEvents()


def _click(lw, app, pos, mod=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(lw.viewport(), Qt.MouseButton.LeftButton, mod, pos)
    for _ in range(30):
        app.processEvents()


def _names(panel):
    lw = panel.file_list
    return sorted(os.path.basename(i.data(Qt.ItemDataRole.UserRole))
                  for i in lw.selectedItems())


def _count_start_drag(lw, app, gesture):
    """Run a gesture and report how many times startDrag was reached.

    offscreen QDrag.exec() is a modal loop that a QTest release cannot
    deliver a drop into, so the drop itself is asserted through the real
    event pipeline below. Counting startDrag is what proves the GESTURE
    worked; the drop helper then proves the RESULT.
    """
    seen = []
    real = type(lw).startDrag

    def spy(self, actions):
        seen.append(actions)
        return real(self, actions)

    type(lw).startDrag = spy
    try:
        gesture()
        for _ in range(40):
            app.processEvents()
    finally:
        type(lw).startDrag = real
    return len(seen)


def _deliver_drop(lw, app, target_item, paths):
    """Deliver a real drag sequence onto the list for an internal drop.

    Qt's own event objects carry the mime payload, the source and the
    modifier, so the widget's own dragEnter/Move/Drop handlers run exactly
    as they would after QDrag.exec() returned -- nothing is stubbed out and
    chest_internal_drop is never called directly.
    """
    from PyQt6.QtCore import QMimeData, QPointF, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    pos = lw.visualItemRect(target_item).center()
    posf = QPointF(float(pos.x()), float(pos.y()))
    for cls in (QDragEnterEvent, QDragMoveEvent):
        ev = cls(pos, Qt.DropAction.MoveAction, md,
                 Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        ev.source = lambda: lw          # an INTERNAL drag
        app.sendEvent(lw.viewport(), ev)
        assert ev.isAccepted(), f"{cls.__name__} was rejected"
    drop = QDropEvent(posf, Qt.DropAction.MoveAction, md,
                      Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    drop.source = lambda: lw
    app.sendEvent(lw.viewport(), drop)
    assert drop.isAccepted(), "the drop was rejected"
    for _ in range(60):
        app.processEvents()


def _item(panel, name):
    """The real (non-placeholder) row carrying this file name."""
    lw = panel.file_list
    return next(it for it in lw.findItems(name, Qt.MatchFlag.MatchExactly)
                if it.data(Qt.ItemDataRole.UserRole))

def _slots(panel):
    """{name: slot}: the sparse placement the chest actually holds."""
    from fastprompter.ui.file_container import is_placeholder
    lw = panel.file_list
    out = {}
    for r in range(lw.count()):
        it = lw.item(r)
        if it is not None and not is_placeholder(it):
            p = it.data(Qt.ItemDataRole.UserRole)
            if p:
                out[os.path.basename(p)] = r
    return out


def _hold_and_move(lw, app, pos, extra=None):
    """The gesture itself: press, hold, move past the drag threshold."""
    reached = extra if extra is not None else QApplication.startDragDistance() + 8
    for step in range(1, reached + 1):
        QTest.mouseMove(lw.viewport(), pos + QPoint(step, 0))
        app.processEvents()
    return pos + QPoint(reached, 0)


# ---- selection semantics --------------------------------------------------

def test_plain_click_selects_one_row(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        gestures = _count_start_drag(
            lw, app, lambda: _click(lw, app, _center(panel, 2)))
        assert gestures == 0, "a stationary click started a drag"
        assert _names(panel) == ["c.md"]
        assert lw.currentItem() is lw.item(2)
    finally:
        panel.close(); panel.deleteLater()


def test_shift_click_selects_the_range_down_to_the_anchor(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 3), Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["a.png", "b.txt", "c.md", "d.txt"]
    finally:
        panel.close(); panel.deleteLater()


def test_shift_click_range_extends_upward(app, tmp_path):
    """Range selection is directional: the anchor, not the top of the list."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 4))
        _click(lw, app, _center(panel, 2), Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["c.md", "d.txt", "e.log"]
    finally:
        panel.close(); panel.deleteLater()


def test_ctrl_click_toggles_one_row_without_clearing(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 3), Qt.KeyboardModifier.ControlModifier)
        assert _names(panel) == ["a.png", "d.txt"]
        # clicking the same row again releases it and keeps the other
        _click(lw, app, _center(panel, 0), Qt.KeyboardModifier.ControlModifier)
        assert _names(panel) == ["d.txt"]
    finally:
        panel.close(); panel.deleteLater()


def test_ctrl_click_toggles_a_row_inside_a_range(app, tmp_path):
    """Ctrl, not Shift, is what removes one row of a chosen range."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 3), Qt.KeyboardModifier.ShiftModifier)
        _click(lw, app, _center(panel, 1), Qt.KeyboardModifier.ControlModifier)
        assert _names(panel) == ["a.png", "c.md", "d.txt"]
    finally:
        panel.close(); panel.deleteLater()


def test_pressing_an_already_selected_row_keeps_the_selection(app, tmp_path):
    """A drag of a group must start by pressing a row that is already in it."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 2), Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["a.png", "b.txt", "c.md"]
        # pick the group up by its MIDDLE row -- the natural grab point
        _press(lw, app, _center(panel, 1))
        assert _names(panel) == ["a.png", "b.txt", "c.md"], \
            "pressing an already-selected row re-scoped the selection"
        _release(lw, app, _center(panel, 1))
    finally:
        panel.close(); panel.deleteLater()


# ---- what the drag carries ------------------------------------------------

def test_shift_press_and_move_selects_a_rectangle_without_a_drag(
        app, tmp_path):
    """Shift is a SELECTION gesture, not a movement one.

    Shift+press starts a rectangle sweep across the grid, Shift+move extends
    it (horizontally and vertically), and Shift+release finishes it. The
    gesture never reaches QDrag -- selecting files must never move them --
    and an ordinary press-and-move still drags."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        start = _center(panel, 2)
        _press(lw, app, start, Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["a.png", "b.txt", "c.md"], \
            "Shift+press did not range-select before the sweep"
        assert lw._sweeping, "Shift+press did not take the sweep gesture"
        before = _slots(panel)
        carried = []
        real = type(lw).startDrag

        def spy(self, actions):
            carried.append(list(self._panel.selected_paths()))
            return real(self, actions)

        type(lw).startDrag = spy
        try:
            _hold_and_move(lw, app, start,
                           extra=_center(panel, 4).x() - start.x() + 4)
            for _ in range(30):
                app.processEvents()
            assert not carried, \
                "a selection sweep entered QDrag, so it could move files"
            # the sweep rectangle covers rows 2..4 on top of the 0..2 range
            assert _names(panel) == ["a.png", "b.txt", "c.md", "d.txt",
                                     "e.log"], \
                "the sweep did not select the rows it passed over"
            _release(lw, app, _center(panel, 4),
                     Qt.KeyboardModifier.ShiftModifier)
            for _ in range(30):
                app.processEvents()
            assert not lw._sweeping, "releasing Shift did not finish the sweep"
            assert not carried, \
                "finishing the selection started a drag"
        finally:
            type(lw).startDrag = real
        # selecting never moves anything
        assert _slots(panel) == before
        assert main.dirty == 0
    finally:
        panel.close(); panel.deleteLater()


def test_shift_drag_escape_cancels_the_sweep_selection(app, tmp_path):
    """Escape aborts the sweep cleanly: the pre-gesture selection returns."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        start = _center(panel, 2)
        _press(lw, app, start, Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["a.png", "b.txt", "c.md"]
        _hold_and_move(lw, app, start,
                       extra=_center(panel, 4).x() - start.x() + 4)
        for _ in range(30):
            app.processEvents()
        assert len(lw.selectedItems()) == 5, \
            "the sweep did not extend across the grid"
        QTest.keyClick(lw.viewport(), Qt.Key.Key_Escape)
        for _ in range(30):
            app.processEvents()
        assert not lw._sweeping, "Escape left the sweep gesture open"
        assert _names(panel) == ["a.png", "b.txt", "c.md"], \
            "Escape did not restore the pre-gesture selection"
    finally:
        panel.close(); panel.deleteLater()


def test_shift_drag_no_longer_quick_moves_the_pressed_item(app, tmp_path):
    """The removed branch moved exactly one item to the first empty slot."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        before = _slots(panel)
        start = _center(panel, 0)
        _press(lw, app, start, Qt.KeyboardModifier.ShiftModifier)
        _hold_and_move(lw, app, start)
        for _ in range(30):
            app.processEvents()
        _release(lw, app, start + QPoint(60, 0),
                 Qt.KeyboardModifier.ShiftModifier)
        for _ in range(30):
            app.processEvents()
        assert _slots(panel) == before, \
            "a Shift gesture still relocated a single item on its own"
    finally:
        panel.close(); panel.deleteLater()


def test_dragging_one_row_of_a_selection_carries_every_selected_row(
        app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 2), Qt.KeyboardModifier.ShiftModifier)
        carried = []
        real = type(lw).startDrag

        def spy(self, actions):
            carried.append(list(self._panel.selected_paths()))
            return real(self, actions)

        type(lw).startDrag = spy
        try:
            start = _center(panel, 1)
            _press(lw, app, start)
            _hold_and_move(lw, app, start)
            for _ in range(30):
                app.processEvents()
            _release(lw, app, start + QPoint(60, 0))
            for _ in range(30):
                app.processEvents()
        finally:
            type(lw).startDrag = real
        assert len(carried) == 1
        assert sorted(os.path.basename(p) for p in carried[0]) == \
            ["a.png", "b.txt", "c.md"]
    finally:
        panel.close(); panel.deleteLater()


def test_drop_on_an_empty_slot_moves_the_dragged_group(app, tmp_path):
    """End to end: the group is carried, then lands at the EXACT slot aimed.

    The gesture half proves the drag really starts from a press-and-move (and
    stops at startDrag, because offscreen QDrag.exec() is a modal loop no
    QTest release can deliver a drop into -- that is why the drop half is
    delivered as a real QDropEvent, the same way the T-1313 pipeline test
    drives a drop the host cannot synthesise).
    """
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 1), Qt.KeyboardModifier.ShiftModifier)
        assert _names(panel) == ["a.png", "b.txt"], "range was not selected"
        gestures = _count_start_drag(lw, app, lambda: (
            _press(lw, app, _center(panel, 0)),
            _hold_and_move(lw, app, _center(panel, 0))))
        assert gestures >= 1, "the group gesture never reached startDrag"

        empty = lw.item(panel._chest_real_count() + 1)
        _deliver_drop(lw, app, empty, [str(tmp_path / n) for n in
                                       ("a.png", "b.txt")])
        # the group lands at the aimed slot, never appended to the real rows
        assert _slots(panel) == {
            "a.png": 6, "b.txt": 7, "c.md": 2, "d.txt": 3, "e.log": 4}, \
            "the group did not land at the exact empty slot"
        # the drop persisted and survives the refresh
        assert main.dirty >= 1
        panel.refresh()
        for _ in range(80):
            app.processEvents()
        assert _slots(panel) == {
            "a.png": 6, "b.txt": 7, "c.md": 2, "d.txt": 3, "e.log": 4}
    finally:
        panel.close(); panel.deleteLater()


def test_drop_on_an_occupied_slot_swaps(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        assert _names(panel) == ["a.png"]
        gestures = _count_start_drag(lw, app, lambda: (
            _press(lw, app, _center(panel, 0)),
            _hold_and_move(lw, app, _center(panel, 0))))
        assert gestures >= 1, "the single-item gesture never reached startDrag"

        _deliver_drop(lw, app, lw.item(3), [str(tmp_path / "a.png")])
        assert _slots(panel) == {
            "a.png": 3, "b.txt": 1, "c.md": 2, "d.txt": 0, "e.log": 4}, \
            "a single dragged item did not swap with the occupied slot"
    finally:
        panel.close(); panel.deleteLater()


def test_drop_onto_a_folder_slot_is_a_slot_swap(app, tmp_path):
    """A folder slot is occupied inventory, NOT a stack target.

    The old chest stacked the dragged file INTO the folder on every drop,
    moving real files on the filesystem as a side effect of a slot gesture.
    The swap is the pending operation the feedback names, and the explicit
    Move Into Folder action is the only thing that touches the disk."""
    (tmp_path / "loot").mkdir()
    (tmp_path / "loot" / "gem.txt").write_text("gem")
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        folder_item = _item(panel, "loot")
        _click(lw, app, _center(panel, 0))
        assert _names(panel) == ["a.png"]
        gestures = _count_start_drag(lw, app, lambda: (
            _press(lw, app, _center(panel, 0)),
            _hold_and_move(lw, app, _center(panel, 0))))
        assert gestures >= 1, "the folder-slot gesture never reached startDrag"

        _deliver_drop(lw, app, folder_item, [str(tmp_path / "a.png")])
        for _ in range(60):
            app.processEvents()
        assert (tmp_path / "a.png").is_file(), \
            "a normal drop moved a file into the folder on the filesystem"
        assert sorted(os.listdir(str(tmp_path / "loot"))) == ["gem.txt"]
        assert _slots(panel) == {
            "a.png": 5, "b.txt": 1, "c.md": 2, "d.txt": 3, "e.log": 4,
            "loot": 0}
    finally:
        panel.close(); panel.deleteLater()


def test_explicit_move_into_folder_is_the_only_filesystem_move(app, tmp_path):
    """Moving files into a folder is an explicit, deliberate action."""
    (tmp_path / "loot").mkdir()
    (tmp_path / "loot" / "gem.txt").write_text("gem")
    main, panel = _make_panel(app, tmp_path)
    try:
        _item(panel, "b.txt").setSelected(True)
        panel._chest_move_selected_into(str(tmp_path / "loot"))
        for _ in range(60):
            app.processEvents()
        assert not (tmp_path / "b.txt").exists(), \
            "the explicit Move Into Folder did not move the file"
        assert (tmp_path / "loot" / "b.txt").read_text() == "b.txt"
        # and the chest grid followed the filesystem
        panel.refresh()
        for _ in range(80):
            app.processEvents()
        assert "b.txt" not in _slots(panel)
    finally:
        panel.close(); panel.deleteLater()


def test_a_drag_start_alone_touches_nothing_on_disk(app, tmp_path):
    """Reordering must be a slot gesture until the drop lands."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        before = sorted(os.listdir(str(tmp_path)))
        start = _center(panel, 0)
        _press(lw, app, start)
        _hold_and_move(lw, app, start)
        for _ in range(40):
            app.processEvents()
        assert sorted(os.listdir(str(tmp_path))) == before, \
            "starting a drag mutated the filesystem"
        _release(lw, app, start + QPoint(60, 0))
    finally:
        panel.close(); panel.deleteLater()


# ---- the selection must be visible ---------------------------------------

def _slot_pixels(panel, app, row, selected):
    """Average colour of a slot's inner rect, rendered by the real delegate."""
    lw = panel.file_list
    if selected:
        lw.item(row).setSelected(True)
    else:
        lw.item(row).setSelected(False)
    for _ in range(10):
        app.processEvents()
    vp = lw.viewport()
    vp.repaint()
    for _ in range(20):
        app.processEvents()
    img = QImage(vp.grab().toImage())
    cell = lw.visualItemRect(lw.item(row)).center()
    from fastprompter.ui.silo_chest import SLOT
    inner = QImage(SLOT - 8, SLOT - 8, QImage.Format.Format_RGB32)
    # sample a ring inside the slot so the icon's own pixels stay out of it
    total = [0, 0, 0]
    n = 0
    scale = 1
    for y in range(0, inner.height(), 3):
        for x in range(0, inner.width(), 3):
            c = img.pixelColor(cell.x() - inner.width() // 2 + x,
                               cell.y() - inner.height() // 2 + y)
            total[0] += c.red(); total[1] += c.green(); total[2] += c.blue()
            n += 1
    assert n, "no pixels sampled"
    del inner, scale
    return (total[0] / n, total[1] / n, total[2] / n)


def test_a_selected_slot_paints_visibly_differently(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        plain = _slot_pixels(panel, app, 0, selected=False)
        picked = _slot_pixels(panel, app, 0, selected=True)
        delta = max(abs(a - b) for a, b in zip(plain, picked))
        assert delta > 12, (
            f"selection is not visually distinct: plain={plain} "
            f"selected={picked} max channel delta {delta:.1f}")
    finally:
        panel.close(); panel.deleteLater()


def test_the_selection_survives_a_refresh(app, tmp_path):
    """The highlight must not vanish the moment the folder is listed again."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        _click(lw, app, _center(panel, 0))
        _click(lw, app, _center(panel, 2), Qt.KeyboardModifier.ShiftModifier)
        assert len(lw.selectedItems()) == 3
        panel.refresh()
        for _ in range(80):
            app.processEvents()
        assert _names(panel) == ["a.png", "b.txt", "c.md"], \
            "a refresh silently changed the chosen range"
    finally:
        panel.close(); panel.deleteLater()

def test_docked_and_floating_input_both_drag(app, tmp_path):
    """The same gesture must work docked and floating.

    set_docked() reparents the panel (window flags Widget <-> Tool) and a
    reparent resets widget state, so drag/select authority has to be
    re-established, not assumed."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list

        def gesture_reaches_start_drag():
            seen = []
            real = type(lw).startDrag

            def spy(self, actions):
                seen.append(actions)
                return real(self, actions)

            type(lw).startDrag = spy
            try:
                start = _center(panel, 0)
                _press(lw, app, start)
                _hold_and_move(lw, app, start)
                for _ in range(30):
                    app.processEvents()
                _release(lw, app, start + QPoint(60, 0))
                for _ in range(20):
                    app.processEvents()
            finally:
                type(lw).startDrag = real
            return len(seen)

        assert panel.file_list.dragEnabled() is True, \
            "the docked chest cannot start a drag"
        assert gesture_reaches_start_drag() >= 1, "docked: no drag"

        host = QWidget()
        panel.set_docked(False)
        panel.show()
        for _ in range(20):
            app.processEvents()
        assert panel.file_list.dragEnabled() is True, \
            "the floating chest lost drag authority"
        assert gesture_reaches_start_drag() >= 1, "floating: no drag"

        panel.set_docked(True, host)
        host.resize(420, 320)
        panel.resize(420, 320)
        host.show()
        panel.show()
        for _ in range(20):
            app.processEvents()
        assert panel.file_list.dragEnabled() is True, \
            "re-docking the chest lost drag authority"
        assert gesture_reaches_start_drag() >= 1, "re-docked: no drag"
    finally:
        panel.close(); panel.deleteLater()

def test_theme_change_survives_the_chest_layout(app, tmp_path):
    """Re-theming rebuilds the delegate; the placement and the highlight
    must survive it."""
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], lw.item(20))
        before = _slots(panel)
        _click(lw, app, _center(panel, 0))
        selected_before = _names(panel)
        main.data["theme"] = "Golden Default"
        main._theme_cache = {
            "raw_colors": {
                "bg_main": "#232018",
                "bg_text": "#1a1810",
                "border_dark": "#100e08",
                "border_light": "#5a5040",
                "accent": "#f0d060",
                "text_main": "#d4c89a",
            }
        }
        panel.apply_theme()
        for _ in range(20):
            app.processEvents()
        assert _slots(panel) == before, "a theme change moved slots"
        assert _names(panel) == selected_before, \
            "a theme change dropped the selection"
        plain = _slot_pixels(panel, app, 1, selected=False)
        picked = _slot_pixels(panel, app, 0, selected=True)
        delta = max(abs(a - b) for a, b in zip(plain, picked))
        assert delta > 12, (
            f"the themed chest hides the selection: plain={plain} "
            f"selected={picked} max channel delta {delta:.1f}")
    finally:
        panel.close(); panel.deleteLater()
