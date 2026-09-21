"""T-1238-C0.17: the integration contracts the UI is allowed to claim.

Everything here failed on the pre-hardening audio core: sequence REPLACE
left the old fragment audible, ``_cancel_sequences`` ignored its bus, the
global Stack/Replace setting only ever acted per bus, ambience never looped
or physically stopped, fades changed no volume, imported ``user:`` sounds
could not resolve, and ordinary SoundManager events bypassed the hub.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.ambience_engine import (  # noqa: E402
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)


def _hub(**kwargs):
    transport = FakeMultiChannelTransport()
    return AudioHub(transport=transport, **kwargs), transport


def _paths(transport) -> set[str]:
    return {c["path"] for c in transport.channels.values()}


# ---------------------------------------------------------------------------
# C0.3 / C0.4 -- voice sequences
# ---------------------------------------------------------------------------


class TestSequenceReplace:
    def test_replace_physically_stops_the_sounding_fragment(self):
        hub, tp = _hub()
        a = hub.play_sequence(["a1.wav", "a2.wav", "a3.wav"], bus=Bus.VOICE,
                              mode=PlaybackMode.MIX)
        assert _paths(tp) == {"a1.wav"}
        first_handle = list(tp.channels)[0]

        b = hub.play_sequence(["b1.wav", "b2.wav"], bus=Bus.VOICE,
                              mode=PlaybackMode.REPLACE)
        assert first_handle in tp.stopped, "a1 was never physically stopped"
        assert a.cancelled and not b.cancelled
        assert _paths(tp) == {"b1.wav"}
        # A late completion from the dead fragment must not resurrect a2.
        tp.finish_all()
        assert "a2.wav" not in _paths(tp)
        assert hub.active_sequences(Bus.VOICE) == [] or all(
            s.request_id == b.request_id for s in hub.active_sequences())

    def test_cancellation_respects_the_bus(self):
        hub, tp = _hub()
        voice = hub.play_sequence(["v1.wav", "v2.wav"], bus=Bus.VOICE,
                                  mode=PlaybackMode.MIX)
        alert = hub.play_sequence(["s1.wav", "s2.wav"], bus=Bus.ALERT,
                                  mode=PlaybackMode.MIX)
        hub.cancel_sequences(Bus.VOICE)
        assert voice.cancelled
        assert not alert.cancelled
        assert "s1.wav" in _paths(tp)
        assert "v1.wav" not in _paths(tp)

    def test_stacked_phrase_is_one_contiguous_job(self):
        """C0.4: no ordinary click may land inside 'thirty minutes remaining'."""
        hub, tp = _hub(global_mode=PlaybackMode.QUEUE)
        hub.play_sequence(["thirty.wav", "minutes.wav", "remaining.wav"],
                          bus=Bus.VOICE)
        hub.play("click.wav", event="click", bus=Bus.UI)  # inherits QUEUE
        order: list[str] = []
        for _ in range(8):
            if not tp.channels:
                break
            handle = next(iter(tp.channels))
            order.append(tp.channels[handle]["path"])
            tp.complete(handle)
        assert order == ["thirty.wav", "minutes.wav", "remaining.wav",
                         "click.wav"]


# ---------------------------------------------------------------------------
# C0.5 -- the global transient domain
# ---------------------------------------------------------------------------


class TestGlobalTransientSemantics:
    def test_global_overlay_lets_different_sounds_coexist(self):
        hub, tp = _hub(global_mode=PlaybackMode.MIX)
        hub.play("a.wav", event="click", bus=Bus.UI)
        hub.play("b.wav", event="timer", bus=Bus.ALERT)
        assert _paths(tp) == {"a.wav", "b.wav"}

    def test_global_stack_is_one_chronological_cross_bus_fifo(self):
        hub, tp = _hub(global_mode=PlaybackMode.QUEUE)
        assert hub.play("a.wav", event="click", bus=Bus.UI) is Outcome.QUEUED
        assert hub.play("b.wav", event="timer", bus=Bus.ALERT) is Outcome.QUEUED
        assert hub.play("c.wav", event="save", bus=Bus.UI) is Outcome.QUEUED
        assert _paths(tp) == {"a.wav"}, "stack must not overlap"
        order = ["a.wav"]
        while tp.channels:
            handle = next(iter(tp.channels))
            tp.complete(handle)
            if tp.channels:
                order.append(next(iter(tp.channels.values()))["path"])
        assert order == ["a.wav", "b.wav", "c.wav"]

    def test_global_replace_leaves_only_the_newest_transient(self):
        hub, tp = _hub(global_mode=PlaybackMode.MIX)
        hub.play("a.wav", event="click", bus=Bus.UI)
        hub.play("b.wav", event="timer", bus=Bus.ALERT)
        hub.set_global_mode(PlaybackMode.REPLACE)
        hub.play("c.wav", event="notify", bus=Bus.ALERT)
        assert _paths(tp) == {"c.wav"}
        assert hub.queue_depth() == 0

    def test_global_replace_never_stops_ambience(self):
        hub, tp = _hub(global_mode=PlaybackMode.REPLACE)
        ambience = hub.start_channel("rain.wav", bus=Bus.AMBIENCE, loop=True)
        hub.play("a.wav", event="click", bus=Bus.UI)
        hub.play("b.wav", event="timer", bus=Bus.ALERT)
        assert ambience.channel in tp.channels
        assert _paths(tp) == {"rain.wav", "b.wav"}

    def test_explicit_per_event_replace_stays_on_its_bus(self):
        """A per-event override is not the global setting; it stays scoped."""
        hub, tp = _hub(global_mode=PlaybackMode.MIX)
        hub.play("ui.wav", event="click", bus=Bus.UI)
        hub.play("p1.wav", event="problip_cue", bus=Bus.PROBLIP,
                 mode=PlaybackMode.REPLACE)
        hub.play("p2.wav", event="problip_cue", bus=Bus.PROBLIP,
                 mode=PlaybackMode.REPLACE)
        assert _paths(tp) == {"ui.wav", "p2.wav"}

    def test_high_rate_events_never_build_a_stack_queue(self):
        hub, _tp = _hub(global_mode=PlaybackMode.QUEUE)
        for _ in range(50):
            hub.play("key.wav", event="type", bus=Bus.UI)
        assert hub.queue_depth() <= 1
        assert hub.diagnostics()["coalesced"] >= 40


# ---------------------------------------------------------------------------
# C0.15 -- Problip skip_busy
# ---------------------------------------------------------------------------


class TestProblipSkipBusy:
    def test_skip_busy_drops_while_an_alert_owns_audio(self):
        hub, tp = _hub()
        hub.play("alarm.wav", event="timer", bus=Bus.ALERT)
        outcome = hub.play("blip.wav", event="problip_cue", bus=Bus.PROBLIP,
                           mode=PlaybackMode.SKIP_BUSY)
        assert outcome is Outcome.DROPPED_BUSY
        assert hub.queue_depth(Bus.PROBLIP) == 0, "a skipped cue never queues"
        assert "blip.wav" not in _paths(tp)

    def test_skip_busy_drops_while_a_voice_phrase_sounds(self):
        hub, _tp = _hub()
        hub.play_sequence(["v1.wav", "v2.wav"], bus=Bus.VOICE,
                          mode=PlaybackMode.MIX)
        assert hub.play("blip.wav", event="problip_cue", bus=Bus.PROBLIP,
                        mode=PlaybackMode.SKIP_BUSY) is Outcome.DROPPED_BUSY

    def test_skip_busy_plays_when_only_ambience_runs(self):
        hub, _tp = _hub()
        hub.start_channel("rain.wav", bus=Bus.AMBIENCE, loop=True)
        assert hub.play("blip.wav", event="problip_cue", bus=Bus.PROBLIP,
                        mode=PlaybackMode.SKIP_BUSY) in (
            Outcome.PLAYED, Outcome.MIXED)


# ---------------------------------------------------------------------------
# C0.8 - C0.11 -- ambience really loops, really stops, really fades
# ---------------------------------------------------------------------------


def _amb_rule(**kwargs) -> AmbienceRule:
    base = dict(id="r1", name="Rain", sound_ref="rain.wav", volume=0.8,
                trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP, enabled=True,
                fade_in_ms=0, fade_out_ms=0)
    base.update(kwargs)
    return AmbienceRule(**base)


NOON = dt.datetime(2026, 9, 9, 12, 0)


class TestAmbienceOnRealHub:
    def test_loop_reaches_the_transport_as_a_real_loop(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule()])
        engine.evaluate(now=NOON)
        job = next(iter(tp.channels.values()))
        assert job["loop"] is True

    def test_stop_ambience_removes_the_physical_channel(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule()])
        engine.evaluate(now=NOON)
        handle = next(iter(tp.channels))
        engine.stop_ambience()
        assert handle in tp.stopped
        assert tp.channels == {}

    def test_pause_is_physically_silent(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule()])
        engine.evaluate(now=NOON)
        engine.pause()
        assert tp.channels == {}

    def test_stop_ambience_leaves_transient_channels_alone(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule()])
        engine.evaluate(now=NOON)
        hub.play("click.wav", event="click", bus=Bus.UI)
        engine.stop_ambience()
        assert _paths(tp) == {"click.wav"}

    def test_fade_in_actually_changes_volume(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule(volume=0.8, fade_in_ms=200)])
        engine.evaluate(now=NOON)
        handle = next(iter(tp.channels))
        assert tp.channels[handle]["volume"] == pytest.approx(0.0)
        engine.tick_fades(100)
        assert tp.channels[handle]["volume"] == pytest.approx(0.4)
        engine.tick_fades(100)
        assert tp.channels[handle]["volume"] == pytest.approx(0.8)
        assert engine.fading_layers() == 0

    def test_fade_out_lowers_volume_then_stops_the_channel(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        rule = _amb_rule(trigger="TIME_WINDOW", start="00:00", end="13:00",
                         fade_out_ms=200)
        engine.set_rules([rule])
        engine.evaluate(now=NOON)
        handle = next(iter(tp.channels))
        engine.evaluate(now=dt.datetime(2026, 9, 9, 14, 0))  # window exited
        assert handle in tp.channels, "a 200ms fade must not stop instantly"
        engine.tick_fades(100)
        assert tp.channels[handle]["volume"] == pytest.approx(0.4)
        engine.tick_fades(100)
        assert handle in tp.stopped
        assert tp.channels == {}

    def test_stop_all_sound_kills_ambience_too(self):
        hub, tp = _hub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_amb_rule()])
        engine.evaluate(now=NOON)
        hub.play("click.wav", event="click", bus=Bus.UI)
        hub.play_sequence(["v1.wav", "v2.wav"], bus=Bus.VOICE)
        hub.stop_all()
        assert tp.channels == {}


# ---------------------------------------------------------------------------
# C0.12 / C0.13 -- managed library and preset global mode
# ---------------------------------------------------------------------------


def _write_wav(path) -> str:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 200)
    return str(path)


class TestManagedLibrary:
    def test_imported_user_ref_resolves_and_plays(self, tmp_path):
        from fastprompter.core import sound_library

        packaged = tmp_path / "packaged"
        managed = tmp_path / "managed"
        _write_wav(packaged / "click.wav")
        _write_wav(managed / "imported" / "bonk.wav")
        ref = sound_library.make_user_ref("imported/bonk.wav")
        assert ref == "user:imported/bonk.wav"
        resolved = sound_library.resolve_sound_ref(
            ref, builtin_root=str(packaged), user_root=str(managed))
        assert resolved is not None and os.path.isfile(resolved)
        hub, tp = _hub()
        assert hub.play(resolved, event="click", bus=Bus.UI) is Outcome.PLAYED
        assert _paths(tp) == {resolved}

    def test_builtin_ref_never_reaches_the_managed_root(self, tmp_path):
        from fastprompter.core import sound_library

        packaged = tmp_path / "packaged"
        managed = tmp_path / "managed"
        os.makedirs(packaged)
        _write_wav(managed / "secret.wav")
        assert sound_library.resolve_sound_ref(
            "builtin:secret.wav", builtin_root=str(packaged),
            user_root=str(managed)) is None

    @pytest.mark.parametrize("evil", [
        "../outside.wav", "/etc/passwd.wav", "C:/Windows/x.wav",
        "user:../../x.wav", "//host/share/x.wav", "sub/../../x.wav",
    ])
    def test_traversal_and_absolute_paths_are_never_playable(self, evil,
                                                             tmp_path):
        from fastprompter.core import sound_library

        assert sound_library.resolve_sound_ref(
            evil, builtin_root=str(tmp_path),
            user_root=str(tmp_path)) is None


class TestPresetGlobalMode:
    def test_applying_a_preset_applies_its_global_mode(self):
        from fastprompter.core.sound_presets import (
            GLOBAL_MODE_KEY,
            apply_preset_to_profile,
            profile_global_mode,
        )

        data: dict = {"sound_events": {}}
        assert profile_global_mode(data) == "mix"
        apply_preset_to_profile(
            {"id": "p", "name": "P", "global_mode": "replace", "events": {}},
            data)
        assert data[GLOBAL_MODE_KEY] == "replace"
        assert profile_global_mode(data) == "replace"

    def test_the_global_mode_has_one_home_not_an_event_row(self):
        from fastprompter.core.sound_presets import apply_preset_to_profile

        data: dict = {"sound_events": {"click": {"enabled": "True",
                                                 "file": "button1.wav",
                                                 "volume": "", "mode": "inherit"}}}
        apply_preset_to_profile(
            {"id": "p", "name": "P", "global_mode": "queue",
             "events": {"click": {"enabled": "True", "file": "x.wav",
                                  "volume": "", "mode": "inherit"}}}, data)
        assert data["sound_events"]["click"]["mode"] == "inherit"
        assert data["audio_global_playback_mode"] == "queue"


# ---------------------------------------------------------------------------
# C0.6 -- ordinary SoundManager events enter the hub
# ---------------------------------------------------------------------------


pytest.importorskip("PyQt6.QtMultimedia", reason="QtMultimedia absent")


@pytest.fixture()
def manager():
    from PyQt6.QtCore import QObject

    from fastprompter.core.audio_hub import AudioHub as _Hub
    from fastprompter.core.sound_manager import SoundManager

    parent = QObject()
    data: dict = {"sound_ui": "True", "sound_typewriter": "True"}
    sound_manager = SoundManager(parent, data)
    transport = FakeMultiChannelTransport()
    sound_manager._hub = _Hub(transport=transport)
    yield sound_manager, transport, data
    sound_manager.shutdown()


class TestSoundManagerConvergence:
    def test_the_packaged_backend_builds_from_the_real_binding(self):
        """The shipped app must get the RICH backend, not NullTransport.

        The test harness deliberately swaps ``sound_manager.QSoundEffect``
        for a muted stand-in, so this asserts against the real binding
        directly: probing ``QSoundEffect.Infinite`` (which PyQt6 does not
        expose) is what silently degraded the whole product to NullTransport.
        """
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QSoundEffect

        from fastprompter.core.audio_hub import QtSoundTransport

        transport = QtSoundTransport(qsoundeffect_cls=QSoundEffect,
                                     url_factory=QUrl.fromLocalFile)
        assert transport.capability_mixing

    def test_ordinary_click_enters_the_hub_with_ui_provenance(self, manager):
        sound_manager, transport, _data = manager
        assert sound_manager.hub_routing_active()
        sound_manager.play("click")
        record = sound_manager._hub.provenance()[-1]
        assert record["bus"] == "ui"
        assert record["event"] == "click"
        assert transport.channels

    def test_notification_enters_the_alert_bus(self, manager):
        sound_manager, _transport, _data = manager
        sound_manager.play("notify")
        record = sound_manager._hub.provenance()[-1]
        assert record["bus"] == "alert"

    def test_timer_event_enters_the_alert_bus(self, manager):
        sound_manager, _transport, _data = manager
        sound_manager.play("timer")
        assert sound_manager._hub.provenance()[-1]["bus"] == "alert"

    def test_per_event_mode_override_is_consumed_at_runtime(self, manager):
        sound_manager, transport, data = manager
        data["sound_events"] = {
            "click": {"enabled": "True", "file": "button1.wav",
                      "volume": "", "mode": "replace"},
        }
        sound_manager.invalidate_cache()
        sound_manager.play("click")
        sound_manager.play("save")
        sound_manager.play("click")
        record = sound_manager._hub.provenance()[-1]
        assert record["mode"] == "replace"
        assert record["outcome"] == "REPLACED"

    def test_global_mode_reaches_the_hub_from_the_profile(self, manager):
        sound_manager, _transport, data = manager
        data["audio_global_playback_mode"] = "queue"
        sound_manager.reload_playback_mode()
        assert sound_manager._hub.global_mode is PlaybackMode.QUEUE

    def test_stop_all_sound_silences_hub_routed_events(self, manager):
        sound_manager, transport, _data = manager
        sound_manager.play("click")
        sound_manager.play("notify")
        assert transport.channels
        sound_manager.stop_all_sound()
        assert transport.channels == {}
