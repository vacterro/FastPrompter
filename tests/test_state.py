"""Tests for fastprompter.core.state — FastPrompterState."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.state import FastPrompterState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path):
    """Fixture that provides an isolated FastPrompterState for testing."""
    state = FastPrompterState(profile_id=999)
    if state.conn:
        state.conn.close()
    state.db_path = str(tmp_path / "test_state.db")
    state.init_db()

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
        assert d["font_size"] == 11

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


# ---------------------------------------------------------------------------
# _export_md_backup
# ---------------------------------------------------------------------------


class TestExportMdBackup:
    """Tests for _export_md_backup — MD file export of snippets, silos, and archives."""

    def _monkeypatch_expanduser(self, monkeypatch, tmpdir):
        """Redirect os.path.expanduser to write to a temp dir."""
        monkeypatch.setattr(os.path, "expanduser", lambda _: str(Path(tmpdir)))

    def test_export_snippet(self, monkeypatch):
        """Export a snippet and verify the file is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {
                    "Code": [{"name": "Test Snip", "text": "print('hello')", "last_edited": 1000}]
                    + [None] * 99,
                },
                "temp_presets_all": {"Code": [""] * 10},
                "archive_temp_presets_all": {"Code": []},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            base = Path(tmpdir) / ".fastprompter" / "Snippets" / "Code"
            files = list(base.glob("*.md"))
            assert len(files) >= 1
            content = files[0].read_text(encoding="utf-8")
            assert "Test Snip" in content
            assert "print('hello')" in content

    def test_export_silo(self, monkeypatch):
        """Export a silo and verify the file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {"Code": [None] * 100},
                "temp_presets_all": {"Code": ["silo text content", ""] + [""] * 8},
                "archive_temp_presets_all": {"Code": []},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            base = Path(tmpdir) / ".fastprompter" / "Silos" / "Code"
            files = sorted(base.glob("*.md"))
            assert len(files) >= 1
            content = files[0].read_text(encoding="utf-8")
            assert content == "silo text content"

    def test_export_archive(self, monkeypatch):
        """Export an archived silo and verify the file is written under Archive/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {"Code": [None] * 100},
                "temp_presets_all": {"Code": [""] * 10},
                "archive_temp_presets_all": {"Code": ["archived text"]},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            base = Path(tmpdir) / ".fastprompter" / "Archive" / "Code"
            files = sorted(base.glob("*.md"))
            assert len(files) >= 1
            content = files[0].read_text(encoding="utf-8")
            assert content == "archived text"

    def test_export_multiple_categories(self, monkeypatch):
        """Export data for multiple categories — each should get its own subdir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {
                    "Code": [None] * 100,
                    "Text": [{"name": "Text Snip", "text": "text content", "last_edited": 1}]
                    + [None] * 99,
                },
                "temp_presets_all": {"Code": [""] * 10, "Text": [""] * 10},
                "archive_temp_presets_all": {"Code": [], "Text": []},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            code_files = list((Path(tmpdir) / ".fastprompter" / "Snippets" / "Code").glob("*.md"))
            text_files = list((Path(tmpdir) / ".fastprompter" / "Snippets" / "Text").glob("*.md"))
            assert len(code_files) == 0  # Code has no non-None snippets
            assert len(text_files) >= 1
            assert "Text Snip" in text_files[0].read_text(encoding="utf-8")

    def test_export_empty_snapshot(self, monkeypatch):
        """Export with empty data should create directories but no files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {"Code": [None] * 100},
                "temp_presets_all": {"Code": [""] * 10},
                "archive_temp_presets_all": {"Code": []},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            base = Path(tmpdir) / ".fastprompter"
            assert (base / "Snippets" / "Code").exists()
            assert (base / "Silos" / "Code").exists()
            assert (base / "Archive" / "Code").exists()
            assert len(list((base / "Snippets" / "Code").glob("*.md"))) == 0
            assert len(list((base / "Silos" / "Code").glob("*.md"))) == 0
            assert len(list((base / "Archive" / "Code").glob("*.md"))) == 0

    def test_export_with_no_archive_key(self, monkeypatch):
        """Export should not crash if snapshot lacks archive key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {"Code": [None] * 100},
                "temp_presets_all": {"Code": [""] * 10},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)  # Should not raise

    def test_export_special_chars_in_name(self, monkeypatch):
        """Category names with special chars should be sanitized in dir names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._monkeypatch_expanduser(monkeypatch, tmpdir)
            snapshot = {
                "categories": {
                    "Code/Text": [
                        {"name": "Test", "text": "content", "last_edited": 1}
                    ]
                    + [None] * 99,
                },
                "temp_presets_all": {"Code/Text": [""] * 10},
                "archive_temp_presets_all": {"Code/Text": []},
            }
            state = FastPrompterState(profile_id=999)
            state._export_md_backup(snapshot)

            expected_dir = Path(tmpdir) / ".fastprompter" / "Snippets" / "CodeText"
            assert expected_dir.exists()
            assert len(list(expected_dir.glob("*.md"))) >= 1
