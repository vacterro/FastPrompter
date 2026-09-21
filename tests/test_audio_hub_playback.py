"""T-1238-G: audio hub playback modes, buses, STOP ALL, queue bounds."""

from __future__ import annotations

import time

from fastprompter.core.audio_hub import (
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)


def make_hub(**kwargs) -> tuple[AudioHub, FakeMultiChannelTransport]:
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport, **kwargs)
    return hub, transport


# ---------------------------------------------------------------------------
# MIX / Overlay
# ---------------------------------------------------------------------------


class TestMixMode:
    def test_two_sounds_play_concurrently(self):
        hub, tp = make_hub()
        o1 = hub.play("a.wav", bus=Bus.UI, mode=PlaybackMode.MIX)
        o2 = hub.play("b.wav", bus=Bus.UI, mode=PlaybackMode.MIX)
        assert o1 is Outcome.PLAYED
        assert o2 in (Outcome.MIXED, Outcome.PLAYED)
        assert len(tp.channels) == 2
        # Both channels still exist concurrently.
        paths = {ch["path"] for ch in tp.channels.values()}
        assert paths == {"a.wav", "b.wav"}

    def test_global_mode_default_is_mix(self):
        hub, tp = make_hub()
        assert hub.global_mode is PlaybackMode.MIX
        hub.play("a.wav")
        hub.play("b.wav")
        assert len(tp.channels) == 2

    def test_channel_count_diagnostics(self):
        hub, tp = make_hub()
        hub.play("a.wav")
        hub.play("b.wav")
        assert hub.diagnostics()["active_channels"] == 2


# ---------------------------------------------------------------------------
# QUEUE / Stack
# ---------------------------------------------------------------------------


