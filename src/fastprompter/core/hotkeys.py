import ctypes
import ctypes.wintypes
from PyQt6.QtCore import QAbstractNativeEventFilter, pyqtSignal, QObject
from typing import Callable, Dict, Tuple

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

def parse_hotkey(hotkey_str):
    if not hotkey_str: return 0, 0
    parts = hotkey_str.upper().split('+')
    modifiers, vk = 0, 0
    for part in parts:
        part = part.strip()
        if part == 'CTRL': modifiers |= MOD_CONTROL
        elif part == 'ALT': modifiers |= MOD_ALT
        elif part == 'SHIFT': modifiers |= MOD_SHIFT
        elif part == 'WIN': modifiers |= MOD_WIN
        elif len(part) == 1 and 'A' <= part <= 'Z': vk = ord(part)
        elif len(part) == 1 and '0' <= part <= '9': vk = ord(part)
        elif part.startswith('F') and part[1:].isdigit(): vk = 0x6F + int(part[1:])
        elif part.startswith('NUMPAD') and part[6:].isdigit() and 0 <= int(part[6:]) <= 9: vk = 0x60 + int(part[6:])
        elif part == 'SPACE': vk = 0x20
    return modifiers, vk

class HotkeySignals(QObject):
    toggle_visibility = pyqtSignal()
    show_quick_list = pyqtSignal()
    toggle_lock = pyqtSignal()
    toggle_always_on_top = pyqtSignal()
    fire_snippet = pyqtSignal(int)
    kill_app = pyqtSignal()

class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.signals = HotkeySignals()
        self.win_id = None
        
    def set_win_id(self, win_id):
        self.win_id = win_id

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == 1: self.signals.toggle_visibility.emit(); return True, 0
                    elif msg.wParam == 2: self.signals.show_quick_list.emit(); return True, 0
                    elif msg.wParam == 3: self.signals.toggle_lock.emit(); return True, 0
                    elif msg.wParam == 4: self.signals.toggle_always_on_top.emit(); return True, 0
                    elif msg.wParam == 5: self.signals.kill_app.emit(); return True, 0
                    elif 10 <= msg.wParam <= 19: self.signals.fire_snippet.emit(msg.wParam - 10); return True, 0
        except Exception:
            pass
        return False, 0

    def parse_hotkey(self, text: str) -> Tuple[int, int]:
        if not text: return 0, 0
        parts = text.split("+")
        modifiers = 0
        key_name = parts[-1].strip().upper()
        if "Ctrl" in parts: modifiers |= MOD_CONTROL
        if "Alt" in parts: modifiers |= MOD_ALT
        if "Shift" in parts: modifiers |= MOD_SHIFT
        if "Win" in parts: modifiers |= MOD_WIN
        
        # Virtual Key codes mapping
        vk_map = {
            'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45, 'F': 0x46, 'G': 0x47, 'H': 0x48,
            'I': 0x49, 'J': 0x4A, 'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F, 'P': 0x50,
            'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54, 'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58,
            'Y': 0x59, 'Z': 0x5A, '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
            '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
            'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
            'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
            'SPACE': 0x20, 'ENTER': 0x0D, 'ESC': 0x1B, 'TAB': 0x09, 'BACKSPACE': 0x08,
            'INSERT': 0x2D, 'DELETE': 0x2E, 'HOME': 0x24, 'END': 0x23, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
            'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27,
            '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
            ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF
        }
        vk = vk_map.get(key_name, 0)
        return modifiers, vk

    def register(self, hk_id: int, hotkey_str: str) -> bool:
        if not self.win_id or not hotkey_str: return False
        mods, vk = self.parse_hotkey(hotkey_str)
        if vk == 0: return False
        return ctypes.windll.user32.RegisterHotKey(int(self.win_id), hk_id, mods, vk)

    def unregister_all(self):
        if not self.win_id: return
        for i in range(1, 20):
            try: ctypes.windll.user32.UnregisterHotKey(int(self.win_id), i)
            except Exception: pass
