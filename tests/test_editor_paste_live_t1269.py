"""T-1269C append — the LIVE Ctrl+V route, on a REAL FastPrompter window.

Why this module exists
----------------------
``tests/test_editor_paste_t1269.py`` hands a ``QKeyEvent`` straight to
``VaultTextEdit.keyPressEvent``. That proves the handler's decision table and
nothing else: it bypasses QApplication event routing, application event
filters, ``LayoutIndependentShortcuts``, QShortcut conflict arbitration and
focus routing. A green run there cannot establish that a real Ctrl+V reaches
the editor -- which is exactly the claim the operator's intermittent
"No visible insertion" report puts in doubt.

So the presses here go through ``QTest.keyClick``. Measured on this build
(``probe_qtest_filters.py`` during the investigation, and pinned by
``test_qtest_does_not_reach_the_shortcut_map`` below), that route gives:

* the full application AND widget event-filter chain, including
  ``ShortcutOverride`` before ``KeyPress`` -- so ``LayoutIndependentShortcuts``
  really sees the key;
* delivery to the FOCUSED widget, so ``QApplication.focusWidget()`` has to be
  the editor for the press to be the thing under test;
* the widget's real visible/enabled/read-only state, which a hidden or
  read-only editor is subject to.

What it does NOT give is QShortcutMap arbitration (a ``QShortcut`` is only
activated by a platform key event) or a native scan code. Those two are
therefore not claimed here -- the shortcut-ownership claim lives in
``tests/test_editor_paste_shortcut_t1269.py``, and the physical-key claim
stays in the direct-handler module.

Every assertion is made against the real window: the active silo, the
``QTextDocument`` the editor is holding, the caret, and the paste cue.

What the operator's report requires the suite to decide
-------------------------------------------------------
* ``NEW`` seeds a silo through ``SnippetOpsMixin._clipboard_text_for_new_silo``
  (``clipboard.text()``) while Ctrl+V goes through ``insertFromMimeData``,
  which branches on the FORMATS present. "NEW can read the clipboard"
  therefore says nothing about the editor's paste route, and the two are
  exercised separately below.
* the cue is emitted BEFORE ``self.paste()`` in ``keyPressEvent``, so a sound
  is not evidence of an insertion -- assert the document revision, then the
  cue.
* no MIME branch may return silently when the same clipboard also carries
  usable text.
* a ``QShortcut`` configured onto Ctrl+V would win over the focused editor, so
  the conflict has to be detected and resolved instead of leaving two owners.

Clipboard hygiene: the machine clipboard is written by these tests. Every test
runs inside a snapshot/restore fixture.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QImage, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# the real window
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1269live")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1269live_{profile_id}.db"))
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
    # The deferred profile-apply (QTimer.singleShot(0)) clears the
    # initialization guards; without a running event loop it never fires and
    # every authoritative save would skip the live-editor flush.
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


@pytest.fixture
def sounds(monkeypatch, win):
    """Record the paste cue without reaching an audio backend."""
    played = []
    monkeypatch.setattr(win, "play_sound", played.append)
    return played


def _reset(win, texts=("alpha", "bravo", "charlie", "delta")):
    """Deterministic starting point: category bound, known silo texts."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = list(texts)
    win.text_area.setReadOnly(False)
    win._switch_to_slot(0, initial=True, is_archive=False)
    _APP.processEvents()
    return win.text_area


def _focus_editor(win):
    """Put real focus on the visible editor and report the owning widget."""
    win.text_area.setVisible(True)
    win.text_area.setReadOnly(False)
    win.activateWindow()
    win.text_area.setFocus(Qt.FocusReason.OtherFocusReason)
    _APP.processEvents()
    return QApplication.focusWidget()


def _silo_switch(win, slot):
    win._switch_to_slot(slot, is_archive=False)
    _APP.processEvents()


def _set_caret(editor, pos):
    cursor = editor.textCursor()
    cursor.setPosition(pos)
    editor.setTextCursor(cursor)


def _press_ctrl_v(widget):
    """A REAL Ctrl+V: spontaneous key event through QApplication.notify."""
    QTest.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()


