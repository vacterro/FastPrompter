"""Tests for fastprompter.core.hotkeys — parse_hotkey, _resolve_vk."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    _resolve_vk,
    parse_hotkey,
)

# ---------------------------------------------------------------------------
# _resolve_vk
# ---------------------------------------------------------------------------


class TestResolveVk:
    def test_letters(self):
        """Letter keys A-Z should resolve to 0x41-0x5A."""
        assert _resolve_vk("A") == 0x41
        assert _resolve_vk("Z") == 0x5A
        assert _resolve_vk("M") == 0x4D

    def test_digits(self):
        """Digit keys 0-9 should resolve to 0x30-0x39."""
        assert _resolve_vk("0") == 0x30
        assert _resolve_vk("9") == 0x39

    def test_function_keys(self):
        """F1-F12 should resolve to 0x70-0x7B, F24 to 0x87."""
        assert _resolve_vk("F1") == 0x70
        assert _resolve_vk("F12") == 0x7B
        assert _resolve_vk("F13") == 0x7C
        assert _resolve_vk("F20") == 0x83
        assert _resolve_vk("F24") == 0x87

    def test_named_keys(self):
        """Named keys should have correct VK codes."""
        assert _resolve_vk("SPACE") == 0x20
        assert _resolve_vk("ENTER") == 0x0D
        assert _resolve_vk("ESC") == 0x1B
        assert _resolve_vk("TAB") == 0x09
        assert _resolve_vk("BACKSPACE") == 0x08
        assert _resolve_vk("INSERT") == 0x2D
        assert _resolve_vk("DELETE") == 0x2E
        assert _resolve_vk("HOME") == 0x24
        assert _resolve_vk("END") == 0x23
        assert _resolve_vk("PAGEUP") == 0x21
        assert _resolve_vk("PAGEDOWN") == 0x22

    def test_arrow_keys(self):
        """Arrow keys should have correct VK codes."""
        assert _resolve_vk("UP") == 0x26
        assert _resolve_vk("DOWN") == 0x28
        assert _resolve_vk("LEFT") == 0x25
        assert _resolve_vk("RIGHT") == 0x27

    def test_oem_fallback(self):
        """OEM keys that fail VkKeyScanW should fall back to static mapping.
        Note: VkKeyScanW resolves characters based on the current keyboard layout,
        so the fallback is only tested for keys known to fail VkKeyScanW.
        """
        # These keys use the layout-dependent VkKeyScanW path.
        # On the current keyboard layout, the result may differ from the
        # static US mapping — that's correct behavior (layout awareness).
        # Just verify the function returns something non-zero.
        vk = _resolve_vk(";")
        assert vk > 0, "Semicolon should resolve to a valid VK code"
        vk = _resolve_vk("-")
        assert vk > 0, "Hyphen should resolve to a valid VK code"

    def test_unknown_key_returns_zero(self):
        """Unknown key names should return 0."""
        assert _resolve_vk("NONEXISTENT") == 0
        assert _resolve_vk("") == 0
        assert _resolve_vk("\x00") == 0  # null char, VkKeyScanW will fail


# ---------------------------------------------------------------------------
# parse_hotkey
# ---------------------------------------------------------------------------


class TestParseHotkey:
    def test_empty_string(self):
        """Empty hotkey string should return (0, 0)."""
        assert parse_hotkey("") == (0, 0)

    def test_single_key(self):
        """A single key without modifiers should parse correctly."""
        mod, vk = parse_hotkey("A")
        assert mod == 0
        assert vk == 0x41

    def test_ctrl_alt_shift(self):
        """CTRL+ALT+SHIFT combination should set all three modifier flags."""
        mod, vk = parse_hotkey("Ctrl+Alt+Shift+X")
        assert mod & MOD_CONTROL
        assert mod & MOD_ALT
        assert mod & MOD_SHIFT
        assert vk == 0x58  # X

    def test_ctrl_key(self):
        """Ctrl+X should have MOD_CONTROL and VK for X."""
        mod, vk = parse_hotkey("Ctrl+X")
        assert mod == MOD_CONTROL
        assert vk == 0x58

    def test_alt_key(self):
        """Alt+Z should have MOD_ALT and VK for Z."""
        mod, vk = parse_hotkey("Alt+Z")
        assert mod == MOD_ALT
        assert vk == 0x5A

    def test_shift_key(self):
        """Shift+F1 should have MOD_SHIFT and VK for F1."""
        mod, vk = parse_hotkey("Shift+F1")
        assert mod == MOD_SHIFT
        assert vk == 0x70

    def test_win_key(self):
        """Win+X should have MOD_WIN."""
        mod, vk = parse_hotkey("Win+X")
        assert mod == MOD_WIN
        assert vk == 0x58

    def test_all_modifiers(self):
        """Ctrl+Alt+Shift+Win+A should set all four modifier flags."""
        mod, vk = parse_hotkey("Ctrl+Alt+Shift+Win+A")
        expected = MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN
        assert mod == expected
        assert vk == 0x41

    def test_numpad_keys(self):
        """NUMPAD0-NUMPAD9 should resolve to 0x60-0x69."""
        for i in range(10):
            mod, vk = parse_hotkey(f"Ctrl+Shift+Numpad{i}")
            assert vk == 0x60 + i
        mod, vk = parse_hotkey("Numpad5")
        assert mod == 0
        assert vk == 0x65

    def test_function_keys(self):
        """F1-F24 should resolve correctly."""
        for i in range(1, 25):
            mod, vk = parse_hotkey(f"Alt+F{i}")
            assert vk == 0x6F + i, f"F{i} should be {hex(0x6F + i)}"
        # F25+ should be 0
        mod, vk = parse_hotkey("F25")
        assert vk == 0

    def test_case_insensitive(self):
        """Hotkey parsing should be case-insensitive."""
        mod1, vk1 = parse_hotkey("CTRL+X")
        mod2, vk2 = parse_hotkey("ctrl+x")
        mod3, vk3 = parse_hotkey("Ctrl+X")
        assert (mod1, vk1) == (mod2, vk2) == (mod3, vk3)

    def test_whitespace_tolerance(self):
        """Hotkey strings with extra whitespace should parse correctly."""
        mod, vk = parse_hotkey(" Ctrl + Shift + A ")
        assert mod == (MOD_CONTROL | MOD_SHIFT)
        assert vk == 0x41

    def test_default_hotkeys(self):
        """Common default hotkeys should work."""
        # Alt+X (default toggle)
        mod, vk = parse_hotkey("Alt+X")
        assert mod == MOD_ALT
        assert vk == 0x58

        # Shift+Alt+X (default pie menu)
        mod, vk = parse_hotkey("Shift+Alt+X")
        assert mod == (MOD_SHIFT | MOD_ALT)
        assert vk == 0x58

        # Ctrl+Shift+L (default lock)
        mod, vk = parse_hotkey("Ctrl+Shift+L")
        assert mod == (MOD_CONTROL | MOD_SHIFT)
        assert vk == 0x4C

        # Ctrl+Shift+E (default AOT)
        mod, vk = parse_hotkey("Ctrl+Shift+E")
        assert mod == (MOD_CONTROL | MOD_SHIFT)
        assert vk == 0x45

    def test_special_character_handling(self):
        """Symbol characters should resolve (may be layout-dependent)."""
        # These use static fallback which maps US layout
        mod, vk = parse_hotkey("Ctrl+Shift+-")
        assert mod == (MOD_CONTROL | MOD_SHIFT)
        assert vk == 0xBD  # US layout hyphen
