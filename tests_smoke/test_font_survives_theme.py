"""The chosen font must survive a theme change, and land everywhere.

Two halves of one report ("Verdana is fighting the font I picked"):

  applying a theme sets an application stylesheet, which makes Qt re-polish
  every widget - the editor and its document came back on the class default
  (Verdana) while data and the app font still said what the user picked;

  QApplication.setFont alone never reached widgets carrying their own
  stylesheet, so the toolbar buttons kept the old family until some later
  theme change happened to re-polish them.

    uv run pytest tests_smoke/test_font_survives_theme.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_font_")

# any family that is definitely not the default, and exists on Windows
PICKED = "Courier New"


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"f_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()


def test_the_editor_keeps_the_picked_font_across_a_theme_change(win):
    win.change_font_family(PICKED)
    assert win.text_area.font().family() == PICKED

    win.change_theme("Amber")
    assert win.text_area.font().family() == PICKED, "theme change stole the font"
    assert win.text_area.document().defaultFont().family() == PICKED


def test_it_survives_several_theme_changes(win):
    win.change_font_family(PICKED)
    for name in ("Default", "Amber", "Default"):
        win.change_theme(name)
        assert win.text_area.font().family() == PICKED, name


def test_a_font_change_reaches_stylesheeted_widgets_immediately(win):
    """Not only after a theme change happens to re-polish them."""
    win.change_theme("Default")
    win.change_font_family(PICKED)
    assert win.btn_new.font().family() == PICKED
    assert win.btn_save.font().family() == PICKED


def test_the_font_the_user_picked_is_what_data_says(win):
    win.change_font_family(PICKED)
    win.change_theme("Amber")
    assert win.data["font_family"] == PICKED
    assert QApplication.font().family() == PICKED
    win.change_theme("Default")
