"""Minecraft-chest slot semantics inside the silo file container (T-1313):
the chest stores SPARSE slot positions -- a dragged file lands exactly on
the slot it was dropped on, gaps stay drawn as empty slots, and the whole
layout survives refresh + reopen. A folder slot is an occupied inventory
slot like any other; moving files into a folder is the explicit context
menu action, never an accidental side effect of a drag."""
import os

import pytest
from PyQt6.QtCore import QPointF, Qt
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

def _slot_of(panel):
    """{name: slot} for every real row: the persisted sparse layout."""
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

def _rows(panel):
    names = _slot_of(panel)
    return [name for slot, name in sorted(
        (s, n) for n, s in names.items())]

def _row_of(panel, name):
    return _slot_of(panel)[name]

def _item(panel, name):
    from fastprompter.ui.file_container import is_placeholder
    lw = panel.file_list
    return next(lw.item(r) for r in range(lw.count())
                if lw.item(r) is not None
                and not is_placeholder(lw.item(r))
                and os.path.basename(
                    lw.item(r).data(Qt.ItemDataRole.UserRole)) == name)

def _empty(panel, slot):
    """The placeholder that physically occupies a slot."""
    from fastprompter.ui.file_container import is_placeholder
    lw = panel.file_list
    it = lw.item(slot)
    assert it is not None and is_placeholder(it)
    return it

def _close(panel):
    panel.close()
    panel.deleteLater()

def test_swap_occupied_slots_persists_through_reopen(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        assert _slot_of(panel) == {"a.png": 0, "b.txt": 1, "c.md": 2}
        panel.chest_internal_drop(
            [str(tmp_path / "a.png")], _item(panel, "c.md"))
        assert _slot_of(panel) == {"c.md": 0, "b.txt": 1, "a.png": 2}
        order_key = os.path.normcase(os.path.abspath(str(tmp_path)))
        assert main.data["silo_chest_order"][order_key] == {
            "a.png": 2, "b.txt": 1, "c.md": 0}
        assert main.dirty == 1
        # the watcher/refresh path re-applies the saved sparse placement
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == {"c.md": 0, "b.txt": 1, "a.png": 2}
        # a fresh panel over the same folder starts at the saved placement
        panel2 = type(panel)(main)
        panel2.open_for(str(tmp_path), "t")
        _settle(app, panel2)
        try:
            assert _slot_of(panel2) == {"c.md": 0, "b.txt": 1, "a.png": 2}
        finally:
            _close(panel2)
    finally:
        _close(panel)

def test_drop_on_empty_slot_uses_the_exact_slot(app, tmp_path):
    """The defect class: dropping onto empty slot 20 must land on slot 20.

    The old code clamped the target row to the highest real row and then
    compacted, so the file appended after the others instead of using the
    slot the hand aimed at."""
    main, panel = _make_panel(app, tmp_path)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "a.png")], _empty(panel, 20))
        assert _slot_of(panel) == {"a.png": 20, "b.txt": 1, "c.md": 2}, \
            "the file did not land on the exact target slot"
        # slot 0 (vacated by a.png) is a real, drawn empty slot
        assert _rows(panel) == ["b.txt", "c.md", "a.png"]
        # gap placeholders below slot 20 are held in the grid
        assert panel.file_list.count() >= 21
        # and it all survives refresh + reopen without compaction
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == {"a.png": 20, "b.txt": 1, "c.md": 2}
        panel2 = type(panel)(main)
        panel2.open_for(str(tmp_path), "t")
        _settle(app, panel2)
        try:
            assert _slot_of(panel2) == {"a.png": 20, "b.txt": 1, "c.md": 2}
        finally:
            _close(panel2)
    finally:
        _close(panel)

def test_group_drop_into_empty_positions(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "b.txt"), str(tmp_path / "c.md")],
            _empty(panel, 10))
        # the group lands at 10,11 in dragged order, relative order intact
        assert _slot_of(panel) == {"b.txt": 10, "c.md": 11, "a.png": 0}
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == {"b.txt": 10, "c.md": 11, "a.png": 0}
    finally:
        _close(panel)

