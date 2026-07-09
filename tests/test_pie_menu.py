"""Tests for fastprompter.ui.pie_menu — QuickListWidget."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# PyQt6 stubs
# ---------------------------------------------------------------------------


class _MockQt:
    """Stand-in for Qt namespace constants."""

    class WindowType:
        Popup = 1
        FramelessWindowHint = 2
        WindowStaysOnTopHint = 4

    class WidgetAttribute:
        WA_TranslucentBackground = 10
        WA_DeleteOnClose = 11

    class FocusPolicy:
        StrongFocus = 20

    class Key:
        Key_Escape = 0x01000000

    class ConnectionType:
        QueuedConnection = 2

    Orientation = MagicMock()
    Horizontal = 1
    Vertical = 2


class _MockLayout:
    """Stand-in for QLayout — tracks added widgets."""

    def __init__(self, parent=None):
        self._parent = parent
        self._items = []
        self._margins = (0, 0, 0, 0)
        self._spacing = 0
        self._count = 0

    def setContentsMargins(self, *args):
        self._margins = args

    def setSpacing(self, spacing):
        self._spacing = spacing

    def addLayout(self, layout):
        self._items.append(layout)

    def addWidget(self, widget):
        self._items.append(widget)

    def count(self):
        return len(self._items)

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return _MockLayoutItem(self._items.pop(index))
        return None

    def removeWidget(self, widget):
        if widget in self._items:
            self._items.remove(widget)


class _MockLayoutItem:
    """Stand-in for QLayoutItem — holds a widget reference."""

    def __init__(self, widget=None):
        self._widget = widget

    def widget(self):
        return self._widget


class _MockWidget:
    """Stand-in for QWidget — tracks state, flags, stylesheets."""

    def __init__(self, parent=None):
        self._parent = parent
        self._flags = 0
        self._attributes = {}
        self._focus_policy = None
        self._deleted = False
        self._stylesheets = []
        self.layout = _MockLayout(self)
        self.cat_layout = _MockLayout(self)
        self.snip_layout = _MockLayout(self)
        self.cats = []
        self.current_cat = ""
        self.main_win = None
        self.kb_listener = None
        self._visible = False

    def setWindowFlags(self, flags):
        self._flags = flags

    def setAttribute(self, attr, value=True):
        self._attributes[attr] = value

    def setFocusPolicy(self, policy):
        self._focus_policy = policy

    def setStyleSheet(self, ss):
        self._stylesheets.append(ss)

    def setFixedSize(self, w, h):
        self._fixed_size = (w, h)

    def setFixedWidth(self, w):
        self._fixed_width = w

    def adjustSize(self):
        pass

    def move(self, x, y):
        self._moved_to = (x, y)

    def close(self):
        self._visible = False

    def deleteLater(self):
        self._deleted = True

    def isVisible(self):
        return self._visible

    def width(self):
        return 200

    def height(self):
        return 300

    def parent(self):
        return self._parent

    def keyPressEvent(self, event):
        pass

    def showEvent(self, event):
        pass

    def hideEvent(self, event):
        pass

    def closeEvent(self, event):
        pass


class _Signal:
    """Stand-in for a Qt signal — stores a connected handler."""

    def connect(self, handler):
        self._handler = handler


class _MockQPushButton(_MockWidget):
    """Stand-in for QPushButton — stores click handlers."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.text = text
        self._signal = _Signal()
        self._clicked_handlers = []

    @property
    def clicked(self):
        return self._signal

    def setText(self, text):
        self.text = text


class _MockTimer:
    """Stand-in for QTimer — captures singleShot calls."""

    _single_shot_calls = []

    @classmethod
    def singleShot(cls, delay, callback):
        cls._single_shot_calls.append((delay, callback))

    @classmethod
    def clear(cls):
        cls._single_shot_calls.clear()


class _MockQCursor:
    """Stand-in for QCursor — returns a fixed position."""

    @staticmethod
    def pos():
        class _Point:
            def x(self):
                return 800

            def y(self):
                return 600

        return _Point()


class _MockSip:
    """Stand-in for sip — provides isdeleted()."""

    @staticmethod
    def isdeleted(obj):
        return False


class _MockMetaObject:
    """Stand-in for QMetaObject — captures invokeMethod calls."""

    _invoked = []

    @classmethod
    def invokeMethod(cls, obj, method, connection_type):
        cls._invoked.append((obj, method, connection_type))

    @classmethod
    def clear(cls):
        cls._invoked.clear()


