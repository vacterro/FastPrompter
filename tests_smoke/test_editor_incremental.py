"""T-815 regression: derived block metadata (checkbox/code flags, code-panel
selections, fence-opener cache) must be maintained incrementally on edit, not
by re-walking the whole document on every keystroke.

Ordinary typing in a large plain document must NOT rebuild code-panel
selections; only a fence edit (which can change code-region membership)
should trigger a recompute.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

import fastprompter.ui.editor as editor_mod
from fastprompter.ui.editor import VaultTextEdit


def _stub():
    s = SimpleNamespace()
    s.data = {
        "show_line_numbers": "False",
        "code_auto_gutter": "False",
        "line_heat_minutes": "1440",
        "line_heat_strength": "18",
        "line_heat_palette": "warm",
        "hover_line": "True",
        "hover_line_opacity": "10",
        "hover_line_color": "auto",
    }
    s.highlighter = None

    def _get_custom_colors():
        return {}

    s._get_custom_colors = _get_custom_colors
    return s


def _app():
    return QApplication.instance() or QApplication([])


def test_ordinary_typing_does_not_rebuild_code_selections():
    app = _app()
    ed = VaultTextEdit(_stub())
    calls = {"n": 0}
    orig = ed._code_block_selections
    ed._code_block_selections = lambda doc: (
        calls.__setitem__("n", calls["n"] + 1) or orig(doc))

    ed.setPlainText("\n".join("line %d" % i for i in range(2000)))
    app.processEvents()  # the single attach build runs here

    for _ in range(100):
        ed.insertPlainText("x")
        app.processEvents()

    # exactly one build (the attach); ordinary typing adds none
    assert calls["n"] == 1, \
        f"ordinary typing rebuilt code selections {calls['n'] - 1} extra times"
    assert ed._doc_has_checkbox is False


def test_fence_edit_triggers_rebuild_and_recomputes():
    app = _app()
    ed = VaultTextEdit(_stub())
    ed.setPlainText("```\ncode here\n```")
    app.processEvents()

    calls = {"n": 0}
    orig = ed._code_block_selections
    ed._code_block_selections = lambda doc: (
        calls.__setitem__("n", calls["n"] + 1) or orig(doc))

    # one fence pair already -> 2 fence lines are code panels
    assert len(orig(ed.document())) == 2

    # append a SECOND fence pair (fence-touching edit)
    ed.append("```\nmore code\n```")
    app.processEvents()

    # the fence edit must have triggered a recompute
    assert calls["n"] >= 1, "fence edit did not trigger a selection rebuild"
    # and the new state is correct: 4 fence lines -> 4 panels
    assert len(orig(ed.document())) == 4


def test_ordinary_edit_leaves_opener_cache_intact():
    app = _app()
    ed = VaultTextEdit(_stub())
    ed.setPlainText("plain\nplain\nplain")
    app.processEvents()
    ed._opener_cache = {0}  # simulate a populated cache
    before = ed._opener_cache

    ed.insertPlainText("x")  # plain edit, no fence line
    app.processEvents()

    assert ed._opener_cache is before, \
        "a plain edit must not invalidate the opener cache"
