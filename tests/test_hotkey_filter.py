"""Tests for fastprompter.core.hotkey_filter — HotkeyFilter."""

import ctypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock


# Build minimal Qt stubs so HotkeyFilter can be imported without real PyQt6
class _MockSip:
    """Stand-in for the sip module — provides isdeleted()."""

    @staticmethod
    def isdeleted(obj):
        return False


class _MockAbstractEventFilter:
    """Stand-in for QAbstractNativeEventFilter."""

    def __init__(self, parent=None):
        self._parent = parent

    def nativeEventFilter(self, eventType, message):
        return False, 0


# Patch modules before importing HotkeyFilter
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.sip"] = _MockSip
sys.modules["PyQt6"].sip = _MockSip
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtCore"].QAbstractNativeEventFilter = _MockAbstractEventFilter

from fastprompter.core.hotkey_filter import HotkeyFilter


class _MsgPointer:
    """Wraps a MSG structure so __int__() returns its memory address.

    The production code calls ``message.__int__()`` on the second argument
    passed to ``nativeEventFilter`` — this is a pointer provided by Qt's
    native event system.  Our stubs must return a real memory address
    so that ``ctypes.wintypes.MSG.from_address()`` can reconstruct the
    structure fields.
    """

    def __init__(self, msg: ctypes.wintypes.MSG) -> None:
        self._msg = msg

    def __int__(self) -> int:
        return ctypes.addressof(self._msg)


def _make_msg(message=0x0312, wParam=1, lParam=0) -> _MsgPointer:
    """Create a _MsgPointer wrapping a ctypes MSG with specified fields."""
    msg = ctypes.wintypes.MSG()
    msg.hwnd = 0
    msg.message = message
    msg.wParam = wParam
    msg.lParam = lParam
    msg.time = 0
    msg.pt = ctypes.wintypes.POINT(0, 0)
    return _MsgPointer(msg)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestHotkeyFilterInit:
    """Verify HotkeyFilter initialization."""

    def test_window_is_stored(self):
        window = MagicMock()
        hf = HotkeyFilter(window)
        assert hf.window is window

    def test_extends_abstract_event_filter(self):
        hf = HotkeyFilter(MagicMock())
        assert isinstance(hf, _MockAbstractEventFilter)


# ---------------------------------------------------------------------------
# WM_HOTKEY dispatch
# ---------------------------------------------------------------------------


class TestWMHotkeyDispatch:
    """Verify WM_HOTKEY (0x0312) messages trigger correct window methods."""

    def _filter_event(self, wParam, window=None, msg_id=0x0312):
        """Helper: simulate a nativeEventFilter call with given MSG fields."""
        if window is None:
            window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=msg_id, wParam=wParam)
        # MSG.from_address needs a real pointer to the MSG
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        return result, window

    def test_wparam_1_toggles_visibility(self):
        """wParam=1 (global_hotkey) -> calls window.toggle_visibility()."""
        result, win = self._filter_event(1)
        assert result == (True, 0)
        win.toggle_visibility.assert_called_once()

    def test_wparam_101_toggles_visibility_alt(self):
        """wParam=101 (global_hotkey_alt) -> calls window.toggle_visibility()."""
        result, win = self._filter_event(101)
        assert result == (True, 0)
        win.toggle_visibility.assert_called_once()

    def test_wparam_2_shows_quick_list(self):
        """wParam=2 (pie_menu_hotkey) -> calls window.show_quick_list()."""
        result, win = self._filter_event(2)
        assert result == (True, 0)
        win.show_quick_list.assert_called_once()

    def test_wparam_102_shows_quick_list_alt(self):
        """wParam=102 (pie_menu_hotkey_alt) -> calls window.show_quick_list()."""
        result, win = self._filter_event(102)
        assert result == (True, 0)
        win.show_quick_list.assert_called_once()

    # Non-global hotkeys (lock/AOT/sidebar/snippet/silo) are handled by
    # window-local QShortcuts, NOT the global native filter. The filter must
    # NOT consume them — otherwise Alt+D & co. react system-wide (that was
    # the bug). It returns (False, 0) so Qt routes them locally.
    def test_wparam_3_lock_not_handled_globally(self):
        result, win = self._filter_event(3)
        assert result == (False, 0)
        win.toggle_lock.assert_not_called()

    def test_wparam_300_stops_the_watcher(self):
        """The watcher types into ANOTHER application, so its stop key has to
        work from whatever window the user is in when they decide it is going
        wrong - not only from FastPrompter."""
        window = MagicMock()
        window.watcher_panic.return_value = True
        result, win = self._filter_event(300, window=window)
        win.watcher_panic.assert_called_once()
        assert result == (True, 0)

    def test_wparam_300_is_passed_on_when_nothing_was_armed(self):
        """A stray press must stay usable in whatever app the user is in."""
        window = MagicMock()
        window.watcher_panic.return_value = False
        result, _win = self._filter_event(300, window=window)
        assert result == (False, 0)

    def test_a_watcher_that_returns_something_odd_does_not_eat_the_key(self):
        """The mock default is a MagicMock, which is truthy. Swallowing on
        truthiness would take the key away from another application on the
        strength of any object at all."""
        result, _win = self._filter_event(300)
        assert result == (False, 0)

    def test_wparam_103_lock_alt_not_handled_globally(self):
        result, win = self._filter_event(103)
        assert result == (False, 0)
        win.toggle_lock.assert_not_called()

    def test_wparam_4_aot_not_handled_globally(self):
        result, win = self._filter_event(4)
        assert result == (False, 0)
        win.toggle_always_on_top.assert_not_called()

    def test_wparam_104_aot_alt_not_handled_globally(self):
        result, win = self._filter_event(104)
        assert result == (False, 0)
        win.toggle_always_on_top.assert_not_called()

    def test_wparam_5_sidebar_not_handled_globally(self):
        result, win = self._filter_event(5)
        assert result == (False, 0)
        win.toggle_visibility.assert_not_called()

    def test_wparam_105_sidebar_alt_not_handled_globally(self):
        result, win = self._filter_event(105)
        assert result == (False, 0)
        win.toggle_visibility.assert_not_called()

    def test_wparam_10_snippet_not_handled_globally(self):
        result, win = self._filter_event(10)
        assert result == (False, 0)
        win.fire_global_snippet.assert_not_called()

    def test_wparam_14_snippet_not_handled_globally(self):
        result, win = self._filter_event(14)
        assert result == (False, 0)
        win.fire_global_snippet.assert_not_called()

    def test_wparam_110_snippet_alt_not_handled_globally(self):
        result, win = self._filter_event(110)
        assert result == (False, 0)
        win.fire_global_snippet.assert_not_called()

    def test_wparam_114_snippet_alt_not_handled_globally(self):
        result, win = self._filter_event(114)
        assert result == (False, 0)
        win.fire_global_snippet.assert_not_called()

    def test_wparam_20_silo_not_handled_globally(self):
        result, win = self._filter_event(20)
        assert result == (False, 0)
        win.fire_global_silo.assert_not_called()

    def test_wparam_24_silo_not_handled_globally(self):
        result, win = self._filter_event(24)
        assert result == (False, 0)
        win.fire_global_silo.assert_not_called()

    def test_wparam_120_silo_alt_not_handled_globally(self):
        result, win = self._filter_event(120)
        assert result == (False, 0)
        win.fire_global_silo.assert_not_called()

    def test_wparam_124_silo_alt_not_handled_globally(self):
        result, win = self._filter_event(124)
        assert result == (False, 0)
        win.fire_global_silo.assert_not_called()


