"""T-1403 RED probe: what does image Copy do TODAY, with no new API?"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath("src"))
sys.path.insert(0, os.path.abspath("tests"))
from PyQt6.QtGui import QColor, QImage
from test_t1339_wrapped_inline_copy import _editor_live, _flush, MD_IMAGE_RE
import tempfile, pathlib

tmp = pathlib.Path(tempfile.mkdtemp())
img = QImage(24, 12, QImage.Format.Format_RGB32); img.fill(QColor("red"))
p = tmp / "clipboard_20261001_212737_5579abbc.png"; img.save(str(p))

for label, text in (
    ("A bare            ", f"![]({p})"),
    ("B prefix only     ", f"prefix ![]({p})"),
    ("C trailing prose  ", f"![]({p}) - trailing prose after the image"),
    ("D both (SCREENSHOT)", f"prefix ![]({p}) - trailing prose after the image"),
):
    ed, owner, hl = _editor_live(tmp, text, width=600)
    try:
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        ed._update_inline_hover(pill.center())
        c = ed._hover_inline_copy_rect
        inside = pill.contains(c)
        print(f"{label} pill={pill.left():>4},{pill.top():>3} {pill.width():>4}x{pill.height():>2}"
              f"  copy={c.left():>4},{c.top():>3} {c.width():>3}x{c.height():>2}"
              f"  offset_right={pill.right()-c.right():>5}"
              f"  dcy={abs(c.center().y()-pill.center().y()):>2}"
              f"  INSIDE={inside}")
    finally:
        ed.close(); ed.deleteLater(); owner.preview_combo.deleteLater(); _flush()
