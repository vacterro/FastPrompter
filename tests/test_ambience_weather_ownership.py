"""CORE-002: weather I/O must not own the engine lock or outlive shutdown.

Two connected defects are pinned here.

1. ``AmbienceEngine.refresh_weather()`` used to hold ``_lock`` across
   ``provider.fetch()``.  The production provider is bounded only by an 8 s
   network timeout, and ``_lock`` is the same lock ``stop_ambience`` /
   ``configure_weather`` / ``evaluate`` need -- so STOP AMBIENCE could not
   silence anything until the network answered.
2. The controller's daemon weather worker was retained but never retired, so a
   request already in flight could emit ``weatherChanged`` against a controller
   that was already logically closed (and possibly destroyed).

Every test here fails against the pre-repair shape; the assertions are about
real transport/lock/thread behaviour, not about the engine's own bookkeeping.
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.ambience_engine import (  # noqa: E402
    AmbienceEngine,
    StaticWeatherProvider,
    WeatherProvider,
)
from fastprompter.core.ambience_store import AmbienceStore  # noqa: E402
from fastprompter.ui import ambience_controller as controller_module  # noqa: E402
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402

#: Long enough that a test never races the release, short enough that a genuine
#: stall is obvious.  The fake never waits this long when the lock is free.
FETCH_BLOCK_S = 10.0
#: How long a transition may legitimately need while a fetch is in flight.
FREE_LOCK_BUDGET_S = 1.0


class BlockingProvider(WeatherProvider):
    """A provider that parks inside ``fetch()`` until the test releases it."""

    def __init__(self, condition: str | None) -> None:
        self.condition = condition
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def fetch(self) -> str | None:
        self.calls += 1
        self.entered.set()
        self.release.wait(FETCH_BLOCK_S)
        return self.condition


def _engine() -> AmbienceEngine:
    """An engine with no rules and no hub traffic (weather-only behaviour)."""
    return AmbienceEngine(object(), clock=lambda: 1000.0)


# ---------------------------------------------------------------------------
# the engine lock
# ---------------------------------------------------------------------------


class TestEngineLockIsNotHeldAcrossFetch:
    def test_stop_ambience_does_not_wait_for_the_network(self):
        """A blocking fetch must not stall STOP AMBIENCE."""
        engine = _engine()
        provider = BlockingProvider("rain")
        engine.configure_weather(provider, enabled=True)

        fetcher = threading.Thread(target=engine.refresh_weather, daemon=True)
        fetcher.start()
        assert provider.entered.wait(FETCH_BLOCK_S)

        stopped = threading.Event()

        def do_stop() -> None:
            engine.stop_ambience()
            stopped.set()

        stopper = threading.Thread(target=do_stop, daemon=True)
        stopper.start()
        completed = stopped.wait(FREE_LOCK_BUDGET_S)

        provider.release.set()
        fetcher.join(FETCH_BLOCK_S)
        stopper.join(FETCH_BLOCK_S)

        assert completed, "stop_ambience blocked behind the in-flight fetch"

    def test_evaluate_and_reconfigure_are_not_stalled_by_a_fetch(self):
        """The other lock owners stay responsive too."""
        engine = _engine()
        provider = BlockingProvider("rain")
        engine.configure_weather(provider, enabled=True)

        fetcher = threading.Thread(target=engine.refresh_weather, daemon=True)
        fetcher.start()
        assert provider.entered.wait(FETCH_BLOCK_S)

        done = threading.Event()

        def reconfigure_then_evaluate() -> None:
            engine.configure_weather(StaticWeatherProvider("snow"), enabled=True)
            engine.evaluate()
            done.set()

        worker = threading.Thread(target=reconfigure_then_evaluate, daemon=True)
        worker.start()
        responsive = done.wait(FREE_LOCK_BUDGET_S)

        provider.release.set()
        fetcher.join(FETCH_BLOCK_S)
        worker.join(FETCH_BLOCK_S)

        assert responsive, "configure_weather/evaluate blocked behind the fetch"

    def test_a_stale_answer_cannot_overwrite_the_new_configuration(self):
        """Provider A's answer describes A; B is configured by then."""
        engine = _engine()
        old = BlockingProvider("rain")
        engine.configure_weather(old, enabled=True)

        fetcher = threading.Thread(target=engine.refresh_weather, daemon=True)
        fetcher.start()
        assert old.entered.wait(FETCH_BLOCK_S)

        engine.configure_weather(StaticWeatherProvider("snow"), enabled=True)
        assert engine.refresh_weather() == "snow"
        assert engine.weather_condition() == "snow"

        old.release.set()
        fetcher.join(FETCH_BLOCK_S)

        assert engine.weather_condition() == "snow", (
            "the retired provider's answer overwrote the live configuration")

    def test_the_fetch_count_still_records_the_attempt(self):
        class Counting(StaticWeatherProvider):
            calls = 0

            def fetch(self):
                type(self).calls += 1
                return super().fetch()

        provider = Counting("rain")
        engine = _engine()
        engine.configure_weather(provider, enabled=True)
        assert engine.refresh_weather() == "rain"
        assert engine.diagnostics["weather_fetches"] == 1
        assert provider.calls == 1


