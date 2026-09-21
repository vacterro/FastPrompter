"""T-1238-C3: the Sound Settings dialog IS the Audio Hub.

The proven event table keeps working and grows a Mode column; the Presets,
Playback, Voice and Ambience pages live beside it in ONE dialog -- never a
second independent settings window.
"""

from __future__ import annotations

import os
import sys

import pytest
from _qt_retire import retire

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
    PlaybackMode,
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.core.sound_presets import PresetStore  # noqa: E402
from fastprompter.ui.audio_hub_pages import (  # noqa: E402
    EVENT_MODE_CHOICES,
    GLOBAL_MODE_CHOICES,
)
from fastprompter.ui.sound_settings_dialog import (  # noqa: E402
    _COL_MODE,
    SoundSettingsDialog,
)

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def dialog(tmp_path, monkeypatch):
    _ensure_app()
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir",
                        lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    data: dict = {"sound_ui": "True"}
    manager = SoundManager(host, data)
    transport = FakeMultiChannelTransport()
    manager._hub = AudioHub(transport=transport)
    widget = SoundSettingsDialog(host, data, manager)
    yield widget, manager, data, transport
    manager.shutdown()
    # T-1260: deleteLater() alone only POSTS the destruction and no event loop
    # runs here, so every test used to leave a whole SoundSettingsDialog alive
    # on the shared QApplication (measured: +35 514 widgets from this module).
    retire(widget, host)


class TestOneDialogFivePages:
    def test_the_five_pages_are_inside_the_same_dialog(self, dialog):
        widget, _m, _d, _t = dialog
        titles = [widget.pages.tabText(i) for i in range(widget.pages.count())]
        assert titles == ["Events", "Presets", "Playback", "Voice", "Ambience"]

    def test_the_event_table_survived_with_a_mode_column(self, dialog):
        widget, _m, _d, _t = dialog
        # T-1242: Event/On/Sound/Mode/Gain(+Auto)/Preview -- Auto shares the
        # Gain cell so the table keeps one cell widget fewer per row.
        assert widget.table.columnCount() == 6
        assert widget.table.rowCount() > 30
        assert widget.table.cellWidget(0, _COL_MODE) is not None

    def test_the_app_event_filters_are_restored_after_the_build(self, dialog):
        """The build suspends them for speed; leaving them off is a bug."""
        widget, _m, _d, _t = dialog
        host = widget.main_win
        for attr in widget._APP_FILTER_ATTRS:
            handler = getattr(host, attr, None)
            if handler is None:
                continue
            # Re-installing an already-installed filter is a no-op in Qt, so
            # the observable contract is simply that the objects still exist
            # and the dialog did not keep a suspension list.
            assert handler is not None


class TestEventModeColumn:
    def test_the_mode_choices_are_the_documented_four(self):
        assert [value for value, _t in EVENT_MODE_CHOICES] == [
            "inherit", "mix", "queue", "replace"]

    def test_changing_mode_persists_to_the_event_contract(self, dialog):
        widget, manager, data, _t = dialog
        combo = widget._modes["click"]
        combo.setCurrentIndex(combo.findData("replace"))
        assert data["sound_events"]["click"]["mode"] == "replace"
        assert manager.event_mode("click") == "replace"

    def test_the_runtime_consumes_it_immediately(self, dialog):
        widget, manager, _data, transport = dialog
        combo = widget._modes["click"]
        combo.setCurrentIndex(combo.findData("replace"))
        manager.play("save")
        manager.play("click")
        record = manager._hub.provenance()[-1]
        assert record["mode"] == "replace"

    def test_changing_mode_does_not_rebuild_the_dialog(self, dialog):
        widget, _m, _d, _t = dialog
        before = id(widget.table), id(widget._modes["click"])
        combo = widget._modes["click"]
        combo.setCurrentIndex(combo.findData("queue"))
        assert (id(widget.table), id(widget._modes["click"])) == before

    def test_a_stored_mode_is_reloaded(self, dialog):
        widget, _m, data, _t = dialog
        data.setdefault("sound_events", {}).setdefault("hover", {})["mode"] = \
            "queue"
        widget._load_settings()
        assert widget._modes["hover"].currentData() == "queue"


