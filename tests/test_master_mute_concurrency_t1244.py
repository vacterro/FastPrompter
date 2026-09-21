"""T-1244 A1: the master-mute gate is atomic with playback admission.

The audit reproduced a deterministic race: a request read ``_muted == False``
outside the hub lock, paused, ``set_muted(True)`` completed (``_muted`` set +
``stop_all`` epoch advanced), the request then re-acquired the lock, read the
NEW epoch and started a fresh channel anyway -- final state ``muted=True,
channels=1``.  The repair makes the mute decision and the queue/channel
admission ONE critical section under ``_lock``, and adds a post-play re-check
so a channel can never register after the mute became active.

These tests force the exact interleavings deterministically with barriers and
events -- no probabilistic loop stress, no sleeps as timing assumptions.
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)


class _BlockingTransport(FakeMultiChannelTransport):
    """play() blocks until released, so a request is HELD between the mute
    gate and its physical admission (the channel is not registered yet)."""

    def __init__(self) -> None:
        super().__init__()
        self.inside_play = threading.Event()
        self.release_play = threading.Event()

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        self.inside_play.set()
        self.release_play.wait(timeout=10)
        return super().play(path, volume=volume, loop=loop,
                            on_complete=on_complete, token=token)


class _ReentrantMuteTransport(FakeMultiChannelTransport):
    """Mute engages INSIDE transport.play(), i.e. after the request passed the
    gate while unmuted but before the channel handle is registered.  The hub
    RLock is reentrant, so this is a legal same-thread interleaving."""

    def __init__(self, hub) -> None:
        super().__init__()
        self._hub = hub
        self._armed = True

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        if self._armed:
            self._armed = False          # one-shot: mute only the FIRST play
            self._hub.set_muted(True)
        return super().play(path, volume=volume, loop=loop,
                            on_complete=on_complete, token=token)


@pytest.fixture()
def rig():
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    return hub, transport


def _mk_rig():
    """Same as the ``rig`` fixture, callable inside helper functions."""
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    return hub, transport


class TestMuteGateAtomicWithAdmission:
    def test_request_held_mid_admission_cannot_survive_mute(self):
        """The exact audit interleaving, forced with events.

        A request passes the gate while unmuted and is held before final
        playback admission (blocked inside the transport, channel not yet
        registered).  Another thread calls set_muted(True).  Because the
        gate and the admission share one critical section, the mute CANNOT
        complete while the request is held: it completes only after the
        request's admission, and its stop_all then physically retires the
        channel.  After set_muted(True) returns, no application-owned audio
        remains.
        """
        tp = _BlockingTransport()
        hub = AudioHub(transport=tp)
        events: list[str] = []
        results: list = []

        def request() -> None:
            results.append(hub.play_result("a.wav", bus=Bus.UI))
            events.append("admission_done")

        def mute() -> None:
            events.append("mute_start")
            hub.set_muted(True)
            events.append("mute_done")

        thread_r = threading.Thread(target=request)
        thread_r.start()
        assert tp.inside_play.wait(timeout=5), "request never reached admission"
        thread_m = threading.Thread(target=mute)
        thread_m.start()

        # Release the request.  The mute thread is blocked on the hub lock
        # until the request's admission finishes -- deterministic, no sleeps.
        tp.release_play.set()
        thread_r.join(timeout=5)
        thread_m.join(timeout=5)
        assert not thread_r.is_alive() and not thread_m.is_alive()

        # set_muted(True) could not complete before the request admitted.
        assert events.index("mute_done") > events.index("admission_done")
        # The request physically started before mute obtained ownership...
        assert results[0].outcome in (Outcome.PLAYED, Outcome.MIXED)
        # ...and was immediately stopped by the mute's stop_all.
        assert hub.is_muted() is True
        assert hub.active_channel_count() == 0
        assert tp.channels == {}
        assert hub.queue_depth() == 0
        assert hub.active_sequences() == []

        # Fresh ordinary requests remain blocked until unmute.
        assert hub.play("fresh.wav", bus=Bus.UI) is Outcome.DROPPED_MUTED
        # The mute confirmation escape remains functional.
        assert hub.play_result(
            "cue.wav", event="audio_mute_on", allow_while_muted=True
        ).outcome is Outcome.PLAYED
        tp.finish_all()          # let the cue complete
        hub.set_muted(False)
        assert hub.play("after.wav", bus=Bus.UI) is Outcome.PLAYED

    def test_mute_engaging_mid_physical_start_never_registers_channel(self):
        """Mute engages between the gate and the channel registration.

        This is the sharpest form of the audit race: the request passed the
        gate while unmuted, and the mute completed before the transport
        returned its handle.  The channel must NOT physically start -- the
        post-play re-check refuses it and reports truthfully.
        """
        tp = _ReentrantMuteTransport(hub=None)  # bound below
        hub = AudioHub(transport=tp)
        tp._hub = hub

        result = hub.play_result("a.wav", bus=Bus.UI)
        assert result.outcome is Outcome.STOPPED          # not PLAYED/MIXED
        assert tp.channels == {}                          # zero physical channels
        assert hub.active_channel_count() == 0
        assert hub.is_muted() is True
        assert hub.queue_depth() == 0                     # no queued job remains

        # Provenance truthfully reflects the rejection/stoppage.
        entries = [e for e in hub.provenance()
                   if e.get("outcome") in (Outcome.STOPPED.value,
                                           Outcome.DROPPED_MUTED.value)]
        assert entries
        assert any(e["outcome"] == Outcome.STOPPED.value
                   and e.get("reason") == "muted_mid_admission"
                   for e in entries)

        # Fresh ordinary requests remain blocked until unmute.
        assert hub.play("b.wav", bus=Bus.UI) is Outcome.DROPPED_MUTED
        # Mute confirmation escape remains functional.
        assert hub.play_result(
            "cue.wav", event="audio_mute_off", allow_while_muted=True
        ).outcome is Outcome.PLAYED
        tp.finish_all()          # let the cue complete
        hub.set_muted(False)
        assert hub.play("c.wav", bus=Bus.UI) is Outcome.PLAYED

    def test_queued_request_held_before_drain_is_cleared_by_mute(self):
        """QUEUE mode: a job parked in the queue (not yet eligible) is held
        before its final admission; mute clears it and it never starts."""
        hub, tp = _mk_rig()
        hub.set_global_mode(PlaybackMode.QUEUE)
        # Occupy the UI bus so a second UI job stays in the queue.
        hub.play_result("busy.wav", bus=Bus.UI)
        queued = hub.play_result("held.wav", bus=Bus.UI)
        assert queued.outcome is Outcome.QUEUED
        assert hub.queue_depth(Bus.UI) == 1

        hub.set_muted(True)

        assert hub.queue_depth() == 0
        assert tp.channels == {}
        assert hub.active_channel_count() == 0
        # Draining after unmute cannot resurrect the stale job.
        hub.set_muted(False)
        tp.finish_all()
        assert hub.queue_depth() == 0
        assert hub.active_channel_count() == 0

    def test_inverse_race_request_started_before_mute_is_stopped(self):
        """A request that physically starts before mute obtains ownership is
        immediately stopped; after set_muted(True) returns, no application-
        owned normal audio may remain active."""
        hub, tp = _mk_rig()
        result = hub.play_result("a.wav", bus=Bus.UI)
        assert result.outcome is Outcome.PLAYED
        assert len(tp.channels) == 1
        hub.set_muted(True)
        assert hub.is_muted() is True
        assert tp.channels == {}
        assert hub.active_channel_count() == 0
        assert hub.queue_depth() == 0
