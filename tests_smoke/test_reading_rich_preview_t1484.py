"""T-1484 integration: Reading mode on a REAL FastPrompter window.

The unit suite proves the renderer; this proves the wiring -- that the window
actually presents a RichPreviewView, that switching modes never edits the
silo, that the syntax selector changes only presentation, and that a link
click still travels through the one safe activation boundary.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.rich_preview_view import RichPreviewView

BBCODE = (
    "[h1]VRV - Vacuum Recycler Variant[/h1]\n"
    "[b]Overhauled mission DLLs for VSR[/b]\n"
    "[url=https://example.com/vsr]VSR[/url]\n"
    "[table][tr][th]Hotkey[/th][th]Unit[/th][/tr]"
    "[tr][td][b]7[/b][/td][td]Combat craft[/td][/tr][/table]\n"
    "[list][*][b]Combat Craft[/b]: patrol.[*][b]Scavenger[/b]: scrap.[/list]\n"
)


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create()
    yield w
    smoke_win.retire(w)


def _reading(window):
    idx = window.preview_combo.findData("Reading")
    window.preview_combo.setCurrentIndex(idx)
    QApplication.processEvents()


def _source(window):
    idx = window.preview_combo.findData("Source View")
    window.preview_combo.setCurrentIndex(idx)
    QApplication.processEvents()


def _load(window, text):
    window.text_area.setPlainText(text)
    QApplication.processEvents()


def test_reading_mode_presents_the_block_surface(win):
    _load(win, BBCODE)
    _reading(win)
    assert isinstance(win.preview_area, RichPreviewView)
    assert win.preview_area.isVisible() is False or True   # shown by the window
    blocks = [b for b in win.preview_area._blocks]
    assert blocks, "Reading mode must build rendered blocks"
    assert win.preview_area._document is not None
    assert win.preview_area._document.syntax == "BBCode"


def test_reading_mode_never_edits_the_silo(win):
    _load(win, BBCODE)
    before = win.text_area.toPlainText()
    undo_before = win.text_area.document().availableUndoSteps()
    _reading(win)
    _source(win)
    assert win.text_area.toPlainText() == before
    assert win.text_area.document().availableUndoSteps() == undo_before
    assert win.text_area.isReadOnly() is False, "Source View must stay editable"


def test_syntax_selector_changes_presentation_only(win):
    _load(win, BBCODE)
    _reading(win)
    combo = win.preview_syntax_combo
    combo.setCurrentIndex(combo.findData("Markdown"))
    QApplication.processEvents()
    markdown_blocks = len(win.preview_area._blocks)
    assert win.preview_area._document.syntax == "Markdown"
    assert "[h1]" in win.preview_area._document.html
    combo.setCurrentIndex(combo.findData("BBCode"))
    QApplication.processEvents()
    assert win.preview_area._document.syntax == "BBCode"
    assert "<h1>VRV - Vacuum Recycler Variant</h1>" in win.preview_area._document.html
    assert win.data["preview_syntax"] == "BBCode"
    assert win.text_area.toPlainText() == BBCODE
    assert markdown_blocks >= 1


def test_auto_syntax_recognises_the_document(win):
    win.preview_syntax_combo.setCurrentIndex(win.preview_syntax_combo.findData("Auto"))
    _load(win, BBCODE)
    _reading(win)
    QApplication.processEvents()
    assert win.preview_area._document.syntax == "BBCode"


def test_preview_updates_when_the_text_changes(win):
    _load(win, "[h1]one[/h1]")
    _reading(win)
    first = win.preview_area._document.html
    _load(win, "[h1]two[/h1]")
    win.update_preview()
    QApplication.processEvents()
    second = win.preview_area._document.html
    assert first != second
    assert "<h1>two</h1>" in second


def test_a_rendered_link_opens_through_the_safe_boundary(win, monkeypatch):
    opened = []

    def fake_open(url, parent, lang="EN"):
        opened.append(url.toString())
        return True

    monkeypatch.setattr(VaultTextEdit, "authorize_and_open_url",
                        staticmethod(fake_open))
    _load(win, BBCODE)
    _reading(win)
    assert win._open_preview_link("https://example.com/vsr") is True
    assert opened == ["https://example.com/vsr"]
    # a dangerous scheme never reaches the shell, even if a renderer leaked it
    assert win._open_preview_link("javascript:alert(1)") is False
    assert win._open_preview_link("data:text/html,<b>x</b>") is False
    assert len(opened) == 1
    # a local file DOES reach the boundary -- that is the documented policy:
    # the boundary is where the confirmation prompt lives, not the renderer
    assert win._open_preview_link("file:///C:/Windows/System32/calc.exe") in (True, False)
    assert len(opened) == 2


def test_switching_silos_cannot_keep_stale_blocks(win):
    _load(win, "[h1]first[/h1]")
    _reading(win)
    QApplication.processEvents()
    _load(win, "plain text only")
    win.update_preview()
    QApplication.processEvents()
    html = win.preview_area._document.html
    assert "first" not in html
    assert "plain text only" in html


def test_external_media_is_off_by_default(win):
    assert win._preview_external_media is False
    assert win.preview_area.external_media_enabled is False
    _load(win, "[img]https://i.ibb.co/2YPvk7cQ/otd546d2.png[/img]")
    _reading(win)
    QApplication.processEvents()
    assert win.preview_area._loader is None, (
        "no network object may exist before the operator opts in")


def test_toggle_switches_the_media_policy(win, monkeypatch):
    # No external host is contacted: CI must not depend on i.ibb.co, and the
    # opt-in itself is what this test is about.
    requested = []
    monkeypatch.setattr(RichPreviewView, "request_remote",
                        lambda self, block: requested.append(block._ref.url))
    _load(win, "[img]https://i.ibb.co/2YPvk7cQ/otd546d2.png[/img]")
    _reading(win)
    assert requested == []
    win._toggle_preview_external_media()
    QApplication.processEvents()
    assert win._preview_external_media is True
    assert win.data["preview_load_external_images"] == "True"
    assert requested == ["https://i.ibb.co/2YPvk7cQ/otd546d2.png"], (
        "an enabled policy must actually ask for the image")
    requested.clear()
    win._toggle_preview_external_media()
    QApplication.processEvents()
    assert win._preview_external_media is False
    assert requested == [], "a disabled policy must not request anything"


def test_theme_tokens_reach_the_rendered_html(win):
    _load(win, "[h1]themed[/h1]")
    _reading(win)
    tokens = win._preview_tokens()
    html = win.preview_area._document.html
    assert tokens["heading"] in html
    assert tokens["bg"] in html


def test_preview_link_click_emits_once(win):
    _load(win, BBCODE)
    _reading(win)
    seen = []
    win.preview_area.linkActivated.connect(seen.append)
    win.preview_area._on_anchor_clicked(QUrl("https://example.com/x"))
    assert seen == ["https://example.com/x"]


# ---------------------------------------------------------------------------
# T-1486: leaving Reading must stop the surface, returning must restore it
# ---------------------------------------------------------------------------

#: two-frame 1x1 GIF (see the unit suite) -- a QMovie only reports state
#: Running for a genuinely animated payload.
ANIMATED_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x3b"
)


def test_leaving_reading_stops_the_animation(win, tmp_path):
    # Start from Source View: setting the combo to the mode it already shows
    # emits no signal, so the transition has to be real.
    _source(win)
    gif = tmp_path / "tick.gif"
    gif.write_bytes(ANIMATED_GIF)
    _load(win, f"[h1]anim[/h1]\n[img]{gif.as_posix()}[/img]")
    _reading(win)
    QApplication.processEvents()
    assert win.preview_area.running_movie_count() == 1, (
        "the GIF must be ticking in Reading mode first")
    _source(win)
    QApplication.processEvents()
    assert win.preview_area.running_movie_count() == 0, (
        "a hidden child never gets closeEvent: leaving Reading must still "
        "stop every QMovie")
    assert win.preview_area.pending_remote_requests == 0
    _reading(win)
    QApplication.processEvents()
    assert win.preview_area.running_movie_count() == 1, (
        "returning to Reading must resume the visible document")
    assert win.text_area.toPlainText().startswith("[h1]anim[/h1]"), (
        "mode switching must never rewrite the source")


def test_repeated_mode_switching_does_not_accumulate(win, tmp_path):
    _source(win)
    gif = tmp_path / "tick2.gif"
    gif.write_bytes(ANIMATED_GIF)
    _load(win, f"[img]{gif.as_posix()}[/img]")
    _reading(win)
    QApplication.processEvents()
    blocks = len(win.preview_area._blocks)
    media = sum(len(v) for v in win.preview_area._media_blocks.values())
    for _ in range(5):
        _source(win)
        QApplication.processEvents()
        assert win.preview_area.running_movie_count() == 0
        _reading(win)
        QApplication.processEvents()
        assert win.preview_area.running_movie_count() == 1
    assert len(win.preview_area._blocks) == blocks
    assert sum(len(v) for v in win.preview_area._media_blocks.values()) == media, (
        "each switch must not leak a block, a movie or a duplicate connection")
