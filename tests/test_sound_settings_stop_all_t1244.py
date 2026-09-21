"""T-1244 A2: STOP ALL SOUND is directly available in the Sound Settings
dialog (the primary Events preview workflow).

Invariants:

1. A persistent footer-level ``■ STOP ALL SOUND`` button exists on every
   tab of the dialog and invokes the ONE canonical handler
   (``SoundManager.stop_all_sound``) — no duplicated STOP logic.
2. Activating it silences channels, queues, sequences and ambience.
3. It does NOT change the master mute state.
4. After STOP ALL, a fresh preview works while master mute is OFF.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    PlaybackMode,
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def dialog(tmp_path, monkeypatch):
    _ensure_app()
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir",
                        lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    data: dict = {"sound_ui": "True"}
    manager = SoundManager(host, data)
    transport = FakeMultiChannelTransport()
    manager._hub = AudioHub(transport=transport)
    widget = SoundSettingsDialog(host, data, manager)
    yield widget, manager, data, transport
    widget.deleteLater()


class TestStopAllInSoundSettings:
    def test_footer_stop_all_button_exists(self, dialog):
        widget, _manager, _data, _tp = dialog
        assert hasattr(widget, "_on_stop_all_sound")
        # The footer must carry a button whose handler is the canonical one.
        from PyQt6.QtWidgets import QPushButton
        stops = [b for b in widget.findChildren(QPushButton)
                 if b._en_text == "■ STOP ALL SOUND"] \
            if hasattr(QPushButton(), "_en_text") else \
            [b for b in widget.findChildren(QPushButton)
             if "STOP ALL SOUND" in b.text()]
        assert stops, "no STOP ALL SOUND button found in the dialog footer"
        # Persistent: it lives in the dialog's main layout (tab-agnostic),
        # not inside one of the tab pages.
        assert widget.pages.indexOf(stops[0]) == -1
        assert stops[0].parent() is widget or stops[0].parent() is None or \
            widget.pages.indexOf(stops[0].parentWidget()) == -1

    def test_stop_all_silences_everything_without_touching_mute(self, dialog):
        widget, manager, _data, tp = dialog
        hub = manager._hub
        hub.set_global_mode(PlaybackMode.MIX)
        # 1. Multiple active audio: transient channels + ambience + queue.
        hub.play_result("a.wav", bus=Bus.UI)
        hub.play_result("b.wav", bus=Bus.UI)
        r = hub.start_channel("amb.wav", event="ambience", bus=Bus.AMBIENCE,
                              loop=True)
        assert r.outcome in (hub_outcome_played(),) or tp.channels
        assert len(tp.channels) >= 1
        # 2. Activate the persistent STOP ALL control.
        widget._on_stop_all_sound()
        # 3. Channels, queues, sequences and ambience are silent.
        assert tp.channels == {}
        assert hub.active_channel_count() == 0
        assert hub.queue_depth() == 0
        assert hub.active_sequences() == []
        # 4. Mute state untouched.
        assert hub.is_muted() is False
        assert manager.master_muted() is False
        assert tp.stop_all_count >= 1
        # 5. A fresh preview works when master mute is OFF.
        assert manager.play_file("Click.wav", 0.5) is True
        assert len(tp.channels) >= 1

    def test_stop_all_keeps_future_audio_allowed_after_unmute_cycle(
            self, dialog):
        widget, manager, _data, tp = dialog
        hub = manager._hub
        hub.play_result("x.wav", bus=Bus.UI)
        widget._on_stop_all_sound()
        assert tp.channels == {}
        # Mute ON then OFF: STOP ALL must not have disturbed either leg.
        manager.set_master_muted(True)
        assert manager.play_file("Click.wav", 0.5) is False
        manager.set_master_muted(False)
        assert manager.play_file("Click.wav", 0.5) is True

    def test_stop_all_handler_uses_canonical_manager_method(self, dialog):
        """The dialog handler must delegate to SoundManager.stop_all_sound —
        no duplicated STOP logic."""
        widget, manager, _data, tp = dialog
        calls = []
        original = manager.stop_all_sound

        def spy():
            calls.append(True)
            original()

        manager.stop_all_sound = spy  # type: ignore[method-assign]
        widget._on_stop_all_sound()
        assert calls == [True]
        assert tp.stop_all_count >= 1


def hub_outcome_played():
    from fastprompter.core.audio_hub import Outcome
    return Outcome.PLAYED
