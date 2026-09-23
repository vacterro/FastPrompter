"""T-1236: identity and text lineage must agree, and a lapse must be visible.

T-1227 gave every silo a stable id. The id is persisted keyed by POSITION -
`silo_identity_v1(category, is_archive, slot)` - so it is stable exactly as
long as every structural route remembers to call `remap_silo_identities`. That
is the discipline the wave existed to stop depending on, and the startup
validator cannot catch a lapse: two ids cleanly SWAPPED leave no duplicate, no
orphan and no change in row count, so every presence and uniqueness check
passes while the mapping is wrong. The next save writes the wrong mapping down
as authoritative, and persistent Ctrl+Z then restores one silo's history into
another - the recovery feature becoming the corruption, at the exact moment the
user reaches for it because they have already lost something.

`validate_silo_lineage()` is the check that does not trust the remap: a silo's
newest committed `after_hash` must be the hash of the text now sitting in the
slot its id maps to.

The last test here is the red control. It skips a real `remap_silo_identities`
call the way a forgetful new structural route would, and asserts the mismatch
is reported. Without it, everything above is decoration that passes whether or
not the check works.
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import fastprompter.core.state as state_mod


def _sha(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / "lineage.db"))
    import fastprompter.utils.portable_backup as backup_mod
    monkeypatch.setattr(backup_mod, "run_portable_backup",
                        lambda data, profile_id=1, **_kw: None)
    state = state_mod.FastPrompterState(profile_id=1)
    yield state
    if state.conn is not None:
        state.conn.close()


def _seed(state, texts):
    """Put texts in the first slots of the first category and commit them."""
    cat = state.data["cats_order"][0]
    state_mod.bind_active_category(state.data, cat)
    slots = state.data["temp_presets_all"][cat]
    for i, text in enumerate(texts):
        slots[i] = text
    state.save_data_to_db("", force=True)
    return cat


def _record(state, sid, before, after):
    state.record_silo_text_history(sid, before, after, "test")
    state.save_data_to_db("", force=True)


def test_a_consistent_tree_reports_nothing(st):
    cat = _seed(st, ["alpha", "bravo", "charlie"])
    sid = st.silo_id_for(cat, False, 1)
    _record(st, sid, "", "bravo")
    assert st.validate_silo_lineage() == []


def test_a_silo_with_no_history_is_not_a_mismatch(st):
    _seed(st, ["alpha", "bravo"])
    assert st.validate_silo_lineage() == []


def test_a_dirty_slot_is_exempt(st):
    """Typing since the last commit is the normal reason for a difference."""
    cat = _seed(st, ["alpha", "bravo"])
    sid = st.silo_id_for(cat, False, 0)
    _record(st, sid, "", "alpha")

    st.data["temp_presets_all"][cat][0] = "alpha, still being typed"
    assert st.validate_silo_lineage() != []
    assert st.validate_silo_lineage(dirty_slots=[(cat, False, 0)]) == []


def test_a_swapped_identity_pair_is_reported(st):
    """The case no presence or uniqueness check can see."""
    cat = _seed(st, ["alpha", "bravo", "charlie"])
    sid_a = st.silo_id_for(cat, False, 0)
    sid_b = st.silo_id_for(cat, False, 1)
    _record(st, sid_a, "", "alpha")
    _record(st, sid_b, "", "bravo")
    assert st.validate_silo_lineage() == []

    # Exchange the two ids without touching the text - no duplicate, no
    # orphan, identical row count.
    st.silo_identities[(cat, 0, 0)] = sid_b
    st.silo_identities[(cat, 0, 1)] = sid_a

    problems = {p["silo_id"]: p for p in st.validate_silo_lineage()}
    assert set(problems) == {sid_a, sid_b}
    assert problems[sid_a]["actual_hash"] == _sha("bravo")
    assert problems[sid_a]["expected_after_hash"] == _sha("alpha")


def test_a_deleted_silo_keeps_its_history_without_being_a_mismatch(st):
    cat = _seed(st, ["alpha", "bravo"])
    sid = st.silo_id_for(cat, False, 1)
    _record(st, sid, "", "bravo")
    del st.silo_identities[(cat, 0, 1)]
    assert st.validate_silo_lineage() == []


def test_the_report_names_where_the_disagreement_is(st):
    cat = _seed(st, ["alpha"])
    sid = st.silo_id_for(cat, False, 0)
    _record(st, sid, "", "alpha")
    st.data["temp_presets_all"][cat][0] = "something else entirely"

    problem, = st.validate_silo_lineage()
    assert problem["silo_id"] == sid
    assert problem["category"] == cat
    assert problem["is_archive"] is False
    assert problem["slot"] == 0
    assert problem["actual_length"] == len("something else entirely")


def test_it_reports_and_never_repairs(st):
    """Guessing which side moved would risk relabelling the user's data."""
    cat = _seed(st, ["alpha"])
    sid = st.silo_id_for(cat, False, 0)
    _record(st, sid, "", "alpha")
    st.data["temp_presets_all"][cat][0] = "drifted"

    before = dict(st.silo_identities)
    st.validate_silo_lineage()
    assert dict(st.silo_identities) == before
    assert st.data["temp_presets_all"][cat][0] == "drifted"


