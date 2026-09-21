"""T-1238-E1.3: audio activity must never touch profile/SILO state.

Problip, ambience and voice each own a SQLite store, Qt timers and (for
weather) a network thread.  None of that may write into the profile data
dict, mark the profile dirty, or reach the profile database -- the T-1227
integrity work is exactly about a second writer appearing where none is
expected.
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.ambience_engine import (  # noqa: E402
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.ambience_store import AmbienceStore, new_rule_id  # noqa: E402
from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport  # noqa: E402
from fastprompter.core.problip_store import ProblipStore  # noqa: E402
from fastprompter.core.voice_store import VoiceStore  # noqa: E402
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402
from fastprompter.ui.problip_controller import ProblipController  # noqa: E402
from fastprompter.ui.voice_controller import VoiceController  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    """A SoundManager stand-in that also records profile-dict access."""

    def __init__(self, hub, data: dict) -> None:
        self._hub = hub
        self._data = data
        self.stop_all_calls = 0

    def audio_hub(self):
        return self._hub

    def stop_all_sound(self) -> None:
        self.stop_all_calls += 1
        self._hub.stop_all()


@pytest.fixture()
def rig(tmp_path):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    # A realistic profile payload: silos, the active slot and sound settings.
    data: dict = {
        "temp_presets_all": {"0": "silo zero text", "1": "silo one text"},
        "active_temp_slot": "0",
        "sound_ui": "True",
        "sound_events": {"click": {"enabled": "True", "file": "button1.wav",
                                   "volume": "", "mode": "inherit"}},
    }
    manager = _Manager(hub, data)
    problip = ProblipController(
        parent, manager, store=ProblipStore(str(tmp_path / "problip.db")),
        random_source=lambda n: 0)
    voice = VoiceController(parent, manager,
                            store=VoiceStore(str(tmp_path / "audio.db")))
    ambience = AmbienceController(
        parent, manager, store=AmbienceStore(str(tmp_path / "audio.db")),
        engine=AmbienceEngine(hub))
    yield data, problip, voice, ambience, transport, tmp_path
    for controller in (problip, voice, ambience):
        controller.shutdown()
    parent.deleteLater()


def _rule() -> AmbienceRule:
    return AmbienceRule(id=new_rule_id(), name="Rain", sound_ref="rain.wav",
                        volume=0.4, trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                        enabled=True, fade_in_ms=0, fade_out_ms=0)


class TestProfileIsolation:
    def test_a_running_problip_never_touches_the_profile(self, rig):
        data, problip, _voice, _ambience, _tp, _tmp = rig
        before = copy.deepcopy(data)
        problip.start()
        for _ in range(5):
            problip._on_timeout()
        problip.update_settings(volume_percent=42, playback_mode="replace")
        assert data == before, "Problip wrote into the profile payload"
        assert problip.stats().total >= 1, "the cues really did happen"

    def test_running_ambience_never_touches_the_profile(self, rig):
        data, _problip, _voice, ambience, transport, _tmp = rig
        before = copy.deepcopy(data)
        ambience.store.save_rules([_rule()])
        ambience.reload_rules()
        ambience.start()
        ambience.engine.tick_fades(50)
        assert transport.channels, "ambience really started"
        assert data == before

    def test_voice_settings_never_touch_the_profile(self, rig):
        data, _problip, voice, _ambience, _tp, _tmp = rig
        before = copy.deepcopy(data)
        voice.update_settings(enabled=True, mode="queue", volume_percent=70)
        voice.refresh_target(timers=[{"id": "t", "due": 9_999_999.0}])
        assert data == before

    def test_the_active_silo_slot_is_never_rewritten(self, rig):
        data, problip, _voice, ambience, _tp, _tmp = rig
        ambience.store.save_rules([_rule()])
        ambience.reload_rules()
        ambience.start()
        problip.start()
        for slot in ("0", "1", "0"):
            data["active_temp_slot"] = slot
            problip._on_timeout()
            ambience._on_evaluate()
            assert data["active_temp_slot"] == slot, (
                "audio activity drifted the active SILO")

    def test_silo_text_survives_a_burst_of_audio_activity(self, rig):
        data, problip, _voice, ambience, _tp, _tmp = rig
        ambience.store.save_rules([_rule()])
        ambience.reload_rules()
        ambience.start()
        problip.start()
        expected = dict(data["temp_presets_all"])
        for index in range(20):
            data["active_temp_slot"] = str(index % 2)
            problip._on_timeout()
            ambience._on_evaluate()
            ambience.engine.tick_fades(50)
        assert data["temp_presets_all"] == expected


class TestStoreIsolation:
    def test_audio_state_lives_in_its_own_databases(self, rig):
        _data, problip, voice, ambience, _tp, tmp_path = rig
        assert problip.store.db_path.endswith("problip.db")
        assert voice.store.db_path.endswith("audio.db")
        assert ambience.store.db_path.endswith("audio.db")
        # ...and nothing else was created next to them.
        created = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
        assert set(created) <= {"problip.db", "audio.db",
                                "problip.db-wal", "problip.db-shm",
                                "audio.db-wal", "audio.db-shm"}

    def test_shutdown_leaves_no_timer_alive(self, rig):
        _data, problip, voice, ambience, transport, _tmp = rig
        ambience.store.save_rules([_rule()])
        ambience.reload_rules()
        ambience.start()
        problip.start()
        voice.update_settings(enabled=True)
        for controller in (problip, voice, ambience):
            controller.shutdown()
        assert not problip._timer.isActive()
        assert not voice._timer.isActive()
        for timer in (ambience._evaluate_timer, ambience._fade_timer,
                      ambience._weather_timer):
            assert not timer.isActive()
        assert transport.channels == {}
