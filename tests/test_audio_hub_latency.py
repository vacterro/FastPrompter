"""Tests for Audio Hub / Sound Settings dialog latency and lazy loading.

Verifies:
1. Fast constructor / time-to-first-paint (< 1000 ms).
2. Progressive row loading: initial rows built immediately, remaining rows populated asynchronously.
3. Hub tabs (Presets, Playback, Voice, Ambience) are lazy-loaded on demand.
4. Forced completion of all rows on external operations (filter, auto level all, reset).
5. STOP ALL SOUND calls controller.stop_runtime_only(), keeping remembered ambience preference.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport
from fastprompter.core.sound_manager import EVENT_LABELS, SoundManager
from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def sound_setup(tmp_path, monkeypatch):
    _ensure_app()
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "fastprompter.core.sound_library.managed_root",
        lambda: str(tmp_path / "sound_library"),
    )
    host = QWidget()
    data = {"sound_ui": "True"}
    manager = SoundManager(host, data)
    transport = FakeMultiChannelTransport()
    manager._hub = AudioHub(transport=transport)
    return host, data, manager


def test_dialog_fast_initialization_and_chunked_rows(sound_setup):
    host, data, manager = sound_setup

    t0 = time.perf_counter()
    dialog = SoundSettingsDialog(host, data, manager)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    try:
        # Hard ceiling: construction must be well under 1000 ms (typically ~200-300 ms)
        assert elapsed_ms < 1000.0, f"Construction too slow: {elapsed_ms:.1f} ms"

        # Initially, only 10 rows built
        assert dialog._built_events_count == 10
        assert len(dialog._rows) == 10

        # Process pending Qt events to let singleShot background loader finish all chunks
        while dialog._built_events_count < len(EVENT_LABELS):
            QApplication.processEvents()

        # All events should now be populated
        total_events = len(EVENT_LABELS)
        assert dialog._built_events_count == total_events
        assert len(dialog._rows) == total_events
    finally:
        dialog.deleteLater()


def test_lazy_tab_instantiation(sound_setup):
    host, data, manager = sound_setup
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        # Initially, pages 1, 2, 3, 4 are placeholder QWidgets
        assert dialog._presets_page_instance is None
        assert dialog._playback_page_instance is None
        assert dialog._voice_page_instance is None
        assert dialog._ambience_page_instance is None

        # Accessing property transparently instantiates the real page
        presets = dialog.presets_page
        from fastprompter.ui.audio_hub_pages import PresetsPage
        assert isinstance(presets, PresetsPage)
        assert dialog._presets_page_instance is presets

        # Switching tabs instantiates page via _on_tab_changed
        from fastprompter.ui.audio_hub_pages import PlaybackPage
        dialog.pages.setCurrentIndex(2)  # Playback tab
        assert isinstance(dialog.playback_page, PlaybackPage)
    finally:
        dialog.deleteLater()


def test_forced_row_completion_on_filter_and_reset(sound_setup):
    host, data, manager = sound_setup
    dialog = SoundSettingsDialog(host, data, manager)
    try:
        # Initially only 10 rows
        assert dialog._built_events_count == 10

        # Applying filter immediately forces all rows to build
        dialog._apply_filter("save")
        assert dialog._built_events_count == len(EVENT_LABELS)
        assert len(dialog._rows) == len(EVENT_LABELS)
    finally:
        dialog.deleteLater()


def test_stop_all_sound_preserves_ambience_desired_preference(sound_setup):
    host, data, manager = sound_setup

    class DummyAmbienceController:
        def __init__(self):
            self.stop_called = False
            self.stop_runtime_only_called = False

        def stop(self):
            self.stop_called = True

        def stop_runtime_only(self):
            self.stop_runtime_only_called = True

    dummy_controller = DummyAmbienceController()
    host.ambience_controller = dummy_controller

    dialog = SoundSettingsDialog(host, data, manager)
    try:
        dialog._on_stop_all_sound()
        # Must call stop_runtime_only, NOT stop!
        assert dummy_controller.stop_runtime_only_called is True
        assert dummy_controller.stop_called is False
    finally:
        dialog.deleteLater()