# --------------------------------------------------------------------------
# Red control
# --------------------------------------------------------------------------

def test_a_structural_route_that_forgets_the_remap_is_caught(st, monkeypatch):
    """Simulate the exact lapse the anchor's position-keying allows.

    A move that shifts the texts but skips `remap_silo_identities` is
    indistinguishable from a correct move by every check that looks only at
    presence, uniqueness or row counts. It must not be indistinguishable to
    this one.
    """
    cat = _seed(st, ["alpha", "bravo", "charlie"])
    ids = [st.silo_id_for(cat, False, i) for i in range(3)]
    for i, text in enumerate(["alpha", "bravo", "charlie"]):
        _record(st, ids[i], "", text)
    assert st.validate_silo_lineage() == []

    # Now the forgetful route: rotate the texts, leave the anchor alone.
    monkeypatch.setattr(st, "remap_silo_identities",
                        lambda *a, **k: None)
    slots = st.data["temp_presets_all"][cat]
    slots[0], slots[1], slots[2] = slots[2], slots[0], slots[1]
    st.remap_silo_identities(cat, False, {0: 1, 1: 2, 2: 0})  # the no-op
    st.save_data_to_db("", force=True)

    problems = st.validate_silo_lineage()
    assert len(problems) == 3, (
        "a structural move that skipped the identity remap went undetected; "
        "persistent undo would now restore one silo's history into another")
    assert {p["silo_id"] for p in problems} == set(ids)


# --------------------------------------------------------------------------
# The gate on the persistent-undo path
# --------------------------------------------------------------------------

class _FakeState:
    def __init__(self, problems):
        self._problems = problems
        self.calls = []

    def validate_silo_lineage(self, dirty_slots=()):
        self.calls.append(tuple(dirty_slots))
        return list(self._problems)


def _gate(problems, sid="sid-1", raises=False):
    """Call the real gate against a stand-in window."""
    from fastprompter.main import FastPrompter

    class _Boom:
        def validate_silo_lineage(self, dirty_slots=()):
            raise RuntimeError("database went away mid-check")

    stub = type("Stub", (), {})()
    stub.state = _Boom() if raises else _FakeState(problems)
    stub.active_temp_slot = 0
    stub.showing_archive = False
    stub.get_current_category = lambda: "Code"
    # CORE-003: the gate builds its dirty exemption through the window's
    # canonical owner helper now; the stand-in binds the real one.
    stub._active_silo_coords = lambda: FastPrompter._active_silo_coords(stub)
    return FastPrompter._silo_lineage_is_trustworthy(stub, sid), stub.state


def test_persistent_recovery_runs_when_lineage_is_clean():
    ok, state = _gate([])
    assert ok is True
    assert state.calls == [(("Code", False, 0),)],         "the active silo must be exempted as legitimately dirty"


def test_persistent_recovery_is_refused_for_a_mismatched_silo():
    ok, _ = _gate([{"silo_id": "sid-1", "category": "Code",
                    "is_archive": False, "slot": 3,
                    "expected_after_hash": "a" * 64, "actual_hash": "b" * 64}])
    assert ok is False


def test_another_silo_s_mismatch_does_not_block_this_one():
    ok, _ = _gate([{"silo_id": "someone-else", "category": "Code",
                    "is_archive": False, "slot": 3,
                    "expected_after_hash": "a" * 64, "actual_hash": "b" * 64}])
    assert ok is True


def test_a_check_that_raises_refuses_rather_than_guesses():
    """Fail closed: an unreadable check is not evidence that all is well."""
    ok, _ = _gate([], raises=True)
    assert ok is False


def test_a_state_without_the_check_does_not_break_older_paths():
    from fastprompter.main import FastPrompter
    stub = type("Stub", (), {})()
    stub.state = object()
    assert FastPrompter._silo_lineage_is_trustworthy(stub, "sid-1") is True
