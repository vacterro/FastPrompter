"""Second-wave audit regressions (P0/P1/P2 follow-ups).

These pin the exact behaviors the follow-up audit calls out: a stale preset
index must not create an undo step, and insert_silo_at must report a real slot
on success vs None when the workspace is full.
"""




def test_silo_preset_invalid_index_is_no_undo_step(win):
    """P2: a stale/out-of-range preset index must NOT create an undo step or
    change state. Only a real application may pollute Ctrl+Z ordering."""
    win.data["temp_presets"] = ["keep", "target"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.data_undo_stack = []
    win.data_redo_stack = []
    win._undo_kinds().clear()
    before = len(win.data_undo_stack)

    win.fill_silo_from_preset(-1, "stale")
    win.fill_silo_from_preset(99, "stale")
    assert len(win.data_undo_stack) == before, "no undo step for bad index"
    assert win.data["temp_presets"] == ["keep", "target"], "state unchanged"

    win.fill_silo_from_preset(1, "# TODO")
    assert win.data["temp_presets"][1] == "# TODO"
    assert len(win.data_undo_stack) == before + 1, "valid index = one undo step"


def test_insert_silo_at_return_contract(win):
    """P0: insert_silo_at returns the slot on success and None when the
    workspace is full, so callers can tell a real restore from a no-op."""
    win.data["temp_presets"] = ["keep", "target"]
    win.silo_docs[:] = [None, None]
    win._switch_to_slot(0, initial=True)
    assert win.insert_silo_at("fresh", pos=1) == 1
    assert win.data["temp_presets"][1] == "fresh"

    n = win.MAX_SILOS_PER_CATEGORY
    win.data["temp_presets"] = ["x"] * n
    win.silo_docs[:] = [None] * n
    assert win.insert_silo_at("extra") is None, "full workspace refuses"
    win.data["temp_presets"][5] = ""
    assert win.insert_silo_at("restored") == 5
    assert win.data["temp_presets"][5] == "restored"
