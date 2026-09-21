"""T-1269: formatting and typo spans must respect the Python/Qt offset boundary.

Root cause of the corruption this pins down: ``apply_format`` read
``QTextCursor.selectionStart()/selectionEnd()`` -- QTextDocument positions,
counted in UTF-16 code units -- and used them directly as Python ``str``
indexes, which count Unicode code points. The two coordinate systems diverge
as soon as a non-BMP character (emoji, CJK ext-B, ...) occurs before or
inside the selection: one such character is TWO UTF-16 units but ONE Python
character, so every later position is shifted and the wrong substring is
sliced, wrapped, and spliced back over the right Qt range -- characters
disappear, duplicate, or are replaced by their neighbours.

The fix keeps all position arithmetic in Qt coordinates (QTextCursor-native)
and the only Python/Qt bridge is ``fastprompter.ui.qt_text_coords``. These
tests exercise the REAL mixin against a REAL QTextEdit document.

The typo consumers share the same defect class and the same repair contract:
the Python-side scanner produces code-point spans; the complete list is
converted ONCE at the GUI/document boundary against the snapshot the scan was
accepted for; ``editor._typo_spans`` then stores Qt UTF-16 offsets for every
consumer (underline painting, spelling menu hit test, word replacement).
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextEdit

from fastprompter.ui.formatting_mixin import FormattingMixin
from fastprompter.ui.qt_text_coords import (
    convert_spans_py_to_qt,
    py_to_qt,
    qt_to_py,
    qt_units,
)

FAMILY = "\U0001F468\u200D\U0001F469\u200D\U0001F467\u200D\U0001F466"  # 👨‍👩‍👧‍👦
EMOJI = "\U0001F600"  # 😀


class _Host(FormattingMixin):
    """FormattingMixin expects a FastPrompter-like owner; only these exist."""

    def __init__(self):
        self.text_area = QTextEdit()
        self.data = {}
        self.dirty_calls = 0

    def mark_dirty(self):
        self.dirty_calls += 1


@pytest.fixture()
def host(qapp):
    h = _Host()
    yield h
    h.text_area.deleteLater()


def _select(ta, start, end):
    """Select [start, end) given in CODE POINTS (the user's logical view)."""
    text = ta.toPlainText()
    cur = ta.textCursor()
    cur.setPosition(py_to_qt(text, start))
    cur.setPosition(py_to_qt(text, end), QTextCursor.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)


def _selection_text(ta):
    cur = ta.textCursor()
    assert cur.hasSelection()
    return cur.selectedText().replace("\u2029", "\n")


VERBS = ["bold", "italic", "underline", "strike"]
MARKERS = {"bold": "**", "italic": "*", "underline": "__", "strike": "~~"}


# --------------------------------------------------------------------------
# the RED control: the old coordinate-mixing shape corrupts this exact input
# --------------------------------------------------------------------------

def test_red_control_italic_after_emoji(host):
    """'A😀BC', select B, italic -> 'A😀*B*C'.

    The old code sliced doc_text with the raw Qt positions (3..4, because
    the emoji costs two UTF-16 units) and got 'C'; it then spliced '*C*'
    over the CORRECT Qt range [3,4), which held B: B vanished, C duplicated.
    """
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)  # the B, by code points
    host.apply_format("italic")
    assert ta.toPlainText() == "A" + EMOJI + "*B*C"


def test_red_control_bold_after_emoji_all_verbs(host):
    ta = host.text_area
    for verb in VERBS:
        m = MARKERS[verb]
        ta.setPlainText("A" + EMOJI + "BC")
        _select(ta, 2, 3)
        host.apply_format(verb)
        assert ta.toPlainText() == "A" + EMOJI + f"{m}B{m}C", verb


# --------------------------------------------------------------------------
# RED CONTROL: the legacy algorithm, kept verbatim, must still corrupt
# --------------------------------------------------------------------------

def _legacy_apply_format(ta, marker):
    """The pre-T-1269 body of apply_format, reduced to its splice.

    Verbatim in the part that matters: Qt positions from the cursor, Python
    slicing of ``toPlainText()``. Kept as executable evidence so the defect
    class cannot silently come back as "it looks fine now" -- a regression
    that reintroduced mixed coordinates would make this control PASS its
    corruption assertions and the contract tests FAIL.
    """
    cursor = ta.textCursor()
    doc_text = ta.toPlainText()                       # PYTHON code points
    start, end = cursor.selectionStart(), cursor.selectionEnd()   # QT units
    sel = doc_text[start:end]                         # <-- the defect
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(f"{marker}{sel}{marker}")


