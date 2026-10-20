"""Tests for T-1468 Stage 4: Real settings persistence and restart verification.

Proves:
1) table_default_layout setting is saved into the live SQLite database file on disk.
2) A fresh state instance pointing at that database file loads the custom template on startup.
3) Switching profiles loads the new profile's template, or falls back to factory if omitted.
4) A legacy database without table_default_layout in settings loads cleanly with factory defaults.
5) Database backup and restore preserves table_default_layout.
6) When silo_remember_scroll is "False", opening a table with a saved layout positions at top-left.
"""

import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from fastprompter.core import state as state_mod
from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.state import FastPrompterState, _backup_atomically, restore_database
from fastprompter.ui import silo_table as st
from fastprompter.ui.table_grid import TableGridWidget

_APP = QApplication.instance() or QApplication([])


def _make_template(cols=5, rows=6, width=175, height=40, word_wrap=True):
    return {
        "version": 1,
        "columns": cols,
        "visible_rows": rows,
        "col_widths": [width] * cols,
        "row_heights": [height] * rows,
        "manual_cols": list(range(cols)),
        "manual_rows": list(range(rows)),
        "word_wrap": word_wrap,
    }


def test_table_default_layout_persists_to_disk_and_reloads_on_restart(tmp_path, monkeypatch):
    """1 & 2: table_default_layout is committed to SQLite on disk and reloaded by fresh state."""
    db_file = str(tmp_path / "fastprompter_live.db")
    monkeypatch.setattr(state_mod, "get_db_path", lambda pid=1: db_file, raising=False)

    tpl = _make_template(cols=4, rows=5, width=180, word_wrap=True)

    # First session: save custom template
    state1 = FastPrompterState(profile_id=1)
    state1.data["table_default_layout"] = json.dumps(tpl)
    state1.mark_dirty("settings")
    saved = state1.save_data_to_db("", force=True)
    assert saved is True
    state1.conn.close()

    # Verify directly inside SQLite file on disk
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'table_default_layout'")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    disk_data = json.loads(row[0])
    assert disk_data["columns"] == 4
    assert disk_data["visible_rows"] == 5
    assert disk_data["col_widths"] == [180, 180, 180, 180]

    # Second session: fresh instance simulation of application restart
    state2 = FastPrompterState(profile_id=1)
    reloaded = state2.data.get("table_default_layout")
    state2.conn.close()

    assert isinstance(reloaded, dict) or isinstance(reloaded, str)
    normalized = st.parse_default_layout(reloaded)
    assert normalized is not None
    assert normalized["columns"] == 4
    assert normalized["visible_rows"] == 5
    assert normalized["cols"] == [180, 180, 180, 180]
    assert normalized["word_wrap"] is True


def test_profile_switching_loads_profile_template_or_falls_back(tmp_path, monkeypatch):
    """3: Profile switching transitions to new profile's template, or factory default if unset."""
    p1_file = str(tmp_path / "p1.db")
    p2_file = str(tmp_path / "p2.db")

    def _mock_path(pid=1):
        return p2_file if pid == 2 else p1_file

    monkeypatch.setattr(state_mod, "get_db_path", _mock_path, raising=False)

    # Initialize Profile 1 with custom template
    tpl1 = _make_template(cols=6, rows=7, width=120)
    s = FastPrompterState(profile_id=1)
    s.data["table_default_layout"] = json.dumps(tpl1)
    s.mark_dirty("settings")
    s.save_data_to_db("", force=True)

    # Switch to Profile 2 (fresh profile with no saved template)
    switched = s.switch_profile(2, save_current=True)
    assert switched is True
    assert s.profile_id == 2

    p2_tpl = s.data.get("table_default_layout")
    # Must fall back to factory default
    assert p2_tpl == DEFAULT_PROFILE.get("table_default_layout")

    # Set custom template in Profile 2
    tpl2 = _make_template(cols=2, rows=3, width=250)
    s.data["table_default_layout"] = json.dumps(tpl2)
    s.mark_dirty("settings")
    s.save_data_to_db("", force=True)

    # Switch back to Profile 1
    switched_back = s.switch_profile(1, save_current=True)
    assert switched_back is True
    assert s.profile_id == 1

    p1_reloaded = st.parse_default_layout(s.data.get("table_default_layout"))
    assert p1_reloaded["columns"] == 6
    assert p1_reloaded["cols"] == [120] * 6
    s.conn.close()


