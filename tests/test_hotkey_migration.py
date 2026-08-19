"""T-814 regression: hotkey map unification + the 14 dead ``_alt`` slots.

The canonical map (per default profile and the wiki) is Alt+E = lock,
Alt+S = always-on-top. Several fallback/default sites carried the swapped
legacy values, so a fresh profile, a missing key, or the settings dialog
could hand the user the OPPOSITE action for a key. Additionally the settings
dialog exposes a second combo (``{key}_alt``) for 14 window-local hotkeys
(lock, always-on-top, sidebar, hide-on-clickout, 5 snippets, 5 silos) that
nothing ever bound — a configured second combo silently did nothing.

Source-level invariants so they run without a live window.
"""

import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "fastprompter")


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_profile_ships_canonical_lock_and_aot():
    import fastprompter.core.default_profile as dp
    assert dp.DEFAULT_PROFILE["lock_window_hotkey"] == "Alt+E"
    assert dp.DEFAULT_PROFILE["always_on_top_hotkey"] == "Alt+S"


def test_no_swapped_lock_aot_defaults_anywhere():
    bad = [
        ('add_shortcut("lock_window_hotkey", "Alt+S"', _src("main.py")),
        ('add_shortcut("always_on_top_hotkey", "Alt+E"', _src("main.py")),
        ('"lock_window_hotkey", "Alt+S"', _src("ui/settings.py")),
        ('"always_on_top_hotkey", "Alt+E"', _src("ui/settings.py")),
        ('get("lock_window_hotkey", "Alt+S")', _src("ui/hotkey_mixin.py")),
        ('get("always_on_top_hotkey", "Alt+E")', _src("ui/hotkey_mixin.py")),
        ('g("lock_window_hotkey", "Alt+S")', _src("ui/help_dialog.py")),
        ('g("always_on_top_hotkey", "Alt+E")', _src("ui/help_dialog.py")),
        ('"lock_window_hotkey": "Alt+S"', _src("core/state.py")),
        ('"always_on_top_hotkey": "Alt+E"', _src("core/state.py")),
    ]
    for needle, src in bad:
        assert needle not in src, f"swapped lock/aot default survives: {needle}"


def test_canonical_defaults_are_present_in_the_binding_sites():
    main = _src("main.py")
    assert 'add_shortcut("lock_window_hotkey", "Alt+E"' in main
    assert 'add_shortcut("always_on_top_hotkey", "Alt+S"' in main
    settings = _src("ui/settings.py")
    assert '"lock_window_hotkey", "Alt+E"' in settings
    assert '"always_on_top_hotkey", "Alt+S"' in settings


def _dual_keys(settings_src):
    return set(re.findall(
        r'DualHotkeyWidget\(self\.main_win, "([A-Za-z_]+)"', settings_src))


def test_every_dialog_alt_slot_is_bound_somewhere():
    """Every ``{key}_alt`` the settings dialog can configure must be bound by
    the app: the global ones (toggle + pie) in hotkey_mixin (Win32 global ids
    101/102), the 14 window-local ones in setup_global_shortcuts."""
    settings = _src("ui/settings.py")
    keys = _dual_keys(settings)
    assert keys, "settings dialog DualHotkeyWidget rows parsed"
    mixin = _src("ui/hotkey_mixin.py")
    main = _src("main.py")
    globally_bound = {"global_hotkey", "pie_menu_hotkey"}
    for key in keys:
        if key in globally_bound:
            assert f'"{key}_alt"' in mixin, f"{key}_alt must be a global binding"
        else:
            assert f'add_shortcut("{key}_alt"' in main, \
                f"{key}_alt is configurable in settings but never bound"


def test_the_14_window_local_alt_slots_are_exactly_bound():
    main = _src("main.py")
    bound = set(re.findall(r'add_shortcut\("([A-Za-z_]+_alt)"', main))
    if 'add_shortcut(f"snippet_{i}_hotkey_alt"' in main:
        bound |= {f"snippet_{i}_hotkey_alt" for i in range(5)}
    if 'add_shortcut(f"silo_{i}_hotkey_alt"' in main:
        bound |= {f"silo_{i}_hotkey_alt" for i in range(5)}
    expected = {
        "lock_window_hotkey_alt", "always_on_top_hotkey_alt",
        "toggle_sidebar_hotkey_alt", "hide_on_clickout_hotkey_alt",
    } | {f"snippet_{i}_hotkey_alt" for i in range(5)} \
        | {f"silo_{i}_hotkey_alt" for i in range(5)}
    assert len(expected) == 14
    assert expected <= bound, f"unbound alt slots: {expected - bound}"
