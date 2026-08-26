"""CORE-002 regression: global volume slider must normalize legacy "1".."10"
strings AND canonical "0.00".."1.00" floats through the canonical parser, so a
legacy-stored value no longer pins the slider to 100%.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.sound_manager import _parse_volume_value  # noqa: E402


def _slider_value(sound_volume):
    """Mirror of the main-window volume slider init (CORE-002 fix)."""
    vol = _parse_volume_value(sound_volume)
    if vol is None:
        vol = 0.15
    return max(0, min(100, int(round(vol * 100))))


def test_legacy_volume_not_pinned_to_100():
    # legacy 0-10 strings must map to 0-100 the same way as canonical floats
    assert _slider_value("0") == 0
    assert _slider_value("1") == 10
    assert _slider_value("5") == 50
    assert _slider_value("7") == 70
    assert _slider_value("10") == 100


def test_canonical_volume_preserved():
    assert _slider_value("0.15") == 15
    assert _slider_value("0.50") == 50
    assert _slider_value("1.00") == 100
    assert _slider_value(0.15) == 15
    assert _slider_value(0.5) == 50


def test_malformed_volume_falls_back():
    assert _slider_value("") == 15        # -> None -> default 0.15
    assert _slider_value("garbage") == 15
    assert _slider_value(None) == 15


def test_legacy_parser_boundaries():
    # values > 1.0 but <= 10.0 that look like legacy are divided by 10
    assert _parse_volume_value("5") == 0.5
    assert _parse_volume_value(5) == 0.5
    assert _parse_volume_value("0.5") == 0.5
    assert _parse_volume_value("11") == 1.0   # clamped
    assert _parse_volume_value("abc") is None
    assert _parse_volume_value(True) is None
