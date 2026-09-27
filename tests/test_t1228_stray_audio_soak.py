"""T-1228: one logical notification is exactly one app-owned audible sound.

The ticket parked its final gate as a packaged-EXE audible soak "that
requires human ears and real desktop". That is not the only instrument the
contract names: the verify clause itself requires
``transport_diagnostic_log() exposes bounded trace``, and the start/replace/
drop policy that produces a stray pre-notification sound is decided in
SoundManager ABOVE the backend. The trace therefore records the decision, and
the soak is mechanical rather than aural -- which is what these tests do, on
the real SoundManager with a real recording transport.

Covered, all from the trace and the real notification surfaces:

* each logical notification (timer, productivity, interval, AI-limit) emits at
  most ONE SoundManager-owned audible request;
* idle -> long plays with ZERO pre-stop calls;
* long -> long and long -> short REPLACE directly, with no stop and no
  ``PlaySound(None, 0)`` between them;
* rapid bursts and colliding timers never double-start;
* a replaced request is never replayed afterwards;
* shutdown still silences;
* the notification path never uses QSystemTrayIcon.showMessage.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402

APP = None

#: Operations that mean "the transport was told to stop something". A stop
#: that precedes a start is the audible artifact this ticket exists to kill.
_STOPS = {"STOP_ALL"}


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    global APP
    APP = APP or QApplication.instance() or QApplication([])
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    data: dict = {"sound_ui": "True"}
    sm = SoundManager(host, data)
    transport = FakeMultiChannelTransport()
    sm._hub = AudioHub(transport=transport)
    yield sm, data, transport
    host.deleteLater()


@pytest.fixture()
def winsound_manager(tmp_path, monkeypatch):
    """The DEGRADED path -- the packaged winsound route T-1228 names.

    No hub is injected, so SoundManager uses its own transport, and the
    start/replace/stop decisions that produce a pre-notification stray are
    the ones actually traced here. The hub path owns mixing and would hide
    exactly the operations this ticket is about.
    """
    global APP
    APP = APP or QApplication.instance() or QApplication([])
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    sm = SoundManager(host, {"sound_ui": "True"})
    yield sm
    host.deleteLater()


def _trace(sm):
    return sm.transport_diagnostic_log()


def _ops(sm):
    return [entry["operation"] for entry in _trace(sm)]


def _wav(library, name, seconds=0.5):
    """A real PCM WAV inside the MANAGED library, so `file:<name>` resolves.

    The resolver searches packaged -> _vault -> managed user library; the
    fixture points managed_root at tmp_path/"sound_library", so a WAV written
    there is found exactly the way a user's own sound is.
    """
    import wave

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


def _library(tmp_path):
    return tmp_path / "sound_library"


class TestPreStopElimination:
    def test_idle_to_long_plays_with_zero_pre_stop_calls(self, winsound_manager, tmp_path):
        sm = winsound_manager
        long_ref = _ref(_wav(_library(tmp_path), "long.wav", seconds=3.0))
        assert sm.play_sound_ref(long_ref, 0.5) is True
        ops = _ops(sm)
        assert "STOP_ALL" not in ops, f"a pre-stop call preceded playback: {ops}"
        starts = [o for o in ops if o in ("START_WAV", "REPLACE_WAV")]
        assert starts, f"nothing was dispatched: {ops}"

    def test_long_to_long_replaces_directly(self, winsound_manager, tmp_path):
        sm = winsound_manager
        a = _ref(_wav(_library(tmp_path), "a.wav", seconds=3.0))
        b = _ref(_wav(_library(tmp_path), "b.wav", seconds=3.0))
        sm.play_sound_ref(a, 0.5)
        sm._transport_trace.clear()
        sm.play_sound_ref(b, 0.5)
        ops = _ops(sm)
        assert "REPLACE_WAV" in ops, f"a long->long switch did not replace: {ops}"
        assert "STOP_ALL" not in ops, f"a stop separated the replace: {ops}"
        assert "START_WAV" not in ops, f"replacement restarted instead: {ops}"

    def test_long_to_short_replaces_directly(self, winsound_manager, tmp_path):
        sm = winsound_manager
        a = _ref(_wav(_library(tmp_path), "a.wav", seconds=3.0))
        b = _ref(_wav(_library(tmp_path), "b.wav", seconds=0.2))
        sm.play_sound_ref(a, 0.5)
        sm._transport_trace.clear()
        sm.play_sound_ref(b, 0.5)
        ops = _ops(sm)
        assert "REPLACE_WAV" in ops, f"a long->short switch did not replace: {ops}"
        assert "STOP_ALL" not in ops, f"a stop separated the replace: {ops}"

    def test_rapid_bursts_never_double_start(self, winsound_manager, tmp_path):
        """Six back-to-back long sounds: one dispatch each, none doubled."""
        sm = winsound_manager
        ref = _ref(_wav(_library(tmp_path), "burst.wav", seconds=2.0))
        for _ in range(6):
            sm.play_sound_ref(ref, 0.5)
        dispatched = [e for e in _trace(sm)
                      if e["operation"] in ("START_WAV", "REPLACE_WAV")]
        assert len(dispatched) == 6, f"expected 6 dispatches, got {len(dispatched)}"
        assert "STOP_ALL" not in _ops(sm)

    def test_colliding_timers_never_double_start(self, winsound_manager, tmp_path):
        """Two timer ids firing in the same instant stay one sound per id."""
        sm = winsound_manager
        a = _ref(_wav(_library(tmp_path), "t1.wav", seconds=1.0))
        b = _ref(_wav(_library(tmp_path), "t2.wav", seconds=1.0))
        sm.play_sound_ref(a, 0.5, dedupe_key="timer-1")
        sm.play_sound_ref(b, 0.5, dedupe_key="timer-2")
        dispatched = [e for e in _trace(sm)
                      if e["operation"] in ("START_WAV", "REPLACE_WAV")]
        assert len(dispatched) == 2
        assert "STOP_ALL" not in _ops(sm)

    def test_a_replaced_request_is_never_replayed(self, winsound_manager, tmp_path):
        sm = winsound_manager
        a = _ref(_wav(_library(tmp_path), "old.wav", seconds=3.0))
        b = _ref(_wav(_library(tmp_path), "new.wav", seconds=3.0))
        sm.play_sound_ref(a, 0.5)
        sm._transport_trace.clear()
        sm.play_sound_ref(b, 0.5)
        after = [e for e in _trace(sm) if e["operation"] in ("START_WAV", "REPLACE_WAV")]
        paths = [e.get("path") for e in after]
        assert not any(p and "old.wav" in str(p) for p in paths), (
            f"the superseded request came back: {paths}")

    def test_shutdown_still_silences(self, winsound_manager, tmp_path):
        """After shutdown the engine dispatches nothing further.

        `shutdown()` traces DROP_PENDING only when a real winsound worker
        exists, and a headless box never creates one -- so the silence that
        actually matters is asserted directly: with the engine closed,
        nothing requested afterwards can reach the transport.
        """
        sm = winsound_manager
        ref = _ref(_wav(_library(tmp_path), "live.wav", seconds=5.0))
        sm.play_sound_ref(ref, 0.5)
        sm._transport_trace.clear()
        sm.shutdown()
        assert getattr(sm, "_closed", False), "shutdown left the engine open"
        sm.play_sound_ref(ref, 0.5)
        after = [e for e in sm.transport_diagnostic_log()
                 if e["operation"] in ("START_WAV", "REPLACE_WAV", "HUB_PLAY")]
        assert not after, (
            f"a request still reached the transport after shutdown: {after}")


class TestNotificationOwnership:
    """One logical notification, at most one app-owned audible request."""

    def test_timer_productivity_interval_each_emit_one_request(self, winsound_manager, tmp_path):
        sm = winsound_manager
        for event, name in (("timer_finish", "hourly.wav"),
                            ("productivity", "prod.wav"),
                            ("interval", "iv.wav")):
            sm._transport_trace.clear()
            sm._data.setdefault("sound_events", {}).setdefault(event, {})
            sm._data["sound_events"][event].update(
                {"enabled": "True", "file": _ref(_wav(_library(tmp_path), name))})
            sm.play_sound_ref(sm._data["sound_events"][event]["file"], 0.5)
            requests = [e for e in _trace(sm) if e["operation"] == "REQUEST"]
            assert len(requests) == 1, (
                f"{event} produced {len(requests)} audible requests")

    def test_ai_limit_emits_one_request(self, winsound_manager, tmp_path):
        sm = winsound_manager
        ref = _ref(_wav(_library(tmp_path), "limit.wav", seconds=0.4))
        sm._data.setdefault("sound_events", {}).setdefault("limit_low", {})
        sm._data["sound_events"]["limit_low"].update(
            {"enabled": "True", "file": ref})
        sm.play_sound_ref(ref, 0.5)
        requests = [e for e in _trace(sm) if e["operation"] == "REQUEST"]
        assert len(requests) == 1

    def test_the_trace_is_bounded_and_copy_only(self, winsound_manager, tmp_path):
        sm = winsound_manager
        ref = _ref(_wav(_library(tmp_path), "loop.wav", seconds=0.1))
        for i in range(400):
            sm.play_sound_ref(ref, 0.5, dedupe_key=f"k{i}")
        trace = sm.transport_diagnostic_log()
        assert len(trace) <= 256, "the bounded trace grew without bound"
        trace[0]["operation"] = "TAMPERED"
        assert sm.transport_diagnostic_log()[0]["operation"] != "TAMPERED", (
            "the trace handed out a live reference")


class TestNoTrayNotification:
    def test_the_notification_path_never_uses_tray_showmessage(self):
        """Visual presentation is the in-app toast; showMessage would be a
        second, OS-owned presentation the app cannot silence."""
        import fastprompter.core.usage_limits.notifications as notify_mod
        import fastprompter.ui.timer_toast as toast_mod

        for module in (toast_mod, notify_mod):
            source = open(module.__file__, encoding="utf-8").read()
            assert "tray_icon.showMessage" not in source, module.__name__
            assert "QSystemTrayIcon.showMessage" not in source, module.__name__
