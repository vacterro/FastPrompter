import os

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import QApplication

from fastprompter.main import _PreviewTextEdit
from fastprompter.ui.editor import VaultTextEdit


@pytest.fixture
def app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

@pytest.fixture
def mock_open_url(monkeypatch):
    calls = []
    def mock_open(url):
        calls.append(url)
        return True
    monkeypatch.setattr(QDesktopServices, 'openUrl', mock_open)
    return calls

@pytest.fixture
def mock_open_folder(monkeypatch):
    calls = []
    def mock_folder(self, url):
        calls.append(url)
        return True
    monkeypatch.setattr(VaultTextEdit, 'open_containing_folder', mock_folder)
    return calls

def _mouse_click(widget, pos, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier, drag_to=None):
    posF = QPointF(pos)
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, posF, posF, button, button, modifiers)
    widget.mousePressEvent(press)
    if drag_to:
        dragF = QPointF(drag_to)
        move = QMouseEvent(QMouseEvent.Type.MouseMove, dragF, dragF, button, button, modifiers)
        widget.mouseMoveEvent(move)
        release_pos = dragF
    else:
        release_pos = posF
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, release_pos, release_pos, button, button, modifiers)
    widget.mouseReleaseEvent(release)

class _FakeMainForPreview:
    def __init__(self):
        class _FakeCombo:
            def currentData(self): return "Live Preview"
            def currentText(self): return "Live Preview"
        self.preview_combo = _FakeCombo()
        self.settings = None

def test_source_links(app, mock_open_url, mock_open_folder, monkeypatch):
    main_win = _FakeMainForPreview()
    main_win.preview_combo.currentData = lambda: "Source"
    editor = VaultTextEdit(main_win)
    
    current_url = "https://example.com"
    monkeypatch.setattr(editor, 'anchor_url_at', lambda pos: QUrl(current_url) if current_url else None)
    pos = QPoint(10, 10)
    
    # plain click -> 0
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 0
    
    # Ctrl click safe -> 1
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    assert len(mock_open_url) == 1
    
    # Ctrl click unsafe -> 0
    current_url = "javascript:alert(1)"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    assert len(mock_open_url) == 1  # unchanged
    
    # Ctrl Shift click file -> reveal folder
    current_url = "file:///C:/test.txt"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert len(mock_open_folder) == 1

def test_live_preview_links(app, mock_open_url, mock_open_folder, monkeypatch):
    editor = VaultTextEdit(_FakeMainForPreview())
    
    current_url = "https://example.com"
    monkeypatch.setattr(editor, 'anchor_url_at', lambda pos: QUrl(current_url) if current_url else None)
    pos = QPoint(10, 10)
    
    # LIVE: plain safe -> 1
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1
    
    # LIVE: unsafe -> 0
    current_url = "javascript:alert(1)"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1 # unchanged
    
    # LIVE drag: 0
    current_url = "https://example.com"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, drag_to=pos + QPoint(50, 0))
    assert len(mock_open_url) == 1 # unchanged
    
    # LIVE Shift local: open_containing_folder exactly once
    current_url = "file:///C:/test.txt"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    assert len(mock_open_folder) == 1
    assert len(mock_open_url) == 1 # unchanged

def test_reading_links(app, mock_open_url, monkeypatch):
    editor = _PreviewTextEdit()
    
    current_url = "https://example.com"
    monkeypatch.setattr(editor, 'anchorAt', lambda pos: current_url if current_url else "")
    pos = QPoint(10, 10)
    
    # plain click -> once
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1
    
    # unsafe -> zero
    current_url = "javascript:alert(1)"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1 # unchanged
    
    # drag -> zero
    current_url = "https://example.com"
    # To simulate drag_to returning True for hasSelection, mock textCursor
    # However, anchorAt won't be called if hasSelection is true.
    class MockCursor:
        def hasSelection(self): return True
    monkeypatch.setattr(editor, 'textCursor', lambda: MockCursor())
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1 # unchanged


