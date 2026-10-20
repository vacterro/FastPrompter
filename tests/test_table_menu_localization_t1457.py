"""T-1457 Stage 3: the table context menu is translated and the row/column
move operations are reachable from it.

The defect this pins: every entry in the grid's context menu was a literal
English string -- "Insert row above", "Delete column", "Auto-fit", ... -- so a
Russian or Estonian user got an English menu inside an otherwise translated
window. The widget's row/column MOVE commands existed and worked, but nothing
in the user-facing menu reached them, which is the "inaccessible custom
control" half of the same complaint.

Three things are asserted here, in the order they can break:

* STRUCTURE -- every visible label in the menu is produced by a lookup, never
  a literal, and the four move entries delegate to the ONE move implementation
  instead of a second copy of the swapping logic (AST scan of the real source).
* LOOKUP -- the labels resolve through the shipped translation architecture
  for English, Russian and Estonian (the three the ticket names).
* REACHABILITY -- the entries really are in the menu a user opens, they are
  QActions (so the keyboard and a screen reader can reach them), and
  triggering one performs the move.
"""

from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QWidget  # noqa: E402

from fastprompter.core.translations import tr  # noqa: E402
from fastprompter.ui.table_grid import TableGridWidget  # noqa: E402

_APP = QApplication.instance() or QApplication([])

_SOURCE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../src/fastprompter/ui/table_grid.py"))

TABLE = (
    "| Name | Qty | Note |\n"
    "| :--- | ---: | :---: |\n"
    "| apple | 3 | red |\n"
    "| pear | 12 | green |\n"
)

#: Every label the menu shows, in the order it shows them.
MENU_KEYS = (
    "Insert row above", "Insert row below", "Delete row(s)",
    "Insert column left", "Insert column right", "Delete column",
    "Move row up", "Move row down", "Move column left", "Move column right",
    "Align left", "Align center", "Align right",
    "Auto-fit", "Reset Size",
    "Copy", "Cut", "Paste",
)

MOVE_KEYS = (
    "Move row up", "Move row down", "Move column left", "Move column right",
)

LANGS = ("EN", "RU", "EST")


def _grid(text=TABLE, lang=None):
    parent = None
    if lang is not None:
        parent = QWidget()
        parent._current_lang = lang
    g = TableGridWidget(parent)
    # Qt owns the child, Python owns the parent: without a reference to the
    # parent, it is collected and takes the grid's C++ object with it.
    g._lang_parent = parent
    g.load_markdown(text)
    return g


def _class_node(name):
    tree = ast.parse(open(_SOURCE, encoding="utf-8").read(), _SOURCE)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {_SOURCE}")


def _method(name):
    for node in _class_node("TableGridWidget").body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == name:
            return node
    raise AssertionError(f"{name} not found in TableGridWidget")


# ------------------------------------------------------------- 1. structure

def test_every_menu_label_goes_through_the_lookup_not_a_literal():
    """One literal label is all it takes for one language to regress."""
    literals = []
    for node in ast.walk(_method("_show_context_menu")):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "addAction"):
            continue
        assert node.args, "addAction with no label"
        label = node.args[0]
        ok = (isinstance(label, ast.Call)
              and isinstance(label.func, ast.Attribute)
              and label.func.attr == "_menu_label")
        if not ok:
            literals.append(ast.unparse(label))
    assert not literals, f"literal menu labels: {literals}"


def test_the_move_entries_are_one_line_delegations_not_a_second_implementation():
    """A copy of the swap logic would drift from the keyboard path."""
    expected = {
        "_menu_move_row_up": "swap_row_up",
        "_menu_move_row_down": "swap_row_down",
        "_menu_move_col_left": "swap_col_left",
        "_menu_move_col_right": "swap_col_right",
    }
    for handler, target in expected.items():
        body = [n for n in _method(handler).body if not isinstance(n, ast.Expr)
                or not isinstance(n.value, ast.Constant)]
        assert len(body) == 1, f"{handler} should be one statement"
        call = body[0].value
        assert isinstance(call, ast.Call)
        assert ast.unparse(call.func) == f"self.{target}"


def test_the_model_move_is_called_from_exactly_one_place():
    """The single implementation: swap_* is the only caller of the model."""
    tree = ast.parse(open(_SOURCE, encoding="utf-8").read(), _SOURCE)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("move_row", "move_column")]
    owners = {ast.unparse(n.func) for n in calls}
    assert owners == {"self.model.move_row", "self.model.move_column"}
    # and no module-level or duplicate helper re-implements it
    assert not any(isinstance(n, ast.FunctionDef)
                   and n.name in ("move_row", "move_column")
                   for n in ast.walk(tree))


