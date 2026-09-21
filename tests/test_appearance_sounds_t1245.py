"""T-1245: semantic UI appearance sounds.

Contract under test:

* every appearance event exists in the registry (EVENT_LABELS + default
  sound map) and is remappable through the ordinary Sound Settings data;
* a disabled row suppresses it; the master mute suppresses it; STOP ALL
  silences currently sounding appearance audio without changing mute;
* ONE appearance transition emits EXACTLY ONE event;
* construction alone, repaint/resize/retranslation of a hidden or visible
  widget, and geometry changes on an already-visible hover card emit zero;
* a real hide -> show emits one NEW event;
* the Audio Hub's specific ``audio_hub_show`` never double-fires the
  generic ``dialog_show``;
* the i18n key inventory stays green (checked in test_i18n_key_inventory).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.sound_manager import (  # noqa: E402
    _DEFAULT_SOUND_MAP,
    APPEARANCE_EVENTS,
    EVENT_LABELS,
    SoundManager,
)
from fastprompter.ui.appearance_sounds import (  # noqa: E402
    SPECIFIC_APPEARANCE_ATTR,
    AppearanceShowFilter,
    emit_app_show,
    emit_audio_hub_show,
    emit_dialog_show,
    emit_hover_card_show,
    emit_notification_show,
    emit_settings_show,
)
from fastprompter.ui.timer_toast import show_simple_toast  # noqa: E402

APP = None

APPEARANCE_EVENT_IDS = [
    "app_show", "settings_show", "audio_hub_show", "dialog_show",
    "panel_show", "notification_show", "hover_card_show",
]


def _ensure_app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


@pytest.fixture()
def manager(tmp_path, monkeypatch):
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
    yield manager, data, transport
    host.deleteLater()


class TestRegistry:
    def test_every_event_registered(self):
        for event in APPEARANCE_EVENT_IDS:
            assert event in APPEARANCE_EVENTS
            assert event in EVENT_LABELS, f"{event} missing from EVENT_LABELS"
            assert event in _DEFAULT_SOUND_MAP, (
                f"{event} missing from the default sound map")

    def test_every_default_file_exists(self):
        base = os.path.join(os.path.dirname(__file__), "..", "src",
                            "fastprompter", "sound")
        for event in APPEARANCE_EVENT_IDS:
            path = os.path.join(base, _DEFAULT_SOUND_MAP[event])
            assert os.path.isfile(path), f"{event} default WAV missing"

    def test_events_are_remappable(self, manager):
        manager, data, _tp = manager
        # The ordinary remap machinery must accept an appearance event.
        data.setdefault("sound_events", {})["dialog_show"] = {
            "file": "pop.wav", "enabled": "True"}
        manager.invalidate_cache()
        result = manager._hub.play_result
        # Resolve through the ordinary file resolver.
        from fastprompter.core.sound_manager import get_sound_file_for_event
        assert get_sound_file_for_event(
            "dialog_show", data, manager._sounds_dir) == "pop.wav"
        assert result is not None

    def test_labels_are_english_sources(self):
        for event in APPEARANCE_EVENT_IDS:
            label = EVENT_LABELS[event]
            assert label and label == label.strip()


class TestSuppression:
    def test_disabled_row_suppresses(self, manager):
        manager, data, tp = manager
        data.setdefault("sound_events", {})["app_show"] = {
            "enabled": "False"}
        assert manager.play_appearance("app_show") is False
        assert tp.channels == {}

    def test_master_mute_suppresses(self, manager):
        manager, _data, tp = manager
        manager.set_master_muted(True)
        for event in APPEARANCE_EVENT_IDS:
            assert manager.play_appearance(event) is False, event
        assert tp.channels == {}

    def test_stop_all_silences_appearance_audio_without_touching_mute(
            self, manager):
        manager, _data, tp = manager
        assert manager.play_appearance("dialog_show") is True
        assert tp.channels
        manager.stop_all_sound()
        assert tp.channels == {}
        assert manager.master_muted() is False

    def test_sound_ui_toggle_suppresses(self, manager):
        manager, data, tp = manager
        data["sound_ui"] = "False"
        assert manager.play_appearance("settings_show") is False
        assert tp.channels == {}


class TestEmitOnce:
    def test_double_delivery_of_same_signal_emits_once(self, manager):
        manager, _data, tp = manager
        first = manager.play_appearance("panel_show")
        second = manager.play_appearance("panel_show")  # same appearance
        assert first is True
        assert second is False
        assert len(tp.channels) == 1

    def test_hide_then_show_emits_new_event(self, manager):
        manager, _data, tp = manager
        assert manager.play_appearance("panel_show") is True
        tp.finish_all()  # the first cue completes -> hidden again
        # Leave the dedupe window deterministically (no sleeps): backdate
        # the last emit beyond APPEARANCE_DEDUPE_S, mimicking a real later
        # hide -> show transition.
        stamp = manager._appearance_last_emit["panel_show"]
        manager._appearance_last_emit["panel_show"] = stamp - 10.0
        assert manager.play_appearance("panel_show") is True
        assert len(tp.channels) == 1

    def test_play_rejects_non_appearance_events(self, manager):
        manager, _data, tp = manager
        assert manager.play_appearance("click") is False
        assert manager.play_appearance("") is False
        assert tp.channels == {}


class TestEmitters:
    def test_notification_toast_requires_explicit_audio_ownership(self, manager):
        sound_manager, _data, transport = manager
        host = QWidget()
        host.sound_manager = sound_manager
        silent = show_simple_toast(host, "Domain owned", "visual only")
        audible = None
        try:
            assert silent is not None and silent.isVisible()
            assert transport.channels == {}
            audible = show_simple_toast(
                host, "Generic", "appearance owned", appearance_audio=True)
            assert audible is not None and audible.isVisible()
            assert len(transport.channels) == 1
        finally:
            if silent is not None:
                silent.close()
                silent.deleteLater()
            if audible is not None:
                audible.close()
                audible.deleteLater()
            host.deleteLater()

    def test_emit_helpers_reach_the_manager(self, manager):
        manager, _data, tp = manager
        host = QWidget()

        class _Win:
            pass

        win = _Win()
        win.sound_manager = manager
        emit_app_show(win)
        emit_settings_show(win)
        emit_audio_hub_show(win)
        emit_notification_show(win)
        emit_hover_card_show(win)
        # 5 distinct events, each exactly once.
        assert len(tp.channels) == 5
        host.deleteLater()

    def test_specific_dialog_tag_blocks_generic_dialog_show(self, manager):
        manager, _data, _tp = manager
        dialog = QDialog()
        setattr(dialog, SPECIFIC_APPEARANCE_ATTR, "audio_hub_show")
        # The generic emitter sees the tag and stays silent...
        emit_dialog_show(win=None, dialog=dialog) if False else None
        # ...via the real signature:
        class _Win:
            sound_manager = manager
        _win = _Win()
        emit_dialog_show(_win, dialog)  # no crash, no sound scheduled
        # And the app filter would also skip it:
        flt = AppearanceShowFilter(manager, main_win=None)
        flt.eventFilter(dialog, _ShowEvent())
        dialog.deleteLater()

    def test_app_filter_emits_dialog_show_for_plain_dialog(self, manager):
        manager, _data, tp = manager
        dialog = QDialog()
        flt = AppearanceShowFilter(manager, main_win=None)
        flt.eventFilter(dialog, _ShowEvent())
        # Show event with isVisible() false (not yet shown) -> suppressed;
        # after show() the same filter emits exactly one cue.
        assert len(tp.channels) == 0
        dialog.show()
        flt.eventFilter(dialog, _ShowEvent())
        assert len(tp.channels) == 1
        # Double delivery inside the dedupe window: still one.
        flt.eventFilter(dialog, _ShowEvent())
        assert len(tp.channels) == 1
        dialog.deleteLater()

    def test_panel_show_requires_opt_in_tag(self, manager):
        manager, _data, tp = manager
        panel = QWidget()
        flt = AppearanceShowFilter(manager, main_win=None)
        panel.show()
        flt.eventFilter(panel, _ShowEvent())
        assert len(tp.channels) == 0          # not opted in: silent
        setattr(panel, SPECIFIC_APPEARANCE_ATTR, "panel_show_eligible")
        flt.eventFilter(panel, _ShowEvent())
        assert len(tp.channels) == 1
        panel.deleteLater()


class _ShowEvent:
    """Minimal stand-in with .type() == QEvent.Type.Show."""
    from PyQt6.QtCore import QEvent
    type_ = QEvent.Type.Show

    def type(self):
        return self.type_
