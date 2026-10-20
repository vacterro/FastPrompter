"""T-1455: Computalk1 default ambience + 24h Chime preset default.

Covers:
- Fresh install: ensure_default_rules seeds Computalk1 (enabled, 0.01,
  TRIGGER_ALWAYS/REPEAT_LOOP) and runtime_enabled=True.
- Existing rule or decision row -> no seed (idempotent, no resurrection).
- Fresh controller start_if_remembered returns True (first launch plays).
- 24h cycle: DEFAULT_PROFILE["interval_notifs"] == daypart_chime_rules()
  and timer_dialog imports the same canonical preset.

Uses pytest tmp_path (not tempfile) like the neighbor ambience suites: the
live audio.db must not be unlinked on Windows while a connection object is
still collecting; pytest defers tmp cleanup past the test frame.
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
    AmbienceStore,
    default_ambience_rules,
    ensure_default_rules,
    is_fresh_database,
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
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402

_APP = None


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
        assert r.name == "Computalk1"
        assert r.sound_ref == "computalk1.wav"
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
        engine = AmbienceEngine(hub)
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
        # The shipped Computalk1 bed is actually playing at 0.01.
        playing = list(transport.channels.values())
        refs = {str(channel.get("path", channel)) for channel in playing}
        assert any("computalk1" in ref.lower() for ref in refs), (
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


class TestComputalk1SoundResolves:
    """The shipped sound file resolves through the library."""

    def test_computalk1_resolves(self):
        from fastprompter.core.sound_library import resolve_sound_ref

        path = resolve_sound_ref("computalk1.wav")
        assert path is not None, "computalk1.wav must ship with the app"
        assert path.lower().endswith("computalk1.wav")
