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
    from fastprompter.ui.editor import VaultTextEdit
    from PyQt6.QtWidgets import QMessageBox
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
    ".txt", ".md", ".png", ".pdf", ".docx", "", ".unknown",
])
def test_core003_every_local_type_requires_confirmation(app, monkeypatch, ext):
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