# ---------------------------------------------------------------------------
# the controller's worker lifetime
# ---------------------------------------------------------------------------


class _Manager:
    def __init__(self, hub) -> None:
        self._hub = hub

    def audio_hub(self):
        return self._hub


_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def rig(tmp_path):
    _ensure_app()
    parent = QObject()
    engine = _engine()
    store = AmbienceStore(str(tmp_path / "audio.db"))
    controller = AmbienceController(parent, _Manager(object()), store=store,
                                    engine=engine)
    provider = BlockingProvider("rain")
    engine.configure_weather(provider, enabled=True)
    yield controller, engine, provider
    controller.shutdown()
    parent.deleteLater()


class TestControllerWorkerLifetime:
    def test_shutdown_reports_an_unretired_worker(self, rig, monkeypatch):
        """A worker that survives its bounded join is reported, not hidden."""
        controller, _engine_, provider = rig
        monkeypatch.setattr(controller_module, "WEATHER_SHUTDOWN_JOIN_S", 0.2)

        controller.refresh_weather_async()
        assert provider.entered.wait(FETCH_BLOCK_S)

        assert controller.shutdown() is False
        provider.release.set()
        assert controller._weather_thread is not None  # still the live worker
        controller._retire_weather_worker()

    def test_no_weather_signal_survives_shutdown(self, rig, monkeypatch):
        """The post-shutdown emit path is gone, not merely unlikely."""
        controller, _engine_, provider = rig
        monkeypatch.setattr(controller_module, "WEATHER_SHUTDOWN_JOIN_S", 0.2)

        seen: list[str] = []
        controller.weatherChanged.connect(seen.append)

        controller.refresh_weather_async()
        assert provider.entered.wait(FETCH_BLOCK_S)
        assert controller.shutdown() is False

        provider.release.set()
        worker = controller._weather_thread
        worker.join(FETCH_BLOCK_S)
        controller._retire_weather_worker()
        # weatherChanged crosses threads as a queued call, so an emit that
        # happened would only be observable after the event loop turns. Drain
        # it before claiming the signal never arrived.
        _ensure_app().processEvents()

        assert seen == [], "weatherChanged was emitted after shutdown"

    def test_a_finished_worker_retires_cleanly(self, rig):
        """The ordinary path: nothing in flight, shutdown is clean."""
        controller, _engine_, provider = rig
        seen: list[str] = []
        controller.weatherChanged.connect(seen.append)

        controller.refresh_weather_async()
        assert provider.entered.wait(FETCH_BLOCK_S)
        provider.release.set()
        controller._weather_thread.join(FETCH_BLOCK_S)
        _ensure_app().processEvents()

        assert seen == ["rain"]
        assert controller.shutdown() is True

    def test_shutdown_is_idempotent(self, rig, monkeypatch):
        controller, _engine_, provider = rig
        monkeypatch.setattr(controller_module, "WEATHER_SHUTDOWN_JOIN_S", 0.2)
        controller.refresh_weather_async()
        assert provider.entered.wait(FETCH_BLOCK_S)

        first = controller.shutdown()
        second = controller.shutdown()
        provider.release.set()
        controller._weather_thread.join(FETCH_BLOCK_S)

        assert first is False
        assert second is first

    def test_shutdown_after_a_clean_retirement_stays_clean(self, rig):
        controller, _engine_, _provider = rig
        assert controller.shutdown() is True
        assert controller.shutdown() is True

    def test_only_one_weather_request_is_in_flight(self, rig):
        """No retry storm: a second request while one runs is dropped."""
        controller, _engine_, provider = rig
        controller.refresh_weather_async()
        assert provider.entered.wait(FETCH_BLOCK_S)

        controller.refresh_weather_async()
        controller.refresh_weather_async()

        assert provider.calls == 1
        provider.release.set()
        controller._weather_thread.join(FETCH_BLOCK_S)

    def test_refresh_after_shutdown_never_starts_a_worker(self, rig):
        controller, _engine_, provider = rig
        controller.shutdown()

        controller.refresh_weather_async()

        assert controller._weather_thread is None
        assert provider.calls == 0
