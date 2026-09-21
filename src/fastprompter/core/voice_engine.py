"""VOX/FVOX/G-Man voice packs and the countdown scheduler (T-1238-H).

A voice pack is a folder of WAV fragments.  A phrase such as "thirty minutes
remaining" is composed from number/unit/remaining tokens and plays as ONE
logical :class:`~fastprompter.core.audio_hub.AudioHub` sequence -- never three
unrelated SoundManager events another click could reorder between.

The countdown scheduler targets the NEAREST active normal timer (or the
NEAREST known AI-limit reset), announces only still-future thresholds exactly
once, never catches up on thresholds that passed while the app was off, and
invalidates stale generations when a deadline moves.

No proprietary game audio ships with FastPrompter: packs are imported from
the user's own local GoldSrc/AMX files by the GoldSrc importer.
"""

from __future__ import annotations

import datetime as _datetime
import os

# Classic GoldSrc VOX token families.  Recognition only; importers must not
# invent files that do not exist.
VOX_NUMBER_TOKENS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "fourty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
)
VOX_UNIT_TOKENS = ("hour", "hours", "minute", "minutes", "second", "seconds")
VOX_REMAINING_TOKENS = ("remaining",)
FVOX_EXTRA_TOKENS = (
    "attention", "admonish", "decon", "detect", "doctor", "drop", "eject",
    "exiting", "field", "fire", "foreign", "freeman", "get", "had", "have",
    "hit", "immediate", "is", "it", "lie", "medic", "now", "officer", "on",
    "penal", "power", "reactor", "retrieve", "security", "service", "ship",
    "silo", "sir", "situation", "spam", "suits", "take", "team", "teleport",
    "terminat", "that", "time", "to", "up", "warhouse", "will", "with",
)
GMAN_CLIP_NAMES = ("gman_choose1", "gman_choose2")

AMX_ULTIMATE_NAMES = (
    "headshot", "multikill", "ultrakill", "monsterkill", "godlike",
    "killingspree", "humiliation", "rampage", "holyshit", "firstblood",
    "maytheforce", "oneandonly",
)

# Countdown thresholds the user configures, in descending order so the first
# still-future threshold wins.  Keys are seconds; values are display labels.
COUNTDOWN_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (3600, "1 hour"),
    (1800, "30 minutes"),
    (900, "15 minutes"),
    (600, "10 minutes"),
    (300, "5 minutes"),
)

# Phrase token plan per threshold: which tokens compose the spoken phrase.
_THRESHOLD_PHRASES: dict[int, tuple[str, ...]] = {
    3600: ("one", "hour", "remaining"),
    1800: ("thirty", "minutes", "remaining"),
    900: ("fifteen", "minutes", "remaining"),
    600: ("ten", "minutes", "remaining"),
    300: ("five", "minutes", "remaining"),
}


def phrase_tokens(threshold_seconds: int) -> tuple[str, ...]:
    """Token plan for one threshold phrase."""
    return _THRESHOLD_PHRASES.get(int(threshold_seconds), ())


