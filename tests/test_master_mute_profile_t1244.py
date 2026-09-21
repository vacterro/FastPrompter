"""T-1244: the master mute survives restart and follows profile switches.

``audio_global_muted`` is profile state: switching from a muted profile to
an unmuted one must release the runtime mute immediately -- and back again
-- without opening Settings.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))


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


def _build():
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
    from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport

    _qt_stub.restore(before)
    return _mod.SoundManager, AudioHub, FakeMultiChannelTransport


SoundManager, AudioHub, FakeMultiChannelTransport = _build()


class _FakeWindow:
    """Just enough window for _sync_audio_mute_state()."""

    def __init__(self, data):
        self.data = data
        self.sound_manager = self._sm
        self._current_lang = "EN"

    def _bind(self, sm):
        self._sm = sm
        self.sound_manager = sm


class TestProfileSwitchMute:
    def _make(self, muted):
        data = {"audio_global_muted": "True" if muted else "False",
                "sound_ui": "True"}
        sm = SoundManager(_MockQObject(), data)
        sm._hub = AudioHub(transport=FakeMultiChannelTransport())
        sm._hub.set_muted(data["audio_global_muted"] == "True")
        return sm, data

    def test_restart_preserves_mute_without_settings(self):
        sm, _data = self._make(muted=True)
        assert sm.master_muted() is True
        sm2, _data2 = self._make(muted=False)
        assert sm2.master_muted() is False

    def test_mute_follows_each_profile_in_a_switch_cycle(self):
        sm, data_a = self._make(muted=True)
        _sm_b_unused, data_b = self._make(muted=False)

        # Simulate _apply_profile_runtime_state: the manager's data pointer
        # moves to the new profile, then reload_playback_mode() re-reads the
        # persisted mute into the hub.
        sm._data = data_b
        sm.reload_playback_mode()
        assert sm.master_muted() is False, "switching away releases the mute"

        sm._data = data_a
        sm.reload_playback_mode()
        assert sm.master_muted() is True, "switching to muted profile mutes"

        # And back once more -- no stale state in either direction.
        sm._data = data_b
        sm.reload_playback_mode()
        assert sm.master_muted() is False

    def test_muted_profile_blocks_audio_right_after_switch(self):
        sm, _data = self._make(muted=False)
        tp = sm._hub.transport
        data_muted = {"audio_global_muted": "True", "sound_ui": "True"}
        sm._data = data_muted
        sm.reload_playback_mode()
        assert sm.play_file("Click.wav", 0.5) is False
        assert len(tp.channels) == 0
