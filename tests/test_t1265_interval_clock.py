"""T-1265 C1: the Interval Notifications dial is a CLOCK first.

The widget always drew live hands, but its centre was occupied by the interval
configuration (``\U0001f514 1h (:00)`` / ``every 30m``) and a filled pie sector
covering up to half the face. Asked "what time is it?", the dial answered
"every 30 minutes" - and the sector made it read as a schedule pie chart.

What changed is PRESENTATION ONLY:

* the current local time is printed in the dial, ``HH:mm:ss``, as the largest
  thing on the face;
* the interval caption is demoted to small dim text below centre;
* the interval pie sector is gone.

What did NOT change: the scheduler, the firing boundaries, and the saved
``minutes`` / ``align_mode`` / ``start_minute`` / ``end_minute`` values. The
spinbox, alignment combo, quick buttons, active-hours controls and rule list
remain the authoritative interval UI.
"""

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.ui.analog_clock import BigAnalogClock  # noqa: E402

_APP = QApplication.instance() or QApplication([])


#: Parents are kept alive on purpose: a QWidget host that falls out of scope
#: takes its children's C++ objects with it, and every later call then raises
#: "wrapped C/C++ object ... has been deleted" instead of testing anything.
_HOSTS = []


def _clock(size=150):
    host = QWidget()
    _HOSTS.append(host)
    clock = BigAnalogClock(None, host, size=size)
    clock.resize(size, size)
    return clock


def _at(clock, *args):
    clock.set_now_provider(lambda: datetime.datetime(*args))
    return clock


def _advancing(start, step=datetime.timedelta(seconds=1)):
    """A now-provider that returns a LATER instant on every call.

    Returns ``(provider, calls)``; ``calls`` grows by one entry per
    invocation, so a test can assert how many samples one paint took.
    """
    calls = []

    def provider():
        value = start + step * len(calls)
        calls.append(value)
        return value

    return provider, calls


def _render(clock):
    pixmap = QPixmap(clock.size())
    clock.render(pixmap)
    return pixmap.toImage()


class TestDigitalTime:
    def test_the_dial_prints_the_supplied_time(self):
        clock = _at(_clock(), 2026, 9, 14, 13, 5, 9)
        assert clock.current_time_text() == "13:05:09"

    def test_a_second_change_updates_the_display(self):
        clock = _clock()
        moments = iter([
            datetime.datetime(2026, 9, 14, 8, 30, 0),
            datetime.datetime(2026, 9, 14, 8, 30, 1),
        ])
        clock.set_now_provider(lambda: next(moments))
        assert clock.current_time_text() == "08:30:00"
        assert clock.current_time_text() == "08:30:01"

    def test_midnight_and_noon_stay_two_digit(self):
        assert _at(_clock(), 2026, 9, 14, 0, 0, 0).current_time_text() == "00:00:00"
        assert _at(_clock(), 2026, 9, 14, 12, 0, 0).current_time_text() == "12:00:00"

    def test_without_seconds_the_face_drops_them(self):
        clock = _at(_clock(), 2026, 9, 14, 21, 7, 42)
        clock._show_seconds = False
        assert clock.current_time_text() == "21:07"

    def test_production_still_reads_the_wall_clock(self):
        """No provider = ``datetime.now()``; the injection is test-only."""
        clock = _clock()
        before = datetime.datetime.now()
        shown = clock.now()
        after = datetime.datetime.now()
        assert before <= shown <= after


