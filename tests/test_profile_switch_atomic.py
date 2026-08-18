"""P0-1 regression: profile transition is atomic.

A failed final A save must REFUSE the switch (returns False, A untouched).
A corrupt/unopenable B must restore A entirely before re-raising, so State
is never stranded bound to a half-initialised B while Main still holds A's
data.
"""

import os

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import FastPrompterState


def _state(profile_id, tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_mod, "get_db_path",
        lambda pid=1: str(tmp_path / f"p{pid}.db"), raising=False)
    s = FastPrompterState(profile_id=profile_id)
    s._last_backup_time_by_profile.clear()
    return s


def test_switch_refuses_when_a_save_fails(tmp_path, monkeypatch):
    s = _state(1, tmp_path, monkeypatch)
    s.data["temp_presets_all"]["Code"][0] = "A-data"
    s.mark_dirty()
    # A's connection is closed-but-present: save_data_to_db will attempt the
    # write, hit the dead connection, and return False (dirty preserved).
    s.conn.close()
    result = s.switch_profile(2, save_current=True)
    assert result is False
    # A is entirely intact: id, path, data, and the (still-dirty) flag.
    assert s.profile_id == 1
    assert s.db_path == str(tmp_path / "p1.db")
    assert s.data["temp_presets_all"]["Code"][0] == "A-data"
    assert s._db_dirty is True
    assert s.conn is not None


def test_switch_restores_a_when_b_load_fails(tmp_path, monkeypatch):
    db_a = str(tmp_path / "p1.db")
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda pid=1: db_a, raising=False)
    s = FastPrompterState(profile_id=1)
    s._last_backup_time_by_profile.clear()
    s.data["temp_presets_all"]["Code"][3] = "A-kept"
    assert s.save_data_to_db("A-kept", force=True) is True

    # B points at a directory: init_db cannot open it.
    bad = str(tmp_path / "b_dir")
    os.makedirs(bad)
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda pid=1: db_a if pid == 1 else bad, raising=False)

    with pytest.raises(Exception):
        s.switch_profile(2, save_current=False)

    # A fully restored; no ownership leaked to the dead B.
    assert s.profile_id == 1
    assert s.db_path == db_a
    assert s.data["temp_presets_all"]["Code"][3] == "A-kept"
    assert s.conn is not None
    # B's database was never created (the directory is untouched, not a file).
    assert not os.path.isfile(str(tmp_path / "p2.db"))


def test_switch_commit_only_after_b_loads(tmp_path, monkeypatch):
    s = _state(1, tmp_path, monkeypatch)
    s.data["temp_presets_all"]["Code"][0] = "A0"
    assert s.save_data_to_db("A0", force=True) is True
    # A is clean/closed-committed; switching to a fresh B must succeed and
    # leave A's connection retired and B's data active.
    assert s.switch_profile(2, save_current=False) is True
    assert s.profile_id == 2
    # B starts empty (its own fresh DB).
    assert s.data["temp_presets_all"]["Code"][0] == ""
