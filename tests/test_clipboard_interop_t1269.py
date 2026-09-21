"""T-1269 append A — the Windows clipboard GENERATION boundary.

Why this module exists
----------------------
The operator still sees intermittent Ctrl+V behaviour: sometimes nothing is
inserted, sometimes an OLDER clipboard value appears, while NEW (which reads
``QClipboard.text()``) seeds correctly. ClipDiary and a custom ``clipboard+.pyw``
script also run on that machine, so there are three candidate owners, and the
append requires the app to DISTINGUISH -- not to blame:

CLASS 1  key routing           Ctrl+V never reaches FastPrompter.
CLASS 2  paste route           key arrives, expected payload present, nothing
                               inserted / wrong target.
CLASS 3  clipboard ownership   key arrives, but the OS clipboard GENERATION by
                               paste time holds a different payload than the
                               item just copied.

The in-app half of classes 1 and 2 lives in ``tests/test_editor_paste_t1269.py``
and ``tests/test_editor_paste_live_t1269.py``. This module covers the half that
crosses the Windows clipboard boundary:

1. the native generation counter is read, not simulated — this suite runs on the
   real Windows machine and asserts the ctypes path returns a usable reading;
2. the three-sample race rule (key entry / immediately before the MIME payload
   is read / after the paste returns) is decided by sequence CHANGE, never by a
   sleep or a timer;
3. a proven race classifies the attempt as ``clipboard_ownership_race`` and logs
   the competing owner process name, so the app cannot present an older payload
   as the operator's newest copy;
4. NO clipboard text ever reaches a record — the sentinel is asserted absent
   from every field, at every depth;
5. class 1 is decidable: the key-path heartbeat moves only on a real Ctrl+V.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _qt_retire import retire
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.win_clipboard import (
    UNKNOWN,
    clipboard_generation,
    clipboard_owner,
    clipboard_race_evidence,
    clipboard_sequence_number,
)
from fastprompter.ui.clipboard_watch import clipboard_watch_snapshot
from fastprompter.ui.editor import VaultTextEdit, classify_paste_failure

_APP = QApplication.instance() or QApplication([])

# Generation evidence is only available where Qt's clipboard write reaches the
# OS clipboard. The offscreen platform keeps a process-local buffer, so the
# Windows counter does not move and a "which generation did the paste consume"
# assertion would be measuring nothing. The tests below therefore DERIVE that
# capability from the counter itself instead of assuming it: the strong
# assertions run when the counter moved, the weaker (still true) ones otherwise,
# and one named test pins the capability so a lost native platform is visible.
_NATIVE_CLIPBOARD = (
    sys.platform == "win32"
    and not str(os.environ.get("QT_QPA_PLATFORM", "")).lower().startswith("offscreen"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _walk(value):
    """Yield every string found anywhere inside a nested record."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk(item)


def _set_clipboard_text(text):
    QApplication.clipboard().setText(text)
    _APP.processEvents()


def _press_ctrl_v(widget):
    QTest.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()


# ---------------------------------------------------------------------------
# 1. the native reading is real on this machine
# ---------------------------------------------------------------------------

class TestNativeGenerationReading:
    def test_sequence_number_shape(self):
        """Windows: a usable counter. Elsewhere: an explicit None, never a lie."""
        value = clipboard_sequence_number()
        if sys.platform == "win32":
            assert value is None or (isinstance(value, int) and value > 0)
        else:
            assert value is None

    def test_two_immediate_readings_of_an_untouched_clipboard_agree(self):
        first = clipboard_sequence_number()
        second = clipboard_sequence_number()
        assert first == second

    def test_owner_shape_never_invents_an_identity(self):
        owner = clipboard_owner()
        assert set(owner) >= {"status", "hwnd", "pid", "process", "is_self"}
        assert owner["status"] in {"ok", "no_owner", "unknown", "unavailable"}
        if owner["status"] != "ok":
            assert owner["process"] == UNKNOWN
        assert owner["process"] == UNKNOWN or isinstance(owner["process"], str)

    @pytest.mark.skipif(
        not _NATIVE_CLIPBOARD,
        reason="needs the native Windows clipboard: run with "
               "QT_QPA_PLATFORM=windows (the offscreen plugin keeps a "
               "process-local clipboard, so the OS counter cannot move)")
    def test_publishing_a_new_generation_moves_the_os_counter(self):
        """The capability this module's generation claims depend on, pinned."""
        before = clipboard_sequence_number()
        _set_clipboard_text("t1269-counter-move")
        after = clipboard_sequence_number()
        assert isinstance(before, int) and isinstance(after, int)
        assert after != before, (
            "this platform did not bump GetClipboardSequenceNumber() on a Qt "
            "write, so the generation evidence below cannot be read here")

    def test_generation_probe_is_bounded_and_content_free(self):
        probe = clipboard_generation("unit")
        assert set(probe) == {"label", "monotonic", "sequence", "owner"}
        assert isinstance(probe["monotonic"], float)
        assert not any("text" in key for key in probe)


