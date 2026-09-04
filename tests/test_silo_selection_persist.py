"""The Ctrl+click silo selection is latched, per-project, and persisted."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.state import bind_active_category

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    """One window for the module: building a FastPrompter costs ~20 s.

    Every test resets the selection through ``_reset`` below, so the shared
    window is not a state-leak hazard for what these tests assert on.
    """
    tmp_path = tmp_path_factory.mktemp("silo_selection")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"sel_{profile_id}.db"))
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
def _reset(win):
    """Land every test on project 0 with four silos and nothing latched."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha", "bravo", "charlie", "delta"]
    for category in list(win.data.get("silo_selected_all", {})):
        win.data["silo_selected_all"][category] = []
    win.data["silo_selected"] = win.data["silo_selected_all"].setdefault(
        win.get_current_category(), [])
    win._silo_selection_source = None
    win._silo_sel()
    return win


class TestSelectionIsAliasedAtStartup:
    def test_the_flat_key_is_bound_to_the_per_category_store(self, win):
        """A free list would send every latch nowhere (the aliasing trap)."""
        cat = win.get_current_category()
        assert win.data["silo_selected"] is win.data["silo_selected_all"][cat]

    def test_a_latch_lands_in_the_store_immediately(self, win):
        cat = win.get_current_category()
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        assert sorted(win._silo_sel()) == [1, 3]
        assert win.data["silo_selected_all"][cat] == [1, 3]

    def test_the_same_ctrl_click_releases_only_that_silo(self, win):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        win.toggle_silo_selection(1)
        assert sorted(win._silo_sel()) == [3]
        assert win.data["silo_selected"] == [3]

    def test_a_corrupt_stored_value_never_crashes_the_read(self, win):
        win.data["silo_selected"] = "not a list"
        assert win._silo_sel() == set()
        assert win.data["silo_selected"] == []
        win.data["silo_selected"] = [1, "x", -4, 2]
        win._silo_selection_source = None
        assert sorted(win._silo_sel()) == [1, 2]


class TestSelectionSurvivesNavigation:
    def test_each_project_keeps_its_own_latched_silos(self, win):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        first = win.get_current_category()

        win.cat_combo.setCurrentIndex(1)
        win.on_tab_changed(1)
        second = win.get_current_category()
        assert second != first
        assert win._silo_sel() == set()      # a fresh project starts empty
        win.toggle_silo_selection(0)
        assert sorted(win._silo_sel()) == [0]

        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        assert win.get_current_category() == first
        assert sorted(win._silo_sel()) == [1, 3]   # not cleared, not leaked
        assert win.data["silo_selected_all"][second] == [0]

    def test_switching_the_open_silo_keeps_the_latch(self, win):
        win.toggle_silo_selection(1)
        win._switch_to_slot(2)
        assert sorted(win._silo_sel()) == [1]

    def test_a_reorder_moves_the_latch_with_its_silo(self, win):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        win._remap_silo_indices(lambda i: 2 if i == 1 else i)
        assert sorted(win._silo_sel()) == [2, 3]


class TestSelectionSurvivesRestart:
    def test_a_latched_selection_reloads_from_the_database(self, win):
        """The real proof: a second state object reads it back off disk."""
        cat = win.get_current_category()
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        win.state.mark_dirty()
        win.state.save_data_to_db("text", force=True)

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            assert fresh.data["silo_selected"] == [1, 3]
        finally:
            if fresh.conn is not None:
                fresh.conn.close()


class TestUnselectMenuActions:
    def _menu_labels(self, win, idx, monkeypatch):
        captured = []
        from fastprompter import main as main_mod

        class _Menu(main_mod.QMenu):
            def addAction(self, *args, **kwargs):
                if args and isinstance(args[0], str):
                    captured.append(args[0])
                return super().addAction(*args, **kwargs)

            def exec(self, *args, **kwargs):
                return None

        monkeypatch.setattr(main_mod, "QMenu", _Menu)
        win.show_temp_menu(idx, win.rect().center())
        return captured

    def test_unselect_and_unselect_all_appear_on_a_selected_silo(
            self, win, monkeypatch):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        labels = self._menu_labels(win, 1, monkeypatch)
        assert any("Unselect All" in text for text in labels)
        assert any(text.strip().endswith("Unselect") for text in labels)

    def test_only_unselect_all_appears_on_an_unselected_silo(
            self, win, monkeypatch):
        win.toggle_silo_selection(1)
        labels = self._menu_labels(win, 2, monkeypatch)
        assert any("Unselect All" in text for text in labels)
        assert not any(text.strip().endswith("Unselect") for text in labels)

    def test_neither_appears_without_a_selection(self, win, monkeypatch):
        labels = self._menu_labels(win, 1, monkeypatch)
        assert not any("Unselect" in text for text in labels)

    def test_unselect_releases_one_and_persists(self, win):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        win.unselect_silo(1)
        assert sorted(win._silo_sel()) == [3]
        assert win.data["silo_selected"] == [3]

    def test_unselect_on_an_unselected_silo_changes_nothing(self, win):
        win.toggle_silo_selection(1)
        win.unselect_silo(2)
        assert sorted(win._silo_sel()) == [1]

    def test_unselect_all_clears_and_persists(self, win):
        win.toggle_silo_selection(1)
        win.toggle_silo_selection(3)
        win.clear_silo_selection()
        assert win._silo_sel() == set()
        assert win.data["silo_selected"] == []