class TestQueueMode:
    def test_fifo_sequential_playback(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("b.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("c.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        # Only A is active; B and C are queued FIFO.
        assert [ch["path"] for ch in tp.channels.values()] == ["a.wav"]
        assert hub.queue_depth(Bus.VOICE) == 2
        tp.complete(next(iter(tp.channels)))
        time.sleep(0.01)
        assert [ch["path"] for ch in tp.channels.values()] == ["b.wav"]
        tp.complete(next(iter(tp.channels)))
        time.sleep(0.01)
        assert [ch["path"] for ch in tp.channels.values()] == ["c.wav"]

    def test_queue_only_advances_on_real_completion(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("b.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        # No completion: B must never start.
        assert hub.queue_depth(Bus.VOICE) == 1
        assert len(tp.channels) == 1

    def test_queue_is_per_bus(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("b.wav", bus=Bus.ALERT, mode=PlaybackMode.QUEUE)
        # Different buses queue independently; both start immediately.
        assert len(tp.channels) == 2


# ---------------------------------------------------------------------------
# REPLACE
# ---------------------------------------------------------------------------


class TestReplaceMode:
    def test_replace_stops_current_and_clears_queue(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.ALERT, mode=PlaybackMode.MIX)
        hub.play("b.wav", bus=Bus.ALERT, mode=PlaybackMode.QUEUE)
        assert len(tp.channels) == 1
        o = hub.play("c.wav", bus=Bus.ALERT, mode=PlaybackMode.REPLACE)
        assert o is Outcome.REPLACED
        paths = {ch["path"] for ch in tp.channels.values()}
        assert paths == {"c.wav"}
        assert hub.queue_depth(Bus.ALERT) == 0
        assert len(tp.stopped) >= 1

    def test_replace_reports_replaced_and_stops_old_handle(self):
        hub, tp = make_hub()
        hub.play("alert.wav", bus=Bus.ALERT, mode=PlaybackMode.MIX)
        old = next(iter(tp.channels))
        o = hub.play("new.wav", bus=Bus.ALERT, mode=PlaybackMode.REPLACE)
        assert o is Outcome.REPLACED
        assert old in tp.stopped

    def test_replace_does_not_touch_other_buses(self):
        hub, tp = make_hub()
        hub.play("alert.wav", bus=Bus.ALERT, mode=PlaybackMode.MIX)
        hub.play("click.wav", bus=Bus.UI, mode=PlaybackMode.MIX)
        hub.play("next.wav", bus=Bus.ALERT, mode=PlaybackMode.REPLACE)
        paths = {ch["path"] for ch in tp.channels.values()}
        # UI channel survives; alert replaced.
        assert "click.wav" in paths and "next.wav" in paths
        assert "alert.wav" not in paths


# ---------------------------------------------------------------------------
# STOP ALL
# ---------------------------------------------------------------------------


class TestStopAll:
    def test_stop_all_silences_channels_queues_sequences(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.UI, mode=PlaybackMode.MIX)
        hub.play("b.wav", bus=Bus.ALERT, mode=PlaybackMode.QUEUE)
        hub.play("c.wav", bus=Bus.ALERT, mode=PlaybackMode.QUEUE)
        seq = hub.play_sequence(["one.wav", "two.wav"], bus=Bus.VOICE,
                                mode=PlaybackMode.MIX)
        hub.stop_all()
        assert len(tp.channels) == 0
        assert tp.stop_all_count == 1
        assert all(depth == 0 for depth in
                   hub.diagnostics()["queue_depths"].values())
        assert seq is not None and seq.cancelled

    def test_stale_completion_cannot_resurrect_after_stop_all(self):
        hub, tp = make_hub()
        hub.play("a.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("b.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.stop_all()
        # The stale completion for A arrives after STOP ALL: B must NOT start.
        for handle in list(tp.channels):
            tp.complete(handle)
        assert len(tp.channels) == 0
        assert hub.queue_depth(Bus.VOICE) == 0

    def test_new_sounds_allowed_after_stop_all(self):
        hub, tp = make_hub()
        hub.play("a.wav")
        hub.stop_all()
        o = hub.play("b.wav")
        assert o is Outcome.PLAYED
        assert len(tp.channels) == 1

    def test_stop_all_does_not_disable_future_notifications(self):
        hub, _ = make_hub()
        hub.stop_all()
        # Future timer notification (ALERT bus) still plays.
        o = hub.play("timer.wav", bus=Bus.ALERT, mode=PlaybackMode.MIX)
        assert o is Outcome.PLAYED


# ---------------------------------------------------------------------------
# Bounded queues and channel limits
# ---------------------------------------------------------------------------


class TestBounds:
    def test_queue_rejects_newest_when_full(self):
        hub, _ = make_hub(max_queue=3)
        for i in range(4):
            o = hub.play(f"s{i}.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
            if i < 3:
                assert o is Outcome.QUEUED
        assert hub.play("s99.wav", bus=Bus.VOICE,
                        mode=PlaybackMode.QUEUE) is Outcome.DROPPED_QUEUE_FULL
        d = hub.diagnostics()
        assert d["dropped_queue_full"] == 1
        assert d["queue_depths"]["voice"] == 3

    def test_transport_refusal_is_truthful_stop(self):
        hub, tp = make_hub()
        assert hub.play("", bus=Bus.UI) is Outcome.STOPPED
        assert hub.active_channel_count() == 0

    def test_channel_limit_drops_newest_deterministically(self):
        hub, _ = make_hub(max_voices=2)
        assert hub.play("a.wav", priority=2) is Outcome.PLAYED
        assert hub.play("b.wav", priority=2) in (Outcome.PLAYED, Outcome.MIXED)
        # Equal priority: newest is rejected, not evicting an equal peer.
        assert hub.play("c.wav", priority=2) in (
            Outcome.DROPPED_CHANNEL_LIMIT, Outcome.MIXED)
        d = hub.diagnostics()
        assert d["dropped_channel_limit"] == 1
        assert d["active_channels"] == 2

    def test_channel_limit_evicts_lowest_priority(self):
        hub, tp = make_hub(max_voices=2)
        hub.play("amb.wav", bus=Bus.PROBLIP, priority=1)
        hub.play("ui.wav", bus=Bus.UI, priority=2)
        # ALERT (3) evicts the PROBLIP (1) channel.
        assert hub.play("al.wav", priority=3) in (
            Outcome.PLAYED, Outcome.MIXED)
        paths = {ch["path"] for ch in tp.channels.values()}
        assert "amb.wav" not in paths
        assert {"ui.wav", "al.wav"} == paths


# ---------------------------------------------------------------------------
# High-rate coalescing
# ---------------------------------------------------------------------------


class TestHighRateCoalescing:
    def test_typewriter_burst_coalesces(self):
        hub, tp = make_hub()
        outcomes = [hub.play("tick.wav", event="typewriter") for _ in range(50)]
        # Rapid burst: many coalesced, few (or one) actually played.
        assert outcomes.count(Outcome.COALESCED) >= 40
        assert len(tp.channels) <= 10

    def test_coalescing_never_fills_queues(self):
        hub, tp = make_hub()
        for _ in range(200):
            hub.play("tick.wav", event="typewriter", mode=PlaybackMode.QUEUE)
        d = hub.diagnostics()
        assert d["queue_depths"]["ui"] <= 5
        assert d["coalesced"] > 0

    def test_distinct_slow_events_do_not_coalesce(self):
        hub, tp = make_hub()
        hub.play("a.wav", event="typewriter")
        time.sleep(0.1)  # > COALESCE_WINDOW_S
        hub.play("a.wav", event="typewriter")
        assert len(tp.channels) == 2

    def test_non_high_rate_events_never_coalesce(self):
        hub, tp = make_hub()
        for _ in range(10):
            o = hub.play("alarm.wav", event="timer")
            assert o is not Outcome.COALESCED


# ---------------------------------------------------------------------------
# Voice sequences
# ---------------------------------------------------------------------------


class TestSequences:
    def test_sequence_is_one_logical_job_in_queue_mode(self):
        hub, tp = make_hub()
        other = hub.play_queue_placeholder if False else None  # noqa: F841
        seq = hub.play_sequence(
            ["thirty.wav", "minutes.wav", "remaining.wav"],
            bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        assert seq is not None
        # One logical job: fragments advance only on completion.
        active = [ch["path"] for ch in tp.channels.values()]
        assert active == ["thirty.wav"]
        tp.complete(next(iter(tp.channels)))
        active = [ch["path"] for ch in tp.channels.values()]
        assert active == ["minutes.wav"]
        tp.complete(next(iter(tp.channels)))
        active = [ch["path"] for ch in tp.channels.values()]
        assert active == ["remaining.wav"]

    def test_sequence_replace_cancels_previous_job(self):
        hub, tp = make_hub()
        hub.play_sequence(["a.wav", "b.wav"], bus=Bus.VOICE,
                          mode=PlaybackMode.REPLACE)
        hub.play_sequence(["c.wav", "d.wav"], bus=Bus.VOICE,
                          mode=PlaybackMode.REPLACE)
        active = {ch["path"] for ch in tp.channels.values()}
        # Old sequence must not continue after the new one replaces it.
        tp.complete(next(iter(tp.channels)))
        active = {ch["path"] for ch in tp.channels.values()}
        assert "b.wav" not in active

    def test_stop_all_interrupts_phrase_no_fragment_leak(self):
        hub, tp = make_hub()
        hub.play_sequence(["one.wav", "two.wav", "three.wav"],
                          bus=Bus.VOICE, mode=PlaybackMode.MIX)
        hub.stop_all()
        for handle in list(tp.channels):
            tp.complete(handle)
        # Nothing further may start after STOP ALL.
        assert len(tp.channels) == 0


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_provenance_records_request_metadata(self):
        hub, _ = make_hub()
        hub.play("click.wav", event="click", bus=Bus.UI,
                 mode=PlaybackMode.MIX)
        entries = hub.provenance()
        assert entries, "expected a provenance entry"
        e = entries[-1]
        assert e["event"] == "click"
        assert e["bus"] == "ui"
        assert e["mode"] == "mix"
        assert e["asset"] == "click.wav"
        assert e["outcome"] in ("PLAYED", "MIXED")
        assert e["request_id"].startswith("req")

    def test_provenance_outcomes_cover_drops(self):
        hub, _ = make_hub(max_queue=1)
        hub.play("a.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("b.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        hub.play("c.wav", bus=Bus.VOICE, mode=PlaybackMode.QUEUE)
        outcomes = [e["outcome"] for e in hub.provenance()]
        assert "DROPPED_QUEUE_FULL" in outcomes
