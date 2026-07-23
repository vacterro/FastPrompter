"""The Ctrl+W settings preview must show what Ctrl+W actually does.

The old dialog drew its examples from a fixed table of strings, so it went
on promising "\\n\\n---" long after the spacing had been changed and nobody
could tell from the screen. core/ctrlw.simulate() replaced that table, and
this file is what keeps it honest: it runs the real editor over the real
sample documents and demands the same text back, caret included.

Standalone run (tests/ stubs PyQt6 out globally):

    uv run pytest tests_smoke/test_ctrlw_preview.py -q
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
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_ctrlw_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"cw_{profile_id}.db")
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


def _run_scenario(w, sid, use_div, use_bul, before, after, bullet):
    """Press Ctrl+W on that scenario's sample and return the document."""
    w.data["ctrlw_bullet_char"] = bullet
    w.data["ctrlw_blanks_before"] = str(before)
    w.data["ctrlw_blanks_after"] = str(after)
    for other, _t, _w in SCENES:
        # the per-scene override must be off, or the globals above are ignored
        w.data[f"ctrlw_{other}_before"] = ""
        w.data[f"ctrlw_{other}_after"] = ""
    w.data[f"ctrlw_{sid}_divider"] = "True" if use_div else "False"
    w.data[f"ctrlw_{sid}_bullet"] = "True" if use_bul else "False"

    src = SAMPLE[sid]
    head, _, _tail = src.partition(CURSOR)
    w.text_area.setPlainText(src.replace(CURSOR, ""))
    cur = w.text_area.textCursor()
    cur.setPosition(len(head))
    w.text_area.setTextCursor(cur)

    w.insert_add_line()

    text = w.text_area.toPlainText()
    pos = w.text_area.textCursor().position()
    return text[:pos] + CURSOR + text[pos:]


@pytest.mark.parametrize("sid", [s[0] for s in SCENES])
def test_preview_matches_the_editor_defaults(win, sid):
    """Shipped defaults: preview text == inserted text, caret and all."""
    use_div = sid != "s5"
    use_bul = sid != "s3"
    _before, expected = simulate(sid, use_div, use_bul, 2, 3, "•")
    actual = _run_scenario(win, sid, use_div, use_bul, 2, 3, "•")
    assert actual == expected


@pytest.mark.parametrize("sid", [s[0] for s in SCENES])
def test_preview_follows_changed_spacing(win, sid):
    """0 above / 1 below - the setting the stale table used to ignore."""
    _before, expected = simulate(sid, True, True, 0, 1, "-")
    actual = _run_scenario(win, sid, True, True, 0, 1, "-")
    assert actual == expected


@pytest.mark.parametrize("doc,expected", [
    # the caret is written as | and removed before typing
    ("a thought|", "s1"),
    ("|", "s2"),
    ("first\n|\nsecond", "s3"),
    ("one two| three", "s4"),
    ("---\n|", "s5"),
    ("# T\n---\n\n|", "s5"),
    # ── the reported bug: everything below used to come out s5 ──
    # After one Ctrl+W the document IS "---, blanks, bullet", so every line
    # the user then typed on had a rule somewhere above it. s5 swallowed
    # them all and every setting on s1 looked like it did nothing.
    ("---\n\n\n- |", "s1"),
    ("- a\n\n---\n\n\n- b|", "s1"),
    ("# T\n---\n\n- one\n\n---\n\n\n- two|", "s1"),
    ("---\nlast point|", "s1"),
])
def test_the_scenario_follows_the_caret_not_the_history(win, doc, expected):
    head, _, _tail = doc.partition("|")
    win.text_area.setPlainText(doc.replace("|", ""))
    cur = win.text_area.textCursor()
    cur.setPosition(len(head))
    win.text_area.setTextCursor(cur)
    assert win.ctrlw_scenario(cur) == expected, doc


def test_editor_and_preview_share_one_template():
    """Not two implementations that happen to agree today."""
    import inspect

    from fastprompter.ui import formatting_mixin

    src = inspect.getsource(formatting_mixin.insert_add_line
                            if hasattr(formatting_mixin, "insert_add_line")
                            else formatting_mixin.FormattingMixin.insert_add_line)
    assert "build_template(" in src
    assert formatting_mixin.build_template is build_template


def test_s2_has_no_leading_gap():
    """Nothing above an empty document to be separated from."""
    assert build_template("s2", True, True, 4, 1, "•").startswith("---")
    assert build_template("s1", True, True, 4, 1, "•").startswith("\n\n\n\n---")


def test_divider_between_blocks_keeps_its_trailing_gap():
    """s3 with no bullet still needs the gap, or the next block sticks to ---."""
    tpl = build_template("s3", True, False, 2, 3, "•")
    assert tpl.endswith("---\n\n\n")
