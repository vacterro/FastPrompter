"""T-1265 C3: plain click views an image, Ctrl+click renames it.

The old interaction was backwards and split across three code paths:

* a rendered/pasted image hitbox needed **Ctrl+click merely to LOOK** at the
  image;
* the collapsed image pill renamed on **double-click**, so an ordinary
  double-click popped a rename dialog nobody asked for;
* Source-mode links, Live Preview and Reading mode each resolved the hit
  differently, and only one of them could recover the markdown link that a
  safe rename needs.

The contract now:

===================  ===========================================
gesture              result
===================  ===========================================
left click           open the image in the internal viewer
Ctrl + left click    rename the file AND its link, one undo step
Ctrl + Shift + left  reveal the containing folder
double click         nothing (the press already acted)
Ctrl + right click   reveal the containing folder (unchanged)
===================  ===========================================

Security is NOT relaxed: opening always goes through
``VaultTextEdit.authorize_and_open_url``, the one router, which decodes
rasters internally and still demands confirmation before any local file
reaches the shell. Ordinary (non-image) Source links keep their Ctrl+click
contract.
"""

from __future__ import annotations

import os
import struct
import zlib

import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import QApplication, QInputDialog

from fastprompter.ui.editor import MD_IMAGE_RE, VaultTextEdit
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter

_LEFT = Qt.MouseButton.LeftButton
_RIGHT = Qt.MouseButton.RightButton
_CTRL = Qt.KeyboardModifier.ControlModifier
_SHIFT = Qt.KeyboardModifier.ShiftModifier
_NONE = Qt.KeyboardModifier.NoModifier


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_png(path):
    """A real 1x1 PNG, so the viewer has something decodable to refuse or open."""
    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    raw = zlib.compress(b"\x00\xff\xff\xff")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    return path


class _FakeMain:
    """Only what the editor and the rename path actually touch."""

    def __init__(self, mode="Source"):
        class _Combo:
            def currentData(self_inner):
                return mode

            def currentText(self_inner):
                return mode

        self.preview_combo = _Combo()
        self.settings = None
        self.data = {"show_line_numbers": "False", "code_auto_gutter": "False",
                     "line_marks": "False"}
        self.highlighter = None
        self._LARGE_DOC_THRESHOLD = 500_000
        self._current_lang = "EN"
        self.focus_locks = 0
        self.ignore_focus_loss = False
        self._file_container = None

    def _increment_focus_lock(self):
        self.focus_locks += 1

    def _decrement_focus_lock(self):
        self.focus_locks -= 1

    def mark_dirty(self, *a, **k):
        pass

    def play_tick_sound(self, *a, **k):
        pass

    def save_line_marks(self):
        pass

    def capture_silo_state(self, *a, **k):
        """The editor's 2 s scroll-idle capture calls this on the main window.

        The double used to omit it, so the timer -- which outlives the test
        that created the editor -- raised inside the Qt event loop and failed
        whatever unrelated test happened to be pumping it next.
        """
        pass


_EDITORS = []


def _editor(text="", mode="Live Preview"):
    editor = VaultTextEdit(_FakeMain(mode))
    _EDITORS.append(editor)
    editor.setPlainText(text)
    editor.resize(600, 300)
    # T-1338: collapsed image pills exist only in Live Preview with a
    # concealing highlighter attached (strict _image_pills_enabled). Wire one
    # so pill hit-testing reflects production, not a lax no-highlighter default.
    if mode == "Live Preview":
        hl = MarkdownHighlighter(editor.document())
        hl.set_degraded(False)
        editor.main_win.highlighter = hl
        hl.rehighlight()
    editor.show()
    return editor


def _router(monkeypatch, fail_on_shell=True):
    """Record what reaches the internal viewer; fail if the shell is used."""
    from fastprompter.ui import image_viewer

    opened = []
    monkeypatch.setattr(
        image_viewer, "open_image_viewer",
        lambda path, parent, lang="EN": opened.append(path) or True)
    if fail_on_shell:
        monkeypatch.setattr(
            QDesktopServices, "openUrl",
            lambda *a: pytest.fail("an image was handed to the shell"))
    return opened


