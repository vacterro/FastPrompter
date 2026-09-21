"""T-1238-I: ambience rules, multi-layer, fades, weather failure policy."""

from __future__ import annotations

import datetime as dt

from fastprompter.core.ambience_engine import (
    REPEAT_EVERY_INTERVAL,
    REPEAT_LOOP,
    REPEAT_ON_ENTER,
    TRIGGER_ALWAYS,
    TRIGGER_TIME_WINDOW,
    TRIGGER_WEATHER,
    TRIGGER_WEEKDAY,
    WEATHER_STALE_S,
    AmbienceEngine,
    AmbienceRule,
    StaticWeatherProvider,
    in_time_window,
)


class _Result:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.outcome = "PLAYED"
        self.request_id = channel


class RecordingHub:
    """Hub double implementing the long-lived-channel contract (C0.8).

    It records what was started, which handles were physically stopped and
    every volume mutation, so a test can assert on real channel state instead
    of the engine's own bookkeeping.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, float]] = []
        self.loops: list[bool] = []
        self.stopped_layers: list[str] = []
        self.volume_calls: list[tuple[str, float]] = []
        self.live: dict[str, dict] = {}

    def start_channel(self, path, *, event="", bus="ambience", volume=1.0,
                      loop=False):
        self.entries.append((event, path, volume))
        self.loops.append(bool(loop))
        handle = f"h{len(self.entries)}"
        self.live[handle] = {"path": path, "event": event, "volume": volume,
                             "loop": bool(loop)}
        return _Result(handle)

    def stop_channel_handle(self, handle):
        self.stopped_layers.append(handle)
        self.live.pop(handle, None)

    def set_channel_volume(self, handle, volume):
        self.volume_calls.append((handle, float(volume)))
        if handle in self.live:
            self.live[handle]["volume"] = float(volume)

    def channel_alive(self, handle):
        return bool(handle) and handle in self.live


def _rule(**kwargs) -> AmbienceRule:
    base = dict(id="r1", name="Always ambience", sound_ref="ambience.wav",
                volume=0.8, trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                enabled=True, fade_in_ms=0, fade_out_ms=0)
    base.update(kwargs)
    return AmbienceRule(**base)


SUNDAY_10AM = dt.datetime(2026, 9, 6, 10, 0)  # a Sunday
MONDAY_10AM = dt.datetime(2026, 9, 7, 10, 0)


class TestAlwaysLoop:
    def test_always_loop_starts_and_stays_active(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule()])
        assert engine.evaluate(now=SUNDAY_10AM) == ["r1"]
        assert engine.is_active("r1")
        # Still active on later sweeps (no duplicate start).
        assert engine.evaluate(now=SUNDAY_10AM) == []
        assert len(hub.entries) == 1

    def test_disabled_rule_never_starts(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(enabled=False)])
        assert engine.evaluate(now=SUNDAY_10AM) == []
        assert not engine.is_active("r1")


class TestTimeWindow:
    def test_time_window_enters_and_exits(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(
            id="tw", trigger=TRIGGER_TIME_WINDOW, start="09:00", end="12:00")])
        assert engine.evaluate(now=SUNDAY_10AM.replace(hour=8)) == []
        assert engine.evaluate(now=SUNDAY_10AM) == ["tw"]
        # Exit is itself a reported transition; the layer fades and stops.
        assert engine.evaluate(now=SUNDAY_10AM.replace(hour=13)) == ["tw"]
        assert not engine.is_active("tw")
        # Settled: no further transitions.
        assert engine.evaluate(now=SUNDAY_10AM.replace(hour=14)) == []

    def test_overnight_window(self):
        assert in_time_window(23 * 60, "22:00", "06:00")
        assert in_time_window(2 * 60, "22:00", "06:00")
        assert not in_time_window(12 * 60, "22:00", "06:00")

    def test_weekday_scoped_time_window(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(
            id="wd", trigger=TRIGGER_TIME_WINDOW, start="09:00", end="12:00",
            weekdays=["sunday"])])
        assert engine.evaluate(now=MONDAY_10AM) == []
        assert engine.evaluate(now=SUNDAY_10AM) == ["wd"]


class TestWeekday:
    def test_sunday_rule(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="sun", trigger=TRIGGER_WEEKDAY,
                                weekday="sunday")])
        assert engine.evaluate(now=SUNDAY_10AM) == ["sun"]
        # Monday: rule exits (reported), layer stops.
        assert engine.evaluate(now=MONDAY_10AM) == ["sun"]
        assert not engine.is_active("sun")


class TestWeather:
    def test_rain_starts_rain_layer(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        engine.refresh_weather(now=0.0)
        engine.set_rules([_rule(id="rain", trigger=TRIGGER_WEATHER,
                                weather="rain")])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["rain"]

    def test_clear_fades_rain_and_starts_clear_layer(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        engine.refresh_weather(now=0.0)
        engine.set_rules([
            _rule(id="rain", trigger=TRIGGER_WEATHER, weather="rain"),
            _rule(id="clear", trigger=TRIGGER_WEATHER, weather="clear"),
        ])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["rain"]
        # Weather changes to clear.
        engine.configure_weather(StaticWeatherProvider("clear"), enabled=True)
        engine.refresh_weather(now=WEATHER_STALE_S / 2)
        changed = engine.evaluate(now=SUNDAY_10AM, monotonic=WEATHER_STALE_S / 2)
        # Rules evaluated in order: rain exits first, clear starts after.
        assert changed == ["rain", "clear"]
        assert not engine.is_active("rain")
        assert engine.is_active("clear")

    def test_stale_weather_does_not_guess(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        engine.refresh_weather(now=0.0)
        # Far past stale window: condition unusable.
        assert engine.weather_condition(now=WEATHER_STALE_S + 1) is None
        engine.set_rules([_rule(id="rain", trigger=TRIGGER_WEATHER,
                                weather="rain")])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=WEATHER_STALE_S + 1) == []

    def test_always_plus_rain_both_active(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        engine.refresh_weather(now=0.0)
        engine.set_rules([
            _rule(id="base", trigger=TRIGGER_ALWAYS),
            _rule(id="rain", trigger=TRIGGER_WEATHER, weather="rain"),
        ])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == ["base", "rain"]
        assert engine.active_rules() == ["base", "rain"]

    def test_each_layer_has_own_volume(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        engine.refresh_weather(now=0.0)
        engine.set_rules([
            _rule(id="base", volume=0.5),
            _rule(id="rain", trigger=TRIGGER_WEATHER, weather="rain",
                  volume=0.25),
        ])
        engine.evaluate(now=SUNDAY_10AM, monotonic=0.0)
        volumes = {event: vol for event, _p, vol in hub.entries}
        assert volumes["ambience:base"] == 0.5
        assert volumes["ambience:rain"] == 0.25


class TestStopPause:
    def test_stop_ambience_stops_all_but_not_transient(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="base")])
        engine.evaluate(now=SUNDAY_10AM)
        handle = hub.entries and "h1"
        engine.stop_ambience()
        assert engine.active_rules() == []
        # C0.10: the physical channel is gone, not merely forgotten.
        assert handle in hub.stopped_layers
        assert hub.live == {}

    def test_pause_preserves_rules_and_resume_re_evaluates(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="base")])
        engine.evaluate(now=SUNDAY_10AM)
        engine.pause()
        assert engine.active_rules() == []
        assert hub.live == {}  # pause is physically silent, not just logical
        engine.resume()
        # Fresh evaluation on resume; exactly one new start, no flood.
        assert engine.evaluate(now=SUNDAY_10AM) == ["base"]
        assert len(hub.entries) == 2

    def test_on_enter_fires_once_per_transition(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(id="oe", trigger=TRIGGER_WEEKDAY,
                                weekday="sunday", repeat=REPEAT_ON_ENTER)])
        assert engine.evaluate(now=SUNDAY_10AM) == ["oe"]
        assert engine.evaluate(now=SUNDAY_10AM) == []
        engine.configure_weather(None, enabled=False)
        engine.pause()
        engine.resume()
        # ON_ENTER only re-fires on a false->true transition, not on resume.

    def test_every_interval_replays_after_interval(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        clock = {"t": 100.0}
        engine = AmbienceEngine(hub, clock=lambda: clock["t"])
        engine.set_rules([_rule(id="per", repeat=REPEAT_EVERY_INTERVAL,
                                interval_seconds=60)])
        assert engine.evaluate(now=SUNDAY_10AM) == ["per"]
        clock["t"] = 130.0
        assert engine.evaluate(now=SUNDAY_10AM) == []  # not yet
        clock["t"] = 161.0
        assert engine.evaluate(now=SUNDAY_10AM) == ["per"]


class TestWeatherFailure:
    def test_timeout_keeps_last_known_then_stales(self):
        class FlakyProvider:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self):
                self.calls += 1
                if self.calls == 1:
                    return "rain"
                raise TimeoutError("network down")

        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        provider = FlakyProvider()
        engine.configure_weather(provider, enabled=True)
        assert engine.refresh_weather(now=0.0) == "rain"
        # Two repeated timeouts: last known result kept, no exception leaks.
        assert engine.refresh_weather(now=60.0) == "rain"
        assert engine.refresh_weather(now=120.0) == "rain"
        assert provider.calls == 3
        # Past stale window: refuses to guess new conditions.
        assert engine.refresh_weather(now=WEATHER_STALE_S + 120) is None

    def test_no_duplicate_players_for_repeated_identical_triggers(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        engine.configure_weather(StaticWeatherProvider("rain"), enabled=True)
        for _ in range(10):
            engine.refresh_weather(now=0.0)
        engine.set_rules([_rule(id="rain", trigger=TRIGGER_WEATHER,
                                weather="rain")])
        engine.evaluate(now=SUNDAY_10AM, monotonic=0.0)
        engine.evaluate(now=SUNDAY_10AM, monotonic=1.0)
        engine.evaluate(now=SUNDAY_10AM, monotonic=2.0)
        assert len(hub.entries) == 1  # one layer, no flood

    def test_success_clear_after_failures_transitions(self):
        class RecoveryProvider:
            def __init__(self) -> None:
                self.state = "fail"

            def fetch(self):
                if self.state == "fail":
                    return None
                return self.state

        hub = RecordingHub()
        engine = AmbienceEngine(hub)
        provider = RecoveryProvider()
        engine.configure_weather(provider, enabled=True)
        engine.refresh_weather(now=0.0)
        engine.set_rules([
            _rule(id="rain", trigger=TRIGGER_WEATHER, weather="rain"),
            _rule(id="clear", trigger=TRIGGER_WEATHER, weather="clear"),
        ])
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=0.0) == []
        provider.state = "clear"
        engine.refresh_weather(now=1.0)
        assert engine.evaluate(now=SUNDAY_10AM, monotonic=1.0) == ["clear"]
