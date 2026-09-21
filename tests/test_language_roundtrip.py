"""Language round-trip: switching away from English and back must restore it.

The old retranslate pass took the label's *current* text as the English base
and only called setText when the translation differed from that base. Both
halves were wrong:

  * base-from-display is a one-way trip - once a label reads Arabic there is
    no reverse map back to the English key, so it stays Arabic forever;
  * `if translated != en` skipped setText for lang == EN, so returning to
    English never repainted anything.

Together they produced the reported symptom: a UI showing "English" in the
language box while half the settings labels were still Arabic.

Also guards the source tree against the UTF-8-read-as-cp1251 mojibake that a
PowerShell-based edit pass baked into main.py (549 occurrences: every dash,
ellipsis and icon glyph in the top bar turned into Cyrillic soup).
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QLabel

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_lang_")


@pytest.fixture(scope="module")
def window():
    # Every patch here is restored on the way out: leaving `get_db_path`
    # pointed at this module's temp dir made unrelated test files later in the
    # session share a database and crash the interpreter.
    import fastprompter.utils.portable_backup as backup_mod
    saved = [
        # `state.py` imports run_portable_backup INSIDE the save, so the
        # owning module is the place to patch it. Hanging an attribute on
        # `state_mod` instead only worked because another test file had put
        # one there first -- an order dependency that made this module pass
        # in a full run and error out on its own.
        (state_mod, "get_db_path",
         lambda profile_id=1: os.path.join(_tmpdir, f"lang_{profile_id}.db")),
        (backup_mod, "run_portable_backup",
         lambda data, profile_id=1, **_kw: None),
        (FastPrompter, "setup_single_instance_server", lambda self: None),
        (FastPrompter, "register_all_hotkeys", lambda self: None),
        (FastPrompter, "unregister_all_hotkeys", lambda self: None),
    ]
    _MISSING = object()
    originals = [(owner, name, getattr(owner, name, _MISSING))
                 for owner, name, _ in saved]
    for owner, name, replacement in saved:
        setattr(owner, name, replacement)

    w = FastPrompter()
    w.resize(1024, 640)
    w.show()
    _app.processEvents()
    # Settings tabs are built lazily on first reveal.
    w.mini_settings_frame.setVisible(True)
    _app.processEvents()

    yield w

    # Revealing the settings frame arms a pile of deferred timers (profile
    # apply, scale, autosave...). Any one still running when the window's C++
    # side goes away fires into freed memory and takes the whole pytest
    # process down with an access violation, several test FILES later. Stop
    # every timer the window owns, not just the four with attribute names.
    for timer in w.findChildren(QTimer):
        timer.stop()
    service = getattr(w, "limit_service", None)
    if service is not None:
        service.shutdown()          # its worker threads outlive the window
    if getattr(w, "state", None) is not None:
        w.state.conn = None
    w.conn = None
    w.hide()
    w.close()
    # Deliberately NOT deleteLater(): actually freeing the C++ window here
    # let a straggling callback land in freed memory and killed the whole
    # pytest process with an access violation inside an unrelated test file
    # (tests/test_limit_alert_copy.py) ~20% into the session. A stopped,
    # hidden, closed window is inert; the process exit reclaims it. Same
    # shape as tests/test_t1227_silo_integrity.py's fixture.

    for owner, name, value in originals:
        if value is _MISSING:
            # It never existed: restoring a stub would leave the same kind of
            # cross-file landmine this fixture was fixed to stop planting.
            try:
                delattr(owner, name)
            except AttributeError:
                pass
        else:
            setattr(owner, name, value)


def _stamped_labels(w):
    return [lbl for lbl in w.mini_settings_frame.findChildren(QLabel)
            if getattr(lbl, "_en_text", None)]


def test_every_static_settings_label_keeps_its_english_source(window):
    """A label with no `_en_text` can never be brought back from a foreign script."""
    labels = _stamped_labels(window)
    assert labels, "no settings label carries an English source string"
    stamped = {lbl._en_text for lbl in labels}
    for expected in ("Font:", "Theme:", "View:", "Volume:", "Silo list"):
        assert expected in stamped, f"{expected!r} label lost its English base"


@pytest.mark.parametrize("lang", ["AR", "JA", "RU", "DED"])
def test_language_round_trip_restores_english(window, lang):
    """EN -> <lang> -> EN must land back on the exact English source text."""
    w = window
    before = {id(lbl): lbl.text() for lbl in _stamped_labels(w)}

    w._on_language_changed(lang)
    _app.processEvents()

    w._on_language_changed("EN")
    _app.processEvents()

    after = {id(lbl): lbl.text() for lbl in _stamped_labels(w)}
    assert after == before, f"labels stayed in {lang} after switching back to EN"

    for lbl in _stamped_labels(w):
        assert lbl.text() == lbl._en_text


def test_settings_tab_titles_round_trip(window):
    """Window/Editor/Clock/Data were translated once at build and never again.

    Same one-way trip the labels used to take, one level up: switch to a
    language, come back, and the tab bar was still in the old one.
    """
    w = window
    tabs = w.settings_tabs
    english = [tabs.tabText(i) for i in range(tabs.count())]
    assert english[:4] == ["Window", "Editor", "Clock", "Data"]

    w._on_language_changed("RU")
    _app.processEvents()
    russian = [tabs.tabText(i) for i in range(tabs.count())]
    assert russian != english, "tab titles never picked up the new language"

    w._on_language_changed("EN")
    _app.processEvents()
    assert [tabs.tabText(i) for i in range(tabs.count())] == english


_LEGACY_CHECKBOX_NAMES = (
    # The hand-typed tuple `_apply_settings_language` used to iterate. It is
    # kept HERE, in the test, as the floor the discovery walk must clear: the
    # refactor from "list of 38 names" to "find the widgets carrying
    # `_en_text`" is only safe if it loses nobody.
    "cb_top", "cb_lock_window", "cb_normal_window", "cb_tray",
    "cb_sidebar", "cb_focus", "cb_snippet_arrows", "cb_silo_ticks",
    "cb_ctrl_c", "cb_lock_cursor", "cb_silo_home", "cb_portable_backup",
    "cb_custom_cursors", "cb_static_cursor",
    "cb_wrap", "cb_line_numbers", "cb_line_marks", "cb_zebra",
    "cb_hide_shortkeys", "cb_double_line", "cb_bold_titles",
    "cb_silo_pinned_gap", "cb_date_rect", "cb_date_seconds",
    "cb_analog_clock", "cb_date_daypart", "cb_date_emoji",
    "cb_date_text_month", "cb_date_ampm", "cb_limit_gauges", "cb_sound",
    "cb_typewriter", "cb_trash_vision", "cb_silo_color_box",
    "cb_typo_check", "cb_passed_alert", "cb_sync_recursive", "cb_sync_live",
)


def test_checkbox_discovery_covers_every_legacy_name(window):
    found = {id(cb) for cb in window._translatable_checkboxes()}
    missed = []
    for name in _LEGACY_CHECKBOX_NAMES:
        cb = getattr(window, name, None)
        if cb is None:
            continue          # the widget itself was removed; not our problem
        if id(cb) not in found:
            missed.append(name)
    assert not missed, f"discovery walk lost: {missed}"


def test_checkbox_discovery_finds_more_than_the_old_list(window):
    """The point of the walk is that it also picks up what nobody listed."""
    assert len(window._translatable_checkboxes()) >= len(_LEGACY_CHECKBOX_NAMES)


def test_every_discovered_checkbox_round_trips(window):
    w = window
    stamped = [cb for cb in w._translatable_checkboxes()
               if getattr(cb, "_en_text", None)]
    assert stamped, "no checkbox carries an English source string"
    before = {id(cb): cb.text() for cb in stamped}

    w._on_language_changed("JA")
    _app.processEvents()
    w._on_language_changed("EN")
    _app.processEvents()

    after = {id(cb): cb.text() for cb in stamped}
    assert after == before


_LEGACY_BUTTON_NAMES = (
    # The eight names the button pass used to iterate.
    "btn_hotkeys", "btn_colors", "btn_backup", "btn_restore", "btn_exit",
    "btn_typo_colour", "btn_typo_clear", "btn_passed_colour",
)


def test_button_discovery_covers_every_legacy_name(window):
    found = {id(b) for b in window._translatable_buttons()}
    missed = [n for n in _LEGACY_BUTTON_NAMES
              if getattr(window, n, None) is not None
              and id(getattr(window, n)) not in found]
    assert not missed, f"discovery walk lost: {missed}"


def test_buttons_the_old_list_forgot_are_now_translated(window):
    """Both of these carry `_en_text` and neither was in the eight names."""
    found = {id(b) for b in window._translatable_buttons()}
    for name in ("btn_exit_app", "btn_sound_settings"):
        btn = getattr(window, name, None)
        assert btn is not None, f"{name} no longer exists"
        assert getattr(btn, "_en_text", None), f"{name} lost its English base"
        assert id(btn) in found, f"{name} is still not reachable"


def test_every_discovered_button_round_trips(window):
    w = window
    stamped = [b for b in w._translatable_buttons()
               if getattr(b, "_en_text", None)]
    assert stamped, "no button carries an English source string"
    before = {id(b): b.text() for b in stamped}

    w._on_language_changed("AR")
    _app.processEvents()
    w._on_language_changed("EN")
    _app.processEvents()

    assert {id(b): b.text() for b in stamped} == before


def test_switch_to_language_actually_translates(window):
    """Guard against "fixing" the round trip by never translating at all."""
    w = window
    w._on_language_changed("RU")
    _app.processEvents()
    texts = {lbl.text() for lbl in _stamped_labels(w)}
    assert any(re.search(r"[Ѐ-ӿ]", t) for t in texts), \
        "no settings label picked up Russian"


_SOURCE_ROOTS = ("src", "tools", "tests", "tests_smoke")

# What a repaired run is allowed to be. Every glyph the corruption ate was a
# symbol, dash, arrow or emoji - never a letter. Real Cyrillic prose can also
# round-trip through cp1251 into *some* valid UTF-8 (Ukrainian "дії"
# decodes to U+4CFF), so the decoded side has to be checked too, not just
# whether it decodes at all.
_SYMBOL_RANGES = (
    (0x00A0, 0x00BF),    # section sign, middle dot, guillemets
    (0x2000, 0x2BFF),    # dashes, bullets, arrows, box drawing, geometric
    (0xFE00, 0xFE0F),    # variation selectors
    (0x1F000, 0x1FAFF),  # emoji
)


def _repair(run):
    """Undo one UTF-8-read-as-cp1251 pass, or None if that is not what happened."""
    raw = bytearray()
    for ch in run:
        o = ord(ch)
        if 0x80 <= o <= 0x9F:  # C1 controls carry their byte value through
            raw.append(o)
            continue
        try:
            raw += ch.encode("cp1251")
        except UnicodeEncodeError:
            return None
    if len(raw) < 2:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if decoded == run:
        return None
    for ch in decoded:
        o = ord(ch)
        if not any(lo <= o <= hi for lo, hi in _SYMBOL_RANGES):
            return None
    return decoded


def test_no_mojibake_in_source_tree():
    """Every non-ASCII run must be text, not UTF-8 misread as cp1251."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for root in _SOURCE_ROOTS:
        for path in (repo / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.resolve() == pathlib.Path(__file__).resolve():
                continue  # this module carries mojibake fixtures on purpose
            text = path.read_bytes().decode("utf-8")
            for run in set(re.findall(r"[^\x00-\x7f]+", text)):
                fixed = _repair(run)
                if fixed is not None:
                    bad.append(f"{path.relative_to(repo)}: {run!a} should be {fixed!a}")
    assert not bad, "mojibake in source:\n" + "\n".join(sorted(set(bad))[:20])


def test_mojibake_detector_catches_the_real_corruption():
    """The detector must fire on the exact byte patterns that shipped in main.py."""
    assert _repair("вЂ”") == "—"          # em dash
    assert _repair("рџ“Ѓ") == "\U0001f4c1"  # file folder
    assert _repair("дії") is None                # real Ukrainian
    assert _repair("заметка") is None  # real Russian
