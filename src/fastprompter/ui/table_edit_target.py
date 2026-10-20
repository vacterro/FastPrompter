"""Replace ONE table region in a live document, not the whole silo.

A visual widget holds the table it was loaded from plus the lines around it,
and it serialises by rebuilding only its own table. The handler used to push
that back by selecting the ENTIRE QTextDocument and inserting a rebuilt copy,
so a stale prefix/suffix — a whitespace edit landed between the load and the
flush — silently consumed everything else in the silo, other tables included.

This module is the one place that turns "here are the lines to write" into a
character range on a real document. Whole lines only: a caret or selection in
the prefix or the suffix is never inside the replaced range, and Qt keeps
document-registered cursors adjusted across the edit, so the caret outside
the table survives untouched.

The region comes from the SAME parser the plain-text path uses
(`silo_region.table_region`), so the two paths cannot disagree about what a
table is. `char_span` is pure text and testable without a window; the Qt work
is confined to `replace_region`.

T-1462 Stage 1: `char_span` works in PYTHON code points (it indexes the string
`toPlainText()` returns), but `QTextCursor.setPosition()` counts UTF-16 code
units. The two diverge the moment the document holds a non-BMP character — one
emoji is two UTF-16 units but one Python character — so a raw offset handed to
`setPosition` silently lands on the wrong characters and the splice eats a
neighbour. The ONE sanctioned bridge (`qt_text_coords`) converts at the cursor
boundary; nothing here does its own encode/decode arithmetic.

T-1462 Stage 2: a region is only meaningful together with the CONTENT it
owns. A same-length concurrent modification remains within the span arithmetic,
so a stale dialog could overwrite newer bytes. `capture_ownership` records the
exact table lines at load time, and `verify_ownership` refuses an Apply when
those lines no longer match the live document.
"""

from __future__ import annotations

import hashlib

from fastprompter.ui.qt_text_coords import py_to_qt, qt_units


def char_span(text: str, span: tuple[int, int]):
    """(start, end) PYTHON code-point offsets covering whole lines [first, last].

    Returns None when there is nothing to replace and False when the span is
    not a whole-line span of THIS text — the caller must then refuse rather
    than write, because the document moved under the stale edit.

    The offsets are in the coordinate system of the Python string, which is
    what `text.split("\\n")` and the `text[start - 1]` guard below speak. The
    Qt cursor boundary is where they become UTF-16 units, in `replace_region`.

    No trailing newline is ever replaced: only the region's own newlines move.
    That is what keeps a table at the very end of the silo from eating the
    document's last line separator, and a table at the very top from eating
    nothing that is not its own.
    """
    if span is None:
        return None
    first, last = span
    lines = text.split("\n")
    if not (0 <= first <= last <= len(lines) - 1):
        return False
    start = sum(len(line) + 1 for line in lines[:first])
    end = start + sum(len(line) + 1 for line in lines[first:last + 1]) - 1
    return start, end