def test_group_drop_onto_occupied_range_cascades_deterministically(
        app, tmp_path):
    """A group dropped over an occupied range displaces those rows upward.

    Determinism matters more than cleverness: the group takes the exact
    target range and every displaced row lands on the next free slot at or
    after the group's end, in one order. Nothing is dropped or compacted."""
    main, panel = _make_panel(app, tmp_path, files=(
        "a.png", "b.txt", "c.md", "d.txt"))
    try:
        # drag [d, a] onto the occupied slot 1 (b.txt)
        panel.chest_internal_drop(
            [str(tmp_path / "d.txt"), str(tmp_path / "a.png")],
            _item(panel, "b.txt"))
        assert _slot_of(panel) == {
            "d.txt": 1, "a.png": 2, "b.txt": 3, "c.md": 4}
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == {
            "d.txt": 1, "a.png": 2, "b.txt": 3, "c.md": 4}
    finally:
        _close(panel)

def test_drop_on_own_selection_is_a_noop(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], _item(panel, "c.md"))
        assert _slot_of(panel) == {"a.png": 0, "b.txt": 1, "c.md": 2}
        assert main.data.get("silo_chest_order") is None, \
            "a no-op drop persisted a placement change"
    finally:
        _close(panel)

def test_folder_slot_drop_is_an_inventory_swap_not_a_filesystem_move(
        app, tmp_path):
    """A folder slot is occupied inventory: a normal drop swaps slots.

    The old chest stacked the dragged file INTO the folder on every drop,
    moving real files on disk as a side effect of a slot gesture. Moving
    into a folder is now the explicit context-menu action only."""
    sub = tmp_path / "loot"
    sub.mkdir()
    (sub / "gem.txt").write_text("gem")
    main, panel = _make_panel(app, tmp_path, files=("a.png", "b.txt"))
    try:
        assert _slot_of(panel) == {"a.png": 0, "b.txt": 1, "loot": 2}
        panel.chest_internal_drop(
            [str(tmp_path / "b.txt")], _item(panel, "loot"))
        assert _slot_of(panel) == {"a.png": 0, "loot": 1, "b.txt": 2}
        assert (tmp_path / "b.txt").is_file(), \
            "a normal drop moved a file on the filesystem"
        assert sorted(os.listdir(str(sub))) == ["gem.txt"]
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == {"a.png": 0, "loot": 1, "b.txt": 2}
    finally:
        _close(panel)

def test_explicit_move_into_folder_performs_the_move(app, tmp_path):
    sub = tmp_path / "loot"
    sub.mkdir()
    (sub / "gem.txt").write_text("gem")
    (sub / "b.txt").write_text("old")
    main, panel = _make_panel(app, tmp_path, files=("a.png", "b.txt"))
    try:
        # select b.txt and take the explicit Move Into Folder action
        _item(panel, "b.txt").setSelected(True)
        panel._chest_move_selected_into(str(sub))
        for _ in range(60):
            app.processEvents()
        assert not (tmp_path / "b.txt").exists()
        assert (sub / "b (2).txt").read_text() == "b.txt", \
            "the collision rename lost the dragged file's content"
        panel.refresh()
        _settle(app, panel)
        assert "b.txt" not in _slot_of(panel)
        assert "loot" in _slot_of(panel)
    finally:
        _close(panel)

def test_explicit_move_into_folder_refuses_targets_outside_the_silo(
        app, tmp_path):
    sub = tmp_path / "loot"
    sub.mkdir()
    outside = tmp_path.parent / "chest_outside_silo"
    outside.mkdir(exist_ok=True)
    (outside / "keep.txt").write_text("keep")
    main, panel = _make_panel(app, tmp_path, files=("a.png", "b.txt"))
    try:
        _item(panel, "b.txt").setSelected(True)
        panel._chest_move_selected_into(str(outside))
        for _ in range(60):
            app.processEvents()
        assert (tmp_path / "b.txt").is_file(), \
            "an explicit move escaped the silo folder"
        assert sorted(os.listdir(str(outside))) == ["keep.txt"]
    finally:
        _close(panel)

