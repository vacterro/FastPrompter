"""PERF-003 (SRC-021 audit/11): startup prewarm order and single ownership.

Before this repair ``SoundManager.__init__`` ran ``prewarm_device_cache([...six
Problip WAVs...])`` BEFORE ``apply_device_render_setting()``.  The renderer
starts disabled, so that first prewarm was guaranteed to no-op -- but it still
resolved NumPy synchronously on the GUI thread and started a daemon worker, and
the same six Problip WAVs were scheduled a SECOND time by the hot-set preload a
few lines later.  Two overlapping startup owners, one pointless NumPy import.

These tests pin the repaired contract:

A. render OFF: constructing SoundManager and running the hot-set preload does
   not resolve NumPy and does not ask the renderer for any file.
B. render ON: the policy is applied first and the renderer prewarm still runs.
C. every hot source is scheduled at most once per startup policy generation.
D. (covered by the broader suites) the existing preload/render policy tests
   stay green.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render, sound_manager  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402


class _SyncThread:
    """Run the preload worker inline so assertions are deterministic."""

    def __init__(self, target=None, name=None, daemon=None, **_kwargs) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        if self._target is not None:
            self._target()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No real worker thread, no real ambience DB, no leaked policy state."""
    monkeypatch.setattr(sound_manager, "threading",
                        SimpleNamespace(Thread=_SyncThread))
    monkeypatch.setattr(
        "fastprompter.core.ambience_store.AmbienceStore.load_rules",
        lambda self: [])
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    yield


class _Spy:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.render_calls: list[str] = []

    def install(self, monkeypatch) -> None:
        spy = self

        def ensure():
            spy.ensure_calls += 1
            return True

        def render(path, rate=None):
            spy.render_calls.append(path)
            return None

        monkeypatch.setattr(audio_render, "ensure_numpy", ensure)
        monkeypatch.setattr(audio_render, "device_ready_wav", render)


def _manager(monkeypatch, data):
    """A real SoundManager, with the deferred startup callback captured."""
    scheduled = []
    monkeypatch.setattr(
        sound_manager.QTimer, "singleShot",
        lambda delay, callback: scheduled.append(callback))
    manager = SoundManager(None, dict(data))
    return manager, scheduled


def test_render_off_startup_never_touches_numpy(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    manager, scheduled = _manager(
        monkeypatch, {"audio_device_render": "False", "audio_edge_pad": "False"})

    assert spy.ensure_calls == 0, "construction must not resolve NumPy"
    assert spy.render_calls == [], "construction must not prewarm the renderer"
    assert len(scheduled) == 1, "exactly one startup preload is scheduled"
    assert scheduled[0] == manager._preload_hot_set_safely

    scheduled[0]()          # the one deferred startup owner
    assert spy.ensure_calls == 0, "render OFF: no NumPy for a no-op prewarm"
    assert spy.render_calls == [], "render OFF: no renderer calls at all"


def test_render_on_applies_policy_before_prewarming(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    manager, scheduled = _manager(
        monkeypatch, {"audio_device_render": "True", "audio_edge_pad": "False"})

    assert audio_render.render_enabled() is True, "policy applied at start"
    assert spy.ensure_calls == 0, "policy application itself resolves nothing"

    scheduled[0]()
    assert spy.ensure_calls == 1, "render ON: NumPy resolved once, on the GUI thread"
    hot = manager.hot_sound_paths()
    assert hot, "the shipped hot set is non-empty"
    assert sorted(spy.render_calls) == sorted(hot), (
        "render ON: every hot source is prewarmed")


def test_each_hot_source_scheduled_at_most_once(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    manager, scheduled = _manager(
        monkeypatch, {"audio_device_render": "True", "audio_edge_pad": "False"})

    scheduled[0]()
    calls = list(spy.render_calls)
    assert len(calls) == len(set(calls)), (
        "no hot source may be scheduled twice per startup policy generation")

    hot = manager.hot_sound_paths()
    assert len(hot) == len(set(os.path.normcase(p) for p in hot)), (
        "hot_sound_paths itself must deduplicate")

    # The six Problip WAVs are covered by the hot-set owner now; the audit's
    # redundant, guaranteed-no-op second prewarm owner is gone.
    from fastprompter.utils.paths import get_resource_path
    blips = {
        os.path.abspath(get_resource_path("sound", "problip", name))
        for name in ("blip01.wav", "blip_glass.wav", "blip_wood.wav",
                     "blip_soft_bell.wav", "blip_bonk.wav", "blip_space.wav")
    }
    assert blips <= {os.path.abspath(p) for p in hot}
    assert blips <= {os.path.abspath(p) for p in calls}
