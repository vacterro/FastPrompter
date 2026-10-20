"""Queue 2 smoke: stale-revision guard + flush-on-navigation.

These two behaviours are timer races: they only show up on a real window with a
live QTimer, which is why they live here and not in the unit suite.
"""

from fastprompter.ui.table_widget import TableGridWidget


def _render_silo(win, table_text):
    """Load a table silo through the real window and return the widget.

    `_set_plain_text_clean` is the harness's way of owning the document: a
    plain setPlainText leaves the silo owner bookkeeping pointing at the old
    document, and the switch then refuses to flush into it (T-1227).
    """
    win._switch_to_slot(0, initial=True)
    win._set_plain_text_clean(win.text_area, table_text)
    # The window clears this on a deferred singleShot during startup; a test
    # window that never ran it would otherwise swallow every visual sync.
    win._suspend_temp_sync = False
    win.data["silo_types"] = {"0": "table", "1": "text"}
    win._apply_silo_type(0, False)
    return win.table_widget


def _type(tw, row, col, text):
    """A real cell edit: setText alone does not emit textEdited, so the
    coalescing timer is never armed and flush() would have nothing to flush."""
    cell = tw.cells[row][col]
    cell.setText(text)
    cell.textEdited.emit(text)


# ------------------------------------------------------- stale revision guard

def test_a_stale_revision_is_rejected_and_not_written(win):
    """A pending edit arriving after the plain-text document changed must NOT
    be spliced over it: the widget holds a cached prefix/suffix, so writing it
    would silently drop whatever changed in the meantime."""
    tw = TableGridWidget()
    win._switch_to_slot(0, initial=True)
    win._set_plain_text_clean(win.text_area, "| A | B |\n| --- | --- |\n| 1 | 2 |")
    win._suspend_temp_sync = False
    tw.load_markdown(win.text_area.toPlainText())

    _type(tw, 1, 0, "EDITED")
    win._on_visual_widget_changed(tw.serialize(), tw)      # current: accepted
    assert "EDITED" in win.text_area.toPlainText()
    assert tw._visual_source == win.text_area.toPlainText()

    win.text_area.setPlainText(
        win.text_area.toPlainText().replace("EDITED", "EXTERNAL"))
    win._on_visual_widget_changed(tw.serialize(), tw)      # stale: rejected
    assert "EXTERNAL" in win.text_area.toPlainText()
    assert "EDITED" not in win.text_area.toPlainText()
    assert tw._visual_source != win.text_area.toPlainText()

    # Re-loaded from the LIVE text, the widget is a valid revision again.
    tw.load_markdown(win.text_area.toPlainText())
    win._on_visual_widget_changed(tw.serialize(), tw)
    assert win.text_area.toPlainText() == tw.serialize()


def test_a_widget_without_a_source_marker_is_never_guarded(win):
    """Kanban sets no _visual_source: its serialization behaviour must not
    change, so the guard has to leave it exactly as it was."""
    kw = object()
    before = win.text_area.toPlainText()
    win._on_visual_widget_changed(before + "\nchanged", kw)
    assert not hasattr(kw, "_visual_source")


# ------------------------------------------------------------------- flush

def test_flush_emits_a_pending_edit_instead_of_waiting_for_the_timer(win):
    tw = _render_silo(win, "| A | B |\n| --- | --- |\n| 1 | 2 |")
    before = win.text_area.toPlainText()

    _type(tw, 1, 0, "FLUSHED")
    assert win.text_area.toPlainText() == before      # still coalescing
    tw.flush()
    out = win.text_area.toPlainText()
    assert "FLUSHED" in out
    assert out == tw.serialize()
    assert tw._sync_timer.isActive() is False


def test_a_switch_flushes_before_it_reads_the_outgoing_document(win):
    """The grid coalesces cell edits on a 500 ms timer. If that timer is still
    armed when the silo is left, the edit is emitted against the NEXT silo or
    lost outright — so navigation flushes first."""
    events = []
    tw = _render_silo(win, "| A | B |\n| --- | --- |\n| 1 | 2 |")
    assert tw is win.table_widget

    real_snapshot = win._editor_text_snapshot
    win._editor_text_snapshot = lambda: (
        events.append("read"), real_snapshot())[1]
    real_flush = tw.flush
    tw.flush = lambda: (events.append("flush"), real_flush())[1]

    _type(tw, 1, 0, "LEAVING")
    win._switch_to_slot(1, initial=False)

    assert events.index("flush") < events.index("read"), events
    assert "LEAVING" in win.data["temp_presets"][0]
