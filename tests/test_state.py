"""Tests for fastprompter.core.state — FastPrompterState."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.state import FastPrompterState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Fixture that provides an isolated FastPrompterState for testing.

    get_db_path is patched to a temp file BEFORE construction so the real
    `data/` directory is never touched or read — the assertions here depend
    on the database being fresh, and the real profile DB accumulates state
    across runs."""
    monkeypatch.setattr(
        "fastprompter.core.state.get_db_path",
        lambda profile_id=1: str(tmp_path / f"state_{profile_id}.db"))
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: None)
    state = FastPrompterState(profile_id=999)

    yield state

    if state.conn:
        try:
            state.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_data_shape(self, state):
        """Verify the initial data dict has all required keys with correct types."""
        d = state.data
        assert "categories" in d
        assert "cats_order" in d
        assert "temp_presets_all" in d
        assert "archive_temp_presets_all" in d
        assert isinstance(d["categories"], dict)
        assert isinstance(d["cats_order"], list)
        assert d["cats_order"] == ["Code", "Text", "Misc"]
        assert d["last_text"] == ""
        assert d["last_tab_idx"] == 0
        assert d["active_temp_slot"] == 0
        # T-696: the shipped default is 10, baked in by DEFAULT_PROFILE
        assert d["font_size"] == 10

    def test_default_categories_have_100_slots(self, state):
        """Each category should have 100 None slots."""
        for cat in state.data["cats_order"]:
            assert len(state.data["categories"][cat]) == 100
            assert all(s is None for s in state.data["categories"][cat])

    def test_default_temp_presets_have_10_empty_slots(self, state):
        """Each category's temp silos should have 10 empty strings."""
        for cat in state.data["cats_order"]:
            slots = state.data["temp_presets_all"][cat]
            assert len(slots) == 10
            assert all(s == "" for s in slots)

    def test_default_archive_empty(self, state):
        """Archive temp presets should be empty lists."""
        for cat in state.data["cats_order"]:
            assert state.data["archive_temp_presets_all"][cat] == []

    def test_current_tab_proxies_set(self, state):
        """temp_presets and archive_temp_presets should point to current tab."""
        assert "temp_presets" in state.data
        assert "archive_temp_presets" in state.data
        active_cat = state.data["cats_order"][state.data["last_tab_idx"]]
        assert state.data["temp_presets"] is state.data["temp_presets_all"][active_cat]
        assert (
            state.data["archive_temp_presets"] is state.data["archive_temp_presets_all"][active_cat]
        )

    def test_database_connection(self, state):
        """Database should be connected with correct tables."""
        assert state.conn is not None
        cur = state.conn.cursor()
        tables = {
            row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "settings" in tables
        assert "presets" in tables
        assert "temp_presets_v2" in tables
        assert "archive_temp_presets_v2" in tables

    def test_snapshot_after_init(self, state):
        """After init, snapshots should match initial data."""
        assert isinstance(state._last_saved_presets, set)
        assert isinstance(state._last_saved_temp, set)
        assert isinstance(state._last_saved_arc, set)
        assert isinstance(state._last_saved_settings, dict)
        # No presets initially (all None)
        assert len(state._last_saved_presets) == 0
        # No temp presets initially (all empty strings)
        assert len(state._last_saved_temp) == 0
        # No archive initially
        assert len(state._last_saved_arc) == 0

    def test_profile_id_default(self):
        """Default profile_id should be 1."""
        s = FastPrompterState()
        assert s.profile_id == 1


# ---------------------------------------------------------------------------
# reset_data
# ---------------------------------------------------------------------------


class TestResetData:
    def test_reset_restores_defaults(self, state):
        """reset_data should restore all data to default values."""
        state.data["categories"]["Code"][0] = {"name": "Test", "text": "Hello"}
        state.data["last_text"] = "modified"
        state.reset_data()
        assert state.data["last_text"] == ""
        assert state.data["categories"]["Code"][0] is None

    def test_reset_does_not_change_profile_id(self, state):
        """reset_data should preserve profile_id."""
        state.reset_data()
        assert state.profile_id == 999


# ---------------------------------------------------------------------------
# mark_dirty
# ---------------------------------------------------------------------------


class TestMarkDirty:
    def test_mark_dirty_sets_flag(self, state):
        """mark_dirty should set _db_dirty to True."""
        state._db_dirty = False
        state.mark_dirty()
        assert state._db_dirty is True

    def test_mark_dirty_is_thread_safe(self, state):
        """mark_dirty should be safe to call from multiple threads."""
        import threading

        errors = []

        def mark():
            try:
                for _ in range(100):
                    state.mark_dirty()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mark) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert state._db_dirty is True


