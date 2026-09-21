"""Regression: a header widget nobody has adopted must not become a window.

Two owners in the header decide visibility from something other than the
window width, and both used to produce a visible widget in a state where the
widget had no business being seen:

* ``lbl_limit_status`` is created in ``init_ui`` but parented by the LAZY
  settings panel, so before that panel exists ``setVisible(True)`` promoted a
  parentless QLabel to a top-level window — a floating strip reading
  "4/4 accounts OK", re-shown once a second by the date timer.
* ``btn_project_folder`` / ``btn_project_run`` belong to silos that carry a
  folder or an executable, but they are also in the density tier lists, so
  every resize/theme pass showed both for silos that have neither.

    uv run pytest tests_smoke/test_orphan_widget_visibility.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_orphan_")


@pytest.fixture
def win(smoke_win):
    w = smoke_win.create(show=True, size=(1400, 700))
    yield w
    smoke_win.retire(w)


def _strays():
    return [w for w in _app.topLevelWidgets()
            if w.isVisible() and not isinstance(w, FastPrompter)]


def test_limit_status_label_never_becomes_a_window(win):
    """The account-count caption belongs to the lazy settings panel alone."""
    assert not getattr(win, "_settings_built", False)

    win._update_limit_status()
    _app.processEvents()

    lbl = win.lbl_limit_status
    assert lbl.text(), "the status text is still computed while unparented"
    assert lbl.parentWidget() is None
    assert not lbl.isVisible(), "a parentless label shown = a stray window"
    assert not _strays(), f"stray top-level windows: {_strays()}"


def test_limit_status_label_shows_once_the_panel_owns_it(win):
    win._ensure_settings_built()
    _app.processEvents()
    win._update_limit_status()
    _app.processEvents()

    lbl = win.lbl_limit_status
    assert lbl.parentWidget() is not None
    assert lbl.isVisibleTo(lbl.parentWidget())
    assert not _strays(), f"stray top-level windows: {_strays()}"


def test_density_pass_keeps_project_buttons_hidden_without_paths(win):
    """Width may narrow the header's button set, never widen it past reality."""
    win.data["silo_project_paths"] = {}
    win.data["archive_project_paths"] = {}
    win.active_is_archive = False
    win._update_project_buttons()
    header = win.header_widget
    assert not win.btn_project_folder.isVisibleTo(header)
    assert not win.btn_project_run.isVisibleTo(header)

    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    _app.processEvents()

    assert not win.btn_project_folder.isVisibleTo(header), \
        "density re-showed the folder button for a silo with no folder"
    assert not win.btn_project_run.isVisibleTo(header), \
        "density re-showed the run button for a silo with no executable"


def test_ultra_tier_still_hides_configured_project_buttons(win):
    """The semantic owner applies the ultra rule instead of fighting it."""
    win.data["silo_project_paths"] = {
        str(win.active_temp_slot): {"folder": _tmpdir, "executable": _tmpdir}}
    win.active_is_archive = False
    header = win.header_widget

    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    assert win.btn_project_folder.isVisibleTo(header)

    # the user's responsive policy is the authority: an explicit 'hide' at
    # the small ranges cannot be overruled by the semantic owner re-asserting
    # availability (the defect this test exists for)
    from fastprompter.core.topbar_visibility import (
        default_topbar_visibility,
        normalize_topbar_visibility,
    )
    default_cfg = default_topbar_visibility()
    cfg = normalize_topbar_visibility(default_cfg)
    for token in ("btn_project_folder", "btn_project_run"):
        for rid in ("narrow", "ultra"):
            cfg["items"][token][rid] = "hide"
    win.data["topbar_visibility"] = cfg

    win.resize(600, 700)
    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    assert not win.btn_project_folder.isVisibleTo(header)

    # A silo switch inside the small range must not bring them back.
    win._update_project_buttons()
    assert not win.btn_project_folder.isVisibleTo(header)

    win.data["topbar_visibility"] = default_cfg
    win.resize(1400, 700)
    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    assert win.btn_project_folder.isVisibleTo(header)