class VoicePack:
    """A folder of WAV fragments with a pack type (VOX, FVOX, GMAN)."""

    def __init__(self, root: str, pack_type: str = "vox") -> None:
        self.root = root
        self.pack_type = "gman" if pack_type == "gman" else (
            "fvox" if pack_type == "fvox" else "vox")
        self._fragments: dict[str, str] | None = None

    def _scan(self) -> dict[str, str]:
        if self._fragments is None:
            fragments: dict[str, str] = {}
            if os.path.isdir(self.root):
                for entry in sorted(os.listdir(self.root)):
                    name, ext = os.path.splitext(entry)
                    if ext.lower() == ".wav":
                        fragments[name.lower()] = os.path.join(self.root, entry)
            self._fragments = fragments
        return self._fragments

    def has_token(self, token: str) -> bool:
        return token.lower() in self._scan()

    def fragment_path(self, token: str) -> str | None:
        return self._scan().get(token.lower())

    def compose(self, tokens: list[str] | tuple[str, ...]) -> list[str]:
        """Resolve token plan to existing fragment paths (missing are dropped)."""
        out: list[str] = []
        for token in tokens:
            path = self.fragment_path(token)
            if path:
                out.append(path)
        return out

    def ready_for_phrases(self, thresholds: list[int]) -> bool:
        """READY only when every required token for the given phrases exists."""
        needed: set[str] = set()
        for seconds in thresholds:
            needed.update(phrase_tokens(seconds))
        return bool(needed) and all(self.has_token(t) for t in needed)

    @property
    def is_ready(self) -> bool:
        """A pack is READY when it holds at least one complete phrase plan."""
        thresholds = [s for s, _ in COUNTDOWN_THRESHOLDS]
        return self.ready_for_phrases(thresholds)

    def diagnostics(self) -> dict[str, object]:
        fragments = self._scan()
        return {
            "root": self.root,
            "pack_type": self.pack_type,
            "fragment_count": len(fragments),
            "is_ready": self.is_ready,
            "missing_tokens": sorted(
                t for t in phrase_tokens(300) if t not in fragments),
        }


def scan_goldsrc_folder(root: str) -> dict[str, list[str]]:
    """Report one user-selected folder's recognisable GoldSrc/AMX content.

    Returns category -> sorted relative paths.  The importer never scans a
    whole drive and never downloads anything; the user chooses what to import.
    """
    report: dict[str, list[str]] = {
        "vox": [], "fvox": [], "gman": [], "amx_ultimate": [], "misc": [],
    }
    if not os.path.isdir(root):
        return report
    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        for filename in sorted(filenames):
            name, ext = os.path.splitext(filename)
            if ext.lower() != ".wav":
                continue
            rel = f"{rel_dir}/{filename}" if rel_dir != "." else filename
            lowered = name.lower()
            parent = rel_dir.rsplit("/", 1)[-1].lower() if rel_dir != "." else ""
            if parent == "vox" or (parent != "fvox" and parent != "gman"
                                   and lowered in VOX_NUMBER_TOKENS):
                    report["vox"].append(rel)
                    continue
            if parent == "fvox" or lowered in FVOX_EXTRA_TOKENS:
                report["fvox"].append(rel)
                continue
            if "gman" in rel.lower() or lowered in GMAN_CLIP_NAMES:
                report["gman"].append(rel)
                continue
            if lowered in AMX_ULTIMATE_NAMES:
                report["amx_ultimate"].append(rel)
                continue
            report["misc"].append(rel)
    return report


# ---------------------------------------------------------------------------
# Countdown scheduler
# ---------------------------------------------------------------------------


class CountdownLedger:
    """Bounded recent-fired ledger: each identity fires at most once."""

    CAPACITY = 256

    def __init__(self) -> None:
        self._fired: set[tuple] = set()
        self._order: list[tuple] = []

    def already_fired(self, identity: tuple) -> bool:
        return identity in self._fired

    def mark_fired(self, identity: tuple) -> None:
        if identity in self._fired:
            return
        self._fired.add(identity)
        self._order.append(identity)
        while len(self._order) > self.CAPACITY:
            dropped = self._order.pop(0)
            self._fired.discard(dropped)


