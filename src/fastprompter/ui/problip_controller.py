"""The ONE application-owned Problip controller (T-1238-C1).

FastPrompter has exactly one Problip runtime for the whole process lifetime.
It owns the global store, the scheduler state machine and the single
single-shot QTimer that drives it.  Settings widgets BIND to it; they never
own it, never recreate it and never restart its timer.

That ownership is the whole point of the ticket: a remembered Problip must
run for a user who never opens Settings, must survive profile switches, tab
changes and preset applications, and must stop cleanly at shutdown with no
callback arriving after teardown.
"""

from __future__ import annotations

import os
import random

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from fastprompter.core.audio_hub import DROPPED_OUTCOMES, Bus, Outcome
from fastprompter.core.logging import logger
from fastprompter.core.problip import (
    CueResult,
    IntervalConfig,
    IntervalMode,
    ProblipScheduler,
    ProblipState,
)
from fastprompter.core.problip_store import ProblipSettings, ProblipStore
from fastprompter.sound.problip.catalog import (
    SoundPoolStatus,
    choose_playable_sound,
    inspect_sound_pool,
    resolve_sound_path,
)

#: Outcomes that mean the cue really became audible.
_AUDIBLE = frozenset({Outcome.PLAYED, Outcome.MIXED, Outcome.REPLACED})


class _QtSingleShotPort:
    """Adapter binding the pure scheduler to ONE Qt single-shot timer."""

    def __init__(self, timer: QTimer) -> None:
        self._timer = timer
        self.generation = 0

    def start(self, delay_ms: int, generation: int) -> None:
        self.generation = int(generation)
        self._timer.stop()
        self._timer.start(max(1, int(delay_ms)))

    def stop(self) -> None:
        self._timer.stop()


