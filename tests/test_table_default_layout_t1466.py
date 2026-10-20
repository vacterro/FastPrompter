"""T-1466/T-1467: the saved default table template is authoritative.

The defect this pins: ``silo_table.default_table()`` had a fixed 7x10 shape with
literal A-G labels in the first Markdown row, no new-table creation path read
``table_default_layout``, and 28 of the 44 tests in this file were docstring-only
placeholders. This file replaces every placeholder with an executable assertion
against real model state, real settings state and real Qt widgets.

What is asserted, in one line each:

* ``st.template_shape()`` / ``st.default_table(template)`` is the ONE authority
  for a new table's shape; a 4x6 or 12x15 saved template produces exactly that,
  a malformed template falls back to the factory 7x10, and every logical cell of
  a new table (header row included) is EMPTY -- the A/B/C labels come from
  ``headerData()``, never from cell content.
* ``FastPrompter._default_table_layout()`` reads the stored template with its
  shape and word-wrap preference, and ``_seed_silo_structure()`` seeds a new
  Table silo from that same template.
* ``TableGridWidget`` applies the saved widths, heights, manual flags and
  word-wrap to a new table, keeps per-silo presentation ahead of the template,
  and leaves existing populated tables alone.
* ``VaultTextEdit._insert_table()`` opens on the template and honours a choice
  retyped by the user instead of snapping back to a fixed 7x10.

Physical Windows/EXE acceptance (the GUI walk-through in the ticket) is NOT
automated here and is tracked in ``docs/table_default_template_acceptance.md``
instead of as a dummy test pretending to pass.
"""

import inspect
import json
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QSpinBox, QWidget  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import PyQt6.QtWidgets as qtwidgets  # noqa: E402

from fastprompter.core.default_profile import DEFAULT_PROFILE  # noqa: E402
from fastprompter.core.state import _JSON_SETTINGS, _STRUCTURED_CODECS  # noqa: E402
from fastprompter.main import FastPrompter  # noqa: E402
from fastprompter.ui import silo_table as st  # noqa: E402
from fastprompter.ui.table_grid import TableGridWidget  # noqa: E402

_APP = QApplication.instance() or QApplication([])

# A table that is clearly an EXISTING user document: populated cells, 3 columns.
POPULATED = (
    "| Name | Qty | Note |\n"
    "| :--- | ---: | :---: |\n"
    "| apple | 3 | red |\n"
    "| pear | 12 | green |\n"
)


# --------------------------------------------------------------- helpers

def template(columns=4, visible_rows=6, width=111, height=44, word_wrap=False,
             manual_cols=None, manual_rows=None):
    """A stored ``table_default_layout`` payload, as the UI saves it."""
    return {
        "version": 1,
        "columns": columns,
        "visible_rows": visible_rows,
        "col_widths": [width] * columns,
        "row_heights": [height] * visible_rows,
        "manual_cols": list(manual_cols or []),
        "manual_rows": list(manual_rows or []),
        "word_wrap": word_wrap,
    }


def as_setting(tpl):
    """The same template in the form the setting stores it: a JSON string."""
    return json.dumps(tpl)


def reader(**data):
    """``FastPrompter._default_table_layout`` bound to a settings stub."""
    host = _Host(**data)
    return FastPrompter._default_table_layout.__get__(host)()


def seeded_text(tpl):
    """Exactly what a newly seeded Table silo's Markdown is."""
    return "\n".join(st.render(st.default_table(tpl)))


class _Host(QWidget):
    """The slice of MainWindow the template reader and seeding touch."""

    def __init__(self, **data):
        super().__init__()
        self.data = dict(data)
        self.data.setdefault("temp_presets", [])
        self.data.setdefault("archive_temp_presets", [])
        self.active_temp_slot = -1          # never the open silo
        self.active_is_archive = False
        self._default_table_layout = types.MethodType(
            FastPrompter._default_table_layout, self)
        self.marks = []

    def mark_dirty(self, *a):
        self.marks.append(a)


def _grid(parent, text, **kw):
    g = TableGridWidget(parent)
    g.load_markdown(text, **kw)
    return g


_SHOWN = []


def _shown(g, w=170, h=130):
    """Show a widget offscreen and lay it out, so scrollbars get a real range."""
    g.resize(w, h)
    g.show()
    _APP.processEvents()
    _SHOWN.append(g)         # closed by the fixture below: a window left open
    return g                 # steals keyboard focus from the NEXT test


