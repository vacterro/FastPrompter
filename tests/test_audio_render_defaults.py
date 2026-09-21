"""T-1242 spec 8/9: the render/edge-pad A/B switches ship OFF.

The first playback of the corrupted-cue reproduction was reported CORRECT --
so raw playback is the control path.  Both "improvements" are experiments
that never earned their default and now default OFF.  This file pins the
defaults themselves; the renderer's own contract tests pin the switches ON
in their own fixtures.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402


@pytest.fixture()
def fresh_render():
    """Reload audio_render so module-level DEFAULTS (not patched globals)
    are what the test observes."""
    saved = {name: value for name, value in vars(audio_render).items()
             if name in ("_render_enabled", "_edge_pad_enabled")}
    try:
        importlib.reload(audio_render)
        yield audio_render
    finally:
        importlib.reload(audio_render)
        for name, value in saved.items():
            setattr(audio_render, name, value)


class TestShippedDefaults:
    def test_the_render_master_switch_defaults_off(self, fresh_render):
        assert fresh_render._render_enabled is False

    def test_edge_padding_defaults_off(self, fresh_render):
        assert fresh_render._edge_pad_enabled is False

    def test_public_switch_helpers_agree_with_the_defaults(self, fresh_render):
        assert fresh_render.render_enabled() is False
        assert fresh_render.edge_pad_enabled() is False


class TestOneShotPolicyMigration:
    """Spec 8: profiles created while the experimental defaults were ON must
    be migrated to OFF exactly once; a choice made AFTER the marker survives
    everything."""

    def _manager(self, data):
        """A SoundManager shell with the profile dict wired in."""
        from fastprompter.core import sound_manager as sm

        manager = sm.SoundManager.__new__(sm.SoundManager)
        manager._data = data
        return manager

    def test_pre_switch_profile_defaults_are_reset_to_off(self):
        from fastprompter.core.sound_manager import SoundManager

        data: dict = {}
        changed = SoundManager.migrate_experimental_render_policy(data)
        assert changed is True
        assert data[SoundManager.DEVICE_RENDER_KEY] == "False"
        assert data[SoundManager.EDGE_PAD_KEY] == "False"
        assert data[SoundManager.RENDER_POLICY_MARKER_KEY] == "True"

    def test_old_experimental_bake_is_reset_to_off(self):
        from fastprompter.core.sound_manager import SoundManager

        data = {SoundManager.DEVICE_RENDER_KEY: "True",
                SoundManager.EDGE_PAD_KEY: "True"}
        changed = SoundManager.migrate_experimental_render_policy(data)
        assert changed is True
        assert data[SoundManager.DEVICE_RENDER_KEY] == "False"
        assert data[SoundManager.EDGE_PAD_KEY] == "False"

    def test_an_explicit_post_marker_choice_is_never_touched(self):
        from fastprompter.core.sound_manager import SoundManager

        data = {SoundManager.RENDER_POLICY_MARKER_KEY: "True",
                SoundManager.DEVICE_RENDER_KEY: "True",
                SoundManager.EDGE_PAD_KEY: "True"}
        changed = SoundManager.migrate_experimental_render_policy(data)
        assert changed is False
        assert data[SoundManager.DEVICE_RENDER_KEY] == "True"
        assert data[SoundManager.EDGE_PAD_KEY] == "True"

    def test_migration_runs_exactly_once(self):
        from fastprompter.core.sound_manager import SoundManager

        data: dict = {}
        assert SoundManager.migrate_experimental_render_policy(data) is True
        data[SoundManager.DEVICE_RENDER_KEY] = "True"   # a later choice
        assert SoundManager.migrate_experimental_render_policy(data) is False
        assert data[SoundManager.DEVICE_RENDER_KEY] == "True"

    def test_startup_migration_hook_is_wired(self, monkeypatch):
        """migrate_sound_settings() runs at every start; it must carry the
        one-shot policy migration."""
        from fastprompter.core import sound_manager as sm

        called = []
        monkeypatch.setattr(sm.SoundManager,
                            "migrate_experimental_render_policy",
                            staticmethod(lambda data: called.append(data)))
        data: dict = {"sound_events": {}}
        sm.migrate_sound_settings(data)
        assert called and called[0] is data


class TestSoundManagerAppliesDefaults:
    def test_missing_profile_keys_mean_off(self, monkeypatch):
        import fastprompter.core.audio_render as ar

        monkeypatch.setattr(ar, "set_render_enabled",
                            lambda v: seen.__setitem__("r", v))
        monkeypatch.setattr(ar, "set_edge_pad_enabled",
                            lambda v: seen.__setitem__("p", v))
        seen: dict = {}
        manager = self._manager({})
        enabled, padded = manager.apply_device_render_setting()
        assert (enabled, padded) == (False, False)
        assert seen == {"r": False, "p": False}

    def test_explicit_opt_in_still_engages_the_experiment(self, monkeypatch):
        import fastprompter.core.audio_render as ar
        from fastprompter.core import sound_manager as sm

        seen: dict = {}
        monkeypatch.setattr(ar, "set_render_enabled",
                            lambda v: seen.__setitem__("r", v))
        monkeypatch.setattr(ar, "set_edge_pad_enabled",
                            lambda v: seen.__setitem__("p", v))
        manager = self._manager({sm.SoundManager.DEVICE_RENDER_KEY: "True"})
        enabled, padded = manager.apply_device_render_setting()
        assert (enabled, padded) == (True, False)
        assert seen == {"r": True, "p": False}

    def test_a_policy_change_invalidates_transport_sources(self, monkeypatch):
        """Spec 5: toggling a switch retires pooled transport sources."""
        import fastprompter.core.audio_render as ar

        # Keep the module-level policy state local to this test.
        monkeypatch.setattr(ar, "_render_enabled", False, raising=False)
        monkeypatch.setattr(ar, "_edge_pad_enabled", False, raising=False)
        state = {"r": False, "p": False}
        monkeypatch.setattr(
            ar, "render_enabled", lambda: state["r"])
        monkeypatch.setattr(
            ar, "edge_pad_enabled", lambda: state["p"])
        monkeypatch.setattr(
            ar, "set_render_enabled",
            lambda v: state.__setitem__("r", bool(v)))
        monkeypatch.setattr(
            ar, "set_edge_pad_enabled",
            lambda v: state.__setitem__("p", bool(v)))
        calls = []
        manager = self._manager({})
        manager._hub = type("Hub", (), {
            "invalidate_sources": staticmethod(lambda: calls.append(1))})()
        manager.apply_device_render_setting()   # first apply: cold state
        assert calls == []                      # nothing changed yet
        manager._data = {"audio_device_render": "True"}   # real transition
        manager.apply_device_render_setting()
        assert len(calls) == 1                  # policy changed -> retire

    @staticmethod
    def _manager(data):
        from collections import deque

        from fastprompter.core import sound_manager as sm

        manager = sm.SoundManager.__new__(sm.SoundManager)
        manager._data = data
        manager._data_id = id(data)
        manager._file_cache = {}
        manager._file_sig = {}
        manager._scaled_cache = {}
        manager._pending = deque()
        manager._hub = type("Hub", (), {
            "invalidate_sources": lambda self: None})()
        return manager
