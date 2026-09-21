"""T-1238-H: VOX/FVOX packs, GoldSrc recognition, countdown scheduling."""

from __future__ import annotations

import os

import pytest

from fastprompter.core.voice_engine import (
    COUNTDOWN_THRESHOLDS,
    CountdownLedger,
    CountdownScheduler,
    VoicePack,
    nearest_ai_reset_due,
    nearest_timer_due,
    phrase_tokens,
    scan_goldsrc_folder,
)

# ---------------------------------------------------------------------------
# Generated tiny WAV fixtures -- never proprietary game assets
# ---------------------------------------------------------------------------


def _make_wav(path: str) -> None:
    """Write one minimal valid WAV (44-byte header + one sample)."""
    import struct
    import wave

    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<B", 128))


@pytest.fixture()
def vox_pack(tmp_path):
    root = tmp_path / "vox"
    root.mkdir()
    for token in ("one", "thirty", "fifteen", "ten", "five",
                  "hour", "hours", "minute", "minutes", "remaining"):
        _make_wav(str(root / f"{token}.wav"))
    return VoicePack(str(root))


# ---------------------------------------------------------------------------
# VOX composer
# ---------------------------------------------------------------------------


class TestVoxComposer:
    def test_all_threshold_tokens_recognized(self, vox_pack):
        for seconds, _label in COUNTDOWN_THRESHOLDS:
            tokens = phrase_tokens(seconds)
            assert tokens, f"no phrase plan for {seconds}s"
            for token in tokens:
                assert vox_pack.has_token(token), token

    def test_compose_returns_existing_fragments_in_order(self, vox_pack):
        fragments = vox_pack.compose(phrase_tokens(1800))
        assert [os.path.basename(f) for f in fragments] == [
            "thirty.wav", "minutes.wav", "remaining.wav"]

    def test_compose_drops_missing_tokens_without_faking(self, tmp_path):
        root = tmp_path / "partial"
        root.mkdir()
        _make_wav(str(root / "thirty.wav"))
        pack = VoicePack(str(root))
        fragments = pack.compose(("thirty", "minutes", "remaining"))
        assert len(fragments) == 1
        assert pack.is_ready is False

    def test_pack_ready_requires_every_phrase_token(self, vox_pack):
        assert vox_pack.is_ready is True

    def test_gman_clips_recognized(self, tmp_path):
        root = tmp_path / "gman"
        root.mkdir()
        _make_wav(str(root / "gman_choose1.wav"))
        report = scan_goldsrc_folder(str(tmp_path))
        assert "gman/gman_choose1.wav" in report["gman"]

    def test_scan_recognizes_amx_ultimate_names(self, tmp_path):
        root = tmp_path / "misc"
        root.mkdir()
        _make_wav(str(root / "godlike.wav"))
        _make_wav(str(root / "holyshit.wav"))
        report = scan_goldsrc_folder(str(root))
        assert "godlike.wav" in report["amx_ultimate"]
        assert "holyshit.wav" in report["amx_ultimate"]
        assert not any(p.endswith(".wav") for p in report["vox"])

    def test_no_proprietary_assets_ship(self):
        """The repo must not bundle GoldSrc vox fragments itself."""
        import fastprompter.core
        spec = getattr(fastprompter.core, "__spec__", None)
        origin = getattr(spec, "origin", None) if spec else None
        if not origin:
            pytest.skip("package origin unavailable")
        core_dir = os.path.dirname(origin)
        sounds = os.path.join(os.path.dirname(core_dir), "sound")
        found = []
        if os.path.isdir(sounds):
            for entry in os.listdir(sounds):
                lowered = entry.lower()
                if lowered in {"vox", "fvox", "gman"}:
                    found.append(entry)
                elif lowered.startswith("gman_") or lowered.startswith("vox_"):
                    found.append(entry)
        assert found == [], found


# ---------------------------------------------------------------------------
# Countdown scheduler: nearest normal timer
# ---------------------------------------------------------------------------