# ---------------------------------------------------------------- 2. lookup

@pytest.mark.parametrize("key", MENU_KEYS)
@pytest.mark.parametrize("lang", LANGS)
def test_menu_label_is_the_translated_string(key, lang):
    g = _grid(lang=lang)
    assert g._menu_label(key) == tr(key, lang)


@pytest.mark.parametrize("key", MENU_KEYS)
def test_english_labels_are_the_source_text(key):
    g = _grid(lang="EN")
    assert g._menu_label(key) == key


@pytest.mark.parametrize("key", MENU_KEYS)
@pytest.mark.parametrize("lang", ("RU", "EST"))
def test_russian_and_estonian_labels_are_not_left_in_english(key, lang):
    g = _grid(lang=lang)
    assert g._menu_label(key) != key


def test_estonian_labels_are_the_real_estonian_words():
    """An anchor: a lookup that returned English would still pass the above."""
    g = _grid(lang="EST")
    assert g._menu_label("Insert row above") == "Lisa rida üles"
    assert g._menu_label("Move column right") == "Liiguta veerg paremale"
    assert g._menu_label("Auto-fit") == "Automaatne sobitamine"


def test_the_language_comes_from_the_widget_that_owns_the_grid():
    """The grid is not a QWidget with its own tr override; the owner decides."""
    parent = QWidget()
    parent._current_lang = "EST"
    g = TableGridWidget(parent)
    g._lang_parent = parent
    assert g._menu_label("Delete column") == tr("Delete column", "EST")


def test_a_grid_with_no_language_anywhere_still_resolves():
    g = TableGridWidget()
    assert g._menu_label("Align left") == tr("Align left", None)


def test_the_shortcut_hint_is_appended_to_the_clipboard_entries():
    g = _grid(lang="EN")
    assert g._menu_label("Copy", "Ctrl+C") == "Copy\tCtrl+C"
    assert g._menu_label("Paste", "Ctrl+V") == tr("Paste", "EN") + "\tCtrl+V"


# ----------------------------------------------------------- 3. reachability

def _open_menu(g):
    """The menu a user actually gets, captured instead of popped up."""
    seen = {}
    original = QMenu.exec

    def fake(self, *args, **kwargs):
        seen["menu"] = self
        return None

    QMenu.exec = fake
    try:
        g._show_context_menu(QPoint(0, 0))
    finally:
        QMenu.exec = original
    assert "menu" in seen, "no menu was opened"
    return seen["menu"]


def _action_labels(menu):
    """The visible label of each entry, with its shortcut column stripped."""
    return [a.text().split("\t")[0] for a in menu.actions() if a.text()]


@pytest.mark.parametrize("lang", LANGS)
def test_the_open_menu_shows_the_move_entries_in_the_user_language(lang):
    g = _grid(lang=lang)
    labels = _action_labels(_open_menu(g))
    for key in MENU_KEYS:
        assert g._menu_label(key) in labels
    for key in MOVE_KEYS:
        assert tr(key, lang) in labels


def test_the_menu_entries_are_qactions_so_the_keyboard_can_reach_them():
    g = _grid(lang="EN")
    actions = [a for a in _open_menu(g).actions() if a.text()]
    assert actions
    for action in actions:
        assert isinstance(action, QAction)
        assert action.isEnabled()


def test_the_add_controls_are_buttons_with_translated_accessible_names():
    """The other half of the same defect: a QLabel is not tab-reachable."""
    g = _grid(lang="EST")
    for button, key in ((g.btn_add_col, "Add Column"), (g.btn_add_row, "Add Row")):
        assert button.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert button.accessibleName() == tr(key, "EST")
        assert button.toolTip() == tr(key, "EST")


def test_triggering_the_move_entry_actually_moves_the_row():
    g = _grid(lang="EN")
    g.view.setCurrentIndex(g.model.index(1, 0))
    menu = _open_menu(g)
    entry = [a for a in menu.actions()
             if a.text() == g._menu_label("Move row down")][0]
    entry.trigger()
    assert g.model.rows[2][0] == "apple"
    assert g.model.rows[1][0] == "pear"


def test_triggering_the_move_column_entry_actually_moves_the_column():
    g = _grid(lang="EST")
    g.view.setCurrentIndex(g.model.index(1, 0))
    menu = _open_menu(g)
    entry = [a for a in menu.actions()
             if a.text() == g._menu_label("Move column right")][0]
    entry.trigger()
    assert g.model.rows[1][:2] == ["3", "apple"]