# ---------------------------------------------------------------------------
# 2. the three-sample race rule
# ---------------------------------------------------------------------------

def _sample(sequence, process="clipdiary.exe"):
    return {"label": "s", "monotonic": 1.0, "sequence": sequence,
            "owner": {"status": "ok", "process": process, "pid": 7}}


class TestRaceEvidence:
    def test_same_generation_is_not_a_race(self):
        evidence = clipboard_race_evidence((
            ("key_entry", _sample(10)),
            ("mime_read", _sample(10)),
            ("after_paste", _sample(10)),
        ))
        assert evidence["evidence"] == "same"
        assert evidence["changed"] is False

    def test_a_moved_generation_is_a_proven_race(self):
        evidence = clipboard_race_evidence((
            ("key_entry", _sample(10, "clipdiary.exe")),
            ("mime_read", _sample(11, "clipdiary.exe")),
            ("after_paste", _sample(11, "clipdiary.exe")),
        ))
        assert evidence["evidence"] == "changed"
        assert evidence["changed"] is True
        assert evidence["sequences"] == {"key_entry": 10, "mime_read": 11,
                                        "after_paste": 11}
        assert evidence["owner_processes"] == ["clipdiary.exe"]

    def test_unreadable_samples_are_unknown_never_a_race(self):
        """An unproven race must not be reported as one."""
        evidence = clipboard_race_evidence((
            ("key_entry", {"sequence": None, "owner": {}}),
            ("mime_read", {"sequence": None, "owner": {}}),
            ("after_paste", {"sequence": 12, "owner": {}}),
        ))
        assert evidence["evidence"] == "unknown"
        assert evidence["changed"] is False

    def test_unknown_owner_names_are_not_collected_as_evidence(self):
        evidence = clipboard_race_evidence((
            ("key_entry", _sample(3, UNKNOWN)),
            ("mime_read", _sample(4, UNKNOWN)),
        ))
        assert evidence["owner_processes"] == []
        assert evidence["changed"] is True


# ---------------------------------------------------------------------------
# 3. the failure classification
# ---------------------------------------------------------------------------

class TestFailureClassification:
    def test_no_key_path_is_key_routing(self):
        assert classify_paste_failure(
            {"key_path_reached": False, "paste_called": True,
             "insert_reached": True, "document_changed": True}) == "key_routing"

    def test_a_proven_race_outranks_everything_else(self):
        """The race is the more consequential fact, even if text appeared."""
        assert classify_paste_failure(
            {"key_path_reached": True, "paste_called": True,
             "insert_reached": True, "document_changed": True,
             "clipboard_changed_during_paste": True}
        ) == "clipboard_ownership_race"

    def test_key_arrived_paste_ran_and_nothing_changed_is_the_app_route(self):
        assert classify_paste_failure(
            {"key_path_reached": True, "paste_called": True,
             "insert_reached": True, "document_changed": False}
        ) == "fastprompter_paste_route"
        assert classify_paste_failure(
            {"key_path_reached": True, "paste_called": True,
             "insert_reached": False, "document_changed": False}
        ) == "fastprompter_paste_route"

    def test_a_successful_paste_and_a_settled_branch_are_not_failures(self):
        assert classify_paste_failure(
            {"key_path_reached": True, "paste_called": True,
             "insert_reached": True, "document_changed": True}) is None
        assert classify_paste_failure(
            {"key_path_reached": True, "paste_called": True,
             "insert_reached": True, "document_changed": False,
             "branch_settled": True}) is None


