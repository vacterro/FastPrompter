"""T-1410 — one authority for "what key does this command have right now?".

Every hoverable control that owns a real keyboard command shows its CURRENT
shortcut. Before this module that promise was kept by hand: about thirty-four
literal ``"(Ctrl+E)"`` strings in the source, a twelve-line block of hard-coded
chords in ``hotkey_mixin``, and a second copy in the settings-language pass.
All of them went stale the moment a key was rebound, and the reader could
never tell a live binding from a shipped default.

The rule this module makes mechanical:

* the BINDING is the authority — ``ui.hotkey_spec`` for a configurable key,
  ``FIXED_SHORTCUTS`` for a key that deliberately has no setting;
* the tooltip is OUTPUT. Nothing is ever parsed back out of a tooltip string.

Nothing here is parsed from text and nothing here parses text: a tooltip is
written once, by the composer, from a value the binding actually has.
"""

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.translations import tr
from fastprompter.ui.hotkey_spec import IN_APP_HOTKEYS

SPEC_BY_NAME = {hk.key_name: hk for hk in IN_APP_HOTKEYS}

# Fixed chords: real commands with NO setting of their own. They are listed
# once here so a tooltip can quote them, and the audit test can compare them
# against what `setup_global_shortcuts`/`keyPressEvent` actually bind. A key
# deliberately left out of both this table and IN_APP_HOTKEYS is a function
# with no shortcut, and its tooltip says so by saying nothing.
FIXED_SHORTCUTS = {
    "strike": "Ctrl+T",            # editor.keyPressEvent
    "clear": "Ctrl+Shift+C",       # add_fixed in setup_global_shortcuts
    "insert_line_up": "Alt+W",     # add_fixed
    "prev_silo": "Alt+Up",         # add_fixed
    "next_silo": "Alt+Down",       # add_fixed
    "redo": "Ctrl+Y",              # add_fixed
    "escape": "Esc",               # add_fixed
}
FIXED_SHORTCUTS.update({f"slot_{i}": f"Ctrl+{i}" for i in range(1, 10)})
FIXED_SHORTCUTS["slot_10"] = "Ctrl+0"
FIXED_SHORTCUTS.update({f"help_{i}": f"F{i}" for i in range(1, 13)})


def shortcut_display(owner, key_name):
    """The sequence bound to ``key_name`` right now, or "" when unbound.

    ``owner`` is anything with a ``data`` dict — the window, or a test double.
    Unset falls back to the shipped default (the spec first, then the profile,
    which also covers the older non-spec keys like ``toggle_sidebar_hotkey``).
    A key the user deliberately emptied comes back "", so an inactive binding
    is never advertised as if it worked.
    """
    data = getattr(owner, "data", None)
    if not isinstance(data, dict):
        return ""
    value = data.get(key_name)
    if value is None:
        spec = SPEC_BY_NAME.get(key_name)
        value = (spec.default if spec is not None
                 else DEFAULT_PROFILE.get(key_name, ""))
    return str(value or "").strip()


def fixed_shortcut(name):
    """A fixed chord by catalog name, or "" when the name is unknown."""
    return FIXED_SHORTCUTS.get(str(name), "")


def tooltip_with_shortcut(description, shortcut="", lang="EN"):
    """Compose a tooltip and its key into one string.

    A description that already carries a ``{}`` placeholder keeps the compact
    one-line form it was authored in; anything else gets the chord on its own
    final line, so a multi-line explanation is not rewritten to fit a key.
    """
    description = str(description)
    if not shortcut:
        return description
    if "{}" in description:
        return description.format(shortcut)
    return f"{description}\n{tr('Shortcut: {0}', lang).format(shortcut)}"


def resolve(owner, name, lang="EN"):
    """Shortcut for ``name``: the configured binding when there is one, else
    the fixed chord of that name.

    One call for a surface that may be pointing at either kind of command —
    the Pack glyph, the context menu, the help sheet. A name that is in
    neither table is a function with no shortcut and comes back "".
    """
    return shortcut_display(owner, name) or fixed_shortcut(name)


def tooltip_lines(owner, description, name, lang="EN"):
    """`tooltip_with_shortcut` fed by `resolve`: the one-line form every
    hoverable command should use."""
    return tooltip_with_shortcut(description, resolve(owner, name, lang), lang)


# The controls whose hover has to carry a key, and where each key lives.
# (button attribute on the window, description template, key name)
#
# A command with NO shortcut is simply absent, which is how "do not invent a
# shortcut for a function merely to satisfy the rule" is kept mechanical
# rather than a matter of discipline. The audit in the test suite iterates
# THIS list, so dropping a control drops it from the guarantee loudly.
SHORTCUT_TOOLTIP_ROWS = (
    ("btn_new", "New ({})", "hk_new_snippet"),
    ("btn_save", "Save ({})", "hk_save_snippet"),
    ("btn_bold", "Bold ({})", "hk_bold"),
    ("btn_italic", "Italic ({})", "hk_italic"),
    ("btn_under", "Underline ({})", "hk_underline"),
    ("btn_add_line",
     "Insert Line ({})\nInsert a spaced --- divider and start a fresh bullet.",
     "hk_divider"),
    ("btn_header",
     "Header ({})\nTitle the line: # + bold + underline + timestamp,\n"
     "then land 2 lines below on a fresh bullet.", "hk_header"),
    ("btn_quote",
     "Quote ({})\nWrap the selected lines as a '> ' quote block.\n"
     "A quote of 2+ lines collapses to one line like a footnote.", "hk_quote"),
    ("btn_exit",
     "Exit FastPrompter ({})\nSave all data and quit application.", "hk_quit"),
    # Fixed commands: real keys with no setting of their own, quoted from the
    # catalog so a tooltip can never drift from the binding.
    ("btn_strike", "Strikethrough ({})\nCross out selected text.", "strike"),
    ("btn_clear", "Clear ({})", "clear"),
)
