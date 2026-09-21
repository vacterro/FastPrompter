"""T-1251: a STORED SOUND REFERENCE IS A REFERENCE, NOT A FILESYSTEM PATH.

The canonical model is ``builtin:<rel>`` / ``user:<rel>`` / legacy bare
``<rel>`` and exactly one resolver turns a reference into a physical path
(:func:`fastprompter.core.sound_library.resolve_sound_ref`).  The legacy
SoundManager helpers validated persisted refs by joining them under the
packaged sounds directory, which declared every valid managed ``user:`` ref
missing -- and then ``migrate_sound_settings`` REPLACED the user's choice
with the shipped default.  That is configuration corruption, so the
reference contract is pinned here end to end.
"""

from __future__ import annotations

import inspect
import io
import json
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

import _qt_stub
import pytest

_before_stubs = _qt_stub.snapshot()
sys.modules.pop("fastprompter.core.sound_manager", None)
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()


class _MockQObject:
    """Stand-in for QObject -- accepts parent arg, stores it."""

    def __init__(self, parent=None):
        self._parent = parent

    def parent(self):
        return self._parent


sys.modules["PyQt6.QtCore"].QObject = _MockQObject

from fastprompter.core import sound_library  # noqa: E402
from fastprompter.core import sound_manager as sm_mod  # noqa: E402
from fastprompter.core.sound_manager import (  # noqa: E402
    _DEFAULT_SOUND_MAP,
    VAULT_DIR_NAME,
    SoundManager,
    get_sound_file_for_event,
    migrate_sound_settings,
)
from fastprompter.core.sound_presets import (  # noqa: E402
    PresetStore,
    apply_preset_to_profile,
    import_preset_payload,
)

_qt_stub.restore(_before_stubs)

USER_REF = "user:imported/custom.wav"


def _make_wav(path) -> str:
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<h", 0) * 100)
    return path


@pytest.fixture()
def builtin_root(tmp_path):
    """A packaged sound tree: one everyday ref, one subfolder ref, one vault ref."""
    root = tmp_path / "packaged"
    _make_wav(root / "hover.wav")
    _make_wav(root / "ui" / "click.wav")
    _make_wav(root / VAULT_DIR_NAME / "vox" / "thirty.wav")
    return str(root)


@pytest.fixture()
def managed_root(tmp_path, monkeypatch):
    """The managed user library -- resolver default, preset import target."""
    root = tmp_path / "data" / "sound_library"
    root.mkdir(parents=True)
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(root))
    return str(root)


@pytest.fixture()
def manager(builtin_root, monkeypatch):
    monkeypatch.setattr(sm_mod, "get_resource_path",
                        lambda *args, **kwargs: builtin_root)
    return SoundManager(_MockQObject(), {})


def _managed_user_wav(managed_root) -> str:
    return _make_wav(os.path.join(managed_root, "imported", "custom.wav"))


# ---------------------------------------------------------------------------
# A / C / D -- event lookup keeps the stored reference
# ---------------------------------------------------------------------------


class TestEventLookup:
    def test_A_valid_user_ref_returns_the_exact_token(self, builtin_root, managed_root):
        _managed_user_wav(managed_root)
        data = {"sound_events": {"click": {"file": USER_REF, "enabled": "True"}}}
        assert get_sound_file_for_event("click", data, builtin_root) == USER_REF

    def test_C_builtin_namespace_ref_is_preserved(self, builtin_root):
        ref = "builtin:ui/click.wav"
        data = {"sound_events": {"click": {"file": ref}}}
        assert get_sound_file_for_event("click", data, builtin_root) == ref

    def test_C_private_vault_ref_is_preserved(self, builtin_root):
        ref = f"{VAULT_DIR_NAME}/vox/thirty.wav"
        data = {"sound_events": {"click": {"file": ref}}}
        assert get_sound_file_for_event("click", data, builtin_root) == ref

    def test_D_legacy_bare_ref_still_resolves(self, builtin_root):
        data = {"sound_events": {"hover": {"file": "hover.wav"}}}
        assert get_sound_file_for_event("hover", data, builtin_root) == "hover.wav"

    def test_D_shipped_defaults_still_answer(self, builtin_root):
        assert get_sound_file_for_event("hover", {}, builtin_root) == "hover.wav"

    def test_missing_override_still_falls_back_to_the_default(self, builtin_root):
        data = {"sound_events": {"hover": {"file": "gone-forever.wav"}}}
        assert get_sound_file_for_event("hover", data, builtin_root) == "hover.wav"


