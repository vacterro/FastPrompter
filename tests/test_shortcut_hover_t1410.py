"""T-1410 — a hover shows the shortcut the command has RIGHT NOW.

The universal requirement was kept by hand: thirty-four literal ``"(Ctrl+E)"``
strings, a twelve-line hard-coded chord block in the cheat sheet, and a second
formatter in the language pass. Every one of them quoted a SHIPPED DEFAULT, so
the moment a user rebound a key the key worked and the tooltip kept advertising
the one they had just given up.

This file pins the structural fix instead of a list of strings. The binding is
the authority; the tooltip is output. So the tests rebind a key AT RUNTIME and
demand the hover follow — which no amount of correct-looking literal text can
satisfy, and which is the only property that actually mattered.
"""

import pytest
from PyQt6.QtWidgets import QPushButton

from fastprompter.ui.hotkey_spec import IN_APP_HOTKEYS
from fastprompter.ui.shortcut_display import (
    FIXED_SHORTCUTS,
    SHORTCUT_TOOLTIP_ROWS,
    resolve,
    shortcut_display,
    tooltip_with_shortcut,
)

_HOTKEY_KEYS = {hk.key_name for hk in IN_APP_HOTKEYS}


class _Win:
    """A window stand-in carrying just the ``data`` the resolver reads."""

    def __init__(self, **overrides):
        self.data = dict(overrides)
        self._current_lang = "EN"
        self._tooltip_calls = 0

    def apply_shortcut_tooltips(self):
        from fastprompter import main as appmain
        appmain.FastPrompter.apply_shortcut_tooltips(self)


# --- the resolver ----------------------------------------------------------

def test_an_unset_key_falls_back_to_its_shipped_default():
    win = _Win()
    assert shortcut_display(win, "hk_bold") == "Ctrl+B"


def test_a_rebound_key_resolves_to_the_new_sequence():
    win = _Win(hk_bold="Alt+Shift+B")
    assert shortcut_display(win, "hk_bold") == "Alt+Shift+B"


def test_a_deliberately_unbound_key_advertises_nothing():
    """An empty binding is an INACTIVE command, not one with a blank key.

    §36: a conflict that left a hotkey refused must not advertise the
    sequence it never got. An empty chord is what stops that.
    """
    win = _Win(hk_bold="")
    assert shortcut_display(win, "hk_bold") == ""
    assert tooltip_with_shortcut("Bold ({})", "", "EN") == "Bold ({})"


def test_a_window_without_data_dict_is_answered_not_crashed():
    assert shortcut_display(object(), "hk_bold") == ""


def test_resolve_prefers_the_configured_binding_over_the_fixed_catalog():
    win = _Win(hk_snap="Alt+Shift+Q")
    assert resolve(win, "hk_snap") == "Alt+Shift+Q"
    # strike has no setting at all: the fixed catalog answers
    assert resolve(win, "strike") == FIXED_SHORTCUTS["strike"] == "Ctrl+T"


def test_resolve_is_empty_for_a_command_with_no_shortcut():
    assert resolve(_Win(), "btn_some_thing_with_no_key") == ""


# --- the composer ----------------------------------------------------------

def test_a_placeholder_description_keeps_its_compact_form():
    assert tooltip_with_shortcut("Bold ({})", "Ctrl+B", "EN") == "Bold (Ctrl+B)"


def test_a_multi_line_description_gains_a_shortcut_line():
    out = tooltip_with_shortcut("Header\nTitle the line.", "Ctrl+E", "EN")
    assert out.splitlines() == ["Header", "Title the line.", "Shortcut: Ctrl+E"]


def test_the_composer_never_eats_a_description_without_a_key():
    assert tooltip_with_shortcut("Files\nAsset drawer.", "", "EN") == \
        "Files\nAsset drawer."


# --- RED regression C: rebind at runtime, hover must follow ---------------

@pytest.mark.usefixtures("qapp")
def test_c_rebinding_a_key_at_runtime_updates_the_hover_with_no_restart():
    """§41 regression C. The defect in one assertion: a hard-coded default
    survives every rebind, so only a runtime change can catch it."""

    win = _Win()
    win.btn_bold = QPushButton("B")
    win.apply_shortcut_tooltips()
    assert "Ctrl+B" in win.btn_bold.toolTip()

    win.data["hk_bold"] = "Alt+Shift+B"
    win.apply_shortcut_tooltips()
    tip = win.btn_bold.toolTip()
    assert "Alt+Shift+B" in tip, tip
    assert "Ctrl+B" not in tip, tip


@pytest.mark.usefixtures("qapp")
def test_c_a_profile_switch_updates_the_hover_too():
    """A profile switch replaces ``data`` wholesale; the hover follows it."""
    from fastprompter.core.default_profile import DEFAULT_PROFILE

    win = _Win()
    win.btn_header = QPushButton("H")
    win.apply_shortcut_tooltips()
    assert "Ctrl+E" in win.btn_header.toolTip()

    switched = dict(DEFAULT_PROFILE)
    switched["hk_header"] = "Ctrl+Alt+E"
    win.data = switched
    win.apply_shortcut_tooltips()
    assert "Ctrl+Alt+E" in win.btn_header.toolTip()


