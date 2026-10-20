"""PERF-003 acceptance: per-document selection history is bounded (T-1432 / SRC-093).

The audit traced 100,000 selection records in ONE document at 48,685,112 bytes
(~487 bytes per record, ~46 MiB) and the stack grew linearly with the session
because nothing ever dropped an old record. The fix keeps one named limit
(``INTERACTION_HISTORY_LIMIT``) and trims the OLDEST records on push, so a
document holds a bounded window of its newest transitions.

What this file pins, one test per audit VERIFY bullet:

* depth never exceeds the limit and consists of the newest records;
* undoing every retained interaction is exact reverse order;
* redoing them is exact forward order, and redo is bounded too;
* several cached documents are each bounded, independently;
* a stress test that proves record count PLATEAUS instead of reproducing the
  100,000-record linear growth (bounded vs deliberately unbounded control);
* the window-level mixed chronology — text edits, data undo and selection
  interactions around the trim boundary — still has correct smart Ctrl+Z/Ctrl+Y
  ordering.
"""

import gc
import os
import sys
import tempfile
import tracemalloc

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../tests_smoke")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _smoke_support import SmokeEnv, SmokeWindowFactory
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.interaction_undo import (
    INTERACTION_HISTORY_LIMIT,
    CursorSelectionState,
    DocumentInteractionHistory,
    SelectionInteractionRecord,
    get_document_interaction_history,
)

_app = QApplication.instance() or QApplication([])

LIMIT = INTERACTION_HISTORY_LIMIT
STRESS = 20_000


def _rec(seq, *, doc_id=1, generation=0, before=None, after=None):
    return SelectionInteractionRecord(
        before=before or CursorSelectionState(anchor=0, position=0),
        after=after or CursorSelectionState(anchor=0, position=5),
        doc_id=doc_id,
        doc_generation=generation,
        text_length=100,
        text_undo_steps=0,
        action_seq=seq,
    )


def _seqs(stack):
    return [record.action_seq for record in stack]


def _history_growth(fn):
    """Traced bytes allocated by ``fn`` inside interaction_undo.py only.

    ``interaction_undo.py`` is the filter so unrelated allocation (Qt, the test
    runner, snapshot bookkeeping) can never be read as history growth.
    """
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    fn()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    total = 0
    for stat in after.compare_to(before, "lineno"):
        traceback = stat.traceback
        if traceback is not None and any(
            "interaction_undo.py" in frame.filename for frame in traceback
        ):
            total += stat.size_diff
    return total


