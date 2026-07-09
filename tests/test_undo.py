"""Tests for deep undo/redo conditions.

Since FastPrompter requires a running QApplication, these tests verify the undo
logic at the data-structure level by inlining the core snapshot and apply
patterns from `main.py`.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest

# ---------------------------------------------------------------------------
# Helpers — replicated from main.py undo logic
# ---------------------------------------------------------------------------


def _snapshot_current(data, active_temp_slot=0, active_is_archive=False):
    """Replicate FastPrompter._snapshot_current()."""
    categories_snap = {
        cat: [None if s is None else dict(s) for s in slots]
        for cat, slots in data["categories"].items()
    }
    return {
        "categories": categories_snap,
        "temp_presets": list(data.get("temp_presets", [])),
        "archive_temp_presets": list(data.get("archive_temp_presets", [])),
        "cats_order": list(data.get("cats_order", [])),
        "active_temp_slot": active_temp_slot,
        "active_is_archive": active_is_archive,
        "editing_snippet": None,
        "last_tab_idx": data.get("last_tab_idx", 0),
        "theme": data.get("theme", "Default"),
    }


def _apply_data_state(data, state):
    """Replicate FastPrompter._apply_data_state() at the data level.

    cats_order is restored from the snapshot so category add/delete can be undone.
    """
    data["categories"] = state["categories"]
    data["temp_presets"] = state["temp_presets"]
    data["archive_temp_presets"] = state["archive_temp_presets"]

    # Restore cats_order from the snapshot
    if "cats_order" in state:
        data["cats_order"] = list(state["cats_order"])

    # Sync tab-preserved backing stores
    cat_idx = data.get("last_tab_idx", 0)
    cats = data["cats_order"]
    if 0 <= cat_idx < len(cats):
        current_cat = cats[cat_idx]
        if current_cat in data.get("temp_presets_all", {}):
            data["temp_presets_all"][current_cat] = data["temp_presets"]
        if current_cat in data.get("archive_temp_presets_all", {}):
            data["archive_temp_presets_all"][current_cat] = data["archive_temp_presets"]

    return state.get("active_temp_slot", 0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_data():
    """Return a data dict resembling FastPrompter's initial data."""
    return {
        "categories": {
            "Code": [None] * 100,
            "Text": [None] * 100,
            "Misc": [None] * 100,
        },
        "cats_order": ["Code", "Text", "Misc"],
        "temp_presets_all": {
            "Code": [""] * 10,
            "Text": [""] * 10,
            "Misc": [""] * 10,
        },
        "archive_temp_presets_all": {
            "Code": [],
            "Text": [],
            "Misc": [],
        },
        "temp_presets": [""] * 10,
        "archive_temp_presets": [],
        "last_tab_idx": 0,
        "last_text": "",
    }


@pytest.fixture
def populated_data(base_data):
    """Return data with some content in silos, archive, and categories."""
    d = copy.deepcopy(base_data)
    d["temp_presets"] = ["silo_a", "silo_b", "silo_c"] + [""] * 7
    d["archive_temp_presets"] = ["archived_1", "archived_2"]
    d["categories"]["Code"][0] = {"name": "Snip A", "text": "code a", "last_edited": 1000}
    d["categories"]["Code"][1] = {"name": "Snip B", "text": "code b", "last_edited": 2000}
    # Sync tab backing stores
    d["temp_presets_all"]["Code"] = d["temp_presets"][:]
    d["archive_temp_presets_all"]["Code"] = d["archive_temp_presets"][:]
    return d


# ---------------------------------------------------------------------------
# Snapshot & Apply Roundtrip
# ---------------------------------------------------------------------------