def _press_ctrl_c(widget):
    QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()


def _direct_mime_for_branch_coverage(editor, data):
    """Exercise one MIME branch while marking it as a paste diagnostic.

    The production ring is intentionally Ctrl+V-only. These cases call the
    MIME entry point directly because QTest/offscreen cannot manufacture every
    native URL/image payload; the helper supplies only the diagnostic context,
    while the mandatory routing proof still uses ``QTest.keyClick``.
    """
    editor._paste_key_path = True
    editor._paste_paste_called = False
    editor._paste_insert_reached = False
    editor._paste_diagnostics_active = True
    try:
        editor.insertFromMimeData(data)
    finally:
        editor._paste_key_path = False
        editor._paste_diagnostics_active = False


def _set_clipboard_text(text):
    QApplication.clipboard().setText(text)
    _APP.processEvents()


# ---------------------------------------------------------------------------
# 1. MANDATORY end-to-end text paste proof
# ---------------------------------------------------------------------------

def test_real_ctrl_v_pastes_into_the_active_silo(win, sounds):
    """The live route: exact text, exact document, exact silo, exact focus."""
    editor = _reset(win)
    editor.setPlainText("hello world")
    _set_caret(editor, 5)
    _set_clipboard_text("XYZ")

    focused = _focus_editor(win)
    assert focused is editor, (
        "the editor must own focus for a real Ctrl+V to be the thing under "
        f"test, but QApplication.focusWidget() is {focused!r}")

    slot_before = win.active_temp_slot
    document_before = editor.document()
    revision_before = document_before.revision()
    _press_ctrl_v(editor)

    assert editor.toPlainText() == "helloXYZ world"
    assert editor.textCursor().position() == 8
    assert editor.document() is document_before, (
        "Ctrl+V must mutate the document the editor already holds, not swap in "
        "another one")
    assert editor.document().revision() > revision_before
    assert win.active_temp_slot == slot_before, (
        "a paste must not navigate between silos")
    assert QApplication.focusWidget() is focused, (
        "a paste must not hand focus anywhere else")
    assert sounds.count("paste") == 1, sounds


def test_real_ctrl_v_into_an_empty_silo(win, sounds):
    editor = _reset(win)
    editor.setPlainText("")
    _set_clipboard_text("seeded from the clipboard")
    _focus_editor(win)
    if editor.document().revision() == 0:
        editor.insertPlainText("")          # make the before/after comparable
    before = editor.toPlainText()
    _press_ctrl_v(editor)
    assert before == ""
    assert editor.toPlainText() == "seeded from the clipboard"
    assert sounds.count("paste") == 1, sounds


def test_real_ctrl_v_replaces_the_selection_on_the_live_route(win, sounds):
    editor = _reset(win)
    editor.setPlainText("keep DROP keep")
    cursor = editor.textCursor()
    cursor.setPosition(5)
    cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    _set_clipboard_text("NEW")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "keep NEW keep"
    assert sounds.count("paste") == 1, sounds


def test_real_ctrl_v_multiline_and_non_bmp_text(win, sounds):
    """Newlines, tabs and a non-BMP glyph survive the live route intact.

    U+00A0 is deliberately absent: ``QTextDocument`` turns a no-break space
    into an ordinary space on insert, and it does so for ``insertPlainText``
    just as much as for a paste -- measured, not assumed -- so asserting it
    here would be asserting Qt, not the paste route.
    """
    editor = _reset(win)
    editor.setPlainText("[]")
    _set_caret(editor, 1)
    payload = "line one\n\tline two \U0001F600\u4e2d\u6587"
    _set_clipboard_text(payload)
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "[" + payload + "]"
    assert editor.document().blockCount() == 2
    assert sounds.count("paste") == 1, sounds


# ---------------------------------------------------------------------------
# 2. document ownership across silo switches
# ---------------------------------------------------------------------------