# ---------------------------------------------------------------------------
# B / H / J -- migration never rewrites a valid ref
# ---------------------------------------------------------------------------


class TestMigration:
    def test_B_valid_user_ref_survives_migration_byte_for_byte(self, builtin_root,
                                                               managed_root):
        _managed_user_wav(managed_root)
        data = {"sound_events": {"click": {"file": USER_REF}}}
        migrate_sound_settings(data, builtin_root)
        assert data["sound_events"]["click"]["file"] == USER_REF

    def test_C_builtin_ref_survives_migration(self, builtin_root):
        ref = "builtin:ui/click.wav"
        data = {"sound_events": {"click": {"file": ref}}}
        migrate_sound_settings(data, builtin_root)
        assert data["sound_events"]["click"]["file"] == ref

    def test_H_repeated_migration_and_rebind_never_drift(self, builtin_root,
                                                        managed_root):
        _managed_user_wav(managed_root)
        data = {"sound_events": {"click": {"file": USER_REF}}}
        for _ in range(5):
            migrate_sound_settings(data, builtin_root)
            assert data["sound_events"]["click"]["file"] == USER_REF
            # a profile rebind hands a fresh dict to the same code path
            data = dict(data, sound_events={
                k: dict(v) for k, v in data["sound_events"].items()})

    def test_J_genuinely_missing_ref_keeps_the_fallback_policy(
            self, builtin_root, managed_root):
        """Documented policy: a ref that really cannot resolve heals to the
        shipped default -- and nothing else moves."""
        data = {"sound_events": {
            "click": {"file": "user:imported/does-not-exist.wav"},
            "hover": {"file": "hover.wav"},
        }}
        migrate_sound_settings(data, builtin_root)
        assert data["sound_events"]["click"]["file"] == _DEFAULT_SOUND_MAP["click"]
        assert data["sound_events"]["hover"]["file"] == "hover.wav"


# ---------------------------------------------------------------------------
# E / F / G / M -- playback and preview share one physical file
# ---------------------------------------------------------------------------


class TestPlaybackAndPreview:
    def test_E_user_event_plays_the_managed_asset_not_the_default(
            self, manager, managed_root, monkeypatch):
        physical = _managed_user_wav(managed_root)
        manager._data = {
            "sound_ui": "True",
            "sound_events": {"click": {"file": USER_REF, "enabled": "True"}},
        }
        asked = {}
        monkeypatch.setattr(
            manager, "_request",
            lambda event, path, *a, **k: asked.update(event=event, path=path) or True)
        manager.play("click")
        assert asked["event"] == "click"
        assert os.path.normcase(asked["path"]) == os.path.normcase(physical)
        assert asked["path"] != os.path.normpath(
            os.path.join(manager._sounds_dir, _DEFAULT_SOUND_MAP["click"]))

    def test_F_preview_passes_the_exact_managed_path(self, manager, managed_root,
                                                     monkeypatch):
        physical = _managed_user_wav(managed_root)
        emitted = {}
        monkeypatch.setattr(
            manager, "_emit_file",
            lambda path, level=None, **k: emitted.update(path=path, level=level) or True)
        assert manager.play_file(USER_REF, 0.5) is True
        assert os.path.normcase(emitted["path"]) == os.path.normcase(physical)
        assert emitted["level"] == 0.5

    def test_G_preview_ignores_the_global_ui_audio_toggle(self, manager, managed_root,
                                                        monkeypatch):
        _managed_user_wav(managed_root)
        manager._data = {"sound_ui": "False"}
        emitted = []
        monkeypatch.setattr(manager, "_emit_file",
                            lambda path, level=None, **k: emitted.append(path) or True)
        assert manager.play_file(USER_REF, None) is True
        assert len(emitted) == 1

    def test_M_one_ref_one_physical_file_for_both_routes(
            self, manager, managed_root, monkeypatch):
        _managed_user_wav(managed_root)
        manager._data = {
            "sound_ui": "True",
            "sound_events": {"click": {"file": USER_REF, "enabled": "True"}},
        }
        previewed = {}
        monkeypatch.setattr(
            manager, "_emit_file",
            lambda path, level=None, **k: previewed.update(path=path) or True)
        manager.play_file(USER_REF, 0.5)
        played = {}
        monkeypatch.setattr(
            manager, "_request",
            lambda event, path, *a, **k: played.update(path=path) or True)
        manager.play("click")
        assert played["path"] == previewed["path"]

    def test_legacy_exit_playback_follows_the_same_contract(
            self, manager, managed_root, monkeypatch):
        physical = _managed_user_wav(managed_root)
        manager._data = {
            "sound_ui": "True",
            "sound_events": {"exit": {"file": USER_REF, "enabled": "True"}},
        }
        asked = {}
        monkeypatch.setattr(
            manager, "_request",
            lambda event, path, *a, **k: asked.update(path=path, kwargs=k) or True)
        assert manager._play_legacy("exit") is True
        assert os.path.normcase(asked["path"]) == os.path.normcase(physical)

    def test_cache_cannot_retain_a_stale_physical_mapping(
            self, manager, managed_root, monkeypatch):
        """_file_resolution_sig keys the cache on the STORED REF, so changing
        the mapping invalidates the cached path without a filesystem probe."""
        physical = _managed_user_wav(managed_root)
        other = _make_wav(os.path.join(manager._sounds_dir, "hover.wav"))
        manager._data = {
            "sound_ui": "True",
            "sound_events": {"click": {"file": USER_REF, "enabled": "True"}},
        }
        asked = []
        monkeypatch.setattr(
            manager, "_request",
            lambda event, path, *a, **k: asked.append(path) or True)
        manager.play("click")
        manager._data["sound_events"]["click"]["file"] = "hover.wav"
        manager.play("click")
        assert os.path.normcase(asked[0]) == os.path.normcase(physical)
        assert os.path.normcase(asked[1]) == os.path.normcase(other)


