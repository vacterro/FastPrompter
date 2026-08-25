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
                    # Only handle global hotkeys: toggle_visibility (1, 101) and pie_menu (2, 102)
                    if msg.wParam in (1, 101):
                        self.window.toggle_visibility()
                        return True, 0
                    elif msg.wParam in (2, 102):
                        self.window.show_quick_list()
                        return True, 0
                    elif msg.wParam == 300:
                        # Swallowed only when it actually stopped a run, so
                        # the key stays usable elsewhere while nothing is
                        # armed. Compared against True rather than tested for
                        # truthiness: any object at all is truthy, and this
                        # decides whether another application sees the key.
                        if self.window.watcher_panic() is True:
                            return True, 0
                elif msg.message == 0x0112:  # WM_SYSCOMMAND
                    if (msg.wParam & 0xFFF0) == 0xF100:  # SC_KEYMENU
                        return True, 0
                elif msg.message in (0x0101, 0x0105):  # WM_KEYUP, WM_SYSKEYUP
                    # P1-7 Fix: Windows natively broadcasts the release, but Qt ignores it
                    # if the window lacks focus, leaving modifier states stuck. Map it here.
                    from PyQt6.QtCore import QEvent, Qt
                    from PyQt6.QtGui import QKeyEvent
                    from PyQt6.QtWidgets import QApplication
                    vk = msg.wParam
                    key = 0
                    if vk == 0x10: key = Qt.Key.Key_Shift
                    elif vk == 0x11: key = Qt.Key.Key_Control
                    elif vk == 0x12: key = Qt.Key.Key_Alt
                    elif vk in (0x5B, 0x5C): key = Qt.Key.Key_Meta
                    if key:
                        evt = QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier)
                        QApplication.postEvent(self.window, evt)
        except Exception:
            logger.exception("Error in native event filter")
        return False, 0
