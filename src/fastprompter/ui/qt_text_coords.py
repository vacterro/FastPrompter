"""The ONE sanctioned bridge between Qt text positions and Python indexes.

T-1269: ``QTextCursor`` positions are ``QTextDocument`` positions, counted in
UTF-16 code units; Python ``str`` indexes count Unicode code points. The two
coordinate systems diverge the moment a non-BMP character (any emoji, CJK
extension-B, ...) is present -- one such character is two UTF-16 units but one
Python character. Indexing ``toPlainText()`` with a raw Qt position (or the
reverse) silently reads the wrong characters, so formatting spans a shifted
range while the splice lands on the right one: text disappears, duplicates or
is replaced by a neighbour.

THE SPAN CONTRACT (T-1269):

- Qt-side code keeps every position in Qt UTF-16 units and uses these two
  helpers ONLY where a Python string and a Qt position must meet. No
  encode/decode arithmetic scattered through call sites.
- A worker that scans a Python snapshot (the typo checker) keeps producing
  PYTHON code-point spans. The COMPLETE span list is converted to Qt UTF-16
  offsets exactly ONCE, at the GUI/document boundary, against the exact
  immutable snapshot the scan was accepted for -- never against newer text.
- ``editor._typo_spans`` stores QT UTF-16 offsets thereafter, so every
  consumer (underline painting, spelling menu hit test, word replacement)
  shares the same coordinate system.
"""

from __future__ import annotations


def qt_units(s: str) -> int:
    """How many UTF-16 code units ``s`` occupies (Qt's idea of its length)."""
    return len(s.encode("utf-16-le")) // 2


def py_to_qt(s: str, i: int) -> int:
    """Convert a Python code-point index in ``s`` to a Qt UTF-16 position."""
    if i <= 0:
        return 0
    if i >= len(s):
        return qt_units(s)
    return qt_units(s[:i])


def qt_to_py(s: str, i: int) -> int:
    """Convert a Qt UTF-16 position into a Python code-point index in ``s``.

    ``i`` is truncated to a code-point boundary: a position landing inside a
    surrogate pair (the boundary of an astral character) maps to the index of
    the character itself.
    """
    if i <= 0:
        return 0
    units = qt_units(s)
    if i >= units:
        return len(s)
    # UTF-16 units -> code points: every code point <= U+FFFF that is not a
    # surrogate occupies one unit; astral characters occupy two. Count the
    # surrogate starts (high surrogates) among the first i units.
    encoded = s.encode("utf-16-le")
    high = sum(1 for k in range(0, i * 2 - 1, 2)
               if 0xD800 <= (encoded[k] | (encoded[k + 1] << 8)) <= 0xDBFF)
    return i - high


def convert_spans_py_to_qt(s: str, spans) -> list[tuple[int, int]]:
    """Convert a COMPLETE list of Python code-point spans into Qt UTF-16 spans.

    Must be called exactly once, at the GUI/document boundary, with the same
    immutable text snapshot the spans were computed against.
    """
    out = []
    for start, end in spans:
        out.append((py_to_qt(s, start), py_to_qt(s, end)))
    return out
