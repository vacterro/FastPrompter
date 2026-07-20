"""Keyboard-layout-independent shortcuts.

Qt matches shortcuts on the CHARACTER a key produces, not the key itself.
With a non-Latin layout active (Russian, Greek, Hebrew...) the Z key emits
a Cyrillic/Greek letter instead, so Alt+Z simply never fires - the app
looks broken until you switch back to English.

This filter matches on the PHYSICAL key instead. Windows gives us the
scan code on every key event; translating scan -> virtual-key yields a
code that is the same no matter which layout is loaded (VK 0x5A is the Z
key whatever it prints).

It deliberately stays a fallback: if the event already carries the Qt key
we want, the ordinary QShortcut has it covered and we do nothing, so a
shortcut can never fire twice.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt

try:
    import ctypes

    _user32 = ctypes.windll.user32
except Exception:  # pragma: no cover - non-Windows
    _user32 = None

_MAPVK_VSC_TO_VK_EX = 3

# Virtual-key codes that are layout-stable, mapped to their Qt equivalents.
_VK_TO_QT: dict[int, Qt.Key] = {}
for _i in range(26):  # A-Z
    _VK_TO_QT[0x41 + _i] = Qt.Key(Qt.Key.Key_A.value + _i)
for _i in range(10):  # 0-9 (top row)
    _VK_TO_QT[0x30 + _i] = Qt.Key(Qt.Key.Key_0.value + _i)
_VK_TO_QT.update({
    0xC0: Qt.Key.Key_QuoteLeft,   # ` ~   (the Alt+` settings toggle)
    0xBD: Qt.Key.Key_Minus,
    0xBB: Qt.Key.Key_Equal,
    0xDB: Qt.Key.Key_BracketLeft,
    0xDD: Qt.Key.Key_BracketRight,
    0xDC: Qt.Key.Key_Backslash,
    0xBA: Qt.Key.Key_Semicolon,
    0xDE: Qt.Key.Key_Apostrophe,
    0xBC: Qt.Key.Key_Comma,
    0xBE: Qt.Key.Key_Period,
    0xBF: Qt.Key.Key_Slash,
})

# Only these participate in matching; Keypad/GroupSwitch etc. would make
# otherwise-identical chords compare unequal.
_MOD_MASK = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.MetaModifier
)


def physical_key(event) -> Qt.Key | None:
    """The Qt key for the PHYSICAL key pressed, ignoring the layout."""
    if _user32 is None:
        return None
    scan = event.nativeScanCode()
    if not scan:
        return None
    try:
        vk = _user32.MapVirtualKeyW(scan, _MAPVK_VSC_TO_VK_EX)
    except Exception:
        return None
    return _VK_TO_QT.get(int(vk))


def split_sequence(seq):
    """QKeySequence -> (key, modifiers), or (None, None) if unusable.

    Only single-chord sequences can be matched this way.
    """
    if seq is None or seq.isEmpty() or seq.count() != 1:
        return None, None
    combo = seq[0]
    try:
        key = Qt.Key(combo.key())
        mods = combo.keyboardModifiers()
    except (AttributeError, TypeError, ValueError):
        # PyQt < 6.4 hands back a plain int
        raw = int(combo)
        key = Qt.Key(raw & ~int(_MOD_MASK.value))
        mods = Qt.KeyboardModifier(raw & int(_MOD_MASK.value))
    return key, (mods & _MOD_MASK)


class LayoutIndependentShortcuts(QObject):
    """Fires registered callbacks on physical-key matches."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bindings: list[tuple[Qt.Key, Qt.KeyboardModifier, object]] = []

    def clear(self):
        self._bindings.clear()

    def register(self, sequence, slot) -> bool:
        key, mods = split_sequence(sequence)
        if key is None or key not in _VK_TO_QT.values():
            return False  # F-keys, Esc, arrows… already layout-independent
        self._bindings.append((key, mods, slot))
        return True

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress or not self._bindings:
            return False
        mods = event.modifiers() & _MOD_MASK
        if not mods:
            return False  # never swallow plain typing
        phys = physical_key(event)
        if phys is None:
            return False
        if Qt.Key(event.key()) == phys:
            return False  # Latin layout — the real QShortcut handles it
        for key, want_mods, slot in self._bindings:
            if key == phys and want_mods == mods:
                slot()
                return True
        return False
