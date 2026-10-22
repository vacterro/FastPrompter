"""T-1455: the shipped default ambience rule + 24h Chime preset default.

Covers:
- Fresh install: ensure_default_rules seeds one enabled loop (0.01,
  TRIGGER_ALWAYS/REPEAT_LOOP) and runtime_enabled=True.
- Existing rule or decision row -> no seed (idempotent, no resurrection).
- Fresh controller start_if_remembered returns True (first launch plays).
- The default's sound ref resolves against the PACKAGED tree alone.
- A database seeded by a pre-T-1501 build is repaired in place (T-1501).
- 24h cycle: DEFAULT_PROFILE["interval_notifs"] == daypart_chime_rules()
  and timer_dialog imports the same canonical preset.

Uses pytest tmp_path (not tempfile) like the neighbor ambience suites: the
live audio.db must not be unlinked on Windows while a connection object is
still collecting; pytest defers tmp cleanup past the test frame.

T-1501: the suite used to assert the literal string "computalk1.wav" in
three places, and its resolve check passed only because the operator's
personal addon folder happens to hold a file of that name. That made the
default look healthy while a fresh data root played nothing at all. Every
assertion here is now derived from the shipped default itself, and the
resolution check runs against the packaged tree with the addon and user
roots deliberately pointed at empty directories.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.ambience_engine import AmbienceEngine  # noqa: E402
from fastprompter.core.ambience_store import (  # noqa: E402
    DEFAULT_AMBIENCE_RULE_ID,
    DEFAULT_AMBIENCE_SOUND_REF,
    AmbienceStore,
    default_ambience_rules,
    ensure_default_rules,
    is_fresh_database,
    repair_dead_default_ref,
)
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.default_profile import DEFAULT_PROFILE  # noqa: E402
from fastprompter.core.interval_presets import (  # noqa: E402
    DAYPART_CHIME_RULES,
    daypart_chime_rules,
)
from fastprompter.core.sound_library import (  # noqa: E402
    packaged_root,
    resolve_sound_ref,
)
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402

_APP = None

#: The one file the pre-fix default named.  Kept as text on purpose: it is
#: the DEAD name, and the only place it may still appear in this suite is the
#: repair control that proves a database holding it gets fixed.
DEAD_DEFAULT_REF = "computalk1.wav"


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    """Minimal SoundManager stand-in (mirrors test_t1265's harness)."""

    def __init__(self, hub) -> None:
        self._hub = hub
        self.stop_all_listeners = []

    def audio_hub(self):
        return self._hub

    def add_stop_all_listener(self, callback):
        self.stop_all_listeners.append(callback)

    def stop_all_sound(self):
        self._hub.stop_all()
        for callback in list(self.stop_all_listeners):
            callback()


@pytest.fixture()
def packaged_only():
    """Resolve against the packaged tree, with no user or addon folders.

    This is the hermetic core of T-1501: the operator's machine has an addon
    folder that shadows the packaged tree, so a resolve check that let the
    default fall through to it could never catch a broken shipped default.
    """
    empty = os.path.join(os.path.dirname(packaged_root()), "_no_such_dir_")
    return {"builtin_root": packaged_root(), "user_root": empty,
            "addon_root_path": empty}


class TestFreshDatabaseDetection:
    def test_brand_new_db_is_fresh(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        assert is_fresh_database(store) is True

    def test_existing_rule_not_fresh(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.save_rules(default_ambience_rules())
        assert is_fresh_database(store) is False

    def test_existing_runtime_true_not_fresh(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.set_runtime_enabled(True)
        assert is_fresh_database(store) is False

    def test_existing_runtime_false_not_fresh(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.set_runtime_enabled(False)
        assert is_fresh_database(store) is False


class TestEnsureDefaultRules:
    def test_seeds_on_virgin_db(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        seeded = ensure_default_rules(store)
        assert seeded is True
        rules = store.load_rules()
        assert len(rules) == 1
        r = rules[0]
        assert r.id == DEFAULT_AMBIENCE_RULE_ID
        assert r.sound_ref == DEFAULT_AMBIENCE_SOUND_REF
        assert r.trigger == "ALWAYS"
        assert r.repeat == "LOOP"
        assert r.enabled is True
        assert r.volume == pytest.approx(0.01)
        assert store.runtime_enabled() is True

    def test_returns_false_on_existing_rule(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.save_rules(default_ambience_rules())
        seeded = ensure_default_rules(store)
        assert seeded is False
        assert len(store.load_rules()) == 1  # unchanged

    def test_returns_false_on_existing_runtime_true(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.set_runtime_enabled(True)
        seeded = ensure_default_rules(store)
        assert seeded is False
        assert store.load_rules() == []

    def test_returns_false_on_existing_runtime_false(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        store.set_runtime_enabled(False)
        seeded = ensure_default_rules(store)
        assert seeded is False
        assert store.load_rules() == []

    def test_idempotent_calls(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        ensure_default_rules(store)
        ensure_default_rules(store)
        assert len(store.load_rules()) == 1


class TestDefaultSoundShips:
    """T-1501: the default must resolve from the packaged tree alone."""

    def test_the_default_ref_resolves_without_user_or_addon_folders(
            self, packaged_only):
        path = resolve_sound_ref(DEFAULT_AMBIENCE_SOUND_REF, **packaged_only)
        assert path is not None, (
            f"the shipped default names {DEFAULT_AMBIENCE_SOUND_REF!r}, which "
            "does not resolve inside the packaged sound tree")
        assert os.path.basename(path).lower() == \
            DEFAULT_AMBIENCE_SOUND_REF.lower()

    def test_the_default_is_allowlisted_and_byte_reproducible(self, tmp_path):
        """The allowlist is what keeps the build honest, so the file it
        names must be named there too -- and the generator must be able to
        recreate the exact bytes, or the pack has silently forked."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        manifest = (root / "sounds-redistributable.manifest").read_text(
            encoding="utf-8").splitlines()
        listed = {line.strip().lower() for line in manifest
                  if line.strip() and not line.startswith("#")}
        assert DEFAULT_AMBIENCE_SOUND_REF.lower() in listed

        sys.path.insert(0, str(root / "tools"))
        import generate_redistributable_sounds as generator

        assert generator.is_loop_name(DEFAULT_AMBIENCE_SOUND_REF) is True
        # Rebuild it through the generator's OWN writer, exactly as `main`
        # does, and require the bytes to match what ships.  A bed the tool
        # cannot reproduce has silently forked from the rest of the pack.
        rebuilt = tmp_path / DEFAULT_AMBIENCE_SOUND_REF
        generator.write_wav(
            rebuilt, generator.synthesize(DEFAULT_AMBIENCE_SOUND_REF),
            fade_edges=not generator.is_loop_name(DEFAULT_AMBIENCE_SOUND_REF))
        shipped = root / "src" / "fastprompter" / "sound" / DEFAULT_AMBIENCE_SOUND_REF
        assert rebuilt.read_bytes() == shipped.read_bytes(), (
            f"{DEFAULT_AMBIENCE_SOUND_REF} is not byte-reproducible from the "
            "generator; regenerate it or update the generator")

    def test_the_default_is_a_loop_length_bed_not_a_blip(self, packaged_only):
        """A 0.1 s cue behind REPEAT_LOOP is a stutter, not ambience."""
        import wave

        path = resolve_sound_ref(DEFAULT_AMBIENCE_SOUND_REF, **packaged_only)
        assert path is not None
        with wave.open(path) as handle:
            seconds = handle.getnframes() / handle.getframerate()
        assert seconds >= 2.0, f"{DEFAULT_AMBIENCE_SOUND_REF} is {seconds:.3f}s"


class TestDeadDefaultRepair:
    """T-1501: an install seeded before the fix must start playing again."""

    def _store_with_dead_default(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        rule = default_ambience_rules()[0]
        rule.sound_ref = DEAD_DEFAULT_REF
        rule.name = "Computalk1"
        store.save_rules([rule])
        return store

    def test_a_dead_default_is_repointed(self, tmp_path):
        store = self._store_with_dead_default(tmp_path)
        assert store.load_rules()[0].sound_ref == DEAD_DEFAULT_REF
        changed = repair_dead_default_ref(store, resolver=lambda ref: False)
        assert changed is True
        repaired = store.load_rules()[0]
        assert repaired.sound_ref == DEFAULT_AMBIENCE_SOUND_REF
        assert repaired.id == DEFAULT_AMBIENCE_RULE_ID      # id is stable
        assert repaired.volume == pytest.approx(0.01)       # choices kept
        assert repaired.enabled is True

    def test_a_renamed_default_keeps_the_users_name(self, tmp_path):
        """Only the broken ref is the defect; the rename is the user's choice.

        The repair must not be a second, unrequested settings change on top
        of the one it exists to make.
        """
        store = AmbienceStore(str(tmp_path / "audio.db"))
        rule = default_ambience_rules()[0]
        rule.sound_ref = DEAD_DEFAULT_REF
        rule.name = "Night bed"
        store.save_rules([rule])

        assert repair_dead_default_ref(store, resolver=lambda ref: False) is True
        repaired = store.load_rules()[0]
        assert repaired.sound_ref == DEFAULT_AMBIENCE_SOUND_REF
        assert repaired.name == "Night bed"

    def test_ensure_default_rules_repairs_instead_of_reseeding(self, tmp_path):
        store = self._store_with_dead_default(tmp_path)
        assert ensure_default_rules(store, resolver=lambda ref: False) is False
        assert len(store.load_rules()) == 1
        assert store.load_rules()[0].sound_ref == DEFAULT_AMBIENCE_SOUND_REF

    def test_a_dead_default_that_still_resolves_is_left_alone(self, tmp_path):
        """A user who owns a file with that name keeps their working rule."""
        store = self._store_with_dead_default(tmp_path)
        assert repair_dead_default_ref(store, resolver=lambda ref: True) is False
        assert store.load_rules()[0].sound_ref == DEAD_DEFAULT_REF

    def test_a_user_rule_naming_the_dead_file_is_never_rewritten(self, tmp_path):
        store = AmbienceStore(str(tmp_path / "audio.db"))
        rule = default_ambience_rules()[0]
        rule.id = "amb_user_mine"
        rule.sound_ref = DEAD_DEFAULT_REF
        store.save_rules([rule])
        assert repair_dead_default_ref(store, resolver=lambda ref: False) is False
        assert store.load_rules()[0].sound_ref == DEAD_DEFAULT_REF

    def test_an_unprovable_resolve_never_rewrites(self, tmp_path):
        """A resolver that raises must not be read as "dead"."""
        store = self._store_with_dead_default(tmp_path)

        def boom(ref):
            raise RuntimeError("resolver unavailable")

        assert repair_dead_default_ref(store, resolver=boom) is False
        assert store.load_rules()[0].sound_ref == DEAD_DEFAULT_REF


class TestFreshControllerStarts:
    """A controller on a freshly-seeded DB restores and starts at launch."""

    @pytest.fixture()
    def seeded_session(self, tmp_path):
        _ensure_app()
        parent = QObject()
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        manager = _Manager(hub)
        store = AmbienceStore(str(tmp_path / "audio.db"))
        ensure_default_rules(store)
        engine = AmbienceEngine(
            hub, resolver=lambda ref: resolve_sound_ref(
                ref, user_root=str(tmp_path / "no-user"),
                addon_root_path=str(tmp_path / "no-addon")))
        controller = AmbienceController(
            parent, manager, store=store, engine=engine)
        try:
            yield controller, transport
        finally:
            controller.shutdown()
            parent.deleteLater()

    def test_desired_enabled_is_true(self, seeded_session):
        controller, _ = seeded_session
        assert controller.desired_enabled() is True

    def test_start_if_remembered_starts_the_default(self, seeded_session):
        controller, transport = seeded_session
        assert controller.start_if_remembered() is True
        assert controller.state() == "running"
        # The shipped bed is actually playing at 0.01, and it came from the
        # packaged tree -- the resolver above had no user or addon root.
        playing = list(transport.channels.values())
        refs = {str(channel.get("path", channel)) for channel in playing}
        assert any(os.path.basename(ref).lower() ==
                   DEFAULT_AMBIENCE_SOUND_REF.lower() for ref in refs), (
            f"the default rule resolved to nothing: {refs}")


class TestTwentyFourHourCycleDefaults:
    """Verify the 24h Chime preset is the canonical default (T-1359)."""

    def test_daypart_chime_rules_returns_canonical_list(self):
        rules = daypart_chime_rules()
        assert isinstance(rules, list)
        assert len(rules) == 4
        assert rules == DAYPART_CHIME_RULES
        # A copy, not the shared list: callers may mutate it.
        assert rules is not DAYPART_CHIME_RULES

    def test_default_profile_bakes_the_same_list(self):
        assert DEFAULT_PROFILE["interval_notifs"] == DAYPART_CHIME_RULES
        assert DEFAULT_PROFILE["interval_notifs"] is not DAYPART_CHIME_RULES

    def test_timer_dialog_imports_the_same_canonical_preset(self):
        from fastprompter.ui import timer_dialog

        assert timer_dialog.DEFAULT_INTERVAL_RULES is DAYPART_CHIME_RULES
