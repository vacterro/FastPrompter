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

