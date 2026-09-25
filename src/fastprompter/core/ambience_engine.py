"""Ambience engine: infinite layers, schedule rules, weather rules (T-1238-I).

The AMBIENCE bus is independent of the transient queue: several layers may
play simultaneously, each with its own volume and fades.  One bounded rule
scheduler computes transitions; it never schedules one timer per layer and
never floods on repeated identical triggers.

Weather is opt-in, user-configured-location only, served through a
``WeatherProvider`` abstraction so tests never require internet.
"""

from __future__ import annotations

import datetime as _datetime
import threading

# Trigger types
TRIGGER_ALWAYS = "ALWAYS"
TRIGGER_TIME_WINDOW = "TIME_WINDOW"
TRIGGER_WEEKDAY = "WEEKDAY"
TRIGGER_WEATHER = "WEATHER"

# Repeat modes
REPEAT_LOOP = "LOOP"
REPEAT_EVERY_INTERVAL = "EVERY_INTERVAL"
REPEAT_ON_ENTER = "ON_ENTER"

WEATHER_CONDITIONS = (
    "rain", "drizzle", "thunderstorm", "snow", "cloudy", "clear",
)

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday")

# Bounded fade machinery
DEFAULT_FADE_MS = 500
MAX_FADE_MS = 10_000
FADE_STEP_MS = 50  # one bounded animation tick, not hundreds of timers
MAX_FADE_TICKS = (MAX_FADE_MS // FADE_STEP_MS) + 2

# Weather fetch policy
WEATHER_REFRESH_S = 15 * 60
WEATHER_STALE_S = 45 * 60

# Rule fields that decide WHAT is audible rather than merely how loud. A change
# to any of them cannot be applied to a channel that is already playing, so the
# layer has to be retired and started again; everything else is a live update.
_MATERIAL_RULE_FIELDS = ("sound_ref", "repeat")


def clamp_fade_ms(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_FADE_MS
    return max(0, min(MAX_FADE_MS, number))


def _parse_hhmm(value: str) -> int | None:
    try:
        hours, minutes = value.strip().split(":")
        h, m = int(hours), int(minutes)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


class AmbienceRule:
    """One persisted ambience layer configuration."""

    def __init__(
        self,
        *,
        id: str,
        name: str,
        sound_ref: str,
        volume: float = 1.0,
        trigger: str = TRIGGER_ALWAYS,
        repeat: str = REPEAT_LOOP,
        enabled: bool = False,
        fade_in_ms: int = DEFAULT_FADE_MS,
        fade_out_ms: int = DEFAULT_FADE_MS,
        priority: int = 0,
        # TIME_WINDOW
        start: str = "00:00",
        end: str = "23:59",
        weekdays: list[str] | None = None,
        # WEEKDAY
        weekday: str = "sunday",
        # WEATHER
        weather: str = "rain",
        # EVERY_INTERVAL
        interval_seconds: int = 3600,
    ) -> None:
        self.id = id
        self.name = name
        self.sound_ref = sound_ref
        self.volume = max(0.0, min(1.0, float(volume)))
        self.trigger = trigger
        self.repeat = repeat
        self.enabled = enabled
        self.fade_in_ms = clamp_fade_ms(fade_in_ms)
        self.fade_out_ms = clamp_fade_ms(fade_out_ms)
        self.priority = priority
        self.start = start
        self.end = end
        self.weekdays = list(weekdays or [])
        self.weekday = weekday
        self.weather = weather
        self.interval_seconds = max(1, int(interval_seconds))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "sound_ref": self.sound_ref,
            "volume": self.volume, "trigger": self.trigger,
            "repeat": self.repeat, "enabled": self.enabled,
            "fade_in_ms": self.fade_in_ms, "fade_out_ms": self.fade_out_ms,
            "priority": self.priority, "start": self.start, "end": self.end,
            "weekdays": self.weekdays, "weekday": self.weekday,
            "weather": self.weather,
            "interval_seconds": self.interval_seconds,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> AmbienceRule:
        known = {"id", "name", "sound_ref", "volume", "trigger", "repeat",
                 "enabled", "fade_in_ms", "fade_out_ms", "priority", "start",
                 "end", "weekdays", "weekday", "weather", "interval_seconds"}
        return cls(**{k: v for k, v in raw.items() if k in known})


def in_time_window(now_minutes: int, start: str, end: str) -> bool:
    """HH:MM window with correct overnight support (22:00 -> 06:00)."""
    start_m = _parse_hhmm(start)
    end_m = _parse_hhmm(end)
    if start_m is None or end_m is None:
        return False
    if start_m == end_m:
        return True  # degenerate window treated as always-within
    if start_m < end_m:
        return start_m <= now_minutes < end_m
    # overnight: window crosses midnight
    return now_minutes >= start_m or now_minutes < end_m


class WeatherProvider:
    """Abstract weather source; tests inject fakes, never the internet."""

    def fetch(self) -> str | None:
        """Return a condition string from WEATHER_CONDITIONS, or None."""
        raise NotImplementedError


class StaticWeatherProvider(WeatherProvider):
    """Deterministic provider for tests and offline defaults."""

    def __init__(self, condition: str | None) -> None:
        self.condition = condition

    def fetch(self) -> str | None:
        return self.condition


class _WeatherState:
    """Bounded stale policy for one weather observation."""

    def __init__(self) -> None:
        self.condition: str | None = None
        self.fetched_monotonic: float | None = None

    def record(self, condition: str | None, now: float) -> None:
        if condition in WEATHER_CONDITIONS:
            self.condition = condition
            self.fetched_monotonic = now
        # A failed fetch keeps the old result; staleness is judged below.

    def usable(self, now: float) -> str | None:
        if (self.condition is None
                or self.fetched_monotonic is None
                or now - self.fetched_monotonic > WEATHER_STALE_S):
            return None
        return self.condition


class _Layer:
    """One audible ambience channel plus its (real) fade envelope."""

    def __init__(self, handle: str, rule_id: str, *, target_volume: float,
                 current_volume: float, fading: str | None = None,
                 fade_total_ms: int = 0) -> None:
        self.handle = handle
        self.rule_id = rule_id
        self.target_volume = max(0.0, min(1.0, float(target_volume)))
        self.current_volume = max(0.0, min(1.0, float(current_volume)))
        self.fading = fading  # "in" | "out" | None
        self.fade_total_ms = max(0, int(fade_total_ms))
        self.fade_elapsed_ms = 0
        self.fade_from = self.current_volume


class AmbienceEngine:
    """Owns every audible ambience layer behind the audio hub."""

    def __init__(
        self,
        hub,  # AudioHub
        *,
        clock=None,
        max_layers: int = 8,
        resolver=None,
    ) -> None:
        self._hub = hub
        # A rule stores a library REF ("computalk1.wav", "user:imported/x").
        # The transport needs a real path; without this resolver every layer
        # was refused as FILE_MISSING and ambience was simply silent.
        self._resolver = resolver
        self._lock = threading.RLock()
        self._clock = clock or _default_monotonic
        self._max_layers = max(1, int(max_layers))
        self._rules: list[AmbienceRule] = []
        self._layers: dict[str, _Layer] = {}  # rule_id -> layer
        self._last_interval_fire: dict[str, float] = {}
        self._prev_trigger_state: dict[str, bool] = {}
        self._paused = False
        self._stopped = False
        self._held_layer_count = 0
        self._weather = _WeatherState()
        self._weather_enabled = False
        self._weather_provider: WeatherProvider | None = None
        self._weather_fetches = 0
        # Bumped by every configure_weather(); a fetch compares its snapshot
        # against it before committing so a stale answer can never win.
        self._weather_generation = 0
        self._fade_ticks_total = 0
        # Layers whose channel is still audible while fading out.  They are
        # off ``_layers`` (logically inactive) but physically alive until the
        # ONE fade driver finishes them.
        self._fading_out: list[_Layer] = []

    def _resolve(self, ref: str) -> str:
        """Library ref -> absolute path ("" when it resolves to nothing)."""
        if not ref:
            return ""
        if self._resolver is None:
            return ref              # legacy/test callers pass real paths
        try:
            return self._resolver(ref) or ""
        except Exception:
            return ""

    # -- rule management ------------------------------------------------------

    def set_rules(self, rules: list[AmbienceRule]) -> None:
        """Adopt a new authoritative rule set AND reconcile the audible runtime.

        This is not a list assignment. The persisted rule set is the truth the
        workspace edits, and the runtime must converge to it immediately, or
        the two disagree in the worst possible way:

        * a rule that was deleted or disabled while audible kept playing
          forever, because ``evaluate`` only walks rules still in ``_rules``
          and skips disabled ones -- no branch ever retired its layer;
        * a rule that kept its id but changed source/volume left the OLD
          channel sounding while the UI and the store claimed the new one.

        So: retire every layer whose rule is gone or disabled, restart exactly
        once when what would be audible materially changed, update the live
        channel in place for a volume-only change, and forget the per-rule
        trigger/interval state of rules that no longer exist so a later
        re-create starts from a clean slate instead of inheriting it.

        A rule that did not previously exist is left to ``evaluate`` -- this
        method reconciles what is already sounding; it never becomes a second
        scheduler with different start semantics.
        """
        with self._lock:
            incoming = {rule.id: rule for rule in rules}
            previous = {rule.id: rule for rule in self._rules}
            self._rules = list(rules)

            # 1. Nothing may stay audible without an enabled rule behind it.
            for rule_id in list(self._layers):
                rule = incoming.get(rule_id)
                if rule is None or not rule.enabled:
                    self._stop_layer_now(self._layers.pop(rule_id))
            # A layer already fading out is still physically sounding, so it
            # is retired here too rather than left to finish on its own.
            for layer in list(self._fading_out):
                rule = incoming.get(layer.rule_id)
                if rule is None or not rule.enabled:
                    self._stop_layer_now(layer)
                    try:
                        self._fading_out.remove(layer)
                    except ValueError:
                        pass

            # 2. Make an unchanged-id rule's runtime match its new config.
            for rule_id, layer in list(self._layers.items()):
                rule = incoming[rule_id]
                old = previous.get(rule_id)
                if old is None or not old.enabled:
                    continue    # newly (re)enabled: evaluate owns the start
                if any(getattr(old, field) != getattr(rule, field)
                       for field in _MATERIAL_RULE_FIELDS):
                    # What is sounding cannot be mutated: retire it, then let
                    # exactly one replacement start. Never overlap the two.
                    self._stop_layer_now(self._layers.pop(rule_id))
                    if self._start_layer(rule):
                        if rule.repeat == REPEAT_EVERY_INTERVAL:
                            self._last_interval_fire[rule_id] = self._clock()
                else:
                    # Volume-only: the live channel follows the new level.
                    # An in-flight fade-in keeps owning current_volume but is
                    # re-aimed, so it lands on the new target instead of the
                    # old one.
                    layer.target_volume = rule.volume
                    if layer.fading == "in":
                        continue
                    layer.current_volume = rule.volume
                    if layer.handle:
                        try:
                            self._hub.set_channel_volume(layer.handle,
                                                         rule.volume)
                        except Exception:
                            pass

            # 3. Per-rule state belongs to the rule, not to the id slot.
            for state in (self._prev_trigger_state, self._last_interval_fire):
                for rule_id in list(state):
                    rule = incoming.get(rule_id)
                    if rule is None or not rule.enabled:
                        state.pop(rule_id, None)

    def rules(self) -> list[AmbienceRule]:
        with self._lock:
            return list(self._rules)

    # -- weather ---------------------------------------------------------------

    def configure_weather(
        self,
        provider: WeatherProvider | None,
        *,
        enabled: bool,
    ) -> None:
        with self._lock:
            self._weather_provider = provider
            self._weather_enabled = bool(enabled and provider is not None)
            # Every configuration change invalidates any request already in
            # flight: its answer describes the OLD provider.
            self._weather_generation += 1

    def refresh_weather(self, now: float | None = None) -> str | None:
        """Async-caller wrapper: one bounded fetch with stale policy.

        Returns the usable condition (possibly the cached one) or None when
        nothing usable is known.  A network error is never treated as a
        condition.

        The provider fetch is blocking network I/O and is deliberately
        performed WITHOUT holding ``_lock``. ``_lock`` is the same lock that
        ``stop_ambience``, ``configure_weather`` and ``evaluate`` need, so
        holding it across an 8-second request stalled every engine transition
        -- stopping ambience could not silence anything until the network
        answered. Only the snapshot and the commit are lock-scoped, and the
        commit is discarded when the configuration changed while the request
        was in flight.
        """
        with self._lock:
            now_value = self._clock() if now is None else now
            if not self._weather_enabled or self._weather_provider is None:
                return self._weather.usable(now_value)
            provider = self._weather_provider
            generation = self._weather_generation
            self._weather_fetches += 1
        try:
            condition = provider.fetch()
        except Exception:
            condition = None  # failure keeps last known; never guesses
        with self._lock:
            if generation != self._weather_generation:
                # Reconfigured mid-flight: this result belongs to a provider
                # nobody is configured with any more. Do not overwrite.
                return self._weather.usable(now_value)
            self._weather.record(condition, now_value)
            return self._weather.usable(now_value)

    def weather_condition(self, now: float | None = None) -> str | None:
        with self._lock:
            now_value = self._clock() if now is None else now
            return self._weather.usable(now_value)

    def weather_state(self, now: float | None = None) -> str:
        with self._lock:
            if not self._weather_enabled or self._weather_provider is None:
                return "disabled"
            now_value = self._clock() if now is None else now
            if self._weather.condition is None:
                return "unavailable"
            if (self._weather.fetched_monotonic is None
                    or now_value - self._weather.fetched_monotonic > WEATHER_STALE_S):
                return "stale"
            return "available"

    # -- pause/stop ------------------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._held_layer_count = len(self._layers)
            self._stop_all_layers()

    def resume(self) -> None:
        """Resume evaluates current conditions fresh; no catch-up events."""
        with self._lock:
            self._paused = False
            self._held_layer_count = 0

    def stop_ambience(self) -> None:
        with self._lock:
            self._stopped = True
            self._held_layer_count = 0
            self._stop_all_layers()

    def start_ambience(self) -> None:
        with self._lock:
            self._stopped = False

    def _stop_all_layers(self) -> None:
        """Physical silence for every ambience channel, fades bypassed.

        STOP AMBIENCE and PAUSE are commands, not transitions: they must
        actually stop the transport, not merely forget a dict entry.
        """
        for layer in list(self._layers.values()):
            self._stop_layer_now(layer)
        self._layers.clear()
        for layer in list(self._fading_out):
            self._stop_layer_now(layer)
        self._fading_out.clear()
        # Trigger states are deliberately KEPT: resume must not re-fire an
        # ON_ENTER rule whose condition never actually changed (no catch-up).
        self._last_interval_fire.clear()

    def is_active(self, rule_id: str) -> bool:
        with self._lock:
            return rule_id in self._layers

    def active_rules(self) -> list[str]:
        with self._lock:
            return sorted(self._layers)

    # -- the ONE scheduler tick -------------------------------------------------

    def evaluate(
        self,
        now: _datetime.datetime | None = None,
        *,
        monotonic: float | None = None,
    ) -> list[str]:
        """Compute one transition sweep across every enabled rule.

        ``now`` (local wall time) drives calendar conditions; ``monotonic``
        drives weather staleness.  Both are injectable so tests can pin the
        same clock domains production uses (wall + monotonic, never mixed).
        Returns the rule ids whose audible state changed.
        """
        with self._lock:
            if self._paused or self._stopped:
                return []
            now_value = now or _datetime.datetime.now()
            now_minutes = now_value.hour * 60 + now_value.minute
            weekday = WEEKDAY_NAMES[now_value.weekday()]
            changed: list[str] = []
            weather = None
            if self._weather_enabled:
                weather = self._weather.usable(
                    self._clock() if monotonic is None else monotonic)
            for rule in self._rules:
                if not rule.enabled:
                    continue
                active = self._rule_active_now(rule, now_minutes, weekday,
                                               weather)
                was = rule.id in self._layers
                # T-1244: an external STOP ALL (master mute) can retire the
                # channel underneath a layer.  The logical layer entry then
                # points at a dead handle; treat it as not-was so a later
                # evaluation restarts cleanly, while configuration is kept.
                if was and not self._hub.channel_alive(
                        self._layers[rule.id].handle):
                    self._layers.pop(rule.id, None)
                    was = False
                if active and not was:
                    if self._should_start(rule, active, was):
                        # Only report a change that actually became audible:
                        # a refused start is not a transition.
                        if self._start_layer(rule):
                            if rule.repeat == REPEAT_EVERY_INTERVAL:
                                self._last_interval_fire[rule.id] = self._clock()
                            changed.append(rule.id)
                elif not active and was:
                    self._fade_out_and_stop(self._layers.pop(rule.id),
                                            rule.fade_out_ms)
                    changed.append(rule.id)
                elif active and was and rule.repeat == REPEAT_EVERY_INTERVAL:
                    last = self._last_interval_fire.get(rule.id, 0.0)
                    if self._clock() - last >= rule.interval_seconds:
                        self._last_interval_fire[rule.id] = self._clock()
                        # A re-fire replaces its own layer: stop it for real
                        # before the next one starts, never overlap itself.
                        self._stop_layer_now(self._layers.pop(rule.id))
                        self._start_layer(rule)
                        changed.append(rule.id)
                self._prev_trigger_state[rule.id] = active
            return changed

    def _rule_active_now(self, rule, now_minutes, weekday, weather) -> bool:
        if rule.trigger == TRIGGER_ALWAYS:
            return True
        if rule.trigger == TRIGGER_TIME_WINDOW:
            day_ok = (not rule.weekdays) or weekday in [
                w.lower() for w in rule.weekdays]
            return day_ok and in_time_window(now_minutes, rule.start, rule.end)
        if rule.trigger == TRIGGER_WEEKDAY:
            return weekday == rule.weekday.lower()
        if rule.trigger == TRIGGER_WEATHER:
            return weather == rule.weather.lower()
        return False

    def _should_start(self, rule, active, was) -> bool:
        if rule.repeat == REPEAT_ON_ENTER:
            return bool(active) and not self._prev_trigger_state.get(rule.id, False)
        return True

    # -- layer lifecycle ----------------------------------------------------------

    def _start_layer(self, rule: AmbienceRule) -> bool:
        """Start one layer; False when nothing became audible."""
        if len(self._layers) >= self._max_layers:
            return False  # bounded layer count; ambience never floods
        loop = rule.repeat == REPEAT_LOOP
        fade_in = clamp_fade_ms(rule.fade_in_ms)
        start_volume = 0.0 if fade_in > 0 else rule.volume
        source = self._resolve(rule.sound_ref)
        if not source:
            return False    # unresolvable ref: stay silent, never guess
        result = self._hub.start_channel(
            source, event=f"ambience:{rule.id}", bus="ambience",
            volume=start_volume, loop=loop)
        handle = getattr(result, "channel", "") or ""
        if not handle:
            return False
        self._layers[rule.id] = _Layer(
            handle, rule.id, target_volume=rule.volume,
            current_volume=start_volume,
            fading="in" if fade_in > 0 else None, fade_total_ms=fade_in)
        return True

    def _stop_layer_now(self, layer: _Layer) -> None:
        """Physically stop one layer's channel immediately."""
        if layer.handle:
            try:
                self._hub.stop_channel_handle(layer.handle)
            except Exception:
                pass
        layer.handle = ""
        layer.fading = None

    def _fade_out_and_stop(self, layer: _Layer, fade_out_ms: int = 0) -> None:
        """Begin a real fade-out, or stop immediately for a 0 ms fade."""
        fade_out_ms = clamp_fade_ms(fade_out_ms)
        if fade_out_ms <= 0 or not layer.handle:
            self._stop_layer_now(layer)
            return
        layer.fading = "out"
        layer.fade_from = layer.current_volume
        layer.fade_total_ms = fade_out_ms
        layer.fade_elapsed_ms = 0
        self._fading_out.append(layer)

    # -- the ONE fade driver ---------------------------------------------------

    def tick_fades(self, elapsed_ms: int = FADE_STEP_MS) -> int:
        """Advance every active fade envelope by ``elapsed_ms``.

        ONE bounded driver owned by the controller advances every layer; the
        engine never creates a QTimer per layer.  Returns how many layers are
        still fading, so the controller can idle its timer.
        """
        step = max(1, int(elapsed_ms))
        with self._lock:
            self._fade_ticks_total += 1
            for layer in list(self._layers.values()):
                if layer.fading == "in":
                    self._advance_fade(layer, step, target=layer.target_volume)
            for layer in list(self._fading_out):
                self._advance_fade(layer, step, target=0.0)
                if layer.fading is None:
                    self._stop_layer_now(layer)
                    try:
                        self._fading_out.remove(layer)
                    except ValueError:
                        pass
            return self._fading_count()

    def _advance_fade(self, layer: _Layer, step_ms: int, *,
                      target: float) -> None:
        layer.fade_elapsed_ms += step_ms
        total = max(1, layer.fade_total_ms)
        ratio = min(1.0, layer.fade_elapsed_ms / total)
        volume = layer.fade_from + (target - layer.fade_from) * ratio
        layer.current_volume = max(0.0, min(1.0, volume))
        if layer.handle:
            try:
                self._hub.set_channel_volume(layer.handle,
                                             layer.current_volume)
            except Exception:
                pass
        if ratio >= 1.0:
            layer.fading = None
            layer.fade_elapsed_ms = 0

    def _fading_count(self) -> int:
        return (sum(1 for lay in self._layers.values() if lay.fading)
                + len(self._fading_out))

    def fading_layers(self) -> int:
        with self._lock:
            return self._fading_count()

    def layer_volume(self, rule_id: str) -> float | None:
        with self._lock:
            layer = self._layers.get(rule_id)
            return None if layer is None else layer.current_volume

    def layer_handle(self, rule_id: str) -> str:
        with self._lock:
            layer = self._layers.get(rule_id)
            return "" if layer is None else layer.handle

    @property
    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "active_layers": sorted(self._layers),
                "held_layers": self._held_layer_count if self._paused else 0,
                "paused": self._paused,
                "stopped": self._stopped,
                "weather_fetches": self._weather_fetches,
                "weather_generation": self._weather_generation,
                "fade_ticks_total": self._fade_ticks_total,
                "fading_out": len(self._fading_out),
            }


def _default_monotonic() -> float:
    import time

    return time.monotonic()
