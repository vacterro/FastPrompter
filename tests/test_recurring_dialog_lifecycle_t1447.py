"""T-1447 regression tests: recurring-dialog lifecycle leak elimination.

Verifies lifecycle contract for TimerDialog and SoundSettingsDialog:
- While visible: intended recurring timer runs (1 Hz for TimerDialog, 400 ms for SoundSettingsDialog).
- After accept, reject, close, or modal finish: recurring timers stop immediately, 0 post-close callbacks.
- Temporary finished dialog scheduled for deletion by owner; repeated open/finish cycles do not accumulate.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from _qt_retire import retire  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog  # noqa: E402
from fastprompter.ui.timer_dialog import TimerDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _FakePomo:
    breaks_enabled = True
    repeat_alarm = False
    running = False
    state = "idle"
    phase = "work"
    alarm_pending = False
    remaining = 0
    work_seconds = 25 * 60
    break_seconds = 5 * 60

    def describe(self):
        return ""

    def apply_durations(self, **kw):
        pass

    def toggle(self):
        pass

    def reset(self):
        pass

    def skip_phase(self):
        pass

    def on_productivity_changed(self):
        pass


class _FakeMain(QWidget):
    def __init__(self):
        super().__init__()
        self.timers = []
        self.data = {"theme": "Default"}
        self._current_lang = "EN"
        self.sound_manager = SoundManager(None, {})
        self.productivity_timer = _FakePomo()
        self.saved = 0
        self.tested = []
        self.label_updates = 0
        self.temp_configs = []

    def styleSheet(self):
        return ""

    def save_timers_to_data(self):
        self.saved += 1
        self.data["timers"] = [timer.to_dict() for timer in self.timers]

    def mark_dirty(self, *_args):
        self.dirty = True

    def _update_timer_label(self):
        self.label_updates += 1

    def save_productivity_timer(self):
        pass

    def on_productivity_changed(self):
        pass

    def test_timer_notification(self, timer, delay):
        self.tested.append((timer, delay))

    def configure_temp_timer(self, settings):
        self.temp_configs.append(settings)


@pytest.fixture()
def timer_host():
    host = _FakeMain()
    host.show()
    _APP.processEvents()
    yield host
    retire(host)


@pytest.fixture()
def sound_fixture():
    host = QWidget()
    host.show()
    _APP.processEvents()
    data = {"theme": "Golden Default", "sounds": {}}
    manager = SoundManager(host, data)
    manager._hub = AudioHub(transport=FakeMultiChannelTransport())
    yield host, data, manager
    manager.shutdown()
    retire(host)


# ======================================================================
# TimerDialog Lifecycle Tests (Cases 1 - 8)
# ======================================================================

def test_timer_dialog_timer_active_while_open(timer_host):
    """Case 1: TimerDialog 1 Hz _tick timer is active while open."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._tick.isActive() is True
        assert dialog.isVisible() is True
    finally:
        retire(dialog)


def test_timer_dialog_accept_stops_tick(timer_host):
    """Case 2: accept() immediately stops _tick."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._tick.isActive() is True

        dialog.accept()
        _APP.processEvents()

        assert dialog._tick.isActive() is False
        assert dialog.isVisible() is False
    finally:
        retire(dialog)


def test_timer_dialog_close_button_click_stops_tick(timer_host):
    """Case 3: Actual Close-button click stops _tick."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._tick.isActive() is True

        # Find the Close button
        close_buttons = [
            btn for btn in dialog.findChildren(QPushButton)
            if "Close" in btn.text()
        ]
        assert len(close_buttons) >= 1
        close_btn = close_buttons[0]

        close_btn.click()
        _APP.processEvents()

        assert dialog._tick.isActive() is False
        assert dialog.isVisible() is False
    finally:
        retire(dialog)


def test_timer_dialog_close_event_stops_tick(timer_host):
    """Case 4: Window close / close() path stops _tick."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._tick.isActive() is True

        dialog.close()
        _APP.processEvents()

        assert dialog._tick.isActive() is False
        assert dialog.isVisible() is False
    finally:
        retire(dialog)


def test_timer_dialog_no_callbacks_post_accept(timer_host):
    """Case 5: Zero timeout callbacks occur for >=2 former intervals after accept."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()

        callbacks = []
        dialog._tick.timeout.connect(lambda: callbacks.append(time.monotonic()))

        # Wait to witness at least one tick while visible
        QTest.qWait(1100)
        assert len(callbacks) >= 1

        # Accept
        dialog.accept()
        _APP.processEvents()
        assert dialog._tick.isActive() is False

        count_at_accept = len(callbacks)
        # Wait 2200 ms (>= 2 intervals)
        QTest.qWait(2200)

        assert len(callbacks) - count_at_accept == 0
    finally:
        retire(dialog)


def test_timer_dialog_temp_settings_synced_on_finish(timer_host):
    """Case 6: Temp Timer final settings synchronization occurs exactly once on finish."""
    dialog = TimerDialog(timer_host)
    try:
        dialog.show()
        _APP.processEvents()

        # Both accept() and closeEvent() should not duplicate sync
        initial_configs = len(timer_host.temp_configs)
        dialog.accept()
        _APP.processEvents()

        assert len(timer_host.temp_configs) == initial_configs + 1

        # Subsequent closeEvent on the same instance is idempotent
        dialog.close()
        _APP.processEvents()
        assert len(timer_host.temp_configs) == initial_configs + 1
    finally:
        retire(dialog)