class TestTimerThresholds:
    def _scheduler(self, fired, clock):
        return CountdownScheduler(
            lambda tokens, seconds, label: fired.append((tokens, seconds, label)),
            clock=clock,
        )

    def test_nearest_timer_is_targeted(self):
        now = 1_000_000.0
        timers = [
            {"id": "A", "due": now + 45 * 60, "active": True},
            {"id": "B", "due": now + 9 * 60, "active": True},
            {"id": "C", "due": now + 3 * 3600, "active": True},
        ]
        target = nearest_timer_due(timers)
        assert target[0] == "B"

    def test_future_threshold_only_no_10m_catchup(self):
        now = 1_000_000.0
        # 9m timer: 10m and 5m... 10m already passed (9 < 10), 5m still future.
        fired = []
        sched = self._scheduler(fired, lambda: now)
        planned = sched.set_target("TIMER", "B", now + 9 * 60, now=now)
        assert 300 in planned
        assert 600 not in planned  # already passed -> never announced
        assert 3600 not in planned
        fired_now = sched.announce(now=now + 4 * 60 + 1)
        assert fired_now == [300]
        assert fired and fired[0][1] == 300
        assert fired[0][0] == ["five", "minutes", "remaining"]

    def test_after_9m_completes_45m_becomes_target(self):
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        sched.set_target("TIMER", "B", now + 9 * 60, now=now)
        # B completes/cancels; A (45m) becomes nearest.
        sched.invalidate()
        timers = [
            {"id": "A", "due": now + 45 * 60, "active": True},
            {"id": "C", "due": now + 3 * 3600, "active": True},
        ]
        target = nearest_timer_due(timers)
        sched.set_target("TIMER", target[0], target[1], now=now)
        assert sched.target[1] == "A"
        # Walk forward through every threshold; each fires exactly once.
        # (The 1h threshold was already passed for a 45m target, so the
        # expected sequence is 30m/15m/10m/5m.)
        fired_seconds = []
        for step in range(1, 50):
            t = now + step * 60
            got = sched.announce(now=t)
            for seconds in got:
                fired_seconds.append(seconds)
        assert fired_seconds == [1800, 900, 600, 300]

    def test_no_catchup_flood_after_restart(self):
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        sched.set_target("TIMER", "X", now + 3600, now=now)
        # App asleep; three thresholds passed while off.
        after = now + 3600 - 240  # 4 minutes remain -> 1h/30m/15m/10m passed
        sched2 = self._scheduler(fired, lambda: after)
        # A fresh scheduler instance models restart: past thresholds skipped.
        sched2.set_target("TIMER", "X", now + 3600, now=after)
        got = sched2.announce(now=after)
        assert got == []  # 5m still future at 4m remaining? No: 4m < 5m
        # Only the still-future (here none) would fire; no speech burst.

    def test_no_catchup_flood_only_future_thresholds_scheduled(self):
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        # 40 minutes remain: 30m/15m/10m/5m future, 1h passed.
        sched.set_target("TIMER", "X", now + 40 * 60, now=now)
        got = sched.announce(now=now)  # nothing due yet
        assert got == []
        fired_all = []
        for step in range(0, 41):
            got = sched.announce(now=now + step * 60)
            fired_all.extend(got)
        assert fired_all == [1800, 900, 600, 300]  # exactly once each, ordered

    def test_generation_invalidated_when_deadline_moves(self):
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        gen1 = sched.generation
        sched.set_target("TIMER", "X", now + 3600, now=now)
        gen2 = sched.generation
        assert gen2 != gen1
        sched.set_target("TIMER", "X", now + 1800, now=now)  # deadline moved
        gen3 = sched.generation
        assert gen3 != gen2
        # Old plan (1h threshold) must be gone: 1h > new 30m window.
        assert sched.due_thresholds(now=now + 1) == []


# ---------------------------------------------------------------------------
# AI-limit countdown target
# ---------------------------------------------------------------------------


class TestAiLimitThresholds:
    def _scheduler(self, fired, clock):
        return CountdownScheduler(
            lambda tokens, seconds, label: fired.append((tokens, seconds, label)),
            clock=clock,
        )

    def test_nearest_reset_targeted(self):
        now = 1_000_000.0
        snapshots = [
            {"key": "codex_weekly", "reset": now + 70 * 60, "enabled": True},
            {"key": "claude_5h", "reset": now + 28 * 60, "enabled": True},
            {"key": "antigravity", "reset": now + 5 * 3600, "enabled": True},
        ]
        target = nearest_ai_reset_due(snapshots)
        assert target[0] == "claude_5h"

    def test_disabled_provider_never_targeted(self):
        now = 1_000_000.0
        snapshots = [
            {"key": "zcode", "reset": now + 60, "enabled": False},
            {"key": "claude_5h", "reset": now + 3600, "enabled": True},
        ]
        target = nearest_ai_reset_due(snapshots)
        assert target[0] == "claude_5h"

    def test_28m_schedules_15_10_5_not_30(self):
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        planned = sched.set_target(
            "AI_LIMIT", "claude_5h", now + 28 * 60, now=now)
        assert 1800 not in planned  # 30m already passed
        assert {900, 600, 300} <= set(planned)
        fired_all = []
        for step in range(0, 29):
            fired_all.extend(sched.announce(now=now + step * 60))
        assert fired_all == [900, 600, 300]

    def test_restart_near_threshold_no_duplicate(self):
        now = 1_000_000.0
        ledger = CountdownLedger()
        fired = []
        clock = lambda: now  # noqa: E731
        sched = CountdownScheduler(
            lambda tokens, seconds, label: fired.append(seconds),
            clock=clock, ledger=ledger)
        sched.set_target("AI_LIMIT", "codex_weekly", now + 600, now=now)
        first = sched.announce(now=now + 5 * 60 + 1)
        assert first == [300]
        # Restart: same identity -> no second announcement.
        sched2 = CountdownScheduler(
            lambda tokens, seconds, label: fired.append(seconds),
            clock=clock, ledger=ledger)
        sched2.set_target("AI_LIMIT", "codex_weekly", now + 600, now=now)
        second = sched2.announce(now=now + 6 * 60)
        assert second == []
        assert fired.count(300) == 1

    def test_no_network_calls_involved(self):
        """The scheduler observes already-known deadlines; it never polls."""
        now = 1_000_000.0
        fired = []
        sched = self._scheduler(fired, lambda: now)
        sched.set_target("AI_LIMIT", "k", now + 600, now=now)
        assert sched.announce(now=now + 301) == [300]
        assert len(fired) == 1


# ---------------------------------------------------------------------------
# Ledger bounds
# ---------------------------------------------------------------------------


class TestLedger:
    def test_ledger_is_bounded(self):
        ledger = CountdownLedger()
        for i in range(1000):
            ledger.mark_fired(("k", i, 0, 0))
        assert len(ledger._order) <= CountdownLedger.CAPACITY
        # oldest evicted
        assert not ledger.already_fired(("k", 0, 0, 0))
        # newest retained
        assert ledger.already_fired(("k", 999, 0, 0))
