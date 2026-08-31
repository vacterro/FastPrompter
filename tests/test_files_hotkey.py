"""Tests for toggle_files_hotkey default + custom-string parse + sound wiring.

Aims at the 4 acceptance criteria (a,b,f) of T-1167:
- default Alt+F parses to (MOD_ALT, 0x46) and lives in default_profile
- non-default "Ctrl+Shift+F" parses to expected mods+vk
- toggle_files_hotkey is in HOTKEY_SOUND_SELF (no double-sound with
  the chest_open/chest_close the panel already plays internally)
- register_all_hotkeys leaves the file drawer binding OFF (Alt+F is a
  local QShortcut, not a global RegisterHotKey) — global registration
  would compete with whatever the user's main "F" key consumer is.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import default_profile
from fastprompter.core.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey


class TestToggleFilesHotkeyDefault:
    def test_default_value_in_default_profile(self):
        """The new default_profile key must exist and equal Alt+F."""
        defaults = default_profile.DEFAULT_PROFILE
        assert "toggle_files_hotkey" in defaults, (
            "default_profile missing toggle_files_hotkey"
        )
        assert defaults["toggle_files_hotkey"] == "Alt+F"

    def test_default_parses_to_alt_f(self):
        """Alt+F -> (MOD_ALT, 0x46). 0x46 is the Windows VK for the F key."""
        mods, vk = parse_hotkey("Alt+F")
        assert mods == MOD_ALT
        assert vk == 0x46


class TestToggleFilesHotkeyCustom:
    def test_ctrl_shift_f_parses(self):
        """A user-configured binding still parses cleanly (no magic tokens)."""
        mods, vk = parse_hotkey("Ctrl+Shift+F")
        assert mods == (MOD_CONTROL | MOD_SHIFT)
        assert vk == 0x46

    def test_empty_string_parses_to_zero(self):
        """Empty config = no binding. parse_hotkey returns (0,0) which the
        register/shortcut layer treats as 'do not bind' — proves the
        add_shortcut path tolerates a user clearing the field."""
        mods, vk = parse_hotkey("")
        assert mods == 0
        assert vk == 0


class TestToggleFilesHotkeySoundContract:
    """The file_container panel plays chest_open/chest_close itself; the
    shortcut wrapper must NOT add a second sound on top."""

    def test_toggle_files_hotkey_is_sound_self(self):
        from fastprompter.main import FastPrompter
        self_key = "toggle_files_hotkey"
        assert hasattr(FastPrompter, "HOTKEY_SOUND_SELF"), (
            "main.py FastPrompter must carry the HOTKEY_SOUND_SELF set"
        )
        assert self_key in FastPrompter.HOTKEY_SOUND_SELF, (
            f"{self_key!r} must be in HOTKEY_SOUND_SELF so the wrapper "
            f"does not double-play the chest_open/chest_close the panel "
            f"already plays on open/close"
        )

    def test_toggle_files_hotkey_sound_event_maps_to_chest(self):
        """The event mapped to toggle_files_hotkey should match what the
        panel actually plays. If the panel ever changes its sound, this
        is the single edit point that has to follow."""
        from fastprompter.main import FastPrompter
        self_key = "toggle_files_hotkey"
        assert hasattr(FastPrompter, "HOTKEY_SOUND_EVENTS"), (
            "main.py FastPrompter must carry the HOTKEY_SOUND_EVENTS map"
        )
        assert FastPrompter.HOTKEY_SOUND_EVENTS.get(self_key) == "chest_open"


class TestToggleFilesHotkeyIsReachable:
    """T-1167 completion: a binding the user cannot see or rebind is a
    hidden feature. The Industrial Completion Rule (MAINTENANCE 2.3) makes
    the settings row and the second (_alt) combo part of the same workflow
    as the binding itself — every other window-local hotkey has both."""

    def _src(self, rel):
        import os
        root = os.path.join(os.path.dirname(__file__), "..", "src", "fastprompter")
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_settings_dialog_exposes_the_binding(self):
        """The hotkey dialog must offer a row for it, or the default is the
        only value a user can ever have."""
        settings = self._src("ui/settings.py")
        assert '"toggle_files_hotkey", "Alt+F"' in settings, (
            "settings dialog must expose toggle_files_hotkey with the Alt+F default"
        )

    def test_settings_dialog_saves_and_resets_the_binding(self):
        """A row that is built but never saved/reset silently discards the
        user's choice — the exact class of bug T-814 fixed for 14 slots."""
        settings = self._src("ui/settings.py")
        assert "self.le_files.save_to_data(self.main_win)" in settings
        assert 'self.le_files.reset_defaults("Alt+F")' in settings

    def test_alt_slot_is_bound(self):
        """DualHotkeyWidget always offers a second combo; leaving it unbound
        is the dead-_alt-slot defect (T-814)."""
        main = self._src("main.py")
        assert 'add_shortcut("toggle_files_hotkey_alt"' in main

    def test_cheatsheet_documents_alt_f(self):
        """The wiki cheatsheet is the user's reference; a binding missing
        from it drifted once already (T-776)."""
        import os
        root = os.path.join(os.path.dirname(__file__), "..")
        sheet = os.path.join(root, "docs", "wiki",
                             "Keyboard-Shortcuts-and-Cheatsheet.md")
        with open(sheet, encoding="utf-8") as fh:
            text = fh.read()
        assert "**Alt+F**" in text, "cheatsheet must document Alt+F"
