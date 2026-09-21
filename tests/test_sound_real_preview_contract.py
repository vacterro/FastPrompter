"""T-1242 spec 3/4/7/8: a Preview is one real physical start, or a truthful
explanation of why it was not.

The reported defect was that most explicit previews and alerts came back as
``STOPPED`` with no reason at all, because ``QtSoundTransport.play()``
swallowed every exception and returned ``""`` and the hub turned that into a
bare ``Outcome.STOPPED``.  The real cause was a ``NameError`` in the
device-rate render path; these tests pin BOTH the cause and the contract that
would have made it visible.
"""

import os
import wave

import pytest

from fastprompter.core import audio_render
from fastprompter.core.audio_hub import (
    AudioHub,
    Bus,
    NullTransport,
    Outcome,
    QtSoundTransport,
    StopReason,
)

REAL_SOUNDS = os.path.join("src", "fastprompter", "sound")


@pytest.fixture(autouse=True)
def _render_switch_on(monkeypatch):
    """This suite exercises the RENDERER's own contract, so the A/B master
    switch is pinned ON here.  The switch defaults OFF in the product
    (T-1242 spec 8/9: raw playback is the control path); tests that pin the
    DEFAULT itself live in test_audio_render_defaults.py."""
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)


# The assets named in the user's diagnostic paste.
DIAGNOSTIC_FILES = [
    "tick_on.wav", "success_scored.wav", "success_powerup.wav",
    "success_levelup.wav", "success_trade_success.wav",
    "step_woodpanel3.wav", "click_hint.wav", "Hello.wav", "HORSE09.wav",
    "HORSE00.wav", "chat_display_text.wav", "blip01.wav",
]


# --------------------------------------------------------------------------
# the render path never raises: it renders, or declines to the original
# --------------------------------------------------------------------------

class TestDeviceRenderNeverRaises:
    def test_a_cold_source_renders_instead_of_raising(self, tmp_path):
        """The T-1242 root cause: an undefined cache key raised NameError,
        which is not an OSError and so escaped the narrow except clause,
        landed in the transport's broad ``except Exception`` and became an
        unexplained STOPPED for every not-yet-cached sound."""
        source = tmp_path / "cold.wav"
        with wave.open(str(source), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x01" * 4000)
        out = audio_render.device_ready_wav(str(source), 48000)
        assert out and os.path.isfile(out)
        with wave.open(out, "rb") as wf:
            assert wf.getframerate() == 48000

    @pytest.mark.parametrize("name", DIAGNOSTIC_FILES)
    def test_every_diagnostic_asset_renders_or_declines_cleanly(self, name):
        path = os.path.join(REAL_SOUNDS, name)
        if not os.path.isfile(path):
            pytest.skip(f"{name} not in this checkout")
        out = audio_render.device_ready_wav(path, 48000)
        # None is only legitimate when the source is already at 48 kHz.
        if out is None:
            with wave.open(path, "rb") as wf:
                assert wf.getframerate() == 48000
        else:
            assert os.path.isfile(out)

    def test_an_unexpected_internal_error_degrades_to_the_original_file(
            self, tmp_path, monkeypatch):
        source = tmp_path / "boom.wav"
        with wave.open(str(source), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x01" * 400)

        def _explode(_path):
            raise RuntimeError("simulated internal defect")

        monkeypatch.setattr(audio_render, "_source_digest", _explode)
        assert audio_render.device_ready_wav(str(source), 48000) is None


# --------------------------------------------------------------------------
# source readiness: what the transport does with a Loading / Error source
# --------------------------------------------------------------------------

class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self):
        for slot in list(self._slots):
            slot()


class FakeEffect:
    """Enough QSoundEffect to exercise the readiness contract."""

    class Loop:
        Infinite = -2

    class Status:
        Null = 0
        Loading = 1
        Ready = 2
        Error = 3

    def __init__(self):
        self._status = FakeEffect.Status.Loading
        self._playing = False
        self.play_calls = 0
        self.playingChanged = _Signal()
        self.statusChanged = _Signal()

    # -- the transport's capability probe uses these names -----------------
    def setSource(self, _url):
        pass

    def setVolume(self, _v):
        pass

    def setLoopCount(self, _n):
        pass

    def status(self):
        return self._status

    def errorString(self):
        return "fake source error" if self._status == 3 else ""

    def isPlaying(self):
        return self._playing

    def play(self):
        self.play_calls += 1
        self._playing = True
        self.playingChanged.emit()

    def stop(self):
        self._playing = False
        self.playingChanged.emit()

    # -- test helpers -------------------------------------------------------
    def become(self, status):
        self._status = status
        self.statusChanged.emit()


def _fake_transport(monkeypatch, made):
    def factory():
        effect = FakeEffect()
        made.append(effect)
        return effect

    factory.Loop = FakeEffect.Loop
    factory.Status = FakeEffect.Status
    for name in ("setSource", "setVolume", "setLoopCount", "play", "stop",
                 "isPlaying", "playingChanged"):
        setattr(factory, name, True)
    return QtSoundTransport(qsoundeffect_cls=factory,
                            url_factory=lambda path: path)


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "cue.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x01" * 2000)
    return str(path)