def test_red_control_legacy_slicing_corrupts_non_bmp(host):
    """'A😀BC', select B, italic: the legacy splice loses B and duplicates C."""
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)  # the B, by code points -> Qt [3, 4)
    _legacy_apply_format(ta, "*")
    # Qt range [3,4) held 'B'; doc_text[3:4] (Python) is 'C'. The legacy code
    # wrapped 'C' and spliced it over 'B'.
    assert ta.toPlainText() == "A" + EMOJI + "*C*C"
    assert "B" not in ta.toPlainText(), "B survived -- control no longer red"

    # and the repaired implementation does NOT do that
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)
    host.apply_format("italic")
    assert ta.toPlainText() == "A" + EMOJI + "*B*C"


def test_red_control_legacy_typo_span_targets_wrong_range(qapp):
    """A raw Python span used as a document position underlines the wrong word."""
    ta = QTextEdit()
    ta.setPlainText("x " + EMOJI + " taer")
    text = ta.toPlainText()
    py_span = (text.index("taer"), text.index("taer") + 4)   # (4, 8)

    # legacy: the worker's code-point span stored and consumed as-is
    cur = ta.textCursor()
    cur.setPosition(py_span[0])
    cur.setPosition(py_span[1], QTextCursor.MoveMode.KeepAnchor)
    assert cur.selectedText() != "taer"
    assert cur.selectedText() == " tae"

    # repaired: converted once at the boundary
    qt_span = convert_spans_py_to_qt(text, [py_span])[0]
    cur.setPosition(qt_span[0])
    cur.setPosition(qt_span[1], QTextCursor.MoveMode.KeepAnchor)
    assert cur.selectedText() == "taer"
    ta.deleteLater()


# --------------------------------------------------------------------------
# the 12 contract case classes, across all four verbs
# --------------------------------------------------------------------------

@pytest.mark.parametrize("verb", VERBS)
def test_ascii_baseline(host, verb):
    m = MARKERS[verb]
    ta = host.text_area
    ta.setPlainText("abcdef")
    _select(ta, 2, 4)  # cd
    host.apply_format(verb)
    assert ta.toPlainText() == f"ab{m}cd{m}ef"
    assert _selection_text(ta) == "cd"
    assert host.dirty_calls >= 1


@pytest.mark.parametrize("verb", VERBS)
def test_non_bmp_before_selection(host, verb):
    m = MARKERS[verb]
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)  # B
    host.apply_format(verb)
    assert ta.toPlainText() == "A" + EMOJI + f"{m}B{m}C"
    assert _selection_text(ta) == "B"


@pytest.mark.parametrize("verb", VERBS)
def test_multiple_emoji_before_selection(host, verb):
    m = MARKERS[verb]
    ta = host.text_area
    ta.setPlainText(EMOJI + "\U0001F603" + "ABCDE")  # 😀😃ABCDE
    _select(ta, 4, 6)  # CD
    host.apply_format(verb)
    assert ta.toPlainText() == EMOJI + "\U0001F603" + f"AB{m}CD{m}E"
    assert _selection_text(ta) == "CD"


@pytest.mark.parametrize("verb", VERBS)
def test_emoji_inside_selection(host, verb):
    m = MARKERS[verb]
    ta = host.text_area
    ta.setPlainText("AB" + EMOJI + "CD")
    _select(ta, 1, 4)  # B😀C
    host.apply_format(verb)
    assert ta.toPlainText() == f"A{m}B" + EMOJI + f"C{m}D"
    assert _selection_text(ta) == "B" + EMOJI + "C"


@pytest.mark.parametrize("verb", VERBS)
def test_zwj_family_before_selection(host, verb):
    """A ZWJ family sequence is 7 code points but 11 UTF-16 units."""
    m = MARKERS[verb]
    # 4 astral characters (2 units each) + 3 U+200D joiners (1 each).
    assert qt_units(FAMILY) == 11 and len(FAMILY) == 7
    ta = host.text_area
    ta.setPlainText(FAMILY + "AB")
    _select(ta, 8, 9)  # the B
    host.apply_format(verb)
    assert ta.toPlainText() == FAMILY + f"A{m}B{m}"
    assert _selection_text(ta) == "B"