def test_t1016_executable_links_require_approval(app, mock_open_url, mock_open_folder, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from fastprompter.ui.editor import VaultTextEdit
    main_win = _FakeMainForPreview()
    main_win._current_lang = "EN"
    editor = VaultTextEdit(main_win)
    
    current_url = "file:///C:/malware.exe"
    monkeypatch.setattr(editor, 'anchor_url_at', lambda pos: QUrl(current_url) if current_url else None)
    pos = QPoint(10, 10)
    
    # 1. Reject approval
    responses = [QMessageBox.StandardButton.No]
    def mock_warning(*args, **kwargs):
        return responses.pop(0)
    monkeypatch.setattr(QMessageBox, 'warning', mock_warning)
    
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 0  # blocked by No
    
    # 2. Accept approval
    responses = [QMessageBox.StandardButton.Yes]
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 1  # allowed by Yes
    
    # 3. Normal web link bypasses approval
    current_url = "https://example.com"
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 2  # allowed immediately
    
    # 4. Normal local-folder reveal bypasses approval
    current_url = "file:///C:/malware.exe"
    # shift-click reveals folder instead of running it
    _mouse_click(editor, pos, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    assert len(mock_open_folder) == 1
    assert len(mock_open_url) == 2  # unchanged openUrl
    
    # Test reading mode (main.py)
    editor_read = _PreviewTextEdit()
    editor_read.main_win = main_win
    monkeypatch.setattr(editor_read, 'anchorAt', lambda pos: current_url if current_url else "")
    
    responses = [QMessageBox.StandardButton.No]
    _mouse_click(editor_read, pos, Qt.MouseButton.LeftButton)
    assert len(mock_open_url) == 2  # blocked by No


# ----------------------------------------------------------------- centralised
# CORE-003: every local file launch must be confirmed before the OS shell
# sees it, regardless of suffix. The extension denylist is gone — confirmation
# is the only gate. Web links pass straight through; folder-reveal is a
# separate, non-launching path and is unaffected.

@pytest.mark.parametrize("ext", [
    # previously-denied Windows-launchable classes
    ".exe", ".com", ".scr", ".hta", ".cmd", ".bat", ".ps1", ".vbs",
    ".js", ".wsf", ".msc", ".lnk", ".url",
    # previously-PASSIVE types the OS still launches per association
    ".py", ".pyw", ".cpl", ".msi", ".msp", ".vbe", ".jse", ".jar",
    ".reg", ".pif",
    # ordinary "safe" documents and unknown types — still a user decision
    ".txt", ".md", ".pdf", ".docx", "", ".unknown",
])
def test_core003_shell_open_requires_confirmation(app, monkeypatch, ext):
    from PyQt6.QtWidgets import QMessageBox
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda u: (opened.append(u), True)[1])

    # refused -> the file is never handed to the shell
    responses = [QMessageBox.StandardButton.No]
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: responses.pop(0))
    url = QUrl(f"file:///C:/payload{ext}")
    result = VaultTextEdit.authorize_and_open_url(url, None, "EN")
    assert result is False
    assert opened == [], f"{ext!r} must not launch without approval"

    # confirmed -> exactly one launch
    responses = [QMessageBox.StandardButton.Yes]
    result = VaultTextEdit.authorize_and_open_url(url, None, "EN")
    assert result is True
    assert len(opened) == 1 and opened[0] == url


def test_core003_web_links_bypass_confirmation(app, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda u: (opened.append(u), True)[1])
    url = QUrl("https://example.com")
    result = VaultTextEdit.authorize_and_open_url(url, None, "EN")
    assert result is True
    assert opened == [url]


@pytest.mark.parametrize("target", [
    "V:/___VAC/screens/image.png", "C:/images/a b.jpg",
    "V:/pildid/õun 猫.jpeg", "file:///V:/___VAC/a%20b.webp",
    "C:/images/test.gif", "C:/images/test.bmp",
    "C:/kuvakaappaukset/päeva pilt.png",
    "file:///V:/pildid/%E7%8C%AB%E3%81%AE%E7%94%BB%E5%83%8F.webp",
])
def test_local_raster_routes_internally(app, monkeypatch, target):
    import os

    from PyQt6.QtWidgets import QMessageBox

    from fastprompter.ui import image_viewer
    calls = []
    monkeypatch.setattr(image_viewer, "open_image_viewer", lambda path, parent, lang="EN": calls.append(path) or True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: pytest.fail("image warning"))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda *a: pytest.fail("image shell launch"))
    assert VaultTextEdit.authorize_and_open_url(QUrl(target), None)
    local = QUrl(target).toLocalFile() if target.startswith("file:") else target
    assert calls == [os.path.realpath(os.path.abspath(local))]


def test_broken_image_never_falls_back_to_shell(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    errors = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: errors.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: pytest.fail("security warning"))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda *a: pytest.fail("shell fallback"))
    assert not VaultTextEdit.authorize_and_open_url(QUrl.fromLocalFile(str(path)), None)
    assert "Image could not be previewed" in errors[0][2]




# ---------------------------------------------------------------- T-1218 A2
# Every REAL entry route must reach the central router: Source Ctrl+click,
# Live Preview plain click, the Reading-mode preview widget, and the pasted
# image hitbox. The viewer boundary is observed, never called directly.

def _write_png(path, width=3, height=3):
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QImage, QImageWriter
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(_Qt.GlobalColor.darkYellow)
    writer = QImageWriter(str(path), b"PNG")
    assert writer.write(image), writer.errorString()
    return path


def _patch_router(app, monkeypatch, tmp_path, name="shot.png"):
    """Point the central router at the real viewer and record its calls."""
    from PyQt6.QtWidgets import QMessageBox

    from fastprompter.ui import image_viewer
    local = _write_png(tmp_path / name)
    calls = []
    monkeypatch.setattr(
        image_viewer, "open_image_viewer",
        lambda path, parent, lang="EN": calls.append(path) or True)
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a: pytest.fail("security warning on an image"))
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda *a: pytest.fail("image handed to the shell"))
    return os.path.realpath(os.path.abspath(str(local))), calls


