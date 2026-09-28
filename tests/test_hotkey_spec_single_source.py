"""T-1335: the in-app hotkeys have ONE source of truth.

The editor's keyPressEvent, the Shortcut settings dialog and the help sheet
used to carry three hand-written copies of the same hotkey list, and they
drifted: five configurable ``hk_*`` keys were bound by the window yet never
shown in the Shortcut settings, so a user could not see or rebind them. This
test pins that they all read ``ui.hotkey_spec`` now, so a new editor hotkey
appears everywhere at once.

Source-level where it can be (no live window), behavioural where it must be.
"""

import json
import os
import re

from fastprompter.ui.hotkey_spec import EDITOR_HOTKEYS, IN_APP_HOTKEYS

ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "fastprompter")


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_spec_defaults_match_the_shipped_profile():
    """Every spec default must equal what default_profile ships, or a fresh
    profile and the settings dialog would disagree about the same key."""
    import fastprompter.core.default_profile as dp
    for hk in IN_APP_HOTKEYS:
        assert dp.DEFAULT_PROFILE[hk.key_name] == hk.default, hk.key_name


def test_settings_dialog_builds_its_rows_from_the_spec():
    """The dialog must not reintroduce a hand-written list."""
    settings = _src("ui/settings.py")
    assert "from fastprompter.ui.hotkey_spec import IN_APP_HOTKEYS" in settings
    # the old inline ladder is gone -- no literal hk_* label tuples left
    assert 'tr("New Empty Snippet", self.lang))' not in settings


def test_editor_dispatches_from_the_spec():
    """The editor must loop the spec, not a hand-written matches() ladder."""
    editor = _src("ui/editor.py")
    assert "from fastprompter.ui.hotkey_spec import EDITOR_HOTKEYS" in editor
    assert "for hk in EDITOR_HOTKEYS:" in editor
    # the old per-key ladder is gone
    assert 'matches("hk_header", "Ctrl+E")' not in editor


def test_previously_hidden_keys_are_now_in_the_in_app_list():
    """The five keys bound in main.py but absent from the old dialog."""
    keys = {hk.key_name for hk in IN_APP_HOTKEYS}
    for hidden in ("hk_quote", "hk_line_nums", "hk_settings",
                   "hk_timers", "hk_hashtags"):
        assert hidden in keys, hidden


def test_every_editor_action_targets_a_real_main_window_method():
    """Each dispatched action must call something the window actually has.

    Guards against a spec entry whose lambda names a renamed method -- it would
    raise only when the user pressed that exact chord. The window is composed
    from mixins, so scan main.py plus every ui/*_mixin.py.
    """
    haystack = _src("main.py")
    ui_dir = os.path.join(ROOT, "ui")
    for name in sorted(os.listdir(ui_dir)):
        if name.endswith("_mixin.py"):
            haystack += _src(os.path.join("ui", name))
    # the method names the spec lambdas call
    called = {
        "select_empty_silo", "save_snippet", "save_silo_to_file",
        "toggle_find", "show_replace", "cycle_focus_mode",
        "apply_header_timestamp", "apply_bold_smart", "apply_format",
        "insert_divider_line", "cycle_snap_corner", "_smart_undo",
    }
    for name in called:
        assert re.search(rf"def {re.escape(name)}\b", haystack), \
            f"{name} is dispatched by a hotkey but not defined on the window"
    # every editor-dispatched spec entry has a callable action
    assert EDITOR_HOTKEYS
    for hk in EDITOR_HOTKEYS:
        assert callable(hk.action), hk.key_name


def test_every_spec_label_is_in_the_canonical_pack():
    """T-1345: a label the spec owns must never go untranslated.

    The labels reach tr() as ``tr(hk.label, ...)``, so tools/i18n_utils.py
    counts them as dynamic and the validator's static-key sweep cannot see
    them -- the T-800 promotion workflow loses every label at the moment the
    list became an object. That blindness is not fixable by making the labels
    literal again (that is the second copy this module exists to delete), so
    the guarantee is pinned here instead: the check the scanner cannot make is
    made explicitly, next to the thing it is about.

    A new HotkeySpec with a label and no pack entry fails HERE rather than
    silently falling back to English for every non-EN user.
    """
    pack = os.path.join(os.path.dirname(__file__), "..", ".saipen",
                        "saitranslate", "locales", "en.json")
    with open(pack, encoding="utf-8") as fh:
        canonical = json.load(fh)["translations"]
    missing = [hk.label for hk in IN_APP_HOTKEYS if hk.label not in canonical]
    assert not missing, f"hotkey labels missing from en.json: {missing}"


def test_help_sheet_shows_the_configured_sequences_not_the_shipped_ones():
    """T-1346: the help sheet was a third hand-written copy of the list.

    It hardcoded Ctrl+N / Ctrl+F / Ctrl+Z ... and so went stale the moment a
    key was rebound, and it omitted the five keys T-1335 made rebindable --
    the same 'bound but invisible' defect the ticket set out to kill, one
    surface over. The sheet now reads each sequence out of ``data`` and
    carries a row for every key the app binds.
    """
    from fastprompter.ui.help_dialog import build_help_html

    rebound = {
        "hk_new_snippet": "Alt+Shift+N",   # was Ctrl+N
        "hk_find": "Alt+Shift+F",          # was Ctrl+F
        "hk_undo": "Alt+Shift+Z",          # was Ctrl+Z
    }
    html = build_help_html(dict(rebound))
    for key, seq in rebound.items():
        assert seq in html, f"help sheet does not show the rebound {key}"
    # The shipped defaults for those keys must be gone from the KEY column,
    # not merely supplemented. Matched as <b>KEY</b> so the Files-panel row
    # ("... · Ctrl+N new folder · ...") -- which is the Qt file dialog's own
    # chord, not an app hotkey -- is not mistaken for a stale app binding.
    for shipped in ("Ctrl+N", "Ctrl+F", "Ctrl+Z"):
        assert f"<b>{shipped}</b>" not in html, \
            f"help sheet still hardcodes {shipped} as an app hotkey"
    # the five keys that used to be missing from the sheet entirely
    for key, default in (("hk_quote", "Ctrl+Shift+Q"), ("hk_line_nums", "Alt+Z"),
                         ("hk_settings", "Alt+`"), ("hk_timers", "Ctrl+Shift+T"),
                         ("hk_hashtags", "Alt+Shift+T")):
        assert default in html, f"help sheet omits {key}"


def test_help_sheet_falls_back_to_the_shipped_default_when_unset():
    from fastprompter.ui.help_dialog import build_help_html

    html = build_help_html({})
    for hk in IN_APP_HOTKEYS:
        assert hk.default in html, f"help sheet omits the default for {hk.key_name}"
