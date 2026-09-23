"""Silo container Chest view + external image viewer routing."""
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

    def mark_dirty(self):
        pass


def _png(path, color="red"):
    img = QImage(40, 20, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def _settle(app, panel, cycles=60):
    import time
    for _ in range(cycles):
        app.processEvents()
        if getattr(panel, "_refresh_inflight_seq", 1) is None:
            break
        time.sleep(0.01)
    app.processEvents()


def test_slot_math():
    from fastprompter.ui.silo_chest import chest_slots, slot_total
    assert chest_slots({}) == 64
    assert chest_slots({"silo_chest_slots": "128"}) == 128
    assert chest_slots({"silo_chest_slots": "junk"}) == 64
    assert chest_slots({"silo_chest_slots": "65"}) == 64
    assert slot_total(3, 64) == 64
    assert slot_total(70, 64, columns=8) == 72


def test_chest_pads_to_capacity_and_never_leaks_placeholders(app, tmp_path):
    from fastprompter.ui.file_container import FileContainerPanel
    _png(tmp_path / "a.png")
    (tmp_path / "b.txt").write_text("hello")
    main = _Main(file_panel_view="Chest", silo_chest_slots="64")
    panel = FileContainerPanel(main)
    try:
        panel.open_for(str(tmp_path), "t")
        _settle(app, panel)
        lw = panel.file_list
        assert lw.count() == 64
        assert panel.lbl_count.text() == "2/64"
        lw.selectAll()
        assert sorted(os.path.basename(p) for p in panel.selected_paths()) == [
            "a.png", "b.txt"]
        panel.set_chest_slots(128)
        assert lw.count() == 128
        # leaving Chest view removes every empty slot
        main.data["file_panel_view"] = "Details"
        panel._apply_view_mode()
        assert lw.count() == 2
        main.data["file_panel_view"] = "Chest"
        panel._apply_view_mode()
        assert lw.count() == 128
        assert panel.lbl_count.text() == "2/128"
        assert sorted(panel.selected_paths()) == [
            os.path.realpath(tmp_path / "a.png"),
            os.path.realpath(tmp_path / "b.txt"),
        ]
    finally:
        panel.close()
        panel.deleteLater()


def test_chest_keyboard_copy_and_drag_use_only_real_files(
        app, tmp_path, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    from fastprompter.ui.file_container import FileContainerPanel

    image_path = _png(tmp_path / "image.png")
    text_path = tmp_path / "note.txt"
    text_path.write_text("text")
    panel = FileContainerPanel(
        _Main(file_panel_view="Chest", silo_chest_slots="64"))
    try:
        panel.open_for(str(tmp_path), "t")
        _settle(app, panel)
        lw = panel.file_list
        image_item = next(
            lw.item(i) for i in range(lw.count())
            if lw.item(i).data(Qt.ItemDataRole.UserRole) == image_path)
        real_paths = sorted((os.path.realpath(image_path),
                             os.path.realpath(text_path)))

        lw.clearSelection()
        image_item.setSelected(True)
        lw.setCurrentItem(image_item)
        lw.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier, "c"))
        mime = app.clipboard().mimeData()
        assert mime.hasImage()
        assert [url.toLocalFile() for url in mime.urls()] == [
            os.path.realpath(image_path).replace("\\", "/")]

        lw.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            "C"))
        assert app.clipboard().text() == os.path.normpath(image_path)

        lw.selectAll()
        deleted = []
        monkeypatch.setattr(panel, "_delete", lambda paths: deleted.extend(paths))
        lw.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Delete,
            Qt.KeyboardModifier.NoModifier))
        assert sorted(deleted) == real_paths

        class _Drag:
            def __init__(self, _parent):
                self.mime = None

            def setMimeData(self, mime_data):
                self.mime = mime_data

            def setPixmap(self, _pixmap):
                pass

            def exec(self, _actions):
                dragged.extend(url.toLocalFile() for url in self.mime.urls())

        from fastprompter.ui import file_container
        dragged = []
        monkeypatch.setattr(file_container, "QDrag", _Drag)
        lw.startDrag(Qt.DropAction.CopyAction)
        assert sorted(os.path.normcase(os.path.normpath(path))
                      for path in dragged) == sorted(
                          os.path.normcase(os.path.normpath(path))
                          for path in real_paths)
    finally:
        panel.close()
        panel.deleteLater()


def test_hover_card_is_reused_across_repeated_hover_cycles(app, tmp_path):
    from PyQt6.QtCore import QPoint

    from fastprompter.ui.file_container import FileContainerPanel
    from fastprompter.ui.silo_chest import ChestItemCard

    _png(tmp_path / "hover.png")
    panel = FileContainerPanel(
        _Main(file_panel_view="Chest", silo_chest_slots="64"))
    try:
        panel.open_for(str(tmp_path), "t")
        _settle(app, panel)
        item = next(
            panel.file_list.item(i) for i in range(panel.file_list.count())
            if panel.file_list.item(i).data(Qt.ItemDataRole.UserRole))
        for _ in range(20):
            panel._hover_item(item, QPoint(20, 20))
            panel.hide_item_card()
        cards = panel.findChildren(ChestItemCard)
        assert len(cards) == 1
        assert panel._card is cards[0]
    finally:
        panel.close()
        panel.deleteLater()


