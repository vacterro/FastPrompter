"""SRC-101 / PERF-002: the canonical profile must ship the OFF render policy.

The audited contradiction was inside the default-profile source of truth:
``DEFAULT_PROFILE`` said ``audio_device_render = 'True'`` while
``audio_render_policy_migrated_v2 = 'True'`` claimed the one-shot migration to
OFF had already run. A fresh or reset profile therefore started as an
ALREADY-MIGRATED EXPLICIT render-ON profile, so the documented "experimental,
default OFF" policy was bypassed: the next event-loop turn resolved NumPy
synchronously on the GUI thread and started background rendering of the shipped
hot sound set, and the one-shot migration could never repair it because the
marker said there was nothing to migrate.

These tests tie the three authorities together -- the baked profile, the
migration semantics and ``SoundManager``'s documented default -- so they cannot
drift apart again:

A. the baked profile is the completed post-migration OFF policy;
B. a fresh/reset profile stays OFF through the normal startup migration;
C. that OFF startup path resolves no NumPy and calls the renderer for nothing;
D. an explicit post-migration opt-in (marker present, render True) still works;
E. a legacy no-marker profile carrying the old baked True migrates to OFF once.
"""

from __future__ import annotations

import copy
import inspect
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render, sound_manager  # noqa: E402
from fastprompter.core.default_profile import DEFAULT_PROFILE  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402

RENDER = SoundManager.DEVICE_RENDER_KEY
PAD = SoundManager.EDGE_PAD_KEY
MARKER = SoundManager.RENDER_POLICY_MARKER_KEY


class _SyncThread:
    """Run the preload worker inline so assertions are deterministic."""

    def __init__(self, target=None, name=None, daemon=None, **_kwargs) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        if self._target is not None:
            self._target()


class _Spy:
    """Count the two renderer-only entry points the OFF path must never reach."""

    def __init__(self) -> None:
        self.ensure_calls = 0
        self.render_calls: list[str] = []

    def install(self, monkeypatch) -> None:
        def ensure():
            self.ensure_calls += 1
            return True

        def render(path, rate=None):
            self.render_calls.append(path)
            return None

        monkeypatch.setattr(audio_render, "ensure_numpy", ensure)
        monkeypatch.setattr(audio_render, "device_ready_wav", render)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No real worker thread, no ambience DB, no leaked policy state."""
    monkeypatch.setattr(sound_manager, "threading",
                        SimpleNamespace(Thread=_SyncThread))
    monkeypatch.setattr(
        "fastprompter.core.ambience_store.AmbienceStore.load_rules",
        lambda self: [])
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    yield


def _manager(monkeypatch, data):
    """A real SoundManager plus its one deferred startup preload callback."""
    scheduled = []
    monkeypatch.setattr(
        sound_manager.QTimer, "singleShot",
        lambda delay, callback: scheduled.append(callback))
    return SoundManager(None, dict(data)), scheduled


# --------------------------------------------------------------------------
# A. the baked profile is the completed OFF policy
# --------------------------------------------------------------------------

def test_the_baked_profile_ships_the_off_render_policy():
    assert DEFAULT_PROFILE[RENDER] == "False", (
        "device-rate rendering is experimental and default OFF; a baked 'True' "
        "makes every fresh profile an explicit opt-in")
    assert DEFAULT_PROFILE[PAD] == "False"
    assert DEFAULT_PROFILE[MARKER] == "True", (
        "the marker means 'this profile already carries the post-migration "
        "policy', which is only true if the policy above is OFF")


def test_the_baked_profile_is_a_fixed_point_of_the_migration():
    """Running the startup migration over the canonical profile changes nothing.

    If the baked profile were pre-migration (no marker) the migration would
    rewrite it; if it were render-ON with the marker it would be read as an
    explicit opt-in. Neither may be true of the shipped default.
    """
    data = copy.deepcopy(DEFAULT_PROFILE)
    changed = SoundManager.migrate_experimental_render_policy(data)

    assert changed is False
    assert data[RENDER] == "False"
    assert data[PAD] == "False"
    assert data[MARKER] == "True"


def test_the_baked_profile_agrees_with_the_documented_default():
    """SoundManager's own comment calls the renderer OFF by default."""
    source = inspect.getsource(SoundManager)
    assert "default OFF" in source, (
        "the documented default moved; this invariant must be re-read, not "
        "silently accepted")
    assert DEFAULT_PROFILE[RENDER] == "False"


