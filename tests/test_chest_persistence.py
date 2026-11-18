"""T-1460: persisted chest slots survive SQLite reload and a fresh panel."""

import json
import os
import sqlite3
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from fastprompter.core import state as state_mod
from fastprompter.core.state import FastPrompterState
from fastprompter.ui.file_container import FileContainerPanel, is_placeholder


@pytest.mark.parametrize("encoding", ["json", "legacy", "double_json"])
def test_persisted_slots_survive_database_and_panel_reload(
        qapp, tmp_path, monkeypatch, encoding):
    folder = tmp_path / "files"
    folder.mkdir()
    for name in ("a.txt", "b.txt"):
        (folder / name).write_text(name, encoding="utf-8")
    key = os.path.normcase(os.path.abspath(folder))
    slots = {"a.txt": 3, "b.txt": 9}
    mapping = {key: slots}
    raw = {
        "json": json.dumps(mapping),
        "legacy": str(mapping),
        "double_json": json.dumps(json.dumps(mapping)),
    }[encoding]
    db = str(tmp_path / "profile.db")
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: db)
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda *args, **kwargs: None)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES (?, ?)",
                     ("silo_chest_order", raw))

    state = FastPrompterState(profile_id=1)
    try:
        assert state.data["silo_chest_order"] == mapping
        state.mark_dirty("settings")
        assert state.save_data_to_db("", force=True)
    finally:
        state.conn.close()
    with sqlite3.connect(db) as conn:
        saved = conn.execute(
            "SELECT value FROM settings WHERE key = 'silo_chest_order'"
        ).fetchone()[0]
    assert json.loads(saved) == mapping

    reloaded = FastPrompterState(profile_id=1)
    main = QWidget()
    main.data = reloaded.data
    main.data["file_panel_view"] = "Chest"
    main._current_lang = "EN"
    panel = FileContainerPanel(main)
    try:
        panel.open_for(str(folder), "persisted chest")
        deadline = time.monotonic() + 5
        while getattr(panel, "_refresh_inflight_seq", None) is not None:
            assert time.monotonic() < deadline, "file listing did not finish"
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
        actual = {}
        for row in range(panel.file_list.count()):
            item = panel.file_list.item(row)
            if item is not None and not is_placeholder(item):
                actual[os.path.basename(item.data(Qt.ItemDataRole.UserRole))] = row
        assert actual == slots
    finally:
        panel.close()
        panel.deleteLater()
        main.deleteLater()
        reloaded.conn.close()