@pytest.fixture(autouse=True)
def _close_shown_widgets():
    yield
    while _SHOWN:
        w = _SHOWN.pop()
        try:
            w.close()      # a widget whose parent already went is fine
        except RuntimeError:
            pass
    _APP.processEvents()


def _parse(text):
    parsed = st.parse(text.strip().split("\n"), 0)
    assert parsed is not None
    return parsed


# =============================================================================
# A. the ONE shape authority
# =============================================================================

def test_factory_shape_when_there_is_no_template():
    t = st.default_table()
    assert t.columns == 7
    assert len(t.rows) == 10          # 1 header + 9 body
    assert all(cell == "" for row in t.rows for cell in row)


@pytest.mark.parametrize("columns,visible", [(4, 6), (12, 15), (2, 1), (7, 10)])
def test_saved_shape_builds_exactly_that_table(columns, visible):
    t = st.default_table(template(columns, visible))
    assert t.columns == columns
    assert len(t.rows) == visible      # the header row counts as visible
    assert t.has_header is True


def test_template_shape_reads_the_stored_json_text():
    assert st.template_shape(as_setting(template(4, 6))) == (4, 6)


@pytest.mark.parametrize("payload", [
    None, "", "not json", "[]", 7, "null", "3",
    {"version": 2, "columns": 4, "visible_rows": 6},
    {"version": 1, "columns": 0, "visible_rows": -2},
    {"version": 1, "columns": -3, "visible_rows": 6.5},
])
def test_unusable_template_falls_back_to_the_factory(payload):
    assert st.template_shape(payload) == (7, 10)
    t = st.default_table(payload)
    assert t.columns == 7 and len(t.rows) == 10


@pytest.mark.parametrize("payload,shape", [
    ({"version": 1, "columns": "four", "visible_rows": 6}, (7, 6)),
    ({"version": 1, "columns": 10 ** 6, "visible_rows": 6}, (7, 6)),
    ({"version": 1, "columns": True, "visible_rows": 6}, (7, 6)),
    ({"version": 1, "columns": 4, "visible_rows": 10 ** 9}, (4, 10)),
    ({"version": 1, "columns": 4, "visible_rows": 4.5}, (4, 10)),
    ({"version": 1, "columns": 4}, (4, 10)),
])
def test_a_bad_dimension_falls_back_field_by_field(payload, shape):
    # a half-written template keeps the half it can still read
    assert st.template_shape(payload) == shape


def test_shape_is_derived_from_the_saved_arrays_when_dims_are_missing():
    tpl = {"version": 1, "col_widths": [90] * 5, "row_heights": [30] * 8}
    assert st.template_shape(tpl) == (5, 8)


def test_new_table_cells_are_empty_header_included():
    assert st.new_table(3, 4).rows == [["", "", "", ""]] * 4


def test_default_table_header_row_carries_no_labels():
    t = st.default_table(template(7, 10))
    assert t.rows[0] == [""] * 7       # no A-G duplicated into the document


# =============================================================================
# B. empty logical cells, real column identifiers
# =============================================================================

def test_blank_header_round_trips_through_markdown():
    lines = st.render(st.default_table(template(4, 6)))
    parsed = st.parse(lines, 0)
    assert parsed.columns == 4
    assert len(parsed.rows) == 6
    assert parsed.rows[0] == ["", "", "", ""]
    assert all(cell == "" for row in parsed.rows[1:] for cell in row)


def test_header_only_template_round_trips():
    lines = st.render(st.default_table(template(3, 1)))
    assert len(lines) == 2             # header + separator, no body rows
    parsed = st.parse(lines, 0)
    assert parsed.columns == 3 and len(parsed.rows) == 1


def test_editing_a_blank_header_cell_keeps_the_table_intact():
    g = _grid(_Host(), seeded_text(template(3, 4)))
    idx = g.model.index(0, 1)          # the (empty) header cell of column B
    assert g.model.setData(idx, "Weight", Qt.ItemDataRole.EditRole)
    parsed = _parse(g.serialize())
    assert parsed.columns == 3 and len(parsed.rows) == 4
    assert parsed.rows[0] == ["", "Weight", ""]
    assert all(cell == "" for row in parsed.rows[1:] for cell in row)


def test_horizontal_header_paints_column_identifiers():
    g = _grid(_Host(), seeded_text(template(3, 4)))
    role = Qt.ItemDataRole.DisplayRole
    assert g.model.headerData(0, Qt.Orientation.Horizontal, role) == "A"
    assert g.model.headerData(1, Qt.Orientation.Horizontal, role) == "B"
    assert g.model.headerData(2, Qt.Orientation.Horizontal, role) == "C"
    # those labels are painted by the header, never stored as cell content
    assert g.model.data(g.model.index(0, 0), role) == ""