def test_paste_after_a_b_a_switch_lands_in_a_document(win, sounds):
    """A -> B -> A: the visible document must be the active silo's own."""
    editor = _reset(win)
    _silo_switch(win, 0)
    editor.setPlainText("AAA")
    _silo_switch(win, 1)
    editor.setPlainText("BBB")
    _silo_switch(win, 0)

    document_a = editor.document()
    assert editor.toPlainText() == "AAA"
    _set_caret(editor, 3)
    _set_clipboard_text("-patched")
    _focus_editor(win)
    _press_ctrl_v(editor)

    assert editor.toPlainText() == "AAA-patched"
    assert editor.document() is document_a
    record = editor.paste_diagnostics()[-1]
    assert record["silo_document_id"] == id(document_a)
    assert record["document_owned_by_active_silo"] is True
    win._switch_to_slot(1, is_archive=False)
    _APP.processEvents()
    assert editor.toPlainText() == "BBB", (
        "the paste must not have leaked into the neighbouring silo")
    assert sounds.count("paste") == 1, sounds


def test_paste_into_an_older_silo_after_a_clipboard_seeded_new(win, sounds):
    """Sequence D: NEW seeds from the clipboard, then paste somewhere else.

    ``NEW`` reads ``clipboard.text()`` while Ctrl+V reads the MIME formats, so
    the two routes are asserted separately on the same window.
    """
    editor = _reset(win)
    _silo_switch(win, 0)
    editor.setPlainText("older silo")

    seeded = "seeded by NEW"
    _set_clipboard_text(seeded)
    win.data["new_silo_paste_clipboard"] = "True"
    win.select_empty_silo(insertion="top")
    _APP.processEvents()

    # NEW's route really did see the clipboard.
    assert win.data["temp_presets"][win.active_temp_slot] == seeded

    # ... and Ctrl+V's route is exercised independently.
    _silo_switch(win, win.active_temp_slot + 1)
    assert editor.toPlainText() == "older silo"
    _set_caret(editor, 0)
    _set_clipboard_text("pasted")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "pastedolder silo"
    assert sounds.count("paste") == 1, sounds


def test_paste_into_the_clipboard_seeded_new_silo(win, sounds):
    """Sequence C: paste a SECOND payload into the silo NEW just seeded."""
    editor = _reset(win)
    _set_clipboard_text("first payload")
    win.data["new_silo_paste_clipboard"] = "True"
    win.select_empty_silo(insertion="top")
    _APP.processEvents()
    assert editor.toPlainText() == "first payload"

    _set_clipboard_text(" + second")
    _set_caret(editor, len(editor.toPlainText()))
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "first payload + second"
    assert sounds.count("paste") == 1, sounds


# ---------------------------------------------------------------------------
# 3. view / visibility / predecessor sequences
# ---------------------------------------------------------------------------

def test_paste_survives_a_view_mode_round_trip(win, sounds):
    """Sequence E: Source View -> Live Preview -> Source View -> paste."""
    editor = _reset(win)
    editor.setPlainText("mode test")
    modes = [win.preview_combo.itemData(i) for i in range(win.preview_combo.count())]
    live = win.preview_combo.findData("Live Preview")
    source = win.preview_combo.findData("Source View")
    assert live != -1 and source != -1, modes

    win.preview_combo.setCurrentIndex(live)
    _APP.processEvents()
    win.preview_combo.setCurrentIndex(source)
    _APP.processEvents()

    _set_caret(editor, 0)
    _set_clipboard_text("pasted ")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "pasted mode test"
    assert sounds.count("paste") == 1, sounds


