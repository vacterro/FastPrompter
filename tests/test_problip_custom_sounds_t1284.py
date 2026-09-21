"""T-1284 / audit/10 CORE-003: the Problip custom-sound dialog's checkbox
selection must persist, and removal must be transactional with a never-dangling
playable pool.

Before the repair `_persist_pool()` had no call site and no list signal was
connected, so ticking/unticking a managed WAV changed only the widget state and
was discarded by the next reload. Removal additionally deleted the file after
mutating the pool and could leave a dangling token.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import sound_library  # noqa: E402
from fastprompter.core.problip import DEFAULT_SOUND_ID  # noqa: E402
from fastprompter.ui.problip_custom_sounds import ProblipCustomDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])

_CHECKED = Qt.CheckState.Checked
_UNCHECKED = Qt.CheckState.Unchecked


class _FakeController:
    """Just enough ProblipController surface for the dialog."""

    def __init__(self, sound_ids):
        self._ids = list(sound_ids)
        self.updates = []

    class _S:
        def __init__(self, ids):
            self.selected_sound_ids = list(ids)

    @property
    def settings(self):
        return self._S(self._ids)

    def update_settings(self, **changes):
        self.updates.append(changes)
        if "selected_sound_ids" in changes:
            self._ids = list(changes["selected_sound_ids"])
        return self.settings

    def test_path(self, path):
        return (True, path)


def _make_wav(path, marker=1):
    import struct
    import wave
    frames = struct.pack("<" + "h" * 32, *([marker, -marker] * 16))
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(22050)
        fh.writeframes(frames)


@pytest.fixture()
def managed(monkeypatch, tmp_path):
    """A private managed sound root with two imported WAVs."""
    root = tmp_path / "managed"
    root.mkdir()
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(root))
    monkeypatch.setattr(sound_library, "ensure_managed_root", lambda: str(root))
    for name in ("imported/a.wav", "imported/b.wav"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        _make_wav(p)
    return root


def _dialog(managed, selected):
    ctrl = _FakeController(selected)
    dlg = ProblipCustomDialog(None, "EN", ctrl)
    return dlg, ctrl


def _item_for(dlg, rel):
    for i in range(dlg.list.count()):
        it = dlg.list.item(i)
        if str(it.data(Qt.ItemDataRole.UserRole)) == rel:
            return it
    raise AssertionError(f"no item for {rel}")


def test_tick_persists_immediately(managed):
    """Ticking an unselected managed sound writes the pool right away."""
    dlg, ctrl = _dialog(managed, [DEFAULT_SOUND_ID])
    assert ctrl.updates == []
    item = _item_for(dlg, "user:imported/a.wav")
    item.setCheckState(_CHECKED)          # a REAL user change, not reload()
    assert ctrl.updates, "checkbox change did not persist the pool"
    assert "user:imported/a.wav" in ctrl.updates[-1]["selected_sound_ids"]


def test_untick_persists_immediately(managed):
    dlg, ctrl = _dialog(managed, [DEFAULT_SOUND_ID, "user:imported/a.wav"])
    dlg._persist_pool()                   # establish the pool baseline
    ctrl.updates.clear()
    item = _item_for(dlg, "user:imported/a.wav")
    item.setCheckState(_UNCHECKED)
    assert ctrl.updates, "untick did not persist the pool"
    assert "user:imported/a.wav" not in ctrl.updates[-1]["selected_sound_ids"]


def test_reload_does_not_rewrite_settings(managed):
    """Programmatic check-state population must not recurse into a write."""
    dlg, ctrl = _dialog(managed, [DEFAULT_SOUND_ID, "user:imported/a.wav"])
    ctrl.updates.clear()
    dlg.reload()
    assert ctrl.updates == [], "reload() wrote settings via itemChanged"


def test_removal_of_sole_selection_restores_canonical_fallback(managed):
    """Removing the only selected custom sound leaves a valid playable pool."""
    dlg, ctrl = _dialog(managed, ["user:imported/a.wav"])
    dlg._drop_from_pool("user:imported/a.wav")
    assert ctrl.updates[-1]["selected_sound_ids"] == [DEFAULT_SOUND_ID]


def test_remove_failure_leaves_pool_and_file_unchanged(managed, monkeypatch):
    """A failed filesystem delete must NOT drop the pool token."""
    dlg, ctrl = _dialog(managed, [DEFAULT_SOUND_ID, "user:imported/a.wav"])
    ctrl.updates.clear()
    monkeypatch.setattr(sound_library, "remove_managed_sound", lambda ref: False)
    monkeypatch.setattr(
        "fastprompter.ui.problip_custom_sounds.QMessageBox.question",
        staticmethod(lambda *a, **k: __import__(
            "PyQt6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(
        "fastprompter.ui.problip_custom_sounds.QMessageBox.warning",
        staticmethod(lambda *a, **k: None))
    dlg.list.setCurrentItem(_item_for(dlg, "user:imported/a.wav"))
    dlg._remove()
    assert ctrl.updates == [], "failed removal mutated the pool"
    assert (managed / "imported/a.wav").exists()
