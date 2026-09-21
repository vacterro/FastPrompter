"""T-1238-E1.4: what the packaged build must and must not contain.

Two real defects this suite pins:

* the build excluded ``PyQt6.QtMultimedia`` outright, so every shipped EXE
  fell back to the degraded NullTransport and NOTHING in the Audio Hub could
  actually mix, loop, fade or stop a channel;
* the private ``_vault/`` namespace now holds GoldSrc VOX/FVOX voice
  material, which belongs to its owners and must never ride along in a
  build -- users import it from their own copy of the game.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "FastPrompter.pyw"
SOUND_DIR = ROOT / "src" / "fastprompter" / "sound"

#: The six Problip cues that MUST ship.
PROBLIP_WAVS = (
    "blip01.wav", "blip_glass.wav", "blip_wood.wav",
    "blip_soft_bell.wav", "blip_bonk.wav", "blip_space.wav",
)

#: Packs that must NEVER be bundled automatically.
PROPRIETARY_VAULT_PACKS = ("vox", "fvox", "gman", "amx_ultimate")


def _nuitka_options() -> list[str]:
    text = LAUNCHER.read_text(encoding="utf-8")
    return re.findall(r"^# nuitka-project:\s*(.+?)\s*$", text, re.MULTILINE)


class TestProblipAssets:
    @pytest.mark.parametrize("name", PROBLIP_WAVS)
    def test_the_six_problip_sounds_are_in_the_checkout(self, name):
        path = SOUND_DIR / "problip" / name
        assert path.is_file(), f"{name} is missing from the real checkout"
        assert path.stat().st_size > 0

    def test_the_problip_folder_ships_with_the_sound_directory(self):
        options = _nuitka_options()
        assert any(o.startswith("--include-data-dir=src/fastprompter/sound=")
                   for o in options)

    def test_every_catalog_entry_resolves(self):
        from fastprompter.sound.problip.catalog import (
            SoundCatalog,
            resolve_sound_path,
        )

        unresolved = [entry.sound_id for entry in SoundCatalog.all
                      if resolve_sound_path(entry.sound_id) is None]
        assert unresolved == []

    def test_default_problip_pool_is_playable_from_a_clean_checkout(self):
        from fastprompter.core.problip_store import ProblipSettings
        from fastprompter.sound.problip.catalog import inspect_sound_pool

        settings = ProblipSettings()
        status = inspect_sound_pool(settings.selected_sound_ids)

        assert status.playable_ids == tuple(settings.selected_sound_ids)
        assert status.missing_ids == ()
        assert status.invalid_ids == ()


class TestMultimediaBackend:
    def test_qtmultimedia_is_not_excluded_from_the_build(self):
        options = _nuitka_options()
        excluded = [o for o in options
                    if "nofollow-import-to" in o and "QtMultimedia" in o]
        assert not excluded, (
            "QtMultimedia was excluded from the EXE, so the packaged app had "
            "no mixing backend at all: " + ", ".join(excluded))

    def test_qtmultimedia_is_explicitly_included(self):
        options = _nuitka_options()
        assert any("QtMultimedia" in o and "include-module" in o
                   for o in options)

    def test_the_multimedia_qt_plugins_are_requested(self):
        options = _nuitka_options()
        plugins = [o for o in options if o.startswith("--include-qt-plugins=")]
        assert plugins, "no Qt plugin set is requested at all"
        assert any("multimedia" in o for o in plugins)

    def test_the_rich_backend_builds_against_this_binding(self):
        pytest.importorskip("PyQt6.QtMultimedia")
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QSoundEffect

        from fastprompter.core.audio_hub import QtSoundTransport

        transport = QtSoundTransport(qsoundeffect_cls=QSoundEffect,
                                     url_factory=QUrl.fromLocalFile)
        assert transport.capability_mixing


class TestProprietaryAssetSafety:
    @pytest.mark.parametrize("pack", PROPRIETARY_VAULT_PACKS)
    def test_goldsrc_packs_are_excluded_from_the_build(self, pack):
        options = _nuitka_options()
        assert any(o == f"--noinclude-data-files=sound/_vault/{pack}/*"
                   for o in options), (
            f"_vault/{pack}/ would be bundled into the release")

    def test_no_imported_pack_lives_outside_the_vault(self):
        """Imported game audio must stay in _vault/ or the user data dir."""
        for pack in PROPRIETARY_VAULT_PACKS:
            assert not (SOUND_DIR / pack).exists(), (
                f"{pack}/ escaped the private namespace into the shipped "
                "sound root")

    def test_the_everyday_library_never_lists_vault_material(self):
        from fastprompter.core.sound_manager import discover_sound_files

        listing = discover_sound_files(str(SOUND_DIR), force=True)
        assert not [ref for ref in listing if ref.startswith("_vault/")]

    def test_no_minecraft_assets_are_bundled(self):
        """The Minecraft preset is a DEFINITION; it ships no audio."""
        from fastprompter.core.sound_presets import minecraft_preset_definition

        preset = minecraft_preset_definition()
        assert preset["assets_missing"] is True
        bound = [event for event, entry in (preset.get("events") or {}).items()
                 if (entry or {}).get("file")]
        assert bound == [], "the Minecraft preset must bind no bundled file"