def test_reading_mode_does_not_claim_a_paste_it_cannot_perform(win, sounds):
    """A hidden editor must not emit a paste cue for an insertion it refuses.

    ``keyPressEvent`` plays the cue before ``self.paste()``, so a read-only or
    hidden editor used to produce exactly the operator's symptom: the sound
    plays, the document does not move. The cue is now gated on the SAME
    predicate the paste consults, and the refusal is recorded with its reason.
    """
    editor = _reset(win)
    editor.setPlainText("frozen")
    reading = win.preview_combo.findData("Reading")
    assert reading != -1
    win.preview_combo.setCurrentIndex(reading)
    _APP.processEvents()
    assert editor.isVisible() is False

    _set_clipboard_text("INTRUDER")
    before = editor.toPlainText()
    _press_ctrl_v(editor)

    assert editor.toPlainText() == before, "a hidden editor must not mutate"
    assert "paste" not in sounds, (
        "the paste cue must not play when no paste can happen: " + repr(sounds))
    refused = [r for r in editor.paste_diagnostics() if r["branch"] == "refused:read_only"]
    assert refused, [r["branch"] for r in editor.paste_diagnostics()]
    assert refused[-1]["key_path_reached"] is True
    assert refused[-1]["paste_called"] is False
    assert refused[-1]["document_changed"] is False

    win.preview_combo.setCurrentIndex(win.preview_combo.findData("Source View"))
    _APP.processEvents()


def test_read_only_editor_refuses_without_a_cue(win, sounds):
    editor = _reset(win)
    editor.setPlainText("frozen")
    editor.setReadOnly(True)
    _set_clipboard_text("INTRUDER")
    _focus_editor(win)
    editor.setReadOnly(True)

    _press_ctrl_v(editor)
    assert editor.toPlainText() == "frozen"
    assert "paste" not in sounds, sounds
    assert editor.paste_diagnostics()[-1]["branch"] == "refused:read_only"
    editor.setReadOnly(False)


def test_paste_after_hide_and_show(win, sounds):
    """Sequence H: hide/show the window, re-focus the editor, paste."""
    editor = _reset(win)
    editor.setPlainText("post-hide")
    win.hide()
    _APP.processEvents()
    win.show()
    _APP.processEvents()

    _set_caret(editor, 0)
    _set_clipboard_text("pasted ")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "pasted post-hide"
    assert sounds.count("paste") == 1, sounds


@pytest.mark.parametrize("control_name", [
    "search_input",       # search control
    "btn_toggle_search",  # sidebar/search control
    "btn_settings_toggle",  # settings control
])
def test_paste_after_focus_moves_through_app_controls(win, sounds, control_name):
    """Sequence G: another app control had focus before returning to editor."""
    editor = _reset(win)
    editor.setPlainText("after control")
    control = getattr(win, control_name)
    _focus_editor(win)
    if control_name == "search_input":
        win.show_find()
    else:
        control.setFocus(Qt.FocusReason.OtherFocusReason)
    _APP.processEvents()
    # The offscreen Windows backend may report no active focus window even
    # after a valid QWidget focus request. On a real desktop this is the
    # control itself; either way the next step deliberately returns focus via
    # the application window before sending the real Ctrl+V.
    focused = QApplication.focusWidget()
    if focused is not None:
        assert focused is control

    try:
        _set_caret(editor, 0)
        _set_clipboard_text("pasted ")
        _focus_editor(win)
        _press_ctrl_v(editor)
        assert editor.toPlainText() == "pasted after control"
        assert sounds.count("paste") == 1, sounds
    finally:
        if control_name == "search_input":
            win.close_search()
            _APP.processEvents()


def test_ctrl_c_then_ctrl_v_round_trip_inside_the_app(win, sounds):
    """Sequence I: copy inside FastPrompter, paste back inside FastPrompter."""
    editor = _reset(win)
    editor.setPlainText("roundtrip source")
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    _focus_editor(win)
    _press_ctrl_c(editor)
    assert QApplication.clipboard().text() == "roundtrip"

    editor.setPlainText("")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "roundtrip"
    assert sounds.count("paste") == 1, sounds


def test_repeated_ctrl_v_after_a_silo_document_swap(win, sounds):
    """Sequence K: repeated paste straddling a document swap."""
    editor = _reset(win)
    _silo_switch(win, 0)
    editor.setPlainText("")
    _set_clipboard_text("ab")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "ab"

    _silo_switch(win, 2)
    editor.setPlainText("")
    _focus_editor(win)
    _press_ctrl_v(editor)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == "abab"
    assert sounds.count("paste") == 3, sounds


# ---------------------------------------------------------------------------
# 4. shortcut ownership: nothing configurable may steal Ctrl+V
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hotkey", ["hk_find", "hk_save_snippet", "hk_divider",
                                    "hk_bold", "hk_undo"])
