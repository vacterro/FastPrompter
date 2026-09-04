"""Static Cursor (``static_cursor``): one pointer image for the whole app.

Off by default. On, the arrow must not change into an I-beam over text or a
pointing hand over links/buttons, and the switch must be exactly reversible:
the toggle pushes ONE application override cursor and releases that one, never a
stack of them (a second push no single restore could undo would leave the
pointer frozen for the rest of the session).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.cursor_mixin import CursorMixin


class _Win(CursorMixin):
    """The mixin's whole contract: a data dict and a dirty flag."""

    def __init__(self, **data):
        self.data = dict(data)
        self.dirty = 0

    def mark_dirty(self, *_a, **_k):
        self.dirty += 1


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    # never leak an override into the next test
    while application.overrideCursor() is not None:
        application.restoreOverrideCursor()


def test_off_by_default(app):
    win = _Win()
    assert win.static_cursor_enabled() is False
    win.apply_static_cursor()
    assert app.overrideCursor() is None


def test_on_freezes_the_pointer_app_wide(app):
    win = _Win(static_cursor="True")
    win.apply_static_cursor()
    cursor = app.overrideCursor()
    assert cursor is not None
    assert cursor.shape() == Qt.CursorShape.ArrowCursor


def test_applying_twice_pushes_one_override_only(app):
    win = _Win(static_cursor="True")
    win.apply_static_cursor()
    win.apply_static_cursor()
    win.apply_static_cursor()
    app.restoreOverrideCursor()
    assert app.overrideCursor() is None, \
        "a repeated apply stacked overrides; one restore can never undo them"


def test_toggle_releases_the_override(app):
    win = _Win()
    win.toggle_static_cursor(True)
    assert win.data["static_cursor"] == "True"
    assert app.overrideCursor() is not None
    win.toggle_static_cursor(False)
    assert win.data["static_cursor"] == "False"
    assert app.overrideCursor() is None
    assert win.dirty == 2


def test_releasing_when_never_applied_is_a_no_op(app):
    """A profile switch into static=off must not pop somebody else's cursor."""
    app.setOverrideCursor(Qt.CursorShape.WaitCursor)   # e.g. a busy indicator
    try:
        _Win().apply_static_cursor()
        assert app.overrideCursor().shape() == Qt.CursorShape.WaitCursor
    finally:
        app.restoreOverrideCursor()