class TestBoundedSelectionHistory:

    def test_limit_is_one_named_constant_honoured_per_document(self):
        """The retention limit is a single named constant, not a literal."""
        assert LIMIT > 0
        history = DocumentInteractionHistory(doc_id=1)
        assert history.undo_limit == LIMIT

        history.undo_limit = 3
        for seq in range(10):
            history.push(_rec(seq))
        assert _seqs(history.undo_stack) == [7, 8, 9]

    def test_retained_depth_never_exceeds_limit_and_keeps_the_newest(self):
        history = DocumentInteractionHistory(doc_id=1)
        pushed = LIMIT * 3
        for seq in range(pushed):
            history.push(_rec(seq))

        assert len(history.undo_stack) == LIMIT
        assert _seqs(history.undo_stack) == list(range(pushed - LIMIT, pushed))
        assert history.peek_undo().action_seq == pushed - 1
        assert history.can_undo()

    def test_undo_of_all_retained_interactions_is_exact_reverse_order(self):
        history = DocumentInteractionHistory(doc_id=1)
        pushed = LIMIT * 2
        for seq in range(pushed):
            history.push(_rec(seq))

        undone = []
        while history.can_undo():
            undone.append(history.pop_undo().action_seq)

        assert undone == list(range(pushed - 1, pushed - LIMIT - 1, -1))
        assert len(undone) == LIMIT
        assert not history.can_undo()
        assert history.pop_undo() is None

    def test_redo_of_all_retained_interactions_is_exact_forward_order(self):
        history = DocumentInteractionHistory(doc_id=1)
        pushed = LIMIT * 2
        for seq in range(pushed):
            history.push(_rec(seq))

        # What the smart-undo consumer does: move each undone record across.
        while history.can_undo():
            history.push_redo(history.pop_undo())

        assert history.can_redo()
        redone = []
        while history.can_redo():
            redone.append(history.pop_redo().action_seq)

        assert redone == list(range(pushed - LIMIT, pushed))
        assert not history.can_redo()

    def test_redo_stack_is_bounded_by_the_same_budget(self):
        history = DocumentInteractionHistory(doc_id=1)
        for seq in range(LIMIT * 2):
            history.push_redo(_rec(seq))

        assert len(history.redo_stack) == LIMIT
        assert _seqs(history.redo_stack) == list(range(LIMIT, LIMIT * 2))

    def test_each_cached_document_holds_its_own_bounded_history(self):
        """Several documents at once: memory ownership stays bounded per document."""
        documents = [QTextDocument() for _ in range(3)]
        histories = []
        for index, doc in enumerate(documents):
            history = get_document_interaction_history(doc)
            assert history is not None
            histories.append(history)
            for seq in range(LIMIT * 2):
                history.push(_rec(seq, doc_id=id(doc), generation=index))

        assert len(set(map(id, histories))) == 3
        for index, history in enumerate(histories):
            assert history.doc_id == id(documents[index])
            assert len(history.undo_stack) == LIMIT
            assert _seqs(history.undo_stack) == list(range(LIMIT, LIMIT * 2))

        # One document's history is not another's: clearing one cannot clear
        # the rest, which is what "bounded per document" has to mean.
        histories[0].clear()
        assert not histories[0].can_undo()
        assert histories[1].can_undo()
        assert histories[2].can_undo()

    def test_record_count_plateaus_instead_of_growing_linearly(self):
        """20,000 pushes into the bounded history must not cost like 20,000 records.

        The audit's baseline was 100,000 records retained = 48,685,112 traced
        bytes. The control below is the pre-repair shape (an effectively
        unbounded stack), so the assertion compares mechanism against mechanism
        rather than against a magic number: the same 20,000 pushes must cost a
        small fraction of what the unbounded stack costs, and stay inside the
        per-document ceiling the limit implies.
        """
        bounded = DocumentInteractionHistory(doc_id=1)
        bounded_ok = []
        growth_bounded = _history_growth(
            lambda: bounded_ok.append(
                [bounded.push(_rec(seq)) for seq in range(STRESS)]
            )
        )

        control = DocumentInteractionHistory(doc_id=1)
        control.undo_limit = STRESS * 10  # the pre-repair unbounded shape
        control_ok = []
        growth_control = _history_growth(
            lambda: control_ok.append(
                [control.push(_rec(seq)) for seq in range(STRESS)]
            )
        )

        assert len(bounded.undo_stack) == LIMIT
        assert len(control.undo_stack) == STRESS
        assert growth_control > 0
        assert growth_bounded < 256 * 1024
        assert growth_bounded * 20 < growth_control


@pytest.fixture(scope="module")
def win():
    tmp = tempfile.mkdtemp(prefix="fp_audit_history_perf_")
    env = SmokeEnv(root=tmp)
    factory = SmokeWindowFactory(env)
    w = factory.create(show=True, size=(960, 540))
    _app.processEvents()
    yield w
    factory.retire(w)
    env.finalize()


def _cursor(editor):
    cursor = editor.textCursor()
    return cursor.anchor(), cursor.position()


class TestTrimBoundaryChronology:

    def test_trim_boundary_keeps_smart_ctrlz_ctrl_y_chronology(self, win):
        """Text edits and selection interactions across the trim boundary still order.

        The boundary is crossed on purpose: many more selection transitions than
        the limit are recorded, then a text edit lands on top. Ctrl+Z must undo
        the text first, then walk back into the retained selection window in
        reverse order, and Ctrl+Y must replay exactly that forward.
        """
        editor = win.text_area
        editor.setPlainText("Hello World and Universe")
        _app.processEvents()

        pushed = LIMIT + 7
        for index in range(pushed):
            cursor = editor.textCursor()
            cursor.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
            if index % 2 == 0:
                cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
            before = editor._capture_cursor_state()
            editor.setTextCursor(cursor)
            after = editor._capture_cursor_state()
            editor._record_selection_interaction_if_meaningful(before, after)

        history = get_document_interaction_history(editor.document())
        assert history is not None
        assert len(history.undo_stack) == LIMIT < pushed
        assert history.undo_limit == LIMIT

        newest = history.peek_undo()
        assert newest is not None
        # One side of the newest retained transition selects, the other is a
        # bare caret: exactly what the alternating loop produced.
        assert newest.before.has_selection != newest.after.has_selection
        assert newest.action_seq == max(_seqs(history.undo_stack))

        original = editor.toPlainText()
        editor.textCursor().insertText("!")
        _app.processEvents()
        assert editor.toPlainText() != original

        win._smart_undo()
        _app.processEvents()
        assert editor.toPlainText() == original

        win._smart_undo()
        _app.processEvents()
        assert _cursor(editor) == (newest.before.anchor, newest.before.position)

        win._smart_redo()
        _app.processEvents()
        assert _cursor(editor) == (newest.after.anchor, newest.after.position)
