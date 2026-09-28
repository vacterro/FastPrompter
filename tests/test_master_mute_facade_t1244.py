"""T-1244: master mute through the SoundManager facade and its direct-hub
users (Problip, Voice, Ambience controller, Sound Settings preview).

Covers BOTH routing modes:
- hub-routing (real mixing backend behind the hub), and
- the legacy/degraded single-transport engine (no mixing capability),
because a portable build may run without QtMultimedia mixing.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
)

# ---------------------------------------------------------------------------
# SoundManager built against the same minimal Qt stubs test_sound_manager uses
# ---------------------------------------------------------------------------

class _MockQObject:
    def __init__(self, parent=None):
        self._parent = parent

    def parent(self):
        return self._parent


class _MockQSoundEffect:
    def __init__(self, parent=None):
        self.parent = parent

    def setSource(self, source):
        pass

    def setVolume(self, vol):
        pass

    def play(self):
        pass


def _build_sound_manager():
    import _qt_stub

    before = _qt_stub.snapshot()
    sys.modules.pop("fastprompter.core.sound_manager", None)
    sys.modules["PyQt6"] = MagicMock()
    sys.modules["PyQt6.QtMultimedia"] = MagicMock()
    sys.modules["PyQt6.QtMultimedia"].QSoundEffect = _MockQSoundEffect
    sys.modules["PyQt6.QtCore"] = MagicMock()
    sys.modules["PyQt6.QtCore"].QObject = _MockQObject
    sys.modules["PyQt6.QtCore"].QUrl = MagicMock()
    sys.modules["PyQt6.QtCore"].QUrl.fromLocalFile = lambda p: f"file:///{p}"
    import fastprompter.core.sound_manager as _mod
    from fastprompter.core.sound_manager import SoundManager  # noqa: F401

    _qt_stub.restore(before)
    return _mod.SoundManager


SoundManager = _build_sound_manager()


def _make_sm(data=None, hub_transport=True):
    """A SoundManager whose hub uses the deterministic fake transport.

    ``hub_transport=False`` degrades the hub (no mixing capability) so the
    facade's LEGACY single-transport path is exercised, exactly like a
    portable build without a mixing backend.
    """
    data = data if data is not None else {"sound_ui": "True"}
    sm = SoundManager(_MockQObject(), data)
    if hub_transport:
        tp = FakeMultiChannelTransport()
        sm._hub = AudioHub(transport=tp)
        sm._hub.set_muted(data.get("audio_global_muted", "False") == "True")
    else:
        tp = None
    return sm, tp


# ---------------------------------------------------------------------------
# Facade: every explicit route is gated while muted (hub-routing mode)
# ---------------------------------------------------------------------------


class TestFacadeMuteHubRouting:
    def test_startup_mutes_without_settings(self):
        sm, tp = _make_sm({"audio_global_muted": "True", "sound_ui": "True"})
        assert sm.master_muted() is True
        # Already muted from construction: nothing may physically start.
        assert sm.play_file("Click.wav", 0.5) is False
        assert len(tp.channels) == 0

    def test_startup_unmuted_by_default(self):
        sm, _tp = _make_sm({"sound_ui": "True"})
        assert sm.master_muted() is False

    def test_play_sound_ref_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        assert sm.play_sound_ref("Click.wav", 0.5) is False
        assert len(tp.channels) == 0

    def test_preview_sound_ref_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        assert sm.preview_sound_ref("Click.wav", 0.5) is False
        assert len(tp.channels) == 0

    def test_play_file_preview_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        assert sm.play_file("Click.wav", 0.5) is False
        assert len(tp.channels) == 0

    def test_named_play_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        sm.play("click")
        assert len(tp.channels) == 0

    def test_timer_and_limit_explicit_refs_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        assert sm.play_sound_ref("file:Click.wav", 0.8) is False
        assert sm.play_sound_ref("timer", 0.8) is False
        assert len(tp.channels) == 0

    def test_mute_cues_allowed(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        assert sm.play_mute_cue("audio_mute_on") is True
        assert len(tp.channels) == 1
        # And exactly the two canonical events, nothing else.
        assert sm.play_mute_cue("click") is False
        assert sm.play_mute_cue("timer") is False

    def test_mute_cue_respects_row_disabled(self):
        data = {
            "audio_global_muted": "True",
            "sound_events": {"audio_mute_on": {"enabled": "False"}},
        }
        sm, _tp = _make_sm(data)
        sm._hub.set_muted(True)
        assert sm.play_mute_cue("audio_mute_on") is False

    def test_set_master_muted_stops_active_audio(self):
        sm, tp = _make_sm({"sound_ui": "True"})
        sm._hub.play("live.wav", bus=Bus.ALERT)
        sm._hub.play_sequence(["v.wav"], bus=Bus.VOICE)
        sm._hub.start_channel("amb.wav", bus=Bus.AMBIENCE, loop=True)
        assert sm._hub.active_channel_count() >= 1

        sm.set_master_muted(True)

        assert sm.master_muted() is True
        assert len(tp.channels) == 0
        assert sm._hub.active_channel_count() == 0
        assert sm._hub.queue_depth() == 0
        assert sm._hub.active_sequences() == []

    def test_no_stale_replay_after_unmute(self):
        sm, tp = _make_sm({"sound_ui": "True"})
        sm._hub.set_global_mode("queue")
        sm._hub.play("old.wav", bus=Bus.ALERT)
        sm.set_master_muted(True)
        sm.set_master_muted(False)
        assert sm._hub.queue_depth() == 0
        assert len(tp.channels) == 0
        # A fresh request works normally again (queue mode with nothing
        # else playing starts immediately).
        result = sm._hub.play_result("new.wav", bus=Bus.ALERT)
        assert result.outcome not in (Outcome.DROPPED_MUTED,)
        assert len(tp.channels) == 1

    def test_diagnostic_records_dropped_muted(self):
        sm, _tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        sm.play_sound_ref("file:Click.wav", 0.5)
        entries = sm.diagnostic_log()
        assert entries
        assert entries[-1]["outcome"] == "DROPPED_MUTED"

    def test_legacy_stop_all_not_repeated_on_unmute(self):
        sm, tp = _make_sm({"sound_ui": "True"})
        sm.set_master_muted(True)
        sm.set_master_muted(False)
        # Unmuting must NOT stop everything: audio that legitimately started
        # between unmute and later plays must survive.
        sm._hub.play("fine.wav", bus=Bus.UI)
        sm.set_master_muted(False)
        assert len(tp.channels) == 1


# ---------------------------------------------------------------------------
# Degraded / legacy engine (no mixing backend in the hub)
# ---------------------------------------------------------------------------


class TestFacadeMuteLegacyMode:
    @pytest.fixture()
    def legacy_sm(self):
        sm, _tp = _make_sm({"audio_global_muted": "False",
                            "sound_ui": "True"}, hub_transport=False)
        # Force the legacy routing decision the same way a degraded build
        # would evaluate it.
        sm._hub_routing_enabled = False
        return sm

    def test_hub_routing_reports_legacy(self, legacy_sm):
        assert legacy_sm.hub_routing_active() is False

    def test_mute_gates_legacy_request(self, legacy_sm):
        legacy_sm.set_master_muted(True)
        assert legacy_sm._request(
            "click", "whatever.wav", 0.5, "PREVIEW") is False
        assert legacy_sm.diagnostic_log()[-1]["outcome"] == "DROPPED_MUTED"

    def test_mute_cues_still_audible_in_legacy_mode(self, legacy_sm):
        legacy_sm.set_master_muted(True)
        assert legacy_sm.play_mute_cue("audio_mute_on") is True
        assert legacy_sm.play_mute_cue("audio_mute_off") is True
        # But only the canonical cue events.
        assert legacy_sm.play_mute_cue("click") is False

    def test_normal_event_blocked_in_legacy_mode(self, legacy_sm):
        legacy_sm.set_master_muted(True)
        assert legacy_sm.play_sound_ref("file:Click.wav", 0.5) is False
        assert legacy_sm.preview_sound_ref("Click.wav", 0.5) is False

    def test_no_physical_player_invocation_while_muted(self, legacy_sm):
        legacy_sm.set_master_muted(True)
        started = []
        legacy_sm._play_winsound = lambda *a, **k: started.append(a)
        legacy_sm.play_sound_ref("file:Click.wav", 0.5)
        legacy_sm.play("click")
        assert started == []


# ---------------------------------------------------------------------------
# Direct hub users: Problip / Voice / Ambience controller / Settings preview
# ---------------------------------------------------------------------------


class _Manager:
    """The SoundManager stand-in the controller tests use."""

    def __init__(self, hub):
        self._hub = hub

    def audio_hub(self):
        return self._hub


class TestDirectHubUsers:
    def test_problip_direct_hub_play_is_blocked(self):
        hub = AudioHub(transport=FakeMultiChannelTransport())
        hub.set_muted(True)
        tp = hub.transport
        outcome = hub.play("blip01.wav", bus=Bus.PROBLIP)
        assert outcome is Outcome.DROPPED_MUTED
        assert tp.channels == {}

    def test_problip_muted_cue_is_skipped_not_failed(self):
        """A muted scheduled cue must be a normal SKIPPED outcome."""
        from fastprompter.core.problip import CueResult
        from fastprompter.ui.problip_controller import _AUDIBLE

        # The controller maps "not audible" to SKIPPED; DROPPED_MUTED is not
        # audible, so it lands in SKIPPED -- never FAILED.
        assert Outcome.DROPPED_MUTED not in _AUDIBLE
        result = CueResult.coerce("SKIPPED")
        assert result is CueResult.SKIPPED

    def test_voice_sequence_blocked(self):
        hub = AudioHub(transport=FakeMultiChannelTransport())
        hub.set_muted(True)
        seq = hub.play_sequence(["thirty.wav", "minutes.wav"], bus=Bus.VOICE)
        assert seq.cancelled
        assert hub.transport.channels == {}

    def test_preview_sound_settings_blocked(self):
        sm, tp = _make_sm({"audio_global_muted": "True"})
        sm._hub.set_muted(True)
        # What SoundSettingsDialog._preview() ultimately calls.
        assert sm.play_file("Click.wav", 0.5) is False
        assert tp.channels == {}


# ---------------------------------------------------------------------------
# Settings / hotkey registration surfaces
# ---------------------------------------------------------------------------


class TestSettingsSurfaces:
    def test_hk_audio_mute_is_an_in_app_bind(self):
        # T-1244 made the master mute an ordinary, remappable in-app shortcut
        # like the rest -- same HotkeyWidget/save path as Ctrl+F, not a
        # hardcoded global. T-1335 moved that list into ui.hotkey_spec, so the
        # contract is now read from there; the second half keeps the part that
        # was the actual bug -- the dialog builds its rows FROM the spec, so
        # the key cannot go back to being bound-but-unlisted.
        from fastprompter.ui.hotkey_spec import IN_APP_HOTKEYS

        binds = {hk.key_name: hk.default for hk in IN_APP_HOTKEYS}
        assert binds.get("hk_audio_mute") == "Ctrl+M"

        path = os.path.join(os.path.dirname(__file__),
                            "../src/fastprompter/ui/settings.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "from fastprompter.ui.hotkey_spec import IN_APP_HOTKEYS" in src

    def test_mute_cues_are_remappable_event_rows(self):
        from fastprompter.core.sound_manager import EVENT_LABELS

        assert "audio_mute_on" in EVENT_LABELS
        assert "audio_mute_off" in EVENT_LABELS
        assert EVENT_LABELS["audio_mute_on"] != EVENT_LABELS["audio_mute_off"]

    def test_default_profile_carries_mute_defaults(self):
        from fastprompter.core.default_profile import DEFAULT_PROFILE

        assert DEFAULT_PROFILE.get("audio_global_muted") == "False"
        assert DEFAULT_PROFILE.get("hk_audio_mute") == "Ctrl+M"
