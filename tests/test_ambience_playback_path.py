"""Two defects that made ambience completely silent (T-1242, user-reported).

1. ``AmbienceEngine._start_layer`` handed the hub the rule's library REF
   ("computalk1.wav") as if it were a path.  The transport asked
   ``os.path.isfile("computalk1.wav")``, got False, and refused the start --
   so every ambience layer died as FILE_MISSING.
2. ``_infinite_loop_value`` returned ``QSoundEffect.Loop.Infinite`` as an
   ENUM MEMBER, and PyQt6's ``setLoopCount(int)`` rejects it with TypeError.
   That killed every LOOPING sound, which is all of ambience.
"""

import os
import wave

import pytest

from fastprompter.core.ambience_engine import (
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.audio_hub import (
    AudioHub,
    FakeMultiChannelTransport,
    _infinite_loop_value,
)


def _rule(rule_id="amb", ref="computalk1.wav", **kw):
    return AmbienceRule(id=rule_id, name=rule_id, sound_ref=ref,
                        trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                        enabled=True, fade_in_ms=0, fade_out_ms=0, **kw)


class TestRefResolution:
    def test_the_engine_resolves_the_ref_before_playing(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        seen = []

        def resolver(ref):
            seen.append(ref)
            return f"V:/library/{ref}"

        engine = AmbienceEngine(hub, resolver=resolver)
        engine.set_rules([_rule()])
        assert engine.evaluate() == ["amb"]
        assert seen == ["computalk1.wav"]
        started = list(transport.channels.values())
        assert started and started[0]["path"] == "V:/library/computalk1.wav"

    def test_an_unresolvable_ref_stays_silent_instead_of_guessing(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        engine = AmbienceEngine(hub, resolver=lambda _ref: "")
        engine.set_rules([_rule()])
        assert engine.evaluate() == []
        assert transport.channels == {}

    def test_without_a_resolver_the_ref_is_used_verbatim(self):
        """Legacy/test callers hand in real paths already."""
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        engine = AmbienceEngine(hub)
        engine.set_rules([_rule(ref="V:/already/a/path.wav")])
        assert engine.evaluate() == ["amb"]

    def test_every_enabled_rule_starts_its_own_layer(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        engine = AmbienceEngine(hub, resolver=lambda ref: f"V:/lib/{ref}")
        engine.set_rules([_rule("a", "one.wav"), _rule("b", "two.wav")])
        assert engine.evaluate() == ["a", "b"]
        assert len(transport.channels) == 2

    def test_a_resolver_that_raises_is_not_a_crash(self):
        def boom(_ref):
            raise RuntimeError("resolver defect")

        transport = FakeMultiChannelTransport()
        engine = AmbienceEngine(AudioHub(transport=transport), resolver=boom)
        engine.set_rules([_rule()])
        assert engine.evaluate() == []


class TestSoundManagerResolver:
    def test_a_bare_library_name_resolves_to_an_absolute_wav(self):
        from fastprompter.core.sound_manager import SoundManager

        resolve = SoundManager.resolve_ref_path
        manager = SoundManager.__new__(SoundManager)
        manager._sounds_dir = os.path.join("src", "fastprompter", "sound")
        resolved = resolve(manager, "computalk1.wav")
        assert resolved and os.path.isfile(resolved)

    def test_an_unknown_name_resolves_to_nothing(self):
        from fastprompter.core.sound_manager import SoundManager

        manager = SoundManager.__new__(SoundManager)
        manager._sounds_dir = os.path.join("src", "fastprompter", "sound")
        assert SoundManager.resolve_ref_path(manager, "nope_missing.wav") == ""

    def test_an_absolute_existing_path_is_returned_unchanged(self, tmp_path):
        from fastprompter.core.sound_manager import SoundManager

        path = tmp_path / "x.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00\x01" * 10)
        manager = SoundManager.__new__(SoundManager)
        manager._sounds_dir = str(tmp_path)
        assert SoundManager.resolve_ref_path(manager, str(path)) == str(path)


class TestInfiniteLoopValue:
    def test_an_enum_member_is_reduced_to_a_plain_int(self):
        import enum

        class Loop(enum.Enum):
            Infinite = -2

        class Stub:
            pass

        Stub.Loop = Loop
        value = _infinite_loop_value(Stub)
        assert value == -2
        assert isinstance(value, int)
        assert not isinstance(value, Loop)

    def test_a_plain_int_survives(self):
        class Stub:
            class Loop:
                Infinite = -2

        assert _infinite_loop_value(Stub) == -2

    def test_a_backend_without_the_value_is_refused(self):
        class Stub:
            pass

        with pytest.raises(RuntimeError):
            _infinite_loop_value(Stub)

    def test_the_real_backend_yields_an_int_setloopcount_accepts(self, qapp):
        """PyQt6 setLoopCount(int) rejects the enum member with TypeError."""
        QSoundEffect = pytest.importorskip("PyQt6.QtMultimedia").QSoundEffect
        value = _infinite_loop_value(QSoundEffect)
        effect = QSoundEffect()
        effect.setLoopCount(value)           # must not raise
        assert effect.loopCount() == value
