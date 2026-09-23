"""W2-003 (audit/12, SRC-041 R006): restore quarantine is invocation-owned.

``restore_database`` used to pre-delete deterministic
``destination + ".wal.quarantine"`` / ``".shm.quarantine"`` paths before
establishing ownership, so a pre-existing file (user data, an older
interrupted restore's scratch) was silently destroyed even when no live
WAL/SHM existed. Quarantine scratch is now unique per invocation through the
shared ownership primitive, every created pair is tracked, and nothing is
deleted merely because its name matches an internal suffix.
"""

import os
import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import (
    CURRENT_SCHEMA_VERSION,
    FastPrompterState,
    FatalRestoreError,
    RestoreError,
    restore_database,
    validate_database,
)

SENTINEL = b"KEEP-ME"


def _make_db(path, marker):
    """A real FastPrompter database containing `marker`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state_mod.get_db_path = lambda profile_id=1: path
    s = FastPrompterState(profile_id=1)
    s.data["temp_presets_all"]["Code"][0] = marker
    s.data["categories"]["Code"][0] = {"name": "snip", "text": marker}
    s.mark_dirty()
    s.save_data_to_db(marker, force=True, sync=True)
    s.conn.close()
    return s


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _rows(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT content FROM temp_presets_v2 "
            "WHERE category='Code' AND slot=0").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _write_sentinels(live):
    """Pre-existing files at the OLD deterministic quarantine names."""
    wal = live + ".wal.quarantine"
    shm = live + ".shm.quarantine"
    for path in (wal, shm):
        with open(path, "wb") as fh:
            fh.write(SENTINEL)
    return wal, shm


def _quarantine_scratch(live, sidecar=None):
    directory = os.path.dirname(live) or "."
    prefix = os.path.basename(live)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    out = sorted(n for n in entries
                 if n.startswith(prefix) and ".quarantine-" in n)
    if sidecar is not None:
        out = [n for n in out if n.startswith(prefix + sidecar)]
    return out


class TestSentinelSurvival:
    def test_preexisting_quarantine_sentinels_survive_success(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        assert restore_database(backup, live) == CURRENT_SCHEMA_VERSION

        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL
        assert _quarantine_scratch(live) == []

    @pytest.mark.parametrize("sidecar", ["-wal", "-shm"])
    def test_real_sidecar_uses_unique_scratch_and_sentinels_survive(
            self, tmp_path, monkeypatch, sidecar):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        with open(live + sidecar, "wb") as fh:
            fh.write(b"frames")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        renames = []
        real_replace = state_mod.os.replace

        def spy_replace(src, dst):
            renames.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", spy_replace)
        assert restore_database(backup, live) == CURRENT_SCHEMA_VERSION

        moves = [dst for src, dst in renames if src == live + sidecar]
        assert len(moves) == 1
        # The live sidecar was NEVER renamed onto a predictable name.
        assert moves[0] != live + ".wal.quarantine"
        assert moves[0] != live + ".shm.quarantine"
        assert ".quarantine-" in os.path.basename(moves[0])
        # ... and it was cleaned up after the successful publication.
        assert _quarantine_scratch(live) == []
        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL

    def test_both_real_sidecars_with_sentinels_survive(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        for sidecar in ("-wal", "-shm"):
            with open(live + sidecar, "wb") as fh:
                fh.write(b"frames")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        assert restore_database(backup, live) == CURRENT_SCHEMA_VERSION
        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL
        assert _quarantine_scratch(live) == []
        assert _rows(live) == "restored"

    def test_main_swap_failure_restores_sidecars_without_touching_sentinels(
            self, tmp_path, monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _read(live)
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        with open(live + "-wal", "wb") as fh:
            fh.write(b"frames")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        real_replace = state_mod.os.replace

        def fake_replace(src, dst):
            if dst == live and ".restore-" in os.path.basename(src):
                raise OSError("swap boom")
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", fake_replace)
        with pytest.raises(RestoreError):
            restore_database(backup, live)

        assert _read(live) == before
        assert os.path.isfile(live + "-wal")
        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL
        assert _quarantine_scratch(live) == []

    def test_fatal_repair_preserves_unrelated_sentinels(self, tmp_path,
                                                        monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        with open(live + "-wal", "wb") as fh:
            fh.write(b"frames")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        real_replace = state_mod.os.replace

        def fake_replace(src, dst):
            if dst == live and ".restore-" in os.path.basename(src):
                raise OSError("swap boom")
            if ".quarantine-" in os.path.basename(src):
                raise OSError("rollback boom")
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", fake_replace)
        with pytest.raises(FatalRestoreError) as einfo:
            restore_database(backup, live)

        assert einfo.value.repaired is True
        assert validate_database(live)[0] == CURRENT_SCHEMA_VERSION
        assert _rows(live) == "live data"
        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL

    def test_owned_cleanup_failure_never_deletes_unrelated_paths(
            self, tmp_path, monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")
        with open(live + "-wal", "wb") as fh:
            fh.write(b"frames")
        wal_sentinel, shm_sentinel = _write_sentinels(live)

        real_remove = os.remove

        def failing_remove(path):
            if ".quarantine-" in os.path.basename(path):
                raise OSError("cleanup boom (best-effort, swallowed)")
            return real_remove(path)

        monkeypatch.setattr(state_mod.os, "remove", failing_remove)
        assert restore_database(backup, live) == CURRENT_SCHEMA_VERSION

        # Success is not vetoed by best-effort scratch cleanup, the OWNED
        # scratch is the only leftover (invocation-unique names, possibly both
        # sidecars — SQLite may materialize an SHM while the safety copy is
        # taken), and neither sentinel was touched.
        leftovers = _quarantine_scratch(live)
        assert leftovers
        assert all(n.startswith(os.path.basename(live) + "-") for n in leftovers)
        assert _read(wal_sentinel) == SENTINEL
        assert _read(shm_sentinel) == SENTINEL

    def test_two_invocations_choose_distinct_scratch_paths(
            self, tmp_path, monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored")

        chosen = []
        real_replace = state_mod.os.replace

        def spy_replace(src, dst):
            chosen.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", spy_replace)
        for _round in range(2):
            with open(live + "-wal", "wb") as fh:
                fh.write(b"frames")
            assert restore_database(backup, live) == CURRENT_SCHEMA_VERSION

        quarantines = [dst for src, dst in chosen if src == live + "-wal"]
        assert len(quarantines) == 2
        assert quarantines[0] != quarantines[1]
        assert all(".quarantine-" in os.path.basename(q) for q in quarantines)