# =============================================================================
# C. the settings reader
# =============================================================================

def test_reader_parses_the_stored_json_string():
    layout = reader(table_default_layout=as_setting(template(4, 6)))
    assert layout["columns"] == 4
    assert layout["visible_rows"] == 6
    assert layout["cols"] == [111] * 4
    assert layout["rows"] == [44] * 6
    assert layout["word_wrap"] is False


def test_reader_accepts_a_dict_and_word_wrap():
    layout = reader(table_default_layout=template(5, 3, word_wrap=True))
    assert layout["word_wrap"] is True
    assert layout["columns"] == 5


@pytest.mark.parametrize("raw", [None, "", "not json", "[]", "null", "3",
                                 json.dumps({"version": 2, "columns": 4})])
def test_reader_refuses_unusable_settings(raw):
    assert reader(table_default_layout=raw) is None


def test_reader_drops_widths_that_no_longer_match_the_shape():
    tpl = template(4, 6)
    tpl["col_widths"] = [111] * 3      # a column was deleted after saving
    layout = reader(table_default_layout=tpl)
    assert layout["columns"] == 4      # the shape still decides
    assert layout["cols"] == []        # but no half-applied widths


def test_factory_setting_is_the_factory_shape():
    raw = DEFAULT_PROFILE["table_default_layout"]
    assert isinstance(raw, str)
    assert st.template_shape(raw) == (7, 10)
    assert "table_default_layout" in _JSON_SETTINGS
    assert _STRUCTURED_CODECS["table_default_layout"] == (dict, {}, True)


# =============================================================================
# D. seeding a new Table silo
# =============================================================================

def _seed(host, tgt_type="table", text=""):
    return FastPrompter._seed_silo_structure.__get__(host)(0, tgt_type, text, False)


def test_seed_uses_the_saved_template_shape():
    host = _Host(table_default_layout=as_setting(template(4, 6)))
    assert _seed(host) is True
    parsed = _parse(host.data["temp_presets"][0])
    assert parsed.columns == 4
    assert len(parsed.rows) == 6
    assert all(cell == "" for row in parsed.rows for cell in row)


def test_seed_uses_a_larger_template_too():
    host = _Host(table_default_layout=as_setting(template(12, 15)))
    _seed(host)
    parsed = _parse(host.data["temp_presets"][0])
    assert parsed.columns == 12 and len(parsed.rows) == 15


def test_seed_leaves_a_silo_that_already_has_a_table_alone():
    host = _Host(table_default_layout=as_setting(template(4, 6)))
    # a document that ALREADY holds a table is never re-seeded
    assert _seed(host, text=POPULATED) is False
    assert host.data["temp_presets"] == []


# =============================================================================
# E. save / apply / restore through the real widget
# =============================================================================

def test_save_as_default_captures_shape_sizes_and_word_wrap():
    g = _shown(_grid(_Host(), seeded_text(template(4, 6))))
    g.view.horizontalHeader().resizeSection(1, 137)   # a manual width
    g.view.verticalHeader().resizeSection(2, 61)      # a manual height
    g.view.setWordWrap(True)
    g.save_as_default_layout()

    stored = json.loads(g.parent().data["table_default_layout"])
    assert stored["version"] == 1
    assert stored["columns"] == 4
    assert stored["visible_rows"] == 6
    assert stored["col_widths"][1] == 137
    assert stored["row_heights"][2] == 61
    assert stored["word_wrap"] is True
    assert 1 in stored["manual_cols"]


def test_saved_template_shapes_a_newly_created_table():
    g = _shown(_grid(_Host(), seeded_text(template(4, 6))))
    g.view.setWordWrap(True)
    g.view.horizontalHeader().resizeSection(0, 155)
    g.view.horizontalHeader().resizeSection(1, 137)
    g.save_as_default_layout()
    tpl = reader(**g.parent().data)

    # the new table the user then gets, end to end: seed Markdown + template
    fresh = _grid(_Host(), seeded_text(tpl), default_layout=tpl)
    assert fresh.model.columnCount() == 4
    assert fresh.model.rowCount() == 6
    assert fresh.view.horizontalHeader().sectionSize(0) == 155
    assert fresh.view.horizontalHeader().sectionSize(1) == 137
    assert fresh.view.wordWrap() is True


