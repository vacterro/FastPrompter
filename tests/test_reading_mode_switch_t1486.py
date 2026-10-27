"""T-1486: leaving Reading must stop the rich preview through the real switch.

``tests/test_rich_preview_t1484.py`` proves the surface's own lifecycle
(``suspend_media`` / ``resume_media``) works when a caller invokes it. That
cannot catch the defect T-1486 reports, because the defect lives one level up:
``change_preview_mode`` HIDES ``preview_area``, and a hidden child never
receives ``closeEvent``. The only reason a document stops animating on a mode
switch is that the mixin calls ``_suspend_preview_media()`` on the way out and
``_resume_preview_media()`` on the way back in.

So this module drives the REAL ``ThemeMixin.change_preview_mode`` against a REAL
``RichPreviewView``. Deleting either call fails here, while every unit test in
the T-1484 module still passes -- which is exactly the gap being closed.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QComboBox, QTextEdit

from fastprompter.core import rich_preview
from fastprompter.ui.rich_preview_view import RichPreviewView
from fastprompter.ui.theme_mixin import ThemeMixin

#: The same two-frame 1x1 GIF the T-1484 suite uses: Qt reports frameCount == 2
#: only for a genuinely animated payload, so "animating" is measured, not hoped.
ANIMATED_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x3b"
)

MODES = ("Source View", "Live Preview", "Reading")


class _Highlighter:
    """The mixin only calls setDocument(None) / set_degraded on this."""

    def setDocument(self, *_args, **_kwargs):  # noqa: N802 - Qt spelling
        pass

    def set_degraded(self, *_args, **_kwargs):
        pass

    def rehighlight(self):
        pass


class _Host(QObject, ThemeMixin):
    """The smallest owner the real mode switch accepts.

    ``ThemeMixin`` is a plain class whose ``change_preview_mode`` touches only
    ``preview_combo``, ``text_area``, ``preview_area``, ``highlighter``,
    ``_preview_connected``, ``_preview_timer``, ``data``, ``update_preview``,
    ``mark_dirty`` and ``_sync_live_preview_highlighter``. Providing exactly
    those keeps the test on production code instead of on a mock of it.
    """

    def __init__(self):
        QObject.__init__(self)
        self.preview_area = RichPreviewView()
        self.preview_area.resize(240, 320)
        self.preview_area.show()
        self.text_area = QTextEdit()
        self.text_area.show()
        self.preview_combo = QComboBox()
        for mode in MODES:
            self.preview_combo.addItem(mode, mode)
        self.highlighter = _Highlighter()
        self.data = {}
        self._preview_connected = False
        self.rendered = 0
        self.dirty = 0

    # -- collaborators the mixin calls --------------------------------
    def update_preview(self):
        self.rendered += 1

    def mark_dirty(self):
        self.dirty += 1

    def _sync_live_preview_highlighter(self):
        pass

    def _refresh_vision_button(self):
        pass

    # -- helpers -------------------------------------------------------
    def select(self, mode: str) -> None:
        index = self.preview_combo.findData(mode)
        assert index >= 0, mode
        self.preview_combo.setCurrentIndex(index)
        self.change_preview_mode(index)


def _animated_host(tmp_path, qapp):
    path = tmp_path / "tick.gif"
    path.write_bytes(ANIMATED_GIF)
    host = _Host()
    host.preview_area.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    QApplication.processEvents()
    return host


def _teardown(host):
    host.preview_area.shutdown()
    host.preview_area.deleteLater()
    host.text_area.deleteLater()
    QApplication.processEvents()


def test_the_fixture_really_animates_before_the_switch(tmp_path, qapp):
    """Guard the guard: a still document would make every assertion vacuous."""
    host = _animated_host(tmp_path, qapp)
    try:
        assert host.preview_area.running_movie_count() == 1
    finally:
        _teardown(host)


def test_hiding_the_surface_alone_does_not_stop_animation(tmp_path, qapp):
    """Negative control: this is the defect's mechanism, not its fix.

    A hidden child never gets ``closeEvent``, so hiding alone leaves the GIF
    ticking. If this control ever fails, the module has stopped testing the
    thing T-1486 is about.
    """
    host = _animated_host(tmp_path, qapp)
    try:
        host.preview_area.setVisible(False)
        QApplication.processEvents()
        assert host.preview_area.running_movie_count() == 1, (
            "if hiding stopped the animation by itself, the mode switch would "
            "not need _suspend_preview_media at all")
    finally:
        _teardown(host)


@pytest.mark.parametrize("mode", ["Source View", "Live Preview"])
def test_switching_away_from_reading_stops_every_animation(mode, tmp_path, qapp):
    host = _animated_host(tmp_path, qapp)
    try:
        host.preview_area.resume_media()
        QApplication.processEvents()
        assert host.preview_area.running_movie_count() == 1

        host.select(mode)
        QApplication.processEvents()

        assert host.preview_area.isVisible() is False
        assert host.preview_area.running_movie_count() == 0, (
            "leaving Reading must stop the QMovies, not just hide the surface")
    finally:
        _teardown(host)


def test_returning_to_reading_resumes_without_duplicating(tmp_path, qapp):
    host = _animated_host(tmp_path, qapp)
    try:
        blocks = len(host.preview_area._blocks)
        host.select("Source View")
        assert host.preview_area.running_movie_count() == 0

        host.select("Reading")
        QApplication.processEvents()

        assert host.preview_area.isVisible() is True
        assert host.preview_area.running_movie_count() == 1, (
            "the retained payload must replay on return, without disk or network")
        assert len(host.preview_area._blocks) == blocks, (
            "a mode switch must not accumulate blocks")
        assert host.rendered == 1, "Reading renders exactly once per entry"
    finally:
        _teardown(host)


def test_repeated_switching_keeps_one_movie(tmp_path, qapp):
    host = _animated_host(tmp_path, qapp)
    try:
        for _ in range(4):
            host.select("Source View")
            assert host.preview_area.running_movie_count() == 0
            host.select("Reading")
            QApplication.processEvents()
            assert host.preview_area.running_movie_count() == 1
    finally:
        _teardown(host)


def test_the_switch_still_marks_the_profile_dirty(tmp_path, qapp):
    """The suspend/resume wiring must not swallow the mode change itself."""
    host = _animated_host(tmp_path, qapp)
    try:
        before = host.dirty
        host.select("Source View")
        assert host.dirty == before + 1
        assert host.preview_combo.currentData() == "Source View"
    finally:
        _teardown(host)