@pytest.mark.parametrize("verb", VERBS)
def test_cyrillic_emoji_latin_mixed(host, verb):
    m = MARKERS[verb]
    ta = host.text_area
    text = "Привет" + EMOJI + "мир abc"
    ta.setPlainText(text)
    _select(ta, 7, 10)  # мир
    host.apply_format(verb)
    assert ta.toPlainText() == "Привет" + EMOJI + f"{m}мир{m} abc"
    assert _selection_text(ta) == "мир"


def test_markers_inside_selection_unwraps(host):
    ta = host.text_area
    ta.setPlainText("x *cd* y")
    _select(ta, 2, 6)  # *cd*
    host.apply_format("italic")
    assert ta.toPlainText() == "x cd y"
    assert _selection_text(ta) == "cd"


def test_markers_outside_selection_unwraps_after_emoji(host):
    ta = host.text_area
    ta.setPlainText(EMOJI + "x *cd* y")
    # EMOJI(0) x(1) " "(2) *(3) c(4) d(5) *(6) " "(7) y(8)
    _select(ta, 4, 6)  # cd
    host.apply_format("italic")
    assert ta.toPlainText() == EMOJI + "x cd y"
    assert _selection_text(ta) == "cd"


def test_bold_italic_ambiguity_preserved(host):
    """Italic on 'bold' inside '**bold**' must NOT unbold (old rule kept)."""
    ta = host.text_area
    ta.setPlainText("**bold**")
    _select(ta, 2, 6)  # bold
    host.apply_format("italic")
    assert ta.toPlainText() == "***bold***"


@pytest.mark.parametrize("verb", VERBS)
def test_toggle_on_off_roundtrip_is_code_point_exact(host, verb):
    m = MARKERS[verb]
    for text, s, e in [
        ("abcdef", 2, 4),
        ("A" + EMOJI + "BC", 2, 3),
        (EMOJI + "\U0001F603" + "ABCDE", 4, 6),
        ("AB" + EMOJI + "CD", 1, 4),
        (FAMILY + "AB", 8, 9),
        ("Привет" + EMOJI + "мир", 7, 10),
    ]:
        ta = host.text_area
        ta.setPlainText(text)
        _select(ta, s, e)
        host.apply_format(verb)
        assert ta.toPlainText() == text[:s] + m + text[s:e] + m + text[e:], (
            verb, text)
        assert _selection_text(ta) == text[s:e]
        host.apply_format(verb)
        assert ta.toPlainText() == text, (verb, text)
        assert _selection_text(ta) == text[s:e]


@pytest.mark.parametrize("verb", VERBS)
def test_undo_redo_exact_roundtrip(host, verb):
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)
    host.apply_format(verb)
    formatted = ta.toPlainText()
    assert formatted != "A" + EMOJI + "BC"
    ta.undo()
    assert ta.toPlainText() == "A" + EMOJI + "BC"
    ta.redo()
    assert ta.toPlainText() == formatted


def test_no_selection_word_under_cursor_with_emoji_in_block(host):
    """Cursor genuinely INSIDE 'ab' -- between its two letters.

    EMOJI(0) " "(1) a(2) b(3) " "(4) c(5) d(6). Index 1 is the SPACE and
    index 2 is the word's leading BOUNDARY; only index 3 is unambiguously
    inside the word, so that is where the caret goes. Index 4 -- used by an
    earlier draft and described as "inside 'ab'" -- is the space AFTER it.
    """
    ta = host.text_area
    ta.setPlainText(EMOJI + " ab cd")
    text = ta.toPlainText()
    assert text[2] == "a" and text[3] == "b" and text[4] == " "
    cur = ta.textCursor()
    cur.setPosition(py_to_qt(text, 3))  # between 'a' and 'b'
    ta.setTextCursor(cur)
    host.apply_format("italic")
    assert ta.toPlainText() == EMOJI + " *ab* cd"
    cur = ta.textCursor()
    assert cur.hasSelection()
    assert cur.selectedText() == "ab"