def _click(editor, pos, button=_LEFT, modifiers=_NONE):
    point = QPointF(pos)
    editor.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, point, point, button, button,
        modifiers))
    editor.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, point, point, button, button,
        modifiers))


def _double_click(editor, pos, modifiers=_NONE):
    """Qt's real sequence: press, release, DBLCLICK, release."""
    _click(editor, pos, _LEFT, modifiers)
    point = QPointF(pos)
    editor.mouseDoubleClickEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, point, point, _LEFT, _LEFT,
        modifiers))
    editor.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, point, point, _LEFT, _LEFT,
        modifiers))


@pytest.fixture()
def pasted(app, tmp_path):
    """An editor whose first line is a pasted-image link, plus its pill centre."""
    image = _write_png(tmp_path / "paste-20260730_140826.png")
    editor = _editor(f"![img]({image})\nsecond line")
    block = editor.document().firstBlock()
    match = next(iter(MD_IMAGE_RE.finditer(block.text())))
    rect = editor._image_pill_rect(block, match)
    return editor, image, rect.center()


class TestViewing:
    def test_a_plain_click_opens_the_viewer_once(self, pasted, monkeypatch):
        editor, image, centre = pasted
        opened = _router(monkeypatch)
        _click(editor, centre)
        assert opened == [os.path.realpath(os.path.abspath(str(image)))]

    def test_a_click_that_misses_the_pill_opens_nothing(self, pasted,
                                                        monkeypatch):
        editor, _image, _centre = pasted
        opened = _router(monkeypatch)
        _click(editor, QPoint(580, 280))
        assert opened == []

    def test_a_rendered_image_hitbox_opens_on_a_plain_click(self, app,
                                                            tmp_path,
                                                            monkeypatch):
        image = _write_png(tmp_path / "rendered.png")
        editor = _editor("no markdown here")
        editor._rendered_images = [(QRect(0, 0, 60, 30), str(image))]
        opened = _router(monkeypatch)
        _click(editor, QPoint(10, 10))
        assert opened == [os.path.realpath(os.path.abspath(str(image)))]

    def test_live_preview_viewing_still_works(self, app, tmp_path,
                                              monkeypatch):
        image = _write_png(tmp_path / "lp.png")
        editor = _editor(f"![img]({image})", mode="Live Preview")
        block = editor.document().firstBlock()
        match = next(iter(MD_IMAGE_RE.finditer(block.text())))
        centre = editor._image_pill_rect(block, match).center()
        opened = _router(monkeypatch)
        _click(editor, centre)
        assert opened == [os.path.realpath(os.path.abspath(str(image)))]

    def test_reading_mode_viewing_still_works(self, app, tmp_path,
                                              monkeypatch):
        image = _write_png(tmp_path / "read.png")
        editor = _editor("rendered only", mode="Reading")
        editor._rendered_images = [(QRect(0, 0, 60, 30), str(image))]
        opened = _router(monkeypatch)
        _click(editor, QPoint(10, 10))
        assert opened == [os.path.realpath(os.path.abspath(str(image)))]


