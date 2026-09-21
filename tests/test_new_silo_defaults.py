"""Appends C + D — clipboard-into-new-silo and random-color-on-new.

Both touch the SAME explicit NEW lifecycle, so this module also carries the
combined regression: both toggles on, one NEW -> one silo owning the
clipboard text AND exactly one palette color.

All fixtures synthetic; randomness is patched, never sampled live.
"""

import os
import sys
import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QApplication.instance() or QApplication(sys.argv)
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_new_defaults_")

from _qt_retire import retire

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

CLIP_TEXT = "  keep\nmy whitespace  \n"

PALETTE = ["#ff4444", "#ffaa00", "#ffff00", "#00ff00", "#00ffff", ""]


@pytest.fixture(autouse=True)
def _own_the_clipboard():
    """T-1260: ``_set_clipboard`` writes to the MACHINE-GLOBAL clipboard.

    Without a restore this module left ``CLIP_TEXT`` (or "") on the operator's
    real clipboard for the rest of the process AND for the rest of their
    desktop session. The shipped profile defaults ``new_silo_paste_clipboard``
    to True, so any later test that creates an empty silo and asserts it is
    blank inherited whatever this module last wrote. Snapshot and put it back;
    the tests below still own the clipboard for their own duration.
    """
    clip = _app.clipboard()
    before = clip.text()
    try:
        yield
    finally:
        clip.setText(before)


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / f"t_{profile_id}.db"))
    for name in ("setup_single_instance_server", "register_all_hotkeys",
                 "unregister_all_hotkeys"):
        monkeypatch.setattr(FastPrompter, name, lambda self: None)
    w = FastPrompter()
    w.data["silo_color_palette"] = PALETTE
    yield w
    w._wait_for_undo_saves()
    w._logical_finalized = True
    w.tray_icon.hide()
    w.close()
    # T-1286: receiver-scoped retirement, not a bare deleteLater(). A posted
    # DeferredDelete is never delivered without an event loop, so a
    # function-scoped window here stayed alive until some LATER test pumped
    # one -- and QTest.qWait() (used by tests/test_timer_fire.py's watchdog)
    # delivers the whole accumulated backlog in a single batch, which stalled
    # that test's real 50 ms QTimer past its 5 s watchdog.
    retire(w)


def _set_clipboard(w, text):
    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText(text)


def _toggle(w, key, on):
    w.data[key] = "True" if on else "False"


# ---------------------------------------------------------------------------
# Append C — clipboard
# ---------------------------------------------------------------------------

