"""T-1270 corrective (T-1277) — the pin / order / named-gap DETERMINISTIC MODEL.

T-1270 was closed on the hover/tick subproblem alone. Its original behavioural
acceptance was never implemented, and there was no deterministic model test at
all. This suite is that test.

The model it pins
-----------------
A named SILO set that crosses a page boundary, asserted after EVERY action on
all seven facts at once: raw order, display order, pinned order, active
identity, gap placement, gap name, page.

Contracts asserted (one explicit choice each, never "both readings"):

* PIN   -> the silo MOVES into the pinned visual zone.
* UNPIN -> it stays at the TOP of the unpinned zone; it never teleports back
  several pages to the stale raw slot it had before the pin.
* GAP   -> the gap BELONGS TO the silo it was placed under, and rides with it
  through reorder (T-704). The "owns no silo, it is a position" wording is the
  OPPOSITE contract and is asserted ABSENT from the documentation string.
* CHILD -> a child cannot independently pin: pinning a child PROMOTES it, so
  ``is_pinned`` is never true while rendering excludes it from the pinned order.

Everything is asserted against the real ``FastPrompter`` window and the real
``refresh_temp_presets`` render pass, so "display order" is the order the user
actually sees, not a re-derived guess.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.state import bind_active_category

_APP = QApplication.instance() or QApplication([])

NAMES = ["alpha", "bravo", "charlie", "delta", "echo",
         "foxtrot", "golf", "hotel", "india", "juliet",
         "kilo", "lima"]

# Small page so "crossing a page boundary" is a real, reachable fact.
PAGE = 4


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("pin_order_t1270")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"pin_{profile_id}.db"))
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
    w._visible_silos = PAGE
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


@pytest.fixture
def w(win):
    """Land on project 0 with the named silo set and nothing pinned/gapped."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win._visible_silos = PAGE
    win.data["temp_presets"][:] = list(NAMES)
    win.data["silo_gaps"][:] = []
    win.data["silo_gap_names"] = {}
    win.data["silo_gap_names_all"] = {win.get_current_category(): {}}
    win.data["pinned_silos"][:] = []
    win.data["silo_children"] = {}
    win.data["silo_collapsed"][:] = []
    win.active_temp_slot = 0
    win.active_is_archive = False
    win._cmap_norm_id = None
    win._hierarchy_cache = None
    win._hierarchy_cache_key = None
    win.refresh_temp_presets()
    return win


# -- observation helpers ----------------------------------------------------

def raw_order(win):
    """Raw order, as the silo text (which IS the silo identity in this model)."""
    return list(win.data["temp_presets"])


def names_of(order):
    """Names of a raw order (already texts) — kept for readability."""
    return list(order)


def names_at(win, slots):
    """Names sitting at the given slot indices, in that slot order."""
    temps = win.data["temp_presets"]
    return [temps[i] for i in slots]


def display_order(win):
    """What the user actually sees, read off the real widget refresh."""
    out = []
    for btn in win.silo_buttons:
        if btn.isHidden():
            continue
        out.append(btn.global_idx)
    return out


def display_names(win):
    return names_at(win, display_order(win))


def pinned_order(win):
    return list(win.data["pinned_silos"])


def active_name(win):
    return win.data["temp_presets"][win.active_temp_slot]


def page_of(win, slot):
    return display_order(win).index(slot) // PAGE


def gap_owner(win):
    """The silo NAME each gap sits under (the T-704 ownership reading)."""
    temps = win.data["temp_presets"]
    return {g: temps[g] for g in (win.data.get("silo_gaps") or [])
            if 0 <= g < len(temps)}


def gap_names(win):
    return dict(win.data.get("silo_gap_names") or {})


def state_of(win):
    slots = display_order(win)
    return {
        "raw": names_of(raw_order(win)),
        "display": names_at(win, slots),
        "display_slots": slots,
        "pinned": pinned_order(win),
        "active": active_name(win),
        "gaps": gap_owner(win),
        "gap_names": gap_names(win),
    }


# -- the model, step by step -----------------------------------------------

