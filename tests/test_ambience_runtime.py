"""T-1238-C3.9..C3.12 + E1: ambience persistence, weather and the runtime.

The engine is pure; this suite proves the parts around it -- rules survive a
restart in ``audio.db``, weather is opt-in with a user-typed location, the
provider maps real WMO codes and never guesses on failure, and the controller
owns exactly one evaluation timer, one fade driver and one weather refresh.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.ambience_engine import (  # noqa: E402
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    TRIGGER_WEATHER,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.ambience_store import (  # noqa: E402
    AmbienceStore,
    new_rule_id,
    rule_templates,
)
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    PlaybackMode,
)
from fastprompter.core.weather import (  # noqa: E402
    OpenMeteoWeatherProvider,
    build_url,
    condition_for_code,
    parse_response,
    provider_for,
)
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    def __init__(self, hub) -> None:
        self._hub = hub

    def audio_hub(self):
        return self._hub


def _rule(**kwargs) -> AmbienceRule:
    base = dict(id=new_rule_id(), name="Rain", sound_ref="rain.wav",
                volume=0.5, trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                enabled=True, fade_in_ms=0, fade_out_ms=0)
    base.update(kwargs)
    return AmbienceRule(**base)


# ---------------------------------------------------------------------------
# C3.10 -- persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_rules_survive_a_restart_with_stable_ids(self, tmp_path):
        path = str(tmp_path / "audio.db")
        rule = _rule(name="Night", volume=0.3, fade_in_ms=750)
        AmbienceStore(path).save_rules([rule])
        loaded = AmbienceStore(path).load_rules()
        assert len(loaded) == 1
        assert loaded[0].id == rule.id
        assert loaded[0].name == "Night"
        assert loaded[0].volume == pytest.approx(0.3)
        assert loaded[0].fade_in_ms == 750

    def test_nothing_transient_is_persisted(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.save_rules([_rule()])
        payload = store.load_rules()[0].to_dict()
        for forbidden in ("handle", "channel", "fade_tick", "fade_elapsed_ms",
                          "timer"):
            assert forbidden not in payload

    def test_it_lives_in_audio_db_not_a_profile(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        assert store.db_path.endswith("audio.db")

    def test_upsert_delete_duplicate(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        rule = _rule(name="One")
        store.upsert_rule(rule)
        rule.name = "Renamed"
        assert store.upsert_rule(rule)[0].name == "Renamed"
        assert len(store.duplicate_rule(rule.id)) == 2
        assert len(store.delete_rule(rule.id)) == 1

    def test_a_corrupt_row_is_skipped_not_guessed(self, tmp_path):
        path = str(tmp_path / "audio.db")
        store = AmbienceStore(path)
        store.save_rules([_rule(name="Good")])
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO ambience_rules_v1(id, position, payload) "
                "VALUES('broken', 9, 'not json')")
        rules = AmbienceStore(path).load_rules()
        assert [r.name for r in rules] == ["Good"]

    def test_templates_ship_disabled_and_soundless(self):
        for rule in rule_templates():
            assert rule.enabled is False
            assert rule.sound_ref == ""


class TestWeatherConfig:
    def test_weather_is_off_until_opted_in(self, tmp_path):
        config = AmbienceStore(str(tmp_path / "audio.db")).weather_config()
        assert config["enabled"] is False
        assert config["latitude"] is None

    def test_enabling_without_a_location_is_refused(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        config = store.set_weather_config(enabled=True, label="Nowhere")
        assert config["enabled"] is False

    def test_a_configured_location_persists(self, tmp_path):
        path = str(tmp_path / "audio.db")
        AmbienceStore(path).set_weather_config(
            enabled=True, label="Tallinn", latitude=59.437, longitude=24.7536)
        config = AmbienceStore(path).weather_config()
        assert config["enabled"] is True
        assert config["label"] == "Tallinn"
        assert config["latitude"] == pytest.approx(59.437)


# ---------------------------------------------------------------------------
# C3.11 -- the real provider
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _limit=None):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestWeatherProvider:
    @pytest.mark.parametrize("code,expected", [
        (0, "clear"), (3, "cloudy"), (55, "drizzle"), (65, "rain"),
        (75, "snow"), (95, "thunderstorm"), (4242, None),
    ])
    def test_wmo_codes_map_to_the_six_conditions(self, code, expected):
        assert condition_for_code(code) == expected

    def test_the_url_carries_only_the_configured_coordinates(self):
        url = build_url(59.437, 24.7536)
        assert "latitude=59.4370" in url and "longitude=24.7536" in url
        assert "current=weather_code" in url

    def test_a_real_response_body_parses(self):
        assert parse_response({"current": {"weather_code": 61}}) == "rain"
        assert parse_response({"current_weather": {"weathercode": 0}}) == "clear"
        assert parse_response({}) is None

    def test_a_network_failure_is_none_not_a_guess(self):
        def _boom(*_a, **_k):
            raise OSError("no network")

        provider = OpenMeteoWeatherProvider(1.0, 2.0, opener=_boom)
        assert provider.fetch() is None
        assert provider.last_error

    def test_a_successful_fetch_returns_the_condition(self):
        payload = b'{"current": {"weather_code": 71}}'
        provider = OpenMeteoWeatherProvider(
            1.0, 2.0, opener=lambda *_a, **_k: _FakeResponse(payload))
        assert provider.fetch() == "snow"

    def test_no_provider_without_an_opt_in(self):
        assert provider_for({"enabled": False, "latitude": 1, "longitude": 2}) is None
        assert provider_for({"enabled": True, "latitude": None,
                             "longitude": 2}) is None
        assert provider_for({"enabled": True, "latitude": 1,
                             "longitude": 2}) is not None


# ---------------------------------------------------------------------------
# C3.12 -- the runtime controller
# ---------------------------------------------------------------------------


@pytest.fixture()
def rig(tmp_path):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    manager = _Manager(hub)
    store = AmbienceStore(str(tmp_path / "audio.db"))
    engine = AmbienceEngine(hub)
    controller = AmbienceController(parent, manager, store=store, engine=engine)
    yield controller, transport, hub, store
    controller.shutdown()
    parent.deleteLater()


class TestController:
    def test_ambience_is_silent_until_started(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        assert transport.channels == {}
        assert not controller.is_running()

    def test_start_plays_the_enabled_rule_as_a_real_loop(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        controller.start()
        assert len(transport.channels) == 1
        assert next(iter(transport.channels.values()))["loop"] is True
        assert controller.state() == "running"

    def test_exactly_one_timer_of_each_kind(self, rig):
        controller, _tp, _hub, store = rig
        store.save_rules([_rule(id="a", name="A"), _rule(id="b", name="B"),
                          _rule(id="c", name="C")])
        controller.reload_rules()
        controller.start()
        timers = [child for child in controller.children()
                  if child.__class__.__name__ == "QTimer"]
        assert len(timers) == 3, "evaluate + fade + weather, never one per rule"

    def test_stop_physically_silences_every_layer(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        controller.start()
        handle = next(iter(transport.channels))
        controller.stop()
        assert handle in transport.stopped
        assert transport.channels == {}

    def test_ambience_survives_an_ordinary_global_replace(self, rig):
        controller, transport, hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        controller.start()
        hub.set_global_mode(PlaybackMode.REPLACE)
        hub.play("click.wav", event="click", bus=Bus.UI)
        hub.play("alarm.wav", event="timer", bus=Bus.ALERT)
        paths = {job["path"] for job in transport.channels.values()}
        assert "rain.wav" in paths

    def test_stop_all_sound_does_silence_ambience(self, rig):
        controller, transport, hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        controller.start()
        hub.stop_all()
        assert transport.channels == {}

    def test_a_weather_rule_reacts_to_a_condition_change(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule(trigger=TRIGGER_WEATHER, weather="rain")])
        controller.reload_rules()
        controller.start()
        assert transport.channels == {}, "no condition known yet"
        from fastprompter.core.ambience_engine import StaticWeatherProvider

        controller.engine.configure_weather(StaticWeatherProvider("rain"),
                                            enabled=True)
        controller.engine.refresh_weather()
        controller.engine.evaluate(now=dt.datetime(2026, 9, 9, 12, 0))
        assert {job["path"] for job in transport.channels.values()} == {"rain.wav"}
        controller.engine.configure_weather(StaticWeatherProvider("clear"),
                                            enabled=True)
        controller.engine.refresh_weather()
        controller.engine.evaluate(now=dt.datetime(2026, 9, 9, 12, 0))
        assert transport.channels == {}

    def test_the_fade_driver_moves_real_volume(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule(volume=0.8, fade_in_ms=200)])
        controller.reload_rules()
        controller.start()
        handle = next(iter(transport.channels))
        assert transport.channels[handle]["volume"] == pytest.approx(0.0)
        controller.engine.tick_fades(200)
        assert transport.channels[handle]["volume"] == pytest.approx(0.8)

    def test_shutdown_retires_every_timer(self, rig):
        controller, transport, _hub, store = rig
        store.save_rules([_rule()])
        controller.reload_rules()
        controller.start()
        controller.shutdown()
        assert transport.channels == {}
        for timer in (controller._evaluate_timer, controller._fade_timer,
                      controller._weather_timer):
            assert not timer.isActive()
        controller.shutdown()  # idempotent