class CountdownScheduler:
    """Announce future thresholds of ONE nearest target, exactly once.

    ``source_kind`` is ``TIMER`` or ``AI_LIMIT``; ``target_id`` identifies the
    timer or provider window; ``due`` is the epoch deadline.  A generation
    counter invalidates all pending announcements when the target changes.
    """

    def __init__(
        self,
        speak,  # Callable[[list[str], int, str], None]: fragments, threshold, label
        *,
        thresholds: tuple[tuple[int, str], ...] = COUNTDOWN_THRESHOLDS,
        clock=None,
        ledger: CountdownLedger | None = None,
    ) -> None:
        self._speak = speak
        self._thresholds = thresholds
        self._clock = clock or _default_epoch
        self._ledger = ledger if ledger is not None else CountdownLedger()
        self._generation = 0
        self._target: tuple[str, str, float] | None = None
        self._scheduled: set[int] = set()

    @property
    def target(self) -> tuple[str, str, float] | None:
        return self._target

    @property
    def generation(self) -> int:
        return self._generation

    def set_target(
        self,
        source_kind: str,
        target_id: str,
        due_epoch: float,
        *,
        now: float | None = None,
    ) -> dict[int, int]:
        """Point the scheduler at one target; return the planned threshold map.

        Only thresholds still in the future are scheduled.  Already-passed
        thresholds are NEVER announced (no catch-up flood).  A new target
        (or a moved deadline) bumps the generation, invalidating old plans.
        """
        self._generation += 1
        self._target = (source_kind, target_id, float(due_epoch))
        self._scheduled.clear()
        now_epoch = self._clock() if now is None else now
        planned: dict[int, int] = {}
        for seconds, label in self._thresholds:
            announce_at = float(due_epoch) - seconds
            if announce_at > now_epoch:
                planned[seconds] = self._generation
                self._scheduled.add(seconds)
        return planned

    def due_thresholds(self, now: float | None = None) -> list[int]:
        """Thresholds whose announcement time has arrived (earliest last).

        Announcing consumes them.  Already-passed-but-unfired thresholds are
        deliberately skipped, not queued for a bureaucratic catch-up speech.
        """
        if not self._target:
            return []
        now_epoch = self._clock() if now is None else now
        source_kind, target_id, due = self._target
        fired: list[int] = []
        for seconds, label in self._thresholds:
            if seconds not in self._scheduled:
                continue
            identity = (source_kind, target_id, round(due), seconds)
            if self._ledger.already_fired(identity):
                self._scheduled.discard(seconds)
                continue
            if now_epoch >= due - seconds:
                self._ledger.mark_fired(identity)
                self._scheduled.discard(seconds)
                fired.append(seconds)
        return fired

    def announce(self, now: float | None = None) -> list[int]:
        """Fire every due threshold as one voice sequence each."""
        fired = self.due_thresholds(now)
        if not self._target:
            return []
        for seconds in fired:
            label = dict(self._thresholds).get(seconds, "")
            fragments = phrase_tokens(seconds)
            try:
                self._speak(list(fragments), seconds, label)
            except Exception:
                pass
        return fired

    def invalidate(self) -> None:
        """Drop all pending plans (deadline moved or target completed)."""
        self._generation += 1
        self._target = None
        self._scheduled.clear()


def nearest_timer_due(timers: list[dict]) -> tuple[str, float] | None:
    """Nearest ACTIVE normal timer by due time.

    Completed/cancelled/absent timers never become the target.  Timers carry
    ``id``, ``due`` (epoch) and optional ``active`` (default True).
    """
    best: tuple[str, float] | None = None
    for timer in timers:
        if not timer.get("active", True):
            continue
        due = timer.get("due")
        if due is None:
            continue
        try:
            due_value = float(due)
        except (TypeError, ValueError):
            continue
        if best is None or due_value < best[1]:
            best = (str(timer.get("id", "")), due_value)
    return best


def nearest_ai_reset_due(snapshots: list[dict]) -> tuple[str, float] | None:
    """Nearest known upcoming AI-limit reset among enabled providers.

    ``snapshots`` are pre-resolved provider windows (the canonical AI-limit
    model's output); this observer NEVER polls providers itself.  Entries
    carry ``key`` and ``reset`` (epoch); disabled/exhausted-forever windows
    are excluded by the caller through ``enabled``.
    """
    best: tuple[str, float] | None = None
    for snapshot in snapshots:
        if snapshot.get("enabled") is False:
            continue
        reset = snapshot.get("reset")
        if reset is None:
            continue
        try:
            reset_value = float(reset)
        except (TypeError, ValueError):
            continue
        if reset_value <= 0:
            continue
        if best is None or reset_value < best[1]:
            best = (str(snapshot.get("key", "")), reset_value)
    return best


def _default_epoch() -> float:
    return _datetime.datetime.now().timestamp()