# Patch modules before importing QuickListWidget
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.sip"] = _MockSip
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtCore"].Qt = _MockQt
sys.modules["PyQt6.QtCore"].QMetaObject = _MockMetaObject
sys.modules["PyQt6.QtCore"].QTimer = _MockTimer
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtGui"].QCursor = _MockQCursor
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["PyQt6.QtWidgets"].QWidget = _MockWidget
sys.modules["PyQt6.QtWidgets"].QPushButton = _MockQPushButton
sys.modules["PyQt6.QtWidgets"].QVBoxLayout = _MockLayout
sys.modules["PyQt6.QtWidgets"].QHBoxLayout = _MockLayout

# pynput stubs — configure the single MagicMock so attribute access returns the same object
_pynput_mock = MagicMock()
_pynput_mock.keyboard = MagicMock()
_pynput_mock.keyboard.Listener = MagicMock()
_pynput_mock.keyboard.Key = MagicMock()
_pynput_mock.keyboard.Key.esc = "Escape"
sys.modules["pynput"] = _pynput_mock
sys.modules["pynput.keyboard"] = _pynput_mock.keyboard  # keep in sync

from fastprompter.ui.pie_menu import QuickListWidget

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_main_win(**overrides):
    """Create a minimal main_win mock with required attributes."""
    data = {
        "cats_order": ["Code", "Text", "Misc"],
        "theme": "Default",
        "button_scale": "1.0",
        "categories": {
            "Code": [
                {"name": "Snippet A", "text": "a"},
                {"name": "Snippet B", "text": "b"},
            ]
            + [None] * 98,
            "Text": [None] * 100,
            "Misc": [None] * 100,
        },
    }
    data.update(overrides)

    from fastprompter.theme.themes import THEMES

    mw = MagicMock()
    mw.data = data
    mw._theme_cache = THEMES.get(data.get("theme", "Default"), THEMES["Default"])
    mw.get_current_category = MagicMock(return_value="Code")
    mw.fire_global_snippet_from_cat = MagicMock()
    return mw


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_main_win(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        assert widget.main_win is mw

    def test_sets_popup_flags(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        assert widget._flags & _MockQt.WindowType.Popup
        assert widget._flags & _MockQt.WindowType.FramelessWindowHint
        assert widget._flags & _MockQt.WindowType.WindowStaysOnTopHint

    def test_sets_translucent_background(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        assert widget._attributes.get(_MockQt.WidgetAttribute.WA_TranslucentBackground) is True

    def test_sets_delete_on_close(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        assert widget._attributes.get(_MockQt.WidgetAttribute.WA_DeleteOnClose) is True

    def test_uses_current_cat_from_main_win(self):
        mw = make_main_win()
        mw.get_current_category.return_value = "Text"
        widget = QuickListWidget(mw)
        assert widget.current_cat == "Text"

    def test_falls_back_to_first_category(self):
        """If current_cat is not in cats_order, fall back to first."""
        mw = make_main_win()
        mw.get_current_category.return_value = "NonExistent"
        widget = QuickListWidget(mw)
        assert widget.current_cat == "Code"

    def test_empty_cats_does_not_crash(self):
        mw = make_main_win(cats_order=[])
        widget = QuickListWidget(mw)
        assert widget.cats == []


# ---------------------------------------------------------------------------
# init_ui
# ---------------------------------------------------------------------------


class TestInitUi:
    def test_clears_existing_layout(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        # Populate layouts with mock widgets that have deleteLater
        widget.cat_layout._items = [MagicMock()]
        widget.snip_layout._items = [MagicMock()]
        widget.init_ui()
        # After init_ui, layouts should be rebuilt
        assert len(widget.cat_layout._items) > 0, "Should have category buttons"
        assert len(widget.snip_layout._items) > 0, "Should have snippet buttons"

    def test_adds_category_buttons(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget.init_ui()
        # Should have 3 category buttons (Code, Text, Misc)
        assert len(widget.cat_layout._items) == 3

    def test_adds_snippet_buttons_for_current_cat(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget.init_ui()
        # Code category has 2 non-None snippets
        assert len(widget.snip_layout._items) == 2

    def test_limits_to_10_snippets(self):
        items = [{"name": f"S{i}", "text": f"content{i}"} for i in range(15)] + [None] * 85
        mw = make_main_win(categories={"Code": items})
        widget = QuickListWidget(mw)
        widget.init_ui()
        assert len(widget.snip_layout._items) == 10

    def test_empty_cats_returns_early(self):
        mw = make_main_win(cats_order=[])
        widget = QuickListWidget(mw)
        widget.init_ui()
        assert len(widget.cat_layout._items) == 0

    def test_adds_timer_for_adjust_size(self):
        _MockTimer.clear()
        mw = make_main_win()
        QuickListWidget(mw)
        delays = [call[0] for call in _MockTimer._single_shot_calls]
        assert 10 in delays, "Should schedule adjustSize at 10ms"
        assert 15 in delays, "Should schedule center_on_cursor at 15ms"


# ---------------------------------------------------------------------------
# center_on_cursor
# ---------------------------------------------------------------------------


class TestCenterOnCursor:
    def test_moves_to_center_of_cursor(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget._moved_to = None
        widget.center_on_cursor()
        # Cursor is at (800, 600), widget is 200x300
        # center = (800 - 200//2, 600 - 300//2) = (700, 450)
        assert widget._moved_to is not None
        expected_x = 800 - widget.width() // 2
        expected_y = 600 - widget.height() // 2
        assert widget._moved_to == (expected_x, expected_y)


# ---------------------------------------------------------------------------
# switch_cat
# ---------------------------------------------------------------------------


class TestSwitchCat:
    def test_updates_current_cat(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget.switch_cat("Text")
        assert widget.current_cat == "Text"

    def test_rebuilds_ui(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        before_count = len(widget.snip_layout._items)
        widget.switch_cat("Misc")  # Misc has 0 snippets
        # Layout should be rebuilt with new category's snippets
        assert len(widget.snip_layout._items) != before_count or before_count == 0


# ---------------------------------------------------------------------------
# Keyboard events
# ---------------------------------------------------------------------------


class TestKeyPressEvent:
    def test_escape_closes_widget(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget._visible = True
        event = MagicMock()
        event.key.return_value = _MockQt.Key.Key_Escape
        widget.keyPressEvent(event)
        assert widget._visible is False

    def test_other_keys_delegate_to_super(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        event = MagicMock()
        event.key.return_value = _MockQt.Key.Key_Escape + 1  # Not Escape
        with patch.object(_MockWidget, "keyPressEvent") as mock_super:
            widget.keyPressEvent(event)
            mock_super.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Focus events
# ---------------------------------------------------------------------------


class TestFocusOutEvent:
    def test_focus_out_closes_widget(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget._visible = True
        widget.focusOutEvent(MagicMock())
        assert widget._visible is False


# ---------------------------------------------------------------------------
# Show/hide/close events — keyboard listener lifecycle
# ---------------------------------------------------------------------------


class TestShowHideCloseEvents:
    def test_show_starts_keyboard_listener(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        assert widget.kb_listener is None
        widget.showEvent(MagicMock())
        assert widget.kb_listener is not None

    def test_hide_stops_keyboard_listener(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        mock_listener = MagicMock()
        widget.kb_listener = mock_listener
        widget.hideEvent(MagicMock())
        mock_listener.stop.assert_called_once()
        assert widget.kb_listener is None

    def test_close_stops_keyboard_listener(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        mock_listener = MagicMock()
        widget.kb_listener = mock_listener
        widget.closeEvent(MagicMock())
        mock_listener.stop.assert_called_once()
        assert widget.kb_listener is None

    def test_show_does_not_create_duplicate_listener(self):
        mw = make_main_win()
        widget = QuickListWidget(mw)
        mock_listener = MagicMock()
        widget.kb_listener = mock_listener
        widget.showEvent(MagicMock())
        # Listener should not be replaced
        assert widget.kb_listener is mock_listener


# ---------------------------------------------------------------------------
# Global key press
# ---------------------------------------------------------------------------


class TestGlobalKeyPress:
    def test_escape_invokes_close(self):
        _MockMetaObject.clear()
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget.on_global_key_press("Escape")
        assert len(_MockMetaObject._invoked) == 1
        obj, method, conn = _MockMetaObject._invoked[0]
        assert method == "close"
        assert conn == _MockQt.ConnectionType.QueuedConnection

    def test_other_keys_do_nothing(self):
        _MockMetaObject.clear()
        mw = make_main_win()
        widget = QuickListWidget(mw)
        widget.on_global_key_press("SomeOtherKey")
        assert len(_MockMetaObject._invoked) == 0
