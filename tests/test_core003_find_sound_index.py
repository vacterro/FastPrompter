"""CORE-003 regression: _find_sound_index must respect the named/file namespace
so a bare event name never resolves to a file of the same stem, and vice versa.
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
    # named events
    for n in ("click", "tick", "newday"):
        c.addItem(n, n)
    # files (display may carry a star; itemData is the canonical file: ref)
    for f in ("Click.wav", "GENIE.wav", "NEWDAY.wav"):
        c.addItem(f, f"file:{f}")
    return c


def test_named_resolves_to_named_not_file():
    c = _build()
    idx = td._find_sound_index(c, "click")
    assert c.itemData(idx) == "click"          # not "file:Click.wav"
    assert "file:" not in c.itemData(idx)


def test_file_ref_resolves_to_file():
    c = _build()
    idx = td._find_sound_index(c, "file:Click.wav")
    assert c.itemData(idx) == "file:Click.wav"


def test_file_ref_case_insensitive():
    c = _build()
    idx = td._find_sound_index(c, "file:click.wav")
    assert c.itemData(idx) == "file:Click.wav"


def test_legacy_wav_alias_resolves_to_file():
    c = _build()
    idx = td._find_sound_index(c, "Click.wav")   # legacy unprefixed
    assert c.itemData(idx) == "file:Click.wav"


def test_named_never_matches_file_stem():
    c = _build()
    # "tick" must NOT resolve to a file named tick.wav (none here, but ensure no
    # file: item is returned for a named query)
    idx = td._find_sound_index(c, "newday")
    assert c.itemData(idx) == "newday"


def test_exact_file_passthrough():
    c = _build()
    # a stored exact file ref selects the file item as-is
    idx = td._find_sound_index(c, "file:GENIE.wav")
    assert c.itemData(idx) == "file:GENIE.wav"
