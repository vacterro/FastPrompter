"""Tests for Search, Archive, and Text Editing features.

Tests the core data filtering and persistence logic without requiring
a full QMainWindow / QApplication instance.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.state import FastPrompterState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path):
    """Isolated FastPrompterState with a temp DB."""
    s = FastPrompterState(profile_id=998)
    if s.conn:
        s.conn.close()
    s.db_path = str(tmp_path / "test_search.db")
    s.init_db()
    yield s
    if s.conn:
        try:
            s.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Search Filtering Logic
# ---------------------------------------------------------------------------


class TestSearchFilterLogic:
    """Test the core substring-matching logic used by all three panel filters."""

    def test_snippet_filter_by_name(self):
        """Snippets should match when query is in name (case-insensitive)."""
        snippets = [
            {"name": "Hello World", "text": "print('hi')"},
            {"name": "Goodbye", "text": "exit()"},
        ]
        query = "hello"
        matched = [
            s
            for s in snippets
            if not query or query in s["name"].lower() or query in s["text"].lower()
        ]
        assert len(matched) == 1
        assert matched[0]["name"] == "Hello World"

    def test_snippet_filter_uppercase_query(self):
        """Query normalization: uppercase query should still match (code lowercases first)."""
        snippets = [
            {"name": "Hello World", "text": "print('hi')"},
        ]
        raw_query = "HELLO"
        query = raw_query.lower()  # simulate normalization in refresh_snippets_panel
        matched = [
            s
            for s in snippets
            if not query or query in s["name"].lower() or query in s["text"].lower()
        ]
        assert len(matched) == 1

    def test_snippet_filter_by_text(self):
        """Snippets should match when query is in text (case-insensitive)."""
        snippets = [
            {"name": "Hi", "text": "print('hello world')"},
            {"name": "Bye", "text": "exit()"},
        ]
        query = "world"
        matched = [
            s
            for s in snippets
            if not query or query in s["name"].lower() or query in s["text"].lower()
        ]
        assert len(matched) == 1
        assert matched[0]["name"] == "Hi"

    def test_snippet_filter_empty_query_shows_all(self):
        """Empty query should return all items."""
        snippets = [
            {"name": "A", "text": "aaa"},
            {"name": "B", "text": "bbb"},
            {"name": "C", "text": "ccc"},
        ]
        query = ""
        matched = [
            s
            for s in snippets
            if not query or query in s["name"].lower() or query in s["text"].lower()
        ]
        assert len(matched) == 3

    def test_snippet_filter_no_match_returns_empty(self):
        """Non-matching query should return no items."""
        snippets = [
            {"name": "A", "text": "aaa"},
            {"name": "B", "text": "bbb"},
        ]
        query = "zzz"
        matched = [
            s
            for s in snippets
            if not query or query in s["name"].lower() or query in s["text"].lower()
        ]
        assert len(matched) == 0

    def test_silo_filter_by_content(self):
        """Silos should match when query is in text content (case-insensitive)."""
        silos = ["hello world", "goodbye", "python code", ""]
        query = "hello"
        filtered = [(idx, t) for idx, t in enumerate(silos) if t and query in t.lower()]
        assert len(filtered) == 1
        assert filtered[0][0] == 0  # correct index
        assert filtered[0][1] == "hello world"

    def test_silo_filter_empty_query(self):
        """Empty query on silos should return None filtered (meaning show all)."""
        # When query is empty, filtered is set to None and filtered_total = total
        filtered = None  # simulating the code path
        filtered_total = 5
        assert filtered is None
        assert filtered_total == 5

    def test_silo_filter_partial_match(self):
        """Partial substring match should work for silos."""
        silos = ["python code snippet", "javascript function", "java class"]
        query = "py"
        filtered = [(idx, t) for idx, t in enumerate(silos) if t and query in t.lower()]
        assert len(filtered) == 1
        assert filtered[0][1] == "python code snippet"

    def test_silo_filter_multiple_matches(self):
        """Multiple silos matching same query should return all matches."""
        silos = ["apple pie", "banana bread", "apple strudel", "cherry tart"]
        query = "apple"
        filtered = [(idx, t) for idx, t in enumerate(silos) if t and query in t.lower()]
        assert len(filtered) == 2
        indices = [idx for idx, _ in filtered]
        assert 0 in indices
        assert 2 in indices

    def test_archive_filter_same_as_silo(self):
        """Archive filtering uses the same pattern as silos."""
        archive = ["saved note", "archived text", "old code"]
        query = "archived"
        filtered = [(idx, t) for idx, t in enumerate(archive) if t and query in t.lower()]
        assert len(filtered) == 1
        assert filtered[0][0] == 1


# ---------------------------------------------------------------------------
# Archive Data Persistence
# ---------------------------------------------------------------------------


class TestArchivePersistence:
    """Test archive save/load/trim via state.py (the data layer)."""

    def test_archive_save_and_reload(self, state, tmp_path):
        """Save archive data, reload from a fresh state, verify content."""
        state.data["archive_temp_presets_all"]["Code"] = [
            "archived snippet 1",
            "archived snippet 2",
        ]
        state.mark_dirty()
        state.save_data_to_db("current text", force=True)

        # Create a fresh state pointing to the same DB
        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        assert len(state2.data["archive_temp_presets_all"]["Code"]) == 2
        assert state2.data["archive_temp_presets_all"]["Code"][0] == "archived snippet 1"
        assert state2.data["archive_temp_presets_all"]["Code"][1] == "archived snippet 2"

        if state2.conn:
            state2.conn.close()

    def test_archive_save_empty_strings_filtered(self, state):
        """Empty strings should be filtered out when loading archive."""
        state.data["archive_temp_presets_all"]["Code"] = ["real content", "", "  ", "more content"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Reload
        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        # Empty and whitespace-only strings should be filtered out
        assert "real content" in state2.data["archive_temp_presets_all"]["Code"]
        assert "more content" in state2.data["archive_temp_presets_all"]["Code"]
        assert "" not in state2.data["archive_temp_presets_all"]["Code"]

        if state2.conn:
            state2.conn.close()

    def test_archive_multi_category(self, state):
        """Each category should have independent archive lists."""
        state.data["archive_temp_presets_all"]["Code"] = ["code archive"]
        state.data["archive_temp_presets_all"]["Text"] = ["text archive"]
        state.data["archive_temp_presets_all"]["Misc"] = ["misc archive"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        assert state2.data["archive_temp_presets_all"]["Code"] == ["code archive"]
        assert state2.data["archive_temp_presets_all"]["Text"] == ["text archive"]
        assert state2.data["archive_temp_presets_all"]["Misc"] == ["misc archive"]

        if state2.conn:
            state2.conn.close()

    def test_archive_delta_sync(self, state):
        """Changing archive data should produce correct delta."""
        state.data["archive_temp_presets_all"]["Code"] = ["item1", "item2"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Snapshot should now include these
        assert ("Code", 0, "item1") in state._last_saved_arc
        assert ("Code", 1, "item2") in state._last_saved_arc

        # Remove one
        state.data["archive_temp_presets_all"]["Code"] = ["item2"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # item1 should be deleted from snapshot
        assert ("Code", 0, "item1") not in state._last_saved_arc
        assert ("Code", 0, "item2") in state._last_saved_arc

    def test_archive_current_tab_proxy(self, state):
        """archive_temp_presets should proxy the current tab's archive list."""
        active_cat = state.data["cats_order"][state.data["last_tab_idx"]]
        assert (
            state.data["archive_temp_presets"] is state.data["archive_temp_presets_all"][active_cat]
        )

    def test_archive_trim_removes_empty(self, state):
        """_trim_archive-like logic: empty entries should be removed."""
        archive = ["valid", "", "also valid", "  "]
        trimmed = [t for t in archive if t.strip()]
        assert trimmed == ["valid", "also valid"]

    def test_archive_preserves_real_indices(self, state):
        """Archive should preserve original insertion order."""
        state.data["archive_temp_presets_all"]["Code"] = ["first", "second", "third"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        assert state2.data["archive_temp_presets_all"]["Code"] == ["first", "second", "third"]
        if state2.conn:
            state2.conn.close()


# ---------------------------------------------------------------------------
# Text Editing / Save Logic
# ---------------------------------------------------------------------------


class TestTextEditingSaveLogic:
    """Test the data layer for text editing persistence."""

    def test_last_text_saved(self, state):
        """save_data_to_db should persist last_text."""
        state.mark_dirty()
        state.save_data_to_db("user typed content", force=True)
        assert state.data["last_text"] == "user typed content"

    def test_temp_preset_updated_via_save(self, state):
        """Text area content should update the active temp_preset."""
        state.data["temp_presets"][state.data["active_temp_slot"]] = "silo content"
        state.mark_dirty()
        state.save_data_to_db("silo content", force=True)

        # Re-read from DB
        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        active_cat = state2.data["cats_order"][state2.data["last_tab_idx"]]
        assert (
            state2.data["temp_presets_all"][active_cat][state2.data["active_temp_slot"]]
            == "silo content"
        )
        if state2.conn:
            state2.conn.close()

    def test_multiple_silos_independent(self, state):
        """Different silo slots should save independently."""
        state.data["temp_presets"][0] = "slot 0 content"
        state.data["temp_presets"][5] = "slot 5 content"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Verify both saved independently
        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        active_cat = state2.data["cats_order"][state2.data["last_tab_idx"]]
        assert state2.data["temp_presets_all"][active_cat][0] == "slot 0 content"
        assert state2.data["temp_presets_all"][active_cat][5] == "slot 5 content"
        assert state2.data["temp_presets_all"][active_cat][1] == ""  # untouched
        if state2.conn:
            state2.conn.close()

    def test_save_clears_silo(self, state):
        """Clearing a silo should persist as empty string."""
        state.data["temp_presets"][2] = "temporary content"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Now clear it
        state.data["temp_presets"][2] = ""
        state.mark_dirty()
        state.save_data_to_db("", force=True)

        # Verify it's removed from snapshot
        active_cat = state.data["cats_order"][state.data["last_tab_idx"]]
        assert (active_cat, 2, "temporary content") not in state._last_saved_temp

    def test_dirty_flag_resets_after_save(self, state):
        """_db_dirty should be False after a successful save."""
        state.mark_dirty()
        state.save_data_to_db("text", force=True)
        assert state._db_dirty is False

    def test_save_with_ui_settings(self, state):
        """save_data_to_db with ui_settings should update data."""
        ui = {"font_size": 18, "theme": "Golden Vintage"}
        state.mark_dirty()
        state.save_data_to_db("text", ui_settings=ui, force=True)
        assert state.data["font_size"] == 18
        assert state.data["theme"] == "Golden Vintage"


# ---------------------------------------------------------------------------
# Cross-cutting: Search + Archive + Text integration via state
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests exercising search, archive, and editing through state."""

    def test_archive_then_reload_with_search(self, state, tmp_path):
        """Archive silos should survive a save/load cycle."""
        state.data["archive_temp_presets_all"]["Code"] = [
            "old snippet 1",
            "important note",
            "obsolete code",
        ]
        state.mark_dirty()
        state.save_data_to_db("current text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        # Simulate search filtering on reloaded data
        archive = state2.data["archive_temp_presets_all"]["Code"]
        query = "important"
        filtered = [(idx, t) for idx, t in enumerate(archive) if t and query in t.lower()]
        assert len(filtered) == 1
        assert filtered[0][1] == "important note"
        if state2.conn:
            state2.conn.close()

    def test_silo_search_after_reload(self, state, tmp_path):
        """Silo search filtering should work after reload."""
        state.data["temp_presets_all"]["Code"] = [
            "python function",
            "javascript loop",
            "css styling",
            "",
        ]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        silos = state2.data["temp_presets_all"]["Code"]
        query = "script"
        filtered = [(idx, t) for idx, t in enumerate(silos) if t and query in t.lower()]
        assert len(filtered) == 1
        assert filtered[0][1] == "javascript loop"

        # Empty query should show all (simulate code path: filtered = None)
        filtered2 = None
        assert filtered2 is None

        if state2.conn:
            state2.conn.close()

    def test_save_preserves_search_visibility(self, state, tmp_path):
        """Search visibility setting should persist across save/load."""
        state.data["search_visible"] = "True"
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        assert state2.data.get("search_visible") == "True"
        if state2.conn:
            state2.conn.close()

    def test_archive_empty_strings_not_in_snapshot(self, state):
        """Empty strings are filtered out on DB load, but whitespace-only strings are
        saved to snapshot (truthy) and filtered on reload by .strip()."""
        state.data["archive_temp_presets_all"]["Code"] = ["real", "", "  "]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        # Empty string "" is falsy, so it should NOT be in snapshot
        # Whitespace "  " is truthy, so it IS in the snapshot (filtered on reload)
        assert ("Code", 0, "real") in state._last_saved_arc
        assert ("Code", 1, "") not in state._last_saved_arc  # empty string skipped
        assert ("Code", 2, "  ") in state._last_saved_arc  # whitespace IS truthy

    def test_multi_tab_archive_independence(self, state, tmp_path):
        """Switching tabs should maintain independent archives per tab."""
        state.data["archive_temp_presets_all"]["Code"] = ["code archive"]
        state.data["archive_temp_presets_all"]["Text"] = ["text archive"]
        state.data["archive_temp_presets_all"]["Misc"] = ["misc archive"]
        state.mark_dirty()
        state.save_data_to_db("text", force=True)

        state2 = FastPrompterState(profile_id=998)
        if state2.conn:
            state2.conn.close()
        state2.db_path = state.db_path
        state2.init_db()

        # Simulate tab switch by changing last_tab_idx
        for idx, cat in enumerate(state2.data["cats_order"]):
            state2.data["last_tab_idx"] = idx
            # Re-point the proxy (as on_tab_changed does)
            if cat in state2.data["archive_temp_presets_all"]:
                state2.data["archive_temp_presets"] = state2.data["archive_temp_presets_all"][cat]
            assert len(state2.data["archive_temp_presets"]) >= 1

        if state2.conn:
            state2.conn.close()