# --------------------------------------------------------------------------
# B. a fresh/reset profile stays OFF through the startup path
# --------------------------------------------------------------------------

def test_a_reset_profile_starts_off_and_stays_off():
    from fastprompter.core.state import FastPrompterState

    state = FastPrompterState.__new__(FastPrompterState)   # no DB, no dialogs
    state.reset_data()

    assert state.data[RENDER] == "False"
    assert state.data[PAD] == "False"
    assert state.data[MARKER] == "True"

    # the normal startup migration, exactly as main.py runs it
    sound_manager.migrate_sound_settings(state.data)
    assert state.data[RENDER] == "False"

    # and the policy application the SoundManager performs at construction
    manager = SoundManager(None, dict(state.data))
    assert manager.apply_device_render_setting() == (False, False)
    assert audio_render.render_enabled() is False


# --------------------------------------------------------------------------
# C. that OFF startup path reaches nothing renderer-specific
# --------------------------------------------------------------------------

def test_a_default_profile_startup_never_touches_the_renderer(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    data = copy.deepcopy(DEFAULT_PROFILE)
    sound_manager.migrate_sound_settings(data)      # no-op for a fresh profile
    manager, scheduled = _manager(monkeypatch, data)

    assert audio_render.render_enabled() is False, "fresh profile is OFF"
    assert spy.ensure_calls == 0, "construction must not import NumPy"
    assert spy.render_calls == []

    assert len(scheduled) == 1, "exactly one startup preload owner"
    scheduled[0]()
    assert spy.ensure_calls == 0, "render OFF: a no-op prewarm must not import NumPy"
    assert spy.render_calls == [], "render OFF: no renderer call at all"


# --------------------------------------------------------------------------
# D/E. explicit opt-in survives, legacy default migrates exactly once
# --------------------------------------------------------------------------

def test_an_explicit_post_migration_opt_in_still_prewarms(monkeypatch):
    """marker=True + render=True is a user decision and must keep working."""
    spy = _Spy()
    spy.install(monkeypatch)
    data = copy.deepcopy(DEFAULT_PROFILE)
    data[RENDER] = "True"

    changed = SoundManager.migrate_experimental_render_policy(data)
    assert changed is False, "a post-migration explicit choice is not migrated"
    assert data[RENDER] == "True"

    manager, scheduled = _manager(monkeypatch, data)
    assert audio_render.render_enabled() is True
    scheduled[0]()
    assert spy.ensure_calls == 1, "render ON resolves NumPy once, on the GUI thread"
    hot = manager.hot_sound_paths()
    assert hot
    assert sorted(spy.render_calls) == sorted(hot)


def test_a_legacy_baked_true_profile_migrates_to_off_once():
    legacy = {RENDER: "True", PAD: "True"}          # pre-marker experimental state
    assert SoundManager.migrate_experimental_render_policy(legacy) is True
    assert (legacy[RENDER], legacy[PAD]) == ("False", "False")
    assert legacy[MARKER] == "True"

    # idempotent: the second run is a no-op and never re-reads a user choice
    assert SoundManager.migrate_experimental_render_policy(legacy) is False
    legacy[RENDER] = "True"                         # user opts in afterwards
    assert SoundManager.migrate_experimental_render_policy(legacy) is False
    assert legacy[RENDER] == "True"


def test_a_reset_profile_never_re_enables_the_renderer(monkeypatch):
    """Reset is the path that made the old baked True actually bite."""
    from fastprompter.core.state import FastPrompterState

    state = FastPrompterState.__new__(FastPrompterState)
    state.reset_data()
    state.reset_data()                              # twice: still OFF

    spy = _Spy()
    spy.install(monkeypatch)
    manager, scheduled = _manager(monkeypatch, state.data)
    scheduled[0]()

    assert audio_render.render_enabled() is False
    assert spy.ensure_calls == 0 and spy.render_calls == []