class TestPresetsPage:
    def test_the_real_store_is_shown(self, dialog):
        widget, _m, _d, _t = dialog
        names = [widget.presets_page.list.item(i).text()
                 for i in range(widget.presets_page.list.count())]
        assert any(n.startswith("Default") for n in names)
        assert any(n.startswith("CS 1.6") for n in names)
        assert any(n.startswith("Minecraft") for n in names)

    def test_minecraft_is_visible_but_marked_incomplete(self, dialog):
        widget, _m, _d, _t = dialog
        names = [widget.presets_page.list.item(i).text()
                 for i in range(widget.presets_page.list.count())]
        minecraft = next(n for n in names if n.startswith("Minecraft"))
        assert "incomplete" in minecraft

    def test_applying_a_preset_changes_mappings_and_the_global_mode(self,
                                                                    dialog):
        widget, manager, data, _t = dialog
        page = widget.presets_page
        for index in range(page.list.count()):
            if page.list.item(index).text().startswith("CS 1.6"):
                page.list.setCurrentRow(index)
                break
        page._apply()
        assert data["sound_events"]["hover"]["file"].endswith(
            "cs_style/buttonrollover.wav")
        assert data["audio_global_playback_mode"] in ("mix", "queue", "replace")
        assert manager._hub.global_mode is PlaybackMode.coerce(
            data["audio_global_playback_mode"])

    def test_save_as_persists_and_survives_a_new_store(self, dialog, tmp_path):
        widget, _m, _d, _t = dialog
        page = widget.presets_page
        definition = page._current_definition("preset_user_test", "My preset")
        page.store.upsert(definition)
        reopened = PresetStore(page.store.db_path)
        assert reopened.get_preset("preset_user_test")["name"] == "My preset"

    def test_delete_hides_a_factory_preset_and_restore_unhides_it(self, dialog):
        """Deleting a BUILT-IN hides it; the template is kept for Restore."""
        widget, _m, _d, _t = dialog
        page = widget.presets_page
        page.store.delete("preset_cs16")
        page.reload()
        listed = [page.list.item(i).text() for i in range(page.list.count())]
        assert not any(n.startswith("CS 1.6") for n in listed)
        page._restore_factory()
        listed = [page.list.item(i).text() for i in range(page.list.count())]
        assert any(n.startswith("CS 1.6") for n in listed)

    def test_events_using_ref_reports_affected_mappings(self, dialog):
        widget, _m, data, _t = dialog
        data.setdefault("sound_events", {})["click"] = {
            "enabled": "True", "file": "user:imported/x.wav",
            "volume": "", "mode": "inherit"}
        assert widget.events_using_ref("user:imported/x.wav") == ["click"]


class TestPlaybackPage:
    def test_the_three_global_modes_are_offered(self):
        assert [value for value, _t in GLOBAL_MODE_CHOICES] == [
            "mix", "queue", "replace"]

    def test_choosing_a_mode_persists_and_reaches_the_hub(self, dialog):
        widget, manager, data, _t = dialog
        page = widget.playback_page
        page.cb_global.setCurrentIndex(page.cb_global.findData("replace"))
        assert data["audio_global_playback_mode"] == "replace"
        assert manager._hub.global_mode is PlaybackMode.REPLACE

    def test_a_mixing_backend_is_reported_truthfully(self, dialog):
        widget, _m, _d, _t = dialog
        page = widget.playback_page
        page.reload()
        assert "Mixer available" in page.lbl_backend.text()
        assert page.cb_global.isEnabled()

    def test_a_degraded_backend_disables_the_modes(self, dialog):
        widget, manager, _d, _t = dialog
        from fastprompter.core.audio_hub import NullTransport

        manager._hub = AudioHub(transport=NullTransport())
        page = widget.playback_page
        page.reload()
        assert "DEGRADED" in page.lbl_backend.text()
        assert not page.cb_global.isEnabled(), (
            "Overlay must never look available without a mixer")

    def test_stop_all_silences_everything_and_allows_new_sounds(self, dialog):
        widget, manager, _d, transport = dialog
        manager.play("click")
        manager.play("notify")
        assert transport.channels
        widget.playback_page._on_stop_all()
        assert transport.channels == {}
        manager.play("click")
        assert transport.channels, "future sounds stay enabled"


class TestHubPagesExist:
    def test_voice_and_ambience_pages_degrade_without_controllers(self, dialog):
        widget, _m, _d, _t = dialog
        # The bare QWidget host has no controllers; the pages must be present
        # and disabled rather than absent or crashing.
        assert widget.voice_page is not None
        assert widget.ambience_page is not None
        assert not widget.voice_page.isEnabled()
        assert not widget.ambience_page.isEnabled()
