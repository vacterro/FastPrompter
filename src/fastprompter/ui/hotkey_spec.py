"""One source of truth for the configurable in-app hotkeys.

The editor's ``keyPressEvent`` used to carry a hand-written ``if matches(...)``
ladder, the settings dialog a hand-written ``app_binds`` list, and the help
dialog a third hand-written table -- three copies of the same facts that drifted
apart (five configurable ``hk_*`` keys were bound in ``main.py`` yet never shown
in the Shortcut settings at all, so the user could not see or rebind them).

This list is that single source. ``settings.py`` builds the Shortcut settings
rows from it, and ``editor.py`` builds its dispatch from it, so a new editor
hotkey is added in ONE place and appears everywhere.

Each entry:
- ``key_name``    the ``data[...]`` key the sequence is stored under.
- ``default``     the shipped default sequence (must match ``default_profile``).
- ``label``       the canonical English label; the UI wraps it in ``tr(...)``.
- ``action``      ``callable(main_window)`` the editor runs when the chord is
                  pressed inside the text widget, or ``None`` for a hotkey the
                  window owns as a global ``QShortcut`` (still listed so it is
                  rebindable, just not dispatched from the editor).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HotkeySpec:
    key_name: str
    default: str
    label: str
    action: Callable[[object], None] | None = None


def _undo(mw):
    if hasattr(mw, "_smart_undo"):
        mw._smart_undo()


# Order is the display order in the Shortcut settings "In-App Shortcuts" tab and
# the match order in the editor. Editor-dispatched entries first, then the
# window-owned ones.
IN_APP_HOTKEYS = [
    HotkeySpec("hk_new_snippet", "Ctrl+N", "New Empty Snippet",
               lambda mw: mw.select_empty_silo(insertion="top")),
    HotkeySpec("hk_save_snippet", "Ctrl+S", "Save Snippet",
               lambda mw: mw.save_snippet()),
    HotkeySpec("hk_export_silo", "Ctrl+Shift+S", "Export Silo to file",
               lambda mw: mw.save_silo_to_file()),
    HotkeySpec("hk_find", "Ctrl+F", "Find Text",
               lambda mw: mw.toggle_find()),
    HotkeySpec("hk_replace", "Ctrl+H", "Replace Text",
               lambda mw: mw.show_replace()),
    HotkeySpec("hk_focus", "Ctrl+D", "Toggle Focus Mode",
               lambda mw: mw.cycle_focus_mode()),
    HotkeySpec("hk_header", "Ctrl+E", "Header+Bold+Underline+Timestamp",
               lambda mw: mw.apply_header_timestamp()),
    HotkeySpec("hk_bold", "Ctrl+B", "Bold / Unbold Line",
               lambda mw: mw.apply_bold_smart()),
    HotkeySpec("hk_italic", "Ctrl+I", "Italic",
               lambda mw: mw.apply_format("italic")),
    HotkeySpec("hk_underline", "Ctrl+U", "Underline",
               lambda mw: mw.apply_format("underline")),
    HotkeySpec("hk_undo", "Ctrl+Z", "Undo", _undo),
    HotkeySpec("hk_divider", "Ctrl+W", "Insert Divider Line",
               lambda mw: mw.insert_divider_line()),
    HotkeySpec("hk_snap", "Ctrl+Q", "Cycle Snap Corners",
               lambda mw: mw.cycle_snap_corner()),
    # Window-owned globals: bound as QShortcuts in setup_global_shortcuts, but
    # listed here so the Shortcut settings shows the FULL set, none hidden.
    HotkeySpec("hk_audio_mute", "Ctrl+M", "Master Mute"),
    HotkeySpec("hk_quote", "Ctrl+Shift+Q", "Toggle Quote Conversion"),
    HotkeySpec("hk_line_nums", "Alt+Z", "Toggle Line Numbers"),
    HotkeySpec("hk_settings", "Alt+`", "Toggle Mini Settings"),
    HotkeySpec("hk_timers", "Ctrl+Shift+T", "Open Timers"),
    HotkeySpec("hk_hashtags", "Alt+Shift+T", "Open Hashtags"),
    HotkeySpec("hk_quit", "Ctrl+Alt+Shift+Q", "Quit Application"),
]

# The subset the editor's keyPressEvent dispatches (has an action).
EDITOR_HOTKEYS = [hk for hk in IN_APP_HOTKEYS if hk.action is not None]