def test_word_under_cursor_after_zwj_family(host):
    ta = host.text_area
    ta.setPlainText(FAMILY + " target")
    cur = ta.textCursor()
    cur.setPosition(py_to_qt(ta.toPlainText(), 9))  # inside 'target'
    ta.setTextCursor(cur)
    host.apply_format("bold")
    assert ta.toPlainText() == FAMILY + " **target**"


def test_apply_bold_smart_whole_line_with_emoji(host):
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC tail")
    cur = ta.textCursor()
    cur.setPosition(0)
    ta.setTextCursor(cur)
    host.apply_bold_smart()
    assert ta.toPlainText() == "**A" + EMOJI + "BC tail**"


def test_multiline_selection_keeps_paragraph_separators(host):
    """'first / A😀BC / third' -- select 'BC' + paragraph break + 'third'.

    Code points: f0 i1 r2 s3 t4 \\n5 A6 😀7 B8 C9 \\n10 t11 h12 i13 r14 d15,
    so 'BC\\nthird' is [8, 16) -- 16 code points in the document, 17 UTF-16
    units. Earlier drafts of this test claimed len 13 and range [4, 12),
    which is 't\\nA😀BC\\nt': neither the asserted text nor a word boundary.
    """
    ta = host.text_area
    text = "first\nA" + EMOJI + "BC\nthird"
    assert len(text) == 16
    assert text[8:16] == "BC\nthird"  # the logical range under test
    ta.setPlainText(text)
    _select(ta, 8, 16)  # 'BC' + paragraph separator + 'third'
    host.apply_format("bold")
    assert ta.toPlainText() == "first\nA" + EMOJI + "**BC\nthird**"
    assert _selection_text(ta) == "BC\nthird"
    host.apply_format("bold")
    assert ta.toPlainText() == text


def test_whitespace_stays_outside_markers(host):
    ta = host.text_area
    ta.setPlainText(EMOJI + "   ab   ")
    _select(ta, 1, 9)  # '   ab   '
    host.apply_format("italic")
    assert ta.toPlainText() == EMOJI + "   *ab*   "
    assert _selection_text(ta) == "ab"


def test_one_undo_edit_block_and_one_undo_step(host):
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)
    doc = ta.document()
    host.apply_format("italic")
    steps = 0
    while doc.isUndoAvailable() and steps < 5:
        ta.undo()
        steps += 1
    assert steps == 1, "one formatting operation must be exactly one undo step"


def test_focus_returns_to_editor(host):
    ta = host.text_area
    ta.setPlainText("A" + EMOJI + "BC")
    _select(ta, 2, 3)
    calls = []
    ta.setFocus = lambda *a, **k: calls.append(True)
    host.apply_format("italic")
    assert calls, "apply_format must hand focus back to the editor"


def test_apply_format_is_cursor_native_no_toplainstring_indexing():
    """Structural pin: apply_format must not index toPlainText() at all."""
    import inspect
    src = inspect.getsource(FormattingMixin.apply_format)
    assert "toPlainText()" not in src, (
        "apply_format must operate through QTextCursor, never through "
        "Python-indexed toPlainText() slices")


# --------------------------------------------------------------------------
# typo-span consumers: one Qt-coordinate contract
# --------------------------------------------------------------------------

def test_qt_py_roundtrip_helpers():
    for text in ("abcdef", "A" + EMOJI + "BC", EMOJI * 2 + "xyz", FAMILY, ""):
        for i in range(len(text) + 1):
            assert qt_to_py(text, py_to_qt(text, i)) == i
        assert qt_to_py(text, qt_units(text)) == len(text)


def test_qt_to_py_truncates_into_surrogate_boundary():
    text = "AB" + EMOJI + "CD"
    # Qt position 3 is INSIDE the emoji's surrogate pair -> the character
    # itself, code-point index 2.
    assert qt_to_py(text, 3) == 2
    assert qt_to_py(text, 4) == 3  # after the emoji