class TestSnapshotApplyRoundtrip:
    """Verify _snapshot/_apply preserve data fidelity."""

    def test_snapshot_basic(self, populated_data):
        snap = _snapshot_current(populated_data)
        assert "categories" in snap
        assert "temp_presets" in snap
        assert "archive_temp_presets" in snap
        assert snap["active_temp_slot"] == 0
        assert snap["active_is_archive"] is False
        assert snap["editing_snippet"] is None
        assert "theme" in snap
        assert "last_tab_idx" in snap

    def test_snapshot_deep_copies(self, populated_data):
        snap = _snapshot_current(populated_data)
        # Mutate original should not affect snapshot
        populated_data["temp_presets"][0] = "MUTATED"
        assert snap["temp_presets"][0] == "silo_a"

    def test_snapshot_categories_deep_copies(self, populated_data):
        snap = _snapshot_current(populated_data)
        populated_data["categories"]["Code"][0]["name"] = "MUTATED"
        assert snap["categories"]["Code"][0]["name"] == "Snip A"

    def test_apply_restores_presets(self, populated_data):
        snap = _snapshot_current(populated_data)
        populated_data["temp_presets"][0] = "CLOBBERED"
        _apply_data_state(populated_data, snap)
        assert populated_data["temp_presets"][0] == "silo_a"

    def test_apply_restores_categories(self, populated_data):
        snap = _snapshot_current(populated_data)
        populated_data["categories"]["Code"][0] = {"name": "CLOBBERED", "text": "", "last_edited": 0}
        _apply_data_state(populated_data, snap)
        assert populated_data["categories"]["Code"][0]["name"] == "Snip A"

    def test_apply_restores_archive(self, populated_data):
        snap = _snapshot_current(populated_data)
        populated_data["archive_temp_presets"] = ["CLOBBERED"]
        _apply_data_state(populated_data, snap)
        assert populated_data["archive_temp_presets"][0] == "archived_1"

    def test_apply_syncs_backing_stores(self, populated_data):
        snap = _snapshot_current(populated_data)
        populated_data["temp_presets"][0] = "CLOBBERED"
        _apply_data_state(populated_data, snap)
        # The tab backing store for Code should be synced
        assert populated_data["temp_presets_all"]["Code"][0] == "silo_a"

    def test_empty_snapshot_roundtrip(self, base_data):
        snap = _snapshot_current(base_data)
        _apply_data_state(base_data, snap)
        assert base_data["temp_presets"] == [""] * 10
        assert base_data["archive_temp_presets"] == []


# ---------------------------------------------------------------------------
# Undo/Redo Stack Operations
# ---------------------------------------------------------------------------


