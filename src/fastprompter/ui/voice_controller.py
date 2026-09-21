"""Voice-countdown runtime (T-1238-C3.7).

The pure ``CountdownScheduler`` was tested but unused.  This adapter is the
one application controller that wires it to real deadlines:

* it OBSERVES the deadlines FastPrompter already knows -- the active normal
  timers and the already-resolved AI-limit reset windows.  It never polls a
  provider and never runs a second timer subsystem;
* on every relevant change it recomputes the ONE nearest target and schedules
  only thresholds still in the future -- no catch-up speech after sleep;
* the exactly-once ledger survives a restart, so reopening FastPrompter does
  not re-announce "thirty minutes remaining";
* every phrase enters the AudioHub VOICE bus as ONE sequence job.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from fastprompter.core.audio_hub import Bus
from fastprompter.core.logging import logger
from fastprompter.core.voice_engine import (
    COUNTDOWN_THRESHOLDS,
    CountdownScheduler,
    nearest_ai_reset_due,
    nearest_timer_due,
)
from fastprompter.core.voice_store import VoiceStore, voice_pack

#: One announcement tick.  Thresholds are minutes apart, so a 5 s heartbeat
#: is precise enough and cheap; it is ONE timer for the whole feature.
TICK_INTERVAL_MS = 5_000


class VoiceController(QObject):
    """Application-owned voice countdown bound to the one AudioHub."""

    targetChanged = pyqtSignal(str, str, float)   # kind, id, due epoch
    announced = pyqtSignal(int)                   # threshold seconds
    settingsChanged = pyqtSignal(object)

    def __init__(self, parent: QObject, sound_manager, *,
                 store: VoiceStore | None = None, clock=None) -> None:
        super().__init__(parent)
        self._sound_manager = sound_manager
        self._store = store if store is not None else VoiceStore()
        self._settings = self._store.load()
        self._closed = False
        self._last_target: tuple[str, str, float] | None = None

        self._scheduler = CountdownScheduler(self._speak, clock=clock)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)
        if self._settings["enabled"]:
            self._timer.start()

    # -- accessors -------------------------------------------------------------

    @property
    def settings(self) -> dict:
        return dict(self._settings)

    @property
    def scheduler(self) -> CountdownScheduler:
        return self._scheduler

    @property
    def store(self) -> VoiceStore:
        return self._store

    def is_enabled(self) -> bool:
        return bool(self._settings["enabled"])

    def pack(self):
        return voice_pack(self._settings["pack"])

    def update_settings(self, **changes) -> dict:
        self._settings = self._store.save(**changes)
        if self._settings["enabled"]:
            self._timer.start()
        else:
            self._timer.stop()
            self._scheduler.invalidate()
            self._last_target = None
        self.settingsChanged.emit(self._settings)
        return self._settings

    # -- observing the deadlines the app already knows ---------------------------

    def refresh_target(self, *, timers=None, limits=None) -> None:
        """Recompute the ONE nearest target from already-known deadlines.

        Callers pass what they already have; nothing here polls.  When the
        deadline moves or the target changes, the scheduler generation is
        bumped so stale plans can never fire.
        """
        if self._closed or not self.is_enabled():
            return
        candidates: list[tuple[str, str, float]] = []
        if self._settings["source_timers"]:
            nearest = nearest_timer_due(list(timers or ()))
            if nearest is not None:
                candidates.append(("TIMER", nearest[0], nearest[1]))
        if self._settings["source_limits"]:
            nearest = nearest_ai_reset_due(list(limits or ()))
            if nearest is not None:
                candidates.append(("AI_LIMIT", nearest[0], nearest[1]))
        if not candidates:
            if self._last_target is not None:
                self._scheduler.invalidate()
                self._last_target = None
            return
        target = min(candidates, key=lambda item: item[2])
        if self._last_target == target:
            return  # no change: never re-plan, never re-announce
        self._last_target = target
        kind, target_id, due = target
        self._scheduler.set_target(kind, target_id, due)
        self.targetChanged.emit(kind, target_id, due)

    def _collect_from_host(self) -> tuple[list[dict], list[dict]]:
        """Read the host window's existing timer / AI-limit state."""
        host = self.parent()
        timers: list[dict] = []
        limits: list[dict] = []
        collector = getattr(host, "voice_countdown_sources", None)
        if callable(collector):
            try:
                timers, limits = collector()
            except Exception:
                logger.debug("voice countdown source collection failed",
                             exc_info=True)
        return list(timers or ()), list(limits or ())

    # -- the ONE tick --------------------------------------------------------------

    def _on_tick(self) -> None:
        if self._closed or not self.is_enabled():
            return
        timers, limits = self._collect_from_host()
        self.refresh_target(timers=timers, limits=limits)
        try:
            for seconds in self._scheduler.announce():
                self.announced.emit(seconds)
        except Exception:
            logger.debug("voice announcement failed", exc_info=True)

    # -- speaking -------------------------------------------------------------------

    def _speak(self, tokens, threshold_seconds: int, _label: str) -> None:
        fragments = self.pack().compose(tokens)
        if not fragments:
            return  # a pack missing its tokens stays silent; it never fakes
        mode = self._settings["mode"]
        self._sound_manager.audio_hub().play_sequence(
            fragments, bus=Bus.VOICE,
            mode=None if mode == "inherit" else mode,
            volume=max(0.0, min(1.0, self._settings["volume_percent"] / 100.0)),
            event=f"voice_countdown_{threshold_seconds}")

    def test_phrase(self, threshold_seconds: int = 1800) -> tuple[bool, str]:
        """Preview one phrase now; no ledger entry, no target change."""
        from fastprompter.core.voice_engine import phrase_tokens

        pack = self.pack()
        fragments = pack.compose(phrase_tokens(threshold_seconds))
        if not fragments:
            return False, f"{self._settings['pack']} pack is missing fragments"
        self._speak(phrase_tokens(threshold_seconds), threshold_seconds, "")
        return True, f"{len(fragments)} fragments"

    def thresholds(self) -> list[int]:
        configured = self._settings["thresholds"]
        return configured or [s for s, _ in COUNTDOWN_THRESHOLDS]

    # -- lifecycle -------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._on_tick)
        except (RuntimeError, TypeError):
            pass
        self._scheduler.invalidate()
