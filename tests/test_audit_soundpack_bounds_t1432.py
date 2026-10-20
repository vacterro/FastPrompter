"""T-1432 (SRC-093) — W2-002 ``.fpsoundpack`` resource-bound suite.

The import boundary must be bounded in ALL FOUR dimensions — compressed input,
``preset.json``, one member, and the aggregate — and the budget must be
enforced from ``ZipInfo`` metadata BEFORE any payload is decompressed, so a
tiny highly-compressed pack cannot exhaust RAM before semantic validation.
"""

from __future__ import annotations

import inspect
import io
import json
import zipfile

import pytest

from fastprompter.core import sound_presets as sp


def _preset(preset_id="p1"):
    return {
        "schema_version": 1, "id": preset_id, "name": "Pack", "events": {},
    }


def _pack_bytes(preset=None, members=None, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        archive.writestr("preset.json", json.dumps(preset or _preset()))
        for name, payload in (members or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_w2_002_declared_aggregate_is_refused_before_any_extraction(
        monkeypatch):
    # 16 x 1 MiB of zeros: a few KB on disk, 16 MiB declared.
    members = {f"sounds/{i:02d}.wav": b"\x00" * (1024 * 1024)
               for i in range(16)}
    pack = _pack_bytes(members=members)
    assert len(pack) < 64 * 1024            # genuinely tiny on disk

    monkeypatch.setattr(sp, "MAX_PACK_TOTAL_BYTES", 1024 * 1024)

    opened = []
    real_open = zipfile.ZipFile.open

    def spy(self, *args, **kwargs):
        opened.append(args)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)

    with pytest.raises(ValueError, match="aggregate"):
        sp.open_preset_pack(pack)
    assert opened == []                     # nothing was decompressed


def test_w2_002_oversized_preset_json_is_refused_before_json_loads(
        monkeypatch):
    pack = _pack_bytes(preset=_preset())

    def explode(*args, **kwargs):           # pragma: no cover - must not run
        raise AssertionError("json.loads ran before the preset bound")

    monkeypatch.setattr(sp.json, "loads", explode)
    monkeypatch.setattr(sp, "MAX_PACK_PRESET_BYTES", 32)

    with pytest.raises(ValueError, match="preset.json"):
        sp.open_preset_pack(pack)


def test_w2_002_compressed_input_over_budget_is_refused_without_reading(
        tmp_path, monkeypatch):
    pack = _pack_bytes(members={"sounds/a.wav": b"\x00" * 4096})
    path = tmp_path / "big.fpsoundpack"
    path.write_bytes(pack)

    monkeypatch.setattr(sp, "MAX_PACK_BYTES", 16)

    with pytest.raises(ValueError, match="too large"):
        sp.open_preset_pack_path(str(path))
    with pytest.raises(ValueError, match="too large"):
        sp.open_preset_pack(pack)


def test_w2_002_duplicate_canonical_member_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("preset.json", json.dumps(_preset()))
        archive.writestr("sounds/a.wav", b"x")
        archive.writestr("sounds/A.wav", b"y")   # same canonical name
    with pytest.raises(ValueError, match="duplicate"):
        sp.open_preset_pack(buffer.getvalue())


def test_w2_002_per_member_bound_is_still_enforced(monkeypatch):
    pack = _pack_bytes(members={"sounds/a.wav": b"\x00" * 2048})
    monkeypatch.setattr(sp, "MAX_PACK_MEMBER_BYTES", 1024)
    with pytest.raises(ValueError, match="member too large"):
        sp.open_preset_pack(pack)


def test_w2_002_a_member_lying_about_its_size_cannot_overflow(monkeypatch):
    # A stored (uncompressed) member whose DECLARED size is small but whose
    # real payload is larger must still be capped by the read bound.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("preset.json", json.dumps(_preset()))
        archive.writestr("sounds/a.wav", b"\x00" * 4096)
    raw = bytearray(buffer.getvalue())
    # Patch the central-directory AND local file_size fields to a lie. The
    # write bound must catch it even though the declared size passes.
    raw = bytes(raw).replace(b"\x00\x10\x00\x00\x00\x00", b"\x00\x01\x00\x00\x00\x00")
    monkeypatch.setattr(sp, "MAX_PACK_MEMBER_BYTES", 2048)
    monkeypatch.setattr(sp, "MAX_PACK_TOTAL_BYTES", 2048)
    # declared sizes now pass the preflight; the read bound must refuse
    with pytest.raises(ValueError):
        sp.open_preset_pack(raw)


def test_w2_002_path_and_bytes_readers_agree_on_a_normal_pack(tmp_path):
    members = {"sounds/a.wav": b"RIFF" + b"\x00" * 64}
    pack = _pack_bytes(members=members)
    path = tmp_path / "ok.fpsoundpack"
    path.write_bytes(pack)

    from_bytes = sp.open_preset_pack(pack)
    from_path = sp.open_preset_pack_path(str(path))
    assert from_bytes == from_path
    definition, sounds = from_path
    assert definition["id"] == "p1"
    assert sounds["a.wav"] == members["sounds/a.wav"]


def test_w2_002_export_round_trips_through_the_path_reader(tmp_path):
    from fastprompter.core.sound_presets import export_preset_pack

    sounds_dir = tmp_path / "lib"
    sounds_dir.mkdir()
    wav = sounds_dir / "a.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 128)
    preset = {
        "schema_version": 1, "id": "p1", "name": "P",
        "events": {"click": {"file": "a.wav"}},
    }
    pack, missing = export_preset_pack(preset, str(sounds_dir))
    assert missing == []
    path = tmp_path / "p.fpsoundpack"
    path.write_bytes(pack)

    definition, sounds = sp.open_preset_pack_path(str(path))
    assert definition["id"] == "p1"
    assert list(sounds) == ["a.wav"]


def test_w2_002_ui_import_never_reads_a_pack_wholesale():
    from fastprompter.ui import audio_hub_pages as pages

    src = inspect.getsource(pages.PresetsPage._import)
    assert "open_preset_pack_path" in src
    assert 'open(path, "rb").read()' not in src
