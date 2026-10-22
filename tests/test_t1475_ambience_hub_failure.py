"""T-1475: a hub refusal must never read as success to the ambience engine.

The engine retired a layer by popping it off ``_layers`` and clearing its
handle whether or not the transport actually stopped the channel, and it
accepted a fade or reconcile volume the transport silently refused. Nothing in
the log or the counts recorded either, so a layer could stay audible with the
engine, the store and the UI all reporting silence.

These tests inject a hub that fails and assert on the recorded failure, not on
the engine's own bookkeeping (the existing ``RecordingHub`` discipline).
"""

from __future__ import annotations

import logging

import test_ambience_engine as _shared

from fastprompter.core.ambience_engine import AmbienceEngine

RecordingHub = _shared.RecordingHub
_rule = _shared._rule
SUNDAY_10AM = _shared.SUNDAY_10AM


class FailingStopHub(RecordingHub):
    """Transport refuses every stop; every volume mutation still succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self.refused_stops = 0

    def stop_channel_handle(self, handle):
        self.refused_stops += 1
        # the transport raises: the channel stays audible, and the engine must
        # not read that as a clean stop
        raise OSError("transport refused the stop")


class FailingVolumeHub(RecordingHub):
    """Transport refuses every volume change; stops still succeed."""

    def __init__(self) -> None:
        super().__init__()
        self.refused_volumes = 0

    def set_channel_volume(self, handle, volume):
        self.refused_volumes += 1
        # the transport raises: the level is never applied
        raise OSError("transport refused the volume")


class TestHubStopFailure:
    def test_a_refused_stop_is_recorded_not_silent(self, caplog):
        hub = FailingStopHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="r1", fade_out_ms=0)])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["r1"]
        assert engine.fading_layers() == 0

        with caplog.at_level(logging.WARNING,
                             logger="fastprompter.core.ambience_engine"):
            engine.set_rules([_rule(id="r1", enabled=False)])

        assert hub.refused_stops == 1
        # the layer is retired by contract, so the channel is now untracked:
        # the count is the only durable evidence anything is still sounding.
        assert engine.failed_hub_calls()["stop"] == 1
        assert any("still be audible" in r.message
                   for r in caplog.records), "stop refusal was not logged"

    def test_refused_stop_leaves_no_layer_claiming_the_channel(self):
        """The layer is off _layers either way; the count says why."""
        hub = FailingStopHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="r1", fade_out_ms=0)])
        engine.evaluate(now=SUNDAY_10AM, monotonic=0.0)
        engine.set_rules([_rule(id="r1", enabled=False)])
        assert hub.refused_stops == 1
        assert engine.failed_hub_calls()["stop"] == 1


class TestHubVolumeFailure:
    def test_a_refused_volume_is_recorded_not_silent(self, caplog):
        hub = FailingVolumeHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="r1", volume=0.2)])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["r1"]

        with caplog.at_level(logging.WARNING,
                             logger="fastprompter.core.ambience_engine"):
            engine.set_rules([_rule(id="r1", volume=0.9)])

        assert hub.refused_volumes >= 1
        assert engine.failed_hub_calls()["volume"] >= 1
        assert any("refused level" in r.message
                   for r in caplog.records), "volume refusal was not logged"

    def test_a_refused_fade_volume_is_recorded_not_silent(self, caplog):
        hub = FailingVolumeHub()
        engine = AmbienceEngine(hub)
        # fade_in drives set_channel_volume through _advance_fade (T-1313)
        engine.set_rules([_rule(id="r1", fade_in_ms=500, volume=0.5)])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["r1"]
        with caplog.at_level(logging.WARNING,
                             logger="fastprompter.core.ambience_engine"):
            engine.tick_fades(50)

        assert hub.refused_volumes >= 1
        assert engine.failed_hub_calls()["volume"] >= 1
        assert any("refused the fade level" in r.message
                   for r in caplog.records), "fade refusal was not logged"

    def test_a_healthy_hub_records_no_failures(self):
        """Negative control: the counts only move on a real refusal."""
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="r1", volume=0.2, fade_in_ms=500)])
        engine.evaluate(now=SUNDAY_10AM, monotonic=0.0)
        engine.tick_fades(50)
        engine.set_rules([_rule(id="r1", volume=0.9, fade_in_ms=500)])
        assert engine.failed_hub_calls() == {"stop": 0, "volume": 0}