class TestSourceReadiness:
    # T-1242 P0: the old contract ("a Loading cue is held and starts
    # whenever it becomes Ready") WAS the stale-resurrection defect.  A late
    # sound is not the same sound: a Loading source is refused NOW.
    def test_a_loading_source_is_refused_now(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        handle = transport.play(wav, token="req1")
        assert handle == "", "no handle for a cue that did not start now"
        assert made[0].play_calls == 0
        assert transport.take_failure("req1")["reason"] == \
            StopReason.SOURCE_LOADING.value
        assert transport.active_handles() == []

    def test_a_late_ready_never_replays_the_refused_cue(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        transport.play(wav, token="req1")
        made[0].become(FakeEffect.Status.Ready)
        made[0].become(FakeEffect.Status.Ready)     # a second Ready signal
        assert made[0].play_calls == 0, "Ready must not start an old request"
        # ...it only makes the effect available to a FUTURE request.
        assert transport.play(wav, token="req2")
        assert made[0].play_calls == 1

    def test_a_ready_source_starts_immediately(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        transport.preload([wav])
        made[0]._status = FakeEffect.Status.Ready
        transport.play(wav, token="req1")
        assert made[0].play_calls == 1

    def test_stop_before_ready_cancels_the_pending_start(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        handle = transport.play(wav, token="req1")
        transport.stop(handle)
        made[0].become(FakeEffect.Status.Ready)
        assert made[0].play_calls == 0, "a stopped cue must not resume"

    def test_stop_all_kills_a_pending_start(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        transport.play(wav, token="req1")
        transport.stop_all()
        made[0].become(FakeEffect.Status.Ready)
        assert made[0].play_calls == 0

    def test_an_error_status_fails_truthfully(self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        transport.preload([wav])
        made[0].become(FakeEffect.Status.Error)
        assert transport.play(wav, token="req1") == ""
        assert made[0].play_calls == 0
        detail = transport.take_failure("req1")
        assert detail["reason"] == StopReason.SOURCE_ERROR.value
        assert detail["error"] == "fake source error"

    def test_a_loading_effect_is_not_mistaken_for_a_finished_one(
            self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        done = []
        transport.play(wav, token="req1", on_complete=lambda: done.append(1))
        transport._on_playing_changed(made[0])       # isPlaying() is False
        assert done == []


# --------------------------------------------------------------------------
# a refused start always explains itself
# --------------------------------------------------------------------------

class TestFailureProvenance:
    def test_a_missing_file_is_reported_as_file_missing(self, monkeypatch,
                                                        tmp_path):
        transport = _fake_transport(monkeypatch, [])
        assert transport.play(str(tmp_path / "nope.wav"), token="r") == ""
        detail = transport.take_failure("r")
        assert detail["reason"] == StopReason.FILE_MISSING.value
        assert detail["file_exists"] is False

    def test_an_exhausted_pool_is_reported_as_pool_exhausted(self, monkeypatch,
                                                             wav):
        made = []
        transport = _fake_transport(monkeypatch, made)
        for index in range(QtSoundTransport.POOL_PER_PATH):
            # each new pooled effect is born Loading and is refused once
            assert transport.play(wav, token=f"cold{index}") == ""
            made[index].become(FakeEffect.Status.Ready)
            assert transport.play(wav, token=f"r{index}")
        assert transport.play(wav, token="over") == ""
        assert transport.take_failure("over")["reason"] == \
            StopReason.POOL_EXHAUSTED.value

    def test_the_null_transport_says_it_is_unavailable(self, wav):
        transport = NullTransport()
        assert transport.play(wav, token="r") == ""
        assert transport.take_failure("r")["reason"] == \
            StopReason.TRANSPORT_UNAVAILABLE.value

    def test_the_hub_carries_the_reason_into_its_provenance(self, wav):
        hub = AudioHub(transport=NullTransport())
        result = hub.play_result(wav, event="preview", bus=Bus.PREVIEW)
        assert result.outcome is Outcome.STOPPED
        entry = hub.provenance()[-1]
        assert entry["outcome"] == "STOPPED"
        assert entry["reason"] == StopReason.TRANSPORT_UNAVAILABLE.value
        assert "STOPPED" != entry.get("reason")     # never an empty excuse

    def test_no_stopped_outcome_is_ever_left_unexplained(self, wav):
        hub = AudioHub(transport=NullTransport())
        for index in range(3):
            hub.play_result(wav, event=f"e{index}", bus=Bus.PREVIEW)
        for entry in hub.provenance():
            if entry["outcome"] == "STOPPED":
                assert entry.get("reason"), entry

    def test_a_failure_detail_never_carries_the_exception_message(
            self, monkeypatch, wav):
        made = []
        transport = _fake_transport(monkeypatch, made)

        def _boom(_self, _value):
            raise RuntimeError("secret path C:/private/user.wav")

        # setLoopCount runs AFTER the pool acquire, so the failure is
        # attributed to the play attempt itself.
        transport.preload([wav])
        made[0]._status = FakeEffect.Status.Ready
        original = FakeEffect.setLoopCount
        FakeEffect.setLoopCount = _boom
        try:
            assert transport.play(wav, token="r") == ""
        finally:
            FakeEffect.setLoopCount = original
        detail = transport.take_failure("r")
        assert detail["exception"] == "RuntimeError"
        assert "secret" not in repr(detail)
