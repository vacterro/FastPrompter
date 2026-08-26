"""CORE-005 regression: _set_combo_sound must show a '(missing)' entry carrying
the original ref when a stored sound is absent, so it survives save/reload and is
never silently swapped for a fallback.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402

app = QApplication.instance() or QApplication([])

import fastprompter.ui.timer_dialog as td  # noqa: E402


def _build():
    c = QComboBox()
    for n in ("click", "tick"):
        c.addItem(n, n)
    for f in ("QUEST.wav", "NEWDAY.wav"):
        c.addItem(f, f"file:{f}")
    return c


def test_missing_ref_shows_marker_with_original_data():
    c = _build()
    td._set_combo_sound(c, "file:GHOST.wav")
    assert c.itemText(c.currentIndex()) == "<file:GHOST.wav> (missing)"
    assert c.currentData() == "file:GHOST.wav"   # itemData preserves the ref


def test_missing_marker_not_duplicated():
    c = _build()
    td._set_combo_sound(c, "file:GHOST.wav")
    td._set_combo_sound(c, "file:GHOST.wav")   # call again
    markers = [c.itemText(i) for i in range(c.count())
               if c.itemText(i).endswith("(missing)")]
    assert markers == ["<file:GHOST.wav> (missing)"]


def test_resolved_ref_selects_existing():
    c = _build()
    td._set_combo_sound(c, "click")
    assert c.currentData() == "click"
    # no missing marker added for a real choice
    assert not any(c.itemText(i).endswith("(missing)")
                 for i in range(c.count()))


def test_legacy_wav_missing_ref():
    c = _build()
    td._set_combo_sound(c, "MISSING.wav")   # legacy unprefixed, not in library
    assert c.currentData() == "MISSING.wav"
    assert c.itemText(c.currentIndex()) == "<MISSING.wav> (missing)"


def test_empty_ref_is_noop():
    c = _build()
    td._set_combo_sound(c, "")
    assert not any(c.itemText(i).endswith("(missing)")
                 for i in range(c.count()))
