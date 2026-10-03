"""Does the PILL itself overlap the trailing prose on the wrapped-image row?

If yes, the overlap is a pre-existing pill-border property (min width 40 x
height 18 on a 14px row) and not something the internal Copy lane introduced.
"""
import os, sys, tempfile, pathlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath("src")); sys.path.insert(0, os.path.abspath("tests"))
from PyQt6.QtGui import QColor, QImage
from test_t1339_wrapped_inline_copy import _editor_live, _flush, _png, MD_IMAGE_RE, _prose_rect
tmp = pathlib.Path(tempfile.mkdtemp())
path = _png(tmp, "clipboard_" + "x"*80 + ".png")
ed, owner, hl = _editor_live(tmp, f"pre ![]({path}) trailing prose", width=280)
try:
    block = ed.document().firstBlock()
    pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
    trailing = _prose_rect(ed, block, "trailing prose")
    ed._update_inline_hover(pill.center())
    lane = ed._hover_inline_copy_rect
    rows = ed._block_visual_rows(block, visible_only=True)
    print("pill    ", pill)
    print("lane    ", lane)
    print("trailing", trailing, "on row(s)", [r["top"] for r in rows])
    print("row height(s)", [r["height"] for r in rows])
    print("PILL intersects trailing prose   :", pill.intersects(trailing))
    print("LANE intersects trailing prose   :", lane.intersects(trailing))
    if pill.intersects(trailing):
        print("  overlap px  x:", max(0, min(pill.right(), trailing.right()) - max(pill.left(), trailing.left())+1),
              " y:", max(0, min(pill.bottom(), trailing.bottom()) - max(pill.top(), trailing.top())+1))
finally:
    ed.close(); ed.deleteLater(); owner.preview_combo.deleteLater(); _flush()
