"""Second-wave audit regressions that need no Qt window.

P0-1: a crafted database carrying a silo row at slot >= 100 must NEVER be
clamped onto slot 99 (which would silently merge two distinct silos). The
load must fail closed — raise DatabaseOverflowError and leave the on-disk
database untouched — so slot 99 and slot 100 are never coalesced.

P2: the window-flags branch that decides frameless vs normal must be a single
`if not normal:` block (the duplicated-branch regression).
"""

import os
import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import DatabaseOverflowError, FastPrompterState


def _make_state(tmp_path, profile_id, monkeypatch):
    db = os.path.join(str(tmp_path), f"p{profile_id}.db")
    # always resolve to the test's db, whatever args init_db passes
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda *a, **k: db, raising=False)
    st = FastPrompterState()
    st.init_db()  # create schema
    return st, db


def _insert_rows(db, table, rows):
    conn = sqlite3.connect(db)
    try:
        conn.executemany(
            f"INSERT INTO {table} (category, slot, content) VALUES (?, ?, ?)",
            rows)
        conn.commit()
    finally:
        conn.close()


def test_slot_99_and_100_never_merge_on_load(tmp_path, monkeypatch):
    """Crafted DB with slots 99 and 100 must raise, not coalesce."""
    st, db = _make_state(tmp_path, 1, monkeypatch)
    _insert_rows(db, "temp_presets_v2",
                 [("Code", 99, "LOW"), ("Code", 100, "HIGH")])
    # The database file must be left untouched (we never wrote past load).
    with pytest.raises(DatabaseOverflowError):
        st.init_db()


def test_slot_99_only_loads_clean(tmp_path, monkeypatch):
    """A DB whose highest slot is exactly 99 loads fine and keeps its content."""
    st, db = _make_state(tmp_path, 2, monkeypatch)
    _insert_rows(db, "temp_presets_v2", [("Code", 99, "LOW")])
    # must not raise
    st.init_db()
    assert st.data["temp_presets_all"]["Code"][99] == "LOW"


def test_archive_slot_99_and_100_never_merge_on_load(tmp_path, monkeypatch):
    st, db = _make_state(tmp_path, 3, monkeypatch)
    _insert_rows(db, "archive_temp_presets_v2",
                 [("Code", 99, "ALOW"), ("Code", 100, "AHIGH")])
    with pytest.raises(DatabaseOverflowError):
        st.init_db()


def test_negative_slot_fails_closed_temp(tmp_path, monkeypatch):
    """A crafted temp row at slot -1 must raise, never alias slot 0."""
    st, db = _make_state(tmp_path, 4, monkeypatch)
    _insert_rows(db, "temp_presets_v2", [("Code", -1, "NEG")])
    with pytest.raises(DatabaseOverflowError):
        st.init_db()


def test_negative_slot_fails_closed_archive(tmp_path, monkeypatch):
    """A crafted archive row at slot -1 must raise, never alias slot 0."""
    st, db = _make_state(tmp_path, 5, monkeypatch)
    _insert_rows(db, "archive_temp_presets_v2", [("Code", -1, "ANEG")])
    with pytest.raises(DatabaseOverflowError):
        st.init_db()


def test_window_flags_single_branch():
    """apply_window_flags must contain exactly ONE `if not normal:` decision."""
    import inspect

    from fastprompter.main import FastPrompter
    src = inspect.getsource(FastPrompter.apply_window_flags)
    decision_lines = [ln for ln in src.splitlines()
                      if ln.lstrip().startswith("if not normal:")]
    assert len(decision_lines) == 1, (
        f"expected exactly one `if not normal:` branch, found "
        f"{len(decision_lines)}: {decision_lines}")
