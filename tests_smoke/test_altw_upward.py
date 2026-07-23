"""Alt+W: Ctrl+W turned around.

Ctrl+W closes the line you are on and opens a fresh point below it. Alt+W
opens the point ABOVE and pushes the existing text down, with the divider
between them. Same parts, same settings page, its own key set (altw_*) so
the two directions can be tuned apart.

Same contract as the Ctrl+W tests: the settings preview is not allowed to
show anything other than what the editor inserts.

    uv run pytest tests_smoke/test_altw_upward.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.ctrlw import CURSOR, SAMPLE, SCENES, build_template, simulate
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_altw_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"a_{profile_id}.db")
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


def _run(win, sid, use_div, use_bul, before, after, bullet):
    win.data["altw_bullet_char"] = bullet
    win.data["altw_blanks_before"] = str(before)
    win.data["altw_blanks_after"] = str(after)
    for other, _t, _w in SCENES:
        win.data[f"altw_{other}_before"] = ""
        win.data[f"altw_{other}_after"] = ""
    win.data[f"altw_{sid}_divider"] = "True" if use_div else "False"
    win.data[f"altw_{sid}_bullet"] = "True" if use_bul else "False"

    src = SAMPLE[sid]
    head, _, _tail = src.partition(CURSOR)
    win.text_area.setPlainText(src.replace(CURSOR, ""))
    cur = win.text_area.textCursor()
    cur.setPosition(len(head))
    win.text_area.setTextCursor(cur)

    win.insert_add_line_up()

    text = win.text_area.toPlainText()
    pos = win.text_area.textCursor().position()
    return text[:pos] + CURSOR + text[pos:]


# ── the block is the same block, reversed ──


def test_the_template_is_the_downward_one_turned_around():
    down = build_template("s1", True, True, 2, 3, "•", upward=False)
    up = build_template("s1", True, True, 2, 3, "•", upward=True)
    assert down == "\n\n---\n\n\n• "
    assert up == "• \n\n\n---\n\n"
    # same parts, same counts - only the order differs
    assert sorted(down.replace("---", "")) == sorted(up.replace("---", ""))


def test_the_point_lands_above_the_existing_text(win):
    out = _run(win, "s1", True, True, 2, 3, "•")
    assert out.startswith("• " + CURSOR), out
    assert out.endswith("a thought"), "the old line must move down, not be eaten"


def test_the_existing_text_is_never_overwritten(win):
    out = _run(win, "s4", True, True, 1, 1, "-")
    assert "one two three" in out.replace(CURSOR, "")


# ── preview equals the editor ──


@pytest.mark.parametrize("sid", [s[0] for s in SCENES])
def test_preview_matches_the_editor_defaults(win, sid):
    use_div = sid != "s5"
    use_bul = sid != "s3"
    _before, expected = simulate(sid, use_div, use_bul, 2, 3, "•", upward=True)
    assert _run(win, sid, use_div, use_bul, 2, 3, "•") == expected


@pytest.mark.parametrize("sid", [s[0] for s in SCENES])
def test_preview_follows_changed_spacing(win, sid):
    _before, expected = simulate(sid, True, True, 0, 1, "-", upward=True)
    assert _run(win, sid, True, True, 0, 1, "-") == expected


# ── the two key sets stay apart ──


def test_alt_w_does_not_read_ctrl_w_settings(win):
    """Two keys sharing one setting would mean neither could be tuned."""
    win.data["ctrlw_s1_divider"] = "False"
    win.data["altw_s1_divider"] = "True"
    out = _run(win, "s1", True, True, 2, 3, "•")
    assert "---" in out
    win.data["ctrlw_s1_divider"] = "True"


def test_the_dialog_reads_and_writes_the_altw_keys(win):
    from fastprompter.ui.ctrlw_settings import CtrlWSettingsDialog

    win.data["altw_bullet_char"] = "▸"
    dlg = CtrlWSettingsDialog(win, prefix="altw", upward=True)
    assert dlg.cb_bullet.currentText() == "▸"
    dlg.cb_bullet.setCurrentText("→")
    dlg.accept()
    assert win.data["altw_bullet_char"] == "→"
    assert win.data.get("ctrlw_bullet_char", "•") != "→", "wrote into Ctrl+W's keys"


def test_the_dialog_titles_say_which_direction(win):
    from fastprompter.ui.ctrlw_settings import CtrlWSettingsDialog

    down = CtrlWSettingsDialog(win)
    up = CtrlWSettingsDialog(win, prefix="altw", upward=True)
    assert down.windowTitle() != up.windowTitle()
    assert up.upward is True and down.upward is False