def _editor_for_mode(mode):
    from fastprompter.ui.editor import VaultTextEdit
    main_win = _FakeMainForPreview()
    if mode != "Live Preview":
        main_win.preview_combo.currentData = lambda: mode
        main_win.preview_combo.currentText = lambda: mode
    return VaultTextEdit(main_win)


def test_source_mode_ctrl_click_local_image_uses_internal_viewer(
        app, monkeypatch, tmp_path):
    expected, calls = _patch_router(app, monkeypatch, tmp_path)
    editor = _editor_for_mode("Source")
    url = QUrl.fromLocalFile(expected)
    monkeypatch.setattr(editor, "anchor_url_at", lambda pos: url)
    _mouse_click(editor, QPoint(10, 10), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.ControlModifier)
    assert calls == [expected], (
        "Source-mode Ctrl+click on a local image link must open the "
        "internal viewer with the canonical path")


def test_live_preview_local_image_click_uses_internal_viewer(
        app, monkeypatch, tmp_path):
    expected, calls = _patch_router(app, monkeypatch, tmp_path)
    editor = _editor_for_mode("Live Preview")
    url = QUrl.fromLocalFile(expected)
    monkeypatch.setattr(editor, "anchor_url_at", lambda pos: url)
    _mouse_click(editor, QPoint(10, 10), Qt.MouseButton.LeftButton)
    assert calls == [expected], (
        "Live Preview plain click on a local image link must open the "
        "internal viewer")


def test_reading_mode_preview_local_image_click_uses_internal_viewer(
        app, monkeypatch, tmp_path):
    expected, calls = _patch_router(app, monkeypatch, tmp_path)
    from fastprompter.main import _PreviewTextEdit
    editor = _PreviewTextEdit()
    href = QUrl.fromLocalFile(expected).toString()
    monkeypatch.setattr(editor, "anchorAt", lambda pos: href)
    _mouse_click(editor, QPoint(10, 10), Qt.MouseButton.LeftButton)
    assert calls == [expected], (
        "Reading-mode preview click on a local image link must open the "
        "internal viewer")


def test_rendered_image_hitbox_click_uses_internal_viewer(
        app, monkeypatch, tmp_path):
    """T-1265 C3: the gesture is a PLAIN click now, the router is unchanged.

    This used to require Ctrl merely to LOOK at an image. What the test is
    really guarding is the routing - the hitbox must reach
    ``authorize_and_open_url``, never the shell - so the assertion stays and
    only the gesture moves.
    """
    from PyQt6.QtCore import QRect

    expected, calls = _patch_router(app, monkeypatch, tmp_path)
    editor = _editor_for_mode("Source")
    editor._rendered_images = [(QRect(0, 0, 40, 20), expected)]
    _mouse_click(editor, QPoint(10, 10), Qt.MouseButton.LeftButton)
    assert calls == [expected], (
        "the pasted/rendered image hitbox must route through the central "
        "router, not open the shell directly")


def test_live_preview_local_executable_still_gated(app, mock_open_url,
                                                   monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    editor = _editor_for_mode("Live Preview")
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a: QMessageBox.StandardButton.No)
    monkeypatch.setattr(editor, "anchor_url_at",
                        lambda pos: QUrl("file:///C:/malware.exe"))
    _mouse_click(editor, QPoint(10, 10), Qt.MouseButton.LeftButton)
    assert mock_open_url == [], (
        "removing the image warning must NOT weaken the arbitrary-file gate")


def test_renamed_executable_png_never_reaches_shell(app, tmp_path,
                                                    monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    path = tmp_path / "payload.png"
    path.write_bytes(b"MZ" + b"\x00" * 64)
    errors = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: errors.append(a))
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a: pytest.fail("security warning"))
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda *a: pytest.fail("shell fallback"))
    assert not VaultTextEdit.authorize_and_open_url(
        QUrl.fromLocalFile(str(path)), None)
    assert errors and "could not be previewed" in errors[0][2]


def test_image_viewer_lifetime(app, tmp_path, qapp=None):
    """Open -> alive -> close -> deregistered -> reopen works, no stale
    deleted QObject retained in _OPEN_VIEWERS."""
    from PyQt6.QtCore import QEvent

    from fastprompter.ui import image_viewer
    from fastprompter.ui.image_viewer import ImageViewer, open_image_viewer
    image_viewer._OPEN_VIEWERS.clear()
    image_viewer.bind_preferences(None)
    png = _write_png(tmp_path / "life.png")
    try:
        assert open_image_viewer(str(png), None, "EN") is True
        assert image_viewer._OPEN_VIEWERS, (
            "viewer must remain alive after open_image_viewer returns")
        viewer = next(iter(image_viewer._OPEN_VIEWERS))
        assert isinstance(viewer, ImageViewer)
        viewer.close()
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        assert viewer not in image_viewer._OPEN_VIEWERS, (
            "a closed viewer must be deregistered, not retained")
        assert open_image_viewer(str(png), None, "EN") is True
        assert len(image_viewer._OPEN_VIEWERS) == 1
    finally:
        for stale in list(image_viewer._OPEN_VIEWERS):
            try:
                stale.close()
            except Exception:
                pass
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