def test_typo_menu_hit_after_one_emoji(qapp, monkeypatch):
    """Menu cursor hit test uses the converted Qt span, not a shifted one."""
    from unittest.mock import MagicMock

    from fastprompter.main import FastPrompter

    ta = QTextEdit()
    ta.setPlainText("x " + EMOJI + " taer wrong")  # 'taer' is not a word
    text = ta.toPlainText()
    s = text.index("taer")
    e = s + 4
    # _typo_spans stores QT UTF-16 offsets per the T-1269 contract.
    ta._typo_spans = convert_spans_py_to_qt(text, [(s, e)])

    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_check_enabled": "True"}
    real_win.text_area = ta
    real_win._typo_dictionary = lambda: MagicMock(suggest=lambda w: ["tear"])
    real_win._typo_check_tick = lambda: None
    real_win._current_lang = "EN"

    menu = MagicMock()
    added = []
    menu.addAction.side_effect = lambda label, cb=None: (
        added.append((label, cb)) or MagicMock())

    for cp_index in (s, s + 1, s + 2, e - 1):  # first/middle/last character
        cur = ta.textCursor()
        cur.setPosition(py_to_qt(text, cp_index))
        ta.setTextCursor(cur)
        added.clear()
        assert real_win.build_spelling_menu(menu, None) is True, cp_index
        assert any("taer" in lbl for lbl, _ in added), (cp_index, added)

    # Apply the FIRST suggestion through the real callback: the replacement
    # must land exactly on the flagged word.
    cbs = [cb for lbl, cb in added if lbl.strip() == "tear" and cb]
    assert cbs, added
    cbs[0]()
    assert ta.toPlainText() == "x " + EMOJI + " tear wrong"
    # neighbours untouched
    assert ta.toPlainText().startswith("x " + EMOJI + " tear ")
    ta.deleteLater()


def test_typo_menu_hit_after_zwj_sequence(qapp):
    from unittest.mock import MagicMock

    from fastprompter.main import FastPrompter

    ta = QTextEdit()
    ta.setPlainText(FAMILY + " taer ok")
    text = ta.toPlainText()
    s = text.index("taer")
    e = s + 4
    ta._typo_spans = convert_spans_py_to_qt(text, [(s, e)])

    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_check_enabled": "True"}
    real_win.text_area = ta
    real_win._typo_dictionary = lambda: MagicMock(suggest=lambda w: ["tear"])
    real_win._typo_check_tick = lambda: None
    real_win._current_lang = "EN"

    menu = MagicMock()
    added = []
    menu.addAction.side_effect = lambda label, cb=None: (
        added.append((label, cb)) or MagicMock())

    for cp_index in (s, s + 1, e - 1):
        cur = ta.textCursor()
        cur.setPosition(py_to_qt(text, cp_index))
        ta.setTextCursor(cur)
        added.clear()
        assert real_win.build_spelling_menu(menu, None) is True, cp_index
        assert any("taer" in lbl for lbl, _ in added), (cp_index, added)
    ta.deleteLater()


def test_typo_menu_multiple_emoji_and_ascii_unchanged(qapp):
    from unittest.mock import MagicMock

    from fastprompter.main import FastPrompter

    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_check_enabled": "True"}
    real_win._typo_dictionary = lambda: MagicMock(suggest=lambda w: ["tear"])
    real_win._typo_check_tick = lambda: None
    real_win._current_lang = "EN"

    # multiple emoji before the flagged word
    ta = QTextEdit()
    ta.setPlainText(EMOJI + "\U0001F603 taer ok")
    text = ta.toPlainText()
    s = text.index("taer")
    ta._typo_spans = convert_spans_py_to_qt(text, [(s, s + 4)])
    real_win.text_area = ta
    menu = MagicMock()
    added = []
    menu.addAction.side_effect = lambda label, cb=None: (
        added.append((label, cb)) or MagicMock())
    cur = ta.textCursor()
    cur.setPosition(py_to_qt(text, s + 1))
    ta.setTextCursor(cur)
    assert real_win.build_spelling_menu(menu, None) is True
    assert any("taer" in lbl for lbl, _ in added)
    ta.deleteLater()

    # ASCII typo behaviour unchanged: still found with a plain cursor
    ta2 = QTextEdit()
    ta2.setPlainText("the taer is fine")
    text2 = ta2.toPlainText()
    s2 = text2.index("taer")
    ta2._typo_spans = convert_spans_py_to_qt(text2, [(s2, s2 + 4)])
    real_win.text_area = ta2
    menu2 = MagicMock()
    added2 = []
    menu2.addAction.side_effect = lambda label, cb=None: (
        added2.append((label, cb)) or MagicMock())
    cur2 = ta2.textCursor()
    cur2.setPosition(py_to_qt(text2, s2 + 1))
    ta2.setTextCursor(cur2)
    assert real_win.build_spelling_menu(menu2, None) is True
    assert any("taer" in lbl for lbl, _ in added2)
    ta2.deleteLater()


