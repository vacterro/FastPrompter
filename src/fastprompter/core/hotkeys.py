import ctypes
import ctypes.wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Cache the user32.VkKeyScanW function pointer for layout-aware VK resolution.
# VkKeyScanW converts a character to its virtual-key code and shift state
# based on the current keyboard layout, so hotkeys work on any layout (AZERTY, QWERTZ, etc.).
_VkKeyScanW = ctypes.windll.user32.VkKeyScanW
_VkKeyScanW.argtypes = [ctypes.wintypes.WCHAR]
_VkKeyScanW.restype = ctypes.wintypes.SHORT

# Static VK map for keys that are layout-independent.
# Letter keys (A-Z), digits (0-9), function keys, and named keys like SPACE/ENTER
# have the same VK codes on every Windows keyboard layout.
_STATIC_VK = {
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45, 'F': 0x46, 'G': 0x47, 'H': 0x48,
    'I': 0x49, 'J': 0x4A, 'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F, 'P': 0x50,
    'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54, 'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58,
    'Y': 0x59, 'Z': 0x5A, '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
    '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'F13': 0x7C, 'F14': 0x7D, 'F15': 0x7E, 'F16': 0x7F,
    'F17': 0x80, 'F18': 0x81, 'F19': 0x82, 'F20': 0x83,
    'F21': 0x84, 'F22': 0x85, 'F23': 0x86, 'F24': 0x87,
    'SPACE': 0x20, 'ENTER': 0x0D, 'ESC': 0x1B, 'TAB': 0x09, 'BACKSPACE': 0x08,
    'INSERT': 0x2D, 'DELETE': 0x2E, 'HOME': 0x24, 'END': 0x23, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
    'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27,
    'PRINTSCREEN': 0x2C, 'SCROLLLOCK': 0x91, 'PAUSE': 0x13, 'CAPSLOCK': 0x14, 'NUMLOCK': 0x90,
    # Fallback US-layout OEM mapping (used if VkKeyScanW fails)
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
}

# Characters that should always use VkKeyScanW for layout-aware resolution.
# These are symbol/OEM characters whose VK codes differ between layouts.
_LAYOUT_DEPENDENT = set("`-=[]\\;',./!@#$%^&*()_+{}|:\"<>?~")


def _resolve_vk(key_name: str) -> int:
    """Resolve a key name to its Windows VK code.

    For layout-dependent symbol characters, uses VkKeyScanW to get the
    correct VK code for the current keyboard layout.
    Falls back to the static US-layout mapping if resolution fails.
    """
    # Check if this is a layout-dependent single character
    if len(key_name) == 1 and key_name in _LAYOUT_DEPENDENT:
        ch = key_name if key_name.isupper() else key_name.upper()
        try:
            result = _VkKeyScanW(ch)
            if result != -1:  # -1 means no key produces this character
                vk = result & 0xFF
                if vk > 0:
                    return vk
        except Exception:
            pass
    # Fall back to static mapping
    return _STATIC_VK.get(key_name, 0)


def parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    if not hotkey_str: return 0, 0
    parts = hotkey_str.upper().split('+')
    modifiers = 0
    key_name = parts[-1].strip()
    for p in parts:
        p = p.strip()
        if p == "CTRL": modifiers |= MOD_CONTROL
        elif p == "ALT": modifiers |= MOD_ALT
        elif p == "SHIFT": modifiers |= MOD_SHIFT
        elif p == "WIN": modifiers |= MOD_WIN

    if key_name.startswith('NUMPAD') and key_name[6:].isdigit() and 0 <= int(key_name[6:]) <= 9:
        vk = 0x60 + int(key_name[6:])
    elif key_name.startswith('F') and key_name[1:].isdigit():
        f_num = int(key_name[1:])
        if 1 <= f_num <= 24:
            vk = 0x6F + f_num
        else:
            vk = 0
    else:
        vk = _resolve_vk(key_name)

    return modifiers, vk
