"""T-1510: every sound picker offers the SAME inventory.

The timer and the AI-limit rule pickers used to list only the packaged
snapshot, so a sound imported into the managed library (or dropped into the
addon folder) could never be selected there.  The one composition of the
picker inventory lives in ``core.sound_library.list_selectable_sounds``:
packaged, then managed, then addon.

The stored reference keeps its namespace (``file:user:imported/x.wav``), so
the canonical resolver finds the managed root instead of guessing.
"""

from __future__ import annotations

import os
import struct
import sys
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402

import fastprompter.ui.limit_settings_dialog as lsd_mod  # noqa: E402
import fastprompter.ui.timer_dialog as td_mod  # noqa: E402
from fastprompter.core import sound_library  # noqa: E402


def _wav(path: str, seconds: float = 0.01) -> None:
    """Write a real, playable PCM WAV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = int(8000 * seconds)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(struct.pack("<h", 0) * frames)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A private user-data root; the app's own root is never touched."""
    monkeypatch.setattr(sound_library, "get_data_dir", lambda: str(tmp_path))
    return tmp_path


class _FakeSoundManager:
    """Only the packaged snapshot -- the managed library is a filesystem fact."""

    def __init__(self, files):
        self._files = files

    def get_available_sounds(self):
        return list(self._files)


class _FakeMain:
    def __init__(self, files):
        self.sound_manager = _FakeSoundManager(files)
        self.data = {}


class _FakeTimer:
    def __init__(self, files):
        self.main_win = _FakeMain(files)
        self._sound_inventory_cache = None

    def _sound_inventory(self):
        return td_mod.TimerDialog._sound_inventory.__get__(self)()


class _FakeLimit:
    def __init__(self, files):
        self.main_win = _FakeMain(files)
        self.data = {}

    def _sound_inventory(self):
        return lsd_mod.LimitSettingsDialog._sound_inventory.__get__(self)()


def test_the_imported_sound_is_offered_by_every_picker(data_root):
    _wav(os.path.join(str(data_root), "sound_library", "imported", "mine.wav"))
    files = ["click.wav"]

    timer = _FakeTimer(files)._sound_inventory()
    limit = _FakeLimit(files)._sound_inventory()

    assert "user:imported/mine.wav" in [disp for disp, _ in timer]
    assert "user:imported/mine.wav" in [disp for disp, _ in limit]
    # the packaged sounds are still offered
    assert "click.wav" in [disp for disp, _ in timer]
    assert "click.wav" in [disp for disp, _ in limit]


def test_the_stored_ref_resolves_to_the_managed_root(data_root):
    _wav(os.path.join(str(data_root), "sound_library", "imported", "mine.wav"))
    files = ["click.wav"]

    timer = dict(_FakeTimer(files)._sound_inventory())
    limit = dict(_FakeLimit(files)._sound_inventory())

    ref = timer["user:imported/mine.wav"]
    assert ref == "file:user:imported/mine.wav"
    assert limit["user:imported/mine.wav"] == ref
    # the timer and the limit rules play the ref back through
    # SoundManager.play_sound_ref, which strips the "file:" prefix
    assert sound_library.resolve_sound_ref(ref[len("file:"):]) is not None


def test_the_addon_sound_is_offered_by_every_picker(data_root):
    _wav(os.path.join(str(data_root), "addon", "sounds", "drop.wav"))
    files = ["click.wav"]

    timer = _FakeTimer(files)._sound_inventory()
    limit = _FakeLimit(files)._sound_inventory()

    assert "addon:drop.wav" in [disp for disp, _ in timer]
    assert "addon:drop.wav" in [disp for disp, _ in limit]
    assert dict(timer)["addon:drop.wav"] == "file:addon:drop.wav"


def test_the_one_composition_lists_the_three_roots(data_root):
    _wav(os.path.join(str(data_root), "sound_library", "imported", "mine.wav"))
    _wav(os.path.join(str(data_root), "addon", "sounds", "drop.wav"))

    names = sound_library.list_selectable_sounds(["click.wav"])

    assert names == ["click.wav", "user:imported/mine.wav", "addon:drop.wav"]
