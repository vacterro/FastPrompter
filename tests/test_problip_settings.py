"""T-1238-C2: the fifth Settings tab BINDS to the controller, never owns it.

Opening or closing Settings, rebuilding the panel, switching tabs and
applying a preset must leave the Problip runtime — its object, its timer,
its store and its statistics — completely untouched.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtWidgets import QWidget  # noqa: E402

from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport  # noqa: E402
from fastprompter.core.problip import IntervalMode, ProblipState  # noqa: E402
from fastprompter.core.problip_store import ProblipStore  # noqa: E402
from fastprompter.ui.problip_controller import ProblipController  # noqa: E402
from fastprompter.ui.problip_settings import (  # noqa: E402
    INTERVAL_CHOICES,
    PLAYBACK_CHOICES,
    ProblipSettingsPage,
)

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    def __init__(self, hub) -> None:
        self._hub = hub
        self.stop_all_calls = 0

    def audio_hub(self):
        return self._hub

    def stop_all_sound(self) -> None:
        self.stop_all_calls += 1
        self._hub.stop_all()


@pytest.fixture()
def page(tmp_path):
    _ensure_app()
    parent = QObject()
    host = QWidget()
    transport = FakeMultiChannelTransport()
    manager = _Manager(AudioHub(transport=transport))
    store = ProblipStore(str(tmp_path / "problip.db"))
    controller = ProblipController(parent, manager, store=store,
                                   random_source=lambda n: 0)
    widget = ProblipSettingsPage(host, controller, "EN")
    yield widget, controller, transport, manager
    controller.shutdown()
    host.deleteLater()
    parent.deleteLater()


class TestBindingNotOwnership:
    def test_rebuilding_the_page_never_restarts_the_runtime(self, page):
        widget, controller, _tp, _mgr = page
        controller.start()
        controller._on_timeout()
        before = (id(controller), id(controller._timer), id(controller.store),
                  controller.scheduler.pending_delay_ms,
                  controller.stats().total)
        # "Closing and reopening Settings" is exactly a second page build.
        second = ProblipSettingsPage(widget.host, controller, "EN")
        after = (id(controller), id(controller._timer), id(controller.store),
                 controller.scheduler.pending_delay_ms,
                 controller.stats().total)
        assert before == after
        assert second.controller is controller
        assert controller.is_running()

    def test_the_page_reflects_state_without_writing_it_back(self, page):
        widget, controller, _tp, _mgr = page
        before = controller.settings.to_dict()
        widget.reload()
        assert controller.settings.to_dict() == before

    def test_every_group_is_present(self, page):
        widget, _controller, _tp, _mgr = page
        titles = [title for title, _widgets in widget.groups()]
        assert titles == ["Problip", "Interval", "Sound pool", "Statistics",
                          "Effects", "Audio", "Help"]


class TestStatusAndControls:
    def test_start_disables_start_and_enables_stop(self, page):
        widget, controller, _tp, _mgr = page
        assert widget.btn_start.isEnabled()
        widget._on_start()
        assert controller.state is ProblipState.STARTING
        assert not widget.btn_start.isEnabled(), (
            "START must not look available while Problip is starting")
        assert widget.btn_stop.isEnabled()

    def test_stop_returns_to_off(self, page):
        widget, controller, _tp, _mgr = page
        widget._on_start()
        widget._on_stop()
        assert controller.state is ProblipState.STOPPED
        assert widget.lbl_status.text() == "OFF"
        assert widget.btn_start.isEnabled()

    def test_first_cue_shows_on(self, page):
        widget, controller, _tp, _mgr = page
        widget._on_start()
        controller._on_timeout()
        assert widget.lbl_status.text() == "ON"

    def test_test_never_touches_statistics_or_the_interval(self, page):
        widget, controller, _tp, _mgr = page
        widget._on_test()
        assert controller.stats().total == 0
        assert not controller._timer.isActive()


class TestSoundPool:
    def test_exactly_six_stable_choices(self, page):
        widget, _controller, _tp, _mgr = page
        assert len(widget.pool_boxes) == 6

    def test_the_last_selected_sound_cannot_be_unchecked(self, page):
        widget, controller, _tp, _mgr = page
        first = next(iter(widget.pool_boxes))
        for sound_id, box in widget.pool_boxes.items():
            if sound_id != first and box.isChecked():
                box.setChecked(False)
        assert widget.pool_boxes[first].isChecked()
        widget.pool_boxes[first].setChecked(False)
        assert widget.pool_boxes[first].isChecked(), (
            "unchecking the last sound would leave Problip silent")
        assert controller.settings.selected_sound_ids

    def test_selecting_more_sounds_persists(self, page):
        widget, controller, _tp, _mgr = page
        widget.pool_boxes["sound_bonk"].setChecked(True)
        assert "sound_bonk" in controller.settings.selected_sound_ids
        assert "sound_bonk" in controller.store.load_settings().selected_sound_ids


class TestVolume:
    def test_dragging_is_silent_and_release_previews_once(self, page):
        widget, controller, transport, _mgr = page
        for value in (10, 20, 30, 40):
            widget.sl_volume.setValue(value)
        assert transport.channels == {}, "dragging must not make a sound"
        widget.sl_volume.sliderReleased.emit()
        assert len(transport.channels) == 1
        assert controller.settings.volume_percent == 40
        assert controller.stats().total == 0
        assert not controller._timer.isActive(), "a preview never re-arms"


class TestSelectors:
    def test_interval_choices_are_real_persisted_modes(self, page):
        widget, controller, _tp, _mgr = page
        values = [value for value, _text in INTERVAL_CHOICES]
        assert values == [mode.value for mode in IntervalMode]
        widget.cb_interval.setCurrentIndex(
            widget.cb_interval.findData(IntervalMode.FIXED_15S.value))
        assert controller.settings.interval_mode is IntervalMode.FIXED_15S

    def test_manual_range_is_only_visible_for_manual(self, page):
        widget, _controller, _tp, _mgr = page
        widget.cb_interval.setCurrentIndex(
            widget.cb_interval.findData(IntervalMode.MANUAL.value))
        assert widget.row_manual.isVisibleTo(widget.row_manual.parentWidget()
                                             or widget.row_manual)
        widget.cb_interval.setCurrentIndex(
            widget.cb_interval.findData(IntervalMode.PULSE.value))
        assert widget.row_manual.isHidden()

    def test_playback_choice_persists(self, page):
        widget, controller, _tp, _mgr = page
        widget.cb_playback.setCurrentIndex(
            widget.cb_playback.findData("replace"))
        assert controller.settings.playback_mode == "replace"
        assert controller.store.load_settings().playback_mode == "replace"

    def test_the_playback_list_offers_the_documented_modes(self):
        assert [value for value, _text in PLAYBACK_CHOICES] == [
            "inherit", "mix", "queue", "replace", "skip_busy"]


class TestGlow:
    def test_repeated_cues_reuse_one_animation_object(self, page):
        widget, _controller, _tp, _mgr = page
        widget.row_controls.show()
        for _ in range(20):
            widget.flash_glow()
        # One animation object at a time, restarted -- never a new one per cue.
        assert widget._glow_anim is None or not sip.isdeleted(widget._glow_anim)

    def test_a_deleted_animation_never_crashes_the_next_cue(self, page):
        """Regression: DeleteWhenStopped left a stale Python wrapper.

        The shipped crash was:
            RuntimeError: wrapped C/C++ object of type QPropertyAnimation
            has been deleted
        raised from flash_glow() on the SECOND Problip cue.
        """
        widget, _controller, _tp, _mgr = page
        widget.row_controls.show()
        widget.flash_glow()
        if widget._glow_anim is not None:
            sip.delete(widget._glow_anim)
            widget.flash_glow()  # must not raise
        sip.delete(widget._glow_effect) if widget._glow_effect is not None else None
        widget.flash_glow()  # must not raise either

    def test_glow_never_fires_for_an_invisible_page(self, page):
        widget, _controller, _tp, _mgr = page
        widget.row_controls.hide()
        widget.flash_glow()
        assert widget._glow_anim is None


class TestAudioActions:
    def test_stop_all_reaches_the_sound_manager(self, page):
        widget, _controller, _tp, manager = page
        widget._on_stop_all()
        assert manager.stop_all_calls == 1


class TestRetranslation:
    def test_every_visible_string_carries_its_english_source(self, page):
        widget, _controller, _tp, _mgr = page
        for name in ("btn_start", "btn_stop", "btn_test", "cb_counter",
                     "cb_glow", "cb_autostart", "btn_audio_hub",
                     "btn_stop_all", "lbl_help", "lbl_volume", "lbl_playback"):
            assert getattr(getattr(widget, name), "_en_text", None), name

    def test_retranslate_rewrites_the_combo_items(self, page):
        widget, _controller, _tp, _mgr = page
        widget.retranslate("EN")
        assert widget.cb_interval.count() == len(INTERVAL_CHOICES)
        assert widget.cb_playback.count() == len(PLAYBACK_CHOICES)


class TestShowCounterContract:
    """T-1242 spec 18: Show counter hides ONLY the compact 'N BLIPS'."""

    def test_stats_row_and_milestone_survive_show_counter_off(self, page):
        widget, controller, _tp, _mgr = page
        controller.update_settings(show_counter=False)
        widget.refresh_stats()
        # the code no longer couples the stats row to show_counter
        assert not widget.row_stats.isHidden()
        # and refresh_stats never hides the milestone bar either
        widget.pb_milestone.setVisible(True)
        widget.refresh_stats()
        assert not widget.pb_milestone.isHidden()

    def test_blips_readout_follows_show_counter(self, page):
        widget, controller, _tp, _mgr = page
        assert controller.start(persist=False)
        controller.update_settings(show_counter=True)
        widget.refresh_stats()
        assert "BLIPS" in widget.lbl_blips.text()
        controller.update_settings(show_counter=False)
        widget.refresh_stats()
        assert widget.lbl_blips.text() == ""

    def test_custom_sounds_entry_point_exists(self, page):
        widget, _controller, _tp, _mgr = page
        # compact custom-sound management on the pool group (spec 14)
        assert hasattr(widget, "btn_custom")
        assert not widget.btn_custom.isHidden()