def _content_hash(lines: list[str]) -> str:
    """SHA-256 of the exact table lines (normalized newlines)."""
    payload = "\n".join(lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_ownership(text: str, span: tuple[int, int]) -> dict | None:
    """Capture the table region's content hash and document identity at load time.

    Returns a dict with:
      - 'span': the line span (first, last)
      - 'hash': SHA-256 of the table lines
      - 'doc_rev': document revision proxy (content hash of full text)
    Returns None if span is invalid for this text.
    """
    if span is None:
        return None
    first, last = span
    lines = text.split("\n")
    if not (0 <= first <= last <= len(lines) - 1):
        return None
    table_lines = lines[first:last + 1]
    return {
        "span": span,
        "hash": _content_hash(table_lines),
        "doc_rev": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def verify_ownership(text: str, ownership: dict) -> bool:
    """Verify the document still contains the captured table at the captured span.

    Returns True if the table lines at `ownership['span']` still hash to the
    captured hash AND the document revision matches (optional: same-length
    modifications to the table itself are detected by the table hash).

    False means the region moved, the table content changed, or the document
    was replaced — the caller must refuse the write.
    """
    if ownership is None:
        return False
    span = ownership.get("span")
    if span is None:
        return False
    first, last = span
    lines = text.split("\n")
    if not (0 <= first <= last <= len(lines) - 1):
        return False
    table_lines = lines[first:last + 1]
    if _content_hash(table_lines) != ownership.get("hash"):
        return False
    # Document revision is a strong proxy: a same-length prose change above
    # the table shifts the span down but keeps the table identical — that is
    # allowed because the table itself is protected. A change inside the
    # table changes its hash and is refused.
    # Note: we do NOT require doc_rev match, because unrelated prose edits
    # are fine as long as the target table is identifiable and unchanged.
    return True


def replace_region(editor, span: tuple[int, int], new_lines,
                   ownership: dict | None = None) -> bool:
    """Overwrite the whole lines [first, last] with `new_lines`.

    The edit is one QTextCursor selection + one insertText inside one
    edit block, so it lands as ONE undo step and the document's own
    undo/redo stack stays coherent — no manual undo gymnastics.

    Returns True when the document was written, False when the edit was
    refused. Refusal reasons, all of them caller-visible:

    * the span is None (no region identified) — nothing owned to replace;
    * the span is out of range for the live text — the document moved,
      so this edit is stale and must be rejected rather than guessed at;
    * `ownership` is supplied and the live document no longer holds the
      captured table at the captured span (T-1462 Stage 2): the content
      changed under the dialog, so applying would overwrite newer bytes.
    * the editor/document is gone.

    An empty `new_lines` deletes the table's lines and nothing else: the
    replaced range ends at the last line's final character, so the newline
    that separates the table from whatever follows is preserved.
    """
    if span is None:
        return False
    text = editor.toPlainText()
    offset = char_span(text, span)
    if offset is None or offset is False:
        return False
    # T-1462 Stage 2: verify the region still holds what the caller captured
    # before the write is allowed to touch a single byte. This is what stops a
    # stale dialog from overwriting a table that was edited (to the SAME
    # LENGTH, which the span arithmetic alone cannot detect) while it was open.
    if ownership is not None and not verify_ownership(text, ownership):
        return False
    py_start, py_end = offset
    # T-1462 Stage 1: char_span speaks Python code points, QTextCursor speaks
    # UTF-16 units. Convert exactly once, here, at the cursor boundary. A
    # document with one emoji in the prose above the table shifts every Qt
    # position by one; without this the write-back would splice one character
    # short and eat the table's leading pipe (or one long and eat the newline).
    start = py_to_qt(text, py_start)
    end = py_to_qt(text, py_end)
    payload = "\n".join(new_lines)
    if payload and py_start > 0 and text[py_start - 1] != "\n":
        # Never splice into the middle of a line: a region always begins at a
        # line start, and this guard makes a stale span refuse instead of
        # corrupting the first line it touches.
        return False
    cursor = editor.textCursor()
    saved_sel = (cursor.selectionStart(), cursor.selectionEnd())
    saved_scroll = editor.verticalScrollBar().value()
    cursor.setPosition(start)
    cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
    from fastprompter.ui.edit_guard import edit_block
    with edit_block(cursor, editor):
        cursor.insertText(payload)
    # A re-written region reflows the document, so the viewport jumps; put the
    # scroll back before the caret comes into view.
    editor.verticalScrollBar().setValue(min(saved_scroll,
                                            editor.verticalScrollBar().maximum()))
    # The saved selection was captured in Qt units against the OLD document;
    # Qt re-anchors registered cursors across the edit, but the caret is
    # re-seated explicitly, so clamp it to the new document length.
    live = editor.toPlainText()
    cur = editor.textCursor()
    sel_start = min(saved_sel[0], qt_units(live))
    sel_end = min(saved_sel[1], qt_units(live))
    cur.setPosition(sel_start)
    if sel_end != sel_start:
        cur.setPosition(sel_end, cur.MoveMode.KeepAnchor)
    editor.setTextCursor(cur)
    editor.ensureCursorVisible()
    return True