class TestHandsFollowTheSameInstant:
    def test_hands_and_digits_read_one_source(self):
        """Both go through ``now()``, so they cannot disagree."""
        clock = _at(_clock(), 2026, 9, 14, 3, 0, 0)
        three = _render(clock)
        assert clock.current_time_text() == "03:00:00"

        _at(clock, 2026, 9, 14, 9, 0, 0)
        nine = _render(clock)
        assert clock.current_time_text() == "09:00:00"

        # Different times must paint differently: if the hands ignored the
        # provider, these two images would be identical.
        assert three != nine

    def test_one_paint_frame_samples_the_clock_exactly_once(self):
        """T-1265 B1 regression: one frame, one instant.

        ``paintEvent`` sampled ``now()`` for the hands and then called
        ``current_time_text()``, which sampled ``now()`` AGAIN. Two samples
        straddling a second boundary painted the hands at second N and the
        digits at second N+1 in the same frame. A constant provider can never
        show that, so this one ADVANCES on every call.
        """
        clock = _clock()
        provider, calls = _advancing(datetime.datetime(2026, 9, 14, 10, 10, 10))
        clock.set_now_provider(provider)
        calls.clear()
        _render(clock)
        assert len(calls) == 1, calls

    def test_the_digits_are_formatted_from_the_hands_own_sample(self):
        """The instant the hands use IS the instant the digits print.

        ``paintEvent`` now hands its single sample to ``current_time_text``;
        a text that re-sampled would show a different second. The spy records
        the exact argument the paint passed, so the two can be compared
        directly instead of through pixels.
        """
        from fastprompter.ui.analog_clock import BigAnalogClock

        clock = _clock()
        provider, calls = _advancing(datetime.datetime(2026, 9, 14, 10, 10, 10))
        clock.set_now_provider(provider)
        received = []
        original = BigAnalogClock.current_time_text

        def spy(self, now=None):
            received.append(now)
            return original(self, now)

        BigAnalogClock.current_time_text = spy
        try:
            calls.clear()
            _render(clock)
        finally:
            BigAnalogClock.current_time_text = original

        assert len(calls) == 1, calls          # one sample for the frame
        assert received == [calls[0]]          # and the digits got THAT one
        assert original(clock, calls[0]) == "10:10:10"

    def test_one_second_of_movement_is_visible(self):
        clock = _at(_clock(), 2026, 9, 14, 10, 10, 10)
        first = _render(clock)
        _at(clock, 2026, 9, 14, 10, 10, 11)
        assert _render(clock) != first


class TestIntervalIsSecondaryButIntact:
    def test_changing_the_interval_does_not_touch_the_displayed_time(self):
        clock = _at(_clock(), 2026, 9, 14, 16, 45, 30)
        assert clock.current_time_text() == "16:45:30"
        for minutes, align in ((15, "clock"), (30, "elapsed"), (120, "clock")):
            clock.set_interval(minutes, align)
            assert clock.current_time_text() == "16:45:30"

    def test_the_interval_configuration_still_round_trips(self):
        clock = _clock()
        clock.set_interval(45, "elapsed")
        assert clock._interval_minutes == 45
        assert clock._align_mode == "elapsed"
        clock.set_interval(120, "clock")
        assert clock._interval_minutes == 120
        assert clock._align_mode == "clock"

    def test_the_interval_caption_still_describes_the_interval(self):
        clock = _clock()
        clock.set_interval(30, "clock")
        assert clock.interval_text() == "every 30m"
        clock.set_interval(60, "clock")
        assert clock.interval_text() == "1h (:00)"
        clock.set_interval(120, "clock")
        assert clock.interval_text() == "2h (:00)"
        clock.set_interval(120, "elapsed")
        assert clock.interval_text() == "every 2h"

    def test_a_bad_interval_value_falls_back_without_raising(self):
        clock = _clock()
        clock.set_interval("nonsense", "clock")
        assert clock._interval_minutes == 60

    def test_the_dial_still_picks_an_interval_on_click(self):
        """Interactive interval picking survives the presentation change."""
        from PyQt6.QtCore import QPointF
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtGui import QMouseEvent

        clock = _at(_clock(200), 2026, 9, 14, 16, 45, 30)
        clock.resize(200, 200)
        seen = []
        clock.intervalChanged.connect(seen.append)
        centre = clock.rect().center()
        # straight down from the centre = the 30-minute mark
        point = QPointF(centre.x(), centre.y() + 70)
        clock.mousePressEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, point,
            _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton,
            _Qt.KeyboardModifier.NoModifier))
        assert seen == [30]
        assert clock._interval_minutes == 30
        # and the time it shows is still the time
        assert clock.current_time_text() == "16:45:30"


class TestRendering:
    def test_every_hour_of_the_day_paints_without_raising(self):
        clock = _clock()
        for hour in range(24):
            _at(clock, 2026, 9, 14, hour, 37, 12)
            assert not _render(clock).isNull()