def test_typo_spans_stored_as_qt_offsets(qapp):
    """The contract: _typo_apply_spans converts the scan's code-point spans
    to Qt offsets exactly once, at the boundary, against the accepted
    snapshot's own text."""

    from fastprompter.main import FastPrompter

    ta = QTextEdit()
    ta.setPlainText("x " + EMOJI + " taer")
    snapshot = ta.toPlainText()
    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_color": "#e05555"}
    real_win.text_area = ta
    real_win._typo_check_tick = lambda: None
    # x(0) " "(1) EMOJI(2) " "(3) t(4) a(5) e(6) r(7)
    real_win._typo_apply_spans([(4, 8)])  # 'taer', code-point span from worker
    stored = ta._typo_spans
    assert stored == convert_spans_py_to_qt(snapshot, [(4, 8)])
    assert stored[0][0] == 5  # shifted by the emoji's extra UTF-16 unit
    # the Qt span must slice the DOCUMENT text correctly via selectedText-like
    # roundtrip: cursor over the span reads exactly 'taer'
    cur = ta.textCursor()
    cur.setPosition(stored[0][0])
    cur.setPosition(stored[0][1], QTextCursor.MoveMode.KeepAnchor)
    assert cur.selectedText() == "taer"
    ta.deleteLater()


def test_typo_underline_geometry_targets_exact_span(qapp):
    """Lower-level underline geometry: block-local positions must fall on the
    typo word, never shifted by preceding non-BMP text."""
    from fastprompter.main import FastPrompter
    from fastprompter.ui.editor import VaultTextEdit

    ed = VaultTextEdit(SimpleNamespace(
        data={}, highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000, _LARGE_DOC_BLOCK_THRESHOLD=2000))
    ed.setPlainText(EMOJI + " taer ok")
    ed.show()
    # QTextLine geometry only exists once the document has been laid out.
    ed.document().documentLayout().documentSize()
    qapp.processEvents()
    snapshot = ed.toPlainText()
    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_color": "#e05555"}
    real_win.text_area = ed
    real_win._typo_check_tick = lambda: None
    real_win._typo_apply_spans([(2, 6)])

    spans = ed._typo_spans
    doc = ed.document()
    for start, end in spans:
        block = doc.findBlock(start)
        assert block.isValid()
        local_s = start - block.position()
        local_e = end - block.position()
        # block-local positions are QT UTF-16 offsets; block.text() is a
        # PYTHON string, so reading it back needs the same conversion the
        # production code refuses to skip.
        block_text = block.text()
        py_s = qt_to_py(block_text, local_s)
        py_e = qt_to_py(block_text, local_e)
        assert block_text[py_s:py_e] == "taer", (local_s, local_e)
        # and the glyph geometry lands inside the line
        layout = block.layout()
        line = layout.lineForTextPosition(local_s)
        assert line.isValid()
        assert line.textStart() <= local_s
        assert local_e <= line.textStart() + line.textLength()
    assert snapshot.startswith(EMOJI)  # snapshot sanity
    ed.deleteLater()


def test_typo_apply_spans_against_current_document_only(qapp):
    """The conversion must run against the CURRENT document text -- after an
    edit a stale conversion would misplace spans; the revision check upstream
    (_on_typo_scanned) is what guarantees the snapshot is still current."""

    from fastprompter.main import FastPrompter

    ta = QTextEdit()
    ta.setPlainText("x " + EMOJI + " taer")
    real_win = FastPrompter.__new__(FastPrompter)
    real_win.data = {"typo_color": "#e05555"}
    real_win.text_area = ta
    real_win._typo_check_tick = lambda: None
    # spans for the CURRENT text convert and store correctly
    # x(0) " "(1) EMOJI(2) " "(3) t(4) a(5) e(6) r(7)
    real_win._typo_apply_spans([(4, 8)])
    assert ta.textCursor()  # no-op sanity
    cur = ta.textCursor()
    cur.setPosition(ta._typo_spans[0][0])
    cur.setPosition(ta._typo_spans[0][1], QTextCursor.MoveMode.KeepAnchor)
    assert cur.selectedText() == "taer"
    ta.deleteLater()