def test_item_card_describes_image(app, tmp_path):
    from fastprompter.core.translations import tr
    from fastprompter.ui.silo_chest import build_item_card
    path = _png(tmp_path / "shot.png")
    text, pix = build_item_card(path, tr, "EN")
    assert "shot.png" in text and "40 × 20 px" in text
    assert pix is not None and not pix.isNull()


def test_item_card_escapes_text_preview(app, tmp_path):
    from fastprompter.core.translations import tr
    from fastprompter.ui.silo_chest import build_item_card
    p = tmp_path / "n.txt"
    p.write_text("<script>x</script>\nline2")
    text, pix = build_item_card(str(p), tr, "EN")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert pix is None


def test_viewer_unbound_stays_internal(app):
    from fastprompter.ui import image_viewer
    image_viewer.bind_preferences(None)
    assert image_viewer.viewer_preference() == ("internal", "")


def test_system_viewer_launches_verified_image_only(app, tmp_path, monkeypatch):
    from fastprompter.ui import image_viewer
    main = _Main(image_viewer_mode="system")
    image_viewer.bind_preferences(main)
    launched = []
    monkeypatch.setattr(image_viewer, "launch_external",
                        lambda path, exe="": launched.append((path, exe)) or True)
    try:
        good = _png(tmp_path / "ok.png")
        assert image_viewer.open_image_viewer(good, None, "EN") is True
        assert launched == [(os.path.realpath(good), "")]
        assert not image_viewer._OPEN_VIEWERS
        fake = tmp_path / "evil.png"
        fake.write_bytes(b"@echo off\r\n")
        monkeypatch.setattr(image_viewer.QMessageBox, "information", lambda *a: None)
        assert image_viewer.open_image_viewer(str(fake), None, "EN") is False
        assert len(launched) == 1
    finally:
        image_viewer.bind_preferences(None)


def test_custom_viewer_gets_exe(app, tmp_path, monkeypatch):
    from fastprompter.ui import image_viewer
    main = _Main(image_viewer_mode="custom", image_viewer_path=r"C:\x\view.exe")
    image_viewer.bind_preferences(main)
    launched = []
    monkeypatch.setattr(image_viewer, "launch_external",
                        lambda path, exe="": launched.append(exe) or True)
    try:
        assert image_viewer.open_image_viewer(_png(tmp_path / "c.png"), None)
        assert launched == [r"C:\x\view.exe"]
    finally:
        image_viewer.bind_preferences(None)


def test_custom_viewer_uses_canonical_argv_without_shell(app, tmp_path,
                                                         monkeypatch):
    from fastprompter.ui import image_viewer

    exe = tmp_path / "viewer ; marker.exe"
    exe.write_bytes(b"test executable placeholder")
    image = _png(tmp_path / "verified image.png")
    main = _Main(image_viewer_mode="custom", image_viewer_path=str(exe))
    image_viewer.bind_preferences(main)
    launched = []
    monkeypatch.setattr(
        image_viewer.subprocess, "Popen",
        lambda args, **kwargs: launched.append((args, kwargs)))
    try:
        assert image_viewer.open_image_viewer(image, None, "EN") is True
        assert launched == [
            ([str(exe), os.path.realpath(image)], {"close_fds": True})]
        missing = str(tmp_path / "missing viewer.exe")
        assert image_viewer.launch_external(image, missing) is False
        assert len(launched) == 1
    finally:
        image_viewer.bind_preferences(None)


def test_copy_image_and_path(app, tmp_path):
    from fastprompter.ui.image_viewer import copy_image_path, copy_image_to_clipboard
    path = _png(tmp_path / "copy.png", "blue")
    assert copy_image_to_clipboard(path)
    mime = QApplication.clipboard().mimeData()
    assert mime.hasImage()
    assert [u.toLocalFile() for u in mime.urls()] == [
        os.path.realpath(path).replace("\\", "/")]
    copy_image_path(path)
    assert QApplication.clipboard().text() == os.path.normpath(path)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"nope")
    assert copy_image_to_clipboard(str(bad)) is False


def test_container_opens_images_via_router(app, tmp_path, monkeypatch):
    from fastprompter.ui import image_viewer
    from fastprompter.ui.file_container import FileContainerPanel
    path = _png(tmp_path / "v.png")
    opened = []
    monkeypatch.setattr(image_viewer, "open_image_viewer",
                        lambda p, parent=None, lang="EN": opened.append(p) or True)
    monkeypatch.setattr(os, "startfile", lambda *a: pytest.fail("shell"), raising=False)
    panel = FileContainerPanel(_Main(file_panel_view="Chest"))
    try:
        panel.open_for(str(tmp_path), "t")
        _settle(app, panel)
        item = next(panel.file_list.item(i) for i in range(panel.file_list.count())
                    if panel.file_list.item(i).data(Qt.ItemDataRole.UserRole))
        panel._open_item(item)
        assert opened == [path]
    finally:
        panel.close()
        panel.deleteLater()