# ---------------------------------------------------------------------------
# I -- preset pack end to end
# ---------------------------------------------------------------------------


def _wav_bytes() -> bytes:
    payload = io.BytesIO()
    with wave.open(payload, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<h", 0) * 100)
    return payload.getvalue()


def _build_pack(tmp_path, wav_bytes: bytes) -> bytes:
    import hashlib as _hashlib

    definition = {
        "schema_version": 1,
        "id": "pack1",
        "name": "Tiny pack",
        "builtin": False,
        "events": {"click": {"file": "custom.wav", "enabled": "True"}},
        # T-1284 / audit/10 W2-004: import now verifies the pack's own asset
        # manifest, so a placeholder digest is (correctly) rejected. Use the
        # real SHA-256 the exporter would have written.
        "asset_manifest": {"custom.wav": _hashlib.sha256(wav_bytes).hexdigest()},
    }
    import zipfile

    target = str(tmp_path / "pack.fpsoundpack")
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("preset.json", json.dumps(definition))
        archive.writestr("sounds/custom.wav", wav_bytes)
    with open(target, "rb") as handle:
        return handle.read()


class TestPresetPackChain:
    def test_I_import_apply_migrate_preview_play_reload(self, manager, managed_root,
                                                       tmp_path, monkeypatch):
        from fastprompter.core.sound_presets import open_preset_pack

        definition, sounds = open_preset_pack(
            _build_pack(tmp_path, _wav_bytes()))
        store = PresetStore(str(tmp_path / "audio.db"))
        imported = import_preset_payload(
            json.dumps(definition).encode("utf-8"), store, new_id="pack1",
            sounds_dir=managed_root, pack_sounds=sounds)
        ref = imported["events"]["click"]["file"]
        assert ref == "user:imported/custom.wav"
        physical = os.path.join(managed_root, "imported", "custom.wav")
        assert os.path.isfile(physical)

        profile: dict = {"sound_ui": "True"}
        apply_preset_to_profile(imported, profile)
        assert profile["sound_events"]["click"]["file"] == ref
        migrate_sound_settings(profile, manager._sounds_dir)
        assert profile["sound_events"]["click"]["file"] == ref

        emitted = {}
        monkeypatch.setattr(
            manager, "_emit_file",
            lambda path, level=None, **k: emitted.update(path=path) or True)
        assert manager.play_file(ref, 0.5) is True
        previewed = emitted["path"]
        played = {}
        monkeypatch.setattr(
            manager, "_request",
            lambda event, path, *a, **k: played.update(path=path) or True)
        manager._data = profile
        manager.play("click")
        assert played["path"] == previewed

        # reload: the persisted mapping survives another start unchanged
        reloaded = json.loads(json.dumps(profile))
        migrate_sound_settings(reloaded, manager._sounds_dir)
        assert reloaded["sound_events"]["click"]["file"] == ref
        assert os.path.normcase(sound_library.resolve_sound_ref(
            ref, builtin_root=manager._sounds_dir)) == os.path.normcase(physical)


# ---------------------------------------------------------------------------
# K / L -- containment is never weakened
# ---------------------------------------------------------------------------


class TestSecurityContract:
    @pytest.mark.parametrize("ref", [
        "user:../outside.wav",
        "builtin:../../outside.wav",
        "../outside.wav",
        "user:imported/../../outside.wav",
    ])
    def test_K_traversal_never_resolves_never_plays(self, manager, managed_root,
                                                    monkeypatch, ref, tmp_path):
        _make_wav(os.path.join(os.path.dirname(managed_root), "outside.wav"))
        assert sound_library.resolve_sound_ref(
            ref, builtin_root=manager._sounds_dir) is None
        emitted = []
        monkeypatch.setattr(manager, "_emit_file",
                            lambda path, level=None, **k: emitted.append(path))
        assert manager.play_file(ref, 0.5) is False
        assert emitted == []
        data = {"sound_events": {"click": {"file": ref}}}
        assert get_sound_file_for_event("click", data, manager._sounds_dir) != ref
        migrate_sound_settings(data, manager._sounds_dir)
        assert data["sound_events"]["click"]["file"] != ref

    def test_L_absolute_persisted_token_is_not_playable(self, manager, tmp_path,
                                                       monkeypatch):
        absolute = _make_wav(tmp_path / "outside" / "secret.wav")
        emitted = []
        monkeypatch.setattr(manager, "_emit_file",
                            lambda path, level=None, **k: emitted.append(path))
        assert manager.play_file(absolute, 0.5) is False
        assert emitted == []
        data = {"sound_events": {"click": {"file": absolute}}}
        assert get_sound_file_for_event("click", data, manager._sounds_dir) != absolute
        migrate_sound_settings(data, manager._sounds_dir)
        assert data["sound_events"]["click"]["file"] != absolute
        assert manager.play(
            "click") is None and emitted == []

    @pytest.mark.parametrize("ref", [
        "user:\\\\server\\share\\x.wav",
        "builtin:C:/Windows/x.wav",
        "user:notes.txt",
    ])
    def test_unsupported_and_qualified_tokens_stay_rejected(self, manager, ref):
        assert sound_library.resolve_sound_ref(
            ref, builtin_root=manager._sounds_dir) is None


# ---------------------------------------------------------------------------
# Static regression -- the legacy pattern must not come back
# ---------------------------------------------------------------------------

_LEGACY_PATTERNS = (
    "os.path.join(sounds_dir,",
    "os.path.join(self._sounds_dir,",
)


class TestStaticGuard:
    @pytest.mark.parametrize("name", (
        "get_sound_file_for_event",
        "migrate_sound_settings",
        "SoundManager.play_file",
        "SoundManager.resolve_ref_path",
    ))
    def test_reference_consumers_never_join_a_stored_ref(self, name):
        """A persisted ref may contain namespace tokens; joining it under a
        root and stat-ing the result is the exact defect this ticket closes.
        Path joins that build a legitimate directory listing stay allowed --
        they live outside these consumers."""
        obj = sm_mod
        for part in name.split("."):
            obj = getattr(obj, part)
        source = inspect.getsource(obj)
        for pattern in _LEGACY_PATTERNS:
            assert pattern not in source, f"{name} still contains {pattern!r}"

    def test_the_guard_is_red_against_the_legacy_pattern(self):
        """A guard that cannot go red guards nothing: the retired defect is
        pinned here as the exact text it must never contain again."""
        legacy = 'path = os.path.join(sounds_dir, file_name)\n'
        assert any(pattern in legacy for pattern in _LEGACY_PATTERNS)
