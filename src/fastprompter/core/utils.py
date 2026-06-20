import ctypes
import re
from PyQt6.QtGui import QKeySequence, QGuiApplication
from PyQt6.QtCore import Qt, QMimeData

def parse_hotkey(hotkey_str):
    """
    Parses a hotkey string like 'Ctrl+Shift+L' into (modifiers, vk).
    Returns (0, 0) if parsing fails.
    """
    if not hotkey_str: return 0, 0
    try:
        parts = [p.strip().upper() for p in hotkey_str.split('+')]
        modifiers = 0
        vk = 0
        
        # Modifier flags for RegisterHotKey
        MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
        
        for part in parts:
            if part in ('CTRL', 'CONTROL'): modifiers |= MOD_CONTROL
            elif part in ('ALT', 'MENU'): modifiers |= MOD_ALT
            elif part in ('SHIFT',): modifiers |= MOD_SHIFT
            elif part in ('WIN', 'META'): modifiers |= MOD_WIN
            elif part.startswith('F') and part[1:].isdigit():
                vk = 0x70 + int(part[1:]) - 1 # VK_F1 is 0x70
            elif part.startswith('NUMPAD') and part[6:].isdigit():
                vk = 0x60 + int(part[6:])
            elif len(part) == 1 and part.isalnum():
                vk = ord(part.upper())
            else:
                # Basic keys
                mapping = {
                    'ESC': 0x1B, 'ESCAPE': 0x1B, 'SPACE': 0x20, 'RETURN': 0x0D,
                    'ENTER': 0x0D, 'BACKSPACE': 0x08, 'TAB': 0x09, 'UP': 0x26,
                    'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27, 'INS': 0x2D,
                    'INSERT': 0x2D, 'DEL': 0x2E, 'DELETE': 0x2E, 'HOME': 0x24,
                    'END': 0x23, 'PGUP': 0x21, 'PAGEUP': 0x21, 'PGDN': 0x22,
                    'PAGEDOWN': 0x22, '`': 0xC0, '-': 0xBD, '=': 0xBB,
                    '[': 0xDB, ']': 0xDD, '\\': 0xDC, ';': 0xBA, "'": 0xDE,
                    ',': 0xBC, '.': 0xBE, '/': 0xBF
                }
                vk = mapping.get(part, 0)
        return modifiers, vk
    except Exception:
        return 0, 0

def simulate_ctrl_v():
    """
    Simulates Ctrl+V using SendInput (Input structure) to prevent forcefully releasing user keys.
    """
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (("wVk", ctypes.c_ushort),
                    ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)))
    class INPUT_union(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", ctypes.c_ulong * 6), ("hi", ctypes.c_ulong * 6))
    class INPUT(ctypes.Structure):
        _fields_ = (("type", ctypes.c_ulong), ("union", INPUT_union))
        
    def send_key(vk, up=False):
        i = INPUT(type=1)
        i.union.ki.wVk = vk
        i.union.ki.dwFlags = 2 if up else 0
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))

    VK_CONTROL = 0x11
    VK_V = 0x56

    send_key(VK_CONTROL, False)
    send_key(VK_V, False)
    send_key(VK_V, True)
    send_key(VK_CONTROL, True)

def safe_set_clipboard(text, is_plain=True):
    """
    Safely sets the clipboard using PyQt6's QGuiApplication instead of deprecated QApplication.
    """
    if not text: return
    clip = QGuiApplication.clipboard()
    if is_plain:
        clip.setText(text)
    else:
        mime = QMimeData()
        mime.setText(text)
        
        # Simple Markdown to HTML conversion
        html = text
        html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)
        html = re.sub(r'\*(.+?)\*', r'<i>\1</i>', html)
        html = re.sub(r'_(.+?)_', r'<u>\1</u>', html)
        html = re.sub(r'~~(.+?)~~', r'<s>\1</s>', html)
        html = html.replace('\n', '<br>')
        
        mime.setHtml(html)
        clip.setMimeData(mime)
