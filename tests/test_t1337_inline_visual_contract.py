"""T-1337: inline image/link visual contract.

Regression discovered after T-1335: in a long Live Preview document
(501..2000 blocks) the MarkdownHighlighter degrades and DROPS the two
image-collapse rules, so the raw ``![](file:///...)`` markup stays visible,
while VaultTextEdit.paintEvent still paints an image pill on top of it. Raw
path fragments and a pill coexist -- a corrupted hybrid.

This proves the STRUCTURAL contract, not that a regex matches:

  * Live Preview conceals the raw image token whether small OR degraded.
  * A pill is eligible to paint ONLY while the token is being concealed.
  * Source View / a detached (huge) highlighter never paints a pill over
    raw markup.
  * Copy controls are hover-only: none paint at idle; exactly one appears
    for the hovered link/image; leaving clears it; the target->Copy bridge
    keeps it alive.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtGui import QTextDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402

from fastprompter.ui.editor import MD_IMAGE_RE, VaultTextEdit  # noqa: E402
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter  # noqa: E402

_APP = QApplication.instance() or QApplication([])

# A long, real-shaped local image target like the operator's.
_IMG = ("![](file:///V:/___VAC/_PIC/_Clipboard_stuff/"
        "clipboard_20260928_111426_corrupted_shape.png)")


def _flush():
    for _ in range(6):
        _APP.processEvents()


def _image_markup_concealed(doc, block_idx):
    """Is the raw image markup on this block visually concealed?

    Concealment is applied as a char format with a fully transparent
    foreground (alpha 0) over the ``![](...)`` range -- the same trick the
    ``---`` rule uses. Read the LAYOUT formats, where setFormat lands."""
    blk = doc.findBlockByNumber(block_idx)
    if not blk.isValid():
        return False
    for f in blk.layout().formats():
        if f.format.foreground().color().alpha() == 0:
            return True
    return False


# ------------------------------------------------------- highlighter conceal


def test_small_live_preview_conceals_image_markup():
    doc = QTextDocument()
    doc.setPlainText(f"prose\n{_IMG}\nmore prose")
    hl = MarkdownHighlighter(doc)
    hl.set_degraded(False)
    hl.rehighlight()
    _flush()
    assert _image_markup_concealed(doc, 1)


def test_degraded_live_preview_still_conceals_image_markup():
    """THE critical oracle: 600+ blocks, degraded, image STILL concealed."""
    lines = ["bullet prose", _IMG, "more prose"] + [
        f"line {i}" for i in range(600)]
    doc = QTextDocument()
    doc.setPlainText("\n".join(lines))
    hl = MarkdownHighlighter(doc)
    hl.set_degraded(True)          # the >500-block path
    hl.rehighlight()
    _flush()
    assert _image_markup_concealed(doc, 1), (
        "degraded Live Preview dropped image concealment -- raw path would "
        "show behind the pill")


def test_huge_highlighter_uses_essential_only_no_image_conceal():
    lines = ["prose", _IMG] + [f"l {i}" for i in range(50)]
    doc = QTextDocument()
    doc.setPlainText("\n".join(lines))
    hl = MarkdownHighlighter(doc)
    hl.set_huge(True)
    hl.rehighlight()
    _flush()
    # huge = essential rules only; images are NOT concealed, and the shared
    # capability decision must therefore report conceal OFF so no pill paints.
    assert hl.conceals_images() is False


def test_conceals_images_true_when_attached_and_degraded():
    doc = QTextDocument()
    doc.setPlainText(_IMG)
    hl = MarkdownHighlighter(doc)
    hl.set_degraded(True)
    assert hl.conceals_images() is True
    hl.set_degraded(False)
    assert hl.conceals_images() is True


# ------------------------------------------------- editor paint eligibility


class _Owner:
    highlighter = None
    _LARGE_DOC_THRESHOLD = 500_000
    _LARGE_DOC_BLOCK_THRESHOLD = 2000
    cb_ctrl_c = None

    def __init__(self, tmp_path):
        self.data = {"sound_ui": "False", "sound_typewriter": "False",
                     "auto_bullet": "False", "bullet_double_line": "False",
                     "ctrl_c_closes": "False", "image_paste_style": "pill",
                     "hover_line": "False"}
        self._current_lang = "EN"
        self._tmp = tmp_path
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("Live Preview", "Live Preview")
        self.preview_combo.addItem("Source View", "Source View")

    def _silo_folder_dir(self, *_a):
        return str(self._tmp)

    def play_tick_sound(self):
        pass

    def themed_cursor(self, shape):
        from PyQt6.QtGui import QCursor
        return QCursor(shape)


def _png(tmp_path):
    from PyQt6.QtGui import QColor, QImage
    img = QImage(24, 12, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    p = tmp_path / "shot.png"
    assert img.save(str(p))
    return str(p)


def _editor_live(tmp_path, text):
    owner = _Owner(tmp_path)
    owner.preview_combo.setCurrentIndex(0)  # Live Preview
    ed = VaultTextEdit(owner)
    ed.resize(900, 600)
    ed.setPlainText(text)
    # attach a real highlighter to THIS document, as production does
    hl = MarkdownHighlighter(ed.document())
    hl.set_degraded(False)
    owner.highlighter = hl
    hl.rehighlight()
    ed.show()
    _flush()
    return ed, owner, hl


def test_pills_eligible_in_live_preview(tmp_path):
    ed, owner, hl = _editor_live(tmp_path, f"![]({_png(tmp_path)})")
    try:
        assert ed._image_pills_enabled() is True
    finally:
        ed.close()


def test_pills_not_eligible_in_source_view(tmp_path):
    ed, owner, hl = _editor_live(tmp_path, f"![]({_png(tmp_path)})")
    try:
        owner.preview_combo.setCurrentIndex(1)  # Source View
        assert ed._image_pills_enabled() is False
    finally:
        ed.close()


def test_pills_not_eligible_when_highlighter_detached(tmp_path):
    """Huge document: highlighter is detached, so no pill may paint over
    honest raw markup."""
    ed, owner, hl = _editor_live(tmp_path, f"![]({_png(tmp_path)})")
    try:
        hl.setDocument(None)       # simulate the huge-doc detach
        assert ed._image_pills_enabled() is False
    finally:
        ed.close()


# ------------------------------------------------------- hover-only Copy


def test_no_copy_control_at_idle(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path, f"[label](https://example.com) and ![]({_png(tmp_path)})")
    try:
        assert ed._hover_inline_kind is None
        # nothing painted means no clickable copy target either
        assert ed._hover_inline_copy_rect is None
    finally:
        ed.close()


def test_hovering_a_link_reveals_one_copy_of_the_url(tmp_path):
    url = "https://example.com/path"
    ed, owner, hl = _editor_live(tmp_path, f"see [label]({url}) here")
    try:
        block = ed.document().findBlockByNumber(0)
        from PyQt6.QtGui import QTextCursor
        cur = QTextCursor(block)
        cur.setPosition(block.position() + block.text().index("label"))
        pos = ed.cursorRect(cur).center()
        ed._update_inline_hover(pos)
        assert ed._hover_inline_kind == "link"
        assert ed._hover_inline_target == url
        assert ed._hover_inline_copy_rect is not None
    finally:
        ed.close()


def test_leaving_clears_the_copy_control(tmp_path):
    url = "https://example.com/x"
    ed, owner, hl = _editor_live(tmp_path, f"[l]({url})")
    try:
        block = ed.document().findBlockByNumber(0)
        from PyQt6.QtGui import QTextCursor
        cur = QTextCursor(block)
        cur.setPosition(block.position() + 1)
        ed._update_inline_hover(ed.cursorRect(cur).center())
        assert ed._hover_inline_kind == "link"
        ed._update_inline_hover(QPoint(5, 590))   # far away, empty area
        # T-1349 supersedes the instant kill: the pointer gets ONE bounded
        # grace to cross to a far-placed Copy, and the control is gone as
        # soon as that grace is spent. It is never a permanent hold.
        assert ed._hover_inline_kind == "link"
        assert ed._inline_hover_grace_timer.isActive()
        ed._on_inline_hover_grace_expired()
        assert ed._hover_inline_kind is None
        assert not ed._inline_hover_grace_timer.isActive()
    finally:
        ed.close()


def test_target_to_copy_bridge_keeps_hover_alive(tmp_path):
    url = "https://example.com/y"
    ed, owner, hl = _editor_live(tmp_path, f"[l]({url})")
    try:
        block = ed.document().findBlockByNumber(0)
        from PyQt6.QtGui import QTextCursor
        cur = QTextCursor(block)
        cur.setPosition(block.position() + 1)
        ed._update_inline_hover(ed.cursorRect(cur).center())
        assert ed._hover_inline_kind == "link"
        copy_rect = ed._hover_inline_copy_rect
        # move the pointer onto the Copy control itself -> stays alive
        ed._update_inline_hover(copy_rect.center())
        assert ed._hover_inline_kind == "link"
        assert ed._hover_inline_target == url
    finally:
        ed.close()


def test_hovering_an_image_reveals_copy_bound_to_that_image(tmp_path):
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, f"![]({path})")
    try:
        block = ed.document().findBlockByNumber(0)
        match = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, match)
        ed._update_inline_hover(pill.center())
        assert ed._hover_inline_kind == "image"
        assert os.path.normcase(ed._hover_inline_target) == os.path.normcase(
            os.path.realpath(path))
        assert ed._hover_inline_copy_rect is not None
        assert not pill.intersects(ed._hover_inline_copy_rect)
    finally:
        ed.close()
