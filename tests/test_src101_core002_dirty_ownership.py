"""SRC-101 CORE-002 (audit/18): every persistence-backed mutation declares itself.

The optimized save path rescans a domain ONLY when that domain's generation is
dirty (``_save_data_to_db_locked``: ``full_scan = self._db_dirty or force``,
``scan_settings = full_scan or dirty_settings > saved_settings_gen or
ui_settings``).  ``_show_files_dock`` and ``save_silo_to_file`` mutated
persisted settings without marking the settings domain, so a NORMAL
(non-force, ``durable=True``) save reported success while ``files_dock_open``,
``files_dock_width`` and ``last_save_format`` stayed in memory only.  The
existing dock restart test passed because it called ``force=True``.

The repair is at the mutation sites: ``set_setting`` assigns and declares the
owning domain, and only a REAL change marks dirty.  ``force=True`` is NOT
restored to the hide path -- the optimization contract is preserved, and
``test_an_unmarked_mutation_is_still_excluded`` pins that.
"""

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])


def _settings_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        return dict(conn.execute("SELECT key, value FROM settings"))


def _settings_dirty(win):
    return win.state._dirty_settings > win.state._saved_settings_gen


def _clean_settings_generation(win):
    """Force a save, then assert the settings generation starts clean."""
    assert win.save_data_to_db(force=True) is True
    assert _settings_dirty(win) is False


@pytest.fixture()
def win(tmp_path, monkeypatch):
    db_path = str(tmp_path / "src101_core002_win.db")
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: db_path)
    import fastprompter.utils.portable_backup as backup_mod
    monkeypatch.setattr(backup_mod, "run_portable_backup",
                        lambda data, profile_id=1, **_kw: None)

    from fastprompter.main import FastPrompter
    monkeypatch.setattr(FastPrompter, "setup_single_instance_server",
                        lambda self: None)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys",
                        lambda self: None)
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys",
                        lambda self: None)
    w = FastPrompter()
    w.resize(1000, 600)
    for _ in range(5):
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
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
        w._unregister_custom_fonts()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()


class TestSetSettingDeclaresOnlyRealChanges:
    def test_a_no_op_assignment_does_not_churn_the_generation(self, win):
        _clean_settings_generation(win)
        current = win.data.get("files_dock_width", "220")
        assert win.set_setting("files_dock_width", str(current)) is False
        assert _settings_dirty(win) is False

    def test_a_real_change_marks_the_settings_domain(self, win):
        _clean_settings_generation(win)
        assert win.set_setting("files_dock_width", "777") is True
        assert win.data["files_dock_width"] == "777"
        assert _settings_dirty(win) is True


class TestProductionMutationPathsOwnTheirKeys:
    def test_opening_the_files_dock_marks_settings_dirty(self, win):
        win.set_setting("file_panel_docked", "True")
        _clean_settings_generation(win)

        win.open_file_container()
        _APP.processEvents()

        assert win.data["files_dock_open"] == "True"
        assert _settings_dirty(win) is True

    def test_closing_the_files_dock_marks_settings_dirty(self, win):
        win.set_setting("file_panel_docked", "True")
        win.open_file_container()
        _APP.processEvents()
        _clean_settings_generation(win)

        win.toggle_file_container()
        _APP.processEvents()

        assert win.data["files_dock_open"] == "False"
        assert _settings_dirty(win) is True

    def test_the_save_format_choice_marks_settings_dirty(
            self, win, monkeypatch, tmp_path):
        target = tmp_path / "note.md"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")))
        win.text_area.setPlainText("hello")
        win.data["last_save_format"] = "txt"
        _clean_settings_generation(win)

        win.save_silo_to_file()

        assert win.data["last_save_format"] == "md"
        assert target.is_file()
        assert _settings_dirty(win) is True


class TestTheNormalDurableSavePersistsThem:
    def test_the_open_files_dock_survives_a_durable_save(self, win):
        win.set_setting("file_panel_docked", "True")
        _clean_settings_generation(win)

        win.open_file_container()
        _APP.processEvents()
        assert win.save_data_to_db(durable=True) is True

        rows = _settings_rows(win.state.db_path)
        assert rows.get("files_dock_open") == "True"

    def test_a_changed_files_dock_width_survives_a_durable_save(self, win):
        win.set_setting("file_panel_docked", "True")
        win.open_file_container()
        _APP.processEvents()
        dock = win.files_dock
        idx = win.splitter.indexOf(dock)
        sizes = win.splitter.sizes()
        assert sizes[idx] >= 60, f"dock too narrow: {sizes}"

        # the user drags the splitter to a width that is NOT the default, so the
        # close has a real change to declare
        sizes[idx] = 300
        win.splitter.setSizes(sizes)
        _APP.processEvents()
        actual = str(win.splitter.sizes()[idx])
        assert win.data.get("files_dock_width") != actual
        _clean_settings_generation(win)

        win.toggle_file_container()          # close: writes width + open=False
        _APP.processEvents()
        assert win.data["files_dock_width"] == actual
        assert win.save_data_to_db(durable=True) is True

        rows = _settings_rows(win.state.db_path)
        assert rows.get("files_dock_open") == "False"
        assert rows.get("files_dock_width") == actual

    def test_the_save_format_survives_a_durable_save(
            self, win, monkeypatch, tmp_path):
        target = tmp_path / "note.md"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")))
        win.text_area.setPlainText("hello")
        win.data["last_save_format"] = "txt"
        _clean_settings_generation(win)

        win.save_silo_to_file()
        assert win.save_data_to_db(durable=True) is True

        assert _settings_rows(win.state.db_path).get("last_save_format") == "md"


class TestTheOptimizationContractIsPreserved:
    """Red control: the repair belongs at mutation ownership, not in the state
    layer.  An UNMARKED mutation must still be excluded from a settings-domain
    save -- otherwise the dirty-generation optimization this bug was hiding
    behind would have been silently reverted to an exhaustive scan.
    """

    def test_an_unmarked_mutation_is_still_excluded(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "src101_core002_state.db")
        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1: db_path)
        import fastprompter.utils.portable_backup as backup_mod
        monkeypatch.setattr(backup_mod, "run_portable_backup",
                            lambda data, profile_id=1, **_kw: None)

        state = state_mod.FastPrompterState()
        try:
            state.data["files_dock_width"] = "320"
            state.data["last_save_format"] = "txt"
            assert state.save_data_to_db("body", force=True) is True
            assert state.has_pending_changes is False

            # mutate WITHOUT declaring the owning domain
            state.data["files_dock_width"] = "777"
            state.data["last_save_format"] = "md"
            state.data["files_dock_open"] = "True"
            assert state.has_pending_changes is False

            assert state.save_data_to_db(
                "body", ui_settings={"last_tab_idx": "0"},
                durable=True) is True

            rows = _settings_rows(db_path)
            assert rows.get("files_dock_width") == "320"
            assert rows.get("last_save_format") == "txt"
            assert rows.get("files_dock_open") is None
        finally:
            state.conn = None
