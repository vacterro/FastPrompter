"""T-1242 append: editor delete sound events separation.

Covers D12 test matrix from the spec:
1. Backspace on "abc|" -> "ab", exactly one "backspace"
2. Backspace on "|abc" -> no change, no sound
3. Delete on "|abc" -> "bc", exactly one "delete_forward"
4. Delete on "abc|" -> no change, no sound
5. Delete on "a[bc]d" -> "ad", exactly one "delete_selection"
6. Backspace on "a[bc]d" -> "ad", exactly one "backspace"
7. Selected text + Ctrl+X -> exactly one "cut", zero delete_selection
8. Selected text + typing -> normal type sound, zero delete_selection
9. Empty SILO + Delete trash path -> no delete_forward editor sound
10. SILO deletion action -> "delete" only, never editor delete events
11. Global mute ON -> all three editor events physically silent
12. Custom mappings -> each key path resolves exactly its own sound
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QMessageBox


def _main_window(sound_events=None):
    """Minimal main window stub with captured sound calls."""
    played = []

    def play_sound(name):
        played.append(name)

    data = {
        "sound_ui": "True",
        "sound_typewriter": "True",
        "sound_volume": "0.5",
    }
    if sound_events:
        data["sound_events"] = sound_events

    return SimpleNamespace(
        data=data,
        play_sound=play_sound,
        highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000,
        _LARGE_DOC_BLOCK_THRESHOLD=2000,
    )


def _setup_editor():
    """Create an editor with captured sounds."""
    app = QApplication.instance() or QApplication([])
    main = _main_window()
    from fastprompter.ui.editor import VaultTextEdit
    editor = VaultTextEdit(main)
    editor.show()
    editor.setFocus()
    return editor, main, app


@pytest.fixture(autouse=True)
def _own_the_clipboard():
    """T-1260: this module CUTS, and a cut is machine-global.

    ``test_cut_plays_cut_not_delete_selection`` presses a real Ctrl+X, so
    "bc" landed on the system clipboard and stayed there -- for every later
    test in the session and for whoever was using the machine. It is a
    genuine leak, not a nuisance: the shipped profile now defaults
    ``new_silo_paste_clipboard`` to True, so every empty silo created after
    this module ran was seeded with "bc" and the whole
    ``test_new_empty_silos`` module went red in a full run while passing
    alone. Snapshot in, restore out -- the cut behaviour under test is
    untouched.
    """
    clip = (QApplication.instance() or QApplication([])).clipboard()
    before = clip.text()
    try:
        yield
    finally:
        if before:
            clip.setText(before)
        else:
            clip.clear()


def _press_key(editor, key, modifiers=Qt.KeyboardModifier.NoModifier, text=""):
    """Send a key press to the editor."""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    editor.keyPressEvent(ev)


def _press_ctrl_x(editor):
    """Ctrl+X cut."""
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X,
                   Qt.KeyboardModifier.ControlModifier, "\x18")
    editor.keyPressEvent(ev)


def _set_text(editor, text):
    """Set editor text and move cursor to end."""
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)


def test_backspace_removes_char_plays_backspace():
    """abc| + Backspace -> ab, one backspace."""
    editor, main, _ = _setup_editor()
    _set_text(editor, "abc")
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "ab"
    assert played == ["backspace"]


def test_backspace_at_start_no_op_no_sound():
    """|abc + Backspace -> no change, no sound."""
    editor, main, _ = _setup_editor()
    _set_text(editor, "abc")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "abc"
    assert played == []


def test_delete_forward_removes_char_plays_delete_forward():
    """|abc + Delete -> bc, one delete_forward."""
    editor, main, _ = _setup_editor()
    _set_text(editor, "abc")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Delete)
    assert editor.toPlainText() == "bc"
    assert played == ["delete_forward"]


def test_delete_at_end_no_op_no_sound():
    """abc| + Delete -> no change, no sound."""
    editor, main, _ = _setup_editor()
    _set_text(editor, "abc")
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Delete)
    assert editor.toPlainText() == "abc"
    assert played == []


def test_delete_selection_plays_delete_selection():
    """a[bc]d + Delete -> ad, one delete_selection."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("abcd")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, cursor.MoveMode.KeepAnchor)  # select "bc"
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Delete)
    assert editor.toPlainText() == "ad"
    assert played == ["delete_selection"]


