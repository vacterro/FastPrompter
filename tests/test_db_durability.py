"""T-1232: the database durability guarantee is the one the code claims.

T-1227 built a crash-safety story - durable undo-before publication, recovery
predecessors committed in the same transaction, structural operations that only
report success once SQLite has the data - on top of a connection configured
with `PRAGMA synchronous=NORMAL`. In WAL mode that setting does not fsync the
write-ahead log at commit: the bytes reach the OS page cache, so a committed
silo edit survives the *process* dying and can still be lost to a power cut, a
kernel panic, or a volume that goes away.

Measured cost of closing that gap on this project's own database (a 20 KB silo
body plus a settings row, 40 commits): median 0.12ms -> 0.47ms, p95 0.22ms ->
1.03ms. A third of a millisecond on a path that already spends tens of
milliseconds in Python.

So the setting is FULL, and these tests exist so a later performance pass
cannot quietly take it back: a durability guarantee nobody asserts is a
durability guarantee that decays into a comment.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from fastprompter.core.state import _SQLITE_SYNCHRONOUS, connect_app_db

# sqlite3 reports the pragma as an integer: 0 OFF, 1 NORMAL, 2 FULL, 3 EXTRA.
_SYNCHRONOUS_LEVELS = {"OFF": 0, "NORMAL": 1, "FULL": 2, "EXTRA": 3}


def _open(tmp_path, name="d.db"):
    path = str(tmp_path / name)
    sqlite3.connect(path).close()
    return connect_app_db(path)


def test_the_shipped_setting_is_durable(tmp_path):
    """NORMAL is the setting this ticket exists to get rid of."""
    assert _SQLITE_SYNCHRONOUS in ("FULL", "EXTRA"), (
        "synchronous=NORMAL does not fsync the WAL at commit; T-1227's "
        "durability claims are false under it")


def test_connect_app_db_applies_the_durability_pragma(tmp_path):
    conn = _open(tmp_path)
    try:
        level = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert level == _SYNCHRONOUS_LEVELS[_SQLITE_SYNCHRONOUS]
    finally:
        conn.close()


def test_connect_app_db_applies_wal_and_busy_timeout(tmp_path):
    conn = _open(tmp_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0
    finally:
        conn.close()


def test_every_live_connect_site_goes_through_the_helper():
    """The pragma block used to be copy-pasted, which is how one copy drifts.

    Two sites carried it: the loader in state.py and the post-restore reopen
    in main.py. Both now call `connect_app_db`. A third hand-rolled
    `sqlite3.connect` on the LIVE database would silently opt out of the
    guarantee the other two advertise, so it is a test failure, not a style
    nit.
    """
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"
    offenders = []
    for path in (src / "core" / "state.py", src / "main.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"PRAGMA synchronous=(\w+)", text):
            # The only literal allowed is the one inside the helper, which
            # interpolates the constant rather than naming a level.
            offenders.append(f"{path.name}: hardcoded {match.group(0)!r}")
    assert not offenders, (
        "durability pragma written by hand instead of via connect_app_db:\n"
        + "\n".join(offenders))


def test_a_committed_row_is_readable_from_a_fresh_connection(tmp_path):
    """The end the user cares about: commit means the next open sees it."""
    conn = _open(tmp_path)
    try:
        conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
        with conn:
            conn.execute("INSERT INTO t VALUES ('silo', 'precious')")
    finally:
        conn.close()

    again = connect_app_db(str(tmp_path / "d.db"))
    try:
        assert again.execute("SELECT v FROM t WHERE k='silo'").fetchone()[0] \
            == "precious"
    finally:
        again.close()


def test_wal_sidecars_are_part_of_the_database(tmp_path):
    """A backup that copies only the .db file can be an OLDER database.

    In WAL mode the newest commits live in `<db>-wal` until a checkpoint
    folds them back. Copying the main file alone is therefore not a copy of
    the database, and a restore from such a copy silently loses the most
    recent silo edits - which is exactly the class of loss this wave is
    about. This test documents the fact so a copy path can be audited
    against it.
    """
    import shutil

    conn = _open(tmp_path)
    try:
        conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
        with conn:
            conn.execute("INSERT INTO t VALUES ('silo', 'newest')")

        naive = str(tmp_path / "naive_copy.db")
        shutil.copy(str(tmp_path / "d.db"), naive)  # main file only
    finally:
        conn.close()

    probe = sqlite3.connect(naive)
    try:
        row = probe.execute(
            "SELECT name FROM sqlite_master WHERE name='t'").fetchone()
        # Either the table is missing entirely or it is there without the
        # row - both mean the naive copy is not the live database.
        if row is not None:
            got = probe.execute("SELECT v FROM t WHERE k='silo'").fetchone()
            assert got is None, (
                "this assertion is a canary: if a main-file-only copy ever "
                "does carry the newest commit, WAL is no longer in play and "
                "the backup-path audit needs revisiting")
    finally:
        probe.close()


@pytest.mark.parametrize("level", ["OFF", "NORMAL"])
def test_the_weak_levels_are_named_so_nobody_reintroduces_them_by_accident(level):
    assert _SQLITE_SYNCHRONOUS != level
