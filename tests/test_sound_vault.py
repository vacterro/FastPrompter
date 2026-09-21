"""The private ``_vault/`` sound namespace.

``src/fastprompter/sound/_vault/`` holds bulk raw material (GoldSrc vox/fvox
fragments, the cs_style pack).  It must stay fully playable by reference and
stay OUT of the everyday picker: listing all 1283 files made every event row
carry its own copy of the library and turned Sound Settings into a
multi-second dialog.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import sound_library  # noqa: E402
from fastprompter.core.sound_manager import (  # noqa: E402
    _DEFAULT_SOUND_MAP,
    VAULT_DIR_NAME,
    discover_sound_files,
    discover_vault_files,
    get_resource_path,
)


def _wav(path) -> None:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 100)


@pytest.fixture()
def library(tmp_path):
    _wav(tmp_path / "click.wav")
    _wav(tmp_path / "pack" / "open.wav")
    _wav(tmp_path / VAULT_DIR_NAME / "vox" / "thirty.wav")
    _wav(tmp_path / VAULT_DIR_NAME / "cs_style" / "buttonclick.wav")
    return str(tmp_path)


class TestDiscovery:
    def test_the_vault_is_not_in_the_everyday_listing(self, library):
        listing = discover_sound_files(library, force=True)
        assert listing == ["click.wav", "pack/open.wav"]

    def test_the_vault_is_listed_only_on_request(self, library):
        assert discover_vault_files(library, force=True) == [
            "_vault/cs_style/buttonclick.wav",
            "_vault/vox/thirty.wav",
        ]

    def test_explicit_include_returns_everything(self, library):
        listing = discover_sound_files(library, force=True, include_vault=True)
        assert len(listing) == 4

    def test_no_vault_directory_is_not_an_error(self, tmp_path):
        _wav(tmp_path / "only.wav")
        assert discover_vault_files(str(tmp_path), force=True) == []

    def test_the_shipped_vault_really_shrinks_the_picker(self):
        packaged = get_resource_path("sound")
        everyday = discover_sound_files(packaged, force=True)
        vault = discover_vault_files(packaged, force=True)
        assert vault, "the shipped _vault/ namespace is missing"
        assert not [ref for ref in everyday if ref.startswith("_")]
        assert len(everyday) < len(everyday) + len(vault)


class TestResolution:
    def test_an_explicit_vault_ref_still_plays(self, library):
        resolved = sound_library.resolve_sound_ref(
            "_vault/vox/thirty.wav", builtin_root=library, user_root=library)
        assert resolved and os.path.isfile(resolved)

    def test_a_plain_ref_falls_back_into_the_vault(self, library):
        """Moving cs_style/ into the vault must not break a shipped default."""
        resolved = sound_library.resolve_sound_ref(
            "cs_style/buttonclick.wav", builtin_root=library,
            user_root=library)
        assert resolved and os.path.isfile(resolved)

    def test_the_root_still_wins_over_the_vault(self, tmp_path):
        _wav(tmp_path / "dup.wav")
        _wav(tmp_path / VAULT_DIR_NAME / "dup.wav")
        resolved = sound_library.resolve_sound_ref(
            "dup.wav", builtin_root=str(tmp_path), user_root=str(tmp_path))
        assert resolved == os.path.normpath(str(tmp_path / "dup.wav"))

    def test_traversal_out_of_the_vault_is_still_refused(self, library):
        assert sound_library.resolve_sound_ref(
            "_vault/../../escape.wav", builtin_root=library,
            user_root=library) is None

    def test_every_shipped_default_still_resolves(self):
        packaged = get_resource_path("sound")
        unresolved = [
            f"{event}={ref}" for event, ref in _DEFAULT_SOUND_MAP.items()
            if sound_library.resolve_sound_ref(ref, builtin_root=packaged) is None
        ]
        assert unresolved == []


qtwidgets = pytest.importorskip("PyQt6.QtWidgets")


class TestDialogSharesOneModel:
    def test_every_combo_shares_one_model_and_keeps_its_own_selection(self):
        from PyQt6.QtWidgets import QApplication, QWidget

        from fastprompter.core.sound_manager import SoundManager
        from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

        app = QApplication.instance() or QApplication([])
        assert app is not None
        parent = QWidget()
        data: dict = {"sound_ui": "True"}
        manager = SoundManager(parent, data)
        dialog = SoundSettingsDialog(parent, data, manager)
        try:
            # T-1272: the dialog builds rows progressively (10 immediately,
            # the rest on a 0 ms timer), so this suite must materialise them
            # explicitly instead of asserting the old eager-build contract.
            dialog._ensure_all_events_built()
            combos = list(dialog._combos.values())
            assert len(combos) > 10
            models = {id(c.model()) for c in combos}
            assert len(models) == 1, "each row must NOT own a copy of the library"
            assert dialog._combos["click"].currentData() == "button1.wav"
            assert dialog._combos["hover"].currentData() == (
                "cs_style/buttonrollover.wav")
        finally:
            dialog.deleteLater()
            manager.shutdown()
            parent.deleteLater()

    def test_a_vault_backed_default_is_not_labelled_missing(self):
        from PyQt6.QtWidgets import QApplication, QWidget

        from fastprompter.core.sound_manager import SoundManager
        from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

        app = QApplication.instance() or QApplication([])
        assert app is not None
        parent = QWidget()
        data: dict = {"sound_ui": "True"}
        manager = SoundManager(parent, data)
        dialog = SoundSettingsDialog(parent, data, manager)
        try:
            assert "missing" not in dialog._combos["hover"].currentText()
        finally:
            dialog.deleteLater()
            manager.shutdown()
            parent.deleteLater()
