"""Smoke tests for the new feature block: typecheck underlines, Sync-Project
two-way sync, per-silo file links, and the passed-event red date alert.

These boot the real window (the shared ``win`` fixture) and drive the same
methods the UI calls, so wiring mistakes (missing attributes, wrong store
names, watcher not re-armed) fail here instead of at the user's desk.
"""

import datetime
import os

from fastprompter.core.timers import Timer


def _set_silo(win, text):
    win.data["temp_presets"][0] = text
    win._switch_to_slot(0, initial=True, is_archive=False)


def _edit_silo(win, idx, text):
    """Simulate the user editing a silo in the app: the editor is the live
    source of truth for the ACTIVE slot (that is what ``_push_sync_files``
    reads), and the cache timer keeps ``temp_presets`` in sync with it."""
    win.data["temp_presets"][idx] = text
    if idx == getattr(win, "active_temp_slot", -1):
        win.text_area.setPlainText(text)


# ---------------------------------------------------------------- typecheck


def test_typo_check_underlines_flagged_words(win):
    win.data["typo_check_enabled"] = "True"
    _set_silo(win, "the wrold is fine")
    win._typo_check_tick()
    spans = win.text_area._typo_spans
    words = [win.text_area.toPlainText()[s:e] for s, e in spans]
    assert "wrold" in words
    assert "fine" not in words
    # the editor exposes the colour the painter will use
    assert win.text_area._typo_color


def test_typo_check_off_clears_spans(win):
    win.data["typo_check_enabled"] = "False"
    _set_silo(win, "the wrold")
    win._typo_check_tick()
    assert win.text_area._typo_spans == []


def test_add_typo_word_clears_the_flag(win):
    win.data["typo_check_enabled"] = "True"
    _set_silo(win, "fastprompterx is here")
    win._typo_check_tick()
    assert win.text_area._typo_spans
    win._add_typo_word("fastprompterx")
    assert not win.text_area._typo_spans
    assert "fastprompterx" in win.data["typo_user_words"]


# ------------------------------------------------------------- Sync-Project


def _convert_project(win, folder):
    files = sorted(p for p in os.listdir(folder)
                   if os.path.isfile(os.path.join(folder, p)))
    cfg = {
        "root": os.path.abspath(folder),
        "recursive": True,
        "include": [".txt", ".md"],
        "exclude": [],
        "enabled": True,
    }
    cat = win.get_current_category() or "Text"
    win.data["project_sync"] = cfg
    win.data.setdefault("project_sync_all", {})[cat] = cfg
    mapping = win.data.setdefault("project_sync_map", {})
    win.data.setdefault("project_sync_map_all", {})[cat] = mapping
    mapping.clear()
    from fastprompter.core import project_sync as ps
    presets = win.data["temp_presets"]
    for slot, rel in enumerate(files):
        path = os.path.join(cfg["root"], rel)
        text, _eol = ps.read_text_file(path)
        while len(presets) <= slot:
            presets.append("")
        presets[slot] = text
        mapping[str(slot)] = rel
        win._sync_last_applied[path] = text
    win._start_project_watcher()
    # load silo 0 into the editor so the ACTIVE slot reflects the converted
    # content (the editor is the live source for app->file pushes)
    win._switch_to_slot(0, initial=True, is_archive=False)
    return cfg


