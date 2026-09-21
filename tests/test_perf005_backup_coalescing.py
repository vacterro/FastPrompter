"""PERF-005 (SRC-021 audit/11): portable-backup coalescing before capture.

``run_portable_backup()`` used to deep-copy the whole project on EVERY
superseding eligible save while a backup was in flight (audit measured 21
``capture_snapshot()`` calls for 21 generations), even though only the newest
pending generation survives.  The repaired contract: a burst costs ONE
immediate capture plus ONE deferred materialisation of the newest COMMITTED
generation, the worker still never receives live mutable data, a deferred
snapshot's content always belongs to the generation its ``_content_gen``
names, failures stay retryable, and profiles coalesce independently.

Corrective wave (T-1286): the first repair coalesced the capture but owned the
deferred generation with a LIVE ``data`` reference, so a save that mutated the
live dict without committing leaked into the snapshot labelled with an earlier
committed generation.  A deferred generation is now materialised from the
committed view the owner of committed truth registers for that exact
generation (``note_committed_view``); live memory is never a source.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.utils.portable_backup as pb  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    pb.set_backup_sink(None)
    pb.last_success_by_profile.clear()
    pb._backup_active.clear()
    pb._backup_newer_wanted.clear()
    pb._backup_pending_data.clear()
    pb._backup_pending_gen.clear()
    pb._committed_view_by_profile.clear()
    pb._last_exported_gen_by_profile.clear()
    pb._last_exported_day_by_profile.clear()
    yield
    pb.set_backup_sink(None)


def _data(mark: str) -> dict:
    """A live state whose EXPORTED content is distinguishable."""
    return {"categories": {"Alpha": [{"text": mark}]},
            "cats_order": ["Alpha"]}


def _view(mark: str) -> dict:
    """The committed view a real commit registers for one exported state."""
    return {"cats_order": ("Alpha",),
            "preset_rows": frozenset({("Alpha", 0, "", mark, 0)}),
            "temp_rows": frozenset(),
            "arc_rows": frozenset()}


def _commit(profile_id: int, content_gen: int, mark: str) -> None:
    pb.note_committed_view(profile_id, content_gen, **_view(mark))


def _counting_capture(monkeypatch):
    calls = {"n": 0}
    captured: list = []
    real = pb.capture_snapshot

    def counting(data, profile_id=1):
        calls["n"] += 1
        snap = real(data, profile_id=profile_id)
        captured.append(snap)
        return snap

    monkeypatch.setattr(pb, "capture_snapshot", counting)
    return calls, captured


def test_burst_of_superseding_saves_captures_once(monkeypatch):
    calls, captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    data = _data("gen1")
    _commit(1, 1, "gen1")
    pb.run_portable_backup(data, profile_id=1, content_gen=1)
    assert calls["n"] == 1 and len(received) == 1

    for gen in range(2, 22):        # 20 superseding saves, gen 21 is the newest
        data["categories"]["Alpha"][0]["text"] = f"gen{gen}"
        _commit(1, gen, f"gen{gen}")
        pb.run_portable_backup(data, profile_id=1, content_gen=gen)

    assert len(received) == 1, "coalescing must prevent dispatch storms"
    assert calls["n"] == 1, (
        "PERF-005: a superseding save records intent, not a snapshot")
    assert pb._backup_pending_gen.get(1) == 21

    pb.backup_finished(profile_id=1)

    assert len(received) == 2, "the newest pending state is dispatched once"
    assert calls["n"] == 2, "exactly ONE deferred capture, not 21"
    deferred = received[1]
    assert deferred["profile_id"] == 1
    assert deferred["_content_gen"] == 21, "generation 21 EXACTLY"
    assert deferred["categories"]["Alpha"][0]["text"] == "gen21"

    # The worker snapshot is immutable: later live mutation cannot change it.
    data["categories"]["Alpha"][0]["text"] = "MUTATED_LIVE"
    assert deferred["categories"]["Alpha"][0]["text"] == "gen21"
    assert captured[1] is deferred


def test_profiles_coalesce_independently(monkeypatch):
    calls, _captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    p1 = _data("p1-v1")
    p2 = _data("p2-v1")
    _commit(1, 1, "p1-v1")
    _commit(2, 1, "p2-v1")
    pb.run_portable_backup(p1, profile_id=1, content_gen=1)
    pb.run_portable_backup(p2, profile_id=2, content_gen=1)
    assert {snap["profile_id"] for snap in received} == {1, 2}

    p1["categories"]["Alpha"][0]["text"] = "p1-v2"
    p2["categories"]["Alpha"][0]["text"] = "p2-v2"
    _commit(1, 2, "p1-v2")
    _commit(2, 2, "p2-v2")
    pb.run_portable_backup(p1, profile_id=1, content_gen=2)
    pb.run_portable_backup(p2, profile_id=2, content_gen=2)
    assert len(received) == 2
    assert calls["n"] == 2, "neither profile deep-copied while active"

    pb.backup_finished(profile_id=1)
    assert received[-1]["profile_id"] == 1
    assert received[-1]["categories"]["Alpha"][0]["text"] == "p1-v2"
    assert received[-1]["_content_gen"] == 2

    pb.backup_finished(profile_id=2)
    assert received[-1]["profile_id"] == 2
    assert received[-1]["categories"]["Alpha"][0]["text"] == "p2-v2"
    assert received[-1]["_content_gen"] == 2
    assert calls["n"] == 4


def test_failed_redispatch_keeps_newest_retryable(monkeypatch):
    calls, captured = _counting_capture(monkeypatch)
    received: list = []

    def flaky_sink(snapshot):
        received.append(snapshot)
        if len(received) == 2:
            raise RuntimeError("sink gone")

    pb.set_backup_sink(flaky_sink)

    _commit(1, 1, "v1")
    pb.run_portable_backup(_data("v1"), profile_id=1, content_gen=1)
    _commit(1, 2, "v2")
    pb.run_portable_backup(_data("v2"), profile_id=1, content_gen=2)
    assert calls["n"] == 1, "coalesced save captured nothing"

    pb.backup_finished(profile_id=1)      # deferred capture + redispatch raises
    assert calls["n"] == 2

    assert 1 not in pb._backup_active
    assert 1 in pb._backup_newer_wanted, "newest must stay re-armed"
    assert 1 in pb._backup_pending_data, "newest snapshot must stay pending"
    assert pb._backup_pending_data[1] is captured[1]
    assert pb._backup_pending_data[1]["categories"]["Alpha"][0]["text"] == "v2"
    assert 1 not in pb.last_success_by_profile, (
        "an obsolete worker must not establish throttle")

    _commit(1, 3, "v3")
    pb.run_portable_backup(_data("v3"), profile_id=1, content_gen=3)
    assert calls["n"] == 3
    assert 1 not in pb._backup_newer_wanted
    assert 1 not in pb._backup_pending_data
    assert received[-1]["categories"]["Alpha"][0]["text"] == "v3"


def test_settings_only_save_with_unchanged_generation_captures_nothing(monkeypatch):
    calls, _captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)
    pb._mark_exported(1, 7)          # gen 7 was already exported today
    data = _data("stable")

    pb.run_portable_backup(data, profile_id=1, content_gen=7)
    assert calls["n"] == 0, "no capture for an already-exported generation"
    assert received == []

    data["some_setting"] = "churned"
    data["categories"]["Alpha"][0]["text"] = "stable"
    pb.run_portable_backup(data, profile_id=1, content_gen=7)
    assert calls["n"] == 0
    assert received == []

    data["categories"]["Alpha"][0]["text"] = "changed"
    _commit(1, 8, "changed")
    pb.run_portable_backup(data, profile_id=1, content_gen=8)
    assert calls["n"] == 1, "real content change re-arms the capture"
    assert len(received) == 1


# ---------------------------------------------------------------------------
# T-1286 corrective: committed-generation ownership
# ---------------------------------------------------------------------------

def test_case_a_uncommitted_future_mutation_never_leaks(monkeypatch):
    """gen1 active, gen2 committed/pending, live mutated WITHOUT committing:
    the deferred snapshot must carry gen2 exactly, never the live mutation."""
    _calls, captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    live = _data("gen1")
    _commit(1, 1, "gen1")
    pb.run_portable_backup(live, profile_id=1, content_gen=1)

    live["categories"]["Alpha"][0]["text"] = "gen2"
    _commit(1, 2, "gen2")
    pb.run_portable_backup(live, profile_id=1, content_gen=2)

    live["categories"]["Alpha"][0]["text"] = "UNCOMMITTED_GEN3"
    pb.backup_finished(profile_id=1)

    deferred = received[-1]
    assert deferred["_content_gen"] == 2
    assert deferred["categories"]["Alpha"][0]["text"] == "gen2"
    assert captured[-1] is deferred


def test_case_b_mutate_then_revert_before_next_save(monkeypatch):
    """A transient live change that reverts and never commits cannot alter
    the deferred generation it never belonged to."""
    _calls, _captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    live = _data("gen1")
    _commit(1, 1, "gen1")
    pb.run_portable_backup(live, profile_id=1, content_gen=1)

    _commit(1, 2, "gen2")
    pb.run_portable_backup(live, profile_id=1, content_gen=2)

    live["categories"]["Alpha"][0]["text"] = "transient"
    live["categories"]["Alpha"][0]["text"] = "gen2"
    pb.backup_finished(profile_id=1)

    assert received[-1]["_content_gen"] == 2
    assert received[-1]["categories"]["Alpha"][0]["text"] == "gen2"


def test_case_c_committed_gen3_supersedes_pending_gen2_once(monkeypatch):
    _calls, captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    live = _data("gen1")
    _commit(1, 1, "gen1")
    pb.run_portable_backup(live, profile_id=1, content_gen=1)

    live["categories"]["Alpha"][0]["text"] = "gen2"
    _commit(1, 2, "gen2")
    pb.run_portable_backup(live, profile_id=1, content_gen=2)

    live["categories"]["Alpha"][0]["text"] = "gen3"
    _commit(1, 3, "gen3")
    pb.run_portable_backup(live, profile_id=1, content_gen=3)

    pb.backup_finished(profile_id=1)
    assert len(received) == 2, "exactly one deferred dispatch"
    assert received[-1]["_content_gen"] == 3
    assert received[-1]["categories"]["Alpha"][0]["text"] == "gen3"
    assert captured[-1] is received[-1]


def test_case_e_profiles_never_alias_committed_views(monkeypatch):
    _calls, _captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    p1 = _data("p1-v1")
    p2 = _data("p2-v1")
    _commit(1, 1, "p1-v1")
    _commit(2, 1, "p2-v1")
    pb.run_portable_backup(p1, profile_id=1, content_gen=1)
    pb.run_portable_backup(p2, profile_id=2, content_gen=1)

    p1["categories"]["Alpha"][0]["text"] = "p1-v2"
    p2["categories"]["Alpha"][0]["text"] = "p2-v2"
    _commit(1, 2, "p1-v2")
    _commit(2, 2, "p2-v2")
    pb.run_portable_backup(p1, profile_id=1, content_gen=2)
    pb.run_portable_backup(p2, profile_id=2, content_gen=2)
    p1["categories"]["Alpha"][0]["text"] = "p1-UNCOMMITTED"
    p2["categories"]["Alpha"][0]["text"] = "p2-UNCOMMITTED"

    pb.backup_finished(profile_id=1)
    pb.backup_finished(profile_id=2)
    by_profile = {snap["profile_id"]: snap for snap in received[2:]}
    assert by_profile[1]["categories"]["Alpha"][0]["text"] == "p1-v2"
    assert by_profile[2]["categories"]["Alpha"][0]["text"] == "p2-v2"


def test_no_committed_view_never_fabricates_from_live_memory(monkeypatch):
    """A pending generation with no committed view stays undispatched: the
    materialiser refuses to read live memory instead of guessing."""
    calls, _captured = _counting_capture(monkeypatch)
    received: list = []
    pb.set_backup_sink(received.append)

    live = _data("gen1")
    _commit(1, 1, "gen1")
    pb.run_portable_backup(live, profile_id=1, content_gen=1)

    live["categories"]["Alpha"][0]["text"] = "gen2-unregistered"
    pb.run_portable_backup(live, profile_id=1, content_gen=2)   # intent only

    pb.backup_finished(profile_id=1)
    assert len(received) == 1, "no snapshot may be fabricated from live data"
    assert calls["n"] == 1
    assert 1 not in pb.last_success_by_profile, (
        "throttle must be cleared so the next eligible save re-dispatches")


def test_abandoned_inflight_is_retryable_after_shutdown():
    """A shutdown that drops the in-flight snapshot retires the coalescing
    markers: otherwise the active/newer intents can never be resolved (their
    completion will never arrive) and every future request for that profile
    is silently coalesced away forever."""
    received: list = []
    pb.set_backup_sink(received.append)

    _commit(1, 1, "gen1")
    pb.run_portable_backup(_data("gen1"), profile_id=1, content_gen=1)
    assert len(received) == 1

    _commit(1, 2, "gen2")
    pb.run_portable_backup(_data("gen2"), profile_id=1, content_gen=2)
    assert pb._backup_active == {1} and pb._backup_newer_wanted == {1}

    pb.abandon_inflight(1)
    assert pb._backup_active == set()
    assert pb._backup_newer_wanted == set()
    assert pb._backup_pending_data == {}
    assert pb._backup_pending_gen == {}

    _commit(1, 3, "gen3")
    pb.run_portable_backup(_data("gen3"), profile_id=1, content_gen=3)
    assert len(received) == 2, "the next eligible save must reach the sink"
    assert received[1]["categories"]["Alpha"][0]["text"] == "gen3"


def test_state_commit_owns_the_deferred_generation(tmp_path, monkeypatch):
    """Production wiring: the state's commit registers the committed view,
    and the deferred materialisation survives uncommitted live mutation."""
    import fastprompter.core.state as state_mod

    monkeypatch.setattr(
        state_mod, "get_db_path",
        lambda profile_id=1: str(tmp_path / f"t_{profile_id}.db"))

    received: list = []
    pb.set_backup_sink(received.append)
    st = state_mod.FastPrompterState(profile_id=1)
    try:
        st.data["categories"]["Alpha"] = [{"name": "", "text": "gen1"}]
        st.mark_dirty("snippets")
        assert st.save_data_to_db("gen1", force=True) is True
        gen1 = st._exported_content_gen
        assert len(received) == 1, "first save dispatches the immediate capture"

        st.data["categories"]["Alpha"][0]["text"] = "gen2"
        st.mark_dirty("snippets")
        assert st.save_data_to_db("gen2", force=True) is True
        gen2 = st._exported_content_gen
        assert gen2 > gen1
        assert len(received) == 1, "superseding save coalesces"

        st.data["categories"]["Alpha"][0]["text"] = "UNCOMMITTED_GEN3"
        pb.backup_finished(profile_id=1)

        deferred = received[-1]
        assert deferred["_content_gen"] == gen2
        assert deferred["categories"]["Alpha"][0]["text"] == "gen2"
    finally:
        if st.conn is not None:
            st.conn.close()
