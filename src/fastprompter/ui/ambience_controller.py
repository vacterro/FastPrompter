"""Ambience runtime: ONE evaluation timer, ONE fade driver, ONE fetch timer.

T-1238-C3.12.  The pure :class:`AmbienceEngine` knows nothing about Qt or the
network; this adapter owns the schedule.  There is exactly one timer of each
kind for the whole application -- never one per rule and never one per layer
-- and the weather fetch runs off the UI thread with a bounded timeout.

Waking from sleep must not produce a flood: the engine's ``evaluate()`` is a
transition sweep over the CURRENT state, so a late tick simply computes the
present truth once.  Nothing is caught up.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from fastprompter.core.ambience_engine import FADE_STEP_MS, AmbienceEngine
from fastprompter.core.ambience_store import AmbienceStore
from fastprompter.core.logging import logger
from fastprompter.core.weather import provider_for

#: Calendar conditions change on minute boundaries; 20 s is well inside that
#: without being a busy loop.
EVALUATE_INTERVAL_MS = 20_000
#: Matches the engine's documented ~15 minute refresh policy.
WEATHER_REFRESH_MS = 15 * 60 * 1000
#: How long shutdown waits for the owned weather worker to retire. Deliberately
#: far shorter than the provider's own 8 s request timeout: the worker is a
#: daemon and can no longer emit once the lifecycle token moved, so blocking
#: application exit for a whole network timeout would buy nothing. A worker
#: still running past this bound is reported as a failed retirement.
WEATHER_SHUTDOWN_JOIN_S = 2.0


class AmbienceController(QObject):
    """Application-owned ambience runtime bound to the one AudioHub."""

    rulesChanged = pyqtSignal(object)      # list[AmbienceRule]
    weatherChanged = pyqtSignal(str)       # condition or ""
    stateChanged = pyqtSignal(str)         # running | paused | stopped

    def __init__(self, parent: QObject, sound_manager, *,
                 store: AmbienceStore | None = None,
                 engine: AmbienceEngine | None = None,
                 opener=None) -> None:
        super().__init__(parent)
        self._sound_manager = sound_manager
        self._store = store if store is not None else AmbienceStore()
        self._engine = engine if engine is not None else AmbienceEngine(
            sound_manager.audio_hub(),
            resolver=getattr(sound_manager, "resolve_ref_path", None))
        self._opener = opener
        self._closed = False
        self._weather_thread: threading.Thread | None = None
        # One token shared by fetch completion and shutdown: a fetch already in
        # flight observes the change and can no longer emit a signal against a
        # controller that is logically closed.
        self._lifecycle = 0
        # Outcome of the one real retirement; a repeated shutdown() reports it
        # rather than pretending a second teardown happened.
        self._retired_clean = True

        self._engine.set_rules(self._store.load_rules())
        # Nothing sounds until something explicitly starts it. The remembered
        # preference is restored by ``start_if_remembered()``, which the window
        # calls once the SoundManager is fully built -- NOT from here, because
        # a constructor that starts making noise is impossible to test and
        # impossible to stop before its first evaluation.
        self._engine.stop_ambience()

        # STOP ALL SOUND is emergency silence for the CURRENT session. It must
        # reach the timers too (otherwise the next evaluation tick, 20 s later,
        # simply starts everything again) but must NEVER rewrite the user's
        # remembered preference -- one press would then disable ambience for
        # every future launch.
        register = getattr(sound_manager, "add_stop_all_listener", None)
        if callable(register):
            register(self.stop_runtime_only)

        self._evaluate_timer = QTimer(self)
        self._evaluate_timer.setInterval(EVALUATE_INTERVAL_MS)
        self._evaluate_timer.timeout.connect(self._on_evaluate)

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(FADE_STEP_MS)
        self._fade_timer.timeout.connect(self._on_fade_tick)

        self._weather_timer = QTimer(self)
        self._weather_timer.setInterval(WEATHER_REFRESH_MS)
        self._weather_timer.timeout.connect(self.refresh_weather_async)

        self._apply_weather_config()

    # -- accessors -------------------------------------------------------------

    @property
    def engine(self) -> AmbienceEngine:
        return self._engine

    @property
    def store(self) -> AmbienceStore:
        return self._store

    def rules(self):
        return self._engine.rules()

    def is_running(self) -> bool:
        return self._evaluate_timer.isActive()

    def state(self) -> str:
        diagnostics = self._engine.diagnostics
        if diagnostics["stopped"]:
            return "stopped"
        return "paused" if diagnostics["paused"] else "running"

    # -- rule editing -----------------------------------------------------------

    def reload_rules(self):
        rules = self._store.load_rules()
        self._engine.set_rules(rules)
        self.rulesChanged.emit(rules)
        if self.is_running():
            self._on_evaluate()
        return rules

    def save_rule(self, rule):
        self._store.upsert_rule(rule)
        return self.reload_rules()

    def delete_rule(self, rule_id: str):
        self._store.delete_rule(rule_id)
        return self.reload_rules()

    def duplicate_rule(self, rule_id: str):
        self._store.duplicate_rule(rule_id)
        return self.reload_rules()

    # -- lifecycle ---------------------------------------------------------------

    def desired_enabled(self) -> bool:
        """Does the user want ambience running across sessions?

        This is the PERSISTED wish, not the runtime state. They differ on
        purpose: shutdown and STOP ALL SOUND silence the runtime and leave
        the wish alone.
        """
        try:
            return bool(self._store.runtime_enabled())
        except Exception:
            logger.debug("ambience runtime preference unreadable",
                         exc_info=True)
            return False

    def _remember(self, enabled: bool) -> None:
        try:
            self._store.set_runtime_enabled(enabled)
        except Exception:
            logger.debug("ambience runtime preference not written",
                         exc_info=True)

    def start_if_remembered(self) -> bool:
        """Restore the remembered ON state at application start.

        Returns True when ambience was actually started. A fresh install has
        nothing remembered and therefore stays silent.
        """
        if self._closed or not self.desired_enabled():
            return False
        self.start(persist=False)   # restoring is not a new user decision
        return True

    def start(self, *, persist: bool = True) -> None:
        if self._closed:
            return
        self._engine.start_ambience()
        self._engine.resume()
        self._evaluate_timer.start()
        self._fade_timer.start()
        if self._engine.diagnostics["weather_fetches"] == 0:
            self.refresh_weather_async()
        self._weather_timer.start()
        self._on_evaluate()
        if persist:
            self._remember(True)
        self.stateChanged.emit(self.state())

    def pause(self) -> None:
        self._engine.pause()
        self._evaluate_timer.stop()
        self.stateChanged.emit(self.state())

    def resume(self) -> None:
        self._engine.resume()
        self._evaluate_timer.start()
        self._on_evaluate()
        self.stateChanged.emit(self.state())

    def stop(self, *, persist: bool = True) -> None:
        self._engine.stop_ambience()
        self._evaluate_timer.stop()
        self._fade_timer.stop()
        self._weather_timer.stop()
        if persist:
            self._remember(False)
        self.stateChanged.emit(self.state())

    def stop_runtime_only(self) -> None:
        """Silence THIS session, keep the remembered preference.

        Used by STOP ALL SOUND. The distinction is the whole point of the
        split: an emergency silence is not the user saying "never start
        ambience again".
        """
        self.stop(persist=False)

    def toggle(self, enabled: bool) -> None:
        """One user-facing switch: on or off, remembered either way."""
        if enabled:
            self.start()
        else:
            self.stop()

    def shutdown(self) -> bool:
        """Retire every timer, the weather worker, and silence ambience (C4.4).

        Deliberately does NOT touch the remembered preference: closing the
        application while ambience plays means the next session should start
        it again, not that the user switched it off.

        Returns True when the controller's owned worker retired cleanly. The
        weather thread is this object's resource, so a silent return used to
        let a request in flight outlive the controller and emit against a
        closed (or already destroyed) receiver. The result is reported to the
        caller instead of being discarded -- see
        ``main._shutdown_application``'s fail-closed accounting. Idempotent: a
        second call is a no-op that still reports the first call's outcome.
        """
        if self._closed:
            return self._retired_clean
        self._closed = True
        # Move the lifecycle token BEFORE anything else: an in-flight fetch
        # compares against it and will refuse to emit.
        self._lifecycle += 1
        for timer in (self._evaluate_timer, self._fade_timer,
                      self._weather_timer):
            try:
                timer.stop()
                timer.timeout.disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            self._engine.stop_ambience()
        except Exception:
            pass
        self._retired_clean = self._retire_weather_worker()
        return self._retired_clean

    def _retire_weather_worker(self) -> bool:
        """Bounded join of the owned weather worker; False when it survives."""
        worker = self._weather_thread
        if worker is None or not worker.is_alive():
            self._weather_thread = None
            return True
        worker.join(timeout=WEATHER_SHUTDOWN_JOIN_S)
        if worker.is_alive():
            logger.debug("ambience weather worker did not retire in time")
            return False
        self._weather_thread = None
        return True

    # -- the ONE ticks -------------------------------------------------------------

    def _on_evaluate(self) -> None:
        if self._closed:
            return
        try:
            self._engine.evaluate()
        except Exception:
            logger.debug("ambience evaluation failed", exc_info=True)

    def _on_fade_tick(self) -> None:
        if self._closed:
            return
        try:
            self._engine.tick_fades(FADE_STEP_MS)
        except Exception:
            logger.debug("ambience fade tick failed", exc_info=True)

    # -- weather --------------------------------------------------------------------

    def weather_config(self) -> dict:
        return self._store.weather_config()

    def set_weather_config(self, **changes) -> dict:
        config = self._store.set_weather_config(**changes)
        self._apply_weather_config()
        if config.get("enabled"):
            self.refresh_weather_async()
        return config

    def _apply_weather_config(self) -> None:
        config = self._store.weather_config()
        provider = provider_for(config, opener=self._opener)
        self._engine.configure_weather(provider,
                                       enabled=bool(config.get("enabled")))

    def refresh_weather_async(self) -> None:
        """Fetch off the UI thread; never block painting on the network."""
        if self._closed:
            return
        if self._weather_thread is not None and self._weather_thread.is_alive():
            return  # one in-flight request at a time; no retry storm
        thread = threading.Thread(target=self._refresh_weather_blocking,
                                  name="fp-ambience-weather", daemon=True)
        self._weather_thread = thread
        thread.start()

    def _refresh_weather_blocking(self) -> None:
        if self._closed:
            return  # shutdown landed before this worker began
        token = self._lifecycle
        try:
            condition = self._engine.refresh_weather()
        except Exception:
            logger.debug("weather refresh failed", exc_info=True)
            return
        if self._closed or token != self._lifecycle:
            return  # retired while the request was in flight; stay silent
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
        except Exception:
            pass
        # Qt signals are thread-safe to emit; the slot runs on the receiver's
        # thread, so the UI never touches the network result off-thread.
        try:
            self.weatherChanged.emit(condition or "")
        except RuntimeError:
            pass

    def current_weather(self) -> str:
        return self._engine.weather_condition() or ""

    def weather_state(self) -> str:
        return self._engine.weather_state()
