"""T-1435 (SRC-095 W2-005 / W2-006) — the preset-pack export is atomic and
never ships a silently incomplete archive.

W2-005: ``export_preset_pack`` hashed each referenced source in one pass and
re-opened it for the member payload in a second pass. A source mutated between
the two passes produced a pack whose ``asset_manifest`` disagreed with its own
member bytes, so the archive failed its own import with
``ValueError: asset digest mismatch``. Each source is now read exactly once.

W2-006: the core already returned ``(zip_bytes, missing_files)`` but
``PresetsPage._export`` discarded the missing list and wrote the payload anyway,
shipping a pack that does not contain every referenced sound. It now refuses.
"""

from __future__ import annotations

import builtins
import hashlib
import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from fastprompter.core import sound_presets as sp

_APP = QApplication.instance() or QApplication([])


def _preset(*rels):
    events = {f"e{i}": {"file": rel} for i, rel in enumerate(rels)}
    return {"schema_version": 1, "id": "p1", "name": "P", "events": events}


# --- W2-005: read once ----------------------------------------------------

def test_w2_005_each_source_is_read_exactly_once(tmp_path, monkeypatch):
    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")
    (sounds / "b.wav").write_bytes(b"RIFF-B")

    opens: list[str] = []
    real_open = builtins.open

    def counting_open(file, *a, **k):
        if isinstance(file, (str, os.PathLike)) and str(file).endswith(".wav"):
            opens.append(os.path.basename(str(file)))
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", counting_open)
    pack, missing = sp.export_preset_pack(_preset("a.wav", "b.wav"), str(sounds))
    monkeypatch.undo()

    assert missing == []
    assert sorted(opens) == ["a.wav", "b.wav"]     # one read each, never two


def test_w2_005_manifest_matches_the_member_bytes(tmp_path):
    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")

    pack, missing = sp.export_preset_pack(_preset("a.wav"), str(sounds))
    assert missing == []

    definition, members = sp.open_preset_pack(pack)
    # the pack validates against its own manifest and the payload is the SAME
    # bytes that produced the manifest digest
    assert definition["asset_manifest"]["a.wav"] == \
        hashlib.sha256(members["a.wav"]).hexdigest()
    assert members["a.wav"] == b"RIFF-A"


def test_w2_005_missing_source_is_reported_and_omitted(tmp_path):
    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")   # b.wav never created

    pack, missing = sp.export_preset_pack(_preset("a.wav", "b.wav"), str(sounds))

    assert missing == ["b.wav"]
    definition, members = sp.open_preset_pack(pack)   # still self-consistent
    assert "a.wav" in members
    assert "b.wav" not in members
    assert "b.wav" not in definition["asset_manifest"]


def test_w2_005_unreadable_source_is_reported_not_raised(tmp_path):
    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")
    (sounds / "dir.wav").mkdir()                # a directory, not a file

    pack, missing = sp.export_preset_pack(_preset("a.wav", "dir.wav"),
                                          str(sounds))

    assert missing == ["dir.wav"]
    _definition, members = sp.open_preset_pack(pack)
    assert "dir.wav" not in members


def test_w2_005_the_second_read_shape_is_gone():
    src = inspect.getsource(sp.export_preset_pack)
    # the member payload must come from the stored bytes, not a fresh open()
    assert "payloads[rel] = data" in src
    assert 'archive.writestr(f"sounds/{rel}", open(' not in src


# --- W2-006: refuse an incomplete pack ------------------------------------

def _page(tmp_path, monkeypatch, preset, sounds_dir):
    from fastprompter.ui import audio_hub_pages as pages

    sounds_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(pages.sound_library, "packaged_root",
                        staticmethod(lambda: str(sounds_dir)))
    store = sp.PresetStore(str(tmp_path / "audio.db"))
    page = pages.PresetsPage(None, "EN", store=store)
    monkeypatch.setattr(page, "current_preset", lambda: preset)
    warnings: list = []
    monkeypatch.setattr(pages.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    return pages, page, warnings


def test_w2_006_export_refuses_when_a_sound_is_missing(tmp_path, monkeypatch):
    from fastprompter.ui import audio_hub_pages as pages

    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")
    preset = _preset("a.wav", "b.wav")           # b.wav missing
    _pages, page, warnings = _page(tmp_path, monkeypatch, preset, sounds)

    target = tmp_path / "out.fpsoundpack"
    monkeypatch.setattr(pages.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))

    page._export()

    assert not target.exists(), "an incomplete pack must never be written"
    assert warnings, "the user must be told which sounds are missing"
    assert "b.wav" in str(warnings[0])


def test_w2_006_export_writes_when_every_asset_is_present(tmp_path,
                                                          monkeypatch):
    from fastprompter.ui import audio_hub_pages as pages

    sounds = tmp_path / "lib"
    sounds.mkdir()
    (sounds / "a.wav").write_bytes(b"RIFF-A")
    preset = _preset("a.wav")
    _pages, page, warnings = _page(tmp_path, monkeypatch, preset, sounds)

    target = tmp_path / "out.fpsoundpack"
    monkeypatch.setattr(pages.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))

    page._export()

    assert target.exists()
    assert warnings == []
    definition, members = sp.open_preset_pack_path(str(target))
    assert members["a.wav"] == b"RIFF-A"


def test_w2_006_the_export_guards_the_write_on_the_missing_list():
    from fastprompter.ui import audio_hub_pages as pages

    src = inspect.getsource(pages.PresetsPage._export)
    assert "missing_files" in src
    assert "if missing_files:" in src
    # the write must come AFTER the refusal, never before it
    assert src.index("if missing_files:") < src.index('open(path, "wb")')