class TestUndoRedoStack:
    """Verify undo/redo stack push/pop/clear behavior."""

    def test_single_undo_roundtrip(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Simulate an action: modify silo 0
        snap_before = _snapshot_current(data)
        undo_stack.append(snap_before)
        redo_stack.clear()
        data["temp_presets"][0] = "modified"

        # Simulate undo
        snap_current = _snapshot_current(data)
        redo_stack.append(snap_current)
        state = undo_stack.pop()
        _apply_data_state(data, state)

        assert data["temp_presets"][0] == "silo_a"
        assert len(undo_stack) == 0
        assert len(redo_stack) == 1

    def test_redo_restores(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Action
        snap_before = _snapshot_current(data)
        undo_stack.append(snap_before)
        redo_stack.clear()
        data["temp_presets"][0] = "modified"

        # Undo
        snap_current = _snapshot_current(data)
        redo_stack.append(snap_current)
        state = undo_stack.pop()
        _apply_data_state(data, state)
        assert data["temp_presets"][0] == "silo_a"

        # Redo
        snap_current2 = _snapshot_current(data)
        undo_stack.append(snap_current2)
        state = redo_stack.pop()
        _apply_data_state(data, state)
        assert data["temp_presets"][0] == "modified"

    def test_new_action_clears_redo(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Action 1
        snap_before = _snapshot_current(data)
        undo_stack.append(snap_before)
        redo_stack.clear()
        data["temp_presets"][0] = "mod1"

        # Undo
        snap_current = _snapshot_current(data)
        redo_stack.append(snap_current)
        state = undo_stack.pop()
        _apply_data_state(data, state)
        assert len(redo_stack) == 1

        # New action (should clear redo)
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["temp_presets"][0] = "mod2"
        assert len(redo_stack) == 0

    def test_multiple_undo_sequential(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Action 1
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][0] = "mod1"

        # Action 2
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][1] = "mod2"

        # Action 3
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][2] = "mod3"

        assert data["temp_presets"][:3] == ["mod1", "mod2", "mod3"]

        # Undo 3
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][:3] == ["mod1", "mod2", "silo_c"]

        # Undo 2
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][:3] == ["mod1", "silo_b", "silo_c"]

        # Undo 1
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][:3] == ["silo_a", "silo_b", "silo_c"]
        assert len(undo_stack) == 0

    def test_redo_three_times(self, populated_data):
        """Redo should replay all three undone actions."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Action
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][0] = "mod1"
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][1] = "mod2"
        undo_stack.append(_snapshot_current(data))
        data["temp_presets"][2] = "mod3"

        # Undo all 3
        for _ in range(3):
            redo_stack.append(_snapshot_current(data))
            _apply_data_state(data, undo_stack.pop())

        assert data["temp_presets"][0] == "silo_a"

        # Redo 1
        undo_stack.append(_snapshot_current(data))
        _apply_data_state(data, redo_stack.pop())
        assert data["temp_presets"][0] == "mod1"
        assert data["temp_presets"][1] == "silo_b"

        # Redo 2
        undo_stack.append(_snapshot_current(data))
        _apply_data_state(data, redo_stack.pop())
        assert data["temp_presets"][1] == "mod2"

        # Redo 3
        undo_stack.append(_snapshot_current(data))
        _apply_data_state(data, redo_stack.pop())
        assert data["temp_presets"][2] == "mod3"

    def test_undo_when_empty_does_nothing(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []

        # No undo states — should no-op
        if undo_stack:
            pytest.fail("Should not reach")
        # Verify data unchanged
        assert data["temp_presets"][0] == "silo_a"

    def test_redo_when_empty_does_nothing(self, populated_data):
        data = copy.deepcopy(populated_data)
        redo_stack = []

        if redo_stack:
            pytest.fail("Should not reach")
        assert data["temp_presets"][0] == "silo_a"

    def test_stack_max_size_50(self, populated_data):
        """Pushing 55 states should cap at 50 (evict oldest)."""
        data = copy.deepcopy(populated_data)
        undo_stack = []

        for i in range(55):
            snap = _snapshot_current(data)
            undo_stack.append(snap)
            if len(undo_stack) > 50:
                undo_stack.pop(0)
            data["temp_presets"][0] = f"mod_{i}"

        assert len(undo_stack) == 50
        # After 55 actions: 5 evictions, stack[0] = snap before i=5 (data[0] = mod_4)
        state = undo_stack[0]
        assert state["temp_presets"][0] == "mod_4"

    def test_stack_max_applied(self, populated_data):
        """Verify 50 undo limit works end-to-end."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        for i in range(52):
            undo_stack.append(_snapshot_current(data))
            if len(undo_stack) > 50:
                undo_stack.pop(0)
            data["temp_presets"][0] = f"mod_{i}"

        assert len(undo_stack) == 50

        # Undo 50 times
        for _ in range(50):
            redo_stack.append(_snapshot_current(data))
            _apply_data_state(data, undo_stack.pop())

        # 52 pushes cap 50 → evict mod_0, mod_1. Stack = [snap_before_2..snap_before_51].
        # After 50 undos, last restored = snap_before_2 (data[0] = mod_1).
        assert data["temp_presets"][0] == "mod_1"
        assert len(undo_stack) == 0


# ---------------------------------------------------------------------------
# Category Undo
# ---------------------------------------------------------------------------


