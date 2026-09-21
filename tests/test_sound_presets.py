"""T-1238-F: presets CRUD, factory truth, apply-to-profile, safe import/export."""

from __future__ import annotations

import json
import struct
import wave

import pytest

from fastprompter.core.sound_presets import (
    MAX_PACK_MEMBER_BYTES,
    PresetStore,
    apply_preset_to_profile,
    cs16_preset_definition,
    default_preset_definition,
    export_preset_json,
    export_preset_pack,
    factory_definitions,
    import_preset_payload,
    minecraft_preset_definition,
    missing_asset_events,
    open_preset_pack,
)


def make_store(tmp_path) -> PresetStore:
    return PresetStore(str(tmp_path / "audio.db"))


def _make_wav(path: str) -> None:
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<B", 128))


# ---------------------------------------------------------------------------
# Factory presets
# ---------------------------------------------------------------------------


class TestFactoryPresets:
    def test_three_factory_definitions(self):
        ids = [d["id"] for d in factory_definitions()]
        assert ids == ["preset_default", "preset_minecraft", "preset_cs16"]

    def test_default_preset_matches_default_map(self):
        from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP

        definition = default_preset_definition()
        assert definition["assets_missing"] is False
        for event, file_name in _DEFAULT_SOUND_MAP.items():
            entry = definition["events"][event]
            assert entry["file"] == file_name
            assert entry["enabled"] == "True"

    def test_cs16_uses_existing_cs_style_assets(self):
        definition = cs16_preset_definition()
        cs_events = [e for e in definition["events"].values()
                     if e["file"].startswith("cs_style/")]
        assert cs_events, "CS preset must map shipped cs_style files"
        # Every referenced cs_style file is one of the three shipped assets;
        # actual on-disk presence is proven by the shipped-assets gate.
        for _event, entry in definition["events"].items():
            if entry["file"].startswith("cs_style/"):
                assert entry["file"] in {
                    "cs_style/buttonclick.wav",
                    "cs_style/buttonclickrelease.wav",
                    "cs_style/buttonrollover.wav",
                }, entry["file"]

    def test_minecraft_is_truthfully_incomplete(self):
        definition = minecraft_preset_definition()
        assert definition["assets_missing"] is True
        assert definition["builtin"] is True
        # No fake file paths that pretend to be Minecraft audio.
        for _event, entry in definition["events"].items():
            assert entry["file"] == ""

    def test_missing_assets_reported(self, tmp_path):
        definition = minecraft_preset_definition()
        assert missing_asset_events(definition, str(tmp_path)) == [
            "click", "button_click", "hover", "chest_open", "chest_close"]

    def test_store_seeds_and_restores_factory(self, tmp_path):
        store = make_store(tmp_path)
        names = [p["name"] for p in store.list_presets()]
        assert names == ["Default", "Minecraft", "CS 1.6"]
        store.delete("preset_default")   # factory -> hidden, not gone
        store.delete("preset_minecraft")
        assert "Default" not in [p["name"] for p in store.list_presets()]
        assert store.restore_factory() == 3
        names = [p["name"] for p in store.list_presets()]
        assert names == ["Default", "Minecraft", "CS 1.6"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestPresetCrud:
    def test_create_save_reload(self, tmp_path):
        store = make_store(tmp_path)
        definition = default_preset_definition()
        definition["id"] = "preset_custom"
        definition["name"] = "Custom"
        definition["builtin"] = False
        store.upsert(definition)
        reloaded = make_store(tmp_path)  # fresh instance over the same db
        assert reloaded.get_preset("preset_custom")["name"] == "Custom"

    def test_rename_keeps_stable_id(self, tmp_path):
        store = make_store(tmp_path)
        store.rename("preset_default", "Renamed Default")
        preset = store.get_preset("preset_default")
        assert preset["id"] == "preset_default"
        assert store.list_presets()[0]["name"] == "Renamed Default"

    def test_duplicate(self, tmp_path):
        store = make_store(tmp_path)
        source = store.get_preset("preset_cs16")
        copy = dict(source, id="preset_cs16_copy", name="CS copy",
                    builtin=False)
        store.upsert(copy)
        assert store.get_preset("preset_cs16_copy")["name"] == "CS copy"

    def test_delete_user_preset_removes(self, tmp_path):
        store = make_store(tmp_path)
        definition = default_preset_definition()
        definition["id"] = "mine"
        store.upsert(definition)
        assert store.delete("mine") is True
        assert store.get_preset("mine") is None

    def test_edit_builtin_via_override(self, tmp_path):
        store = make_store(tmp_path)
        definition = store.get_preset("preset_default")
        definition["events"]["click"]["file"] = "my_click.wav"
        store.upsert(definition, user_override=True)
        assert store.get_preset("preset_default")["events"]["click"]["file"] == "my_click.wav"
        assert store.get_preset("preset_default")["user_override"] is True
        # Restore factory repairs the template.
        store.restore_factory()
        assert store.get_preset("preset_default")["events"]["click"]["file"] == "button1.wav"


# ---------------------------------------------------------------------------
# Apply to profile
# ---------------------------------------------------------------------------


class TestApplyToProfile:
    def test_apply_changes_only_current_profile_dict(self):
        preset = cs16_preset_definition()
        profile = {"sound_events": {
            "click": {"enabled": "True", "file": "button1.wav", "volume": ""},
        }}
        apply_preset_to_profile(preset, profile)
        assert profile["sound_events"]["click"]["file"] == "cs_style/buttonclick.wav"
        # Other preset events are written into the same contract.
        assert profile["sound_events"]["hover"]["file"] == "cs_style/buttonrollover.wav"

    def test_apply_never_binds_fake_files(self):
        preset = minecraft_preset_definition()
        profile: dict = {}
        apply_preset_to_profile(preset, profile)
        for _event, entry in profile["sound_events"].items():
            assert entry["file"] == ""  # asset-less stays asset-less

    def test_apply_is_profile_scoped(self):
        preset = default_preset_definition()
        profile_a: dict = {}
        profile_b: dict = {}
        apply_preset_to_profile(preset, profile_a)
        assert "sound_events" in profile_a
        assert "sound_events" not in profile_b  # other profile untouched


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


class TestImportExport:
    def test_json_roundtrip_is_semantically_exact(self, tmp_path):
        store = make_store(tmp_path)
        payload = export_preset_json(cs16_preset_definition())
        definition = import_preset_payload(payload, store, new_id="imported1")
        again = store.get_preset("imported1")
        assert again["events"] == definition["events"]
        assert again["builtin"] is False

    def test_pack_roundtrip_with_sounds(self, tmp_path):
        # A full standalone library: the whole Default map + cs_style trio,
        # so the CS 1.6 pack can export every referenced file.
        from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP

        sounds_dir = tmp_path / "lib"
        (sounds_dir / "cs_style").mkdir(parents=True)
        for rel in set(_DEFAULT_SOUND_MAP.values()) | {
                "cs_style/buttonclick.wav", "cs_style/buttonclickrelease.wav",
                "cs_style/buttonrollover.wav"}:
            target = sounds_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _make_wav(str(target))
        pack_bytes, missing = export_preset_pack(
            cs16_preset_definition(), str(sounds_dir))
        assert missing == []
        definition, sounds = open_preset_pack(pack_bytes)
        assert "cs_style/buttonclick.wav" in sounds
        store = make_store(tmp_path / "target")
        imported = import_preset_payload(
            json.dumps(definition).encode("utf-8"), store,
            new_id="pack1", sounds_dir=str(tmp_path / "target_lib"),
            pack_sounds=sounds)
        assert imported["id"] == "pack1"

    def test_traversal_member_rejected(self):
        evil = {
            "schema_version": 1, "id": "evil", "name": "Evil", "events": {},
            "asset_manifest": {},
        }
        import io as _io
        import zipfile as _zf

        buffer = _io.BytesIO()
        with _zf.ZipFile(buffer, "w") as archive:
            archive.writestr("preset.json", json.dumps(evil))
            archive.writestr("sounds/../evil.wav", b"MZ")
        with pytest.raises(ValueError):
            open_preset_pack(buffer.getvalue())

    def test_absolute_path_member_rejected(self):
        import io as _io
        import zipfile as _zf

        evil = {"schema_version": 1, "id": "evil", "events": {}}
        buffer = _io.BytesIO()
        with _zf.ZipFile(buffer, "w") as archive:
            archive.writestr("preset.json", json.dumps(evil))
            archive.writestr("sounds//etc/passwd.wav", b"x")
        with pytest.raises(ValueError):
            open_preset_pack(buffer.getvalue())

    def test_oversized_member_rejected(self):
        import io as _io
        import zipfile as _zf

        evil = {"schema_version": 1, "id": "evil", "events": {}}
        buffer = _io.BytesIO()
        with _zf.ZipFile(buffer, "w") as archive:
            archive.writestr("preset.json", json.dumps(evil))
            archive.writestr("sounds/big.wav", b"x" * (MAX_PACK_MEMBER_BYTES + 1))
        with pytest.raises(ValueError):
            open_preset_pack(buffer.getvalue())

    def test_newer_schema_rejected(self, tmp_path):
        store = make_store(tmp_path)
        payload = json.dumps({
            "schema_version": 99, "id": "future", "name": "F", "events": {},
        }).encode("utf-8")
        with pytest.raises(ValueError):
            import_preset_payload(payload, store)

    # -- T-1284 / audit/10 W2-004: transactional, integrity-checked import ----

    def test_bad_second_member_leaves_library_and_store_unchanged(
            self, tmp_path, monkeypatch):
        """Preflight is ALL-or-nothing: a rejected member publishes no bytes."""
        lib = tmp_path / "lib"
        lib.mkdir()
        monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                            lambda: str(lib))
        store = make_store(tmp_path)
        definition = {
            "schema_version": 1, "id": "p", "name": "P",
            "events": {"click": {"file": "a.wav"}},
        }
        with pytest.raises(ValueError):
            import_preset_payload(
                json.dumps(definition).encode("utf-8"), store, new_id="p",
                sounds_dir=str(lib),
                pack_sounds={"a.wav": b"GOOD", "z.txt": b"BAD"})
        assert not (lib / "imported" / "a.wav").exists(), (
            "a rejected member must not leave an orphan of an accepted one")
        assert store.get_preset("p") is None

    def test_manifest_digest_mismatch_rejected(self, tmp_path, monkeypatch):
        lib = tmp_path / "lib"
        lib.mkdir()
        monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                            lambda: str(lib))
        store = make_store(tmp_path)
        definition = {
            "schema_version": 1, "id": "p", "name": "P", "events": {},
            "asset_manifest": {"a.wav": "0" * 64},
        }
        with pytest.raises(ValueError):
            import_preset_payload(
                json.dumps(definition).encode("utf-8"), store, new_id="p",
                sounds_dir=str(lib),
                pack_sounds={"a.wav": b"payload-not-matching-manifest"})
        assert store.get_preset("p") is None

    def test_existing_asset_is_not_overwritten(self, tmp_path, monkeypatch):
        """An import must not clobber an existing managed asset in place."""
        lib = tmp_path / "lib"
        (lib / "imported").mkdir(parents=True)
        existing = lib / "imported" / "a.wav"
        existing.write_bytes(b"OLD")
        monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                            lambda: str(lib))
        store = make_store(tmp_path)
        import hashlib as _h
        definition = {
            "schema_version": 1, "id": "p", "name": "P",
            "events": {"click": {"file": "a.wav"}},
            "asset_manifest": {"a.wav": _h.sha256(b"NEW").hexdigest()},
        }
        imported = import_preset_payload(
            json.dumps(definition).encode("utf-8"), store, new_id="p",
            sounds_dir=str(lib),
            pack_sounds={"a.wav": b"NEW"})
        assert existing.read_bytes() == b"OLD", "existing asset was clobbered"
        # The pack's own mapping points at a collision-safe imported ref.
        new_ref = imported["events"]["click"]["file"]
        assert new_ref != "user:imported/a.wav"
        assert new_ref.startswith("user:imported/")

    def test_store_failure_rolls_back_published_files(self, tmp_path, monkeypatch):
        """If the preset store write fails, the just-published file is removed."""
        lib = tmp_path / "lib"
        lib.mkdir()
        monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                            lambda: str(lib))
        store = make_store(tmp_path)
        import hashlib as _h
        definition = {
            "schema_version": 1, "id": "p", "name": "P",
            "events": {"click": {"file": "a.wav"}},
            "asset_manifest": {"a.wav": _h.sha256(b"NEW").hexdigest()},
        }

        def boom(*a, **k):
            raise RuntimeError("store down")

        monkeypatch.setattr(store, "upsert", boom)
        with pytest.raises(RuntimeError):
            import_preset_payload(
                json.dumps(definition).encode("utf-8"), store, new_id="p",
                sounds_dir=str(lib),
                pack_sounds={"a.wav": b"NEW"})
        assert not (lib / "imported" / "a.wav").exists(), (
            "a store failure after publication must roll the file back")
        assert not any(lib.glob(".fpsoundpack-*")), "staging dir not cleaned"