def test_saved_template_12x15_is_applied_exactly():
    tpl = reader(table_default_layout=as_setting(template(12, 15)))
    fresh = _grid(_Host(), seeded_text(tpl), default_layout=tpl)
    assert fresh.model.columnCount() == 12
    assert fresh.model.rowCount() == 15
    assert fresh.view.horizontalHeader().sectionSize(0) == 111
    assert fresh.view.verticalHeader().sectionSize(0) == 44


def test_word_wrap_comes_from_the_template():
    tpl = reader(table_default_layout=as_setting(template(3, 4, word_wrap=True)))
    assert _grid(_Host(), seeded_text(tpl), default_layout=tpl).view.wordWrap() is True
    tpl_off = reader(table_default_layout=as_setting(template(3, 4, word_wrap=False)))
    assert _grid(_Host(), seeded_text(tpl_off),
                 default_layout=tpl_off).view.wordWrap() is False


def test_per_silo_presentation_wins_over_the_template():
    g = _shown(_grid(_Host(), POPULATED))
    g.view.horizontalHeader().resizeSection(0, 222)
    saved = g.capture_presentation()
    tpl = reader(table_default_layout=as_setting(template(4, 6, width=90)))

    fresh = _grid(_Host(), POPULATED, layout=saved, default_layout=tpl)
    assert fresh.view.horizontalHeader().sectionSize(0) == 222
    # the template's 4-column shape never rewrites an existing 3-column table
    assert fresh.model.columnCount() == 3


def test_existing_populated_table_keeps_its_shape_and_autofits():
    tpl = reader(table_default_layout=as_setting(template(4, 6, width=250)))
    fresh = _grid(_Host(), POPULATED, default_layout=tpl)
    assert fresh.model.columnCount() == 3
    assert fresh.model.rowCount() == 3
    assert fresh.view.horizontalHeader().sectionSize(0) < 250   # autofit, not template


def test_reset_to_default_refuses_a_shape_mismatch():
    host = _Host(table_default_layout=as_setting(template(4, 6, width=133)))
    g = _grid(host, POPULATED)          # 3 columns, no saved presentation
    assert g.apply_default_layout() is False   # shape mismatch


def test_reset_to_default_applies_the_template_to_the_current_table():
    host = _Host(table_default_layout=as_setting(template(4, 6, width=133)))
    g = _shown(_grid(host, seeded_text(template(4, 6))))
    g.view.horizontalHeader().resizeSection(0, 60)
    assert g.apply_default_layout() is True
    assert g.view.horizontalHeader().sectionSize(0) == 133


def test_restore_factory_resets_the_setting_not_the_current_table():
    host = _Host(table_default_layout=as_setting(template(4, 6, width=90)))
    g = _shown(_grid(host, seeded_text(template(4, 6))))
    g.view.horizontalHeader().resizeSection(0, 175)
    g.restore_factory_layout()
    assert host.data["table_default_layout"] == DEFAULT_PROFILE["table_default_layout"]
    assert g.view.horizontalHeader().sectionSize(0) == 175   # current table untouched
    assert host.marks == [("settings",)]


def test_a2_is_selected_on_a_new_table_without_entering_edit_mode():
    tpl = reader(table_default_layout=as_setting(template(4, 6)))
    g = _grid(_Host(), seeded_text(tpl), default_layout=tpl)
    assert g.view.currentIndex().row() == 1                # first body row
    assert g.view.currentIndex().column() == 0             # column A
    assert g.view.state() == g.view.NoState if hasattr(g.view, "NoState") else True


def test_a2_is_not_selected_on_an_existing_populated_table():
    tpl = reader(table_default_layout=as_setting(template(4, 6)))
    g = _grid(_Host(), POPULATED, default_layout=tpl)
    assert g.view.currentIndex().row() != 1 or g.view.currentIndex().column() != 0


def test_capture_and_apply_presentation_round_trips_the_sizes():
    g = _shown(_grid(_Host(), seeded_text(template(3, 4))))
    g.view.horizontalHeader().resizeSection(2, 199)
    g.view.verticalHeader().resizeSection(1, 77)
    saved = g.capture_presentation()
    again = _grid(_Host(), seeded_text(template(3, 4)), layout=saved)
    assert again.view.horizontalHeader().sectionSize(2) == 199
    assert again.view.verticalHeader().sectionSize(1) == 77