def test_editor_shortcut_conflict_decision(hotkey):
    """The pure decision: a configurable command may not take Ctrl+V."""
    from fastprompter.main import editor_shortcut_conflict
    assert editor_shortcut_conflict(hotkey, "Ctrl+V") == "paste"
    assert editor_shortcut_conflict(hotkey, "ctrl+v") == "paste"
    assert editor_shortcut_conflict(hotkey, "Ctrl+A") == "select all"
    assert editor_shortcut_conflict(hotkey, "Ctrl+C") == "copy"
    assert editor_shortcut_conflict(hotkey, "Ctrl+X") == "cut"
    assert editor_shortcut_conflict(hotkey, "Ctrl+Y") == "redo"
    # Keys the editor does not own stay available to the user.
    for free in ("Ctrl+D", "Ctrl+F", "Ctrl+B", "Shift+Ctrl+V",
                 "Ctrl+Alt+V", "Alt+V"):
        assert editor_shortcut_conflict(hotkey, free) is None, free


def test_ctrl_z_keeps_its_shipped_owner_only():
    from fastprompter.main import editor_shortcut_conflict
    assert editor_shortcut_conflict("hk_undo", "Ctrl+Z") is None
    assert editor_shortcut_conflict("hk_find", "Ctrl+Z") == "undo"


def test_default_profile_has_no_hotkey_conflicts(win):
    """Asserted without rebuilding shortcuts: the startup call already ran."""
    conflicts = win.hotkey_conflicts()
    assert conflicts == [], (
        "every shipped default must leave the editor's editing keys alone: "
        f"{conflicts}")


def test_editor_reserved_sequences_cover_the_editing_keys():
    from fastprompter.main import EDITOR_RESERVED_SEQUENCES
    for seq in ("Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Y"):
        assert seq in EDITOR_RESERVED_SEQUENCES, seq
    assert EDITOR_RESERVED_SEQUENCES["Ctrl+V"] == ("paste", None)
    assert EDITOR_RESERVED_SEQUENCES["Ctrl+X"] == ("cut", None)
    # Ctrl+Z's shipped owner is the window's smart undo; anything else is a
    # collision, because it would take undo away from the whole application.
    assert EDITOR_RESERVED_SEQUENCES["Ctrl+Z"] == ("undo", "hk_undo")


def test_the_shipped_ctrl_z_owner_really_registered(win):
    """hk_undo defaults to Ctrl+Z and kept it -- no self-inflicted break."""
    assert win.data.get("hk_undo", "Ctrl+Z") == "Ctrl+Z"
    assert [c for c in win.hotkey_conflicts() if c["sequence"] == "Ctrl+Z"] == []
    registered = {s.key().toString() for s in win._app_shortcuts}
    assert "Ctrl+Z" in registered, sorted(registered)


# ---------------------------------------------------------------------------
# 5. the paste RESULT contract and its diagnostics
# ---------------------------------------------------------------------------

def test_paste_record_names_the_branch_and_proves_the_insertion(win, sounds):
    editor = _reset(win)
    editor.setPlainText("x")
    _set_caret(editor, 1)
    _set_clipboard_text("yz")
    _focus_editor(win)
    _press_ctrl_v(editor)

    record = editor.paste_diagnostics()[-1]
    assert record["branch"] == "text_plain", record["branch"]
    assert record["key_path_reached"] is True
    assert record["paste_called"] is True
    assert record["insert_reached"] is True
    assert record["document_changed"] is True
    assert record["document_revision_after"] > record["document_revision_before"]
    assert record["editor_id"] == id(editor)
    assert record["document_id"] == id(editor.document())
    assert record["cursor_position"] is not None
    assert record["editor_read_only"] is False
    assert record["silo_view_page"] == win.silo_view.currentIndex()
    assert record["document_owned_by_active_silo"] is True
    assert record["mime"]["has_text"] is True
    assert record["mime"]["text_length"] == 2