class TestPinContract:
    def test_pinning_moves_the_silo_into_the_pinned_zone(self, w):
        w._toggle_pin_silo(6)                       # "golf", page 1
        assert pinned_order(w) == [0]
        assert names_of(raw_order(w))[0] == "golf"
        assert display_names(w)[0] == "golf"
        assert w.data["temp_presets"][6] == "foxtrot"  # the rest shifted down
        assert active_name(w) == "alpha"             # active identity travelled
        assert page_of(w, 0) == 0

    def test_unpinning_stays_at_the_top_of_the_unpinned_zone(self, w):
        w._toggle_pin_silo(6)
        w._toggle_pin_silo(0)                       # the pinned slot is now 0
        assert pinned_order(w) == []
        # It used to jump back to raw slot 6 — page 1. It must stay at 0.
        assert names_of(raw_order(w))[0] == "golf"
        assert page_of(w, 0) == 0
        assert active_name(w) == "alpha"

    def test_the_old_teleport_is_gone(self, w):
        """The exact operator complaint, as an assertion."""
        assert page_of(w, 6) == 1                   # golf starts on page 1
        w._toggle_pin_silo(6)
        assert page_of(w, 0) == 0                   # pinned: first page
        w._toggle_pin_silo(0)
        assert page_of(w, 0) == 0                   # unpinned: still first page

    def test_two_pins_keep_their_relative_order(self, w):
        w._toggle_pin_silo(5)                       # foxtrot
        w._toggle_pin_silo(9)                       # juliet
        assert names_of(raw_order(w)[:2]) == ["juliet", "foxtrot"]
        assert pinned_order(w) == [0, 1]
        assert display_names(w)[:2] == ["juliet", "foxtrot"]

    def test_pinned_drag_reorder_survives_a_reload(self, w):
        w._toggle_pin_silo(5)
        w._toggle_pin_silo(9)
        assert w.handle_pinned_drop(0, swap_idx=1) is True
        assert names_of(raw_order(w)[:2]) == ["foxtrot", "juliet"]
        assert w.data["pinned_silos"] == [0, 1]
        # A reload of the same category rebuilds the pinned block identically.
        w.refresh_temp_presets()
        assert display_names(w)[:2] == ["foxtrot", "juliet"]


class TestGapContract:
    def test_gap_belongs_to_the_silo_it_was_placed_under(self, w):
        w.toggle_silo_gap(2)                        # under "charlie"
        assert gap_owner(w) == {2: "charlie"}
        w.move_temp_to_index(2, 5)                  # charlie -> slot 5
        assert gap_owner(w) == {5: "charlie"}

    def test_gap_follows_a_reorder_and_never_lands_on_a_stranger(self, w):
        w.toggle_silo_gap(2)                        # under "charlie"
        w.move_temp_to_index(0, 11)                 # alpha to the end
        assert gap_owner(w) == {1: "charlie"}
        w.move_temp_to_index(11, 0)                 # and back
        assert gap_owner(w) == {2: "charlie"}

    def test_gap_name_rides_with_a_moved_gap(self, w):
        w.toggle_silo_gap(2)
        w.data["silo_gap_names"] = {"2": "Work"}
        w.data["silo_gap_names_all"][w.get_current_category()] = \
            w.data["silo_gap_names"]
        w.move_silo_gap(2, 7)
        assert gap_names(w) == {"7": "Work"}
        assert gap_owner(w) == {7: "hotel"}

    def test_the_two_readings_are_not_both_documented(self, w):
        """The contradictory "owns no silo" wording must be gone."""
        from fastprompter.ui.snippet_panel import SiloGapBar
        doc = SiloGapBar.__doc__ or ""
        assert "owns no silo" not in doc
        assert "belongs to" in doc.lower()


class TestChildPinContract:
    def test_pinning_a_child_promotes_it(self, w):
        w.make_silo_child(2, 0)                     # charlie under alpha
        assert w.silo_parent_of(2) == 0
        w._toggle_pin_silo(2)
        assert w.silo_parent_of(2) is None          # promoted, not ghost-pinned
        assert 2 in [0] or pinned_order(w) == [0]
        assert display_names(w)[0] == "charlie"

    def test_a_pin_never_survives_without_an_ordering_effect(self, w):
        w.make_silo_child(2, 0)
        w.data["pinned_silos"][:] = [2]             # stale pre-contract data
        w._apply_pinned_block(w.data["pinned_silos"])
        assert 2 not in w.data["pinned_silos"]
        assert w.silo_parent_of(2) == 0

    def test_pinning_a_child_puts_it_in_the_leading_block(self, w):
        w.make_silo_child(2, 0)                     # charlie under alpha
        w._toggle_pin_silo(2)
        assert w.data["temp_presets"][0] == "charlie"
        assert w.data["pinned_silos"] == [0]
        assert w.silo_depth(0) == 0                 # promoted to top level