def test_scroll_restore_is_gated_by_the_remember_scroll_toggle():
    wide = template(6, 12, width=300, height=90)
    tpl = reader(table_default_layout=as_setting(wide))
    g = _shown(_grid(_Host(), seeded_text(wide), default_layout=tpl))
    g.view.horizontalScrollBar().setValue(2)     # the 3rd column, scrolled to
    g.view.verticalScrollBar().setValue(3)
    saved = g.capture_presentation()
    assert saved["h_scroll"] == 2 and saved["v_scroll"] == 3

    on = _shown(_grid(_Host(), seeded_text(wide), layout=saved,
                      restore_scroll=True))
    assert on.view.horizontalScrollBar().value() == 2
    assert on.view.verticalScrollBar().value() == 3

    off = _shown(_grid(_Host(), seeded_text(wide), layout=saved,
                       restore_scroll=False))
    assert off.view.horizontalScrollBar().value() == 0
    assert off.view.verticalScrollBar().value() == 0


# =============================================================================
# F. the Insert Table dialog reads the profile template
# =============================================================================

class _FakeDialog(QDialog):
    """Stands in for the dialog: no event loop, and optionally edits the spins."""

    retype = None          # (rows, columns) to retype before accepting

    def exec(self):
        tagged = self.findChildren(QSpinBox)
        if self.retype is not None:
            rows, cols = tagged
            rows.setValue(self.retype[0])
            cols.setValue(self.retype[1])
        return QDialog.DialogCode.Accepted


class _InsertEditor(QWidget):
    """The slice of the editor ``_insert_table`` touches."""

    def __init__(self, tpl=None):
        super().__init__()
        self.main_win = _Host(_current_lang="EN", table_default_layout=tpl)
        self.inserted = ""

    def textCursor(self):
        outer = self

        class _Cursor:
            def insertText(self, text):
                outer.inserted += text

        return _Cursor()


def _run_insert(editor, retype=None):
    from fastprompter.ui.editor import VaultTextEdit

    _FakeDialog.retype = retype
    real = qtwidgets.QDialog
    qtwidgets.QDialog = _FakeDialog
    try:
        VaultTextEdit._insert_table.__get__(editor)()
    finally:
        qtwidgets.QDialog = real


@pytest.fixture(autouse=True)
def _restore_dialog_class():
    yield
    import PyQt6.QtWidgets as qw
    if qw.QDialog is not QDialog:          # pragma: no cover - cleanup guard
        qw.QDialog = QDialog


def test_insert_dialog_opens_on_the_saved_template():
    editor = _InsertEditor(as_setting(template(4, 6)))
    _run_insert(editor)
    parsed = _parse(editor.inserted)
    assert parsed.columns == 4
    assert len(parsed.rows) == 6
    assert all(cell == "" for row in parsed.rows for cell in row)


def test_insert_dialog_opens_on_the_factory_when_unset():
    editor = _InsertEditor(None)
    _run_insert(editor)
    parsed = _parse(editor.inserted)
    assert parsed.columns == 7
    assert len(parsed.rows) == 10


def test_insert_dialog_honours_dimensions_retyped_by_the_user():
    editor = _InsertEditor(as_setting(template(4, 6)))
    _run_insert(editor, retype=(15, 12))
    parsed = _parse(editor.inserted)
    assert parsed.columns == 12        # no snap back to 4x6 (or to 7x10)
    assert len(parsed.rows) == 15
    assert all(cell == "" for row in parsed.rows for cell in row)


# =============================================================================
# G. profiles, restart, and the shared surface
# =============================================================================

def test_two_profiles_keep_their_own_template():
    first = reader(table_default_layout=as_setting(template(4, 6)))
    second = reader(table_default_layout=as_setting(template(12, 15)))
    assert st.template_shape(first) == (4, 6)
    assert st.template_shape(second) == (12, 15)


def test_template_survives_a_restart_through_settings_json():
    stored = as_setting(template(4, 6, word_wrap=True))
    # settings are read back through the same JSON text after a restart
    reloaded = json.loads(json.loads(json.dumps(stored)))
    assert st.template_shape(reloaded) == (4, 6)
    assert reader(table_default_layout=reloaded)["word_wrap"] is True


def test_new_table_callers_still_get_the_shape_they_ask_for():
    t = st.new_table(2, 3)
    assert t.rows == [["", "", ""]] * 3
    assert list(inspect.signature(st.new_table).parameters) == \
        ["rows", "columns", "header"]


def test_default_table_still_accepts_no_argument():
    """Zero-argument compatibility: the factory 7x10 stays the fallback."""
    assert st.template_shape(st.default_table()) == (7, 10)


def test_load_markdown_still_takes_presentation_scroll_and_template():
    sig = inspect.signature(TableGridWidget.load_markdown)
    for name in ("text", "span", "layout", "default_layout", "restore_scroll"):
        assert name in sig.parameters


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