def test_clipboard_toggle_off_keeps_new_blank(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", False)
    win.select_empty_silo(insertion="top")
    assert win.data["temp_presets"][win.active_temp_slot] == ""


def test_clipboard_toggle_on_seeds_top_new(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    win.select_empty_silo(insertion="top")
    assert win.data["temp_presets"][win.active_temp_slot] == CLIP_TEXT


def test_clipboard_toggle_on_empty_clipboard_keeps_new_blank(win):
    _set_clipboard(win, "")
    _toggle(win, "new_silo_paste_clipboard", True)
    win.select_empty_silo(insertion="top")
    assert win.data["temp_presets"][win.active_temp_slot] == ""


def test_clipboard_relative_above_and_below_new(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    win.select_empty_silo(insertion="top")            # slot 0 owns the text
    assert win.data["temp_presets"][0] == CLIP_TEXT
    win.active_temp_slot = 0
    win.select_empty_silo(insertion="above")          # new slot 0
    win.select_empty_silo(insertion="below")
    assert win.data["temp_presets"][1] == CLIP_TEXT


def test_clipboard_bottom_new(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    win.append_empty_silo()
    assert win.data["temp_presets"][-1] == CLIP_TEXT


def test_capacity_refused_new_mutates_nothing(win, monkeypatch):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    monkeypatch.setattr(win, "_silo_at_capacity", lambda arc: True)
    before = list(win.data["temp_presets"])
    win.select_empty_silo(insertion="top")
    assert win.data["temp_presets"] == before


def test_failed_durable_undo_new_mutates_nothing(win, monkeypatch):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    monkeypatch.setattr(win, "_durable_undo_or_refuse", lambda name: False)
    before = list(win.data["temp_presets"])
    win.select_empty_silo(insertion="top")
    assert win.data["temp_presets"] == before


def test_preset_new_keeps_template_not_clipboard(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    win._new_silo_with_text("TEMPLATE BODY")
    slot = win.active_temp_slot
    assert win.data["temp_presets"][slot] == "TEMPLATE BODY"


def test_clipboard_does_not_mutate_system_clipboard(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    win.select_empty_silo(insertion="top")
    from PyQt6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == CLIP_TEXT


def test_child_new_seeds_clipboard(win):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    if len(win.data["temp_presets"]) < 1:
        win.data["temp_presets"].append("parent")
    win.new_child_silo(0)
    assert win.data["temp_presets"][win.active_temp_slot] == CLIP_TEXT


# ---------------------------------------------------------------------------
# Append D — random color
# ---------------------------------------------------------------------------

def test_color_toggle_off_assigns_nothing(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", False)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win.select_empty_silo(insertion="top")
    assert win.data["silo_colors"].get(str(win.active_temp_slot), "") == ""


def test_color_boxes_disabled_means_no_assignment(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", False)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win.select_empty_silo(insertion="top")
    assert win.data["silo_colors"].get(str(win.active_temp_slot), "") == ""
    # and the automation must NOT silently re-enable the color boxes
    assert win.data["silo_color_box"] == "False"


def test_color_assigned_when_enabled(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[3])
    win.select_empty_silo(insertion="top")
    assert (win.data["silo_colors"][str(win.active_temp_slot)]
            == "#00ff00")


def test_color_written_after_insert_remap(win, monkeypatch):
    """Insert ABOVE slot 2: everything >= 0 shifts +1 and the color must
    land on the NEW silo's final index, with neighbors riding along."""
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    while len(win.data["temp_presets"]) < 3:
        win.data["temp_presets"].append(f"silo {len(win.data['temp_presets'])}")
    win.data["silo_colors"].clear()
    win.data["silo_colors"]["0"] = "#111111"
    win.data["silo_colors"]["2"] = "#222222"
    monkeypatch.setattr("random.choice", lambda seq: "#NEWCOLOR")
    win.active_temp_slot = 2
    win.select_empty_silo(insertion="above")      # new silo becomes slot 2
    colors = win.data["silo_colors"]
    assert colors["0"] == "#111111"               # neighbor kept its identity
    assert colors["3"] == "#222222"               # old slot 2 shifted to 3
    assert colors["2"] == "#NEWCOLOR"             # the NEW silo


def test_color_bottom_new(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win.append_empty_silo()
    assert win.data["silo_colors"][str(len(win.data["temp_presets"]) - 1)]


def test_capacity_refused_new_assigns_no_color(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    monkeypatch.setattr(win, "_silo_at_capacity", lambda arc: True)
    before = dict(win.data["silo_colors"])
    win.select_empty_silo(insertion="top")
    assert win.data["silo_colors"] == before


def test_preset_new_receives_color_but_not_clipboard(win, monkeypatch):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win._new_silo_with_text("TEMPLATE BODY")
    slot = win.active_temp_slot
    assert win.data["temp_presets"][slot] == "TEMPLATE BODY"
    assert win.data["silo_colors"].get(str(slot)) == "#ff4444"


def test_empty_palette_uses_canonical_fallback(win, monkeypatch):
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    win.data["silo_color_palette"] = ["", "  "]
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win.select_empty_silo(insertion="top")
    assert win.data["silo_colors"][str(win.active_temp_slot)] == "#ff4444"


def test_archive_new_gets_no_defaults(win, monkeypatch):
    _toggle(win, "new_silo_paste_clipboard", True)
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    win.active_is_archive = True
    try:
        win.select_empty_silo(insertion="top")
    finally:
        win.active_is_archive = False
    assert win.data["silo_colors"] == {}


# ---------------------------------------------------------------------------
# combined regression: both toggles on one NEW lifecycle
# ---------------------------------------------------------------------------

def test_combined_new_owns_clipboard_text_and_one_color(win, monkeypatch):
    _set_clipboard(win, CLIP_TEXT)
    _toggle(win, "new_silo_paste_clipboard", True)
    _toggle(win, "silo_random_color_on_new", True)
    _toggle(win, "silo_color_box", True)
    monkeypatch.setattr("random.choice", lambda seq: seq[1])
    before = len(win.data["temp_presets"])
    win.select_empty_silo(insertion="top")
    slot = win.active_temp_slot
    # exactly one new silo, active, owning BOTH artifacts
    assert len(win.data["temp_presets"]) == before + 1
    assert win.data["temp_presets"][slot] == CLIP_TEXT
    assert win.data["silo_colors"].get(str(slot)) == "#ffaa00"
    assert win.data["temp_presets"].count(CLIP_TEXT) == 1
    # save/reload preserves both
    doc = win.silo_docs[slot]
    assert doc.toPlainText() == CLIP_TEXT
    cat = win.get_current_category()
    all_colors = win.data["silo_colors_all"]
    assert all_colors[cat][str(slot)] == "#ffaa00"


def test_settings_persist_and_profile_reload(win):
    _toggle(win, "new_silo_paste_clipboard", True)
    _toggle(win, "silo_random_color_on_new", True)
    assert win.data["new_silo_paste_clipboard"] == "True"
    assert win.data["silo_random_color_on_new"] == "True"
    # the profile-apply path must recognize the new keys as widget-backed
    win.data.update({"new_silo_paste_clipboard": "False",
                     "silo_random_color_on_new": "False"})
    win._apply_profile_runtime_state()
    assert win.data["new_silo_paste_clipboard"] == "False"
