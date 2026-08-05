"""T-738: a silo dragged out of the app lands as a named .md file."""

import datetime
import os

WHEN = datetime.datetime(2026, 8, 5, 17, 30)


def test_a_header_becomes_the_name():
    from fastprompter.core.silo_export import drag_filename
    assert drag_filename("# Fix the parser\n\nbody", WHEN) == \
        "Fix the parser_20260805_1730.md"


def test_prose_gives_the_first_three_words():
    from fastprompter.core.silo_export import drag_filename
    assert drag_filename("alpha beta gamma delta epsilon", WHEN) == \
        "alpha beta gamma_20260805_1730.md"


def test_bullets_and_checkboxes_are_not_part_of_the_name():
    from fastprompter.core.silo_export import drag_filename
    assert drag_filename("- [ ] buy milk today please", WHEN) == \
        "buy milk today_20260805_1730.md"
    assert drag_filename("\u2022 one two three four", WHEN) == \
        "one two three_20260805_1730.md"


def test_illegal_characters_never_reach_the_filename():
    from fastprompter.core.silo_export import drag_filename
    name = drag_filename(r'# a/b\c:d*e?f"g<h>i|j', WHEN)
    assert not set(name) & set(r'\/:*?"<>|'), name
    assert name.endswith("_20260805_1730.md")


def test_an_empty_silo_still_gets_a_name():
    from fastprompter.core.silo_export import drag_filename
    assert drag_filename("", WHEN) == "silo_20260805_1730.md"
    assert drag_filename("\n\n   \n", WHEN) == "silo_20260805_1730.md"


def test_the_written_file_holds_the_exact_text(tmp_path, monkeypatch):
    from fastprompter.core import silo_export
    monkeypatch.setattr(silo_export, "scratch_dir", lambda: str(tmp_path))
    text = "# Title\n\nline one\nline two\n"
    path = silo_export.write_drag_file(text, WHEN)
    assert path and os.path.basename(path) == "Title_20260805_1730.md"
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == text


def test_two_drags_in_one_minute_do_not_overwrite(tmp_path, monkeypatch):
    from fastprompter.core import silo_export
    monkeypatch.setattr(silo_export, "scratch_dir", lambda: str(tmp_path))
    a = silo_export.write_drag_file("# Same\nfirst", WHEN)
    b = silo_export.write_drag_file("# Same\nsecond", WHEN)
    assert a != b, "the second drag overwrote the first"
    with open(a, encoding="utf-8") as fh:
        assert "first" in fh.read()
    with open(b, encoding="utf-8") as fh:
        assert "second" in fh.read()