def test_explicit_move_into_folder_refuses_own_descendant(app, tmp_path):
    sub = tmp_path / "loot"
    sub.mkdir()
    main, panel = _make_panel(app, tmp_path, files=("a.png", "b.txt"))
    try:
        # moving the folder into its own child is impossible and refused
        _item(panel, "loot").setSelected(True)
        panel._chest_move_selected_into(str(sub))
        for _ in range(60):
            app.processEvents()
        assert (sub).is_dir()
        assert (tmp_path / "loot").is_dir(), "the folder was moved into itself"
        assert "loot" in _slot_of(panel)
    finally:
        _close(panel)

def test_saved_placement_drops_vanished_names_and_appends_new(app, tmp_path):
    main, panel = _make_panel(app, tmp_path)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], _empty(panel, 20))
        assert _slot_of(panel) == {"a.png": 0, "b.txt": 1, "c.md": 20}
        os.remove(tmp_path / "b.txt")
        (tmp_path / "d.txt").write_text("d")
        panel.refresh()
        _settle(app, panel)
        # the vanished name's slot is freed, and the new file appends ABOVE
        # the highest placement: no compaction toward slot 0
        assert _slot_of(panel) == {"a.png": 0, "c.md": 20, "d.txt": 21}
    finally:
        _close(panel)

def test_shrinking_capacity_never_discards_a_placed_slot(app, tmp_path):
    main, panel = _make_panel(app, tmp_path, files=(
        "a.png", "b.txt", "c.md", "d.txt"))
    # rebuild the same panel at the larger capacity so slots 70/100 exist
    _close(panel)
    from fastprompter.ui.file_container import FileContainerPanel
    main = _Main(file_panel_view="Chest", silo_chest_slots="128")
    panel = FileContainerPanel(main)
    panel.open_for(str(tmp_path), "t")
    _settle(app, panel)
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], _empty(panel, 100))
        panel.chest_internal_drop(
            [str(tmp_path / "d.txt")], _empty(panel, 70))
        assert _slot_of(panel) == {
            "a.png": 0, "b.txt": 1, "c.md": 100, "d.txt": 70}
        panel.set_chest_slots(64)
        panel.refresh()
        _settle(app, panel)
        # every placed item survives, the grid simply overflows, and the
        # count label says so instead of silently dropping anything
        assert _slot_of(panel) == {
            "a.png": 0, "b.txt": 1, "c.md": 100, "d.txt": 70}
        assert panel.lbl_count.text() == "4/64"
    finally:
        _close(panel)

def test_full_chest_group_drag_moves_the_selection_without_touching_rows(
        app, tmp_path, monkeypatch):
    """A full chest is exactly when a user grabs several slots and moves
    them: starting the drag relocates nothing, and the payload is the whole
    selection."""
    from fastprompter.ui.file_container import FileContainerPanel

    main = _Main(file_panel_view="Chest", silo_chest_slots="64")
    panel = FileContainerPanel(main)
    for index in range(64):
        (tmp_path / f"{index:02}.txt").write_text(str(index))
    panel.open_for(str(tmp_path), "t")
    _settle(app, panel)
    try:
        lw = panel.file_list
        lw.item(0).setSelected(True)
        lw.item(1).setSelected(True)
        lw.item(2).setSelected(True)
        before = _slot_of(panel)

        from fastprompter.ui import file_container

        entered = []
        carried = []
        real_qdrag = file_container.QDrag

        def _recording_qdrag(*_args, **_kwargs):
            entered.append(1)
            drag = real_qdrag(*_args, **_kwargs)
            real_set = drag.setMimeData

            def _record(md):
                carried.extend(sorted(os.path.basename(u.toLocalFile())
                                      for u in md.urls() if u.isLocalFile()))
                return real_set(md)

            drag.setMimeData = _record
            return drag

        monkeypatch.setattr(file_container, "QDrag", _recording_qdrag)
        lw.startDrag(Qt.DropAction.MoveAction)

        assert entered, \
            "a full chest refused the drag, so the group could not be moved"
        assert _slot_of(panel) == before, \
            "starting the drag relocated slots in a full chest"
        assert main.dirty == 0
        assert carried == ["00.txt", "01.txt", "02.txt"]
    finally:
        _close(panel)