@pytest.mark.usefixtures("qapp")
def test_c_a_language_switch_keeps_the_live_key_and_translates_the_word():
    """§26: the key is language-neutral; the WORD around it is not."""
    from fastprompter.core.translations import tr

    win = _Win(hk_bold="Alt+Shift+B")
    win.btn_bold = QPushButton("B")
    win.apply_shortcut_tooltips()

    win._current_lang = "EN"
    win.apply_shortcut_tooltips()
    english = win.btn_bold.toolTip()

    win._current_lang = "RU"
    win.apply_shortcut_tooltips()
    russian = win.btn_bold.toolTip()

    assert "Alt+Shift+B" in english and "Alt+Shift+B" in russian
    assert tr("Bold ({})", "EN").format("Alt+Shift+B") in english
    assert tr("Bold ({})", "RU").format("Alt+Shift+B") in russian
    assert english != russian, "the description should follow the language"


# --- the audit -------------------------------------------------------------

@pytest.mark.usefixtures("qapp")
def test_every_shortcut_backed_control_shows_its_current_key():
    """§34, registry-driven: every row of the ONE table resolves to a real
    chord and paints it into that button's tooltip."""
    rows = SHORTCUT_TOOLTIP_ROWS
    assert rows, "the table is empty — nothing would show a key"

    win = _Win()
    for attr, _description, _key_name in rows:
        setattr(win, attr, QPushButton("x"))
    win.apply_shortcut_tooltips()

    for attr, description, key_name in rows:
        btn = getattr(win, attr)
        expected = resolve(win, key_name)
        assert expected, f"{attr} names {key_name}, which has no shortcut"
        assert expected in btn.toolTip(), (attr, key_name, btn.toolTip())
        assert "{}" not in btn.toolTip(), "an unformatted template leaked"


def test_the_audit_table_covers_the_representative_commands():
    """§36: New, Header, Quote, Exit are configurable; Strikethrough and
    Clear are fixed. A control is not dropped from the rule by accident."""
    keys = {key_name for _attr, _desc, key_name in SHORTCUT_TOOLTIP_ROWS}
    for required in ("hk_new_snippet", "hk_header", "hk_quote", "hk_quit",
                     "strike", "clear", "hk_divider"):
        assert required in keys, required


def test_no_configurable_key_is_shadowed_by_a_fixed_one():
    """A name in both tables would let a stale catalog answer for a key the
    user can rebind, which is the exact drift this file exists to stop."""
    assert not (_HOTKEY_KEYS & set(FIXED_SHORTCUTS))


def test_a_tooltip_is_never_the_source_of_a_shortcut():
    """§23: a rebindable command's chord may not be written into a tooltip
    literal again. Each configurable key's SHIPPED default used to sit in a
    ``"(Ctrl+E)"`` string somewhere in main.py, which is what made a rebind
    look like it had done nothing. The rows that quote a chord now read it
    from the binding, so the default may not reappear as text."""
    import os
    import re

    import fastprompter
    root = os.path.dirname(os.path.abspath(fastprompter.__file__))
    with open(os.path.join(root, "main.py"), encoding="utf-8") as fh:
        main_src = fh.read()

    drifted = []
    for spec in IN_APP_HOTKEYS:
        # Only the sequence, not the key name, and only inside a tooltip.
        chord = spec.default.replace("+", r"\+")
        pattern = re.compile(
            rf"""setToolTip\(\s*tr\(\s*["'][^"']*\({chord}\)""")
        if pattern.search(main_src):
            drifted.append(spec.key_name)
    assert not drifted, (
        "these rebindable chords are written into a tooltip literal again: "
        f"{drifted}"
    )


def test_the_pack_glyph_reports_the_live_pack_key():
    """§27: the inline Pack tooltip carries the configured key."""
    from fastprompter.ui.editor import VaultTextEdit
    from fastprompter.ui.shortcut_display import resolve, tooltip_with_shortcut

    win = _Win(hk_pack_silo="Ctrl+Alt+P")
    editor = VaultTextEdit.__new__(VaultTextEdit)
    editor.main_win = win
    key = resolve(win, "hk_pack_silo")
    assert key == "Ctrl+Alt+P"
    assert "Ctrl+Alt+P" in tooltip_with_shortcut("Pack Silo", key, "EN")


def test_pack_silo_has_a_real_key_and_exactly_one_owner():
    """§16/§35: Quick Pack must be reachable by key, and the chord must have
    ONE dispatch owner — the window QShortcut, not the editor ladder too."""
    from fastprompter.ui.hotkey_spec import EDITOR_HOTKEYS

    spec = next(hk for hk in IN_APP_HOTKEYS if hk.key_name == "hk_pack_silo")
    assert spec.default == "Ctrl+Shift+P"
    # Window-owned: absent from the editor dispatch ladder.
    assert spec not in EDITOR_HOTKEYS
    assert spec.action is None

    import inspect

    from fastprompter import main as appmain
    source = inspect.getsource(appmain.FastPrompter.setup_global_shortcuts)
    assert 'add_shortcut("hk_pack_silo", "Ctrl+Shift+P"' in source

    import fastprompter.core.default_profile as dp
    assert dp.DEFAULT_PROFILE["hk_pack_silo"] == "Ctrl+Shift+P"

    # No duplicate owner: the editor ladder must not mention the chord.
    import fastprompter.ui.editor as editor_mod
    editor_src = inspect.getsource(editor_mod)
    assert '"Ctrl+Shift+P"' not in editor_src