class ProblipController(QObject):
    """Application-global Problip runtime.

    Signals are the only channel the UI needs; nothing in this class knows
    what a settings page looks like.
    """

    stateChanged = pyqtSignal(str)        # ProblipState value
    statsChanged = pyqtSignal(object)     # StatsSnapshot
    settingsChanged = pyqtSignal(object)  # ProblipSettings
    cuePlayed = pyqtSignal()              # one AUDIBLE scheduled cue (glow)
    errorChanged = pyqtSignal(str)

    def __init__(self, parent: QObject, sound_manager, *,
                 store: ProblipStore | None = None,
                 random_source=None) -> None:
        super().__init__(parent)
        self._sound_manager = sound_manager
        self._random_source = random_source or (lambda n: random.randrange(n))
        self._closed = False
        self._store = store if store is not None else ProblipStore.open_default()
        self._settings: ProblipSettings = self._store.load_settings()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._port = _QtSingleShotPort(self._timer)
        # Session playback policy (T-1242 spec 13), pinned at START.
        self._session_playback_mode = self._settings.playback_mode
        self._session_policy_generation = -1

        self._scheduler = ProblipScheduler(
            self._port,
            self._play_cue,
            interval=self._settings.interval_config,
            random_source=self._random_source,
            on_success=self._on_cue_success,
            on_state_changed=self._on_state_changed,
        )

    # -- lifecycle -----------------------------------------------------------

    def start_if_remembered(self) -> bool:
        """Honour the remembered run preference exactly once, at startup."""
        if self._settings.run_on_launch:
            return self.start(persist=False)
        return False

    def start(self, *, persist: bool = True) -> bool:
        if self._closed:
            return False
        status = self.pool_status()
        if not status.playable:
            self._scheduler.fail(status.error or "No playable Problip sound")
            self.errorChanged.emit(self._scheduler.error or "")
            return False
        # T-1242 spec 13: ONE session playback policy.  Resolve the cue
        # transport contract ONCE per scheduler run; cues 4-7 seconds apart
        # must never flip between physical representations mid-session.  A
        # settings change may intentionally start a new generation (see
        # _on_settings_generation_change); ordinary scheduling may not.
        self._session_policy_generation = (
            self._sound_manager.audio_hub().transport_policy_generation())
        self._session_playback_mode = self._settings.playback_mode
        started = self._scheduler.start()
        if started and persist:
            self._remember_run(True)
        return started

    def stop(self, *, persist: bool = True) -> bool:
        stopped = self._scheduler.stop()
        if persist:
            self._remember_run(False)
        return stopped

    def shutdown(self) -> None:
        """Stop everything and make every pending callback inert (C4.4)."""
        if self._closed:
            return
        self._closed = True
        try:
            self._scheduler.stop()
        except Exception:
            pass
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._on_timeout)
        except (RuntimeError, TypeError):
            pass
        try:
            self._store.close()
        except Exception:
            pass

    # -- state / data --------------------------------------------------------

    @property
    def state(self) -> ProblipState:
        return self._scheduler.state

    @property
    def error(self) -> str | None:
        return self._scheduler.error

    @property
    def settings(self) -> ProblipSettings:
        return self._settings

    @property
    def store(self) -> ProblipStore:
        return self._store

    @property
    def scheduler(self) -> ProblipScheduler:
        return self._scheduler

    def is_running(self) -> bool:
        return self.state in (ProblipState.STARTING, ProblipState.RUNNING)

    def stats(self):
        return self._store.get_stats()

    def pool_status(self) -> SoundPoolStatus:
        return inspect_sound_pool(self._settings.selected_sound_ids)

    # -- settings mutation ---------------------------------------------------

    def update_settings(self, **changes) -> ProblipSettings:
        """Persist one settings change and rearm only when it needs rearming.

        Opening Settings, switching tabs or applying a sound preset must not
        pass through here at all -- and even a real change only rearms when
        the INTERVAL actually changed.
        """
        if self._closed:
            return self._settings
        before = self._settings
        self._settings = self._store.update_settings(**changes)
        if (self._settings.interval_config != before.interval_config
                and self.is_running()):
            self._scheduler.set_interval(self._settings.interval_config)
        if self._settings.playback_mode != before.playback_mode:
            # An explicit user transition starts a new playback-policy
            # generation; the NEXT cue intentionally adopts it.
            self._session_playback_mode = self._settings.playback_mode
        self.settingsChanged.emit(self._settings)
        return self._settings

    def _remember_run(self, enabled: bool) -> None:
        try:
            self._settings = self._store.set_run_on_launch(bool(enabled))
        except Exception:
            logger.debug("Problip run preference could not be persisted",
                         exc_info=True)

    # -- the scheduled cue ---------------------------------------------------

    def _on_timeout(self) -> None:
        if self._closed:
            return
        try:
            self._scheduler.timer_fired(self._port.generation)
        except Exception:
            logger.debug("Problip timer callback failed", exc_info=True)

    def _play_cue(self) -> CueResult:
        """Emit ONE scheduled Problip cue on the hub's PROBLIP bus."""
        status = self.pool_status()
        if not status.playable:
            return CueResult.FAILED
        entry = choose_playable_sound(status.playable_ids,
                                      random_source=self._random_source)
        if entry is None:
            return CueResult.FAILED
        path = resolve_sound_path(entry.sound_id)
        if not path:
            return CueResult.FAILED
        outcome = self._emit(path, bus=Bus.PROBLIP, event="problip_cue",
                             mode=self._session_playback_mode)
        if outcome in _AUDIBLE:
            return CueResult.PLAYED
        # A queued cue has not started yet and a dropped one never will:
        # neither is a broken installation, and neither may be counted.
        return CueResult.SKIPPED

    def _emit(self, path: str, *, bus: Bus, event: str, mode: str) -> Outcome:
        hub = self._sound_manager.audio_hub()
        volume = max(0.0, min(1.0, self._settings.volume_percent / 100.0))
        return hub.play(path, event=event, bus=bus,
                        mode=None if mode == "inherit" else mode,
                        volume=volume)

    def _on_cue_success(self) -> None:
        """Only a physically started scheduled cue counts and glows."""
        try:
            snapshot = self._store.record_successful_blip()
        except Exception:
            logger.debug("Problip statistic write failed", exc_info=True)
            return
        self.statsChanged.emit(snapshot)
        if self._settings.blip_glow_enabled:
            self.cuePlayed.emit()

    def _on_state_changed(self, state: ProblipState) -> None:
        self.stateChanged.emit(str(state))
        self.errorChanged.emit(self._scheduler.error or "")

    # -- explicit user preview ------------------------------------------------

    def test(self) -> tuple[bool, str]:
        """TEST: one immediate PREVIEW cue.  No stats, no glow, no rearm.

        Works while Problip is OFF and never changes the remembered run
        preference.  Returns ``(ok, message)`` so the page can be truthful.
        """
        status = self.pool_status()
        if not status.playable:
            return False, status.error or "No playable Problip sound"
        entry = choose_playable_sound(status.playable_ids,
                                      random_source=self._random_source)
        path = resolve_sound_path(entry.sound_id) if entry else None
        if not path:
            return False, "Problip sound could not be resolved"
        outcome = self._emit(path, bus=Bus.PREVIEW, event="problip_test",
                             mode="mix")
        if outcome in DROPPED_OUTCOMES:
            return False, f"Preview was not played ({outcome.value})"
        return True, entry.display_name

    def test_path(self, path: str) -> tuple[bool, str]:
        """Preview ONE explicit path (custom-sound dialog); no stats, no rearm."""
        if not path or not os.path.isfile(path):
            return False, "Sound file is missing"
        outcome = self._emit(path, bus=Bus.PREVIEW, event="problip_test",
                             mode="mix")
        if outcome in DROPPED_OUTCOMES:
            return False, f"Preview was not played ({outcome.value})"
        return True, os.path.basename(path)

    # -- interval helpers used by the settings page ---------------------------

    def set_interval_mode(self, mode: IntervalMode | str) -> ProblipSettings:
        return self.update_settings(interval_mode=IntervalMode.coerce(mode))

    def set_manual_range(self, from_seconds, to_seconds) -> ProblipSettings:
        return self.update_settings(manual_from_seconds=from_seconds,
                                    manual_to_seconds=to_seconds)

    def interval_config(self) -> IntervalConfig:
        return self._settings.interval_config
