"""Minecraft-chest slot semantics inside the silo file container (T-1313):
drag within the chest swaps occupied slots, moves to empty slots, stacks
files into folder slots, and the dragged order survives refresh + reopen."""
import os

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Main(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = dict(data)
        self._current_lang = "EN"
        self.dirty = 0

    def mark_dirty(self):
        self.dirty += 1


def _settle(app, panel, cycles=80):
    import time
    for _ in range(cycles):
        app.processEvents()
        if getattr(panel, "_refresh_inflight_seq", 1) is None:
            break
        time.sleep(0.01)
    app.processEvents()


def _make_panel(app, tmp_path, files=("a.png", "b.txt", "c.md")):
    from fastprompter.ui.file_container import FileContainerPanel
    for name in files:
        p = tmp_path / name
        if name.endswith(".png"):
            img = QImage(40, 20, QImage.Format.Format_RGB32)
            img.fill(QColor("red"))
            assert img.save(str(p))
        else:
            p.write_text(name)
    main = _Main(file_panel_view="Chest", silo_chest_slots="64")
    panel = FileContainerPanel(main)
    panel.open_for(str(tmp_path), "t")
    _settle(app, panel)
    return main, panel


def _rows(panel):
    lw = panel.file_list
    return [os.path.basename(lw.item(r).data(Qt.ItemDataRole.UserRole))
            for r in range(panel._chest_real_count())]


def _item(panel, name):
    lw = panel.file_list
    return next(lw.item(r) for r in range(panel._chest_real_count())
                if os.path.basename(
                    lw.item(r).data(Qt.ItemDataRole.UserRole)) == name)


def _close(panel):
    panel.close()
    panel.deleteLater()


def test_swap_occupied_slots_persists_through_reopen(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        assert _rows(panel) == ["a.png", "b.txt", "c.md"]
        panel.chest_internal_drop(
            [str(tmp_path / "a.png")], _item(panel, "c.md"))
        assert _rows(panel) == ["c.md", "b.txt", "a.png"]
        order_key = os.path.normcase(os.path.abspath(str(tmp_path)))
        assert main.data["silo_chest_order"][order_key] == [
            "c.md", "b.txt", "a.png"]
        assert main.dirty == 1
        # the watcher/refresh path re-applies the saved order
        panel.refresh()
        _settle(app, panel)
        assert _rows(panel) == ["c.md", "b.txt", "a.png"]
        # a fresh panel over the same folder starts at the saved order
        panel2 = type(panel)(main)
        panel2.open_for(str(tmp_path), "t")
        _settle(app, panel2)
        try:
            assert _rows(panel2) == ["c.md", "b.txt", "a.png"]
        finally:
            _close(panel2)
    finally:
        _close(panel)


def test_move_to_empty_slot_and_multi_insert(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        # drag a onto the first empty slot: it lands after the real files
        lw = panel.file_list
        first_empty = lw.item(panel._chest_real_count())
        panel.chest_internal_drop([str(tmp_path / "a.png")], first_empty)
        assert _rows(panel) == ["b.txt", "c.md", "a.png"]

        # multi-selection insert before an occupied slot
        panel.chest_internal_drop(
            [str(tmp_path / "b.txt"), str(tmp_path / "a.png")],
            _item(panel, "c.md"))
        assert _rows(panel) == ["b.txt", "a.png", "c.md"]

        # drop onto itself / own selection: no-op, nothing saved
        before = dict(main.data.get("silo_chest_order", {}))
        panel.chest_internal_drop([str(tmp_path / "c.md")], _item(panel, "c.md"))
        assert _rows(panel) == ["b.txt", "a.png", "c.md"]
        assert main.data.get("silo_chest_order") == before
    finally:
        _close(panel)


def test_shift_drag_quick_moves_only_pressed_item(app, tmp_path, monkeypatch):
    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        a, b, c = (_item(panel, name) for name in ("a.png", "b.txt", "c.md"))
        lw.setCurrentItem(a)
        lw.clearSelection()
        a.setSelected(True)
        b.setSelected(True)
        c.setSelected(True)
        assert lw.currentItem() is a
        assert {item.data(Qt.ItemDataRole.UserRole)
                for item in lw.selectedItems()} == {
                    str(tmp_path / "a.png"), str(tmp_path / "b.txt"),
                    str(tmp_path / "c.md")}

        monkeypatch.setattr(
            QApplication, "keyboardModifiers",
            lambda: Qt.KeyboardModifier.ShiftModifier,
        )
        from fastprompter.ui import file_container

        def _unexpected_qdrag(*_args, **_kwargs):
            pytest.fail("Shift quick-move must not enter QDrag")

        monkeypatch.setattr(file_container, "QDrag", _unexpected_qdrag)
        lw.startDrag(Qt.DropAction.MoveAction)

        assert _rows(panel) == ["b.txt", "c.md", "a.png"]
        order_key = os.path.normcase(os.path.abspath(str(tmp_path)))
        assert main.data["silo_chest_order"][order_key] == [
            "b.txt", "c.md", "a.png"]
        assert main.dirty == 1
    finally:
        _close(panel)


def test_shift_drag_full_chest_is_noop(app, tmp_path, monkeypatch):
    from fastprompter.ui.file_container import FileContainerPanel

    main = _Main(file_panel_view="Chest", silo_chest_slots="64")
    panel = FileContainerPanel(main)
    for index in range(64):
        (tmp_path / f"{index:02}.txt").write_text(str(index))
    panel.open_for(str(tmp_path), "t")
    _settle(app, panel)
    try:
        from fastprompter.ui import file_container

        monkeypatch.setattr(
            QApplication, "keyboardModifiers",
            lambda: Qt.KeyboardModifier.ShiftModifier,
        )

        def _unexpected_qdrag(*_args, **_kwargs):
            pytest.fail("full-chest Shift quick-move must be a no-op")

        monkeypatch.setattr(file_container, "QDrag", _unexpected_qdrag)
        first_item = panel.file_list.item(0)
        panel.file_list.setCurrentItem(first_item)
        first_item.setSelected(True)
        assert panel.file_list.currentItem() is first_item
        before = _rows(panel)
        panel.file_list.startDrag(Qt.DropAction.MoveAction)
        assert _rows(panel) == before
        assert main.dirty == 0
    finally:
        _close(panel)


def test_stack_file_onto_folder_slot(app, tmp_path):
    sub = tmp_path / "loot"
    sub.mkdir()
    (sub / "gem.txt").write_text("gem")
    (sub / "b.txt").write_text("old")
    main, panel = _make_panel(
        app, tmp_path, files=("a.png", "b.txt"))
    try:
        assert _rows(panel) == ["a.png", "b.txt", "loot"]
        # b.txt already exists inside the folder -> collision rename
        (tmp_path / "b.txt").write_text("b2")
        panel.chest_internal_drop(
            [str(tmp_path / "b.txt")], _item(panel, "loot"))
        panel.refresh()
        _settle(app, panel)
        assert _rows(panel) == ["a.png", "loot"]
        assert os.path.isfile(sub / "b (2).txt")
        assert (sub / "b (2).txt").read_text() == "b2"
        assert not os.path.exists(tmp_path / "b.txt")
        # the stack count badge source reflects the merged entries
        from fastprompter.ui.silo_chest import folder_badge
        assert folder_badge(str(sub)) == "3"
    finally:
        _close(panel)


def test_saved_order_drops_vanished_names_and_appends_new(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], _item(panel, "a.png"))
        assert _rows(panel) == ["a.png", "b.txt", "c.md"][::-1] == [
            "c.md", "b.txt", "a.png"]
        os.remove(tmp_path / "b.txt")
        (tmp_path / "d.txt").write_text("d")
        panel.refresh()
        _settle(app, panel)
        # gone name ignored, unranked new file lands after the ranked ones
        assert _rows(panel) == ["c.md", "a.png", "d.txt"]
    finally:
        _close(panel)


def test_real_qt_drag_and_drop_event_pipeline(app, tmp_path):
    from PyQt6.QtCore import QMimeData, QPointF, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        target_item = _item(panel, "c.md")
        target_pos = lw.visualItemRect(target_item).center()

        src_file = str(tmp_path / "a.png")
        # Simulate Qt MIME data which normalizes to forward slashes on Windows
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(src_file)])

        enter = QDragEnterEvent(
            target_pos, Qt.DropAction.MoveAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        enter.source = lambda: lw
        app.sendEvent(lw.viewport(), enter)
        assert enter.isAccepted()

        move = QDragMoveEvent(
            target_pos, Qt.DropAction.MoveAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        move.source = lambda: lw
        app.sendEvent(lw.viewport(), move)
        assert move.isAccepted()
        assert getattr(lw, "_drag_hover_item", None) is target_item

        drop = QDropEvent(
            QPointF(target_pos), Qt.DropAction.MoveAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        drop.source = lambda: lw
        app.sendEvent(lw.viewport(), drop)
        assert drop.isAccepted()
        assert getattr(lw, "_drag_hover_item", None) is None

        # Slots must have swapped!
        assert _rows(panel) == ["c.md", "b.txt", "a.png"]
    finally:
        _close(panel)
