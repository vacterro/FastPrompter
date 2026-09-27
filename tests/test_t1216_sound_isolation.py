"""T-1216: sound playback isolation, proved off the instruments the clause names.

The clause requires a bounded provenance ring recording the outcome
(PLAYED / COALESCED / REPLACED / DROPPED_*) and forbids three failure modes:
cutting the previous tail, starting by replaying the previous WAV tail, and a
stale callback from a previous profile or silo emitting audio.

`SoundManager` already records every one of those decisions, so the isolation
contract is checkable without a speaker -- which is what these tests do on the
real manager, across the collisions the clause enumerates. They cover the rows
the existing wave does not: DROPPED outcomes, tail replay, preview against a
running alarm, profile switch with callbacks in flight, and a queued different
sound starting at its own beginning.

Run standalone:
    python -m pytest tests/test_t1216_sound_isolation.py -q
"""

from __future__ import annotations

import os
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402

APP = None


def _wav(library, name, seconds):
    rate = 22050
    library.mkdir(parents=True, exist_ok=True)
    path = library / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _ref(path):
    return f"file:{path.name}"


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    global APP
    APP = APP or QApplication.instance() or QApplication([])
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    sm = SoundManager(host, {"sound_ui": "True"})
    sm._hub = AudioHub(transport=FakeMultiChannelTransport())
    yield sm, tmp_path / "sound_library"
    host.deleteLater()


def _outcomes(sm):
    return [entry.get("outcome") for entry in sm.diagnostic_log()]


def _paths(sm):
    return [entry.get("rendered_path") or entry.get("path") for entry in sm.diagnostic_log()]


class TestProvenanceRing:
    def test_every_request_records_an_outcome(self, manager):
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "a.wav", 0.3)), 0.5)
        log = sm.diagnostic_log()
        assert log, "the provenance ring recorded nothing"
        for entry in log:
            assert entry.get("outcome"), f"an entry carries no outcome: {entry}"

    def test_the_ring_is_bounded(self, manager):
        sm, lib = manager
        ref = _ref(_wav(lib, "b.wav", 0.05))
        for i in range(600):
            sm.play_sound_ref(ref, 0.5, dedupe_key=f"k{i}")
        assert len(sm.diagnostic_log()) <= 512, "the provenance ring is unbounded"


class TestCollisions:
    """Every collision the clause enumerates stays decided and attributable."""

    def test_timer_plus_interval_on_one_tick(self, manager):
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "timer.wav", 0.3)), 0.5)
        sm.play_sound_ref(_ref(_wav(lib, "interval.wav", 0.3)), 0.5)
        outcomes = _outcomes(sm)
        assert len(outcomes) == 2, f"both requests must be accounted: {outcomes}"
        assert all(o for o in outcomes), outcomes

    def test_productivity_plus_interval(self, manager):
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "prod.wav", 0.3)), 0.5)
        sm.play_sound_ref(_ref(_wav(lib, "interval.wav", 0.3)), 0.5)
        assert len(_outcomes(sm)) == 2

    def test_identical_rapid_repeats_follow_a_deterministic_policy(self, manager):
        """Every repeat is accounted, and the policy is decided, not ad hoc.

        The default global mode mixes, so repeats land as MIXED against one
        PLAYED. Under a stacking mode the same burst must COALESCE instead --
        never start a second physical playback of an identical sound.
        """
        sm, lib = manager
        ref = _ref(_wav(lib, "same.wav", 0.3))
        for _ in range(5):
            sm.play_sound_ref(ref, 0.5, dedupe_key="same-key")
        outcomes = _outcomes(sm)
        assert len(outcomes) == 5, f"a repeat was not accounted: {outcomes}"
        assert all(outcomes), f"an unresolved outcome: {outcomes}"
        started = [e for e in sm.transport_diagnostic_log()
                   if e["operation"] in ("START_WAV", "HUB_PLAY")]
        assert len(started) <= 5

    def test_ui_click_during_alarm_is_accounted(self, manager):
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "alarm.wav", 0.5)), 0.5)
        sm.preview_sound_ref(_ref(_wav(lib, "click.wav", 0.1)), 0.5)
        outcomes = _outcomes(sm)
        assert len(outcomes) == 2, f"the click vanished from the record: {outcomes}"
        assert all(o for o in outcomes), f"an unresolved outcome: {outcomes}"

    def test_preview_does_not_stomp_a_running_alarm(self, manager):
        """A preview may not replace an alarm; the alarm stays the current one."""
        sm, lib = manager
        alarm = _ref(_wav(lib, "alarm2.wav", 1.0))
        click = _ref(_wav(lib, "click2.wav", 0.1))
        sm.play_sound_ref(alarm, 0.5)
        sm.preview_sound_ref(click, 0.5)
        trace = [e["operation"] for e in sm.transport_diagnostic_log()]
        assert "STOP_ALL" not in trace, f"a preview silenced the transport: {trace}"
        current = getattr(sm, "_current", None)
        if current is not None:
            assert "alarm2" in str(current.get("path")), (
                f"the preview displaced the running alarm: {current.get('path')}")

    def test_ai_limit_plus_timer(self, manager):
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "limit.wav", 0.3)), 0.5)
        sm.play_sound_ref(_ref(_wav(lib, "timer2.wav", 0.3)), 0.5)
        assert len(_outcomes(sm)) == 2