def test_timer_dialog_repeated_open_accept_delete_no_accumulation(timer_host):
    """Case 7: Repeated open/accept/delete cycles do not accumulate children or timers."""
    for _ in range(10):
        dialog = TimerDialog(timer_host)
        dialog.show()
        _APP.processEvents()
        dialog.accept()
        dialog.deleteLater()
        _APP.processEvents()

    # Deliver DeferredDelete
    _APP.sendPostedEvents(None, 52)  # DeferredDelete
    _APP.processEvents()

    retained_dialogs = [
        c for c in timer_host.children()
        if isinstance(c, TimerDialog) and not sip.isdeleted(c)
    ]
    active_timers = [
        d._tick for d in retained_dialogs
        if hasattr(d, "_tick") and not sip.isdeleted(d._tick) and d._tick.isActive()
    ]
    assert len(active_timers) == 0


def test_timer_dialog_fresh_instance_works_after_retirement(timer_host):
    """Case 8: Fresh TimerDialog operates normally after retiring previous dialog."""
    d1 = TimerDialog(timer_host)
    d1.show()
    _APP.processEvents()
    d1.accept()
    retire(d1)

    d2 = TimerDialog(timer_host)
    try:
        d2.show()
        _APP.processEvents()
        assert d2._tick.isActive() is True
        assert d2.isVisible() is True

        ticks = []
        d2._tick.timeout.connect(lambda: ticks.append(1))
        QTest.qWait(1100)
        assert len(ticks) >= 1
    finally:
        retire(d2)


# ======================================================================
# SoundSettingsDialog Lifecycle Tests (Cases 9 - 17)
# ======================================================================

def test_sound_settings_poll_active_while_open(sound_fixture):
    """Case 9: _master_poll 400ms timer is active while open."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._master_poll.isActive() is True
        assert dialog.isVisible() is True
    finally:
        retire(dialog)


def test_sound_settings_accept_stops_master_poll(sound_fixture):
    """Case 10: accept() stops _master_poll."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._master_poll.isActive() is True

        dialog.accept()
        _APP.processEvents()

        assert dialog._master_poll.isActive() is False
        assert dialog.isVisible() is False
    finally:
        retire(dialog)


def test_sound_settings_window_close_stops_master_poll(sound_fixture):
    """Case 11: Window close / close() stops _master_poll."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog.show()
        _APP.processEvents()
        assert dialog._master_poll.isActive() is True

        dialog.close()
        _APP.processEvents()

        assert dialog._master_poll.isActive() is False
        assert dialog.isVisible() is False
    finally:
        retire(dialog)


def test_sound_settings_no_poll_callbacks_post_finish(sound_fixture):
    """Case 12: Zero poll callbacks after finish for >=2-3 former intervals."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog.show()
        _APP.processEvents()

        polls = []
        dialog._master_poll.timeout.connect(lambda: polls.append(time.monotonic()))

        # Witness at least 1 poll while visible
        QTest.qWait(500)
        assert len(polls) >= 1

        # Finish
        dialog.accept()
        _APP.processEvents()
        assert dialog._master_poll.isActive() is False

        count_at_finish = len(polls)
        # Wait 1000 ms (2.5 intervals of 400 ms)
        QTest.qWait(1000)

        assert len(polls) - count_at_finish == 0
    finally:
        retire(dialog)


def test_sound_settings_done_clears_last_instance(sound_fixture):
    """Case 13: done() clears _LAST_INSTANCE registration."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        assert SoundSettingsDialog._LAST_INSTANCE is dialog
        dialog.done(0)
        assert SoundSettingsDialog._LAST_INSTANCE is None
    finally:
        retire(dialog)


def test_sound_settings_repeated_open_accept_retirement_no_accumulation(sound_fixture):
    """Case 14: Repeated open_canonical -> accept -> retirement leaves no accumulating children or polls."""
    host, data, manager = sound_fixture
    for _ in range(8):
        dialog = SoundSettingsDialog.open_canonical(host, data, manager)
        dialog.show()
        _APP.processEvents()
        dialog.accept()
        dialog.deleteLater()
        _APP.processEvents()

    _APP.sendPostedEvents(None, 52)  # DeferredDelete
    _APP.processEvents()

    retained_dialogs = [
        c for c in host.children()
        if isinstance(c, SoundSettingsDialog) and not sip.isdeleted(c)
    ]
    active_polls = [
        d._master_poll for d in retained_dialogs
        if hasattr(d, "_master_poll") and not sip.isdeleted(d._master_poll) and d._master_poll.isActive()
    ]
    assert len(active_polls) == 0


def test_sound_settings_fresh_canonical_instance_after_retirement(sound_fixture):
    """Case 15: Fresh canonical instance created after previous retirement."""
    host, data, manager = sound_fixture
    d1 = SoundSettingsDialog.open_canonical(host, data, manager)
    d1.show()
    _APP.processEvents()
    d1.accept()
    retire(d1)

    assert SoundSettingsDialog._LAST_INSTANCE is None

    d2 = SoundSettingsDialog.open_canonical(host, data, manager)
    try:
        assert d2 is not d1
        assert SoundSettingsDialog._LAST_INSTANCE is d2
        assert d2._master_poll.isActive() is True
    finally:
        retire(d2)


def test_sound_settings_canonical_reuses_live_instance(sound_fixture):
    """Case 16: While a canonical instance is genuinely live, open_canonical reuses/raises it."""
    host, data, manager = sound_fixture
    d1 = SoundSettingsDialog.open_canonical(host, data, manager)
    try:
        assert SoundSettingsDialog._LAST_INSTANCE is d1
        d2 = SoundSettingsDialog.open_canonical(host, data, manager)
        assert d2 is d1
    finally:
        retire(d1)


def test_sound_settings_fake_audio_shutdown_clean(sound_fixture):
    """Case 17: AudioHub/SoundManager shutdown remains clean."""
    host, data, manager = sound_fixture
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog.accept()
        manager.shutdown()
        assert manager._closed is True
        assert manager._poll_timer.isActive() is False
    finally:
        retire(dialog)
