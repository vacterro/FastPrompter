"""Global hotkey event filter for FastPrompter.

Intercepts WM_HOTKEY (0x0312) and WM_SYSCOMMAND (0x0112 / SC_KEYMENU)
messages to trigger window actions from registered global hotkeys.
"""

import ctypes
import ctypes.wintypes

from PyQt6 import sip
from PyQt6.QtCore import QAbstractNativeEventFilter

from fastprompter.core.logging import logger

_is_deleted = sip.isdeleted


class HotkeyFilter(QAbstractNativeEventFilter):
    """Native Win32 event filter that dispatches registered hotkeys.

    Maps ``wParam`` values (set when ``RegisterHotKey`` is called) to
    window actions such as toggle visibility, show pie menu, etc.

    Usage::

        filter_obj = HotkeyFilter(window)
        app.installNativeEventFilter(filter_obj)
    """

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window

    def nativeEventFilter(self, eventType: bytes, message) -> tuple[bool, int]:
        if _is_deleted(self.window):
            return False, 0
        try:
            if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam in (1, 101):
                        self.window.toggle_visibility()
                        return True, 0
                    elif msg.wParam in (2, 102):
                        self.window.show_quick_list()
                        return True, 0
                    elif msg.wParam in (3, 103):
                        self.window.toggle_lock()
                        return True, 0
                    elif msg.wParam in (4, 104):
                        self.window.toggle_always_on_top()
                        return True, 0
                    elif msg.wParam in (5, 105):
                        self.window.toggle_visibility(force_sidebar=True)
                        return True, 0
                    elif msg.wParam in (6, 106):
                        self.window.toggle_hide_on_clickout()
                        return True, 0
                    elif (10 <= msg.wParam <= 14) or (110 <= msg.wParam <= 114):
                        self.window.fire_global_snippet((msg.wParam % 100) - 10)
                        return True, 0
                    elif (20 <= msg.wParam <= 24) or (120 <= msg.wParam <= 124):
                        self.window.fire_global_silo((msg.wParam % 100) - 20)
                        return True, 0
                elif msg.message == 0x0112:  # WM_SYSCOMMAND
                    if (msg.wParam & 0xFFF0) == 0xF100:  # SC_KEYMENU
                        return True, 0
        except Exception:
            logger.exception("Error in native event filter")
        return False, 0