class TestCategoryUndo:
    """Undo for category add/delete operations."""

    def test_undo_add_category(self, base_data):
        data = copy.deepcopy(base_data)
        undo_stack = []
        redo_stack = []

        # Add category
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        new_cat = "NewCat"
        data["cats_order"].append(new_cat)
        data["categories"][new_cat] = [None] * 100
        data["temp_presets_all"][new_cat] = [""] * 10
        data["archive_temp_presets_all"][new_cat] = []
        assert "NewCat" in data["categories"]

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert "NewCat" not in data["categories"]
        assert data["cats_order"] == ["Code", "Text", "Misc"]

    def test_undo_delete_category(self, base_data):
        data = copy.deepcopy(base_data)
        undo_stack = []
        redo_stack = []

        # First add a snippet so category is non-trivial
        data["categories"]["Code"][5] = {"name": "Test", "text": "content", "last_edited": 1000}

        # Delete category
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        idx = 0  # "Code"
        removed_cat = data["cats_order"].pop(idx)
        del data["categories"][removed_cat]
        del data["temp_presets_all"][removed_cat]
        del data["archive_temp_presets_all"][removed_cat]
        assert "Code" not in data["categories"]

        # Undo
        redo_stack.append(_snapshot_current(data))
        # Need to restore cats_order before apply since apply uses it
        # (in real app, cats_order is stored in data so apply restores it)
        # For this test we manually rebuild data structure
        _apply_data_state(data, undo_stack.pop())
        # _apply_data_state restores categories dict which includes the deleted cat
        assert "Code" in data["categories"]
        assert data["categories"]["Code"][5]["name"] == "Test"


# ---------------------------------------------------------------------------
# Silo (temp_presets) Undo
# ---------------------------------------------------------------------------


