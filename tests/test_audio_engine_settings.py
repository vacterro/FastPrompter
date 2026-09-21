"""T-1242 spec A1-A5 / B1-B11: the engine settings are TRUSTWORTHY.

The user's two defects this wave:

A. Settings -> Problip -> "Open Audio Hub..." did nothing (name mismatch
   ``open_sound_settings`` vs the real ``open_sound_settings_dialog``, and
   ``callable()`` swallowed the miss).

B. "Add silent margins to short sounds" could not be turned OFF: with the
   renderer OFF the pad checkbox sat CHECKED but DISABLED -- permanently on,
   unclickable -- because the pad runtime state was never clamped to render.

These tests pin the fixed contracts.  They use REAL Qt mouse clicks (B10),
because the user's failure was an interactive UI failure.
"""

from __future__ import annotations

import os
import sys

import pytest
from _qt_retire import retire

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.ui.audio_hub_pages import PlaybackPage  # noqa: E402
from fastprompter.ui.problip_settings import ProblipSettingsPage  # noqa: E402
from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def hub_env(tmp_path, monkeypatch):
    _ensure_app()
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir",
                        lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    data: dict = {"sound_ui": "True"}
    manager = SoundManager(host, data)
    manager._hub = AudioHub(transport=FakeMultiChannelTransport())
    yield host, data, manager
    manager.shutdown()
    retire(host)   # T-1260: deliver the destruction, do not just post it


def _click(checkbox):
    """A REAL mouse click on the checkbox (spec B10), not setChecked()."""
    QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton)


class TestEngineToggleRoundtrip:
    """Spec B9: render OFF / pad OFF -> click pad ON -> click pad OFF."""

    def test_pad_roundtrip_through_real_clicks(self, hub_env):
        _host, data, manager = hub_env
        data[SoundManager.DEVICE_RENDER_KEY] = "False"
        data[SoundManager.EDGE_PAD_KEY] = "False"

        dialog = SoundSettingsDialog(_host_placeholder(hub_env), data, manager)
        page: PlaybackPage = dialog.playback_page
        try:
            # Refresh with both OFF -> both checkboxes unchecked.
            page.reload()
            assert not page.cb_render.isChecked()
            assert not page.cb_edge_pad.isChecked()

            # With render OFF the pad checkbox is DISABLED -- a real click is
            # swallowed by Qt, so the user can never turn on a sub-mode of a
            # disabled feature and no stray pad=True can be created here.
            assert not page.cb_edge_pad.isEnabled()
            _click(page.cb_edge_pad)
            assert data[SoundManager.EDGE_PAD_KEY] == "False"
            assert not page.cb_edge_pad.isChecked()

            # Enable render: pad becomes clickable (still unchecked).
            _click(page.cb_render)
            assert data[SoundManager.DEVICE_RENDER_KEY] == "True"
            assert page.cb_edge_pad.isEnabled()
            assert not page.cb_edge_pad.isChecked()

            # Click pad ON: persists True immediately, UI truthful.
            _click(page.cb_edge_pad)
            assert data[SoundManager.EDGE_PAD_KEY] == "True"
            assert page.cb_edge_pad.isChecked()
            assert manager.apply_device_render_setting() == (True, True)

            # Click pad OFF: persists False immediately (the user's defect:
            # it used to bounce back ON).
            _click(page.cb_edge_pad)
            assert data[SoundManager.EDGE_PAD_KEY] == "False"
            assert not page.cb_edge_pad.isChecked()
            assert manager.apply_device_render_setting() == (True, False)
        finally:
            dialog.deleteLater()

    def test_refresh_does_not_rebound_the_checkbox(self, hub_env):
        _host, data, manager = hub_env
        data[SoundManager.DEVICE_RENDER_KEY] = "True"
        data[SoundManager.EDGE_PAD_KEY] = "False"

        dialog = SoundSettingsDialog(_host_placeholder(hub_env), data, manager)
        page: PlaybackPage = dialog.playback_page
        try:
            page.reload()
            assert page.cb_edge_pad.isChecked() is False
            # A refresh re-reads the model; it must NOT write pad back ON.
            page.reload()
            page.reload()
            assert data[SoundManager.EDGE_PAD_KEY] == "False"
            assert not page.cb_edge_pad.isChecked()
        finally:
            dialog.deleteLater()

    def test_dialog_reopen_preserves_state(self, hub_env):
        host, data, manager = hub_env
        data[SoundManager.DEVICE_RENDER_KEY] = "True"
        data[SoundManager.EDGE_PAD_KEY] = "False"

        dialog = SoundSettingsDialog(host, data, manager)
        page: PlaybackPage = dialog.playback_page
        QTest.mouseClick(page.cb_edge_pad, Qt.MouseButton.LeftButton)
        dialog.done(0)
        dialog.deleteLater()

        # A fresh dialog object (what "close and reopen the Audio Hub" does)
        # reads the SAME persisted data.
        dialog2 = SoundSettingsDialog(host, data, manager)
        try:
            assert dialog2.playback_page.cb_edge_pad.isChecked()
            assert data[SoundManager.EDGE_PAD_KEY] == "True"
        finally:
            dialog2.deleteLater()

    def test_stray_pad_true_with_render_off_is_clamped_truthfully(self, hub_env):
        """Spec B5/B8: a persisted pad=True without render cannot survive as
        a checked-but-disabled checkbox; the UI shows the clamp."""
        _host, data, manager = hub_env
        data[SoundManager.DEVICE_RENDER_KEY] = "False"
        data[SoundManager.EDGE_PAD_KEY] = "True"

        dialog = SoundSettingsDialog(_host_placeholder(hub_env), data, manager)
        page: PlaybackPage = dialog.playback_page
        try:
            assert manager.apply_device_render_setting() == (False, False)
            assert not page.cb_render.isChecked()
            assert not page.cb_edge_pad.isChecked()
            assert not page.cb_edge_pad.isEnabled()
            assert data[SoundManager.EDGE_PAD_KEY] == "False"
        finally:
            dialog.deleteLater()


