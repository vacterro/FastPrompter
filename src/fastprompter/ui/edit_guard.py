"""Exception-safe grouping of document edits into one undo step.

QTextDocument counts nested beginEditBlock/endEditBlock calls. If an edit
raises between the two, the counter never unwinds: from then on the
document thinks it is still inside an edit block, undo grouping breaks and
rendering can stall. Every historical "the app froze after formatting" bug
in this codebase traces back to exactly that.

Early-return code can be written correctly by hand, but only stays correct
until someone adds a branch. This makes it structural::

    with edit_block(cursor):
        cursor.insertText(...)
        if nothing_to_do:
            return          # still closed
        cursor.insertText(...)   # even if this raises, still closed
"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def edit_block(cursor, editor=None):
    """Group everything inside into a single undo step, come what may.

    Pass `editor` to also arm an undo boundary: Qt merges an adjacent
    insertion into the preceding undo command, so typing right after a
    formatting command would otherwise be undone TOGETHER with it — one
    Ctrl+Z wiping out a command the user never meant to touch. The editor
    breaks that merge on the next keystroke (see VaultTextEdit.keyPressEvent).
    """
    cursor.beginEditBlock()
    try:
        yield cursor
    finally:
        cursor.endEditBlock()
        if editor is not None:
            editor._undo_boundary_pending = True


@contextmanager
def undo_group(text_edit):
    """Same, for when you only have the widget to hand."""
    cursor = text_edit.textCursor()
    cursor.beginEditBlock()
    try:
        yield cursor
    finally:
        cursor.endEditBlock()
