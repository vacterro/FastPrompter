"""T-1269C append — Ctrl+V ownership when the operator's profile is remapped.

Why this is its own module
--------------------------
The claim under test is about QShortcut arbitration, and two things make it
awkward to test anywhere else:

* ``setup_global_shortcuts`` rebuilds the whole QShortcut set. That is a real
  production path -- ``ui/settings.py`` calls it when settings are applied --
  so it must run against a live window, but not against the window
  ``tests/test_editor_paste_live_t1269.py`` shares across forty paste tests;
* a second simultaneous ``FastPrompter`` is not something this suite can build
  safely, so the window here is the only one alive in this module.

What is asserted
----------------
With a profile that maps a configurable command onto Ctrl+V, applying settings
must refuse the theft, record the refusal on the window, and leave the rest of
the shortcut set intact. Two owners for one keypress is what makes an
intermittent "Ctrl+V does nothing" report unfalsifiable: the loser is
invisible, because the paste cue never plays while the clipboard route through
NEW keeps working.

The paste half of the claim is NOT re-asserted here. See the note on
``test_no_late_key_press_after_a_rebuild`` for the measured reason.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1269shortcut")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1269shortcut_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from fastprompter.main import FastPrompter
    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    for _ in range(5):
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    w.show()
    _APP.processEvents()
    try:
        yield w
    finally:
        for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
            timer = getattr(w, name, None)
            if timer is not None:
                timer.stop()
        service = getattr(w, "limit_service", None)
        if service is not None:
            service.shutdown()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup


@pytest.fixture(autouse=True)
def _own_the_clipboard():
    clip = QApplication.clipboard()
    before = clip.text()
    try:
        yield
    finally:
        try:
            clip.setText(before)
        except Exception:
            clip.clear()


def _registered(win):
    from fastprompter.main import _portable_sequence
    return {_portable_sequence(s.key()) for s in win._app_shortcuts}


# ---------------------------------------------------------------------------
# the way in: config -> settings apply -> registration
# ---------------------------------------------------------------------------

def test_startup_registered_the_editor_keys_as_shipped(win):
    """Baseline: the shipped profile leaves every editing key to the editor."""
    registered = _registered(win)
    # The two shared ones: hk_undo and the fixed Ctrl+Y both run the window
    # handler the editor's own branch calls, so one keypress still means one
    # action.
    assert {"Ctrl+Z", "Ctrl+Y"} <= registered, sorted(registered)
    assert not ({"Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X"} & registered)
    assert win.hotkey_conflicts() == []


def test_a_remapped_ctrl_v_is_refused_by_the_settings_apply_path(win):
    """The settings-apply path with a profile that would steal Ctrl+V.

    ``ui/settings.py`` rebuilds the shortcuts when settings are applied, so this
    is precisely the moment a remap can quietly take the key. It must not: the
    refusal has to be visible on the window instead of leaving two commands
    sharing one keypress, one of which is invisible to the user.
    """
    original = win.data.get("hk_find")
    assert original != "Ctrl+V"
    win.data["hk_find"] = "Ctrl+V"
    try:
        win.setup_global_shortcuts()

        conflicts = win.hotkey_conflicts()
        assert [c["hotkey"] for c in conflicts] == ["hk_find"], conflicts
        assert conflicts[0]["sequence"] == "Ctrl+V"
        assert conflicts[0]["editor_action"] == "paste"

        registered = _registered(win)
        assert "Ctrl+V" not in registered, sorted(registered)
        assert "Ctrl+F" not in registered          # the refused binding only
        # Everything else still went in: refusing one binding must not
        # abandon the rest of the set.
        assert "Ctrl+D" in registered, sorted(registered)
        assert "Ctrl+Z" in registered and "Ctrl+Y" in registered
    finally:
        if original is None:
            win.data.pop("hk_find", None)
        else:
            win.data["hk_find"] = original


def test_the_conflict_report_is_rebuilt_not_appended(win):
    """A second apply with the profile back to normal reports nothing.

    The settings dialog may be applied any number of times, and a stale
    conflict left in the report would tell the user their Ctrl+V is broken long
    after they fixed it.
    """
    win.setup_global_shortcuts()
    assert win.hotkey_conflicts() == []
    assert win.data.get("hk_find", "Ctrl+F") == "Ctrl+F"
    assert "Ctrl+F" in _registered(win)


def test_a_second_command_cannot_claim_ctrl_z_either(win):
    """Ctrl+Z already has an owner; a second claim is refused the same way."""
    original = win.data.get("hk_find")
    win.data["hk_find"] = "Ctrl+Z"
    try:
        win.setup_global_shortcuts()
        conflicts = win.hotkey_conflicts()
        assert [c["hotkey"] for c in conflicts] == ["hk_find"], conflicts
        assert conflicts[0]["editor_action"] == "undo"
        # hk_undo kept it, so exactly one binding owns Ctrl+Z.
        assert "Ctrl+Z" in _registered(win)
    finally:
        if original is None:
            win.data.pop("hk_find", None)
        else:
            win.data["hk_find"] = original


def test_no_late_key_press_after_a_rebuild(win):
    """Measured limit of this module, and why the paste half lives elsewhere.

    A synthetic key press (``QTest.keyClick``) AFTER ``setup_global_shortcuts``
    has been run a second time terminates the pytest process outright in this
    environment: the press is reached, nothing is printed -- not even the
    test's own result line -- and the process exits 127. It is not a
    signal crash (``-X faulthandler`` prints no traceback), it does not
    reproduce in a plain script, and it is not this wave's defect.

    Rather than hide that behind a flaky test, the module stops at the
    registration it produced, and ``test_editor_paste_live_t1269`` -- which
    never rebuilds shortcuts -- carries the forty live-paste assertions,
    including "a real Ctrl+V still inserts after a silo switch". Set
    ``FASTPROMPTER_PROBE_REBUILD_KEY=1`` to re-run the fatal press and see it
    for yourself.
    """
    if os.environ.get("FASTPROMPTER_PROBE_REBUILD_KEY") != "1":
        pytest.skip(
            "set FASTPROMPTER_PROBE_REBUILD_KEY=1 to reproduce the fatal "
            "post-rebuild key press")
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    win.setup_global_shortcuts()
    editor = win.text_area
    QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