def test_key_route_records_a_missing_mime_callback(win, sounds, monkeypatch):
    """A reached key with a broken paste call is diagnosable as such."""
    editor = _reset(win)
    editor.setPlainText("unchanged")
    _set_caret(editor, len(editor.toPlainText()))
    _set_clipboard_text("payload")
    _focus_editor(win)
    monkeypatch.setattr(editor, "paste", lambda: None)

    _press_ctrl_v(editor)

    record = editor.paste_diagnostics()[-1]
    assert record["key_path_reached"] is True
    assert record["paste_called"] is True
    assert record["insert_reached"] is False
    assert record["document_changed"] is False
    assert record["branch"] == "paste_no_insert_callback"
    assert sounds.count("paste") == 1


def test_paste_diagnostics_never_record_clipboard_content(win, sounds):
    """The evidence has to be usable without leaking what was copied."""
    secret = "TOP-SECRET-PAYLOAD-2b7f"
    editor = _reset(win)
    editor.setPlainText("")
    _set_clipboard_text(secret)
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert editor.toPlainText() == secret

    for record in editor.paste_diagnostics():
        assert secret not in repr(record)
    assert editor.paste_diagnostics()[-1]["mime"]["text_length"] == len(secret)


def test_diagnostics_ring_is_bounded(win, sounds):
    editor = _reset(win)
    editor.setPlainText("")
    _set_clipboard_text("q")
    _focus_editor(win)
    for _ in range(editor._PASTE_DIAG_LIMIT + 8):
        _press_ctrl_v(editor)
    assert len(editor.paste_diagnostics()) == editor._PASTE_DIAG_LIMIT


def test_ordinary_typing_does_not_grow_the_ring(win, sounds):
    editor = _reset(win)
    editor.setPlainText("")
    _focus_editor(win)
    before = len(editor.paste_diagnostics())
    QTest.keyClicks(editor, "typing away")
    _APP.processEvents()
    assert editor.toPlainText() == "typing away"
    assert len(editor.paste_diagnostics()) == before


# ---------------------------------------------------------------------------
# 6. MIME differential: no branch may silently do nothing
# ---------------------------------------------------------------------------

def _unreadable(path):
    """Claim a text file exists but refuse to read it."""
    return path


@pytest.mark.parametrize("shape", [
    "plain_text",
    "text_plus_html",
    "text_plus_html_plus_url",
])
def test_text_capable_clipboards_always_produce_a_result(win, sounds, shape,
                                                         tmp_path):
    """Every text-capable clipboard shape must change the document.

    These are the shapes the operator's machine can actually hold. A round
    trip through the real clipboard is used where the offscreen backend
    preserves the format; the assertion is the same either way: the document
    moves, or a documented file/link action happened instead -- never silence.
    """
    editor = _reset(win)
    editor.setPlainText("")

    data = QMimeData()
    data.setText("whole payload")
    if shape in ("text_plus_html", "text_plus_html_plus_url"):
        data.setHtml("<p>whole payload</p>")
    if shape == "text_plus_html_plus_url":
        source = tmp_path / "notes.txt"
        source.write_text("file body", encoding="utf-8")
        data.setUrls([QUrl.fromLocalFile(str(source))])

    QApplication.clipboard().setMimeData(data)
    _APP.processEvents()

    # Reproduce the operator's asymmetry explicitly: NEW's route must see the
    # ordinary text representation before Ctrl+V takes its MIME-aware route.
    assert win._clipboard_text_for_new_silo() == "whole payload"

    _focus_editor(win)
    _press_ctrl_v(editor)

    text = editor.toPlainText()
    assert text != "", (
        f"{shape}: a text-capable clipboard reached a writable editor and "
        "produced nothing")
    record = editor.paste_diagnostics()[-1]
    assert record["document_changed"] is True, record

    # The operator's NEW observation was proven above on the same clipboard
    # shape; Ctrl+V must not be silent after that route succeeds.