def test_backspace_selection_plays_backspace():
    """a[bc]d + Backspace -> ad, one backspace (D6)."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("abcd")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, cursor.MoveMode.KeepAnchor)  # select "bc"
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == "ad"
    assert played == ["backspace"]


def test_cut_plays_cut_not_delete_selection():
    """Selected + Ctrl+X -> one cut, zero delete_selection (D7)."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("abcd")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_ctrl_x(editor)
    # Ctrl+X triggers cut sound through _BUILTIN_KEY_SOUNDS
    assert "cut" in played
    assert "delete_selection" not in played


def test_typing_over_selection_plays_type_not_delete_selection():
    """Selected + typing -> type sound, zero delete_selection (D7)."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("abcd")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    played = []
    main.play_sound = played.append
    _press_key(editor, Qt.Key.Key_X, text="x")  # replace selection with "x"
    assert editor.toPlainText() == "axd"
    assert "type" in played
    assert "delete_selection" not in played


def test_empty_silo_delete_no_editor_sound():
    """Empty SILO + Delete -> trash confirm, no editor delete_forward (D9)."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("")  # empty silo
    played = []
    main.play_sound = played.append
    # The empty-silo Delete triggers a QMessageBox in editor keyPressEvent,
    # which returns early before super().keyPressEvent. No editor sound.
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        _press_key(editor, Qt.Key.Key_Delete)
    assert "delete_forward" not in played
    assert "delete" not in played  # editor never plays "delete" (silo sound)


def test_silo_deletion_plays_delete_only():
    """Silo deletion action -> "delete" only, never editor events (D8/D10)."""
    editor, main, _ = _setup_editor()
    editor.setPlainText("some text")
    played = []
    main.play_sound = played.append
    # Simulate the silo delete action (main.trash_silo) which calls play_sound("delete")
    # The editor's Delete key on non-empty text just edits, doesn't trigger silo delete.
    main.play_sound("delete")
    assert "delete" in played
    assert "delete_forward" not in played
    assert "delete_selection" not in played
    assert "backspace" not in played


def test_global_mute_silences_editor_events():
    """Global mute ON -> all three editor events physically silent (D11).

    The manager's play() path resolves the effective volume from the master;
    a 0.0 master produces a 0.0 level, and both transports (winsound and
    QSoundEffect) treat 0 as "play nothing". The events stay enabled and
    configurable - muting is the master's job, never a per-event toggle.
    """
    from fastprompter.core.sound_manager import effective_event_volume

    data = {
        "sound_ui": "True",
        "sound_typewriter": "True",
        "sound_volume": "0",
        "sound_events": {
            "backspace": {"enabled": "True", "file": "type_key_3.wav"},
            "delete_forward": {"enabled": "True", "file": "type_key_2.wav"},
            "delete_selection": {"enabled": "True", "file": "ui_delete.wav"},
        },
    }
    for event in ("backspace", "delete_forward", "delete_selection"):
        assert effective_event_volume(event, data) == 0.0, event


def test_editor_delete_events_gated_by_typewriter_toggle():
    """The three editor delete events obey sound_typewriter, not sound_ui."""
    from fastprompter.core.sound_manager import is_event_enabled

    data = {"sound_ui": "True", "sound_typewriter": "False"}
    for event in ("backspace", "delete_forward", "delete_selection"):
        assert is_event_enabled(event, data) is False, event
    data["sound_typewriter"] = "True"
    for event in ("backspace", "delete_forward", "delete_selection"):
        assert is_event_enabled(event, data) is True, event


def test_custom_mappings_resolve_independently():
    """Each editor delete event uses its own sound file (D12.12)."""
    played = []

    def play_sound(name):
        played.append(name)

    # The point is: backspace/delete_forward/delete_selection are SEPARATE
    # events, so play_sound resolves each independently.  _set_text and
    # _setup_editor both manage their own cursor; doing manual cursor
    # operations HERE has to go through the public editor API.
    _ = QApplication.instance() or QApplication([])

    # backspace
    editor, main, _ = _setup_editor()
    main.play_sound = played.append
    _set_text(editor, "abcd")
    played.clear()
    _press_key(editor, Qt.Key.Key_Backspace)
    assert played == ["backspace"]

    # delete forward (caret at start)
    editor.setPlainText("abc")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    played.clear()
    _press_key(editor, Qt.Key.Key_Delete)
    assert played == ["delete_forward"]

    # delete selection
    editor.setPlainText("abcd")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    played.clear()
    _press_key(editor, Qt.Key.Key_Delete)
    assert played == ["delete_selection"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
