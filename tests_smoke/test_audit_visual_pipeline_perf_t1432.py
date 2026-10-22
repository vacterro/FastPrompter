"""T-1432 PERF-002: visual silos share ONE revision-owned snapshot and
structural analysis for a settled edit instead of parsing the whole document
once per consumer.

Measured before the repair: a settled edit in a live Kanban/Table silo ran
board_region/table_region (a full silo_span parse of every line) twice
once in the 300 ms type recheck and again inside KanbanWidget.load_markdown
plus a second whole-document toPlainText() that bypassed the revision-keyed
snapshot cache. The audit baselines for the single pass were
23.066 ms at ~0.45 MiB and 52.151 ms at ~1.1 MiB.
"""

from __future__ import annotations

import time

import pytest
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

BOARD = (
    "# Sprint 12\n"
    "\n"
    "Goal: ship the thing.\n"
    "\n"
    "## To Do\n"
    "- [ ] write it\n"
    "\n"
    "## Done\n"
    "- [x] plan it\n"
    "\n"
    "Footer note."
)

TABLE = (
    "# Weekly report\n"
    "\n"
    "Notes before the table.\n"
    "\n"
    "| Name | Qty |\n"
    "| --- | --- |\n"
    "| apple | 3 |\n"
    "\n"
    "And a paragraph AFTER the table."
)

PROSE = "just prose now\nnothing structured at all"


@pytest.fixture
def win(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    import fastprompter.core.state as sm
    from fastprompter.main import FastPrompter

    monkeypatch.setattr(sm, "get_db_path",
                        lambda profile_id=1, _p=tmp_path: str(_p / f"t_{profile_id}.db"))
    monkeypatch.setattr(sm, "run_portable_backup", lambda data, profile_id=1: None)
    monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None)
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    w = FastPrompter()
    _app.processEvents()
    try:
        yield w
    finally:
        w.close()


def _pump(seconds=0.9):
    """Past BOTH settled-edit single-shots (300 ms each) and their effects."""
    end = time.time() + seconds
    while time.time() < end:
        _app.processEvents()
        time.sleep(0.01)


def _open(w, stype, text):
    w._switch_to_slot(0)
    _app.processEvents()
    w._set_plain_text_clean(w.text_area, text)
    _app.processEvents()
    w.data["silo_types"]["0"] = stype
    w._apply_silo_type(0, False)
    _app.processEvents()
    _pump(0.05)


def _spy_region(monkeypatch, name):
    """Count whole-document region parses for one structure kind."""
    from fastprompter.ui import silo_region

    calls = {"n": 0}
    real = getattr(silo_region, name)

    def counted(lines):
        calls["n"] += 1
        return real(lines)

    monkeypatch.setattr(silo_region, name, counted)
    return calls


def _spy_analysis(monkeypatch):
    from fastprompter.main import FastPrompter

    calls = {"n": 0}
    real = FastPrompter._silo_analyse_structure

    def counted(stype, text):
        calls["n"] += 1
        return real(stype, text)

    monkeypatch.setattr(FastPrompter, "_silo_analyse_structure",
                        staticmethod(counted))
    return calls


def _spy_loader(monkeypatch, widget_cls):
    spans = []
    real = widget_cls.load_markdown

    def spy(self, text, span=None, layout=None):
        spans.append(span)
        if layout is None:
            return real(self, text, span=span)
        return real(self, text, span=span, layout=layout)

    monkeypatch.setattr(widget_cls, "load_markdown", spy)
    return spans


def test_perf_002_kanban_settled_edit_parses_structure_once(win, monkeypatch):
    from fastprompter.ui.kanban_widget import KanbanBoardWidget

    _open(win, "kanban", BOARD)
    assert win.silo_view.currentIndex() == 1

    regions = _spy_region(monkeypatch, "board_region")
    analyses = _spy_analysis(monkeypatch)
    spans = _spy_loader(monkeypatch, KanbanBoardWidget)

    win._set_plain_text_clean(win.text_area, BOARD.replace("write it", "write it well"))
    _pump()

    assert analyses["n"] == 1, "the settled edit ran the structural pass more than once"
    assert regions["n"] == 1, "the board region was reparsed for the same revision"
    assert spans and spans[-1] is not None, "the loader reparsed what the recheck already found"

    snapshot = win._editor_text_snapshot()
    assert snapshot is not None
    assert "write it well" in snapshot
    assert win._editor_text_snapshot() is snapshot, "the snapshot was not memoized"
    assert len(win._editor_text_snaps) == 1


def test_perf_002_table_settled_edit_parses_structure_once(win, monkeypatch):
    from fastprompter.ui.table_widget import TableGridWidget

    _open(win, "table", TABLE)
    assert win.silo_view.currentIndex() == 2

    regions = _spy_region(monkeypatch, "table_region")
    analyses = _spy_analysis(monkeypatch)
    spans = _spy_loader(monkeypatch, TableGridWidget)

    win._set_plain_text_clean(win.text_area, TABLE.replace("apple", "pear"))
    _pump()

    assert analyses["n"] == 1
    assert regions["n"] == 1
    assert spans and spans[-1] is not None
    assert win.silo_view.currentIndex() == 2


