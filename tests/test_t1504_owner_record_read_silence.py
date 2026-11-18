"""T-1504: a corrupt/unreadable owner record must not pass silently on read.

``_read_owner_record`` used two bare ``except Exception: pass`` branches (one
for a json.loads failure, one for a file read failure) and returned None, so a
corrupt or unreadable owner record was indistinguishable from no owner at all.
The write side logs the same class of failure (T-1474); the read side must
match.
"""

from __future__ import annotations

import json
import logging

from fastprompter.core.instance_lock import (
    _read_owner_record,
)

_LOGGER_NAME = "fastprompter.core.instance_lock"


class TestOwnerRecordReadFailure:
    def test_corrupt_record_is_logged_not_silent(self, tmp_path, monkeypatch,
                                                 caplog):
        record_path = tmp_path / "owner_v15.json"
        record_path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            rec = _read_owner_record()

        assert rec is None
        assert any("could not parse owner record" in r.message
                   for r in caplog.records), "corrupt record was not logged"

    def test_unreadable_record_is_logged_not_silent(self, tmp_path, monkeypatch,
                                                    caplog):
        record_path = tmp_path / "owner_v15.json"
        record_path.write_text('{"pid": 7}', encoding="utf-8")
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))

        real_open = open

        def refusing_open(*args, **kwargs):
            if str(record_path) in str(args[0] if args else kwargs.get("file", "")):
                raise OSError("permission denied")
            return real_open(*args, **kwargs)

        monkeypatch.setattr("builtins.open", refusing_open)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            rec = _read_owner_record()

        assert rec is None
        assert any("could not read owner record" in r.message
                   for r in caplog.records), "unreadable record was not logged"

    def test_healthy_record_stays_silent(self, tmp_path, monkeypatch, caplog):
        record_path = tmp_path / "owner_v15.json"
        record_path.write_text(json.dumps({"pid": 99, "create_time": 0,
                                          "exe": "x"}), encoding="utf-8")
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE",
            str(record_path))
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            rec = _read_owner_record()

        assert rec is not None and rec.get("pid") == 99
        assert [r for r in caplog.records
                if "could not" in r.message] == [], (
            "a healthy read must not warn")