@pytest.mark.parametrize("shape", [
    "urls_empty_with_text",
    "urls_remote_with_text",
    "image_without_payload_with_text",
    "unreadable_local_text_file_with_text",
    "empty_local_text_file_with_text",
    "malformed_mixed",
])
def test_no_rich_branch_returns_silently_when_text_is_present(win, sounds,
                                                              shape, monkeypatch,
                                                              tmp_path):
    """The early-return audit, driven through the editor's MIME entry point.

    A synthetic payload is needed here -- ``hasImage() == True`` with a null
    ``imageData()``, or a URL list that cannot be round-tripped through the
    offscreen clipboard -- so the shape is handed to ``insertFromMimeData``
    directly. That is the same call ``self.paste()`` makes, and the assertion
    is about the branch contract, not about key routing (section 1 covers
    routing).
    """
    editor = _reset(win)
    editor.setPlainText("")
    # ``_insert_from_mime_data`` consults the silo folder for images.
    editor.main_win._silo_folder_dir = lambda *a, **k: str(tmp_path)

    data = QMimeData()
    data.setText("usable text")
    expected_owner = "text"

    if shape == "urls_remote_with_text":
        data.setUrls([QUrl("https://example.invalid/remote")])
        expected_owner = "url"
    elif shape == "urls_empty_with_text":
        # A custom/native provider may claim the URL representation while
        # returning no usable URL objects. Keep this shape explicit.
        monkeypatch.setattr(data, "hasUrls", lambda: True)
        monkeypatch.setattr(data, "urls", lambda: [])
    elif shape == "image_without_payload_with_text":
        monkeypatch.setattr(data, "hasImage", lambda: True)
        monkeypatch.setattr(data, "imageData", lambda: None)
    elif shape == "unreadable_local_text_file_with_text":
        target = tmp_path / "report.md"
        target.write_text("on disk", encoding="utf-8")
        data.setUrls([QUrl.fromLocalFile(str(target))])

        import fastprompter.ui.editor as editor_mod
        monkeypatch.setattr(editor_mod, "_read_text_file",
                            lambda path: _raise_oserror(path))
    elif shape == "empty_local_text_file_with_text":
        target = tmp_path / "empty.md"
        target.write_text("", encoding="utf-8")
        data.setUrls([QUrl.fromLocalFile(str(target))])
        monkeypatch.setattr(
            data, "text", lambda: "usable text")
    elif shape == "malformed_mixed":
        data.setHtml("<p>usable text</p>")
        data.setUrls([])

    revision_before = editor.document().revision()
    _direct_mime_for_branch_coverage(editor, data)
    _APP.processEvents()

    text = editor.toPlainText()
    changed = editor.document().revision() != revision_before
    record = editor.paste_diagnostics()[-1]
    assert record["insert_reached"] is True

    if not changed:
        pytest.fail(
            f"{shape}: the MIME branch did nothing at all although the "
            f"clipboard carries usable text (branch={record['branch']}, "
            f"mime={record['mime']})")
    if expected_owner == "text":
        assert "usable text" in text, (shape, repr(text), record["branch"])
    else:
        assert "example.invalid" in text, (shape, repr(text))


def _raise_oserror(path):
    raise OSError("simulated unreadable file")


def test_url_only_clipboard_is_a_documented_action_never_silence(win, sounds):
    """A remote URL pastes as the URL itself -- an explicit, documented shape."""
    editor = _reset(win)
    editor.setPlainText("")
    QApplication.clipboard().setText("https://example.invalid/page")
    _focus_editor(win)
    _press_ctrl_v(editor)
    assert "https://example.invalid/page" in editor.toPlainText()
    assert editor.paste_diagnostics()[-1]["document_changed"] is True


def test_image_clipboard_paste_still_saves_a_file(win, sounds, tmp_path):
    editor = _reset(win)
    editor.setPlainText("")
    editor.main_win._silo_folder_dir = lambda *a, **k: str(tmp_path)
    editor.main_win._file_container = None
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x112233)
    data = QMimeData()
    data.setImageData(image)

    _direct_mime_for_branch_coverage(editor, data)
    _APP.processEvents()

    saved = list(tmp_path.glob("paste-*.png"))
    assert saved, "the image payload must land on disk"
    assert saved[0].name in editor.toPlainText()
    assert editor.paste_diagnostics()[-1]["branch"] == "image_saved"


