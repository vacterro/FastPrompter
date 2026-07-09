"""Tests for fastprompter.ui.search_mixin — find/replace logic."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# PyQt6 stubs
# ---------------------------------------------------------------------------


class _MockQt:
    class WindowType:
        Window = 0


class _MockQTextDocument:
    class FindFlag:
        def __init__(self, value=0):
            self._value = int(value)

        def __ior__(self, other):
            if isinstance(other, _MockQTextDocument.FindFlag):
                self._value |= other._value
            else:
                self._value |= int(other)
            return self

        def __int__(self):
            return self._value

        FindBackward = 1

    FindBackward = 1

    def __init__(self, text=""):
        self._text = text

    def toPlainText(self):
        return self._text


class _MockQTextCursor:
    class MoveOperation:
        Start = 0
        End = 1
        StartOfBlock = 2
        EndOfBlock = 3

    class SelectionType:
        Document = 0
        BlockUnderCursor = 1

    def __init__(self):
        self._start = 0
        self._end = 0
        self._text = ""
        self._selection = ""
        self._block = MagicMock()

    def positionInBlock(self):
        return 0

    def movePosition(self, op, mode=0, n=1):
        if op == self.MoveOperation.Start:
            self._start = 0
        elif op == self.MoveOperation.End:
            self._end = len(self._text)
        return True

    def selectedText(self):
        return self._selection

    def hasSelection(self):
        return bool(self._selection)

    def block(self):
        return self._block

    def beginEditBlock(self):
        pass

    def endEditBlock(self):
        pass

    def insertText(self, text):
        pass

    def charFormat(self):
        return MagicMock()

    def mergeCharFormat(self, fmt):
        pass

    def select(self, mode):
        if mode == self.SelectionType.Document:
            self._selection = self._text
        elif mode == self.SelectionType.BlockUnderCursor:
            self._selection = self._text

    def setPosition(self, pos):
        pass

    def clearSelection(self):
        self._selection = ""


class _MockQPlainTextEdit:
    """Stand-in for QPlainTextEdit — tracks setFocus, find calls."""

    def __init__(self, text=""):
        self._doc = _MockQTextDocument(text)
        self._cursor = _MockQTextCursor()
        self._cursor._text = text
        self._focus_count = 0
        self._find_results = []
        self._find_idx = 0

    def document(self):
        return self._doc

    def textCursor(self):
        return self._cursor

    def setTextCursor(self, cursor):
        self._cursor = cursor

    def setFocus(self):
        self._focus_count += 1

    def toPlainText(self):
        return self._doc._text

    def find(self, text, options=0):
        """Simple find simulation — returns True next call, then False."""
        if self._find_idx < len(self._find_results):
            result = self._find_results[self._find_idx]
            self._find_idx += 1
            return result
        return False


class _MockQLineEdit:
    def __init__(self, text=""):
        self._text = text
        self._select_all_called = False
        self._focus_count = 0
        self._visible = True

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def setFocus(self):
        self._focus_count += 1

    def selectAll(self):
        self._select_all_called = True

    def hide(self):
        self._visible = False

    def show(self):
        self._visible = True

    def isVisible(self):
        return self._visible


class _MockQFrame:
    def __init__(self):
        self._visible = False

    def hide(self):
        self._visible = False

    def show(self):
        self._visible = True

    def isVisible(self):
        return self._visible


class _MockQMessageBox:
    _last_info_caption = ""
    _last_info_text = ""

    @classmethod
    def information(cls, parent, caption, text):
        cls._last_info_caption = caption
        cls._last_info_text = text

    @classmethod
    def reset(cls):
        cls._last_info_caption = ""
        cls._last_info_text = ""


sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtGui"].QTextCursor = _MockQTextCursor
sys.modules["PyQt6.QtGui"].QTextDocument = _MockQTextDocument
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["PyQt6.QtWidgets"].QMessageBox = _MockQMessageBox
sys.modules["PyQt6.QtWidgets"].QPlainTextEdit = _MockQPlainTextEdit
sys.modules["PyQt6.QtWidgets"].QLineEdit = _MockQLineEdit
sys.modules["PyQt6.QtWidgets"].QFrame = _MockQFrame
sys.modules["PyQt6.QtCore"] = MagicMock()

from fastprompter.ui.search_mixin import SearchMixin

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_search_mixin(**overrides):
    """Create a SearchMixin instance with mock attributes."""
    mixin = SearchMixin()
    mixin.search_frame = _MockQFrame()
    mixin.search_input = _MockQLineEdit("")
    mixin.replace_input = _MockQLineEdit("")
    mixin.text_area = _MockQPlainTextEdit("")
    mixin.btn_replace = _MockQFrame()
    mixin.btn_replace_all = _MockQFrame()
    mixin.search_bar = MagicMock()
    mixin.data = {}
    mixin.mark_dirty = MagicMock()

    for k, v in overrides.items():
        setattr(mixin, k, v)

    return mixin


# ---------------------------------------------------------------------------
# show_find / show_replace
# ---------------------------------------------------------------------------


class TestShowFind:
    def test_shows_frame(self):
        m = make_search_mixin()
        m.show_find()
        assert m.search_frame._visible is True

    def test_hides_replace_widgets(self):
        m = make_search_mixin()
        m.show_find()
        assert m.replace_input._visible is False
        assert m.btn_replace._visible is False
        assert m.btn_replace_all._visible is False

    def test_focuses_search_input(self):
        m = make_search_mixin()
        m.show_find()
        assert m.search_input._focus_count > 0


class TestShowReplace:
    def test_shows_frame(self):
        m = make_search_mixin()
        m.show_replace()
        assert m.search_frame._visible is True

    def test_shows_replace_widgets(self):
        m = make_search_mixin()
        m.show_replace()
        assert m.replace_input._visible is True
        assert m.btn_replace._visible is True
        assert m.btn_replace_all._visible is True


class TestCloseSearch:
    def test_hides_frame(self):
        m = make_search_mixin()
        m.search_frame.show()
        m.close_search()
        assert m.search_frame._visible is False

    def test_focuses_text_area(self):
        m = make_search_mixin()
        before = m.text_area._focus_count
        m.close_search()
        assert m.text_area._focus_count == before + 1


# ---------------------------------------------------------------------------
# find_text
# ---------------------------------------------------------------------------


class TestFindText:
    def test_empty_query_does_nothing(self):
        m = make_search_mixin()
        m.search_input._text = ""
        m.find_text(backward=False)
        # Should not crash

    def test_wrap_around(self):
        """When no match found, wraps around and tries again."""
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.text_area._find_results = [False, True]
        m.find_text(backward=False)
        assert m.text_area._find_idx == 2  # both calls consumed

    def test_wrap_around_no_match(self):
        """When neither direct nor wrapped search finds match, cursor is restored."""
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.text_area._find_results = [False, False]
        m.find_text(backward=False)
        assert m.text_area._find_idx == 2

    def test_find_backward(self):
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.text_area._find_results = [True]
        m.find_text(backward=True)
        assert m.text_area._find_idx == 1

    def test_find_forward(self):
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.text_area._find_results = [True]
        m.find_text(backward=False)
        assert m.text_area._find_idx == 1


# ---------------------------------------------------------------------------
# replace_text
# ---------------------------------------------------------------------------


class TestReplaceText:
    def test_replaces_selection_and_finds_next(self):
        m = make_search_mixin()
        m.search_input._text = "old"
        m.replace_input._text = "new"
        m.text_area._cursor._selection = "old"
        m.text_area._find_results = [True]
        m.replace_text()
        assert m.text_area._find_idx == 1

    def test_no_selection_does_not_replace(self):
        m = make_search_mixin()
        m.search_input._text = "old"
        m.replace_input._text = "new"
        m.text_area._cursor._selection = ""
        m.text_area._find_results = [True]
        m.replace_text()
        # Should still call find_next
        assert m.text_area._find_idx == 1


# ---------------------------------------------------------------------------
# replace_all
# ---------------------------------------------------------------------------


class TestReplaceAll:
    def test_empty_query_does_nothing(self):
        _MockQMessageBox.reset()
        m = make_search_mixin()
        m.search_input._text = ""
        m.replace_all()
        # Should not show a message box
        assert _MockQMessageBox._last_info_caption == ""

    def test_shows_count_message(self):
        _MockQMessageBox.reset()
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.replace_input._text = "replacement"
        m.text_area._find_results = [True, True, True, False]
        m.replace_all()
        assert _MockQMessageBox._last_info_caption == "Replace All"
        assert "3" in _MockQMessageBox._last_info_text

    def test_zero_replaces_shows_zero(self):
        _MockQMessageBox.reset()
        m = make_search_mixin()
        m.search_input._text = "needle"
        m.text_area._find_results = [False]
        m.replace_all()
        assert _MockQMessageBox._last_info_caption == "Replace All"
        assert "0" in _MockQMessageBox._last_info_text


# ---------------------------------------------------------------------------
# on_search_toggle
# ---------------------------------------------------------------------------


class TestOnSearchToggle:
    def test_checked_shows_bar(self):
        m = make_search_mixin()
        m.on_search_toggle(True)
        m.search_bar.setVisible.assert_called_once_with(True)
        assert m.data.get("search_visible") == "True"
        m.mark_dirty.assert_called_once()

    def test_unchecked_hides_bar(self):
        m = make_search_mixin()
        m.on_search_toggle(False)
        assert m.data.get("search_visible") == "False"
        m.mark_dirty.assert_called_once()

    def test_unchecked_clears_bar(self):
        m = make_search_mixin()
        m.on_search_toggle(False)
        m.search_bar.clear.assert_called_once()
