"""Clip-safe width for fixed-width buttons and labels.

The app stylesheet renders text at 11px, several theme styles add
font-weight: bold, and emoji fall back to substitution fonts that run
wider than QFontMetrics reports. Every widget that gets a FIXED width
derived from its text must compute it here — measured bold at the
rendered pixel size with padding — so labels can never be clipped.
"""

from PyQt6.QtGui import QFont, QFontMetrics


def clip_safe_width(text, base_font, pixel_size=11, pad=12):
    f = QFont(base_font)
    f.setPixelSize(pixel_size)
    f.setBold(True)  # worst case: themes bold some buttons (NEW/Save)
    w = QFontMetrics(f).horizontalAdvance(text) + pad
    if any(ord(ch) > 0x2000 for ch in text):
        w += 8  # emoji glyphs render wider than their reported advance
    return w