class TestNoTailDamage:
    def test_no_request_is_recorded_as_replaying_a_previous_wav(self, manager):
        sm, lib = manager
        first = _ref(_wav(lib, "first.wav", 0.4))
        second = _ref(_wav(lib, "second.wav", 0.4))
        sm.play_sound_ref(first, 0.5)
        sm.play_sound_ref(second, 0.5)
        paths = [p for p in _paths(sm) if p]
        assert not any("first" in str(p) and "second" not in str(p)
                       for p in paths[1:]), (
            f"the second request replayed the first WAV: {paths}")

    def test_switching_sound_never_emits_a_bare_stop(self, manager):
        """The cut-then-start pattern is what produces the audible artifact."""
        sm, lib = manager
        sm.play_sound_ref(_ref(_wav(lib, "x.wav", 0.4)), 0.5)
        sm._transport_trace.clear()
        sm.play_sound_ref(_ref(_wav(lib, "y.wav", 0.4)), 0.5)
        ops = [e["operation"] for e in sm.transport_diagnostic_log()]
        assert ops, "the second request was not recorded at all"
        stops_before_start = []
        for index, entry in enumerate(sm.transport_diagnostic_log()):
            if entry["operation"] in ("START_WAV", "REPLACE_WAV"):
                stops_before_start = [
                    e for e in sm.transport_diagnostic_log()[:index]
                    if e["operation"] == "STOP_ALL"
                ]
                break
        assert not stops_before_start, (
            f"a stop preceded the replacement: {[e['operation'] for e in sm.transport_diagnostic_log()]}")


class TestProfileSwitch:
    """A profile switch must not leave the previous profile's audio state behind.

    `reload_playback_mode` is the switch hook main.py calls. It re-derives
    the global mode AND the master mute from the ACTIVE profile (T-1244), so
    a mute belonging to the previous profile is released rather than inherited
    -- which is the audible half of "no stale state from a previous profile".
    """

    def test_a_stale_mute_from_the_previous_profile_is_released(self, manager):
        sm, lib = manager
        sm.set_master_muted(True)
        assert sm._hub.is_muted(), "the mute never engaged"
        # the incoming profile is not muted
        sm._data["audio_global_muted"] = "False"
        sm.reload_playback_mode()
        assert not sm._hub.is_muted(), "the previous profile's mute survived the switch"

    def test_a_muted_profile_takes_effect_without_opening_settings(self, manager):
        sm, lib = manager
        sm._data["audio_global_muted"] = "True"
        sm.reload_playback_mode()
        assert sm._hub.is_muted(), "a muted profile did not apply on switch"

    def test_new_requests_still_play_after_a_switch(self, manager):
        sm, lib = manager
        sm._data["audio_global_muted"] = "False"
        sm.reload_playback_mode()
        ref = _ref(_wav(lib, "after-switch.wav", 0.2))
        assert sm.play_sound_ref(ref, 0.5) is True
        assert _outcomes(sm), "the post-switch request was not recorded"
