"""T-1294: transactional partial-publication rollback for preset-pack import.

Post-closure corrective for audit/10 W2-004 (refs T-1284, SRC-013:R008):
``_publish_pack_sounds`` rolled back ONLY when the caller received the
published list, so an ``os.replace`` failure mid-publication left the
already-published members in the managed library, and rollback rebuilt
its paths through ``sound_library.managed_root()`` instead of the root
the transaction published into.

Contract under test: for every import failure before the preset-store
commit, the managed library after the failure equals the library before
the import. Only files introduced by THIS import may be removed; a
pre-existing collision target is never deleted or overwritten. Rollback
targets the SAME root publication used -- every test here owns a
temporary library root passed as ``sounds_dir`` and never monkeypatches
unrelated global state to aim rollback at it.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from fastprompter.core import sound_presets
from fastprompter.core.sound_presets import PresetStore, import_preset_payload


def _snapshot(root: str) -> dict[str, bytes]:
    """Every file under ``root`` with its content, keyed by relative path."""
    snap: dict[str, bytes] = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as handle:
                snap[rel] = handle.read()
    return snap


def _no_staging(lib: str) -> bool:
    return not any(
        name.startswith(".fpsoundpack-") for name in os.listdir(lib))


def _payload(sounds: dict[str, bytes],
             manifest: dict[str, str] | None = None) -> bytes:
    """A valid pack payload: every member mapped, digests matching bytes."""
    events = {}
    for index, rel in enumerate(sorted(sounds)):
        events[f"event{index}"] = {"file": rel}
    if manifest is None:
        manifest = {
            rel: hashlib.sha256(data).hexdigest()
            for rel, data in sounds.items()}
    return json.dumps({
        "schema_version": 1,
        "id": "p",
        "name": "P",
        "events": events,
        "asset_manifest": manifest,
    }).encode("utf-8")


def _store(tmp_path) -> PresetStore:
    return PresetStore(str(tmp_path / "audio.db"))


def _fail_nth_publication(monkeypatch, imported_root: str, nth: int) -> None:
    """Make the ``nth`` publication move into ``imported_root`` fail."""
    real_replace = os.replace
    seen = {"n": 0}

    def wrapper(src, dst):
        target = os.path.normpath(str(dst))
        if target.lower().startswith(
                os.path.normpath(imported_root).lower() + os.sep):
            seen["n"] += 1
            if seen["n"] == nth:
                raise OSError(f"injected publication failure #{nth}")
        return real_replace(src, dst)

    monkeypatch.setattr(sound_presets.os, "replace", wrapper)


class TestPartialPublicationRollback:
    def test_second_publish_failure_rolls_back_first(
            self, tmp_path, monkeypatch):
        """A: first os.replace succeeds, second raises -> nothing survives."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        _fail_nth_publication(monkeypatch, str(lib / "imported"), nth=2)
        with pytest.raises(OSError):
            import_preset_payload(
                _payload(sounds), store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        assert _snapshot(str(lib)) == before, (
            "a failed publication must leave the managed library exactly as "
            "it was -- the already-published a.wav was not rolled back")
        assert _no_staging(str(lib)), "staging directory must be removed"
        assert store.get_preset("p") is None

    def test_first_publish_failure_introduces_nothing(
            self, tmp_path, monkeypatch):
        """B: the very first publication fails -> zero files introduced."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        _fail_nth_publication(monkeypatch, str(lib / "imported"), nth=1)
        with pytest.raises(OSError):
            import_preset_payload(
                _payload(sounds), store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        assert _snapshot(str(lib)) == before
        assert _no_staging(str(lib))
        assert store.get_preset("p") is None

    def test_third_of_three_failure_rolls_back_first_two(
            self, tmp_path, monkeypatch):
        """C: publications 1 and 2 rolled back, 3 never lands."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B", "c.wav": b"WAV-C"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        _fail_nth_publication(monkeypatch, str(lib / "imported"), nth=3)
        with pytest.raises(OSError):
            import_preset_payload(
                _payload(sounds), store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        assert _snapshot(str(lib)) == before
        assert _no_staging(str(lib))
        assert store.get_preset("p") is None

    def test_collision_target_preserved_and_new_file_removed(
            self, tmp_path, monkeypatch):
        """D: existing imported/a.wav=OLD stays byte-identical; the
        collision-safe copy of NEW is removed when a later member fails."""
        lib = tmp_path / "lib"
        (lib / "imported").mkdir(parents=True)
        existing = lib / "imported" / "a.wav"
        existing.write_bytes(b"OLD")
        sounds = {"a.wav": b"NEW", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        _fail_nth_publication(monkeypatch, str(lib / "imported"), nth=2)
        with pytest.raises(OSError):
            import_preset_payload(
                _payload(sounds), store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        after = _snapshot(str(lib))
        assert after == before, (
            "OLD must remain byte-identical and the collision-safe NEW "
            f"copy must be removed; delta={set(after) ^ set(before)}")
        assert existing.read_bytes() == b"OLD"
        assert not (lib / "imported" / "a__import1.wav").exists(), (
            "the collision-safe publication of NEW is an orphan")
        assert _no_staging(str(lib))
        assert store.get_preset("p") is None

    def test_store_failure_rolls_back_all_published_assets(
            self, tmp_path, monkeypatch):
        """E: publication succeeds fully, store.upsert fails -> every newly
        published asset removed, pre-existing assets untouched."""
        lib = tmp_path / "lib"
        (lib / "imported").mkdir(parents=True)
        (lib / "imported" / "old.wav").write_bytes(b"OLD")
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))

        def boom(*args, **kwargs):
            raise RuntimeError("store down")

        monkeypatch.setattr(store, "upsert", boom)
        with pytest.raises(RuntimeError):
            import_preset_payload(
                _payload(sounds), store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        after = _snapshot(str(lib))
        assert after == before, (
            "a store failure must remove the files THIS import published "
            f"and nothing else; delta={set(after) ^ set(before)}")
        assert after["imported/old.wav"] == b"OLD"
        assert _no_staging(str(lib))

    def test_success_publishes_each_asset_once_with_final_refs(
            self, tmp_path):
        """F: all assets published exactly once, refs remapped to their final
        collision-safe paths, preset stored, no staging remains."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        imported = import_preset_payload(
            _payload(sounds), store, new_id="p",
            sounds_dir=str(lib), pack_sounds=sounds)
        snap = _snapshot(str(lib))
        assert snap == {
            "imported/a.wav": b"WAV-A",
            "imported/b.wav": b"WAV-B",
        }, "each asset published exactly once at its final path"
        assert imported["events"]["event0"]["file"] == "user:imported/a.wav"
        assert imported["events"]["event1"]["file"] == "user:imported/b.wav"
        stored = store.get_preset("p")
        assert stored is not None
        assert stored["events"]["event0"]["file"] == "user:imported/a.wav"
        assert _no_staging(str(lib))

    def test_digest_mismatch_leaves_zero_publication(self, tmp_path):
        """G (digest): a manifest that does not match the bytes rejects the
        import before any publication."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "b.wav": b"WAV-B"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        with pytest.raises(ValueError):
            import_preset_payload(
                _payload(sounds, manifest={"a.wav": "0" * 64,
                                           "b.wav": "0" * 64}),
                store, new_id="p",
                sounds_dir=str(lib), pack_sounds=sounds)
        assert _snapshot(str(lib)) == before
        assert _no_staging(str(lib))
        assert store.get_preset("p") is None

    def test_preflight_rejection_leaves_zero_publication(self, tmp_path):
        """G (preflight): a non-.wav member rejects the whole pack before
        any publication."""
        lib = tmp_path / "lib"
        lib.mkdir()
        sounds = {"a.wav": b"WAV-A", "z.txt": b"BAD"}
        store = _store(tmp_path)
        before = _snapshot(str(lib))
        with pytest.raises(ValueError):
            import_preset_payload(
                _payload(sounds), store,
                new_id="p", sounds_dir=str(lib),
                pack_sounds=sounds)
        assert _snapshot(str(lib)) == before
        assert _no_staging(str(lib))
        assert store.get_preset("p") is None
