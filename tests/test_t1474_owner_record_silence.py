"""T-1474: a failed owner-record write must not pass silently.

``_write_owner_record`` persisted the writer-ownership identity behind a bare
``except Exception: pass``.  A disk-full, permission-denied or still-held-file
condition therefore left the on-disk record stale or absent, with no log,
no re-raise and no signal -- while ``_read_owner_pid`` and
``_verify_owner_identity`` both read that exact record to prove the live
process is the recorded mutex owner.  The safety check degrades to a guess
and nothing anywhere says so.

The write is the last observable moment for that failure: once the record is
stale, no later call can recover the fact that it was never written.
"""

from __future__ import annotations

import logging

from fastprompter.core.instance_lock import (
    _read_owner_pid,
    _write_owner_pid,
    _write_owner_record,
)

_LOGGER_NAME = "fastprompter.core.instance_lock"


class TestOwnerRecordWriteFailure:
    def test_a_failed_write_is_logged_not_silent(self, tmp_path, monkeypatch,
                                                 caplog):
        """The refusal is visible in the log and names the record path."""
        record_path = tmp_path / "owner_v15.json"
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))

        real_open = open

        def refusing_open(*args, **kwargs):
            raise PermissionError("device or directory is locked")

        monkeypatch.setattr("builtins.open", refusing_open)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            _write_owner_record({"pid": 4242, "create_time": 1, "exe": "x"})

        # the record was not written, and the caller can see that it wasn't
        assert not record_path.exists()
        assert any("writer ownership identity" in r.message
                   for r in caplog.records), "write failure was not logged"
        assert any(str(record_path) in r.message
                   for r in caplog.records), "the record path was not named"
        # the swallow must stay a swallow: startup survives a full disk
        monkeypatch.setattr("builtins.open", real_open)

    def test_a_failed_write_through_the_public_owner_helper_is_logged(
            self, tmp_path, monkeypatch, caplog):
        """The path the running process actually takes is covered too.

        ``InstanceLock.acquire`` records ownership through ``_write_owner_pid``
        (instance_lock.py:338), not through ``_write_owner_record`` directly.
        """
        record_path = tmp_path / "owner_v15.json"
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))

        def refusing_open(*args, **kwargs):
            raise OSError("no space left on device")

        monkeypatch.setattr("builtins.open", refusing_open)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            _write_owner_pid(4242)

        assert not record_path.exists()
        # a stale or absent record reads back as "no owner", which is exactly
        # what _verify_owner_identity depends on -- so it must be reported
        assert _read_owner_pid() is None
        assert any("writer ownership identity" in r.message
                   for r in caplog.records), "write failure was not logged"

    def test_a_healthy_write_stays_silent(self, tmp_path, monkeypatch, caplog):
        """Negative control: a good write produces no warning of its own."""
        record_path = tmp_path / "owner_v15.json"
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            _write_owner_record({"pid": 99, "create_time": 0, "exe": "x"})

        assert _read_owner_pid() == 99
        assert [r for r in caplog.records
                if "writer ownership identity" in r.message] == [], (
            "a successful write must not warn")
        try:
            record_path.unlink()
        except OSError:
            pass