def test_shift_press_never_enters_qdrag(app, tmp_path, monkeypatch):
    """Shift is a SELECTION gesture now, not a movement one.

    Shift+press starts a rectangle sweep and the release finishes it, so a
    selection-only gesture never reaches QDrag: selecting must not move
    anything. The gesture itself is driven end-to-end by
    test_chest_input_state_t1478; here the authority boundary is pinned by
    driving the sweep state directly through the list's own event handlers.
    """
    from fastprompter.ui import file_container

    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        entered = []
        real_qdrag = file_container.QDrag

        def _recording_qdrag(*_args, **_kwargs):
            entered.append(1)
            return real_qdrag(*_args, **_kwargs)

        monkeypatch.setattr(file_container, "QDrag", _recording_qdrag)
        before = _slot_of(panel)
        try:
            lw._sweep_begin(lw.visualItemRect(lw.item(0)).center(), False)
            assert lw._sweeping, "Shift+press did not take the sweep gesture"
            # a sweep move past the drag threshold must NOT start a drag
            lw.mouseMoveEvent(_FakeMove(
                lw, lw.visualItemRect(lw.item(2)).center()))
            for _ in range(30):
                app.processEvents()
            assert not entered, \
                "a selection sweep entered QDrag, so it could move files"
            lw._sweep_end()
            lw.startDrag(Qt.DropAction.MoveAction)
        finally:
            monkeypatch.setattr(file_container, "QDrag", real_qdrag)
        assert entered, "an ordinary drag must still reach QDrag"
        assert _slot_of(panel) == before, \
            "selecting slots relocated them"
    finally:
        _close(panel)