class TestEngineStateLabel:
    """Spec B8: the engine line shows the ACTUAL active policy."""

    def test_engine_line_matches_runtime(self, hub_env):
        _host, data, manager = hub_env
        data[SoundManager.DEVICE_RENDER_KEY] = "True"
        data[SoundManager.EDGE_PAD_KEY] = "True"

        dialog = SoundSettingsDialog(_host_placeholder(hub_env), data, manager)
        try:
            text = dialog.playback_page.lbl_engine_state.text()
            assert "Pre-render: ON" in text
            assert "Silent margins: ON" in text
        finally:
            dialog.deleteLater()

    def test_engine_line_shows_off_when_raw(self, hub_env):
        _host, data, manager = hub_env
        dialog = SoundSettingsDialog(_host_placeholder(hub_env), data, manager)
        try:
            text = dialog.playback_page.lbl_engine_state.text()
            assert "Pre-render: OFF" in text
            assert "Silent margins: OFF" in text
        finally:
            dialog.deleteLater()


class TestOpenAudioHubLifecycle:
    """Spec A1-A4: the Problip button opens THE dialog, once."""

    @staticmethod
    def _host_with_opener(host, calls):
        host.open_sound_settings_dialog = (
            lambda: calls.append("open") or SoundSettingsDialog.open_canonical(
                host, host._engine_data, host._engine_manager))
        return host

    def test_button_calls_the_canonical_opener(self, hub_env):
        host, data, manager = hub_env
        calls: list = []
        host._engine_data = data
        host._engine_manager = manager

        def opener():
            calls.append("open")
            return SoundSettingsDialog.open_canonical(host, data, manager)

        host.open_sound_settings_dialog = opener
        from fastprompter.core.problip import ProblipState  # noqa: F401

        controller = type("C", (), {})()
        controller.settings = type("S", (), {})()
        controller.settings.interval_mode = "random_4_7"
        controller.settings.manual_from_seconds = 4
        controller.settings.manual_to_seconds = 7
        controller.settings.selected_sound_ids = ["blip01"]
        controller.settings.volume_percent = 50
        controller.settings.playback_mode = "inherit"
        controller.settings.show_counter = True
        controller.settings.blip_glow_enabled = False
        controller.settings.windows_autostart = False
        controller.update_settings = lambda **kw: None
        controller.state = ProblipState.STOPPED
        controller.is_running = lambda: False
        controller.error = ""
        from fastprompter.core.problip_store import StatsSnapshot
        from fastprompter.sound.problip.catalog import SoundPoolStatus

        controller.stats = lambda: StatsSnapshot()
        controller.pool_status = lambda: SoundPoolStatus(
            selected_ids=("blip01",), playable_ids=("blip01",))
        controller._sound_manager = manager

        class _Sig:
            def connect(self, *_a, **_kw):
                pass

        controller.stateChanged = _Sig()
        controller.statsChanged = _Sig()
        controller.settingsChanged = _Sig()
        controller.errorChanged = _Sig()
        controller.cuePlayed = _Sig()

        page = ProblipSettingsPage(host, controller, "EN")
        try:
            page.btn_audio_hub.click()
            assert calls == ["open"]
            page.btn_audio_hub.click()
            page.btn_audio_hub.click()
            # Repeated opens reuse ONE canonical dialog instance.
            assert calls == ["open", "open", "open"]
            live = SoundSettingsDialog._LAST_INSTANCE
            assert live is not None
            assert live.isVisible()
        finally:
            live = SoundSettingsDialog._LAST_INSTANCE
            if live is not None:
                live.deleteLater()
                SoundSettingsDialog._LAST_INSTANCE = None
            # ProblipSettingsPage is a plain builder (no QWidget), so it has
            # no deleteLater/close; the host panel owns any real widgets.

    def test_missing_opener_is_a_visible_failure_not_silence(self, hub_env):
        host, _data, manager = hub_env

        class _Bare:
            pass  # no open_sound_settings_dialog at all

        controller = type("C", (), {})()
        controller._sound_manager = manager

        page = ProblipSettingsPage.__new__(ProblipSettingsPage)
        page.host = _Bare()
        page.controller = controller
        page.lang = "EN"
        from PyQt6.QtWidgets import QLabel

        page.lbl_error = QLabel("")
        page.lbl_error.setVisible(False)

        page._on_open_audio_hub()
        assert page.lbl_error.isVisible()
        assert "opener" in page.lbl_error.text().lower()

    def test_open_canonical_reuses_a_live_dialog(self, hub_env):
        host, data, manager = hub_env
        first = SoundSettingsDialog.open_canonical(host, data, manager)
        try:
            second = SoundSettingsDialog.open_canonical(host, data, manager)
            assert second is first
        finally:
            first.deleteLater()

    def test_destroyed_dialog_can_be_reopened(self, hub_env):
        host, data, manager = hub_env
        first = SoundSettingsDialog.open_canonical(host, data, manager)
        assert SoundSettingsDialog._LAST_INSTANCE is first
        # Destroy WITHOUT done(): deferred deletion kills the C++ object
        # while _LAST_INSTANCE still points at it -- the stale-ref path.
        first.deleteLater()
        QTest.qWait(0)
        second = SoundSettingsDialog.open_canonical(host, data, manager)
        try:
            assert second is not first
            assert second.isVisible()
            # The class reference now tracks the live dialog.
            assert SoundSettingsDialog._LAST_INSTANCE is second
        finally:
            second.deleteLater()


def _host_placeholder(env):
    """The parent widget of the fixture (host itself)."""
    return env[0]