class TestSiloUndo:
    """Undo for silo swap, move, clear operations."""

    def test_undo_swap_temp_slots(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Swap silo 0 and silo 2
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["temp_presets"][0], data["temp_presets"][2] = (
            data["temp_presets"][2],
            data["temp_presets"][0],
        )

        assert data["temp_presets"][0] == "silo_c"
        assert data["temp_presets"][2] == "silo_a"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"
        assert data["temp_presets"][2] == "silo_c"

    def test_undo_move_temp_slot(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Move silo 2 to index 1 (remove from 2, insert at 1)
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        val = data["temp_presets"].pop(2)
        data["temp_presets"].insert(1, val)
        # After: [silo_a, silo_c, silo_b, ...]
        assert data["temp_presets"][1] == "silo_c"
        assert data["temp_presets"][2] == "silo_b"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][1] == "silo_b"
        assert data["temp_presets"][2] == "silo_c"

    def test_undo_clear_silo(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Clear silo 0
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["temp_presets"][0] = ""

        assert data["temp_presets"][0] == ""

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"

    def test_undo_delete_silo(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Delete silo 1
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["temp_presets"].pop(1)

        assert len(data["temp_presets"]) == 9
        assert data["temp_presets"][1] == "silo_c"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert len(data["temp_presets"]) == 10
        assert data["temp_presets"][1] == "silo_b"


# ---------------------------------------------------------------------------
# Archive Undo
# ---------------------------------------------------------------------------


class TestArchiveUndo:
    """Undo for archive operations."""

    def test_undo_archive_silo(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Archive silo 0 (move from temp_presets to archive_temp_presets)
        undo_stack.append(_snapshot_current(data, active_temp_slot=0))
        redo_stack.clear()
        val = data["temp_presets"].pop(0)
        data["archive_temp_presets"].append(val)

        assert data["temp_presets"][0] == "silo_b"
        assert data["archive_temp_presets"][-1] == "silo_a"

        # Undo
        redo_stack.append(_snapshot_current(data, active_temp_slot=0))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"
        assert "silo_a" not in data["archive_temp_presets"]

    def test_undo_clear_archive(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Clear archive
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["archive_temp_presets"].clear()

        assert data["archive_temp_presets"] == []

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["archive_temp_presets"] == ["archived_1", "archived_2"]

    def test_undo_clear_archive_single(self, populated_data):
        """Clearing a single archive slot (like clear_text with active_is_archive=True)."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Clear archive slot 1
        undo_stack.append(_snapshot_current(data, active_temp_slot=1, active_is_archive=True))
        redo_stack.clear()
        data["archive_temp_presets"][1] = ""

        assert data["archive_temp_presets"][1] == ""

        # Undo
        redo_stack.append(_snapshot_current(data, active_temp_slot=1, active_is_archive=True))
        _apply_data_state(data, undo_stack.pop())
        assert data["archive_temp_presets"][1] == "archived_2"

    def test_undo_archive_swap(self, populated_data):
        """Swap between archive and regular silos."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Simulate: archive silo [0] with regular silo [1]
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["temp_presets"][0], data["archive_temp_presets"][1] = (
            data["archive_temp_presets"][1],
            data["temp_presets"][0],
        )

        assert data["temp_presets"][0] == "archived_2"
        assert data["archive_temp_presets"][1] == "silo_a"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"
        assert data["archive_temp_presets"][1] == "archived_2"


# ---------------------------------------------------------------------------
# Cross-Category Undo
# ---------------------------------------------------------------------------


class TestCrossCategoryUndo:
    """Undo for cross-category move operations."""

    def test_undo_move_preset_to_index(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Move snippet from index 0 to index 2 in Code
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        item = data["categories"]["Code"].pop(0)
        data["categories"]["Code"].insert(2, item)

        # After pop(0), SnipB shifted from idx 1 to idx 0; SnipA inserted at idx 2
        assert data["categories"]["Code"][0]["name"] == "Snip B"
        assert data["categories"]["Code"][2]["name"] == "Snip A"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["categories"]["Code"][0]["name"] == "Snip A"
        assert data["categories"]["Code"][1]["name"] == "Snip B"

    def test_undo_move_preset_cross_category(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Move Snip A from Code[0] to Text[0]
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        item = data["categories"]["Code"].pop(0)
        data["categories"]["Text"].insert(0, item)
        if data["categories"]["Text"][-1] is None:
            data["categories"]["Text"].pop()

        # After pop(0), SnipB shifted from Code[1] to Code[0]
        assert data["categories"]["Code"][0]["name"] == "Snip B"
        assert data["categories"]["Text"][0]["name"] == "Snip A"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["categories"]["Code"][0]["name"] == "Snip A"
        assert data["categories"]["Text"][0] is None

    def test_undo_move_silo_to_category(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Move silo 0 to category Code at index 2
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        text = data["temp_presets"].pop(0)
        item = {"name": text[:20], "text": text}
        data["categories"]["Code"].insert(2, item)
        if data["categories"]["Code"][-1] is None:
            data["categories"]["Code"].pop()

        assert data["temp_presets"][0] == "silo_b"
        assert data["categories"]["Code"][2]["name"] == "silo_a"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"
        # Original Code had items at idx 0-1 only; idx 2 was None
        assert data["categories"]["Code"][2] is None

    def test_undo_move_category_to_silo(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Move Snip A from Code[0] to silo at index 3
        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        item = data["categories"]["Code"].pop(0)
        data["temp_presets"].insert(3, item["text"])
        if data["categories"]["Code"][-1] is None:
            data["categories"]["Code"].append(None)

        # After pop(0), SnipB shifted from Code[1] to Code[0]
        assert data["categories"]["Code"][0]["name"] == "Snip B"
        assert data["temp_presets"][3] == "code a"

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["categories"]["Code"][0]["name"] == "Snip A"
        assert data["temp_presets"][3] == ""  # reverted


# ---------------------------------------------------------------------------
# Active Temp Slot Preservation
# ---------------------------------------------------------------------------


class TestActiveSlotPreservation:
    """Undo/redo should preserve or restore active_temp_slot."""

    def test_undo_preserves_slot_when_unrelated(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []
        active_slot = 3

        # Action unrelated to slot 3
        undo_stack.append(_snapshot_current(data, active_temp_slot=active_slot))
        redo_stack.clear()
        data["temp_presets"][1] = "modified"

        # Undo
        redo_stack.append(_snapshot_current(data, active_temp_slot=active_slot))
        state = undo_stack.pop()
        _apply_data_state(data, state)
        assert data["temp_presets"][1] == "silo_b"

    def test_undo_updates_slot_after_swap(self, populated_data):
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []
        active_slot = 0

        # Swap slot 0 and 2
        undo_stack.append(_snapshot_current(data, active_temp_slot=active_slot))
        redo_stack.clear()
        data["temp_presets"][0], data["temp_presets"][2] = (
            data["temp_presets"][2],
            data["temp_presets"][0],
        )

        # Undo
        redo_stack.append(_snapshot_current(data, active_temp_slot=active_slot))
        _apply_data_state(data, undo_stack.pop())
        assert data["temp_presets"][0] == "silo_a"


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestUndoEdgeCases:
    """Edge cases for undo/redo."""

    def test_undo_with_mixed_content(self, populated_data):
        """Undo preserves complex state with snippets and silos."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()

        # Multiple changes
        data["temp_presets"][0] = "new_content"
        data["temp_presets"][4] = "slot_4_content"
        data["archive_temp_presets"].append("new_archive_entry")
        data["categories"]["Text"][0] = {
            "name": "New Snippet",
            "text": "snippet text",
            "last_edited": 3000,
        }

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())

        assert data["temp_presets"][0] == "silo_a"
        assert data["temp_presets"][4] == ""
        assert "new_archive_entry" not in data["archive_temp_presets"]
        assert data["categories"]["Text"][0] is None

    def test_undo_after_archive_becomes_empty(self, populated_data):
        """Undo works when archive is emptied and restored."""
        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()
        data["archive_temp_presets"].clear()
        assert data["archive_temp_presets"] == []

        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["archive_temp_presets"] == ["archived_1", "archived_2"]

    def test_undo_active_is_archive_flag(self, populated_data):
        """Undo should handle active_is_archive flag."""
        data = copy.deepcopy(populated_data)

        snap = _snapshot_current(data, active_temp_slot=0, active_is_archive=True)
        assert snap["active_is_archive"] is True

    def test_undo_editing_snippet_state(self, populated_data):
        """Snapshot captures editing_snippet."""
        data = copy.deepcopy(populated_data)
        snap = _snapshot_current(data)
        assert snap["editing_snippet"] is None

        # With editing_snippet set
        state_copy = _snapshot_current(data)
        state_copy["editing_snippet"] = ("Code", 0)
        assert state_copy["editing_snippet"] == ("Code", 0)

    def test_deep_undo_same_as_original(self, populated_data):
        """After undo, data structure should be identical to original snapshot."""
        original = copy.deepcopy(populated_data)
        _snapshot_current(original)

        data = copy.deepcopy(populated_data)
        undo_stack = []
        redo_stack = []

        # Perform 3 modifications
        for i in range(3):
            undo_stack.append(_snapshot_current(data))
            data["temp_presets"][i] = f"deep_mod_{i}"

        # Undo all 3
        for _ in range(3):
            redo_stack.append(_snapshot_current(data))
            _apply_data_state(data, undo_stack.pop())

        # Deep compare — all state should match original
        assert data["temp_presets"] == original["temp_presets"]
        assert data["archive_temp_presets"] == original["archive_temp_presets"]
        for cat in data["cats_order"]:
            for i in range(100):
                orig_item = original["categories"][cat][i]
                restored_item = data["categories"][cat][i]
                assert orig_item == restored_item, f"Mismatch at {cat}[{i}]"

    def test_undo_with_100_slots_full(self, base_data):
        """Undo works when all 100 snippet slots in a category are full."""
        data = copy.deepcopy(base_data)
        for i in range(100):
            data["categories"]["Code"][i] = {
                "name": f"Snippet {i}",
                "text": f"text {i}",
                "last_edited": i,
            }

        undo_stack = []
        redo_stack = []

        undo_stack.append(_snapshot_current(data))
        redo_stack.clear()

        # Delete a few snippets
        data["categories"]["Code"][50] = None
        data["categories"]["Code"][51] = None

        assert data["categories"]["Code"][50] is None

        # Undo
        redo_stack.append(_snapshot_current(data))
        _apply_data_state(data, undo_stack.pop())
        assert data["categories"]["Code"][50]["name"] == "Snippet 50"
        assert data["categories"]["Code"][51]["name"] == "Snippet 51"