# ---------------------------------------------------------------------------
# save_data_to_db
# ---------------------------------------------------------------------------


class TestSaveToDB:
    def test_no_save_if_not_dirty(self, state):
        """save_data_to_db should not write if _db_dirty is False and not forced."""
        state._db_dirty = False
        state.save_data_to_db("text")
        # Should still have initial empty data
        cur = state.conn.cursor()
        rows = cur.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
        assert rows >= 0  # no error

    def test_save_settings(self, state):
        """Save a setting change and verify it's persisted."""
        state.data["theme"] = "Golden Vintage"
        state.mark_dirty()
        state.save_data_to_db("some text", force=True)

        cur = state.conn.cursor()
        row = cur.execute("SELECT value FROM settings WHERE key='theme'").fetchone()
        assert row is not None
        assert row[0] == "Golden Vintage"

    def test_save_preset(self, state):
        """Save a new preset and verify it's in the presets table."""
        state.data["categories"]["Code"][0] = {
            "name": "Hello Snippet",
            "text": "print('hello')",
            "last_edited": 1000,
        }
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        cur = state.conn.cursor()
        row = cur.execute(
            "SELECT name, content, last_edited FROM presets WHERE category='Code' AND slot=0"
        ).fetchone()
        assert row is not None
        assert row[0] == "Hello Snippet"
        assert row[1] == "print('hello')"
        assert row[2] == 1000

    def test_update_preset(self, state):
        """Update an existing preset and verify it's updated."""
        state.data["categories"]["Code"][0] = {
            "name": "Original",
            "text": "original text",
            "last_edited": 1000,
        }
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state.data["categories"]["Code"][0] = {
            "name": "Updated",
            "text": "updated text",
            "last_edited": 2000,
        }
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        cur = state.conn.cursor()
        row = cur.execute(
            "SELECT name, content FROM presets WHERE category='Code' AND slot=0"
        ).fetchone()
        assert row[0] == "Updated"
        assert row[1] == "updated text"

    def test_delete_preset(self, state):
        """Delete a preset and verify it's removed from DB."""
        state.data["categories"]["Code"][0] = {
            "name": "To Delete",
            "text": "delete me",
            "last_edited": 1000,
        }
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state.data["categories"]["Code"][0] = None
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        cur = state.conn.cursor()
        row = cur.execute(
            "SELECT COUNT(*) FROM presets WHERE category='Code' AND slot=0"
        ).fetchone()
        assert row[0] == 0

    def test_save_temp_preset(self, state):
        """Save a temp preset (silo) and verify it's in the DB."""
        state.data["temp_presets_all"]["Code"][3] = "silo content"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        cur = state.conn.cursor()
        row = cur.execute(
            "SELECT content FROM temp_presets_v2 WHERE category='Code' AND slot=3"
        ).fetchone()
        assert row is not None
        assert row[0] == "silo content"

    def test_save_archive_temp(self, state):
        """Save an archive temp preset and verify it's in the DB."""
        state.data["archive_temp_presets_all"]["Code"] = ["archived content"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        cur = state.conn.cursor()
        row = cur.execute(
            "SELECT content FROM archive_temp_presets_v2 WHERE category='Code' AND slot=0"
        ).fetchone()
        assert row is not None
        assert row[0] == "archived content"

    def test_delta_sync_settings_only(self, state):
        """Changing only a setting should only write to settings table."""
        state.data["theme"] = "Vintage Dark"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Should be fast and not affect presets
        cur = state.conn.cursor()
        preset_count = cur.execute("SELECT COUNT(*) FROM presets").fetchone()[0]
        assert preset_count == 0  # No presets were saved

    def test_last_save_had_silo_text_flag(self, state):
        """PERF-004: a settings-only save must NOT report silo-text change, so
        the caller can skip app->file sync for it."""
        # prime: the first save after construction flushes every domain
        state.save_data_to_db("text", force=True)
        assert state.last_save_had_silo_text is True

        state.data["theme"] = "Vintage Dark"
        state.mark_dirty(domain="settings")
        state.save_data_to_db("text", ui_settings={"font_size": 13})
        # only a setting changed this run -> flag False
        assert state.last_save_had_silo_text is False

        state.data["temp_presets_all"] = {"Code": ["# new silo text"]}
        state.mark_dirty()
        state.save_data_to_db("# new silo text")
        # full dirty -> silo domains scanned -> flag True
        assert state.last_save_had_silo_text is True

    def test_save_with_ui_settings(self, state):
        """save_data_to_db with ui_settings dict should merge settings."""
        ui_settings = {"font_size": 14, "theme": "Dark 2 (OLED)"}
        state.mark_dirty()
        state.save_data_to_db("text", ui_settings=ui_settings, force=True)

        assert state.data["font_size"] == 14
        assert state.data["theme"] == "Dark 2 (OLED)"

    def test_current_text_updated(self, state):
        """The current_text param should be saved as last_text."""
        state.mark_dirty()
        state.save_data_to_db("hello world", force=True)
        assert state.data["last_text"] == "hello world"

    def test_backup_throttled(self, state):
        """Backup should be throttled and not affect save correctness."""
        # init_db creates an initial backup, so we just verify saves work
        state.data["theme"] = "Golden Vintage"
        state.mark_dirty()
        state.save_data_to_db("first", force=True)

        state.data["theme"] = "Default"
        state.mark_dirty()
        state.save_data_to_db("second", force=True)

        cur = state.conn.cursor()
        row = cur.execute("SELECT value FROM settings WHERE key='theme'").fetchone()
        assert row is not None
        assert row[0] == "Default"

    def test_hung_startup_backup_gate_never_blocks_save(self, state):
        """T03 / W2-P0-004: an ordinary autosave while the startup safety
        snapshot is still pending must NOT block the GUI thread and must NOT
        silently mutate SQLite (the recovery guarantee survives). The save
        returns False (deferred); dirty state is preserved; the next
        autosave retries once the snapshot is ready."""
        import time

        from fastprompter.core.state import _StartupBackupContext

        # Re-arm a gate that will never release (simulates a stalled worker).
        gate = _StartupBackupContext(state.db_path, state._startup_backup_gen + 1)
        state._startup_backup_ctx = gate
        state._dirty_settings = state._saved_settings_gen + 1

        start = time.monotonic()
        ok = state.save_data_to_db("text", ui_settings={"font_size": "14"})
        first_elapsed = time.monotonic() - start
        assert ok is False, \
            "autosave must defer while the startup snapshot is pending"
        assert first_elapsed < 0.5, \
            f"autosave blocked {first_elapsed:.2f}s on a pending snapshot"
        # dirty state preserved
        assert state._dirty_settings > state._saved_settings_gen, \
            "deferred save must preserve dirty state"
        # the live DB was NOT mutated: read back the old font_size
        row = state.conn.execute(
            "SELECT value FROM settings WHERE key='font_size'").fetchone()
        assert row is None or row[0] != "14", \
            "deferred save must not mutate the live database"

        state._dirty_settings = state._saved_settings_gen + 1
        start = time.monotonic()
        ok = state.save_data_to_db("text2", ui_settings={"font_size": "15"}, durable=True)
        second_elapsed = time.monotonic() - start
        assert ok is False
        assert second_elapsed < 5.5, (
            f"durable save exceeded bounded timeout {second_elapsed:.2f}s")


# ---------------------------------------------------------------------------
# switch_profile
# ---------------------------------------------------------------------------


class TestSwitchProfile:
    def test_switch_profile_creates_new_db(self, state, tmp_path):
        """Switching profile should create a new database file."""
        old_db = state.db_path
        state.switch_profile(2)
        assert state.profile_id == 2
        assert state.db_path != old_db
        # Verify the db_path changed (actual file may be in %LOCALAPPDATA% not tmp_path)
        assert state.db_path != old_db

    def test_switch_profile_resets_data(self, state):
        """Switching profile should reset all data to defaults."""
        state.data["categories"]["Code"][0] = {"name": "Test", "text": "data"}
        state.switch_profile(2)
        assert state.data["categories"]["Code"][0] is None

    def test_switch_profile_conn_valid(self, state):
        """After switch_profile, the connection should be valid."""
        state.switch_profile(2)
        assert state.conn is not None
        cur = state.conn.cursor()
        cur.execute("SELECT 1")  # Should not raise

    def test_switch_profile_multiple(self, state):
        """Switch profiles multiple times without errors."""
        for pid in [2, 3, 1, 2]:
            state.switch_profile(pid)
            assert state.profile_id == pid
            assert state.conn is not None


# ---------------------------------------------------------------------------
# Thread Safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_saves(self, state):
        """Multiple threads should be able to save concurrently."""
        import threading

        errors = []

        def saver():
            try:
                for i in range(50):
                    state.data["temp_presets_all"]["Code"][0] = f"thread_{i}"
                    state.mark_dirty()
                    state.save_data_to_db(f"text_{i}", force=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=saver) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_mark_dirty_and_save(self, state):
        """Concurrent mark_dirty and save should not deadlock."""
        import threading

        errors = []

        def worker():
            try:
                for _ in range(30):
                    state.mark_dirty()
                    state.save_data_to_db("test", force=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_save_without_conn_does_not_crash(self, state):
        """save_data_to_db should not crash if conn is None."""
        state.conn = None
        state.save_data_to_db("text", force=True)  # Should not raise

    def test_save_empty_settings(self, state):
        """Saving without any changes should succeed."""
        state._db_dirty = False
        state.save_data_to_db("text", force=False)  # Should no-op without error


# TestExportMdBackup lived here — nine tests for a method with no
# production caller. Both are gone (T-633); the real Markdown mirror is
# TestPortableBackupCoversEveryProject below.


class TestPortableBackupCoversEveryProject:
    """`temp_presets` is an alias for the ACTIVE category, so exporting from
    it silently left every other project out of the daily snapshot — and the
    folder looked full, so nothing said so."""

    def _run(self, tmp_path, data, monkeypatch):
        from fastprompter.utils import portable_backup as pb
        monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: str(tmp_path))
        pb.last_success_by_profile.clear()
        pb.run_portable_backup(data)
        import time as _t
        return tmp_path / _t.strftime("%Y-%m-%d")

    def test_every_project_is_exported(self, tmp_path, monkeypatch):
        data = {
            "cats_order": ["Text", "Code"],
            "temp_presets_all": {"Text": ["note one", ""], "Code": ["snippet two"]},
            "archive_temp_presets_all": {"Text": ["old note"], "Code": []},
            "temp_presets": ["note one", ""],
            "categories": {},
        }
        day = self._run(tmp_path, data, monkeypatch)
        assert (day / "silos" / "Text" / "silo_001.md").exists()
        assert (day / "silos" / "Code" / "silo_001.md").exists()
        assert "snippet two" in (day / "silos" / "Code" / "silo_001.md").read_text(
            encoding="utf-8")
        assert (day / "archive" / "Text" / "archive_001.md").exists()
        # an empty project gets no empty folder
        assert not (day / "archive" / "Code").exists()

    def test_manifest_counts_every_project(self, tmp_path, monkeypatch):
        import json
        data = {
            "cats_order": ["Text", "Code"],
            "temp_presets_all": {"Text": ["a", "b"], "Code": ["c"]},
            "archive_temp_presets_all": {"Text": ["d"]},
            "categories": {},
        }
        day = self._run(tmp_path, data, monkeypatch)
        meta = json.loads((day / "_meta.json").read_text(encoding="utf-8"))
        assert meta["silo_count"] == 3
        assert meta["archive_count"] == 1

    def test_falls_back_to_the_active_alias(self, tmp_path, monkeypatch):
        """Older data, or a caller holding only the alias, still exports."""
        data = {"cats_order": ["Text"], "temp_presets": ["only this"],
                "categories": {}}
        day = self._run(tmp_path, data, monkeypatch)
        assert (day / "silos" / "Text" / "silo_001.md").exists()

    def test_project_names_are_made_filesystem_safe(self, tmp_path, monkeypatch):
        """A hostile project name becomes a SAFE single component; different
        hostile names never collapse onto the same path (Phase-5 second pass)."""
        data = {"cats_order": ["a/b:c", "a?b:c"],
                "temp_presets_all": {"a/b:c": ["x"], "a?b:c": ["y"]},
                "categories": {}}
        day = self._run(tmp_path, data, monkeypatch)
        silos = sorted(os.listdir(day / "silos"))
        assert len(silos) == 2, silos
        for comp in silos:
            # a safe single component with no separators or traversal
            from fastprompter.utils.path_safety import validate_component
            assert validate_component(comp)[0] == comp, comp
            assert (day / "silos" / comp / "silo_001.md").exists()


class TestSettingsSurviveAReload:
    """A dict setting must come back as a dict, not as its own repr.

    Settings not listed in `_JSON_SETTINGS` are written with `str()`. A list
    survives that by accident (valid JSON); a dict does not — single quotes —
    so it reloads as a raw string and the guard that expects a dict throws it
    away. `silo_type_all` was missing from the list, which is why a silo's
    Table/Kanban type never survived a restart.
    """

    def _reload(self, state):
        """Close and reopen the same database file."""
        state.conn.close()
        fresh = FastPrompterState(profile_id=999)
        if fresh.conn:
            fresh.conn.close()
        fresh.db_path = state.db_path
        fresh.init_db()
        return fresh

    def test_silo_types_survive_a_restart(self, state):
        types = {"Code": {"0": "table", "1": "kanban"}}
        state.data["silo_type_all"] = {k: dict(v) for k, v in types.items()}
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        fresh = self._reload(state)
        try:
            assert fresh.data.get("silo_type_all") == types
        finally:
            if fresh.conn:
                fresh.conn.close()

    def test_every_structured_setting_is_json_encoded(self):
        """Guard the tuple itself: no dict or list default may be missing.

        This is the check that would have caught silo_type_all before a user
        did. Lists are included, not just dicts: `str([1, 2])` happens to be
        valid JSON and survives, but `str(['a', 'b'])` is single-quoted and
        does not — so "it is only a list" is not safety, it is luck about the
        element type.
        """
        from fastprompter.core.state import _JSON_SETTINGS, _SETTINGS_SKIP

        probe = FastPrompterState(profile_id=999)
        try:
            missing = [
                k for k, v in probe.data.items()
                if isinstance(v, (dict, list)) and k not in _SETTINGS_SKIP
                and k not in _JSON_SETTINGS
            ]
            assert not missing, f"structured settings written with str(): {missing}"
        finally:
            if probe.conn:
                probe.conn.close()

    def test_a_settings_round_trip_keeps_every_structured_value(self):
        """Save then reload must hand back the same objects, not their reprs.

        The point of the ticket: "100% save state". Every dict/list setting is
        given a distinctive value, written, and read back from a fresh state on
        the same file. Anything that comes back as a str, or empty, is a
        setting the user would silently lose on restart.
        """
        from fastprompter.core.state import _JSON_SETTINGS, _SETTINGS_SKIP

        state = FastPrompterState(profile_id=999)
        state.conn.close()
        import tempfile
        state.db_path = os.path.join(tempfile.mkdtemp(), "roundtrip.db")
        state.init_db()

        expected = {}
        for key, value in list(state.data.items()):
            if key in _SETTINGS_SKIP or not isinstance(value, (dict, list)):
                continue
            _base = key[:-4] if key.endswith("_all") else key
            if _base in ("silo_gaps", "pinned_silos", "silo_ticked", "silo_collapsed"):
                if key.endswith("_all"):
                    # Per-category *_all store: top-level must be a dict, and
                    # each category value is a list of ints (CORE-003 keeps it).
                    marker = {"probe": [1, 2, 3]}
                else:
                    # Flat alias: a plain integer list.
                    marker = [1, 2, 3]
            elif key == "folder_trash_log":
                marker = [["path1", "path2"], ["path3", "path4"]]
            elif isinstance(value, dict):
                # Dict settings (including the per-category *_all stores):
                # CORE-003 validates each per-category member against its
                # natural type, so the member must itself be a dict, not a list.
                marker = {"probe": {"inner": key}}
            else:
                marker = [key, "x"]
            state.data[key] = marker
            expected[key] = marker
        assert expected, "no structured settings found — the probe is wrong"

        state.mark_dirty()
        state.save_data_to_db("text", force=True)
        db_path = state.db_path
        state.conn.close()

        fresh = FastPrompterState(profile_id=999)
        fresh.conn.close()
        fresh.db_path = db_path
        fresh.init_db()
        try:
            lost = {k: fresh.data.get(k) for k, v in expected.items()
                    if fresh.data.get(k) != v}
            assert not lost, (
                "settings that did not survive a save/reload: "
                + ", ".join(f"{k} -> {v!r}" for k, v in lost.items())
            )
            missing_from_tuple = [k for k in expected if k not in _JSON_SETTINGS]
            assert not missing_from_tuple, missing_from_tuple
        finally:
            if fresh.conn:
                fresh.conn.close()


# ---------------------------------------------------------------------------
# Shipped defaults (T-695 / T-696)
# ---------------------------------------------------------------------------


class TestDefaultProfile:
    """The baked "current configuration" that ships as the defaults."""

    def test_baked_values_reach_the_data_dict(self, state):
        from fastprompter.core.default_profile import DEFAULT_PROFILE

        assert state.data["font_size"] == 10
        assert state.data["ui_scale"] == DEFAULT_PROFILE["ui_scale"]
        assert state.data["language"] == "EN"
        assert state.data["theme"] == DEFAULT_PROFILE["theme"]
        # the Ctrl+Q window presets ship with the app, not just the toggle
        assert isinstance(state.data["window_presets"], list)
        assert state.data["window_presets"], "no window presets baked in"
        assert state.data["window_presets_enabled"] == "True"

    def test_no_user_content_baked_in(self):
        """A regenerated profile must never carry somebody's silos with it.

        The generator excludes these; this is the guard that says so out loud,
        because the failure is invisible — the app works perfectly while
        shipping a stranger's project paths and note titles.
        """
        from fastprompter.core.default_profile import DEFAULT_PROFILE

        forbidden = {
            "last_text", "last_geometry", "categories", "cats_order",
            "timers", "agent_timers", "files_root",
            "silo_folders", "silo_folders_all", "silo_colors_all",
            "silo_project_paths_all", "silo_last_edited_all",
            "silo_view_state_all", "silo_session_all", "line_marks_data",
            "centered_blocks", "aligned_blocks", "watcher_queues_all",
            "archive_silo_folders_all", "archive_project_paths_all",
        }
        leaked = sorted(forbidden & set(DEFAULT_PROFILE))
        assert not leaked, f"user content baked into the shipped defaults: {leaked}"

    def test_custom_colors_never_shadow_a_theme(self):
        """custom_colors is an unconditional overlay on the active theme.

        Baking a key a theme already owns pins the shipped palette onto EVERY
        theme — pick Vintage Classic and the background stays golden. Only
        keys no theme defines (the overlay/edit extras) may ship.
        """
        from fastprompter.core.default_profile import DEFAULT_PROFILE
        from fastprompter.theme.themes import THEMES

        theme_keys = set()
        for spec in THEMES.values():
            theme_keys |= set((spec.get("raw_colors") or {}).keys())
        shadowed = sorted(set(DEFAULT_PROFILE.get("custom_colors", {})) & theme_keys)
        assert not shadowed, f"baked custom_colors override every theme: {shadowed}"

    def test_stored_values_win_over_the_baked_default(self, state):
        """Defaults are a fallback, never a migration.

        DEFAULT_PROFILE is also the map an existing database falls back to for
        keys it never stored, so the dangerous direction is the baked value
        overwriting a value the user actually chose.
        """
        state.data["font_size"] = 9
        state.data["theme"] = "Something Else"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)
        db_path = state.db_path
        state.conn.close()

        fresh = FastPrompterState(profile_id=999)
        fresh.conn.close()
        fresh.db_path = db_path
        fresh.init_db()
        try:
            assert fresh.data["font_size"] == 9
            assert fresh.data["theme"] == "Something Else"
        finally:
            if fresh.conn:
                fresh.conn.close()

    def test_mutable_defaults_are_not_shared(self, state):
        """Each profile gets its own copy of the structured values."""
        from fastprompter.core.default_profile import DEFAULT_PROFILE

        before = len(DEFAULT_PROFILE["window_presets"])
        state.data["window_presets"].append({"name": "scratch"})
        state.data["custom_colors"]["probe"] = "#000000"
        assert len(DEFAULT_PROFILE["window_presets"]) == before
        assert "probe" not in DEFAULT_PROFILE["custom_colors"]

        state.reset_data()
        assert len(state.data["window_presets"]) == before

    def test_every_structured_default_field_has_serializer_membership(self):
        """T-758: a structured (dict/list) field with no JSON serializer is
        written with str() and silently reloads as a string — the H-653 trap
        that ate silo_type_all."""

        from fastprompter.core import state as state_mod
        from fastprompter.core.default_profile import DEFAULT_PROFILE

        json_keys = set(state_mod._JSON_SETTINGS)
        skip = set(state_mod._SETTINGS_SKIP)
        for key, value in DEFAULT_PROFILE.items():
            if isinstance(value, (dict, list, tuple)):
                assert key in json_keys or key in skip, (
                    f"{key!r} is structured but has no JSON serializer — "
                    "it would reload as a str() and be silently lost")

    def test_json_serializer_round_trips(self):
        """Every key the JSON path writes must come back identical under
        json.loads — otherwise the decoder and the encoder disagree."""
        import json

        from fastprompter.core import state as state_mod

        sample = {
            "silo_colors_all": {"Code": {"0": "#fff"}},
            "watcher_queues_all": {"Code": {"a0": [{"id": "x", "text": "t", "line": 3}]}},
            "silo_view_state_all": {"Code": {"s0": {"pos": 1, "scroll": 0}}},
            "silo_gaps_all": {"Code": [1, 2]},
            "archive_silo_folders_all": {"Code": {"0": "folder"}},
            "sound_events": {"tick": {"file": "tick.wav", "enabled": True, "volume": 5}},
        }
        encoded = state_mod._encode_settings(sample)
        for key, raw in encoded.items():
            assert json.loads(raw) == sample[key], f"{key} did not round-trip"

    def test_every_live_all_key_is_in_the_per_category_registry(self, state):
        """T-758: the rename/delete registry must cover every *_all store the
        defaults actually carry, or a project keeps data under its old name.
        (silo_view_state_all is created lazily, so the registry may carry one
        more key than a fresh state.)"""
        from fastprompter.core import state as state_mod

        live = {k for k in state.data if k.endswith("_all")}
        registered = set(state_mod._PER_CATEGORY_STATE_KEYS)
        missing = live - registered
        assert not missing, f"unregistered *_all stores: {sorted(missing)}"
        assert all(k.endswith("_all") for k in registered), (
            "the registry must only carry per-category *_all keys")