def test_no_urls_and_no_text_and_no_image_changes_nothing(win, sounds):
    """The one shape where doing nothing is correct is reported, not silent."""
    editor = _reset(win)
    editor.setPlainText("unchanged")
    _focus_editor(win)
    _direct_mime_for_branch_coverage(editor, QMimeData())
    assert editor.toPlainText() == "unchanged"
    assert editor.paste_diagnostics()[-1]["branch"] == "empty_mime"


def test_non_keyboard_mime_insertion_does_not_fill_ctrl_v_ring(win, sounds):
    """Drag/drop MIME delivery is not reported as a Ctrl+V attempt."""
    editor = _reset(win)
    editor.setPlainText("")
    before = len(editor.paste_diagnostics())
    editor.insertFromMimeData(QMimeData())
    assert editor.toPlainText() == ""
    assert len(editor.paste_diagnostics()) == before


# ---------------------------------------------------------------------------
# 7. the layout-normalized live route
# ---------------------------------------------------------------------------

# NOTE: the physical-key normalization (a Russian layout reporting Key_M for
# the physical V) cannot be driven through QTest -- QTest::keyClick carries no
# scan code -- so it stays pinned where it can be observed, in
# tests/test_editor_paste_t1269.py. What this module owns is the routing above
# the handler.


# ---------------------------------------------------------------------------
# 8. LATE: shortcut ownership, end to end
# ---------------------------------------------------------------------------

def test_no_startup_hotkey_can_take_an_editor_key(win):
    """The bindings the app actually registered may not rival the editor.

    Ctrl+Z and Ctrl+Y are SHARED and deliberately so: ``hk_undo`` and the fixed
    Ctrl+Y both run the very window handler the editor's own branch calls, so
    whichever wins the keypress the user gets the same undo/redo -- one owner
    for one action. Ctrl+A/C/V/X are different: the editor is their only
    implementation, so an app-level owner for any of them would mean the
    editor's copy/cut/paste/select-all never runs for that keypress.

    A CONFIGURABLE hotkey may not claim Ctrl+Y either (see the pure-decision
    tests): the fixed redo binding is the product's own delegate, but a remap
    putting some other command on Ctrl+Y would take redo with it.
    """
    from fastprompter.main import _portable_sequence
    registered = {_portable_sequence(s.key()) for s in win._app_shortcuts}
    assert {"Ctrl+Z", "Ctrl+Y"} <= registered, sorted(registered)
    exclusive = {"Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X"}
    offending = sorted(registered & exclusive)
    assert offending == [], (
        "an app-level shortcut owns a key only the editor implements, which "
        f"would steal it from the editor: {offending}")
    assert win.hotkey_conflicts() == []


def test_qtest_does_not_reach_the_shortcut_map(win, monkeypatch):
    """Pin the harness's own limit, so this suite's scope stays honest.

    A ``QShortcut`` wins over the focused widget in production, and it does NOT
exist in QTest: the event is delivered to the widget, so the shortcut never
    activates. If a future Qt starts routing QTest presses through the shortcut
    map, this test fails and the "QTest cannot settle shortcut ownership"
    caveat above stops being true -- which is exactly when somebody needs to
    know, because the whole module's claims would need re-reading.
    """
    from PyQt6.QtGui import QKeySequence, QShortcut
    editor = _reset(win)
    editor.setPlainText("base")
    stolen = []
    shortcut = QShortcut(QKeySequence("Ctrl+V"), win,
                         context=Qt.ShortcutContext.ApplicationShortcut)
    shortcut.activated.connect(lambda: stolen.append("hk_find"))
    try:
        _set_caret(editor, 4)
        _set_clipboard_text("-ok")
        _focus_editor(win)
        _press_ctrl_v(editor)
        assert stolen == [], (
            "QTest now activates QShortcuts: the shortcut-ownership caveat in "
            "this module's docstring is stale and must be re-derived")
        assert editor.toPlainText() == "base-ok", (
            "the editor received the key directly, as QTest does")
    finally:
        shortcut.setEnabled(False)
        shortcut.deleteLater()
        _APP.processEvents()