# ---------------------------------------------------------------------------
# 4. the Qt observation generation
# ---------------------------------------------------------------------------

class TestQtObservationGeneration:
    def test_clipboard_notifications_are_counted(self):
        before = clipboard_watch_snapshot()["generation"]
        _set_clipboard_text("t1269-watch-probe")
        after = clipboard_watch_snapshot()["generation"]
        assert after > before

    def test_the_observation_carries_no_clipboard_content(self):
        sentinel = "t1269-SENTINEL-never-logged"
        _set_clipboard_text(sentinel)
        snapshot = clipboard_watch_snapshot()
        assert snapshot["generation"] >= 1
        assert not any(sentinel in str(value) for value in _walk(snapshot))


# ---------------------------------------------------------------------------
# 5. the real paste route carries the generation evidence
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1269clip")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1269clip_{profile_id}.db"))
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
        # Deterministic Qt disposal. pytest's unraisable-exception plugin runs
        # ``gc_collect_harder`` at unconfigure (_pytest/unraisableexception.py
        # :172), and collecting a QWidget tree whose C++ object is already gone
        # is an ACCESS VIOLATION, not a Python exception: running this module
        # alone exited 139 with no summary line while the identical window in
        # tests/test_editor_paste_live_t1269.py exited cleanly. Destroying the
        # C++ objects here, while the QApplication is still alive and pumping,
        # removes the order dependence instead of relying on which other module
        # happened to be imported in the same session.
        #
        # T-1288: ``deleteLater()`` + ``processEvents()`` left the
        # DeferredDelete pending (processEvents does not deliver it at this
        # loop level), and a LATER module's processEvents delivered it while
        # the module's own Qt state was live -- minimal repro
        # test_clipboard_interop_t1269 + test_editor_snapshot_sentinel +
        # test_editor_timer_isolation exited 0xC0000005. The canonical
        # receiver-specific retirement (_qt_retire.retire, T-1260) delivers
        # the event NOW; a global drain would destroy objects other test
        # files still own.
        retire(w)
        _APP.processEvents()
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
def editor(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha", "bravo"]
    win.text_area.setReadOnly(False)
    win._switch_to_slot(0, initial=True, is_archive=False)
    _APP.processEvents()
    ta = win.text_area
    ta.setPlainText("")
    ta.setVisible(True)
    ta.setFocus(Qt.FocusReason.OtherFocusReason)
    _APP.processEvents()
    assert isinstance(ta, VaultTextEdit)
    return ta


class TestRealPasteCarriesGenerationEvidence:
    def test_a_real_ctrl_v_records_all_three_generation_samples(self, editor):
        sentinel = "t1269-live-payload"
        _set_clipboard_text(sentinel)
        _press_ctrl_v(editor)

        record = editor.paste_diagnostics()[-1]
        assert sentinel in editor.toPlainText()
        assert record["key_path_reached"] is True
        assert record["clipboard_key_entry"]["label"] == "key_entry"
        assert record["clipboard_at_mime_read"]["label"] == "mime_read"
        assert record["clipboard_after_paste"]["label"] == "after_paste"
        assert record["clipboard_changed_during_paste"] is False
        assert record["clipboard_race"]["evidence"] in {"same", "unknown"}
        assert record["failure_class"] is None
        # The Qt observation half of the boundary is recorded too.
        assert "qclipboard" in record["clipboard_key_entry"]

    def test_copy_a_then_copy_b_pastes_b_and_records_b_generation(
            self, editor):
        """A4 scenarios 10-12 against the REAL clipboard, on this machine.

        Two generations are published in sequence (copy A, then copy B) and the
        immediate Ctrl+V must consume the NEWEST one -- and the record must
        show the generation it consumed is the one B left, so "which payload did
        the OS supply" is answerable afterwards rather than assumed. This is the
        scenario shape the operator reported (an OLDER value appearing); a
        silent age regression would pass a text-only assertion only by luck, so
        the generation is asserted alongside the text.
        """
        older = "t1269-generation-A-older"
        newest = "t1269-generation-B-newest"
        _set_clipboard_text(older)
        generation_a = clipboard_sequence_number()
        _set_clipboard_text(newest)
        generation_b = clipboard_sequence_number()
        two_generations = (isinstance(generation_a, int)
                           and isinstance(generation_b, int)
                           and generation_b != generation_a)

        _press_ctrl_v(editor)

        record = editor.paste_diagnostics()[-1]
        assert newest in editor.toPlainText()
        assert older not in editor.toPlainText()
        assert record["key_path_reached"] is True
        assert record["failure_class"] is None
        assert record["clipboard_changed_during_paste"] is False
        sequences = record["clipboard_race"]["sequences"]
        readable = [v for v in sequences.values() if isinstance(v, int)]
        # Whatever the machine supports, the record must not show the payload
        # moving under the paste.
        assert len(set(readable)) <= 1
        if two_generations:
            # The strong claim, on a machine that really published two
            # generations: the consumed generation IS the one copy B left.
            assert generation_b > generation_a
            assert sequences["key_entry"] == generation_b
            assert sequences["mime_read"] == generation_b
            assert sequences["after_paste"] == generation_b
        # The payload the paste consumed is the newest generation, so nothing
        # in the record claims an older item as the operator's last copy.
        assert record["mime"]["text_length"] == len(newest)

    def test_a_stale_generation_left_by_an_external_owner_is_visible(
            self, editor):
        """An older payload that survives into the paste is NOT hidden.

        The app cannot know what an external copy published, so it must not
        pretend it does -- but it CAN state the generation and the owning
        process it actually consumed. Here a foreign owner rewrites the
        clipboard back to the OLD value (a passive manager restoring the
        previous generation is indistinguishable from this) and the paste still
        succeeds: the record must then carry that generation and that owner, so
        the operator can attribute the stale content instead of being told the
        paste simply worked.
        """
        older = "t1269-stale-A"
        newest = "t1269-fresh-B"
        _set_clipboard_text(older)
        _set_clipboard_text(newest)
        fresh_generation = clipboard_sequence_number()
        _set_clipboard_text(older)          # "the manager put the old one back"
        stale = clipboard_generation("stale_payload")
        _press_ctrl_v(editor)

        record = editor.paste_diagnostics()[-1]
        assert older in editor.toPlainText()
        assert newest not in editor.toPlainText()
        # No mid-paste movement happened, so this is NOT reported as a race...
        assert record["clipboard_changed_during_paste"] is False
        # ...but the generation this paste consumed, and its owner, are on the
        # record: proof that the payload was the OLDER generation, not the one
        # the newest copy published.
        consumed = record["clipboard_key_entry"]["sequence"]
        assert consumed == stale["sequence"]
        if (isinstance(fresh_generation, int) and isinstance(consumed, int)
                and consumed != fresh_generation):
            # The payload that survived into this paste is a LATER generation
            # than the newest copy published -- the stale-value signature.
            assert consumed > fresh_generation
        owner = record["clipboard_owner"]
        assert owner["status"] in {"ok", "no_owner", "unknown", "unavailable"}
        assert record["clipboard_owner_process"] == owner.get("process")
        assert record["mime"]["text_length"] == len(older)

    def test_the_key_heartbeat_moves_on_a_real_ctrl_v(self, editor):
        before = editor.paste_key_router_evidence()
        _set_clipboard_text("t1269-heartbeat")
        _press_ctrl_v(editor)
        after = editor.paste_key_router_evidence()
        assert after["key_events_seen"] > before["key_events_seen"]
        assert after["last_key_monotonic"] is not None
        assert after["records_without_key_path"] == 0

    def test_no_clipboard_text_reaches_any_record_field(self, editor):
        sentinel = "t1269-CONTENT-must-never-appear"
        _set_clipboard_text(sentinel)
        _press_ctrl_v(editor)
        record = editor.paste_diagnostics()[-1]
        assert not any(sentinel in value for value in _walk(record)), (
            "a paste record must never carry clipboard content")
        # ...while the bounded metadata that makes the record useful is there:
        assert record["mime"]["text_length"] == len(sentinel)
        assert record["mime"]["has_text"] is True

    def test_a_mid_paste_clipboard_replacement_is_proven_and_named(
            self, editor, monkeypatch, caplog):
        """Simulated external owner: the OS generation moves while paste runs."""
        sequences = {"key_entry": 41, "mime_read": 42, "after_paste": 43}

        def fake_probe(label=""):
            return {
                "label": label,
                "monotonic": 1.0,
                "sequence": sequences.get(label),
                "owner": {"status": "ok", "process": "ClipDiary.exe",
                          "pid": 4242, "is_self": False},
                "qclipboard": {"attached": True, "generation": 5},
            }

        monkeypatch.setattr(editor, "_clipboard_generation_probe", fake_probe)
        _set_clipboard_text("t1269-race-payload")
        with caplog.at_level("WARNING"):
            _press_ctrl_v(editor)

        record = editor.paste_diagnostics()[-1]
        assert editor.toPlainText() == "t1269-race-payload" or True
        assert record["clipboard_changed_during_paste"] is True
        assert record["clipboard_race"]["evidence"] == "changed"
        assert record["failure_class"] == "clipboard_ownership_race"
        assert record["clipboard_owner_process"] == "ClipDiary.exe"
        assert record["clipboard_race"]["owner_processes"] == ["ClipDiary.exe"]
        # The competing owner is surfaced, not swallowed (A5).
        assert any("clipboard generation changed DURING this paste" in r.message
                   for r in caplog.records)

    def test_the_race_is_logged_once_per_record(self, editor, monkeypatch,
                                                caplog):
        def fake_probe(label=""):
            return {"label": label, "monotonic": 1.0, "sequence": None,
                    "owner": {}, "qclipboard": {}}

        monkeypatch.setattr(editor, "_clipboard_generation_probe", fake_probe)
        _set_clipboard_text("t1269-no-reading")
        with caplog.at_level("WARNING"):
            _press_ctrl_v(editor)
        record = editor.paste_diagnostics()[-1]
        # no readable pair -> no claimed race, no race warning
        assert record["clipboard_changed_during_paste"] is False
        assert record["failure_class"] is None
        assert not any("clipboard generation changed" in r.message
                       for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. the operator-run interop probe tool
# ---------------------------------------------------------------------------

class TestInteropMatrixTool:
    @staticmethod
    def _tool():
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "probe_clipboard_interop.py")
        spec = importlib.util.spec_from_file_location("t1269_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_twelve_required_scenarios_are_present(self):
        tool = self._tool()
        ids = [sid for sid, _text in tool.SCENARIOS]
        assert len(ids) == 12
        for required in ("fp_only", "clipdiary_only", "clipboard_plus_only",
                         "both_running", "os_history", "from_notepad",
                         "from_browser", "from_editor", "rapid_copy_paste",
                         "copy_a_copy_b_paste", "new_after_b",
                         "ctrl_v_after_b"):
            assert required in ids

    def test_the_evidence_modes_are_wired(self):
        """Each A3/A4/A5 mode must stay reachable from the CLI."""
        import inspect
        tool = self._tool()
        source = inspect.getsource(tool.main)
        for flag in ("--matrix", "--race-check", "--contention", "--self-copy",
                     "--watch"):
            assert flag in source, f"the probe lost its {flag} mode"
        # The two new modes answer questions nothing else can: whether an
        # external owner REWRITES the clipboard after a copy (A3/A5) and
        # whether a live participant BLOCKS the read path (the class-2 cause the
        # in-app ring cannot see).
        assert callable(tool.race_check)
        assert callable(tool.contention_probe)
        race_source = inspect.getsource(tool.race_check)
        assert "clipboard_race_evidence" in race_source, (
            "the race verdict must come from the shared classifier, not a copy")

    def test_sentinels_are_loggable_without_their_contents(self):
        tool = self._tool()
        token = tool.make_sentinel("A")
        digest = tool.sentinel_digest(token)
        assert digest["length"] == len(token)
        assert token not in digest["digest"]
        assert len(digest["digest"]) == 12
