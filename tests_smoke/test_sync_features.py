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
    # PERF-005 moved typo scan to worker thread; test drives sync path directly
    from fastprompter.core import typecheck as tc
    dictionary = win._typo_dictionary()
    text = win.text_area.toPlainText()
    spans = [(s, e) for _, s, e in tc.find_unknown(text, dictionary)]
    win._typo_apply_spans(spans)
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
    from fastprompter.core import typecheck as tc
    dictionary = win._typo_dictionary()
    text = win.text_area.toPlainText()
    spans = [(s, e) for _, s, e in tc.find_unknown(text, dictionary)]
    win._typo_apply_spans(spans)
    assert win.text_area._typo_spans
    win._add_typo_word("fastprompterx")
    # _add_typo_word triggers a re-check; apply sync result for test determinism
    text2 = win.text_area.toPlainText()
    spans2 = [(s, e) for _, s, e in tc.find_unknown(text2, win._typo_dictionary())]
    win._typo_apply_spans(spans2)
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
        text, eol, _bom = ps.read_text_file(path)
        while len(presets) <= slot:
            presets.append("")
        presets[slot] = text
        mapping[str(slot)] = rel
        key = win._sync_baseline_key(slot, path)
        win._sync_eol_cache[key] = eol
        win._sync_last_applied[key] = win._sync_side_digest(text)
    win._start_project_watcher()
    # load silo 0 into the editor so the ACTIVE slot reflects the converted
    # content (the editor is the live source for app->file pushes)
    win._switch_to_slot(0, initial=True, is_archive=False)
    return cfg


def test_sync_project_app_to_file(win, tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\r\n")
    (tmp_path / "b.md").write_text("two", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    # edit silo 0 in the app -> push -> the FILE changes
    _edit_silo(win, 0, "one edited\n")
    win._push_sync_files(); win._push_wait_idle()
    key = win._sync_baseline_key(0, str(tmp_path / "a.txt"))
    assert (tmp_path / "a.txt").read_bytes() == b"one edited\r\n", (
        repr(win._sync_eol_cache.get(key)), repr(key),
    )
    # and the OTHER silo's file is untouched
    assert (tmp_path / "b.md").read_text(encoding="utf-8") == "two"


def test_sync_project_file_to_app(win, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    # external edit -> apply -> the SILO changes. The session baseline
    # (what we last wrote) stays in place: a normal external edit is only a
    # conflict when there is NO baseline (e.g. after an app restart).
    (tmp_path / "a.txt").write_text("one external", encoding="utf-8")
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
    win._push_sync_files(); win._push_wait_idle()
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
    # an external edit must work immediately, before the app has made its
    # first push (the initial baseline is already canonical).
    linked.write_text("external before push", encoding="utf-8")
    win._apply_external_sync()
    assert win.data["temp_presets"][0] == "external before push"
    # app edit -> file
    _edit_silo(win, 0, "edited in app")
    win._push_sync_files(); win._push_wait_idle()
    assert linked.read_text(encoding="utf-8") == "edited in app"
    # external edit -> silo (baseline stays: not a restart conflict)
    linked.write_text("edited outside", encoding="utf-8")
    win._apply_external_sync()
    assert win.data["temp_presets"][0] == "edited outside"
    # unlink: silo keeps its text, file untouched afterwards
    win._unlink_silo_file(0)
    assert win.data["temp_presets"][0] == "edited outside"
    win.data["temp_presets"][0] = "post unlink"
    win._push_sync_files(); win._push_wait_idle()
    assert linked.read_text(encoding="utf-8") == "edited outside"


# ------------------------------------------------------------- sync conflicts


def _seed_conflict(win, tmp_path, silo_text="app edited", file_text="file edited"):
    """Convert a one-file project, then simulate an app restart (no session
    baselines) with BOTH sides edited differently."""
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    win._sync_last_applied.clear()  # fresh session: no baselines
    _edit_silo(win, 0, silo_text)
    (tmp_path / "a.txt").write_text(file_text, encoding="utf-8")
    return tmp_path / "a.txt"


def test_conflict_file_wins_on_external_apply(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    calls = []
    monkeypatch.setattr(
        win, "_sync_ask_conflict",
        lambda path, slot, ft, st: calls.append((path, slot, ft, st)) or "file")
    win._apply_external_sync()
    # the file version wins: the silo takes the file text, file untouched
    assert win.data["temp_presets"][0] == "file edited"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "file edited"
    assert calls and calls[0][2] == "file edited" and calls[0][3] == "app edited"


def test_conflict_app_wins_on_external_apply(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda path, slot, ft, st: "app")
    win._apply_external_sync()
    # the app version wins: the FILE takes the silo text
    assert win.data["temp_presets"][0] == "app edited"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "app edited"


def test_conflict_skip_leaves_both_untouched(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda path, slot, ft, st: None)
    win._apply_external_sync()
    assert win.data["temp_presets"][0] == "app edited"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "file edited"


def test_conflict_app_wins_on_push(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda path, slot, ft, st: "app")
    win._push_sync_files(); win._push_wait_idle()
    # the app version wins: the FILE takes the silo text
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "app edited"
    assert win.data["temp_presets"][0] == "app edited"


def test_conflict_file_wins_on_push(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda path, slot, ft, st: "file")
    win._push_sync_files(); win._push_wait_idle()
    # the file version wins: the silo takes the file text, file untouched
    assert win.data["temp_presets"][0] == "file edited"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "file edited"


def test_no_conflict_when_sides_are_equal(win, tmp_path, monkeypatch):
    # fresh session, but neither side changed: no prompt, no clobber
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    _convert_project(win, str(tmp_path))
    win._sync_last_applied.clear()
    called = []
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda *a, **k: called.append(1) or "app")
    win._apply_external_sync()
    assert not called
    assert win.data["temp_presets"][0] == "one"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one"


def test_skip_is_remembered_for_the_same_conflict(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    calls = []
    monkeypatch.setattr(
        win, "_sync_ask_conflict",
        lambda path, slot, ft, st: calls.append(1) or None)
    win._apply_external_sync()
    assert len(calls) == 1
    # second pass with the SAME sides: the skip is remembered, no re-prompt
    win._apply_external_sync()
    assert len(calls) == 1
    assert win.data["temp_presets"][0] == "app edited"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "file edited"


def test_skip_reprompts_after_a_side_changes(win, tmp_path, monkeypatch):
    _seed_conflict(win, tmp_path)
    calls = []
    monkeypatch.setattr(win, "_sync_ask_conflict",
                        lambda path, slot, ft, st: calls.append(1) or None)
    win._apply_external_sync()
    assert len(calls) == 1
    # the user edits the silo again -> the conflict tuple changed -> re-prompt
    _edit_silo(win, 0, "app edited v2")
    win._apply_external_sync()
    assert len(calls) == 2


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


def test_silent_calendar_event_still_marks_passed_attention(win, monkeypatch):
    win.data["passed_alert_enabled"] = "True"
    t = _seed_missed(win, minutes_ago=1)
    t.show_notification = False
    win._missed_timer_ids.clear()
    monkeypatch.setattr(win, "_play_timer_sound", lambda *args: None)
    win._notify_timer(t, fired_at=datetime.datetime.now())
    assert t.id in win._missed_timer_ids
    assert win._missed_attention()
    win._ack_missed(t)
