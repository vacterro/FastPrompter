"""T-1408: the Ctrl+E header stamp can follow the silo's last edit.

"Follow last edit" (ctrl_e_follow_edit, default off) rewrites the date and
time on every stamped header in the open silo so it reads as the silo's last
edit rather than the moment the key was last pressed.

The property that matters and is easy to get wrong: it CONVERGES. The rewrite
dirties the document, which makes the flush save the new text, which is what
stops the next rewrite. An implementation that rewrote unconditionally would
leave an idle editor rewriting itself forever; the guard is that a stamp
already showing the right value is left alone, and that is asserted here.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QTextEdit

from fastprompter.core import header as header_core
from fastprompter.main import FastPrompter

EPOCH = datetime.datetime(2026, 3, 7, 18, 42, 0).timestamp()
STAMPED = "# Notes (07.03 - 14:05)"
LATER = "# Notes (07.03 - 18:42)"


# ── the Qt-free half ────────────────────────────────────────────────────────

def test_follow_edit_defaults_off_and_is_readable():
    assert header_core.DEFAULTS["ctrl_e_follow_edit"] == "False"
    assert header_core.read_settings({})["follow_edit"] is False
    assert header_core.read_settings(
        {"ctrl_e_follow_edit": "True"})["follow_edit"] is True


def test_pattern_round_trips_the_text_and_recognises_the_stamp():
    pat = header_core.stamp_line_pattern("{text} ({time})")
    line = header_core.header_line("{text} ({time})", "Notes", "07.03 - 14:05", "Day")
    assert pat.match(line).group(1) == "Notes"
    assert pat.match("# Section") is None, "a plain header is not a stamp"


def test_pattern_still_matches_a_template_with_no_time_field():
    # Ctrl+E must be able to recognise -- and therefore undo -- a line it
    # stamped under a {text}-only template, so the pattern must exist here.
    pat = header_core.stamp_line_pattern("{text}")
    assert pat.match("# Notes").group(1) == "Notes"


def test_time_text_is_one_format_for_every_caller():
    when = datetime.datetime(2026, 3, 7, 18, 42, 0)
    assert header_core.stamp_time_text(when, "%H:%M") == "07.03 - 18:42"
    assert header_core.stamp_time_text(when, "%H:%M", daypart=True) \
        == "Evening 07.03 - 18:42"
    assert header_core.stamp_time_text(when, "%H:%M", text_month=True) \
        == "07 Mar - 18:42"


# ── the window half ─────────────────────────────────────────────────────────

@pytest.fixture
def win(qapp):
    """A shell carrying the REAL refresh_header_stamp over a real editor."""
    w = SimpleNamespace(
        data={},
        text_area=QTextEdit(),
        editing_snippet=("Code", 0),
        mark_dirty=MagicMock(),
    )
    w._clock_time_fmt = lambda *a, **k: "%H:%M"
    w.refresh_header_stamp = FastPrompter.refresh_header_stamp.__get__(w)
    return w


def _open(win, text, follow="True"):
    win.data["ctrl_e_follow_edit"] = follow
    win.text_area.setPlainText(text)
    win.mark_dirty.reset_mock()


def test_the_stamp_moves_to_the_last_edit(win):
    _open(win, f"{STAMPED}\nbody")
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText().splitlines()[0] == LATER
    win.mark_dirty.assert_called_once()


def test_off_by_default_the_stamp_stays_where_ctrl_e_put_it(win):
    _open(win, f"{STAMPED}\nbody", follow="False")
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText().splitlines()[0] == STAMPED
    win.mark_dirty.assert_not_called()


def test_it_converges_instead_of_rewriting_an_idle_note(win):
    _open(win, f"{STAMPED}\nbody")
    win.refresh_header_stamp(0, EPOCH)
    settled = win.text_area.toPlainText()
    win.mark_dirty.reset_mock()
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText() == settled
    win.mark_dirty.assert_not_called(), "a settled stamp must not dirty again"


def test_a_hand_written_header_is_never_guessed_at(win):
    _open(win, "# Notes\n# 07.03 - 14:05")
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText() == "# Notes\n# 07.03 - 14:05"


def test_every_stamped_header_moves_when_stamp_every_is_on(win):
    _open(win, f"{STAMPED}\nmore\n{STAMPED}")
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText().splitlines() == [LATER, "more", LATER]


def test_a_background_silo_is_left_alone(win):
    _open(win, f"{STAMPED}\nbody")
    win.editing_snippet = ("Code", 3)
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText().splitlines()[0] == STAMPED


def test_a_template_with_no_time_field_changes_nothing(win):
    win.data["ctrl_e_follow_edit"] = "True"
    win.data["ctrl_e_format"] = "{text}"
    win.text_area.setPlainText("# Notes")
    win.refresh_header_stamp(0, EPOCH)
    assert win.text_area.toPlainText() == "# Notes"