# ---------------------------------------------------------------------------
# WM_SYSCOMMAND handling
# ---------------------------------------------------------------------------


class TestWMSysCommand:
    """Verify WM_SYSCOMMAND (0x0112 / SC_KEYMENU) is consumed."""

    def test_sc_keymenu_is_consumed(self):
        """SC_KEYMENU (0xF100) should be consumed (return True)."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0112, wParam=0xF100)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (True, 0), "SC_KEYMENU should be consumed"

    def test_other_syscommand_is_not_consumed(self):
        """Non-SC_KEYMENU syscommands should not be consumed."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0112, wParam=0xF120)  # SC_MOVE or similar
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0), "Non-SC_KEYMENU should not be consumed"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Verify edge cases and error handling."""

    def test_unknown_wparam_does_nothing(self):
        """An unrecognized wParam value should not trigger any action."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=999)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        # Should return False (not consumed) and no method called
        assert result == (False, 0)
        window.toggle_visibility.assert_not_called()
        window.show_quick_list.assert_not_called()
        window.toggle_lock.assert_not_called()

    def test_non_windows_event_type_returns_false(self):
        """Non-Windows event types should return (False, 0) immediately."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        result = hf.nativeEventFilter(b"generic", None)
        assert result == (False, 0)
        window.toggle_visibility.assert_not_called()

    def test_windows_dispatcher_msg_also_works(self):
        """windows_dispatcher_MSG should be handled like windows_generic_MSG."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=1)
        result = hf.nativeEventFilter(b"windows_dispatcher_MSG", msg)
        assert result == (True, 0)
        window.toggle_visibility.assert_called_once()

    def test_snippet_wparam_out_of_range_does_nothing(self):
        """wParam=9 (just below snippet range 10-14) should not trigger."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=9)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0)
        window.fire_global_snippet.assert_not_called()

    def test_snippet_wparam_above_range_does_nothing(self):
        """wParam=15 (just above snippet range 10-14) should not trigger."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=15)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0)
        window.fire_global_snippet.assert_not_called()

    def test_alternate_snippet_wparam_out_of_range_does_nothing(self):
        """wParam=115 (just above alt snippet range 110-114) should not trigger."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=115)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0)
        window.fire_global_snippet.assert_not_called()

    def test_silo_wparam_below_range_does_nothing(self):
        """wParam=19 (just below silo range 20-24) should not trigger."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        msg = _make_msg(message=0x0312, wParam=19)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0)
        window.fire_global_silo.assert_not_called()

    def test_both_wm_hotkey_and_syscommand_check_order(self):
        """WM_HOTKEY is checked before WM_SYSCOMMAND, and unknown messages fall through."""
        window = MagicMock()
        hf = HotkeyFilter(window)
        # A non-WM_HOTKEY, non-WM_SYSCOMMAND message should return False
        msg = _make_msg(message=0x0100, wParam=0)  # WM_KEYDOWN (unhandled)
        result = hf.nativeEventFilter(b"windows_generic_MSG", msg)
        assert result == (False, 0)

    def test_multiple_hotkeys_sequentially(self):
        """Multiple WM_HOTKEY messages in sequence -> each triggers its action."""
        window = MagicMock()
        hf = HotkeyFilter(window)

        msg1 = _make_msg(message=0x0312, wParam=1)
        result1 = hf.nativeEventFilter(b"windows_generic_MSG", msg1)
        assert result1 == (True, 0)

        msg2 = _make_msg(message=0x0312, wParam=2)
        result2 = hf.nativeEventFilter(b"windows_generic_MSG", msg2)
        assert result2 == (True, 0)

        window.toggle_visibility.assert_called_once()
        window.show_quick_list.assert_called_once()
