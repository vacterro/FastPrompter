"""Integration tests for kanban_widget and table_widget visual widgets."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


# ── helpers ──────────────────────────────────────────────────────────────────

def _flush():
    _app.processEvents()
    _app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _app.processEvents()


# ═══════════════════════════════════════════════════════════════════════════════
# Kanban widget
# ═══════════════════════════════════════════════════════════════════════════════

from fastprompter.ui.kanban_widget import (
    CardState,
    ColumnState,
    KanbanBoardWidget,
    KanbanColumnWidget,
    KanbanParser,
)


class TestKanbanParser:
    def test_parse_empty_text_produces_one_column(self):
        cols = KanbanParser.parse("")
        assert len(cols) == 1
        assert cols[0].name == "New Column"
        assert cols[0].cards == []

    def test_parse_full_board(self):
        text = "## To Do\n- [ ] write\n- [x] done\n## Doing\n- [ ] work"
        cols = KanbanParser.parse(text)
        assert [c.name for c in cols] == ["To Do", "Doing"]
        assert len(cols[0].cards) == 2
        assert cols[0].cards[0].title == "write"
        assert cols[0].cards[0].done is False
        assert cols[0].cards[1].title == "done"
        assert cols[0].cards[1].done is True
        assert cols[1].cards[0].title == "work"

    def test_parse_legacy_bullet(self):
        cols = KanbanParser.parse("## Ideas\n- just an idea\n- [x] shipped")
        assert len(cols[0].cards) == 2
        assert cols[0].cards[0].title == "just an idea"
        assert cols[0].cards[0].done is False

    def test_parse_continuation_lines(self):
        text = "## Col\n- [ ] title\n  detail line\n  another"
        cols = KanbanParser.parse(text)
        assert cols[0].cards[0].continuation == ["detail line", "another"]

    def test_parse_unknown_text_dumped_into_first_column(self):
        cols = KanbanParser.parse("some random text\nnot markdown")
        assert cols[0].cards[0].title == "some random text\nnot markdown"


class TestKanbanSerialize:
    def test_round_trip_full_board(self):
        text = "## To Do\n- [ ] write\n- [x] done\n## Doing\n- [ ] work"
        expected = "## To Do\n- [ ] write\n- [x] done\n\n## Doing\n- [ ] work"
        board = KanbanBoardWidget()
        board.load_markdown(text)
        result = board.serialize()
        assert result == expected

    def test_round_trip_with_continuations(self):
        text = "## Col\n- [ ] title\n  detail\n## Col2\n- [x] fin"
        expected = "## Col\n- [ ] title\n  detail\n\n## Col2\n- [x] fin"
        board = KanbanBoardWidget()
        board.load_markdown(text)
        assert board.serialize() == expected

    def test_add_column_shows_in_serialize(self):
        board = KanbanBoardWidget()
        board.load_markdown("## A\n- [ ] 1")
        assert board.columns[0].name == "A"
        board._on_add_column_clicked(None)
        assert len(board.columns) == 2
        assert "## A" in board.serialize()
        assert "## New Column" in board.serialize()

    def test_column_count_label(self):
        col_state = ColumnState("Test")
        col_state.cards.append(CardState("a", False))
        col_state.cards.append(CardState("b", True))
        widget = KanbanColumnWidget(col_state)
        assert "(2)" in widget.lbl_count.text()

    def test_card_count_updates_on_add(self):
        col_state = ColumnState("Test")
        col_state.cards.append(CardState("a", False))
        widget = KanbanColumnWidget(col_state)
        assert "(1)" in widget.lbl_count.text()

    def test_empty_serialize_is_empty(self):
        board = KanbanBoardWidget()
        assert board.serialize() == ""

    def test_load_then_add_column_then_serialize(self):
        board = KanbanBoardWidget()
        board.load_markdown("## Todo\n- [ ] a\n- [x] b")
        assert len(board.columns) == 1
        assert board.columns[0].name == "Todo"


# ═══════════════════════════════════════════════════════════════════════════════
# Table widget
# ═══════════════════════════════════════════════════════════════════════════════

from fastprompter.ui.table_widget import TableGridWidget


class TestTableLoadMarkdown:
    def test_round_trip(self):
        # Asserted on MEANING, not on an exact string. The widget renders
        # through silo_table.render() now — one formatter for the visual and
        # the plain-text paths, because two serialisers for one format meant a
        # silo edited in both spun `---` against `:---` on every save. That
        # formatter also column-aligns the pipes, so the old hardcoded
        # expectation pinned cosmetics that changed deliberately.
        from fastprompter.ui import silo_table as st
        text = "| Name | Qty |\n| :--- | ---: |\n| apple | 3 |\n| pear | 12 |"
        t = TableGridWidget()
        t.load_markdown(text)
        assert t.cells
        out = t.serialize()
        parsed = st.parse(out.split("\n"), 0)
        assert parsed is not None
        assert parsed.rows == [["Name", "Qty"], ["apple", "3"], ["pear", "12"]]
        assert parsed.aligns == [st.ALIGN_LEFT, st.ALIGN_RIGHT]
        assert len({len(line) for line in out.split("\n")}) == 1, out

    def test_round_trip_with_alignment(self):
        from fastprompter.ui import silo_table as st
        text = "| L | C | R |\n| :--- | :---: | ---: |\n| a | b | c |"
        t = TableGridWidget()
        t.load_markdown(text)
        parsed = st.parse(t.serialize().split("\n"), 0)
        assert parsed.aligns == [st.ALIGN_LEFT, st.ALIGN_CENTER, st.ALIGN_RIGHT]
        assert parsed.rows == [["L", "C", "R"], ["a", "b", "c"]]
        assert t.alignments[0] == Qt.AlignmentFlag.AlignLeft
        assert t.alignments[1] == Qt.AlignmentFlag.AlignCenter
        assert t.alignments[2] == Qt.AlignmentFlag.AlignRight

    def test_escaped_pipe_in_cell(self):
        text = "| a | grep a\\|b | c |\n| --- | --- | --- |\n| 1 | 2 | 3 |"
        t = TableGridWidget()
        t.load_markdown(text)
        assert _cell_text(t, 0, 1) == "grep a|b"

    def test_empty_input_creates_default_table(self):
        t = TableGridWidget()
        t.load_markdown("")
        assert len(t.cells) >= 2

    def test_header_cells_are_marked_for_the_skin(self):
        # Bold moved from an inline stylesheet to a dynamic property. An
        # inline sheet set ON the widget overrides the themed one, so the
        # header was the single cell that stopped following the theme.
        t = TableGridWidget()
        t.load_markdown("| H1 | H2 |\n| --- | --- |\n| a | b |")
        assert t.cells[0][0].property("header") == "true"
        assert t.cells[1][0].property("header") in (None, "false")
        assert not (t.cells[0][0].styleSheet() or "")

    def test_round_trip_mixed_content(self):
        t = TableGridWidget()
        t.load_markdown("| A | B | C |\n| :--- | ---: | :---: |\n| hello | 42 | 3.14 |\n| foo | bar | baz |")
        rt = t.serialize()
        t2 = TableGridWidget()
        t2.load_markdown(rt)
        assert len(t2.cells) == 3
        assert _cell_text(t2, 1, 0) == "hello"
        assert _cell_text(t2, 2, 2) == "baz"


class TestTableInsertDelete:
    def test_insert_row_mid_table(self):
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.insert_row(t.cells[1][0], 1)
        assert len(t.cells) == 4
        assert _cell_text(t, 1, 0) == "1"
        assert _cell_text(t, 2, 0) == ""
        assert _cell_text(t, 3, 0) == "3"

    def test_insert_row_above(self):
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.insert_row(t.cells[1][0], -1)
        assert len(t.cells) == 3
        assert _cell_text(t, 2, 0) == "1"

    def test_delete_row(self):
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.delete_row(t.cells[1][0])
        assert len(t.cells) == 2
        assert _cell_text(t, 1, 0) == "3"

    def test_delete_row_keeps_at_least_one_body_row(self):
        t = TableGridWidget()
        t.load_markdown("| A | B |\n| --- | --- |\n| only | row |")
        t.delete_row(t.cells[1][0])
        assert len(t.cells) == 2

    def test_insert_col_mid(self):
        text = "| A | C |\n| --- | --- |\n| 1 | 3 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.insert_col(t.cells[0][0], 1)
        assert len(t.cells[0]) == 3
        assert _cell_text(t, 0, 0) == "A"
        assert _cell_text(t, 0, 1) == ""
        assert _cell_text(t, 0, 2) == "C"

    def test_insert_col_left(self):
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.insert_col(t.cells[0][0], -1)
        assert len(t.cells[0]) == 3
        assert _cell_text(t, 0, 0) == ""

    def test_delete_col(self):
        text = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.delete_col(t.cells[0][1])
        assert len(t.cells[0]) == 2
        assert _cell_text(t, 0, 0) == "A"
        assert _cell_text(t, 0, 1) == "C"
        assert _cell_text(t, 1, 0) == "1"
        assert _cell_text(t, 1, 1) == "3"

    def test_delete_col_keeps_at_least_one(self):
        t = TableGridWidget()
        t.load_markdown("| only |\n| --- |\n| x |")
        t.delete_col(t.cells[0][0])
        assert len(t.cells[0]) == 1


class TestTableSwaps:
    def test_swap_row_down(self):
        text = "| A |\n| --- |\n| top |\n| bot |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.swap_row_down(t.cells[1][0])
        assert _cell_text(t, 1, 0) == "bot"
        assert _cell_text(t, 2, 0) == "top"

    def test_swap_row_up(self):
        t = TableGridWidget()
        t.load_markdown("| A |\n| --- |\n| top |\n| bot |")
        t.swap_row_up(t.cells[2][0])
        assert _cell_text(t, 1, 0) == "bot"
        assert _cell_text(t, 2, 0) == "top"

    def test_swap_row_up_blocked_on_header(self):
        t = TableGridWidget()
        t.load_markdown("| A |\n| --- |\n| top |")
        t.swap_row_up(t.cells[1][0])
        assert _cell_text(t, 1, 0) == "top"

    def test_swap_col_right(self):
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.swap_col_right(t.cells[0][0])
        assert _cell_text(t, 0, 0) == "B"
        assert _cell_text(t, 0, 1) == "A"
        assert _cell_text(t, 1, 0) == "2"
        assert _cell_text(t, 1, 1) == "1"

    def test_swap_col_left(self):
        t = TableGridWidget()
        t.load_markdown("| A | B |\n| --- | --- |\n| 1 | 2 |")
        t.swap_col_left(t.cells[0][1])
        assert _cell_text(t, 0, 0) == "B"
        assert _cell_text(t, 0, 1) == "A"
        assert _cell_text(t, 1, 0) == "2"
        assert _cell_text(t, 1, 1) == "1"


class TestTableSerialize:
    def test_serialize_empty_returns_empty(self):
        t = TableGridWidget()
        assert t.serialize() == ""

    def test_serialize_pipe_escaping(self):
        t = TableGridWidget()
        t.load_markdown("| A | B |\n| --- | --- |\n| a\\|b | c |")
        result = t.serialize()
        assert "a\\|b" in result

    def test_serialize_preserves_alignment_after_edit(self):
        text = "| L | R |\n| :--- | ---: |\n| left | right |"
        t = TableGridWidget()
        t.load_markdown(text)
        t.insert_col(t.cells[0][1], 1)
        result = t.serialize()
        # after insert between L and R, L stays left, new col is left, R stays right
        assert "L" in result.split("\n")[0]
        assert "R" in result.split("\n")[0]


# ── internals ─────────────────────────────────────────────────────────────────

def _cell_text(tbl: TableGridWidget, row: int, col: int) -> str:
    return tbl.cells[row][col].text()


# ---------------------------------------------------------------------------
# T-634: a visual widget owns a REGION of the silo, not the whole silo
# ---------------------------------------------------------------------------


class TestVisualWidgetsPreserveTheRestOfTheSilo:
    """Both widgets serialise back over the entire silo, so a widget that
    knows only about its own table or board takes everything else with it.

    Measured before the region split, on a silo of
    "# Weekly report / notes / <table> / trailing paragraph":

        table widget  ->  "| # Weekly report |\n| --- |"

    the heading became the header row, the blank line ended the table, and two
    lines replaced the whole silo. The board was less spectacular and just as
    wrong: title, goal line and footer gone.
    """

    TABLE_SILO = ("# Weekly report\n"
                  "\n"
                  "Notes before the table.\n"
                  "\n"
                  "| Name | Qty |\n"
                  "| :--- | --- |\n"
                  "| apple | 3 |\n"
                  "\n"
                  "And a paragraph AFTER the table.")

    BOARD_SILO = ("# Sprint 12\n"
                  "\n"
                  "Goal: ship the thing.\n"
                  "\n"
                  "## To Do\n"
                  "- [ ] write it\n"
                  "\n"
                  "## Done\n"
                  "- [x] plan it\n"
                  "\n"
                  "Footer note.")

    def test_table_keeps_the_text_around_it(self):
        from fastprompter.ui import silo_table as st
        t = TableGridWidget()
        t.load_markdown(self.TABLE_SILO)
        out = t.serialize()
        assert "# Weekly report" in out
        assert "Notes before the table." in out
        assert "And a paragraph AFTER the table." in out
        table = st.parse(out.split("\n"), out.split("\n").index("| Name  | Qty |"))
        assert table.rows == [["Name", "Qty"], ["apple", "3"]]

    def test_table_edit_does_not_eat_the_silo(self):
        t = TableGridWidget()
        t.load_markdown(self.TABLE_SILO)
        t.cells[1][0].setText("banana")
        out = t.serialize()
        assert "banana" in out
        assert "# Weekly report" in out
        assert "And a paragraph AFTER the table." in out

    def test_board_keeps_the_text_around_it(self):
        from fastprompter.ui.kanban_widget import KanbanBoardWidget
        k = KanbanBoardWidget()
        k.load_markdown(self.BOARD_SILO)
        out = k.serialize()
        for kept in ("# Sprint 12", "Goal: ship the thing.", "Footer note.",
                     "## To Do", "- [ ] write it", "- [x] plan it"):
            assert kept in out, kept

    def test_board_edit_does_not_eat_the_silo(self):
        from fastprompter.ui.kanban_widget import KanbanBoardWidget
        k = KanbanBoardWidget()
        k.load_markdown(self.BOARD_SILO)
        k.columns[0].cards[0].title = "write it properly"
        out = k.serialize()
        assert "write it properly" in out
        assert "# Sprint 12" in out
        assert "Footer note." in out

    def test_a_silo_with_no_table_is_left_alone_as_a_prefix(self):
        """Unrecognised text must never be claimed by the widget."""
        t = TableGridWidget()
        t.load_markdown("just prose\nand more prose")
        out = t.serialize()
        assert out.startswith("just prose\nand more prose")

    def test_the_board_span_stops_at_the_last_card(self):
        from fastprompter.ui import silo_kanban as sk
        lines = self.BOARD_SILO.split("\n")
        first, last = sk.board_span(lines)
        assert lines[first] == "## To Do"
        assert lines[last] == "- [x] plan it", lines[last]


class TestNoLayoutAttributeShadowing:
    """`self.layout = QGridLayout(self)` shadows QWidget.layout(), so any
    generic pass over widgets hits "'QGridLayout' object is not callable"."""

    def test_widgets_keep_a_callable_layout(self):
        from fastprompter.ui.kanban_widget import KanbanBoardWidget
        t = TableGridWidget()
        t.load_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |")
        assert callable(t.layout)
        k = KanbanBoardWidget()
        k.load_markdown("## Col\n- [ ] card")
        assert callable(k.layout)
        for col in k.findChildren(type(k)) or []:
            assert callable(col.layout)


# ---------------------------------------------------------------------------
# T-635: transforming an EMPTY silo has to produce something to work in
# ---------------------------------------------------------------------------


class TestTransformSeedsStructure:
    """The main way in is: new silo -> right-click -> "Transform to Kanban".
    The old prompt asked "Format as one first?" and then formatted nothing
    whichever button you pressed, so both answers dropped you into an empty
    widget."""

    def _win(self, tmp_path):
        import fastprompter.core.state as sm
        from fastprompter.main import FastPrompter
        sm.get_db_path = lambda profile_id=1, _p=tmp_path: str(_p / f"s_{profile_id}.db")
        sm.run_portable_backup = lambda data: None
        FastPrompter.setup_single_instance_server = lambda self: None
        FastPrompter.register_all_hotkeys = lambda self: None
        FastPrompter.unregister_all_hotkeys = lambda self: None
        return FastPrompter()

    def test_empty_silo_becomes_a_real_board(self, tmp_path):
        from fastprompter.ui import silo_kanban as sk
        w = self._win(tmp_path)
        try:
            w.data["temp_presets"][0] = ""
            assert w._seed_silo_structure(0, "kanban", "", False) is True
            board = sk.parse(w.data["temp_presets"][0].split("\n"))
            assert [c.name for c in board.columns] == ["To Do", "Doing", "Done"]
        finally:
            w.close()

    def test_empty_silo_becomes_a_real_table(self, tmp_path):
        from fastprompter.ui import silo_table as st
        w = self._win(tmp_path)
        try:
            assert w._seed_silo_structure(0, "table", "", False) is True
            lines = w.data["temp_presets"][0].split("\n")
            table = st.parse(lines, 0)
            assert table is not None and table.columns == 3
        finally:
            w.close()

    def test_a_silo_that_already_has_one_is_left_alone(self, tmp_path):
        w = self._win(tmp_path)
        try:
            text = "## To Do\n- [ ] a"
            assert w._seed_silo_structure(0, "kanban", text, False) is False
            table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
            assert w._seed_silo_structure(0, "table", table, False) is False
        finally:
            w.close()

    def test_text_mode_never_rewrites_anything(self, tmp_path):
        w = self._win(tmp_path)
        try:
            assert w._seed_silo_structure(0, "text", "anything", False) is False
        finally:
            w.close()

    def test_existing_notes_are_kept_above_the_new_structure(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        from fastprompter.ui import silo_kanban as sk
        w = self._win(tmp_path)
        try:
            monkeypatch.setattr(QMessageBox, "question",
                                lambda *a, **k: QMessageBox.StandardButton.Yes)
            assert w._seed_silo_structure(0, "kanban", "my notes", False) is True
            body = w.data["temp_presets"][0]
            assert body.startswith("my notes")
            assert [c.name for c in sk.parse(body.split("\n")).columns] == [
                "To Do", "Doing", "Done"]
        finally:
            w.close()

    def test_saying_no_leaves_the_silo_untouched(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        w = self._win(tmp_path)
        try:
            w.data["temp_presets"][0] = "my notes"
            monkeypatch.setattr(QMessageBox, "question",
                                lambda *a, **k: QMessageBox.StandardButton.No)
            assert w._seed_silo_structure(0, "kanban", "my notes", False) is None
            assert w.data["temp_presets"][0] == "my notes"
        finally:
            w.close()


# ---------------------------------------------------------------------------
# T-645: rename a pasted image by double-clicking its pill
# ---------------------------------------------------------------------------


class TestRenamePastedImage:
    """A pasted image lands as `paste-20260730_140826.png` — a name that says
    when it arrived and nothing about what it is."""

    def _win(self, tmp_path):
        import fastprompter.core.state as sm
        from fastprompter.main import FastPrompter
        sm.get_db_path = lambda profile_id=1, _p=tmp_path: str(_p / f"r_{profile_id}.db")
        sm.run_portable_backup = lambda data: None
        FastPrompter.setup_single_instance_server = lambda self: None
        FastPrompter.register_all_hotkeys = lambda self: None
        FastPrompter.unregister_all_hotkeys = lambda self: None
        return FastPrompter()

    def _seed(self, w, tmp_path, name="paste-20260730_140826.png"):
        from PyQt6.QtCore import QUrl
        img = tmp_path / name
        img.write_bytes(b"not really a png")
        url = QUrl.fromLocalFile(str(img)).toString()
        w.text_area.setPlainText(f"before\n![]({url})\nafter")
        _app.processEvents()
        block = w.text_area.document().findBlockByNumber(1)
        from fastprompter.ui.editor import MD_IMAGE_RE
        match = MD_IMAGE_RE.search(block.text())
        return img, block, match

    def test_renames_the_file_and_the_link(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            img, block, match = self._seed(w, tmp_path)
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("architecture", True)))
            assert w.text_area.rename_image_at(block, match) is True
            assert not img.exists()
            assert (tmp_path / "architecture.png").exists()
            assert "architecture.png" in w.text_area.toPlainText()
            assert "paste-2026" not in w.text_area.toPlainText()
        finally:
            w.close()

    def test_keeps_the_extension_the_user_left_off(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            self._seed(w, tmp_path)
            block = w.text_area.document().findBlockByNumber(1)
            from fastprompter.ui.editor import MD_IMAGE_RE
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("diagram.png", True)))
            w.text_area.rename_image_at(block, MD_IMAGE_RE.search(block.text()))
            assert (tmp_path / "diagram.png").exists()
            assert "diagram.png.png" not in w.text_area.toPlainText()
        finally:
            w.close()

    def test_cancel_changes_nothing(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            img, block, match = self._seed(w, tmp_path)
            before = w.text_area.toPlainText()
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("nope", False)))
            assert w.text_area.rename_image_at(block, match) is False
            assert img.exists()
            assert w.text_area.toPlainText() == before
        finally:
            w.close()

    def test_illegal_characters_are_replaced(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            self._seed(w, tmp_path)
            block = w.text_area.document().findBlockByNumber(1)
            from fastprompter.ui.editor import MD_IMAGE_RE
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("a/b:c", True)))
            w.text_area.rename_image_at(block, MD_IMAGE_RE.search(block.text()))
            assert (tmp_path / "a_b_c.png").exists()
        finally:
            w.close()

    def test_an_existing_name_is_not_clobbered(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            (tmp_path / "taken.png").write_bytes(b"i was here first")
            self._seed(w, tmp_path)
            block = w.text_area.document().findBlockByNumber(1)
            from fastprompter.ui.editor import MD_IMAGE_RE
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("taken", True)))
            w.text_area.rename_image_at(block, MD_IMAGE_RE.search(block.text()))
            assert (tmp_path / "taken.png").read_bytes() == b"i was here first"
            assert (tmp_path / "taken (2).png").exists()
        finally:
            w.close()

    def test_rename_is_one_undo_step(self, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        w = self._win(tmp_path)
        try:
            _img, block, match = self._seed(w, tmp_path)
            before = w.text_area.toPlainText()
            monkeypatch.setattr(QInputDialog, "getText",
                                staticmethod(lambda *a, **k: ("one-step", True)))
            w.text_area.rename_image_at(block, match)
            assert w.text_area.toPlainText() != before
            w.text_area.undo()
            assert w.text_area.toPlainText() == before
        finally:
            w.close()

    def test_the_pill_is_hit_testable(self, tmp_path):
        w = self._win(tmp_path)
        try:
            w.resize(900, 400)
            w.show()
            _app.processEvents()
            self._seed(w, tmp_path)
            _app.processEvents()
            block = w.text_area.document().findBlockByNumber(1)
            from fastprompter.ui.editor import MD_IMAGE_RE
            match = MD_IMAGE_RE.search(block.text())
            rect = w.text_area._image_pill_rect(block, match)
            assert rect.width() >= 40 and rect.height() >= 18
            assert w.text_area.image_pill_at(rect.center()) is not None
            # ordinary prose is not a pill
            plain = w.text_area.document().findBlockByNumber(0)
            from PyQt6.QtGui import QTextCursor
            pos = w.text_area.cursorRect(QTextCursor(plain)).center()
            assert w.text_area.image_pill_at(pos) is None
        finally:
            w.close()