def test_perf_002_repeated_rebuild_of_one_revision_stays_cached(win, monkeypatch):
    """Neither timer order nor an extra flush may buy a second parse."""
    _open(win, "kanban", BOARD)
    win._set_plain_text_clean(win.text_area, BOARD.replace("plan it", "plan it twice"))
    _pump()

    regions = _spy_region(monkeypatch, "board_region")
    win._flush_silo_type_recheck()
    win._flush_visual_rebuild()
    win._flush_silo_type_recheck()
    win._flush_visual_rebuild()
    assert regions["n"] == 0

    # A NEW revision must not answer from the old one.
    win._set_plain_text_clean(win.text_area, BOARD.replace("plan it", "plan it thrice"))
    win._flush_silo_type_recheck()
    assert regions["n"] == 1
    win._flush_visual_rebuild()
    assert regions["n"] == 1


def test_perf_002_prose_falls_back_and_never_reaches_the_board(win, monkeypatch):
    from fastprompter.ui.kanban_widget import KanbanBoardWidget

    _open(win, "kanban", BOARD)
    spans = _spy_loader(monkeypatch, KanbanBoardWidget)

    win._set_plain_text_clean(win.text_area, PROSE)
    _pump()

    assert win.silo_view.currentIndex() == 0, "prose must fall back to the text editor"
    assert spans == [], "a board was rebuilt over text that holds no board"
    assert "just prose now" in win.text_area.toPlainText()


def test_perf_002_invalid_table_text_falls_back(win, monkeypatch):
    _open(win, "table", TABLE)
    win._set_plain_text_clean(win.text_area, PROSE)
    _pump()
    assert win.silo_view.currentIndex() == 0


def test_perf_002_undo_back_to_a_board_restores_the_visual_view(win):
    _open(win, "kanban", BOARD)
    original = win.text_area.toPlainText()

    win._set_plain_text_clean(win.text_area, PROSE)
    _pump()
    assert win.silo_view.currentIndex() == 0

    win._set_plain_text_clean(win.text_area, original)
    _pump()
    assert win.silo_view.currentIndex() == 1


def test_perf_002_prefix_and_suffix_notes_survive_byte_equivalent(win):
    """The cached span must be the SAME region the widget would have found."""
    from fastprompter.ui import silo_region

    _open(win, "kanban", BOARD)
    board = win.kanban_widget
    lines = BOARD.split("\n")
    prefix, region, suffix = silo_region.split(lines, silo_region.board_region(lines))
    assert board._prefix == prefix
    assert board._suffix == suffix

    win._set_plain_text_clean(win.text_area, BOARD.replace("write it", "write it well"))
    _pump()
    assert board._prefix == prefix
    assert board._suffix == suffix
    assert "write it well" in board.serialize()
    assert "# Sprint 12" in board.serialize()
    assert "Footer note." in board.serialize()


def _big_board(target_bytes):
    """A board whose document size is at least target_bytes.

    Uses a linear-size accumulator instead of repeated
    sum(len(r) for r in rows) which is O(n^2) over fixture generation.
    """
    line = "- [ ] do the thing carefully\n"
    line_len = len(line)
    n = max(1, (target_bytes + line_len - 1) // line_len)
    core = "## To Do\n" + line * n
    return "# Sprint\n\n" + core + "\n\n## Done\n- [x] shipped\n\nFooter."


def test_perf_002_structure_correctness_at_audit_sizes():
    """Correctness gate: _silo_analyse_structure recognises every audit board.

    Deterministic assertion -- no timing ratio.
    """
    from fastprompter.main import FastPrompter

    for target in (450_000, 1_100_000):
        text = _big_board(target)
        ok, span = FastPrompter._silo_analyse_structure("kanban", text)
        assert ok is True
        assert span is not None
        assert len(text.encode("utf-8")) >= target


def test_perf_002_one_pass_measured_at_the_audit_sizes(capsys):
    """Timing diagnostic only -- NOT a pass/fail gate.

    Compares the full _silo_analyse_structure path (split + board_region)
    against the raw board_region call on pre-split lines, using consistent
    text preparation, warm-up, repeated samples, and reports median + spread.
    Numbers are printed for evidence but do not determine pass/fail.
    """
    import statistics

    from fastprompter.main import FastPrompter
    from fastprompter.ui import silo_region

    for target in (450_000, 1_100_000):
        text = _big_board(target)

        _ = FastPrompter._silo_analyse_structure("kanban", text)
        _ = silo_region.board_region(text.split("\n"))

        one_pass_samples = []
        raw_two_samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            ok, span = FastPrompter._silo_analyse_structure("kanban", text)
            one_pass_samples.append(time.perf_counter() - t0)
            assert ok is True and span is not None

            lines = text.split("\n")
            t0 = time.perf_counter()
            silo_region.board_region(lines)
            silo_region.board_region(lines)
            raw_two_samples.append(time.perf_counter() - t0)

        med_full = statistics.median(one_pass_samples) * 1000
        med_raw = statistics.median(raw_two_samples) * 1000
        spread = max(one_pass_samples) - min(one_pass_samples)
        print(f"\n  target={target:,} chars={len(text)} "
              f"one_pass_median={med_full:.3f}ms "
              f"raw_two_median={med_raw:.3f}ms "
              f"spread={spread * 1000:.3f}ms")