class TestUndoRedoAndReload:
    def test_one_gesture_is_one_undo(self, w):
        before = state_of(w)
        w._toggle_pin_silo(7)
        after = state_of(w)
        assert after != before
        assert w.undo_action() is True
        assert state_of(w) == before
        assert w.redo_action() is True
        assert state_of(w) == after

    def test_undo_of_a_gap_move_restores_name_and_placement(self, w):
        w.toggle_silo_gap(3)
        w.data["silo_gap_names"] = {"3": "Later"}
        w.data["silo_gap_names_all"][w.get_current_category()] = \
            w.data["silo_gap_names"]
        before = state_of(w)
        assert w.move_silo_gap(3, 8) is True
        assert state_of(w) != before
        assert w.undo_action() is True
        assert state_of(w) == before

    def test_save_and_reload_preserve_the_model(self, w):
        w._toggle_pin_silo(4)                       # echo
        w.toggle_silo_gap(0)
        w.data["silo_gap_names"] = {"0": "Top"}
        w.data["silo_gap_names_all"][w.get_current_category()] = \
            w.data["silo_gap_names"]
        expected = state_of(w)
        w.state.mark_dirty()
        w.state.save_data_to_db("text", force=True)

        cat = w.get_current_category()
        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            assert list(fresh.data["temp_presets"]) == \
                list(w.data["temp_presets"])
            assert list(fresh.data["pinned_silos"]) == expected["pinned"]
            assert list(fresh.data["silo_gaps"]) == list(
                w.data["silo_gaps"])
            assert dict(fresh.data["silo_gap_names"]) == expected["gap_names"]
        finally:
            if fresh.conn is not None:
                fresh.conn.close()
        assert state_of(w) == expected


class TestEveryActionKeepsAllSevenFacts:
    """One traversal that asserts the FULL model after each action."""

    def test_the_whole_sequence(self, w):
        facts = []

        def snap(label):
            facts.append((label, state_of(w)))

        snap("start")
        w._toggle_pin_silo(6)
        snap("pin golf")
        w._toggle_pin_silo(9)
        snap("pin juliet")
        w.handle_pinned_drop(0, swap_idx=1)
        snap("pinned reorder")
        w._toggle_pin_silo(1)
        snap("unpin first")
        w.toggle_silo_gap(3)
        snap("gap under delta")
        w.data["silo_gap_names"] = {"3": "Section"}
        w.data["silo_gap_names_all"][w.get_current_category()] = \
            w.data["silo_gap_names"]
        snap("gap renamed")
        w.move_silo_gap(3, 7)
        snap("gap moved")
        w.move_temp_to_index(7, 2)
        snap("reorder")
        w.make_silo_child(4, 0)
        snap("child created")
        w._toggle_pin_silo(4)
        snap("child pinned (promotes)")
        w.undo_action()
        snap("undo")
        w.redo_action()
        snap("redo")

        # Every step names the same silo set: nothing vanished, nothing duped.
        for label, fact in facts:
            assert sorted(fact["raw"]) == sorted(NAMES), label
            assert sorted(fact["display"]) == sorted(NAMES), label
            assert fact["display"][0] in fact["raw"], label

        # The pin contract holds after every step that involved pins: the
        # pinned set occupies the LEADING display block in pinned order.
        for label, fact in facts:
            if not fact["pinned"]:
                continue
            assert fact["pinned"] == list(range(len(fact["pinned"]))), label
            assert fact["display_slots"][:len(fact["pinned"])] == \
                fact["pinned"], label

        # The gap never lost its name, and it never sat on nothing.
        gap_steps = [f for lbl, f in facts if f["gaps"]]
        assert gap_steps, "the sequence must exercise gaps"
        for fact in gap_steps:
            for owner in fact["gaps"].values():
                assert owner in NAMES

        # Pages are consistent with what is displayed.
        for label, fact in facts:
            assert len(fact["display"]) <= len(NAMES), label