def test_sync_project_app_to_file(win, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    (tmp_path / "b.md").write_text("two", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    # edit silo 0 in the app -> push -> the FILE changes
    _edit_silo(win, 0, "one edited")
    win._push_sync_files()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one edited"
    # and the OTHER silo's file is untouched
    assert (tmp_path / "b.md").read_text(encoding="utf-8") == "two"


def test_sync_project_file_to_app(win, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    # external edit -> apply -> the SILO changes
    (tmp_path / "a.txt").write_text("one external", encoding="utf-8")
    win._sync_last_applied.pop(
        os.path.join(str(tmp_path), "a.txt"), None)
    win._apply_external_sync()
    assert win.data["temp_presets"][0] == "one external"


def test_sync_project_does_not_clobber_unsaved_typing(win, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    # the user is typing: editor is ahead of the last-applied baseline
    win.data["temp_presets"][0] = "one"
    win.text_area.setPlainText("one but newer")
    win._sync_last_applied[os.path.join(str(tmp_path), "a.txt")] = "one"
    (tmp_path / "a.txt").write_text("external edit", encoding="utf-8")
    win._apply_external_sync()
    # the app side wins while it is being typed
    assert win.data["temp_presets"][0] == "one"
    assert win.text_area.toPlainText() == "one but newer"


def test_sync_project_new_file_becomes_a_silo(win, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    n_before = len(win.data["temp_presets"])
    (tmp_path / "c.txt").write_text("three", encoding="utf-8")
    win._apply_external_sync()
    presets = win.data["temp_presets"]
    assert any("three" == (p or "").strip() for p in presets)
    # bound: the map grew by one entry for c.txt
    rels = list((win.data["project_sync_map"] or {}).values())
    assert "c.txt" in rels
    assert len(presets) >= n_before


def test_unlink_project_keeps_silos_and_stops_mapping(win, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        "fastprompter.main.QMessageBox.question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    win._unlink_project_sync()
    assert win.data["temp_presets"][0] == "one"
    assert not (win.data.get("project_sync_map") or {})
    # app edits no longer reach the file
    _edit_silo(win, 0, "after unlink")
    win._push_sync_files()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one"


# ------------------------------------------------------------- per-silo link


def test_silo_link_and_unlink(win, tmp_path, monkeypatch):
    linked = tmp_path / "linked.txt"
    linked.write_text("file content", encoding="utf-8")
    _set_silo(win, "silo content")
    # the real call opens a modal file dialog — hand it the answer
    monkeypatch.setattr(
        "fastprompter.main.QFileDialog.getOpenFileName",
        lambda *a, **k: (os.path.abspath(str(linked)), ""))
    win._link_silo_to_file(0)
    # linking loads the file into the silo (the file is the source)
    assert win.data["temp_presets"][0] == "file content"
    assert win._link_file_for_slot(0) == os.path.abspath(str(linked))
    # app edit -> file
    _edit_silo(win, 0, "edited in app")
    win._push_sync_files()
    assert linked.read_text(encoding="utf-8") == "edited in app"
    # external edit -> silo
    linked.write_text("edited outside", encoding="utf-8")
    win._sync_last_applied.pop(os.path.abspath(str(linked)), None)
    win._apply_external_sync()
    assert win.data["temp_presets"][0] == "edited outside"
    # unlink: silo keeps its text, file untouched afterwards
    win._unlink_silo_file(0)
    assert win.data["temp_presets"][0] == "edited outside"
    win.data["temp_presets"][0] = "post unlink"
    win._push_sync_files()
    assert linked.read_text(encoding="utf-8") == "edited outside"


# ------------------------------------------------------------- passed events


def _seed_missed(win, minutes_ago=30):
    t = Timer(name="rent", kind="calendar",
              target=datetime.datetime.now()
              - datetime.timedelta(minutes=minutes_ago))
    t.fired = True  # a one-shot that already fired (as _notify_timer leaves it)
    win.timers.append(t)
    win._missed_timer_ids.add(t.id)
    return t


def test_passed_event_turns_date_label_red(win):
    win.data["passed_alert_enabled"] = "True"
    t = _seed_missed(win)
    win._apply_date_alert_style()
    assert "color:" in win.lbl_date.styleSheet()
    assert win.lbl_date.styleSheet().lower().find("#e05555") != -1
    # acknowledge -> back to normal
    win._ack_missed(t)
    assert "#e05555" not in win.lbl_date.styleSheet().lower()


def test_passed_event_uses_user_colour(win):
    win.data["passed_alert_enabled"] = "True"
    win.data["passed_event_color"] = "#ff00ff"
    _seed_missed(win)
    win._apply_date_alert_style()
    assert "#ff00ff" in win.lbl_date.styleSheet().lower()
    win._clear_missed_alert()
    assert "color:" not in win.lbl_date.styleSheet()


def test_snooze_clears_the_missed_alert(win):
    win.data["passed_alert_enabled"] = "True"
    t = _seed_missed(win)
    assert win._missed_attention()
    win._snooze_timer(t, 10)
    assert not win._missed_attention()