class _FakeMove:
    """A minimal QMouseEvent stand-in carrying the gesture position."""

    def __init__(self, lw, pos):
        self._pos = QPointF(float(pos.x()), float(pos.y()))

    def position(self):
        return self._pos

    def modifiers(self):
        return Qt.KeyboardModifier.ShiftModifier

    def buttons(self):
        return Qt.MouseButton.LeftButton

    def accept(self):
        pass

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
        # the hover feedback names the PENDING OPERATION, not just "valid"
        assert lw._drag_hover_kind == "swap"

        drop = QDropEvent(
            QPointF(target_pos), Qt.DropAction.MoveAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        drop.source = lambda: lw
        app.sendEvent(lw.viewport(), drop)
        assert drop.isAccepted()
        assert getattr(lw, "_drag_hover_item", None) is None

        # Slots must have swapped!
        assert _slot_of(panel) == {"a.png": 2, "b.txt": 1, "c.md": 0}
    finally:
        _close(panel)

def test_hover_feedback_names_the_empty_swap_and_invalid_targets(app, tmp_path):
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent

    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(tmp_path / "a.png"))])

        def hover(item):
            """One real drag-move step over a slot.

            The enter comes first, exactly as a live drag produces it: Qt
            only routes drag-move events into the viewport once the drag is
            over the widget."""
            pos = lw.visualItemRect(item).center()
            enter = QDragEnterEvent(
                pos, Qt.DropAction.MoveAction, md,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            enter.source = lambda: lw
            app.sendEvent(lw.viewport(), enter)
            assert enter.isAccepted(), "the chest refused a valid drag"
            ev = QDragMoveEvent(pos,
                                Qt.DropAction.MoveAction, md,
                                Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            ev.source = lambda: lw
            app.sendEvent(lw.viewport(), ev)
            return ev.isAccepted(), lw._drag_hover_kind

        ok, kind = hover(_empty(panel, 30))
        assert ok and kind == "empty", "an empty slot is not a valid target"
        ok, kind = hover(_item(panel, "b.txt"))
        assert ok and kind == "swap", "an occupied slot is not a swap target"
        # dragging the selection onto itself is a no-op, not a "valid drop":
        # the event may stay accepted, but the feedback must name it invalid,
        # so no highlight claims an operation that is none
        _ok, kind = hover(_item(panel, "a.png"))
        assert kind == "invalid", \
            "dropping onto the drag's own source was highlighted as an op"
        lw._drag_hover_item = None
        lw._drag_hover_kind = None
        lw.dragLeaveEvent(QDragLeaveEvent())
        assert getattr(lw, "_drag_hover_kind", None) is None, \
            "feedback survived the drag leaving the slot"
    finally:
        _close(panel)

def test_placeholder_lifecycle_leaks_no_empty_slots_outside_chest(
        app, tmp_path):
    from fastprompter.ui.file_container import is_placeholder

    main, panel = _make_panel(app, tmp_path)
    try:
        lw = panel.file_list
        panel.chest_internal_drop(
            [str(tmp_path / "c.md")], _empty(panel, 20))
        assert any(is_placeholder(lw.item(r)) for r in range(lw.count()))
        main.data["file_panel_view"] = "Details"
        panel._apply_view_mode()
        assert all(not is_placeholder(lw.item(r))
                   for r in range(lw.count())), \
            "leaving the chest left empty placeholders in the list"
        assert lw.count() == 3
        main.data["file_panel_view"] = "Chest"
        panel._apply_view_mode()
        assert _slot_of(panel) == {"a.png": 0, "b.txt": 1, "c.md": 20}, \
            "returning to the chest lost the sparse placement"
    finally:
        _close(panel)

def test_legacy_compact_settings_migrate_to_slots(app, tmp_path):
    """An existing profile stored a compact name order; it must survive.

    Migration reads the old list as initial positions (rank = slot), so an
    upgraded profile starts exactly where the user left it -- nothing is
    re-dropped, nothing is compacted."""
    main, panel = _make_panel(app, tmp_path)
    try:
        key = os.path.normcase(os.path.abspath(str(tmp_path)))
        main.data["silo_chest_order"] = {key: ["c.md", "b.txt", "a.png"]}
        panel2 = type(panel)(main)
        panel2.open_for(str(tmp_path), "t")
        _settle(app, panel2)
        try:
            assert _slot_of(panel2) == {"c.md": 0, "b.txt": 1, "a.png": 2}
            # and the map is rewritten in the sparse shape on the next drop
            panel2.chest_internal_drop(
                [str(tmp_path / "a.png")], _empty(panel2, 20))
            assert main.data["silo_chest_order"][key] == {
                "c.md": 0, "b.txt": 1, "a.png": 20}
        finally:
            _close(panel2)
    finally:
        _close(panel)

def test_no_two_items_ever_share_a_slot(app, tmp_path):
    """Slot identity is unique after every operation the chest performs."""
    main, panel = _make_panel(app, tmp_path, files=(
        "a.png", "b.txt", "c.md", "d.txt", "e.log"))
    try:
        panel.chest_internal_drop(
            [str(tmp_path / "a.png")], _empty(panel, 12))
        panel.chest_internal_drop(
            [str(tmp_path / "b.txt"), str(tmp_path / "c.md")],
            _empty(panel, 20))
        panel.chest_internal_drop(
            [str(tmp_path / "d.txt")], _item(panel, "e.log"))
        slots = _slot_of(panel)
        assert len(slots) == 5
        assert len(set(slots.values())) == 5, \
            "two files occupy one slot: the grid lost an identity"
        panel.refresh()
        _settle(app, panel)
        assert _slot_of(panel) == slots, "refresh changed the placement"
        # the persisted map is the same identity set
        key = os.path.normcase(os.path.abspath(str(tmp_path)))
        saved = main.data["silo_chest_order"][key]
        assert len(set(saved.values())) == len(saved) == 5
        assert set(saved.values()) == set(slots.values())
    finally:
        _close(panel)

def test_full_chest_loses_nothing_and_overflow_gets_slots(app, tmp_path):
    """A full chest still accepts a drop: the grid grows by whole rows."""
    from fastprompter.ui.file_container import FileContainerPanel, is_placeholder

    main = _Main(file_panel_view="Chest", silo_chest_slots="64")
    panel = FileContainerPanel(main)
    for index in range(64):
        (tmp_path / f"{index:02}.txt").write_text(str(index))
    panel.open_for(str(tmp_path), "t")
    _settle(app, panel)
    try:
        lw = panel.file_list
        assert panel._chest_real_count() == 64
        # no placeholder leaked into the selection
        lw.selectAll()
        assert all(not is_placeholder(it) for it in lw.selectedItems())
        lw.clearSelection()
        # move a group onto the last two occupied slots: nothing is dropped
        panel.chest_internal_drop(
            [str(tmp_path / "00.txt"), str(tmp_path / "01.txt")],
            lw.item(63))
        slots = _slot_of(panel)
        assert len(slots) == 64, "a full-chest drop dropped items"
        assert len(set(slots.values())) == 64
        assert slots["00.txt"] == 63 and slots["01.txt"] == 64
        assert "63.txt" in slots, "the displaced item vanished"
        assert panel.lbl_count.text() == "64/64" or \
            panel.lbl_count.text().startswith("64/")
    finally:
        _close(panel)

def test_switching_silos_invalidates_a_stale_drag(app, tmp_path):
    """A drag born over one silo may never act on another.

    The drop carries the OLD folder's paths; the new listing has no such
    item, so the inventory operation is a no-op and nothing moves on disk."""
    other = tmp_path / "other_silo"
    other.mkdir()
    (other / "keep.png").write_bytes(b"keep")
    main, panel = _make_panel(app, tmp_path)
    try:
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

        stale = [str(tmp_path / "a.png"), str(tmp_path / "b.txt")]
        before_here = _slot_of(panel)
        panel.open_for(str(other), "t")
        _settle(app, panel)
        lw = panel.file_list
        target = lw.item(0)
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in stale])
        pos = QPointF(float(lw.visualItemRect(target).center().x()),
                      float(lw.visualItemRect(target).center().y()))
        point = lw.visualItemRect(target).center()
        for cls in (QDragEnterEvent, QDragMoveEvent):
            ev = cls(point, Qt.DropAction.MoveAction, md,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            ev.source = lambda: lw
            app.sendEvent(lw.viewport(), ev)
        drop = QDropEvent(pos, Qt.DropAction.MoveAction, md,
                          Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        drop.source = lambda: lw
        app.sendEvent(lw.viewport(), drop)
        for _ in range(60):
            app.processEvents()
        assert _slot_of(panel) == {"keep.png": 0}, \
            "a stale drag from another silo mutated this chest"
        assert (tmp_path / "a.png").is_file()
        assert before_here == {"a.png": 0, "b.txt": 1, "c.md": 2,
                               "other_silo": 3}
    finally:
        _close(panel)

def test_external_explorer_drop_imports_into_the_silo(app, tmp_path):
    """A drop from Explorer is an import: the file lands in this silo.

    It is not an internal slot operation, so it must not go through
    chest_internal_drop, and the source outside the silo is left intact."""
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtGui import QDropEvent

    outside = tmp_path / "outside_explorer"
    outside.mkdir()
    src = outside / "dropped.txt"
    src.write_text("FROM EXPLORER")
    main, panel = _make_panel(app, tmp_path)
    try:
        calls = []
        real_chest = panel.chest_internal_drop

        def chest_spy(paths, target):
            calls.append(paths)
            return real_chest(paths, target)

        panel.chest_internal_drop = chest_spy
        try:
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(str(src))])
            ev = QDropEvent(
                QPointF(20.0, 20.0), Qt.DropAction.CopyAction, md,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            panel.dropEvent(ev)
            for _ in range(80):
                app.processEvents()
        finally:
            panel.chest_internal_drop = real_chest
        assert calls == [], \
            "an external Explorer drop entered the chest slot machinery"
        assert (tmp_path / "dropped.txt").is_file(), \
            "the external import did not land in the silo"
        assert src.is_file(), "an import must copy, not steal, the source"
        panel.refresh()
        _settle(app, panel)
        assert "dropped.txt" in _slot_of(panel)
    finally:
        _close(panel)
