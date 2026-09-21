"""T-1244: the global master mute at the one audio authority.

The invariant: while ``audio_global_muted`` is ON, no application-owned
audio can physically start -- except the two mute confirmation cues -- and
whatever was already playing is physically retired with no possibility of
stale replay after unmute.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.audio_hub import (  # noqa: E402
    DROPPED_OUTCOMES,
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)


@pytest.fixture()
def rig():
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    return hub, transport


class TestAudioHubMuteGate:
    def test_default_is_unmuted(self, rig):
        hub, _tp = rig
        assert hub.is_muted() is False

    def test_muted_transient_is_dropped_muted(self, rig):
        hub, tp = rig
        hub.set_muted(True)
        result = hub.play_result("a.wav", bus=Bus.UI)
        assert result.outcome is Outcome.DROPPED_MUTED
        assert result.outcome in DROPPED_OUTCOMES
        assert not result
        assert tp.channels == {}          # no physical start
        assert hub.active_channel_count() == 0
        assert hub.queue_depth() == 0

    def test_muted_queue_mode_never_enqueues(self, rig):
        hub, tp = rig
        hub.set_global_mode(PlaybackMode.QUEUE)
        hub.set_muted(True)
        assert hub.play_result("a.wav").outcome is Outcome.DROPPED_MUTED
        assert hub.queue_depth() == 0
        assert tp.channels == {}

    def test_muted_start_channel_refused(self, rig):
        """Ambience cannot start (or restart on an evaluate tick)."""
        hub, tp = rig
        hub.set_muted(True)
        result = hub.start_channel("amb.wav", bus=Bus.AMBIENCE, loop=True)
        assert result.outcome is Outcome.DROPPED_MUTED
        assert result.channel == ""
        assert tp.channels == {}

    def test_muted_sequence_cancelled_not_started(self, rig):
        hub, tp = rig
        hub.set_muted(True)
        seq = hub.play_sequence(["one.wav", "two.wav"], bus=Bus.VOICE)
        assert seq.cancelled
        assert len(seq) == 2
        assert tp.channels == {}
        assert hub.active_sequences() == []

    def test_provenance_records_dropped_muted(self, rig):
        hub, _tp = rig
        hub.set_muted(True)
        hub.play_result("a.wav", event="timer", bus=Bus.ALERT)
        entries = [e for e in hub.provenance()
                   if e.get("outcome") == Outcome.DROPPED_MUTED.value]
        assert entries and entries[-1]["event"] == "timer"

    def test_diagnostics_expose_mute_state(self, rig):
        hub, _tp = rig
        hub.play("x.wav")   # one muted drop to count
        hub.set_muted(True)
        hub.play("a.wav")
        diag = hub.diagnostics()
        assert diag["muted"] is True
        assert diag["dropped_muted"] >= 1
        hub.set_muted(False)
        assert hub.diagnostics()["muted"] is False


class TestMuteStopsActiveAudio:
    def test_stop_all_reused_for_every_domain(self, rig):
        """Transient + queued + sequence + ambience all die at once."""
        hub, tp = rig
        stop_all_before = tp.stop_all_count
        hub.play("live.wav", bus=Bus.UI)
        hub.set_global_mode(PlaybackMode.QUEUE)
        queued = hub.play_result("queued.wav", bus=Bus.ALERT)
        hub.set_global_mode(PlaybackMode.MIX)
        seq = hub.play_sequence(["v1.wav", "v2.wav"], bus=Bus.VOICE)
        amb = hub.start_channel("amb.wav", bus=Bus.AMBIENCE, loop=True)
        assert queued.outcome is Outcome.QUEUED
        assert seq.started
        assert amb.channel

        hub.set_muted(True)

        assert hub.active_channel_count() == 0
        assert hub.queue_depth() == 0
        assert hub.active_sequences() == []
        assert tp.stop_all_count == stop_all_before + 1
        assert tp.channels == {}

    def test_no_stale_resume_after_unmute(self, rig):
        """Muted, unmuted: nothing queued or cancelled may come back."""
        hub, tp = rig
        hub.set_global_mode(PlaybackMode.QUEUE)
        hub.play_result("old1.wav", bus=Bus.ALERT)
        seq = hub.play_sequence(["v1.wav", "v2.wav"], bus=Bus.VOICE)
        hub.set_muted(True)
        hub.set_muted(False)

        assert hub.queue_depth() == 0
        assert seq.cancelled
        assert hub.active_sequences() == []
        # A completion callback from the dead job cannot resurrect anything.
        tp.finish_all()
        assert hub.active_channel_count() == 0

    def test_epoch_guards_late_completions(self, rig):
        hub, tp = rig
        result = hub.play_result("live.wav", bus=Bus.UI)
        handle = result.channel
        hub.set_muted(True)
        # The transport finished the channel just before/while stop_all ran:
        # its completion must not advance anything stale.
        tp.complete(handle)
        hub.set_muted(False)
        hub.play_result("new.wav", bus=Bus.UI)
        assert hub.active_channel_count() == 1


class TestMuteCueEscape:
    def test_allow_while_muted_plays(self, rig):
        hub, tp = rig
        hub.set_muted(True)
        result = hub.play_result("cue.wav", event="audio_mute_on",
                                 bus=Bus.UI, allow_while_muted=True)
        assert result.outcome in (Outcome.PLAYED, Outcome.MIXED)
        assert len(tp.channels) == 1

    def test_normal_requests_still_blocked_alongside_escape(self, rig):
        """The escape hatch is per-request, not a global hole."""
        hub, _tp = rig
        hub.set_muted(True)
        assert hub.play_result(
            "cue.wav", event="audio_mute_on",
            allow_while_muted=True).outcome is Outcome.PLAYED
        assert hub.play("alert.wav", bus=Bus.ALERT) is Outcome.DROPPED_MUTED
        assert hub.start_channel(
            "amb.wav", bus=Bus.AMBIENCE).outcome is Outcome.DROPPED_MUTED
        assert hub.play_sequence(["v.wav"], bus=Bus.VOICE).cancelled

    def test_unmute_restores_normal_service(self, rig):
        hub, _tp = rig
        hub.set_muted(True)
        hub.set_muted(False)
        assert hub.play("fresh.wav", bus=Bus.ALERT) is Outcome.PLAYED


class TestAmbienceWhileMuted:
    def test_evaluation_cannot_restart_layers(self, rig):
        """Mute -> evaluate -> still silent; unmute -> evaluate may play."""
        from fastprompter.core.ambience_engine import (
            REPEAT_LOOP,
            TRIGGER_ALWAYS,
            AmbienceEngine,
            AmbienceRule,
        )

        hub, tp = rig
        engine = AmbienceEngine(hub)  # resolver=None: refs are real paths

        rule = AmbienceRule(id="r1", name="rain", sound_ref="amb.wav",
                            enabled=True, trigger=TRIGGER_ALWAYS,
                            repeat=REPEAT_LOOP, volume=0.5)
        engine.set_rules([rule])
        engine.start_ambience()

        engine.evaluate()
        hub.set_muted(True)
        assert hub.active_channel_count() == 0   # playing -> mute = silence
        # The logical rule is untouched: evaluation ticks just cannot start
        # audio while muted.
        engine.evaluate()
        assert hub.active_channel_count() == 0
        assert rule.enabled
        # After unmute, the next ordinary evaluation restores the layer.
        hub.set_muted(False)
        engine.evaluate()
        assert engine.is_active("r1")
        assert hub.active_channel_count() == 1
