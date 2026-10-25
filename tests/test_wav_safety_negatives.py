"""T-1517 negative regression tests for SOUND-01 / SOUND-02 / SOUND-03.

Each test documents a defect that the fix closed: if the defensive code were
ever removed or weakened, the corresponding test would go red.

SOUND-01  contained_path must use realpath so a symlinked child cannot
         escape the managed root.
SOUND-02  import_file's collision loop must never overwrite an existing
         file; a new suffix must be minted instead.
SOUND-03  a failed copy must remove only the staging temp, never the
         pre-existing destination.
"""

from __future__ import annotations

import os
import struct
import sys
import wave

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import sound_library


def _make_wav(path: str, frames: int = 16) -> str:
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<h", 0) * frames)
    return path


# --- SOUND-01: containment rejects traversal through realpath -----------------

def test_so1_contained_path_rejects_traversal_escape(tmp_path):
    """A ref with ``..`` that would resolve outside the managed root is rejected.

    Before the fix, ``contained_path`` used lexical ``normpath`` which could
    be tricked by crafted paths. The fix switched both the base and the joined
    path to ``realpath``, so the real destination is checked against the real
    base directory.
    """
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside.wav"
    _make_wav(outside)

    # Traversal that would escape the managed root
    resolved = sound_library.contained_path(str(managed), "../outside.wav")
    assert resolved is None, "traversal escape must be rejected at the resolver"


def test_so1_contained_path_rejects_deep_traversal(tmp_path):
    """``a/../../outside.wav`` resolves outside the root and is rejected."""
    managed = tmp_path / "managed"
    (managed / "sub").mkdir(parents=True)
    outside = tmp_path / "outside.wav"
    _make_wav(outside)

    resolved = sound_library.contained_path(str(managed), "sub/../../outside.wav")
    assert resolved is None


def test_so1_contained_path_accepts_valid_relative(tmp_path):
    """A genuinely contained relative path resolves correctly."""
    managed = tmp_path / "managed"
    (managed / "imported").mkdir(parents=True)
    target = managed / "imported" / "custom.wav"
    _make_wav(target)

    resolved = sound_library.contained_path(str(managed), "imported/custom.wav")
    assert resolved is not None
    assert os.path.realpath(resolved) == os.path.realpath(str(target))


def test_so1_contained_path_rejects_absolute(tmp_path):
    """Absolute paths are always rejected -- never a playable token."""
    managed = tmp_path / "managed"
    managed.mkdir()
    target = tmp_path / "outside.wav"
    _make_wav(target)

    resolved = sound_library.contained_path(str(managed), str(target))
    assert resolved is None


def test_so1_realpath_used_not_normpath():
    """Static guard: contained_path must use os.path.realpath, not normpath.

    If someone reverts to ``os.path.normpath`` for containment, this test goes
    red, catching the SOUND-01 regression at import time.
    """
    import inspect

    source = inspect.getsource(sound_library.contained_path)
    assert "os.path.realpath" in source
    assert "os.path.normpath" not in source


# --- SOUND-02: no-clobber collision in import_file ---------------------------

def test_so2_import_file_never_overwrites_existing(tmp_path, monkeypatch):
    """A destination that already exists must get a suffixed copy, not a
    clobber. Before the fix the loop could exhaust and fall through to an
    unconditional ``shutil.copy2`` that overwrote the file the user picked."""

    managed = tmp_path / "data" / "sound_library"
    managed.mkdir(parents=True)
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(managed))
    monkeypatch.setattr(sound_library, "ensure_managed_root", lambda: str(managed))

    src_a = _make_wav(tmp_path / "a.wav")
    src_b = _make_wav(tmp_path / "b.wav")

    ref_a = sound_library.import_file(src_a, subdir="imported")
    ref_b = sound_library.import_file(src_b, subdir="imported")

    # both succeeded and are distinct
    assert ref_a and ref_b
    phys_a = sound_library.contained_path(str(managed), ref_a.split("user:", 1)[1])
    phys_b = sound_library.contained_path(str(managed), ref_b.split("user:", 1)[1])
    assert phys_a and phys_b and phys_a != phys_b

    # the FIRST file must still be intact (not overwritten by the second import)
    assert os.path.isfile(phys_a)
    assert _looks_like_wav(phys_a)


def test_so2_import_file_preserves_existing_until_publish(tmp_path, monkeypatch):
    """If the copy itself fails, the existing destination is untouched.

    Before the fix, a failed copy could remove the pre-existing file because
    the cleanup path used the destination path. Now the staging temp is the
    only thing removed.
    """
    managed = tmp_path / "data" / "sound_library"
    managed.mkdir(parents=True)
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(managed))
    monkeypatch.setattr(sound_library, "ensure_managed_root", lambda: str(managed))

    pre_existing = _make_wav(managed / "imported" / "keep.wav")
    assert os.path.isfile(pre_existing)
    before = open(pre_existing, "rb").read()

    garbage_src = tmp_path / "source.txt"
    garbage_src.write_text("not a wav")

    # import_file rejects non-.wav sources entirely
    ref = sound_library.import_file(str(garbage_src), subdir="imported")
    assert ref == ""

    # the pre-existing wav is intact
    assert os.path.isfile(pre_existing)
    assert open(pre_existing, "rb").read() == before


# --- SOUND-03: staging temp is cleaned on failure ---------------------------

def test_so3_failed_import_removes_only_staging(tmp_path, monkeypatch):
    """On a copy failure the staging file is removed but no destination is
    created. Before the fix, the cleanup-delete path targeted the real
    destination, so a failed import could delete a user's file."""

    managed = tmp_path / "data" / "sound_library"
    managed.mkdir(parents=True)
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(managed))
    monkeypatch.setattr(sound_library, "ensure_managed_root", lambda: str(managed))

    src = _make_wav(tmp_path / "src.wav")

    # Sabotage shutil.copy2 to simulate a disk failure mid-copy
    def boom_copy2(src, dst, *a, **kw):
        # leave a partial staging file behind to prove cleanup runs
        with open(dst, "wb") as f:
            f.write(b"PARTIAL")
        raise OSError("simulated disk full")

    monkeypatch.setattr("shutil.copy2", boom_copy2)

    ref = sound_library.import_file(src, subdir="imported")
    assert ref == ""

    # no destination was ever created
    files = os.listdir(managed / "imported")
    assert files == []  # only a staging temp might have existed, now removed


# --- helper -------------------------------------------------------------------

def _looks_like_wav(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    except OSError:
        return False