class TestRenaming:
    def test_ctrl_click_opens_the_rename_dialog_exactly_once(self, pasted,
                                                             monkeypatch):
        editor, _image, centre = pasted
        _router(monkeypatch)
        prompts = []
        monkeypatch.setattr(
            QInputDialog, "getText",
            lambda *a, **k: prompts.append(1) or ("", False))
        _click(editor, centre, _LEFT, _CTRL)
        assert len(prompts) == 1

    def test_ctrl_click_renames_the_file_and_the_link_together(self, pasted,
                                                               monkeypatch):
        editor, image, centre = pasted
        _router(monkeypatch)
        monkeypatch.setattr(QInputDialog, "getText",
                            lambda *a, **k: ("screenshot", True))
        _click(editor, centre, _LEFT, _CTRL)

        renamed = image.parent / "screenshot.png"
        assert renamed.is_file()
        assert not image.exists()
        assert "screenshot.png" in editor.toPlainText()
        assert "paste-20260730_140826.png" not in editor.toPlainText()

    def test_cancelling_changes_nothing(self, pasted, monkeypatch):
        editor, image, centre = pasted
        _router(monkeypatch)
        before = editor.toPlainText()
        monkeypatch.setattr(QInputDialog, "getText",
                            lambda *a, **k: ("", False))
        _click(editor, centre, _LEFT, _CTRL)
        assert editor.toPlainText() == before
        assert image.is_file()

    def test_the_rename_is_one_undo_step(self, pasted, monkeypatch):
        editor, image, centre = pasted
        _router(monkeypatch)
        before = editor.toPlainText()
        monkeypatch.setattr(QInputDialog, "getText",
                            lambda *a, **k: ("screenshot", True))
        _click(editor, centre, _LEFT, _CTRL)
        assert editor.toPlainText() != before
        editor.undo()
        assert editor.toPlainText() == before

    def test_an_http_image_is_never_offered_a_local_rename(self, app,
                                                           monkeypatch):
        editor = _editor("![web](https://example.com/pic.png)")
        block = editor.document().firstBlock()
        match = next(iter(MD_IMAGE_RE.finditer(block.text())))
        centre = editor._image_pill_rect(block, match).center()
        monkeypatch.setattr(
            QInputDialog, "getText",
            lambda *a, **k: pytest.fail("offered to rename a remote image"))
        _click(editor, centre, _LEFT, _CTRL)

    def test_a_rendered_visual_with_no_link_is_not_renameable(self, app,
                                                              tmp_path,
                                                              monkeypatch):
        """Nothing to move the file WITH, so rename is refused, not guessed."""
        image = _write_png(tmp_path / "orphan.png")
        editor = _editor("the document does not mention it")
        editor._rendered_images = [(QRect(0, 0, 60, 30), str(image))]
        monkeypatch.setattr(
            QInputDialog, "getText",
            lambda *a, **k: pytest.fail("renamed a visual with no link"))
        _click(editor, QPoint(10, 10), _LEFT, _CTRL)
        assert image.is_file()

    def test_a_rendered_visual_recovers_its_link_for_rename(self, app,
                                                            tmp_path,
                                                            monkeypatch):
        """_rendered_images alone loses the block/match; we recover it."""
        image = _write_png(tmp_path / "linked.png")
        editor = _editor(f"![img]({image})")
        editor._rendered_images = [(QRect(200, 200, 60, 30), str(image))]
        hit = editor.image_hit_at(QPoint(210, 210))
        assert hit is not None
        block, match, url = hit
        assert block is not None and match is not None
        assert VaultTextEdit._image_hit_is_renameable(block, match, url)


class TestDoubleClick:
    def test_a_plain_double_click_never_renames(self, pasted, monkeypatch):
        editor, _image, centre = pasted
        _router(monkeypatch)
        monkeypatch.setattr(
            QInputDialog, "getText",
            lambda *a, **k: pytest.fail("double-click opened rename"))
        _double_click(editor, centre)

    def test_a_double_click_opens_the_viewer_only_once(self, pasted,
                                                       monkeypatch):
        editor, image, centre = pasted
        opened = _router(monkeypatch)
        _double_click(editor, centre)
        assert opened == [os.path.realpath(os.path.abspath(str(image)))]

    def test_ctrl_double_click_opens_one_rename_dialog(self, pasted,
                                                       monkeypatch):
        editor, _image, centre = pasted
        _router(monkeypatch)
        prompts = []
        monkeypatch.setattr(
            QInputDialog, "getText",
            lambda *a, **k: prompts.append(1) or ("", False))
        _double_click(editor, centre, _CTRL)
        assert len(prompts) == 1