def test_legacy_profile_without_table_default_layout_loads_cleanly(tmp_path, monkeypatch):
    """4: A legacy database without table_default_layout loads cleanly with factory defaults."""
    db_file = str(tmp_path / "legacy.db")
    monkeypatch.setattr(state_mod, "get_db_path", lambda pid=1: db_file, raising=False)

    # Initialize standard database
    s = FastPrompterState(profile_id=1)
    s.save_data_to_db("", force=True)

    # Manually delete table_default_layout from settings table to simulate pre-T-1466 legacy DB
    s.conn.execute("DELETE FROM settings WHERE key = 'table_default_layout'")
    s.conn.commit()
    s.conn.close()

    # Load legacy DB in a fresh state
    fresh = FastPrompterState(profile_id=1)
    val = fresh.data.get("table_default_layout")
    fresh.conn.close()

    # Missing key defaults cleanly to factory profile value
    assert val == DEFAULT_PROFILE.get("table_default_layout")
    assert st.template_shape(val) == (st.FACTORY_COLUMNS, st.FACTORY_VISIBLE_ROWS)


def test_backup_and_restore_preserves_table_default_layout(tmp_path, monkeypatch):
    """5: Exporting/importing database backup preserves table_default_layout."""
    src_db = str(tmp_path / "source.db")
    backup_file = str(tmp_path / "backup.db")
    restored_db = str(tmp_path / "restored.db")

    monkeypatch.setattr(state_mod, "get_db_path", lambda pid=1: src_db, raising=False)

    tpl = _make_template(cols=8, rows=10, width=210, word_wrap=True)

    # Save template to source database
    s = FastPrompterState(profile_id=1)
    s.data["table_default_layout"] = json.dumps(tpl)
    s.mark_dirty("settings")
    s.save_data_to_db("", force=True)

    # Atomically create backup snapshot
    _backup_atomically(s.conn, backup_file)
    s.conn.close()

    # Target live destination database must exist on disk before restore
    monkeypatch.setattr(state_mod, "get_db_path", lambda pid=1: restored_db, raising=False)
    target = FastPrompterState(profile_id=1)
    target.save_data_to_db("", force=True)
    target.conn.close()

    # Restore backup file into target database
    restore_database(backup_file, restored_db)

    # Point state to restored database and verify template
    monkeypatch.setattr(state_mod, "get_db_path", lambda pid=1: restored_db, raising=False)
    restored_state = FastPrompterState(profile_id=1)
    restored_tpl = st.parse_default_layout(restored_state.data.get("table_default_layout"))
    restored_state.conn.close()

    assert restored_tpl is not None
    assert restored_tpl["columns"] == 8
    assert restored_tpl["visible_rows"] == 10
    assert restored_tpl["cols"] == [210] * 8
    assert restored_tpl["word_wrap"] is True


def test_scroll_position_toggle_controls_restore(monkeypatch):
    """6: When Remember Silo Scroll Position is OFF, opening table positions at top-left."""
    grid = TableGridWidget()
    # Large 10x10 table with large cells so scrollbars have travel
    md_lines = ["| " + " | ".join(f"C{c}" for c in range(10)) + " |"]
    md_lines.append("| " + " | ".join(["---"] * 10) + " |")
    for r in range(15):
        md_lines.append("| " + " | ".join(f"v_{r}_{c}" for c in range(10)) + " |")
    grid.load_markdown("\n".join(md_lines))

    # Resize widget so scrollbars have positive maximum range
    grid.resize(300, 200)
    grid.show()
    _APP = QApplication.instance()
    _APP.processEvents()

    # Layout with saved scroll positions
    layout_with_scroll = {
        "cols": [300] * 10,
        "rows": [90] * 16,
        "h_scroll": 250,
        "v_scroll": 180,
    }

    # Case A: restore_scroll=False (Remember Scroll OFF)
    applied = grid.apply_presentation(layout_with_scroll, restore_scroll=False)
    assert applied is True
    assert grid.view.horizontalScrollBar().value() == 0
    assert grid.view.verticalScrollBar().value() == 0

    # Case B: restore_scroll=True (Remember Scroll ON)
    applied = grid.apply_presentation(layout_with_scroll, restore_scroll=True)
    assert applied is True
    assert grid.view.horizontalScrollBar().value() > 0
    assert grid.view.verticalScrollBar().value() > 0