class TestFolderRevealSurvives:
    def test_ctrl_shift_left_reveals_the_folder(self, pasted, monkeypatch):
        editor, image, centre = pasted
        _router(monkeypatch, fail_on_shell=False)
        revealed = []
        monkeypatch.setattr(VaultTextEdit, "open_containing_folder",
                            lambda *a: revealed.append(a[-1]) or True)
        _click(editor, centre, _LEFT, _CTRL | _SHIFT)
        assert len(revealed) == 1

    def test_ctrl_right_on_a_rendered_image_still_reveals(self, app, tmp_path,
                                                          monkeypatch):
        image = _write_png(tmp_path / "menu.png")
        editor = _editor("no markdown")
        editor._rendered_images = [(QRect(0, 0, 60, 30), str(image))]
        revealed = []
        monkeypatch.setattr(VaultTextEdit, "open_containing_folder",
                            lambda *a: revealed.append(a[-1]) or True)
        _click(editor, QPoint(10, 10), _RIGHT, _CTRL)
        assert len(revealed) == 1


class TestSecurityIsUnchanged:
    def test_ordinary_source_links_keep_their_ctrl_gesture(self, app,
                                                           monkeypatch):
        editor = _editor("plain text", mode="Source")
        opened = []
        monkeypatch.setattr(QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()) or True)
        monkeypatch.setattr(editor, "anchor_url_at",
                            lambda pos: QUrl("https://example.com"))
        _click(editor, QPoint(10, 10))                 # plain: nothing
        assert opened == []
        _click(editor, QPoint(10, 10), _LEFT, _CTRL)   # Ctrl: opens
        assert opened == ["https://example.com"]

    def test_an_executable_behind_an_image_link_is_still_gated(self, app,
                                                               tmp_path,
                                                               monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        payload = tmp_path / "invoice.exe"
        payload.write_bytes(b"MZ" + b"\x00" * 32)
        editor = _editor(f"![img]({payload})")
        block = editor.document().firstBlock()
        match = next(iter(MD_IMAGE_RE.finditer(block.text())))
        centre = editor._image_pill_rect(block, match).center()

        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a: QMessageBox.StandardButton.No)
        monkeypatch.setattr(
            QDesktopServices, "openUrl",
            lambda *a: pytest.fail("an .exe reached the shell from an image "
                                   "click"))
        _click(editor, centre)

    def test_a_fake_raster_never_falls_through_to_the_shell(self, app,
                                                            tmp_path,
                                                            monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        payload = tmp_path / "payload.png"
        payload.write_bytes(b"MZ" + b"\x00" * 64)
        editor = _editor(f"![img]({payload})")
        block = editor.document().firstBlock()
        match = next(iter(MD_IMAGE_RE.finditer(block.text())))
        centre = editor._image_pill_rect(block, match).center()

        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *a: pytest.fail("a .png must not reach the shell gate"))
        monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
        monkeypatch.setattr(
            QDesktopServices, "openUrl",
            lambda *a: pytest.fail("a fake raster reached the shell"))
        _click(editor, centre)


def test_inline_image_context_menu_copies_pixels_and_canonical_path(
        pasted, monkeypatch, app):
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu

    editor, image, centre = pasted
    editor.main_win.build_send_selection_menu = lambda _menu: None
    editor.main_win.clear_formatting = lambda: None
    editor.main_win.insert_divider_line = lambda: None
    menus = []
    monkeypatch.setattr(
        QMenu, "exec", lambda menu, *_args, **_kw: menus.append(menu))
    point = QPoint(centre)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, editor.mapToGlobal(point))

    editor.contextMenuEvent(event)

    assert len(menus) == 1
    actions = {action.text().split("\t", 1)[0]: action
               for action in menus[0].actions()}
    assert "Copy Image" in actions
    assert "Copy Image Path" in actions

    actions["Copy Image"].trigger()
    mime = app.clipboard().mimeData()
    assert mime.hasImage()
    assert [url.toLocalFile() for url in mime.urls()] == [
        os.path.realpath(str(image)).replace("\\", "/")]

    actions["Copy Image Path"].trigger()
    assert app.clipboard().text() == os.path.normpath(
        os.path.realpath(str(image)))
